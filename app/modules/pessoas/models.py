"""Cadastros de pessoas — cliente (com obra), fornecedor (com histórico de empresa
compradora), colaborador, profissional externo, transportadora.

Todas por empresa (`ModeloTenant`), como a S0.5 já tinha decidido para clientes,
fornecedores e profissionais. Nome físico de tabela em **português**: ao contrário das sete
tabelas herdadas do bake-off (`products`, `tenants`, `employees` — DDL fixo do banco
compartilhado do Neon), estas nascem neste projeto, e a S0/S0.5 já usa português nas tabelas
próprias (`filial`, `centro_custo`, `cidade`, `banco`, `grupo`). Manter o inglês só faria
sentido pela regra escrita no README, cuja razão original — schema compartilhado imutável —
não existe para tabela nova.
"""

from __future__ import annotations

import enum
import uuid
from datetime import date

from sqlalchemy import (
    Date,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.base_model import ModeloTenant, pk_tenant
from app.common.mixins import AtivoMixin, ContatosMixin, EnderecoMixin, ObservacaoMixin
from app.core.numbering import enum_col
from app.modules.auth.models import Usuario


class TipoPessoa(enum.StrEnum):
    fisica = "fisica"
    juridica = "juridica"


TIPO_PESSOA_ENUM = enum_col(TipoPessoa, "tipo_pessoa")


class Cliente(ModeloTenant, AtivoMixin, EnderecoMixin, ContatosMixin, ObservacaoMixin):
    __tablename__ = "cliente"
    __table_args__ = (
        pk_tenant("cliente"),
        UniqueConstraint("tenant_id", "codigo", name="uq_cliente_tenant_codigo"),
    )

    codigo: Mapped[str] = mapped_column(String(20), nullable=False)
    nome: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    tipo_pessoa: Mapped[TipoPessoa] = mapped_column(TIPO_PESSOA_ENUM, nullable=False)
    # `varchar(14)` cobre os dois: CPF são 11 dígitos, CNPJ são 14. `CpfCnpj`
    # (`app/common/schemas.py`) só normaliza e aceita 11 **ou** 14; quem confere que o
    # tamanho bate com `tipo_pessoa` é o `model_validator` do schema
    # (`ClienteCriar._documento_bate_com_tipo_pessoa`).
    cpf_cnpj: Mapped[str | None] = mapped_column(String(14))
    rg_ie: Mapped[str | None] = mapped_column(String(20))
    dt_nascimento: Mapped[date | None] = mapped_column(Date)

    # Os cinco `[combo +...]` da ficha de cliente. FK simples: `catalog_lookups` é global,
    # sem `tenant_id`, então não há chave composta a carregar aqui.
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

    obras: Mapped[list[Obra]] = relationship(back_populates="cliente")


class Obra(ModeloTenant, AtivoMixin, EnderecoMixin):
    """`Cliente → Obra`. A tela nunca foi capturada nas fontes do legado — modelo mínimo
    assumido (ver "Lacunas reais das fontes" no plano); ambientes vivem no orçamento, não
    aqui."""

    __tablename__ = "obra"
    __table_args__ = (
        pk_tenant("obra"),
        ForeignKeyConstraint(
            ["tenant_id", "cliente_id"],
            ["cliente.tenant_id", "cliente.id"],
            name="fk_obra_cliente",
            ondelete="CASCADE",
        ),
    )

    cliente_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    nome: Mapped[str] = mapped_column(String(160), nullable=False)

    cliente: Mapped[Cliente] = relationship(back_populates="obras")


class Transportadora(ModeloTenant, AtivoMixin, EnderecoMixin, ContatosMixin):
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


class Fornecedor(ModeloTenant, AtivoMixin, EnderecoMixin, ContatosMixin):
    __tablename__ = "fornecedor"
    __table_args__ = (
        pk_tenant("fornecedor"),
        UniqueConstraint("tenant_id", "codigo", name="uq_fornecedor_tenant_codigo"),
        # `RESTRICT`, não `SET NULL`: cadastro deste projeto nunca é apagado de verdade
        # (`ativo=false` — ver `AtivoMixin`), então o `ON DELETE` quase nunca dispara; e
        # `SET NULL` numa FK composta teria que zerar `tenant_id` também, que é `NOT NULL`
        # e faz parte da PK. Postgres 17 aceita `SET NULL` por coluna específica desde a 15,
        # mas não vale a complexidade para um caminho que a aplicação não exercita.
        ForeignKeyConstraint(
            ["tenant_id", "transportadora_padrao_id"],
            ["transportadora.tenant_id", "transportadora.id"],
            name="fk_fornecedor_transportadora_padrao",
            ondelete="RESTRICT",
        ),
    )

    codigo: Mapped[str] = mapped_column(String(20), nullable=False)
    razao_social: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    nome_fantasia: Mapped[str | None] = mapped_column(String(160))
    cnpj: Mapped[str | None] = mapped_column(String(14))
    transportadora_padrao_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)

    historico_empresas: Mapped[list[FornecedorEmpresa]] = relationship(
        back_populates="fornecedor", cascade="all, delete-orphan"
    )


class FornecedorEmpresa(ModeloTenant):
    """`Empresa compradora` + aba `Histórico Emp. Comp.`: o vínculo muda no tempo, então é
    histórico com vigência, não coluna no fornecedor.

    Duas colunas apontam para uma empresa e significam coisas diferentes — não é redundância:
    `tenant_id` é *de quem é a linha* (o recorte do RLS, sempre a empresa que está com a
    conexão aberta); `empresa_compradora_id` é *qual empresa do grupo compra deste
    fornecedor*, o dado de negócio que a aba `Histórico Emp. Comp.` mostra. As duas podem, e
    normalmente vão, ser a mesma empresa — mas contam histórias diferentes.
    """

    __tablename__ = "fornecedor_empresa"
    __table_args__ = (
        pk_tenant("fornecedor_empresa"),
        ForeignKeyConstraint(
            ["tenant_id", "fornecedor_id"],
            ["fornecedor.tenant_id", "fornecedor.id"],
            name="fk_fornecedor_empresa_fornecedor",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["empresa_compradora_id"],
            ["tenants.id"],
            name="fk_fornecedor_empresa_compradora",
            ondelete="RESTRICT",
        ),
        # Só uma vigência aberta (`vigencia_fim IS NULL`) por fornecedor: é a regra que a
        # tela pressupõe («o histórico tem uma linha atual») e que nenhuma checagem de
        # serviço garante sozinha sem o índice.
        Index(
            "uq_fornecedor_empresa_vigente",
            "tenant_id",
            "fornecedor_id",
            unique=True,
            postgresql_where=text("vigencia_fim IS NULL"),
        ),
    )

    fornecedor_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    empresa_compradora_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    vigencia_inicio: Mapped[date] = mapped_column(Date, nullable=False)
    vigencia_fim: Mapped[date | None] = mapped_column(Date)
    motivo: Mapped[str | None] = mapped_column(String(300))

    fornecedor: Mapped[Fornecedor] = relationship(back_populates="historico_empresas")


class ProfissionalExterno(ModeloTenant, AtivoMixin, EnderecoMixin, ContatosMixin):
    """O arquiteto/decorador do orçamento. Participação (comissão/rateio) fica fora da S1 —
    sem captura nas fontes; a FK do orçamento para cá já existe no plano e não quebra quando
    a participação entrar depois."""

    __tablename__ = "profissional_externo"
    __table_args__ = (
        pk_tenant("profissional_externo"),
        UniqueConstraint("tenant_id", "codigo", name="uq_profissional_externo_tenant_codigo"),
    )

    codigo: Mapped[str] = mapped_column(String(20), nullable=False)
    nome: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    tipo_pessoa: Mapped[TipoPessoa] = mapped_column(TIPO_PESSOA_ENUM, nullable=False)
    cpf_cnpj: Mapped[str | None] = mapped_column(String(14))
    profissao_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("catalog_lookups.id", ondelete="RESTRICT")
    )
    # CREA (engenheiro) ou CAU (arquiteto) — um campo livre, sem validar dígito verificador.
    crea_cau: Mapped[str | None] = mapped_column(String(30))


class Colaborador(ModeloTenant, AtivoMixin):
    """Dados de RH da pessoa **naquela empresa** — cargo, setor, admissão, vínculo. A
    identidade (login, senha) é global desde a S0.5 (`Usuario` = `employees`); o que muda de
    empresa para empresa é o papel de trabalho, não quem a pessoa é.

    Separado de `VinculoEmpresa` (`employee_company`) de propósito: aquela tabela é o
    caminho quente — lida em todo request por `tem_vinculo()` e, a partir da S2, por
    `require()` — e pendurar ~10 colunas de RH nela tornaria uma linha fina de acesso numa
    linha larga de cadastro. `Colaborador` é o cadastro; `VinculoEmpresa` continua sendo só
    "quem trabalha onde, com qual grupo".
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
