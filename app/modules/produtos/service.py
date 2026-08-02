"""Serviços de produtos.

O que a S2 acrescenta ao esqueleto herdado do bake-off:

* **Confere o domínio das nove FKs para `catalog_lookups`** (`ConfereDominiosMixin`,
  compartilhado com `pessoas` — ver `app/modules/apoio/service.py`).
* **As três grades do `PUT /produtos/{id}`** — variantes, fornecedores e grupos
  relacionados — via `substituir_conjunto` (diff por PK, nunca delete-all/insert-all).
  Só no `atualizar`, nunca no `criar`: `POST` cria o produto sozinho, como `Cliente` cria
  sem `Obra` junto.
* **`lookup` por código próprio *e* por código do fornecedor**, via `EXISTS`
  correlacionado — não `JOIN`, que duplicaria linha e quebraria o `LIMIT` da paginação.
* **`ItemRelacionadoService`** — os itens de um grupo relacionado, escopados por
  `grupo_id` (e conferindo que o grupo é do produto do path), no mesmo molde de
  `ObraService` escopado por `cliente_id`. Fora da grade do `PUT /produtos/{id}` de
  propósito: cada item aponta para *outro* produto/variante, e a tela mexe neles um de
  cada vez (adicionar, remover), não em bloco.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Select, or_, select

from app.common.base_service import BaseService
from app.common.child_set import substituir_conjunto
from app.core.errors import NaoEncontrado, RegraDeNegocio
from app.core.listing import ListingSpec, LookupItem, contem_sem_acento
from app.modules.apoio.models import DominioApoio
from app.modules.apoio.service import ConfereDominiosMixin, conferir_dominio
from app.modules.produtos.models import (
    GrupoRelacionado,
    ItemRelacionado,
    Produto,
    ProdutoFornecedor,
    Variante,
)
from app.modules.produtos.schemas import ItemRelacionadoCriar, ProdutoAtualizar, ProdutoCriar

_DOMINIOS_PRODUTO: dict[str, DominioApoio] = {
    "tipo_produto_id": DominioApoio.tipo_produto,
    "tipo_peca_id": DominioApoio.tipo_peca,
    "tipo_linha_id": DominioApoio.tipo_linha,
    "classificacao_id": DominioApoio.classificacao,
    "designer_modelo_id": DominioApoio.designer_modelo,
    "fabrica_id": DominioApoio.fabrica,
    "marca_id": DominioApoio.marca,
    "unidade_entrada_id": DominioApoio.unidade,
    "unidade_saida_id": DominioApoio.unidade,
}

SPEC_PRODUTO = ListingSpec(
    model=Produto,
    campos_busca=("codigo", "descricao"),
    campo_codigo="codigo",
    campos_ordenacao=("codigo", "descricao", "criado_em"),
    ordenacao_padrao="codigo",
    campo_unico="codigo",
)


class ProdutoService(ConfereDominiosMixin, BaseService[Produto, ProdutoCriar, ProdutoAtualizar]):
    nome_recurso = "Produto"
    spec = SPEC_PRODUTO
    dominios_por_campo = _DOMINIOS_PRODUTO
    colecoes_novas = ("variantes", "fornecedores", "grupos_relacionados")
    campos_relacao = frozenset({"variantes", "fornecedores", "grupos_relacionados"})

    def _stmt_base(self) -> Select[Any]:
        # Sem `.options(selectinload(...))` explícito: `variantes`/`fornecedores`/
        # `grupos_relacionados` já são `lazy="selectin"` no mapeamento
        # (`app/modules/produtos/models.py`) — e precisam ser, porque `BaseService.obter()`
        # (usado dentro de `atualizar()`) não passa por este método, só pelo `select()` cru.
        # Deixar o carregamento como padrão do mapeamento, em vez de opção por consulta, é o
        # que garante os dois caminhos (`listar`/`lookup` aqui, `obter`/`atualizar` fora
        # daqui) carregando do mesmo jeito.
        return select(Produto)

    async def _resolver_relacoes(
        self, obj: Produto, dados: ProdutoCriar | ProdutoAtualizar
    ) -> None:
        if not isinstance(dados, ProdutoAtualizar):
            return

        # `substituir_conjunto` grava as linhas novas com `session.add()` — isso não
        # atualiza a lista Python já carregada em `obj.variantes`/etc (`lazy="selectin"`
        # carrega uma vez e cacheia; adicionar filho pela FK não é o mesmo que atribuir a
        # relação). Sem o `refresh()` no fim, `ProdutoSaida.model_validate(obj)` serializa
        # a coleção de antes do `PUT`, porque é o objeto Python em memória que ela lê,
        # não uma consulta nova ao banco.
        colecoes_tocadas: list[str] = []

        if "variantes" in dados.model_fields_set and dados.variantes is not None:
            # `substituir_conjunto` cria `Variante` direto (fora de `criar()`/`_antes_de_criar`),
            # então nada passa pelo `ConfereDominiosMixin` daqui — sem esta checagem,
            # `acabamento_id`/`tamanho_id` aceitariam qualquer `catalog_lookups.id`, do
            # domínio que fosse (o mesmo furo que a revisão do PR #7 encontrou em
            # `pessoas`, aqui replicado se não fechado).
            for item in dados.variantes:
                await conferir_dominio(
                    self.session, item.acabamento_id, DominioApoio.acabamento, "acabamento_id"
                )
                await conferir_dominio(
                    self.session, item.tamanho_id, DominioApoio.tamanho, "tamanho_id"
                )
            await substituir_conjunto(
                self.session,
                model=Variante,
                existentes=obj.variantes,
                entrada=dados.variantes,
                fixos={"tenant_id": obj.tenant_id, "produto_id": obj.id},
                usuario_id=self.usuario_id,
            )
            colecoes_tocadas.append("variantes")
        if "fornecedores" in dados.model_fields_set and dados.fornecedores is not None:
            await substituir_conjunto(
                self.session,
                model=ProdutoFornecedor,
                existentes=obj.fornecedores,
                entrada=dados.fornecedores,
                fixos={"tenant_id": obj.tenant_id, "produto_id": obj.id},
                usuario_id=self.usuario_id,
                # `uq_produto_fornecedor_padrao`: um padrão por produto. Sem isto, trocar
                # qual fornecedor é o padrão funciona ou não conforme a ordem do array —
                # achado de revisão, rodada 2.
                campo_exclusivo="padrao",
            )
            colecoes_tocadas.append("fornecedores")
        if (
            "grupos_relacionados" in dados.model_fields_set
            and dados.grupos_relacionados is not None
        ):
            await substituir_conjunto(
                self.session,
                model=GrupoRelacionado,
                existentes=obj.grupos_relacionados,
                entrada=dados.grupos_relacionados,
                fixos={"tenant_id": obj.tenant_id, "produto_id": obj.id},
                usuario_id=self.usuario_id,
            )
            colecoes_tocadas.append("grupos_relacionados")

        if colecoes_tocadas:
            await self.session.refresh(obj, attribute_names=colecoes_tocadas)

    def _label_lookup(self, obj: Produto) -> str:
        return obj.descricao

    async def lookup(self, q: str | None, limite: int) -> list[LookupItem]:
        """`[busca +...]` por código/descrição do produto **ou** por código/descrição do
        fornecedor — a tela de orçamento (S4) precisa achar o item digitando o código que o
        fornecedor usa, não só o código próprio."""
        stmt = select(Produto).where(Produto.ativo.is_(True))
        if q:
            no_fornecedor = (
                select(ProdutoFornecedor.id)
                .where(
                    ProdutoFornecedor.tenant_id == Produto.tenant_id,
                    ProdutoFornecedor.produto_id == Produto.id,
                    or_(
                        contem_sem_acento(ProdutoFornecedor.codigo_fornecedor, q),
                        contem_sem_acento(ProdutoFornecedor.descricao_fornecedor, q),
                    ),
                )
                .correlate(Produto)
                .exists()
            )
            stmt = stmt.where(
                or_(
                    contem_sem_acento(Produto.codigo, q),
                    contem_sem_acento(Produto.descricao, q),
                    no_fornecedor,
                )
            )
        stmt = stmt.order_by(Produto.codigo).limit(limite)
        linhas = (await self.session.execute(stmt)).scalars().unique().all()
        return [
            LookupItem(
                id=obj.id,
                codigo=obj.codigo,
                label=obj.descricao,
                extras=self._extras_lookup_com_termo(obj, q),
            )
            for obj in linhas
        ]

    def _extras_lookup_com_termo(self, obj: Produto, q: str | None) -> dict[str, Any]:
        """Qual código casou — senão o front não sabe se o resultado veio do código
        próprio ou do código de um fornecedor específico.

        Comparação simples (`in`, minúsculo) para achar o *hint* de exibição, não o filtro
        de verdade — o filtro já rodou no banco, acentuado-insensível, via
        `contem_sem_acento`. Perder um acento aqui só deixaria de destacar qual fornecedor
        casou; nunca esconde ou inventa resultado.
        """
        if not q:
            return {}
        termo = q.strip().lower()
        if termo in obj.codigo.lower() or termo in obj.descricao.lower():
            return {}
        casado = next(
            (
                f
                for f in obj.fornecedores
                if (f.codigo_fornecedor and termo in f.codigo_fornecedor.lower())
                or (f.descricao_fornecedor and termo in f.descricao_fornecedor.lower())
            ),
            None,
        )
        if casado is None:
            return {}
        return {
            "fornecedor_id": str(casado.fornecedor_id),
            "codigo_fornecedor": casado.codigo_fornecedor,
        }


class ItemRelacionadoService:
    """Itens de um `GrupoRelacionado`, escopados por `grupo_id` — mesmo molde de
    `ObraService` escopado por `cliente_id`. CRUD simples (listar/criar/remover), não
    replace-set: a tela adiciona e remove item um de cada vez."""

    def __init__(
        self,
        session: Any,
        produto_id: uuid.UUID,
        grupo_id: uuid.UUID,
        usuario_id: uuid.UUID | None = None,
        tenant_id: uuid.UUID | None = None,
    ) -> None:
        self.session = session
        self.produto_id = produto_id
        self.grupo_id = grupo_id
        self.usuario_id = usuario_id
        self.tenant_id = tenant_id

    async def _exigir_grupo(self) -> None:
        existe = (
            await self.session.execute(
                select(GrupoRelacionado.id).where(
                    GrupoRelacionado.id == self.grupo_id,
                    GrupoRelacionado.produto_id == self.produto_id,
                )
            )
        ).first()
        if existe is None:
            raise NaoEncontrado("Grupo relacionado", self.grupo_id)

    async def listar(self) -> list[ItemRelacionado]:
        await self._exigir_grupo()
        stmt = select(ItemRelacionado).where(ItemRelacionado.grupo_id == self.grupo_id)
        return list((await self.session.execute(stmt)).scalars().all())

    async def criar(self, dados: ItemRelacionadoCriar) -> ItemRelacionado:
        await self._exigir_grupo()

        if dados.produto_id == self.produto_id:
            raise RegraDeNegocio(
                "Um produto não pode ser item relacionado do próprio grupo.",
                codigo="item_relacionado_ciclico",
            )

        if dados.variante_id is not None:
            variante_do_produto = (
                await self.session.execute(
                    select(Variante.id).where(
                        Variante.id == dados.variante_id, Variante.produto_id == dados.produto_id
                    )
                )
            ).first()
            if variante_do_produto is None:
                raise RegraDeNegocio(
                    "`variante_id` não pertence ao `produto_id` informado.",
                    codigo="variante_de_outro_produto",
                    campos={"variante_id": str(dados.variante_id)},
                )

        item = ItemRelacionado(
            tenant_id=self.tenant_id,
            grupo_id=self.grupo_id,
            produto_id=dados.produto_id,
            variante_id=dados.variante_id,
            quantidade=dados.quantidade,
            padrao=dados.padrao,
        )
        if self.usuario_id is not None:
            item.criado_por_id = self.usuario_id
        self.session.add(item)
        await self.session.flush()
        return item

    async def remover(self, item_id: uuid.UUID) -> None:
        await self._exigir_grupo()
        item = (
            await self.session.execute(
                select(ItemRelacionado).where(
                    ItemRelacionado.id == item_id, ItemRelacionado.grupo_id == self.grupo_id
                )
            )
        ).scalar_one_or_none()
        if item is None:
            raise NaoEncontrado("Item relacionado", item_id)
        await self.session.delete(item)
        await self.session.flush()
