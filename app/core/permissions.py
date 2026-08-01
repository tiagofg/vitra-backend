from __future__ import annotations

import enum
import uuid
from collections.abc import Callable, Coroutine
from typing import Annotated, Any

from fastapi import Header

from app.core.deps import ClaimsDoToken, Sessao, UsuarioAtual
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
    "produto": CRUD,
    "cliente": CRUD,
    "obra": CRUD,
    "fornecedor": CRUD,
    "colaborador": CRUD,
    "profissional_externo": CRUD,
    "transportadora": CRUD,
}

# Recursos cuja tabela é por empresa (`ModeloTenant`, sob RLS) — só esses fazem sentido para
# o grupo do vínculo decidir sozinho. O resto do `CATALOGO` é global (sem `tenant_id`):
# `usuario`, `grupo`, `permissao`, `empresa`, `apoio`, `cidade`, `banco`, `uf` valem para a
# instalação inteira, então "grupo da ABACAXI" não pode ser a palavra final sobre eles — do
# contrário um grupo de vínculo com `usuario:criar` cria conta em qualquer empresa
# (achado na revisão: escalada de privilégio) e a mesma rota global responde diferente só
# porque o pedido levou `X-Empresa-Id`. Fora daqui, `require()` sempre cai em
# `Usuario.pode()`, os grupos globais — igual ao comportamento anterior à S2.
RECURSOS_POR_EMPRESA = frozenset(
    {
        "filial",
        "centro_custo",
        "produto",
        "cliente",
        "obra",
        "fornecedor",
        "colaborador",
        "profissional_externo",
        "transportadora",
    }
)


def pares_do_catalogo() -> list[tuple[str, str]]:
    return [(recurso, acao.value) for recurso, acoes in CATALOGO.items() for acao in acoes]


# Calculado uma vez no import, não a cada `require()`: a checagem de pertencimento é feita
# em tempo de importação (uma por rota, ~poucas dezenas no total), mas não custa nada
# construir o conjunto uma vez em vez de reconstruir a lista inteira a cada chamada.
_PARES_VALIDOS = frozenset(pares_do_catalogo())


async def _permissao_por_empresa(
    session: Sessao, usuario: Usuario, empresa_id: uuid.UUID, recurso: str, acao_str: str
) -> bool | None:
    """`None` = o vínculo não tem grupo específico daquela empresa (ou não há vínculo) —
    cai em `Usuario.pode()`, os grupos globais. `True`/`False` = o grupo do vínculo decide
    sozinho, **sem união** com os grupos globais: é o que faz "admin na ABACAXI" não
    vazar permissão para a UVA (ver docstring de `VinculoEmpresa.grupo_id`).

    Import local de `app.core.tenancy`/`app.modules.auth.*`: mesma técnica de
    `app/common/crud_router.py` para não fazer `app.core.permissions` depender de módulo
    na importação — só paga o custo quem de fato tem empresa declarada no pedido.
    """
    from app.core.tenancy import declarar_empresa
    from app.modules.auth.models import Grupo
    from app.modules.auth.service import grupo_do_vinculo

    # Declarar antes de consultar: `employee_company` está sob RLS, e a checagem de
    # vínculo (`grupo_do_vinculo`) já filtra `tenant_id` explícito na consulta mesmo assim
    # — mas sem declarar, uma conexão que *respeita* RLS (o papel de runtime de produção)
    # veria sempre vazio, porque a política ainda não tem GUC para casar. Mesma ordem de
    # `empresa_do_pedido`.
    await declarar_empresa(session, empresa_id)
    grupo_id = await grupo_do_vinculo(session, usuario.id, empresa_id)
    if grupo_id is None:
        return None

    grupo = await session.get(Grupo, grupo_id)
    if grupo is None or not grupo.ativo:
        return None

    chave = f"{recurso}:{acao_str}"
    return any(p.chave == chave for p in grupo.permissoes)


def require(recurso: str, acao: Acao | str) -> Callable[..., Coroutine[Any, Any, Usuario]]:
    """Dependência de rota: `Depends(require("apoio", Acao.criar))`.

    Espelha `Controle de Acesso → Permissões de Acesso` do legado: a permissão é o par
    recurso+ação, concedido a grupos; usuário herda dos grupos globais
    (`usuario_grupo`) — **exceto** quando o vínculo com a empresa ativa do pedido aponta
    um grupo específico (`employee_company.grupo_id`), caso em que só esse grupo vale.
    """
    acao_str = acao.value if isinstance(acao, Acao) else acao
    if (recurso, acao_str) not in _PARES_VALIDOS:
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
    async def _verificar(
        usuario: UsuarioAtual,
        session: Sessao,
        claims: ClaimsDoToken,
        x_empresa_id: Annotated[uuid.UUID | None, Header()] = None,
    ) -> Usuario:
        if usuario.superusuario:
            return usuario

        # Mesma resolução de `empresa_do_pedido` (claim ou cabeçalho), mas sem levantar
        # quando falta: `require()` roda antes de `EmpresaDoPedido` em toda rota por
        # empresa, e precisa continuar respondendo 403 sem empresa nenhuma declarada —
        # inverter a ordem aqui reabriria o furo que
        # `test_sem_permissao_prevalece_sobre_empresa_nao_declarada` fecha.
        empresa_id = x_empresa_id or claims.tenant_id
        permitido = (
            await _permissao_por_empresa(session, usuario, empresa_id, recurso, acao_str)
            if empresa_id is not None and recurso in RECURSOS_POR_EMPRESA
            else None
        )
        if permitido is None:
            permitido = usuario.pode(recurso, acao_str)

        if not permitido:
            raise SemPermissao(recurso, acao_str)
        return usuario

    return _verificar
