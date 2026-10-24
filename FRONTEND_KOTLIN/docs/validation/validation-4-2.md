# Validación 4-2 — FE-4.2 Ajustes (6.7)

| Campo | Valor |
|---|---|
| Lote | `FE-4.2` — criterios en [`PLAN.md`](../PLAN.md) §2.2 |
| Script | `project/src/ops/validate42.py` |
| Entornos | `dev` con dispositivo físico. No necesita backend: el script no llama a la API (con `local` hace lo mismo) |
| Criterios | Automáticos: C1, C2 · Manuales: ninguno |

Contrato común de los validadores: `INFRASTRUCTURA_TERRAFORM/docs/ARCHITECTURE.md` §5.11. Lo propio de esta carpeta:
`ARCHITECTURE.md` §5.11.

## 1. Precondiciones

Si alguna no se cumple, el script termina con código 2 y el lote queda `Bloqueado`. El PLAN no fija lotes previos.

| ID | Qué debe cumplirse | Cómo lo comprueba el script |
|---|---|---|
| P1 | Gradle listo y la dependencia de `AccessibilityChecks` declarada (la usan las pruebas de FE-3.5) | `./gradlew --version` termina con 0 y `app/build.gradle.kts` declara `androidTestImplementation` de `espresso-accessibility` |
| P2 | Dispositivo físico conectado | `adb devices` con uno en estado `device` (el de `ANDROID_SERIAL` si hay varios) y `adb shell getprop ro.kernel.qemu` distinto de `1` |
| P3 | Nada que perder en el teléfono: `connectedDebugAndroidTest` desinstala la app al terminar y borra sus datos locales (también la calibración de 7.3b) | Ningún `files/recoleccion/*/manifest.json` tiene fotos con `"sync": "pendiente"` (`adb exec-out run-as com.example.myapplication cat …`); el script avisa si existe `shared_prefs/campus_calibracion.xml` y pide confirmar con Enter |

## 2. Comprobaciones automáticas

Ambas usan la misma ejecución: `./gradlew connectedDebugAndroidTest
-Pandroid.testInstrumentationRunnerArguments.package=com.example.myapplication.ui.ajustes`, con los resultados en
`app/build/outputs/androidTest-results/connected/`.

| ID | Qué hace el script | Pasa si |
|---|---|---|
| C1 | Ejecuta `./gradlew connectedDebugAndroidTest -Pandroid.testInstrumentationRunnerArguments.class=com.example.myapplication.ui.ajustes.AjustesPersistenciaTest` y lee sus resultados | Gradle sale con 0, hay ≥ 1 caso y 0 fallos (la revisión del PR confirma que cubren cada control de 6.7, incluida la unidad metros / pasos con la longitud calibrada, y que recrean la actividad antes de comprobar el valor guardado) |
| C2 | Comprueba que esas pruebas llaman a `AccessibilityChecks.enable()`, como las vistas públicas de FE-3.5, y lee los mismos resultados | Hay ≥ 1 clase con `AccessibilityChecks.enable()` y ningún caso falla por `AccessibilityViewCheckException` |

## 3. Comprobaciones manuales

Ninguna: todos los criterios son automáticos.

## 4. Datos de prueba y limpieza

No crea nada en el backend. Los ajustes que cambian las pruebas desaparecen al desinstalarse la app al final de
`connectedDebugAndroidTest`; después, el script reinstala el APK con `./gradlew installDebug`. No usa `pm clear`.

## 5. Cómo ejecutarlo

```bash
cd FRONTEND_KOTLIN/project
uv run --group ops python src/ops/validate42.py --entorno dev
```

Variables: `ANDROID_SERIAL` si hay varios dispositivos (`ARCHITECTURE.md` §5.11); no usa las de la API. Duración
aproximada: 8 minutos.
