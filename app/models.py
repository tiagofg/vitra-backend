"""Ponto único de importação de todos os modelos.

Alembic e os testes importam daqui: se um modelo não estiver nesta lista, ele não existe
para o autogenerate e a migração sai incompleta.
"""

from __future__ import annotations

from app.common.base_model import Base, ModeloBase
from app.core.numbering import ContadorDocumento, TipoDocumento
from app.modules.apoio.models import Banco, Cidade, DominioApoio, TabelaApoio, Uf
from app.modules.auth.models import (
    AutorizacaoDocumento,
    Grupo,
    Permissao,
    StatusAutorizacao,
    TipoAutorizacao,
    Usuario,
    grupo_permissao,
    usuario_grupo,
)
from app.modules.empresa.models import CentroCusto, Empresa, Filial

__all__ = [
    "AutorizacaoDocumento",
    "Banco",
    "Base",
    "CentroCusto",
    "Cidade",
    "ContadorDocumento",
    "DominioApoio",
    "Empresa",
    "Filial",
    "Grupo",
    "ModeloBase",
    "Permissao",
    "StatusAutorizacao",
    "TabelaApoio",
    "TipoAutorizacao",
    "TipoDocumento",
    "Uf",
    "Usuario",
    "grupo_permissao",
    "usuario_grupo",
]
