/* Bitácora GRM — frontend minimalista. Consume la API REST (configurable). */
const API_BASE = (location.hostname === "127.0.0.1" || location.hostname === "localhost")
  ? "http://127.0.0.1:8000"
  : "";  // en deploy, mismo origen

const $ = (id) => document.getElementById(id);

async function call(method, path, body) {
  const opts = { method, headers: { "Content-Type": "application/json" } };
  if (body) opts.body = JSON.stringify(body);
  const r = await fetch(API_BASE + path, opts);
  const text = await r.text();
  let parsed; try { parsed = JSON.parse(text); } catch { parsed = text; }
  return { ok: r.ok, status: r.status, data: parsed };
}

function show(target, payload, okOverride) {
  const el = $(target);
  const isOk = okOverride ?? (payload.status >= 200 && payload.status < 300);
  el.textContent = `HTTP ${payload.status}\n` + JSON.stringify(payload.data, null, 2);
  el.style.borderLeft = `4px solid ${isOk ? "var(--ok)" : "var(--err)"}`;
}

async function checkHealth() {
  const box = $("health");
  try {
    const r = await call("GET", "/health");
    if (r.ok) {
      box.className = "health-box ok";
      box.textContent = `✔ ${r.data.status} · versión ${r.data.version} · ${r.data.timestamp}`;
    } else {
      box.className = "health-box err";
      box.textContent = `✘ Health check devolvió HTTP ${r.status}`;
    }
  } catch (e) {
    box.className = "health-box err";
    box.textContent = `✘ No se puede contactar la API en ${API_BASE || "(mismo origen)"}/health. ¿Está levantada uvicorn?`;
  }
}

function formData(form) {
  const fd = new FormData(form);
  const obj = {};
  for (const [k, v] of fd.entries()) {
    if (v === "" || v == null) continue;
    obj[k] = v;
  }
  return obj;
}

document.addEventListener("DOMContentLoaded", () => {
  checkHealth();

  $("form-despliegue").addEventListener("submit", async (e) => {
    e.preventDefault();
    const body = formData(e.target);
    const r = await call("POST", "/despliegues/", body);
    show("out-despliegue", r);
  });

  $("form-componente").addEventListener("submit", async (e) => {
    e.preventDefault();
    const body = formData(e.target);
    const id = body.despliegue_id;
    delete body.despliegue_id;
    const r = await call("POST", `/despliegues/${id}/componentes/`, body);
    show("out-componente", r);
  });

  $("form-incidencia").addEventListener("submit", async (e) => {
    e.preventDefault();
    const body = formData(e.target);
    ["asignado_a_id", "despliegue_id", "componente_id"].forEach((k) => {
      if (body[k] === "" || body[k] == null) delete body[k];
    });
    const r = await call("POST", "/incidencias/", body);
    show("out-incidencia", r);
  });

  $("form-trazabilidad").addEventListener("submit", async (e) => {
    e.preventDefault();
    const id = e.target.despliegue_id.value;
    const r = await call("GET", `/trazabilidad/despliegues/${id}`);
    show("out-trazabilidad", r);
  });
});
