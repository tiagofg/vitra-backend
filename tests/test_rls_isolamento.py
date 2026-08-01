"""Os 4 testes de isolamento do bake-off.

Todos rodam contra **Postgres real**, com o papel de runtime — que não é dono das tabelas e
não tem `BYPASSRLS`. Não é preciosismo: contra um dublê, ou conectado como dono, os quatro
passariam sem provar nada, porque não haveria política valendo.

Cada um prova o **caso positivo antes do negativo**. É o que faz uma fixture vazia
*reprovar* o teste em vez de deixá-lo passar por acidente — o modo de falha silenciosa mais
comum em teste de isolamento.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core.listing import ListParams
from app.core.tenancy import declarar_empresa
from app.models import TABELAS_POR_EMPRESA
from app.modules.produtos.models import ProdutoEmpresa
from app.modules.produtos.schemas import ProdutoSaida
from app.modules.produtos.service import ProdutoService
from tests.cenario import SQL_DECLARAR, Cenario

# --- 1. a FK composta recusa o cruzamento entre empresas ----------------------


async def test_fk_composta_recusa_preco_de_produto_de_outra_empresa(
    motor_runtime: AsyncEngine, cenario: Cenario
) -> None:
    """Preço da ABACAXI apontando para variante da UVA: o banco recusa.

    Não é validação de serviço que alguém pode esquecer de chamar — é a FK
    `(tenant_id, variant_id)` não encontrando linha. O `INSERT` falha.
    """
    # Positivo primeiro: a mesma inserção, na variante certa, tem que funcionar. Sem esta
    # metade, o teste passaria mesmo se o INSERT estivesse quebrado por outro motivo.
    async with AsyncSession(motor_runtime) as sessao:
        await declarar_empresa(sessao, cenario.abacaxi)
        sessao.add(
            ProdutoEmpresa(
                tenant_id=cenario.abacaxi,
                variante_id=cenario.variante_livre_abacaxi,
                preco_cents=9990,
                estoque=0,
                estoque_minimo=0,
            )
        )
        await sessao.commit()

    async with AsyncSession(motor_runtime) as sessao:
        await declarar_empresa(sessao, cenario.abacaxi)
        sessao.add(
            ProdutoEmpresa(
                tenant_id=cenario.abacaxi,
                variante_id=cenario.variante_uva,  # variante da OUTRA empresa
                preco_cents=100,
                estoque=0,
                estoque_minimo=0,
            )
        )
        with pytest.raises(IntegrityError) as erro:
            await sessao.commit()

    assert "fk_product_tenant_variant" in str(erro.value)


# --- 2. consulta sem filtro no código só enxerga a empresa declarada ----------


async def test_listagem_sem_filtro_no_codigo_so_ve_a_empresa_declarada(
    motor_runtime: AsyncEngine, cenario: Cenario
) -> None:
    """`ProdutoService.listar` não escreve `WHERE tenant_id`. Quem recorta é o banco."""
    async with AsyncSession(motor_runtime) as sessao:
        await declarar_empresa(sessao, cenario.abacaxi)
        pagina = await ProdutoService(sessao).listar(_params(), ProdutoSaida.model_validate)
        codigos_abacaxi = {p.codigo for p in pagina.itens}

    async with AsyncSession(motor_runtime) as sessao:
        await declarar_empresa(sessao, cenario.uva)
        pagina = await ProdutoService(sessao).listar(_params(), ProdutoSaida.model_validate)
        codigos_uva = {p.codigo for p in pagina.itens}

    # Positivo: cada uma vê o que é dela.
    assert cenario.codigo_abacaxi in codigos_abacaxi
    assert cenario.codigo_uva in codigos_uva
    # Negativo: e só isso.
    assert cenario.codigo_uva not in codigos_abacaxi
    assert cenario.codigo_abacaxi not in codigos_uva


async def test_update_nao_alcanca_linha_de_outra_empresa(
    motor_runtime: AsyncEngine, cenario: Cenario
) -> None:
    """A política do SELECT filtraria a leitura; a do UPDATE tem que filtrar a escrita.

    Um `UPDATE ... WHERE code = <código da UVA>` disparado com a ABACAXI declarada não dá
    erro — ele simplesmente **não encontra linha**. Testar isto separado importa porque uma
    política `FOR SELECT` sozinha deixaria a escrita passar.
    """
    async with AsyncSession(motor_runtime) as sessao:
        await declarar_empresa(sessao, cenario.abacaxi)

        proprio = await sessao.execute(
            text("UPDATE products SET description = :d WHERE code = :c"),
            {"d": "renomeado pelo dono legítimo", "c": cenario.codigo_abacaxi},
        )
        alheio = await sessao.execute(
            text("UPDATE products SET description = :d WHERE code = :c"),
            {"d": "não deveria acontecer", "c": cenario.codigo_uva},
        )
        await sessao.commit()

    assert proprio.rowcount == 1, "o UPDATE na própria empresa tem que alcançar a linha"
    assert alheio.rowcount == 0, "o UPDATE na outra empresa não pode alcançar nada"


async def test_insert_em_nome_de_outra_empresa_e_recusado(
    motor_runtime: AsyncEngine, cenario: Cenario
) -> None:
    """`WITH CHECK` na política de INSERT: não dá para gravar em nome de outra empresa."""
    async with AsyncSession(motor_runtime) as sessao:
        await declarar_empresa(sessao, cenario.abacaxi)
        with pytest.raises(DBAPIError) as erro:
            await sessao.execute(
                text(
                    "INSERT INTO products (tenant_id, id, code, description, active) "
                    "VALUES (:t, :i, :c, 'contrabando', true)"
                ),
                {"t": cenario.uva, "i": uuid.uuid4(), "c": f"X-{cenario.sufixo}"},
            )

    assert "row-level security" in str(erro.value).lower()


# --- 3. sem empresa declarada: zero linhas, sem erro --------------------------


async def test_sem_empresa_declarada_volta_vazio_sem_erro(
    motor_runtime: AsyncEngine, cenario: Cenario
) -> None:
    """A propriedade que se está comprando: esquecer a empresa dá **lista vazia**.

    Nunca dado da empresa errada, e nunca exceção. Em troca, "voltou vazio do nada" passa
    a ser sintoma comum em desenvolvimento — e a primeira hipótese é sempre a mesma.
    """
    async with AsyncSession(motor_runtime) as sessao:
        # Positivo: com empresa, vem coisa. Sem esta linha o teste passaria contra um banco
        # vazio, contra uma tabela inexistente, contra qualquer coisa.
        await declarar_empresa(sessao, cenario.abacaxi)
        assert (
            await ProdutoService(sessao).listar(_params(), ProdutoSaida.model_validate)
        ).total > 0

    async with AsyncSession(motor_runtime) as sessao:
        pagina = await ProdutoService(sessao).listar(_params(), ProdutoSaida.model_validate)

    assert pagina.total == 0
    assert pagina.itens == []


async def test_conexao_reciclada_do_pool_nao_carrega_a_empresa_anterior(
    motor_runtime: AsyncEngine, cenario: Cenario
) -> None:
    """O caso do pool, que é o que justifica `SET LOCAL` em vez de `SET`.

    A mesma conexão física atende dois pedidos seguidos. Se o segundo enxergasse a empresa
    do primeiro, o vazamento entre empresas aconteceria sem ninguém escrever uma linha de
    código errada — bastaria o pool reciclar a conexão.
    """
    from sqlalchemy.ext.asyncio import create_async_engine

    # Um único slot: o segundo uso é garantidamente a mesma conexão física, não sorteio.
    motor = create_async_engine(motor_runtime.url, pool_size=1, max_overflow=0)
    try:
        async with AsyncSession(motor) as sessao:
            await declarar_empresa(sessao, cenario.abacaxi)
            assert (
                await ProdutoService(sessao).listar(_params(), ProdutoSaida.model_validate)
            ).total > 0

        async with AsyncSession(motor) as sessao:
            pagina = await ProdutoService(sessao).listar(_params(), ProdutoSaida.model_validate)
        assert pagina.total == 0, "a conexão devolvida ao pool carregou a empresa anterior"
    finally:
        await motor.dispose()


async def test_guc_vazio_nao_estoura_o_cast(motor_runtime: AsyncEngine) -> None:
    """O que o `NULLIF` do predicado compra, isolado.

    Sem ele, `''::uuid` levanta `invalid input syntax for type uuid` e a listagem devolve
    **500** em vez de vazio — numa conexão de pool que ainda não recebeu a empresa, ou seja,
    de forma intermitente e difícil de reproduzir. Com ele o predicado dá NULL, nada casa.
    """
    async with motor_runtime.connect() as conexao:
        await conexao.execute(SQL_DECLARAR, {"empresa": ""})
        linhas = (await conexao.execute(text("SELECT id FROM products"))).all()

    assert linhas == []


# --- 4. a aplicação não desliga nem burla a política -------------------------


async def test_papel_de_runtime_nao_e_superusuario_nem_bypassrls(
    motor_runtime: AsyncEngine,
) -> None:
    """Pré-condição de tudo o mais. Se falhar aqui, os outros três não provam nada."""
    async with motor_runtime.connect() as conexao:
        linha = (
            await conexao.execute(
                text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
            )
        ).one()

    assert linha.rolsuper is False, "a aplicação não pode conectar como superusuário"
    assert linha.rolbypassrls is False, "BYPASSRLS tornaria toda a política decorativa"


@pytest.mark.parametrize(
    "comando",
    [
        "ALTER TABLE products DISABLE ROW LEVEL SECURITY",
        "ALTER TABLE products NO FORCE ROW LEVEL SECURITY",
        'DROP POLICY "products_sel" ON products',
        "CREATE POLICY tudo_liberado ON products FOR SELECT USING (true)",
    ],
)
async def test_aplicacao_nao_consegue_afrouxar_a_politica(
    motor_runtime: AsyncEngine, comando: str
) -> None:
    """Nenhum caminho de DDL sobra para o papel de runtime.

    `FORCE` protege contra o dono ignorar a política por padrão; isto protege contra ele
    simplesmente desligá-la. As duas coisas juntas são o que separa RLS de RLS decorativo.
    """
    async with motor_runtime.connect() as conexao:
        with pytest.raises(DBAPIError) as erro:
            await conexao.execute(text(comando))

    assert "must be owner" in str(erro.value).lower() or "denied" in str(erro.value).lower()


async def test_toda_tabela_com_tenant_id_tem_rls_forcado(motor_runtime: AsyncEngine) -> None:
    """Confere no catálogo, não pelo comportamento, e **descobre** a lista em vez de repeti-la.

    Um teste de comportamento em `products` não diz nada sobre `employee_company`; e uma
    lista escrita à mão aqui protegeria exatamente as tabelas de que alguém se lembrou.
    Então o teste pergunta ao banco quem tem `tenant_id` e cobra política de todas — é o
    que pega a tabela nova que nasce por empresa e sai sem RLS.

    O cruzamento com `TABELAS_POR_EMPRESA` fecha o outro lado: se o modelo declarar uma
    tabela por empresa que a migração não criou (ou vice-versa), os dois conjuntos deixam
    de bater antes de qualquer asserção sobre política.
    """
    async with motor_runtime.connect() as conexao:
        com_tenant = {
            linha.table_name
            for linha in (
                await conexao.execute(
                    text(
                        "SELECT table_name FROM information_schema.columns "
                        "WHERE table_schema = 'public' AND column_name = 'tenant_id'"
                    )
                )
            ).all()
        }

        estado = (
            await conexao.execute(
                text(
                    """
                    SELECT c.relname,
                           c.relrowsecurity,
                           c.relforcerowsecurity,
                           count(p.polname) AS politicas
                      FROM pg_class c
                      JOIN pg_namespace n ON n.oid = c.relnamespace
                      LEFT JOIN pg_policy p ON p.polrelid = c.oid
                     WHERE n.nspname = 'public'
                       AND c.relname = ANY(:tabelas)
                     GROUP BY c.relname, c.relrowsecurity, c.relforcerowsecurity
                    """
                ),
                {"tabelas": sorted(com_tenant)},
            )
        ).all()

    assert com_tenant == set(TABELAS_POR_EMPRESA), (
        "as tabelas com `tenant_id` no banco não são as que o modelo declara por empresa"
    )
    assert {linha.relname for linha in estado} == com_tenant

    for linha in estado:
        assert linha.relrowsecurity, f"{linha.relname}: RLS não está habilitado"
        assert linha.relforcerowsecurity, f"{linha.relname}: falta FORCE — o dono ignoraria"
        assert linha.politicas == 4, (
            f"{linha.relname}: esperadas 4 políticas (uma por comando), veio {linha.politicas}"
        )


def _params(**kwargs: object) -> ListParams:
    """`ListParams` é dependência do FastAPI; fora de rota, monta-se na mão."""
    padrao: dict[str, object] = {
        "busca": None,
        "busca_codigo": None,
        "pagina": 1,
        "tamanho": 50,
        "ordenar_por": None,
        "ordem": "asc",
        "ativo": None,
    }
    padrao.update(kwargs)
    return ListParams(**padrao)  # type: ignore[arg-type]
