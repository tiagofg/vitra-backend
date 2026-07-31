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
from typing import Annotated

from fastapi import Depends, Header
from sqlalchemy import event, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, SessionTransaction

from app.core.errors import ErroDominio

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
            "Nenhuma empresa ativa no pedido. Informe o cabeçalho X-Empresa-Id.",
            campos={"X-Empresa-Id": "obrigatório"},
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


# --- borda HTTP ---------------------------------------------------------------


async def empresa_do_pedido(
    x_empresa_id: Annotated[
        uuid.UUID | None,
        Header(description="UUID da empresa ativa (tenant_id)."),
    ] = None,
) -> uuid.UUID:
    """De onde vem a empresa ativa.

    Hoje: cabeçalho. Para o VITRA real a recomendação é *claim no JWT*, com o cabeçalho
    sobrevivendo só para quem opera em mais de uma empresa — é o caso da ANA SILVA, que é
    `admin` na ABACAXI e `operator-sales` na UVA. A decisão está aberta no plano; isolá-la
    aqui é o que mantém a troca barata: muda esta função, mais nada.
    """
    if x_empresa_id is None:
        raise EmpresaNaoDeclarada()
    return x_empresa_id


EmpresaDoPedido = Annotated[uuid.UUID, Depends(empresa_do_pedido)]

# A dependência que junta sessão + empresa mora em `app/core/deps.py`: ela precisa de
# `get_session`, e `db.py` importa este módulo para registrar o evento. Manter `tenancy`
# sem dependência de `db` é o que evita o ciclo.
