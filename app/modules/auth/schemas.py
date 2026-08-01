from __future__ import annotations

import uuid
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class _Saida(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- autenticação ------------------------------------------------------------


class LoginEntrada(BaseModel):
    login: str = Field(min_length=1, max_length=60)
    senha: str = Field(min_length=1, max_length=200)


class RefreshEntrada(BaseModel):
    refresh_token: str


class TokenSaida(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"  # noqa: S105 — tipo de token do OAuth2, não segredo


class AlterarSenhaEntrada(BaseModel):
    senha_atual: str = Field(min_length=1, max_length=200)
    senha_nova: str = Field(min_length=8, max_length=200)


# --- permissões e grupos -----------------------------------------------------


class PermissaoSaida(_Saida):
    id: uuid.UUID
    recurso: str
    acao: str
    descricao: str | None = None


class GrupoCriar(BaseModel):
    nome: str = Field(min_length=1, max_length=80)
    descricao: str | None = Field(default=None, max_length=200)


class GrupoAtualizar(BaseModel):
    nome: str | None = Field(default=None, min_length=1, max_length=80)
    descricao: str | None = Field(default=None, max_length=200)
    ativo: bool | None = None


class GrupoSaida(_Saida):
    id: uuid.UUID
    nome: str
    descricao: str | None = None
    ativo: bool
    permissoes: list[PermissaoSaida] = []


class PermissoesGrupoEntrada(BaseModel):
    """PUT substitui o conjunto inteiro — é como a tela de permissões funciona."""

    permissao_ids: list[uuid.UUID] = []


# --- usuários ----------------------------------------------------------------


class UsuarioCriar(BaseModel):
    login: str = Field(min_length=1, max_length=60)
    nome: str = Field(min_length=1, max_length=120)
    senha: str = Field(min_length=8, max_length=200)
    email: EmailStr
    superusuario: bool = False
    limite_desconto_pct: Decimal = Field(default=Decimal("0.0000"), ge=0, le=100)
    grupo_ids: list[uuid.UUID] = []


class UsuarioAtualizar(BaseModel):
    nome: str | None = Field(default=None, min_length=1, max_length=120)
    email: EmailStr | None = None
    superusuario: bool | None = None
    ativo: bool | None = None
    limite_desconto_pct: Decimal | None = Field(default=None, ge=0, le=100)
    grupo_ids: list[uuid.UUID] | None = None


class UsuarioSenhaEntrada(BaseModel):
    """Redefinição por um administrador — não pede a senha atual."""

    senha_nova: str = Field(min_length=8, max_length=200)


class UsuarioSaida(_Saida):
    id: uuid.UUID
    login: str
    nome: str
    email: str
    ativo: bool
    superusuario: bool
    limite_desconto_pct: Decimal
    grupos: list[GrupoSaida] = []


class EuSaida(_Saida):
    id: uuid.UUID
    login: str
    nome: str
    email: str
    superusuario: bool
    limite_desconto_pct: Decimal
    grupos: list[str]
    permissoes: list[str]


class TrocarEmpresaEntrada(BaseModel):
    """`X-Empresa-Id` do corpo, não do cabeçalho: o pedido troca o próprio token."""

    empresa_id: uuid.UUID
