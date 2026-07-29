from __future__ import annotations

import asyncio
import uuid

import pytest
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.common.child_set import substituir_conjunto
from app.core.errors import RegraDeNegocio
from app.core.numbering import ContadorDocumento, TipoDocumento, proximo_numero
from app.modules.empresa.models import Empresa, Filial


class FilialItem(BaseModel):
    """Uma linha da GRADE editável."""

    id: uuid.UUID | None = None
    codigo: str
    nome: str


# --- numeração de documento --------------------------------------------------


async def test_numeracao_e_sequencial_por_serie(
    sessao: AsyncSession, empresa: Empresa
) -> None:
    numeros = [
        await proximo_numero(
            sessao, empresa_id=empresa.id, tipo=TipoDocumento.orcamento, serie="1"
        )
        for _ in range(3)
    ]
    assert numeros == [1, 2, 3]


async def test_series_e_tipos_contam_separado(
    sessao: AsyncSession, empresa: Empresa
) -> None:
    a = await proximo_numero(
        sessao, empresa_id=empresa.id, tipo=TipoDocumento.orcamento, serie="1"
    )
    b = await proximo_numero(
        sessao, empresa_id=empresa.id, tipo=TipoDocumento.orcamento, serie="2"
    )
    c = await proximo_numero(
        sessao, empresa_id=empresa.id, tipo=TipoDocumento.pedido_compra, serie="1"
    )
    assert a == b == c == 1


async def test_empresas_diferentes_nao_compartilham_numeracao(
    sessao: AsyncSession, empresa: Empresa
) -> None:
    outra = Empresa(codigo="VIAHF", razao_social="Via HF")
    sessao.add(outra)
    await sessao.flush()

    await proximo_numero(sessao, empresa_id=empresa.id, tipo=TipoDocumento.orcamento)
    numero = await proximo_numero(
        sessao, empresa_id=outra.id, tipo=TipoDocumento.orcamento
    )
    assert numero == 1


async def test_numeracao_concorrente_nao_repete_numero(motor: AsyncEngine) -> None:
    """Dois documentos criados em paralelo na mesma série não podem repetir número.

    Precisa de transações de verdade (não a fixture que dá rollback): o que está sob teste
    é o `SELECT ... FOR UPDATE` serializando concorrentes.
    """
    async with AsyncSession(motor, expire_on_commit=False) as s:
        empresa = Empresa(codigo="CONCORRENCIA", razao_social="Teste de Concorrência")
        s.add(empresa)
        await s.commit()
        empresa_id = empresa.id

    async def reservar() -> int:
        async with AsyncSession(motor) as s:
            numero = await proximo_numero(
                s, empresa_id=empresa_id, tipo=TipoDocumento.orcamento, serie="1"
            )
            await s.commit()
            return numero

    try:
        numeros = await asyncio.gather(*[reservar() for _ in range(5)])
        assert sorted(numeros) == [1, 2, 3, 4, 5]
    finally:
        async with AsyncSession(motor) as s:
            await s.execute(
                delete(ContadorDocumento).where(ContadorDocumento.empresa_id == empresa_id)
            )
            await s.execute(delete(Empresa).where(Empresa.id == empresa_id))
            await s.commit()


# --- replace-set das grades --------------------------------------------------


async def _filiais(sessao: AsyncSession, empresa: Empresa) -> list[Filial]:
    resultado = await sessao.execute(
        select(Filial).where(Filial.empresa_id == empresa.id).order_by(Filial.codigo)
    )
    return list(resultado.scalars().all())


async def test_substituir_conjunto_insere_atualiza_e_remove(
    sessao: AsyncSession, empresa: Empresa
) -> None:
    await substituir_conjunto(
        sessao,
        model=Filial,
        existentes=[],
        entrada=[
            FilialItem(codigo="001", nome="Matriz"),
            FilialItem(codigo="002", nome="Filial Sul"),
        ],
        fixos={"empresa_id": empresa.id},
    )
    iniciais = await _filiais(sessao, empresa)
    assert [f.codigo for f in iniciais] == ["001", "002"]
    id_matriz = iniciais[0].id

    resultado = await substituir_conjunto(
        sessao,
        model=Filial,
        existentes=iniciais,
        entrada=[
            FilialItem(id=id_matriz, codigo="001", nome="Matriz Renomeada"),
            FilialItem(codigo="003", nome="Filial Norte"),
        ],
        fixos={"empresa_id": empresa.id},
    )

    assert (resultado.criados, resultado.atualizados, resultado.removidos) == (1, 1, 1)
    finais = await _filiais(sessao, empresa)
    assert [f.codigo for f in finais] == ["001", "003"]
    # A linha que sobreviveu manteve o mesmo id — é isso que o diff protege.
    assert finais[0].id == id_matriz
    assert finais[0].nome == "Matriz Renomeada"


async def test_substituir_conjunto_com_lista_vazia_limpa_tudo(
    sessao: AsyncSession, empresa: Empresa
) -> None:
    await substituir_conjunto(
        sessao,
        model=Filial,
        existentes=[],
        entrada=[FilialItem(codigo="001", nome="Matriz")],
        fixos={"empresa_id": empresa.id},
    )
    existentes = await _filiais(sessao, empresa)

    resultado = await substituir_conjunto(
        sessao, model=Filial, existentes=existentes, entrada=[], fixos={"empresa_id": empresa.id}
    )
    assert resultado.removidos == 1
    assert await _filiais(sessao, empresa) == []


async def test_substituir_conjunto_recusa_filho_de_outro_pai(
    sessao: AsyncSession, empresa: Empresa
) -> None:
    with pytest.raises(RegraDeNegocio):
        await substituir_conjunto(
            sessao,
            model=Filial,
            existentes=[],
            entrada=[FilialItem(id=uuid.uuid4(), codigo="001", nome="Intrusa")],
            fixos={"empresa_id": empresa.id},
        )
