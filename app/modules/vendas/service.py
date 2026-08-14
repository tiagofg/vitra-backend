"""Serviço de orçamento.

Nenhum filtro por empresa em nenhum `select()` — é o RLS que recorta. O que este serviço
acrescenta ao `BaseService`:

* **Numeração.** `numero` nunca vem do corpo: sai de `proximo_numero()`, por empresa e
  série, sem buracos.
* **Total calculado, nunca recebido.** `total_cents` do item e do documento são derivados de
  quantidade × preço × descontos, aqui. Aceitar o total do cliente seria aceitar que ele
  informe um valor que não fecha com as linhas.
* **Máquina de estados.** `rascunho → aberto → fechado`, com `cancelado` alcançável de
  qualquer um dos três. Fechado e cancelado não aceitam mais edição — é o que faz o
  documento assinado parar de mudar.
* **Grades por replace-set.** Ambientes e itens usam `substituir_conjunto`, o mesmo diff por
  PK que produtos usa — apagar tudo e reinserir perderia o `id` das linhas, e com ele
  qualquer movimento de estoque que aponte para o item.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.orm import selectinload

from app.common.base_service import BaseService
from app.common.child_set import substituir_conjunto
from app.core.errors import NaoEncontrado, RegraDeNegocio
from app.core.listing import ListingSpec
from app.core.numbering import TipoDocumento, proximo_numero
from app.modules.pessoas.models import Parceiro
from app.modules.vendas.models import (
    ModoDesconto,
    Orcamento,
    OrcamentoAmbiente,
    OrcamentoItem,
    StatusOrcamento,
)
from app.modules.vendas.schemas import (
    CancelarOrcamento,
    OrcamentoAtualizar,
    OrcamentoCriar,
)

#: Estados em que o documento ainda aceita edição. Fechado e cancelado saem da lista de
#: propósito: um orçamento fechado virou compromisso, e um cancelado é registro histórico.
EDITAVEIS = frozenset({StatusOrcamento.rascunho, StatusOrcamento.aberto})

CENTAVO = Decimal("1")


class OrcamentoService(BaseService[Orcamento, OrcamentoCriar, OrcamentoAtualizar]):
    nome_recurso = "Orçamento"
    spec = ListingSpec(
        model=Orcamento,
        campos_busca=("nome_projeto", "numero_pasta"),
        campos_ordenacao=("numero", "emitido_em", "total_cents", "criado_em"),
        ordenacao_padrao="numero",
    )
    campos_relacao = frozenset({"ambientes", "itens"})
    colecoes_novas = ("ambientes", "itens")

    def _stmt_base(self) -> Select[Any]:
        # `selectinload` nas duas grades: `OrcamentoSaida` sempre serializa ambientes e
        # itens, então o lazy load aconteceria de qualquer jeito — e num contexto async
        # estouraria `MissingGreenlet`. `selectin` e não `joined` porque são duas coleções:
        # com `joined` o produto cartesiano entre elas multiplicaria as linhas e quebraria
        # a paginação.
        return select(Orcamento).options(
            selectinload(Orcamento.ambientes), selectinload(Orcamento.itens)
        )

    # --- criação e numeração ------------------------------------------------------

    async def _preparar_valores(self, dados: OrcamentoCriar) -> dict[str, Any]:
        valores = await super()._preparar_valores(dados)
        if self.tenant_id is None:
            raise RegraDeNegocio(
                "Não é possível numerar um orçamento sem uma empresa ativa.",
                codigo="empresa_nao_declarada_para_orcamento",
            )
        serie = valores.get("serie", "1")
        valores["numero"] = await proximo_numero(
            self.session,
            tenant_id=self.tenant_id,
            tipo=TipoDocumento.orcamento,
            serie=serie,
        )
        valores["status"] = StatusOrcamento.rascunho
        return valores

    async def _antes_de_criar(self, valores: dict[str, Any]) -> None:
        await super()._antes_de_criar(valores)
        await self._exigir_cliente(valores["cliente_id"])
        if valores.get("profissional_id") is not None:
            await self._exigir_profissional(valores["profissional_id"])

    async def _antes_de_atualizar(self, obj: Orcamento, valores: dict[str, Any]) -> None:
        await super()._antes_de_atualizar(obj, valores)
        self._exigir_editavel(obj)
        if "cliente_id" in valores:
            await self._exigir_cliente(valores["cliente_id"])
        if valores.get("profissional_id") is not None:
            await self._exigir_profissional(valores["profissional_id"])

    def _exigir_editavel(self, obj: Orcamento) -> None:
        if obj.status not in EDITAVEIS:
            raise RegraDeNegocio(
                f"Orçamento {obj.status.value} não aceita mais edição.",
                codigo="orcamento_nao_editavel",
                campos={"status": obj.status.value},
            )

    async def _exigir_cliente(self, parceiro_id: uuid.UUID) -> None:
        """A FK composta já garante que o parceiro é desta empresa. O que ela **não**
        garante é o papel: sem esta checagem, um fornecedor entraria como cliente do
        orçamento, porque para o banco os dois são a mesma tabela. É o preço da unificação
        em `partners`, e é este o lugar de pagá-lo."""
        parceiro = (
            await self.session.execute(select(Parceiro).where(Parceiro.id == parceiro_id))
        ).scalar_one_or_none()
        if parceiro is None:
            raise NaoEncontrado("Parceiro", parceiro_id)
        if not parceiro.e_cliente:
            raise RegraDeNegocio(
                "Parceiro não está marcado como cliente.",
                codigo="parceiro_nao_e_cliente",
                campos={"cliente_id": str(parceiro_id)},
            )

    async def _exigir_profissional(self, parceiro_id: uuid.UUID) -> None:
        parceiro = (
            await self.session.execute(select(Parceiro).where(Parceiro.id == parceiro_id))
        ).scalar_one_or_none()
        if parceiro is None:
            raise NaoEncontrado("Parceiro", parceiro_id)
        if not parceiro.e_profissional:
            raise RegraDeNegocio(
                "Parceiro não está marcado como profissional.",
                codigo="parceiro_nao_e_profissional",
                campos={"profissional_id": str(parceiro_id)},
            )

    # --- grades -------------------------------------------------------------------

    async def _resolver_relacoes(
        self, obj: Orcamento, dados: OrcamentoCriar | OrcamentoAtualizar
    ) -> None:
        enviados = dados.model_dump(exclude_unset=True)
        fixos = {"tenant_id": obj.tenant_id, "orcamento_id": obj.id}

        if "ambientes" in enviados and enviados["ambientes"] is not None:
            await substituir_conjunto(
                self.session,
                model=OrcamentoAmbiente,
                existentes=obj.ambientes,
                entrada=dados.ambientes or [],
                fixos=fixos,
                usuario_id=self.usuario_id,
                campo_ordem="ordem",
            )

        if "itens" in enviados and enviados["itens"] is not None:
            itens = dados.itens or []
            # `total_cents` de cada item é calculado aqui, não recebido: o schema de entrada
            # nem tem o campo. `substituir_conjunto` copia o que veio do schema, então o
            # total precisa ser injetado antes — via `model_copy`, para não mutar a entrada
            # que o chamador ainda pode estar usando.
            preparados = [
                item.model_copy(update={"total_cents": self._total_do_item(item)}) for item in itens
            ]
            await substituir_conjunto(
                self.session,
                model=OrcamentoItem,
                existentes=obj.itens,
                entrada=preparados,
                fixos=fixos,
                usuario_id=self.usuario_id,
                campo_ordem="linha",
            )

        await self.session.flush()
        await self._recalcular_total(obj)

    @staticmethod
    def _total_do_item(item: Any) -> int:
        """quantidade × preço unitário, menos o desconto do item. Arredonda meio para cima
        no centavo — dinheiro é inteiro, e `ROUND_HALF_EVEN` (o padrão do `Decimal`) daria
        um centavo a menos em metade dos casos de empate, o que o financeiro cobra depois."""
        bruto = Decimal(item.quantidade) * Decimal(item.preco_unitario_cents)
        liquido = bruto * (Decimal("1") - Decimal(item.desconto_pct) / Decimal("100"))
        return int(liquido.quantize(CENTAVO, rounding=ROUND_HALF_UP))

    async def _recalcular_total(self, obj: Orcamento) -> None:
        """Soma dos itens, menos o desconto do documento. Roda depois de toda escrita nas
        grades — o total nunca é escrito por fora.

        `SUM` no banco, e não `sum(obj.itens)`: `substituir_conjunto` acabou de inserir e
        remover linhas pela sessão, sem tocar na coleção já carregada em `obj.itens` — somar
        a coleção daria o total **anterior** à edição, calado e errado.
        """
        soma = (
            await self.session.execute(
                select(func.coalesce(func.sum(OrcamentoItem.total_cents), 0)).where(
                    OrcamentoItem.orcamento_id == obj.id
                )
            )
        ).scalar_one()
        if obj.modo_desconto == ModoDesconto.percentual:
            desconto = Decimal(soma) * (obj.desconto_valor / Decimal("100"))
        else:
            desconto = obj.desconto_valor
        total = Decimal(soma) - desconto
        # O desconto do documento não pode virar total negativo — o CHECK do banco pegaria,
        # mas com uma mensagem que não diz qual desconto estourou.
        if total < 0:
            raise RegraDeNegocio(
                "Desconto do documento é maior que a soma dos itens.",
                codigo="desconto_maior_que_total",
                campos={"desconto_valor": str(obj.desconto_valor)},
            )
        obj.total_cents = int(total.quantize(CENTAVO, rounding=ROUND_HALF_UP))
        await self.session.flush()

    # --- transições de estado -----------------------------------------------------

    async def abrir(self, id_: uuid.UUID) -> Orcamento:
        """Rascunho vira aberto — é o que o legado chama de "emitir": a partir daqui o
        documento tem número visível ao cliente e data de emissão."""
        obj = await self.obter(id_)
        if obj.status != StatusOrcamento.rascunho:
            raise RegraDeNegocio(
                f"Só rascunho pode ser aberto; este está {obj.status.value}.",
                codigo="transicao_invalida",
                campos={"status": obj.status.value},
            )
        if not obj.itens:
            raise RegraDeNegocio(
                "Orçamento sem itens não pode ser aberto.",
                codigo="orcamento_sem_itens",
            )
        obj.status = StatusOrcamento.aberto
        obj.emitido_em = obj.emitido_em or date.today()
        await self.session.flush()
        return obj

    async def fechar(self, id_: uuid.UUID) -> Orcamento:
        obj = await self.obter(id_)
        if obj.status != StatusOrcamento.aberto:
            raise RegraDeNegocio(
                f"Só orçamento aberto pode ser fechado; este está {obj.status.value}.",
                codigo="transicao_invalida",
                campos={"status": obj.status.value},
            )
        obj.status = StatusOrcamento.fechado
        obj.fechado_em = date.today()
        await self.session.flush()
        return obj

    async def cancelar(self, id_: uuid.UUID, dados: CancelarOrcamento) -> Orcamento:
        """Não apaga. O `Excluir` da tela do legado é isto — o documento sai do fluxo mas
        continua na listagem, com o motivo registrado."""
        obj = await self.obter(id_)
        if obj.status == StatusOrcamento.cancelado:
            raise RegraDeNegocio(
                "Orçamento já está cancelado.",
                codigo="transicao_invalida",
                campos={"status": obj.status.value},
            )
        obj.status = StatusOrcamento.cancelado
        obj.fechado_em = date.today()
        obj.observacao = (
            f"{obj.observacao}\n[cancelado] {dados.motivo}"
            if obj.observacao
            else f"[cancelado] {dados.motivo}"
        )
        await self.session.flush()
        return obj

    async def revisar(self, id_: uuid.UUID) -> Orcamento:
        """Copia o orçamento para um novo, encadeado por `origem_id`.

        Dois orçamentos do mesmo cliente no mesmo dia (21638/21639) são caso real do legado:
        é revisão, não duplicata. Sem `origem_id` os dois ficariam soltos, e ninguém
        conseguiria dizer depois qual substituiu qual.
        """
        origem = await self.obter(id_)
        if self.tenant_id is None:
            raise RegraDeNegocio(
                "Não é possível numerar a revisão sem uma empresa ativa.",
                codigo="empresa_nao_declarada_para_orcamento",
            )

        nova = Orcamento(
            tenant_id=origem.tenant_id,
            numero=await proximo_numero(
                self.session,
                tenant_id=self.tenant_id,
                tipo=TipoDocumento.orcamento,
                serie=origem.serie,
            ),
            serie=origem.serie,
            status=StatusOrcamento.rascunho,
            cliente_id=origem.cliente_id,
            obra_id=origem.obra_id,
            profissional_id=origem.profissional_id,
            vendedor_id=origem.vendedor_id,
            filial_id=origem.filial_id,
            centro_custo_id=origem.centro_custo_id,
            origem_id=origem.id,
            nome_projeto=origem.nome_projeto,
            numero_pasta=origem.numero_pasta,
            categoria_id=origem.categoria_id,
            modo_desconto=origem.modo_desconto,
            desconto_valor=origem.desconto_valor,
            total_cents=origem.total_cents,
            observacao=origem.observacao,
        )
        nova.ambientes = []
        nova.itens = []
        if self.usuario_id is not None:
            nova.criado_por_id = self.usuario_id
        self.session.add(nova)
        await self.session.flush()

        # `id` novo para cada linha copiada — não reaproveita o da origem, que continua
        # existindo. O mapa liga o ambiente antigo ao novo para os itens apontarem certo.
        de_para: dict[uuid.UUID, uuid.UUID] = {}
        for ambiente in origem.ambientes:
            copia = OrcamentoAmbiente(
                tenant_id=nova.tenant_id,
                orcamento_id=nova.id,
                codigo=ambiente.codigo,
                nome=ambiente.nome,
                ordem=ambiente.ordem,
                criado_por_id=self.usuario_id,
            )
            self.session.add(copia)
            await self.session.flush()
            de_para[ambiente.id] = copia.id

        for item in origem.itens:
            self.session.add(
                OrcamentoItem(
                    tenant_id=nova.tenant_id,
                    orcamento_id=nova.id,
                    linha=item.linha,
                    ambiente_id=de_para.get(item.ambiente_id) if item.ambiente_id else None,
                    produto_id=item.produto_id,
                    variante_id=item.variante_id,
                    descricao=item.descricao,
                    acabamento=item.acabamento,
                    tamanho=item.tamanho,
                    unidade=item.unidade,
                    fornecedor_id=item.fornecedor_id,
                    fornecedor_nome=item.fornecedor_nome,
                    fornecedor_codigo=item.fornecedor_codigo,
                    grupo_produto=item.grupo_produto,
                    tipo_peca=item.tipo_peca,
                    quantidade=item.quantidade,
                    preco_unitario_cents=item.preco_unitario_cents,
                    desconto_pct=item.desconto_pct,
                    total_cents=item.total_cents,
                    criado_por_id=self.usuario_id,
                )
            )
        await self.session.flush()
        return await self.obter(nova.id)
