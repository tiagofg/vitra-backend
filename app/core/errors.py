from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
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


class ErroDetalhe(BaseModel):
    codigo: str = Field(
        description=(
            "Identificador estável da falha — é por ele que o cliente decide o que fazer, "
            "nunca pela mensagem."
        ),
        examples=["nao_encontrado"],
    )
    mensagem: str = Field(
        description="Texto pronto para exibição, em português.",
        examples=["Empresa 6f1c… não encontrado."],
    )
    campos: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Detalhe por campo, quando existe: em `validacao` é `campo → motivo`; nas demais, "
            "o contexto da falha. Pode vir vazio."
        ),
    )


class EnvelopeErro(BaseModel):
    """O corpo de **toda** resposta de erro da API, do 400 ao 500.

    Existe como modelo, e não só como o dicionário que o handler monta, porque o contrato
    OpenAPI é o substituto do tRPC para o front: sem um schema aqui, o cliente gerado não
    conhece nenhum caminho de erro. `envelope()` constrói por este modelo justamente para
    que documentação e resposta não possam divergir.
    """

    erro: ErroDetalhe


def envelope(codigo: str, mensagem: str, campos: dict[str, Any] | None = None) -> dict[str, Any]:
    detalhe = ErroDetalhe(codigo=codigo, mensagem=mensagem, campos=campos or {})
    return EnvelopeErro(erro=detalhe).model_dump(mode="json")


# --- o que cada rota pode responder de errado --------------------------------

ATRIBUTO_FALHAS = "__vitra_falhas__"

F = TypeVar("F", bound=Callable[..., Any])


@dataclass(frozen=True)
class Falha:
    """Uma resposta de erro possível, do jeito que ela sai na resposta de verdade.

    `app/core/openapi.py` recolhe as falhas de cada rota e as escreve no contrato. O
    exemplo publicado sai de `envelope()` — a mesma função do handler —, então um campo
    que mude de nome muda nos dois lugares de uma vez.
    """

    status: int
    codigo: str
    descricao: str
    mensagem: str
    campos: dict[str, Any] = field(default_factory=dict)

    @property
    def exemplo(self) -> dict[str, Any]:
        return envelope(self.codigo, self.mensagem, self.campos)


def pode_falhar(*falhas: Falha) -> Callable[[F], F]:
    """Declara falhas que só o corpo da rota conhece — 404, 409, regra de negócio.

    As falhas da borda (token, empresa, permissão, ordenação) não usam isto: elas são
    declaradas **na dependência** que as levanta e chegam à rota pelo grafo do FastAPI,
    para que nenhuma rota precise repetir o que já depende.
    """

    def marcar(alvo: F) -> F:
        anteriores: tuple[Falha, ...] = getattr(alvo, ATRIBUTO_FALHAS, ())
        setattr(alvo, ATRIBUTO_FALHAS, (*anteriores, *falhas))
        return alvo

    return marcar


NAO_AUTENTICADO = Falha(
    status=NaoAutenticado.http_status,
    codigo=NaoAutenticado.codigo,
    descricao="Token ausente, expirado, inválido, ou de usuário que não existe mais.",
    mensagem="Credenciais ausentes ou inválidas.",
)

NAO_ENCONTRADO = Falha(
    status=NaoEncontrado.http_status,
    codigo=NaoEncontrado.codigo,
    descricao="O identificador da rota não corresponde a nenhum registro visível.",
    mensagem="Empresa 6f1c8f0a-1f1e-4a5b-9d3c-2b7a5e4f8c10 não encontrado.",
)

CONFLITO = Falha(
    status=Conflito.http_status,
    codigo=Conflito.codigo,
    descricao="Viola unicidade ou um vínculo do banco — código, login ou e-mail repetido.",
    mensagem="Já existe empresa com código 'VITRA'.",
    campos={"codigo": "já utilizado"},
)

REGRA_DE_NEGOCIO = Falha(
    status=RegraDeNegocio.http_status,
    codigo=RegraDeNegocio.codigo,
    descricao="A operação é sintaticamente válida, mas o domínio a recusa.",
    mensagem="Um usuário não pode desativar a si mesmo.",
)

VALIDACAO = Falha(
    status=HTTP_422,
    codigo="validacao",
    descricao="Corpo, query ou cabeçalho fora do schema.",
    mensagem="Dados inválidos.",
    campos={"nome": "Field required"},
)


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
