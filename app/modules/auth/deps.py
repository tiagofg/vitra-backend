"""Borda HTTP: qual empresa está ativa, e se quem pediu tem direito a ela.

Mora no módulo, e não em `app/core/deps.py`, porque a resposta depende de
`VinculoEmpresa` — tabela deste módulo. Core importando modelo de módulo seria a inversão
de camada errada.

**A ordem das três perguntas é o desenho, não detalhe de implementação:**

1. *Quem é?* — `UsuarioAtual`, ou 401.
2. *Qual empresa?* — claim do token ou cabeçalho `X-Empresa-Id`, ou 400.
3. *Pode essa empresa?* — vínculo em `employee_company`, ou 403.

Sem a terceira, o encadeamento seria *RLS confia no GUC → GUC confia no token/cabeçalho →
ambos vêm do cliente*: a política do Postgres protegeria um recorte escolhido por quem
chama. O RLS entrega imunidade a `WHERE` esquecido no serviço; é esta função que entrega
imunidade a chamador malicioso. São coisas diferentes e as duas são necessárias.

**Claim vs cabeçalho.** O token carrega a empresa ativa (`ClaimsToken.tenant_id`), obtida em
`POST /auth/trocar-empresa`. O cabeçalho `X-Empresa-Id` continua aceito e, quando presente,
tem prioridade — é o caminho de quem tem vínculo em mais de uma empresa (a ANA SILVA) e
quer operar na outra sem trocar de token. Os dois caminhos passam pela mesma checagem de
vínculo: um cabeçalho forjado não vale mais que um claim forjado, porque nenhum dos dois é
aceito sem prova em `employee_company`.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import ClaimsDoToken, Sessao, UsuarioAtual
from app.core.errors import pode_falhar
from app.core.tenancy import (
    EMPRESA_NAO_DECLARADA,
    SEM_VINCULO_COM_EMPRESA,
    EmpresaNaoDeclarada,
    SemVinculoComEmpresa,
    declarar_empresa,
)
from app.modules.auth.models import Usuario
from app.modules.auth.service import tem_vinculo


@pode_falhar(EMPRESA_NAO_DECLARADA, SEM_VINCULO_COM_EMPRESA)
async def empresa_do_pedido(
    session: Sessao,
    usuario: UsuarioAtual,
    claims: ClaimsDoToken,
    x_empresa_id: Annotated[
        uuid.UUID | None,
        Header(description="UUID da empresa ativa. Sobrepõe a empresa do token, se houver."),
    ] = None,
) -> uuid.UUID:
    empresa_id = x_empresa_id or claims.tenant_id
    if empresa_id is None:
        raise EmpresaNaoDeclarada()

    # Declarar **antes** de checar é deliberado: `employee_company` está sob RLS, então a
    # consulta de vínculo já sai recortada pela empresa pedida.
    await declarar_empresa(session, empresa_id)

    if not await tem_vinculo(session, usuario.id, empresa_id):
        raise SemVinculoComEmpresa(empresa_id)
    return empresa_id


EmpresaDoPedido = Annotated[uuid.UUID, Depends(empresa_do_pedido)]


async def sessao_da_empresa(session: Sessao, _: EmpresaDoPedido) -> AsyncSession:
    """Sessão com a empresa já declarada **e já autorizada**.

    Toda rota que toca tabela por empresa depende desta, e não de `Sessao`. Como ela
    depende de `EmpresaDoPedido`, que depende de `UsuarioAtual`, a autenticação entra
    junto: não dá para usar esta sessão e esquecer o token.
    """
    return session


SessaoEmpresa = Annotated[AsyncSession, Depends(sessao_da_empresa)]

# Reexportado para quem só precisa saber "quem está pedindo", sem repetir o import de
# `app.core.deps` — a maior parte das rotas de módulo já importa daqui.
__all__ = ["EmpresaDoPedido", "SessaoEmpresa", "Usuario", "empresa_do_pedido", "sessao_da_empresa"]
