"""Serviços de cadastro de pessoas.

Nenhum filtro por empresa em nenhum `_stmt_base`/`select()` daqui — é o RLS que recorta,
como em todo o resto do projeto desde a SB. O que estes serviços acrescentam ao `BaseService`
comum:

* **Confere o domínio das FKs para `catalog_lookups`.** A FK em si é só
  `catalog_lookups.id` — nada no banco impede apontar `profissao_id` para uma linha de
  `marca`. `_conferir_dominio` fecha essa lacuna como regra de negócio.
* **`ObraService`** é recortado por `cliente_id`, no mesmo molde de `ApoioService` recortado
  por `dominio`.
* **`FornecedorEmpresaService`** não é CRUD: só abre vigência (fecha a anterior) e lista o
  histórico — não há `PUT`/`DELETE` de uma vigência.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.base_service import BaseService
from app.core.errors import NaoEncontrado, RegraDeNegocio
from app.core.listing import ListingSpec
from app.modules.apoio.models import DominioApoio, TabelaApoio
from app.modules.pessoas.models import (
    Cliente,
    Colaborador,
    Fornecedor,
    FornecedorEmpresa,
    Obra,
    ProfissionalExterno,
    Transportadora,
)
from app.modules.pessoas.schemas import (
    ClienteAtualizar,
    ClienteCriar,
    ColaboradorAtualizar,
    ColaboradorCriar,
    FornecedorAtualizar,
    FornecedorCriar,
    FornecedorEmpresaAbrir,
    ObraAtualizar,
    ObraCriar,
    ProfissionalExternoAtualizar,
    ProfissionalExternoCriar,
    TransportadoraAtualizar,
    TransportadoraCriar,
)


async def _conferir_dominio(
    session: AsyncSession, valor: uuid.UUID | None, dominio: DominioApoio, campo: str
) -> None:
    """`campo` aponta para `catalog_lookups.id` — a FK simples não garante *qual* domínio.
    Confere aqui porque é regra de negócio, não algo que o banco possa checar sozinho."""
    if valor is None:
        return
    dominio_real = (
        await session.execute(select(TabelaApoio.dominio).where(TabelaApoio.id == valor))
    ).scalar_one_or_none()
    if dominio_real is None:
        raise RegraDeNegocio(
            f"'{campo}' não corresponde a um valor de apoio existente.",
            codigo="referencia_invalida",
            campos={campo: str(valor)},
        )
    if dominio_real != dominio:
        raise RegraDeNegocio(
            f"'{campo}' precisa ser um valor de apoio do domínio '{dominio.value}'.",
            codigo="dominio_invalido",
            campos={campo: str(valor)},
        )


# --- Cliente ------------------------------------------------------------------

_DOMINIOS_CLIENTE: dict[str, DominioApoio] = {
    "profissao_id": DominioApoio.profissao,
    "estado_civil_id": DominioApoio.estado_civil,
    "raca_cor_id": DominioApoio.raca_cor,
    "nacionalidade_id": DominioApoio.nacionalidade,
    "categoria_id": DominioApoio.categoria,
}


class ClienteService(BaseService[Cliente, ClienteCriar, ClienteAtualizar]):
    nome_recurso = "Cliente"
    spec = ListingSpec(
        model=Cliente,
        campos_busca=("codigo", "nome", "cpf_cnpj"),
        campo_codigo="codigo",
        campos_ordenacao=("codigo", "nome", "criado_em"),
        ordenacao_padrao="codigo",
        campo_unico="codigo",
    )

    async def _antes_de_criar(self, valores: dict[str, Any]) -> None:
        await super()._antes_de_criar(valores)
        await self._conferir_dominios(valores)

    async def _antes_de_atualizar(self, obj: Cliente, valores: dict[str, Any]) -> None:
        await super()._antes_de_atualizar(obj, valores)
        await self._conferir_dominios(valores)

    async def _conferir_dominios(self, valores: dict[str, Any]) -> None:
        for campo, dominio in _DOMINIOS_CLIENTE.items():
            if campo in valores:
                await _conferir_dominio(self.session, valores[campo], dominio, campo)

    def _label_lookup(self, obj: Cliente) -> str:
        return obj.nome

    def _extras_lookup(self, obj: Cliente) -> dict[str, Any]:
        return {"cpf_cnpj": obj.cpf_cnpj}


class ObraService(BaseService[Obra, ObraCriar, ObraAtualizar]):
    """Recortado por `cliente_id`, no mesmo molde de `ApoioService` recortado por
    `dominio` — o `cliente_id` vem do path (`/clientes/{cliente_id}/obras`), nunca do
    corpo."""

    nome_recurso = "Obra"
    spec = ListingSpec(
        model=Obra,
        campos_busca=("nome",),
        campos_ordenacao=("nome", "criado_em"),
        ordenacao_padrao="nome",
    )

    def __init__(
        self,
        session: AsyncSession,
        cliente_id: uuid.UUID,
        usuario_id: uuid.UUID | None = None,
        tenant_id: uuid.UUID | None = None,
    ) -> None:
        super().__init__(session, usuario_id, tenant_id)
        self.cliente_id = cliente_id

    def _stmt_base(self) -> Select[Any]:
        return select(Obra).where(Obra.cliente_id == self.cliente_id)

    async def obter(self, id_: uuid.UUID) -> Obra:
        # `BaseService.obter()` não passa por `_stmt_base()` — é um `select` direto por
        # `id`, então o recorte por `cliente_id` fica de fora se não for conferido aqui.
        # Sem isto, `GET /clientes/A/obras/{obra-de-B}` acharia a obra de outro cliente
        # da mesma empresa. Mesmo motivo de `ApoioService.obter` conferir `dominio`.
        obra = await super().obter(id_)
        if obra.cliente_id != self.cliente_id:
            raise NaoEncontrado(self.nome_recurso, id_)
        return obra

    async def _preparar_valores(self, dados: ObraCriar) -> dict[str, Any]:
        valores = await super()._preparar_valores(dados)
        valores["cliente_id"] = self.cliente_id
        return valores

    def _label_lookup(self, obj: Obra) -> str:
        return obj.nome


# --- Transportadora -------------------------------------------------------------


class TransportadoraService(
    BaseService[Transportadora, TransportadoraCriar, TransportadoraAtualizar]
):
    nome_recurso = "Transportadora"
    spec = ListingSpec(
        model=Transportadora,
        campos_busca=("codigo", "nome", "cnpj"),
        campo_codigo="codigo",
        campos_ordenacao=("codigo", "nome", "criado_em"),
        ordenacao_padrao="codigo",
        campo_unico="codigo",
    )

    def _label_lookup(self, obj: Transportadora) -> str:
        return obj.nome


# --- Fornecedor -----------------------------------------------------------------


class FornecedorService(BaseService[Fornecedor, FornecedorCriar, FornecedorAtualizar]):
    nome_recurso = "Fornecedor"
    spec = ListingSpec(
        model=Fornecedor,
        campos_busca=("codigo", "razao_social", "nome_fantasia", "cnpj"),
        campo_codigo="codigo",
        campos_ordenacao=("codigo", "razao_social", "criado_em"),
        ordenacao_padrao="codigo",
        campo_unico="codigo",
    )

    def _label_lookup(self, obj: Fornecedor) -> str:
        return obj.nome_fantasia or obj.razao_social

    def _extras_lookup(self, obj: Fornecedor) -> dict[str, Any]:
        return {"cnpj": obj.cnpj}


class FornecedorEmpresaService:
    """Histórico de `Empresa compradora` de um fornecedor. Não herda `BaseService`: não há
    `PUT`/`DELETE` de uma vigência — só abrir uma nova (que fecha a anterior) e listar."""

    def __init__(
        self,
        session: AsyncSession,
        fornecedor_id: uuid.UUID,
        usuario_id: uuid.UUID | None = None,
        tenant_id: uuid.UUID | None = None,
    ) -> None:
        self.session = session
        self.fornecedor_id = fornecedor_id
        self.usuario_id = usuario_id
        self.tenant_id = tenant_id

    async def _exigir_fornecedor(self) -> None:
        existe = (
            await self.session.execute(
                select(Fornecedor.id).where(Fornecedor.id == self.fornecedor_id)
            )
        ).first()
        if existe is None:
            raise NaoEncontrado("Fornecedor", self.fornecedor_id)

    async def historico(self) -> list[FornecedorEmpresa]:
        await self._exigir_fornecedor()
        stmt = (
            select(FornecedorEmpresa)
            .where(FornecedorEmpresa.fornecedor_id == self.fornecedor_id)
            .order_by(FornecedorEmpresa.vigencia_inicio.desc())
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def empresa_compradora_em(self, data: date) -> uuid.UUID | None:
        """A vigência que cobre `data` — ou `None` se nenhuma cobre."""
        stmt = select(FornecedorEmpresa.empresa_compradora_id).where(
            FornecedorEmpresa.fornecedor_id == self.fornecedor_id,
            FornecedorEmpresa.vigencia_inicio <= data,
            (FornecedorEmpresa.vigencia_fim.is_(None)) | (FornecedorEmpresa.vigencia_fim >= data),
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def abrir_vigencia(self, dados: FornecedorEmpresaAbrir) -> FornecedorEmpresa:
        await self._exigir_fornecedor()

        aberta = (
            await self.session.execute(
                select(FornecedorEmpresa).where(
                    FornecedorEmpresa.fornecedor_id == self.fornecedor_id,
                    FornecedorEmpresa.vigencia_fim.is_(None),
                )
            )
        ).scalar_one_or_none()

        if aberta is not None:
            if dados.vigencia_inicio <= aberta.vigencia_inicio:
                raise RegraDeNegocio(
                    "A nova vigência precisa começar depois do início da vigência aberta atual.",
                    codigo="vigencia_invalida",
                    campos={"vigencia_inicio": str(dados.vigencia_inicio)},
                )
            aberta.vigencia_fim = dados.vigencia_inicio - timedelta(days=1)

        nova = FornecedorEmpresa(
            tenant_id=self.tenant_id,
            fornecedor_id=self.fornecedor_id,
            empresa_compradora_id=dados.empresa_compradora_id,
            vigencia_inicio=dados.vigencia_inicio,
            motivo=dados.motivo,
        )
        if self.usuario_id is not None:
            nova.criado_por_id = self.usuario_id
        self.session.add(nova)
        await self.session.flush()
        return nova


# --- Profissional externo --------------------------------------------------------


class ProfissionalExternoService(
    BaseService[ProfissionalExterno, ProfissionalExternoCriar, ProfissionalExternoAtualizar]
):
    nome_recurso = "Profissional externo"
    spec = ListingSpec(
        model=ProfissionalExterno,
        campos_busca=("codigo", "nome", "cpf_cnpj"),
        campo_codigo="codigo",
        campos_ordenacao=("codigo", "nome", "criado_em"),
        ordenacao_padrao="codigo",
        campo_unico="codigo",
    )

    async def _antes_de_criar(self, valores: dict[str, Any]) -> None:
        await super()._antes_de_criar(valores)
        if "profissao_id" in valores:
            await _conferir_dominio(
                self.session, valores["profissao_id"], DominioApoio.profissao, "profissao_id"
            )

    async def _antes_de_atualizar(self, obj: ProfissionalExterno, valores: dict[str, Any]) -> None:
        await super()._antes_de_atualizar(obj, valores)
        if "profissao_id" in valores:
            await _conferir_dominio(
                self.session, valores["profissao_id"], DominioApoio.profissao, "profissao_id"
            )

    def _label_lookup(self, obj: ProfissionalExterno) -> str:
        return obj.nome


# --- Colaborador -----------------------------------------------------------------

_DOMINIOS_COLABORADOR: dict[str, DominioApoio] = {
    "cargo_id": DominioApoio.cargo,
    "setor_id": DominioApoio.setor,
    "vinculo_id": DominioApoio.vinculo,
    "grau_instrucao_id": DominioApoio.grau_instrucao,
}


class ColaboradorService(BaseService[Colaborador, ColaboradorCriar, ColaboradorAtualizar]):
    nome_recurso = "Colaborador"
    spec = ListingSpec(
        model=Colaborador,
        campos_ordenacao=("criado_em",),
        ordenacao_padrao="criado_em",
        campo_unico="employee_id",
    )

    async def _antes_de_criar(self, valores: dict[str, Any]) -> None:
        await super()._antes_de_criar(valores)
        await self._conferir_dominios(valores)

    async def _antes_de_atualizar(self, obj: Colaborador, valores: dict[str, Any]) -> None:
        await super()._antes_de_atualizar(obj, valores)
        await self._conferir_dominios(valores)

    async def _conferir_dominios(self, valores: dict[str, Any]) -> None:
        for campo, dominio in _DOMINIOS_COLABORADOR.items():
            if campo in valores:
                await _conferir_dominio(self.session, valores[campo], dominio, campo)

    def _label_lookup(self, obj: Colaborador) -> str:
        return obj.colaborador.nome
