"""Rotas do bake-off.

**Três perguntas diferentes, e o bake-off só responde duas.**

*Quem é?* e *de qual empresa é o dado?* estão respondidas: toda rota daqui exige token, e
`SessaoEmpresa` só devolve a sessão depois de provar o vínculo do usuário com a empresa
pedida (ver `deps.py`). Uma rota que dependa de `Sessao` cru precisa declarar
`_: UsuarioAtual` explicitamente — é o caso de `listar_empresas`, que é global.

*O que aquele usuário pode fazer?* — essa não. Sem `Depends(require(...))` aqui, e é
decisão: o RBAC do VITRA vive em `usuario`/`grupo`/`permissao`, que **não existem** no
schema fixo do bake-off; lá a autorização é `employee_company.role`, cinco papéis fixos.
Amarrar as duas coisas agora misturaria o que o bake-off mede (isolamento por RLS) com o
que ele deixou em aberto (papel fixo × RBAC granular).

A distinção importa porque a primeira versão deste arquivo usava o segundo argumento — bom
— para justificar a ausência do primeiro, que é outra coisa inteiramente. RBAC inaplicável
é motivo para dispensar `require(...)`, nunca para dispensar autenticação.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy import select

from app.core.deps import Sessao, UsuarioAtual
from app.core.errors import CONFLITO, pode_falhar
from app.core.listing import ListParams, Pagina
from app.modules.bakeoff.deps import EmpresaDoPedido, SessaoEmpresa
from app.modules.bakeoff.models import ColaboradorEmpresa, Empresa
from app.modules.bakeoff.schemas import EmpresaSaida, PapelSaida, ProdutoCriar, ProdutoSaida
from app.modules.bakeoff.service import ProdutoService

router_produtos = APIRouter(prefix="/produtos", tags=["bake-off"])
router_empresas = APIRouter(prefix="/bakeoff/empresas", tags=["bake-off"])


@router_produtos.get("", response_model=Pagina[ProdutoSaida])
async def listar_produtos(
    session: SessaoEmpresa,
    params: Annotated[ListParams, Depends()],
) -> Pagina[ProdutoSaida]:
    """Listagem server-side: busca sem acento, ordenação e paginação, tudo no servidor.

    Devolve `{itens, total, pagina, tamanho, paginas}` — o contrato que o TanStack Table
    server-side do front espera. `empresa_id` **não** é parâmetro: a empresa vem do
    cabeçalho `X-Empresa-Id` e entra na transação, não na query string.
    """
    return await ProdutoService(session).listar(params)


@router_produtos.post("", response_model=ProdutoSaida, status_code=status.HTTP_201_CREATED)
@pode_falhar(CONFLITO)
async def criar_produto(
    dados: ProdutoCriar,
    session: SessaoEmpresa,
    empresa_id: EmpresaDoPedido,
) -> ProdutoSaida:
    produto = await ProdutoService(session).criar(dados, empresa_id)
    return ProdutoSaida.model_validate(produto)


@router_empresas.get("", response_model=list[EmpresaSaida])
async def listar_empresas(session: Sessao, _: UsuarioAtual) -> list[EmpresaSaida]:
    """`tenants` é global e não tem RLS — é a raiz do recorte, não algo recortado.

    Depende de `Sessao`, não de `SessaoEmpresa`: exigir empresa declarada para descobrir
    quais empresas existem seria um ovo que precisa da galinha. Por isso o `UsuarioAtual`
    explícito — é a única rota do módulo em que a autenticação não vem de carona.

    Ela devolve razão social e CNPJ de todas as empresas do grupo. Não é dado secreto, mas
    também não é dado público: sem o token, isto era um diretório aberto do grupo Vertz.
    """
    linhas = (await session.execute(select(Empresa).order_by(Empresa.name))).scalars().all()
    return [EmpresaSaida.model_validate(e) for e in linhas]


@router_empresas.get("/papeis", response_model=list[PapelSaida])
async def listar_papeis(session: SessaoEmpresa) -> list[PapelSaida]:
    """Papéis da empresa ativa. ANA SILVA aparece com papel diferente em cada uma."""
    linhas = (await session.execute(select(ColaboradorEmpresa))).scalars().all()
    return [PapelSaida.model_validate(v) for v in linhas]


routers = [router_produtos, router_empresas]
