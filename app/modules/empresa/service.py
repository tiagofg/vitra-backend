from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select

from app.common.base_service import BaseService
from app.core.errors import RegraDeNegocio
from app.core.listing import ListingSpec
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
        campo_unico="codigo",
    )

    def _label_lookup(self, obj: Empresa) -> str:
        return obj.nome_fantasia or obj.razao_social

    def _extras_lookup(self, obj: Empresa) -> dict[str, Any]:
        return {"cnpj": obj.cnpj}


class FilialService(BaseService[Filial, FilialCriar, FilialAtualizar]):
    nome_recurso = "Filial"
    spec = ListingSpec(
        model=Filial,
        campos_busca=("codigo", "nome", "cnpj"),
        campo_codigo="codigo",
        campos_ordenacao=("codigo", "nome", "criado_em"),
        ordenacao_padrao="codigo",
        campo_unico="codigo",
    )


class CentroCustoService(BaseService[CentroCusto, CentroCustoCriar, CentroCustoAtualizar]):
    nome_recurso = "Centro de custo"
    spec = ListingSpec(
        model=CentroCusto,
        campos_busca=("codigo", "nome"),
        campo_codigo="codigo",
        campos_ordenacao=("codigo", "nome", "criado_em"),
        ordenacao_padrao="codigo",
        campo_unico="codigo",
    )

    async def _antes_de_atualizar(self, obj: CentroCusto, valores: dict[str, Any]) -> None:
        await super()._antes_de_atualizar(obj, valores)

        if "pai_id" not in valores or valores["pai_id"] is None:
            return
        pai_id: uuid.UUID = valores["pai_id"]

        # Sobe a cadeia de pais a partir do `pai_id` candidato: se `obj` aparecer nela,
        # apontar `obj.pai_id` para lá fecharia um ciclo (A → B → A). A FK composta
        # garante que os dois são da mesma empresa, não que a árvore é acíclica — isso é
        # regra de negócio, não constraint de banco.
        visitados: set[uuid.UUID] = set()
        atual: uuid.UUID | None = pai_id
        while atual is not None:
            if atual == obj.id:
                raise RegraDeNegocio(
                    "Essa mudança de pai formaria um ciclo na árvore de centros de custo.",
                    codigo="ciclo_centro_custo",
                )
            if atual in visitados:
                break  # ciclo pré-existente alheio a esta operação; não é o que valida aqui
            visitados.add(atual)
            atual = (
                await self.session.execute(
                    select(CentroCusto.pai_id).where(CentroCusto.id == atual)
                )
            ).scalar_one_or_none()
