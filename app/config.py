"""
app.config
Configuración centralizada de Bitácora GRM.
Sigue el principio 12-Factor (variables de entorno).
"""
from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    database_url: str = Field(
        default="postgresql+psycopg2://bitacora:bitacora@localhost:5432/bitacora_grm",
        description="DSN de SQLAlchemy.",
    )
    log_level: str = Field(default="INFO")
    pool_size: int = Field(default=10, ge=1, le=50)
    max_overflow: int = Field(default=20, ge=0, le=100)
    echo_sql: bool = Field(default=False)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
