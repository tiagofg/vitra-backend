"""Catálogo de produtos (S2): campos novos, especificação JSONB e as três grades do
`PUT /produtos/{id}` (variantes, fornecedores, grupos relacionados)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core.tenancy import declarar_empresa
from app.modules.empresa.models import Empresa
from app.modules.produtos.models import Variante
from tests.cenario import Cenario


def _cabecalho(cabecalho_admin: dict[str, str], empresa: Empresa) -> dict[str, str]:
    return {**cabecalho_admin, "X-Empresa-Id": str(empresa.id)}


async def _criar_apoio(
    cliente: AsyncClient, cabecalho_admin: dict[str, str], dominio: str, descricao: str
) -> str:
    resposta = await cliente.post(
        f"/api/v1/apoio/{dominio}", json={"descricao": descricao}, headers=cabecalho_admin
    )
    assert resposta.status_code == 201, resposta.text
    return str(resposta.json()["id"])


async def test_crud_de_produto_com_campos_novos(
    cliente: AsyncClient, cabecalho_admin: dict[str, str], empresa: Empresa
) -> None:
    cabecalho = _cabecalho(cabecalho_admin, empresa)
    marca_id = await _criar_apoio(cliente, cabecalho_admin, "marca", "Lumini")

    criado = await cliente.post(
        "/api/v1/produtos",
        json={
            "codigo": "PROD001",
            "descricao": "Pendente Aurora",
            "marca_id": marca_id,
            "ncm": "94054010",
            "especificacao": {"potencia_watts": 12, "fluxo_luminoso_lumens": 1200, "ip": "IP65"},
        },
        headers=cabecalho,
    )
    assert criado.status_code == 201, criado.text
    corpo = criado.json()
    assert corpo["marca_id"] == marca_id
    assert corpo["especificacao"]["potencia_watts"] == 12
    assert Decimal(corpo["qtd_entrada"]) == 1  # default

    produto_id = corpo["id"]
    atualizado = await cliente.put(
        f"/api/v1/produtos/{produto_id}",
        json={"descricao": "Pendente Aurora — revisado"},
        headers=cabecalho,
    )
    assert atualizado.status_code == 200
    assert atualizado.json()["descricao"] == "Pendente Aurora — revisado"
    # PUT parcial não apaga o que não veio no corpo.
    assert atualizado.json()["marca_id"] == marca_id

    desativado = await cliente.delete(f"/api/v1/produtos/{produto_id}", headers=cabecalho)
    assert desativado.status_code == 200
    assert desativado.json()["ativo"] is False


async def test_especificacao_com_campo_desconhecido_da_422(
    cliente: AsyncClient, cabecalho_admin: dict[str, str], empresa: Empresa
) -> None:
    """`EspecificacaoLuminaria` é `extra=\"forbid\"`: campo digitado errado estoura na hora,
    não vira chave morta dentro do JSONB."""
    cabecalho = _cabecalho(cabecalho_admin, empresa)
    resposta = await cliente.post(
        "/api/v1/produtos",
        json={
            "codigo": "PROD001",
            "descricao": "Teste",
            "especificacao": {"potencia_watts_errado": 12},
        },
        headers=cabecalho,
    )
    assert resposta.status_code == 422


async def test_produto_marca_precisa_ser_do_dominio_certo(
    cliente: AsyncClient, cabecalho_admin: dict[str, str], empresa: Empresa
) -> None:
    """Prova o caso positivo antes do negativo — mesmo padrão de `Cliente.profissao_id`."""
    cabecalho = _cabecalho(cabecalho_admin, empresa)
    marca_id = await _criar_apoio(cliente, cabecalho_admin, "marca", "Lumini")
    tipo_produto_id = await _criar_apoio(cliente, cabecalho_admin, "tipo_produto", "Luminária")

    valido = await cliente.post(
        "/api/v1/produtos",
        json={"codigo": "PROD001", "descricao": "Teste", "marca_id": marca_id},
        headers=cabecalho,
    )
    assert valido.status_code == 201, valido.text

    invalido = await cliente.post(
        "/api/v1/produtos",
        json={"codigo": "PROD002", "descricao": "Teste 2", "marca_id": tipo_produto_id},
        headers=cabecalho,
    )
    assert invalido.status_code == 422
    assert invalido.json()["erro"]["codigo"] == "dominio_invalido"


async def test_grade_de_variantes_preserva_id_no_diff(
    cliente: AsyncClient, cabecalho_admin: dict[str, str], empresa: Empresa
) -> None:
    cabecalho = _cabecalho(cabecalho_admin, empresa)
    acabamento_id = await _criar_apoio(cliente, cabecalho_admin, "acabamento", "Preto")
    tamanho_p_id = await _criar_apoio(cliente, cabecalho_admin, "tamanho", "P")
    tamanho_g_id = await _criar_apoio(cliente, cabecalho_admin, "tamanho", "G")

    produto_id = (
        await cliente.post(
            "/api/v1/produtos",
            json={"codigo": "PROD001", "descricao": "Teste"},
            headers=cabecalho,
        )
    ).json()["id"]

    primeira = await cliente.put(
        f"/api/v1/produtos/{produto_id}",
        json={
            "variantes": [
                {"acabamento_id": acabamento_id, "tamanho_id": tamanho_p_id},
                {"acabamento_id": acabamento_id, "tamanho_id": tamanho_g_id},
            ]
        },
        headers=cabecalho,
    )
    assert primeira.status_code == 200, primeira.text
    variantes = primeira.json()["variantes"]
    assert len(variantes) == 2
    id_p = next(v["id"] for v in variantes if v["tamanho_id"] == tamanho_p_id)
    id_g = next(v["id"] for v in variantes if v["tamanho_id"] == tamanho_g_id)

    # Segunda chamada: mantém a P (com o mesmo id), desativa ela, remove a G, acrescenta
    # nada — diff por PK, não delete-all/insert-all.
    segunda = await cliente.put(
        f"/api/v1/produtos/{produto_id}",
        json={
            "variantes": [
                {
                    "id": id_p,
                    "acabamento_id": acabamento_id,
                    "tamanho_id": tamanho_p_id,
                    "ativo": False,
                }
            ]
        },
        headers=cabecalho,
    )
    assert segunda.status_code == 200, segunda.text
    variantes_depois = segunda.json()["variantes"]
    assert len(variantes_depois) == 1
    assert variantes_depois[0]["id"] == id_p, "o id da variante mantida não pode mudar"
    assert variantes_depois[0]["ativo"] is False
    assert id_g not in {v["id"] for v in variantes_depois}


async def test_grade_de_variantes_confere_dominio(
    cliente: AsyncClient, cabecalho_admin: dict[str, str], empresa: Empresa
) -> None:
    """`substituir_conjunto` cria `Variante` fora de `criar()`/`_antes_de_criar` — sem
    checagem própria, `acabamento_id`/`tamanho_id` aceitariam qualquer domínio."""
    cabecalho = _cabecalho(cabecalho_admin, empresa)
    marca_id = await _criar_apoio(cliente, cabecalho_admin, "marca", "Lumini")
    tamanho_id = await _criar_apoio(cliente, cabecalho_admin, "tamanho", "P")

    produto_id = (
        await cliente.post(
            "/api/v1/produtos", json={"codigo": "PROD001", "descricao": "Teste"}, headers=cabecalho
        )
    ).json()["id"]

    resposta = await cliente.put(
        f"/api/v1/produtos/{produto_id}",
        # `acabamento_id` aponta para um valor de `marca`, não de `acabamento`.
        json={"variantes": [{"acabamento_id": marca_id, "tamanho_id": tamanho_id}]},
        headers=cabecalho,
    )
    assert resposta.status_code == 422
    assert resposta.json()["erro"]["codigo"] == "dominio_invalido"


async def test_grade_de_fornecedores_um_padrao_por_produto(
    cliente: AsyncClient, cabecalho_admin: dict[str, str], empresa: Empresa
) -> None:
    cabecalho = _cabecalho(cabecalho_admin, empresa)
    fornecedor_a = (
        await cliente.post(
            "/api/v1/fornecedores",
            json={"codigo": "FOR001", "razao_social": "Fornecedor A"},
            headers=cabecalho,
        )
    ).json()["id"]
    fornecedor_b = (
        await cliente.post(
            "/api/v1/fornecedores",
            json={"codigo": "FOR002", "razao_social": "Fornecedor B"},
            headers=cabecalho,
        )
    ).json()["id"]
    produto_id = (
        await cliente.post(
            "/api/v1/produtos", json={"codigo": "PROD001", "descricao": "Teste"}, headers=cabecalho
        )
    ).json()["id"]

    valido = await cliente.put(
        f"/api/v1/produtos/{produto_id}",
        json={
            "fornecedores": [
                {"fornecedor_id": fornecedor_a, "codigo_fornecedor": "A-123", "padrao": True},
                {"fornecedor_id": fornecedor_b, "codigo_fornecedor": "B-456", "padrao": False},
            ]
        },
        headers=cabecalho,
    )
    assert valido.status_code == 200, valido.text
    assert len(valido.json()["fornecedores"]) == 2

    # Dois fornecedores padrão ao mesmo tempo: o índice único parcial recusa. Ambos sem
    # `id` — é a duplicação do par (produto, fornecedor) que dá 409 aqui, não o `padrao`
    # (ver `test_grade_de_fornecedores_troca_qual_e_padrao` para esse caso).
    invalido = await cliente.put(
        f"/api/v1/produtos/{produto_id}",
        json={
            "fornecedores": [
                {"fornecedor_id": fornecedor_a, "padrao": True},
                {"fornecedor_id": fornecedor_b, "padrao": True},
            ]
        },
        headers=cabecalho,
    )
    assert invalido.status_code == 409, invalido.text


@pytest.mark.parametrize("liga_primeiro", [False, True])
async def test_grade_de_fornecedores_troca_qual_e_padrao(
    cliente: AsyncClient, cabecalho_admin: dict[str, str], empresa: Empresa, liga_primeiro: bool
) -> None:
    """O caminho documentado de trocar o padrão: os dois itens já existentes, só
    movendo a bandeira — nas duas ordens possíveis. Achado de revisão (rodada 1):
    `substituir_conjunto` fazia um só `flush()` em lote, e a ordem das duas instruções
    `UPDATE` ficava a critério do `Session`, não da entrada — o índice único parcial
    (`padrao`) via as duas linhas com a bandeira ligada ao mesmo tempo e recusava com
    409. Achado de revisão (rodada 2): a correção da rodada 1 (`flush()` por item na
    ordem da entrada) só funcionava quando o cliente por acaso mandava "desliga" antes
    de "liga" — a ordem inversa (`liga_primeiro=True`) continuava com 409.
    `campo_exclusivo="padrao"` em `substituir_conjunto` resolve para as duas ordens: ele
    processa quem desliga a bandeira antes de quem liga, **independente** da ordem da
    `entrada`."""
    cabecalho = _cabecalho(cabecalho_admin, empresa)
    fornecedor_a = (
        await cliente.post(
            "/api/v1/fornecedores",
            json={"codigo": "FOR001", "razao_social": "Fornecedor A"},
            headers=cabecalho,
        )
    ).json()["id"]
    fornecedor_b = (
        await cliente.post(
            "/api/v1/fornecedores",
            json={"codigo": "FOR002", "razao_social": "Fornecedor B"},
            headers=cabecalho,
        )
    ).json()["id"]
    produto_id = (
        await cliente.post(
            "/api/v1/produtos", json={"codigo": "PROD001", "descricao": "Teste"}, headers=cabecalho
        )
    ).json()["id"]

    primeira = await cliente.put(
        f"/api/v1/produtos/{produto_id}",
        json={
            "fornecedores": [
                {"fornecedor_id": fornecedor_a, "padrao": True},
                {"fornecedor_id": fornecedor_b, "padrao": False},
            ]
        },
        headers=cabecalho,
    )
    assert primeira.status_code == 200, primeira.text
    por_fornecedor = {f["fornecedor_id"]: f["id"] for f in primeira.json()["fornecedores"]}

    desliga = {"id": por_fornecedor[fornecedor_a], "fornecedor_id": fornecedor_a, "padrao": False}
    liga = {"id": por_fornecedor[fornecedor_b], "fornecedor_id": fornecedor_b, "padrao": True}
    ordem = [liga, desliga] if liga_primeiro else [desliga, liga]

    troca = await cliente.put(
        f"/api/v1/produtos/{produto_id}",
        json={"fornecedores": ordem},
        headers=cabecalho,
    )
    assert troca.status_code == 200, troca.text
    padrao_agora = {f["fornecedor_id"]: f["padrao"] for f in troca.json()["fornecedores"]}
    assert padrao_agora == {fornecedor_a: False, fornecedor_b: True}


async def test_grade_de_grupos_relacionados(
    cliente: AsyncClient, cabecalho_admin: dict[str, str], empresa: Empresa
) -> None:
    cabecalho = _cabecalho(cabecalho_admin, empresa)
    produto_id = (
        await cliente.post(
            "/api/v1/produtos", json={"codigo": "PROD001", "descricao": "Teste"}, headers=cabecalho
        )
    ).json()["id"]

    resposta = await cliente.put(
        f"/api/v1/produtos/{produto_id}",
        json={"grupos_relacionados": [{"nome": "Kit banheiro", "padrao": True}]},
        headers=cabecalho,
    )
    assert resposta.status_code == 200, resposta.text
    grupos = resposta.json()["grupos_relacionados"]
    assert len(grupos) == 1
    assert grupos[0]["nome"] == "Kit banheiro"


async def test_put_parcial_omitindo_grade_nao_mexe_nela(
    cliente: AsyncClient, cabecalho_admin: dict[str, str], empresa: Empresa
) -> None:
    """`None` (o padrão quando o campo nem aparece no corpo) não mexe na coleção — só uma
    lista explícita (mesmo vazia) faz `substituir_conjunto` rodar."""
    cabecalho = _cabecalho(cabecalho_admin, empresa)
    acabamento_id = await _criar_apoio(cliente, cabecalho_admin, "acabamento", "Preto")
    tamanho_id = await _criar_apoio(cliente, cabecalho_admin, "tamanho", "P")
    produto_id = (
        await cliente.post(
            "/api/v1/produtos", json={"codigo": "PROD001", "descricao": "Teste"}, headers=cabecalho
        )
    ).json()["id"]
    await cliente.put(
        f"/api/v1/produtos/{produto_id}",
        json={"variantes": [{"acabamento_id": acabamento_id, "tamanho_id": tamanho_id}]},
        headers=cabecalho,
    )

    sem_tocar_na_grade = await cliente.put(
        f"/api/v1/produtos/{produto_id}",
        json={"descricao": "Só mudando a descrição"},
        headers=cabecalho,
    )
    assert sem_tocar_na_grade.status_code == 200
    assert len(sem_tocar_na_grade.json()["variantes"]) == 1

    limpando_a_grade = await cliente.put(
        f"/api/v1/produtos/{produto_id}", json={"variantes": []}, headers=cabecalho
    )
    assert limpando_a_grade.status_code == 200
    assert limpando_a_grade.json()["variantes"] == []


async def test_variante_de_outra_empresa_nao_aparece_no_recorte(
    motor_runtime: AsyncEngine, cenario: Cenario
) -> None:
    """`product_variants` está sob RLS como qualquer tabela por empresa — reforça o que
    `test_rls_isolamento.py::test_fk_composta_recusa_preco_de_produto_de_outra_empresa` já
    prova para a FK composta, aqui do lado da leitura simples."""
    async with AsyncSession(motor_runtime) as sessao:
        await declarar_empresa(sessao, cenario.uva)
        variantes = (
            (
                await sessao.execute(
                    select(Variante.id).where(Variante.id == cenario.variante_livre_abacaxi)
                )
            )
            .scalars()
            .all()
        )

    assert variantes == []


# --- itens de um grupo relacionado -------------------------------------------------


async def test_item_relacionado_cria_lista_e_remove(
    cliente: AsyncClient, cabecalho_admin: dict[str, str], empresa: Empresa
) -> None:
    cabecalho = _cabecalho(cabecalho_admin, empresa)
    produto_principal = (
        await cliente.post(
            "/api/v1/produtos",
            json={"codigo": "PEND001", "descricao": "Pendente"},
            headers=cabecalho,
        )
    ).json()["id"]
    produto_relacionado = (
        await cliente.post(
            "/api/v1/produtos", json={"codigo": "SUP001", "descricao": "Suporte"}, headers=cabecalho
        )
    ).json()["id"]
    grupo_id = (
        await cliente.put(
            f"/api/v1/produtos/{produto_principal}",
            json={"grupos_relacionados": [{"nome": "Acessórios"}]},
            headers=cabecalho,
        )
    ).json()["grupos_relacionados"][0]["id"]

    base = f"/api/v1/produtos/{produto_principal}/grupos-relacionados/{grupo_id}/itens"

    # `quantidade` preenchida = kit.
    criado = await cliente.post(
        base, json={"produto_id": produto_relacionado, "quantidade": "2"}, headers=cabecalho
    )
    assert criado.status_code == 201, criado.text
    assert Decimal(criado.json()["quantidade"]) == 2

    listado = await cliente.get(base, headers=cabecalho)
    assert len(listado.json()) == 1

    item_id = criado.json()["id"]
    removido = await cliente.delete(f"{base}/{item_id}", headers=cabecalho)
    assert removido.status_code == 204

    listado_depois = await cliente.get(base, headers=cabecalho)
    assert listado_depois.json() == []


async def test_item_relacionado_recusa_ciclo_com_o_proprio_produto(
    cliente: AsyncClient, cabecalho_admin: dict[str, str], empresa: Empresa
) -> None:
    cabecalho = _cabecalho(cabecalho_admin, empresa)
    produto_id = (
        await cliente.post(
            "/api/v1/produtos",
            json={"codigo": "PEND001", "descricao": "Pendente"},
            headers=cabecalho,
        )
    ).json()["id"]
    grupo_id = (
        await cliente.put(
            f"/api/v1/produtos/{produto_id}",
            json={"grupos_relacionados": [{"nome": "Acessórios"}]},
            headers=cabecalho,
        )
    ).json()["grupos_relacionados"][0]["id"]

    resposta = await cliente.post(
        f"/api/v1/produtos/{produto_id}/grupos-relacionados/{grupo_id}/itens",
        json={"produto_id": produto_id},
        headers=cabecalho,
    )
    assert resposta.status_code == 422
    assert resposta.json()["erro"]["codigo"] == "item_relacionado_ciclico"


async def test_item_relacionado_recusa_variante_de_outro_produto(
    cliente: AsyncClient, cabecalho_admin: dict[str, str], empresa: Empresa
) -> None:
    cabecalho = _cabecalho(cabecalho_admin, empresa)
    acabamento_id = await _criar_apoio(cliente, cabecalho_admin, "acabamento", "Preto")
    tamanho_id = await _criar_apoio(cliente, cabecalho_admin, "tamanho", "P")

    produto_principal = (
        await cliente.post(
            "/api/v1/produtos",
            json={"codigo": "PEND001", "descricao": "Pendente"},
            headers=cabecalho,
        )
    ).json()["id"]
    produto_relacionado = (
        await cliente.post(
            "/api/v1/produtos", json={"codigo": "SUP001", "descricao": "Suporte"}, headers=cabecalho
        )
    ).json()["id"]
    # Variante de um produto QUALQUER, diferente de `produto_relacionado`.
    outro_produto = (
        await cliente.post(
            "/api/v1/produtos", json={"codigo": "OUT001", "descricao": "Outro"}, headers=cabecalho
        )
    ).json()["id"]
    variante_de_outro = (
        await cliente.put(
            f"/api/v1/produtos/{outro_produto}",
            json={"variantes": [{"acabamento_id": acabamento_id, "tamanho_id": tamanho_id}]},
            headers=cabecalho,
        )
    ).json()["variantes"][0]["id"]

    grupo_id = (
        await cliente.put(
            f"/api/v1/produtos/{produto_principal}",
            json={"grupos_relacionados": [{"nome": "Acessórios"}]},
            headers=cabecalho,
        )
    ).json()["grupos_relacionados"][0]["id"]

    resposta = await cliente.post(
        f"/api/v1/produtos/{produto_principal}/grupos-relacionados/{grupo_id}/itens",
        json={"produto_id": produto_relacionado, "variante_id": variante_de_outro},
        headers=cabecalho,
    )
    assert resposta.status_code == 422
    assert resposta.json()["erro"]["codigo"] == "variante_de_outro_produto"


async def test_item_relacionado_grupo_de_outro_produto_da_404(
    cliente: AsyncClient, cabecalho_admin: dict[str, str], empresa: Empresa
) -> None:
    cabecalho = _cabecalho(cabecalho_admin, empresa)
    produto_a = (
        await cliente.post(
            "/api/v1/produtos", json={"codigo": "PRODA", "descricao": "A"}, headers=cabecalho
        )
    ).json()["id"]
    produto_b = (
        await cliente.post(
            "/api/v1/produtos", json={"codigo": "PRODB", "descricao": "B"}, headers=cabecalho
        )
    ).json()["id"]
    grupo_de_a = (
        await cliente.put(
            f"/api/v1/produtos/{produto_a}",
            json={"grupos_relacionados": [{"nome": "Grupo A"}]},
            headers=cabecalho,
        )
    ).json()["grupos_relacionados"][0]["id"]

    # Pede o grupo de A através do path de B — não pode achar.
    resposta = await cliente.get(
        f"/api/v1/produtos/{produto_b}/grupos-relacionados/{grupo_de_a}/itens", headers=cabecalho
    )
    assert resposta.status_code == 404
