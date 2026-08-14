from __future__ import annotations

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core.security import gerar_hash_senha
from app.core.tenancy import declarar_empresa
from app.modules.auth.models import Usuario, VinculoEmpresa
from app.modules.empresa.models import Empresa
from app.modules.pessoas.models import (
    Colaborador,
    Obra,
    Parceiro,
    Transportadora,
)
from tests.cenario import Cenario, criar_usuario_vinculado


def _cabecalho(cabecalho_admin: dict[str, str], empresa: Empresa) -> dict[str, str]:
    return {**cabecalho_admin, "X-Empresa-Id": str(empresa.id)}


# --- Parceiro --------------------------------------------------------------------


async def test_crud_de_cliente(
    cliente: AsyncClient, cabecalho_admin: dict[str, str], empresa: Empresa
) -> None:
    cabecalho = _cabecalho(cabecalho_admin, empresa)

    criado = await cliente.post(
        "/api/v1/parceiros",
        json={
            "codigo": "CLI001",
            "razao_social": "Maria Andrade",
            "tipo_pessoa": "fisica",
            "e_cliente": True,
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
        f"/api/v1/parceiros/{cliente_id}",
        json={"razao_social": "Maria Andrade Silva"},
        headers=cabecalho,
    )
    assert atualizado.status_code == 200
    assert atualizado.json()["razao_social"] == "Maria Andrade Silva"
    # PUT parcial não apaga o que não veio no corpo.
    assert atualizado.json()["cpf_cnpj"] == "12345678900"

    desativado = await cliente.delete(f"/api/v1/parceiros/{cliente_id}", headers=cabecalho)
    assert desativado.status_code == 200
    assert desativado.json()["ativo"] is False


async def test_codigo_de_cliente_e_unico_por_empresa(
    cliente: AsyncClient, cabecalho_admin: dict[str, str], empresa: Empresa
) -> None:
    cabecalho = _cabecalho(cabecalho_admin, empresa)
    dados = {
        "codigo": "CLI001",
        "razao_social": "Fulano",
        "tipo_pessoa": "fisica",
        "e_cliente": True,
    }
    await cliente.post("/api/v1/parceiros", json=dados, headers=cabecalho)
    repetido = await cliente.post("/api/v1/parceiros", json=dados, headers=cabecalho)
    assert repetido.status_code == 409
    assert repetido.json()["erro"]["campos"] == {"codigo": "já utilizado"}


async def test_cliente_inexistente_da_404(
    cliente: AsyncClient, cabecalho_admin: dict[str, str], empresa: Empresa
) -> None:
    resposta = await cliente.get(
        "/api/v1/parceiros/00000000-0000-0000-0000-000000000000",
        headers=_cabecalho(cabecalho_admin, empresa),
    )
    assert resposta.status_code == 404
    assert resposta.json()["erro"]["codigo"] == "nao_encontrado"


async def test_lookup_de_cliente_ignora_acento(
    cliente: AsyncClient, cabecalho_admin: dict[str, str], empresa: Empresa
) -> None:
    cabecalho = _cabecalho(cabecalho_admin, empresa)
    await cliente.post(
        "/api/v1/parceiros",
        json={
            "codigo": "CLI001",
            "razao_social": "Cliente São Paulo",
            "tipo_pessoa": "juridica",
            "e_cliente": True,
        },
        headers=cabecalho,
    )

    resposta = await cliente.get(
        "/api/v1/parceiros/lookup", params={"q": "sao paulo"}, headers=cabecalho
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
        "/api/v1/parceiros",
        json={
            "codigo": "CLI001",
            "razao_social": "Fulano",
            "tipo_pessoa": "fisica",
            "e_cliente": True,
            "profissao_id": profissao.json()["id"],
        },
        headers=cabecalho,
    )
    assert valido.status_code == 201, valido.text

    invalido = await cliente.post(
        "/api/v1/parceiros",
        json={
            "codigo": "CLI002",
            "razao_social": "Beltrano",
            "e_cliente": True,
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
            Parceiro(
                tenant_id=cenario.abacaxi,
                codigo=codigo_abacaxi,
                razao_social="Da Abacaxi",
                tipo_pessoa="fisica",
                e_cliente=True,
            )
        )
        await sessao.commit()

    async with AsyncSession(motor_runtime, expire_on_commit=False) as sessao:
        await declarar_empresa(sessao, cenario.uva)
        sessao.add(
            Parceiro(
                tenant_id=cenario.uva,
                codigo=codigo_uva,
                razao_social="Da Uva",
                tipo_pessoa="fisica",
                e_cliente=True,
            )
        )
        await sessao.commit()

    async with AsyncSession(motor_runtime) as sessao:
        await declarar_empresa(sessao, cenario.uva)
        clientes = (await sessao.execute(select(Parceiro))).scalars().all()

    assert [c.codigo for c in clientes] == [codigo_uva]


# --- Obra: subrecurso de parceiro --------------------------------------------------


async def test_obra_vive_sob_cliente(
    cliente: AsyncClient, cabecalho_admin: dict[str, str], empresa: Empresa
) -> None:
    cabecalho = _cabecalho(cabecalho_admin, empresa)
    criado = await cliente.post(
        "/api/v1/parceiros",
        json={
            "codigo": "CLI001",
            "razao_social": "Fulano",
            "tipo_pessoa": "fisica",
            "e_cliente": True,
        },
        headers=cabecalho,
    )
    cliente_id = criado.json()["id"]

    obra = await cliente.post(
        f"/api/v1/parceiros/{cliente_id}/obras",
        json={"nome": "Apto 302", "endereco_logradouro": "Rua Augusta"},
        headers=cabecalho,
    )
    assert obra.status_code == 201, obra.text
    assert obra.json()["parceiro_id"] == cliente_id

    listagem = await cliente.get(f"/api/v1/parceiros/{cliente_id}/obras", headers=cabecalho)
    assert listagem.json()["total"] == 1


async def test_obra_sob_cliente_inexistente_da_404(
    cliente: AsyncClient, cabecalho_admin: dict[str, str], empresa: Empresa
) -> None:
    cabecalho = _cabecalho(cabecalho_admin, empresa)
    bogus = "00000000-0000-0000-0000-000000000000"

    listagem = await cliente.get(f"/api/v1/parceiros/{bogus}/obras", headers=cabecalho)
    assert listagem.status_code == 404

    criacao = await cliente.post(
        f"/api/v1/parceiros/{bogus}/obras", json={"nome": "Obra fantasma"}, headers=cabecalho
    )
    assert criacao.status_code == 404


async def test_obra_de_outro_cliente_nao_aparece_no_recorte(
    cliente: AsyncClient, cabecalho_admin: dict[str, str], empresa: Empresa
) -> None:
    """`ObraService.obter` confere `cliente_id` — não basta o `id` da obra bater."""
    cabecalho = _cabecalho(cabecalho_admin, empresa)

    cliente_a = (
        await cliente.post(
            "/api/v1/parceiros",
            json={
                "codigo": "CLI001",
                "razao_social": "Cliente A",
                "tipo_pessoa": "fisica",
                "e_cliente": True,
            },
            headers=cabecalho,
        )
    ).json()["id"]
    cliente_b = (
        await cliente.post(
            "/api/v1/parceiros",
            json={
                "codigo": "CLI002",
                "razao_social": "Cliente B",
                "tipo_pessoa": "fisica",
                "e_cliente": True,
            },
            headers=cabecalho,
        )
    ).json()["id"]

    obra = (
        await cliente.post(
            f"/api/v1/parceiros/{cliente_a}/obras", json={"nome": "Obra A"}, headers=cabecalho
        )
    ).json()

    cruzado = await cliente.get(
        f"/api/v1/parceiros/{cliente_b}/obras/{obra['id']}", headers=cabecalho
    )
    assert cruzado.status_code == 404


async def test_obra_de_outra_empresa_nao_aparece_no_recorte(
    motor_runtime: AsyncEngine, cenario: Cenario
) -> None:
    """`obra` está sob RLS — não é só o `cliente_id` que a `ObraService` confere na
    aplicação; o banco recorta por `tenant_id` mesmo antes disso."""
    codigo_abacaxi = f"CLI-OBRA-A-{cenario.sufixo}"
    codigo_uva = f"CLI-OBRA-U-{cenario.sufixo}"

    async with AsyncSession(motor_runtime, expire_on_commit=False) as sessao:
        await declarar_empresa(sessao, cenario.abacaxi)
        cliente_abacaxi = Parceiro(
            tenant_id=cenario.abacaxi,
            codigo=codigo_abacaxi,
            razao_social="Da Abacaxi",
            tipo_pessoa="fisica",
            e_cliente=True,
        )
        sessao.add(cliente_abacaxi)
        await sessao.flush()
        sessao.add(Obra(tenant_id=cenario.abacaxi, parceiro_id=cliente_abacaxi.id, nome="Obra A"))
        await sessao.commit()

    async with AsyncSession(motor_runtime, expire_on_commit=False) as sessao:
        await declarar_empresa(sessao, cenario.uva)
        cliente_uva = Parceiro(
            tenant_id=cenario.uva,
            codigo=codigo_uva,
            razao_social="Da Uva",
            tipo_pessoa="fisica",
            e_cliente=True,
        )
        sessao.add(cliente_uva)
        await sessao.flush()
        sessao.add(Obra(tenant_id=cenario.uva, parceiro_id=cliente_uva.id, nome="Obra U"))
        await sessao.commit()

    async with AsyncSession(motor_runtime) as sessao:
        await declarar_empresa(sessao, cenario.uva)
        obras = (await sessao.execute(select(Obra))).scalars().all()

    assert [o.nome for o in obras] == ["Obra U"]


# --- Parceiro: papel de fornecedor -----------------------------------------------


async def test_crud_de_fornecedor(
    cliente: AsyncClient, cabecalho_admin: dict[str, str], empresa: Empresa
) -> None:
    cabecalho = _cabecalho(cabecalho_admin, empresa)
    criado = await cliente.post(
        "/api/v1/parceiros",
        json={
            "codigo": "FOR001",
            "razao_social": "Lumini Distribuidora Ltda",
            "tipo_pessoa": "juridica",
            "e_fornecedor": True,
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
            Parceiro(
                tenant_id=cenario.abacaxi,
                codigo=codigo_abacaxi,
                razao_social="Da Abacaxi",
                tipo_pessoa="juridica",
                e_fornecedor=True,
            )
        )
        await sessao.commit()

    async with AsyncSession(motor_runtime, expire_on_commit=False) as sessao:
        await declarar_empresa(sessao, cenario.uva)
        sessao.add(
            Parceiro(
                tenant_id=cenario.uva,
                codigo=codigo_uva,
                razao_social="Da Uva",
                tipo_pessoa="juridica",
                e_fornecedor=True,
            )
        )
        await sessao.commit()

    async with AsyncSession(motor_runtime) as sessao:
        await declarar_empresa(sessao, cenario.uva)
        fornecedores = (await sessao.execute(select(Parceiro))).scalars().all()

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


async def test_colaborador_recusa_pessoa_de_outra_empresa(
    cliente: AsyncClient,
    cabecalho_admin: dict[str, str],
    empresa: Empresa,
    sessao: AsyncSession,
) -> None:
    """`employee_id` é FK simples para `employees` — tabela **global**, sem RLS. Sem
    checar vínculo explicitamente, o `POST` aceitaria (e o lookup vazaria o nome de)
    qualquer pessoa da instalação, vinculada ou não com a empresa ativa."""
    rival = Empresa(codigo="RIVAL", razao_social="Rival Iluminação Ltda")
    sessao.add(rival)
    await sessao.flush()

    pessoa_da_rival = Usuario(
        login="pessoa-rival",
        nome="Pessoa Da Rival",
        email="rival@outraempresa.teste",
        senha_hash=gerar_hash_senha("senha-de-teste-123"),
    )
    sessao.add(pessoa_da_rival)
    await sessao.flush()
    sessao.add(VinculoEmpresa(tenant_id=rival.id, employee_id=pessoa_da_rival.id))
    await sessao.flush()

    cabecalho = _cabecalho(cabecalho_admin, empresa)
    resposta = await cliente.post(
        "/api/v1/colaboradores",
        json={"employee_id": str(pessoa_da_rival.id)},
        headers=cabecalho,
    )
    assert resposta.status_code == 422, resposta.text
    assert resposta.json()["erro"]["codigo"] == "colaborador_sem_vinculo"

    # Nada foi criado — o lookup não vaza o nome dela por busca.
    lookup = await cliente.get(
        "/api/v1/colaboradores/lookup", params={"q": "rival"}, headers=cabecalho
    )
    assert lookup.json() == []


async def test_colaborador_lookup_e_listagem_filtram_por_nome(
    cliente: AsyncClient,
    cabecalho_admin: dict[str, str],
    empresa: Empresa,
    sessao: AsyncSession,
) -> None:
    """O nome mora em `employees` (`Usuario.nome`), não em `Colaborador` — sem o `join`
    explícito em `ColaboradorService`, `?q=`/`?busca=` eram aceitos e silenciosamente
    ignorados (`spec.campos_busca` vazio)."""
    outro = Usuario(
        login="vendedora-sp",
        nome="Vendedora São Paulo",
        email="vendedora-sp@vertz.teste",
        senha_hash=gerar_hash_senha("senha-de-teste-123"),
    )
    sessao.add(outro)
    await sessao.flush()
    sessao.add(VinculoEmpresa(tenant_id=empresa.id, employee_id=outro.id))
    await sessao.flush()

    cabecalho = _cabecalho(cabecalho_admin, empresa)
    await cliente.post(
        "/api/v1/colaboradores", json={"employee_id": str(outro.id)}, headers=cabecalho
    )

    # Positivo antes do negativo, e sem acento — "sao paulo" acha "São Paulo".
    lookup_acha = await cliente.get(
        "/api/v1/colaboradores/lookup", params={"q": "sao paulo"}, headers=cabecalho
    )
    assert len(lookup_acha.json()) == 1
    assert lookup_acha.json()[0]["label"] == "Vendedora São Paulo"

    lookup_vazio = await cliente.get(
        "/api/v1/colaboradores/lookup", params={"q": "zzz-nao-existe"}, headers=cabecalho
    )
    assert lookup_vazio.json() == []

    listagem_acha = await cliente.get(
        "/api/v1/colaboradores", params={"busca": "vendedora"}, headers=cabecalho
    )
    assert listagem_acha.json()["total"] == 1

    listagem_vazia = await cliente.get(
        "/api/v1/colaboradores", params={"busca": "zzz-nao-existe"}, headers=cabecalho
    )
    assert listagem_vazia.json()["total"] == 0


async def test_colaborador_de_outra_empresa_nao_aparece_no_recorte(
    motor_runtime: AsyncEngine, cenario: Cenario
) -> None:
    pessoa_abacaxi = await criar_usuario_vinculado(
        motor_runtime,
        cenario,
        empresas=(cenario.abacaxi,),
        sufixo_login="-colab-aba",
        com_permissao_produtos=False,
    )
    pessoa_uva = await criar_usuario_vinculado(
        motor_runtime,
        cenario,
        empresas=(cenario.uva,),
        sufixo_login="-colab-uva",
        com_permissao_produtos=False,
    )

    async with AsyncSession(motor_runtime, expire_on_commit=False) as sessao:
        await declarar_empresa(sessao, cenario.abacaxi)
        sessao.add(Colaborador(tenant_id=cenario.abacaxi, employee_id=pessoa_abacaxi.id))
        await sessao.commit()

    async with AsyncSession(motor_runtime, expire_on_commit=False) as sessao:
        await declarar_empresa(sessao, cenario.uva)
        sessao.add(Colaborador(tenant_id=cenario.uva, employee_id=pessoa_uva.id))
        await sessao.commit()

    async with AsyncSession(motor_runtime) as sessao:
        await declarar_empresa(sessao, cenario.uva)
        colaboradores = (await sessao.execute(select(Colaborador))).scalars().all()

    assert [c.employee_id for c in colaboradores] == [pessoa_uva.id]


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


# --- Transportadora e parceiro profissional: CRUD básico ---------------------------


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


async def test_transportadora_de_outra_empresa_nao_aparece_no_recorte(
    motor_runtime: AsyncEngine, cenario: Cenario
) -> None:
    codigo_abacaxi = f"TRA-A-{cenario.sufixo}"
    codigo_uva = f"TRA-U-{cenario.sufixo}"

    async with AsyncSession(motor_runtime, expire_on_commit=False) as sessao:
        await declarar_empresa(sessao, cenario.abacaxi)
        sessao.add(
            Transportadora(tenant_id=cenario.abacaxi, codigo=codigo_abacaxi, nome="Da Abacaxi")
        )
        await sessao.commit()

    async with AsyncSession(motor_runtime, expire_on_commit=False) as sessao:
        await declarar_empresa(sessao, cenario.uva)
        sessao.add(Transportadora(tenant_id=cenario.uva, codigo=codigo_uva, nome="Da Uva"))
        await sessao.commit()

    async with AsyncSession(motor_runtime) as sessao:
        await declarar_empresa(sessao, cenario.uva)
        transportadoras = (await sessao.execute(select(Transportadora))).scalars().all()

    assert [t.codigo for t in transportadoras] == [codigo_uva]


async def test_crud_de_profissional_externo(
    cliente: AsyncClient, cabecalho_admin: dict[str, str], empresa: Empresa
) -> None:
    cabecalho = _cabecalho(cabecalho_admin, empresa)
    criado = await cliente.post(
        "/api/v1/parceiros",
        json={
            "codigo": "PROF001",
            "razao_social": "Arquiteta Ana",
            "e_profissional": True,
            "tipo_pessoa": "fisica",
            "registro_profissional": "CAU12345",
        },
        headers=cabecalho,
    )
    assert criado.status_code == 201, criado.text
    assert criado.json()["registro_profissional"] == "CAU12345"


async def test_profissional_externo_de_outra_empresa_nao_aparece_no_recorte(
    motor_runtime: AsyncEngine, cenario: Cenario
) -> None:
    codigo_abacaxi = f"PROF-A-{cenario.sufixo}"
    codigo_uva = f"PROF-U-{cenario.sufixo}"

    async with AsyncSession(motor_runtime, expire_on_commit=False) as sessao:
        await declarar_empresa(sessao, cenario.abacaxi)
        sessao.add(
            Parceiro(
                tenant_id=cenario.abacaxi,
                codigo=codigo_abacaxi,
                razao_social="Da Abacaxi",
                tipo_pessoa="fisica",
                e_cliente=True,
            )
        )
        await sessao.commit()

    async with AsyncSession(motor_runtime, expire_on_commit=False) as sessao:
        await declarar_empresa(sessao, cenario.uva)
        sessao.add(
            Parceiro(
                tenant_id=cenario.uva,
                codigo=codigo_uva,
                razao_social="Da Uva",
                tipo_pessoa="fisica",
                e_cliente=True,
            )
        )
        await sessao.commit()

    async with AsyncSession(motor_runtime) as sessao:
        await declarar_empresa(sessao, cenario.uva)
        profissionais = (await sessao.execute(select(Parceiro))).scalars().all()

    assert [p.codigo for p in profissionais] == [codigo_uva]
