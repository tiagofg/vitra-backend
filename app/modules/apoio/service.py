from __future__ import annotations

import re
import unicodedata
import uuid
from typing import Any

from sqlalchemy import ColumnElement, Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.base_service import BaseService
from app.core.errors import NaoEncontrado, RegraDeNegocio
from app.core.listing import ListingSpec, LookupItem, contem_sem_acento
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


async def conferir_dominio(
    session: AsyncSession, valor: uuid.UUID | None, dominio: DominioApoio, campo: str
) -> None:
    """`campo` aponta para `catalog_lookups.id` — a FK simples não garante *qual* domínio
    (nada impede `profissao_id` apontar para uma linha de `marca`). Confere aqui porque é
    regra de negócio, não algo que o banco possa checar sozinho. Usada por qualquer serviço
    de outro módulo com FK para `catalog_lookups` — `pessoas` e `produtos`, por ora.
    """
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


class ConfereDominiosMixin:
    """Gancho comum a serviços com FK simples para `catalog_lookups`: a subclasse só
    declara `dominios_por_campo`, o resto (checar em `criar` e em `atualizar`) é herdado.

    Precisa vir **antes** de `BaseService` na lista de bases — é o que faz
    `super()._antes_de_criar(...)` chamar a implementação de `BaseService` em vez de
    recursão infinita. `self.session` também vem de `BaseService.__init__`, herdado
    normalmente; o mypy não enxerga essa garantia através do mixin, daí os `type: ignore`.
    """

    dominios_por_campo: dict[str, DominioApoio] = {}

    async def _antes_de_criar(self, valores: dict[str, Any]) -> None:
        await super()._antes_de_criar(valores)  # type: ignore[misc]
        await self._conferir_dominios(valores)

    async def _antes_de_atualizar(self, obj: Any, valores: dict[str, Any]) -> None:
        await super()._antes_de_atualizar(obj, valores)  # type: ignore[misc]
        await self._conferir_dominios(valores)

    async def _conferir_dominios(self, valores: dict[str, Any]) -> None:
        for campo, dominio in self.dominios_por_campo.items():
            if campo in valores:
                await conferir_dominio(self.session, valores[campo], dominio, campo)  # type: ignore[attr-defined]


class ApoioService(BaseService[TabelaApoio, ApoioCriar, ApoioAtualizar]):
    """Um serviço para os 19 combos. O domínio é o recorte."""

    nome_recurso = "Valor de apoio"
    spec = ListingSpec(
        model=TabelaApoio,
        campos_busca=("codigo", "descricao"),
        campo_codigo="codigo",
        campos_ordenacao=("ordem", "codigo", "descricao", "criado_em"),
        ordenacao_padrao="descricao",
        campo_unico="codigo",
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

    def _filtro_unicidade_extra(self) -> ColumnElement[bool]:
        # `codigo` é único **por domínio**, não global: "preto" existe em `marca` e em
        # `acabamento` ao mesmo tempo — ver `test_mesmo_codigo_em_dominios_diferentes_convive`.
        return TabelaApoio.dominio == self.dominio

    async def obter(self, id_: uuid.UUID) -> TabelaApoio:
        obj = await super().obter(id_)
        if obj.dominio != self.dominio:
            # Não vaza a existência do registro em outro domínio.
            raise NaoEncontrado(self.nome_recurso, id_)
        return obj

    async def _preparar_valores(self, dados: ApoioCriar) -> dict[str, Any]:
        valores = await super()._preparar_valores(dados)
        valores["dominio"] = self.dominio
        # `codigo` opcional: o botão `...` da tela cria o valor só com a descrição. Sem
        # `codigo` explícito, deriva do slug e já garante disponibilidade no laço — por
        # isso `_antes_de_criar` (via `spec.campo_unico`) nunca rejeita um código derivado.
        valores["codigo"] = dados.codigo or await self._codigo_livre(slugificar(dados.descricao))
        return valores

    def _ordenacao_lookup(self) -> tuple[Any, ...]:
        # `ordem` é a posição curada da tela (o combo do legado); `descricao` só desempata.
        return (TabelaApoio.ordem, TabelaApoio.descricao)

    def _label_lookup(self, obj: TabelaApoio) -> str:
        return obj.descricao

    async def _codigo_livre(self, base: str) -> str:
        candidato = base
        sufixo = 2
        while not await self._campo_disponivel("codigo", candidato):
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
    """Fora da tabela de apoio: `[busca +...]` com campos próprios (UF, IBGE).

    `lookup` não usa `BaseService.lookup()`: recebe um parâmetro extra (`uf`) que o
    contrato genérico não tem, e o rótulo precisa do `join` carregado (`Cidade.uf`), não
    só das colunas da própria linha.
    """

    nome_recurso = "Cidade"
    spec = ListingSpec(
        model=Cidade,
        campos_busca=("nome",),
        campos_ordenacao=("nome", "criado_em"),
        ordenacao_padrao="nome",
        tem_ativo=False,
    )

    # Assinatura deliberadamente diferente da base (parâmetro `uf` a mais) — ver o
    # docstring da classe. Nunca chamado por uma referência `BaseService`, então o LSP
    # que o mypy cobra aqui não se aplica de verdade.
    async def lookup(  # type: ignore[override]
        self, q: str | None, limite: int, uf: str | None
    ) -> list[LookupItem]:
        stmt = select(Cidade).join(Uf)
        if q:
            stmt = stmt.where(contem_sem_acento(Cidade.nome, q))
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
        campo_unico="codigo",
    )

    def _label_lookup(self, obj: Banco) -> str:
        return f"{obj.codigo} - {obj.nome}"
