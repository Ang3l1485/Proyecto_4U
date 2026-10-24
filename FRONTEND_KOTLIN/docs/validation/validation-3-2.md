# Validación 3-2 — FE-3.2 Ubicación real y Resultado (6.3)

| Campo | Valor |
|---|---|
| Lote | `FE-3.2` — criterios en [`PLAN.md`](../PLAN.md) §2.2 |
| Script | `project/src/ops/validate32.py` |
| Entornos | `dev` con dispositivo físico |
| Criterios | Automáticos: C2, C3 · Manuales: C1, C4 |

Contrato común de los validadores: `INFRASTRUCTURA_TERRAFORM/docs/ARCHITECTURE.md` §5.11. Lo propio de esta carpeta:
`ARCHITECTURE.md` §5.11.

## 1. Precondiciones

Si alguna no se cumple, el script termina con código 2 y el lote queda `Bloqueado`.

| ID | Qué debe cumplirse | Cómo lo comprueba el script |
|---|---|---|
| P1 | `FE-3.1` en «Hecho»: lugares y alertas reales en la app | Fila de `FE-3.1` en `PLAN.md` §3 = `Hecho` |
| P2 | `BE-3.2` en «Hecho»: localización con dataset del campus | Fila en `BACKEND_FASTAPI/docs/PLAN.md` §3 = `Hecho`; `POST /v1/localize` con `metadatos` y sin fotos responde `400 FOTOS_INVALIDAS` (existe y no procesa nada); `GET /v1/admin/stats` (con token de admin) da `total_fotos` > 0 |
| P3 | Dispositivo físico y Gradle | `adb devices` con uno en estado `device` (el de `ANDROID_SERIAL` si hay varios), `ro.kernel.qemu` distinto de `1` y `./gradlew --version` con salida 0 |

## 2. Comprobaciones automáticas

| ID | Qué hace el script | Pasa si |
|---|---|---|
| C2 | `./gradlew testDebugUnitTest --tests '*.ConversionRumboTest'` (pruebas de la conversión de §5.10, «Rumbo») | Sale con 0 y los XML de `app/build/test-results/testDebugUnitTest/` suman ≥ 1 caso y 0 fallos (la revisión del PR confirma que incluyen −180, 180, 0 y una declinación negativa) |
| C3 | Comprueba que `ui/ubicacion/EscaneoViewModel.kt` declara `CONSERVAR_FOTOS = false`. En el teléfono donde se hicieron las vueltas de C1 o C4 lee `files/logs/app.log` (`adb exec-out run-as com.example.myapplication cat files/logs/app.log`), la fecha de instalación (`adb shell dumpsys package com.example.myapplication`, `lastUpdateTime`) y las fotos (`adb shell run-as com.example.myapplication ls -R files/camera/photos`) | El valor es `false`, `app.log` tiene ≥ 1 sesión `[scan-…]` y ninguna carpeta `<yyyy-MM-dd_HH-mm-ss>` posterior a la instalación contiene `.jpg` |

Si C3 falla por no haber escaneos, se repite después de las manuales con `--solo C3`.

## 3. Comprobaciones manuales

El script imprime los lugares de `GET /v1/places` y la hora de `dev`: C1 se hace entre las 06:00 y las 22:00
`America/Bogota` (`GET /v1/health/ready` da `"embedding": "ok"`) y C4, fuera de ese horario (`"no_disponible"`).

| ID | Qué hace la persona | Evidencia en el PR |
|---|---|---|
| C1 | Elige 10 puntos conocidos del campus con dataset (junto a lugares de la lista) y en cada uno hace Inicio → Ubicarme, da la vuelta y escucha el Resultado (6.3) | Tabla de los 10 puntos (punto, lugar esperado, lo que dijo la app, nivel de confianza, si pidió repetir) y video con audio de al menos dos; en cada punto la app dice el lugar correcto o, con confianza baja, lo dice y ofrece «Volver a ubicarme» |
| C4 | Fuera del horario, hace Inicio → Ubicarme y da la vuelta completa | Video con audio: tras «Analizando…», la app dice «El servicio de ubicación no está disponible en este momento» (§5.10) y no se cierra |

## 4. Datos de prueba y limpieza

No crea nada en el backend: `POST /v1/localize` no guarda las fotos (BE-3.2) y la llamada de P2 se rechaza antes de
procesar. En el teléfono solo lee archivos; no usa `pm clear`.

## 5. Cómo ejecutarlo

```bash
cd FRONTEND_KOTLIN/project
uv run --group ops python src/ops/validate32.py --entorno dev
```

Variables: `VALIDACION_API_URL`, `VALIDACION_ADMIN_CORREO`, `VALIDACION_ADMIN_PASSWORD` (`ARCHITECTURE.md` §5.11)
y `ANDROID_SERIAL` si hay varios dispositivos. Duración aproximada: 4 minutos de script, más 60 de C1 en el campus y
10 de C4 de noche.
