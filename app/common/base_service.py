from __future__ import annotations

import uuid
from typing import Any, Generic, TypeVar

from pydantic import BaseModel
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.base_model import ModeloBase
from app.core.errors import NaoEncontrado, RegraDeNegocio
from app.core.listing import ListingSpec, ListParams, Pagina, aplicar_listagem, paginar

M = TypeVar("M", bound=ModeloBase)
CriarSchema = TypeVar("CriarSchema", bound=BaseModel)
AtualizarSchema = TypeVar("AtualizarSchema", bound=BaseModel)


class BaseService(Generic[M, CriarSchema, AtualizarSchema]):
    """CRUD comum. Regra específica sobrescreve os ganchos `_antes_de_*`."""

    spec: ListingSpec
    nome_recurso: str

    # Coleções a inicializar vazias no create. Sem isso, ler a relação depois do flush
    # dispara lazy load em contexto síncrono (MissingGreenlet) — o objeto recém-criado
    # já é persistente, então o SQLAlchemy tenta buscar a coleção no banco.
    colecoes_novas: tuple[str, ...] = ()

    def __init__(self, session: AsyncSession, usuario_id: uuid.UUID | None = None) -> None:
        self.session = session
        self.usuario_id = usuario_id

    @property
    def model(self) -> type[M]:
        return self.spec.model

    async def obter(self, id_: uuid.UUID) -> M:
        obj = await self.session.get(self.model, id_)
        if obj is None:
            raise NaoEncontrado(self.nome_recurso, id_)
        return obj

    def _stmt_base(self) -> Select[Any]:
        """Gancho para recortes fixos do recurso (ex.: o domínio da tabela de apoio)."""
        return select(self.model)

    async def listar(self, params: ListParams, serializar: Any) -> Pagina[Any]:
        stmt = aplicar_listagem(self._stmt_base(), params, self.spec)
        return await paginar(self.session, stmt, params, serializar)

    async def criar(self, dados: CriarSchema) -> M:
        valores = dados.model_dump(exclude_unset=True)
        await self._antes_de_criar(valores)
        obj = self.model(**valores)
        for nome in self.colecoes_novas:
            setattr(obj, nome, [])  # antes do flush: não gera IO
        if self.usuario_id is not None:
            obj.criado_por_id = self.usuario_id
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def atualizar(self, id_: uuid.UUID, dados: AtualizarSchema) -> M:
        obj = await self.obter(id_)
        valores = dados.model_dump(exclude_unset=True)
        await self._antes_de_atualizar(obj, valores)
        for campo, valor in valores.items():
            setattr(obj, campo, valor)
        await self.session.flush()
        return obj

    async def desativar(self, id_: uuid.UUID) -> M:
        """Cadastro nunca é apagado — `Excluir` da tela é desativação lógica."""
        obj = await self.obter(id_)
        if not hasattr(obj, "ativo"):
            raise RegraDeNegocio(f"{self.nome_recurso} não suporta desativação.")
        await self._antes_de_desativar(obj)
        obj.ativo = False
        await self.session.flush()
        return obj

    async def reativar(self, id_: uuid.UUID) -> M:
        obj = await self.obter(id_)
        obj.ativo = True  # type: ignore[attr-defined]
        await self.session.flush()
        return obj

    # Ganchos ------------------------------------------------------------
    async def _antes_de_criar(self, valores: dict[str, Any]) -> None:
        return None

    async def _antes_de_atualizar(self, obj: M, valores: dict[str, Any]) -> None:
        return None

    async def _antes_de_desativar(self, obj: M) -> None:
        return None
