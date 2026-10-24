# Validación 2-3 — FE-2.3 Pruebas en dispositivo y robustez de la recolección

| Campo | Valor |
|---|---|
| Lote | `FE-2.3` — criterios en [`PLAN.md`](../PLAN.md) §2.2 |
| Script | `project/src/ops/validate23.py` |
| Entornos | `dev` con dispositivo físico. No necesita backend: el script no llama a la API (con `local` hace lo mismo) |
| Criterios | Automáticos: C1, C2 · Manuales: C3, C4, C5 |

Contrato común de los validadores: `INFRASTRUCTURA_TERRAFORM/docs/ARCHITECTURE.md` §5.11. Lo propio de esta carpeta:
`ARCHITECTURE.md` §5.11.

## 1. Precondiciones

Si alguna no se cumple, el script termina con código 2 y el lote queda `Bloqueado`. El PLAN no fija lotes previos.

| ID | Qué debe cumplirse | Cómo lo comprueba el script |
|---|---|---|
| P1 | Gradle listo y el proyecto compila | `./gradlew assembleDebug` termina con 0 |
| P2 | Dispositivo físico conectado, para instalar el APK y apoyar las manuales | `adb devices` con uno en estado `device` (el de `ANDROID_SERIAL` si hay varios) y `adb shell getprop ro.kernel.qemu` distinto de `1` |

## 2. Comprobaciones automáticas

| ID | Qué hace el script | Pasa si |
|---|---|---|
| C1 | `./gradlew testDebugUnitTest --tests '*.CalibracionPasoTest' --tests '*.StepDetectorTest' --tests '*.DisparadorCapturaTest' --tests '*.DerivaTest'` y lee los XML de `app/build/test-results/testDebugUnitTest/` | Sale con 0, cada una de las cuatro clases ejecutó ≥ 1 caso y no hay fallos ni casos omitidos |
| C2 | Busca en `app/src/main/assets/recoleccion_mapa.js` y `calibracion_mapa.js` las llamadas a `crearMapa` | En cada archivo hay ≥ 1 `MapaBase.crearMapa(` y ninguna `base.crearMapa(` (5.9) |

## 3. Comprobaciones manuales

Para C3 a C5 el script instala el APK (`./gradlew installDebug`, sin borrar datos) e imprime modelo y versión de
Android (`getprop ro.product.model`, `ro.build.version.release`) y la calibración guardada (`adb exec-out run-as
com.example.myapplication cat shared_prefs/campus_calibracion.xml`: `longitud_paso_m` y `fecha_ms`). Las vistas de
administración piden login (si FE-1.2 ya está hecho, contra `dev`).

| ID | Qué hace la persona | Evidencia en el PR |
|---|---|---|
| C3 | Recalibra en 7.3b con una pasada A→B de ≥ 30 m y guarda. Luego, en un recorrido conocido de ≥ 100 m con puntos marcados en el mapa: (a) mapa público (`MapaPublicoScreen`): fija el inicio y camina; (b) 7.3: fija punto y rumbo y comprueba coordenadas, dial y brújula; (c) 7.4 con la longitud calibrada y captura cada 5 m. Mide en el punto final la distancia entre la posición de la app y la real | Tabla «Registro de pruebas en dispositivo» en el PR: modelo, Android, prueba (PDR, 7.3, 7.3b, 7.4), recorrido, pasos, `distanciaMetros`, longitud guardada (`fecha_ms` posterior al 2026-10-12), fotos por cada 5 m frente a `5 / longitud` pasos y error final medido |
| C4 | Inicia una recolección (7.4, modo «cada 3 s», basta estar quieto), espera ≥ 5 fotos, pulsa Inicio del sistema y mata el proceso con `adb shell am kill com.example.myapplication`. Vuelve a abrir la app, entra como admin si lo pide y retoma la grabación; espera otras 5 fotos y finaliza | Video corto; salida de `adb shell run-as com.example.myapplication ls files/recoleccion/` (una sola carpeta `rec_NNNN` nueva) y del `manifest.json` con la numeración de fotos continua |
| C5 | Con la calibración (7.3b) en fase `CAMINANDO` y, aparte, con el mapa público siguiendo pasos, pulsa Inicio del sistema, espera 10 s y ejecuta `adb shell dumpsys sensorservice`; vuelve a la app | Salida de `dumpsys` con la app en segundo plano: no hay conexión activa de `com.example.myapplication` al acelerómetro ni al vector de rotación (en primer plano, sí) |

## 4. Datos de prueba y limpieza

No crea nada en el backend. En el teléfono, la calibración nueva de C3 **se conserva** (es la que se usará para
recolectar el dataset real) y los videos locales de C3 y C4 los descarta la persona en la app si no los va a subir.
El script no usa `pm clear`: borraría la calibración (`campus_calibracion`).

## 5. Cómo ejecutarlo

```bash
cd FRONTEND_KOTLIN/project
uv run --group ops python src/ops/validate23.py --entorno dev
```

Variables: `ANDROID_SERIAL` si hay varios dispositivos (`ARCHITECTURE.md` §5.11); no usa las de la API. Duración
aproximada: 4 minutos de script, más 60 a 90 de pruebas en el campus.
