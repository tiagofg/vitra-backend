"""Cadastros de pessoas — parceiro (cliente/fornecedor/profissional num cadastro só, com
obra e condição comercial), colaborador e transportadora.

**A unificação em `partners`.** Até o diagrama `cabinet-minimo`, `cliente`, `fornecedor` e
`profissional_externo` eram três tabelas com as mesmas ~25 colunas de identidade (nome,
documento, endereço, contatos) e três CRUDs idênticos. O diagrama as funde em `partners`
com três bandeiras — `is_customer`, `is_supplier`, `is_professional` — e a fusão resolve um
problema real do ramo, não só duplicação de código: o **arquiteto que também compra** e a
**loja que também revende** existem, e nas três tabelas viravam três cadastros
desconectados da mesma pessoa, com o mesmo CNPJ, sem nada ligando um ao outro.

Uma pessoa pode ser as três coisas ao mesmo tempo; o `CHECK` só exige que seja ao menos
uma. Quem filtra por papel é a bandeira (`ParceiroService.somente(...)`), não a tabela.

`partners` continua **por empresa** (`ModeloTenant`, sob RLS), ao contrário do diagrama, que
a desenha global: o cliente de uma empresa do grupo não pode aparecer na listagem da outra.
O que é global de verdade continua global (`catalog_lookups`, `tenants`, `employees`).

Nome físico de tabela em inglês aqui (`partners`, `partner_tenant_links`) porque é o nome do
diagrama; as tabelas que ele não redesenha (`obra`, `transportadora`, `colaborador`,
`fornecedor_empresa`) mantêm o português com que nasceram.
"""

from __future__ import annotations

import enum
import uuid
from datetime import date
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.base_model import ModeloTenant, pk_tenant
from app.common.mixins import AtivoMixin, ContatosMixin, EnderecoMixin, ObservacaoMixin
from app.core.numbering import enum_col
from app.modules.auth.models import Usuario


class TipoPessoa(enum.StrEnum):
    fisica = "fisica"
    juridica = "juridica"


TIPO_PESSOA_ENUM = enum_col(TipoPessoa, "tipo_pessoa")


class Parceiro(ModeloTenant, AtivoMixin, EnderecoMixin, ContatosMixin, ObservacaoMixin):
    __tablename__ = "partners"
    __table_args__ = (
        pk_tenant("partners"),
        UniqueConstraint("tenant_id", "codigo", name="uq_partners_tenant_codigo"),
        ForeignKeyConstraint(
            ["tenant_id", "transportadora_padrao_id"],
            ["transportadora.tenant_id", "transportadora.id"],
            name="fk_partners_transportadora_padrao",
            ondelete="RESTRICT",
        ),
        # Um parceiro que não é nem cliente, nem fornecedor, nem profissional não é nada —
        # seria uma linha invisível para toda listagem do sistema, que ninguém conseguiria
        # achar depois para corrigir.
        CheckConstraint(
            "is_customer OR is_supplier OR is_professional",
            name="partners_ao_menos_um_papel",
        ),
        Index("ix_partners_tenant_legal_name", "tenant_id", "legal_name"),
    )

    codigo: Mapped[str] = mapped_column(String(20), nullable=False)
    # `legal_name`/`trade_name` do diagrama. Para pessoa física, `razao_social` é o nome
    # civil — a coluna é a mesma, o rótulo na tela é que muda com `tipo_pessoa`.
    razao_social: Mapped[str] = mapped_column("legal_name", String(160), nullable=False)
    nome_fantasia: Mapped[str | None] = mapped_column("trade_name", String(160))
    tipo_pessoa: Mapped[TipoPessoa] = mapped_column(TIPO_PESSOA_ENUM, nullable=False)
    # `varchar(14)` cobre os dois: CPF são 11 dígitos, CNPJ são 14. `CpfCnpj`
    # (`app/common/schemas.py`) só normaliza e aceita 11 **ou** 14; quem confere que o
    # tamanho bate com `tipo_pessoa` é o `model_validator` do schema.
    cpf_cnpj: Mapped[str | None] = mapped_column("document", String(14))
    rg_ie: Mapped[str | None] = mapped_column(String(20))
    dt_nascimento: Mapped[date | None] = mapped_column(Date)

    # --- os três papéis ---
    e_cliente: Mapped[bool] = mapped_column("is_customer", Boolean, nullable=False, default=False)
    e_fornecedor: Mapped[bool] = mapped_column(
        "is_supplier", Boolean, nullable=False, default=False
    )
    e_profissional: Mapped[bool] = mapped_column(
        "is_professional", Boolean, nullable=False, default=False
    )

    # CREA (engenheiro) ou CAU (arquiteto) — campo livre, sem validar dígito verificador.
    # Só faz sentido com `e_profissional`, mas não é `CHECK`: o registro pode ser preenchido
    # antes de a bandeira ser marcada, e recusar isso irritaria sem proteger nada.
    registro_profissional: Mapped[str | None] = mapped_column("registration", String(30))

    # Conta para repasse de comissão do profissional e pagamento do fornecedor. JSONB, e não
    # colunas: banco/agência/conta/tipo/PIX mudam de formato por instituição, e nenhuma
    # consulta filtra por eles.
    dados_bancarios: Mapped[dict[str, Any] | None] = mapped_column("payout_bank_details", JSONB)

    # Os `[combo +...]` da ficha. FK simples: `catalog_lookups` é global, sem `tenant_id`.
    profissao_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("catalog_lookups.id", ondelete="RESTRICT")
    )
    estado_civil_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("catalog_lookups.id", ondelete="RESTRICT")
    )
    raca_cor_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("catalog_lookups.id", ondelete="RESTRICT")
    )
    nacionalidade_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("catalog_lookups.id", ondelete="RESTRICT")
    )
    categoria_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("catalog_lookups.id", ondelete="RESTRICT")
    )

    transportadora_padrao_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)

    obras: Mapped[list[Obra]] = relationship(back_populates="parceiro")
    historico_empresas: Mapped[list[FornecedorEmpresa]] = relationship(
        back_populates="parceiro", cascade="all, delete-orphan"
    )


class ParceiroEmpresa(ModeloTenant, AtivoMixin):
    """`partner_tenant_links` — a condição comercial do parceiro naquela empresa.

    Separada de `partners` pela mesma razão que `variant_tenant_settings` é separada de
    `product_variants`: identidade de um lado, acordo comercial do outro. O CNPJ do
    fornecedor é o mesmo em todo o grupo; o prazo de pagamento e o limite de crédito que a
    VERTZ negociou com ele não são os da Via HF.

    Não confundir com `FornecedorEmpresa`, logo abaixo: aquela é o **histórico com
    vigência** de qual empresa do grupo compra deste fornecedor; esta é a condição
    corrente, sem linha do tempo.
    """

    __tablename__ = "partner_tenant_links"
    __table_args__ = (
        pk_tenant("partner_tenant_links"),
        ForeignKeyConstraint(
            ["tenant_id", "partner_id"],
            ["partners.tenant_id", "partners.id"],
            name="fk_partner_tenant_links_partner",
            ondelete="CASCADE",
        ),
        UniqueConstraint("tenant_id", "partner_id", name="uq_partner_tenant_links_partner"),
        CheckConstraint(
            "credit_limit_cents IS NULL OR credit_limit_cents >= 0",
            name="credit_limit_nao_negativo",
        ),
    )

    parceiro_id: Mapped[uuid.UUID] = mapped_column("partner_id", Uuid, nullable=False)
    # O código que **esta** empresa usa para o parceiro, quando difere do código geral —
    # herança de quem migra de outro sistema e não quer reescrever a referência antiga.
    codigo: Mapped[str | None] = mapped_column("code", String(20))
    condicao_pagamento: Mapped[str | None] = mapped_column("payment_terms", String(60))
    limite_credito_cents: Mapped[int | None] = mapped_column("credit_limit_cents", BigInteger)

    parceiro: Mapped[Parceiro] = relationship()


class Obra(ModeloTenant, AtivoMixin, EnderecoMixin):
    """`Parceiro → Obra`. É o `quotes.site_id` do diagrama — que lá aponta para lugar
    nenhum, porque o diagrama não desenha esta tabela.

    A tela nunca foi capturada nas fontes do legado — modelo mínimo assumido (ver "Lacunas
    reais das fontes" no plano); ambientes vivem no orçamento, não aqui.
    """

    __tablename__ = "obra"
    __table_args__ = (
        pk_tenant("obra"),
        ForeignKeyConstraint(
            ["tenant_id", "parceiro_id"],
            ["partners.tenant_id", "partners.id"],
            name="fk_obra_parceiro",
            ondelete="CASCADE",
        ),
    )

    parceiro_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    nome: Mapped[str] = mapped_column(String(160), nullable=False)

    parceiro: Mapped[Parceiro] = relationship(back_populates="obras")


class Transportadora(ModeloTenant, AtivoMixin, EnderecoMixin, ContatosMixin):
    """Fora de `partners` de propósito: transportadora não é parte do negócio (não compra,
    não vende, não indica), é logística — não tem nenhuma das três bandeiras, e forçá-la
    para dentro exigiria uma quarta que só ela usaria."""

    __tablename__ = "transportadora"
    __table_args__ = (
        pk_tenant("transportadora"),
        UniqueConstraint("tenant_id", "codigo", name="uq_transportadora_tenant_codigo"),
    )

    codigo: Mapped[str] = mapped_column(String(20), nullable=False)
    nome: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    cnpj: Mapped[str | None] = mapped_column(String(14))
    # Registro Nacional de Transportadores Rodoviários de Carga.
    antt: Mapped[str | None] = mapped_column(String(20))


class FornecedorEmpresa(ModeloTenant):
    """Aba `Histórico Emp. Comp.`: qual empresa do grupo compra deste parceiro, ao longo do
    tempo. O vínculo muda, então é histórico com vigência — não coluna no parceiro.

    Duas colunas apontam para uma empresa e significam coisas diferentes — não é
    redundância: `tenant_id` é *de quem é a linha* (o recorte do RLS, sempre a empresa que
    está com a conexão aberta); `empresa_compradora_id` é *qual empresa do grupo compra
    deste fornecedor*. As duas podem, e normalmente vão, ser a mesma — mas contam histórias
    diferentes.
    """

    __tablename__ = "fornecedor_empresa"
    __table_args__ = (
        pk_tenant("fornecedor_empresa"),
        ForeignKeyConstraint(
            ["tenant_id", "parceiro_id"],
            ["partners.tenant_id", "partners.id"],
            name="fk_fornecedor_empresa_parceiro",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["empresa_compradora_id"],
            ["tenants.id"],
            name="fk_fornecedor_empresa_compradora",
            ondelete="RESTRICT",
        ),
        # Só uma vigência aberta (`vigencia_fim IS NULL`) por parceiro: é a regra que a tela
        # pressupõe («o histórico tem uma linha atual») e que nenhuma checagem de serviço
        # garante sozinha sem o índice.
        Index(
            "uq_fornecedor_empresa_vigente",
            "tenant_id",
            "parceiro_id",
            unique=True,
            postgresql_where=text("vigencia_fim IS NULL"),
        ),
    )

    parceiro_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    empresa_compradora_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    vigencia_inicio: Mapped[date] = mapped_column(Date, nullable=False)
    vigencia_fim: Mapped[date | None] = mapped_column(Date)
    motivo: Mapped[str | None] = mapped_column(String(300))

    parceiro: Mapped[Parceiro] = relationship(back_populates="historico_empresas")


class Colaborador(ModeloTenant, AtivoMixin):
    """Dados de RH da pessoa **naquela empresa** — cargo, setor, admissão, vínculo. A
    identidade (login, senha) é global (`Usuario` = `employees`); o que muda de empresa para
    empresa é o papel de trabalho, não quem a pessoa é.

    Fora de `partners`: colaborador não é contraparte comercial, é gente de dentro — e a
    identidade dele já tem tabela própria e global (`employees`), que `partners` não teria
    como reaproveitar sem duplicar login e senha por empresa.
    """

    __tablename__ = "colaborador"
    __table_args__ = (
        pk_tenant("colaborador"),
        UniqueConstraint("tenant_id", "employee_id", name="uq_colaborador_tenant_employee"),
    )

    employee_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("employees.id", ondelete="CASCADE"), nullable=False
    )
    dt_admissao: Mapped[date | None] = mapped_column(Date)
    cargo_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("catalog_lookups.id", ondelete="RESTRICT")
    )
    setor_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("catalog_lookups.id", ondelete="RESTRICT")
    )
    vinculo_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("catalog_lookups.id", ondelete="RESTRICT")
    )
    grau_instrucao_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("catalog_lookups.id", ondelete="RESTRICT")
    )

    # `foreign_keys` explícito: `criado_por_id` (herdado de `_AuditoriaMixin`) também aponta
    # para `employees.id`, então o SQLAlchemy não consegue escolher sozinho qual FK usar
    # para este relacionamento.
    colaborador: Mapped[Usuario] = relationship(foreign_keys=[employee_id], lazy="joined")
