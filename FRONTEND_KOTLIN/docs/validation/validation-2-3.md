# Validación 2-3 — FE-2.3 Pruebas en dispositivo y robustez de la recolección

| Campo | Valor |
|---|---|
| Lote | `FE-2.3` — criterios en [`PLAN.md`](../PLAN.md) §2.2 |
| Script | `project/src/ops/validate23.py` |
| Entornos | `dev` con dispositivo físico (cierra el lote, junto con la evidencia de C3–C5); `local` (sin teléfono: C1 y C2). No usa la API ni AWS en ninguno de los dos |
| Criterios | Automáticos: C1, C2 · Manuales: C3, C4, C5 |

Contrato común de los validadores: `INFRASTRUCTURA_TERRAFORM/docs/ARCHITECTURE.md` §5.11. Lo propio de esta carpeta
(dónde corren, variables, `comun.py`, detalles de `validate23.py`, trampas): `ARCHITECTURE.md` §5.11. Piezas que se
comprueban: `ARCHITECTURE.md` §4.3 (lo construido en FE-2.3), §5.2 (PDR, segundo plano y flujo de la recolección), §5.6
(`progress` del manifest), §5.7 (casos de uso) y §5.8 (ruta `mapa` y retomar).

## 1. Precondiciones

Se evalúan en este orden y el script no sigue si una falla. Las dos son de la máquina (código 3). El PLAN no fija lotes
previos para validar, así que este validador nunca da código 2. En `local` solo se evalúa P1.

| ID | Qué debe cumplirse | Cómo lo comprueba el script |
|---|---|---|
| P1 | Gradle y un JDK que lo ejecute | `<VALIDACION_GRADLE> --version` termina con 0 (detalle: versión de Gradle y JVM). Si no → 3. Que el proyecto compila lo prueba C1 (compila la app y las pruebas) y, en `dev`, el `installDebug` de las manuales |
| P2 | Dispositivo físico conectado (solo `dev`) | `adb devices` muestra uno en estado `device` (el de `ANDROID_SERIAL` si hay varios) y `adb shell getprop ro.kernel.qemu` no es `1`; lee modelo, versión de Android y SDK. Si no → 3 |

## 2. Comprobaciones automáticas

| ID | Qué hace el script | Pasa si |
|---|---|---|
| C1 | Borra los XML anteriores de las cuatro clases y ejecuta una vez `<VALIDACION_GRADLE> testDebugUnitTest --tests '*.CalibracionPasoTest' --tests '*.StepDetectorTest' --tests '*.DisparadorCapturaTest' --tests '*.DerivaTest'`; lee `app/build/test-results/testDebugUnitTest/TEST-*.<clase>.xml` | Gradle sale con 0 y cada clase tiene su XML, 0 fallos, 0 errores, 0 casos omitidos y al menos su mínimo de casos: 8, 6, 6 y 4 (hoy 13, 11, 10 y 6). Qué cubre cada clase: `ARCHITECTURE.md` §5.2 (`StepDetector`) y §5.7; lo confirma la revisión del PR |
| C2 | Lee `app/src/main/assets/recoleccion_mapa.js` y `calibracion_mapa.js`, quita los comentarios (`//` y `/* */`, respetando las cadenas) y cuenta las llamadas `MapaBase.crearMapa(` y `base.crearMapa(` (esta última, solo si no va precedida de una letra, `$` o `.`) | En cada archivo hay ≥ 1 `MapaBase.crearMapa(` y ninguna `base.crearMapa(` (`ARCHITECTURE.md` §5.9). Si falta un archivo, falla |

## 3. Comprobaciones manuales

En `dev`, si C1 y C2 pasan, el script instala el APK de depuración (`installDebug`, **conserva los datos**; nunca usa
`pm clear`) e imprime por stderr y al principio de cada instrucción `[MANUAL]`, para la evidencia:
- el teléfono: modelo, Android y SDK (`getprop ro.product.model`, `ro.build.version.release`, `ro.build.version.sdk`);
- la calibración guardada (`run-as … cat shared_prefs/campus_calibracion.xml`): `longitud_paso_m`, pasos y distancia
  de la medición, `fecha_ms` con su fecha en Bogotá y si es posterior al 2026-10-12 (el cambio de detector, ADR-FE-04);
  sin archivo, «ninguna (la app usa el valor genérico de 0.72 m)»;
- los recorridos locales (`run-as … ls -1 files/recoleccion` y cada `manifest.json`): `rec_NNNN (estado, N fotos[, con
  progress])`. Es la lista «antes» de C4.

Si C1 o C2 fallan, no instala y las instrucciones empiezan con «APK sin instalar: … no pasan». En `local` empiezan con
«entorno local: sin datos del teléfono».

Las vistas de administración piden login contra `dev` (FE-1.2). La evidencia se guarda en
[`evidencia/fe-2-3/`](./evidencia/) (como `evidencia/fe-1-1/`) y se cita en el PR. En los comandos, `adb` es
`$VALIDACION_ADB` en WSL (§5) y `EVID=../docs/validation/evidencia/fe-2-3` desde `FRONTEND_KOTLIN/project`.

| ID | Qué hace la persona | Evidencia |
|---|---|---|
| C3 | Recalibra (7.3b) y prueba el PDR en el mapa público, 7.3 y 7.4 en un recorrido conocido (procedimiento abajo) | `evidencia/fe-2-3/registro.md` con la tabla «Registro de pruebas en dispositivo» (plantilla abajo) y `c3-manifest.json` del recorrido de 7.4 |
| C4 | Mata el proceso a mitad de una grabación y la retoma (abajo) | `c4-video.mp4` (corto, de la pantalla), `c4-recoleccion.txt` (listado de `files/recoleccion/` antes y después) y `c4-manifest.json` |
| C5 | Comprueba que en segundo plano el PDR no lee sensores, en la calibración y en el mapa público (abajo) | `c5-calibracion-fondo.txt`, `c5-mapa-fondo.txt` y `c5-mapa-frente.txt` (`dumpsys sensorservice`) y `c5-app-log.txt` (líneas `Pdr` de `app.log`) |

**C3 — procedimiento.** Elegir en el campus un recorrido de **≥ 100 m** con puntos reconocibles (esquinas, postes,
placas) cuyas coordenadas se puedan marcar en el mapa, y un tramo recto de **≥ 30 m** (A→B) para calibrar.
1. **7.3b (calibrar):** Panel → Recolector → «Calibrar mi paso». Marcar A y B en el mapa, «Inicio» parado en A,
   caminar a B **como al recolectar** (mismo ritmo y forma de llevar el teléfono), «Fin» y «Guardar». Anotar tramo,
   pasos y longitud. Comprobar con `adb exec-out run-as com.example.myapplication cat shared_prefs/campus_calibracion.xml`
   que `fecha_ms` es de hoy (posterior al 2026-10-12).
2. **Mapa público (PDR):** `adb shell am force-stop com.example.myapplication` y
   `adb shell am start -n com.example.myapplication/.MainActivity --es ruta mapa` (solo APK de depuración; ARCHITECTURE
   §5.8). Tocar el punto de inicio en el mapa, ▶, caminar el recorrido y parar en el punto final. Anotar pasos y
   distancia del panel de estadísticas y las coordenadas finales que muestra.
3. **7.3:** Panel → Recolector. Tocar el punto de inicio exacto, comprobar las coordenadas (6 decimales), girar el dial y
   probar «Usar brújula del teléfono» apuntando a un rumbo conocido (p. ej. a lo largo de una fachada). Anotar el
   desvío entre el punto marcado y el real.
4. **7.4:** desde 7.3 con ese punto, «Confirmar y comenzar» con «Cada 5 m». Caminar el recorrido sin re-anclarse,
   parar en el punto final, anotar pasos y distancia de la pantalla y «Finalizar video». Guardar el manifest:
   `adb exec-out run-as com.example.myapplication cat files/recoleccion/rec_NNNN/manifest.json > $EVID/c3-manifest.json`.
   Su última foto da la posición final de la app; `steps` y el número de fotos sirven para la columna de fotos.
5. **Error final:** distancia entre la posición final de la app y las coordenadas reales del punto final (medida en el
   mapa o con haversine). La longitud recalibrada **se queda** en el teléfono: es la que se usará para el dataset.

Plantilla de `evidencia/fe-2-3/registro.md` (una fila por prueba; la columna de fotos solo para 7.4: con longitud
`L`, el disparador de 5 m toma una foto cada `ceil(5 / L)` pasos, así que se esperan `floor(pasos / ceil(5 / L)) + 1`
fotos):

```markdown
# Registro de pruebas en dispositivo — FE-2.3 C3

| Fecha | Modelo | Android | Prueba | Recorrido | Pasos | `distanciaMetros` | Longitud guardada (`fecha_ms`) | Fotos frente a `5 / longitud` | Error final medido | Notas |
|---|---|---|---|---|---|---|---|---|---|---|
| AAAA-MM-DD | 23028RA60L | 14 | 7.3b | Tramo A→B de N m (dónde) | N | — | L m (`fecha_ms`) | — | — | |
| AAAA-MM-DD | 23028RA60L | 14 | PDR (mapa público) | Inicio → fin, N m (dónde) | N | N m | L m | — | N m | |
| AAAA-MM-DD | 23028RA60L | 14 | 7.3 | Punto de inicio (dónde) | — | — | L m | — | N m (punto marcado frente al real) | rumbo de la brújula frente al real |
| AAAA-MM-DD | 23028RA60L | 14 | 7.4 | Inicio → fin, N m, `rec_NNNN` | N | N m (≈ pasos × L) | L m | N fotos; esperadas floor(pasos / ceil(5 / L)) + 1 | N m | |
```

**C4 — procedimiento** (basta estar quieto; ARCHITECTURE §5.2, «Retomar»).
1. `adb exec-out run-as com.example.myapplication ls -1 files/recoleccion > $EVID/c4-recoleccion.txt` (lista «antes»).
2. Empezar a grabar el video corto de la pantalla. Panel → Recolector → punto en el mapa → «Confirmar y comenzar»;
   cambiar el intervalo a «Cada 3 s» y esperar **≥ 5 fotos**.
3. Pulsar **Inicio** del sistema (la grabación se pausa y guarda su progreso) y matar el proceso:
   `adb shell am kill com.example.myapplication`. Comprobar que murió: `adb shell pidof com.example.myapplication` sin
   salida.
4. Abrir la app desde el lanzador. Esperado: Android restaura la pila y 7.4 aparece **en pausa** con el aviso «Grabación
   retomada: N fotos guardadas. Revisa tu posición y pulsa Reanudar.», el mismo nombre, las fotos y el intervalo «Cada
   3 s». Si en cambio sale Inicio: entrar como admin → Recolector, tocar «Retomar «video_N»» (fila ámbar) y seguir.
5. «Reanudar», esperar otras 5 fotos y «Finalizar video». Parar el video de pantalla.
6. `adb exec-out run-as com.example.myapplication ls -1 files/recoleccion >> $EVID/c4-recoleccion.txt` y
   `adb exec-out run-as com.example.myapplication cat files/recoleccion/rec_NNNN/manifest.json > $EVID/c4-manifest.json`.
   Pasa si entre «antes» y «después» hay **una sola** carpeta `rec_NNNN` nueva y su manifest tiene `estado = finalizado` y
   fotos `0001`… seguidas sin huecos ni repetidas (unas 10). Para verlo:
   `python3 -c "import json,sys; d=json.load(open(sys.argv[1])); print(d['estado'], [p['id'] for p in d['photos']])" $EVID/c4-manifest.json`.

**C5 — procedimiento** (ARCHITECTURE §5.2, «Segundo plano»; el formato de `dumpsys` está sin comprobar en el Xiaomi).
1. **Calibración:** abrir 7.3b, marcar A y B y tocar «Inicio» (fase «Caminando»). Pulsar Inicio del sistema, esperar
   10 s y `adb shell dumpsys sensorservice > $EVID/c5-calibracion-fondo.txt`. Volver a la app: la medición quedó
   cancelada con un aviso (es lo esperado: una pasada interrumpida no sirve).
2. **Mapa público:** abrirlo como en C3 (paso 2), tocar un punto y ▶ (siguiendo pasos). Pulsar Inicio del sistema,
   esperar 10 s y `adb shell dumpsys sensorservice > $EVID/c5-mapa-fondo.txt`. Volver a la app, esperar 5 s y
   `adb shell dumpsys sensorservice > $EVID/c5-mapa-frente.txt`.
3. `adb exec-out run-as com.example.myapplication cat files/logs/app.log | grep "I/Pdr" | tail -n 20 > $EVID/c5-app-log.txt`.
4. Pasa si en los dos archivos `…-fondo.txt` no hay ninguna conexión **activa** de `com.example.myapplication` al
   acelerómetro ni al vector de rotación (buscar `com.example.myapplication` en la sección de conexiones activas; el
   historial de registros anteriores también la nombra y no cuenta), si en `c5-mapa-frente.txt` sí la hay, y si
   `c5-app-log.txt` muestra `sensores quitados (detener)` en la calibración, `sensores quitados (segundo plano)` en el
   mapa y `sensores registrados (primer plano; …)` al volver al mapa.

## 4. Datos de prueba y limpieza

No crea nada en el backend ni en AWS. En el teléfono, `installDebug` conserva los datos de la app (recorridos,
calibración, `app.log`) y el script **no** usa `pm clear` (borraría `campus_calibracion`); no registra limpiezas. La
calibración nueva de C3 **se conserva** (es la que se usará para recolectar el dataset real). Los videos locales de C3
y C4 quedan en `files/recoleccion/`: la persona los descarta en la app si no los va a subir (aún no hay vista para
borrarlos: FE-2.1/FE-4.1; mientras tanto no estorban). Los archivos de `evidencia/fe-2-3/` no llevan secretos (no hay
tokens en `app.log` ni en `dumpsys`).

## 5. Cómo ejecutarlo

```bash
cd FRONTEND_KOTLIN/project
uv run --group ops python src/ops/validate23.py --entorno dev
```

**Variables** (detalle en `ARCHITECTURE.md` §5.11). En la máquina del equipo el validador corre en WSL y usa el
Gradle y el `adb` de Windows (ARCHITECTURE §4.1); no necesita AWS ni la API:

| Variable | Valor en WSL | Obligatoria |
|---|---|---|
| `VALIDACION_GRADLE` | `cmd.exe /c .\gradlew.bat` | Sí en WSL (WSL no tiene JDK ni SDK) |
| `JAVA_HOME` | `C:\Users\frank\.jdks\jbr-21.0.11` (el JBR 21; el de Android Studio es Java 25 y Gradle 8.7 no lo admite) | Sí en WSL |
| `WSLENV` | `JAVA_HOME:ANDROID_SERIAL` (pasa esas dos a los procesos de Windows) | Sí en WSL |
| `VALIDACION_ADB` | `/mnt/c/Users/frank/AppData/Local/Android/Sdk/platform-tools/adb.exe` | Sí en WSL, en `dev` |
| `ANDROID_SERIAL` | Solo si hay varios dispositivos | No |
| `UV_PROJECT_ENVIRONMENT` | `/root/.cache/uv-envs/fe-ops` (el `.venv` fuera de `/mnt/c`, más rápido) | No |

Herramientas: `uv` en WSL y, en Windows, el JBR 21 y el Android SDK. Duración aproximada: 3–5 min de script (Gradle de
C1 y `installDebug`, 1–2 min cada uno), más 60–90 min de pruebas en el campus (C3) y ~15 min de C4 y C5. No necesita
`embedding` (sin hora límite). El informe queda en `project/.validacion/FE-2.3-<AAAAMMDD-HHMMSS>.json` (hora UTC) o en
`--informe RUTA`.

**Preparación.**

1. Variables del entorno (en la misma terminal de WSL donde se ejecutará el validador):
   ```bash
   cd /mnt/c/Users/frank/Documents/baul/uni/2026-2/P2/4U_project/FRONTEND_KOTLIN/project
   export JAVA_HOME='C:\Users\frank\.jdks\jbr-21.0.11'
   export WSLENV=JAVA_HOME:ANDROID_SERIAL
   export VALIDACION_GRADLE='cmd.exe /c .\gradlew.bat'
   export VALIDACION_ADB=/mnt/c/Users/frank/AppData/Local/Android/Sdk/platform-tools/adb.exe
   export UV_PROJECT_ENVIRONMENT=/root/.cache/uv-envs/fe-ops
   export EVID=../docs/validation/evidencia/fe-2-3
   ```
   Esperado: sin salida.
2. Pruebas y estilo de los validadores:
   ```bash
   uv run --frozen ruff check . && uv run --frozen ruff format --check . && uv run --frozen pytest -q
   ```
   Esperado: `All checks passed!`, `9 files already formatted` y `93 passed`.
3. Compilación y pruebas unitarias de la app:
   ```bash
   cmd.exe /c '.\gradlew.bat' --console=plain testDebugUnitTest assembleDebug
   ```
   Esperado: `BUILD SUCCESSFUL` (102 casos, sin fallos). Si dice `Unable to delete directory '…\app\build\…'`, borrar
   `app/build` (`rm -rf app/build`) y repetir (ARCHITECTURE §4.1, «Trampas»).
4. Copia de trabajo limpia (si no, el informe sale con `-dirty`; ARCHITECTURE §5.11, «Trampas»):
   ```bash
   git -c core.autocrlf=input status --short -- .
   ```
   Esperado: sin salida.
5. Teléfono: conectado por USB a Windows, con la depuración USB autorizada y desbloqueado:
   ```bash
   $VALIDACION_ADB devices
   ```
   Esperado: una línea `<serial>	device` (no `unauthorized` ni `offline`).
6. Solo en Xiaomi (MIUI/HyperOS): «Instalar vía USB» activo en Opciones de desarrollador (ya hecho en FE-1.1; si al
   instalar aparece un diálogo en el teléfono, aceptarlo). Este validador no usa `pm grant` ni `input`, así que no
   necesita «Depuración USB (Configuración de seguridad)».
7. Carpeta de la evidencia:
   ```bash
   mkdir -p $EVID && ls -d $EVID
   ```
   Esperado: `../docs/validation/evidencia/fe-2-3`.

**Ejecución.**

```bash
uv run --group ops python src/ops/validate23.py --entorno dev
```

Esperado (código 0; por stderr salen además `· instalando el APK de depuración (installDebug, conserva los datos)`,
`· teléfono: …`, `· calibración guardada: …`, `· recorridos locales …` y la ruta del informe):

```
[PASA] P1 Gradle 8.7, JVM 21.0.11 (JetBrains s.r.o. 21.0.11+1-b1163.116)
[PASA] P2 23028RA60L (Android 14, SDK 34, serial <serial>)
[PASA] C1 CalibracionPasoTest 13/13, StepDetectorTest 11/11, DisparadorCapturaTest 10/10, DerivaTest 6/6 (mínimos 8, 6, 6, 4)
[PASA] C2 recoleccion_mapa.js 1× MapaBase.crearMapa; calibracion_mapa.js 1× MapaBase.crearMapa; ninguna base.crearMapa
[MANUAL] C3 [23028RA60L, Android 14 (SDK 34); calibración guardada: …; recorridos locales (files/recoleccion): …] Recalibra en 7.3b (Panel → Recolector → «Calibrar mi paso») …
[MANUAL] C4 [23028RA60L, …] 7.4 en «Cada 3 s», quieto: espera ≥ 5 fotos, pulsa Inicio del sistema y `adb shell am kill com.example.myapplication` …
[MANUAL] C5 [23028RA60L, …] Con la calibración en CAMINANDO y, aparte, con el mapa público siguiendo pasos …
Resultado: pasa (código 0)
```

Después, las manuales de §3 en este orden: C4 y C5 (en cualquier sitio, ~15 min), luego C3 en el campus. La app queda
instalada y abierta como la dejó la persona.

Casos previstos:
- `[FALLA] P2 adb devices no muestra ningún dispositivo` (código 3) → paso 5.
- `[ERROR] installDebug: INSTALL_FAILED_USER_RESTRICTED …` (código 3) → paso 6.
- `[FALLA] C1 <Clase>: sin resultados; Gradle salió con 1: …` → error de compilación o de Gradle; el final de la salida
  está en el detalle. Con `[FALLA] C1 … N fallos`, ver el XML de esa clase en `app/build/test-results/testDebugUnitTest/`.
- `[FALLA] C2 <archivo>: 1 llamada(s) a base.crearMapa(` → cambiar a `MapaBase.crearMapa(` (§5.9).

En `local` (sin teléfono): `uv run --group ops python src/ops/validate23.py --entorno local` da código 0 con `[PASA]`
en P1, C1 y C2 y las tres `[MANUAL]` con «entorno local: sin datos del teléfono» (comprobado el 2026-10-25). Sin
teléfono en `dev`, P2 falla y el código es 3.

Con el validador en `dev` con código 0 sobre un commit de `main` sin `-dirty` y la evidencia de C3, C4 y C5 en
`evidencia/fe-2-3/`, la fila FE-2.3 de PLAN §3 pasa a «Hecho» y se quitan de ARCHITECTURE los «a verificar en
dispositivo (FE-2.3 …)» que la evidencia confirme.
