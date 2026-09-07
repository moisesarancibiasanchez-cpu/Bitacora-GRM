"""
app.main
Bitácora GRM — API FastAPI.

Endpoints críticos del enunciado:
    POST /despliegues/
    POST /despliegues/{despliegue_id}/componentes/
    POST /incidencias/
    GET  /trazabilidad/despliegues/{despliegue_id}

Mejoras Tier 1 (v1.1.0):
    - Autenticación ligera por cabecera X-User-Id (inyección de dependencias).
    - `reportado_por_id` se toma del header, no del body.
    - PATCH /incidencias/{id} con actualización parcial + state machine.
    - Filtros (validados con el Enum) y paginación en listados.
    - CORS restrictivo por entorno.
    - Helper `require_role()` para autorización por rol.
"""
from __future__ import annotations
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Path, Query, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from sqlalchemy import and_, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.config import get_settings
from app.database import get_db
from app.models import (
    Componente, Despliegue, EstadoDespliegue, EstadoIncidencia,
    Incidencia, RolUsuario, SeveridadIncidencia, Usuario,
)
from app.schemas import (
    ActualizarIncidencia, ComponenteResponse, CrearComponente,
    CrearDespliegue, CrearIncidencia, CrearUsuario, DespliegueResponse,
    HealthResponse, IncidenciaResponse, PaginatedResponse,
    TrazabilidadDespliegue, UsuarioResponse,
)

settings = get_settings()

# Estados terminales de una incidencia: no admiten transiciones ni edición.
_INCIDENCIA_ESTADOS_TERMINALES = frozenset({EstadoIncidencia.CERRADA, EstadoIncidencia.CANCELADA})

# State machine: transiciones válidas de Incidencia.estado.
# Formato: estado_actual -> {estados_permitidos}
_TRANSICIONES_INCIDENCIA: dict[EstadoIncidencia, frozenset[EstadoIncidencia]] = {
    EstadoIncidencia.ABIERTA:      frozenset({EstadoIncidencia.EN_ANALISIS, EstadoIncidencia.CANCELADA}),
    EstadoIncidencia.EN_ANALISIS:  frozenset({EstadoIncidencia.EN_RESOLUCION, EstadoIncidencia.CANCELADA}),
    EstadoIncidencia.EN_RESOLUCION: frozenset({EstadoIncidencia.RESUELTA, EstadoIncidencia.CANCELADA}),
    EstadoIncidencia.RESUELTA:     frozenset({EstadoIncidencia.CERRADA}),
    EstadoIncidencia.CERRADA:      frozenset(),  # terminal
    EstadoIncidencia.CANCELADA:    frozenset(),  # terminal
}

app = FastAPI(
    title="Bitácora GRM — API",
    description=(
        "Sistema de Gestión de Despliegues e Incidencias para entorno bancario. "
        "Trazabilidad, integridad y auditoría."
    ),
    version="1.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# CORS: la política se valida en app.config.Settings._cors_segun_entorno.
# - dev: si CORS_ORIGINS no se define o vale '*', se acepta cualquier origen.
# - staging/prod: se exige al menos un origen http(s) explícito (nunca '*').
# `cors_origins_list` es la propiedad de Settings que parsea el string
# crudo `cors_origins` (e.g. "https://a,https://b") en una lista.
cors_allow_origins = (
    ["*"] if settings.environment == "dev" else settings.cors_origins_list
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_allow_origins,
    allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
    allow_headers=["*"],
    allow_credentials=False,
)

# --------------------------- startup log ---------------------------
# Logueamos el entorno al arrancar para que sea muy visible en los
# logs de Railway si por accidente se está ejecutando como "dev" en
# un entorno de producción.
logger = logging.getLogger("bitacora_grm.startup")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(settings.log_level.upper() if hasattr(settings, "log_level") else "INFO")
logger.info(
    "Bitácora GRM v%s arrancando en entorno=%s | CORS=%s",
    app.version,
    settings.environment,
    cors_allow_origins,
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


def _validar_transicion_estado(
    actual: EstadoIncidencia, nuevo: EstadoIncidencia
) -> None:
    """Verifica la transición de estado permitida por la state machine."""
    if nuevo == actual:
        return  # idempotente
    if actual in _INCIDENCIA_ESTADOS_TERMINALES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"La incidencia está en estado terminal '{actual.value}' "
                f"y no admite transiciones."
            ),
        )
    permitidos = _TRANSICIONES_INCIDENCIA.get(actual, frozenset())
    if nuevo not in permitidos:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Transición de estado inválida: '{actual.value}' → '{nuevo.value}'. "
                f"Estados permitidos desde '{actual.value}': "
                f"{sorted(s.value for s in permitidos) or '(ninguno)'}."
            ),
        )


# =====================================================================
# Seguridad: autenticación ligera + autorización por rol
# =====================================================================
def get_current_user(
    db: Session = Depends(get_db),
    x_user_id: Optional[str] = Header(default=None, alias="X-User-Id"),
) -> Usuario:
    """
    Resuelve el usuario actual desde la cabecera `X-User-Id`.
    Si la cabecera falta, no es numérica o es inválida → 401.
    Si el usuario no existe o está inactivo → 401.

    Esto es deliberadamente "ligero": se asume un gateway upstream
    (e.g. SSO corporativo) que ya validó la identidad. Aquí solo
    se traduce la identidad a un usuario interno y se valida su estado.

    Nota: usamos `str` y parseamos manualmente para que cualquier
    valor mal formado (no numérico, negativo, etc.) devuelva SIEMPRE
    401 (auth) y nunca 422 (validation), evitando filtrar info del
    tipo esperado al cliente.
    """
    if x_user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                f"Autenticación requerida. Envíe la cabecera '{settings.auth_header_name}' "
                f"con el id del usuario."
            ),
            headers={"WWW-Authenticate": f"{settings.auth_header_name}"},
        )
    try:
        user_id = int(x_user_id)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                f"Valor inválido para la cabecera '{settings.auth_header_name}'. "
                f"Debe ser un entero positivo."
            ),
            headers={"WWW-Authenticate": f"{settings.auth_header_name}"},
        )
    if user_id <= 0:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                f"Valor inválido para la cabecera '{settings.auth_header_name}'. "
                f"Debe ser un entero positivo."
            ),
            headers={"WWW-Authenticate": f"{settings.auth_header_name}"},
        )
    user = db.get(Usuario, user_id)
    if user is None or not user.activo:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario no encontrado o inactivo.",
        )
    return user


def require_role(*roles: RolUsuario):
    """
    Fábrica de dependencias para autorización por rol.

    Uso:
        _: Usuario = Depends(require_role(RolUsuario.QA, RolUsuario.JEFE_PROYECTO))

    El `_` indica que no necesitamos el objeto Usuario en el handler, solo
    la verificación. Si necesitas el usuario, asígnalo a una variable.
    """
    allowed = frozenset(roles)

    def _checker(current_user: Usuario = Depends(get_current_user)) -> Usuario:
        if current_user.rol not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Operación no permitida para el rol '{current_user.rol.value}'. "
                    f"Roles permitidos: {sorted(r.value for r in allowed)}."
                ),
            )
        return current_user

    return _checker


# =====================================================================
# 0 · Raíz y Health
# =====================================================================
_HTML_ENV_BADGE_COLORS = {
    "dev": ("#f59e0b", "#7c2d12"),     # ámbar
    "staging": ("#3b82f6", "#1e3a8a"), # azul
    "prod": ("#10b981", "#064e3b"),    # verde
}


@app.get("/", response_class=HTMLResponse, tags=["Sistema"], summary="Landing page del servicio")
def root() -> HTMLResponse:
    """
    Landing HTML del servicio. Sirve como punto de entrada amigable
    cuando alguien navega a la URL raíz del despliegue.

    Para consumir la información programáticamente, usar /openapi.json
    o /health (que devuelven JSON).
    """
    env = settings.environment
    badge_bg, badge_fg = _HTML_ENV_BADGE_COLORS.get(env, ("#64748b", "#0f172a"))
    now = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    version = app.version

    html = f"""<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="description" content="Bitácora GRM — Sistema de Gestión de Despliegues e Incidencias para entorno bancario.">
    <title>Bitácora GRM — API</title>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        :root {{
            --bg: #f8fafc;
            --surface: #ffffff;
            --border: #e2e8f0;
            --text: #0f172a;
            --text-muted: #475569;
            --primary: #0a2540;
            --primary-hover: #1e3a5f;
            --accent: #2563eb;
            --accent-hover: #1d4ed8;
            --success: #10b981;
            --success-bg: #d1fae5;
            --code-bg: #0f172a;
            --code-fg: #e2e8f0;
            --shadow: 0 1px 3px 0 rgba(0,0,0,.08), 0 1px 2px -1px rgba(0,0,0,.04);
            --shadow-lg: 0 10px 25px -5px rgba(0,0,0,.08), 0 8px 10px -6px rgba(0,0,0,.04);
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
                         "Helvetica Neue", Arial, sans-serif;
            background: var(--bg);
            color: var(--text);
            line-height: 1.6;
            min-height: 100vh;
            padding: 2rem 1rem;
        }}
        .container {{ max-width: 1100px; margin: 0 auto; }}
        header {{
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 1.75rem 2rem;
            box-shadow: var(--shadow);
            margin-bottom: 1.5rem;
            display: flex;
            align-items: center;
            justify-content: space-between;
            flex-wrap: wrap;
            gap: 1rem;
        }}
        .brand {{ display: flex; align-items: center; gap: 1rem; }}
        .brand-icon {{
            width: 48px; height: 48px;
            background: var(--primary);
            border-radius: 10px;
            display: flex; align-items: center; justify-content: center;
            color: #fff;
        }}
        .brand h1 {{
            font-size: 1.5rem;
            color: var(--primary);
            font-weight: 700;
            letter-spacing: -0.01em;
        }}
        .brand .tagline {{
            font-size: 0.875rem;
            color: var(--text-muted);
        }}
        .badges {{ display: flex; gap: 0.5rem; flex-wrap: wrap; }}
        .badge {{
            display: inline-flex; align-items: center;
            padding: 0.375rem 0.75rem;
            font-size: 0.75rem;
            font-weight: 600;
            border-radius: 999px;
            background: var(--border);
            color: var(--text);
            font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
        }}
        .badge.version {{ background: #e0e7ff; color: #3730a3; }}
        .badge.env {{ background: {badge_bg}; color: {badge_fg}; }}
        section {{
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 1.5rem 2rem;
            box-shadow: var(--shadow);
            margin-bottom: 1.5rem;
        }}
        section h2 {{
            font-size: 0.8125rem;
            font-weight: 600;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 0.05em;
            margin-bottom: 1rem;
        }}
        .status-row {{
            display: flex;
            align-items: center;
            gap: 0.75rem;
        }}
        .status-dot {{
            width: 12px; height: 12px;
            background: var(--success);
            border-radius: 50%;
            box-shadow: 0 0 0 4px var(--success-bg);
            animation: pulse 2s infinite;
        }}
        @keyframes pulse {{
            0%, 100% {{ box-shadow: 0 0 0 4px var(--success-bg); }}
            50%      {{ box-shadow: 0 0 0 8px rgba(16,185,129,0); }}
        }}
        .status-text {{ font-weight: 600; color: var(--text); }}
        .status-sub {{ color: var(--text-muted); font-size: 0.875rem; }}
        .grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            gap: 1rem;
        }}
        .link-card {{
            display: flex; align-items: center; gap: 0.75rem;
            padding: 1rem 1.25rem;
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 10px;
            text-decoration: none;
            color: inherit;
            transition: all .15s ease;
        }}
        .link-card:hover {{
            border-color: var(--accent);
            background: #f1f5f9;
            transform: translateY(-1px);
            box-shadow: var(--shadow-lg);
        }}
        .link-card svg {{ flex-shrink: 0; color: var(--accent); }}
        .link-card .label {{ font-weight: 600; color: var(--text); }}
        .link-card .path {{
            font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
            font-size: 0.8125rem;
            color: var(--text-muted);
        }}
        .endpoint-list {{ list-style: none; display: grid; gap: 0.5rem; }}
        .endpoint-row {{
            display: flex; align-items: center; gap: 0.75rem;
            padding: 0.625rem 0.875rem;
            background: #f8fafc;
            border: 1px solid var(--border);
            border-radius: 8px;
            font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
            font-size: 0.8125rem;
        }}
        .method {{
            display: inline-block;
            min-width: 56px;
            padding: 0.125rem 0.5rem;
            border-radius: 4px;
            font-weight: 700;
            font-size: 0.6875rem;
            text-align: center;
            color: #fff;
        }}
        .method.GET    {{ background: #0ea5e9; }}
        .method.POST   {{ background: #10b981; }}
        .method.PATCH  {{ background: #f59e0b; }}
        .method.DELETE {{ background: #ef4444; }}
        .endpoint-path {{ color: var(--text); font-weight: 500; }}
        .endpoint-desc {{ color: var(--text-muted); font-size: 0.75rem; margin-left: auto; }}
        details {{ margin-top: 1rem; }}
        details summary {{
            cursor: pointer; user-select: none;
            color: var(--accent);
            font-size: 0.875rem;
            font-weight: 500;
        }}
        details summary:hover {{ text-decoration: underline; }}
        pre.code {{
            margin-top: 0.75rem;
            background: var(--code-bg);
            color: var(--code-fg);
            padding: 1rem;
            border-radius: 8px;
            overflow-x: auto;
            font-size: 0.8125rem;
            line-height: 1.5;
        }}
        footer {{
            text-align: center;
            color: var(--text-muted);
            font-size: 0.8125rem;
            padding: 1rem 0 0;
        }}
        footer code {{
            font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
            background: var(--border);
            padding: 0.125rem 0.375rem;
            border-radius: 4px;
        }}
        @media (max-width: 640px) {{
            body {{ padding: 1rem 0.75rem; }}
            header, section {{ padding: 1.25rem 1rem; }}
            .brand h1 {{ font-size: 1.25rem; }}
            .endpoint-desc {{ display: none; }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <div class="brand">
                <div class="brand-icon" aria-hidden="true">
                    <svg width="24" height="24" viewBox="0 0 24 24" fill="none"
                         stroke="currentColor" stroke-width="2"
                         stroke-linecap="round" stroke-linejoin="round">
                        <rect x="3" y="3" width="18" height="18" rx="2"/>
                        <path d="M8 8h8M8 12h8M8 16h5"/>
                    </svg>
                </div>
                <div>
                    <h1>Bitácora GRM</h1>
                    <p class="tagline">API de Gestión de Despliegues e Incidencias</p>
                </div>
            </div>
            <div class="badges">
                <span class="badge version">v{version}</span>
                <span class="badge env">{env.upper()}</span>
            </div>
        </header>

        <section>
            <h2>Estado del servicio</h2>
            <div class="status-row">
                <span class="status-dot" aria-hidden="true"></span>
                <div>
                    <div class="status-text">Operacional</div>
                    <div class="status-sub">API respondiendo · última verificación {now}</div>
                </div>
            </div>
        </section>

        <section>
            <h2>Acceso rápido</h2>
            <div class="grid">
                <a href="/docs" class="link-card">
                    <svg width="22" height="22" viewBox="0 0 24 24" fill="none"
                         stroke="currentColor" stroke-width="2"
                         stroke-linecap="round" stroke-linejoin="round">
                        <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/>
                        <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/>
                    </svg>
                    <div>
                        <div class="label">Swagger UI</div>
                        <div class="path">/docs</div>
                    </div>
                </a>
                <a href="/redoc" class="link-card">
                    <svg width="22" height="22" viewBox="0 0 24 24" fill="none"
                         stroke="currentColor" stroke-width="2"
                         stroke-linecap="round" stroke-linejoin="round">
                        <path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/>
                        <path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/>
                    </svg>
                    <div>
                        <div class="label">ReDoc</div>
                        <div class="path">/redoc</div>
                    </div>
                </a>
                <a href="/openapi.json" class="link-card">
                    <svg width="22" height="22" viewBox="0 0 24 24" fill="none"
                         stroke="currentColor" stroke-width="2"
                         stroke-linecap="round" stroke-linejoin="round">
                        <polyline points="16 18 22 12 16 6"/>
                        <polyline points="8 6 2 12 8 18"/>
                    </svg>
                    <div>
                        <div class="label">Esquema OpenAPI</div>
                        <div class="path">/openapi.json</div>
                    </div>
                </a>
                <a href="/health" class="link-card">
                    <svg width="22" height="22" viewBox="0 0 24 24" fill="none"
                         stroke="currentColor" stroke-width="2"
                         stroke-linecap="round" stroke-linejoin="round">
                        <path d="M22 12h-4l-3 9L9 3l-3 9H2"/>
                    </svg>
                    <div>
                        <div class="label">Health Check</div>
                        <div class="path">/health</div>
                    </div>
                </a>
            </div>
        </section>

        <section>
            <h2>Endpoints principales</h2>
            <ul class="endpoint-list">
                <li class="endpoint-row">
                    <span class="method POST">POST</span>
                    <span class="endpoint-path">/despliegues/</span>
                    <span class="endpoint-desc">Registrar pase a producción</span>
                </li>
                <li class="endpoint-row">
                    <span class="method POST">POST</span>
                    <span class="endpoint-path">/despliegues/{{'{'}}id{{'}'}}/componentes/</span>
                    <span class="endpoint-desc">Agregar artefacto técnico</span>
                </li>
                <li class="endpoint-row">
                    <span class="method POST">POST</span>
                    <span class="endpoint-path">/incidencias/</span>
                    <span class="endpoint-desc">Reportar ticket</span>
                </li>
                <li class="endpoint-row">
                    <span class="method PATCH">PATCH</span>
                    <span class="endpoint-path">/incidencias/{{'{'}}id{{'}'}}</span>
                    <span class="endpoint-desc">Actualizar incidencia</span>
                </li>
                <li class="endpoint-row">
                    <span class="method GET">GET</span>
                    <span class="endpoint-path">/trazabilidad/despliegues/{{'{'}}id{{'}'}}</span>
                    <span class="endpoint-desc">Trazabilidad de despliegue</span>
                </li>
                <li class="endpoint-row">
                    <span class="method GET">GET</span>
                    <span class="endpoint-path">/usuarios/</span>
                    <span class="endpoint-desc">Listar usuarios</span>
                </li>
            </ul>
            <details>
                <summary>¿Cómo autenticarme?</summary>
                <pre class="code">curl -H "X-User-Id: 1" \\
     https://&lt;tu-dominio&gt;.up.railway.app/incidencias/</pre>
            </details>
        </section>

        <footer>
            Bitácora GRM <code>v{version}</code> · Entorno <code>{env}</code> ·
            FastAPI · SQLAlchemy · PostgreSQL
        </footer>
    </div>
</body>
</html>"""
    return HTMLResponse(content=html)


@app.get("/health", response_model=HealthResponse, tags=["Sistema"])
def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        version=app.version,
        environment=settings.environment,
        timestamp=datetime.now(tz=timezone.utc),
    )


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> Response:
    """
    Favicon vacío para evitar el 404 que los navegadores disparan
    automáticamente al cargar cualquier página de la API.
    """
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# =====================================================================
# 1 · POST /despliegues/  (rol JEFE_PROYECTO o DESARROLLO)
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
    _: Usuario = Depends(require_role(RolUsuario.JEFE_PROYECTO, RolUsuario.DESARROLLO)),
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
            detail="Conflicto: ya existe un despliegue con ese código o las FK son inválidas.",
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
    _: Usuario = Depends(require_role(RolUsuario.JEFE_PROYECTO, RolUsuario.DESARROLLO)),
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
# 3 · POST /incidencias/  (cualquier usuario autenticado puede reportar)
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
    current_user: Usuario = Depends(get_current_user),
) -> IncidenciaResponse:
    if payload.asignado_a_id is not None:
        _get_or_404(db, Usuario, payload.asignado_a_id, "Usuario")

    if payload.despliegue_id is not None:
        _get_or_404(db, Despliegue, payload.despliegue_id, "Despliegue")

    if payload.componente_id is not None:
        comp = _get_or_404(db, Componente, payload.componente_id, "Componente")
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
        estado=EstadoIncidencia.ABIERTA,
        reportado_por_id=current_user.id,  # tomado del header, no del body
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
            detail="Conflicto: ya existe una incidencia con ese código.",
        ) from exc
    db.refresh(i)
    return IncidenciaResponse.model_validate(i)


# =====================================================================
# 3.1 · PATCH /incidencias/{id}  (parcial + state machine)
# =====================================================================
@app.patch(
    "/incidencias/{incidencia_id}",
    response_model=IncidenciaResponse,
    tags=["Incidencias"],
    summary="Actualizar parcialmente una incidencia",
)
def actualizar_incidencia(
    payload: ActualizarIncidencia,
    incidencia_id: int = Path(gt=0),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> IncidenciaResponse:
    """
    Reglas:
    - Cualquier usuario autenticado puede editar `titulo`/`descripcion`/`severidad`
      y cambiar la asignación a un componente/despliegue.
    - Para cambiar `estado` o `asignado_a_id` se requiere rol QA, DESARROLLO o JEFE_PROYECTO.
    - Las transiciones de estado siguen una state machine estricta:
        ABIERTA       → EN_ANALISIS, CANCELADA
        EN_ANALISIS   → EN_RESOLUCION, CANCELADA
        EN_RESOLUCION → RESUELTA, CANCELADA
        RESUELTA      → CERRADA
        CERRADA / CANCELADA → (terminales, inmutables)
    - No se permiten cambios si la incidencia está en estado terminal.
    - Si se asigna un `componente_id`, debe existir y pertenecer al `despliegue_id`
      efectivo (nuevo si se actualiza, o el actual).
    """
    inc = _get_or_404(db, Incidencia, incidencia_id, "Incidencia")

    # Estado terminal: inmutable.
    if inc.estado in _INCIDENCIA_ESTADOS_TERMINALES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"La incidencia está en estado terminal '{inc.estado.value}' "
                f"y no admite más cambios."
            ),
        )

    cambios = payload.campos_a_actualizar()
    if not cambios:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No se proporcionaron campos para actualizar.",
        )

    # Autorización específica para campos restringidos.
    campos_restringidos = {"estado", "asignado_a_id"}
    if campos_restringidos.intersection(cambios):
        if current_user.rol not in {
            RolUsuario.QA, RolUsuario.DESARROLLO, RolUsuario.JEFE_PROYECTO,
        }:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Cambiar {sorted(campos_restringidos)} requiere rol QA, DESARROLLO "
                    f"o JEFE_PROYECTO. Su rol actual: '{current_user.rol.value}'."
                ),
            )

    # State machine para el campo `estado`.
    if "estado" in cambios:
        _validar_transicion_estado(inc.estado, cambios["estado"])

    # Validaciones de FK (orden importa: primero despliegue, luego componente).
    if "asignado_a_id" in cambios and cambios["asignado_a_id"] is not None:
        _get_or_404(db, Usuario, cambios["asignado_a_id"], "Usuario")

    if "despliegue_id" in cambios and cambios["despliegue_id"] is not None:
        _get_or_404(db, Despliegue, cambios["despliegue_id"], "Despliegue")

    if "componente_id" in cambios and cambios["componente_id"] is not None:
        comp = _get_or_404(db, Componente, cambios["componente_id"], "Componente")
        # El despliegue efectivo (nuevo si se actualiza en el mismo PATCH, o el actual).
        despliegue_efectivo = cambios.get("despliegue_id", inc.despliegue_id)
        if comp.despliegue_id != despliegue_efectivo:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"El componente id={comp.id} pertenece al despliegue "
                    f"id={comp.despliegue_id}, no al id={despliegue_efectivo}."
                ),
            )

    # Aplicar cambios.
    for campo, valor in cambios.items():
        setattr(inc, campo, valor)

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Conflicto de integridad al actualizar la incidencia.",
        ) from exc
    db.refresh(inc)
    return IncidenciaResponse.model_validate(inc)


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
    _: Usuario = Depends(get_current_user),
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
def crear_usuario(
    payload: CrearUsuario,
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_role(RolUsuario.JEFE_PROYECTO)),
) -> UsuarioResponse:
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
            detail="Conflicto: ya existe un usuario con ese email.",
        ) from exc
    db.refresh(u)
    return UsuarioResponse.model_validate(u)


@app.get(
    "/usuarios/",
    response_model=PaginatedResponse[UsuarioResponse],
    tags=["Usuarios"],
)
def listar_usuarios(
    page: int = Query(default=1, ge=1, description="Número de página (1-based)."),
    page_size: int = Query(default=50, ge=1, le=200, description="Tamaño de página."),
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_user),
) -> PaginatedResponse[UsuarioResponse]:
    total = db.execute(select(func.count(Usuario.id))).scalar_one()
    offset = (page - 1) * page_size
    rows = db.execute(
        select(Usuario).order_by(Usuario.id.asc()).offset(offset).limit(page_size)
    ).scalars().all()
    return PaginatedResponse[UsuarioResponse].build(
        items=[UsuarioResponse.model_validate(u) for u in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@app.get(
    "/despliegues/",
    response_model=PaginatedResponse[DespliegueResponse],
    tags=["Despliegues"],
)
def listar_despliegues(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    # Uso del Enum directamente: Pydantic valida y rechaza valores no permitidos (422).
    estado: Optional[EstadoDespliegue] = Query(
        default=None,
        description="Filtra por estado exacto del despliegue.",
    ),
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_user),
) -> PaginatedResponse[DespliegueResponse]:
    filtros = []
    if estado is not None:
        filtros.append(Despliegue.estado == estado)
    where_clause = and_(*filtros) if filtros else None

    count_stmt = select(func.count(Despliegue.id))
    list_stmt = select(Despliegue).order_by(Despliegue.id.desc())
    if where_clause is not None:
        count_stmt = count_stmt.where(where_clause)
        list_stmt = list_stmt.where(where_clause)

    total = db.execute(count_stmt).scalar_one()
    offset = (page - 1) * page_size
    rows = db.execute(list_stmt.offset(offset).limit(page_size)).scalars().all()
    return PaginatedResponse[DespliegueResponse].build(
        items=[DespliegueResponse.model_validate(d) for d in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@app.get(
    "/incidencias/",
    response_model=PaginatedResponse[IncidenciaResponse],
    tags=["Incidencias"],
)
def listar_incidencias(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    estado: Optional[EstadoIncidencia] = Query(
        default=None,
        description="Filtra por estado exacto (Pydantic valida el enum).",
    ),
    severidad: Optional[SeveridadIncidencia] = Query(
        default=None,
        description="Filtra por severidad exacta (Pydantic valida el enum).",
    ),
    asignado_a_id: Optional[int] = Query(default=None, gt=0, description="Tickets asignados a un usuario."),
    reportado_por_id: Optional[int] = Query(default=None, gt=0, description="Tickets reportados por un usuario."),
    despliegue_id: Optional[int] = Query(default=None, gt=0, description="Tickets asociados a un despliegue."),
    fecha_desde: Optional[datetime] = Query(default=None, description="ISO-8601; filtra fecha_deteccion >= fecha_desde."),
    fecha_hasta: Optional[datetime] = Query(default=None, description="ISO-8601; filtra fecha_deteccion <= fecha_hasta."),
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_user),
) -> PaginatedResponse[IncidenciaResponse]:
    if fecha_desde is not None and fecha_hasta is not None and fecha_desde > fecha_hasta:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="fecha_desde no puede ser mayor que fecha_hasta.",
        )

    filtros = []
    if estado is not None:
        filtros.append(Incidencia.estado == estado)
    if severidad is not None:
        filtros.append(Incidencia.severidad == severidad)
    if asignado_a_id is not None:
        filtros.append(Incidencia.asignado_a_id == asignado_a_id)
    if reportado_por_id is not None:
        filtros.append(Incidencia.reportado_por_id == reportado_por_id)
    if despliegue_id is not None:
        filtros.append(Incidencia.despliegue_id == despliegue_id)
    if fecha_desde is not None:
        filtros.append(Incidencia.fecha_deteccion >= fecha_desde)
    if fecha_hasta is not None:
        filtros.append(Incidencia.fecha_deteccion <= fecha_hasta)
    where_clause = and_(*filtros) if filtros else None

    count_stmt = select(func.count(Incidencia.id))
    list_stmt = select(Incidencia).order_by(Incidencia.fecha_deteccion.desc())
    if where_clause is not None:
        count_stmt = count_stmt.where(where_clause)
        list_stmt = list_stmt.where(where_clause)

    total = db.execute(count_stmt).scalar_one()
    offset = (page - 1) * page_size
    rows = db.execute(list_stmt.offset(offset).limit(page_size)).scalars().all()
    return PaginatedResponse[IncidenciaResponse].build(
        items=[IncidenciaResponse.model_validate(i) for i in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


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
