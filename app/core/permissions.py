from __future__ import annotations

import enum
from collections.abc import Callable, Coroutine
from typing import Any

from app.core.deps import UsuarioAtual
from app.core.errors import Falha, SemPermissao, pode_falhar
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


def require(recurso: str, acao: Acao | str) -> Callable[[Usuario], Coroutine[Any, Any, Usuario]]:
    """Dependência de rota: `Depends(require("apoio", Acao.criar))`.

    Espelha `Controle de Acesso → Permissões de Acesso` do legado: a permissão é o par
    recurso+ação, concedido a grupos; usuário herda dos grupos.
    """
    acao_str = acao.value if isinstance(acao, Acao) else acao
    if (recurso, acao_str) not in pares_do_catalogo():
        raise KeyError(f"Permissão '{recurso}:{acao_str}' não está no catálogo.")

    # A falha é montada aqui, e não uma vez no módulo, porque cada rota tem o seu par: o
    # contrato de `POST /grupos` mostra `grupo:criar` no exemplo, não um 403 genérico. É a
    # mesma dependência que exige a permissão e que a documenta — não dá para acrescentar
    # uma sem a outra.
    falha = Falha(
        status=SemPermissao.http_status,
        codigo=SemPermissao.codigo,
        descricao=f"Usuário autenticado sem a permissão '{recurso}:{acao_str}'.",
        mensagem=f"Usuário não tem permissão de '{acao_str}' sobre '{recurso}'.",
        campos={"recurso": recurso, "acao": acao_str},
    )

    @pode_falhar(falha)
    async def _verificar(usuario: UsuarioAtual) -> Usuario:
        if not usuario.pode(recurso, acao_str):
            raise SemPermissao(recurso, acao_str)
        return usuario

    return _verificar
