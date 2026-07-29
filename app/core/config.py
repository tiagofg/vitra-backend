from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


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

    database_url: str = "postgresql+asyncpg://vitra:vitra@localhost:5433/vitra"
    database_url_teste: str = "postgresql+asyncpg://vitra:vitra@localhost:5433/vitra_teste"
    db_echo: bool = False
    db_pool_size: int = 10
    db_max_overflow: int = 20

    jwt_secret: str = "troque-esta-chave-em-producao-0000000000000000"
    jwt_algoritmo: str = "HS256"
    jwt_access_ttl_minutos: int = 60
    jwt_refresh_ttl_dias: int = 7

    api_prefix: str = "/api/v1"
    cors_origens: list[str] = ["http://localhost:3000"]

    # Paginação padrão das listagens (app/core/listing.py)
    pagina_tamanho_padrao: int = 50
    pagina_tamanho_maximo: int = 200

    @property
    def url_efetiva(self) -> str:
        return self.database_url_teste if self.ambiente == "teste" else self.database_url


@lru_cache
def get_config() -> Config:
    return Config()


config = get_config()
