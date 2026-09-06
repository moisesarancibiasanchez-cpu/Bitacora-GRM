"""
app.database
Configuración del motor de SQLAlchemy 2.0 y de la sesión transaccional.
- Engine con pool_pre_ping (detecta conexiones caídas).
- SessionLocal como factory.
- get_db() como generador apto para inyección de dependencias en FastAPI.
"""
from typing import Generator
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from app.config import get_settings


class Base(DeclarativeBase):
    """Base declarativa única para todos los modelos ORM."""


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


engine: Engine = _build_engine()
SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
    class_=Session,
)


def get_db() -> Generator[Session, None, None]:
    """Inyección de dependencias: garantiza cierre y rollback en excepciones."""
    db: Session = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
