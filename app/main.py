from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import config
from app.core.db import engine
from app.core.errors import registrar_handlers
from app.core.openapi import documentar_erros
from app.modules.apoio.router import routers as routers_apoio
from app.modules.auth.router import routers as routers_auth
from app.modules.bakeoff.router import routers as routers_bakeoff
from app.modules.empresa.router import routers as routers_empresa

DESCRICAO = """
Backend do VITRA — núcleo comercial, substituto do SoftLux.

**S0 — Fundação:** autenticação JWT, RBAC granular recurso+ação, empresa/filial/centro de custo
e a tabela de apoio genérica que cobre os 19 combos das telas do legado.

**SB — Bake-off:** as 7 tabelas do schema compartilhado, com chave primária composta
`(tenant_id, id)` e multiempresa imposta por Row-Level Security. As rotas marcadas
`bake-off` exigem o cabeçalho **`X-Empresa-Id`**: a empresa ativa entra na transação
(`SET LOCAL app.current_tenant`), nunca na query string. Sem o cabeçalho a resposta é
`400`; com a empresa errada, a listagem simplesmente não enxerga o dado da outra.
"""


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    await engine.dispose()


def criar_app() -> FastAPI:
    app = FastAPI(
        title="VITRA API",
        description=DESCRICAO,
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs",
        openapi_url="/openapi.json",
    )

    if config.cors_origens:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=config.cors_origens,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    registrar_handlers(app)

    api = APIRouter(prefix=config.api_prefix)
    for router in [*routers_auth, *routers_empresa, *routers_apoio, *routers_bakeoff]:
        api.include_router(router)
    app.include_router(api)

    @app.get("/saude", tags=["infra"])
    async def saude() -> dict[str, str]:
        return {"status": "ok", "ambiente": config.ambiente}

    # Depois das rotas: a leitura das falhas percorre o grafo de dependências já montado.
    documentar_erros(app)

    return app


app = criar_app()
