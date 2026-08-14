"""Cenário de dados para os testes de multiempresa (ex-bake-off).

Duas regras que a qualidade do VITRA exige e que valem repetir porque explicam o formato:

* **Sufixo único por execução.** Nada de código fixo `"PRD-001"`: duas execuções em
  paralelo, ou uma execução contra um banco que sobrou, colidiriam na unicidade e a falha
  apareceria num teste que não tem nada a ver com o assunto.
* **Provar o caso positivo antes do negativo.** Um teste que só afirma "não veio nada da
  empresa B" passa igualzinho contra uma fixture vazia. Por isso todo cenário devolve
  também o que *tem* que aparecer, e os testes conferem os dois lados.

Desde a unificação (S0.5), `Usuario` **é** a identidade de quem trabalha — não há mais uma
segunda tabela `employees` ligada por e-mail. `VinculoEmpresa` liga `Usuario.id` direto a
`tenant_id`, então montar um cenário fica mais simples: não existe mais o caso "usuário sem
e-mail não alcança empresa nenhuma" — todo `Usuario` tem e-mail (é NOT NULL agora), e quem
não tem vínculo simplesmente não tem linha em `VinculoEmpresa`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core.security import criar_token, gerar_hash_senha
from app.core.tenancy import GUC_EMPRESA, declarar_empresa
from app.modules.apoio.models import DominioApoio, TabelaApoio
from app.modules.auth.models import Grupo, Permissao, Usuario, VinculoEmpresa
from app.modules.empresa.models import Empresa
from app.modules.produtos.models import Produto, Variante, VarianteEmpresa

# Nome fixo do grupo que `criar_usuario_vinculado` concede por padrão. Get-or-create: vários
# testes criam usuários na mesma execução, e `Grupo.nome`/`Permissao.(recurso, acao)` são
# `UniqueConstraint` — recriar a cada chamada estouraria a partir do segundo teste.
_NOME_GRUPO_PRODUTOS = "produtos (cenário de teste)"


def parceiro_json(codigo: str, razao_social: str, **papeis: bool) -> dict[str, object]:
    """Corpo de `POST /parceiros`. Desde a unificação em `partners`, criar um fornecedor é
    criar um parceiro com `e_fornecedor=true` — não há mais `POST /fornecedores`.

    Sem papel explícito assume fornecedor: é o uso dominante nos testes de catálogo, que
    precisam de alguém para pendurar em `produto_fornecedor`. Passe `e_cliente=True` (etc.)
    para os outros.
    """
    corpo: dict[str, object] = {
        "codigo": codigo,
        "razao_social": razao_social,
        "tipo_pessoa": "juridica",
        "e_cliente": False,
        "e_fornecedor": True,
        "e_profissional": False,
    }
    corpo.update(papeis)
    return corpo


# Lê `GUC_EMPRESA` em vez de repetir a string. Não é a linha duplicada que custa: com o
# nome literal aqui, renomear o GUC deixaria `test_guc_vazio_nao_estoura_o_cast` **verde**
# por acidente — ele passaria a setar um GUC que ninguém lê, e o `assert linhas == []`
# seria satisfeito sem provar mais nada sobre o NULLIF.
SQL_DECLARAR = text(f"SELECT set_config('{GUC_EMPRESA}', :empresa, true)")

# Calculado uma vez: o argon2 é lento de propósito, e nenhum teste daqui faz login — os
# tokens são emitidos direto. Repetir o hash por usuário criado só queimaria segundos.
_HASH_DESCARTAVEL = gerar_hash_senha("senha-de-teste-123")


@dataclass(frozen=True)
class UsuarioDeTeste:
    """Quem loga e o token dele."""

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
        abacaxi = Empresa(codigo=f"ABACAXI-{sufixo}", razao_social=f"ABACAXI {sufixo}", cnpj=None)
        uva = Empresa(codigo=f"UVA-{sufixo}", razao_social=f"UVA {sufixo}", cnpj=None)
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


async def apoio_id(
    sessao: AsyncSession, dominio: DominioApoio, codigo: str, nome: str
) -> uuid.UUID:
    """Get-or-create num valor de `catalog_lookups` — global, então reaproveitado entre
    empresas e entre execuções que caiam no mesmo `codigo`. Mesmo padrão de
    `_grupo_produtos` para `Grupo`."""
    existente = (
        await sessao.execute(
            select(TabelaApoio.id).where(
                TabelaApoio.dominio == dominio, TabelaApoio.codigo == codigo
            )
        )
    ).scalar_one_or_none()
    if existente is not None:
        return existente
    novo = TabelaApoio(dominio=dominio, codigo=codigo, descricao=nome)
    sessao.add(novo)
    await sessao.flush()
    return novo.id


async def _catalogo_da_empresa(
    motor: AsyncEngine, empresa_id: uuid.UUID, codigo: str, descricao: str
) -> uuid.UUID:
    """Um produto com duas variantes; só a primeira recebe preço.

    Devolve o id da **segunda** — a que ficou sem linha em `product_tenant` e por isso
    aceita uma inserção legítima no teste de FK composta.
    """
    async with AsyncSession(motor, expire_on_commit=False) as sessao:
        await declarar_empresa(sessao, empresa_id)

        # `catalog_lookups` é global e sem RLS: o get-or-create roda sob a mesma conexão
        # declarada para `empresa_id`, mas a tabela em si não é recortada por tenant.
        acabamento_id = await apoio_id(sessao, DominioApoio.acabamento, "cobre", "Cobre")
        tamanho_p_id = await apoio_id(sessao, DominioApoio.tamanho, "p", "Pequeno")
        tamanho_g_id = await apoio_id(sessao, DominioApoio.tamanho, "g", "Grande")

        produto = Produto(tenant_id=empresa_id, codigo=codigo, descricao=descricao, ativo=True)
        sessao.add(produto)
        await sessao.flush()

        com_preco = Variante(
            tenant_id=empresa_id,
            produto_id=produto.id,
            acabamento_id=acabamento_id,
            tamanho_id=tamanho_p_id,
            ativo=True,
        )
        sem_preco = Variante(
            tenant_id=empresa_id,
            produto_id=produto.id,
            acabamento_id=acabamento_id,
            tamanho_id=tamanho_g_id,
            ativo=True,
        )
        sessao.add_all([com_preco, sem_preco])
        await sessao.flush()

        sessao.add(
            VarianteEmpresa(
                tenant_id=empresa_id,
                variante_id=com_preco.id,
                preco_cents=189_90,
                estoque_minimo=Decimal("2.000"),
            )
        )
        await sessao.commit()
        return sem_preco.id


async def _grupo_produtos(sessao: AsyncSession) -> Grupo:
    """Grupo global `produto:ler`+`produto:criar`, criado sob demanda e reaproveitado.

    Get-or-create em vez de fixture de schema porque só quem bate em `/produtos` precisa
    dele — os testes de RLS/vínculo puro (a maioria do cenário) nunca leem `permissoes_efetivas`.
    """
    grupo = (
        await sessao.execute(select(Grupo).where(Grupo.nome == _NOME_GRUPO_PRODUTOS))
    ).scalar_one_or_none()
    if grupo is not None:
        return grupo

    permissoes = []
    for acao in ("ler", "criar"):
        permissao = (
            await sessao.execute(
                select(Permissao).where(Permissao.recurso == "produto", Permissao.acao == acao)
            )
        ).scalar_one_or_none()
        if permissao is None:
            permissao = Permissao(recurso="produto", acao=acao, descricao=f"{acao} produto")
            sessao.add(permissao)
            await sessao.flush()
        permissoes.append(permissao)

    grupo = Grupo(nome=_NOME_GRUPO_PRODUTOS, permissoes=permissoes)
    sessao.add(grupo)
    await sessao.flush()
    return grupo


async def criar_usuario_vinculado(
    motor: AsyncEngine,
    cenario: Cenario,
    *,
    empresas: tuple[uuid.UUID, ...],
    sufixo_login: str = "",
    com_permissao_produtos: bool = True,
) -> UsuarioDeTeste:
    """Cria quem loga e o vínculo dele com cada empresa em `empresas`.

    Passar uma empresa só é o que permite testar o 403: autenticado, mas pedindo a empresa
    do vizinho. O token é emitido direto em vez de passar pelo login: a suíte não está
    testando autenticação aqui, e o argon2 custa caro por teste.

    `com_permissao_produtos=True` (padrão): concede o grupo `produto:ler`+`produto:criar`.
    Este cenário existe para exercitar RLS e vínculo entre empresas, não RBAC recurso+ação —
    sem a concessão, toda rota que ganhou `require(...)` (produtos, por exemplo) devolveria
    403 antes mesmo de chegar na checagem que o teste quer provar. Um `superusuario=True`
    mascararia a mesma checagem, então a concessão é uma permissão real, não um bypass.
    Passar `False` monta o caso oposto — autenticado, com ou sem vínculo, mas sem a
    permissão — que é o que prova que `require()` está de fato no caminho.
    """
    email = f"pessoa{sufixo_login}+{cenario.sufixo}@grupo.dev"

    async with AsyncSession(motor, expire_on_commit=False) as sessao:
        grupos = [await _grupo_produtos(sessao)] if com_permissao_produtos else []
        usuario = Usuario(
            login=f"user{sufixo_login}-{cenario.sufixo}",
            nome="Pessoa de Teste",
            email=email,
            senha_hash=_HASH_DESCARTAVEL,
            grupos=grupos,
        )
        sessao.add(usuario)
        await sessao.commit()

    # Um `flush()` por empresa: inserir os vínculos de duas empresas na mesma sessão sem
    # dar `flush()` entre elas faria o SQLAlchemy juntar os dois INSERTs num único
    # `executemany`, que sairia inteiro sob o `SET LOCAL` da última empresa declarada —
    # exatamente o tipo de furo silencioso que este cenário existe para não ter.
    for empresa_id in empresas:
        async with AsyncSession(motor, expire_on_commit=False) as sessao:
            await declarar_empresa(sessao, empresa_id)
            sessao.add(VinculoEmpresa(tenant_id=empresa_id, employee_id=usuario.id))
            await sessao.commit()

    return UsuarioDeTeste(id=usuario.id, token=criar_token(usuario.id), email=email)


async def criar_usuario_sem_vinculo(motor: AsyncEngine, cenario: Cenario) -> str:
    """Usuário que loga mas não tem vínculo com nenhuma empresa. Devolve o token.

    `empresas=()` faz `criar_usuario_vinculado` pular o laço de vínculo inteiro — é a
    mesma criação de identidade, só que sem nenhuma empresa depois.
    """
    usuario = await criar_usuario_vinculado(motor, cenario, empresas=(), sufixo_login="-livre")
    return usuario.token
