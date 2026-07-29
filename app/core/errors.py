from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException

# Literal em vez da constante: o nome dela mudou entre versões do Starlette
# (UNPROCESSABLE_ENTITY → UNPROCESSABLE_CONTENT) e o número não muda.
HTTP_422 = 422


class ErroDominio(Exception):
    """Base de todas as exceções de negócio. Vira o envelope {erro: {...}}."""

    http_status: int = status.HTTP_400_BAD_REQUEST
    codigo: str = "erro_dominio"

    def __init__(
        self,
        mensagem: str,
        *,
        codigo: str | None = None,
        campos: dict[str, str] | None = None,
    ) -> None:
        super().__init__(mensagem)
        self.mensagem = mensagem
        if codigo is not None:
            self.codigo = codigo
        self.campos = campos or {}


class NaoEncontrado(ErroDominio):
    http_status = status.HTTP_404_NOT_FOUND
    codigo = "nao_encontrado"

    def __init__(self, recurso: str, identificador: Any = None) -> None:
        alvo = f"{recurso} {identificador}" if identificador is not None else recurso
        super().__init__(f"{alvo} não encontrado.")


class Conflito(ErroDominio):
    """Violação de unicidade ou estado incompatível."""

    http_status = status.HTTP_409_CONFLICT
    codigo = "conflito"


class RegraDeNegocio(ErroDominio):
    http_status = HTTP_422
    codigo = "regra_de_negocio"


class NaoAutenticado(ErroDominio):
    http_status = status.HTTP_401_UNAUTHORIZED
    codigo = "nao_autenticado"

    def __init__(self, mensagem: str = "Credenciais ausentes ou inválidas.") -> None:
        super().__init__(mensagem)


class SemPermissao(ErroDominio):
    http_status = status.HTTP_403_FORBIDDEN
    codigo = "sem_permissao"

    def __init__(self, recurso: str, acao: str) -> None:
        super().__init__(
            f"Usuário não tem permissão de '{acao}' sobre '{recurso}'.",
            campos={"recurso": recurso, "acao": acao},
        )
        self.recurso = recurso
        self.acao = acao


def envelope(codigo: str, mensagem: str, campos: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"erro": {"codigo": codigo, "mensagem": mensagem, "campos": campos or {}}}


def registrar_handlers(app: FastAPI) -> None:
    """Todo erro que sai da API usa o mesmo envelope."""

    @app.exception_handler(ErroDominio)
    async def _dominio(_: Request, exc: ErroDominio) -> JSONResponse:
        headers = {"WWW-Authenticate": "Bearer"} if isinstance(exc, NaoAutenticado) else None
        return JSONResponse(
            status_code=exc.http_status,
            content=envelope(exc.codigo, exc.mensagem, exc.campos),
            headers=headers,
        )

    @app.exception_handler(RequestValidationError)
    async def _validacao(_: Request, exc: RequestValidationError) -> JSONResponse:
        campos: dict[str, Any] = {}
        for erro in exc.errors():
            caminho = ".".join(str(p) for p in erro["loc"][1:]) or str(erro["loc"][0])
            campos[caminho] = erro["msg"]
        return JSONResponse(
            status_code=HTTP_422,
            content=envelope("validacao", "Dados inválidos.", campos),
        )

    @app.exception_handler(IntegrityError)
    async def _integridade(_: Request, exc: IntegrityError) -> JSONResponse:
        detalhe = getattr(getattr(exc, "orig", None), "detail", None)
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content=envelope(
                "conflito",
                "Operação viola uma restrição do banco (registro duplicado ou vínculo inválido).",
                {"detalhe": detalhe} if detalhe else None,
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=envelope(f"http_{exc.status_code}", str(exc.detail)),
            headers=getattr(exc, "headers", None),
        )
