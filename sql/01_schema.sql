-- ============================================================================
-- Bitácora GRM · 01_schema.sql
-- Sistema de Gestión de Despliegues e Incidencias para entorno bancario.
-- PostgreSQL 13+ (DDL puro, sin ORM).
-- ============================================================================

-- Limpieza idempotente (útil para re-ejecución en DEV)
DROP TABLE IF EXISTS incidencias CASCADE;
DROP TABLE IF EXISTS componentes  CASCADE;
DROP TABLE IF EXISTS despliegues  CASCADE;
DROP TABLE IF EXISTS usuarios     CASCADE;
DROP TYPE  IF EXISTS rol_usuario       CASCADE;
DROP TYPE  IF EXISTS estado_despliegue CASCADE;
DROP TYPE  IF EXISTS tipo_componente   CASCADE;
DROP TYPE  IF EXISTS severidad_incidencia CASCADE;
DROP TYPE  IF EXISTS estado_incidencia CASCADE;

-- ----------------------------------------------------------------------------
-- ENUMs (dominios cerrados)
-- ----------------------------------------------------------------------------
CREATE TYPE rol_usuario          AS ENUM ('JEFE_PROYECTO','QA','DESARROLLO','NEGOCIO');
CREATE TYPE estado_despliegue    AS ENUM ('PLANIFICADO','EN_CURSO','COMPLETADO','FALLIDO','CANCELADO','REVERTIDO');
CREATE TYPE tipo_componente      AS ENUM ('SCRIPT_SQL','SCRIPT_SHELL','BINARIO','CONFIGURACION','CONTENEDOR','OTRO');
CREATE TYPE severidad_incidencia AS ENUM ('BAJA','MEDIA','ALTA','CRITICA');
CREATE TYPE estado_incidencia    AS ENUM ('ABIERTA','EN_ANALISIS','EN_RESOLUCION','RESUELTA','CERRADA','CANCELADA');

-- ----------------------------------------------------------------------------
-- usuarios
-- ----------------------------------------------------------------------------
CREATE TABLE usuarios (
    id            BIGSERIAL PRIMARY KEY,
    nombre        VARCHAR(120)  NOT NULL,
    email         VARCHAR(160)  NOT NULL UNIQUE,
    rol           rol_usuario   NOT NULL DEFAULT 'NEGOCIO',
    departamento  VARCHAR(80),
    activo        BOOLEAN       NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_usuarios_rol    ON usuarios(rol);
CREATE INDEX idx_usuarios_activo ON usuarios(activo);

-- ----------------------------------------------------------------------------
-- despliegues
-- ----------------------------------------------------------------------------
CREATE TABLE despliegues (
    id                    BIGSERIAL PRIMARY KEY,
    codigo                VARCHAR(40)  NOT NULL UNIQUE,
    titulo                VARCHAR(200) NOT NULL,
    descripcion           TEXT,
    fecha_programada      TIMESTAMPTZ  NOT NULL,
    estado                estado_despliegue NOT NULL DEFAULT 'PLANIFICADO',
    plan_rollback         TEXT         NOT NULL,
    ambiente              VARCHAR(40)  NOT NULL DEFAULT 'PRODUCCION',
    ventana_mantenimiento VARCHAR(40),

    solicitante_id        BIGINT       NOT NULL REFERENCES usuarios(id) ON UPDATE CASCADE ON DELETE RESTRICT,
    aprobador_id          BIGINT       NOT NULL REFERENCES usuarios(id) ON UPDATE CASCADE ON DELETE RESTRICT,

    created_at            TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_despliegues_aprobador_distinto CHECK (solicitante_id <> aprobador_id),
    CONSTRAINT chk_despliegues_plan_rollback_min  CHECK (char_length(plan_rollback) >= 20)
);
CREATE INDEX idx_despliegues_estado      ON despliegues(estado);
CREATE INDEX idx_despliegues_fecha_prog  ON despliegues(fecha_programada);
CREATE INDEX idx_despliegues_ambiente    ON despliegues(ambiente);

-- ----------------------------------------------------------------------------
-- componentes  (N:1 con despliegues)
-- ----------------------------------------------------------------------------
CREATE TABLE componentes (
    id                   BIGSERIAL PRIMARY KEY,
    despliegue_id        BIGINT       NOT NULL REFERENCES despliegues(id) ON UPDATE CASCADE ON DELETE CASCADE,
    nombre               VARCHAR(150) NOT NULL,
    version              VARCHAR(60)  NOT NULL,
    tipo                 tipo_componente NOT NULL,
    ruta_almacenamiento  VARCHAR(500) NOT NULL,
    checksum_sha256      CHAR(64)     NOT NULL,
    notas                TEXT,

    created_at           TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_componentes_despliegue_nombre_version UNIQUE (despliegue_id, nombre, version),
    CONSTRAINT chk_componentes_checksum_sha256           CHECK (checksum_sha256 ~ '^[A-Fa-f0-9]{64}$')
);
CREATE INDEX idx_componentes_tipo ON componentes(tipo);

-- ----------------------------------------------------------------------------
-- incidencias  (FKs opcionales hacia despliegues / componentes => trazabilidad)
-- ----------------------------------------------------------------------------
CREATE TABLE incidencias (
    id                BIGSERIAL PRIMARY KEY,
    codigo            VARCHAR(40) NOT NULL UNIQUE,
    titulo            VARCHAR(200) NOT NULL,
    descripcion       TEXT NOT NULL,
    severidad         severidad_incidencia NOT NULL,
    estado            estado_incidencia    NOT NULL DEFAULT 'ABIERTA',

    reportado_por_id  BIGINT NOT NULL REFERENCES usuarios(id)     ON UPDATE CASCADE ON DELETE RESTRICT,
    asignado_a_id     BIGINT          REFERENCES usuarios(id)     ON UPDATE CASCADE ON DELETE SET NULL,
    despliegue_id     BIGINT          REFERENCES despliegues(id)  ON UPDATE CASCADE ON DELETE SET NULL,
    componente_id     BIGINT          REFERENCES componentes(id)  ON UPDATE CASCADE ON DELETE SET NULL,

    fecha_deteccion   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_incidencias_estado          ON incidencias(estado);
CREATE INDEX idx_incidencias_severidad       ON incidencias(severidad);
CREATE INDEX idx_incidencias_fecha_deteccion ON incidencias(fecha_deteccion);
CREATE INDEX idx_incidencias_despliegue      ON incidencias(despliegue_id);

-- ----------------------------------------------------------------------------
-- Triggers: mantener updated_at automáticamente
-- ----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION trg_set_updated_at() RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at := NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER usuarios_updated_at
    BEFORE UPDATE ON usuarios
    FOR EACH ROW EXECUTE FUNCTION trg_set_updated_at();

CREATE TRIGGER despliegues_updated_at
    BEFORE UPDATE ON despliegues
    FOR EACH ROW EXECUTE FUNCTION trg_set_updated_at();

CREATE TRIGGER componentes_updated_at
    BEFORE UPDATE ON componentes
    FOR EACH ROW EXECUTE FUNCTION trg_set_updated_at();

CREATE TRIGGER incidencias_updated_at
    BEFORE UPDATE ON incidencias
    FOR EACH ROW EXECUTE FUNCTION trg_set_updated_at();

-- ============================================================================
-- Fin del esquema Bitácora GRM.
-- ============================================================================
