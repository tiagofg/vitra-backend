"""Serviços de cadastro de pessoas.

Nenhum filtro por empresa em nenhum `_stmt_base`/`select()` daqui — é o RLS que recorta,
como em todo o resto do projeto desde a SB. O que estes serviços acrescentam ao `BaseService`
comum:

* **Confere o domínio das FKs para `catalog_lookups`.** A FK em si é só
  `catalog_lookups.id` — nada no banco impede apontar `profissao_id` para uma linha de
  `marca`. `_ConfereDominiosMixin` fecha essa lacuna como regra de negócio, uma vez só para
  os três serviços que precisam dela.
* **Confere toda referência a outra tabela global.** `employee_id` (em `Colaborador`) e
  `empresa_compradora_id` (em `FornecedorEmpresa`) são FK simples para tabela **global**
  (`employees`/`tenants`) — sem `tenant_id`, então sem RLS a proteger. Sem checagem
  explícita, qualquer usuário autenticado grava um cadastro apontando para um UUID alheio
  só porque ele existe — o mesmo furo que `empresa_do_pedido` fecha na borda para a
  *própria* empresa do pedido, mas que nenhum RLS fecha sozinho para uma referência *a
  outra* tabela global dentro do corpo do pedido. **As duas checagens não são a mesma
  coisa, de propósito:**
    - `ColaboradorService` usa `tem_vinculo(session, employee_id, self.tenant_id)` — aqui
      `self.tenant_id` é a empresa **ativa** do pedido, a mesma que o GUC do RLS já
      declarou; a consulta a `employee_company` (sob RLS) sai naturalmente recortada para
      ela, e o filtro explícito continua correto mesmo sob uma conexão que ignora RLS.
    - `FornecedorEmpresaService.abrir_vigencia` **não** usa `tem_vinculo` — confere só que
      `empresa_compradora_id` é uma `Empresa` ativa. `tem_vinculo` consultaria
      `employee_company` pedindo vínculo com uma empresa **diferente** da ativa; sob RLS de
      produção (papel de runtime, sem `BYPASSRLS`), a política já recorta a consulta para
      `tenant_id = <empresa ativa>`, então perguntar por qualquer outro `tenant_id` na
      mesma consulta é pedir a interseção de dois valores diferentes — sempre vazia,
      inclusive para vínculo legítimo. `empresa_compradora_id` pode, de propósito, ser uma
      empresa diferente da ativa (ver docstring de `FornecedorEmpresa`), então a checagem
      certa é existência na tabela global, não vínculo pessoal.
* **`ObraService`** é recortado por `cliente_id`, no mesmo molde de `ApoioService` recortado
  por `dominio`.
* **`FornecedorEmpresaService`** não é CRUD: só abre vigência (fecha a anterior) e lista o
  histórico — não há `PUT`/`DELETE` de uma vigência.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Any

from sqlalchemy import Select, asc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.base_service import BaseService
from app.core.errors import NaoEncontrado, RegraDeNegocio
from app.core.listing import (
    ListingSpec,
    ListParams,
    LookupItem,
    Pagina,
    aplicar_listagem,
    contem_sem_acento,
    paginar,
)
from app.modules.apoio.models import DominioApoio, TabelaApoio
from app.modules.auth.models import Usuario
from app.modules.auth.service import tem_vinculo
from app.modules.empresa.models import Empresa
from app.modules.pessoas.models import (
    Cliente,
    Colaborador,
    Fornecedor,
    FornecedorEmpresa,
    Obra,
    ProfissionalExterno,
    Transportadora,
)
from app.modules.pessoas.schemas import (
    ClienteAtualizar,
    ClienteCriar,
    ColaboradorAtualizar,
    ColaboradorCriar,
    FornecedorAtualizar,
    FornecedorCriar,
    FornecedorEmpresaAbrir,
    ObraAtualizar,
    ObraCriar,
    ProfissionalExternoAtualizar,
    ProfissionalExternoCriar,
    TransportadoraAtualizar,
    TransportadoraCriar,
)


async def _conferir_dominio(
    session: AsyncSession, valor: uuid.UUID | None, dominio: DominioApoio, campo: str
) -> None:
    """`campo` aponta para `catalog_lookups.id` — a FK simples não garante *qual* domínio.
    Confere aqui porque é regra de negócio, não algo que o banco possa checar sozinho."""
    if valor is None:
        return
    dominio_real = (
        await session.execute(select(TabelaApoio.dominio).where(TabelaApoio.id == valor))
    ).scalar_one_or_none()
    if dominio_real is None:
        raise RegraDeNegocio(
            f"'{campo}' não corresponde a um valor de apoio existente.",
            codigo="referencia_invalida",
            campos={campo: str(valor)},
        )
    if dominio_real != dominio:
        raise RegraDeNegocio(
            f"'{campo}' precisa ser um valor de apoio do domínio '{dominio.value}'.",
            codigo="dominio_invalido",
            campos={campo: str(valor)},
        )


class _ConfereDominiosMixin:
    """Gancho comum a serviços com FK simples para `catalog_lookups`: a subclasse só
    declara `dominios_por_campo`, o resto (checar em `criar` e em `atualizar`) é herdado.

    Precisa vir **antes** de `BaseService` na lista de bases — é o que faz
    `super()._antes_de_criar(...)` chamar a implementação de `BaseService` em vez de
    recursão infinita. `self.session` também vem de `BaseService.__init__`, herdado
    normalmente; o mypy não enxerga essa garantia através do mixin, daí os `type: ignore`.
    """

    dominios_por_campo: dict[str, DominioApoio] = {}

    async def _antes_de_criar(self, valores: dict[str, Any]) -> None:
        await super()._antes_de_criar(valores)  # type: ignore[misc]
        await self._conferir_dominios(valores)

    async def _antes_de_atualizar(self, obj: Any, valores: dict[str, Any]) -> None:
        await super()._antes_de_atualizar(obj, valores)  # type: ignore[misc]
        await self._conferir_dominios(valores)

    async def _conferir_dominios(self, valores: dict[str, Any]) -> None:
        for campo, dominio in self.dominios_por_campo.items():
            if campo in valores:
                await _conferir_dominio(self.session, valores[campo], dominio, campo)  # type: ignore[attr-defined]


# --- Cliente ------------------------------------------------------------------

_DOMINIOS_CLIENTE: dict[str, DominioApoio] = {
    "profissao_id": DominioApoio.profissao,
    "estado_civil_id": DominioApoio.estado_civil,
    "raca_cor_id": DominioApoio.raca_cor,
    "nacionalidade_id": DominioApoio.nacionalidade,
    "categoria_id": DominioApoio.categoria,
}


class ClienteService(_ConfereDominiosMixin, BaseService[Cliente, ClienteCriar, ClienteAtualizar]):
    nome_recurso = "Cliente"
    spec = ListingSpec(
        model=Cliente,
        campos_busca=("codigo", "nome", "cpf_cnpj"),
        campo_codigo="codigo",
        campos_ordenacao=("codigo", "nome", "criado_em"),
        ordenacao_padrao="codigo",
        campo_unico="codigo",
    )
    dominios_por_campo = _DOMINIOS_CLIENTE

    def _label_lookup(self, obj: Cliente) -> str:
        return obj.nome

    def _extras_lookup(self, obj: Cliente) -> dict[str, Any]:
        return {"cpf_cnpj": obj.cpf_cnpj}


class ObraService(BaseService[Obra, ObraCriar, ObraAtualizar]):
    """Recortado por `cliente_id`, no mesmo molde de `ApoioService` recortado por
    `dominio` — o `cliente_id` vem do path (`/clientes/{cliente_id}/obras`), nunca do
    corpo."""

    nome_recurso = "Obra"
    spec = ListingSpec(
        model=Obra,
        campos_busca=("nome",),
        campos_ordenacao=("nome", "criado_em"),
        ordenacao_padrao="nome",
    )

    def __init__(
        self,
        session: AsyncSession,
        cliente_id: uuid.UUID,
        usuario_id: uuid.UUID | None = None,
        tenant_id: uuid.UUID | None = None,
    ) -> None:
        super().__init__(session, usuario_id, tenant_id)
        self.cliente_id = cliente_id

    def _stmt_base(self) -> Select[Any]:
        return select(Obra).where(Obra.cliente_id == self.cliente_id)

    async def obter(self, id_: uuid.UUID) -> Obra:
        # `BaseService.obter()` não passa por `_stmt_base()` — é um `select` direto por
        # `id`, então o recorte por `cliente_id` fica de fora se não for conferido aqui.
        # Sem isto, `GET /clientes/A/obras/{obra-de-B}` acharia a obra de outro cliente
        # da mesma empresa. Mesmo motivo de `ApoioService.obter` conferir `dominio`.
        obra = await super().obter(id_)
        if obra.cliente_id != self.cliente_id:
            raise NaoEncontrado(self.nome_recurso, id_)
        return obra

    async def _preparar_valores(self, dados: ObraCriar) -> dict[str, Any]:
        valores = await super()._preparar_valores(dados)
        valores["cliente_id"] = self.cliente_id
        return valores

    def _label_lookup(self, obj: Obra) -> str:
        return obj.nome


# --- Transportadora -------------------------------------------------------------


class TransportadoraService(
    BaseService[Transportadora, TransportadoraCriar, TransportadoraAtualizar]
):
    nome_recurso = "Transportadora"
    spec = ListingSpec(
        model=Transportadora,
        campos_busca=("codigo", "nome", "cnpj"),
        campo_codigo="codigo",
        campos_ordenacao=("codigo", "nome", "criado_em"),
        ordenacao_padrao="codigo",
        campo_unico="codigo",
    )

    def _label_lookup(self, obj: Transportadora) -> str:
        return obj.nome


# --- Fornecedor -----------------------------------------------------------------


class FornecedorService(BaseService[Fornecedor, FornecedorCriar, FornecedorAtualizar]):
    nome_recurso = "Fornecedor"
    spec = ListingSpec(
        model=Fornecedor,
        campos_busca=("codigo", "razao_social", "nome_fantasia", "cnpj"),
        campo_codigo="codigo",
        campos_ordenacao=("codigo", "razao_social", "criado_em"),
        ordenacao_padrao="codigo",
        campo_unico="codigo",
    )

    def _label_lookup(self, obj: Fornecedor) -> str:
        return obj.nome_fantasia or obj.razao_social

    def _extras_lookup(self, obj: Fornecedor) -> dict[str, Any]:
        return {"cnpj": obj.cnpj}


class FornecedorEmpresaService:
    """Histórico de `Empresa compradora` de um fornecedor. Não herda `BaseService`: não há
    `PUT`/`DELETE` de uma vigência — só abrir uma nova (que fecha a anterior) e listar."""

    def __init__(
        self,
        session: AsyncSession,
        fornecedor_id: uuid.UUID,
        usuario_id: uuid.UUID | None = None,
        tenant_id: uuid.UUID | None = None,
    ) -> None:
        self.session = session
        self.fornecedor_id = fornecedor_id
        self.usuario_id = usuario_id
        self.tenant_id = tenant_id

    async def _exigir_fornecedor(self) -> None:
        existe = (
            await self.session.execute(
                select(Fornecedor.id).where(Fornecedor.id == self.fornecedor_id)
            )
        ).first()
        if existe is None:
            raise NaoEncontrado("Fornecedor", self.fornecedor_id)

    async def historico(self) -> list[FornecedorEmpresa]:
        await self._exigir_fornecedor()
        stmt = (
            select(FornecedorEmpresa)
            .where(FornecedorEmpresa.fornecedor_id == self.fornecedor_id)
            .order_by(FornecedorEmpresa.vigencia_inicio.desc())
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def empresa_compradora_em(self, data: date) -> uuid.UUID | None:
        """A vigência que cobre `data` — ou `None` se nenhuma cobre.

        Ainda sem chamador: é o que a S5 (compras) vai usar para resolver, num pedido, qual
        é a empresa compradora vigente do fornecedor naquela data. Fica coberto por teste
        próprio (`tests/test_fornecedor_empresa.py`) mesmo sem consumidor de produção ainda,
        porque é a regra de negócio que a aba `Histórico Emp. Comp.` do legado documenta —
        não é exploração especulativa, é o próximo passo já desenhado.
        """
        stmt = select(FornecedorEmpresa.empresa_compradora_id).where(
            FornecedorEmpresa.fornecedor_id == self.fornecedor_id,
            FornecedorEmpresa.vigencia_inicio <= data,
            (FornecedorEmpresa.vigencia_fim.is_(None)) | (FornecedorEmpresa.vigencia_fim >= data),
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def abrir_vigencia(self, dados: FornecedorEmpresaAbrir) -> FornecedorEmpresa:
        await self._exigir_fornecedor()

        # `empresa_compradora_id` é FK simples para `tenants` (global, sem RLS): sem esta
        # checagem, qualquer usuário autenticado registra como compradora um UUID que nem
        # é empresa — corrompe o dado de negócio.
        #
        # **Não** é checagem de vínculo do usuário com a compradora — tentativa anterior
        # (revisão do PR #7, rodada 1) usava `tem_vinculo`, que consulta `employee_company`,
        # tabela **sob RLS**. Sob o papel de runtime de produção, a política já recorta toda
        # consulta para `tenant_id = <empresa ativa>`; pedir vínculo com qualquer *outra*
        # empresa nessa mesma consulta é pedir a interseção de dois valores de `tenant_id`
        # diferentes — sempre vazia, não importa o dado real. O efeito não era "recusar
        # empresa alheia": era recusar **toda** `empresa_compradora_id` diferente da ativa,
        # inclusive para quem tem vínculo legítimo nas duas (o caso da ANA SILVA) — e a
        # suíte não pegou porque os testes rodam pela conexão de **dono**, que ignora RLS
        # (`conftest.py::motor`).
        #
        # A invariante certa é mais simples: `empresa_compradora_id` precisa ser uma
        # `Empresa` ativa do grupo — não precisa ser a empresa do pedido, nem uma que o
        # usuário tenha vínculo pessoal; é exatamente o que o docstring de
        # `FornecedorEmpresa` já descreve ("podem, e normalmente vão, ser a mesma empresa —
        # mas contam histórias diferentes"). `tenants` é global, então esta consulta enxerga
        # o grupo inteiro em qualquer sessão, RLS ou não.
        empresa_existe = (
            await self.session.execute(
                select(Empresa.id).where(
                    Empresa.id == dados.empresa_compradora_id, Empresa.ativo.is_(True)
                )
            )
        ).first()
        if empresa_existe is None:
            raise RegraDeNegocio(
                "Empresa compradora não existe ou está desativada.",
                codigo="empresa_compradora_invalida",
                campos={"empresa_compradora_id": str(dados.empresa_compradora_id)},
            )

        aberta = (
            await self.session.execute(
                select(FornecedorEmpresa).where(
                    FornecedorEmpresa.fornecedor_id == self.fornecedor_id,
                    FornecedorEmpresa.vigencia_fim.is_(None),
                )
            )
        ).scalar_one_or_none()

        if aberta is not None:
            if dados.vigencia_inicio <= aberta.vigencia_inicio:
                raise RegraDeNegocio(
                    "A nova vigência precisa começar depois do início da vigência aberta atual.",
                    codigo="vigencia_invalida",
                    campos={"vigencia_inicio": str(dados.vigencia_inicio)},
                )
            aberta.vigencia_fim = dados.vigencia_inicio - timedelta(days=1)

        # Duas aberturas simultâneas passam pela checagem acima vendo a mesma `aberta` (ou
        # nenhuma) e as duas tentam inserir uma linha sem `vigencia_fim` — quem chega
        # depois esbarra em `uq_fornecedor_empresa_vigente` (índice único parcial) e recebe
        # `409 conflito` genérico do handler de `IntegrityError`, não este
        # `RegraDeNegocio`. Correto e seguro: é o índice que garante a invariante "no
        # máximo uma vigência aberta", a checagem acima só dá a mensagem específica no
        # caminho sem corrida.
        nova = FornecedorEmpresa(
            tenant_id=self.tenant_id,
            fornecedor_id=self.fornecedor_id,
            empresa_compradora_id=dados.empresa_compradora_id,
            vigencia_inicio=dados.vigencia_inicio,
            motivo=dados.motivo,
        )
        if self.usuario_id is not None:
            nova.criado_por_id = self.usuario_id
        self.session.add(nova)
        await self.session.flush()
        return nova


# --- Profissional externo --------------------------------------------------------

_DOMINIOS_PROFISSIONAL_EXTERNO: dict[str, DominioApoio] = {
    "profissao_id": DominioApoio.profissao,
}


class ProfissionalExternoService(
    _ConfereDominiosMixin,
    BaseService[ProfissionalExterno, ProfissionalExternoCriar, ProfissionalExternoAtualizar],
):
    nome_recurso = "Profissional externo"
    spec = ListingSpec(
        model=ProfissionalExterno,
        campos_busca=("codigo", "nome", "cpf_cnpj"),
        campo_codigo="codigo",
        campos_ordenacao=("codigo", "nome", "criado_em"),
        ordenacao_padrao="codigo",
        campo_unico="codigo",
    )
    dominios_por_campo = _DOMINIOS_PROFISSIONAL_EXTERNO

    def _label_lookup(self, obj: ProfissionalExterno) -> str:
        return obj.nome


# --- Colaborador -----------------------------------------------------------------

_DOMINIOS_COLABORADOR: dict[str, DominioApoio] = {
    "cargo_id": DominioApoio.cargo,
    "setor_id": DominioApoio.setor,
    "vinculo_id": DominioApoio.vinculo,
    "grau_instrucao_id": DominioApoio.grau_instrucao,
}


class ColaboradorService(
    _ConfereDominiosMixin, BaseService[Colaborador, ColaboradorCriar, ColaboradorAtualizar]
):
    """`employee_id` aponta para `employees` (identidade global, sem RLS) — o serviço
    precisa conferir *na mão* que a pessoa referenciada tem vínculo com a empresa ativa,
    porque nenhuma política de banco faz isso por ele (ver docstring do módulo).

    `nome` — o que `?busca=`/`?q=` esperam filtrar — mora em `Usuario`, não em
    `Colaborador`; por isso `listar`/`lookup` são sobrescritos com o `join` explícito, em
    vez de usar `spec.campos_busca` (que só resolve atributo do próprio modelo).
    """

    nome_recurso = "Colaborador"
    spec = ListingSpec(
        model=Colaborador,
        campos_ordenacao=("criado_em",),
        ordenacao_padrao="criado_em",
        campo_unico="employee_id",
    )
    dominios_por_campo = _DOMINIOS_COLABORADOR

    async def _antes_de_criar(self, valores: dict[str, Any]) -> None:
        await super()._antes_de_criar(valores)
        # Falha fechado: sem `tenant_id` não há como conferir vínculo nenhum, e um guard de
        # segurança que desaparece em silêncio quando falta contexto é pior que um que
        # nunca existiu — o próximo chamador que esquecer de passar `tenant_id` recebe um
        # erro alto na hora, não um bypass silencioso. Hoje toda rota real passa os dois
        # (`crud_router.criar_item_por_empresa` sempre injeta `empresa_id`).
        if self.tenant_id is None:
            raise RegraDeNegocio(
                "Não é possível conferir o vínculo do colaborador sem uma empresa ativa.",
                codigo="empresa_nao_declarada_para_colaborador",
            )
        if not await tem_vinculo(self.session, valores["employee_id"], self.tenant_id):
            raise RegraDeNegocio(
                "Colaborador não tem vínculo com esta empresa.",
                codigo="colaborador_sem_vinculo",
                campos={"employee_id": str(valores["employee_id"])},
            )

    def _stmt_base(self) -> Select[Any]:
        return select(Colaborador).join(Usuario, Colaborador.employee_id == Usuario.id)

    async def listar(self, params: ListParams, serializar: Any) -> Pagina[Any]:
        stmt = aplicar_listagem(self._stmt_base(), params, self.spec)
        if params.busca:
            stmt = stmt.where(contem_sem_acento(Usuario.nome, params.busca))
        return await paginar(self.session, stmt, params, serializar)

    async def lookup(self, q: str | None, limite: int) -> list[LookupItem]:
        stmt = self._stmt_base().where(Colaborador.ativo.is_(True))
        if q:
            stmt = stmt.where(contem_sem_acento(Usuario.nome, q))
        stmt = stmt.order_by(asc(Usuario.nome)).limit(limite)
        linhas = (await self.session.execute(stmt)).scalars().all()
        return [
            LookupItem(id=obj.id, codigo=None, label=self._label_lookup(obj), extras={})
            for obj in linhas
        ]

    def _label_lookup(self, obj: Colaborador) -> str:
        return obj.colaborador.nome
