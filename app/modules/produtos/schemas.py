from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, computed_field

from app.common.schemas import SaidaBase

# --- Especificação (aba "Outros Dados") ------------------------------------------


class EspecificacaoLuminaria(BaseModel):
    """Os campos luminotécnicos da aba 2 — especificação de catálogo, não regra de
    negócio. `extra="forbid"`: um nome de campo digitado errado deve estourar 422 na hora,
    não virar uma chave morta dentro do JSONB que ninguém mais lê.

    Numérico aqui é `float`, não `Decimal` — ao contrário de dinheiro (`BIGINT` em
    centavos) e quantidade de estoque (`Numeric`), watts/mm/kg de uma especificação de
    catálogo não têm o mesmo requisito de precisão exata, e `Decimal` dentro de um `dict`
    quebra a serialização padrão do driver para `JSONB` (`Decimal` não é serializável por
    `json.dumps` sem um encoder à parte). `float` é o tipo nativo do JSON para número.
    """

    model_config = ConfigDict(extra="forbid")

    potencia_watts: float | None = None
    tensao: str | None = Field(default=None, max_length=20, description='"127V", "Bivolt"…')
    fluxo_luminoso_lumens: int | None = None
    angulo_abertura_graus: int | None = Field(default=None, ge=0, le=360)
    temperatura_cor_kelvin: int | None = None
    ip: str | None = Field(default=None, max_length=6, description='Grau de proteção, "IP65"')
    base_soquete: str | None = Field(default=None, max_length=20, description='"E27", "GU10"…')
    classe_eletrica: str | None = Field(default=None, max_length=10)
    regulavel: bool | None = Field(default=None, description="Aceita dimmer")
    vida_util_horas: int | None = None
    comprimento_mm: float | None = None
    largura_mm: float | None = None
    altura_mm: float | None = None
    peso_kg: float | None = None


# --- Variante ---------------------------------------------------------------------


class VarianteItem(BaseModel):
    """Item da grade de variantes no `PUT /produtos/{id}`. Sem `id` = variante nova; com
    `id` = variante existente (`substituir_conjunto` faz o diff por PK)."""

    id: uuid.UUID | None = None
    acabamento_id: uuid.UUID
    tamanho_id: uuid.UUID
    ativo: bool = True


class PrecoSaida(SaidaBase):
    """Configuração da variante naquela empresa — preço de venda e ponto de reposição.

    `preco_cents` sai como veio: inteiro em centavos. Converter para reais é trabalho da
    borda que **apresenta**, e o front do VITRA já faz isso — devolver `12.34` daqui
    reintroduziria float no caminho, que é justamente o que a convenção proíbe.

    **Sem `estoque`.** O saldo deixou de ser uma coluna da variante e virou
    `stock_balances`, por variante **e local** — um número só aqui não teria como dizer se
    as 12 unidades estão no depósito ou na loja. Quem quer saldo consulta
    `GET /estoque/saldos/{variante_id}`.
    """

    preco_cents: int = Field(description="Centavos. 1234 = R$ 12,34")
    estoque_minimo: Decimal
    indice: Decimal | None = None
    tipo_valor: str | None = None


class VarianteSaida(SaidaBase):
    id: uuid.UUID
    acabamento_id: uuid.UUID
    tamanho_id: uuid.UUID
    ativo: bool
    preco: PrecoSaida | None = None


# --- Fornecedor do produto ---------------------------------------------------------


class ProdutoFornecedorItem(BaseModel):
    """Item da grade de fornecedores no `PUT /produtos/{id}`."""

    id: uuid.UUID | None = None
    fornecedor_id: uuid.UUID
    codigo_fornecedor: str | None = Field(default=None, max_length=60)
    descricao_fornecedor: str | None = Field(default=None, max_length=300)
    padrao: bool = False


class ProdutoFornecedorSaida(SaidaBase):
    id: uuid.UUID
    fornecedor_id: uuid.UUID
    codigo_fornecedor: str | None = None
    descricao_fornecedor: str | None = None
    padrao: bool


# --- Grupo relacionado --------------------------------------------------------------


class GrupoRelacionadoItem(BaseModel):
    """Item da grade de grupos relacionados no `PUT /produtos/{id}`. Só o grupo em si —
    os itens do grupo (`ItemRelacionado`) têm rota própria, escopada por grupo."""

    id: uuid.UUID | None = None
    nome: str = Field(min_length=1, max_length=120)
    padrao: bool = False
    ativo: bool = True


class GrupoRelacionadoSaida(SaidaBase):
    id: uuid.UUID
    nome: str
    padrao: bool
    ativo: bool


class ItemRelacionadoCriar(BaseModel):
    """`quantidade` preenchida = kit; nula = sugestão de venda cruzada."""

    produto_id: uuid.UUID
    variante_id: uuid.UUID | None = None
    quantidade: Decimal | None = Field(default=None, gt=0)
    padrao: bool = False


class ItemRelacionadoSaida(SaidaBase):
    id: uuid.UUID
    grupo_id: uuid.UUID
    produto_id: uuid.UUID
    variante_id: uuid.UUID | None = None
    quantidade: Decimal | None = None
    padrao: bool


# --- Produto ------------------------------------------------------------------------


class _ProdutoCamposComuns(BaseModel):
    codigo_especial: str | None = Field(default=None, max_length=40)
    codigo_reduzido: str | None = Field(default=None, max_length=20)
    descricao_complementar: str | None = Field(default=None, max_length=500)
    dt_vigencia: date | None = None

    tipo_produto_id: uuid.UUID | None = None
    tipo_peca_id: uuid.UUID | None = None
    tipo_linha_id: uuid.UUID | None = None
    classificacao_id: uuid.UUID | None = None
    designer_modelo_id: uuid.UUID | None = None
    fabrica_id: uuid.UUID | None = None
    marca_id: uuid.UUID | None = None
    unidade_entrada_id: uuid.UUID | None = None
    unidade_saida_id: uuid.UUID | None = None
    qtd_entrada: Decimal = Field(default=Decimal(1), gt=0)
    qtd_saida: Decimal = Field(default=Decimal(1), gt=0)

    empresa_compradora_id: uuid.UUID | None = None

    fora_de_linha: bool = False
    consultar_valor: bool = False
    sobre_medida: bool = False
    publicar_no_site: bool = False

    ncm: str | None = Field(default=None, max_length=8)
    cest: str | None = Field(default=None, max_length=7)
    origem: str | None = Field(default=None, max_length=1)

    especificacao: EspecificacaoLuminaria = Field(default_factory=EspecificacaoLuminaria)


class ProdutoCriar(_ProdutoCamposComuns):
    """Repare no que **não** está aqui: `tenant_id`. A empresa vem da transação (RLS,
    `SessaoEmpresa`), nunca do corpo do pedido.

    Sem grades no `criar`: `POST` cria só o produto (`colecoes_novas` inicializa as
    coleções vazias); variantes/fornecedores/grupos relacionados entram depois, no `PUT` —
    mesmo motivo de `Obra` não nascer junto com `Cliente`.
    """

    model_config = ConfigDict(extra="forbid")

    codigo: str = Field(min_length=1, max_length=40)
    descricao: str = Field(min_length=1, max_length=300)
    ativo: bool = True


class ProdutoAtualizar(_ProdutoCamposComuns):
    model_config = ConfigDict(extra="forbid")

    codigo: str | None = Field(default=None, min_length=1, max_length=40)
    descricao: str | None = Field(default=None, min_length=1, max_length=300)
    ativo: bool | None = None

    # Campos de relação — fora de `model_dump()` na hora de montar `valores` (ver
    # `ProdutoService.campos_relacao`), tratados em `_resolver_relacoes` via
    # `substituir_conjunto`. `None` (o padrão) = não mexe na coleção; lista vazia = limpa.
    variantes: list[VarianteItem] | None = None
    fornecedores: list[ProdutoFornecedorItem] | None = None
    grupos_relacionados: list[GrupoRelacionadoItem] | None = None


class ProdutoSaida(SaidaBase):
    id: uuid.UUID
    codigo: str
    descricao: str
    ativo: bool

    codigo_especial: str | None = None
    codigo_reduzido: str | None = None
    descricao_complementar: str | None = None
    dt_vigencia: date | None = None

    tipo_produto_id: uuid.UUID | None = None
    tipo_peca_id: uuid.UUID | None = None
    tipo_linha_id: uuid.UUID | None = None
    classificacao_id: uuid.UUID | None = None
    designer_modelo_id: uuid.UUID | None = None
    fabrica_id: uuid.UUID | None = None
    marca_id: uuid.UUID | None = None
    unidade_entrada_id: uuid.UUID | None = None
    unidade_saida_id: uuid.UUID | None = None
    qtd_entrada: Decimal
    qtd_saida: Decimal

    empresa_compradora_id: uuid.UUID | None = None

    fora_de_linha: bool
    consultar_valor: bool
    sobre_medida: bool
    publicar_no_site: bool

    ncm: str | None = None
    cest: str | None = None
    origem: str | None = None

    especificacao: EspecificacaoLuminaria

    variantes: list[VarianteSaida] = Field(default_factory=list)
    fornecedores: list[ProdutoFornecedorSaida] = Field(default_factory=list)
    grupos_relacionados: list[GrupoRelacionadoSaida] = Field(default_factory=list)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def preco_minimo_cents(self) -> int | None:
        """Menor preço entre as variantes. `None` quando nenhuma tem preço na empresa.

        `None` e `0` são coisas diferentes: produto sem preço cadastrado versus produto que
        custa zero. Um `or` no lugar deste `is not None` colapsaria os dois casos.
        """
        precos = [v.preco.preco_cents for v in self.variantes if v.preco is not None]
        return min(precos) if precos else None
