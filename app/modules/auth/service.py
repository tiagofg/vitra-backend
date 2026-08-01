from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.base_service import BaseService
from app.core.errors import NaoAutenticado, NaoEncontrado, RegraDeNegocio
from app.core.listing import ListingSpec
from app.core.security import (
    criar_token,
    gerar_hash_senha,
    ler_claims,
    precisa_reidratar_hash,
    verificar_senha,
)
from app.core.tenancy import SemVinculoComEmpresa, declarar_empresa
from app.modules.auth.models import Grupo, Permissao, Usuario, VinculoEmpresa
from app.modules.auth.schemas import (
    GrupoAtualizar,
    GrupoCriar,
    TokenSaida,
    UsuarioAtualizar,
    UsuarioCriar,
)
from app.modules.empresa.models import Empresa

# Trava de força bruta em `/auth/login`: depois disto, a conta fica bloqueada por
# `_BLOQUEIO_MINUTOS`, mesmo com a senha certa. Sem alguma trava, o argon2 (deliberadamente
# lento) é a única barreira contra tentativa repetida — e ela sozinha não impede um script.
_TENTATIVAS_MAXIMAS = 5
_BLOQUEIO_MINUTOS = 15

# Hash de uma senha que não existe, calculado uma vez no import. `autenticar` verifica
# contra ele quando o login não existe, para que o tempo de resposta seja o mesmo de um
# login que existe com senha errada — sem isto, a ausência do `argon2.verify()` (rápida)
# denuncia por timing quais logins são válidos, mesmo a mensagem de erro sendo idêntica.
_HASH_DUMMY = gerar_hash_senha(uuid.uuid4().hex)


async def tem_vinculo(session: AsyncSession, employee_id: uuid.UUID, tenant_id: uuid.UUID) -> bool:
    """A pessoa tem vínculo ativo com **aquela** empresa?

    O filtro por `tenant_id` é explícito na consulta, e não apenas confiado ao RLS. A
    política de `employee_company` já recortaria pela empresa declarada na transação, mas
    esta função precisa continuar correta **mesmo sob uma conexão que ignora RLS** — dono,
    superusuário, ou um bug futuro que troque o papel de runtime. Sem o filtro aqui, as
    duas camadas que `app/modules/auth/deps.py` descreve como independentes colapsam numa
    só: a checagem de vínculo passaria a valer só porque o RLS por baixo também filtrou,
    que é exatamente o encadeamento *"RLS confia no GUC → borda confia no RLS"* que a
    checagem existe para não ter.
    """
    linha = await session.execute(
        select(VinculoEmpresa.tenant_id)
        .join(Empresa, Empresa.id == VinculoEmpresa.tenant_id)
        .where(
            VinculoEmpresa.employee_id == employee_id,
            VinculoEmpresa.tenant_id == tenant_id,
            Empresa.ativo.is_(True),
        )
        .limit(1)
    )
    return linha.scalar_one_or_none() is not None


class AuthService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def autenticar(self, login: str, senha: str) -> Usuario:
        usuario = (
            await self.session.execute(select(Usuario).where(Usuario.login == login))
        ).scalar_one_or_none()

        if usuario is None:
            # Verifica contra um hash que não corresponde a ninguém, só para gastar o
            # mesmo tempo de CPU que `verificar_senha` gastaria se o login existisse —
            # ver `_HASH_DUMMY`.
            verificar_senha(senha, _HASH_DUMMY)
            raise NaoAutenticado("Login ou senha inválidos.")

        agora = datetime.now(UTC)
        if usuario.bloqueado_ate is not None and usuario.bloqueado_ate <= agora:
            # A janela expirou: reinicia a contagem antes de seguir. Sem isto,
            # `tentativas_falhas` fica travado em `_TENTATIVAS_MAXIMAS` para sempre — depois
            # do primeiro bloqueio, uma única tentativa errada isolada (mesmo passados
            # meses) volta a somar 5+1 e re-bloqueia por mais 15 minutos, indefinidamente.
            # Vira DoS por conta a 1 request a cada 15 min, e não exige senha nem token.
            usuario.tentativas_falhas = 0
            usuario.bloqueado_ate = None

        if usuario.bloqueado_ate is not None and usuario.bloqueado_ate > agora:
            # Verifica mesmo assim: recusar antes de chamar `verificar_senha` devolveria
            # a resposta mais rápido que o caminho de senha errada e vazaria, por timing,
            # que a conta existe e está bloqueada.
            verificar_senha(senha, usuario.senha_hash)
            raise NaoAutenticado("Login ou senha inválidos.")

        if not verificar_senha(senha, usuario.senha_hash):
            usuario.tentativas_falhas += 1
            if usuario.tentativas_falhas >= _TENTATIVAS_MAXIMAS:
                usuario.bloqueado_ate = agora + timedelta(minutes=_BLOQUEIO_MINUTOS)
            # `commit()`, não só `flush()`: `get_session()` desfaz a transação inteira
            # quando qualquer exceção sai do request — inclusive um `NaoAutenticado`
            # esperado — então sem isto o contador de tentativas nunca sobrevivia à
            # própria falha que deveria contar. É seguro fazer aqui porque `autenticar`
            # nunca toca tabela sob RLS: não há `SET LOCAL` desta transação para perder.
            await self.session.commit()
            raise NaoAutenticado("Login ou senha inválidos.")

        if not usuario.ativo:
            raise NaoAutenticado("Usuário desativado.")

        if usuario.tentativas_falhas or usuario.bloqueado_ate:
            usuario.tentativas_falhas = 0
            usuario.bloqueado_ate = None

        if precisa_reidratar_hash(usuario.senha_hash):
            usuario.senha_hash = gerar_hash_senha(senha)
        await self.session.flush()
        return usuario

    def emitir_tokens(self, usuario: Usuario, *, tenant_id: uuid.UUID | None = None) -> TokenSaida:
        return TokenSaida(
            access_token=criar_token(
                usuario.id, "access", tenant_id=tenant_id, senha_versao=usuario.senha_versao
            ),
            refresh_token=criar_token(
                usuario.id, "refresh", tenant_id=tenant_id, senha_versao=usuario.senha_versao
            ),
        )

    async def renovar(self, refresh_token: str) -> TokenSaida:
        claims = ler_claims(refresh_token, "refresh")
        usuario = await self.session.get(Usuario, claims.usuario_id)
        if usuario is None or not usuario.ativo:
            raise NaoAutenticado("Usuário do token não está ativo.")
        if claims.senha_versao != usuario.senha_versao:
            raise NaoAutenticado("Token emitido antes da última troca de senha.")
        # Preserva a empresa ativa: sem isto, todo refresh derrubava silenciosamente o
        # claim de tenant e o cliente passava a tomar 400 até chamar trocar-empresa de novo.
        return self.emitir_tokens(usuario, tenant_id=claims.tenant_id)

    async def alterar_senha(self, usuario: Usuario, senha_atual: str, senha_nova: str) -> None:
        if not verificar_senha(senha_atual, usuario.senha_hash):
            raise NaoAutenticado("Senha atual incorreta.")
        if senha_atual == senha_nova:
            raise RegraDeNegocio("A senha nova precisa ser diferente da atual.")
        usuario.senha_hash = gerar_hash_senha(senha_nova)
        usuario.senha_versao += 1
        await self.session.flush()

    async def trocar_empresa(self, usuario: Usuario, empresa_id: uuid.UUID) -> TokenSaida:
        """Reemite o token já com a empresa como claim.

        A checagem de vínculo é a mesma que `empresa_do_pedido` faz na borda — `tem_vinculo`
        filtra por `tenant_id` na própria consulta, não só via RLS, então continua correta
        aqui mesmo que este método venha a rodar sob uma conexão que não impõe a política.
        `declarar_empresa` entra antes só para que a consulta em `tem_vinculo` já saia
        naturalmente recortada quando RLS estiver valendo — é reforço, não a defesa em si.
        """
        await declarar_empresa(self.session, empresa_id)
        if not await tem_vinculo(self.session, usuario.id, empresa_id):
            raise SemVinculoComEmpresa(empresa_id)
        return self.emitir_tokens(usuario, tenant_id=empresa_id)


class GrupoService(BaseService[Grupo, GrupoCriar, GrupoAtualizar]):
    nome_recurso = "Grupo"
    colecoes_novas = ("permissoes",)
    spec = ListingSpec(
        model=Grupo,
        campos_busca=("nome", "descricao"),
        campos_ordenacao=("nome", "criado_em"),
        ordenacao_padrao="nome",
        campo_unico="nome",
    )

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
        campo_unico="login",
    )
    campos_relacao = frozenset({"grupo_ids"})

    def __init__(
        self,
        session: AsyncSession,
        usuario_id: uuid.UUID | None = None,
        tenant_id: uuid.UUID | None = None,
        *,
        ator: Usuario | None = None,
    ) -> None:
        super().__init__(session, usuario_id, tenant_id)
        # `ator` é quem está pedindo — decide *se pode*, diferente de `usuario_id`, que só
        # carimba `criado_por_id`. Nulável: nem todo caminho que usa este serviço decide
        # algo sensível (listagem, seed); `criar`/`atualizar`/`definir_senha` tratam `None`
        # como "não é superusuário" — falha fechado.
        self.ator = ator

    def _e_superusuario(self) -> bool:
        return bool(self.ator and self.ator.superusuario)

    async def _preparar_valores(self, dados: UsuarioCriar) -> dict[str, Any]:
        valores = await super()._preparar_valores(dados)
        valores.pop("senha")
        valores["senha_hash"] = gerar_hash_senha(dados.senha)
        return valores

    async def _resolver_relacoes(
        self, obj: Usuario, dados: UsuarioCriar | UsuarioAtualizar
    ) -> None:
        if dados.grupo_ids is not None:
            obj.grupos = await self._buscar_grupos(dados.grupo_ids)

    async def _antes_de_criar(self, valores: dict[str, Any]) -> None:
        # Conceder `superusuario` exige já ser superusuário: sem isto, a permissão
        # rotineira `usuario:criar` bastaria para fabricar uma conta com controle total.
        if valores.get("superusuario") and not self._e_superusuario():
            raise RegraDeNegocio(
                "Só um superusuário pode criar outro superusuário.",
                codigo="escalada_de_privilegio",
            )
        await super()._antes_de_criar(valores)

    async def _antes_de_atualizar(self, obj: Usuario, valores: dict[str, Any]) -> None:
        # Editar qualquer campo de um superusuário exige ser superusuário — inclusive para
        # *tirar* o `superusuario` de alguém, senão um `usuario:editar` comum rebaixaria o
        # superusuário de propósito e assumiria o papel sozinho depois.
        if obj.superusuario and not self._e_superusuario():
            raise RegraDeNegocio(
                "Só um superusuário pode alterar outro superusuário.",
                codigo="escalada_de_privilegio",
            )
        if valores.get("superusuario") and not self._e_superusuario():
            raise RegraDeNegocio(
                "Só um superusuário pode conceder superusuário.",
                codigo="escalada_de_privilegio",
            )
        # `PUT {"ativo": false}` é a mesma transição de estado que `DELETE`, por outra
        # rota — e `_antes_de_desativar` só roda para o `DELETE`. Sem isto, a regra "um
        # usuário não pode desativar a si mesmo" valia numa rota e não na outra.
        if (
            valores.get("ativo") is False
            and self.usuario_id is not None
            and obj.id == self.usuario_id
        ):
            raise RegraDeNegocio("Um usuário não pode desativar a si mesmo.")
        await super()._antes_de_atualizar(obj, valores)

    async def definir_senha(self, id_: uuid.UUID, senha_nova: str) -> Usuario:
        usuario = await self.obter(id_)
        # Mesma trava: `usuario:editar` não é permissão para assumir a conta de um
        # superusuário redefinindo a senha dele e logando como ele.
        if usuario.superusuario and not self._e_superusuario():
            raise RegraDeNegocio(
                "Só um superusuário pode redefinir a senha de outro superusuário.",
                codigo="escalada_de_privilegio",
            )
        usuario.senha_hash = gerar_hash_senha(senha_nova)
        usuario.senha_versao += 1
        await self.session.flush()
        return usuario

    async def _antes_de_desativar(self, obj: Usuario) -> None:
        if self.usuario_id is not None and obj.id == self.usuario_id:
            raise RegraDeNegocio("Um usuário não pode desativar a si mesmo.")
        # Mesma trava de criar/atualizar/definir_senha: `usuario:excluir` é permissão de
        # cadastro rotineira, não autorização para tirar um superusuário do ar. Sem isto,
        # `DELETE` vira o caminho que ignora a proteção que `PUT {"ativo": false}` já tem —
        # e como não há rota de reativação além desta, o dano seria irreversível pela API.
        if obj.superusuario and not self._e_superusuario():
            raise RegraDeNegocio(
                "Só um superusuário pode desativar outro superusuário.",
                codigo="escalada_de_privilegio",
            )

    async def _antes_de_reativar(self, obj: Usuario) -> None:
        if obj.superusuario and not self._e_superusuario():
            raise RegraDeNegocio(
                "Só um superusuário pode reativar outro superusuário.",
                codigo="escalada_de_privilegio",
            )

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
