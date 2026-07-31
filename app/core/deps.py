from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.errors import NAO_AUTENTICADO, NaoAutenticado, pode_falhar
from app.core.security import ler_token
from app.modules.auth.models import Usuario

Sessao = Annotated[AsyncSession, Depends(get_session)]

# `SessaoEmpresa` — a sessão com empresa declarada e autorizada — mora em
# `app/modules/bakeoff/deps.py`: autorizar depende de `employee_company`, e core não
# importa modelo de módulo.

# auto_error=False para que a falta de header vire o nosso envelope, não o do Starlette.
_bearer = HTTPBearer(auto_error=False, description="Token JWT obtido em POST /auth/login")


@pode_falhar(NAO_AUTENTICADO)
async def usuario_atual(
    session: Sessao,
    credencial: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)] = None,
) -> Usuario:
    if credencial is None or not credencial.credentials:
        raise NaoAutenticado()

    usuario_id = ler_token(credencial.credentials, "access")
    usuario = await session.get(Usuario, usuario_id)
    if usuario is None:
        raise NaoAutenticado("Usuário do token não existe mais.")
    if not usuario.ativo:
        raise NaoAutenticado("Usuário desativado.")
    return usuario


UsuarioAtual = Annotated[Usuario, Depends(usuario_atual)]
