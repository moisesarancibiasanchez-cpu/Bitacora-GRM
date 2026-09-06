-- ============================================================================
-- Bitácora GRM · 02_seed.sql
-- Datos de prueba mínimos (idempotente).
-- ============================================================================

INSERT INTO usuarios (nombre, email, rol, departamento) VALUES
  ('Laura Pérez',  'laura.perez@banco.com',  'JEFE_PROYECTO', 'TI'),
  ('Mario Gómez',   'mario.gomez@banco.com',  'QA',            'Calidad'),
  ('Carlos Ruiz',   'carlos.ruiz@banco.com',  'DESARROLLO',    'TI'),
  ('Ana Torres',    'ana.torres@banco.com',   'NEGOCIO',       'Operaciones')
ON CONFLICT (email) DO NOTHING;
