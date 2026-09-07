"""
app.database
Configuración del motor de SQLAlchemy 2.0 y de la sesión transaccional.

- Engine con pool_pre_ping (detecta conexiones caídas).
- SessionLocal como factory.
- get_db() como generador apto para inyección de dependencias en FastAPI.

El engine se crea de forma **perezosa** (lazy): la primera vez que se necesita
un Session. Esto permite:
  - Importar la app sin tener el driver DB instalado (tests sin DB).
  - Arrancar el proceso aunque la DB esté momentáneamente caída.
  - Configurar el engine por-request en entornos de testing.
"""
from __future__ import annotations
from typing import Generator, Optional
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from app.config import get_settings


class Base(DeclarativeBase):
    """Base declarativa única para todos los modelos ORM."""


# --- Estado global (lazy) ---
_engine: Optional[Engine] = None
_SessionLocal: Optional[sessionmaker] = None


def _build_engine() -> Engine:
    s = get_settings()
    return create_engine(
        s.database_url,
        pool_pre_ping=True,
        pool_size=s.pool_size,
        max_overflow=s.max_overflow,
        future=True,
        echo=s.echo_sql,
    )


def get_engine() -> Engine:
    """Devuelve el engine, creándolo en la primera invocación."""
    global _engine
    if _engine is None:
        _engine = _build_engine()
    return _engine


def get_session_factory() -> sessionmaker:
    """Devuelve el factory de sesiones, creándolo en la primera invocación."""
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(
            bind=get_engine(),
            autocommit=False,
            autoflush=False,
            expire_on_commit=False,
            class_=Session,
        )
    return _SessionLocal


def reset_engine() -> None:
    """
    Resetea el engine y el factory. Útil en tests para forzar recreación
    tras cambiar variables de entorno (e.g. DATABASE_URL).
    """
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None


def get_db() -> Generator[Session, None, None]:
    """
    Inyección de dependencias: garantiza cierre y rollback en excepciones.
    Uso: `db: Session = Depends(get_db)`.
    """
    SessionLocal = get_session_factory()
    db: Session = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
