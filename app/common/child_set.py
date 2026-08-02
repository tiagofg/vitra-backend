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
    campo_exclusivo: str | None = None,
) -> ResultadoConjunto:
    """*Replace-set* transacional das GRADEs editáveis: diff por PK, não delete-all/insert-all.

    Apagar tudo e reinserir perderia o `id` das linhas — e com ele qualquer coisa que aponte
    para elas (movimento de estoque, item de ordem de compra). O diff preserva identidade.

    `entrada` são schemas com `id` opcional: sem `id` = linha nova; com `id` = linha existente.
    O que ficou de fora da entrada é removido.

    Um `flush()` por item, não um só no fim: índice único parcial (ex.: "um fornecedor
    padrão por produto") é checado pelo Postgres por instrução, não por transação — trocar
    qual linha carrega a bandeira exige que o `UPDATE`/`INSERT` que a desliga seja
    *serializado* antes do que a liga.

    `campo_exclusivo`: nome do campo booleano que só pode ser `True` numa linha do conjunto
    por vez, quando o modelo tem esse tipo de índice. Informado, os itens são processados em
    duas rodadas — quem **não** liga a bandeira primeiro, quem liga depois — para o
    resultado não depender da ordem em que o cliente listou a `entrada`. Achado na revisão
    do PR de produtos: processar simplesmente na ordem da `entrada` corrigia o caso em que o
    cliente por acaso mandava "desliga" antes de "liga", mas devolvia 409 na ordem inversa
    — o índice único parcial não é `DEFERRABLE` (só *constraint* é adiável, e não existe
    unique constraint parcial em Postgres), então a serialização tem que vir do lado do ORM,
    não do banco. `sorted()` é estável: dentro de cada rodada, a ordem da `entrada`
    continua valendo — só a fronteira entre "desliga" e "liga" é reordenada.
    """
    por_id: dict[uuid.UUID, M] = {obj.id: obj for obj in existentes}
    ids_na_entrada: set[uuid.UUID] = set()
    for item in entrada:
        item_id = item.model_dump(include={"id"}).get("id")
        if item_id is not None:
            ids_na_entrada.add(item_id)

    removidos = 0
    for obj_id, obj in por_id.items():
        if obj_id not in ids_na_entrada:
            await session.delete(obj)
            removidos += 1
    if removidos:
        await session.flush()

    itens_preparados: list[tuple[uuid.UUID | None, dict[str, Any]]] = []
    for posicao, item in enumerate(entrada):
        valores = item.model_dump(exclude_unset=True)
        item_id = valores.pop("id", None)
        valores.update(fixos)
        if campo_ordem is not None:
            valores[campo_ordem] = posicao
        itens_preparados.append((item_id, valores))

    if campo_exclusivo is not None:
        itens_preparados.sort(key=lambda par: bool(par[1].get(campo_exclusivo, False)))

    criados = atualizados = 0
    for item_id, valores in itens_preparados:
        if item_id is None:
            novo = model(**valores)
            if usuario_id is not None:
                novo.criado_por_id = usuario_id
            session.add(novo)
            criados += 1
        else:
            existente = por_id.get(item_id)
            if existente is None:
                raise RegraDeNegocio(
                    "Item enviado não pertence a este registro.",
                    codigo="filho_invalido",
                    campos={"id": str(item_id)},
                )
            for campo, valor in valores.items():
                setattr(existente, campo, valor)
            atualizados += 1
        await session.flush()

    return ResultadoConjunto(criados=criados, atualizados=atualizados, removidos=removidos)
