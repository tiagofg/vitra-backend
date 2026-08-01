from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_JWT_SECRET_PADRAO = "troque-esta-chave-em-producao-0000000000000000"  # noqa: S105 — sentinela, não segredo


class Config(BaseSettings):
    """Configuração da aplicação. Prefixo VITRA_ em todas as variáveis."""

    model_config = SettingsConfigDict(
        env_prefix="VITRA_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    ambiente: Literal["dev", "teste", "producao"] = "dev"
    debug: bool = True

    # A aplicação conecta como `vitra_runtime`: não é dono das tabelas e não tem BYPASSRLS.
    # Conectar como dono ou superusuário faria o Postgres ignorar as políticas de RLS e o
    # recorte por empresa deixaria de existir — em silêncio, e só visível em produção.
    # Uma URL só. Havia uma segunda, `database_url_teste`, de quando a suíte rodava contra
    # um banco `vitra_teste` fixo declarado aqui. Agora cada execução sobe o próprio
    # Postgres descartável e injeta a URL pelo ambiente, então a segunda variável só podia
    # confundir: quem a preenchesse no `.env` veria o valor ser ignorado.
    database_url: str = "postgresql+asyncpg://vitra_runtime:vitra_runtime@localhost:5433/vitra"
    # Migração é a exceção: ela cria e altera tabela, então roda como dono. Nulo = usa a
    # mesma URL da aplicação, que é o que vale para os testes (lá o dono é o container).
    database_url_admin: str | None = None

    # Banco compartilhado do bake-off (`vitra_bakeoff`, Neon/São Paulo). As três stacks em
    # disputa apontam para ele ao mesmo tempo, então: **nada de DDL** e nada de escrita
    # automatizada. A suíte inteira roda local; contra o Neon vai só a listagem, que é
    # leitura. Um teste que suja o dado sujou para os outros dois times também.
    # Nulo por padrão — sem a variável no `.env`, o que depende dele é pulado.
    bakeoff_database_url: str | None = None
    db_echo: bool = False
    db_pool_size: int = 10
    db_max_overflow: int = 20

    jwt_secret: str = _JWT_SECRET_PADRAO
    # Só HMAC simétrico: são os três que `pyjwt` verifica sem chave pública separada, e é
    # o que `criar_token`/`ler_claims` esperam. String livre aceitaria um algoritmo que o
    # resto do código não sabe usar direito — melhor estourar na config do que em runtime.
    jwt_algoritmo: Literal["HS256", "HS384", "HS512"] = "HS256"
    jwt_access_ttl_minutos: int = 60
    jwt_refresh_ttl_dias: int = 7

    api_prefix: str = "/api/v1"
    cors_origens: list[str] = ["http://localhost:3000"]

    # Paginação padrão das listagens (app/core/listing.py)
    pagina_tamanho_padrao: int = 50
    pagina_tamanho_maximo: int = 200

    # O Neon suspende o banco após alguns minutos ocioso: a primeira conexão depois disso
    # leva 1–2 s. Não é queda — o pool só precisa tolerar a espera em vez de desistir.
    bakeoff_timeout_conexao: int = 15

    @property
    def url_migracao(self) -> str:
        """URL do **dono** das tabelas. Só o Alembic usa."""
        return self.database_url_admin or self.database_url

    @model_validator(mode="after")
    def _recusar_segredo_fraco_em_producao(self) -> Config:
        """Sobe com o segredo padrão em `producao` = qualquer um forja token para
        qualquer `sub`. Falhar no boot troca uma variável de ambiente esquecida por um
        crash imediato e legível, em vez de um furo silencioso descoberto meses depois."""
        if self.ambiente != "producao":
            return self
        if self.jwt_secret == _JWT_SECRET_PADRAO:
            raise ValueError(
                "VITRA_JWT_SECRET não pode ser o valor padrão em produção. "
                "Gere um com `openssl rand -hex 32`."
            )
        if len(self.jwt_secret) < 32:
            raise ValueError("VITRA_JWT_SECRET precisa ter pelo menos 32 caracteres em produção.")
        return self


@lru_cache
def get_config() -> Config:
    return Config()


config = get_config()
