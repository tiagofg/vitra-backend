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

from app.core.tenancy import declarar_empresa
from app.modules.bakeoff.models import (
    Colaborador,
    ColaboradorEmpresa,
    Empresa,
    PapelEmpresa,
    Produto,
    ProdutoEmpresa,
    Variante,
)

SQL_DECLARAR = text("SELECT set_config('app.current_tenant', :empresa, true)")


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
