from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

from tests import banco

# Tudo daqui até o primeiro `import app.*` precisa acontecer nesta ordem: a config do VITRA
# é lida na importação do módulo, então o banco tem que existir e estar no ambiente antes.
#
# `VITRA_DATABASE_URL` sobrescreve o que estiver no `.env` — variável de ambiente vence
# arquivo no pydantic-settings. É o que garante que rodar a suíte nunca toque no banco de
# desenvolvimento de ninguém, mesmo com `.env` apontando para lá.
os.environ["VITRA_AMBIENTE"] = "teste"
BANCO = banco.iniciar()
os.environ["VITRA_DATABASE_URL"] = BANCO.url_dono

import pytest  # noqa: E402
from alembic.config import Config as AlembicConfig  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool  # noqa: E402

from alembic import command  # noqa: E402
from app.core.config import config  # noqa: E402
from app.core.db import get_session  # noqa: E402
from app.core.permissions import pares_do_catalogo  # noqa: E402
from app.core.security import gerar_hash_senha  # noqa: E402
from app.main import criar_app  # noqa: E402
from app.modules.auth.models import Grupo, Permissao, Usuario  # noqa: E402
from app.modules.empresa.models import Empresa  # noqa: E402
from tests.bakeoff import (  # noqa: E402
    Cenario,
    UsuarioDeTeste,
    criar_usuario_sem_email,
    criar_usuario_vinculado,
    montar_cenario,
)

SENHA_PADRAO = "senha-de-teste-123"


@pytest.fixture(scope="session", autouse=True)
def schema() -> Iterator[None]:
    """Monta o schema uma vez por execução, **aplicando as migrações**.

    Usar `Base.metadata.create_all` aqui seria mais rápido e mentiria de dois jeitos: o
    schema dos testes passaria a ser o do modelo em vez do que o Alembic produz (foi assim
    que as FKs de `criado_por_id` sumiram da migração inicial sem nenhum teste reclamar),
    e o **RLS não existiria** — `create_all` não cria política, e a suíte inteira de
    isolamento passaria contra um banco sem trava nenhuma.

    Fixture síncrona de propósito: o `env.py` do Alembic abre o próprio event loop.
    """

    async def _zerar() -> None:
        motor = create_async_engine(config.database_url, poolclass=NullPool)
        async with motor.begin() as conn:
            await conn.execute(text("DROP SCHEMA public CASCADE"))
            await conn.execute(text("CREATE SCHEMA public"))
        await motor.dispose()

    asyncio.run(_zerar())

    raiz = Path(__file__).resolve().parents[1]
    cfg = AlembicConfig(str(raiz / "alembic.ini"))
    cfg.set_main_option("script_location", str(raiz / "alembic"))
    command.upgrade(cfg, "head")

    # Depois das migrações: é a migração de RLS que cria o papel de grupo `vitra_app`.
    asyncio.run(banco.provisionar_papel_runtime(BANCO.url_dono))

    yield
    banco.encerrar()


@pytest.fixture
async def motor() -> AsyncIterator[AsyncEngine]:
    """Engine do **dono** do banco. Serve para montar fixtures, não para testar RLS."""
    engine = create_async_engine(config.database_url, poolclass=NullPool)
    yield engine
    await engine.dispose()


@pytest.fixture
async def motor_runtime() -> AsyncIterator[AsyncEngine]:
    """Engine do papel que a aplicação usa: não é dono e não tem BYPASSRLS.

    Todo teste de isolamento passa por aqui. Um que use `motor` em vez deste passa sempre —
    e não prova nada, porque o superusuário do container ignora política por definição.
    """
    engine = create_async_engine(BANCO.url_runtime, poolclass=NullPool)
    yield engine
    await engine.dispose()


@pytest.fixture
async def sessao(motor: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """Cada teste roda dentro de uma transação que é desfeita no fim.

    `join_transaction_mode="create_savepoint"` deixa o código sob teste chamar `commit()`
    sem encerrar a transação externa — o rollback final continua limpando tudo.
    """
    async with motor.connect() as conn:
        transacao = await conn.begin()
        session = AsyncSession(
            bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False
        )
        try:
            yield session
        finally:
            await session.close()
            await transacao.rollback()


@pytest.fixture
async def app_teste(sessao: AsyncSession) -> FastAPI:
    app = criar_app()

    async def _sessao_de_teste() -> AsyncIterator[AsyncSession]:
        try:
            yield sessao
            await sessao.commit()
        except Exception:
            await sessao.rollback()
            raise

    app.dependency_overrides[get_session] = _sessao_de_teste
    return app


@pytest.fixture
async def cliente(app_teste: FastAPI) -> AsyncIterator[AsyncClient]:
    transporte = ASGITransport(app=app_teste)
    async with AsyncClient(transport=transporte, base_url="http://teste") as c:
        yield c


# --- bake-off ----------------------------------------------------------------


@pytest.fixture
async def cenario(motor_runtime: AsyncEngine) -> Cenario:
    """Duas empresas com catálogos disjuntos, montadas **pelo papel de runtime**.

    Montar pelo dono seria mais fácil e esvaziaria o exercício: provaria que o RLS filtra
    leitura, mas não que a aplicação consegue *escrever* sob a política.
    """
    return await montar_cenario(motor_runtime)


@pytest.fixture
async def app_bakeoff() -> AsyncIterator[FastAPI]:
    """App com pool de conexão de verdade, sem a sessão compartilhada dos testes da S0.

    O `app_teste` injeta **uma** sessão em todos os pedidos, o que serve para isolar dado
    de teste e destrói o que o bake-off precisa medir: dois pedidos concorrentes têm que
    disputar conexões de um pool real, senão o teste de concorrência não testa nada.

    `pool_size=2` com `max_overflow=0`: pequeno o bastante para forçar reuso de conexão
    entre pedidos — que é exatamente onde um `SET` no lugar de `SET LOCAL` vazaria.
    """
    motor = create_async_engine(BANCO.url_runtime, pool_size=2, max_overflow=0)
    fabrica = async_sessionmaker(motor, expire_on_commit=False, autoflush=False)

    async def _sessao() -> AsyncIterator[AsyncSession]:
        async with fabrica() as sessao:
            try:
                yield sessao
            except Exception:
                await sessao.rollback()
                raise
            else:
                await sessao.commit()

    app = criar_app()
    app.dependency_overrides[get_session] = _sessao
    yield app
    await motor.dispose()


@pytest.fixture
async def cliente_bakeoff(app_bakeoff: FastAPI) -> AsyncIterator[AsyncClient]:
    """Cliente **sem** credencial. Serve para provar que as rotas exigem token."""
    transporte = ASGITransport(app=app_bakeoff)
    async with AsyncClient(transport=transporte, base_url="http://teste") as c:
        yield c


@pytest.fixture
async def usuario_das_duas(motor_runtime: AsyncEngine, cenario: Cenario) -> UsuarioDeTeste:
    """Quem tem vínculo com as **duas** empresas — o caso da ANA SILVA."""
    return await criar_usuario_vinculado(
        motor_runtime, cenario, empresas=(cenario.abacaxi, cenario.uva)
    )


@pytest.fixture
async def email_do_token(usuario_das_duas: UsuarioDeTeste) -> str:
    """O e-mail que liga `usuario` a `employees` — a ponte que a autorização percorre."""
    return usuario_das_duas.email


@pytest.fixture
async def usuario_so_abacaxi(motor_runtime: AsyncEngine, cenario: Cenario) -> UsuarioDeTeste:
    """Quem só trabalha na ABACAXI. Pedir a UVA com este token tem que dar 403."""
    return await criar_usuario_vinculado(
        motor_runtime, cenario, empresas=(cenario.abacaxi,), sufixo_login="-aba"
    )


def _cliente_com_token(app: FastAPI, token: str) -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://teste",
        headers={"Authorization": f"Bearer {token}"},
    )


@pytest.fixture
async def autenticado(
    app_bakeoff: FastAPI, usuario_das_duas: UsuarioDeTeste
) -> AsyncIterator[AsyncClient]:
    """Cliente já com o Bearer no cabeçalho padrão — o caminho feliz das rotas do módulo."""
    async with _cliente_com_token(app_bakeoff, usuario_das_duas.token) as c:
        yield c


@pytest.fixture
async def so_abacaxi(
    app_bakeoff: FastAPI, usuario_so_abacaxi: UsuarioDeTeste
) -> AsyncIterator[AsyncClient]:
    """Cliente de quem só trabalha na ABACAXI. Pedir a UVA com ele tem que dar 403."""
    async with _cliente_com_token(app_bakeoff, usuario_so_abacaxi.token) as c:
        yield c


@pytest.fixture
async def sem_email(
    app_bakeoff: FastAPI, motor_runtime: AsyncEngine, cenario: Cenario
) -> AsyncIterator[AsyncClient]:
    """Cliente de um usuário sem e-mail — a ponte para `employees` não fecha."""
    token = await criar_usuario_sem_email(motor_runtime, cenario)
    async with _cliente_com_token(app_bakeoff, token) as c:
        yield c


# --- dados ------------------------------------------------------------------


@pytest.fixture
async def permissoes(sessao: AsyncSession) -> list[Permissao]:
    itens = [
        Permissao(recurso=recurso, acao=acao, descricao=f"{acao} {recurso}")
        for recurso, acao in pares_do_catalogo()
    ]
    sessao.add_all(itens)
    await sessao.flush()
    return itens


@pytest.fixture
async def empresa(sessao: AsyncSession) -> Empresa:
    obj = Empresa(codigo="VERTZ", razao_social="Vertz Iluminação Ltda", nome_fantasia="Vertz")
    sessao.add(obj)
    await sessao.flush()
    return obj


@pytest.fixture
async def admin(sessao: AsyncSession, empresa: Empresa) -> Usuario:
    usuario = Usuario(
        login="admin",
        nome="Administrador",
        senha_hash=gerar_hash_senha(SENHA_PADRAO),
        superusuario=True,
        empresa_id=empresa.id,
    )
    sessao.add(usuario)
    await sessao.flush()
    return usuario


@pytest.fixture
async def consultor(sessao: AsyncSession, empresa: Empresa, permissoes: list[Permissao]) -> Usuario:
    """Só enxerga apoio, e só para ler. Serve para provar que o RBAC bloqueia."""
    grupo = Grupo(nome="Consultor", descricao="Somente leitura de apoio")
    grupo.permissoes = [p for p in permissoes if p.recurso == "apoio" and p.acao == "ler"]
    sessao.add(grupo)
    usuario = Usuario(
        login="consultor",
        nome="Consultor de Vendas",
        senha_hash=gerar_hash_senha(SENHA_PADRAO),
        empresa_id=empresa.id,
    )
    usuario.grupos = [grupo]
    sessao.add(usuario)
    await sessao.flush()
    return usuario


async def autenticar(cliente: AsyncClient, login: str, senha: str = SENHA_PADRAO) -> dict[str, str]:
    resposta = await cliente.post("/api/v1/auth/login", json={"login": login, "senha": senha})
    assert resposta.status_code == 200, resposta.text
    return {"Authorization": f"Bearer {resposta.json()['access_token']}"}


@pytest.fixture
async def cabecalho_admin(cliente: AsyncClient, admin: Usuario) -> dict[str, str]:
    return await autenticar(cliente, admin.login)


@pytest.fixture
async def cabecalho_consultor(cliente: AsyncClient, consultor: Usuario) -> dict[str, str]:
    return await autenticar(cliente, consultor.login)
