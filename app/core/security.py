from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import config
from app.core.errors import NaoAutenticado

_hasher = PasswordHasher()

TipoToken = Literal["access", "refresh"]


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


def criar_token(subject: uuid.UUID, tipo: TipoToken = "access") -> str:
    agora = datetime.now(UTC)
    if tipo == "access":
        expira = agora + timedelta(minutes=config.jwt_access_ttl_minutos)
    else:
        expira = agora + timedelta(days=config.jwt_refresh_ttl_dias)
    payload = {
        "sub": str(subject),
        "tipo": tipo,
        "iat": int(agora.timestamp()),
        "exp": int(expira.timestamp()),
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, config.jwt_secret, algorithm=config.jwt_algoritmo)


def ler_token(token: str, tipo_esperado: TipoToken = "access") -> uuid.UUID:
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
        return uuid.UUID(payload["sub"])
    except (KeyError, ValueError) as exc:
        raise NaoAutenticado("Token sem subject válido.") from exc
