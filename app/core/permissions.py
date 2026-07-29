from __future__ import annotations

import enum
from collections.abc import Callable, Coroutine
from typing import Any

from app.core.deps import UsuarioAtual
from app.core.errors import SemPermissao
from app.modules.auth.models import Usuario


class Acao(enum.StrEnum):
    ler = "ler"
    criar = "criar"
    editar = "editar"
    excluir = "excluir"
    cancelar = "cancelar"
    fechar = "fechar"
    aprovar = "aprovar"
    importar = "importar"


CRUD = (Acao.ler, Acao.criar, Acao.editar, Acao.excluir)

# Catálogo canônico de permissões. Cresce a cada fase; o seed sincroniza a tabela
# `permissao` a partir daqui — nunca à mão no banco.
CATALOGO: dict[str, tuple[Acao, ...]] = {
    "usuario": CRUD,
    "grupo": CRUD,
    "permissao": (Acao.ler,),
    "empresa": CRUD,
    "filial": CRUD,
    "centro_custo": CRUD,
    "apoio": CRUD,
    "cidade": CRUD,
    "banco": CRUD,
    "uf": (Acao.ler,),
}


def pares_do_catalogo() -> list[tuple[str, str]]:
    return [(recurso, acao.value) for recurso, acoes in CATALOGO.items() for acao in acoes]


def require(
    recurso: str, acao: Acao | str
) -> Callable[[Usuario], Coroutine[Any, Any, Usuario]]:
    """Dependência de rota: `Depends(require("apoio", Acao.criar))`.

    Espelha `Controle de Acesso → Permissões de Acesso` do legado: a permissão é o par
    recurso+ação, concedido a grupos; usuário herda dos grupos.
    """
    acao_str = acao.value if isinstance(acao, Acao) else acao
    if (recurso, acao_str) not in pares_do_catalogo():
        raise KeyError(f"Permissão '{recurso}:{acao_str}' não está no catálogo.")

    async def _verificar(usuario: UsuarioAtual) -> Usuario:
        if not usuario.pode(recurso, acao_str):
            raise SemPermissao(recurso, acao_str)
        return usuario

    return _verificar
