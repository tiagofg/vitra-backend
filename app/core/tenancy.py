"""Multiempresa imposta pelo banco: a empresa ativa vira um GUC da transação.

O recorte entre empresas não é mais um `WHERE empresa_id = ...` que alguém pode esquecer —
é política do Postgres (ver a migração de RLS). Este módulo é a metade da aplicação:
declarar, no início de cada transação, de qual empresa é aquele trabalho.

Duas garantias que valem repetir porque explicam o formato do código:

* **`SET LOCAL`, nunca `SET`.** Vale até o fim da transação, então a conexão devolvida ao
  pool não carrega a empresa do request anterior. Usamos `set_config(..., true)`, que é o
  `SET LOCAL` em forma de função — e, ao contrário do `SET`, aceita parâmetro ligado.
  `SET app.current_tenant = '<uuid>'` só existiria por interpolação de string.
* **Emitido pela `Connection`, não pela `Session`.** O evento `after_begin` entrega as duas;
  `session.execute()` ali poderia disparar fora da transação que acabou de abrir.
"""

from __future__ import annotations

import uuid

from sqlalchemy import event, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, SessionTransaction

from app.core.errors import ErroDominio, Falha

GUC_EMPRESA = "app.current_tenant"

# Chave em `Session.info`. Preferida a um ContextVar: o evento `after_begin` já recebe a
# sessão, então não há como o valor pertencer à sessão errada.
_CHAVE = "vitra_empresa_id"

_SQL_DECLARAR = text(f"SELECT set_config('{GUC_EMPRESA}', :empresa, true)")


class EmpresaNaoDeclarada(ErroDominio):
    """Rota que lê ou escreve dado por empresa sem dizer de qual empresa é.

    Sem isto o pedido não daria erro — daria **lista vazia**, que é o sintoma mais caro de
    depurar sob RLS. Falhar na borda é mais barato que investigar depois.
    """

    http_status = 400
    codigo = "empresa_nao_declarada"

    def __init__(self) -> None:
        super().__init__(
            "Nenhuma empresa ativa no pedido. Informe o cabeçalho X-Empresa-Id ou "
            "autentique-se com um token que já carregue a empresa.",
            campos={"X-Empresa-Id": "obrigatório quando o token não tem empresa"},
        )


class SemVinculoComEmpresa(ErroDominio):
    """Quem pediu está autenticado, mas não trabalha na empresa que pediu.

    É o que fecha a última brecha do desenho: sem esta checagem, o encadeamento seria
    *RLS confia no GUC → GUC confia no cabeçalho → cabeçalho vem do cliente*, e a política
    do Postgres — impecável — estaria protegendo um recorte escolhido por quem chama.

    403 e não 404: dizer "não encontrado" esconderia de propósito a existência da empresa,
    e o `tenant_id` não é segredo (ele aparece em `GET /bakeoff/empresas`). O que é
    controlado é o acesso, não a existência.
    """

    http_status = 403
    codigo = "sem_vinculo_com_empresa"

    def __init__(self, empresa_id: uuid.UUID) -> None:
        super().__init__(
            "Usuário não tem vínculo com a empresa informada.",
            campos={"X-Empresa-Id": str(empresa_id)},
        )


EMPRESA_NAO_DECLARADA = Falha(
    status=EmpresaNaoDeclarada.http_status,
    codigo=EmpresaNaoDeclarada.codigo,
    descricao="Nem o token nem o cabeçalho `X-Empresa-Id` trazem uma empresa ativa.",
    mensagem="Nenhuma empresa ativa no pedido. Informe o cabeçalho X-Empresa-Id ou "
    "autentique-se com um token que já carregue a empresa.",
    campos={"X-Empresa-Id": "obrigatório quando o token não tem empresa"},
)

SEM_VINCULO_COM_EMPRESA = Falha(
    status=SemVinculoComEmpresa.http_status,
    codigo=SemVinculoComEmpresa.codigo,
    descricao="Autenticado, mas sem vínculo ativo com a empresa pedida.",
    mensagem="Usuário não tem vínculo com a empresa informada.",
    campos={"X-Empresa-Id": "6f1c8f0a-1f1e-4a5b-9d3c-2b7a5e4f8c10"},
)


async def declarar_empresa(session: AsyncSession, empresa_id: uuid.UUID) -> None:
    """Fixa a empresa ativa desta sessão.

    Se a transação ainda não abriu, o `after_begin` cuida dela quando abrir. Se já abriu —
    e isso é o caso comum, porque autenticar o usuário já consultou o banco — o `set_config`
    sai aqui mesmo. Sem este segundo caminho, a primeira transação do request rodaria sem
    empresa e devolveria vazio.
    """
    session.info[_CHAVE] = empresa_id
    if session.in_transaction():
        await session.execute(_SQL_DECLARAR, {"empresa": str(empresa_id)})


def registrar_eventos() -> None:
    """Liga o `after_begin` na classe `Session` — vale para toda sessão do processo.

    Idempotente: importar o módulo duas vezes não registra o ouvinte duas vezes.
    """
    if event.contains(Session, "after_begin", _ao_abrir_transacao):
        return
    event.listen(Session, "after_begin", _ao_abrir_transacao)


def _ao_abrir_transacao(
    session: Session, _transacao: SessionTransaction, connection: Connection
) -> None:
    empresa_id = session.info.get(_CHAVE)
    if empresa_id is None:
        # Nada a declarar. Não é erro: o RLS devolve zero linhas, e as tabelas globais
        # (tenants, employees, catalog_lookups) continuam legíveis normalmente.
        return
    connection.execute(_SQL_DECLARAR, {"empresa": str(empresa_id)})


# A borda HTTP — de onde vem a empresa e quem pode pedi-la — mora em
# `app/modules/auth/deps.py`. Ela precisa de `get_session`, de `usuario_atual` e da tabela
# `employee_company`; `db.py` importa este arquivo para registrar o evento, então manter
# `tenancy` sem essas dependências é o que evita o ciclo de importação.
#
# Este módulo é só o mecanismo: como a empresa entra na transação, e o que fazer quando
# ela falta ou não é do usuário. **Declarar não é autorizar** — quem decide se aquele
# usuário pode operar naquela empresa é a dependência, antes de qualquer query de negócio.
