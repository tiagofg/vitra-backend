"""Seed idempotente da F0.

    python scripts/seed.py

Cria/atualiza: permissões (a partir do catálogo), UFs, cidades e bancos de exemplo,
as duas empresas do grupo, os grupos de acesso e o usuário administrador.
Rodar duas vezes não duplica nada.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.db import SessionLocal, engine  # noqa: E402
from app.core.permissions import pares_do_catalogo  # noqa: E402
from app.core.security import gerar_hash_senha  # noqa: E402
from app.modules.apoio.models import Banco, Cidade, DominioApoio, TabelaApoio, Uf  # noqa: E402
from app.modules.auth.models import Grupo, Permissao, Usuario  # noqa: E402
from app.modules.empresa.models import Empresa, Filial  # noqa: E402

ADMIN_LOGIN = os.getenv("VITRA_ADMIN_LOGIN", "admin")
ADMIN_SENHA = os.getenv("VITRA_ADMIN_SENHA", "admin12345")

UFS: list[tuple[str, str, str]] = [
    ("AC", "Acre", "12"), ("AL", "Alagoas", "27"), ("AP", "Amapá", "16"),
    ("AM", "Amazonas", "13"), ("BA", "Bahia", "29"), ("CE", "Ceará", "23"),
    ("DF", "Distrito Federal", "53"), ("ES", "Espírito Santo", "32"), ("GO", "Goiás", "52"),
    ("MA", "Maranhão", "21"), ("MT", "Mato Grosso", "51"), ("MS", "Mato Grosso do Sul", "50"),
    ("MG", "Minas Gerais", "31"), ("PA", "Pará", "15"), ("PB", "Paraíba", "25"),
    ("PR", "Paraná", "41"), ("PE", "Pernambuco", "26"), ("PI", "Piauí", "22"),
    ("RJ", "Rio de Janeiro", "33"), ("RN", "Rio Grande do Norte", "24"),
    ("RS", "Rio Grande do Sul", "43"), ("RO", "Rondônia", "11"), ("RR", "Roraima", "14"),
    ("SC", "Santa Catarina", "42"), ("SP", "São Paulo", "35"), ("SE", "Sergipe", "28"),
    ("TO", "Tocantins", "17"),
]

CIDADES: list[tuple[str, str, str]] = [
    ("SP", "São Paulo", "3550308"),
    ("SP", "Campinas", "3509502"),
    ("RJ", "Rio de Janeiro", "3304557"),
    ("MG", "Belo Horizonte", "3106200"),
    ("PR", "Curitiba", "4106902"),
    ("SC", "Florianópolis", "4205407"),
    ("RS", "Porto Alegre", "4314902"),
    ("GO", "Goiânia", "5208707"),
]

BANCOS: list[tuple[str, str]] = [
    ("001", "Banco do Brasil"),
    ("033", "Santander"),
    ("104", "Caixa Econômica Federal"),
    ("237", "Bradesco"),
    ("341", "Itaú Unibanco"),
    ("260", "Nu Pagamentos"),
    ("077", "Banco Inter"),
    ("756", "Sicoob"),
]

# Valores de apoio que já aparecem nas telas transcritas.
APOIO: dict[DominioApoio, list[tuple[str, str]]] = {
    DominioApoio.unidade: [
        ("un", "Unidade"), ("pc", "Peça"), ("cx", "Caixa"),
        ("mt", "Metro"), ("m2", "Metro quadrado"), ("kg", "Quilograma"),
    ],
    DominioApoio.acabamento: [
        ("preto", "Preto"), ("branco", "Branco"), ("dourado", "Dourado"),
        ("cobre", "Cobre"), ("escovado", "Alumínio escovado"),
    ],
    DominioApoio.tamanho: [
        ("p", "Pequeno"), ("m", "Médio"), ("g", "Grande"), ("unico", "Único"),
    ],
    DominioApoio.tipo_produto: [
        ("luminaria", "Luminária"), ("lampada", "Lâmpada"),
        ("fita_led", "Fita de LED"), ("perfil", "Perfil"), ("acessorio", "Acessório"),
    ],
    DominioApoio.tipo_peca: [
        ("pendente", "Pendente"), ("embutido", "Embutido"),
        ("sobrepor", "Sobrepor"), ("arandela", "Arandela"), ("trilho", "Trilho"),
    ],
    DominioApoio.classificacao: [("a", "Curva A"), ("b", "Curva B"), ("c", "Curva C")],
    DominioApoio.estado_civil: [
        ("solteiro", "Solteiro(a)"), ("casado", "Casado(a)"),
        ("divorciado", "Divorciado(a)"), ("viuvo", "Viúvo(a)"), ("uniao", "União estável"),
    ],
    DominioApoio.cargo: [
        ("consultor", "Consultor de vendas"), ("gerente", "Gerente"),
        ("comprador", "Comprador"), ("estoquista", "Estoquista"),
    ],
    DominioApoio.setor: [
        ("vendas", "Vendas"), ("compras", "Compras"),
        ("estoque", "Estoque"), ("administrativo", "Administrativo"),
    ],
}

# Perfis de acesso. O administrador recebe tudo; o consultor só leitura + apoio.
GRUPOS_LEITURA = {"consultor"}


async def sincronizar_permissoes(session: AsyncSession) -> list[Permissao]:
    existentes = {
        (p.recurso, p.acao): p
        for p in (await session.execute(select(Permissao))).scalars().all()
    }
    for recurso, acao in pares_do_catalogo():
        if (recurso, acao) not in existentes:
            nova = Permissao(recurso=recurso, acao=acao, descricao=f"{acao} {recurso}")
            session.add(nova)
            existentes[(recurso, acao)] = nova
    await session.flush()
    return list(existentes.values())


async def semear_ufs(session: AsyncSession) -> dict[str, Uf]:
    atuais = {u.sigla: u for u in (await session.execute(select(Uf))).scalars().all()}
    for sigla, nome, ibge in UFS:
        if sigla not in atuais:
            uf = Uf(sigla=sigla, nome=nome, codigo_ibge=ibge)
            session.add(uf)
            atuais[sigla] = uf
    await session.flush()
    return atuais


async def semear_cidades(session: AsyncSession, ufs: dict[str, Uf]) -> None:
    atuais = {
        (c.uf_id, c.nome) for c in (await session.execute(select(Cidade))).scalars().all()
    }
    for sigla, nome, ibge in CIDADES:
        uf = ufs[sigla]
        if (uf.id, nome) not in atuais:
            session.add(Cidade(uf_id=uf.id, nome=nome, codigo_ibge=ibge))
    await session.flush()


async def semear_bancos(session: AsyncSession) -> None:
    atuais = {b.codigo for b in (await session.execute(select(Banco))).scalars().all()}
    for codigo, nome in BANCOS:
        if codigo not in atuais:
            session.add(Banco(codigo=codigo, nome=nome))
    await session.flush()


async def semear_apoio(session: AsyncSession) -> int:
    atuais = {
        (a.dominio, a.codigo, a.empresa_id)
        for a in (await session.execute(select(TabelaApoio))).scalars().all()
    }
    criados = 0
    for dominio, valores in APOIO.items():
        for ordem, (codigo, descricao) in enumerate(valores):
            if (dominio, codigo, None) in atuais:
                continue
            session.add(
                TabelaApoio(dominio=dominio, codigo=codigo, descricao=descricao, ordem=ordem)
            )
            criados += 1
    await session.flush()
    return criados


async def semear_empresas(session: AsyncSession, ufs: dict[str, Uf]) -> dict[str, Empresa]:
    atuais = {e.codigo: e for e in (await session.execute(select(Empresa))).scalars().all()}
    definicoes = [
        ("VERTZ", "Vertz Iluminação e Decoração Ltda", "Vertz"),
        ("VIAHF", "Via HF Iluminação Ltda", "Via HF Iluminação"),
    ]
    for codigo, razao, fantasia in definicoes:
        if codigo not in atuais:
            empresa = Empresa(codigo=codigo, razao_social=razao, nome_fantasia=fantasia)
            session.add(empresa)
            atuais[codigo] = empresa
    await session.flush()

    filiais = {
        (f.empresa_id, f.codigo)
        for f in (await session.execute(select(Filial))).scalars().all()
    }
    for codigo in ("VERTZ", "VIAHF"):
        empresa = atuais[codigo]
        if (empresa.id, "001") not in filiais:
            session.add(
                Filial(
                    empresa_id=empresa.id,
                    codigo="001",
                    nome=f"{empresa.nome_fantasia} — Matriz",
                    matriz=True,
                )
            )
    await session.flush()
    return atuais


async def semear_acesso(
    session: AsyncSession, permissoes: list[Permissao], empresa: Empresa
) -> tuple[Usuario, bool]:
    grupos = {g.nome: g for g in (await session.execute(select(Grupo))).scalars().all()}

    if "Administradores" not in grupos:
        grupos["Administradores"] = Grupo(
            nome="Administradores", descricao="Acesso total ao sistema"
        )
        session.add(grupos["Administradores"])
    grupos["Administradores"].permissoes = permissoes

    if "Consultor" not in grupos:
        grupos["Consultor"] = Grupo(nome="Consultor", descricao="Vendas — leitura de cadastros")
        session.add(grupos["Consultor"])
    grupos["Consultor"].permissoes = [
        p for p in permissoes if p.acao == "ler" or p.recurso == "apoio"
    ]
    await session.flush()

    admin = (
        await session.execute(select(Usuario).where(Usuario.login == ADMIN_LOGIN))
    ).scalar_one_or_none()
    criado = admin is None
    if admin is None:
        admin = Usuario(
            login=ADMIN_LOGIN,
            nome="Administrador",
            senha_hash=gerar_hash_senha(ADMIN_SENHA),
            superusuario=True,
            empresa_id=empresa.id,
        )
        session.add(admin)
    admin.grupos = [grupos["Administradores"]]
    await session.flush()
    return admin, criado


async def main() -> None:
    async with SessionLocal() as session:
        permissoes = await sincronizar_permissoes(session)
        ufs = await semear_ufs(session)
        await semear_cidades(session, ufs)
        await semear_bancos(session)
        apoio_criados = await semear_apoio(session)
        empresas = await semear_empresas(session, ufs)
        _, admin_criado = await semear_acesso(session, permissoes, empresas["VERTZ"])
        await session.commit()

    print(f"permissões no catálogo : {len(permissoes)}")
    print(f"UFs                    : {len(ufs)}")
    print(f"valores de apoio novos : {apoio_criados}")
    print(f"empresas               : {', '.join(sorted(empresas))}")
    if admin_criado:
        print(f"\nusuário criado: {ADMIN_LOGIN} / {ADMIN_SENHA}  (troque a senha)")
    else:
        print(f"\nusuário '{ADMIN_LOGIN}' já existia — senha preservada")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
