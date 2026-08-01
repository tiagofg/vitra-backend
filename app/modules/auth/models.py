from __future__ import annotations

import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Numeric,
    PrimaryKeyConstraint,
    String,
    Table,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.base_model import Base, ModeloBase
from app.common.mixins import AtivoMixin, TenantScopedMixin
from app.core.numbering import TIPO_DOCUMENTO_ENUM, TipoDocumento, enum_col

usuario_grupo = Table(
    "usuario_grupo",
    Base.metadata,
    Column("usuario_id", Uuid, ForeignKey("employees.id", ondelete="CASCADE"), primary_key=True),
    Column("grupo_id", Uuid, ForeignKey("grupo.id", ondelete="CASCADE"), primary_key=True),
)

grupo_permissao = Table(
    "grupo_permissao",
    Base.metadata,
    Column("grupo_id", Uuid, ForeignKey("grupo.id", ondelete="CASCADE"), primary_key=True),
    Column("permissao_id", Uuid, ForeignKey("permissao.id", ondelete="CASCADE"), primary_key=True),
)


class Permissao(ModeloBase):
    """Par recurso+ação. O catálogo canônico vive em `app/core/permissions.py`."""

    __tablename__ = "permissao"
    __table_args__ = (UniqueConstraint("recurso", "acao", name="uq_permissao_recurso_acao"),)

    recurso: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    acao: Mapped[str] = mapped_column(String(30), nullable=False)
    descricao: Mapped[str | None] = mapped_column(String(200))

    @property
    def chave(self) -> str:
        return f"{self.recurso}:{self.acao}"


class Grupo(ModeloBase, AtivoMixin):
    """O grupo de permissões. É o mesmo conceito que `employee_company.grupo_id` referencia
    como papel de uma pessoa numa empresa — ver `VinculoEmpresa`."""

    __tablename__ = "grupo"

    nome: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    descricao: Mapped[str | None] = mapped_column(String(200))

    permissoes: Mapped[list[Permissao]] = relationship(secondary=grupo_permissao, lazy="selectin")


class Usuario(ModeloBase, AtivoMixin):
    """Identidade única no grupo: quem loga **e** quem trabalha.

    Antes da unificação (S0.5) existiam duas tabelas para a mesma pessoa — `usuario`
    (login e senha) e `employees` (identidade do bake-off) —, ligadas por e-mail. A tabela
    física agora é `employees`; o nome da classe continua `Usuario` porque é a língua do
    domínio e é o nome que o resto do código já usa em toda parte.
    """

    __tablename__ = "employees"

    login: Mapped[str] = mapped_column(String(60), nullable=False, unique=True, index=True)
    nome: Mapped[str] = mapped_column("name", String(160), nullable=False)
    # Identidade, não só contato: é por ele que `employee_company` teria sido ligado antes
    # da unificação. Agora o vínculo é FK direta (`VinculoEmpresa.employee_id`), então o
    # e-mail não precisa mais ser único por essa razão — mas continua sendo, porque duas
    # contas com o mesmo e-mail seguem sendo o mesmo tipo de furo de identidade.
    email: Mapped[str] = mapped_column(String(160), nullable=False, unique=True)
    senha_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    # Incrementada a cada troca de senha. Vai no claim `sv` do token (`ClaimsToken`) e é
    # conferida em `usuario_atual`: um token emitido antes da troca deixa de autenticar,
    # mesmo dentro do prazo de validade — sem isto, uma senha vazada e depois trocada não
    # invalidava o token que já estava com quem não devia.
    senha_versao: Mapped[int] = mapped_column(default=0, nullable=False)
    superusuario: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Trava de força bruta em `/auth/login` — ver `AuthService.autenticar`. Só reseta ao
    # atingir o limite e a janela expirar, ou no login certo: não há decaimento gradual
    # (ex.: -1 por hora sem tentativa nova). Um script lento o bastante para nunca bater
    # nas 5 tentativas nunca aciona `bloqueado_ate`, e por ora não há IP throttle
    # complementar — aceito por enquanto, registrado para quando um dos dois entrar.
    tentativas_falhas: Mapped[int] = mapped_column(default=0, nullable=False)
    bloqueado_ate: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # `Alterar Limites` do orçamento: acima disto o desconto exige autorização (S4).
    limite_desconto_pct: Mapped[Decimal] = mapped_column(
        Numeric(9, 4), default=Decimal("0.0000"), nullable=False
    )

    grupos: Mapped[list[Grupo]] = relationship(secondary=usuario_grupo, lazy="selectin")

    def permissoes_efetivas(self) -> set[str]:
        return {p.chave for grupo in self.grupos if grupo.ativo for p in grupo.permissoes}

    def pode(self, recurso: str, acao: str) -> bool:
        return self.superusuario or f"{recurso}:{acao}" in self.permissoes_efetivas()


class VinculoEmpresa(Base, TenantScopedMixin):
    """Papel da pessoa naquela empresa — o antigo `employee_company.role` (5 valores
    fixos do bake-off), agora apontando para um `Grupo` de verdade.

    Uma pessoa, N papéis — um por empresa: ANA SILVA pode ser `admin` na ABACAXI e
    `operator-sales` na UVA porque são duas linhas aqui, não porque `Usuario` tem duas
    permissões. `grupo_id` nulável por ora: o RBAC por empresa (permissão que muda conforme
    a empresa ativa) é o que a S2 em diante passa a exercer de verdade; aqui a coluna já
    existe para que a tabela não precise de outra migração quando isso acontecer.

    **Até lá, `grupo_id` não é lido por `require()` em runtime.** `Usuario.pode()` resolve
    permissão só a partir de `usuario_grupo` — global, sem RLS, a mesma para o usuário em
    qualquer empresa. Ou seja: hoje o recorte por empresa protege *dado de tabela por
    empresa* (é o que o RLS garante), não *ação administrativa* — um `empresa:editar`
    concedido a alguém vale para editar qualquer empresa da instalação, não só a ativa.
    Isso é esperado e não é a lacuna que este comentário registra; a lacuna é não deixar
    isso implícito.
    """

    __tablename__ = "employee_company"
    # PK (tenant_id, employee_id), não (tenant_id, id): não há `id` aqui — é um vínculo por
    # (empresa, pessoa), não um registro autônomo. Por isso este modelo usa
    # `TenantScopedMixin` direto em vez de `ModeloTenant`, que assume a coluna `id`.
    __table_args__ = (PrimaryKeyConstraint("tenant_id", "employee_id", name="pk_employee_company"),)

    employee_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("employees.id", ondelete="CASCADE"), nullable=False
    )
    grupo_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("grupo.id", ondelete="RESTRICT"), nullable=True
    )

    colaborador: Mapped[Usuario] = relationship(lazy="joined")
    grupo: Mapped[Grupo | None] = relationship(lazy="joined")


class TipoAutorizacao(enum.StrEnum):
    desconto_acima_do_limite = "desconto_acima_do_limite"
    alteracao_de_preco = "alteracao_de_preco"
    liberacao_de_credito = "liberacao_de_credito"


class StatusAutorizacao(enum.StrEnum):
    pendente = "pendente"
    aprovada = "aprovada"
    rejeitada = "rejeitada"


class AutorizacaoDocumento(ModeloBase):
    """O botão `Permissões` do orçamento: autorização pontual, por documento.

    Modelo criado em S0 junto com o RBAC porque a migração inicial já o comporta;
    o serviço que o consome entra em S4 (desconto acima do limite do usuário).
    """

    __tablename__ = "autorizacao_documento"

    documento_tipo: Mapped[TipoDocumento] = mapped_column(TIPO_DOCUMENTO_ENUM, nullable=False)
    documento_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    tipo: Mapped[TipoAutorizacao] = mapped_column(
        enum_col(TipoAutorizacao, "tipo_autorizacao"), nullable=False
    )
    solicitante_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("employees.id", ondelete="RESTRICT"), nullable=False
    )
    autorizador_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("employees.id", ondelete="RESTRICT")
    )
    valor_solicitado: Mapped[Decimal | None] = mapped_column(Numeric(15, 4))
    status: Mapped[StatusAutorizacao] = mapped_column(
        enum_col(StatusAutorizacao, "status_autorizacao"),
        default=StatusAutorizacao.pendente,
        nullable=False,
    )
    motivo: Mapped[str | None] = mapped_column(String(500))
