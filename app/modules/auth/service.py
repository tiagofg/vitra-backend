from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.base_service import BaseService
from app.core.errors import Conflito, NaoAutenticado, NaoEncontrado, RegraDeNegocio
from app.core.listing import ListingSpec
from app.core.security import (
    criar_token,
    gerar_hash_senha,
    ler_token,
    precisa_reidratar_hash,
    verificar_senha,
)
from app.modules.auth.models import Grupo, Permissao, Usuario
from app.modules.auth.schemas import (
    GrupoAtualizar,
    GrupoCriar,
    TokenSaida,
    UsuarioAtualizar,
    UsuarioCriar,
)


class AuthService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def autenticar(self, login: str, senha: str) -> Usuario:
        usuario = (
            await self.session.execute(select(Usuario).where(Usuario.login == login))
        ).scalar_one_or_none()

        # Mensagem única para login inexistente e senha errada: não revela quem existe.
        if usuario is None or not verificar_senha(senha, usuario.senha_hash):
            raise NaoAutenticado("Login ou senha inválidos.")
        if not usuario.ativo:
            raise NaoAutenticado("Usuário desativado.")

        if precisa_reidratar_hash(usuario.senha_hash):
            usuario.senha_hash = gerar_hash_senha(senha)
            await self.session.flush()
        return usuario

    def emitir_tokens(self, usuario: Usuario) -> TokenSaida:
        return TokenSaida(
            access_token=criar_token(usuario.id, "access"),
            refresh_token=criar_token(usuario.id, "refresh"),
        )

    async def renovar(self, refresh_token: str) -> TokenSaida:
        usuario_id = ler_token(refresh_token, "refresh")
        usuario = await self.session.get(Usuario, usuario_id)
        if usuario is None or not usuario.ativo:
            raise NaoAutenticado("Usuário do token não está ativo.")
        return self.emitir_tokens(usuario)

    async def alterar_senha(self, usuario: Usuario, senha_atual: str, senha_nova: str) -> None:
        if not verificar_senha(senha_atual, usuario.senha_hash):
            raise NaoAutenticado("Senha atual incorreta.")
        if senha_atual == senha_nova:
            raise RegraDeNegocio("A senha nova precisa ser diferente da atual.")
        usuario.senha_hash = gerar_hash_senha(senha_nova)
        await self.session.flush()


class GrupoService(BaseService[Grupo, GrupoCriar, GrupoAtualizar]):
    nome_recurso = "Grupo"
    colecoes_novas = ("permissoes",)
    spec = ListingSpec(
        model=Grupo,
        campos_busca=("nome", "descricao"),
        campos_ordenacao=("nome", "criado_em"),
        ordenacao_padrao="nome",
    )

    async def _antes_de_criar(self, valores: dict[str, Any]) -> None:
        await self._checar_nome_livre(valores.get("nome"))

    async def _antes_de_atualizar(self, obj: Grupo, valores: dict[str, Any]) -> None:
        if "nome" in valores and valores["nome"] != obj.nome:
            await self._checar_nome_livre(valores["nome"])

    async def _checar_nome_livre(self, nome: str | None) -> None:
        if nome is None:
            return
        existe = (await self.session.execute(select(Grupo.id).where(Grupo.nome == nome))).first()
        if existe:
            raise Conflito(f"Já existe um grupo chamado '{nome}'.", campos={"nome": "já utilizado"})

    async def definir_permissoes(
        self, grupo_id: uuid.UUID, permissao_ids: list[uuid.UUID]
    ) -> Grupo:
        grupo = await self.obter(grupo_id)
        permissoes = list(
            (await self.session.execute(select(Permissao).where(Permissao.id.in_(permissao_ids))))
            .scalars()
            .all()
        )
        faltando = set(permissao_ids) - {p.id for p in permissoes}
        if faltando:
            raise NaoEncontrado("Permissão", ", ".join(str(i) for i in sorted(faltando)))
        grupo.permissoes = permissoes
        await self.session.flush()
        return grupo


class UsuarioService(BaseService[Usuario, UsuarioCriar, UsuarioAtualizar]):
    nome_recurso = "Usuário"
    spec = ListingSpec(
        model=Usuario,
        campos_busca=("login", "nome", "email"),
        campo_codigo="login",
        campos_ordenacao=("login", "nome", "criado_em"),
        ordenacao_padrao="login",
        tem_empresa=True,
    )

    async def criar(self, dados: UsuarioCriar) -> Usuario:
        existe = (
            await self.session.execute(select(Usuario.id).where(Usuario.login == dados.login))
        ).first()
        if existe:
            raise Conflito(
                f"Login '{dados.login}' já está em uso.", campos={"login": "já utilizado"}
            )

        valores = dados.model_dump(exclude={"senha", "grupo_ids"})
        usuario = Usuario(**valores, senha_hash=gerar_hash_senha(dados.senha))
        if self.usuario_id is not None:
            usuario.criado_por_id = self.usuario_id
        usuario.grupos = await self._buscar_grupos(dados.grupo_ids)
        self.session.add(usuario)
        await self.session.flush()
        return usuario

    async def atualizar(self, id_: uuid.UUID, dados: UsuarioAtualizar) -> Usuario:
        usuario = await self.obter(id_)
        valores = dados.model_dump(exclude_unset=True, exclude={"grupo_ids"})
        for campo, valor in valores.items():
            setattr(usuario, campo, valor)
        if dados.grupo_ids is not None:
            usuario.grupos = await self._buscar_grupos(dados.grupo_ids)
        await self.session.flush()
        return usuario

    async def definir_senha(self, id_: uuid.UUID, senha_nova: str) -> Usuario:
        usuario = await self.obter(id_)
        usuario.senha_hash = gerar_hash_senha(senha_nova)
        await self.session.flush()
        return usuario

    async def _antes_de_desativar(self, obj: Usuario) -> None:
        if self.usuario_id is not None and obj.id == self.usuario_id:
            raise RegraDeNegocio("Um usuário não pode desativar a si mesmo.")

    async def _buscar_grupos(self, grupo_ids: list[uuid.UUID]) -> list[Grupo]:
        if not grupo_ids:
            return []
        grupos = list(
            (await self.session.execute(select(Grupo).where(Grupo.id.in_(grupo_ids))))
            .scalars()
            .all()
        )
        faltando = set(grupo_ids) - {g.id for g in grupos}
        if faltando:
            raise NaoEncontrado("Grupo", ", ".join(str(i) for i in sorted(faltando)))
        return grupos


class PermissaoService(BaseService[Permissao, Any, Any]):
    nome_recurso = "Permissão"
    spec = ListingSpec(
        model=Permissao,
        campos_busca=("recurso", "acao", "descricao"),
        campos_ordenacao=("recurso", "acao"),
        ordenacao_padrao="recurso",
        tem_ativo=False,
    )
