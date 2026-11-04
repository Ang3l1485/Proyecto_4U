// Mapa de lugares (FE-3.4): selector del punto de llegada en el formulario 7.7 (modo editable) y vista de mapa de la
// lista 7.6 (modo ver). Puente: LugarBridge (ARCHITECTURE §5.9). Página embebida en una tarjeta de Compose, como
// recoleccion_mapa: no define setInsets ni onAtras propio (Atrás lo maneja la pantalla).
(function () {
  'use strict';

  const base = MapaBase.iniciar({ puente: 'LugarBridge' });
  if (!base.leaflet) return;           // sin Leaflet: MapaBase ya avisó y nunca llamamos a listo()
  const L = window.L;

  const CENTRO_INICIAL = [6.2007, -75.5783];   // aprox. EAFIT; solo el encuadre si no hay punto ni lugares
  const ZOOM_PUNTO = 18;

  const mapa = MapaBase.crearMapa({ centro: CENTRO_INICIAL, zoom: 17, maxZoom: 21 });
  const capaLugares = L.layerGroup().addTo(mapa);

  // ── Estado ──────────────────────────────────────────────────────────────────
  let editable = false;   // true: tocar el mapa pone el alfiler (7.7); false: tocar un lugar avisa (7.6)
  let pin = null;         // L.marker arrastrable del punto de llegada
  let arrastrando = false;
  let encuadrado = false; // el primer dato encuadra el mapa una sola vez
  let lugares = [];

  const ICONO_PIN =
    '<svg viewBox="0 0 40 40" aria-hidden="true">' +
    '<path d="M20 38 C20 38 7 24 7 16 a13 13 0 0 1 26 0 C33 24 20 38 20 38Z" fill="#FF4D7D" stroke="#fff" stroke-width="2.5"/>' +
    '<circle cx="20" cy="16" r="5" fill="#fff"/></svg>';

  const num = (v) => (typeof v === 'number' && isFinite(v) ? v : null);
  const parse = (texto, porDefecto) => {
    try { return JSON.parse(texto); } catch (e) { console.error('JSON inválido: ' + e.message); return porDefecto; }
  };

  function avisarPunto() {
    if (!pin) return;
    const p = pin.getLatLng();
    base.call('puntoCambiado', p.lat, p.lng);
  }

  function dibujarLugares() {
    capaLugares.clearLayers();
    for (const l of lugares) {
      const lat = num(l.lat), lng = num(l.lng);
      if (lat === null || lng === null) continue;
      const tam = editable ? 18 : 24;
      const marker = L.marker([lat, lng], {
        icon: L.divIcon({ className: 'icono-vacio', iconSize: [tam, tam], iconAnchor: [tam / 2, tam / 2],
                          html: '<div class="lugar' + (editable ? '' : ' tocable') + '"></div>' }),
        interactive: !editable, keyboard: false,
      }).addTo(capaLugares);
      const tip = document.createElement('span');
      tip.textContent = String(l.nombre || '');   // textContent: el nombre es texto del usuario
      marker.bindTooltip(tip, { permanent: true, direction: 'bottom', offset: [0, 8], className: 'nombre' });
      if (!editable) marker.on('click', () => base.call('lugarTocado', String(l.id)));
    }
  }

  function encuadrarUnaVez() {
    if (encuadrado) return;
    if (pin) {
      mapa.setView(pin.getLatLng(), ZOOM_PUNTO, { animate: false });
      encuadrado = true;
    } else if (lugares.length) {
      window.encuadrar();
      encuadrado = true;
    }
  }

  // ── App → web ───────────────────────────────────────────────────────────────

  // true en el formulario 7.7 (alfiler), false en la lista 7.6 (lugares tocables).
  window.setModo = function (valor) {
    editable = !!valor;
    dibujarLugares();
  };

  // Lugares de contexto: texto JSON [{id, nombre, lat, lng}] (en 7.7, los demás lugares; en 7.6, todos).
  window.cargarLugares = function (texto) {
    lugares = parse(texto, []).filter((l) => l && num(l.lat) !== null && num(l.lng) !== null);
    dibujarLugares();
    encuadrarUnaVez();
  };

  // Punto de llegada. La app es la dueña del punto; mientras se arrastra se ignoran sus ecos.
  window.setPunto = function (lat, lng) {
    lat = num(lat); lng = num(lng);
    if (lat === null || lng === null) return;
    if (!pin) {
      pin = L.marker([lat, lng], {
        draggable: true, keyboard: false, title: 'Punto de llegada', zIndexOffset: 2000,
        icon: L.divIcon({ className: 'icono-vacio', iconSize: [40, 40], iconAnchor: [20, 38],
                          html: '<div class="pin">' + ICONO_PIN + '</div>' }),
      }).addTo(mapa);
      pin.on('dragstart', () => { arrastrando = true; });
      pin.on('dragend', () => { arrastrando = false; avisarPunto(); });
    } else if (!arrastrando) {
      pin.setLatLng([lat, lng]);
    }
    encuadrarUnaVez();
  };

  window.quitarPunto = function () {
    if (pin) { mapa.removeLayer(pin); pin = null; arrastrando = false; }
  };

  // Encuadra los lugares y el punto.
  window.encuadrar = function () {
    const puntos = lugares.map((l) => L.latLng(l.lat, l.lng));
    if (pin) puntos.push(pin.getLatLng());
    if (!puntos.length) return;
    if (puntos.length === 1) { mapa.setView(puntos[0], ZOOM_PUNTO, { animate: false }); return; }
    mapa.fitBounds(L.latLngBounds(puntos), { padding: [32, 32], maxZoom: ZOOM_PUNTO, animate: false });
  };

  // Tocar el mapa en modo editable pone (o mueve) el alfiler ahí.
  mapa.on('click', (e) => {
    if (!editable) return;
    if (!pin) window.setPunto(e.latlng.lat, e.latlng.lng);
    else pin.setLatLng(e.latlng);
    avisarPunto();
  });

  // ── Arranque ────────────────────────────────────────────────────────────────
  const hayPuente = base.call('listo');
  if (!hayPuente) demo();     // en un navegador de escritorio, sin app: datos de ejemplo

  function demo() {
    window.setModo(true);
    window.cargarLugares(JSON.stringify([
      { id: 'a', nombre: 'Biblioteca Central', lat: 6.2008, lng: -75.5783 },
      { id: 'b', nombre: 'Bloque 19', lat: 6.2002, lng: -75.5779 },
    ]));
    console.log('Modo demo (sin LugarBridge)');
  }
})();
