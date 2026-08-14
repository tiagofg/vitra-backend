from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field, model_validator

from app.common.schemas import SaidaBase
from app.modules.vendas.models import ModoDesconto, StatusOrcamento

# --- ambiente ---------------------------------------------------------------------


class AmbienteEntrada(BaseModel):
    """Item da GRADE de ambientes. `id` ausente = linha nova; presente = linha existente.
    O que ficar de fora do `PUT` é removido — ver `substituir_conjunto`."""

    id: uuid.UUID | None = None
    codigo: str = Field(min_length=1, max_length=20)
    nome: str = Field(min_length=1, max_length=120)


class AmbienteSaida(SaidaBase):
    id: uuid.UUID
    codigo: str
    nome: str
    ordem: int


# --- item -------------------------------------------------------------------------


class ItemEntrada(BaseModel):
    """Item da GRADE do orçamento.

    `produto_id`/`variante_id` nulos = **pré-produto**: item orçado só pela descrição,
    ainda sem cadastro no catálogo. É caso corrente na tela do legado, e é a razão de
    `descricao` ser obrigatória enquanto as duas FKs não são.
    """

    id: uuid.UUID | None = None
    ambiente_id: uuid.UUID | None = None
    produto_id: uuid.UUID | None = None
    variante_id: uuid.UUID | None = None
    descricao: str = Field(min_length=1)
    acabamento: str | None = Field(default=None, max_length=60)
    tamanho: str | None = Field(default=None, max_length=60)
    unidade: str | None = Field(default=None, max_length=20)
    fornecedor_id: uuid.UUID | None = None
    fornecedor_nome: str | None = Field(default=None, max_length=160)
    fornecedor_codigo: str | None = Field(default=None, max_length=60)
    grupo_produto: str | None = Field(default=None, max_length=60)
    tipo_peca: str | None = Field(default=None, max_length=60)
    quantidade: Decimal = Field(gt=0)
    preco_unitario_cents: int = Field(ge=0)
    desconto_pct: Decimal = Field(default=Decimal("0"), ge=0, le=100)

    @model_validator(mode="after")
    def _variante_exige_produto(self) -> ItemEntrada:
        # Espelha o CHECK `quote_items_variante_exige_produto` na borda: variante sem
        # produto é estado incoerente, e o 422 com o campo apontado é mais útil que o 409
        # genérico de integridade.
        if self.variante_id is not None and self.produto_id is None:
            raise ValueError("Item com variante precisa informar o produto.")
        return self


class ItemSaida(SaidaBase):
    id: uuid.UUID
    linha: int
    ambiente_id: uuid.UUID | None = None
    produto_id: uuid.UUID | None = None
    variante_id: uuid.UUID | None = None
    descricao: str
    acabamento: str | None = None
    tamanho: str | None = None
    unidade: str | None = None
    fornecedor_id: uuid.UUID | None = None
    fornecedor_nome: str | None = None
    fornecedor_codigo: str | None = None
    grupo_produto: str | None = None
    tipo_peca: str | None = None
    quantidade: Decimal
    preco_unitario_cents: int
    desconto_pct: Decimal
    total_cents: int


# --- orçamento --------------------------------------------------------------------


class OrcamentoCriar(BaseModel):
    """Sem `numero`: quem gera é `app.core.numbering.proximo_numero`, por empresa e série.
    Deixar o cliente escolher reabriria o buraco que a numeração sem buracos existe para
    fechar."""

    serie: str = Field(default="1", max_length=3)
    cliente_id: uuid.UUID
    obra_id: uuid.UUID | None = None
    profissional_id: uuid.UUID | None = None
    vendedor_id: uuid.UUID | None = None
    filial_id: uuid.UUID | None = None
    centro_custo_id: uuid.UUID | None = None
    origem_id: uuid.UUID | None = None
    nome_projeto: str | None = Field(default=None, max_length=160)
    numero_pasta: str | None = Field(default=None, max_length=30)
    categoria_id: uuid.UUID | None = None
    emitido_em: date | None = None
    expira_em: date | None = None
    modo_desconto: ModoDesconto = ModoDesconto.percentual
    desconto_valor: Decimal = Field(default=Decimal("0"), ge=0)
    observacao: str | None = Field(default=None, max_length=2000)

    ambientes: list[AmbienteEntrada] = Field(default_factory=list)
    itens: list[ItemEntrada] = Field(default_factory=list)


class OrcamentoAtualizar(BaseModel):
    cliente_id: uuid.UUID | None = None
    obra_id: uuid.UUID | None = None
    profissional_id: uuid.UUID | None = None
    vendedor_id: uuid.UUID | None = None
    filial_id: uuid.UUID | None = None
    centro_custo_id: uuid.UUID | None = None
    nome_projeto: str | None = Field(default=None, max_length=160)
    numero_pasta: str | None = Field(default=None, max_length=30)
    categoria_id: uuid.UUID | None = None
    emitido_em: date | None = None
    expira_em: date | None = None
    modo_desconto: ModoDesconto | None = None
    desconto_valor: Decimal | None = Field(default=None, ge=0)
    observacao: str | None = Field(default=None, max_length=2000)

    ambientes: list[AmbienteEntrada] | None = None
    itens: list[ItemEntrada] | None = None


class OrcamentoSaida(SaidaBase):
    id: uuid.UUID
    tenant_id: uuid.UUID
    numero: int
    serie: str
    status: StatusOrcamento
    cliente_id: uuid.UUID
    obra_id: uuid.UUID | None = None
    profissional_id: uuid.UUID | None = None
    vendedor_id: uuid.UUID | None = None
    filial_id: uuid.UUID | None = None
    centro_custo_id: uuid.UUID | None = None
    origem_id: uuid.UUID | None = None
    nome_projeto: str | None = None
    numero_pasta: str | None = None
    categoria_id: uuid.UUID | None = None
    emitido_em: date | None = None
    expira_em: date | None = None
    fechado_em: date | None = None
    modo_desconto: ModoDesconto
    desconto_valor: Decimal
    total_cents: int
    observacao: str | None = None
    ambientes: list[AmbienteSaida] = Field(default_factory=list)
    itens: list[ItemSaida] = Field(default_factory=list)


class CancelarOrcamento(BaseModel):
    """`Excluir` da tela do legado é isto: o documento muda de estado e continua na
    listagem. O motivo é obrigatório — cancelamento sem justificativa é o que impede
    reconstituir o que aconteceu depois."""

    motivo: str = Field(min_length=3, max_length=300)
