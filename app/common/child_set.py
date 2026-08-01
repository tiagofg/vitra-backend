from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, TypeVar

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.base_model import _ModeloComId
from app.core.errors import RegraDeNegocio

# `_ModeloComId`, não `ModeloBase`: toda grade da S1/S2 em diante é por empresa
# (`ModeloTenant`), que não é subtipo de `ModeloBase` — os dois só compartilham `id` e
# auditoria em `_ModeloComId`. Quem chama para uma grade por empresa passa `tenant_id`
# dentro de `fixos`, junto com a FK do pai.
M = TypeVar("M", bound=_ModeloComId)


@dataclass(frozen=True)
class ResultadoConjunto:
    criados: int
    atualizados: int
    removidos: int


async def substituir_conjunto(
    session: AsyncSession,
    *,
    model: type[M],
    existentes: Sequence[M],
    entrada: Sequence[BaseModel],
    fixos: dict[str, Any],
    usuario_id: uuid.UUID | None = None,
    campo_ordem: str | None = None,
) -> ResultadoConjunto:
    """*Replace-set* transacional das GRADEs editáveis: diff por PK, não delete-all/insert-all.

    Apagar tudo e reinserir perderia o `id` das linhas — e com ele qualquer coisa que aponte
    para elas (movimento de estoque, item de ordem de compra). O diff preserva identidade.

    `entrada` são schemas com `id` opcional: sem `id` = linha nova; com `id` = linha existente.
    O que ficou de fora da entrada é removido.
    """
    por_id: dict[uuid.UUID, M] = {obj.id: obj for obj in existentes}
    vistos: set[uuid.UUID] = set()
    criados = atualizados = 0

    for posicao, item in enumerate(entrada):
        valores = item.model_dump(exclude_unset=True)
        item_id = valores.pop("id", None)
        valores.update(fixos)
        if campo_ordem is not None:
            valores[campo_ordem] = posicao

        if item_id is None:
            novo = model(**valores)
            if usuario_id is not None:
                novo.criado_por_id = usuario_id
            session.add(novo)
            criados += 1
            continue

        existente = por_id.get(item_id)
        if existente is None:
            raise RegraDeNegocio(
                "Item enviado não pertence a este registro.",
                codigo="filho_invalido",
                campos={"id": str(item_id)},
            )
        for campo, valor in valores.items():
            setattr(existente, campo, valor)
        vistos.add(item_id)
        atualizados += 1

    removidos = 0
    for obj_id, obj in por_id.items():
        if obj_id not in vistos:
            await session.delete(obj)
            removidos += 1

    await session.flush()
    return ResultadoConjunto(criados=criados, atualizados=atualizados, removidos=removidos)
