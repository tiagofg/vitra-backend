from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.errors import NaoAutenticado
from app.core.security import ler_token
from app.core.tenancy import EmpresaDoPedido, declarar_empresa
from app.modules.auth.models import Usuario

Sessao = Annotated[AsyncSession, Depends(get_session)]


async def sessao_da_empresa(session: Sessao, empresa_id: EmpresaDoPedido) -> AsyncSession:
    """Sessão com a empresa ativa já declarada na transação.

    Toda rota que toca tabela por empresa depende desta, e não de `Sessao`. A partir daqui
    o serviço não escreve — nem pode escrever — filtro de empresa: quem recorta é o banco.
    """
    await declarar_empresa(session, empresa_id)
    return session


SessaoEmpresa = Annotated[AsyncSession, Depends(sessao_da_empresa)]

# auto_error=False para que a falta de header vire o nosso envelope, não o do Starlette.
_bearer = HTTPBearer(auto_error=False, description="Token JWT obtido em POST /auth/login")


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
