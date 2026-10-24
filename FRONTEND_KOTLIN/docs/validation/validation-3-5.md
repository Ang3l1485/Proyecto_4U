# Validación 3-5 — FE-3.5 Accesibilidad y voz del flujo público

| Campo | Valor |
|---|---|
| Lote | `FE-3.5` — criterios en [`PLAN.md`](../PLAN.md) §2.2 |
| Script | `project/src/ops/validate35.py` |
| Entornos | `dev` con dispositivo físico |
| Criterios | Automáticos: C1, C2 · Manuales: C3 |

Contrato común de los validadores: `INFRASTRUCTURA_TERRAFORM/docs/ARCHITECTURE.md` §5.11. Lo propio de esta carpeta:
`ARCHITECTURE.md` §5.11.

## 1. Precondiciones

Si alguna no se cumple, el script termina con código 2 y el lote queda `Bloqueado`.

| ID | Qué debe cumplirse | Cómo lo comprueba el script |
|---|---|---|
| P1 | `FE-3.2` en «Hecho»: flujo Inicio → Ubicarme → Resultado → Destino con backend real | Fila de `FE-3.2` en `PLAN.md` §3 = `Hecho`; `GET /v1/health` responde 200 y `GET /v1/places` devuelve ≥ 1 lugar |
| P2 | Dispositivo físico y Gradle | `adb devices` con uno en estado `device` (el de `ANDROID_SERIAL` si hay varios), `ro.kernel.qemu` distinto de `1` y `./gradlew --version` con salida 0 |
| P3 | Nada que perder en el teléfono: `connectedDebugAndroidTest` desinstala la app al terminar y borra sus datos locales | Ningún `files/recoleccion/*/manifest.json` tiene fotos con `"sync": "pendiente"` (`adb exec-out run-as com.example.myapplication cat …`); si la app no está instalada, se da por cumplida |

## 2. Comprobaciones automáticas

| ID | Qué hace el script | Pasa si |
|---|---|---|
| C1 | Comprueba que las pruebas instrumentadas de `app/src/androidTest/` de los paquetes `ui.inicio`, `ui.ubicacion` y `ui.destino` llaman a `AccessibilityChecks.enable()`, y ejecuta `./gradlew connectedDebugAndroidTest -Pandroid.testInstrumentationRunnerArguments.package=com.example.myapplication.ui.inicio,com.example.myapplication.ui.ubicacion,com.example.myapplication.ui.destino` | Cada paquete tiene ≥ 1 clase con `AccessibilityChecks.enable()`; Gradle sale con 0 y los XML de `app/build/outputs/androidTest-results/connected/` tienen ≥ 1 caso por paquete y 0 fallos |
| C2 | `./gradlew testDebugUnitTest --tests '*.BuscarLugaresTest'` | Sale con 0 y los XML de `app/build/test-results/testDebugUnitTest/` suman ≥ 2 casos y 0 fallos (la revisión del PR confirma que cubren la coincidencia exacta que gana sin preguntar y las hipótesis unidas de `listen`, 5.7) |

## 3. Comprobaciones manuales

El script reinstala el APK (`./gradlew installDebug`) tras C1 y la persona concede los permisos al abrir la app,
escuchando antes la explicación hablada.

| ID | Qué hace la persona | Evidencia en el PR |
|---|---|---|
| C3 | Una persona usuaria de lector de pantalla hace dos veces el recorrido Inicio → Ubicarme → Resultado (6.3) → Destino (6.4, hasta confirmar un lugar), en `dev` y dentro del horario de `embedding` (06:00–22:00 `America/Bogota`): una solo con voz (sin tocar la pantalla salvo para iniciar) y otra solo con TalkBack (sin voz). Se anota cada vez que hablan dos voces a la vez | Video con audio de cada recorrido; nota de la sesión (fecha, modelo, versión de Android y de TalkBack, si la explicación de permisos sonó antes del diálogo, voces superpuestas: 0, y observaciones), sin datos personales de quien probó |

## 4. Datos de prueba y limpieza

No crea nada en el backend. `connectedDebugAndroidTest` instala y desinstala la app de prueba (por eso P3); el script
no usa `pm clear`.

## 5. Cómo ejecutarlo

```bash
cd FRONTEND_KOTLIN/project
uv run --group ops python src/ops/validate35.py --entorno dev
```

Variables: `VALIDACION_API_URL` (`ARCHITECTURE.md` §5.11) y `ANDROID_SERIAL` si hay varios dispositivos. Duración
aproximada: 15 minutos de script, más 45 de la sesión con la persona usuaria.
