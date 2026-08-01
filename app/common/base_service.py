from __future__ import annotations

import uuid
from typing import Any, Generic, TypeVar

from pydantic import BaseModel
from sqlalchemy import ColumnElement, Select, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.base_model import _ModeloComId
from app.core.errors import Conflito, NaoEncontrado, RegraDeNegocio
from app.core.listing import (
    ListingSpec,
    ListParams,
    LookupItem,
    Pagina,
    aplicar_listagem,
    contem_sem_acento,
    paginar,
)

M = TypeVar("M", bound=_ModeloComId)
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

    # Campos do schema de entrada que **não** são coluna — mapeiam para relação
    # (`grupo_ids` → `Usuario.grupos`) e por isso saem de `model_dump()`/`setattr` e vão
    # para `_resolver_relacoes`, o gancho feito para eles.
    campos_relacao: frozenset[str] = frozenset()

    def __init__(
        self,
        session: AsyncSession,
        usuario_id: uuid.UUID | None = None,
        tenant_id: uuid.UUID | None = None,
    ) -> None:
        self.session = session
        self.usuario_id = usuario_id
        # Só usado por serviços de modelo `ModeloTenant`: injeta o `tenant_id` no `criar()`
        # sem que cada serviço concreto precise sobrescrever o método só para isso. Não é a
        # empresa que autoriza a escrita — isso já aconteceu na dependência da rota — é só
        # o valor que a linha nova precisa carregar.
        self.tenant_id = tenant_id

    @property
    def model(self) -> type[M]:
        return self.spec.model

    async def obter(self, id_: uuid.UUID) -> M:
        # `select().where(id == ...)`, não `session.get()`: `session.get()` espera a PK
        # inteira, e a de um `ModeloTenant` é composta `(tenant_id, id)`. O `WHERE id = ...`
        # sozinho continua correto porque quem recorta por empresa é o RLS, não este método
        # — a mesma razão pela qual nenhum serviço escreve `WHERE tenant_id = ...`.
        obj = (
            await self.session.execute(select(self.model).where(self.model.id == id_))
        ).scalar_one_or_none()
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
        valores = await self._preparar_valores(dados)
        if self.tenant_id is not None and hasattr(self.model, "tenant_id"):
            # Sobrescreve, não `setdefault`: o valor da transação tem que vencer o do
            # corpo, nunca ceder a ele.
            valores["tenant_id"] = self.tenant_id
        await self._antes_de_criar(valores)
        obj = self.model(**valores)
        for nome in self.colecoes_novas:
            setattr(obj, nome, [])  # antes do flush: não gera IO
        if self.usuario_id is not None:
            obj.criado_por_id = self.usuario_id
        # Antes do `add()`, com o objeto ainda transiente: depois de entrar na sessão,
        # atribuir uma relação dispara um lazy load da coleção *antiga* primeiro — e isso
        # é síncrono, então estoura `MissingGreenlet` num contexto async. É o mesmo motivo
        # de `colecoes_novas` inicializar antes daqui.
        await self._resolver_relacoes(obj, dados)
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def atualizar(self, id_: uuid.UUID, dados: AtualizarSchema) -> M:
        obj = await self.obter(id_)
        valores = dados.model_dump(exclude_unset=True, exclude=set(self.campos_relacao))
        await self._antes_de_atualizar(obj, valores)
        for campo, valor in valores.items():
            setattr(obj, campo, valor)
        await self._resolver_relacoes(obj, dados)
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
        if not hasattr(obj, "ativo"):
            raise RegraDeNegocio(f"{self.nome_recurso} não suporta reativação.")
        await self._antes_de_reativar(obj)
        obj.ativo = True
        await self.session.flush()
        return obj

    async def lookup(self, q: str | None, limite: int) -> list[LookupItem]:
        """`[busca +...]` / F4-F5-F6 padronizado. Dirigido pelo `spec` — `campos_busca`
        para o filtro, `campo_codigo` para o código do item. Só o rótulo (`_label_lookup`)
        precisa mesmo de código por recurso; ordenação e extras têm gancho para quem foge
        do padrão (ver `ApoioService`/`EmpresaService`).

        Quem tem forma genuinamente diferente — parâmetro extra, join — não usa isto; ver
        `CidadeService.lookup`.
        """
        stmt = self._stmt_base()
        if hasattr(self.model, "ativo"):
            stmt = stmt.where(getattr(self.model, "ativo").is_(True))  # noqa: B009
        if q and self.spec.campos_busca:
            stmt = stmt.where(
                or_(
                    *[
                        contem_sem_acento(getattr(self.model, campo), q)
                        for campo in self.spec.campos_busca
                    ]
                )
            )
        stmt = stmt.order_by(*self._ordenacao_lookup()).limit(limite)
        linhas = (await self.session.execute(stmt)).scalars().all()
        return [
            LookupItem(
                id=obj.id,
                codigo=getattr(obj, self.spec.campo_codigo) if self.spec.campo_codigo else None,
                label=self._label_lookup(obj),
                extras=self._extras_lookup(obj),
            )
            for obj in linhas
        ]

    # Ganchos — parâmetros não usados de propósito: são o ponto de extensão que a
    # subclasse concreta preenche. `noqa: ARG002` em cada um, não um ignore geral do
    # arquivo, para que um parâmetro esquecido de verdade em outro método continue pegando.

    async def _preparar_valores(self, dados: CriarSchema) -> dict[str, Any]:
        """Dados do schema → kwargs do modelo, na criação. Assíncrono porque derivar um
        valor pode exigir consulta (`ApoioService` deriva `codigo` do slug da descrição,
        checando disponibilidade). Sobrescrever também para excluir campos que não são
        coluna (`senha` → `senha_hash`, nunca os dois) — é aqui, e não em `_antes_de_criar`,
        porque o valor precisa existir antes do objeto ser instanciado."""
        return dados.model_dump(exclude_unset=True, exclude=set(self.campos_relacao))

    async def _resolver_relacoes(self, obj: M, dados: CriarSchema | AtualizarSchema) -> None:  # noqa: ARG002
        """Preenche o que está em `campos_relacao` (`obj.grupos = ...`). Roda depois do
        `setattr`/`add`, antes do `flush()` — o objeto já existe, a coleção pode ser
        atribuída direto."""
        return None

    async def _antes_de_criar(self, valores: dict[str, Any]) -> None:
        """Checa unicidade quando `spec.campo_unico` está declarado. Sobrescrever para
        regra adicional — chame `await super()._antes_de_criar(valores)` para manter esta
        checagem."""
        campo = self.spec.campo_unico
        if campo and campo in valores:
            await self._exigir_campo_livre(campo, valores[campo])

    async def _antes_de_atualizar(self, obj: M, valores: dict[str, Any]) -> None:
        """Mesma checagem de `_antes_de_criar`, ignorando a própria linha (`obj.id`) e só
        quando o valor de fato muda — trocar outros campos não deveria reavaliar
        unicidade do que ficou igual."""
        campo = self.spec.campo_unico
        if campo and campo in valores and valores[campo] != getattr(obj, campo):
            await self._exigir_campo_livre(campo, valores[campo], exceto=obj.id)

    async def _antes_de_desativar(self, obj: M) -> None:  # noqa: ARG002
        return None

    async def _antes_de_reativar(self, obj: M) -> None:  # noqa: ARG002
        return None

    def _filtro_unicidade_extra(self) -> ColumnElement[bool] | None:
        """Recorte adicional para a checagem de `spec.campo_unico` — ex.: `TabelaApoio`
        é única por `(dominio, codigo)`, não só `codigo`."""
        return None

    async def _campo_disponivel(
        self, campo: str, valor: Any, *, exceto: uuid.UUID | None = None
    ) -> bool:
        """`True` se nenhum outro registro visível tem `campo == valor`. Aplica
        `_filtro_unicidade_extra()` quando declarado — é o que faz `TabelaApoio.codigo`
        ser único por domínio, não global."""
        stmt = select(self.model.id).where(getattr(self.model, campo) == valor)
        extra = self._filtro_unicidade_extra()
        if extra is not None:
            stmt = stmt.where(extra)
        if exceto is not None:
            stmt = stmt.where(self.model.id != exceto)
        return (await self.session.execute(stmt)).first() is None

    async def _exigir_campo_livre(
        self, campo: str, valor: Any, *, exceto: uuid.UUID | None = None
    ) -> None:
        if not await self._campo_disponivel(campo, valor, exceto=exceto):
            raise Conflito(
                f"Já existe {self.nome_recurso.lower()} com {campo} '{valor}'.",
                campos={campo: "já utilizado"},
            )

    def _ordenacao_lookup(self) -> tuple[Any, ...]:
        campo = self.spec.campo_codigo or self.spec.ordenacao_padrao
        return (getattr(self.model, campo),)

    def _label_lookup(self, obj: M) -> str:
        raise NotImplementedError(f"{type(self).__name__} precisa de _label_lookup")

    def _extras_lookup(self, obj: M) -> dict[str, Any]:  # noqa: ARG002
        return {}
