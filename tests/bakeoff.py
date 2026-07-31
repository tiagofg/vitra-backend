"""Cenário de dados do bake-off, montado por teste.

Duas regras que a qualidade do VITRA exige e que valem repetir porque explicam o formato:

* **Sufixo único por execução.** Nada de código fixo `"PRD-001"`: duas execuções em
  paralelo, ou uma execução contra um banco que sobrou, colidiriam na unicidade e a falha
  apareceria num teste que não tem nada a ver com o assunto.
* **Provar o caso positivo antes do negativo.** Um teste que só afirma "não veio nada da
  empresa B" passa igualzinho contra uma fixture vazia. Por isso todo cenário devolve
  também o que *tem* que aparecer, e os testes conferem os dois lados.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core.security import criar_token, gerar_hash_senha
from app.core.tenancy import GUC_EMPRESA, declarar_empresa
from app.modules.auth.models import Usuario
from app.modules.bakeoff.models import (
    Colaborador,
    ColaboradorEmpresa,
    Empresa,
    PapelEmpresa,
    Produto,
    ProdutoEmpresa,
    Variante,
)

# Lê `GUC_EMPRESA` em vez de repetir a string. Não é a linha duplicada que custa: com o
# nome literal aqui, renomear o GUC deixaria `test_guc_vazio_nao_estoura_o_cast` **verde**
# — ele passaria a setar um GUC que ninguém lê, o SELECT voltaria vazio de qualquer forma
# e o `assert linhas == []` seria satisfeito por acidente. O teste que existe para provar o
# NULLIF pararia de provar qualquer coisa, sem nenhum sinal.
SQL_DECLARAR = text(f"SELECT set_config('{GUC_EMPRESA}', :empresa, true)")

# Calculado uma vez: o argon2 é lento de propósito, e nenhum teste daqui faz login — os
# tokens são emitidos direto. Repetir o hash por usuário criado só queimaria segundos.
_HASH_DESCARTAVEL = gerar_hash_senha("senha-de-teste-123")


@dataclass(frozen=True)
class UsuarioDeTeste:
    """Quem loga, o token dele e o e-mail que liga `usuario` a `employees`."""

    id: uuid.UUID
    token: str
    email: str


@dataclass(frozen=True)
class Cenario:
    """Duas empresas com catálogos disjuntos — o mínimo para o isolamento significar algo."""

    sufixo: str
    abacaxi: uuid.UUID
    uva: uuid.UUID
    #: Variante da ABACAXI que ainda **não** tem linha em `product_tenant`. É o alvo do
    #: caso positivo do teste de FK composta: sem ela, só daria para testar a falha.
    variante_livre_abacaxi: uuid.UUID
    #: Variante da UVA, já com preço. Apontar para ela a partir da ABACAXI é o cruzamento
    #: que o banco tem que recusar.
    variante_uva: uuid.UUID
    codigo_abacaxi: str
    codigo_uva: str


async def montar_cenario(motor: AsyncEngine) -> Cenario:
    sufixo = uuid.uuid4().hex[:8]
    codigo_abacaxi = f"ABA-{sufixo}"
    codigo_uva = f"UVA-{sufixo}"

    async with AsyncSession(motor, expire_on_commit=False) as sessao:
        abacaxi = Empresa(name=f"ABACAXI {sufixo}", cnpj=f"11{sufixo.upper()}0001", active=True)
        uva = Empresa(name=f"UVA {sufixo}", cnpj=f"22{sufixo.upper()}0001", active=True)
        sessao.add_all([abacaxi, uva])
        await sessao.commit()

    variante_livre = await _catalogo_da_empresa(
        motor, abacaxi.id, codigo_abacaxi, "Pendente Aurora — cobre escovado"
    )
    variante_uva = await _catalogo_da_empresa(motor, uva.id, codigo_uva, "Plafon Vega — alumínio")

    return Cenario(
        sufixo=sufixo,
        abacaxi=abacaxi.id,
        uva=uva.id,
        variante_livre_abacaxi=variante_livre,
        variante_uva=variante_uva,
        codigo_abacaxi=codigo_abacaxi,
        codigo_uva=codigo_uva,
    )


async def _catalogo_da_empresa(
    motor: AsyncEngine, empresa_id: uuid.UUID, codigo: str, descricao: str
) -> uuid.UUID:
    """Um produto com duas variantes; só a primeira recebe preço.

    Devolve o id da **segunda** — a que ficou sem linha em `product_tenant` e por isso
    aceita uma inserção legítima no teste de FK composta.
    """
    async with AsyncSession(motor, expire_on_commit=False) as sessao:
        await declarar_empresa(sessao, empresa_id)

        produto = Produto(tenant_id=empresa_id, code=codigo, description=descricao, active=True)
        sessao.add(produto)
        await sessao.flush()

        com_preco = Variante(
            tenant_id=empresa_id,
            product_id=produto.id,
            finish="cobre",
            size="P",
            active=True,
        )
        sem_preco = Variante(
            tenant_id=empresa_id,
            product_id=produto.id,
            finish="cobre",
            size="G",
            active=True,
        )
        sessao.add_all([com_preco, sem_preco])
        await sessao.flush()

        sessao.add(
            ProdutoEmpresa(
                tenant_id=empresa_id,
                variant_id=com_preco.id,
                price_cents=189_90,
                stock_qty=Decimal("12.000"),
                min_stock=Decimal("2.000"),
            )
        )
        await sessao.commit()
        return sem_preco.id


async def criar_usuario_vinculado(
    motor: AsyncEngine,
    cenario: Cenario,
    *,
    empresas: tuple[uuid.UUID, ...],
    sufixo_login: str = "",
) -> UsuarioDeTeste:
    """Cria quem loga (`usuario`), quem trabalha (`employees`) e o vínculo entre eles.

    São duas tabelas para a mesma pessoa: o schema fixo do bake-off tem
    `employees(id, name, email, active)`, sem senha, e a S0 guarda credencial em `usuario`.
    A ponte é o e-mail — o mesmo caminho que `_tem_vinculo` percorre em produção.

    `empresas` é a lista de onde a pessoa tem vínculo. Passar uma só é o que permite testar
    o 403: autenticado, mas pedindo a empresa do vizinho.

    Devolve id, token **e e-mail**: o e-mail é a ponte que a autorização percorre, então
    o teste que desativa o colaborador precisa dele para achar a linha. Derivá-lo de novo
    no teste duplicaria o padrão de formatação — e duplicata de padrão apodrece.

    O token é emitido direto em vez de passar pelo login: a suíte não está testando
    autenticação aqui, e o argon2 custa caro por teste.
    """
    email = f"pessoa{sufixo_login}+{cenario.sufixo}@grupo.dev"

    async with AsyncSession(motor, expire_on_commit=False) as sessao:
        usuario = Usuario(
            login=f"user{sufixo_login}-{cenario.sufixo}",
            nome="Pessoa de Teste",
            email=email,
            senha_hash=_HASH_DESCARTAVEL,
        )
        sessao.add(usuario)

        pessoa = Colaborador(name="Pessoa de Teste", email=email, active=True)
        sessao.add(pessoa)
        await sessao.commit()

    for empresa_id in empresas:
        async with AsyncSession(motor, expire_on_commit=False) as sessao:
            await declarar_empresa(sessao, empresa_id)
            sessao.add(
                ColaboradorEmpresa(
                    tenant_id=empresa_id,
                    employee_id=pessoa.id,
                    role=PapelEmpresa.operator_full.value,
                )
            )
            await sessao.commit()

    return UsuarioDeTeste(id=usuario.id, token=criar_token(usuario.id), email=email)


async def criar_usuario_sem_email(motor: AsyncEngine, cenario: Cenario) -> str:
    """Usuário que loga mas não tem como ser ligado a `employees`.

    `Usuario.email` é nulável na S0, então este caso existe de verdade. A alternativa a
    negar — tratar a ausência como "não dá para checar, então deixa passar" — seria o mesmo
    furo com outra cara. Devolve o token.
    """
    async with AsyncSession(motor, expire_on_commit=False) as sessao:
        usuario = Usuario(
            login=f"sem-email-{cenario.sufixo}",
            nome="Sem e-mail",
            senha_hash=_HASH_DESCARTAVEL,
        )
        sessao.add(usuario)
        await sessao.commit()
    return criar_token(usuario.id)


async def criar_colaborador_nos_dois(
    motor: AsyncEngine, cenario: Cenario, nome: str = "ANA SILVA"
) -> uuid.UUID:
    """Mesma identidade global, papel diferente em cada empresa.

    É o caso da ANA SILVA no enunciado do bake-off: `admin` na ABACAXI e `operator-sales`
    na UVA. Prova que o papel não pode ser coluna de `employees`.
    """
    async with AsyncSession(motor, expire_on_commit=False) as sessao:
        pessoa = Colaborador(name=nome, email=f"ana+{cenario.sufixo}@grupo.dev", active=True)
        sessao.add(pessoa)
        await sessao.commit()

    for empresa_id, papel in (
        (cenario.abacaxi, PapelEmpresa.admin),
        (cenario.uva, PapelEmpresa.operator_sales),
    ):
        async with AsyncSession(motor, expire_on_commit=False) as sessao:
            await declarar_empresa(sessao, empresa_id)
            sessao.add(
                ColaboradorEmpresa(tenant_id=empresa_id, employee_id=pessoa.id, role=papel.value)
            )
            await sessao.commit()

    return pessoa.id
