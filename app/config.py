"""
app.config
Configuración centralizada de Bitácora GRM.
Sigue el principio 12-Factor (variables de entorno).
"""
from functools import lru_cache
from typing import List
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Base de datos ---
    database_url: str = Field(
        default="postgresql+psycopg2://bitacora:bitacora@localhost:5432/bitacora_grm",
        description="DSN de SQLAlchemy.",
    )
    pool_size: int = Field(default=10, ge=1, le=50)
    max_overflow: int = Field(default=20, ge=0, le=100)
    echo_sql: bool = Field(default=False)

    # --- Logging / entorno ---
    log_level: str = Field(default="INFO")
    environment: str = Field(
        default="dev",
        description="Entorno de ejecución: dev | staging | prod",
    )

    # --- Seguridad ---
    # CORS_ORIGINS=https://app.banco.local,https://admin.banco.local
    #
    # Usamos `str` (no `List[str]`) a propósito: pydantic-settings intenta
    # parsear como JSON cualquier tipo complejo (List, Dict) ANTES de
    # invocar los field_validators, lo que rompe con valores como "*" o
    # "https://a,https://b". Manteniendo el campo como `str` evitamos ese
    # pre-procesado y la descomposición a lista se hace en
    # `cors_origins_list`. Esto nos independiza de la anotación
    # `NoDecode` (pydantic-settings >= 2.4) y funciona con cualquier
    # versión >= 2.0.
    cors_origins: str = Field(
        default="*",
        description=(
            "Orígenes CORS separados por coma. "
            "Use '*' para permitir cualquier origen (solo dev)."
        ),
    )
    auth_header_name: str = Field(
        default="X-User-Id",
        description="Cabecera HTTP que identifica al usuario actual.",
    )

    @field_validator("environment")
    @classmethod
    def _valida_ambiente(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in {"dev", "staging", "prod"}:
            raise ValueError("environment debe ser uno de: dev, staging, prod")
        return v

    @field_validator("cors_origins")
    @classmethod
    def _normaliza_cors(cls, v: str) -> str:
        """Normaliza el valor crudo. La descomposición a lista se hace en
        `cors_origins_list` (property) para evitar el JSON-decoding que
        pydantic-settings aplica a tipos complejos como List[str]."""
        if v is None:
            return "*"
        return v.strip()

    @property
    def cors_origins_list(self) -> List[str]:
        """
        Devuelve la lista de orígenes parseada desde `cors_origins`.
        - "" o None     -> ["*"]
        - "*"           -> ["*"]
        - "https://a,https://b" -> ["https://a", "https://b"]
        """
        raw = self.cors_origins
        if not raw or raw.strip() == "*":
            return ["*"]
        parsed = [o.strip() for o in raw.split(",") if o.strip()]
        return parsed or ["*"]

    @model_validator(mode="after")
    def _cors_segun_entorno(self) -> "Settings":
        """
        Política de CORS:
          - dev: si la lista está vacía o contiene '*', permitimos '*' por defecto.
          - staging/prod: exigimos al menos un origen EXPLÍCITO (no '*'), y
            los orígenes deben tener esquema http(s) y host.
        Esto evita que en prod un CORS_ORIGINS mal configurado deje la API
        abierta a cualquier origen.
        """
        env = self.environment
        origins = self.cors_origins_list

        if env in {"staging", "prod"}:
            if not origins or origins == ["*"]:
                raise ValueError(
                    f"En entorno '{env}' la variable CORS_ORIGINS es OBLIGATORIA "
                    f"y debe contener al menos un origen explícito "
                    f"(e.g. 'https://app.banco.local')."
                )
            for o in origins:
                if o == "*":
                    raise ValueError(
                        f"En entorno '{env}' CORS_ORIGINS no admite '*'. "
                        f"Especifique orígenes concretos."
                    )
                if not (o.startswith("http://") or o.startswith("https://")):
                    raise ValueError(
                        f"Origen CORS inválido '{o}'. Debe empezar por http:// o https://."
                    )
        # En 'dev' mantenemos el comportamiento permisivo por defecto.
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
