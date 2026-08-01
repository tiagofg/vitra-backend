from __future__ import annotations

import uuid
from datetime import date

from pydantic import BaseModel, Field, model_validator

from app.common.schemas import (
    ContatosCampos,
    CpfCnpj,
    EnderecoCampos,
    SaidaBase,
)
from app.modules.pessoas.models import TipoPessoa


def _conferir_documento_do_tipo_pessoa(
    tipo_pessoa: TipoPessoa | None, cpf_cnpj: str | None
) -> None:
    """`CpfCnpj` (`app/common/schemas.py`) aceita 11 **ou** 14 caracteres incondicionalmente
    — só quem sabe se é PF ou PJ pode dizer qual dos dois vale. Chamado do `model_validator`
    de cada schema que tem os dois campos juntos.

    Só valida quando os dois vêm juntos nesta requisição: num `PUT` parcial que manda só
    `cpf_cnpj` sem repetir `tipo_pessoa`, não dá para saber o tipo atual sem consultar o
    banco — validação cruzada de schema para quando o dado já existe fica para o serviço,
    se algum dia importar o suficiente para valer o consulta extra.
    """
    if tipo_pessoa is None or cpf_cnpj is None:
        return
    esperado, rotulo = (11, "CPF") if tipo_pessoa == TipoPessoa.fisica else (14, "CNPJ")
    if len(cpf_cnpj) != esperado:
        raise ValueError(
            f"tipo_pessoa '{tipo_pessoa.value}' espera {rotulo} ({esperado} caracteres), "
            f"recebeu {len(cpf_cnpj)}."
        )


# --- Cliente ------------------------------------------------------------------


class ClienteCriar(EnderecoCampos, ContatosCampos):
    """Sem `tenant_id`: a empresa vem da transação (RLS), não do corpo do pedido."""

    codigo: str = Field(min_length=1, max_length=20)
    nome: str = Field(min_length=1, max_length=160)
    tipo_pessoa: TipoPessoa
    cpf_cnpj: CpfCnpj | None = None
    rg_ie: str | None = Field(default=None, max_length=20)
    dt_nascimento: date | None = None
    profissao_id: uuid.UUID | None = None
    estado_civil_id: uuid.UUID | None = None
    raca_cor_id: uuid.UUID | None = None
    nacionalidade_id: uuid.UUID | None = None
    categoria_id: uuid.UUID | None = None
    observacao: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def _documento_bate_com_tipo_pessoa(self) -> ClienteCriar:
        _conferir_documento_do_tipo_pessoa(self.tipo_pessoa, self.cpf_cnpj)
        return self


class ClienteAtualizar(EnderecoCampos, ContatosCampos):
    codigo: str | None = Field(default=None, min_length=1, max_length=20)
    nome: str | None = Field(default=None, min_length=1, max_length=160)
    tipo_pessoa: TipoPessoa | None = None
    cpf_cnpj: CpfCnpj | None = None
    rg_ie: str | None = Field(default=None, max_length=20)
    dt_nascimento: date | None = None
    profissao_id: uuid.UUID | None = None
    estado_civil_id: uuid.UUID | None = None
    raca_cor_id: uuid.UUID | None = None
    nacionalidade_id: uuid.UUID | None = None
    categoria_id: uuid.UUID | None = None
    observacao: str | None = Field(default=None, max_length=2000)
    ativo: bool | None = None

    @model_validator(mode="after")
    def _documento_bate_com_tipo_pessoa(self) -> ClienteAtualizar:
        _conferir_documento_do_tipo_pessoa(self.tipo_pessoa, self.cpf_cnpj)
        return self


class ClienteSaida(SaidaBase, EnderecoCampos, ContatosCampos):
    id: uuid.UUID
    tenant_id: uuid.UUID
    codigo: str
    nome: str
    tipo_pessoa: TipoPessoa
    cpf_cnpj: str | None = None
    rg_ie: str | None = None
    dt_nascimento: date | None = None
    profissao_id: uuid.UUID | None = None
    estado_civil_id: uuid.UUID | None = None
    raca_cor_id: uuid.UUID | None = None
    nacionalidade_id: uuid.UUID | None = None
    categoria_id: uuid.UUID | None = None
    observacao: str | None = None
    ativo: bool


# --- Obra -----------------------------------------------------------------------


class ObraCriar(EnderecoCampos):
    """`cliente_id` vem do path (`/clientes/{cliente_id}/obras`), não do corpo."""

    nome: str = Field(min_length=1, max_length=160)


class ObraAtualizar(EnderecoCampos):
    nome: str | None = Field(default=None, min_length=1, max_length=160)
    ativo: bool | None = None


class ObraSaida(SaidaBase, EnderecoCampos):
    id: uuid.UUID
    tenant_id: uuid.UUID
    cliente_id: uuid.UUID
    nome: str
    ativo: bool


# --- Transportadora ---------------------------------------------------------------


class TransportadoraCriar(EnderecoCampos, ContatosCampos):
    codigo: str = Field(min_length=1, max_length=20)
    nome: str = Field(min_length=1, max_length=160)
    cnpj: CpfCnpj | None = None
    antt: str | None = Field(default=None, max_length=20)


class TransportadoraAtualizar(EnderecoCampos, ContatosCampos):
    codigo: str | None = Field(default=None, min_length=1, max_length=20)
    nome: str | None = Field(default=None, min_length=1, max_length=160)
    cnpj: CpfCnpj | None = None
    antt: str | None = Field(default=None, max_length=20)
    ativo: bool | None = None


class TransportadoraSaida(SaidaBase, EnderecoCampos, ContatosCampos):
    id: uuid.UUID
    tenant_id: uuid.UUID
    codigo: str
    nome: str
    cnpj: str | None = None
    antt: str | None = None
    ativo: bool


# --- Fornecedor -------------------------------------------------------------------


class FornecedorCriar(EnderecoCampos, ContatosCampos):
    codigo: str = Field(min_length=1, max_length=20)
    razao_social: str = Field(min_length=1, max_length=160)
    nome_fantasia: str | None = Field(default=None, max_length=160)
    cnpj: CpfCnpj | None = None
    transportadora_padrao_id: uuid.UUID | None = None


class FornecedorAtualizar(EnderecoCampos, ContatosCampos):
    codigo: str | None = Field(default=None, min_length=1, max_length=20)
    razao_social: str | None = Field(default=None, min_length=1, max_length=160)
    nome_fantasia: str | None = Field(default=None, max_length=160)
    cnpj: CpfCnpj | None = None
    transportadora_padrao_id: uuid.UUID | None = None
    ativo: bool | None = None


class FornecedorSaida(SaidaBase, EnderecoCampos, ContatosCampos):
    id: uuid.UUID
    tenant_id: uuid.UUID
    codigo: str
    razao_social: str
    nome_fantasia: str | None = None
    cnpj: str | None = None
    transportadora_padrao_id: uuid.UUID | None = None
    ativo: bool


class FornecedorEmpresaAbrir(BaseModel):
    """Abre uma nova vigência de empresa compradora — fecha a anterior (se houver) na
    mesma transação."""

    empresa_compradora_id: uuid.UUID
    vigencia_inicio: date
    motivo: str | None = Field(default=None, max_length=300)

    @model_validator(mode="after")
    def _vigencia_nao_pode_ser_futura_demais(self) -> FornecedorEmpresaAbrir:
        # Sem limite de passado (histórico legado pode migrar datas antigas), mas nenhuma
        # vigência nasce no futuro — a tela não previu isso e o serviço de resolução
        # (`empresa_compradora_em`) assume ordem cronológica real.
        if self.vigencia_inicio > date.today():
            raise ValueError("Vigência não pode começar no futuro.")
        return self


class FornecedorEmpresaSaida(SaidaBase):
    id: uuid.UUID
    tenant_id: uuid.UUID
    fornecedor_id: uuid.UUID
    empresa_compradora_id: uuid.UUID
    vigencia_inicio: date
    vigencia_fim: date | None = None
    motivo: str | None = None


# --- Profissional externo ----------------------------------------------------------


class ProfissionalExternoCriar(EnderecoCampos, ContatosCampos):
    codigo: str = Field(min_length=1, max_length=20)
    nome: str = Field(min_length=1, max_length=160)
    tipo_pessoa: TipoPessoa
    cpf_cnpj: CpfCnpj | None = None
    profissao_id: uuid.UUID | None = None
    crea_cau: str | None = Field(default=None, max_length=30)

    @model_validator(mode="after")
    def _documento_bate_com_tipo_pessoa(self) -> ProfissionalExternoCriar:
        _conferir_documento_do_tipo_pessoa(self.tipo_pessoa, self.cpf_cnpj)
        return self


class ProfissionalExternoAtualizar(EnderecoCampos, ContatosCampos):
    codigo: str | None = Field(default=None, min_length=1, max_length=20)
    nome: str | None = Field(default=None, min_length=1, max_length=160)
    tipo_pessoa: TipoPessoa | None = None
    cpf_cnpj: CpfCnpj | None = None
    profissao_id: uuid.UUID | None = None
    crea_cau: str | None = Field(default=None, max_length=30)
    ativo: bool | None = None

    @model_validator(mode="after")
    def _documento_bate_com_tipo_pessoa(self) -> ProfissionalExternoAtualizar:
        _conferir_documento_do_tipo_pessoa(self.tipo_pessoa, self.cpf_cnpj)
        return self


class ProfissionalExternoSaida(SaidaBase, EnderecoCampos, ContatosCampos):
    id: uuid.UUID
    tenant_id: uuid.UUID
    codigo: str
    nome: str
    tipo_pessoa: TipoPessoa
    cpf_cnpj: str | None = None
    profissao_id: uuid.UUID | None = None
    crea_cau: str | None = None
    ativo: bool


# --- Colaborador --------------------------------------------------------------------


class ColaboradorCriar(BaseModel):
    """Sem `tenant_id`: a empresa vem da transação. `employee_id` aponta para a identidade
    global — já criada via `/usuarios` (RH de quem ainda não existe como `Usuario` é fora
    de escopo desta fase)."""

    employee_id: uuid.UUID
    dt_admissao: date | None = None
    cargo_id: uuid.UUID | None = None
    setor_id: uuid.UUID | None = None
    vinculo_id: uuid.UUID | None = None
    grau_instrucao_id: uuid.UUID | None = None


class ColaboradorAtualizar(BaseModel):
    dt_admissao: date | None = None
    cargo_id: uuid.UUID | None = None
    setor_id: uuid.UUID | None = None
    vinculo_id: uuid.UUID | None = None
    grau_instrucao_id: uuid.UUID | None = None
    ativo: bool | None = None


class ColaboradorSaida(SaidaBase):
    id: uuid.UUID
    tenant_id: uuid.UUID
    employee_id: uuid.UUID
    dt_admissao: date | None = None
    cargo_id: uuid.UUID | None = None
    setor_id: uuid.UUID | None = None
    vinculo_id: uuid.UUID | None = None
    grau_instrucao_id: uuid.UUID | None = None
    ativo: bool
