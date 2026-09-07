# Bitácora GRM

> Sistema de Gestión de Despliegues e Incidencias (ITSM) para entorno bancario.
> Núcleo: Base de Datos PostgreSQL + API REST con FastAPI.

![Status](https://img.shields.io/badge/status-MVP-blue) ![Python](https://img.shields.io/badge/python-3.11%2B-blue) ![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688) ![PostgreSQL](https://img.shields.io/badge/PostgreSQL-13%2B-336791) ![Version](https://img.shields.io/badge/version-1.1.0-success)

---

## 📁 Estructura

```
bitacora_grm/
├── app/
│   ├── __init__.py
│   ├── config.py            # Settings (pydantic-settings + validators)
│   ├── database.py          # Engine SQLAlchemy + get_db() con yield
│   ├── models.py            # ORM tipado Mapped[]
│   ├── schemas.py           # Pydantic v2 (entrada, salida, PATCH, paginación)
│   └── main.py              # FastAPI: endpoints, auth, autorización
├── sql/
│   ├── 01_schema.sql        # DDL (4 tablas, ENUMs, CHECKs, índices, triggers)
│   └── 02_seed.sql          # 4 usuarios base
├── frontend/
│   ├── index.html
│   ├── styles.css
│   └── app.js
├── tests/                   # (opcional) tests pytest
├── .env.example
├── .gitignore
├── Procfile                 # uvicorn para Railway/Heroku
├── railway.json             # config NIXPACKS
├── runtime.txt              # python-3.11.9
├── requirements.txt
└── README.md
```

---

## 🚀 Puesta en marcha

### 1. Base de datos

```bash
# Crear BD y usuario
sudo -u postgres psql -c "CREATE DATABASE bitacora_grm;"
sudo -u postgres psql -c "CREATE USER bitacora WITH PASSWORD 'bitacora';"
sudo -u postgres psql -c "GRANT ALL ON DATABASE bitacora_grm TO bitacora;"

# Aplicar esquema y datos
sudo -u postgres psql -d bitacora_grm -f sql/01_schema.sql
sudo -u postgres psql -d bitacora_grm -f sql/02_seed.sql
```

### 2. Backend

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# editar DATABASE_URL si es necesario

uvicorn app.main:app --reload --port 8000
```

Documentación interactiva: <http://localhost:8000/docs>

### 3. Frontend

Servir `frontend/` con cualquier servidor estático, o abrirlo directamente
en el navegador (consume la API en `http://127.0.0.1:8000`).

```bash
# Opción A: con Python
cd frontend && python -m http.server 5500
# Abrir http://127.0.0.1:5500
```

---

## 🔐 Autenticación y autorización

### Cabecera `X-User-Id`

Todos los endpoints (excepto `/health`) requieren la cabecera:

```
X-User-Id: 42
```

El servidor:
1. Lee la cabecera.
2. Busca al usuario en `usuarios`.
3. Valida `activo = TRUE`.
4. Si falta o el usuario no existe/inactivo → **401 Unauthorized**.

### Autorización por rol

| Endpoint | Roles permitidos |
|---|---|
| `POST /despliegues/` | JEFE_PROYECTO, DESARROLLO |
| `POST /despliegues/{id}/componentes/` | JEFE_PROYECTO, DESARROLLO |
| `POST /usuarios/` | JEFE_PROYECTO |
| `POST /incidencias/` | Cualquier usuario autenticado |
| `PATCH /incidencias/{id}` (cambia `estado` o `asignado_a_id`) | QA, DESARROLLO, JEFE_PROYECTO |
| `PATCH /incidencias/{id}` (cambia `descripcion` o `severidad`) | Cualquier usuario autenticado |
| `GET /trazabilidad/...` y listados | Cualquier usuario autenticado |

> **Importante**: `POST /incidencias/` ya no acepta `reportado_por_id` en el
> body. El servidor lo toma de la cabecera `X-User-Id`.

---

## 🔌 Endpoints clave

### Críticos (enunciado original)

| Método | Ruta | Descripción |
|--------|------|-------------|
| `POST` | `/despliegues/` | Registrar pase a producción |
| `POST` | `/despliegues/{id}/componentes/` | Agregar artefacto técnico |
| `POST` | `/incidencias/` | Crear ticket (trazabilidad opcional) |
| `GET`  | `/trazabilidad/despliegues/{id}` | Vista 360° (cabecera + componentes + inc.) |

### Complementarios

| Método | Ruta | Descripción |
|--------|------|-------------|
| `GET`  | `/health` | Health check (con entorno) |
| `POST` | `/usuarios/` | Alta de usuarios (JEFE_PROYECTO) |
| `GET`  | `/usuarios/` | Listar usuarios (paginado) |
| `GET`  | `/despliegues/` | Listar despliegues (paginado, filtro `estado`) |
| `GET`  | `/incidencias/` | Listar incidencias (paginado, 7 filtros) |
| `PATCH`| `/incidencias/{id}` | Actualización parcial |

### Filtros de `GET /incidencias/`

| Query param | Tipo | Descripción |
|---|---|---|
| `estado` | enum | ABIERTA, EN_ANALISIS, EN_RESOLUCION, RESUELTA, CERRADA, CANCELADA |
| `severidad` | enum | BAJA, MEDIA, ALTA, CRITICA |
| `asignado_a_id` | int | Tickets asignados a un usuario |
| `reportado_por_id` | int | Tickets reportados por un usuario |
| `despliegue_id` | int | Tickets asociados a un despliegue |
| `fecha_desde` | ISO-8601 | `fecha_deteccion >= fecha_desde` |
| `fecha_hasta` | ISO-8601 | `fecha_deteccion <= fecha_hasta` |
| `page` | int (≥1) | Número de página (default 1) |
| `page_size` | int (1..200) | Tamaño de página (default 50) |

### Envelope de paginación

```json
{
  "items": [ ... ],
  "total": 123,
  "page": 1,
  "page_size": 50,
  "total_pages": 3
}
```

---

## 🛡️ Garantías de diseño

- **Anti-inyección SQL**: todas las consultas usan SQLAlchemy 2.0 parametrizado.
- **Integridad referencial**: FKs con `ON UPDATE CASCADE` y `ON DELETE RESTRICT/SET NULL`.
- **Reglas de negocio en BD**:
  - `solicitante_id <> aprobador_id` (CHECK).
  - `plan_rollback` ≥ 20 caracteres (CHECK).
  - `checksum_sha256` con regex hexadecimal 64 chars (CHECK).
- **Trazabilidad**: las incidencias pueden vincularse opcionalmente a un
  despliegue y, dentro de él, a un componente específico.
- **Auditoría**: `created_at` y `updated_at` con trigger automático de mantenimiento.
- **Inyección de dependencias**: `get_db()` como generador (`yield db`) con
  rollback automático ante excepciones.
- **Type hints** en todas las funciones.
- **Errores transaccionales**: HTTP 400/401/403/404/409 según el caso.
- **CORS restrictivo por entorno**: `["*"]` solo en dev; en staging/prod exige lista explícita.

---

## 🧪 Smoke test con curl

> **Nota:** En v1.1+ todos los endpoints (salvo `/health`) requieren la
> cabecera `X-User-Id`. Asumimos que existe el usuario con id=1 (cargado en
> el seed) y rol JEFE_PROYECTO.

```bash
# 1) Health (sin auth)
curl http://127.0.0.1:8000/health
# → {"status":"ok","version":"1.1.0","environment":"dev","timestamp":"..."}

# 2) Crear despliegue (rol JEFE_PROYECTO o DESARROLLO)
curl -X POST http://127.0.0.1:8000/despliegues/ \
  -H "Content-Type: application/json" \
  -H "X-User-Id: 1" \
  -d '{
    "codigo": "DEP-2026-0001",
    "titulo": "Pase a producción - Pagos",
    "fecha_programada": "2026-09-10T02:00:00Z",
    "plan_rollback": "1) Detener servicio. 2) Restaurar backup. 3) Reaplicar v3.",
    "solicitante_id": 1,
    "aprobador_id": 2
  }'

# 3) Reportar incidencia (cualquier usuario autenticado)
curl -X POST http://127.0.0.1:8000/incidencias/ \
  -H "Content-Type: application/json" \
  -H "X-User-Id: 3" \
  -d '{
    "codigo": "INC-0001",
    "titulo": "Caída del portal de transferencias",
    "descripcion": "Desde las 09:00 el portal devuelve 500 en login",
    "severidad": "CRITICA",
    "despliegue_id": 1
  }'

# 4) Trazabilidad 360° (cualquier usuario autenticado)
curl -H "X-User-Id: 1" http://127.0.0.1:8000/trazabilidad/despliegues/1

# 5) PATCH para cambiar estado de la incidencia (rol QA/DESARROLLO/JEFE_PROYECTO)
curl -X PATCH http://127.0.0.1:8000/incidencias/1 \
  -H "Content-Type: application/json" \
  -H "X-User-Id: 1" \
  -d '{"estado": "EN_ANALISIS", "asignado_a_id": 2}'

# 6) Listar incidencias filtrando
curl -H "X-User-Id: 1" "http://127.0.0.1:8000/incidencias/?estado=ABIERTA&severidad=CRITICA&page=1&page_size=20"
```

---

## ☁️ Despliegue en Railway

1. **Crear proyecto** en <https://railway.com/new> → *Deploy from GitHub repo* → `Bitacora-GRM`.
2. **Agregar plugin PostgreSQL** desde el dashboard.
3. **Variables de entorno** (en *Variables* del servicio):
   ```
   DATABASE_URL = <URL que Railway asigna al plugin Postgres>
   ENVIRONMENT  = prod
   CORS_ORIGINS = https://tu-frontend.banco.local
   LOG_LEVEL    = INFO
   ```
4. Railway detecta automáticamente `Procfile` y `railway.json`.
5. **Inicializar el esquema** (opcional, en release phase):
   ```bash
   psql $DATABASE_URL < sql/01_schema.sql
   psql $DATABASE_URL < sql/02_seed.sql
   ```

---

## 🧾 Changelog

### v1.1.0 (Tier 1 — multi-usuario)

- ➕ Autenticación ligera por cabecera `X-User-Id`.
- ➕ `reportado_por_id` se toma del header, no del body.
- ➕ `PATCH /incidencias/{id}` con actualización parcial.
- ➕ Filtros en `GET /incidencias/` (estado, severidad, asignado, reportado, despliegue, fechas).
- ➕ Paginación con metadatos (`PaginatedResponse[T]`) en todos los listados.
- ➕ CORS restrictivo por entorno (`["*"]` solo en dev).
- ➕ Helper `require_role()` para autorización por rol.
- 🔒 Mensajes de error de integridad ya no exponen `exc.orig`.
- 🔒 `GET /health` ahora incluye `environment`.

### v1.0.0 — Núcleo inicial

- 4 endpoints críticos del enunciado.
- DDL con 4 tablas, ENUMs, CHECKs, triggers.
- ORM SQLAlchemy 2.0 con `Mapped[]`.
- Pydantic v2 con validación.
- Trazabilidad 360°.
- Reglas de separación de funciones (solicitante ≠ aprobador).

---

## 📜 Licencia

Proyecto académico / prototipo interno — Uso restringido.
