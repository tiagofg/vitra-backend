from __future__ import annotations

import uuid

from pydantic import BaseModel, Field

from app.common.schemas import SaidaBase
from app.modules.apoio.models import DominioApoio


class ApoioCriar(BaseModel):
    """`codigo` é opcional: o botão `...` da tela cria o valor na hora, só com a descrição."""

    descricao: str = Field(min_length=1, max_length=160)
    codigo: str | None = Field(default=None, max_length=30)
    ordem: int = 0
    empresa_id: uuid.UUID | None = None


class ApoioAtualizar(BaseModel):
    descricao: str | None = Field(default=None, min_length=1, max_length=160)
    codigo: str | None = Field(default=None, max_length=30)
    ordem: int | None = None
    ativo: bool | None = None


class ApoioSaida(SaidaBase):
    id: uuid.UUID
    dominio: DominioApoio
    codigo: str
    descricao: str
    ordem: int
    ativo: bool
    empresa_id: uuid.UUID | None = None


class DominioSaida(BaseModel):
    dominio: DominioApoio
    rotulo: str


class UfSaida(SaidaBase):
    id: uuid.UUID
    sigla: str
    nome: str
    codigo_ibge: str


class CidadeCriar(BaseModel):
    uf_id: uuid.UUID
    nome: str = Field(min_length=1, max_length=120)
    codigo_ibge: str | None = Field(default=None, max_length=7)


class CidadeAtualizar(BaseModel):
    nome: str | None = Field(default=None, min_length=1, max_length=120)
    codigo_ibge: str | None = Field(default=None, max_length=7)


class CidadeSaida(SaidaBase):
    id: uuid.UUID
    nome: str
    codigo_ibge: str | None = None
    uf_id: uuid.UUID
    uf_sigla: str


class BancoCriar(BaseModel):
    codigo: str = Field(min_length=1, max_length=5)
    nome: str = Field(min_length=1, max_length=120)


class BancoAtualizar(BaseModel):
    codigo: str | None = Field(default=None, min_length=1, max_length=5)
    nome: str | None = Field(default=None, min_length=1, max_length=120)
    ativo: bool | None = None


class BancoSaida(SaidaBase):
    id: uuid.UUID
    codigo: str
    nome: str
    ativo: bool
