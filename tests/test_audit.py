"""`registrar_evento()` não tem nenhum chamador de produção ainda (entra em S3/S4, quando
`estoque`/`vendas` existirem) — mas fica no repositório, então precisa de prova própria. O
risco que o docstring do módulo aponta é concreto: `antes`/`depois` são `JSONB`, e o
serializador padrão do SQLAlchemy não converte `Decimal` nem `UUID` sozinho. Sem este teste,
esse bug só apareceria no primeiro uso real, dentro de outra fase.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.exc import StatementError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core.audit import AcaoAuditoria, RegistroAuditoria, registrar_evento
from app.core.tenancy import declarar_empresa
from tests.cenario import Cenario


async def test_registrar_evento_grava_na_mesma_transacao(
    motor_runtime: AsyncEngine, cenario: Cenario
) -> None:
    linha_id = uuid.uuid4()
    async with AsyncSession(motor_runtime, expire_on_commit=False) as sessao:
        await declarar_empresa(sessao, cenario.abacaxi)
        await registrar_evento(
            sessao,
            tenant_id=cenario.abacaxi,
            tabela="products",
            linha_id=linha_id,
            acao=AcaoAuditoria.criar,
            antes=None,
            depois={"codigo": "ABC-1", "ativo": True},
        )
        await sessao.commit()

    async with AsyncSession(motor_runtime) as sessao:
        await declarar_empresa(sessao, cenario.abacaxi)
        registro = (
            await sessao.execute(
                select(RegistroAuditoria).where(RegistroAuditoria.linha_id == linha_id)
            )
        ).scalar_one()

    assert registro.tabela == "products"
    assert registro.acao == AcaoAuditoria.criar
    assert registro.antes is None
    assert registro.depois == {"codigo": "ABC-1", "ativo": True}


async def test_registrar_evento_so_enxerga_a_empresa_declarada(
    motor_runtime: AsyncEngine, cenario: Cenario
) -> None:
    """`audit_log` está em `TABELAS_POR_EMPRESA` — RLS recorta como qualquer outra."""
    codigo_uva = f"SO-UVA-{cenario.sufixo}"
    async with AsyncSession(motor_runtime, expire_on_commit=False) as sessao:
        await declarar_empresa(sessao, cenario.uva)
        await registrar_evento(
            sessao,
            tenant_id=cenario.uva,
            tabela="products",
            linha_id=uuid.uuid4(),
            acao=AcaoAuditoria.criar,
            depois={"codigo": codigo_uva},
        )
        await sessao.commit()

    # Positivo: sob a própria empresa, o registro aparece.
    async with AsyncSession(motor_runtime) as sessao:
        await declarar_empresa(sessao, cenario.uva)
        assert (
            await sessao.execute(
                select(RegistroAuditoria.id).where(
                    RegistroAuditoria.depois["codigo"].astext == codigo_uva
                )
            )
        ).first() is not None

    # Negativo: sob a empresa vizinha, não.
    async with AsyncSession(motor_runtime) as sessao:
        await declarar_empresa(sessao, cenario.abacaxi)
        assert (
            await sessao.execute(
                select(RegistroAuditoria.id).where(
                    RegistroAuditoria.depois["codigo"].astext == codigo_uva
                )
            )
        ).first() is None


async def test_registrar_evento_rejeita_valor_nao_serializavel_em_json(
    motor_runtime: AsyncEngine, cenario: Cenario
) -> None:
    """`Decimal` e `UUID` cru dentro de `antes`/`depois` não são JSON-serializáveis pelo
    codec padrão — é exatamente o risco que o docstring do módulo descreve. Prova que o
    erro aparece na hora (`flush`), não como dado corrompido silencioso: quem for chamar
    isto em S3/S4 precisa converter (`str(valor)`, `float`/`int` em centavos) antes.

    `StatementError`, não `TypeError` cru: é a exceção do SQLAlchemy que embrulha a falha
    do serializador JSON — `.orig`/`__cause__` é o `TypeError` de verdade.
    """
    async with AsyncSession(motor_runtime, expire_on_commit=False) as sessao:
        await declarar_empresa(sessao, cenario.abacaxi)
        with pytest.raises(StatementError, match="not JSON serializable"):
            await registrar_evento(
                sessao,
                tenant_id=cenario.abacaxi,
                tabela="product_tenant",
                linha_id=uuid.uuid4(),
                acao=AcaoAuditoria.atualizar,
                antes={"preco_cents": Decimal("100.00")},
            )
