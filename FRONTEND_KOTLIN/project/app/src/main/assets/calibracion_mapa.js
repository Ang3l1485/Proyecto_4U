// Mapa de la calibración de longitud de paso (vista 7.3b): el admin marca el tramo A → B.
// Puente web → app (CalibracionBridge): listo() (lo llama ESTA página al final: MapaBase no lo hace),
// toque(lat, lng), puntoMovido(extremo, lat, lng).
// App → web: setCentro(lat, lng, zoom), setPuntos(texto), setBloqueado(bool).
(function () {
  'use strict';

  const base = MapaBase.iniciar({ puente: 'CalibracionBridge' });
  if (!base.leaflet) return;

  const map = MapaBase.crearMapa({ centro: [6.2006, -75.5783], zoom: 18, maxZoom: 21 }); // EAFIT, aproximado
  const mapaEl = document.getElementById('map');

  let bloqueado = false;
  let arrastrando = false;
  const marcadores = { A: null, B: null };
  let linea = null;
  let demo = { A: null, B: null }; // solo sin puente (navegador de escritorio)

  // Los pines llevan sus estilos EN LÍNEA: no dependen de que el HTML defina `.pin`.
  const TAM = 40;
  const COLOR = { A: '#2EE887', B: '#8B6BFF' };       // los de .pin-a / .pin-b del HTML
  const TEXTO = { A: '#04210F', B: '#FFFFFF' };

  function icono(extremo) {
    const estilo =
      'width:' + TAM + 'px;height:' + TAM + 'px;box-sizing:border-box;border-radius:50%;' +
      'background:' + COLOR[extremo] + ';border:3px solid #fff;color:' + TEXTO[extremo] + ';' +
      'font:700 18px/34px system-ui,sans-serif;text-align:center;' +
      'box-shadow:0 2px 8px rgba(0,0,0,.6);';
    return L.divIcon({
      className: '', // sin la caja blanca por defecto de Leaflet
      html: '<div class="pin pin-' + extremo.toLowerCase() + '" style="' + estilo + '"></div>',
      iconSize: [TAM, TAM],
      iconAnchor: [TAM / 2, TAM / 2],
    });
  }

  function crearMarcador(extremo, ll) {
    const m = L.marker(ll, {
      draggable: !bloqueado,
      icon: icono(extremo),
      keyboard: false,
      zIndexOffset: 1000, // por encima de la línea y de las teselas
    });
    m.on('dragstart', function () { arrastrando = true; });
    m.on('drag', function () { dibujarLinea(); });
    m.on('dragend', function () {
      arrastrando = false;
      const p = m.getLatLng();
      if (!base.call('puntoMovido', extremo, p.lat, p.lng)) {
        demo[extremo] = { lat: p.lat, lng: p.lng };
      }
    });
    m.addTo(map);
    // La letra va con textContent (nunca innerHTML con datos).
    const pin = m.getElement() && m.getElement().querySelector('.pin');
    if (pin) pin.textContent = extremo;
    return m;
  }

  function textoDistancia(m) {
    return (Math.round(m * 10) / 10).toFixed(1).replace('.', ',') + ' m';
  }

  function dibujarLinea() {
    if (linea) { map.removeLayer(linea); linea = null; }
    if (marcadores.A && marcadores.B) {
      const a = marcadores.A.getLatLng();
      const b = marcadores.B.getLatLng();
      linea = L.polyline([a, b], {
        color: '#6366f1', weight: 4, dashArray: '8 8', interactive: false,
      }).addTo(map);
      // Distancia sobre la línea (texto calculado aquí, no viene de datos externos).
      linea.bindTooltip(textoDistancia(map.distance(a, b)), {
        permanent: true, direction: 'center', opacity: 0.95,
      });
    }
  }

  function poner(extremo, p) {
    const actual = marcadores[extremo];
    if (!p) {
      if (actual) { map.removeLayer(actual); marcadores[extremo] = null; }
      return;
    }
    const ll = [p.lat, p.lng];
    if (actual) actual.setLatLng(ll);
    else marcadores[extremo] = crearMarcador(extremo, ll);
  }

  // texto = '{"a": {"lat": .., "lng": ..} | null, "b": ... }'
  window.setPuntos = function (texto) {
    console.log('setPuntos recibido: ' + texto); // diagnóstico: llega a Logcat (tag CalibracionMapa)
    // Con un marcador arrastrándose, el eco de la app haría temblar el pin: se ignora.
    if (arrastrando) return;
    let d;
    try { d = JSON.parse(texto); } catch (e) { console.log('setPuntos: JSON inválido'); return; }
    const habiaAmbos = !!(marcadores.A && marcadores.B);
    poner('A', d.a);
    poner('B', d.b);
    dibujarLinea();
    if (!habiaAmbos && marcadores.A && marcadores.B) {
      map.fitBounds(L.latLngBounds(marcadores.A.getLatLng(), marcadores.B.getLatLng()),
        { padding: [48, 48], maxZoom: 20 });
    }
    window.setBloqueado(bloqueado); // los marcadores nuevos heredan el bloqueo actual
  };

  window.setBloqueado = function (valor) {
    bloqueado = !!valor;
    mapaEl.classList.toggle('bloqueado', bloqueado);
    ['A', 'B'].forEach(function (k) {
      const m = marcadores[k];
      if (!m) return;
      if (bloqueado) m.dragging.disable(); else m.dragging.enable();
    });
  };

  window.setCentro = function (lat, lng, zoom) {
    map.setView([lat, lng], zoom || map.getZoom());
  };

  map.on('click', function (e) {
    console.log('toque en el mapa: ' + e.latlng.lat + ', ' + e.latlng.lng + (bloqueado ? ' (bloqueado)' : ''));
    if (bloqueado) return;
    if (base.call('toque', e.latlng.lat, e.latlng.lng)) return;
    // Modo demo (sin app): primero A, luego B.
    const k = !demo.A ? 'A' : (!demo.B ? 'B' : null);
    if (k) {
      demo[k] = { lat: e.latlng.lat, lng: e.latlng.lng };
      window.setPuntos(JSON.stringify({ a: demo.A, b: demo.B }));
    }
  });

  // Avisa a la app de que el mapa ya existe. Hasta entonces Kotlin NO envía setCentro, setPuntos ni
  // setBloqueado (`mapa.listo` sigue en false). Sin puente (navegador de escritorio) devuelve false.
  const conPuente = base.call('listo');
  console.log('calibracion_mapa: listo() ' + (conPuente ? 'enviado a la app' : 'sin puente (modo demo)'));
})();