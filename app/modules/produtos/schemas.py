from __future__ import annotations

import uuid
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, computed_field

from app.common.schemas import SaidaBase


class PrecoSaida(SaidaBase):
    """Preço e estoque da variante naquela empresa.

    `preco_cents` sai como veio: inteiro em centavos. Converter para reais é trabalho da
    borda que **apresenta**, e o front do VITRA já faz isso — devolver `12.34` daqui
    reintroduziria float no caminho, que é justamente o que a convenção proíbe.
    """

    preco_cents: int = Field(description="Centavos. 1234 = R$ 12,34")
    estoque: Decimal
    estoque_minimo: Decimal


class VarianteSaida(SaidaBase):
    id: uuid.UUID
    acabamento: str
    tamanho: str
    ativo: bool
    preco: PrecoSaida | None = None


class ProdutoSaida(SaidaBase):
    id: uuid.UUID
    codigo: str
    descricao: str
    ativo: bool
    variantes: list[VarianteSaida] = Field(default_factory=list)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def preco_minimo_cents(self) -> int | None:
        """Menor preço entre as variantes. `None` quando nenhuma tem preço na empresa.

        `None` e `0` são coisas diferentes: produto sem preço cadastrado versus produto que
        custa zero. Um `or` no lugar deste `is not None` colapsaria os dois casos.
        """
        precos = [v.preco.preco_cents for v in self.variantes if v.preco is not None]
        return min(precos) if precos else None


class ProdutoCriar(BaseModel):
    """Esboço herdado do bake-off — a S2 acrescenta o resto das ~20 colunas do catálogo.

    Repare no que **não** está aqui: `tenant_id`. A empresa vem da transação (RLS,
    `SessaoEmpresa`), nunca do corpo do pedido.
    """

    model_config = ConfigDict(extra="forbid")

    codigo: str = Field(min_length=1, max_length=40)
    descricao: str = Field(min_length=1, max_length=300)
    ativo: bool = True
