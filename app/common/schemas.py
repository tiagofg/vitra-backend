from __future__ import annotations

import re
import uuid
from typing import Annotated, Any

from pydantic import AfterValidator, BaseModel, BeforeValidator, ConfigDict, Field

_NAO_ALFANUMERICO = re.compile(r"[^0-9A-Za-z]")


def _normalizar_documento(valor: Any) -> Any:
    """Tira máscara e sobe para caixa alta antes de qualquer validação.

    Vale para CNPJ e CPF: o banco guarda `varchar(14)` sem máscara — a borda é que aceita
    `12.345.678/0001-90` ou `123.456.789-00`, porque é assim que o dado chega da tela e do
    arquivo do legado. Caixa alta não é capricho: **o CNPJ alfanumérico passa a valer em
    31/07/2026**, e guardar `a1b2...` e `A1B2...` como valores diferentes quebraria a
    unicidade em silêncio.
    """
    if not isinstance(valor, str):
        return valor
    return _NAO_ALFANUMERICO.sub("", valor).upper()


def _conferir_tamanho_cnpj(valor: str) -> str:
    if len(valor) != 14:
        raise ValueError("CNPJ deve ter 14 caracteres, sem máscara.")
    return valor


def _conferir_tamanho_cpf(valor: str) -> str:
    if len(valor) != 11:
        raise ValueError("CPF deve ter 11 caracteres, sem máscara.")
    return valor


def _conferir_tamanho_cpf_ou_cnpj(valor: str) -> str:
    if len(valor) not in (11, 14):
        raise ValueError("CPF/CNPJ deve ter 11 (CPF) ou 14 (CNPJ) caracteres, sem máscara.")
    return valor


Cnpj = Annotated[
    str,
    BeforeValidator(_normalizar_documento),
    AfterValidator(_conferir_tamanho_cnpj),
    Field(max_length=14, examples=["12345678000190"]),
]

Cpf = Annotated[
    str,
    BeforeValidator(_normalizar_documento),
    AfterValidator(_conferir_tamanho_cpf),
    Field(max_length=11, examples=["12345678900"]),
]

# Cliente e profissional externo podem ser pessoa física ou jurídica (`tipo_pessoa` decide
# qual); a coluna é a mesma `varchar(14)` nos dois casos, só o comprimento do valor muda.
CpfCnpj = Annotated[
    str,
    BeforeValidator(_normalizar_documento),
    AfterValidator(_conferir_tamanho_cpf_ou_cnpj),
    Field(max_length=14, examples=["12345678900", "12345678000190"]),
]


class SaidaBase(BaseModel):
    """Todo schema de saída lê direto do modelo ORM."""

    model_config = ConfigDict(from_attributes=True)


class EnderecoCampos(BaseModel):
    """Espelha `EnderecoMixin`. Reusado por empresa, filial e (em S1) pelos cadastros."""

    endereco_cep: str | None = Field(default=None, max_length=9)
    endereco_logradouro: str | None = Field(default=None, max_length=160)
    endereco_numero: str | None = Field(default=None, max_length=20)
    endereco_complemento: str | None = Field(default=None, max_length=80)
    endereco_bairro: str | None = Field(default=None, max_length=80)
    endereco_ponto_referencia: str | None = Field(default=None, max_length=160)
    endereco_cidade_id: uuid.UUID | None = None


class ContatosCampos(BaseModel):
    telefone: str | None = Field(default=None, max_length=20)
    telefone_secundario: str | None = Field(default=None, max_length=20)
    celular: str | None = Field(default=None, max_length=20)
    fax: str | None = Field(default=None, max_length=20)
    email: str | None = Field(default=None, max_length=160)
    email_secundario: str | None = Field(default=None, max_length=160)
    site: str | None = Field(default=None, max_length=160)


class RedesSociaisCampos(BaseModel):
    instagram: str | None = Field(default=None, max_length=120)
    facebook: str | None = Field(default=None, max_length=120)
    linkedin: str | None = Field(default=None, max_length=120)
    youtube: str | None = Field(default=None, max_length=120)
    tiktok: str | None = Field(default=None, max_length=120)


class ComunicadoresCampos(BaseModel):
    comunicadores: list[dict[str, Any]] = Field(default_factory=list)
