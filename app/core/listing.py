from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field
from typing import Any, Generic, Literal, TypeVar

from fastapi import Query
from pydantic import BaseModel
from sqlalchemy import ColumnElement, Select, asc, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import config
from app.core.errors import ErroDominio, Falha, pode_falhar

T = TypeVar("T")

ORDENACAO_INVALIDA = Falha(
    status=ErroDominio.http_status,
    codigo="ordenacao_invalida",
    descricao="`ordenar_por` fora da whitelist do recurso.",
    mensagem="Não é possível ordenar por 'senha_hash'.",
    campos={"ordenar_por": "permitidos: codigo, razao_social, criado_em"},
)


# Declarado na classe, e não em cada listagem: quem aceita `ordenar_por` é ela, e toda rota
# que a usa como dependência herda o 400 sem repetir nada.
@pode_falhar(ORDENACAO_INVALIDA)
class ListParams:
    """A barra de 7 ações das listagens do legado vira este único conjunto de parâmetros.

    Usado como dependência: `params: ListParams = Depends()`.
    """

    def __init__(
        self,
        busca: str | None = Query(None, description="Texto livre nos campos de busca do recurso"),
        busca_codigo: str | None = Query(None, description="Busca exata por código"),
        pagina: int = Query(1, ge=1),
        tamanho: int = Query(config.pagina_tamanho_padrao, ge=1, le=config.pagina_tamanho_maximo),
        ordenar_por: str | None = Query(None),
        ordem: Literal["asc", "desc"] = Query("asc"),
        ativo: bool | None = Query(None, description="Nulo = todos"),
    ) -> None:
        self.busca = busca.strip() if busca else None
        self.busca_codigo = busca_codigo.strip() if busca_codigo else None
        self.pagina = pagina
        self.tamanho = tamanho
        self.ordenar_por = ordenar_por
        self.ordem = ordem
        self.ativo = ativo

    @property
    def offset(self) -> int:
        return (self.pagina - 1) * self.tamanho


def contem_sem_acento(coluna: Any, texto: str) -> ColumnElement[bool]:
    """`ILIKE %texto%` ignorando acento — 'sao' encontra 'São Paulo'.

    Quem digita num `[busca +...]` não põe acento. `vitra_unaccent` é o wrapper IMMUTABLE
    criado na migração `0402c7bf6bee`; normalizar os dois lados é o que faz o casamento
    funcionar nos dois sentidos ('são' também encontra 'Sao').
    """
    return func.vitra_unaccent(coluna).ilike(func.vitra_unaccent(f"%{texto}%"))


@dataclass(frozen=True)
class ListingSpec:
    """Declara, por recurso, o que é buscável e o que é ordenável. Whitelist explícita:
    `ordenar_por` vem do cliente e nunca pode virar SQL arbitrário."""

    model: type[Any]
    campos_busca: tuple[str, ...] = ()
    campo_codigo: str | None = None
    campos_ordenacao: tuple[str, ...] = field(default_factory=tuple)
    ordenacao_padrao: str = "criado_em"
    tem_ativo: bool = True


class Pagina(BaseModel, Generic[T]):
    itens: list[T]
    total: int
    pagina: int
    tamanho: int
    paginas: int


def aplicar_listagem(stmt: Select[Any], params: ListParams, spec: ListingSpec) -> Select[Any]:
    """Filtros + ordenação. A paginação fica em `paginar`, que precisa contar antes."""
    model = spec.model

    if params.busca and spec.campos_busca:
        stmt = stmt.where(
            or_(
                *[
                    contem_sem_acento(getattr(model, campo), params.busca)
                    for campo in spec.campos_busca
                ]
            )
        )

    if params.busca_codigo and spec.campo_codigo:
        stmt = stmt.where(getattr(model, spec.campo_codigo) == params.busca_codigo)

    if params.ativo is not None and spec.tem_ativo:
        stmt = stmt.where(model.ativo.is_(params.ativo))

    campo_ordem = params.ordenar_por or spec.ordenacao_padrao
    permitidos = spec.campos_ordenacao or (spec.ordenacao_padrao,)
    if params.ordenar_por is not None and campo_ordem not in permitidos:
        raise ErroDominio(
            f"Não é possível ordenar por '{campo_ordem}'.",
            codigo="ordenacao_invalida",
            campos={"ordenar_por": f"permitidos: {', '.join(permitidos)}"},
        )

    coluna = getattr(model, campo_ordem)
    stmt = stmt.order_by(desc(coluna) if params.ordem == "desc" else asc(coluna))
    # Desempate estável: sem isso, páginas seguintes podem repetir ou pular linhas.
    return stmt.order_by(asc(model.id))


async def paginar(
    session: AsyncSession,
    stmt: Select[Any],
    params: ListParams,
    serializar: Any,
) -> Pagina[Any]:
    total_stmt = select(func.count()).select_from(stmt.order_by(None).subquery())
    total = (await session.execute(total_stmt)).scalar_one()

    resultado = await session.execute(stmt.offset(params.offset).limit(params.tamanho))
    itens = [serializar(linha) for linha in resultado.scalars().unique().all()]

    return Pagina(
        itens=itens,
        total=total,
        pagina=params.pagina,
        tamanho=params.tamanho,
        paginas=math.ceil(total / params.tamanho) if params.tamanho else 0,
    )


class LookupItem(BaseModel):
    """Retorno padronizado de todo `[busca +...]` / F4-F5-F6 do legado."""

    id: uuid.UUID
    codigo: str | None = None
    label: str
    extras: dict[str, Any] = {}
