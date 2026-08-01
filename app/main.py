from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.core.config import config
from app.core.db import engine
from app.core.errors import registrar_handlers
from app.core.openapi import documentar_erros
from app.modules.apoio.router import routers as routers_apoio
from app.modules.auth.router import routers as routers_auth
from app.modules.empresa.router import routers as routers_empresa
from app.modules.produtos.router import routers as routers_produtos

DESCRICAO = """
Backend do VITRA — núcleo comercial, substituto do SoftLux.

Autenticação JWT, RBAC granular recurso+ação, cadastros (empresa/filial/centro de custo,
produtos) e a tabela de apoio genérica que cobre os 19 combos das telas do legado.

**Multiempresa por Row-Level Security.** Toda tabela por empresa tem chave primária
composta `(tenant_id, id)` e é recortada pelo Postgres, não pelo serviço. A empresa ativa
entra na transação a partir de um claim no token (`POST /auth/trocar-empresa`) ou do
cabeçalho **`X-Empresa-Id`**, que tem prioridade quando presente — é o caminho de quem tem
vínculo em mais de uma empresa. Sem nenhuma das duas a resposta é `400`; com a empresa
errada, a listagem simplesmente não enxerga o dado da outra.
"""


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    if config.ambiente == "producao":
        await _recusar_subir_sem_rls()
    yield
    await engine.dispose()


async def _recusar_subir_sem_rls() -> None:
    """A propriedade "a aplicação não é dono nem tem BYPASSRLS" hoje só é afirmada por um
    comentário em `config.py`, um `.sql` de implantação e um teste que prova o papel **de
    teste**, não o implantado. Se `VITRA_DATABASE_URL` apontar para o dono numa implantação
    futura — troca de variável, ambiente mal configurado — o RLS vira decorativo em
    silêncio: `tem_vinculo` continua barrando (filtra `tenant_id` explicitamente), mas todo
    o resto do schema vaza entre empresas sem ninguém perceber. Mesma consulta de
    `test_papel_de_runtime_nao_e_superusuario_nem_bypassrls`, rodada contra o banco real.
    """
    async with engine.connect() as conexao:
        linha = (
            await conexao.execute(
                text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
            )
        ).one()
    if linha.rolsuper or linha.rolbypassrls:
        raise RuntimeError(
            "A aplicação conectou como superusuário ou com BYPASSRLS — o Row-Level "
            "Security ficaria decorativo. Corrija VITRA_DATABASE_URL para o papel de "
            "runtime (sem BYPASSRLS, não dono das tabelas)."
        )


def criar_app() -> FastAPI:
    # Em produção, `/docs` e `/openapi.json` saem do ar: o contrato já é publicado como
    # arquivo versionado (`make openapi`), e servir o schema completo — rotas, formatos de
    # erro, nomes internos — publicamente não tem contrapartida depois que o front já gera
    # o cliente a partir do arquivo. `None` desliga a rota; `scripts/exportar_openapi.py`
    # continua funcionando porque chama `app.openapi()` direto, sem depender da URL.
    publicar_docs = config.ambiente != "producao"
    app = FastAPI(
        title="VITRA API",
        description=DESCRICAO,
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if publicar_docs else None,
        openapi_url="/openapi.json" if publicar_docs else None,
    )

    if config.cors_origens:
        # `allow_credentials=True` só é seguro com origem explícita: com `"*"` no meio de
        # `VITRA_CORS_ORIGENS`, o Starlette passa a ecoar de volta a origem do próprio
        # pedido (é a exigência da spec do CORS para coringa + credencial) — o que na
        # prática autoriza qualquer site a mandar o Bearer do usuário. A API é Bearer, não
        # cookie, então não precisa de `allow_credentials` para funcionar; ele só existe
        # para quem hospedar o front em subdomínio com cookie de sessão no futuro.
        coringa = "*" in config.cors_origens
        app.add_middleware(
            CORSMiddleware,
            allow_origins=config.cors_origens,
            allow_credentials=not coringa,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    registrar_handlers(app)

    api = APIRouter(prefix=config.api_prefix)
    for router in [*routers_auth, *routers_empresa, *routers_apoio, *routers_produtos]:
        api.include_router(router)
    app.include_router(api)

    @app.get("/saude", tags=["infra"])
    async def saude() -> dict[str, str]:
        return {"status": "ok", "ambiente": config.ambiente}

    # Depois das rotas: a leitura das falhas percorre o grafo de dependências já montado.
    documentar_erros(app)

    return app


app = criar_app()
