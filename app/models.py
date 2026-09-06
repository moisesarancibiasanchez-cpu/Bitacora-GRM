"""
app.models
Mapeo ORM (SQLAlchemy 2.0 con tipado Mapped[]) de las tablas definidas
en sql/01_schema.sql. Mantiene paridad 1:1 con el DDL.
"""
from __future__ import annotations
import enum
from datetime import datetime
from typing import List, Optional
from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Index,
    String, Text, UniqueConstraint, text,
)
from sqlalchemy.dialects.postgresql import CHAR
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


# Enums (espejo de los ENUM nativos de PostgreSQL)
class RolUsuario(str, enum.Enum):
    JEFE_PROYECTO = "JEFE_PROYECTO"
    QA = "QA"
    DESARROLLO = "DESARROLLO"
    NEGOCIO = "NEGOCIO"


class EstadoDespliegue(str, enum.Enum):
    PLANIFICADO = "PLANIFICADO"
    EN_CURSO = "EN_CURSO"
    COMPLETADO = "COMPLETADO"
    FALLIDO = "FALLIDO"
    CANCELADO = "CANCELADO"
    REVERTIDO = "REVERTIDO"


class TipoComponente(str, enum.Enum):
    SCRIPT_SQL = "SCRIPT_SQL"
    SCRIPT_SHELL = "SCRIPT_SHELL"
    BINARIO = "BINARIO"
    CONFIGURACION = "CONFIGURACION"
    CONTENEDOR = "CONTENEDOR"
    OTRO = "OTRO"


class SeveridadIncidencia(str, enum.Enum):
    BAJA = "BAJA"
    MEDIA = "MEDIA"
    ALTA = "ALTA"
    CRITICA = "CRITICA"


class EstadoIncidencia(str, enum.Enum):
    ABIERTA = "ABIERTA"
    EN_ANALISIS = "EN_ANALISIS"
    EN_RESOLUCION = "EN_RESOLUCION"
    RESUELTA = "RESUELTA"
    CERRADA = "CERRADA"
    CANCELADA = "CANCELADA"


class Usuario(Base):
    __tablename__ = "usuarios"
    __table_args__ = (
        Index("idx_usuarios_rol", "rol"),
        Index("idx_usuarios_activo", "activo"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    nombre: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(160), nullable=False, unique=True)
    rol: Mapped[RolUsuario] = mapped_column(
        nullable=False, server_default=text("'NEGOCIO'::rol_usuario"),
    )
    departamento: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("TRUE"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()"),
    )


class Despliegue(Base):
    __tablename__ = "despliegues"
    __table_args__ = (
        UniqueConstraint("codigo", name="uq_despliegues_codigo"),
        CheckConstraint(
            "solicitante_id <> aprobador_id",
            name="chk_despliegues_aprobador_distinto",
        ),
        CheckConstraint(
            "char_length(plan_rollback) >= 20",
            name="chk_despliegues_plan_rollback_min",
        ),
        Index("idx_despliegues_estado", "estado"),
        Index("idx_despliegues_fecha_prog", "fecha_programada"),
        Index("idx_despliegues_ambiente", "ambiente"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    codigo: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    titulo: Mapped[str] = mapped_column(String(200), nullable=False)
    descripcion: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    fecha_programada: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )
    estado: Mapped[EstadoDespliegue] = mapped_column(
        nullable=False, server_default=text("'PLANIFICADO'::estado_despliegue"),
    )
    plan_rollback: Mapped[str] = mapped_column(Text, nullable=False)
    ambiente: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default=text("'PRODUCCION'"),
    )
    ventana_mantenimiento: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)

    solicitante_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("usuarios.id", onupdate="CASCADE", ondelete="RESTRICT"),
        nullable=False,
    )
    aprobador_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("usuarios.id", onupdate="CASCADE", ondelete="RESTRICT"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()"),
    )

    componentes: Mapped[List["Componente"]] = relationship(
        back_populates="despliegue", cascade="all, delete-orphan", passive_deletes=True,
    )
    incidencias: Mapped[List["Incidencia"]] = relationship(
        back_populates="despliegue", passive_deletes=True,
    )


class Componente(Base):
    __tablename__ = "componentes"
    __table_args__ = (
        UniqueConstraint(
            "despliegue_id", "nombre", "version",
            name="uq_componentes_despliegue_nombre_version",
        ),
        Index("idx_componentes_tipo", "tipo"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    despliegue_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("despliegues.id", onupdate="CASCADE", ondelete="CASCADE"),
        nullable=False,
    )
    nombre: Mapped[str] = mapped_column(String(150), nullable=False)
    version: Mapped[str] = mapped_column(String(60), nullable=False)
    tipo: Mapped[TipoComponente] = mapped_column(nullable=False)
    ruta_almacenamiento: Mapped[str] = mapped_column(String(500), nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    notas: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()"),
    )

    despliegue: Mapped["Despliegue"] = relationship(back_populates="componentes")
    incidencias: Mapped[List["Incidencia"]] = relationship(
        back_populates="componente", passive_deletes=True,
    )


class Incidencia(Base):
    __tablename__ = "incidencias"
    __table_args__ = (
        UniqueConstraint("codigo", name="uq_incidencias_codigo"),
        Index("idx_incidencias_estado", "estado"),
        Index("idx_incidencias_severidad", "severidad"),
        Index("idx_incidencias_fecha_deteccion", "fecha_deteccion"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    codigo: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    titulo: Mapped[str] = mapped_column(String(200), nullable=False)
    descripcion: Mapped[str] = mapped_column(Text, nullable=False)
    severidad: Mapped[SeveridadIncidencia] = mapped_column(nullable=False)
    estado: Mapped[EstadoIncidencia] = mapped_column(
        nullable=False, server_default=text("'ABIERTA'::estado_incidencia"),
    )

    reportado_por_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("usuarios.id", onupdate="CASCADE", ondelete="RESTRICT"),
        nullable=False,
    )
    asignado_a_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("usuarios.id", onupdate="CASCADE", ondelete="SET NULL"),
        nullable=True,
    )
    despliegue_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("despliegues.id", onupdate="CASCADE", ondelete="SET NULL"),
        nullable=True,
    )
    componente_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("componentes.id", onupdate="CASCADE", ondelete="SET NULL"),
        nullable=True,
    )

    fecha_deteccion: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()"),
    )

    despliegue: Mapped[Optional["Despliegue"]] = relationship(back_populates="incidencias")
    componente: Mapped[Optional["Componente"]] = relationship(back_populates="incidencias")
