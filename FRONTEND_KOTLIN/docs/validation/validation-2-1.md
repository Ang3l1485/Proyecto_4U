# Validación 2-1 — FE-2.1 Subida de recorridos y Resumen de video (7.5)

| Campo | Valor |
|---|---|
| Lote | `FE-2.1` — criterios en [`PLAN.md`](../PLAN.md) §2.2 |
| Script | `project/src/ops/validate21.py` |
| Entornos | `dev` (cierra el lote, junto con la evidencia de C2c): usa la API de `dev`, S3 (solo lectura) y, si hace falta, enciende `embedding`; **no** necesita el teléfono conectado (el recorrido lo grabó y subió la persona en la preparación). `local` (sin teléfono, API ni AWS: C2a, C3a y C4) |
| Criterios | Automáticos: C1, C2 (apoyo: C2a y C2b), C3 (C3a y C3b), C4 · Manuales: C2 (C2c, el corte de red) |

Contrato común de los validadores: `INFRASTRUCTURA_TERRAFORM/docs/ARCHITECTURE.md` §5.11. Lo propio de esta carpeta
(dónde corren, variables, `comun.py`, detalles de `validate21.py`, trampas): `ARCHITECTURE.md` §5.11. Piezas que se
comprueban: `ARCHITECTURE.md` §4.4 (lo construido en FE-2.1), §5.5 (vista 7.5 y Panel), §5.6 (repositorio compuesto y
claves del manifest), §5.8 (ruta de 7.5) y §5.10 («Subida de un recorrido»). Contrato del backend que se consume:
`BACKEND_FASTAPI/docs/ARCHITECTURE.md` §5.4 y §5.5.

## 1. Precondiciones

Se evalúan en este orden y el script no sigue si una falla (las siguientes quedan «no evaluada»). Las de la máquina, las
credenciales o los datos de la persona dan **3**; las de otros lotes, **2** (lote `Bloqueado`). En `local` solo se
evalúa P1.

| ID | Qué debe cumplirse | Cómo lo comprueba el script |
|---|---|---|
| P1 | Gradle y un JDK que lo ejecute | `<VALIDACION_GRADLE> --version` termina con 0 (detalle: versión de Gradle y JVM). Si no → 3 |
| P2 | `--video` y acceso a AWS (solo `dev`) | Hay `--video <nombre>` (si no → 3). Si C1 o C3b están incluidas: `aws sts get-caller-identity` (perfil de `AWS_PROFILE`) da la cuenta `648617469176` (si no, o sin credenciales → 3) y `terraform output -json` de `INFRASTRUCTURA_TERRAFORM/project/envs/dev` trae `bucket_dataset`, `ecs_cluster` y `ecs_servicios` (sin Terraform, `init` o credenciales → 3; falta un output → 2). Con `--solo` sin C1 ni C3b no mira AWS |
| P3 | `FE-1.2` en «Hecho» y login de admin contra `dev` | La fila de `FE-1.2` en `PLAN.md` §3 dice `Hecho` (si no → 2); URL vigente = `terraform output -raw api_base_url` + `/v1` (sin Terraform, `VALIDACION_API_URL`; sin ninguna → 3); `GET <URL>/health` → 200 `"estado": "ok"` (si no → 2); `POST <URL>/auth/login` con `VALIDACION_ADMIN_CORREO`/`VALIDACION_ADMIN_PASSWORD` o el secreto `campus-locator/dev/admin-inicial` → 200 con `token` y `usuario.rol = "admin"` (`401` o rol distinto → 3; otro código → 2). El token se usa en las siguientes y nunca se imprime |
| P4 | `FE-2.3` en «Hecho»: el PDR que etiqueta las fotos está probado en dispositivo | La fila de `FE-2.3` en `PLAN.md` §3 dice `Hecho` y su «Última validación» no está vacía ni es «—». Si no → 2 |
| P5 | `BE-2.1` en «Hecho»: endpoints de recolección | La fila en `BACKEND_FASTAPI/docs/PLAN.md` §3 dice `Hecho` y `POST <URL>/collect/videos` con el token y cuerpo `{}` responde `422 VALIDACION` (existe y no crea nada). Si no → 2 |
| P6 | `BE-2.2` en «Hecho»: ingesta | La fila en `BACKEND_FASTAPI/docs/PLAN.md` §3 dice `Hecho` y `GET <URL>/health/ready` responde 200 con `"db": "ok"` (el detalle dice además cómo está `embedding`). Si no → 2 |
| P7 | El recorrido de `--video` está en el backend | `GET <URL>/admin/videos?q=<nombre>&por_pagina=100` con el token: exactamente **un** video cuyo `nombre`, sin espacios alrededor, es el de `--video` (el `q` del backend busca «contiene» sin distinguir mayúsculas: aquí se exige igual); lee su detalle `GET <URL>/admin/videos/{id}`. Ninguno o varios → 3 (subida sin terminar, nombre mal escrito o repetido) |
| P8 | `embedding` encendido mientras haga falta | No hace falta si C1 está excluida o el video ya está `procesado`. Si `/health/ready` ya dice `"embedding": "ok"`, publica un latido (`EmbeddingEncendidos`) y sigue. Si está apagado: pasadas las **21:30 de Bogotá** → 3 (se apaga solo a las 22:00); si no, comprueba los objetivos escalables de INF-2.1 (si faltan → 2), registra el apagado en la limpieza **antes** de encender y lo enciende con el contrato de infra §5.10 (`comun.EmbeddingDev`, hasta ~6 min; si no queda sano → 2). Al terminar, también si algo falló, lo apaga **solo** si lo encendió él (infra §5.11) |

## 2. Comprobaciones automáticas

Antes de ejecutar el script, la persona graba y sube el recorrido (preparación de §5, pasos 8 y 9). En `local`, C1, C2b
y C3b quedan `omitida`.

| ID | Qué hace el script | Pasa si |
|---|---|---|
| C1 | Lee `GET /v1/admin/videos/{id}` cada 30 s, hasta 15 min, mientras el video esté `pendiente` o `procesando` (la ingesta avanza con `embedding` encendido, P8) | `estado = "procesado"`, las fotos registradas (la suma del `conteo`) son ≥ 50 y `conteo.procesada` = registradas. Con `estado = "con_errores"` falla en el acto, con el primer motivo de `error` de las fotos; si a los 15 min no llegó, falla con el estado y el conteo (con `pendiente`: «¿terminó la subida en el teléfono?») |
| C2a | Borra los XML anteriores y ejecuta una vez `<VALIDACION_GRADLE> testDebugUnitTest --tests '*.SubidaRecorridoTest' --tests '*.ColaSubidaTest' --tests '*.AlmacenRecorridosTest'` (junto con C3a si está incluida); lee `app/build/test-results/testDebugUnitTest/TEST-*.<clase>.xml` | Gradle sale con 0 y cada clase tiene su XML, 0 fallos, 0 errores, 0 omitidos y al menos 10, 6 y 10 casos (hoy 13, 8 y 13). Cubren retomar sin duplicar (corte de red en un `PUT`, `403`, video remoto ya creado, foto que el backend ya tenía), «esperar sesión» sin peticiones ni bucles y la cola en disco (`ARCHITECTURE.md` §5.10); lo confirma la revisión del PR |
| C2b | Con el último detalle de C1 (o lo lee si C1 está excluida) | `ref_cliente` es un id local `rec_NNNN`, ningún `orden` se repite y el número de fotos del detalle = la suma del `conteo` = `total_fotos` (lo que la app declaró al crear el video): ninguna foto duplicada ni perdida en el backend |
| C3a | Como C2a, con `--tests '*.RecodificacionFotoTest'` | XML con 0 fallos, errores ni omitidos y ≥ 8 casos (hoy 12): lado mayor a 1600 px sin ampliar, orientación EXIF, escalera de calidades y de lados, foto ilegible y un barrido que nunca pasa de 1600 px ni de 4 194 304 bytes |
| C3b | Por cada foto del detalle lee el objeto `dataset/<video_id>/<imagen_id>.jpg` del bucket `bucket_dataset` con `aws s3api get-object --range bytes=0-131071` (4 a la vez; solo lectura, nunca URLs prefirmadas): el tamaño total sale de `ContentRange` y el ancho y el alto, del marcador SOF del JPEG | Todos son JPEG legibles, con ≤ 4 194 304 bytes y lado mayor ≤ 1600 px. El detalle da el máximo de cada uno; si falla, las primeras 5 fotos fuera de límites |
| C4 | Lee `app/src/main/java/com/example/myapplication/MainActivity.kt` (`AppNav`) | No queda `composable("admin/recoleccion/resumen") { /* placeholder */ }`; el bloque de la ruta `admin/recoleccion/resumen…` compone `ResumenVideoScreen(`; y el `onFinalizado` de `RecoleccionScreen` (ruta `admin/recoleccion`) navega a `admin/recoleccion/resumen` («Finalizar» en 7.4 abre 7.5) |

Por qué C3b mide en S3 y no descarga `url`: hasta BE-4.1 `url` llega `null` (backend §5.5); el objeto del bucket es lo
que de verdad recibió el backend (ADR-FE-21).

## 3. Comprobaciones manuales

La evidencia se guarda en [`evidencia/fe-2-1/`](./evidencia/) y se cita en el PR. En los comandos, `adb` es
`$VALIDACION_ADB` en WSL (§5) y `EVID=../docs/validation/evidencia/fe-2-1` desde `FRONTEND_KOTLIN/project`. El script la
imprime como `[MANUAL] C2c` (en `dev`, con el nombre, el id y el estado del video).

| ID | Qué hace la persona | Evidencia |
|---|---|---|
| C2c | Corta la red a mitad de la subida, cierra la app, la reabre y la subida termina sin duplicar fotos (procedimiento abajo; es el paso 9 de la preparación de §5) | `c2-video.mp4` (grabación de pantalla de 7.5 antes del corte y tras reabrir, hasta «Subido»; si muestra algo privado no se versiona y se cita en el PR), `c2-manifest.json` del recorrido y `c2-videos.png` (captura de 7.13 con el recorrido y el mismo número de fotos que 7.5). C2b del informe con `pasa` confirma que el backend no tiene fotos duplicadas |

**C2c — procedimiento** (`ARCHITECTURE.md` §5.10, «Subida de un recorrido» y «Subida y sesión»).
1. En 7.5 del recorrido grabado (paso 8 de §5), con red, comprobar el nombre, las estadísticas, el mapa y el carrusel.
   Empezar la grabación de pantalla (en el Xiaomi, «Grabadora de pantalla»).
2. Tocar **«Subir y procesar»**. La tarjeta pasa por «Preparando fotos: N de M» y después «Subiendo: X de N».
3. Cuando X esté entre el 20 % y el 60 % de N, activar el **modo avión**. La tarjeta dice «Sin conexión: reintento en
   N s».
4. Cerrar la app desde **Recientes** (deslizarla fuera) y esperar 10 s.
5. Quitar el modo avión y abrir la app desde el lanzador: sale Inicio (en un arranque en frío no hay sesión). «Acceso
   administrador» → iniciar sesión.
6. En el Panel aparece la tarjeta «Subida pendiente de «nombre»» o «Subiendo «nombre»» (el Panel retoma la cola solo).
   Tocarla: 7.5 sigue desde la foto donde se cortó hasta «Subido: procesando en el servidor». Parar la grabación.
7. Guardar el manifest y comprobarlo:
   `adb exec-out run-as com.example.myapplication cat files/recoleccion/rec_NNNN/manifest.json > $EVID/c2-manifest.json`
   y `python3 -c "import json,sys; d=json.load(open(sys.argv[1])); f=d['photos']; print(d.get('subida_estado'), d.get('remote_video_id') is not None, len(f), sum(p.get('sync') == 'subida' for p in f))" $EVID/c2-manifest.json`.
   Pasa si imprime `completada True N N` (N = el número de fotos de 7.5).
8. Panel → Videos (7.13): captura `c2-videos.png` con el recorrido y sus N fotos.

## 4. Datos de prueba y limpieza

El recorrido es **real** y se queda: es parte del dataset (lo usan EMB-3.2 y BE-3.2). El script no crea ni borra nada
en el backend (`POST /v1/collect/videos {}` de P5 da `422` y no crea nada) y solo **lee** S3; el login deja su fila en
`auditoria` (registro, se conserva). La única limpieza es apagar `embedding` si lo encendió el script (con
`--sin-limpieza` queda encendido: apagarlo con `embedding.py apagar` de infra, `INFRASTRUCTURA_TERRAFORM/docs/ARCHITECTURE.md`
§5.11). Si la validación falla por algo del recorrido (por ejemplo, menos de 50 fotos), la persona decide si lo
conserva o lo borra: borrar un video del backend es de BE-4.1 y FE-4.1 (hoy no hay forma desde la app; lo coordina el
maestro), y grabar otro recorrido no estorba (cada uno es un video distinto).

En el teléfono: la copia local queda en `files/recoleccion/rec_NNNN/` con `subida_estado = completada` y sin la carpeta
`subida/` (las copias re-codificadas se borran al completar; los originales se quedan). El script no usa `adb` ni
`pm clear`. Los archivos de `evidencia/fe-2-1/` no llevan secretos (el manifest no tiene tokens ni URLs).

## 5. Cómo ejecutarlo

```bash
cd FRONTEND_KOTLIN/project
uv run --group ops python src/ops/validate21.py --entorno dev --video "Entrada norte"
```

Argumentos propios: `--video <nombre exacto del recorrido>` (obligatorio en `dev`; en `local` se ignora) y
`--minimo-fotos N` (por defecto 50). Validación del 2026-10-26, por decisión del usuario: en casa, con el recorrido de
prueba `validacion-21-casa` de 10 fotos (`--minimo-fotos 10`), que el maestro borra del backend al terminar con
`limpiar-validacion` (no debe quedar en el dataset); la evidencia de C2c son capturas de 7.5 y 7.13 (el teléfono, un
Redmi Note 15 Pro, no tenía depuración USB). El recorrido real del campus sigue con 50 fotos.

**Variables** (detalle en `ARCHITECTURE.md` §5.11). En la máquina del equipo el validador corre en WSL, usa el Gradle de
Windows (ARCHITECTURE §4.1) y la CLI `aws` de WSL:

| Variable | Valor en WSL | Obligatoria |
|---|---|---|
| `VALIDACION_GRADLE` | `cmd.exe /c .\gradlew.bat` | Sí en WSL (WSL no tiene JDK ni SDK) |
| `JAVA_HOME` | `C:\Users\frank\.jdks\jbr-21.0.11` (el JBR 21; el de Android Studio es Java 25 y Gradle 8.7 no lo admite) | Sí en WSL |
| `WSLENV` | `JAVA_HOME:ANDROID_SERIAL` (pasa esas dos a los procesos de Windows) | Sí en WSL |
| `AWS_PROFILE` | `campus-admin` (`terraform output`, `aws sts`, el secreto del admin, S3 en C3b y `embedding` en P8) | Sí en `dev` |
| `VALIDACION_ADB` | `/mnt/c/Users/frank/AppData/Local/Android/Sdk/platform-tools/adb.exe` (solo para la preparación y la evidencia; el script no usa `adb`) | No (sí para los pasos 5, 6 y 9) |
| `VALIDACION_ADMIN_CORREO`, `VALIDACION_ADMIN_PASSWORD` | No hacen falta: sin ellas se usa el secreto `campus-locator/dev/admin-inicial` | No |
| `VALIDACION_API_URL` | No hace falta: solo se usa si `terraform output` falla | No |
| `ANDROID_SERIAL` | Solo si hay varios dispositivos | No |
| `UV_PROJECT_ENVIRONMENT` | `/root/.cache/uv-envs/fe-ops` (el `.venv` fuera de `/mnt/c`, más rápido) | No |

Herramientas: `uv`, `terraform` con `terraform init` hecho en `INFRASTRUCTURA_TERRAFORM/project/envs/dev`, la CLI `aws`
v2 en WSL y, en Windows, el JBR 21 y el Android SDK. Duración aproximada del script en `dev`: 5–25 min (Gradle 1–2 min;
`embedding` 3–6 min si estaba apagado; la ingesta, hasta 15 min; S3, 1–2 min para 80 fotos), más 60–90 min de
preparación (FE-2.3 C3, grabar 60–80 fotos caminando y subir). **Hora límite para empezar: 21:30 de Bogotá** si
`embedding` está apagado (se apaga solo a las 22:00); `embedding` cuesta ~0,10 USD/h y el script lo apaga al terminar si
lo encendió. El informe queda en `project/.validacion/FE-2.1-<AAAAMMDD-HHMMSS>.json` (hora UTC) o en `--informe RUTA`.

**Preparación.**

1. Variables del entorno (en la misma terminal de WSL donde se ejecutará el validador):
   ```bash
   cd /mnt/c/Users/frank/Documents/baul/uni/2026-2/P2/4U_project/FRONTEND_KOTLIN/project
   export AWS_PROFILE=campus-admin
   export JAVA_HOME='C:\Users\frank\.jdks\jbr-21.0.11'
   export WSLENV=JAVA_HOME:ANDROID_SERIAL
   export VALIDACION_GRADLE='cmd.exe /c .\gradlew.bat'
   export VALIDACION_ADB=/mnt/c/Users/frank/AppData/Local/Android/Sdk/platform-tools/adb.exe
   export UV_PROJECT_ENVIRONMENT=/root/.cache/uv-envs/fe-ops
   export EVID=../docs/validation/evidencia/fe-2-1
   ```
   Esperado: sin salida.
2. Pruebas y estilo de los validadores:
   ```bash
   uv run --frozen ruff check . && uv run --frozen ruff format --check . && uv run --frozen pytest -q
   ```
   Esperado: `All checks passed!`, `12 files already formatted` y `128 passed`.
3. Compilación y pruebas unitarias de la app:
   ```bash
   cmd.exe /c '.\gradlew.bat' --console=plain testDebugUnitTest assembleDebug
   ```
   Esperado: `BUILD SUCCESSFUL` (151 casos, sin fallos). Si dice `Unable to delete directory '…\app\build\…'`, borrar
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
6. Instalar el APK de depuración del commit que se valida (conserva los datos: calibración y recorridos):
   ```bash
   cmd.exe /c '.\gradlew.bat' --console=plain installDebug
   ```
   Esperado: `Installed on 1 device.` y `BUILD SUCCESSFUL`. En MIUI/HyperOS hace falta «Instalar vía USB» (si aparece un
   diálogo en el teléfono, aceptarlo); sin él, `INSTALL_FAILED_USER_RESTRICTED`.
7. Acceso a AWS y `dev`:
   ```bash
   aws sts get-caller-identity --query Account --output text
   curl -s "$(terraform -chdir=../../INFRASTRUCTURA_TERRAFORM/project/envs/dev output -raw api_base_url)/v1/health"
   mkdir -p $EVID && ls -d $EVID
   ```
   Esperado: `648617469176`, `{"estado":"ok","version":"…","commit":"<SHA corto>"}` y
   `../docs/validation/evidencia/fe-2-1`.
8. **En el campus** (el mismo día que FE-2.3 C3, que va primero: recalibrar en 7.3b y probar el PDR, `validation-2-3`
   §3): Panel → Recolector (7.3) → marcar el punto de inicio exacto y el rumbo → nombre descriptivo (p. ej. «Entrada
   norte»; es el `--video`) → «Confirmar y comenzar» con «Cada 5 m». Caminar un recorrido **real** de **60 a 80 fotos**
   (300–400 m) en una zona sin dataset, re-anclándose en puntos conocidos si hace falta → «Finalizar video» → se abre
   **7.5** (es lo que comprueba C4 en el código; aquí se ve): nombre, duración, distancia, fotos, mapa con la
   trayectoria y carrusel. Si alguna foto salió mal (dedo, cielo), descartarla en el carrusel. Si no hay buena señal,
   «Guardar y subir después»: el Panel lo ofrecerá luego en su tarjeta «Recorridos sin subir».
9. **Subir con el corte de red (C2c, §3):** con red (en el campus o después con Wi-Fi), en 7.5 → «Subir y procesar» y
   seguir el procedimiento de C2c (modo avión entre el 20 % y el 60 %, cerrar desde Recientes, reabrir, entrar, tarjeta
   del Panel → 7.5 hasta «Subido»), guardando `c2-video.mp4`, `c2-manifest.json` y `c2-videos.png` en `$EVID`. Esperado:
   `completada True N N` en la comprobación del paso 7 de C2c. Con `embedding` apagado, las fotos quedan «Subida» (no
   «Procesada»): es lo normal; el script lo enciende.

**Ejecución.** No necesita el teléfono (puede seguir conectado).

```bash
uv run --group ops python src/ops/validate21.py --entorno dev --video "Entrada norte"
```

Esperado (código 0; por stderr salen además líneas `· …` de progreso —el encendido de `embedding`, las consultas de C1
cada 30 s, la limpieza— y la ruta del informe):

```
[PASA] P1 Gradle 8.7, JVM 21.0.11 (JetBrains s.r.o. 21.0.11+1-b1163.116)
[PASA] P2 --video «Entrada norte»; cuenta 648617469176 (root); bucket y servicios de ECS
[PASA] P3 FE-1.2 Hecho; terraform output api_base_url; GET /v1/health -> 200; login admin 200 (admin@campus.edu.co)
[PASA] P4 FE-2.3 Hecho (`<commit>` <fecha>)
[PASA] P5 BE-2.1 Hecho; POST /v1/collect/videos {} -> 422 VALIDACION (no crea nada)
[PASA] P6 BE-2.2 Hecho; /v1/health/ready db ok, embedding no_disponible
[PASA] P7 «Entrada norte»: n.º <n>, ref_cliente rec_NNNN, estado procesando, <N> fotos
[PASA] P8 encendido por el validador en <s> s (se apaga al terminar)
[PASA] C1 estado procesado; <N> fotos, procesada <N> (esperó <s> s)
[PASA] C2a SubidaRecorridoTest 13/13, ColaSubidaTest 8/8, AlmacenRecorridosTest 13/13 (mínimos 10, 6, 10)
[PASA] C2b ref_cliente rec_NNNN; <N> fotos = total_fotos, órdenes sin repetir
[PASA] C3a RecodificacionFotoTest 12/12 (mínimos 8)
[PASA] C3b <N> fotos en S3: máx. <bytes> B (límite 4194304) y máx. 1600 px de lado mayor (límite 1600)
[PASA] C4 ruta admin/recoleccion/resumen?video={video} → ResumenVideoScreen; onFinalizado de 7.4 navega a ella
[MANUAL] C2c [video «Entrada norte» (<uuid>), estado procesado] Durante la subida de la preparación (validation-2-1 §5, paso 9), …
Resultado: pasa (código 0)
```

Con `embedding` ya encendido, P8 dice «ya estaba encendido (latido publicado)» y no lo apaga; con el video ya
`procesado`, «no hace falta: el video ya está procesado» y C1 pasa en la primera consulta. Al terminar, si lo encendió,
en stderr `· limpieza: apagar embedding (lo encendió el validador)`.

Casos previstos:
- `[FALLA] P4 FE-2.3 no está «Hecho» con «Última validación»…` (código 2) → cerrar antes FE-2.3 (C3 del mismo día).
- `[FALLA] P7 no hay ningún video llamado «…» en el backend…` (código 3) → la subida del paso 9 no terminó (abrir el
  Panel en el teléfono: la tarjeta la retoma) o el nombre no es exacto (mirarlo en 7.13).
- `[FALLA] P8 son las HH:MM en Bogotá…` (código 3) → repetir antes de las 21:30.
- `[FALLA] P8 INF-2.1: embedding no quedó sano en 10 min (…)` (código 2) → la limpieza lo apaga; repetir, y si vuelve a
  pasar, avisar al maestro (infra §5.10).
- `[FALLA] C1 en 15 min el video no llegó a procesado: estado pendiente (¿terminó la subida en el teléfono?)` → abrir
  7.5 en el teléfono y esperar a «Subido»; repetir el script (es idempotente).
- `[FALLA] C1 en 15 min … estado procesando` → el `worker` tarda en subir (métricas con minutos de retraso, infra §3.4):
  repetir el script; `embedding` sigue encendido mientras haya mensajes en `ingesta`.
- `[FALLA] C1 estado con_errores: N foto(s) en error (p. ej. «…»)` → el motivo es del backend (backend §4.6, p. ej.
  «lado menor …»); avisar al maestro con el motivo.
- `[FALLA] C2b … fotos en el detalle, … en el conteo y total_fotos …` → fotos perdidas o duplicadas: revisar el
  manifest del teléfono (`c2-manifest.json`) y avisar.
- `[FALLA] C3b N foto(s) fuera de límites: …` → la re-codificación no cumplió C3: avisar con el detalle.
- `[FALLA] P2 AWS_PROFILE apunta a la cuenta …` o `… credenciales o permisos de AWS …` (código 3) → `AWS_PROFILE`.

En `local` (sin teléfono, API ni AWS): `uv run --group ops python src/ops/validate21.py --entorno local` da código 0 con
`[PASA]` en P1, C2a, C3a y C4, `[OMITIDA]` en C1, C2b y C3b y la `[MANUAL]` C2c con «entorno local: sin backend»
(comprobado el 2026-10-25).

Con el validador en `dev` con código 0 sobre un commit de `main` sin `-dirty` y la evidencia de C2c en
`evidencia/fe-2-1/`, la fila FE-2.1 de PLAN §3 pasa a «Hecho» y se quitan de ARCHITECTURE los «a verificar en
dispositivo y en `dev` (FE-2.1 …)» que la evidencia confirme.
