"""Borda HTTP do bake-off: quem está pedindo, e por qual empresa.

Mora no módulo, e não em `app/core/deps.py`, porque a resposta depende de
`employee_company` — tabela deste módulo. Core importando modelo de módulo seria a
inversão de camada errada, e a ponte usada aqui é temporária de qualquer forma: no VITRA
real a empresa ativa vem de um claim no JWT, e a checagem deixa de precisar de join.

**A ordem das três perguntas é o desenho, não detalhe de implementação:**

1. *Quem é?* — `UsuarioAtual`, ou 401. Sem isto, as rotas do bake-off seriam as únicas da
   API sem autenticação, e `POST /produtos` gravaria no banco sem credencial nenhuma.
2. *Qual empresa?* — cabeçalho, ou 400.
3. *Pode essa empresa?* — vínculo em `employee_company`, ou 403.

Sem a terceira, o encadeamento seria *RLS confia no GUC → GUC confia no cabeçalho →
cabeçalho vem do cliente*: a política do Postgres protegeria um recorte escolhido por quem
chama. O RLS entrega imunidade a `WHERE` esquecido no serviço; é esta função que entrega
imunidade a chamador malicioso. São coisas diferentes e as duas são necessárias.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Depends, Header
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import Sessao, UsuarioAtual
from app.core.errors import pode_falhar
from app.core.tenancy import (
    EMPRESA_NAO_DECLARADA,
    SEM_VINCULO_COM_EMPRESA,
    EmpresaNaoDeclarada,
    SemVinculoComEmpresa,
    declarar_empresa,
)
from app.modules.auth.models import Usuario
from app.modules.bakeoff.models import Colaborador, ColaboradorEmpresa, Empresa


@pode_falhar(EMPRESA_NAO_DECLARADA, SEM_VINCULO_COM_EMPRESA)
async def empresa_do_pedido(
    session: Sessao,
    usuario: UsuarioAtual,
    x_empresa_id: Annotated[
        uuid.UUID | None,
        Header(description="UUID da empresa ativa (tenant_id) para este pedido."),
    ] = None,
) -> uuid.UUID:
    """Resolve a empresa ativa e prova que o usuário tem direito a ela.

    Para o VITRA real a recomendação é *claim no JWT*, com o cabeçalho sobrevivendo só para
    quem opera em mais de uma empresa — é o caso da ANA SILVA, `admin` na ABACAXI e
    `operator-sales` na UVA. A decisão está aberta no plano; concentrá-la aqui é o que
    mantém a troca barata: muda esta função, mais nada.
    """
    if x_empresa_id is None:
        raise EmpresaNaoDeclarada()

    # Declarar **antes** de checar é deliberado: `employee_company` está sob RLS, então a
    # consulta abaixo já sai recortada pela empresa pedida. Não é preciso escrever
    # `WHERE tenant_id = ...` nem confiar que alguém lembre de escrevê-lo — e a checagem
    # usa a mesma política que protege o resto, em vez de um caminho paralelo.
    await declarar_empresa(session, x_empresa_id)

    if not await _tem_vinculo(session, usuario):
        raise SemVinculoComEmpresa(x_empresa_id)
    return x_empresa_id


EmpresaDoPedido = Annotated[uuid.UUID, Depends(empresa_do_pedido)]


async def sessao_da_empresa(session: Sessao, _: EmpresaDoPedido) -> AsyncSession:
    """Sessão com a empresa já declarada **e já autorizada**.

    Toda rota que toca tabela por empresa depende desta, e não de `Sessao`. Como ela
    depende de `EmpresaDoPedido`, que depende de `UsuarioAtual`, a autenticação entra
    junto: não dá para usar esta sessão e esquecer o token.
    """
    return session


SessaoEmpresa = Annotated[AsyncSession, Depends(sessao_da_empresa)]


async def _tem_vinculo(session: AsyncSession, usuario: Usuario) -> bool:
    """Liga a identidade que loga (`usuario`) à identidade do grupo (`employees`).

    A ponte é o e-mail, e é ponte mesmo: o schema fixo do bake-off tem
    `employees(id, name, email, active)` — sem senha —, então `usuario` e `employees` são
    duas tabelas para a mesma pessoa enquanto o retrabalho da S0 não acontecer. É esse
    retrabalho que remove esta função.

    Sem e-mail no cadastro, não há como ligar as duas pontas e o acesso é negado. Falhar
    fechado é o único padrão aceitável aqui: um usuário sem e-mail passando a enxergar
    qualquer empresa seria o mesmo furo com outra cara.

    Não há atalho para superusuário. Ele existe para atravessar o RBAC — *o que pode
    fazer* —, e aqui a pergunta é outra: *de qual empresa é o dado*. Deixá-lo passar
    reabriria a escolha livre de `tenant_id` para a conta mais poderosa do sistema.

    **Três linhas precisam estar ativas**, e não só existir:

    * `usuario.ativo` — já conferido por `usuario_atual`, que devolve 401 antes de chegar
      aqui;
    * `employees.active` — desativar é *o* mecanismo de offboarding do VITRA ("cadastros
      nunca são apagados, são desativados"). Se desativar não corta o acesso, `active` vira
      um campo que parece proteger e não protege — a pior categoria, porque ninguém
      confere de novo;
    * `tenants.active` — empresa desativada e ainda operável é o mesmo problema um nível
      acima.
    """
    if not usuario.email:
        return False

    # `employee_company` está sob RLS e a empresa já foi declarada: esta consulta enxerga
    # apenas os vínculos da empresa pedida. Se voltar linha, o vínculo existe *nela*.
    #
    # `tenants` é global e não tem RLS, então o join com ela precisa da igualdade
    # explícita — é a única parte desta query que nomeia o tenant, e mesmo assim para
    # *ler o status da empresa*, não para recortar.
    #
    # Sobre o `lower()`: ele impede o uso do índice único de `employees.email` e força
    # varredura. Fica assim de propósito — a correção seria um índice funcional em
    # `lower(email)`, e `employees` faz parte do schema **fixo** do banco compartilhado,
    # onde não se cria índice. `employees` é pequena (pessoas do grupo, não documentos), e
    # a alternativa — comparar a coluna crua — dependeria de a caixa do e-mail semeado pelo
    # Henrique casar com a do nosso cadastro. Ver a ressalva de latência em
    # `notas-bakeoff.md`: no VITRA real, onde o schema é nosso, o índice entra.
    vinculo = await session.execute(
        select(ColaboradorEmpresa.role)
        .join(Colaborador, Colaborador.id == ColaboradorEmpresa.employee_id)
        .join(Empresa, Empresa.id == ColaboradorEmpresa.tenant_id)
        .where(
            func.lower(Colaborador.email) == usuario.email.lower(),
            Colaborador.active.is_(True),
            Empresa.active.is_(True),
        )
        .limit(1)
    )
    return vinculo.scalar_one_or_none() is not None
