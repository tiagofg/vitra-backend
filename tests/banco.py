"""Sobe o Postgres descartável da suíte e provisiona o papel de runtime.

Importado por `conftest.py` **antes** de qualquer `import app.*`: a config do VITRA é lida
na importação, então a URL do banco precisa já estar no ambiente quando isso acontece.

Por que Postgres descartável e não o container fixo do docker-compose: o que esta fase
testa é política de segurança, e política que sobra de uma execução para a outra faz um
teste de isolamento passar por acidente. Cada execução recria o RLS do zero, a partir das
migrações — o que também prova que o RLS está *na migração*, e não só no banco de alguém.
"""

from __future__ import annotations

import os
import warnings
from dataclasses import dataclass

from testcontainers.community.postgres import PostgresContainer

# Postgres 17, igual ao alvo. `FORCE ROW LEVEL SECURITY` e `current_setting(..., true)`
# existem há muitas versões, mas testar noutra versão da de produção é dívida gratuita.
IMAGEM = os.environ.get("VITRA_TESTE_IMAGEM_PG", "postgres:17-alpine")

# Usuário que a *aplicação* usa nos testes: membro de `vitra_app`, sem ser dono de nada e
# sem BYPASSRLS. Ele é o ponto inteiro do exercício — conectar como dono ou superusuário
# faria o RLS ser ignorado e os quatro testes de isolamento passariam sem provar nada.
USUARIO_RUNTIME = "vitra_runtime"
SENHA_RUNTIME = "runtime-de-teste"

# Papel de grupo criado pela migração de RLS. É nele que moram os privilégios de DML.
PAPEL_GRUPO = "vitra_app"

# O Ryuk é o container que o testcontainers usa para varrer sobras. Ele precisa de acesso
# ao socket do Docker que nem todo ambiente concede — e a suíte já para o container dela
# em `encerrar()`. Sem isto, o `atexit` do reaper falha ruidosamente no fim de cada rodada.
os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")


@dataclass(frozen=True)
class BancoDeTeste:
    """As duas identidades do mesmo banco.

    `url_dono` roda as migrações e monta fixtures sem esbarrar em política. `url_runtime` é
    o que a aplicação enxerga. Manter as duas explícitas evita o engano mais caro daqui:
    escrever um teste de RLS que, sem querer, conecta como dono.
    """

    url_dono: str
    url_runtime: str


_container: PostgresContainer | None = None


def iniciar() -> BancoDeTeste:
    """Sobe o container (ou reaproveita um banco externo) e devolve as duas URLs.

    `VITRA_TESTE_URL_EXTERNA` existe para o dev que já tem um Postgres à mão e não quer
    esperar o container a cada rodada. O CI não usa: lá o container é o ponto.
    """
    global _container

    externa = os.environ.get("VITRA_TESTE_URL_EXTERNA")
    if externa:
        return BancoDeTeste(url_dono=externa, url_runtime=_trocar_credenciais(externa))

    _container = PostgresContainer(IMAGEM, driver="asyncpg")
    _container.start()
    url_dono = _container.get_connection_url()
    return BancoDeTeste(url_dono=url_dono, url_runtime=_trocar_credenciais(url_dono))


def encerrar() -> None:
    """Derruba o container. Falhar aqui **não** reprova a suíte.

    Há ambientes (Docker rootless, sandbox com syscall de kill restrita) em que parar o
    container é negado mesmo com os testes todos verdes. Deixar a exceção subir trocaria
    "76 passaram" por "erro na sessão" — reportaria falha de teste onde só houve sobra de
    container, que é descartável por construção e some com o runner.
    """
    global _container
    if _container is None:
        return
    try:
        _container.stop()
    except Exception as exc:  # noqa: BLE001 — o motivo não muda o que fazemos
        warnings.warn(
            f"Container de teste não pôde ser removido ({exc}). "
            "Os testes não são afetados; limpe com `docker rm -f` se sobrar.",
            RuntimeWarning,
            stacklevel=2,
        )
    finally:
        _container = None


async def provisionar_papel_runtime(url_dono: str) -> None:
    """Cria o usuário de login e o põe dentro do papel `vitra_app` criado pela migração.

    Chamado **depois** do `alembic upgrade head`: é a migração que cria `vitra_app` e
    concede os privilégios de DML. Aqui só nasce a identidade que loga.

    Em produção o passo equivalente é o mesmo, com senha de verdade vinda do ambiente:
    o papel de grupo é schema e vive na migração; o usuário com senha não entra no repo.
    """
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    # `CREATE ROLE` não aceita parâmetro ligado — nome e senha entram interpolados. São
    # constantes deste módulo, nunca entrada de teste, e o banco é descartável.
    comandos = (
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{USUARIO_RUNTIME}') THEN
                CREATE ROLE {USUARIO_RUNTIME} LOGIN NOBYPASSRLS PASSWORD '{SENHA_RUNTIME}';
            END IF;
        END
        $$
        """,
        f"GRANT {PAPEL_GRUPO} TO {USUARIO_RUNTIME}",
        # Sem `GRANT USAGE ON SCHEMA public` avulso e sem `ON ALL TABLES`: desde a
        # unificação (S0.5), toda tabela — global ou por empresa — recebe seu `GRANT` na
        # própria migração de RLS, junto com o papel de grupo `vitra_app`. Dar mais que
        # isso aqui mascararia uma tabela nova que esqueceu de entrar na migração.
    )

    motor = create_async_engine(url_dono, poolclass=NullPool, isolation_level="AUTOCOMMIT")
    async with motor.connect() as conexao:
        for comando in comandos:
            await conexao.execute(text(comando))
    await motor.dispose()


def _trocar_credenciais(url: str) -> str:
    """Mesma máquina, mesmo banco, outro usuário — o que a aplicação usaria.

    `render_as_string(hide_password=False)` e não `str(url)`: o `__str__` do SQLAlchemy
    troca a senha por `***` para não vazá-la em log, e a URL resultante não conecta.
    """
    from sqlalchemy.engine import make_url

    nova = make_url(url).set(username=USUARIO_RUNTIME, password=SENHA_RUNTIME)
    return nova.render_as_string(hide_password=False)
