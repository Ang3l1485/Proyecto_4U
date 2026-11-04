// mapa_base.js — Infraestructura común de las páginas de mapa (editor, detalle de video, y el helper del puente en app.js).
// Se carga DESPUÉS de Leaflet y ANTES del script de cada página. No hace nada al cargarse: cada página llama a
// `MapaBase.iniciar({ puente: 'NombreDelPuente' })` (app.js solo usa `MapaBase.puente`).
(function () {
'use strict';
const $ = (id) => document.getElementById(id);
const ic = (n) => `<svg class="ic"><use href="#i-${n}"/></svg>`;   // icono del sprite del HTML
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

// ── Puente con Kotlin ──────────────────────────
// `call(fn, ...args)` llama a window[nombre][fn](...args) y devuelve true; si no hay puente (navegador) devuelve false,
// y la página usa sus datos de demo. Cada llamada va en try/catch.
function puente(nombre) {
  return {
    existe: () => !!window[nombre],
    call(fn, ...a) {
      const B = window[nombre];
      if (B && B[fn]) { try { B[fn](...a); } catch (e) { console.warn(nombre + '.' + fn, e); } return true; }
      return false;
    },
  };
}

// ── Aviso y diálogos propios (el WebView no muestra window.prompt) ──
function toast(t) { const e = document.createElement('div'); e.className = 'toast'; e.textContent = t; document.body.appendChild(e); setTimeout(() => e.remove(), 2200); }

/** Con `input` pide texto y valida antes de habilitar el botón. o: { texto, label, peligro, input, valor, placeholder, valida(v), ok(v) } */
function dialogo(o) {
  const m = document.createElement('div'); m.className = 'modal';
  m.innerHTML = '<div role="alertdialog" aria-modal="true"><p class="tx"></p>' + (o.input ? '<input id="m-in" type="text" autocomplete="off" maxlength="40">' : '') +
    '<div class="acts"><button class="no">Cancelar</button><button class="si ' + (o.peligro ? 'del' : 'pri') + '"></button></div></div>';
  m.querySelector('.tx').textContent = o.texto;
  const si = m.querySelector('.si'), inp = m.querySelector('#m-in');
  si.textContent = o.label;
  const valido = () => !o.input || o.valida(inp.value.trim());
  const refrescar = () => { si.disabled = !valido(); };
  if (inp) { inp.placeholder = o.placeholder || ''; inp.value = o.valor || ''; inp.addEventListener('input', refrescar); }
  refrescar();
  m.querySelector('.no').onclick = () => m.remove();
  si.onclick = () => { if (!valido()) return; const v = inp ? inp.value.trim() : null; m.remove(); o.ok(v); };
  document.body.appendChild(m); (inp || m.querySelector('.no')).focus();
}
const confirmar = (texto, ok, label = 'Eliminar') => dialogo({ texto, label, peligro: true, ok });

// ── Medidas de la interfaz ─────────────────────
// La cabecera (#top) y el dock (#dock) cambian de alto. Se publican como --toph y --dockh para que los controles
// del mapa y los botones laterales se acomoden sin taparse.
function medir() {
  const r = document.documentElement.style, t = $('top'), d = $('dock');
  if (t) r.setProperty('--toph', t.offsetHeight + 'px');
  if (d) r.setProperty('--dockh', d.offsetHeight + 'px');
}

// ── Mapa Leaflet con la configuración común ────
// o: { centro, zoom, maxZoom }. Las teselas OSM llegan al zoom 19; con maxZoom mayor se amplían.
function crearMapa(o = {}) {
  const maxZoom = o.maxZoom || 19;
  const map = L.map('map', { center: o.centro || [6.2002, -75.5783], zoom: o.zoom || 17, zoomControl: false, attributionControl: false, maxZoom });
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxNativeZoom: 19, maxZoom }).addTo(map);
  L.control.attribution({ position: 'bottomleft', prefix: false }).addAttribution('© <a href="https://openstreetmap.org">OSM</a>').addTo(map);
  L.control.zoom({ position: 'bottomleft' }).addTo(map);
  return map;
}

// ── Arranque común ─────────────────────────────
// Deja listo, ANTES de comprobar Leaflet, todo lo que Kotlin necesita aunque el mapa no cargue:
// window.setInsets, window.onAtras (por defecto llama a salir()), el botón #btn-back y las medidas.
// Devuelve { existe, call, leaflet }. Si `leaflet` es false la página debe terminar (return): ya se avisó en pantalla.
function iniciar(o) {
  const b = puente(o.puente);
  // Alto de la barra de estado y de navegación (en dp = px CSS). Lo envía Kotlin al cargar y al cambiar.
  window.setInsets = (top, bottom) => {
    const r = document.documentElement.style;
    r.setProperty('--sat', top + 'px'); r.setProperty('--sab', bottom + 'px'); medir();
  };
  // La página sustituye este manejador por el suyo (cerrar diálogos, modos, selección…) y al final llama a salir().
  window.onAtras = () => { if (!b.call('salir')) toast('Saliste de la pantalla'); return true; };
  const back = $('btn-back'); if (back) back.onclick = () => window.onAtras();
  if (window.ResizeObserver) { const ro = new ResizeObserver(medir); ['top', 'dock'].forEach((id) => { if ($(id)) ro.observe($(id)); }); }
  window.addEventListener('resize', medir);
  medir();
  const leaflet = typeof L !== 'undefined';
  // Sin Leaflet (sin internet o sin permiso INTERNET) se avisa en pantalla en vez de dejarla vacía.
  if (!leaflet) document.body.insertAdjacentHTML('beforeend', '<div class="toast" style="bottom:50%;white-space:normal;text-align:center;max-width:80%">No se pudo cargar el mapa. Revisa tu conexión a internet.</div>');
  return { existe: b.existe, call: b.call, leaflet };
}

window.MapaBase = { $, ic, esc, puente, toast, dialogo, confirmar, medir, crearMapa, iniciar };
})();