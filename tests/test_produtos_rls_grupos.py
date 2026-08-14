"""`ItemRelacionadoService` — o único serviço da S2 que nunca escreve `tenant_id` explícito
numa consulta (`_exigir_grupo`/`listar`, `app/modules/produtos/service.py`): a isolação
inteira depende do RLS.

`tests/test_produtos_catalogo.py` prova o CRUD desses recursos, mas pela fixture `cliente`
— conexão de **dono**, que ignora política. Passar só por lá deixaria essa dependência do
RLS sem prova: achado da revisão do PR de produtos, mesma lição que
`tests/test_rls_isolamento.py` já aplica para `VarianteEmpresa`. Aqui é a versão para
`grupo_relacionado`/`item_relacionado`, direto no serviço, sob o papel de runtime.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core.errors import NaoEncontrado
from app.core.tenancy import declarar_empresa
from app.modules.produtos.models import GrupoRelacionado, ItemRelacionado, Variante
from app.modules.produtos.service import ItemRelacionadoService
from tests.cenario import Cenario


async def _produto_da_variante(
    motor: AsyncEngine, tenant_id: uuid.UUID, variante_id: uuid.UUID
) -> uuid.UUID:
    async with AsyncSession(motor) as sessao:
        await declarar_empresa(sessao, tenant_id)
        return (
            await sessao.execute(select(Variante.produto_id).where(Variante.id == variante_id))
        ).scalar_one()


async def test_item_relacionado_isolado_por_rls(
    motor_runtime: AsyncEngine, cenario: Cenario
) -> None:
    """Grupo e item criados na ABACAXI: visíveis por lá, invisíveis pela UVA — caso
    positivo antes do negativo, para a fixture vazia não fazer o lado UVA passar à toa."""
    produto_id = await _produto_da_variante(
        motor_runtime, cenario.abacaxi, cenario.variante_livre_abacaxi
    )

    async with AsyncSession(motor_runtime, expire_on_commit=False) as sessao:
        await declarar_empresa(sessao, cenario.abacaxi)
        grupo = GrupoRelacionado(tenant_id=cenario.abacaxi, produto_id=produto_id, nome="Kit")
        sessao.add(grupo)
        await sessao.flush()
        item = ItemRelacionado(
            tenant_id=cenario.abacaxi,
            grupo_id=grupo.id,
            produto_id=produto_id,
            quantidade=Decimal(2),
        )
        sessao.add(item)
        await sessao.commit()
        grupo_id = grupo.id

    # Positivo: sob a mesma empresa, o serviço enxerga o grupo e o item.
    async with AsyncSession(motor_runtime, expire_on_commit=False) as sessao:
        await declarar_empresa(sessao, cenario.abacaxi)
        servico = ItemRelacionadoService(sessao, produto_id, grupo_id)
        itens = await servico.listar()

    assert len(itens) == 1
    assert itens[0].id == item.id

    # Negativo: sob a UVA, a mesma consulta não encontra o grupo — não porque o serviço
    # filtrou por `tenant_id` (ele não filtra), mas porque o RLS torna a linha invisível.
    async with AsyncSession(motor_runtime, expire_on_commit=False) as sessao:
        await declarar_empresa(sessao, cenario.uva)
        servico_uva = ItemRelacionadoService(sessao, produto_id, grupo_id)
        with pytest.raises(NaoEncontrado):
            await servico_uva.listar()
