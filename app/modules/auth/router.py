from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.core.deps import Sessao, UsuarioAtual
from app.core.listing import ListParams, Pagina
from app.core.permissions import Acao, require
from app.modules.auth.models import Usuario
from app.modules.auth.schemas import (
    AlterarSenhaEntrada,
    EuSaida,
    GrupoAtualizar,
    GrupoCriar,
    GrupoSaida,
    LoginEntrada,
    PermissaoSaida,
    PermissoesGrupoEntrada,
    RefreshEntrada,
    TokenSaida,
    UsuarioAtualizar,
    UsuarioCriar,
    UsuarioSaida,
    UsuarioSenhaEntrada,
)
from app.modules.auth.service import AuthService, GrupoService, PermissaoService, UsuarioService

router_auth = APIRouter(prefix="/auth", tags=["auth"])
router_grupos = APIRouter(prefix="/grupos", tags=["acesso"])
router_usuarios = APIRouter(prefix="/usuarios", tags=["acesso"])
router_permissoes = APIRouter(prefix="/permissoes", tags=["acesso"])


# --- autenticação ------------------------------------------------------------


@router_auth.post("/login", response_model=TokenSaida)
async def login(dados: LoginEntrada, session: Sessao) -> TokenSaida:
    service = AuthService(session)
    usuario = await service.autenticar(dados.login, dados.senha)
    return service.emitir_tokens(usuario)


@router_auth.post("/refresh", response_model=TokenSaida)
async def refresh(dados: RefreshEntrada, session: Sessao) -> TokenSaida:
    return await AuthService(session).renovar(dados.refresh_token)


@router_auth.post("/alterar-senha", status_code=status.HTTP_204_NO_CONTENT)
async def alterar_senha(dados: AlterarSenhaEntrada, session: Sessao, usuario: UsuarioAtual) -> None:
    await AuthService(session).alterar_senha(usuario, dados.senha_atual, dados.senha_nova)


@router_auth.get("/eu", response_model=EuSaida)
async def eu(usuario: UsuarioAtual) -> EuSaida:
    return EuSaida(
        id=usuario.id,
        login=usuario.login,
        nome=usuario.nome,
        email=usuario.email,
        superusuario=usuario.superusuario,
        empresa_id=usuario.empresa_id,
        limite_desconto_pct=usuario.limite_desconto_pct,
        grupos=[g.nome for g in usuario.grupos],
        permissoes=sorted(usuario.permissoes_efetivas()),
    )


# --- grupos ------------------------------------------------------------------


@router_grupos.get("", response_model=Pagina[GrupoSaida])
async def listar_grupos(
    session: Sessao,
    params: Annotated[ListParams, Depends()],
    _: Annotated[Usuario, Depends(require("grupo", Acao.ler))],
) -> Pagina[GrupoSaida]:
    return await GrupoService(session).listar(params, GrupoSaida.model_validate)


@router_grupos.post("", response_model=GrupoSaida, status_code=status.HTTP_201_CREATED)
async def criar_grupo(
    dados: GrupoCriar,
    session: Sessao,
    usuario: Annotated[Usuario, Depends(require("grupo", Acao.criar))],
) -> GrupoSaida:
    grupo = await GrupoService(session, usuario.id).criar(dados)
    return GrupoSaida.model_validate(grupo)


@router_grupos.get("/{grupo_id}", response_model=GrupoSaida)
async def obter_grupo(
    grupo_id: uuid.UUID,
    session: Sessao,
    _: Annotated[Usuario, Depends(require("grupo", Acao.ler))],
) -> GrupoSaida:
    return GrupoSaida.model_validate(await GrupoService(session).obter(grupo_id))


@router_grupos.put("/{grupo_id}", response_model=GrupoSaida)
async def atualizar_grupo(
    grupo_id: uuid.UUID,
    dados: GrupoAtualizar,
    session: Sessao,
    usuario: Annotated[Usuario, Depends(require("grupo", Acao.editar))],
) -> GrupoSaida:
    grupo = await GrupoService(session, usuario.id).atualizar(grupo_id, dados)
    return GrupoSaida.model_validate(grupo)


@router_grupos.delete("/{grupo_id}", response_model=GrupoSaida)
async def desativar_grupo(
    grupo_id: uuid.UUID,
    session: Sessao,
    usuario: Annotated[Usuario, Depends(require("grupo", Acao.excluir))],
) -> GrupoSaida:
    """Desativação lógica: cadastro nunca sai do banco."""
    grupo = await GrupoService(session, usuario.id).desativar(grupo_id)
    return GrupoSaida.model_validate(grupo)


@router_grupos.get("/{grupo_id}/permissoes", response_model=list[PermissaoSaida])
async def listar_permissoes_do_grupo(
    grupo_id: uuid.UUID,
    session: Sessao,
    _: Annotated[Usuario, Depends(require("grupo", Acao.ler))],
) -> list[PermissaoSaida]:
    grupo = await GrupoService(session).obter(grupo_id)
    return [PermissaoSaida.model_validate(p) for p in grupo.permissoes]


@router_grupos.put("/{grupo_id}/permissoes", response_model=GrupoSaida)
async def definir_permissoes_do_grupo(
    grupo_id: uuid.UUID,
    dados: PermissoesGrupoEntrada,
    session: Sessao,
    usuario: Annotated[Usuario, Depends(require("grupo", Acao.editar))],
) -> GrupoSaida:
    grupo = await GrupoService(session, usuario.id).definir_permissoes(
        grupo_id, dados.permissao_ids
    )
    return GrupoSaida.model_validate(grupo)


# --- usuários ----------------------------------------------------------------


@router_usuarios.get("", response_model=Pagina[UsuarioSaida])
async def listar_usuarios(
    session: Sessao,
    params: Annotated[ListParams, Depends()],
    _: Annotated[Usuario, Depends(require("usuario", Acao.ler))],
) -> Pagina[UsuarioSaida]:
    return await UsuarioService(session).listar(params, UsuarioSaida.model_validate)


@router_usuarios.post("", response_model=UsuarioSaida, status_code=status.HTTP_201_CREATED)
async def criar_usuario(
    dados: UsuarioCriar,
    session: Sessao,
    usuario: Annotated[Usuario, Depends(require("usuario", Acao.criar))],
) -> UsuarioSaida:
    novo = await UsuarioService(session, usuario.id).criar(dados)
    return UsuarioSaida.model_validate(novo)


@router_usuarios.get("/{usuario_id}", response_model=UsuarioSaida)
async def obter_usuario(
    usuario_id: uuid.UUID,
    session: Sessao,
    _: Annotated[Usuario, Depends(require("usuario", Acao.ler))],
) -> UsuarioSaida:
    return UsuarioSaida.model_validate(await UsuarioService(session).obter(usuario_id))


@router_usuarios.put("/{usuario_id}", response_model=UsuarioSaida)
async def atualizar_usuario(
    usuario_id: uuid.UUID,
    dados: UsuarioAtualizar,
    session: Sessao,
    usuario: Annotated[Usuario, Depends(require("usuario", Acao.editar))],
) -> UsuarioSaida:
    alvo = await UsuarioService(session, usuario.id).atualizar(usuario_id, dados)
    return UsuarioSaida.model_validate(alvo)


@router_usuarios.post("/{usuario_id}/senha", status_code=status.HTTP_204_NO_CONTENT)
async def redefinir_senha(
    usuario_id: uuid.UUID,
    dados: UsuarioSenhaEntrada,
    session: Sessao,
    usuario: Annotated[Usuario, Depends(require("usuario", Acao.editar))],
) -> None:
    await UsuarioService(session, usuario.id).definir_senha(usuario_id, dados.senha_nova)


@router_usuarios.delete("/{usuario_id}", response_model=UsuarioSaida)
async def desativar_usuario(
    usuario_id: uuid.UUID,
    session: Sessao,
    usuario: Annotated[Usuario, Depends(require("usuario", Acao.excluir))],
) -> UsuarioSaida:
    alvo = await UsuarioService(session, usuario.id).desativar(usuario_id)
    return UsuarioSaida.model_validate(alvo)


# --- permissões --------------------------------------------------------------


@router_permissoes.get("", response_model=Pagina[PermissaoSaida])
async def listar_permissoes(
    session: Sessao,
    params: Annotated[ListParams, Depends()],
    _: Annotated[Usuario, Depends(require("permissao", Acao.ler))],
) -> Pagina[PermissaoSaida]:
    return await PermissaoService(session).listar(params, PermissaoSaida.model_validate)


routers = [router_auth, router_grupos, router_usuarios, router_permissoes]
