// Mapa en vivo de la recolección (vista 7.4). Puente: RecoleccionBridge (ARCHITECTURE 11.9).
// Reutiliza MapaBase (mapa_base.js): iniciar, crearMapa y esc. No define setInsets ni onAtras propio:
// la pantalla Compose maneja Atrás (alPedirFinalizar) y las barras del sistema.
(function () {
  'use strict';

  const base = MapaBase.iniciar({ puente: 'RecoleccionBridge' });
  if (!base.leaflet) return;           // sin Leaflet: MapaBase ya avisó y nunca llamamos a listo()
  const L = window.L;

  const CENTRO_INICIAL = [6.2007, -75.5783];   // ⚠ aproximado (EAFIT); solo es el encuadre antes del primer fix
  const ZOOM_SEGUIR = 19;
  const ZOOM_MIN_CENTRAR = 18;

  const mapa = MapaBase.crearMapa({ centro: CENTRO_INICIAL, zoom: 17, maxZoom: 21 });
  if (mapa.zoomControl && mapa.zoomControl.remove) mapa.zoomControl.remove();

  // ── Capas (de abajo hacia arriba) ───────────────────────────────────────────
  const capaAlertas = L.layerGroup().addTo(mapa);
  const trayectoria = L.polyline([], { color: '#A78BFA', weight: 4, opacity: .9, lineCap: 'round', lineJoin: 'round' }).addTo(mapa);
  const capaFotos = L.layerGroup().addTo(mapa);

  // ── Estado ──────────────────────────────────────────────────────────────────
  let yo = null;                // L.marker de la posición actual
  let yoFlecha = null;          // elemento rotable dentro del marcador
  let siguiendo = true;
  let ancla = null;             // L.marker arrastrable del re-anclaje (null = modo cerrado)
  let arrastrandoAncla = false;
  let ultimoAvisoAncla = 0;
  const fotos = new Map();      // id → { marker, lat, lng }

  const ICONO_FLECHA =
    '<svg viewBox="0 0 36 36" aria-hidden="true">' +
    '<circle cx="18" cy="18" r="8" fill="#7C5CFF" stroke="#fff" stroke-width="2.5"/>' +
    '<path d="M18 2 L24 12 L12 12 Z" fill="#fff"/></svg>';
  const ICONO_ANCLA =
    '<svg viewBox="0 0 40 40" aria-hidden="true">' +
    '<path d="M20 38 C20 38 7 24 7 16 a13 13 0 0 1 26 0 C33 24 20 38 20 38Z" fill="#FF4D7D" stroke="#fff" stroke-width="2.5"/>' +
    '<circle cx="20" cy="16" r="5" fill="#fff"/></svg>';

  // ── Utilidades ──────────────────────────────────────────────────────────────
  const num = (v) => (typeof v === 'number' && isFinite(v) ? v : null);
  const parse = (texto, porDefecto) => {
    try { return JSON.parse(texto); } catch (e) { console.error('JSON inválido: ' + e.message); return porDefecto; }
  };
  const aviso = (fn, ...args) => base.call(fn, ...args);   // true si había puente

  function setSiguiendo(valor) {
    if (siguiendo === valor) return;
    siguiendo = valor;
    aviso('seguimientoCambiado', siguiendo);
  }

  // ── App → web ───────────────────────────────────────────────────────────────

  // Posición actual (PDR) y rumbo en grados 0…360.
  window.setPosicion = function (lat, lng, rumbo) {
    lat = num(lat); lng = num(lng);
    if (lat === null || lng === null) return;
    const primera = !yo;
    if (primera) {
      const icono = L.divIcon({
        className: 'icono-vacio', iconSize: [36, 36], iconAnchor: [18, 18],
        html: '<div class="yo"><div class="halo"></div><div class="flecha">' + ICONO_FLECHA + '</div></div>'
      });
      yo = L.marker([lat, lng], { icon: icono, interactive: false, keyboard: false, zIndexOffset: 1000 }).addTo(mapa);
      yoFlecha = yo.getElement().querySelector('.flecha');
    } else {
      yo.setLatLng([lat, lng]);
    }
    if (yoFlecha && num(rumbo) !== null) yoFlecha.style.transform = 'rotate(' + rumbo + 'deg)';

    if (primera) {
      mapa.setView([lat, lng], ZOOM_SEGUIR, { animate: false });
    } else if (siguiendo && !ancla) {
      mapa.panTo([lat, lng], { animate: true, duration: 0.4, noMoveStart: true });
    }
  };

  // Fotos tomadas: texto JSON [{id, lat, lng, rumbo|null}]. Se actualiza por id (el re-anclaje las mueve).
  window.cargarFotos = function (texto) {
    const lista = parse(texto, []);
    const vistos = new Set();
    for (const f of lista) {
      const lat = num(f.lat), lng = num(f.lng);
      if (lat === null || lng === null) continue;
      const id = String(f.id);
      vistos.add(id);
      const previa = fotos.get(id);
      if (previa) {
        if (previa.lat !== lat || previa.lng !== lng) {
          previa.marker.setLatLng([lat, lng]);
          previa.lat = lat; previa.lng = lng;
        }
        continue;
      }
      const marca = num(f.rumbo) !== null
        ? '<i style="transform:rotate(' + f.rumbo + 'deg)"></i>' : '';
      const marker = L.marker([lat, lng], {
        icon: L.divIcon({ className: 'icono-vacio', iconSize: [16, 16], iconAnchor: [8, 8],
                          html: '<div class="foto">' + marca + '<b></b></div>' }),
        interactive: false, keyboard: false
      }).addTo(capaFotos);
      fotos.set(id, { marker, lat, lng });
    }
    for (const [id, f] of fotos) {
      if (!vistos.has(id)) { capaFotos.removeLayer(f.marker); fotos.delete(id); }
    }
  };

  // Trayectoria: texto JSON [[lat, lng], …] (reemplaza la lista completa).
  window.cargarTrayectoria = function (texto) {
    const puntos = parse(texto, []).filter((p) => Array.isArray(p) && num(p[0]) !== null && num(p[1]) !== null);
    trayectoria.setLatLngs(puntos);
  };

  // Alertas existentes: texto JSON con los campos del editor (id, lat, lng, mensaje, tipo, prioridad, radio, activa).
  window.cargarAlertas = function (texto) {
    capaAlertas.clearLayers();
    for (const a of parse(texto, [])) {
      const lat = num(a.lat), lng = num(a.lng);
      if (lat === null || lng === null) continue;
      const activa = a.activa !== false;
      const color = activa ? '#F59E0B' : '#64748b';
      if (num(a.radio) && a.radio > 0) {
        L.circle([lat, lng], { radius: a.radio, color, weight: 1.5, fillColor: color, fillOpacity: .12, interactive: false })
          .addTo(capaAlertas);
      }
      const pin = L.marker([lat, lng], {
        icon: L.divIcon({ className: 'icono-vacio', iconSize: [22, 22], iconAnchor: [11, 11],
                          html: '<div class="alerta-pin' + (activa ? '' : ' off') + '">!</div>' }),
        keyboard: false, title: 'Alerta'
      }).addTo(capaAlertas);
      const tip = document.createElement('div');
      tip.textContent = String(a.mensaje || 'Alerta');     // textContent: el mensaje es texto del usuario
      pin.bindTooltip(tip, { direction: 'top', offset: [0, -10] });
    }
  };

  // Re-anclaje: alfiler arrastrable. El ViewModel es el dueño del punto; mientras se arrastra se ignoran sus ecos.
  window.setReanclaje = function (lat, lng) {
    lat = num(lat); lng = num(lng);
    if (lat === null || lng === null) return;
    if (!ancla) {
      ancla = L.marker([lat, lng], {
        draggable: true, keyboard: false, title: 'Punto de re-anclaje', zIndexOffset: 2000,
        icon: L.divIcon({ className: 'icono-vacio', iconSize: [40, 40], iconAnchor: [20, 38],
                          html: '<div class="ancla">' + ICONO_ANCLA + '</div>' })
      }).addTo(mapa);
      ancla.on('dragstart', () => { arrastrandoAncla = true; });
      ancla.on('drag', () => avisarAncla(false));
      ancla.on('dragend', () => { arrastrandoAncla = false; avisarAncla(true); });
      mapa.panTo([lat, lng], { animate: true });
    } else if (!arrastrandoAncla) {
      ancla.setLatLng([lat, lng]);
    }
  };

  window.quitarReanclaje = function () {
    if (ancla) { mapa.removeLayer(ancla); ancla = null; arrastrandoAncla = false; }
  };

  function avisarAncla(forzar) {
    if (!ancla) return;
    const ahora = Date.now();
    if (!forzar && ahora - ultimoAvisoAncla < 100) return;      // ~10 avisos por segundo
    ultimoAvisoAncla = ahora;
    const p = ancla.getLatLng();
    aviso('puntoCambiado', p.lat, p.lng);
  }

  // Tocar el mapa también mueve el alfiler (más fácil que arrastrarlo con un dedo).
  mapa.on('click', (e) => {
    if (!ancla) return;
    ancla.setLatLng(e.latlng);
    avisarAncla(true);
  });

  // Controles que dibuja Compose.
  window.centrar = function () {
    setSiguiendo(true);
    const destino = ancla ? ancla.getLatLng() : (yo ? yo.getLatLng() : null);
    if (destino) mapa.setView(destino, Math.max(mapa.getZoom(), ZOOM_MIN_CENTRAR), { animate: true });
  };
  window.zoomMas = function () { mapa.zoomIn(); };
  window.zoomMenos = function () { mapa.zoomOut(); };

  // FE-2.1 (vista 7.5, recorrido terminado): encuadra la trayectoria y las fotos y deja de seguir la posición.
  window.encuadrar = function () {
    const puntos = trayectoria.getLatLngs().slice();
    for (const f of fotos.values()) puntos.push(L.latLng(f.lat, f.lng));
    if (!puntos.length) return;
    setSiguiendo(false);
    mapa.fitBounds(L.latLngBounds(puntos), { padding: [24, 24], maxZoom: ZOOM_SEGUIR, animate: false });
  };

  // Si el admin arrastra el mapa con el dedo, deja de seguirlo hasta que pulse «Centrar».
  mapa.on('dragstart', () => setSiguiendo(false));

  // ── Arranque ────────────────────────────────────────────────────────────────
  const hayPuente = base.call('listo');
  if (!hayPuente) demo();     // en un navegador de escritorio, sin app: datos de ejemplo

  function demo() {
    const R = 0.00018; let t = 0; const trayecto = []; const fs = [];
    window.cargarAlertas(JSON.stringify([
      { id: 'a1', lat: CENTRO_INICIAL[0] + 0.0004, lng: CENTRO_INICIAL[1] + 0.0003, mensaje: 'Escalón sin señalizar', radio: 15, activa: true }
    ]));
    setInterval(() => {
      t += 0.12;
      const lat = CENTRO_INICIAL[0] + R * Math.sin(t), lng = CENTRO_INICIAL[1] + R * Math.cos(t);
      const rumbo = (((-t * 180 / Math.PI) + 360) % 360 + 360) % 360;
      trayecto.push([lat, lng]);
      if (trayecto.length % 6 === 0) fs.push({ id: String(fs.length + 1), lat, lng, rumbo });
      window.setPosicion(lat, lng, rumbo);
      window.cargarTrayectoria(JSON.stringify(trayecto));
      window.cargarFotos(JSON.stringify(fs));
    }, 500);
    console.log('Modo demo (sin RecoleccionBridge)');
  }
})();