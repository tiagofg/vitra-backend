from __future__ import annotations

from httpx import AsyncClient

from app.modules.apoio.models import DominioApoio
from app.modules.apoio.service import slugificar
from app.modules.empresa.models import Empresa


async def test_criar_e_listar_valor_de_apoio(
    cliente: AsyncClient, cabecalho_admin: dict[str, str]
) -> None:
    criado = await cliente.post(
        "/api/v1/apoio/marca", json={"descricao": "Lumini"}, headers=cabecalho_admin
    )
    assert criado.status_code == 201
    corpo = criado.json()
    assert corpo["dominio"] == "marca"
    assert corpo["descricao"] == "Lumini"

    listado = await cliente.get("/api/v1/apoio/marca", headers=cabecalho_admin)
    assert listado.status_code == 200
    pagina = listado.json()
    assert pagina["total"] == 1
    assert pagina["itens"][0]["id"] == corpo["id"]


async def test_codigo_e_derivado_da_descricao_quando_omitido(
    cliente: AsyncClient, cabecalho_admin: dict[str, str]
) -> None:
    """É o botão `...` da tela: o usuário digita só a descrição."""
    resposta = await cliente.post(
        "/api/v1/apoio/acabamento",
        json={"descricao": "Alumínio Escovado"},
        headers=cabecalho_admin,
    )
    assert resposta.status_code == 201
    assert resposta.json()["codigo"] == "aluminio_escovado"


async def test_codigo_derivado_nao_colide(
    cliente: AsyncClient, cabecalho_admin: dict[str, str]
) -> None:
    primeiro = await cliente.post(
        "/api/v1/apoio/marca", json={"descricao": "Lumini"}, headers=cabecalho_admin
    )
    segundo = await cliente.post(
        "/api/v1/apoio/marca", json={"descricao": "Lumini"}, headers=cabecalho_admin
    )
    assert primeiro.json()["codigo"] == "lumini"
    assert segundo.json()["codigo"] == "lumini_2"


async def test_codigo_repetido_no_mesmo_dominio_e_conflito(
    cliente: AsyncClient, cabecalho_admin: dict[str, str]
) -> None:
    dados = {"descricao": "Lumini", "codigo": "lumini"}
    await cliente.post("/api/v1/apoio/marca", json=dados, headers=cabecalho_admin)
    repetido = await cliente.post("/api/v1/apoio/marca", json=dados, headers=cabecalho_admin)
    assert repetido.status_code == 409
    assert repetido.json()["erro"]["codigo"] == "conflito"


async def test_mesmo_codigo_em_dominios_diferentes_convive(
    cliente: AsyncClient, cabecalho_admin: dict[str, str]
) -> None:
    """Uma tabela para 19 combos só funciona se o domínio isolar de verdade."""
    a = await cliente.post(
        "/api/v1/apoio/marca", json={"descricao": "Preto", "codigo": "preto"},
        headers=cabecalho_admin,
    )
    b = await cliente.post(
        "/api/v1/apoio/acabamento", json={"descricao": "Preto", "codigo": "preto"},
        headers=cabecalho_admin,
    )
    assert a.status_code == 201
    assert b.status_code == 201


async def test_listagem_nao_vaza_entre_dominios(
    cliente: AsyncClient, cabecalho_admin: dict[str, str]
) -> None:
    await cliente.post(
        "/api/v1/apoio/marca", json={"descricao": "Lumini"}, headers=cabecalho_admin
    )
    resposta = await cliente.get("/api/v1/apoio/acabamento", headers=cabecalho_admin)
    assert resposta.json()["total"] == 0


async def test_obter_por_id_no_dominio_errado_da_404(
    cliente: AsyncClient, cabecalho_admin: dict[str, str]
) -> None:
    criado = await cliente.post(
        "/api/v1/apoio/marca", json={"descricao": "Lumini"}, headers=cabecalho_admin
    )
    item_id = criado.json()["id"]
    resposta = await cliente.get(f"/api/v1/apoio/acabamento/{item_id}", headers=cabecalho_admin)
    assert resposta.status_code == 404


async def test_dominio_inexistente_e_rejeitado(
    cliente: AsyncClient, cabecalho_admin: dict[str, str]
) -> None:
    resposta = await cliente.get("/api/v1/apoio/dominio_inventado", headers=cabecalho_admin)
    assert resposta.status_code == 422


async def test_lookup_devolve_formato_padronizado(
    cliente: AsyncClient, cabecalho_admin: dict[str, str]
) -> None:
    await cliente.post(
        "/api/v1/apoio/marca", json={"descricao": "Lumini"}, headers=cabecalho_admin
    )
    await cliente.post(
        "/api/v1/apoio/marca", json={"descricao": "Bella Luce"}, headers=cabecalho_admin
    )

    resposta = await cliente.get(
        "/api/v1/apoio/marca/lookup", params={"q": "lumi"}, headers=cabecalho_admin
    )
    assert resposta.status_code == 200
    itens = resposta.json()
    assert len(itens) == 1
    assert set(itens[0]) == {"id", "codigo", "label", "extras"}
    assert itens[0]["label"] == "Lumini"


async def test_lookup_por_empresa_inclui_valores_globais(
    cliente: AsyncClient, cabecalho_admin: dict[str, str], empresa: Empresa
) -> None:
    await cliente.post(
        "/api/v1/apoio/marca", json={"descricao": "Global"}, headers=cabecalho_admin
    )
    await cliente.post(
        "/api/v1/apoio/marca",
        json={"descricao": "Só da Vertz", "empresa_id": str(empresa.id)},
        headers=cabecalho_admin,
    )

    resposta = await cliente.get(
        "/api/v1/apoio/marca/lookup",
        params={"empresa_id": str(empresa.id)},
        headers=cabecalho_admin,
    )
    rotulos = {item["label"] for item in resposta.json()}
    assert rotulos == {"Global", "Só da Vertz"}


async def test_lookup_ignora_desativados(
    cliente: AsyncClient, cabecalho_admin: dict[str, str]
) -> None:
    criado = await cliente.post(
        "/api/v1/apoio/marca", json={"descricao": "Lumini"}, headers=cabecalho_admin
    )
    item_id = criado.json()["id"]

    apagado = await cliente.delete(f"/api/v1/apoio/marca/{item_id}", headers=cabecalho_admin)
    assert apagado.status_code == 200
    assert apagado.json()["ativo"] is False

    resposta = await cliente.get("/api/v1/apoio/marca/lookup", headers=cabecalho_admin)
    assert resposta.json() == []

    # Desativado é diferente de apagado: continua no banco.
    ainda_la = await cliente.get(f"/api/v1/apoio/marca/{item_id}", headers=cabecalho_admin)
    assert ainda_la.status_code == 200


async def test_atualizar_descricao(
    cliente: AsyncClient, cabecalho_admin: dict[str, str]
) -> None:
    criado = await cliente.post(
        "/api/v1/apoio/marca", json={"descricao": "Lumini"}, headers=cabecalho_admin
    )
    item_id = criado.json()["id"]
    resposta = await cliente.put(
        f"/api/v1/apoio/marca/{item_id}",
        json={"descricao": "Lumini Design"},
        headers=cabecalho_admin,
    )
    assert resposta.status_code == 200
    assert resposta.json()["descricao"] == "Lumini Design"
    assert resposta.json()["codigo"] == "lumini"


async def test_endpoint_de_dominios_lista_todos_os_combos(
    cliente: AsyncClient, cabecalho_admin: dict[str, str]
) -> None:
    resposta = await cliente.get("/api/v1/apoio/dominios", headers=cabecalho_admin)
    assert resposta.status_code == 200
    assert len(resposta.json()) == len(DominioApoio)


def test_slugificar_remove_acento_e_pontuacao() -> None:
    assert slugificar("Designer\\Modelo") == "designer_modelo"
    assert slugificar("Grau de Instrução") == "grau_de_instrucao"
    assert slugificar("!!!") == "item"
    assert len(slugificar("a" * 80)) == 30
