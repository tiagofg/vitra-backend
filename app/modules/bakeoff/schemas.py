"""Schemas do bake-off. Campo do banco em inglês; o que a API expõe, em português."""

from __future__ import annotations

import uuid
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, computed_field

from app.common.schemas import SaidaBase


class PrecoSaida(SaidaBase):
    """Preço e estoque da variante naquela empresa.

    `price_cents` sai como veio: inteiro em centavos. Converter para reais é trabalho da
    borda que **apresenta**, e o front do VITRA já faz isso — devolver `12.34` daqui
    reintroduziria float no caminho, que é justamente o que a convenção proíbe.
    """

    preco_cents: int = Field(
        validation_alias="price_cents", description="Centavos. 1234 = R$ 12,34"
    )
    estoque: Decimal = Field(validation_alias="stock_qty")
    estoque_minimo: Decimal = Field(validation_alias="min_stock")


class VarianteSaida(SaidaBase):
    id: uuid.UUID
    acabamento: str = Field(validation_alias="finish")
    tamanho: str = Field(validation_alias="size")
    ativo: bool = Field(validation_alias="active")
    preco: PrecoSaida | None = None


class ProdutoSaida(SaidaBase):
    id: uuid.UUID
    codigo: str = Field(validation_alias="code")
    descricao: str = Field(validation_alias="description")
    ativo: bool = Field(validation_alias="active")
    variantes: list[VarianteSaida] = Field(default_factory=list)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def preco_minimo_cents(self) -> int | None:
        """Menor preço entre as variantes. `None` quando nenhuma tem preço na empresa.

        `None` e `0` são coisas diferentes e o dado do bake-off traz as duas de propósito:
        produto sem preço cadastrado versus produto que custa zero. Um `or` no lugar deste
        `is not None` colapsaria os dois casos — é o bug que os dados existem para pegar.
        """
        precos = [v.preco.preco_cents for v in self.variantes if v.preco is not None]
        return min(precos) if precos else None


class ProdutoCriar(BaseModel):
    """Escrita existe para provar o RLS, não para cobrir o cadastro real (isso é a S2).

    Repare no que **não** está aqui: `tenant_id`. A empresa vem da transação, nunca do
    corpo — aceitá-la seria deixar o cliente escolher em qual empresa escreve.
    """

    model_config = ConfigDict(extra="forbid")

    codigo: str = Field(min_length=1, max_length=40)
    descricao: str = Field(min_length=1, max_length=300)
    ativo: bool = True


class EmpresaSaida(SaidaBase):
    id: uuid.UUID
    nome: str = Field(validation_alias="name")
    cnpj: str | None = None
    ativo: bool = Field(validation_alias="active")


class PapelSaida(SaidaBase):
    """Uma pessoa e o papel dela numa empresa."""

    empresa_id: uuid.UUID = Field(validation_alias="tenant_id")
    colaborador_id: uuid.UUID = Field(validation_alias="employee_id")
    papel: str = Field(validation_alias="role")
