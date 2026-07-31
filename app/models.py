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
from app.modules.bakeoff.models import (
    Colaborador,
    ColaboradorEmpresa,
    PapelEmpresa,
    ProdutoEmpresa,
    ValorApoio,
    Variante,
)
from app.modules.bakeoff.models import Empresa as EmpresaBakeoff
from app.modules.bakeoff.models import Produto as ProdutoBakeoff
from app.modules.empresa.models import CentroCusto, Empresa, Filial

# Os apelidos `*Bakeoff` são deliberados: `tenants` e `empresa` são a mesma ideia em dois
# desenhos que coexistem por ora — o novo, por RLS, e o da S0, por coluna filtrada no
# serviço. Quando o retrabalho da S0 terminar, `Empresa` volta a ser um nome só.

__all__ = [
    "AutorizacaoDocumento",
    "Banco",
    "Base",
    "CentroCusto",
    "Cidade",
    "Colaborador",
    "ColaboradorEmpresa",
    "ContadorDocumento",
    "DominioApoio",
    "Empresa",
    "EmpresaBakeoff",
    "Filial",
    "Grupo",
    "ModeloBase",
    "PapelEmpresa",
    "Permissao",
    "ProdutoBakeoff",
    "ProdutoEmpresa",
    "StatusAutorizacao",
    "TabelaApoio",
    "TipoAutorizacao",
    "TipoDocumento",
    "Uf",
    "Usuario",
    "ValorApoio",
    "Variante",
    "grupo_permissao",
    "usuario_grupo",
]
