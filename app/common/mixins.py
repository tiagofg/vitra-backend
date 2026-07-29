from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import ForeignKey, String, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, declared_attr, mapped_column

# Os blocos abaixo aparecem repetidos em 4+ cadastros. São mixins de COLUNA, não tabelas:
# a tela trata cada bloco como um trecho inline do formulário e o join extra não pagaria.


class AtivoMixin:
    """Cadastros nunca são apagados — são desativados."""

    ativo: Mapped[bool] = mapped_column(default=True, nullable=False, index=True)


class EmpresaScopedMixin:
    """Recorte multiempresa por linha, banco único."""

    @declared_attr
    @classmethod
    def empresa_id(cls) -> Mapped[uuid.UUID]:
        return mapped_column(
            Uuid, ForeignKey("empresa.id", ondelete="RESTRICT"), nullable=False, index=True
        )


class EmpresaOpcionalMixin:
    """Para registros que podem ser globais (empresa_id nulo) ou de uma empresa."""

    @declared_attr
    @classmethod
    def empresa_id(cls) -> Mapped[uuid.UUID | None]:
        return mapped_column(
            Uuid, ForeignKey("empresa.id", ondelete="RESTRICT"), nullable=True, index=True
        )


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
