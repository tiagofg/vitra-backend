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
from app.modules.estoque.models import (
    LocalEstoque,
    MotivoMovimento,
    MovimentoEstoque,
    OrigemMovimento,
    SaldoEstoque,
    TipoLocalEstoque,
)
from app.modules.pessoas.models import (
    Colaborador,
    FornecedorEmpresa,
    Obra,
    Parceiro,
    ParceiroEmpresa,
    TipoPessoa,
    Transportadora,
)
from app.modules.produtos.models import (
    GrupoRelacionado,
    ItemRelacionado,
    Produto,
    ProdutoFornecedor,
    Variante,
    VarianteEmpresa,
)
from app.modules.vendas.models import (
    ModoDesconto,
    Orcamento,
    OrcamentoAmbiente,
    OrcamentoItem,
    StatusOrcamento,
)

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
    VarianteEmpresa.__tablename__,
    RegistroAuditoria.__tablename__,
    Parceiro.__tablename__,
    ParceiroEmpresa.__tablename__,
    Obra.__tablename__,
    FornecedorEmpresa.__tablename__,
    Colaborador.__tablename__,
    Transportadora.__tablename__,
    ProdutoFornecedor.__tablename__,
    GrupoRelacionado.__tablename__,
    ItemRelacionado.__tablename__,
    LocalEstoque.__tablename__,
    SaldoEstoque.__tablename__,
    MovimentoEstoque.__tablename__,
    Orcamento.__tablename__,
    OrcamentoAmbiente.__tablename__,
    OrcamentoItem.__tablename__,
)

__all__ = [
    "AutorizacaoDocumento",
    "Banco",
    "Base",
    "CentroCusto",
    "Cidade",
    "Colaborador",
    "ContadorDocumento",
    "DominioApoio",
    "Empresa",
    "Filial",
    "FornecedorEmpresa",
    "Grupo",
    "GrupoRelacionado",
    "ItemRelacionado",
    "LocalEstoque",
    "ModeloBase",
    "ModeloTenant",
    "ModoDesconto",
    "MotivoMovimento",
    "MovimentoEstoque",
    "Obra",
    "Orcamento",
    "OrcamentoAmbiente",
    "OrcamentoItem",
    "OrigemMovimento",
    "Parceiro",
    "ParceiroEmpresa",
    "Permissao",
    "Produto",
    "ProdutoFornecedor",
    "RegistroAuditoria",
    "SaldoEstoque",
    "StatusAutorizacao",
    "StatusOrcamento",
    "TabelaApoio",
    "TipoAutorizacao",
    "TipoDocumento",
    "TipoLocalEstoque",
    "TipoPessoa",
    "Transportadora",
    "Uf",
    "Usuario",
    "Variante",
    "VarianteEmpresa",
    "VinculoEmpresa",
    "grupo_permissao",
    "usuario_grupo",
]
