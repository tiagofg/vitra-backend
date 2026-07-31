"""Seed local das 7 tabelas do bake-off.

    python scripts/seed_bakeoff.py

**Só para o Postgres local.** O banco compartilhado no Neon já vem populado pelo Henrique,
e escrever lá suja o dado dos outros dois times do bake-off. O script recusa rodar se a URL
apontar para fora de `localhost` — é barato e evita o acidente que custa caro.

Reproduz o enunciado: ABACAXI e UVA com os `tenant_id` fixos, 200 produtos por empresa, 3
variantes por produto, os 19 `kind` de apoio e a ANA SILVA com papel diferente em cada
empresa. Os casos de borda entram de propósito — preço `0`, estoque `0` e `active = false`
são exatamente o que a listagem tem que aguentar.

Idempotente: rodar duas vezes não duplica nada.
"""

from __future__ import annotations

import asyncio
import random
import sys
import uuid
from decimal import Decimal
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import config  # noqa: E402
from app.core.db import SessionLocal, engine  # noqa: E402
from app.core.tenancy import declarar_empresa  # noqa: E402
from app.modules.bakeoff.models import (  # noqa: E402
    Colaborador,
    ColaboradorEmpresa,
    Empresa,
    PapelEmpresa,
    Produto,
    ProdutoEmpresa,
    ValorApoio,
    Variante,
)

ABACAXI = uuid.UUID("11111111-1111-1111-1111-111111111111")
UVA = uuid.UUID("22222222-2222-2222-2222-222222222222")

EMPRESAS = [
    (ABACAXI, "ABACAXI ILUMINACAO LTDA", "11111111000191"),
    (UVA, "UVA DECORACOES LTDA", "22222222000172"),
]

# Os 19 `[combo +...]` das telas do legado. `kind` aqui é o `dominio` do plano.
KINDS = [
    "setor", "grau_instrucao", "profissao", "raca_cor", "estado_civil", "nacionalidade",
    "cargo", "vinculo", "categoria", "tipo_produto", "tipo_peca", "tipo_linha",
    "classificacao", "designer_modelo", "fabrica", "marca", "material", "unidade",
    "acabamento", "tamanho",
]  # fmt: skip

FAMILIAS = ["Pendente", "Plafon", "Arandela", "Spot", "Trilho", "Luminária", "Balizador"]
MODELOS = ["Órion", "Aurora", "Vega", "Íris", "Ácis", "Lyra", "Atlas", "Cassiopeia"]
ACABAMENTOS = ["cobre escovado", "preto fosco", "dourado"]
TAMANHOS = ["P", "M", "G"]

PRODUTOS_POR_EMPRESA = 200

# Semente fixa: o dado de teste tem que ser o mesmo em duas máquinas, senão "funciona aqui"
# vira uma afirmação sem valor. O acaso é só para variedade, não para imprevisibilidade.
SORTEIO = random.Random(20260730)


async def main() -> None:
    _recusar_banco_remoto()

    async with SessionLocal() as sessao:
        await _empresas(sessao)
        await _apoio(sessao)
        await sessao.commit()

    for empresa_id, nome, _ in EMPRESAS:
        async with SessionLocal() as sessao:
            await declarar_empresa(sessao, empresa_id)
            criados = await _catalogo(sessao, empresa_id)
            await sessao.commit()
        print(f"  {nome}: {criados} produtos")

    async with SessionLocal() as sessao:
        await _ana_silva(sessao)

    await engine.dispose()
    print("Seed do bake-off concluído.")


HOSTS_LOCAIS = frozenset({"localhost", "127.0.0.1", "::1", "db"})


def _recusar_banco_remoto() -> None:
    """A regra nº 1 do banco compartilhado: não escrever nele por automação.

    Compara o **host**, não a URL inteira. Um `in` sobre a string crua examinaria também
    usuário e senha, e uma senha que por acaso contivesse `@db` liberaria a execução contra
    o Neon. É a única coisa entre um comando distraído e o banco de outros dois times, e
    esse tipo de trava não pode ser mais frouxa que o risco que ela cobre.
    """
    host = make_url(config.database_url).host or ""
    if host not in HOSTS_LOCAIS:
        raise SystemExit(
            f"Recusando rodar contra o host {host!r}.\n"
            "Este seed é só para o Postgres local. O banco do bake-off no Neon é "
            "compartilhado com os outros dois times e tem estrutura e dados fixos."
        )


async def _empresas(sessao: AsyncSession) -> None:
    existentes = set((await sessao.execute(select(Empresa.id))).scalars())
    for empresa_id, nome, cnpj in EMPRESAS:
        if empresa_id not in existentes:
            sessao.add(Empresa(id=empresa_id, name=nome, cnpj=cnpj, active=True))
    await sessao.flush()


async def _apoio(sessao: AsyncSession) -> None:
    """Alguns valores por `kind`, o bastante para os combos não virem vazios."""
    existentes = {
        (kind, nome)
        for kind, nome in (await sessao.execute(select(ValorApoio.kind, ValorApoio.name))).all()
    }
    for kind in KINDS:
        for i in range(1, 4):
            nome = f"{kind.replace('_', ' ').capitalize()} {i}"
            if (kind, nome) not in existentes:
                sessao.add(ValorApoio(kind=kind, name=nome, active=True))
    await sessao.flush()


async def _catalogo(sessao: AsyncSession, empresa_id: uuid.UUID) -> int:
    """200 produtos, 3 variantes cada, preço e estoque por empresa.

    Sem `WHERE tenant_id` em lugar nenhum: a empresa está declarada na transação, e a
    política de INSERT recusaria qualquer linha de outra empresa mesmo se tentasse.
    """
    ja_tem = (await sessao.execute(select(func.count()).select_from(Produto))).scalar_one()
    if ja_tem >= PRODUTOS_POR_EMPRESA:
        return 0

    prefixo = "ABA" if empresa_id == ABACAXI else "UVA"
    for numero in range(ja_tem + 1, PRODUTOS_POR_EMPRESA + 1):
        familia = SORTEIO.choice(FAMILIAS)
        modelo = SORTEIO.choice(MODELOS)

        # 1 em cada 12 nasce inativo: `active = false` é caso de borda da listagem, e
        # descontinuado não some do catálogo — só deixa de aparecer por padrão.
        ativo = numero % 12 != 0

        produto = Produto(
            tenant_id=empresa_id,
            code=f"{prefixo}-{numero:04d}",
            description=f"{familia} {modelo} {numero:04d}",
            active=ativo,
        )
        sessao.add(produto)
        await sessao.flush()

        for indice, (acabamento, tamanho) in enumerate(zip(ACABAMENTOS, TAMANHOS, strict=True)):
            variante = Variante(
                tenant_id=empresa_id,
                product_id=produto.id,
                finish=acabamento,
                size=tamanho,
                active=True,
            )
            sessao.add(variante)
            await sessao.flush()

            # 1 em 15 fica sem linha em `product_tenant`: "sem preço" é diferente de
            # "preço zero", e a listagem precisa distinguir os dois.
            if numero % 15 == 0 and indice == 2:
                continue

            # 1 em 20 custa zero e tem estoque zero — de propósito.
            zerado = numero % 20 == 0
            sessao.add(
                ProdutoEmpresa(
                    tenant_id=empresa_id,
                    variant_id=variante.id,
                    price_cents=0 if zerado else SORTEIO.randrange(4_900, 890_000, 10),
                    stock_qty=Decimal(0) if zerado else Decimal(SORTEIO.randrange(0, 400)),
                    min_stock=Decimal(SORTEIO.choice([0, 2, 5])),
                )
            )

    return PRODUTOS_POR_EMPRESA - ja_tem


async def _ana_silva(sessao: AsyncSession) -> None:
    """`admin` na ABACAXI, `operator-sales` na UVA. Mesma pessoa, papel por empresa."""
    email = "ana@grupo.dev"
    pessoa = (
        await sessao.execute(select(Colaborador).where(Colaborador.email == email))
    ).scalar_one_or_none()
    if pessoa is None:
        pessoa = Colaborador(name="ANA SILVA", email=email, active=True)
        sessao.add(pessoa)
        await sessao.commit()

    for empresa_id, papel in (
        (ABACAXI, PapelEmpresa.admin),
        (UVA, PapelEmpresa.operator_sales),
    ):
        async with SessionLocal() as por_empresa:
            await declarar_empresa(por_empresa, empresa_id)
            existente = await por_empresa.get(ColaboradorEmpresa, (empresa_id, pessoa.id))
            if existente is None:
                por_empresa.add(
                    ColaboradorEmpresa(
                        tenant_id=empresa_id, employee_id=pessoa.id, role=papel.value
                    )
                )
                await por_empresa.commit()
    print(f"  ANA SILVA: admin na ABACAXI, operator-sales na UVA ({pessoa.id})")


if __name__ == "__main__":
    asyncio.run(main())
