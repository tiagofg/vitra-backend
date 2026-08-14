"""Seed idempotente.

    python scripts/seed.py

Cria/atualiza: permissões (a partir do catálogo), UFs, cidades e bancos de exemplo,
as duas empresas do grupo, os grupos de acesso, o usuário administrador, parceiros e
transportadora de exemplo, locais de estoque, e produtos com variante, preço e saldo
inicial — tudo sob a VERTZ.
Rodar duas vezes não duplica nada.
"""

from __future__ import annotations

import asyncio
import os
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import config  # noqa: E402
from app.core.db import SessionLocal, engine  # noqa: E402
from app.core.permissions import pares_do_catalogo  # noqa: E402
from app.core.security import gerar_hash_senha  # noqa: E402
from app.core.tenancy import declarar_empresa  # noqa: E402
from app.modules.apoio.models import Banco, Cidade, DominioApoio, TabelaApoio, Uf  # noqa: E402
from app.modules.auth.models import Grupo, Permissao, Usuario, VinculoEmpresa  # noqa: E402
from app.modules.empresa.models import Empresa, Filial  # noqa: E402
from app.modules.estoque.models import (  # noqa: E402
    LocalEstoque,
    MotivoMovimento,
    MovimentoEstoque,
    OrigemMovimento,
    SaldoEstoque,
    TipoLocalEstoque,
)
from app.modules.pessoas.models import Parceiro, Transportadora  # noqa: E402
from app.modules.produtos.models import Produto, Variante, VarianteEmpresa  # noqa: E402

ADMIN_LOGIN = os.getenv("VITRA_ADMIN_LOGIN", "admin")
ADMIN_SENHA = os.getenv("VITRA_ADMIN_SENHA", "admin12345")
ADMIN_EMAIL = os.getenv("VITRA_ADMIN_EMAIL", "admin@vertz.local")

UFS: list[tuple[str, str, str]] = [
    ("AC", "Acre", "12"),
    ("AL", "Alagoas", "27"),
    ("AP", "Amapá", "16"),
    ("AM", "Amazonas", "13"),
    ("BA", "Bahia", "29"),
    ("CE", "Ceará", "23"),
    ("DF", "Distrito Federal", "53"),
    ("ES", "Espírito Santo", "32"),
    ("GO", "Goiás", "52"),
    ("MA", "Maranhão", "21"),
    ("MT", "Mato Grosso", "51"),
    ("MS", "Mato Grosso do Sul", "50"),
    ("MG", "Minas Gerais", "31"),
    ("PA", "Pará", "15"),
    ("PB", "Paraíba", "25"),
    ("PR", "Paraná", "41"),
    ("PE", "Pernambuco", "26"),
    ("PI", "Piauí", "22"),
    ("RJ", "Rio de Janeiro", "33"),
    ("RN", "Rio Grande do Norte", "24"),
    ("RS", "Rio Grande do Sul", "43"),
    ("RO", "Rondônia", "11"),
    ("RR", "Roraima", "14"),
    ("SC", "Santa Catarina", "42"),
    ("SP", "São Paulo", "35"),
    ("SE", "Sergipe", "28"),
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
        ("un", "Unidade"),
        ("pc", "Peça"),
        ("cx", "Caixa"),
        ("mt", "Metro"),
        ("m2", "Metro quadrado"),
        ("kg", "Quilograma"),
    ],
    DominioApoio.acabamento: [
        ("preto", "Preto"),
        ("branco", "Branco"),
        ("dourado", "Dourado"),
        ("cobre", "Cobre"),
        ("escovado", "Alumínio escovado"),
    ],
    DominioApoio.tamanho: [
        ("p", "Pequeno"),
        ("m", "Médio"),
        ("g", "Grande"),
        ("unico", "Único"),
    ],
    DominioApoio.tipo_produto: [
        ("luminaria", "Luminária"),
        ("lampada", "Lâmpada"),
        ("fita_led", "Fita de LED"),
        ("perfil", "Perfil"),
        ("acessorio", "Acessório"),
    ],
    DominioApoio.tipo_peca: [
        ("pendente", "Pendente"),
        ("embutido", "Embutido"),
        ("sobrepor", "Sobrepor"),
        ("arandela", "Arandela"),
        ("trilho", "Trilho"),
    ],
    DominioApoio.classificacao: [("a", "Curva A"), ("b", "Curva B"), ("c", "Curva C")],
    DominioApoio.estado_civil: [
        ("solteiro", "Solteiro(a)"),
        ("casado", "Casado(a)"),
        ("divorciado", "Divorciado(a)"),
        ("viuvo", "Viúvo(a)"),
        ("uniao", "União estável"),
    ],
    DominioApoio.cargo: [
        ("consultor", "Consultor de vendas"),
        ("gerente", "Gerente"),
        ("comprador", "Comprador"),
        ("estoquista", "Estoquista"),
    ],
    DominioApoio.setor: [
        ("vendas", "Vendas"),
        ("compras", "Compras"),
        ("estoque", "Estoque"),
        ("administrativo", "Administrativo"),
    ],
    DominioApoio.profissao: [
        ("arquiteto", "Arquiteto(a)"),
        ("designer_de_interiores", "Designer de interiores"),
        ("engenheiro", "Engenheiro(a)"),
    ],
    DominioApoio.marca: [
        ("lumini", "Lumini"),
        ("bella_luce", "Bella Luce"),
    ],
}

# Cadastros de exemplo sob a empresa VERTZ.
# Parceiros: `(codigo, razao_social, tipo_pessoa, cliente, fornecedor,
# profissional)`. `PAR003` é o caso que motivou a unificação em `partners` — o escritório
# de arquitetura que indica obra **e** compra por conta própria seria dois cadastros
# desconectados no desenho antigo.
PARCEIROS: list[tuple[str, str, str, bool, bool, bool]] = [
    ("PAR001", "Maria Andrade", "fisica", True, False, False),
    ("PAR002", "Lumini Distribuidora Ltda", "juridica", False, True, False),
    ("PAR003", "Studio ADR Arquitetura Ltda", "juridica", True, False, True),
]

TRANSPORTADORAS: list[tuple[str, str]] = [
    ("TRA001", "Rápido Entrega Transportes Ltda"),
]

LOCAIS_ESTOQUE: list[tuple[str, str, TipoLocalEstoque]] = [
    ("DEP01", "Depósito central", TipoLocalEstoque.deposito),
    ("LOJ01", "Loja", TipoLocalEstoque.loja),
]

# Produtos de exemplo com variante (acabamento × tamanho) e preço/estoque — S2.
PRODUTOS: list[dict[str, Any]] = [
    {
        "codigo": "PEND001",
        "descricao": "Pendente Aurora",
        "marca": "lumini",
        "variantes": [
            {"acabamento": "preto", "tamanho": "m", "preco_cents": 45900, "estoque": "12.000"},
            {"acabamento": "dourado", "tamanho": "m", "preco_cents": 52900, "estoque": "5.000"},
        ],
    },
    {
        "codigo": "PLAF001",
        "descricao": "Plafon Vega",
        "marca": "bella_luce",
        "variantes": [
            {"acabamento": "branco", "tamanho": "unico", "preco_cents": 18900, "estoque": "30.000"},
        ],
    },
]


async def sincronizar_permissoes(session: AsyncSession) -> list[Permissao]:
    existentes = {
        (p.recurso, p.acao): p for p in (await session.execute(select(Permissao))).scalars().all()
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
    atuais = {(c.uf_id, c.nome) for c in (await session.execute(select(Cidade))).scalars().all()}
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
        (a.dominio, a.codigo) for a in (await session.execute(select(TabelaApoio))).scalars().all()
    }
    criados = 0
    for dominio, valores in APOIO.items():
        for ordem, (codigo, descricao) in enumerate(valores):
            if (dominio, codigo) in atuais:
                continue
            session.add(
                TabelaApoio(dominio=dominio, codigo=codigo, descricao=descricao, ordem=ordem)
            )
            criados += 1
    await session.flush()
    return criados


async def semear_empresas(session: AsyncSession) -> dict[str, Empresa]:
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

    # `filial` está sob RLS: a leitura e a escrita só enxergam a empresa declarada na
    # transação, então o laço declara cada uma antes de checar/criar a matriz dela — e
    # dá `flush()` a cada volta, senão o SQLAlchemy tenta agrupar os dois INSERTs num só
    # `executemany`, que sairia inteiro sob o `SET LOCAL` da última empresa declarada.
    for codigo in ("VERTZ", "VIAHF"):
        empresa = atuais[codigo]
        await declarar_empresa(session, empresa.id)
        existe = (await session.execute(select(Filial.id).where(Filial.codigo == "001"))).first()
        if existe is None:
            session.add(
                Filial(
                    tenant_id=empresa.id,
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
            email=ADMIN_EMAIL,
            senha_hash=gerar_hash_senha(ADMIN_SENHA),
            superusuario=True,
        )
        session.add(admin)
    admin.grupos = [grupos["Administradores"]]
    await session.flush()

    # `employee_company` está sob RLS: o vínculo entra na empresa declarada.
    await declarar_empresa(session, empresa.id)
    vinculo = (
        await session.execute(select(VinculoEmpresa).where(VinculoEmpresa.employee_id == admin.id))
    ).scalar_one_or_none()
    if vinculo is None:
        session.add(
            VinculoEmpresa(
                tenant_id=empresa.id,
                employee_id=admin.id,
                grupo_id=grupos["Administradores"].id,
            )
        )
    await session.flush()
    return admin, criado


async def semear_pessoas(session: AsyncSession, empresa: Empresa) -> int:
    """Parceiros e transportadora de exemplo, sob a empresa dada.

    `partners`/`transportadora` estão sob RLS: a leitura de "já existe?" só
    enxerga a empresa declarada, então a checagem de idempotência já sai recortada sem
    filtro escrito à mão — mesmo padrão de `semear_empresas` para `Filial`.
    """
    await declarar_empresa(session, empresa.id)
    criados = 0

    for codigo, razao_social, tipo_pessoa, e_cli, e_for, e_pro in PARCEIROS:
        existe = (
            await session.execute(select(Parceiro.id).where(Parceiro.codigo == codigo))
        ).first()
        if existe is None:
            session.add(
                Parceiro(
                    tenant_id=empresa.id,
                    codigo=codigo,
                    razao_social=razao_social,
                    tipo_pessoa=tipo_pessoa,
                    e_cliente=e_cli,
                    e_fornecedor=e_for,
                    e_profissional=e_pro,
                )
            )
            criados += 1

    for codigo, nome in TRANSPORTADORAS:
        existe = (
            await session.execute(select(Transportadora.id).where(Transportadora.codigo == codigo))
        ).first()
        if existe is None:
            session.add(Transportadora(tenant_id=empresa.id, codigo=codigo, nome=nome))
            criados += 1

    for codigo, nome, tipo in LOCAIS_ESTOQUE:
        existe = (
            await session.execute(select(LocalEstoque.id).where(LocalEstoque.codigo == codigo))
        ).first()
        if existe is None:
            session.add(LocalEstoque(tenant_id=empresa.id, codigo=codigo, nome=nome, tipo=tipo))
            criados += 1

    await session.flush()
    return criados


async def semear_produtos(session: AsyncSession, empresa: Empresa) -> int:
    """Produtos de exemplo com variante, preço e saldo inicial, sob a empresa dada —
    mesmo padrão de idempotência de `semear_pessoas`. Depende de `semear_apoio` (de onde
    vêm `marca`/`acabamento`/`tamanho`) e de `semear_pessoas` (de onde vêm os locais de
    estoque) já terem rodado nesta mesma transação.
    """
    await declarar_empresa(session, empresa.id)

    apoio_por_chave = {
        (a.dominio, a.codigo): a
        for a in (await session.execute(select(TabelaApoio))).scalars().all()
    }
    # Depende de `semear_pessoas` já ter rodado nesta transação — é de lá que vêm os locais.
    locais = {
        local.tipo: local for local in (await session.execute(select(LocalEstoque))).scalars().all()
    }

    criados = 0
    for definicao in PRODUTOS:
        existe = (
            await session.execute(select(Produto.id).where(Produto.codigo == definicao["codigo"]))
        ).first()
        if existe is not None:
            continue

        marca = apoio_por_chave.get((DominioApoio.marca, definicao["marca"]))
        produto = Produto(
            tenant_id=empresa.id,
            codigo=definicao["codigo"],
            descricao=definicao["descricao"],
            marca_id=marca.id if marca else None,
        )
        session.add(produto)
        await session.flush()
        criados += 1

        for var in definicao["variantes"]:
            acabamento = apoio_por_chave[(DominioApoio.acabamento, var["acabamento"])]
            tamanho = apoio_por_chave[(DominioApoio.tamanho, var["tamanho"])]
            variante = Variante(
                tenant_id=empresa.id,
                produto_id=produto.id,
                acabamento_id=acabamento.id,
                tamanho_id=tamanho.id,
            )
            session.add(variante)
            await session.flush()
            session.add(
                VarianteEmpresa(
                    tenant_id=empresa.id,
                    variante_id=variante.id,
                    preco_cents=var["preco_cents"],
                )
            )
            # O saldo não mora mais na variante: entra como movimento de inventário no
            # depósito, e o saldo é consequência dele — ver `app/modules/estoque/models.py`.
            deposito = locais[TipoLocalEstoque.deposito]
            qtd = Decimal(var["estoque"])
            session.add(
                SaldoEstoque(
                    tenant_id=empresa.id,
                    variante_id=variante.id,
                    local_id=deposito.id,
                    quantidade=qtd,
                )
            )
            session.add(
                MovimentoEstoque(
                    tenant_id=empresa.id,
                    variante_id=variante.id,
                    local_id=deposito.id,
                    delta=qtd,
                    motivo=MotivoMovimento.inventario,
                    origem_tipo=OrigemMovimento.inventario,
                    saldo_apos=qtd,
                )
            )

    await session.flush()
    return criados


HOSTS_LOCAIS = frozenset({"localhost", "127.0.0.1", "::1", "db"})


def _recusar_senha_padrao_fora_do_dev_local() -> None:
    """`Config` já recusa o boot da API com `jwt_secret` default em produção — o seed cria
    a conta que possui tudo com uma senha que está no Git (`admin12345`) e só imprime
    "(troque a senha)", o que não impede nada. Mesma classe de risco, guarda equivalente.

    Duas checagens, cinto e suspensório: `VITRA_AMBIENTE` é fácil de esquecer (o padrão é
    `"dev"`), e quem roda este script contra um banco remoto por engano não necessariamente
    setou a variável errada — só apontou `VITRA_DATABASE_URL` para o lugar errado. Comparar
    o **host** pega esse segundo caso; comparar a URL inteira não serviria — uma senha que
    por acaso contivesse `@banco-prod` bateria num `in` ingênuo sobre a string crua.
    """
    host = make_url(config.database_url).host or ""
    fora_do_dev_local = config.ambiente == "producao" or host not in HOSTS_LOCAIS
    if fora_do_dev_local and "VITRA_ADMIN_SENHA" not in os.environ:
        raise SystemExit(
            f"Recusando semear a senha padrão (admin12345) contra o host {host!r} — "
            "defina VITRA_ADMIN_SENHA explícita no ambiente."
        )


async def main() -> None:
    _recusar_senha_padrao_fora_do_dev_local()
    async with SessionLocal() as session:
        permissoes = await sincronizar_permissoes(session)
        ufs = await semear_ufs(session)
        await semear_cidades(session, ufs)
        await semear_bancos(session)
        apoio_criados = await semear_apoio(session)
        empresas = await semear_empresas(session)
        _, admin_criado = await semear_acesso(session, permissoes, empresas["VERTZ"])
        pessoas_criadas = await semear_pessoas(session, empresas["VERTZ"])
        produtos_criados = await semear_produtos(session, empresas["VERTZ"])
        await session.commit()

    print(f"permissões no catálogo : {len(permissoes)}")
    print(f"UFs                    : {len(ufs)}")
    print(f"valores de apoio novos : {apoio_criados}")
    print(f"empresas               : {', '.join(sorted(empresas))}")
    print(f"pessoas novas (VERTZ)  : {pessoas_criadas}")
    print(f"produtos novos (VERTZ) : {produtos_criados}")
    if admin_criado:
        print(f"\nusuário criado: {ADMIN_LOGIN} / {ADMIN_SENHA}  (troque a senha)")
    else:
        print(f"\nusuário '{ADMIN_LOGIN}' já existia — senha preservada")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
