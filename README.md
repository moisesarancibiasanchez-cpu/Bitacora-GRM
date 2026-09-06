# Bitácora GRM

> Sistema de Gestión de Despliegues e Incidencias (ITSM) para entorno bancario.
> Núcleo mínimo: DDL PostgreSQL + API FastAPI + frontend HTML estático.

![Status](https://img.shields.io/badge/status-MVP-blue) ![Python](https://img.shields.io/badge/python-3.10%2B-blue) ![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688) ![PostgreSQL](https://img.shields.io/badge/PostgreSQL-13%2B-336791)

---

## 📁 Estructura

```
bitacora_grm/
├── app/
│   ├── __init__.py
│   ├── config.py        # Configuración (pydantic-settings)
│   ├── database.py      # Engine SQLAlchemy + get_db() con yield
│   ├── models.py        # ORM tipado Mapped[]
│   ├── schemas.py       # Validación Pydantic v2
│   └── main.py          # Endpoints REST
├── sql/
│   ├── 01_schema.sql    # DDL (4 tablas, ENUMs, CHECKs, índices, triggers)
│   └── 02_seed.sql      # 4 usuarios base
├── frontend/
│   ├── index.html
│   ├── styles.css
│   └── app.js
├── requirements.txt
├── .env.example
├── .gitignore
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

## 🔌 Endpoints clave

| Método | Ruta                                       | Descripción                                |
|--------|--------------------------------------------|--------------------------------------------|
| POST   | `/despliegues/`                            | Registrar pase a producción                |
| POST   | `/despliegues/{id}/componentes/`           | Agregar artefacto técnico                  |
| POST   | `/incidencias/`                            | Crear ticket (trazabilidad opcional)       |
| GET    | `/trazabilidad/despliegues/{id}`           | Vista 360° (cabecera + componentes + inc.) |
| GET    | `/health`                                  | Health check                               |
| GET    | `/despliegues/` `/incidencias/` `/usuarios/`| Listados                                   |
| POST   | `/usuarios/`                               | Alta de usuarios                           |

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
- **Errores transaccionales**: HTTP 400/404/409 según el caso.

---

## 🧪 Smoke test con curl

```bash
# 1) Health
curl http://127.0.0.1:8000/health

# 2) Crear despliegue
curl -X POST http://127.0.0.1:8000/despliegues/ \
  -H "Content-Type: application/json" \
  -d '{
    "codigo": "DEP-2026-0001",
    "titulo": "Pase a producción - Pagos",
    "fecha_programada": "2026-09-10T02:00:00Z",
    "plan_rollback": "1) Detener servicio. 2) Restaurar backup. 3) Reaplicar v3.",
    "solicitante_id": 1,
    "aprobador_id": 2
  }'

# 3) Trazabilidad 360°
curl http://127.0.0.1:8000/trazabilidad/despliegues/1
```

---

## 📜 Licencia

Proyecto académico / prototipo inicial.
