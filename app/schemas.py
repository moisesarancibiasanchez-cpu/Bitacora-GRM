"""
app.schemas
Modelos Pydantic v2 para validación de payloads de entrada/salida.
Convención: CrearXxx (entrada) / XxxResponse (salida) / ActualizarXxx (PATCH).
"""
from __future__ import annotations
from datetime import datetime
from typing import Generic, List, Optional, TypeVar
from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator
from app.models import (
    EstadoDespliegue, EstadoIncidencia,
    RolUsuario, SeveridadIncidencia, TipoComponente,
)


# ===== USUARIOS =====
class UsuarioBase(BaseModel):
    nombre: str = Field(min_length=2, max_length=120)
    email: EmailStr
    rol: RolUsuario
    departamento: Optional[str] = Field(default=None, max_length=80)


class CrearUsuario(UsuarioBase):
    pass


class UsuarioResponse(UsuarioBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    activo: bool
    created_at: datetime
    updated_at: datetime


# ===== DESPLIEGUES =====
class DespliegueBase(BaseModel):
    codigo: str = Field(min_length=3, max_length=40, pattern=r"^[A-Z0-9_\-]+$")
    titulo: str = Field(min_length=5, max_length=200)
    descripcion: Optional[str] = None
    fecha_programada: datetime
    plan_rollback: str = Field(min_length=20)
    ambiente: str = Field(default="PRODUCCION", max_length=40)
    ventana_mantenimiento: Optional[str] = Field(default=None, max_length=40)


class CrearDespliegue(DespliegueBase):
    estado: EstadoDespliegue = EstadoDespliegue.PLANIFICADO
    aprobador_id: int = Field(gt=0)
    solicitante_id: int = Field(gt=0)

    @model_validator(mode="after")
    def _solicitante_diferente_de_aprobador(self) -> "CrearDespliegue":
        if self.solicitante_id == self.aprobador_id:
            raise ValueError("El aprobador no puede ser el mismo usuario que el solicitante.")
        return self


class DespliegueResponse(DespliegueBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    estado: EstadoDespliegue
    solicitante_id: int
    aprobador_id: int
    created_at: datetime
    updated_at: datetime


# ===== COMPONENTES =====
class ComponenteBase(BaseModel):
    nombre: str = Field(min_length=2, max_length=150)
    version: str = Field(min_length=1, max_length=60)
    tipo: TipoComponente
    ruta_almacenamiento: str = Field(min_length=1, max_length=500)
    checksum_sha256: str = Field(min_length=64, max_length=64, pattern=r"^[A-Fa-f0-9]{64}$")
    notas: Optional[str] = None


class CrearComponente(ComponenteBase):
    pass


class ComponenteResponse(ComponenteBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    despliegue_id: int
    created_at: datetime
    updated_at: datetime


# ===== INCIDENCIAS =====
class IncidenciaBase(BaseModel):
    codigo: str = Field(min_length=3, max_length=40, pattern=r"^[A-Z0-9_\-]+$")
    titulo: str = Field(min_length=5, max_length=200)
    descripcion: str = Field(min_length=10)
    severidad: SeveridadIncidencia
    asignado_a_id: Optional[int] = Field(default=None, gt=0)


class CrearIncidencia(IncidenciaBase):
    """
    El campo `reportado_por_id` ya NO viaja en el payload.
    El servidor lo toma de la cabecera `X-User-Id` (ver get_current_user en main.py).
    """
    despliegue_id: Optional[int] = Field(default=None, gt=0)
    componente_id: Optional[int] = Field(default=None, gt=0)

    @model_validator(mode="after")
    def _componente_requiere_despliegue(self) -> "CrearIncidencia":
        if self.componente_id is not None and self.despliegue_id is None:
            raise ValueError("Si se indica 'componente_id' también debe indicarse 'despliegue_id'.")
        return self


class ActualizarIncidencia(BaseModel):
    """
    PATCH semántico: todos los campos son opcionales. Solo se actualizan
    los campos provistos (no nulos). El servidor controla la transición
    de estado (no se permite 'saltar' a un estado final arbitrario).
    """
    titulo: Optional[str] = Field(default=None, min_length=5, max_length=200)
    descripcion: Optional[str] = Field(default=None, min_length=10)
    severidad: Optional[SeveridadIncidencia] = None
    estado: Optional[EstadoIncidencia] = None
    asignado_a_id: Optional[int] = Field(default=None, gt=0)
    despliegue_id: Optional[int] = Field(default=None, gt=0)
    componente_id: Optional[int] = Field(default=None, gt=0)

    def campos_a_actualizar(self) -> dict:
        """Devuelve solo los campos no nulos provistos."""
        return self.model_dump(exclude_unset=True, exclude_none=True)


class IncidenciaResponse(IncidenciaBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    estado: EstadoIncidencia
    reportado_por_id: int
    despliegue_id: Optional[int]
    componente_id: Optional[int]
    fecha_deteccion: datetime
    created_at: datetime
    updated_at: datetime


# ===== TRAZABILIDAD =====
class TrazabilidadDespliegue(BaseModel):
    """Vista 360°: cabecera + componentes + incidencias."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    codigo: str
    titulo: str
    estado: EstadoDespliegue
    fecha_programada: datetime
    ambiente: str
    solicitante_id: int
    aprobador_id: int
    total_componentes: int
    total_incidencias: int
    componentes: List[ComponenteResponse]
    incidencias: List[IncidenciaResponse]
    created_at: datetime
    updated_at: datetime


# ===== GENÉRICOS =====
class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "1.0.0"
    environment: str
    timestamp: datetime


# ===== PAGINACIÓN =====
T = TypeVar("T")


class PaginatedResponse(BaseModel, Generic[T]):
    """Envelope de paginación estándar para listados."""
    items: List[T]
    total: int
    page: int
    page_size: int
    total_pages: int

    @classmethod
    def build(cls, items: List[T], total: int, page: int, page_size: int) -> "PaginatedResponse[T]":
        total_pages = (total + page_size - 1) // page_size if page_size > 0 else 0
        return cls(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
        )
