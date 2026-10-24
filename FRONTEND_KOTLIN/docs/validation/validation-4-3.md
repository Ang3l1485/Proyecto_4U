# Validación 4-3 — FE-4.3 Limpieza y deuda técnica

| Campo | Valor |
|---|---|
| Lote | `FE-4.3` — criterios en [`PLAN.md`](../PLAN.md) §2.2 |
| Script | `project/src/ops/validate43.py` |
| Entornos | `dev` con dispositivo físico. No necesita backend: el script no llama a la API (con `local` hace lo mismo) |
| Criterios | Automáticos: C1, C2, C3a, C3b, C4 · Manuales: C5 |

Contrato común de los validadores: `INFRASTRUCTURA_TERRAFORM/docs/ARCHITECTURE.md` §5.11. Lo propio de esta carpeta:
`ARCHITECTURE.md` §5.11.

## 1. Precondiciones

Si alguna no se cumple, el script termina con código 2 y el lote queda `Bloqueado`. El PLAN no fija lotes previos.

| ID | Qué debe cumplirse | Cómo lo comprueba el script |
|---|---|---|
| P1 | Gradle listo y el proyecto compila tras la limpieza | `./gradlew assembleDebug` termina con 0 |
| P2 | Dispositivo físico conectado, para C3b | `adb devices` con uno en estado `device` (el de `ANDROID_SERIAL` si hay varios) y `adb shell getprop ro.kernel.qemu` distinto de `1` |

## 2. Comprobaciones automáticas

Las búsquedas son sobre los archivos versionados (`git ls-files`) de `FRONTEND_KOTLIN/`; rutas relativas a `project/`.

| ID | Qué hace el script | Pasa si |
|---|---|---|
| C1 | Lista los archivos de `app/src/main/java/` con extensión `.py` o `.zip` | No hay ninguno (en particular, ni `archivos_zip.py` ni `crear_archivos.py` ni `out.zip`) |
| C2 | Busca el texto `eafit.mbtiles` en todo `project/`; `docs/` queda fuera porque el ARCHITECTURE y el CHANGELOG conservan la decisión que lo descartó (2.6) | 0 coincidencias |
| C3a | Busca `ACTIVITY_RECOGNITION` en `app/src/main/AndroidManifest.xml` y en `MainActivity.kt`, donde vive `object Permisos` (5.3) | 0 coincidencias |
| C3b | Instala el APK (`./gradlew installDebug`) y lee `adb shell dumpsys package com.example.myapplication` | En los permisos pedidos no figura `android.permission.ACTIVITY_RECOGNITION` (ninguna dependencia lo vuelve a meter en el Manifest combinado) |
| C4 | Busca `unpkg.com`, `fonts.googleapis.com` y `fonts.gstatic.com` en todos los `.html`, `.js` y `.css` de `app/src/main/assets/` | 0 coincidencias |

## 3. Comprobaciones manuales

| ID | Qué hace la persona | Evidencia en el PR |
|---|---|---|
| C5 | Recorre la lista completa de FE-4.3 en `PLAN.md` §2.2 («Código y configuración», «Diseño pendiente» y «Decisiones a tomar», incluidas las decisiones abiertas 13, 14, 17 y 19) y marca cada tarea como hecha o la enlaza a un lote nuevo de `PLAN.md` | Lista de verificación en la descripción del PR con cada tarea marcada `[x]` y el commit que la hace, o con el identificador `FE-x.y` del lote nuevo; para las decisiones, el ADR o la entrada de §8 que las cierra |

## 4. Datos de prueba y limpieza

No crea nada en el backend ni en el teléfono: solo lee el código e instala el APK de depuración (conserva los datos de
la app). No usa `pm clear`.

## 5. Cómo ejecutarlo

```bash
cd FRONTEND_KOTLIN/project
uv run --group ops python src/ops/validate43.py --entorno dev
```

Variables: `ANDROID_SERIAL` si hay varios dispositivos (`ARCHITECTURE.md` §5.11); no usa las de la API. Duración
aproximada: 5 minutos (la compilación domina).
