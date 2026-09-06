"""
app.main
Bitácora GRM — API FastAPI con los 4 endpoints críticos del enunciado:
    POST /despliegues/
    POST /despliegues/{despliegue_id}/componentes/
    POST /incidencias/
    GET  /trazabilidad/despliegues/{despliegue_id}

Más endpoints auxiliares: health, listados, /docs (Swagger).
"""
from __future__ import annotations
from datetime import datetime, timezone
from typing import List

from fastapi import Depends, FastAPI, HTTPException, Path, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.config import get_settings
from app.database import get_db
from app.models import Componente, Despliegue, Incidencia, Usuario
from app.schemas import (
    ComponenteResponse, CrearComponente, CrearDespliegue, CrearIncidencia,
    CrearUsuario, DespliegueResponse, HealthResponse, IncidenciaResponse,
    TrazabilidadDespliegue, UsuarioResponse,
)

settings = get_settings()
app = FastAPI(
    title="Bitácora GRM — API",
    description=(
        "Sistema de Gestión de Despliegues e Incidencias para entorno bancario. "
        "Trazabilidad, integridad y auditoría."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------- helpers ---------------------------
def _get_or_404(db: Session, model, obj_id: int, entity_name: str):
    instance = db.get(model, obj_id)
    if instance is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{entity_name} con id={obj_id} no existe.",
        )
    return instance


# =====================================================================
# 0 · Health
# =====================================================================
@app.get("/health", response_model=HealthResponse, tags=["Sistema"])
def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        version="1.0.0",
        timestamp=datetime.now(tz=timezone.utc),
    )


# =====================================================================
# 1 · POST /despliegues/
# =====================================================================
@app.post(
    "/despliegues/",
    response_model=DespliegueResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Despliegues"],
    summary="Registrar un nuevo pase a producción",
)
def crear_despliegue(
    payload: CrearDespliegue,
    db: Session = Depends(get_db),
) -> DespliegueResponse:
    _get_or_404(db, Usuario, payload.solicitante_id, "Usuario")
    _get_or_404(db, Usuario, payload.aprobador_id, "Usuario")

    d = Despliegue(
        codigo=payload.codigo,
        titulo=payload.titulo,
        descripcion=payload.descripcion,
        fecha_programada=payload.fecha_programada,
        estado=payload.estado,
        plan_rollback=payload.plan_rollback,
        ambiente=payload.ambiente,
        ventana_mantenimiento=payload.ventana_mantenimiento,
        solicitante_id=payload.solicitante_id,
        aprobador_id=payload.aprobador_id,
    )
    db.add(d)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Conflicto de integridad: {exc.orig}",
        ) from exc
    db.refresh(d)
    return DespliegueResponse.model_validate(d)


# =====================================================================
# 2 · POST /despliegues/{despliegue_id}/componentes/
# =====================================================================
@app.post(
    "/despliegues/{despliegue_id}/componentes/",
    response_model=ComponenteResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Componentes"],
    summary="Agregar artefacto técnico a un despliegue planificado",
)
def crear_componente(
    payload: CrearComponente,
    despliegue_id: int = Path(gt=0, description="ID del despliegue padre"),
    db: Session = Depends(get_db),
) -> ComponenteResponse:
    _get_or_404(db, Despliegue, despliegue_id, "Despliegue")

    c = Componente(
        despliegue_id=despliegue_id,
        nombre=payload.nombre,
        version=payload.version,
        tipo=payload.tipo,
        ruta_almacenamiento=payload.ruta_almacenamiento,
        checksum_sha256=payload.checksum_sha256.lower(),
        notas=payload.notas,
    )
    db.add(c)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Conflicto: ya existe un componente con ese nombre+versión en este despliegue.",
        ) from exc
    db.refresh(c)
    return ComponenteResponse.model_validate(c)


# =====================================================================
# 3 · POST /incidencias/
# =====================================================================
@app.post(
    "/incidencias/",
    response_model=IncidenciaResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Incidencias"],
    summary="Reportar un ticket y, opcionalmente, vincularlo a un despliegue",
)
def crear_incidencia(
    payload: CrearIncidencia,
    db: Session = Depends(get_db),
) -> IncidenciaResponse:
    _get_or_404(db, Usuario, payload.reportado_por_id, "Usuario")
    if payload.asignado_a_id is not None:
        _get_or_404(db, Usuario, payload.asignado_a_id, "Usuario")

    if payload.despliegue_id is not None:
        _get_or_404(db, Despliegue, payload.despliegue_id, "Despliegue")

    if payload.componente_id is not None:
        comp = _get_or_404(db, Componente, payload.componente_id, "Componente")
        # Regla: el componente debe pertenecer al despliegue declarado
        if comp.despliegue_id != payload.despliegue_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"El componente id={comp.id} pertenece al despliegue "
                    f"id={comp.despliegue_id}, no al id={payload.despliegue_id}."
                ),
            )

    i = Incidencia(
        codigo=payload.codigo,
        titulo=payload.titulo,
        descripcion=payload.descripcion,
        severidad=payload.severidad,
        estado="ABIERTA",
        reportado_por_id=payload.reportado_por_id,
        asignado_a_id=payload.asignado_a_id,
        despliegue_id=payload.despliegue_id,
        componente_id=payload.componente_id,
    )
    db.add(i)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Conflicto de integridad: {exc.orig}",
        ) from exc
    db.refresh(i)
    return IncidenciaResponse.model_validate(i)


# =====================================================================
# 4 · GET /trazabilidad/despliegues/{despliegue_id}
# =====================================================================
@app.get(
    "/trazabilidad/despliegues/{despliegue_id}",
    response_model=TrazabilidadDespliegue,
    tags=["Trazabilidad"],
    summary="Estado del despliegue + componentes + incidencias asociadas",
)
def trazabilidad_despliegue(
    despliegue_id: int = Path(gt=0),
    db: Session = Depends(get_db),
) -> TrazabilidadDespliegue:
    stmt = (
        select(Despliegue)
        .where(Despliegue.id == despliegue_id)
        .options(
            selectinload(Despliegue.componentes),
            selectinload(Despliegue.incidencias),
        )
    )
    d = db.execute(stmt).scalar_one_or_none()
    if d is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Despliegue con id={despliegue_id} no existe.",
        )

    total_componentes = db.execute(
        select(func.count(Componente.id)).where(Componente.despliegue_id == despliegue_id)
    ).scalar_one()
    total_incidencias = db.execute(
        select(func.count(Incidencia.id)).where(Incidencia.despliegue_id == despliegue_id)
    ).scalar_one()

    return TrazabilidadDespliegue(
        id=d.id,
        codigo=d.codigo,
        titulo=d.titulo,
        estado=d.estado,
        fecha_programada=d.fecha_programada,
        ambiente=d.ambiente,
        solicitante_id=d.solicitante_id,
        aprobador_id=d.aprobador_id,
        total_componentes=total_componentes,
        total_incidencias=total_incidencias,
        componentes=[ComponenteResponse.model_validate(c) for c in d.componentes],
        incidencias=[IncidenciaResponse.model_validate(i) for i in d.incidencias],
        created_at=d.created_at,
        updated_at=d.updated_at,
    )


# =====================================================================
# Endpoints auxiliares
# =====================================================================
@app.post(
    "/usuarios/",
    response_model=UsuarioResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Usuarios"],
    summary="Registrar un nuevo usuario (Jefe de Proyecto, QA, Desarrollo, Negocio)",
)
def crear_usuario(payload: CrearUsuario, db: Session = Depends(get_db)) -> UsuarioResponse:
    u = Usuario(
        nombre=payload.nombre,
        email=payload.email,
        rol=payload.rol,
        departamento=payload.departamento,
    )
    db.add(u)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Email duplicado: {exc.orig}",
        ) from exc
    db.refresh(u)
    return UsuarioResponse.model_validate(u)


@app.get("/usuarios/", response_model=List[UsuarioResponse], tags=["Usuarios"])
def listar_usuarios(
    skip: int = 0, limit: int = 50, db: Session = Depends(get_db),
) -> List[UsuarioResponse]:
    limit = min(max(limit, 1), 200)
    rows = db.execute(
        select(Usuario).order_by(Usuario.id.asc()).offset(skip).limit(limit)
    ).scalars().all()
    return [UsuarioResponse.model_validate(u) for u in rows]


@app.get("/despliegues/", response_model=List[DespliegueResponse], tags=["Despliegues"])
def listar_despliegues(
    skip: int = 0, limit: int = 50, db: Session = Depends(get_db),
) -> List[DespliegueResponse]:
    limit = min(max(limit, 1), 200)
    rows = db.execute(
        select(Despliegue).order_by(Despliegue.id.desc()).offset(skip).limit(limit)
    ).scalars().all()
    return [DespliegueResponse.model_validate(d) for d in rows]


@app.get("/incidencias/", response_model=List[IncidenciaResponse], tags=["Incidencias"])
def listar_incidencias(
    skip: int = 0, limit: int = 50, db: Session = Depends(get_db),
) -> List[IncidenciaResponse]:
    limit = min(max(limit, 1), 200)
    rows = db.execute(
        select(Incidencia).order_by(Incidencia.id.desc()).offset(skip).limit(limit)
    ).scalars().all()
    return [IncidenciaResponse.model_validate(i) for i in rows]


# =====================================================================
# Arranque
# =====================================================================
if __name__ == "__main__":  # pragma: no cover
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_level=settings.log_level.lower(),
    )
