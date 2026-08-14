"""Serviços de estoque.

Nenhum filtro por empresa em nenhum `select()` daqui — é o RLS que recorta, como em todo o
resto do projeto. O que este módulo tem de próprio é `EstoqueService.movimentar`: a única
porta de escrita do saldo.

**Ninguém escreve `stock_balances` direto.** Saldo e extrato só são consistentes se forem
escritos juntos, e `movimentar()` é o lugar onde isso acontece — sob o mesmo
`SELECT ... FOR UPDATE` que serializa duas saídas concorrentes da mesma variante. Um
serviço que atualizasse o saldo sem lançar o movimento deixaria o extrato mentindo; um que
lançasse o movimento sem travar o saldo deixaria duas saídas de 8 unidades passarem sobre
um saldo de 12.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.base_service import BaseService
from app.core.errors import NaoEncontrado, RegraDeNegocio
from app.core.listing import ListingSpec, ListParams, Pagina, aplicar_listagem, paginar
from app.modules.estoque.models import (
    LocalEstoque,
    MotivoMovimento,
    MovimentoEstoque,
    OrigemMovimento,
    SaldoEstoque,
)
from app.modules.estoque.schemas import (
    LocalEstoqueAtualizar,
    LocalEstoqueCriar,
    MovimentoCriar,
    TransferenciaCriar,
)
from app.modules.produtos.models import Variante


class LocalEstoqueService(BaseService[LocalEstoque, LocalEstoqueCriar, LocalEstoqueAtualizar]):
    nome_recurso = "Local de estoque"
    spec = ListingSpec(
        model=LocalEstoque,
        campos_busca=("codigo", "nome"),
        campo_codigo="codigo",
        campos_ordenacao=("codigo", "nome", "criado_em"),
        ordenacao_padrao="codigo",
        campo_unico="codigo",
    )

    def _label_lookup(self, obj: LocalEstoque) -> str:
        return obj.nome

    def _extras_lookup(self, obj: LocalEstoque) -> dict[str, Any]:
        return {"tipo": obj.tipo.value}

    async def _antes_de_desativar(self, obj: LocalEstoque) -> None:
        """Local com saldo não some do mapa. Desativar um local que ainda guarda mercadoria
        esconderia o saldo da listagem sem zerá-lo — o inventário deixaria de bater sem
        nenhum movimento ter acontecido. Esvazie (ou transfira) antes."""
        saldo = (
            await self.session.execute(
                select(SaldoEstoque.id).where(
                    SaldoEstoque.local_id == obj.id, SaldoEstoque.quantidade != 0
                )
            )
        ).first()
        if saldo is not None:
            raise RegraDeNegocio(
                "Local de estoque ainda tem saldo. Transfira ou zere antes de desativar.",
                codigo="local_com_saldo",
                campos={"local_id": str(obj.id)},
            )


class EstoqueService:
    """Saldo e extrato. Não herda `BaseService`: movimento não tem `PUT` nem `DELETE` —
    corrigir um lançamento errado é lançar o inverso, como em qualquer razão contábil."""

    nome_recurso = "Movimento de estoque"

    spec_movimentos = ListingSpec(
        model=MovimentoEstoque,
        campos_ordenacao=("ocorrido_em", "criado_em"),
        ordenacao_padrao="ocorrido_em",
    )
    spec_saldos = ListingSpec(
        model=SaldoEstoque,
        campos_ordenacao=("quantidade", "criado_em"),
        ordenacao_padrao="criado_em",
    )

    def __init__(
        self,
        session: AsyncSession,
        usuario_id: uuid.UUID | None = None,
        tenant_id: uuid.UUID | None = None,
    ) -> None:
        self.session = session
        self.usuario_id = usuario_id
        self.tenant_id = tenant_id

    async def _exigir_variante(self, variante_id: uuid.UUID) -> None:
        existe = (
            await self.session.execute(select(Variante.id).where(Variante.id == variante_id))
        ).first()
        if existe is None:
            raise NaoEncontrado("Variante", variante_id)

    async def _exigir_local(self, local_id: uuid.UUID) -> LocalEstoque:
        local = (
            await self.session.execute(select(LocalEstoque).where(LocalEstoque.id == local_id))
        ).scalar_one_or_none()
        if local is None:
            raise NaoEncontrado("Local de estoque", local_id)
        if not local.ativo:
            raise RegraDeNegocio(
                "Local de estoque está desativado.",
                codigo="local_desativado",
                campos={"local_id": str(local_id)},
            )
        return local

    async def _saldo_travado(self, variante_id: uuid.UUID, local_id: uuid.UUID) -> SaldoEstoque:
        """A linha de saldo, criada se ainda não existir, e **travada** até o fim da
        transação.

        `ON CONFLICT DO NOTHING` antes do `FOR UPDATE`, e não um `SELECT` seguido de
        `INSERT` se vier vazio: duas transações que movimentam pela primeira vez a mesma
        variante no mesmo local veriam as duas o vazio e as duas tentariam inserir — a
        segunda tomaria violação de `uq_stock_balances_variante_local`. Com o `INSERT`
        idempotente primeiro, a linha existe com certeza quando o `FOR UPDATE` chega, e é
        ele que serializa as duas dali em diante.
        """
        if self.tenant_id is None:
            # Falha fechado: sem empresa não há linha de saldo a criar, e inserir com
            # `tenant_id` nulo estouraria no banco com um erro que não explica nada.
            raise RegraDeNegocio(
                "Não é possível movimentar estoque sem uma empresa ativa.",
                codigo="empresa_nao_declarada_para_estoque",
            )

        await self.session.execute(
            pg_insert(SaldoEstoque)
            .values(
                tenant_id=self.tenant_id,
                id=uuid.uuid4(),
                variante_id=variante_id,
                local_id=local_id,
                quantidade=Decimal("0"),
                criado_por_id=self.usuario_id,
            )
            .on_conflict_do_nothing(constraint="uq_stock_balances_variante_local")
        )
        saldo = (
            await self.session.execute(
                select(SaldoEstoque)
                .where(
                    SaldoEstoque.variante_id == variante_id,
                    SaldoEstoque.local_id == local_id,
                )
                .with_for_update()
            )
        ).scalar_one()
        return saldo

    async def movimentar(self, dados: MovimentoCriar) -> MovimentoEstoque:
        await self._exigir_variante(dados.variante_id)
        await self._exigir_local(dados.local_id)

        saldo = await self._saldo_travado(dados.variante_id, dados.local_id)
        novo = saldo.quantidade + dados.delta
        if novo < 0:
            # Mensagem de negócio antes do CHECK do banco: o `qty_nao_negativo` também
            # pegaria, mas devolveria um 409 genérico de integridade em vez de dizer quanto
            # tem e quanto foi pedido.
            raise RegraDeNegocio(
                f"Estoque insuficiente: saldo {saldo.quantidade}, movimento {dados.delta}.",
                codigo="estoque_insuficiente",
                campos={
                    "saldo": str(saldo.quantidade),
                    "delta": str(dados.delta),
                },
            )

        saldo.quantidade = novo
        movimento = MovimentoEstoque(
            tenant_id=self.tenant_id,
            variante_id=dados.variante_id,
            local_id=dados.local_id,
            delta=dados.delta,
            motivo=dados.motivo,
            origem_tipo=dados.origem_tipo,
            origem_id=dados.origem_id,
            saldo_apos=novo,
            employee_id=self.usuario_id,
        )
        if self.usuario_id is not None:
            movimento.criado_por_id = self.usuario_id
        self.session.add(movimento)
        await self.session.flush()
        return movimento

    async def transferir(
        self, dados: TransferenciaCriar
    ) -> tuple[MovimentoEstoque, MovimentoEstoque]:
        """Duas linhas no extrato, saída e entrada. Os dois locais são travados na mesma
        transação — se a entrada falhar, a saída volta atrás junto."""
        if dados.local_origem_id == dados.local_destino_id:
            raise RegraDeNegocio(
                "Origem e destino da transferência são o mesmo local.",
                codigo="transferencia_mesmo_local",
                campos={"local_destino_id": str(dados.local_destino_id)},
            )

        saida = await self.movimentar(
            MovimentoCriar(
                variante_id=dados.variante_id,
                local_id=dados.local_origem_id,
                delta=-dados.quantidade,
                motivo=MotivoMovimento.transferencia,
                origem_tipo=OrigemMovimento.ajuste_manual,
            )
        )
        entrada = await self.movimentar(
            MovimentoCriar(
                variante_id=dados.variante_id,
                local_id=dados.local_destino_id,
                delta=dados.quantidade,
                motivo=MotivoMovimento.transferencia,
                origem_tipo=OrigemMovimento.ajuste_manual,
                # Encadeia as duas pontas: dado o movimento de entrada, o de saída é
                # alcançável. Sem isto as duas linhas ficariam órfãs uma da outra no extrato.
                origem_id=saida.id,
            )
        )
        return saida, entrada

    async def saldos(self, params: ListParams, serializar: Any) -> Pagina[Any]:
        stmt = aplicar_listagem(select(SaldoEstoque), params, self.spec_saldos)
        return await paginar(self.session, stmt, params, serializar)

    async def saldos_da_variante(self, variante_id: uuid.UUID) -> list[SaldoEstoque]:
        await self._exigir_variante(variante_id)
        stmt = select(SaldoEstoque).where(SaldoEstoque.variante_id == variante_id)
        return list((await self.session.execute(stmt)).scalars().all())

    async def extrato(
        self,
        params: ListParams,
        serializar: Any,
        *,
        variante_id: uuid.UUID | None = None,
        local_id: uuid.UUID | None = None,
    ) -> Pagina[Any]:
        stmt = select(MovimentoEstoque)
        if variante_id is not None:
            stmt = stmt.where(MovimentoEstoque.variante_id == variante_id)
        if local_id is not None:
            stmt = stmt.where(MovimentoEstoque.local_id == local_id)
        stmt = aplicar_listagem(stmt, params, self.spec_movimentos)
        return await paginar(self.session, stmt, params, serializar)
