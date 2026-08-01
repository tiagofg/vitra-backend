from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import config
from app.core.errors import NaoAutenticado

_hasher = PasswordHasher()

TipoToken = Literal["access", "refresh"]


@dataclass(frozen=True)
class ClaimsToken:
    """O que um token de acesso carrega. `tenant_id` é a empresa ativa no momento da
    emissão — claim, não header: é o que deixa o cliente operar sem enviar `X-Empresa-Id`
    em todo pedido. Ausente para quem ainda não escolheu empresa (o token do login inicial,
    antes de `POST /auth/trocar-empresa`).

    `senha_versao` é a versão de `Usuario.senha_versao` no momento da emissão — conferida
    em `usuario_atual` contra a versão atual da linha. Sem isto, trocar a senha não invalida
    tokens já emitidos: um `access_token` vazado continuaria funcionando até expirar por
    conta própria, mesmo depois da vítima trocar a senha achando que resolveu o problema.
    """

    usuario_id: uuid.UUID
    tenant_id: uuid.UUID | None
    senha_versao: int


def gerar_hash_senha(senha: str) -> str:
    return _hasher.hash(senha)


def verificar_senha(senha: str, senha_hash: str) -> bool:
    try:
        return _hasher.verify(senha_hash, senha)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def precisa_reidratar_hash(senha_hash: str) -> bool:
    """True quando os parâmetros do argon2 mudaram e vale regravar o hash no login."""
    try:
        return _hasher.check_needs_rehash(senha_hash)
    except InvalidHashError:
        return True


def criar_token(
    subject: uuid.UUID,
    tipo: TipoToken = "access",
    *,
    tenant_id: uuid.UUID | None = None,
    senha_versao: int = 0,
) -> str:
    agora = datetime.now(UTC)
    if tipo == "access":
        expira = agora + timedelta(minutes=config.jwt_access_ttl_minutos)
    else:
        expira = agora + timedelta(days=config.jwt_refresh_ttl_dias)
    payload: dict[str, Any] = {
        "sub": str(subject),
        "tipo": tipo,
        "iat": int(agora.timestamp()),
        "exp": int(expira.timestamp()),
        "jti": uuid.uuid4().hex,
        "sv": senha_versao,
    }
    if tenant_id is not None:
        payload["tenant"] = str(tenant_id)
    return jwt.encode(payload, config.jwt_secret, algorithm=config.jwt_algoritmo)


def ler_claims(token: str, tipo_esperado: TipoToken = "access") -> ClaimsToken:
    try:
        payload: dict[str, Any] = jwt.decode(
            token, config.jwt_secret, algorithms=[config.jwt_algoritmo]
        )
    except jwt.ExpiredSignatureError as exc:
        raise NaoAutenticado("Token expirado.") from exc
    except jwt.PyJWTError as exc:
        raise NaoAutenticado("Token inválido.") from exc

    if payload.get("tipo") != tipo_esperado:
        raise NaoAutenticado(f"Esperado token do tipo '{tipo_esperado}'.")
    try:
        usuario_id = uuid.UUID(payload["sub"])
    except (KeyError, ValueError) as exc:
        raise NaoAutenticado("Token sem subject válido.") from exc

    tenant_bruto = payload.get("tenant")
    tenant_id = uuid.UUID(tenant_bruto) if tenant_bruto else None
    # `.get("sv", 0)`: tokens emitidos antes deste campo existir (nenhum em produção ainda)
    # não têm a chave; tratar como versão 0 é o mesmo valor inicial de `Usuario.senha_versao`.
    senha_versao = int(payload.get("sv", 0))
    return ClaimsToken(usuario_id=usuario_id, tenant_id=tenant_id, senha_versao=senha_versao)
