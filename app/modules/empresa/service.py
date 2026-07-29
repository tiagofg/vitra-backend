from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select

from app.common.base_service import BaseService
from app.core.errors import Conflito, RegraDeNegocio
from app.core.listing import ListingSpec, LookupItem, contem_sem_acento
from app.modules.empresa.models import CentroCusto, Empresa, Filial
from app.modules.empresa.schemas import (
    CentroCustoAtualizar,
    CentroCustoCriar,
    EmpresaAtualizar,
    EmpresaCriar,
    FilialAtualizar,
    FilialCriar,
)


class EmpresaService(BaseService[Empresa, EmpresaCriar, EmpresaAtualizar]):
    nome_recurso = "Empresa"
    spec = ListingSpec(
        model=Empresa,
        campos_busca=("codigo", "razao_social", "nome_fantasia", "cnpj"),
        campo_codigo="codigo",
        campos_ordenacao=("codigo", "razao_social", "criado_em"),
        ordenacao_padrao="codigo",
    )

    async def _antes_de_criar(self, valores: dict[str, Any]) -> None:
        codigo = valores.get("codigo")
        existe = (
            await self.session.execute(select(Empresa.id).where(Empresa.codigo == codigo))
        ).first()
        if existe:
            raise Conflito(
                f"Já existe empresa com código '{codigo}'.", campos={"codigo": "já utilizado"}
            )

    async def lookup(self, q: str | None, limite: int) -> list[LookupItem]:
        stmt = select(Empresa).where(Empresa.ativo.is_(True))
        if q:
            stmt = stmt.where(
                contem_sem_acento(Empresa.razao_social, q)
                | contem_sem_acento(Empresa.nome_fantasia, q)
                | contem_sem_acento(Empresa.codigo, q)
            )
        stmt = stmt.order_by(Empresa.codigo).limit(limite)
        return [
            LookupItem(
                id=e.id,
                codigo=e.codigo,
                label=e.nome_fantasia or e.razao_social,
                extras={"cnpj": e.cnpj},
            )
            for e in (await self.session.execute(stmt)).scalars().all()
        ]


class FilialService(BaseService[Filial, FilialCriar, FilialAtualizar]):
    nome_recurso = "Filial"
    spec = ListingSpec(
        model=Filial,
        campos_busca=("codigo", "nome", "cnpj"),
        campo_codigo="codigo",
        campos_ordenacao=("codigo", "nome", "criado_em"),
        ordenacao_padrao="codigo",
        tem_empresa=True,
    )


class CentroCustoService(BaseService[CentroCusto, CentroCustoCriar, CentroCustoAtualizar]):
    nome_recurso = "Centro de custo"
    spec = ListingSpec(
        model=CentroCusto,
        campos_busca=("codigo", "nome"),
        campo_codigo="codigo",
        campos_ordenacao=("codigo", "nome", "criado_em"),
        ordenacao_padrao="codigo",
        tem_empresa=True,
    )

    async def _antes_de_atualizar(self, obj: CentroCusto, valores: dict[str, Any]) -> None:
        pai_id: uuid.UUID | None = valores.get("pai_id")
        if pai_id is not None and pai_id == obj.id:
            raise RegraDeNegocio("Um centro de custo não pode ser pai de si mesmo.")
