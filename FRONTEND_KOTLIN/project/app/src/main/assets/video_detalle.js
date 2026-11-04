// Detalle de video (vista 7.14) — Leaflet + OpenStreetMap en línea.
// Kotlin ⇄ Web: ver `VideoDetalleScreen.kt`. Sin puente (navegador) usa datos de demo.
(function () {
'use strict';
const base = MapaBase.iniciar({ puente: 'VideoBridge' });
if (!base.leaflet) return;   // sin Leaflet no hay mapa: la base ya avisó y dejó funcionando Atrás
const { $, ic, esc, toast, dialogo, confirmar, medir } = MapaBase;
const call = base.call, B = base.existe();   // B: hay puente (en un navegador no) → si no, datos de demo
const CARDINALES = ['N', 'NE', 'E', 'SE', 'S', 'SO', 'O', 'NO'];

// FE-4.1: `editable` (renombrar y eliminar permitidos), `nota` (por qué no) y `otrosPedidos` («Mostrar otros videos» se
// carga la primera vez que se activa).
const S = { video: null, fotos: [], sel: null, editable: true, otrosPedidos: false };

// ── Mapa ───────────────────────────────────────
// Las teselas OSM llegan al zoom 19; más allá se amplían para poder acercarse a fotos muy juntas.
const map = MapaBase.crearMapa({ maxZoom: 21 });
const capas = { ruta: L.layerGroup().addTo(map), fotos: L.layerGroup().addTo(map), otros: L.layerGroup() };
const marcas = new Map();

// ── Utilidades ─────────────────────────────────

function hav(a, b) {
  const R = 6371000, r = (x) => x * Math.PI / 180, dl = r(b.lat - a.lat), dn = r(b.lng - a.lng);
  const h = Math.sin(dl / 2) ** 2 + Math.cos(r(a.lat)) * Math.cos(r(b.lat)) * Math.sin(dn / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(h));
}
function distancia(fotos) { let t = 0; for (let i = 1; i < fotos.length; i++) t += hav(fotos[i - 1], fotos[i]); return t; }
const fmtDist = (m) => (m < 1000 ? Math.round(m) + ' m' : (m / 1000).toFixed(2) + ' km');
const fmtFecha = (f) => (f ? f.split('-').reverse().join('/') : null);

// Centra una coordenada en el área libre del mapa (entre la cabecera y el dock), no en el centro de la pantalla.
function centrarEn(ll, z) {
  const off = ($('dock').offsetHeight - $('top').offsetHeight) / 2;
  const p = map.project(ll, z).add([0, off]);
  map.setView(map.unproject(p, z), z, { animate: true });
}
function ajustar() {
  if (!S.fotos.length) return;
  const b = L.latLngBounds(S.fotos.map((f) => [f.lat, f.lng]));
  if (S.fotos.length === 1) { centrarEn(b.getCenter(), 19); return; }
  map.fitBounds(b, { paddingTopLeft: [24, $('top').offsetHeight + 16], paddingBottomRight: [24, $('dock').offsetHeight + 16], maxZoom: 20 });
}

// ── Pintar ─────────────────────────────────────
const icono = (f, i, sel) => L.divIcon({
  className: '', iconSize: [44, 44], iconAnchor: [22, 22],
  html: `<div class="ph${sel ? ' sel' : ''}">` +
    (f.rumbo == null ? '' : `<svg class="arr" viewBox="0 0 44 44" style="transform:rotate(${f.rumbo}deg)"><path d="M22 1 30 13 22 9.5 14 13Z"/></svg>`) +
    `<span>${i + 1}</span></div>`,
});

function pintar() {
  capas.fotos.clearLayers(); capas.ruta.clearLayers(); marcas.clear();
  if (S.fotos.length > 1) L.polyline(S.fotos.map((f) => [f.lat, f.lng]), { color: '#6366f1', weight: 4, opacity: .8 }).addTo(capas.ruta);
  S.fotos.forEach((f, i) => {
    const m = L.marker([f.lat, f.lng], { icon: icono(f, i, f.id === S.sel), keyboard: true, title: 'Foto ' + (i + 1), zIndexOffset: f.id === S.sel ? 1000 : 0 })
      .on('click', (e) => { L.DomEvent.stopPropagation(e); seleccionar(f.id, false); });
    m.addTo(capas.fotos); marcas.set(f.id, m);
  });
  renderTitulo(); renderTira(); renderCard();
}
function renderTitulo() {
  const v = S.video; if (!v) return;
  $('t-nombre').textContent = v.nombre;
  const n = S.fotos.length;
  $('t-meta').textContent = [v.local ? 'En este teléfono, sin subir' : null, fmtFecha(v.fecha), n === 1 ? '1 foto' : n + ' fotos',
    fmtDist(distancia(S.fotos))].filter(Boolean).join(' · ');
  const nota = $('t-nota');
  nota.textContent = v.nota || '';
  nota.classList.toggle('hidden', !v.nota);
  $('btn-ren').disabled = !S.editable;
  $('btn-del').disabled = !S.editable;
  medir();
}

// ── Selección: marcador, tira y vista previa siempre sincronizados ──
function seleccionar(id, centrar) {
  const prev = S.sel; S.sel = id;
  [prev, id].forEach((k) => {
    const i = S.fotos.findIndex((f) => f.id === k), m = marcas.get(k);
    if (m && i >= 0) { m.setIcon(icono(S.fotos[i], i, k === S.sel)); m.setZIndexOffset(k === S.sel ? 1000 : 0); }
  });
  marcarTira(); renderCard();
  const f = S.fotos.find((x) => x.id === id);
  if (centrar && f) centrarEn(L.latLng(f.lat, f.lng), Math.max(map.getZoom(), 19));
}
function renderTira() {
  const s = $('strip'); s.innerHTML = '';
  S.fotos.forEach((f, i) => {
    const b = document.createElement('button');
    b.dataset.id = f.id; b.setAttribute('aria-label', 'Foto ' + (i + 1) + ' de ' + S.fotos.length);
    b.innerHTML = `<img alt="" loading="lazy" src="${esc(f.thumb)}" onerror="this.style.visibility='hidden'"><span>${i + 1}</span>`;
    b.onclick = () => seleccionar(f.id, true);
    s.appendChild(b);
  });
  marcarTira();
}
function marcarTira() {
  $('strip').querySelectorAll('button').forEach((b) => {
    const on = b.dataset.id === S.sel;
    b.classList.toggle('sel', on); b.setAttribute('aria-pressed', on);
    if (on) b.scrollIntoView({ inline: 'center', block: 'nearest', behavior: 'smooth' });
  });
}
function renderCard() {
  const c = $('card'), i = S.fotos.findIndex((f) => f.id === S.sel), f = S.fotos[i];
  c.classList.toggle('hidden', !f);
  if (!f) { medir(); return; }
  c.innerHTML = `<button class="x" aria-label="Cerrar">${ic('x')}</button>
    <div class="c-head"><img class="c-img" alt="Vista previa de la foto ${i + 1}" src="${esc(f.thumb)}" onerror="this.style.visibility='hidden'">
      <div><h2>Foto ${i + 1} de ${S.fotos.length}</h2>
        <div class="meta"><div>${ic('pin')}<span class="pos"></span></div><div>${ic('compass')}<span class="rum"></span></div></div></div></div>
    <div class="acts"><button id="a-ver" disabled aria-label="Ver detalle: próximamente">${ic('img')}<span>Detalle (próximamente)</span></button><button class="del" id="a-del">${ic('trash')}<span>Eliminar foto</span></button></div>`;
  c.querySelector('.pos').textContent = f.lat.toFixed(6) + ', ' + f.lng.toFixed(6);
  // FE-4.1: con rumbo negativo `% 8` daba un índice negativo («undefined»): se normaliza a 0…360 antes.
  const r = f.rumbo == null ? null : ((f.rumbo % 360) + 360) % 360;
  c.querySelector('.rum').textContent = r == null ? 'Orientación: sin dato'
    : 'Orientación: ' + Math.round(r) + '° ' + CARDINALES[Math.round(r / 45) % 8];
  c.querySelector('.x').onclick = () => seleccionar(null);
  // 7.12 (Detalle de imagen) está fuera de FE-4.1: el botón queda deshabilitado.
  const del = $('a-del');
  del.disabled = !S.editable;
  del.onclick = () => confirmar('¿Eliminar esta foto? Dejará de usarse para ubicar a los usuarios.', () => eliminarFoto(f.id));
  medir();
}

// ── Acciones ───────────────────────────────────
// FE-4.1: las acciones las confirma Kotlin. Mientras el servidor responde, la app tapa el mapa con un aviso
// («Eliminando…»); si falla, muestra el error con «Reintentar» y vuelve a enviar el video tal como está (cargarVideo).
function eliminarFoto(id) {
  if (!call('eliminarFoto', id)) { toast('Foto eliminada (demo)'); }
  S.fotos = S.fotos.filter((f) => f.id !== id);   // se aplica ya; si el servidor falla, Kotlin la devuelve
  if (S.sel === id) S.sel = null;
  pintar();
  if (!S.fotos.length) {
    confirmar('Este video se quedó sin fotos. ¿Quieres eliminarlo también?', eliminarVideo, 'Eliminar video');
  }
}
// Ya no sale sola a los 900 ms: Kotlin vuelve a la lista solo cuando el servidor confirmó el borrado (202).
function eliminarVideo() {
  if (!call('eliminarVideo')) toast('Video eliminado (demo)');
}
$('btn-ren').onclick = () => {
  if (!S.video || !S.editable) return;
  dialogo({
    texto: 'Nuevo nombre del video', input: true, valor: S.video.nombre, label: 'Guardar',
    valida: (v) => v.length > 0 && v.length <= 40 && v !== S.video.nombre,
    // El nombre nuevo llega con el siguiente cargarVideo, cuando el servidor (o el disco) lo guardó.
    ok: (nombre) => { if (!call('renombrar', nombre)) { S.video.nombre = nombre; renderTitulo(); } },
  });
};
$('btn-del').onclick = () => {
  if (!S.video || !S.editable) return;
  const n = S.fotos.length;
  dialogo({
    texto: `Vas a eliminar «${S.video.nombre}» y sus ${n} fotos. Esto quitará esas fotos del sistema de ubicación y no se puede deshacer.\n\nEscribe el nombre del video para confirmar.`,
    input: true, placeholder: S.video.nombre, label: 'Eliminar video', peligro: true,
    valida: (v) => v === S.video.nombre, ok: eliminarVideo,
  });
};
map.on('click', () => seleccionar(null));
$('chk-otros').addEventListener('change', (e) => {
  if (e.target.checked && !S.otrosPedidos) {   // FE-4.1: se cargan (con tope) la primera vez que se activa
    S.otrosPedidos = true;
    if (call('pedirOtros')) toast('Cargando las fotos de otros videos…');
  }
  e.target.checked ? capas.otros.addTo(map) : capas.otros.remove();
});

// ── API para Kotlin ────────────────────────────
window.cargarVideo = (json) => {
  const v = JSON.parse(json), nuevo = !S.video || S.video.id !== v.id;
  S.video = v; S.fotos = v.fotos || []; S.editable = v.editable !== false;
  if (S.sel && !S.fotos.some((f) => f.id === S.sel)) S.sel = null;
  pintar();
  if (nuevo) ajustar();   // se encuadra solo la primera vez: editar no debe mover el mapa
};
// Fotos de los demás videos, en gris tenue, como contexto (se muestran con el conmutador). FE-4.1: llega
// {videos: [{id, fotos: [{lat, lng}]}], aviso} (antes, solo la lista); se acepta también la lista sola.
window.cargarOtros = (json) => {
  const d = JSON.parse(json), lista = Array.isArray(d) ? d : (d.videos || []);
  capas.otros.clearLayers();
  lista.forEach((v) => (v.fotos || []).forEach((f) =>
    L.circleMarker([f.lat, f.lng], { radius: 5, color: '#64748b', weight: 1, fillColor: '#64748b', fillOpacity: .6, interactive: false }).addTo(capas.otros)));
  if (!Array.isArray(d) && d.aviso) toast(d.aviso);
};
// Botón Atrás: cierra primero diálogo y selección; devuelve true si lo consumió.
window.onAtras = () => {
  const m = document.querySelector('.modal'); if (m) { m.remove(); return true; }
  if (S.sel) { seleccionar(null); return true; }
  if (!call('salir')) toast('Saliste del detalle');
  return true;
};

// ── Arranque ───────────────────────────────────
if (B) call('listo');   // Kotlin responde con setInsets / cargarVideo / cargarOtros
else cargarDemo();
function cargarDemo() {
  const pts = [[6.2017936, -75.5788621], [6.2017313, -75.5788577], [6.2016682, -75.578862], [6.2016001, -75.5788583], [6.2015529, -75.5788604], [6.2014725, -75.5788661]];
  window.cargarVideo(JSON.stringify({
    id: 'vid_0001', nombre: 'video1', fecha: '2026-10-09',
    fotos: pts.map((p, i) => ({ id: String(i + 1).padStart(4, '0'), url: '', thumb: '', lat: p[0], lng: p[1], rumbo: 180 })),
  }));
}
medir();
})();