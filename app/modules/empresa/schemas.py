from __future__ import annotations

import uuid

from pydantic import BaseModel, Field

from app.common.schemas import (
    Cnpj,
    ComunicadoresCampos,
    ContatosCampos,
    EnderecoCampos,
    RedesSociaisCampos,
    SaidaBase,
)


class EmpresaCriar(EnderecoCampos, ContatosCampos, RedesSociaisCampos, ComunicadoresCampos):
    codigo: str = Field(min_length=1, max_length=20)
    razao_social: str = Field(min_length=1, max_length=160)
    nome_fantasia: str | None = Field(default=None, max_length=160)
    cnpj: Cnpj | None = None
    inscricao_estadual: str | None = Field(default=None, max_length=30)
    inscricao_municipal: str | None = Field(default=None, max_length=30)
    observacao: str | None = Field(default=None, max_length=2000)


class EmpresaAtualizar(EnderecoCampos, ContatosCampos, RedesSociaisCampos):
    razao_social: str | None = Field(default=None, min_length=1, max_length=160)
    nome_fantasia: str | None = Field(default=None, max_length=160)
    cnpj: Cnpj | None = None
    inscricao_estadual: str | None = Field(default=None, max_length=30)
    inscricao_municipal: str | None = Field(default=None, max_length=30)
    observacao: str | None = Field(default=None, max_length=2000)
    ativo: bool | None = None


class EmpresaSaida(SaidaBase, EnderecoCampos, ContatosCampos, RedesSociaisCampos):
    id: uuid.UUID
    codigo: str
    razao_social: str
    nome_fantasia: str | None = None
    cnpj: str | None = None
    inscricao_estadual: str | None = None
    inscricao_municipal: str | None = None
    observacao: str | None = None
    ativo: bool


class FilialCriar(EnderecoCampos, ContatosCampos):
    empresa_id: uuid.UUID
    codigo: str = Field(min_length=1, max_length=20)
    nome: str = Field(min_length=1, max_length=160)
    cnpj: Cnpj | None = None
    matriz: bool = False


class FilialAtualizar(EnderecoCampos, ContatosCampos):
    codigo: str | None = Field(default=None, min_length=1, max_length=20)
    nome: str | None = Field(default=None, min_length=1, max_length=160)
    cnpj: Cnpj | None = None
    matriz: bool | None = None
    ativo: bool | None = None


class FilialSaida(SaidaBase, EnderecoCampos, ContatosCampos):
    id: uuid.UUID
    empresa_id: uuid.UUID
    codigo: str
    nome: str
    cnpj: str | None = None
    matriz: bool
    ativo: bool


class CentroCustoCriar(BaseModel):
    empresa_id: uuid.UUID
    codigo: str = Field(min_length=1, max_length=20)
    nome: str = Field(min_length=1, max_length=160)
    pai_id: uuid.UUID | None = None


class CentroCustoAtualizar(BaseModel):
    codigo: str | None = Field(default=None, min_length=1, max_length=20)
    nome: str | None = Field(default=None, min_length=1, max_length=160)
    pai_id: uuid.UUID | None = None
    ativo: bool | None = None


class CentroCustoSaida(SaidaBase):
    id: uuid.UUID
    empresa_id: uuid.UUID
    codigo: str
    nome: str
    pai_id: uuid.UUID | None = None
    ativo: bool
