// ========================================
// StepTracker — Core Application Engine
// ========================================
// Mapa Leaflet + panel de estadísticas. NO calcula la posición:
// pasos, rumbo y posición los calcula Kotlin (sensors/PdrEngine) y llegan
// por window.onNative*. Lo que el usuario toca se envía por AndroidBridge.
// ========================================

(function () {
    'use strict';

    // ── State ──────────────────────────────────
    const state = {
        map: null,
        userMarker: null,
        startMarker: null,
        trailLine: null,
        trailCoords: [],

        // Position
        startLat: null,
        startLng: null,
        currentLat: null,
        currentLng: null,
        positionSet: false,

        // Tracking
        isTracking: false,
        startTime: null,
        elapsedMs: 0,
        timerInterval: null,

        // Pasos, distancia y velocidad: los entrega Kotlin (onNativePosition)
        steps: 0,
        distanceM: 0,
        speedMps: 0,
        maxSpeedKmh: 0,

        // Acceleration (solo para la gráfica; Kotlin envía la desviación)
        accelGraphData: new Array(100).fill(0),
        lastAccelMag: 0,
        peakAccel: 0,
        // Solo dibuja la línea roja de la gráfica. Debe coincidir con StepDetector.UMBRAL (Kotlin).
        accelThreshold: 2.2,

        // Heading: el rumbo ya llega promediado desde Kotlin; aquí solo se suaviza la flecha
        displayHeading: 0,     // rumbo suavizado para la UI
        targetHeading: 0,
        hasDeviceCompass: false,
        manualHeading: 0,
        headingInitialized: false,
        lastShownHeadingInt: -1,
        unwrappedHeading: 0,     // ángulo continuo (puede pasar de 360 o ser negativo) solo para el DOM
        lastWrappedHeading: 0,

        // Calories
        caloriesPerStep: 0.04,

        // UI
        statsExpanded: false,
    };

    const $ = (id) => document.getElementById(id);

    /** Llama a AndroidBridge.<fn>(...) si existe (en un navegador no existe). Helper común: mapa_base.js. */
    const bridgeCall = MapaBase.puente('AndroidBridge').call;

    // ── Map ──────────────────────────────────
    function initMap() {
        state.map = L.map('map', {
            center: [19.4326, -99.1332],
            zoom: 15,
            zoomControl: true,
            attributionControl: false,
        });

        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            maxZoom: 19,
            attribution: '© OpenStreetMap',
        }).addTo(state.map);

        L.control.attribution({ position: 'bottomright', prefix: false })
            .addAttribution('© <a href="https://openstreetmap.org">OSM</a>')
            .addTo(state.map);

        state.map.on('click', onMapClick);
    }

    function onMapClick(e) {
        if (state.isTracking) return;
        const { lat, lng } = e.latlng;
        setUserPosition(lat, lng);
        showToast('📍 Posición establecida', 'success');
    }

    function setUserPosition(lat, lng) {
        state.startLat = lat;
        state.startLng = lng;
        state.currentLat = lat;
        state.currentLng = lng;
        state.positionSet = true;
        bridgeCall('setPosition', lat, lng);

        if (state.userMarker) state.map.removeLayer(state.userMarker);
        if (state.startMarker) state.map.removeLayer(state.startMarker);
        if (state.trailLine) state.map.removeLayer(state.trailLine);

        const startIcon = L.divIcon({
            className: 'start-marker',
            html: '<div class="start-marker-icon"></div>',
            iconSize: [14, 14],
            iconAnchor: [7, 7],
        });
        state.startMarker = L.marker([lat, lng], { icon: startIcon })
            .addTo(state.map)
            .bindPopup('<b>Inicio</b><br>Posición inicial');

        createUserMarker(lat, lng);

        state.trailCoords = [[lat, lng]];
        state.trailLine = L.polyline(state.trailCoords, {
            color: '#6366f1',
            weight: 4,
            opacity: 0.7,
            smoothFactor: 1,
            dashArray: '8, 6',
        }).addTo(state.map);

        state.map.setView([lat, lng], Math.max(state.map.getZoom(), 16));

        $('top-bar').classList.remove('hidden');
        $('stats-panel').classList.remove('hidden');
        $('tracking-controls').classList.remove('hidden');
        $('compass-widget').classList.add('visible');
        $('status-dot').classList.add('waiting');
        $('status-text').textContent = 'Listo — pulsa ▶ para rastrear';

        updateCoordsDisplay();
    }

    function createUserMarker(lat, lng) {
        // El "rotor" es un cuadrado del tamaño del marcador que gira sobre su centro;
        // la flecha va pegada a su borde superior, así que orbita alrededor del círculo.
        const userIcon = L.divIcon({
            className: 'user-marker',
            html: `
                <div class="um-pulse"></div>
                <div class="um-ring"></div>
                <div class="um-dot"></div>
                <div class="um-rotor" id="marker-heading" style="transition:none; transform: rotate(${state.unwrappedHeading}deg)">
                    <div class="um-arrow"></div>
                </div>
            `,
            iconSize: [56, 56],
            iconAnchor: [28, 28],
        });
        state.userMarker = L.marker([lat, lng], {
            icon: userIcon,
            zIndexOffset: 1000,
            interactive: false, // los toques pasan al mapa (el marcador es grande)
        }).addTo(state.map);
    }

    /** Estilos del marcador de usuario (círculo + flecha orbitando), inyectados desde JS. */
    function injectMarkerStyles() {
        const style = document.createElement('style');
        style.textContent = `
            .user-marker{position:relative}
            .um-pulse,.um-ring,.um-dot{position:absolute;top:50%;left:50%;border-radius:50%}
            .um-pulse{width:30px;height:30px;margin:-15px 0 0 -15px;border:2px solid var(--accent-primary);animation:pulse-ring 2s ease-out infinite}
            .um-ring{width:30px;height:30px;margin:-15px 0 0 -15px;background:rgba(17,24,39,.78);border:2px solid rgba(255,255,255,.9);box-shadow:0 0 10px rgba(99,102,241,.45)}
            .um-dot{width:10px;height:10px;margin:-5px 0 0 -5px;background:var(--accent-primary);box-shadow:0 0 8px rgba(99,102,241,.8);animation:pulse-dot 2s ease-in-out infinite}
            .um-rotor{position:absolute;top:0;left:0;width:56px;height:56px;transform-origin:50% 50%;will-change:transform;pointer-events:none}
            .um-arrow{position:absolute;top:2px;left:50%;margin-left:-7px;width:0;height:0;border-left:7px solid transparent;border-right:7px solid transparent;border-bottom:12px solid var(--accent-primary);filter:drop-shadow(0 0 1px #fff) drop-shadow(0 0 3px rgba(99,102,241,.7))}
        `;
        document.head.appendChild(style);
    }

    // ── Tracking Control ───────────────────────
    window.toggleTracking = function () {
        if (!state.positionSet) {
            showToast('⚠️ Primero selecciona tu posición en el mapa', 'error');
            return;
        }
        if (state.isTracking) stopTracking();
        else startTracking();
    };

    function startTracking() {
        if (!window.AndroidBridge) {
            showToast('⚠️ El seguimiento solo funciona dentro de la app', 'error');
            return;
        }
        state.isTracking = true;
        state.startTime = Date.now() - state.elapsedMs;

        $('btn-track').classList.add('recording');
        $('icon-play').style.display = 'none';
        $('icon-pause').style.display = 'block';
        $('status-dot').classList.remove('waiting');
        $('status-dot').classList.add('active');
        $('status-text').textContent = 'Rastreando...';
        $('compass-widget').classList.add('tracking');

        // La rueda manual de rumbo la muestra onNativeBrujula(false) si no hay brújula.

        state.timerInterval = setInterval(updateTimer, 1000);

        startSensors();
        showToast('🏃 Rastreo iniciado', 'info');
    }

    function stopTracking() {
        state.isTracking = false;
        state.elapsedMs = Date.now() - state.startTime;

        $('btn-track').classList.remove('recording');
        $('icon-play').style.display = 'block';
        $('icon-pause').style.display = 'none';
        $('status-dot').classList.remove('active');
        $('status-dot').classList.add('waiting');
        $('status-text').textContent = 'Pausado';
        $('compass-widget').classList.remove('tracking');
        $('heading-control').classList.add('hidden');

        clearInterval(state.timerInterval);
        stopSensors();

        showToast('⏸ Rastreo pausado', 'info');
    }

    window.resetTracking = function () {
        if (state.isTracking) stopTracking();

        state.steps = 0;
        state.distanceM = 0;
        state.elapsedMs = 0;
        state.startTime = null;
        state.speedMps = 0;
        state.maxSpeedKmh = 0;
        state.peakAccel = 0;
        bridgeCall('reset');
        state.accelGraphData = new Array(100).fill(0);
        $('stat-time').textContent = '00:00';

        if (state.positionSet) {
            state.currentLat = state.startLat;
            state.currentLng = state.startLng;
            if (state.userMarker) {
                state.userMarker.setLatLng([state.startLat, state.startLng]);
            }
            state.trailCoords = [[state.startLat, state.startLng]];
            if (state.trailLine) state.trailLine.setLatLngs(state.trailCoords);
        }

        updateAllStats();
        showToast('🔄 Reiniciado', 'success');
    };

    // ── Sensores (los lee Kotlin: sensors/PdrTracker) ──
    // Esta página solo pide arrancar/parar y dibuja lo que llega por window.onNative*.
    function startSensors() { bridgeCall('startSensors'); }
    function stopSensors() { bridgeCall('stopSensors'); }

    // ── Callbacks desde Android (Kotlin) ───────

    /** Posición calculada por PdrEngine tras cada paso (y al fijar o reiniciar la posición). */
    window.onNativePosition = function (lat, lng, pasos, distanciaM, velocidadMps) {
        if (!state.positionSet) return;

        state.currentLat = lat;
        state.currentLng = lng;
        state.steps = pasos;
        state.distanceM = distanciaM;
        state.speedMps = velocidadMps;

        const speedKmh = velocidadMps * 3.6;
        if (speedKmh > state.maxSpeedKmh) state.maxSpeedKmh = speedKmh;

        if (state.userMarker) state.userMarker.setLatLng([lat, lng]);

        // pasos = 0 es la posición inicial o un reinicio: no se agrega punto a la trayectoria
        if (pasos > 0) {
            state.trailCoords.push([lat, lng]);
            if (state.trailLine) state.trailLine.setLatLngs(state.trailCoords);
        }
        updateAllStats();
    };

    /** Desviación de la aceleración respecto a la gravedad (m/s²), solo para la gráfica. */
    window.onNativeAccel = function (desviacion) {
        if (!state.isTracking) return;
        state.accelGraphData.push(desviacion);
        if (state.accelGraphData.length > 100) state.accelGraphData.shift();
        if (desviacion > state.peakAccel) state.peakAccel = desviacion;
        state.lastAccelMag = desviacion;
    };

    /** Rumbo en grados (0–360, norte real), ya promediado por PdrEngine. */
    window.onNativeHeading = function (degrees) {
        setTargetHeading(degrees);
    };

    /** Kotlin avisa si el teléfono tiene sensor de rotación; si no, se usa la rueda manual. */
    window.onNativeBrujula = function (disponible) {
        state.hasDeviceCompass = !!disponible;
        $('heading-control').classList.toggle('hidden', !!disponible || !state.isTracking);
    };

    /** Los pasos se detectan con el acelerómetro en vez del sensor de hardware. */
    window.onNativeStepUnavailable = function (reason) {
        showToast(
            reason === 'permission_denied'
                ? '⚠️ Sin permiso de actividad: pasos por acelerómetro'
                : 'ℹ️ Sin contador de pasos: usando acelerómetro',
            'info'
        );
    };

    /** Guarda el rumbo recibido; la flecha lo sigue con el suavizado de animateHeading(). */
    function setTargetHeading(degrees) {
        if (typeof degrees !== 'number' || isNaN(degrees)) return;
        degrees = ((degrees % 360) + 360) % 360;

        state.targetHeading = degrees;
        if (!state.headingInitialized) {
            state.displayHeading = degrees;
            state.headingInitialized = true;
            updateHeadingDisplay();
        }
    }

    /**
     * Interpola displayHeading hacia targetHeading por el camino más corto.
     * Suavizado adaptativo e independiente de los FPS:
     *  - diferencias pequeñas (ruido del sensor) → filtro fuerte, la flecha casi no tiembla
     *  - diferencias grandes (giro real) → filtro ligero, la flecha responde rápido
     */
    const HEADING_TAU_SLOW = 0.35;  // segundos, para ruido
    const HEADING_TAU_FAST = 0.10;  // segundos, para giros reales
    const HEADING_FAST_AT = 30;     // grados de diferencia a partir de los que se usa el filtro rápido
    let lastFrameTs = 0;

    function animateHeading(ts) {
        const now = ts || performance.now();
        const dt = lastFrameTs ? Math.min((now - lastFrameTs) / 1000, 0.05) : 0.016;
        lastFrameTs = now;

        if (state.headingInitialized) {
            let delta = state.targetHeading - state.displayHeading;
            if (delta > 180) delta -= 360;
            if (delta < -180) delta += 360;

            const absDelta = Math.abs(delta);
            if (absDelta > 0.05) {
                const t = Math.min(absDelta / HEADING_FAST_AT, 1);
                const tau = HEADING_TAU_SLOW + (HEADING_TAU_FAST - HEADING_TAU_SLOW) * t;
                const alpha = 1 - Math.exp(-dt / tau);

                state.displayHeading += delta * alpha;
                if (state.displayHeading < 0) state.displayHeading += 360;
                if (state.displayHeading >= 360) state.displayHeading -= 360;
                updateHeadingDisplay();
            }
        }
        requestAnimationFrame(animateHeading);
    }

    // ── GPS ────────────────────────────────────
    window.requestGPS = function () {
        if (!navigator.geolocation) {
            showToast('⚠️ GPS no disponible', 'error');
            return;
        }

        showToast('📡 Obteniendo ubicación GPS...', 'info');
        $('btn-gps').classList.add('active');

        navigator.geolocation.getCurrentPosition(
            (pos) => {
                const { latitude, longitude } = pos.coords;
                setUserPosition(latitude, longitude);
                state.map.setView([latitude, longitude], 17);
                $('btn-gps').classList.remove('active');
                showToast('✅ Posición GPS obtenida', 'success');
            },
            (err) => {
                $('btn-gps').classList.remove('active');
                showToast('❌ Error GPS: ' + err.message, 'error');
            },
            { enableHighAccuracy: true, timeout: 10000 }
        );
    };

    window.centerOnUser = function () {
        if (state.currentLat && state.currentLng) {
            state.map.setView([state.currentLat, state.currentLng], Math.max(state.map.getZoom(), 17), {
                animate: true,
                duration: 0.5,
            });
        }
    };

    // ── UI Updates ─────────────────────────────
    function updateAllStats() {
        const totalDistM = state.distanceM;
        const speedKmh = state.speedMps * 3.6;
        const elapsed = state.isTracking && state.startTime
            ? Date.now() - state.startTime
            : state.elapsedMs;
        const elapsedMin = elapsed / 60000;
        const cadence = elapsedMin > 0.1 ? Math.round(state.steps / elapsedMin) : 0;
        const calories = Math.round(state.steps * state.caloriesPerStep);

        $('stat-steps-compact').textContent = state.steps;
        $('stat-speed-compact').textContent = speedKmh.toFixed(1);
        $('stat-distance-compact').textContent = Math.round(totalDistM);

        $('stat-steps').textContent = state.steps;
        $('steps-bar').style.width = Math.min(100, (state.steps / 10000) * 100) + '%';

        $('stat-speed').innerHTML = speedKmh.toFixed(1) + ' <small>km/h</small>';
        $('stat-speed-max').textContent = state.maxSpeedKmh.toFixed(1);

        $('stat-accel').innerHTML = state.lastAccelMag.toFixed(2) + ' <small>m/s²</small>';
        $('stat-accel-max').textContent = state.peakAccel.toFixed(2);

        $('stat-distance').innerHTML = Math.round(totalDistM) + ' <small>m</small>';
        $('stat-distance-km').textContent = (totalDistM / 1000).toFixed(2);

        $('stat-cadence').innerHTML = cadence + ' <small>p/min</small>';
        $('stat-calories').innerHTML = calories + ' <small>kcal</small>';

        updateCoordsDisplay();
    }

    function updateCoordsDisplay() {
        if (state.currentLat !== null) {
            $('stat-coords').innerHTML =
                state.currentLat.toFixed(6) + '<small>, </small>' + state.currentLng.toFixed(6);
            $('stat-coords-sub').textContent = 'Lat, Lng';
        }
    }

    function updateHeadingDisplay() {
        const h = state.displayHeading;

        // ── Parte visual: en cada frame ──
        // Ángulo continuo: nunca salta de 359° a 0°, así que ninguna transición CSS
        // puede dar la vuelta larga ni girar "sola" cuando el rumbo oscila cerca del norte.
        let d = h - state.lastWrappedHeading;
        if (d > 180) d -= 360;
        if (d < -180) d += 360;
        state.unwrappedHeading += d;
        state.lastWrappedHeading = h;
        const a = state.unwrappedHeading;

        const markerHeading = document.getElementById('marker-heading');
        if (markerHeading) {
            markerHeading.style.transition = 'none'; // la suavización ya la hace animateHeading()
            markerHeading.style.transform = 'rotate(' + a + 'deg)';
        }

        const needle = $('compass-needle');
        if (needle) needle.style.transform = 'rotate(' + a + 'deg)';

        const roseLabels = $('compass-rose-labels');
        if (roseLabels) roseLabels.style.transform = 'rotate(' + (-a) + 'deg)';

        // ── Textos: solo cuando cambia el grado entero (evita tocar el DOM a 60 Hz) ──
        const hInt = Math.round(h) % 360;
        if (hInt === state.lastShownHeadingInt) return;
        state.lastShownHeadingInt = hInt;

        const dir = getCardinalDirection(h);
        $('stat-heading').innerHTML = hInt + '° <small>' + dir + '</small>';
        $('heading-value').textContent = hInt + '°';
        $('compass-dir-label').textContent = dir;
        $('compass-dir-full').textContent = getCardinalDirectionFull(h);
        $('compass-degrees').textContent = hInt + '°';
    }

    function getCardinalDirection(deg) {
        const dirs = ['N', 'NE', 'E', 'SE', 'S', 'SO', 'O', 'NO'];
        return dirs[Math.round(deg / 45) % 8];
    }

    function getCardinalDirectionFull(deg) {
        const dirs = ['Norte', 'Noreste', 'Este', 'Sureste', 'Sur', 'Suroeste', 'Oeste', 'Noroeste'];
        return dirs[Math.round(deg / 45) % 8];
    }

    function updateTimer() {
        if (!state.startTime) return;
        const totalSec = Math.floor((Date.now() - state.startTime) / 1000);
        const min = Math.floor(totalSec / 60);
        const sec = totalSec % 60;
        $('stat-time').textContent =
            String(min).padStart(2, '0') + ':' + String(sec).padStart(2, '0');
    }

    // ── Acceleration Graph ─────────────────────
    function drawAccelGraph() {
        const canvas = $('accel-canvas');
        if (!canvas) { requestAnimationFrame(drawAccelGraph); return; }

        const ctx = canvas.getContext('2d');
        const w = canvas.width;
        const h = canvas.height;
        const data = state.accelGraphData;

        ctx.clearRect(0, 0, w, h);

        ctx.strokeStyle = 'rgba(255,255,255,0.04)';
        ctx.lineWidth = 1;
        for (let i = 0; i < 5; i++) {
            const y = (h / 5) * i;
            ctx.beginPath();
            ctx.moveTo(0, y);
            ctx.lineTo(w, y);
            ctx.stroke();
        }

        const thresholdY = h - (state.accelThreshold / 10) * h;
        ctx.strokeStyle = 'rgba(239,68,68,0.3)';
        ctx.setLineDash([4, 4]);
        ctx.beginPath();
        ctx.moveTo(0, thresholdY);
        ctx.lineTo(w, thresholdY);
        ctx.stroke();
        ctx.setLineDash([]);

        const gradient = ctx.createLinearGradient(0, 0, 0, h);
        gradient.addColorStop(0, 'rgba(99,102,241,0.4)');
        gradient.addColorStop(1, 'rgba(99,102,241,0)');

        const step = w / (data.length - 1);

        ctx.beginPath();
        ctx.moveTo(0, h);
        for (let i = 0; i < data.length; i++) {
            const val = Math.min(data[i], 10);
            ctx.lineTo(i * step, h - (val / 10) * h);
        }
        ctx.lineTo(w, h);
        ctx.closePath();
        ctx.fillStyle = gradient;
        ctx.fill();

        ctx.beginPath();
        for (let i = 0; i < data.length; i++) {
            const val = Math.min(data[i], 10);
            const x = i * step;
            const y = h - (val / 10) * h;
            if (i === 0) ctx.moveTo(x, y);
            else ctx.lineTo(x, y);
        }
        ctx.strokeStyle = '#6366f1';
        ctx.lineWidth = 2;
        ctx.stroke();

        requestAnimationFrame(drawAccelGraph);
    }

    // ── Manual Heading Wheel ───────────────────
    function initHeadingWheel() {
        const canvas = $('heading-wheel');
        if (!canvas) return;

        const ctx = canvas.getContext('2d');
        const size = canvas.width;
        const center = size / 2;
        const radius = center - 8;

        function drawWheel(heading) {
            ctx.clearRect(0, 0, size, size);

            ctx.beginPath();
            ctx.arc(center, center, radius, 0, Math.PI * 2);
            ctx.strokeStyle = 'rgba(255,255,255,0.1)';
            ctx.lineWidth = 2;
            ctx.stroke();

            const labels = ['N', 'E', 'S', 'O'];
            ctx.font = '10px Inter, sans-serif';
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';

            for (let i = 0; i < 4; i++) {
                const angle = (i * 90 - 90) * (Math.PI / 180);
                const lx = center + (radius - 12) * Math.cos(angle);
                const ly = center + (radius - 12) * Math.sin(angle);
                ctx.fillStyle = i === 0 ? '#ef4444' : 'rgba(255,255,255,0.4)';
                ctx.fillText(labels[i], lx, ly);
            }

            for (let i = 0; i < 36; i++) {
                const angle = (i * 10 - 90) * (Math.PI / 180);
                const inner = i % 9 === 0 ? radius - 20 : radius - 6;
                ctx.beginPath();
                ctx.moveTo(center + inner * Math.cos(angle), center + inner * Math.sin(angle));
                ctx.lineTo(center + (radius - 2) * Math.cos(angle), center + (radius - 2) * Math.sin(angle));
                ctx.strokeStyle = i % 9 === 0 ? 'rgba(255,255,255,0.5)' : 'rgba(255,255,255,0.15)';
                ctx.lineWidth = i % 9 === 0 ? 2 : 1;
                ctx.stroke();
            }

            const pAngle = (heading - 90) * (Math.PI / 180);
            const px = center + (radius - 24) * Math.cos(pAngle);
            const py = center + (radius - 24) * Math.sin(pAngle);

            ctx.beginPath();
            ctx.arc(px, py, 5, 0, Math.PI * 2);
            ctx.fillStyle = '#6366f1';
            ctx.fill();
            ctx.strokeStyle = 'white';
            ctx.lineWidth = 2;
            ctx.stroke();
        }

        drawWheel(state.manualHeading);

        let dragging = false;

        function getAngle(e) {
            const rect = canvas.getBoundingClientRect();
            const touch = e.touches ? e.touches[0] : e;
            const x = touch.clientX - rect.left - center;
            const y = touch.clientY - rect.top - center;
            let angle = Math.atan2(y, x) * (180 / Math.PI) + 90;
            if (angle < 0) angle += 360;
            return angle;
        }

        function onStart(e) { dragging = true; updateHeading(e); e.preventDefault(); }
        function onMove(e) { if (!dragging) return; updateHeading(e); e.preventDefault(); }
        function onEnd() { dragging = false; }

        function updateHeading(e) {
            const angle = getAngle(e);
            state.manualHeading = angle;
            // El rumbo manual se aplica directo (sin promedio ni animación) y se avisa a Kotlin
            bridgeCall('setManualHeading', angle);
            state.targetHeading = angle;
            state.displayHeading = angle;
            state.headingInitialized = true;
            drawWheel(angle);
            updateHeadingDisplay();
        }

        canvas.addEventListener('mousedown', onStart);
        canvas.addEventListener('mousemove', onMove);
        canvas.addEventListener('mouseup', onEnd);
        canvas.addEventListener('mouseleave', onEnd);

        canvas.addEventListener('touchstart', onStart, { passive: false });
        canvas.addEventListener('touchmove', onMove, { passive: false });
        canvas.addEventListener('touchend', onEnd);
    }

    // ── Stats Panel Toggle ─────────────────────
    window.toggleStatsExpand = function () {
        const panel = $('stats-panel');
        state.statsExpanded = !state.statsExpanded;
        panel.classList.toggle('expanded', state.statsExpanded);
    };

    // ── Toast ──────────────────────────────────
    function showToast(message, type = 'info') {
        const container = $('toast-container');
        const toast = document.createElement('div');
        toast.className = 'toast ' + type;
        toast.textContent = message;
        container.appendChild(toast);
        setTimeout(() => {
            if (toast.parentNode) toast.parentNode.removeChild(toast);
        }, 3000);
    }

    // ── Splash ─────────────────────────────────
    window.dismissSplash = function () {
        const splash = $('splash-screen');
        splash.classList.add('dismissed');
        setTimeout(() => {
            splash.style.display = 'none';
            $('top-bar').classList.remove('hidden');
        }, 600);

        if (navigator.geolocation) {
            navigator.geolocation.getCurrentPosition(
                (pos) => {
                    setUserPosition(pos.coords.latitude, pos.coords.longitude);
                    state.map.setView([pos.coords.latitude, pos.coords.longitude], 17);
                    showToast('📍 Posición GPS detectada', 'success');
                },
                () => {
                    showToast('Toca el mapa para establecer tu posición', 'info');
                },
                { enableHighAccuracy: true, timeout: 5000 }
            );
        }
    };

    // ── Boot ───────────────────────────────────
    function boot() {
        injectMarkerStyles();
        initMap();
        initHeadingWheel();
        drawAccelGraph();
        animateHeading();

        function resizeCanvas() {
            const canvas = $('accel-canvas');
            if (canvas) canvas.width = canvas.parentElement.clientWidth - 24;
        }
        window.addEventListener('resize', resizeCanvas);
        setTimeout(resizeCanvas, 500);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', boot);
    } else {
        boot();
    }
})();