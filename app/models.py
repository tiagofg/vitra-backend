"""Ponto único de importação de todos os modelos.

Alembic e os testes importam daqui: se um modelo não estiver nesta lista, ele não existe
para o autogenerate e a migração sai incompleta.
"""

from __future__ import annotations

from app.common.base_model import Base, ModeloBase, ModeloTenant
from app.core.audit import RegistroAuditoria
from app.core.numbering import ContadorDocumento, TipoDocumento
from app.modules.apoio.models import Banco, Cidade, DominioApoio, TabelaApoio, Uf
from app.modules.auth.models import (
    AutorizacaoDocumento,
    Grupo,
    Permissao,
    StatusAutorizacao,
    TipoAutorizacao,
    Usuario,
    VinculoEmpresa,
    grupo_permissao,
    usuario_grupo,
)
from app.modules.empresa.models import CentroCusto, Empresa, Filial
from app.modules.pessoas.models import (
    Cliente,
    Colaborador,
    Fornecedor,
    FornecedorEmpresa,
    Obra,
    ProfissionalExterno,
    Transportadora,
)
from app.modules.produtos.models import Produto, ProdutoEmpresa, Variante

# Toda tabela por empresa sob RLS, num lugar só. A migração de RLS **não** importa daqui —
# ela repete a lista em SQL cru, de propósito (migração é foto do schema num instante do
# tempo). Quem cruza as duas é `test_toda_tabela_com_tenant_id_tem_rls_forcado`, que
# descobre no catálogo do Postgres quem tem `tenant_id` e cobra que o conjunto bata com
# esta constante — divergir entre modelo e migração reprova, em vez de passar calado.
TABELAS_POR_EMPRESA: tuple[str, ...] = (
    Filial.__tablename__,
    CentroCusto.__tablename__,
    ContadorDocumento.__tablename__,
    VinculoEmpresa.__tablename__,
    Produto.__tablename__,
    Variante.__tablename__,
    ProdutoEmpresa.__tablename__,
    RegistroAuditoria.__tablename__,
    Cliente.__tablename__,
    Obra.__tablename__,
    Fornecedor.__tablename__,
    FornecedorEmpresa.__tablename__,
    Colaborador.__tablename__,
    ProfissionalExterno.__tablename__,
    Transportadora.__tablename__,
)

__all__ = [
    "AutorizacaoDocumento",
    "Banco",
    "Base",
    "CentroCusto",
    "Cidade",
    "Cliente",
    "Colaborador",
    "ContadorDocumento",
    "DominioApoio",
    "Empresa",
    "Filial",
    "Fornecedor",
    "FornecedorEmpresa",
    "Grupo",
    "ModeloBase",
    "ModeloTenant",
    "Obra",
    "Permissao",
    "Produto",
    "ProdutoEmpresa",
    "ProfissionalExterno",
    "RegistroAuditoria",
    "StatusAutorizacao",
    "TabelaApoio",
    "TipoAutorizacao",
    "TipoDocumento",
    "Transportadora",
    "Uf",
    "Usuario",
    "Variante",
    "VinculoEmpresa",
    "grupo_permissao",
    "usuario_grupo",
]
