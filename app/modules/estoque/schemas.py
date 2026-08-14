from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.common.schemas import SaidaBase
from app.modules.estoque.models import MotivoMovimento, OrigemMovimento, TipoLocalEstoque

# --- local -----------------------------------------------------------------------


class LocalEstoqueCriar(BaseModel):
    codigo: str = Field(max_length=20)
    nome: str = Field(max_length=120)
    tipo: TipoLocalEstoque = TipoLocalEstoque.deposito


class LocalEstoqueAtualizar(BaseModel):
    codigo: str | None = Field(default=None, max_length=20)
    nome: str | None = Field(default=None, max_length=120)
    tipo: TipoLocalEstoque | None = None


class LocalEstoqueSaida(SaidaBase):
    id: uuid.UUID
    codigo: str
    nome: str
    tipo: TipoLocalEstoque
    ativo: bool


# --- saldo -----------------------------------------------------------------------


class SaldoEstoqueSaida(SaidaBase):
    id: uuid.UUID
    variante_id: uuid.UUID
    local_id: uuid.UUID
    quantidade: Decimal


# --- movimento -------------------------------------------------------------------


class MovimentoCriar(BaseModel):
    """`delta` assinado: positivo entra, negativo sai. Zero é recusado pelo banco
    (`delta_nao_zero`) e não teria sentido no extrato."""

    variante_id: uuid.UUID
    local_id: uuid.UUID
    delta: Decimal
    motivo: MotivoMovimento
    origem_tipo: OrigemMovimento | None = None
    origem_id: uuid.UUID | None = None


class MovimentoSaida(SaidaBase):
    id: uuid.UUID
    variante_id: uuid.UUID
    local_id: uuid.UUID
    delta: Decimal
    motivo: MotivoMovimento
    origem_tipo: OrigemMovimento | None
    origem_id: uuid.UUID | None
    saldo_apos: Decimal
    ocorrido_em: datetime
    employee_id: uuid.UUID | None


class TransferenciaCriar(BaseModel):
    """Transferência entre locais — o que o diagrama não representa (`stock_movements` não
    tem local de destino). Vira **duas** linhas no extrato, saída e entrada, com o mesmo
    `motivo=transferencia`: é assim que o saldo de cada local fecha sozinho, sem que uma
    consulta de saldo precise entender o conceito de transferência."""

    variante_id: uuid.UUID
    local_origem_id: uuid.UUID
    local_destino_id: uuid.UUID
    quantidade: Decimal = Field(gt=0)


class TransferenciaSaida(SaidaBase):
    saida: MovimentoSaida
    entrada: MovimentoSaida
