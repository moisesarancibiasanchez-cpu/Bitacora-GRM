/* =============================================================================
 * Bitácora GRM — frontend SPA (vanilla JS)
 * -----------------------------------------------------------------------------
 *  - Cliente API con X-User-Id
 *  - Router hash-based
 *  - Vistas: dashboard, despliegues, componentes, incidencias, trazabilidad,
 *            usuarios, api-docs
 *  - Enums sincronizados con app/models.py
 *  - Estado: paginación, filtros, formularios
 * ============================================================================= */
'use strict';

/* ====================== Config ====================== */
const API_BASE = (location.hostname === '127.0.0.1' || location.hostname === 'localhost')
  ? 'http://127.0.0.1:8000'
  : '';   // en producción: mismo origen

const DEFAULT_USER_ID = 1;
const LS_USER_KEY = 'bitacora_grm.userId';

/* ====================== Enums (sincronizados con backend) ====================== */
const ENUMS = {
  rol:         ['JEFE_PROYECTO', 'QA', 'DESARROLLO', 'NEGOCIO'],
  estadoDespliegue: ['PLANIFICADO', 'EN_CURSO', 'COMPLETADO', 'FALLIDO', 'CANCELADO', 'REVERTIDO'],
  tipoComponente:   ['SCRIPT_SQL', 'SCRIPT_SHELL', 'BINARIO', 'CONFIGURACION', 'CONTENEDOR', 'OTRO'],
  severidad:   ['BAJA', 'MEDIA', 'ALTA', 'CRITICA'],
  estadoInc:   ['ABIERTA', 'EN_ANALISIS', 'EN_RESOLUCION', 'RESUELTA', 'CERRADA', 'CANCELADA'],
};

/* State machine de Incidencia (mismas reglas que el backend) */
const TRANSICIONES_INC = {
  ABIERTA:       ['EN_ANALISIS', 'CANCELADA'],
  EN_ANALISIS:   ['EN_RESOLUCION', 'CANCELADA'],
  EN_RESOLUCION: ['RESUELTA', 'CANCELADA'],
  RESUELTA:      ['CERRADA'],
  CERRADA:       [],
  CANCELADA:     [],
};

/* Roles restringidos para cambiar estado/asignado */
const ROL_RESTRINGIDO_INC = new Set(['QA', 'DESARROLLO', 'JEFE_PROYECTO']);
const ROL_CREAR_DESPLIEGUE = new Set(['JEFE_PROYECTO', 'DESARROLLO']);
const ROL_CREAR_USUARIO    = new Set(['JEFE_PROYECTO']);

/* ====================== Util ====================== */
const $  = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
}[c]));

function fmtDate(s) {
  if (!s) return '—';
  const d = new Date(s);
  if (isNaN(d)) return s;
  return d.toLocaleString('es-MX', { dateStyle: 'short', timeStyle: 'short' });
}
function fmtDateOnly(s) {
  if (!s) return '—';
  const d = new Date(s);
  if (isNaN(d)) return s;
  return d.toLocaleDateString('es-MX', { dateStyle: 'medium' });
}
function nowLocalForInput() {
  const d = new Date(Date.now() + 60 * 60 * 1000);
  const pad = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/* ====================== Estado ====================== */
const state = {
  userId: Number(localStorage.getItem(LS_USER_KEY) || DEFAULT_USER_ID),
  userInfo: null,        // cache: usuario actual (rol, etc.)
  health: null,
  pagination: { despliegues: { page: 1 }, incidencias: { page: 1 }, usuarios: { page: 1 } },
  filtrosIncidencias: {},
  filtrosDespliegues: {},
};

/* ====================== API client ====================== */
async function api(method, path, body) {
  const headers = { 'Content-Type': 'application/json' };
  if (state.userId) headers['X-User-Id'] = String(state.userId);

  const opts = { method, headers };
  if (body !== undefined) opts.body = JSON.stringify(body);

  const url = API_BASE + path;
  let resp, text;
  try {
    resp = await fetch(url, opts);
    text = await resp.text();
  } catch (e) {
    throw new ApiError(0, 'network', `No se pudo contactar la API (${url}). ¿Está levantada uvicorn?`);
  }

  let data;
  try { data = text ? JSON.parse(text) : null; } catch { data = text; }

  if (!resp.ok) {
    const detail = (data && (data.detail || data.message)) || resp.statusText || `HTTP ${resp.status}`;
    throw new ApiError(resp.status, data?.code || 'http_error', detail, data);
  }
  return data;
}

class ApiError extends Error {
  constructor(status, code, message, data) {
    super(message);
    this.status = status; this.code = code; this.data = data;
  }
}

/* ====================== UI helpers ====================== */
function toast(kind, title, body, ttl = 4500) {
  const wrap = $('#toasts');
  const t = document.createElement('div');
  t.className = `toast ${kind}`;
  t.innerHTML = `<strong>${esc(title)}</strong>${body ? `<div class="body">${esc(body)}</div>` : ''}`;
  wrap.appendChild(t);
  setTimeout(() => { t.style.opacity = '0'; t.style.transition = 'opacity .25s'; }, ttl - 250);
  setTimeout(() => t.remove(), ttl);
}

function openModal(title, bodyHTML) {
  $('#modalTitle').textContent = title;
  $('#modalBody').innerHTML = bodyHTML;
  $('#modal').hidden = false;
}
function closeModal() { $('#modal').hidden = true; }
document.addEventListener('click', (e) => {
  if (e.target.matches('[data-modal-close]')) closeModal();
});
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeModal(); });

function badge(text, kind = 'muted') {
  return `<span class="badge ${esc(kind)}">${esc(text)}</span>`;
}

function stateBadgeDespliegue(estado) {
  const map = {
    PLANIFICADO: 'info', EN_CURSO: 'warn', COMPLETADO: 'ok',
    FALLIDO: 'err', CANCELADO: 'muted', REVERTIDO: 'err',
  };
  return badge(estado, map[estado] || 'muted');
}
function stateBadgeInc(estado) {
  const map = {
    ABIERTA: 'err', EN_ANALISIS: 'warn', EN_RESOLUCION: 'warn',
    RESUELTA: 'info', CERRADA: 'ok', CANCELADA: 'muted',
  };
  return badge(estado, map[estado] || 'muted');
}
function sevBadge(sev) {
  const map = { BAJA: 'muted', MEDIA: 'info', ALTA: 'warn', CRITICA: 'err' };
  return badge(sev, map[sev] || 'muted');
}
function rolBadge(rol) {
  const map = { JEFE_PROYECTO: 'brand', QA: 'info', DESARROLLO: 'accent', NEGOCIO: 'muted' };
  return badge(rol, map[rol] || 'muted');
}

function formData(form) {
  const fd = new FormData(form);
  const out = {};
  for (const [k, v] of fd.entries()) {
    if (v === '' || v == null) continue;
    out[k] = v;
  }
  return out;
}

/* Convertir input datetime-local a ISO con Z (UTC) */
function toIsoLocal(v) {
  if (!v) return undefined;
  // "2026-09-10T02:00" -> "2026-09-10T02:00:00Z" (interpretado como UTC por el input)
  // Si quieres local-time, sustituye por: new Date(v).toISOString()
  return new Date(v).toISOString();
}

function pageHeader({ title, hint, actions = [] }) {
  return `
    <div class="page-head">
      <div>
        <h2>${esc(title)}</h2>
        ${hint ? `<p class="hint">${esc(hint)}</p>` : ''}
      </div>
      <div class="actions">${actions.join(' ')}</div>
    </div>
  `;
}

function pagerHTML(p) {
  if (!p || p.total_pages <= 1) {
    return `<div class="pager"><span>${p ? `${p.total} resultado(s)` : ''}</span></div>`;
  }
  const pages = [];
  const cur = p.page, total = p.total_pages;
  const win = (n) => Array.from({ length: n }, (_, i) => cur - 2 + i).filter((x) => x >= 1 && x <= total);
  let set = new Set([1, ...win(cur), total]);
  // añadir elipsis
  const arr = Array.from(set).sort((a, b) => a - b);
  let prev = 0;
  for (const n of arr) {
    if (prev && n - prev > 1) pages.push(`<span class="muted">…</span>`);
    pages.push(`<button data-page="${n}" class="${n === cur ? 'active' : ''}">${n}</button>`);
    prev = n;
  }
  return `
    <div class="pager">
      <span>${p.total} resultado(s) · página ${cur} de ${total}</span>
      <div class="pager__pages">
        <button data-page="1" ${cur === 1 ? 'disabled' : ''}>«</button>
        <button data-page="${cur - 1}" ${cur === 1 ? 'disabled' : ''}>‹</button>
        ${pages.join('')}
        <button data-page="${cur + 1}" ${cur === total ? 'disabled' : ''}>›</button>
        <button data-page="${total}" ${cur === total ? 'disabled' : ''}>»</button>
      </div>
    </div>
  `;
}

/* ====================== Health ====================== */
async function checkHealth() {
  const pill = $('#healthPill');
  const txt  = $('#healthPillTxt');
  try {
    const h = await api('GET', '/health');
    state.health = h;
    pill.classList.add('ok');
    pill.classList.remove('err');
    txt.textContent = `${h.environment} · v${h.version}`;
  } catch (e) {
    pill.classList.add('err'); pill.classList.remove('ok');
    txt.textContent = 'API no disponible';
  }
}

/* ====================== Router ====================== */
const routes = {
  dashboard:    renderDashboard,
  despliegues:  renderDespliegues,
  componentes:  renderComponentes,
  incidencias:  renderIncidencias,
  trazabilidad: renderTrazabilidad,
  usuarios:     renderUsuarios,
  'api-docs':   renderApiDocs,
};

function currentRoute() {
  const h = (location.hash || '#dashboard').replace(/^#/, '');
  return routes[h] ? h : 'dashboard';
}

function navigate(hash) {
  if (location.hash === hash) render();
  else location.hash = hash;
}

function setActiveNav() {
  const r = currentRoute();
  $$('#nav a').forEach((a) => a.classList.toggle('active', a.dataset.route === r));
}

function render() {
  setActiveNav();
  const r = currentRoute();
  const view = routes[r] || renderDashboard;
  const main = $('#main');
  main.innerHTML = `<div class="card"><span class="loading"></span> Cargando…</div>`;
  Promise.resolve(view(main)).catch((e) => {
    console.error(e);
    main.innerHTML = '';
    main.appendChild(errorBox(e));
  });
}

function errorBox(err) {
  const div = document.createElement('div');
  div.className = 'card';
  let body = `<strong>Error ${err.status || ''}</strong><p>${esc(err.message)}</p>`;
  if (err.status === 401) {
    body = `<strong>401 · No autenticado</strong>
            <p>Revisa el campo <code>X-User-Id</code> en la barra superior (debe ser un id de usuario existente y activo).</p>`;
  } else if (err.status === 403) {
    body = `<strong>403 · Prohibido</strong>
            <p>El usuario actual no tiene el rol necesario para esta operación.</p>`;
  } else if (err.status === 404) {
    body = `<strong>404 · No encontrado</strong><p>${esc(err.message)}</p>`;
  } else if (err.status === 409) {
    body = `<strong>409 · Conflicto</strong><p>${esc(err.message)}</p>`;
  } else if (err.status === 422) {
    const det = err.data?.detail || [];
    const items = Array.isArray(det) ? det.map(d => `<li>${esc(d.loc?.join('.'))}: ${esc(d.msg)}</li>`).join('') : esc(err.message);
    body = `<strong>422 · Validación</strong><ul>${items}</ul>`;
  }
  div.innerHTML = body;
  return div;
}

/* ============================================================================
 * VIEW: Dashboard
 * ========================================================================== */
async function renderDashboard(main) {
  main.innerHTML = pageHeader({
    title: 'Dashboard',
    hint: 'Vista general del sistema y KPIs clave.',
  });

  let counts = { despliegues: '—', incidencias: '—', criticas: '—', usuarios: '—', comp: '—' };
  try {
    const [d, i, u] = await Promise.all([
      api('GET', '/despliegues/?page=1&page_size=1'),
      api('GET', '/incidencias/?page=1&page_size=1'),
      api('GET', '/usuarios/?page=1&page_size=1'),
    ]);
    counts.despliegues = d.total;
    counts.incidencias = i.total;
    counts.usuarios    = u.total;
    // Sumar componentes de las primeras N incidencias... o via otra señal.
  } catch (e) { /* se mostrará abajo en tarjetas individuales */ }

  // Incidencias críticas abiertas
  let criticas = '—';
  try {
    const c = await api('GET', '/incidencias/?severidad=CRITICA&page=1&page_size=1');
    criticas = c.total;
  } catch (e) { /* noop */ }

  const kpis = `
    <div class="kpi-grid">
      <div class="kpi info">
        <span class="kpi__label">Despliegues</span>
        <span class="kpi__value">${esc(counts.despliegues)}</span>
        <span class="kpi__sub">Registrados en el sistema</span>
      </div>
      <div class="kpi warn">
        <span class="kpi__label">Incidencias</span>
        <span class="kpi__value">${esc(counts.incidencias)}</span>
        <span class="kpi__sub">Tickets totales</span>
      </div>
      <div class="kpi err">
        <span class="kpi__label">Críticas</span>
        <span class="kpi__value">${esc(criticas)}</span>
        <span class="kpi__sub">Severidad CRITICA</span>
      </div>
      <div class="kpi ok">
        <span class="kpi__label">Usuarios</span>
        <span class="kpi__value">${esc(counts.usuarios)}</span>
        <span class="kpi__sub">Activos en el sistema</span>
      </div>
    </div>
  `;

  // Lista de incidencias recientes + despliegues recientes
  let ultimasInc = [];
  let ultimosDespl = [];
  try {
    const r = await api('GET', '/incidencias/?page=1&page_size=5');
    ultimasInc = r.items;
  } catch (e) {}
  try {
    const r = await api('GET', '/despliegues/?page=1&page_size=5');
    ultimosDespl = r.items;
  } catch (e) {}

  const incRows = ultimasInc.length === 0
    ? `<div class="empty"><strong>Sin incidencias</strong>Aún no se han reportado tickets.</div>`
    : `<div class="table-wrap"><table>
         <thead><tr><th>Código</th><th>Título</th><th>Severidad</th><th>Estado</th><th>Detectada</th></tr></thead>
         <tbody>${ultimasInc.map(i => `
           <tr>
             <td class="mono">${esc(i.codigo)}</td>
             <td>${esc(i.titulo)}</td>
             <td>${sevBadge(i.severidad)}</td>
             <td>${stateBadgeInc(i.estado)}</td>
             <td class="muted">${esc(fmtDate(i.fecha_deteccion))}</td>
           </tr>`).join('')}
         </tbody>
       </table></div>`;

  const desplRows = ultimosDespl.length === 0
    ? `<div class="empty"><strong>Sin despliegues</strong>Aún no se han registrado pases a producción.</div>`
    : `<div class="table-wrap"><table>
         <thead><tr><th>Código</th><th>Título</th><th>Estado</th><th>Fecha</th></tr></thead>
         <tbody>${ultimosDespl.map(d => `
           <tr>
             <td class="mono">${esc(d.codigo)}</td>
             <td>${esc(d.titulo)}</td>
             <td>${stateBadgeDespliegue(d.estado)}</td>
             <td class="muted">${esc(fmtDate(d.fecha_programada))}</td>
           </tr>`).join('')}
         </tbody>
       </table></div>`;

  main.insertAdjacentHTML('beforeend', kpis + `
    <div class="card">
      <h3>Incidencias recientes</h3>
      ${incRows}
    </div>
    <div class="card">
      <h3>Despliegues recientes</h3>
      ${desplRows}
    </div>
  `);
}

/* ============================================================================
 * VIEW: Despliegues
 * ========================================================================== */
async function renderDespliegues(main) {
  const canCreate = state.userInfo && ROL_CREAR_DESPLIEGUE.has(state.userInfo.rol);

  main.innerHTML = pageHeader({
    title: 'Despliegues',
    hint: 'Pases a producción registrados (ordenados por id desc).',
    actions: [canCreate ? `<button id="btnNewDespliegue">+ Nuevo despliegue</button>` : ''],
  });

  // Filtros
  const filtros = state.filtrosDespliegues;
  const filterBar = `
    <div class="toolbar">
      <div class="field">
        <label for="fEstado">Estado</label>
        <select id="fEstado">
          <option value="">— todos —</option>
          ${ENUMS.estadoDespliegue.map(s => `<option value="${s}" ${filtros.estado === s ? 'selected' : ''}>${s}</option>`).join('')}
        </select>
      </div>
      <button class="btn--ghost btn" id="btnFiltrar">Aplicar</button>
      <button class="btn--ghost btn" id="btnLimpiarFiltros">Limpiar</button>
      <div class="spacer"></div>
      <span class="muted" id="totalInfo"></span>
    </div>
    <div id="listaDespliegues"><div class="card"><span class="loading"></span> Cargando…</div></div>
  `;
  main.insertAdjacentHTML('beforeend', filterBar);

  async function load() {
    const page = state.pagination.despliegues.page;
    const qs = new URLSearchParams({ page, page_size: 50 });
    if (state.filtrosDespliegues.estado) qs.set('estado', state.filtrosDespliegues.estado);
    const data = await api('GET', `/despliegues/?${qs}`);
    render(data);
    state.pagination.despliegues.page = data.page;
  }

  function render(data) {
    const cont = $('#listaDespliegues');
    cont.innerHTML = '';
    if (data.items.length === 0) {
      cont.innerHTML = `<div class="card empty">
        <strong>Sin resultados</strong>
        Ajusta los filtros o crea un nuevo despliegue.
      </div>`;
      $('#totalInfo').textContent = '';
      return;
    }
    const t = document.createElement('div');
    t.className = 'table-wrap';
    t.innerHTML = `
      <table>
        <thead><tr>
          <th>ID</th><th>Código</th><th>Título</th><th>Estado</th>
          <th>Ambiente</th><th>Fecha programada</th><th class="right">Acciones</th>
        </tr></thead>
        <tbody>
          ${data.items.map(d => `
            <tr>
              <td class="mono">#${d.id}</td>
              <td class="mono">${esc(d.codigo)}</td>
              <td>${esc(d.titulo)}</td>
              <td>${stateBadgeDespliegue(d.estado)}</td>
              <td>${esc(d.ambiente)}</td>
              <td class="muted">${esc(fmtDate(d.fecha_programada))}</td>
              <td class="row-actions right">
                <button class="btn--ghost btn btn--sm" data-action="trazabilidad" data-id="${d.id}">Trazabilidad</button>
                <button class="btn--ghost btn btn--sm" data-action="componentes"  data-id="${d.id}">+ Componente</button>
                <button class="btn--ghost btn btn--sm" data-action="detalle"      data-id="${d.id}">Detalle</button>
              </td>
            </tr>
          `).join('')}
        </tbody>
      </table>
      ${pagerHTML(data)}
    `;
    cont.appendChild(t);

    // Eventos
    t.addEventListener('click', (e) => {
      const btn = e.target.closest('button');
      if (!btn) return;
      const id = Number(btn.dataset.id);
      if (btn.dataset.action === 'trazabilidad') { navigate(`#trazabilidad&id=${id}`); }
      else if (btn.dataset.action === 'componentes') { openComponenteModal(id); }
      else if (btn.dataset.action === 'detalle') { openDespliegueDetalle(id); }
      else if (btn.dataset.page) {
        state.pagination.despliegues.page = Number(btn.dataset.page);
        load();
      }
    });

    $('#totalInfo').textContent = `${data.total} resultado(s)`;
  }

  $('#btnFiltrar').onclick = () => {
    state.filtrosDespliegues.estado = $('#fEstado').value || undefined;
    state.pagination.despliegues.page = 1;
    load().catch((err) => { toast('err', 'Error al listar', err.message); $('#listaDespliegues').innerHTML = ''; });
  };
  $('#btnLimpiarFiltros').onclick = () => {
    state.filtrosDespliegues = {};
    state.pagination.despliegues.page = 1;
    $('#fEstado').value = '';
    load();
  };

  if (canCreate) {
    $('#btnNewDespliegue').onclick = () => openDespliegueCreateModal(load);
  }

  await load().catch((err) => { toast('err', 'Error al listar', err.message); });
}

function openDespliegueCreateModal(onSaved) {
  if (!state.userInfo) { toast('warn', 'Sin usuario', 'Define X-User-Id arriba'); return; }
  if (!ROL_CREAR_DESPLIEGUE.has(state.userInfo.rol)) {
    toast('warn', 'Rol insuficiente', `Tu rol '${state.userInfo.rol}' no puede crear despliegues (requerido: JEFE_PROYECTO o DESARROLLO).`);
    return;
  }
  const body = `
    <form id="formNewDespliegue" class="grid">
      <label>Código <input name="codigo" required pattern="[A-Z0-9_\\-]+" value="DEP-${new Date().getFullYear()}-${Math.floor(Math.random()*9000+1000)}"></label>
      <label>Estado
        <select name="estado">
          ${ENUMS.estadoDespliegue.map(s => `<option ${s === 'PLANIFICADO' ? 'selected' : ''}>${s}</option>`).join('')}
        </select>
      </label>
      <label class="full">Título <input name="titulo" required minlength="5" placeholder="Pase a producción - Pagos"></label>
      <label>Fecha programada <input name="fecha_programada" type="datetime-local" required value="${nowLocalForInput()}"></label>
      <label>Ambiente <input name="ambiente" value="PRODUCCION"></label>
      <label>Solicitante ID <input name="solicitante_id" type="number" min="1" required value="${esc(state.userId)}"></label>
      <label>Aprobador ID <input name="aprobador_id" type="number" min="1" required value="2"></label>
      <label>Ventana de mantenimiento <input name="ventana_mantenimiento" placeholder="opcional"></label>
      <label class="full">Descripción <textarea name="descripcion" rows="2" placeholder="opcional"></textarea></label>
      <label class="full">Plan de rollback (mín. 20 chars)
        <textarea name="plan_rollback" required minlength="20" rows="3"
          placeholder="1) Detener servicio. 2) Restaurar backup. 3) Reaplicar versión anterior."></textarea>
      </label>
      <div class="full row">
        <button type="submit">Crear despliegue</button>
        <button type="button" class="btn--ghost" data-modal-close>Cancelar</button>
      </div>
    </form>
  `;
  openModal('Nuevo despliegue', body);
  $('#formNewDespliegue').onsubmit = async (e) => {
    e.preventDefault();
    const data = formData(e.target);
    data.fecha_programada = toIsoLocal(data.fecha_programada);
    try {
      const created = await api('POST', '/despliegues/', data);
      toast('ok', 'Despliegue creado', `${created.codigo} (id #${created.id})`);
      closeModal();
      if (onSaved) onSaved();
    } catch (err) { toast('err', `Error ${err.status || ''}`, err.message); }
  };
}

async function openDespliegueDetalle(id) {
  // La API no expone GET /despliegues/{id} directo (sólo la lista y la trazabilidad).
  // Usamos la lista filtrando… o, mejor, mostramos la trazabilidad en modal.
  try {
    const tz = await api('GET', `/trazabilidad/despliegues/${id}`);
    const body = `
      <dl class="kv">
        <dt>Código</dt><dd class="mono">${esc(tz.codigo)}</dd>
        <dt>Título</dt><dd>${esc(tz.titulo)}</dd>
        <dt>Estado</dt><dd>${stateBadgeDespliegue(tz.estado)}</dd>
        <dt>Ambiente</dt><dd>${esc(tz.ambiente)}</dd>
        <dt>Fecha programada</dt><dd>${esc(fmtDate(tz.fecha_programada))}</dd>
        <dt>Solicitante</dt><dd>#${esc(tz.solicitante_id)}</dd>
        <dt>Aprobador</dt><dd>#${esc(tz.aprobador_id)}</dd>
        <dt>Componentes</dt><dd>${esc(tz.total_componentes)}</dd>
        <dt>Incidencias</dt><dd>${esc(tz.total_incidencias)}</dd>
        <dt>Creado</dt><dd class="muted">${esc(fmtDate(tz.created_at))}</dd>
        <dt>Actualizado</dt><dd class="muted">${esc(fmtDate(tz.updated_at))}</dd>
      </dl>
    `;
    openModal(`Despliegue #${id}`, body);
  } catch (err) {
    toast('err', 'Error al cargar', err.message);
  }
}

/* ============================================================================
 * VIEW: Componentes (gestión rápida: elegir despliegue + agregar)
 * ========================================================================== */
async function renderComponentes(main) {
  const canCreate = state.userInfo && ROL_CREAR_DESPLIEGUE.has(state.userInfo.rol);
  main.innerHTML = pageHeader({
    title: 'Componentes',
    hint: 'Artefactos técnicos asociados a un despliegue. Elige el despliegue y registra los binarios / scripts / configuraciones.',
  });

  // Listar despliegues para elegir uno
  let despliegues = [];
  try { despliegues = (await api('GET', '/despliegues/?page=1&page_size=200')).items; }
  catch (e) {}

  if (despliegues.length === 0) {
    main.insertAdjacentHTML('beforeend', `
      <div class="card empty">
        <strong>Sin despliegues</strong>
        Crea primero un despliegue en la sección <a href="#despliegues">Despliegues</a>.
      </div>`);
    return;
  }

  const select = `
    <div class="card">
      <h3>Selecciona un despliegue</h3>
      <div class="row">
        <label class="row" style="gap:8px;">
          <span class="muted">Despliegue</span>
          <select id="selDespliegue" style="min-width:340px;">
            ${despliegues.map(d => `<option value="${d.id}">#${d.id} · ${esc(d.codigo)} · ${esc(d.titulo)} · ${d.estado}</option>`).join('')}
          </select>
        </label>
        <button id="btnVer">Ver componentes</button>
        ${canCreate ? `<button class="btn--accent" id="btnAdd">+ Agregar componente</button>` : ''}
      </div>
    </div>
    <div id="componentesArea"></div>
  `;
  main.insertAdjacentHTML('beforeend', select);

  async function show() {
    const id = Number($('#selDespliegue').value);
    $('#componentesArea').innerHTML = `<div class="card"><span class="loading"></span> Cargando…</div>`;
    try {
      const tz = await api('GET', `/trazabilidad/despliegues/${id}`);
      const cont = $('#componentesArea');
      cont.innerHTML = '';
      const card = document.createElement('div');
      card.className = 'card';
      card.innerHTML = `
        <h3>Componentes del despliegue <span class="mono">${esc(tz.codigo)}</span>
          <span class="muted" style="font-weight:400;font-size:13px">(${tz.total_componentes})</span>
        </h3>
        ${tz.componentes.length === 0
          ? `<div class="empty"><strong>Sin componentes</strong>Agrega el primer artefacto técnico.</div>`
          : `<div class="table-wrap"><table>
               <thead><tr><th>ID</th><th>Nombre</th><th>Versión</th><th>Tipo</th><th>Ruta</th><th>Checksum (SHA-256)</th></tr></thead>
               <tbody>${tz.componentes.map(c => `
                 <tr>
                   <td class="mono">#${c.id}</td>
                   <td>${esc(c.nombre)}</td>
                   <td class="mono">${esc(c.version)}</td>
                   <td>${badge(c.tipo, 'info')}</td>
                   <td class="mono" style="max-width:260px;word-break:break-all">${esc(c.ruta_almacenamiento)}</td>
                   <td class="mono" style="max-width:180px;word-break:break-all;font-size:11px;">${esc(c.checksum_sha256)}</td>
                 </tr>`).join('')}
               </tbody>
             </table></div>`
        }
      `;
      cont.appendChild(card);
    } catch (err) { toast('err', 'Error', err.message); }
  }

  $('#btnVer').onclick = show;
  $('#selDespliegue').onchange = show;
  if (canCreate) {
    $('#btnAdd').onclick = () => openComponenteModal(Number($('#selDespliegue').value), show);
  }
  show();
}

function openComponenteModal(despliegueId, onSaved) {
  if (!state.userInfo || !ROL_CREAR_DESPLIEGUE.has(state.userInfo.rol)) {
    toast('warn', 'Rol insuficiente', 'Se requiere JEFE_PROYECTO o DESARROLLO.');
    return;
  }
  const body = `
    <form id="formNewComp" class="grid">
      <label>Despliegue ID <input name="despliegue_id" type="number" min="1" required value="${despliegueId}"></label>
      <label>Tipo
        <select name="tipo">
          ${ENUMS.tipoComponente.map(t => `<option>${t}</option>`).join('')}
        </select>
      </label>
      <label class="full">Nombre <input name="nombre" required value="migracion_pagos_v4.sql"></label>
      <label>Versión <input name="version" required value="4.1.0"></label>
      <label class="full">Ruta de almacenamiento
        <input name="ruta_almacenamiento" required value="s3://itsm-artifacts/sql/migracion_pagos_v4.sql">
      </label>
      <label class="full">Checksum SHA-256 (64 hex)
        <input name="checksum_sha256" required pattern="[A-Fa-f0-9]{64}"
               value="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855">
      </label>
      <label class="full">Notas <textarea name="notas" rows="2" placeholder="opcional"></textarea></label>
      <div class="full row">
        <button type="submit">Agregar componente</button>
        <button type="button" class="btn--ghost" data-modal-close>Cancelar</button>
      </div>
    </form>
  `;
  openModal(`Nuevo componente para despliegue #${despliegueId}`, body);
  $('#formNewComp').onsubmit = async (e) => {
    e.preventDefault();
    const data = formData(e.target);
    const id = Number(data.despliegue_id);
    delete data.despliegue_id;
    try {
      const c = await api('POST', `/despliegues/${id}/componentes/`, data);
      toast('ok', 'Componente creado', `${c.nombre} v${c.version} (id #${c.id})`);
      closeModal();
      if (onSaved) onSaved();
    } catch (err) { toast('err', `Error ${err.status || ''}`, err.message); }
  };
}

/* ============================================================================
 * VIEW: Incidencias
 * ========================================================================== */
async function renderIncidencias(main) {
  main.innerHTML = pageHeader({
    title: 'Incidencias',
    hint: 'Tickets reportados, con sus 7 filtros y PATCH con state machine.',
  });

  const f = state.filtrosIncidencias;
  const filtros = `
    <div class="toolbar">
      <div class="field"><label>Estado</label>
        <select id="fEstado"><option value="">—</option>
          ${ENUMS.estadoInc.map(s => `<option ${f.estado === s ? 'selected' : ''}>${s}</option>`).join('')}
        </select>
      </div>
      <div class="field"><label>Severidad</label>
        <select id="fSev"><option value="">—</option>
          ${ENUMS.severidad.map(s => `<option ${f.severidad === s ? 'selected' : ''}>${s}</option>`).join('')}
        </select>
      </div>
      <div class="field"><label>Asignado a ID</label>
        <input id="fAsig" type="number" min="1" value="${f.asignado_a_id || ''}">
      </div>
      <div class="field"><label>Reportado por ID</label>
        <input id="fRep" type="number" min="1" value="${f.reportado_por_id || ''}">
      </div>
      <div class="field"><label>Despliegue ID</label>
        <input id="fDesp" type="number" min="1" value="${f.despliegue_id || ''}">
      </div>
      <div class="field"><label>Desde</label>
        <input id="fDesde" type="datetime-local" value="${f.fecha_desde || ''}">
      </div>
      <div class="field"><label>Hasta</label>
        <input id="fHasta" type="datetime-local" value="${f.fecha_hasta || ''}">
      </div>
      <button class="btn" id="btnFiltrar">Aplicar</button>
      <button class="btn--ghost btn" id="btnLimpiar">Limpiar</button>
      <div class="spacer"></div>
      <button id="btnNew">+ Nueva incidencia</button>
    </div>
    <div id="listaIncidencias"><div class="card"><span class="loading"></span> Cargando…</div></div>
  `;
  main.insertAdjacentHTML('beforeend', filtros);

  function readFilters() {
    state.filtrosIncidencias = {
      estado:        $('#fEstado').value || undefined,
      severidad:     $('#fSev').value    || undefined,
      asignado_a_id:  $('#fAsig').value  || undefined,
      reportado_por_id: $('#fRep').value || undefined,
      despliegue_id:  $('#fDesp').value  || undefined,
      fecha_desde:    $('#fDesde').value ? toIsoLocal($('#fDesde').value) : undefined,
      fecha_hasta:    $('#fHasta').value ? toIsoLocal($('#fHasta').value) : undefined,
    };
  }

  async function load() {
    readFilters();
    const page = state.pagination.incidencias.page;
    const qs = new URLSearchParams({ page, page_size: 50 });
    for (const [k, v] of Object.entries(state.filtrosIncidencias)) {
      if (v) qs.set(k, v);
    }
    const data = await api('GET', `/incidencias/?${qs}`);
    render(data);
  }

  function render(data) {
    const cont = $('#listaIncidencias');
    cont.innerHTML = '';
    if (data.items.length === 0) {
      cont.innerHTML = `<div class="card empty">
        <strong>Sin resultados</strong>Ajusta los filtros o crea una nueva incidencia.
      </div>`;
      return;
    }
    const t = document.createElement('div');
    t.className = 'table-wrap';
    t.innerHTML = `
      <table>
        <thead><tr>
          <th>ID</th><th>Código</th><th>Título</th>
          <th>Severidad</th><th>Estado</th><th>Asignado</th>
          <th>Despliegue</th><th>Detectada</th><th class="right">Acciones</th>
        </tr></thead>
        <tbody>
          ${data.items.map(i => `
            <tr>
              <td class="mono">#${i.id}</td>
              <td class="mono">${esc(i.codigo)}</td>
              <td>${esc(i.titulo)}</td>
              <td>${sevBadge(i.severidad)}</td>
              <td>${stateBadgeInc(i.estado)}</td>
              <td class="muted">${i.asignado_a_id ? '#' + esc(i.asignado_a_id) : '—'}</td>
              <td class="muted">${i.despliegue_id ? '#' + esc(i.despliegue_id) : '—'}</td>
              <td class="muted">${esc(fmtDate(i.fecha_deteccion))}</td>
              <td class="row-actions right">
                <button class="btn--ghost btn btn--sm" data-action="edit" data-id="${i.id}">Editar / PATCH</button>
                ${i.despliegue_id ? `<button class="btn--ghost btn btn--sm" data-action="traz" data-id="${i.despliegue_id}">Trazabilidad</button>` : ''}
              </td>
            </tr>
          `).join('')}
        </tbody>
      </table>
      ${pagerHTML(data)}
    `;
    cont.appendChild(t);
    t.addEventListener('click', (e) => {
      const btn = e.target.closest('button');
      if (!btn) return;
      const id = Number(btn.dataset.id);
      if (btn.dataset.action === 'edit') openIncEditModal(id, load);
      else if (btn.dataset.action === 'traz') navigate(`#trazabilidad&id=${id}`);
      else if (btn.dataset.page) {
        state.pagination.incidencias.page = Number(btn.dataset.page);
        load();
      }
    });
  }

  $('#btnFiltrar').onclick = () => { state.pagination.incidencias.page = 1; load().catch(handleErr); };
  $('#btnLimpiar').onclick = () => {
    state.filtrosIncidencias = {};
    state.pagination.incidencias.page = 1;
    ['fEstado','fSev','fAsig','fRep','fDesp','fDesde','fHasta'].forEach(id => $('#'+id).value = '');
    load();
  };
  $('#btnNew').onclick = () => openIncCreateModal(load);

  await load().catch(handleErr);
}

function handleErr(err) { toast('err', `Error ${err.status || ''}`, err.message); }

function openIncCreateModal(onSaved) {
  if (!state.userId) { toast('warn', 'Sin usuario', 'Define X-User-Id arriba'); return; }
  const body = `
    <form id="formNewInc" class="grid">
      <label>Código <input name="codigo" required pattern="[A-Z0-9_\\-]+" value="INC-${new Date().getFullYear()}-${Math.floor(Math.random()*9000+1000)}"></label>
      <label>Severidad
        <select name="severidad">${ENUMS.severidad.map(s => `<option ${s==='ALTA'?'selected':''}>${s}</option>`).join('')}</select>
      </label>
      <label class="full">Título <input name="titulo" required minlength="5" placeholder="Caída del portal de transferencias"></label>
      <label>Asignado a ID (opcional) <input name="asignado_a_id" type="number" min="1"></label>
      <label>Despliegue ID (opcional) <input name="despliegue_id" type="number" min="1"></label>
      <label class="full">Componente ID (opcional) <input name="componente_id" type="number" min="1"></label>
      <label class="full">Descripción (mín. 10 chars)
        <textarea name="descripcion" required minlength="10" rows="3" placeholder="Detalle del problema, hora de detección, impacto, etc."></textarea>
      </label>
      <p class="muted full" style="font-size:12px;margin:0;">
        <span class="badge brand">${esc(state.userInfo?.rol || '?')}</span>
        Reportado por <code>X-User-Id=${esc(state.userId)}</code> — se toma de la cabecera, no del body.
      </p>
      <div class="full row">
        <button type="submit">Reportar incidencia</button>
        <button type="button" class="btn--ghost" data-modal-close>Cancelar</button>
      </div>
    </form>
  `;
  openModal('Nueva incidencia', body);
  $('#formNewInc').onsubmit = async (e) => {
    e.preventDefault();
    const data = formData(e.target);
    ['asignado_a_id', 'despliegue_id', 'componente_id'].forEach((k) => {
      if (!data[k]) delete data[k];
      else data[k] = Number(data[k]);
    });
    try {
      const inc = await api('POST', '/incidencias/', data);
      toast('ok', 'Incidencia creada', `${inc.codigo} (id #${inc.id})`);
      closeModal();
      if (onSaved) onSaved();
    } catch (err) { toast('err', `Error ${err.status || ''}`, err.message); }
  };
}

async function openIncEditModal(id, onSaved) {
  let inc;
  try {
    // No hay GET /incidencias/{id}; lo obtenemos filtrando por id en la lista.
    // Como filtro, esto es feo. Mejor: cargamos una página y buscamos.
    // Truco: usamos reportado_por_id o el id con un hack no soportado. Mejor:
    // Hacemos una llamada a la página 1 con page_size muy grande.
    const r = await api('GET', `/incidencias/?page=1&page_size=200`);
    inc = r.items.find((x) => x.id === id);
    if (!inc) throw new ApiError(404, 'not_found', 'No se encontró la incidencia.');
  } catch (err) { toast('err', 'Error', err.message); return; }

  const terminal = inc.estado === 'CERRADA' || inc.estado === 'CANCELADA';
  const userRol  = state.userInfo?.rol;
  const canEstado = !terminal && ROL_RESTRINGIDO_INC.has(userRol);
  const transiciones = TRANSICIONES_INC[inc.estado] || [];
  const estadoOpts = [inc.estado, ...transiciones].map(s => `<option ${s === inc.estado ? 'selected' : ''}>${s}</option>`).join('');

  const body = `
    <form id="formEditInc" class="grid">
      <label>Código <input value="${esc(inc.codigo)}" disabled></label>
      <label>Severidad
        <select name="severidad">${ENUMS.severidad.map(s => `<option ${s===inc.severidad?'selected':''}>${s}</option>`).join('')}</select>
      </label>
      <label class="full">Título <input name="titulo" required minlength="5" value="${esc(inc.titulo)}"></label>
      <label>Estado
        <select name="estado" ${!canEstado ? 'disabled' : ''}>
          ${estadoOpts}
        </select>
      </label>
      <label>Asignado a ID
        <input name="asignado_a_id" type="number" min="1" value="${inc.asignado_a_id ?? ''}" ${!canEstado ? 'disabled' : ''}>
      </label>
      <label>Despliegue ID <input name="despliegue_id" type="number" min="1" value="${inc.despliegue_id ?? ''}"></label>
      <label>Componente ID <input name="componente_id" type="number" min="1" value="${inc.componente_id ?? ''}"></label>
      <label class="full">Descripción <textarea name="descripcion" required minlength="10" rows="3">${esc(inc.descripcion)}</textarea></label>
      <p class="muted full" style="font-size:12px;margin:0;">
        ${terminal
          ? `<span class="badge muted">Terminal</span> Estado inmutable.`
          : canEstado
            ? `Tu rol <code>${esc(userRol)}</code> permite cambiar estado y asignado.`
            : `Tu rol <code>${esc(userRol || '?')}</code> <strong>NO</strong> puede cambiar estado ni asignado.`
        }
      </p>
      <div class="full row">
        <button type="submit">Guardar cambios</button>
        <button type="button" class="btn--ghost" data-modal-close>Cancelar</button>
      </div>
    </form>
  `;
  openModal(`Editar incidencia #${id}`, body);
  $('#formEditInc').onsubmit = async (e) => {
    e.preventDefault();
    const fd = formData(e.target);
    const patch = {};
    if (fd.severidad && fd.severidad !== inc.severidad) patch.severidad = fd.severidad;
    if (fd.titulo && fd.titulo !== inc.titulo) patch.titulo = fd.titulo;
    if (fd.descripcion && fd.descripcion !== inc.descripcion) patch.descripcion = fd.descripcion;
    if (canEstado) {
      if (fd.estado && fd.estado !== inc.estado) patch.estado = fd.estado;
      const aId = fd.asignado_a_id ? Number(fd.asignado_a_id) : null;
      if (aId !== (inc.asignado_a_id || null)) patch.asignado_a_id = aId;
    }
    const dId = fd.despliegue_id ? Number(fd.despliegue_id) : null;
    if (dId !== (inc.despliegue_id || null)) patch.despliegue_id = dId;
    const cId = fd.componente_id ? Number(fd.componente_id) : null;
    if (cId !== (inc.componente_id || null)) patch.componente_id = cId;

    if (Object.keys(patch).length === 0) { toast('warn', 'Sin cambios', 'No modificaste nada.'); return; }
    try {
      await api('PATCH', `/incidencias/${id}`, patch);
      toast('ok', 'Incidencia actualizada', `#${id}`);
      closeModal();
      if (onSaved) onSaved();
    } catch (err) { toast('err', `Error ${err.status || ''}`, err.message); }
  };
}

/* ============================================================================
 * VIEW: Trazabilidad 360°
 * ========================================================================== */
async function renderTrazabilidad(main) {
  main.innerHTML = pageHeader({
    title: 'Trazabilidad 360°',
    hint: 'Vista analítica de un despliegue: cabecera, componentes y todas las incidencias asociadas.',
  });

  // Permitir preselección por ?id=NN en el hash
  const hash = location.hash.split('?')[1] || '';
  const qs = new URLSearchParams(hash);
  const presetId = qs.get('id') || '';

  const form = `
    <div class="card">
      <form id="formTz" class="row">
        <label>
          <span class="muted">ID de despliegue</span>
          <input id="tzId" type="number" min="1" required value="${esc(presetId)}" style="width:160px;">
        </label>
        <button type="submit">Consultar</button>
      </form>
    </div>
    <div id="tzResult"></div>
  `;
  main.insertAdjacentHTML('beforeend', form);

  $('#formTz').onsubmit = async (e) => {
    e.preventDefault();
    const id = Number($('#tzId').value);
    $('#tzResult').innerHTML = `<div class="card"><span class="loading"></span> Cargando…</div>`;
    try {
      const tz = await api('GET', `/trazabilidad/despliegues/${id}`);
      renderTz(tz);
    } catch (err) { $('#tzResult').innerHTML = ''; toast('err', `Error ${err.status || ''}`, err.message); }
  };
  if (presetId) $('#formTz').requestSubmit();

  function renderTz(tz) {
    const cont = $('#tzResult');
    cont.innerHTML = '';
    const head = document.createElement('div');
    head.className = 'tz-head';
    head.innerHTML = `
      <div>
        <h3>${esc(tz.titulo)} <span class="muted" style="font-weight:400;opacity:.7;font-size:14px">· ${esc(tz.codigo)}</span></h3>
        <div class="meta">
          <span><strong>ID:</strong> #${esc(tz.id)}</span>
          <span><strong>Estado:</strong> ${tz.estado}</span>
          <span><strong>Ambiente:</strong> ${esc(tz.ambiente)}</span>
          <span><strong>Fecha programada:</strong> ${esc(fmtDate(tz.fecha_programada))}</span>
          <span><strong>Solicitante:</strong> #${esc(tz.solicitante_id)}</span>
          <span><strong>Aprobador:</strong> #${esc(tz.aprobador_id)}</span>
        </div>
      </div>
      <div class="row">
        <button class="btn--ghost btn btn--sm" id="btnExportar">Exportar JSON</button>
      </div>
    `;
    cont.appendChild(head);

    const compSec = document.createElement('div');
    compSec.className = 'tz-section';
    compSec.innerHTML = `
      <h4>Componentes <span class="count">${tz.total_componentes}</span></h4>
      ${tz.componentes.length === 0
        ? `<div class="empty"><strong>Sin componentes</strong>Este despliegue aún no tiene artefactos.</div>`
        : `<div class="table-wrap"><table>
             <thead><tr><th>ID</th><th>Nombre</th><th>Versión</th><th>Tipo</th><th>Ruta</th><th>Checksum (SHA-256)</th></tr></thead>
             <tbody>${tz.componentes.map(c => `
               <tr>
                 <td class="mono">#${c.id}</td>
                 <td>${esc(c.nombre)}</td>
                 <td class="mono">${esc(c.version)}</td>
                 <td>${badge(c.tipo, 'info')}</td>
                 <td class="mono" style="max-width:280px;word-break:break-all">${esc(c.ruta_almacenamiento)}</td>
                 <td class="mono" style="max-width:160px;word-break:break-all;font-size:11px;">${esc(c.checksum_sha256)}</td>
               </tr>`).join('')}
             </tbody>
           </table></div>`
      }
    `;
    cont.appendChild(compSec);

    const incSec = document.createElement('div');
    incSec.className = 'tz-section';
    incSec.innerHTML = `
      <h4>Incidencias asociadas <span class="count">${tz.total_incidencias}</span></h4>
      ${tz.incidencias.length === 0
        ? `<div class="empty"><strong>Sin incidencias</strong>Nadie ha reportado problemas contra este despliegue.</div>`
        : `<div class="table-wrap"><table>
             <thead><tr><th>ID</th><th>Código</th><th>Título</th><th>Severidad</th><th>Estado</th><th>Detectada</th></tr></thead>
             <tbody>${tz.incidencias.map(i => `
               <tr>
                 <td class="mono">#${i.id}</td>
                 <td class="mono">${esc(i.codigo)}</td>
                 <td>${esc(i.titulo)}</td>
                 <td>${sevBadge(i.severidad)}</td>
                 <td>${stateBadgeInc(i.estado)}</td>
                 <td class="muted">${esc(fmtDate(i.fecha_deteccion))}</td>
               </tr>`).join('')}
             </tbody>
           </table></div>`
      }
    `;
    cont.appendChild(incSec);

    $('#btnExportar').onclick = () => {
      const blob = new Blob([JSON.stringify(tz, null, 2)], { type: 'application/json' });
      const url  = URL.createObjectURL(blob);
      const a    = document.createElement('a');
      a.href = url; a.download = `trazabilidad_${tz.codigo}.json`;
      a.click();
      URL.revokeObjectURL(url);
    };
  }
}

/* ============================================================================
 * VIEW: Usuarios
 * ========================================================================== */
async function renderUsuarios(main) {
  const canCreate = state.userInfo && ROL_CREAR_USUARIO.has(state.userInfo.rol);
  main.innerHTML = pageHeader({
    title: 'Usuarios',
    hint: 'Listado paginado. La creación está restringida al rol JEFE_PROYECTO.',
    actions: [canCreate ? `<button id="btnNewUser">+ Nuevo usuario</button>` : ''],
  });

  const cont = document.createElement('div');
  cont.id = 'usuariosList';
  cont.innerHTML = `<div class="card"><span class="loading"></span> Cargando…</div>`;
  main.appendChild(cont);

  async function load() {
    const page = state.pagination.usuarios.page;
    const qs = new URLSearchParams({ page, page_size: 50 });
    const data = await api('GET', `/usuarios/?${qs}`);
    render(data);
  }

  function render(data) {
    cont.innerHTML = '';
    if (data.items.length === 0) {
      cont.innerHTML = `<div class="card empty">
        <strong>Sin usuarios</strong>Aún no hay usuarios registrados.
      </div>`;
      return;
    }
    const t = document.createElement('div');
    t.className = 'table-wrap';
    t.innerHTML = `
      <table>
        <thead><tr>
          <th>ID</th><th>Nombre</th><th>Email</th><th>Rol</th>
          <th>Departamento</th><th>Activo</th><th>Creado</th>
        </tr></thead>
        <tbody>
          ${data.items.map(u => `
            <tr>
              <td class="mono">#${u.id}</td>
              <td>${esc(u.nombre)}</td>
              <td class="mono">${esc(u.email)}</td>
              <td>${rolBadge(u.rol)}</td>
              <td>${esc(u.departamento || '—')}</td>
              <td>${u.activo ? badge('ACTIVO','ok') : badge('INACTIVO','err')}</td>
              <td class="muted">${esc(fmtDate(u.created_at))}</td>
            </tr>
          `).join('')}
        </tbody>
      </table>
      ${pagerHTML(data)}
    `;
    cont.appendChild(t);
    t.addEventListener('click', (e) => {
      const btn = e.target.closest('button');
      if (btn && btn.dataset.page) {
        state.pagination.usuarios.page = Number(btn.dataset.page);
        load();
      }
    });
  }

  if (canCreate) {
    $('#btnNewUser').onclick = () => openUserCreateModal(load);
  }

  await load().catch(handleErr);
}

function openUserCreateModal(onSaved) {
  if (!state.userInfo || !ROL_CREAR_USUARIO.has(state.userInfo.rol)) {
    toast('warn', 'Rol insuficiente', 'Se requiere JEFE_PROYECTO.'); return;
  }
  const body = `
    <form id="formNewUser" class="grid">
      <label>Nombre <input name="nombre" required minlength="2"></label>
      <label>Email <input name="email" type="email" required></label>
      <label>Rol
        <select name="rol">${ENUMS.rol.map(r => `<option>${r}</option>`).join('')}</select>
      </label>
      <label>Departamento <input name="departamento" placeholder="TI, Calidad, etc."></label>
      <div class="full row">
        <button type="submit">Crear usuario</button>
        <button type="button" class="btn--ghost" data-modal-close>Cancelar</button>
      </div>
    </form>
  `;
  openModal('Nuevo usuario', body);
  $('#formNewUser').onsubmit = async (e) => {
    e.preventDefault();
    const data = formData(e.target);
    try {
      const u = await api('POST', '/usuarios/', data);
      toast('ok', 'Usuario creado', `${u.nombre} (id #${u.id})`);
      closeModal();
      if (onSaved) onSaved();
    } catch (err) { toast('err', `Error ${err.status || ''}`, err.message); }
  };
}

/* ============================================================================
 * VIEW: API Docs
 * ========================================================================== */
function renderApiDocs(main) {
  const base = API_BASE || location.origin;
  const docs = [
    { m: 'GET',   p: '/',                   d: 'Landing HTML del servicio' },
    { m: 'GET',   p: '/health',             d: 'Health check (status, version, environment)' },
    { m: 'GET',   p: '/openapi.json',       d: 'Esquema OpenAPI' },
    { m: 'GET',   p: '/docs',               d: 'Swagger UI' },
    { m: 'GET',   p: '/redoc',              d: 'ReDoc' },
    { m: 'POST',  p: '/despliegues/',       d: 'Crear despliegue (JEFE_PROYECTO o DESARROLLO)' },
    { m: 'GET',   p: '/despliegues/',       d: 'Listar despliegues (paginado, filtro estado)' },
    { m: 'POST',  p: '/despliegues/{id}/componentes/', d: 'Agregar componente a un despliegue' },
    { m: 'POST',  p: '/incidencias/',       d: 'Reportar incidencia (cualquier usuario)' },
    { m: 'GET',   p: '/incidencias/',       d: 'Listar incidencias (paginado, 7 filtros)' },
    { m: 'PATCH', p: '/incidencias/{id}',   d: 'Actualizar parcialmente (state machine)' },
    { m: 'GET',   p: '/trazabilidad/despliegues/{id}', d: 'Vista 360°' },
    { m: 'POST',  p: '/usuarios/',          d: 'Crear usuario (JEFE_PROYECTO)' },
    { m: 'GET',   p: '/usuarios/',          d: 'Listar usuarios (paginado)' },
  ];
  main.innerHTML = pageHeader({
    title: 'API Docs',
    hint: 'Documentación interactiva y referencia de endpoints.',
  }) + `
    <div class="card">
      <h3>Documentación interactiva</h3>
      <div class="api-doc">
        <a href="${base}/docs" target="_blank" rel="noopener">
          <span class="method get">GET</span> <strong>/docs</strong> — Swagger UI (probar endpoints)
        </a>
        <a href="${base}/redoc" target="_blank" rel="noopener">
          <span class="method get">GET</span> <strong>/redoc</strong> — ReDoc (documentación legible)
        </a>
        <a href="${base}/openapi.json" target="_blank" rel="noopener">
          <span class="method get">GET</span> <strong>/openapi.json</strong> — Esquema OpenAPI
        </a>
      </div>
    </div>
    <div class="card">
      <h3>Referencia rápida</h3>
      <div class="table-wrap">
        <table>
          <thead><tr><th>Método</th><th>Ruta</th><th>Descripción</th></tr></thead>
          <tbody>
            ${docs.map(d => `
              <tr>
                <td><span class="method ${esc(d.m.toLowerCase())}">${esc(d.m)}</span></td>
                <td class="mono">${esc(d.p)}</td>
                <td>${esc(d.d)}</td>
              </tr>`).join('')}
          </tbody>
        </table>
      </div>
    </div>
    <div class="card">
      <h3>Autenticación</h3>
      <p>Todos los endpoints (excepto <code>/health</code> y <code>/</code>) requieren la cabecera:</p>
      <pre class="mono" style="background:#0b2a4a;color:#e3ecf8;padding:10px 12px;border-radius:6px;overflow-x:auto;">X-User-Id: 1</pre>
      <p>El servidor valida que el usuario exista y esté <code>activo=TRUE</code>. Algunas rutas requieren roles específicos:</p>
      <ul>
        <li><code>POST /despliegues/</code> y <code>POST /despliegues/{id}/componentes/</code> → <strong>JEFE_PROYECTO</strong> o <strong>DESARROLLO</strong></li>
        <li><code>POST /usuarios/</code> → <strong>JEFE_PROYECTO</strong></li>
        <li><code>PATCH /incidencias/{id}</code> cambiando <code>estado</code> o <code>asignado_a_id</code> → <strong>QA</strong>, <strong>DESARROLLO</strong> o <strong>JEFE_PROYECTO</strong></li>
      </ul>
    </div>
  `;
}

/* ============================================================================
 * Inicialización
 * ========================================================================== */
async function loadUserInfo() {
  if (!state.userId) { state.userInfo = null; return; }
  try {
    // No hay GET /usuarios/{id}; buscamos en la primera página.
    const r = await api('GET', `/usuarios/?page=1&page_size=200`);
    state.userInfo = r.items.find((u) => u.id === state.userId) || null;
  } catch (e) {
    state.userInfo = null;
  }
}

function bindGlobal() {
  // X-User-Id
  const userInput = $('#xUserId');
  userInput.value = state.userId;
  userInput.addEventListener('change', async () => {
    const n = Number(userInput.value);
    if (!n || n < 1) { toast('warn', 'X-User-Id inválido', 'Debe ser un entero positivo.'); return; }
    state.userId = n;
    localStorage.setItem(LS_USER_KEY, String(n));
    await refreshAfterUserChange();
  });

  window.addEventListener('hashchange', render);
}

async function refreshAfterUserChange() {
  await loadUserInfo();
  if (state.userInfo) {
    toast('ok', 'Usuario activo', `#${state.userId} · ${state.userInfo.nombre} (${state.userInfo.rol})`);
  } else {
    toast('warn', 'Usuario no encontrado', `El id ${state.userId} no existe o la API no responde.`);
  }
  render();
}

document.addEventListener('DOMContentLoaded', async () => {
  bindGlobal();
  await checkHealth();
  await loadUserInfo();
  render();
});
