from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from pathlib import Path

# Precisa vir antes de qualquer import de app.*: a config é lida na importação.
os.environ["VITRA_AMBIENTE"] = "teste"

import pytest  # noqa: E402
from alembic.config import Config as AlembicConfig  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

from alembic import command  # noqa: E402
from app.core.config import config  # noqa: E402
from app.core.db import get_session  # noqa: E402
from app.core.permissions import pares_do_catalogo  # noqa: E402
from app.core.security import gerar_hash_senha  # noqa: E402
from app.main import criar_app  # noqa: E402
from app.modules.auth.models import Grupo, Permissao, Usuario  # noqa: E402
from app.modules.empresa.models import Empresa  # noqa: E402

SENHA_PADRAO = "senha-de-teste-123"


@pytest.fixture(scope="session", autouse=True)
def schema() -> None:
    """Recria o schema uma vez por execução, **aplicando as migrações**.

    Usar `Base.metadata.create_all` aqui seria mais rápido e mentiria: o schema dos testes
    passaria a ser o do modelo, não o que o Alembic realmente produz. Foi assim que as FKs
    de `criado_por_id` sumiram da migração inicial sem nenhum teste reclamar.

    Fixture síncrona de propósito: o `env.py` do Alembic abre o próprio event loop.
    """

    async def _zerar() -> None:
        motor = create_async_engine(config.url_efetiva, poolclass=NullPool)
        async with motor.begin() as conn:
            await conn.execute(text("DROP SCHEMA public CASCADE"))
            await conn.execute(text("CREATE SCHEMA public"))
        await motor.dispose()

    asyncio.run(_zerar())

    raiz = Path(__file__).resolve().parents[1]
    cfg = AlembicConfig(str(raiz / "alembic.ini"))
    cfg.set_main_option("script_location", str(raiz / "alembic"))
    command.upgrade(cfg, "head")


@pytest.fixture
async def motor() -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(config.url_efetiva, poolclass=NullPool)
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
async def consultor(
    sessao: AsyncSession, empresa: Empresa, permissoes: list[Permissao]
) -> Usuario:
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
    resposta = await cliente.post(
        "/api/v1/auth/login", json={"login": login, "senha": senha}
    )
    assert resposta.status_code == 200, resposta.text
    return {"Authorization": f"Bearer {resposta.json()['access_token']}"}


@pytest.fixture
async def cabecalho_admin(cliente: AsyncClient, admin: Usuario) -> dict[str, str]:
    return await autenticar(cliente, admin.login)


@pytest.fixture
async def cabecalho_consultor(cliente: AsyncClient, consultor: Usuario) -> dict[str, str]:
    return await autenticar(cliente, consultor.login)
