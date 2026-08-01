from __future__ import annotations

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core.security import gerar_hash_senha
from app.core.tenancy import declarar_empresa
from app.modules.auth.models import Usuario, VinculoEmpresa
from app.modules.empresa.models import Empresa
from app.modules.pessoas.models import Cliente, Fornecedor
from tests.cenario import Cenario


def _cabecalho(cabecalho_admin: dict[str, str], empresa: Empresa) -> dict[str, str]:
    return {**cabecalho_admin, "X-Empresa-Id": str(empresa.id)}


# --- Cliente --------------------------------------------------------------------


async def test_crud_de_cliente(
    cliente: AsyncClient, cabecalho_admin: dict[str, str], empresa: Empresa
) -> None:
    cabecalho = _cabecalho(cabecalho_admin, empresa)

    criado = await cliente.post(
        "/api/v1/clientes",
        json={
            "codigo": "CLI001",
            "nome": "Maria Andrade",
            "tipo_pessoa": "fisica",
            "cpf_cnpj": "123.456.789-00",
            "endereco_logradouro": "Rua das Flores",
            "telefone": "1133334444",
        },
        headers=cabecalho,
    )
    assert criado.status_code == 201, criado.text
    corpo = criado.json()
    # Máscara sai na entrada, nunca no banco/saída — mesma convenção de CNPJ.
    assert corpo["cpf_cnpj"] == "12345678900"
    assert corpo["tenant_id"] == str(empresa.id)
    assert corpo["ativo"] is True

    cliente_id = corpo["id"]
    atualizado = await cliente.put(
        f"/api/v1/clientes/{cliente_id}",
        json={"nome": "Maria Andrade Silva"},
        headers=cabecalho,
    )
    assert atualizado.status_code == 200
    assert atualizado.json()["nome"] == "Maria Andrade Silva"
    # PUT parcial não apaga o que não veio no corpo.
    assert atualizado.json()["cpf_cnpj"] == "12345678900"

    desativado = await cliente.delete(f"/api/v1/clientes/{cliente_id}", headers=cabecalho)
    assert desativado.status_code == 200
    assert desativado.json()["ativo"] is False


async def test_codigo_de_cliente_e_unico_por_empresa(
    cliente: AsyncClient, cabecalho_admin: dict[str, str], empresa: Empresa
) -> None:
    cabecalho = _cabecalho(cabecalho_admin, empresa)
    dados = {"codigo": "CLI001", "nome": "Fulano", "tipo_pessoa": "fisica"}
    await cliente.post("/api/v1/clientes", json=dados, headers=cabecalho)
    repetido = await cliente.post("/api/v1/clientes", json=dados, headers=cabecalho)
    assert repetido.status_code == 409
    assert repetido.json()["erro"]["campos"] == {"codigo": "já utilizado"}


async def test_cliente_inexistente_da_404(
    cliente: AsyncClient, cabecalho_admin: dict[str, str], empresa: Empresa
) -> None:
    resposta = await cliente.get(
        "/api/v1/clientes/00000000-0000-0000-0000-000000000000",
        headers=_cabecalho(cabecalho_admin, empresa),
    )
    assert resposta.status_code == 404
    assert resposta.json()["erro"]["codigo"] == "nao_encontrado"


async def test_lookup_de_cliente_ignora_acento(
    cliente: AsyncClient, cabecalho_admin: dict[str, str], empresa: Empresa
) -> None:
    cabecalho = _cabecalho(cabecalho_admin, empresa)
    await cliente.post(
        "/api/v1/clientes",
        json={"codigo": "CLI001", "nome": "Cliente São Paulo", "tipo_pessoa": "juridica"},
        headers=cabecalho,
    )

    resposta = await cliente.get(
        "/api/v1/clientes/lookup", params={"q": "sao paulo"}, headers=cabecalho
    )
    assert resposta.status_code == 200
    itens = resposta.json()
    assert len(itens) == 1
    assert itens[0]["label"] == "Cliente São Paulo"


async def test_cliente_profissao_precisa_ser_do_dominio_certo(
    cliente: AsyncClient, cabecalho_admin: dict[str, str], empresa: Empresa
) -> None:
    """`profissao_id` aponta para `catalog_lookups.id` — a FK simples não garante o
    domínio. Prova o caso positivo antes do negativo."""
    cabecalho = _cabecalho(cabecalho_admin, empresa)

    profissao = await cliente.post(
        "/api/v1/apoio/profissao", json={"descricao": "Arquiteto"}, headers=cabecalho_admin
    )
    marca = await cliente.post(
        "/api/v1/apoio/marca", json={"descricao": "Lumini"}, headers=cabecalho_admin
    )

    valido = await cliente.post(
        "/api/v1/clientes",
        json={
            "codigo": "CLI001",
            "nome": "Fulano",
            "tipo_pessoa": "fisica",
            "profissao_id": profissao.json()["id"],
        },
        headers=cabecalho,
    )
    assert valido.status_code == 201, valido.text

    invalido = await cliente.post(
        "/api/v1/clientes",
        json={
            "codigo": "CLI002",
            "nome": "Beltrano",
            "tipo_pessoa": "fisica",
            "profissao_id": marca.json()["id"],
        },
        headers=cabecalho,
    )
    assert invalido.status_code == 422
    assert invalido.json()["erro"]["codigo"] == "dominio_invalido"


async def test_cliente_de_outra_empresa_nao_aparece_no_recorte(
    motor_runtime: AsyncEngine, cenario: Cenario
) -> None:
    """`cliente` está sob RLS como qualquer tabela por empresa. Mesmo molde de
    `test_filial_de_outra_empresa_nao_aparece_no_recorte`.

    `codigo` carrega `cenario.sufixo`, não um literal fixo: esta linha é gravada com
    `commit()` direto (fora do savepoint por-teste), então sobrevive à própria execução do
    teste — um literal fixo colidiria com a checagem de unicidade de outro teste que passe
    pela conexão de dono (sem RLS) mais tarde. Mesma razão do sufixo em `tests/cenario.py`.
    """
    codigo_abacaxi = f"CLI-A-{cenario.sufixo}"
    codigo_uva = f"CLI-U-{cenario.sufixo}"

    async with AsyncSession(motor_runtime, expire_on_commit=False) as sessao:
        await declarar_empresa(sessao, cenario.abacaxi)
        sessao.add(
            Cliente(
                tenant_id=cenario.abacaxi,
                codigo=codigo_abacaxi,
                nome="Da Abacaxi",
                tipo_pessoa="fisica",
            )
        )
        await sessao.commit()

    async with AsyncSession(motor_runtime, expire_on_commit=False) as sessao:
        await declarar_empresa(sessao, cenario.uva)
        sessao.add(
            Cliente(tenant_id=cenario.uva, codigo=codigo_uva, nome="Da Uva", tipo_pessoa="fisica")
        )
        await sessao.commit()

    async with AsyncSession(motor_runtime) as sessao:
        await declarar_empresa(sessao, cenario.uva)
        clientes = (await sessao.execute(select(Cliente))).scalars().all()

    assert [c.codigo for c in clientes] == [codigo_uva]


# --- Obra: subrecurso de cliente --------------------------------------------------


async def test_obra_vive_sob_cliente(
    cliente: AsyncClient, cabecalho_admin: dict[str, str], empresa: Empresa
) -> None:
    cabecalho = _cabecalho(cabecalho_admin, empresa)
    criado = await cliente.post(
        "/api/v1/clientes",
        json={"codigo": "CLI001", "nome": "Fulano", "tipo_pessoa": "fisica"},
        headers=cabecalho,
    )
    cliente_id = criado.json()["id"]

    obra = await cliente.post(
        f"/api/v1/clientes/{cliente_id}/obras",
        json={"nome": "Apto 302", "endereco_logradouro": "Rua Augusta"},
        headers=cabecalho,
    )
    assert obra.status_code == 201, obra.text
    assert obra.json()["cliente_id"] == cliente_id

    listagem = await cliente.get(f"/api/v1/clientes/{cliente_id}/obras", headers=cabecalho)
    assert listagem.json()["total"] == 1


async def test_obra_sob_cliente_inexistente_da_404(
    cliente: AsyncClient, cabecalho_admin: dict[str, str], empresa: Empresa
) -> None:
    cabecalho = _cabecalho(cabecalho_admin, empresa)
    bogus = "00000000-0000-0000-0000-000000000000"

    listagem = await cliente.get(f"/api/v1/clientes/{bogus}/obras", headers=cabecalho)
    assert listagem.status_code == 404

    criacao = await cliente.post(
        f"/api/v1/clientes/{bogus}/obras", json={"nome": "Obra fantasma"}, headers=cabecalho
    )
    assert criacao.status_code == 404


async def test_obra_de_outro_cliente_nao_aparece_no_recorte(
    cliente: AsyncClient, cabecalho_admin: dict[str, str], empresa: Empresa
) -> None:
    """`ObraService.obter` confere `cliente_id` — não basta o `id` da obra bater."""
    cabecalho = _cabecalho(cabecalho_admin, empresa)

    cliente_a = (
        await cliente.post(
            "/api/v1/clientes",
            json={"codigo": "CLI001", "nome": "Cliente A", "tipo_pessoa": "fisica"},
            headers=cabecalho,
        )
    ).json()["id"]
    cliente_b = (
        await cliente.post(
            "/api/v1/clientes",
            json={"codigo": "CLI002", "nome": "Cliente B", "tipo_pessoa": "fisica"},
            headers=cabecalho,
        )
    ).json()["id"]

    obra = (
        await cliente.post(
            f"/api/v1/clientes/{cliente_a}/obras", json={"nome": "Obra A"}, headers=cabecalho
        )
    ).json()

    cruzado = await cliente.get(
        f"/api/v1/clientes/{cliente_b}/obras/{obra['id']}", headers=cabecalho
    )
    assert cruzado.status_code == 404


# --- Fornecedor -------------------------------------------------------------------


async def test_crud_de_fornecedor(
    cliente: AsyncClient, cabecalho_admin: dict[str, str], empresa: Empresa
) -> None:
    cabecalho = _cabecalho(cabecalho_admin, empresa)
    criado = await cliente.post(
        "/api/v1/fornecedores",
        json={
            "codigo": "FOR001",
            "razao_social": "Lumini Distribuidora Ltda",
            "cnpj": "12345678000190",
        },
        headers=cabecalho,
    )
    assert criado.status_code == 201, criado.text
    assert criado.json()["razao_social"] == "Lumini Distribuidora Ltda"


async def test_fornecedor_de_outra_empresa_nao_aparece_no_recorte(
    motor_runtime: AsyncEngine, cenario: Cenario
) -> None:
    """`codigo` carrega `cenario.sufixo` pela mesma razão do teste de `Cliente` acima: esta
    linha sobrevive ao próprio teste (commit direto, fora do savepoint), e um literal fixo
    colidiria com a checagem de unicidade de outro teste que passe pela conexão de dono."""
    codigo_abacaxi = f"FOR-A-{cenario.sufixo}"
    codigo_uva = f"FOR-U-{cenario.sufixo}"

    async with AsyncSession(motor_runtime, expire_on_commit=False) as sessao:
        await declarar_empresa(sessao, cenario.abacaxi)
        sessao.add(
            Fornecedor(tenant_id=cenario.abacaxi, codigo=codigo_abacaxi, razao_social="Da Abacaxi")
        )
        await sessao.commit()

    async with AsyncSession(motor_runtime, expire_on_commit=False) as sessao:
        await declarar_empresa(sessao, cenario.uva)
        sessao.add(Fornecedor(tenant_id=cenario.uva, codigo=codigo_uva, razao_social="Da Uva"))
        await sessao.commit()

    async with AsyncSession(motor_runtime) as sessao:
        await declarar_empresa(sessao, cenario.uva)
        fornecedores = (await sessao.execute(select(Fornecedor))).scalars().all()

    assert [f.codigo for f in fornecedores] == [codigo_uva]


# --- Colaborador ------------------------------------------------------------------


async def test_colaborador_liga_identidade_global_a_dados_por_empresa(
    cliente: AsyncClient,
    cabecalho_admin: dict[str, str],
    empresa: Empresa,
    sessao: AsyncSession,
) -> None:
    outro = Usuario(
        login="vendedor",
        nome="Vendedor da Loja",
        email="vendedor@vertz.teste",
        senha_hash=gerar_hash_senha("senha-de-teste-123"),
    )
    sessao.add(outro)
    await sessao.flush()
    sessao.add(VinculoEmpresa(tenant_id=empresa.id, employee_id=outro.id))
    await sessao.flush()

    cabecalho = _cabecalho(cabecalho_admin, empresa)
    setor = await cliente.post(
        "/api/v1/apoio/setor", json={"descricao": "Vendas"}, headers=cabecalho_admin
    )

    criado = await cliente.post(
        "/api/v1/colaboradores",
        json={"employee_id": str(outro.id), "setor_id": setor.json()["id"]},
        headers=cabecalho,
    )
    assert criado.status_code == 201, criado.text
    assert criado.json()["employee_id"] == str(outro.id)

    repetido = await cliente.post(
        "/api/v1/colaboradores",
        json={"employee_id": str(outro.id)},
        headers=cabecalho,
    )
    assert repetido.status_code == 409


async def test_colaborador_cargo_precisa_ser_do_dominio_certo(
    cliente: AsyncClient,
    cabecalho_admin: dict[str, str],
    empresa: Empresa,
    sessao: AsyncSession,
) -> None:
    outro = Usuario(
        login="tecnico",
        nome="Técnico",
        email="tecnico@vertz.teste",
        senha_hash=gerar_hash_senha("senha-de-teste-123"),
    )
    sessao.add(outro)
    await sessao.flush()
    sessao.add(VinculoEmpresa(tenant_id=empresa.id, employee_id=outro.id))
    await sessao.flush()

    cabecalho = _cabecalho(cabecalho_admin, empresa)
    marca = await cliente.post(
        "/api/v1/apoio/marca", json={"descricao": "Lumini"}, headers=cabecalho_admin
    )

    resposta = await cliente.post(
        "/api/v1/colaboradores",
        json={"employee_id": str(outro.id), "cargo_id": marca.json()["id"]},
        headers=cabecalho,
    )
    assert resposta.status_code == 422
    assert resposta.json()["erro"]["codigo"] == "dominio_invalido"


# --- Transportadora e profissional externo: CRUD básico ---------------------------


async def test_crud_de_transportadora(
    cliente: AsyncClient, cabecalho_admin: dict[str, str], empresa: Empresa
) -> None:
    cabecalho = _cabecalho(cabecalho_admin, empresa)
    criado = await cliente.post(
        "/api/v1/transportadoras",
        json={"codigo": "TRA001", "nome": "Rápido Entrega", "antt": "123456"},
        headers=cabecalho,
    )
    assert criado.status_code == 201, criado.text
    assert criado.json()["antt"] == "123456"


async def test_crud_de_profissional_externo(
    cliente: AsyncClient, cabecalho_admin: dict[str, str], empresa: Empresa
) -> None:
    cabecalho = _cabecalho(cabecalho_admin, empresa)
    criado = await cliente.post(
        "/api/v1/profissionais-externos",
        json={
            "codigo": "PROF001",
            "nome": "Arquiteta Ana",
            "tipo_pessoa": "fisica",
            "crea_cau": "CAU12345",
        },
        headers=cabecalho,
    )
    assert criado.status_code == 201, criado.text
    assert criado.json()["crea_cau"] == "CAU12345"
