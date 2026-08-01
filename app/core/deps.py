from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.errors import NAO_AUTENTICADO, NaoAutenticado, pode_falhar
from app.core.security import ClaimsToken, ler_claims
from app.modules.auth.models import Usuario

Sessao = Annotated[AsyncSession, Depends(get_session)]

# `SessaoEmpresa` — a sessão com empresa declarada e autorizada — mora em
# `app/modules/auth/deps.py`: autorizar depende de `employee_company`, e core não importa
# modelo de módulo.

# auto_error=False para que a falta de header vire o nosso envelope, não o do Starlette.
_bearer = HTTPBearer(auto_error=False, description="Token JWT obtido em POST /auth/login")


@pode_falhar(NAO_AUTENTICADO)
async def claims_do_token(
    credencial: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)] = None,
) -> ClaimsToken:
    """Decodifica o token uma vez; `usuario_atual` e `empresa_do_pedido` dependem daqui.

    O FastAPI cacheia dependências por request: as duas dependências acima recebem o
    mesmo objeto sem decodificar o JWT duas vezes.
    """
    if credencial is None or not credencial.credentials:
        raise NaoAutenticado()
    return ler_claims(credencial.credentials, "access")


ClaimsDoToken = Annotated[ClaimsToken, Depends(claims_do_token)]


@pode_falhar(NAO_AUTENTICADO)
async def usuario_atual(session: Sessao, claims: ClaimsDoToken) -> Usuario:
    usuario = await session.get(Usuario, claims.usuario_id)
    if usuario is None:
        raise NaoAutenticado("Usuário do token não existe mais.")
    if not usuario.ativo:
        raise NaoAutenticado("Usuário desativado.")
    # Token emitido antes da senha mudar: `alterar_senha`/`definir_senha` incrementam
    # `senha_versao`, e um token com a versão antiga para de autenticar mesmo dentro do
    # prazo de validade — sem isto, trocar a senha não invalidava o que já tinha vazado.
    if claims.senha_versao != usuario.senha_versao:
        raise NaoAutenticado("Token emitido antes da última troca de senha.")
    return usuario


UsuarioAtual = Annotated[Usuario, Depends(usuario_atual)]
