"""Quem pode pedir, e por qual empresa.

Cobre a lacuna que a revisão do PR #1 encontrou: o RLS estava impecável e o recorte inteiro
era escolhido pelo cabeçalho `X-Empresa-Id`, que vinha do cliente e não era conferido
contra nada. O encadeamento era *RLS confia no GUC → GUC confia no cabeçalho → cabeçalho
vem do cliente*. E as quatro rotas do módulo não pediam credencial nenhuma.

A distinção que estes testes fixam:

* o **RLS** entrega imunidade a `WHERE` esquecido no serviço — é o que
  `test_rls_isolamento` prova, e continua valendo;
* a **borda HTTP** entrega imunidade a chamador malicioso — é o que este arquivo prova.

São defesas contra atacantes diferentes, e uma não substitui a outra.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.modules.bakeoff.models import Colaborador, Empresa
from tests.bakeoff import Cenario

# As quatro rotas do módulo. Antes desta correção eram as únicas 4 operações sem
# `security` num contrato de 55 — fora as três que são públicas por natureza.
ROTAS = [
    ("GET", "/api/v1/produtos"),
    ("POST", "/api/v1/produtos"),
    ("GET", "/api/v1/bakeoff/empresas"),
    ("GET", "/api/v1/bakeoff/empresas/papeis"),
]

PUBLICAS_POR_NATUREZA = {
    # Não dá para autenticar antes de autenticar.
    ("post", "/api/v1/auth/login"),
    ("post", "/api/v1/auth/refresh"),
    # A sonda precisa responder para o orquestrador.
    ("get", "/saude"),
}


# --- autenticação -------------------------------------------------------------


@pytest.mark.parametrize(("metodo", "rota"), ROTAS)
async def test_rota_sem_token_responde_401(
    cliente_bakeoff: AsyncClient, cenario: Cenario, metodo: str, rota: str
) -> None:
    """`POST /produtos` gravava no banco sem token; `GET /bakeoff/empresas` listava o CNPJ
    de todas as empresas do grupo."""
    resposta = await cliente_bakeoff.request(
        metodo,
        rota,
        headers={"X-Empresa-Id": str(cenario.abacaxi)},
        json={"codigo": f"SEM-TOKEN-{cenario.sufixo}", "descricao": "não deveria entrar"}
        if metodo == "POST"
        else None,
    )

    assert resposta.status_code == 401, resposta.text
    assert resposta.json()["erro"]["codigo"] == "nao_autenticado"


async def test_contrato_nao_tem_rota_aberta_alem_das_publicas(
    cliente_bakeoff: AsyncClient,
) -> None:
    """Varre o contrato em vez de conferir uma lista escrita à mão.

    Uma lista fixa protegeria as rotas de que alguém lembrou. Isto reprova a rota nova que
    nascer sem autenticação — que é exatamente como a lacuna original apareceu.
    """
    contrato = (await cliente_bakeoff.get("/openapi.json")).json()

    abertas = {
        (verbo, rota)
        for rota, operacoes in contrato["paths"].items()
        for verbo, operacao in operacoes.items()
        if verbo in {"get", "post", "put", "delete", "patch"} and "security" not in operacao
    }

    assert abertas == PUBLICAS_POR_NATUREZA, (
        f"operações sem autenticação além das esperadas: {abertas - PUBLICAS_POR_NATUREZA}"
    )


# --- vínculo com a empresa ----------------------------------------------------


async def test_empresa_com_vinculo_responde_200(so_abacaxi: AsyncClient, cenario: Cenario) -> None:
    """O caso positivo, e vem primeiro: sem ele, o 403 abaixo passaria mesmo se a
    dependência estivesse negando tudo."""
    resposta = await so_abacaxi.get(
        "/api/v1/produtos", headers={"X-Empresa-Id": str(cenario.abacaxi)}
    )

    assert resposta.status_code == 200, resposta.text
    assert cenario.codigo_abacaxi in {i["codigo"] for i in resposta.json()["itens"]}


async def test_empresa_sem_vinculo_responde_403(so_abacaxi: AsyncClient, cenario: Cenario) -> None:
    """Autenticado, mas pedindo a empresa do vizinho.

    403 e não lista vazia: o RLS sozinho devolveria vazio, o que é seguro mas
    indistinguível de "não há produtos". A borda diz o que de fato aconteceu.
    """
    resposta = await so_abacaxi.get("/api/v1/produtos", headers={"X-Empresa-Id": str(cenario.uva)})

    assert resposta.status_code == 403, resposta.text
    assert resposta.json()["erro"]["codigo"] == "sem_vinculo_com_empresa"


async def test_escrita_em_empresa_sem_vinculo_nao_grava(
    so_abacaxi: AsyncClient, autenticado: AsyncClient, cenario: Cenario
) -> None:
    """A leitura era o sintoma visível; a escrita era o dano real."""
    codigo = f"INVASAO-{cenario.sufixo}"

    resposta = await so_abacaxi.post(
        "/api/v1/produtos",
        json={"codigo": codigo, "descricao": "gravado em empresa alheia"},
        headers={"X-Empresa-Id": str(cenario.uva)},
    )
    assert resposta.status_code == 403, resposta.text

    # E não gravou: o 403 poderia, em tese, ter vindo depois do INSERT.
    listagem = await autenticado.get(
        "/api/v1/produtos",
        params={"busca_codigo": codigo, "tamanho": 200},
        headers={"X-Empresa-Id": str(cenario.uva)},
    )
    assert listagem.json()["total"] == 0


async def test_empresa_inexistente_responde_403(autenticado: AsyncClient) -> None:
    """UUID chutado não vira erro de banco nem lista vazia: não há vínculo, logo 403."""
    resposta = await autenticado.get(
        "/api/v1/produtos", headers={"X-Empresa-Id": str(uuid.uuid4())}
    )

    assert resposta.status_code == 403
    assert resposta.json()["erro"]["codigo"] == "sem_vinculo_com_empresa"


async def test_usuario_sem_email_nao_alcanca_nenhuma_empresa(
    sem_email: AsyncClient, cenario: Cenario
) -> None:
    """A ponte `usuario` → `employees` é o e-mail, e `Usuario.email` é nulável na S0.

    Falha fechado de propósito: tratar a ausência como "não dá para checar, então deixa
    passar" seria o mesmo furo com outra cara.
    """
    resposta = await sem_email.get(
        "/api/v1/produtos", headers={"X-Empresa-Id": str(cenario.abacaxi)}
    )

    assert resposta.status_code == 403


# --- desativação corta o acesso -----------------------------------------------


async def test_colaborador_desativado_perde_o_acesso(
    autenticado: AsyncClient, motor_runtime: AsyncEngine, cenario: Cenario, email_do_token: str
) -> None:
    """Desativar é *o* mecanismo de offboarding do VITRA — precisa cortar o acesso.

    Positivo primeiro: com a pessoa ativa, a listagem responde. Sem essa metade, o 403
    abaixo passaria mesmo se a rota estivesse quebrada por outro motivo.
    """
    cabecalho = {"X-Empresa-Id": str(cenario.abacaxi)}
    assert (await autenticado.get("/api/v1/produtos", headers=cabecalho)).status_code == 200

    await _desativar(motor_runtime, Colaborador, Colaborador.email == email_do_token)

    resposta = await autenticado.get("/api/v1/produtos", headers=cabecalho)
    assert resposta.status_code == 403, resposta.text
    assert resposta.json()["erro"]["codigo"] == "sem_vinculo_com_empresa"


async def test_empresa_desativada_deixa_de_ser_operavel(
    autenticado: AsyncClient, motor_runtime: AsyncEngine, cenario: Cenario
) -> None:
    """Empresa desativada e ainda operável é o mesmo problema um nível acima.

    E o recorte continua valendo: desativar a ABACAXI não pode derrubar a UVA.
    """
    abacaxi = {"X-Empresa-Id": str(cenario.abacaxi)}
    uva = {"X-Empresa-Id": str(cenario.uva)}
    assert (await autenticado.get("/api/v1/produtos", headers=abacaxi)).status_code == 200

    await _desativar(motor_runtime, Empresa, Empresa.id == cenario.abacaxi)

    assert (await autenticado.get("/api/v1/produtos", headers=abacaxi)).status_code == 403
    assert (await autenticado.get("/api/v1/produtos", headers=uva)).status_code == 200


async def _desativar(motor: AsyncEngine, modelo: type, condicao: Any) -> None:
    """`tenants` e `employees` são globais — dá para atualizar sem declarar empresa."""
    async with AsyncSession(motor) as sessao:
        await sessao.execute(update(modelo).where(condicao).values(active=False))
        await sessao.commit()


async def test_quem_tem_vinculo_com_as_duas_alterna_pelo_cabecalho(
    autenticado: AsyncClient, cenario: Cenario
) -> None:
    """É o caso da ANA SILVA, e é o que justifica o cabeçalho existir: mesma identidade,
    duas empresas, uma por vez."""
    for empresa, esperado, proibido in (
        (cenario.abacaxi, cenario.codigo_abacaxi, cenario.codigo_uva),
        (cenario.uva, cenario.codigo_uva, cenario.codigo_abacaxi),
    ):
        resposta = await autenticado.get(
            "/api/v1/produtos",
            params={"tamanho": 200},
            headers={"X-Empresa-Id": str(empresa)},
        )
        assert resposta.status_code == 200, resposta.text
        codigos = {i["codigo"] for i in resposta.json()["itens"]}
        assert esperado in codigos
        assert proibido not in codigos
