from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import ForeignKey, String, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, declared_attr, mapped_column

# Os blocos abaixo aparecem repetidos em 4+ cadastros. São mixins de COLUNA, não tabelas:
# a tela trata cada bloco como um trecho inline do formulário e o join extra não pagaria.


class AtivoMixin:
    """Cadastros nunca são apagados — são desativados.

    Coluna física `active`: nome de coluna em inglês é a convenção do projeto (README,
    "Convenções que valem para todas as fases"); o atributo Python continua `ativo`, que é
    a língua do domínio. Isso também reconcilia as tabelas herdadas do bake-off — que já
    usavam `active` — com o resto do schema, sem exigir um `campo_ativo` por spec.
    """

    ativo: Mapped[bool] = mapped_column("active", default=True, nullable=False, index=True)


class TenantScopedMixin:
    """Tabela por empresa sob RLS: `tenant_id` faz parte da **chave primária**.

    A PK composta `(tenant_id, id)` não é enfeite. É ela que deixa a FK entre duas tabelas
    por empresa carregar o `tenant_id` junto — e é isso que torna *fisicamente impossível*
    ligar o preço da empresa A ao produto da empresa B. Não é validação de serviço que
    alguém pode esquecer: o `INSERT` falha.

    A ordem das colunas na PK vem do `PrimaryKeyConstraint` explícito de cada modelo, não
    da ordem de declaração — herança de mixin não dá garantia de ordem.
    """

    @declared_attr
    @classmethod
    def tenant_id(cls) -> Mapped[uuid.UUID]:
        # Sem `index=True`: a PK composta `(tenant_id, id)` já cria um índice com
        # `tenant_id` como coluna líder, que serve para tudo que um índice só nesta coluna
        # serviria. O segundo custaria escrita e espaço sem ganhar nenhuma consulta.
        return mapped_column(Uuid, ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False)


class EnderecoMixin:
    endereco_cep: Mapped[str | None] = mapped_column(String(9))
    endereco_logradouro: Mapped[str | None] = mapped_column(String(160))
    endereco_numero: Mapped[str | None] = mapped_column(String(20))
    endereco_complemento: Mapped[str | None] = mapped_column(String(80))
    endereco_bairro: Mapped[str | None] = mapped_column(String(80))
    endereco_ponto_referencia: Mapped[str | None] = mapped_column(String(160))

    @declared_attr
    @classmethod
    def endereco_cidade_id(cls) -> Mapped[uuid.UUID | None]:
        return mapped_column(Uuid, ForeignKey("cidade.id", ondelete="RESTRICT"), nullable=True)


class ContatosMixin:
    telefone: Mapped[str | None] = mapped_column(String(20))
    telefone_secundario: Mapped[str | None] = mapped_column(String(20))
    celular: Mapped[str | None] = mapped_column(String(20))
    fax: Mapped[str | None] = mapped_column(String(20))
    email: Mapped[str | None] = mapped_column(String(160))
    email_secundario: Mapped[str | None] = mapped_column(String(160))
    site: Mapped[str | None] = mapped_column(String(160))


class RedesSociaisMixin:
    instagram: Mapped[str | None] = mapped_column(String(120))
    facebook: Mapped[str | None] = mapped_column(String(120))
    linkedin: Mapped[str | None] = mapped_column(String(120))
    youtube: Mapped[str | None] = mapped_column(String(120))
    tiktok: Mapped[str | None] = mapped_column(String(120))


class ComunicadoresMixin:
    """Sempre 2 pares combo+texto na tela. Lista curta e sem consulta → JSONB."""

    comunicadores: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, server_default="[]", nullable=False
    )


class ObservacaoMixin:
    observacao: Mapped[str | None] = mapped_column(String(2000))
