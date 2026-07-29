from __future__ import annotations

import re
import unicodedata
import uuid
from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.base_service import BaseService
from app.core.errors import Conflito, NaoEncontrado
from app.core.listing import ListingSpec, LookupItem
from app.modules.apoio.models import Banco, Cidade, DominioApoio, TabelaApoio, Uf
from app.modules.apoio.schemas import (
    ApoioAtualizar,
    ApoioCriar,
    BancoAtualizar,
    BancoCriar,
    CidadeAtualizar,
    CidadeCriar,
)


def slugificar(texto: str, tamanho: int = 30) -> str:
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    limpo = re.sub(r"[^a-zA-Z0-9]+", "_", sem_acento).strip("_").lower()
    return (limpo or "item")[:tamanho]


class ApoioService(BaseService[TabelaApoio, ApoioCriar, ApoioAtualizar]):
    """Um serviço para os 19 combos. O domínio é o recorte."""

    nome_recurso = "Valor de apoio"
    spec = ListingSpec(
        model=TabelaApoio,
        campos_busca=("codigo", "descricao"),
        campo_codigo="codigo",
        campos_ordenacao=("ordem", "codigo", "descricao", "criado_em"),
        ordenacao_padrao="descricao",
        tem_empresa=True,
    )

    def __init__(
        self,
        session: AsyncSession,
        dominio: DominioApoio,
        usuario_id: uuid.UUID | None = None,
    ) -> None:
        super().__init__(session, usuario_id)
        self.dominio = dominio

    def _stmt_base(self) -> Select[Any]:
        return select(TabelaApoio).where(TabelaApoio.dominio == self.dominio)

    async def obter(self, id_: uuid.UUID) -> TabelaApoio:
        obj = await super().obter(id_)
        if obj.dominio != self.dominio:
            # Não vaza a existência do registro em outro domínio.
            raise NaoEncontrado(self.nome_recurso, id_)
        return obj

    async def criar(self, dados: ApoioCriar) -> TabelaApoio:
        codigo = dados.codigo or await self._codigo_livre(
            slugificar(dados.descricao), dados.empresa_id
        )
        if await self._existe(codigo, dados.empresa_id):
            raise Conflito(
                f"Já existe '{codigo}' no domínio '{self.dominio.value}'.",
                campos={"codigo": "já utilizado"},
            )
        obj = TabelaApoio(
            dominio=self.dominio,
            codigo=codigo,
            descricao=dados.descricao,
            ordem=dados.ordem,
            empresa_id=dados.empresa_id,
            criado_por_id=self.usuario_id,
        )
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def _antes_de_atualizar(self, obj: TabelaApoio, valores: dict[str, Any]) -> None:
        novo_codigo = valores.get("codigo")
        if novo_codigo and novo_codigo != obj.codigo and await self._existe(
            novo_codigo, obj.empresa_id
        ):
            raise Conflito(
                f"Já existe '{novo_codigo}' no domínio '{self.dominio.value}'.",
                campos={"codigo": "já utilizado"},
            )

    async def lookup(
        self, q: str | None, limite: int, empresa_id: uuid.UUID | None
    ) -> list[LookupItem]:
        stmt = self._stmt_base().where(TabelaApoio.ativo.is_(True))
        if q:
            padrao = f"%{q}%"
            stmt = stmt.where(
                TabelaApoio.descricao.ilike(padrao) | TabelaApoio.codigo.ilike(padrao)
            )
        if empresa_id is not None:
            # Valores globais (empresa_id nulo) sempre aparecem.
            stmt = stmt.where(
                (TabelaApoio.empresa_id == empresa_id) | (TabelaApoio.empresa_id.is_(None))
            )
        stmt = stmt.order_by(TabelaApoio.ordem, TabelaApoio.descricao).limit(limite)
        return [
            LookupItem(id=a.id, codigo=a.codigo, label=a.descricao)
            for a in (await self.session.execute(stmt)).scalars().all()
        ]

    async def _existe(self, codigo: str, empresa_id: uuid.UUID | None) -> bool:
        stmt = select(TabelaApoio.id).where(
            TabelaApoio.dominio == self.dominio,
            TabelaApoio.codigo == codigo,
            TabelaApoio.empresa_id.is_(None)
            if empresa_id is None
            else TabelaApoio.empresa_id == empresa_id,
        )
        return (await self.session.execute(stmt)).first() is not None

    async def _codigo_livre(self, base: str, empresa_id: uuid.UUID | None) -> str:
        candidato = base
        sufixo = 2
        while await self._existe(candidato, empresa_id):
            corte = 30 - len(str(sufixo)) - 1
            candidato = f"{base[:corte]}_{sufixo}"
            sufixo += 1
        return candidato


class UfService(BaseService[Uf, Any, Any]):
    nome_recurso = "UF"
    spec = ListingSpec(
        model=Uf,
        campos_busca=("sigla", "nome"),
        campo_codigo="sigla",
        campos_ordenacao=("sigla", "nome"),
        ordenacao_padrao="sigla",
        tem_ativo=False,
    )


class CidadeService(BaseService[Cidade, CidadeCriar, CidadeAtualizar]):
    """Fora da tabela de apoio: `[busca +...]` com campos próprios (UF, IBGE)."""

    nome_recurso = "Cidade"
    spec = ListingSpec(
        model=Cidade,
        campos_busca=("nome",),
        campos_ordenacao=("nome", "criado_em"),
        ordenacao_padrao="nome",
        tem_ativo=False,
    )

    async def lookup(self, q: str | None, limite: int, uf: str | None) -> list[LookupItem]:
        stmt = select(Cidade).join(Uf)
        if q:
            stmt = stmt.where(Cidade.nome.ilike(f"%{q}%"))
        if uf:
            stmt = stmt.where(Uf.sigla == uf.upper())
        stmt = stmt.order_by(Cidade.nome).limit(limite)
        return [
            LookupItem(
                id=c.id,
                codigo=c.codigo_ibge,
                label=f"{c.nome} - {c.uf.sigla}",
                extras={"uf_id": str(c.uf_id), "uf": c.uf.sigla},
            )
            for c in (await self.session.execute(stmt)).scalars().unique().all()
        ]


class BancoService(BaseService[Banco, BancoCriar, BancoAtualizar]):
    nome_recurso = "Banco"
    spec = ListingSpec(
        model=Banco,
        campos_busca=("codigo", "nome"),
        campo_codigo="codigo",
        campos_ordenacao=("codigo", "nome"),
        ordenacao_padrao="codigo",
    )

    async def lookup(self, q: str | None, limite: int) -> list[LookupItem]:
        stmt = select(Banco).where(Banco.ativo.is_(True))
        if q:
            padrao = f"%{q}%"
            stmt = stmt.where(Banco.nome.ilike(padrao) | Banco.codigo.ilike(padrao))
        stmt = stmt.order_by(Banco.codigo).limit(limite)
        return [
            LookupItem(id=b.id, codigo=b.codigo, label=f"{b.codigo} - {b.nome}")
            for b in (await self.session.execute(stmt)).scalars().all()
        ]
