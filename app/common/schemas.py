from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SaidaBase(BaseModel):
    """Todo schema de saída lê direto do modelo ORM."""

    model_config = ConfigDict(from_attributes=True)


class EnderecoCampos(BaseModel):
    """Espelha `EnderecoMixin`. Reusado por empresa, filial e (em F1) pelos cadastros."""

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
