/*
 * Mapa de la vista 7.3 — Ubicación manual inicial.
 *
 * Solo dibuja y avisa. La posición, el rumbo y las coordenadas viven en Kotlin
 * (UbicacionManualViewModel); este archivo no calcula nada.
 *
 *   web → app (UbicacionBridge):  listo() · puntoCambiado(lat, lng) · gesto(activo)
 *   app → web:  setCentro(lat, lng, zoom) · setPunto(lat, lng) · setRumbo(grados) · centrar()
 *               zoomMas() · zoomMenos() · cargarLugares(textoJson)
 *
 * Los controles (Centrar, zoom) los dibuja Compose encima del WebView.
 */
(function () {
  'use strict';

  var puente = window.UbicacionBridge || null;

  function enviar(fn) {
    var args = Array.prototype.slice.call(arguments, 1);
    try {
      if (puente && typeof puente[fn] === 'function') {
        puente[fn].apply(puente, args);
        return true;
      }
    } catch (e) {
      console.error('UbicacionBridge.' + fn + ': ' + e);
    }
    return false;
  }

  // Sin Leaflet no hay mapa: se avisa en pantalla y NO se llama a listo() (Kotlin no envía nada).
  if (typeof L === 'undefined') {
    document.getElementById('falla').hidden = false;
    document.getElementById('map').hidden = true;
    return;
  }

  // ── Íconos de las etiquetas (solo trazos propios; claves = CategoriaLugar.name) ──────
  var ICONOS = {
    BIBLIOTECA: '<path d="M3 5h7a2 2 0 0 1 2 2v12a2 2 0 0 0-2-2H3z"/><path d="M21 5h-7a2 2 0 0 0-2 2v12a2 2 0 0 1 2-2h7z"/>',
    CAFETERIA: '<path d="M5 8h11v5a4 4 0 0 1-4 4H9a4 4 0 0 1-4-4z"/><path d="M16 9h2a2 2 0 0 1 0 4h-2"/><path d="M8 3v2M12 3v2"/>',
    BANO: '<circle cx="8" cy="5" r="2"/><circle cx="16" cy="5" r="2"/><path d="M8 9v10M16 9v10M5 12h6M13 12h6"/>',
    BLOQUE: '<rect x="5" y="3" width="14" height="18" rx="1"/><path d="M9 7h2M13 7h2M9 11h2M13 11h2M10 21v-4h4v4"/>',
    AUDITORIO: '<path d="M3 7h18"/><path d="M5 7v8a7 7 0 0 0 14 0V7"/><path d="M9 12h.01M15 12h.01"/>',
    DEPORTES: '<circle cx="12" cy="12" r="8"/><path d="M12 4v16M4 12h16"/>',
    ADMINISTRACION: '<path d="M3 9l9-5 9 5"/><path d="M5 10v8M10 10v8M14 10v8M19 10v8M3 20h18"/>',
    ENTRADA: '<path d="M6 21V4h9l3 2v15"/><path d="M3 21h18M12 12h.01"/>',
    OTRO: '<circle cx="12" cy="10" r="3"/><path d="M12 21s-6-5.5-6-11a6 6 0 0 1 12 0c0 5.5-6 11-6 11z"/>'
  };

  // ── Mapa ─────────────────────────────────────────────────────────────────────────────
  var mapa = L.map('map', {
    zoomControl: false,         // el zoom lo dibuja Compose
    attributionControl: false,
    maxZoom: 19,
    zoomSnap: 0.5,
    tap: true
  }).setView([6.2006, -75.5783], 17); // Kotlin lo recoloca con setCentro()

  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
  }).addTo(mapa);
  L.control.attribution({ position: 'bottomleft', prefix: false }).addTo(mapa);

  var centroInicial = mapa.getCenter();
  var marcador = null;
  var cono = null;
  var rumbo = 0;
  var arrastrando = false;
  var ultimoEnvio = 0;
  var capaLugares = L.layerGroup().addTo(mapa);

  // ── Marcador de la persona ───────────────────────────────────────────────────────────
  function elementoMarcador() {
    var raiz = document.createElement('div');
    raiz.className = 'yo';
    raiz.innerHTML =
      '<div class="halo"></div>' +
      '<div class="cono"><svg viewBox="0 0 72 72" aria-hidden="true">' +
      '<defs><linearGradient id="gcono" x1="0" y1="1" x2="0" y2="0">' +
      '<stop offset="0" stop-color="#8B6BFF" stop-opacity=".9"/>' +
      '<stop offset="1" stop-color="#8B6BFF" stop-opacity="0"/></linearGradient></defs>' +
      '<path d="M36 36 L22 2 Q36 -4 50 2 Z" fill="url(#gcono)"/></svg></div>' +
      '<div class="punto"></div>';
    cono = raiz.querySelector('.cono');
    cono.style.transform = 'rotate(' + rumbo + 'deg)';
    return raiz;
  }

  function crearMarcador(latlng) {
    marcador = L.marker(latlng, {
      draggable: true,
      keyboard: false,
      alt: 'Tu posición de partida',
      title: 'Tu posición de partida',
      zIndexOffset: 1000,
      icon: L.divIcon({ className: '', html: elementoMarcador(), iconSize: [72, 72], iconAnchor: [36, 36] })
    }).addTo(mapa);

    marcador.on('dragstart', function () { arrastrando = true; });
    // Durante el arrastre se avisa ~10 veces por segundo para que las coordenadas se vean en vivo.
    marcador.on('drag', function () {
      var t = Date.now();
      if (t - ultimoEnvio > 90) { ultimoEnvio = t; avisarPunto(); }
    });
    marcador.on('dragend', function () { arrastrando = false; avisarPunto(); });
  }

  function avisarPunto() {
    var p = marcador.getLatLng();
    enviar('puntoCambiado', p.lat, p.lng);
  }

  function poner(lat, lng) {
    var ll = L.latLng(lat, lng);
    if (!marcador) crearMarcador(ll);
    else if (!ll.equals(marcador.getLatLng(), 1e-9)) marcador.setLatLng(ll);
  }

  // Un toque en el mapa coloca (o mueve) el marcador. Las etiquetas no son interactivas, así que
  // tocar una no mueve nada raro: coloca el punto justo donde está el dedo.
  mapa.on('click', function (e) {
    poner(e.latlng.lat, e.latlng.lng);
    avisarPunto();
  });

  // Mientras hay un dedo sobre el mapa, Kotlin bloquea el desplazamiento de la pantalla.
  var contenedor = document.getElementById('map');
  contenedor.addEventListener('touchstart', function () { enviar('gesto', true); }, { passive: true });
  ['touchend', 'touchcancel'].forEach(function (nombre) {
    contenedor.addEventListener(nombre, function (e) {
      if (!e.touches || e.touches.length === 0) enviar('gesto', false);
    }, { passive: true });
  });

  // ── Lugares de referencia ────────────────────────────────────────────────────────────
  function etiquetaLugar(lugar) {
    var caja = document.createElement('div');
    caja.className = 'lugar';
    var svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('aria-hidden', 'true');
    svg.innerHTML = ICONOS[lugar.categoria] || ICONOS.OTRO; // solo constantes de este archivo
    var texto = document.createElement('span');
    texto.textContent = lugar.nombre;                        // dato externo: siempre textContent
    caja.appendChild(svg);
    caja.appendChild(texto);
    return caja;
  }

  // ── app → web ────────────────────────────────────────────────────────────────────────
  window.setCentro = function (lat, lng, zoom) {
    centroInicial = L.latLng(lat, lng);
    mapa.setView(centroInicial, zoom, { animate: false });
  };

  // Mientras se arrastra se ignora: Kotlin devuelve el mismo punto y haría temblar el marcador.
  window.setPunto = function (lat, lng) {
    if (arrastrando) return;
    poner(lat, lng);
  };

  window.setRumbo = function (grados) {
    rumbo = grados;
    if (cono) cono.style.transform = 'rotate(' + grados + 'deg)';
  };

  window.centrar = function () {
    var destino = marcador ? marcador.getLatLng() : centroInicial;
    mapa.setView(destino, Math.max(mapa.getZoom(), 18), { animate: true });
  };

  window.zoomMas = function () { mapa.zoomIn(); };
  window.zoomMenos = function () { mapa.zoomOut(); };

  // `textoJson` llega como TEXTO entre comillas (literalJs en Kotlin): se hace JSON.parse aquí.
  window.cargarLugares = function (textoJson) {
    var lugares;
    try { lugares = JSON.parse(textoJson); } catch (e) { console.error('cargarLugares: ' + e); return; }
    capaLugares.clearLayers();
    (lugares || []).forEach(function (l) {
      if (typeof l.lat !== 'number' || typeof l.lng !== 'number') return;
      L.marker([l.lat, l.lng], {
        interactive: false,
        keyboard: false,
        icon: L.divIcon({ className: '', html: etiquetaLugar(l), iconSize: null, iconAnchor: [0, 0] })
      }).addTo(capaLugares);
    });
  };

  // ── Arranque ─────────────────────────────────────────────────────────────────────────
  if (!enviar('listo')) {
    // Modo demo en un navegador de escritorio (sin Android): sirve para iterar la interfaz.
    console.info('Sin UbicacionBridge: modo demo.');
    window.cargarLugares(JSON.stringify([
      { id: 'a', nombre: 'Biblioteca Central', categoria: 'BIBLIOTECA', lat: 6.2013, lng: -75.5780 },
      { id: 'b', nombre: 'Cafetería Principal', categoria: 'CAFETERIA', lat: 6.2002, lng: -75.5776 },
      { id: 'c', nombre: 'Bloque de los Trillizos', categoria: 'BLOQUE', lat: 6.2006, lng: -75.5791 }
    ]));
    window.setPunto(6.2006, -75.5783);
    window.setRumbo(45);
  }
})();