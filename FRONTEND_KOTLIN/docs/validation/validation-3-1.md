# Validación 3-1 — FE-3.1 Lugares y alertas públicas con caché local

| Campo | Valor |
|---|---|
| Lote | `FE-3.1` — criterios en [`PLAN.md`](../PLAN.md) §2.2 |
| Script | `project/src/ops/validate31.py` |
| Entornos | `dev` con dispositivo físico |
| Criterios | Automáticos: C1, C2a, C2b, C4 · Manuales: C3 |

Contrato común de los validadores: `INFRASTRUCTURA_TERRAFORM/docs/ARCHITECTURE.md` §5.11. Lo propio de esta carpeta:
`ARCHITECTURE.md` §5.11.

## 1. Precondiciones

Si alguna no se cumple, el script termina con código 2 y el lote queda `Bloqueado`.

| ID | Qué debe cumplirse | Cómo lo comprueba el script |
|---|---|---|
| P1 | `FE-1.1` en «Hecho»: cliente HTTP contra `dev` | Fila de `FE-1.1` en `PLAN.md` §3 = `Hecho` y `GET /v1/health` responde 200 |
| P2 | `BE-3.1` en «Hecho»: lugares y alertas | Fila en `BACKEND_FASTAPI/docs/PLAN.md` §3 = `Hecho`; `GET /v1/places` responde 200 con ≥ 1 lugar y `GET /v1/alerts` responde 200 con `generado_en` y `completo = true` |
| P3 | Credenciales de admin para crear las alertas de prueba | `POST /v1/auth/login` con las credenciales de admin responde 200 (con `401`: código 3) |
| P4 | Dispositivo físico y Gradle | `adb devices` con uno en estado `device` (el de `ANDROID_SERIAL` si hay varios), `ro.kernel.qemu` distinto de `1` y `./gradlew --version` con salida 0 |

## 2. Comprobaciones automáticas

Instala el APK con `./gradlew installDebug`. La «siguiente sincronización» se provoca reiniciando la app
(`am force-stop` y `am start -n com.example.myapplication/.MainActivity`) y esperando 20 s. La caché se lee copiando la
base de Room de las alertas con `adb exec-out run-as com.example.myapplication cat databases/campus_locator.db` (tabla
`alertas`, §5.10) y
abriéndola con `sqlite3` de Python.

| ID | Qué hace el script | Pasa si |
|---|---|---|
| C1 | **Paso guiado:** pide abrir Selección de destino (por voz «dos» o con la acción de TalkBack «Ir a un lugar») y espera Enter. Lee la lista con `uiautomator dump`, desplazándola con `adb shell input swipe` hasta el final, y la compara con `GET /v1/places` | Los nombres de las filas (`FilaLugar`) son exactamente los de `items[].nombre`, sin faltantes ni sobrantes, e incluye `validacion-3-1-lugar` (§4) |
| C2a | Crea la alerta `validacion-3-1-c2` con `PUT /v1/admin/alerts/{uuid}`, provoca una sincronización y lee la caché | La caché tiene una fila con ese `id`, `mensaje` y `radio = 15` |
| C2b | Borra la alerta con `DELETE /v1/admin/alerts/{id}`, provoca otra sincronización y vuelve a leer la caché | `GET /v1/alerts?desde=<generado_en anterior>` trae el `id` en `eliminadas` y la caché ya no tiene ese `id` |
| C4 | `./gradlew testDebugUnitTest --tests '*.DetectarAlertasCercanasTest'` | Sale con 0 y los XML de `app/build/test-results/testDebugUnitTest/` suman ≥ 4 casos y 0 fallos (la revisión del PR confirma que cubren radio, incertidumbre, una vez por aproximación y vigencia) |

## 3. Comprobaciones manuales

Antes de limpiar, el script espera Enter para que la persona haga C3 con la alerta `validacion-3-1-c3` (§4).

| ID | Qué hace la persona | Evidencia en el PR |
|---|---|---|
| C3 | Con red, abre la app y espera 20 s (sincroniza). Activa el modo avión, ve a ≥ 50 m del lugar que imprime el script, abre el mapa público desde Inicio (comando de voz «mapa» o acción de TalkBack «Ver mapa»: ruta `mapa`, `MapaPublicoScreen`, posición por PDR), fija ahí el inicio y camina hasta el lugar | Video con audio: modo avión visible y la app leyendo «validacion-3-1-c3» al entrar en el radio, una sola vez mientras sigue dentro |

## 4. Datos de prueba y limpieza

Crea con la API: el lugar `validacion-3-1-lugar` (`POST /v1/admin/places`, categoría `bloque`, junto al primer lugar
de `GET /v1/places`), la alerta de C2 y la alerta `validacion-3-1-c3` (prioridad `alta`, radio 15 m, en la coordenada
del primer lugar de `GET /v1/places` por nombre, que el script imprime). Al terminar, también si algo falló, borra con
`DELETE /v1/admin/places/{id}` y `DELETE /v1/admin/alerts/{id}` todo lo que empiece por `validacion-3-1`; al empezar,
hace lo mismo con los restos de una ejecución anterior (`GET /v1/admin/places?q=` y `GET /v1/admin/alerts?q=`). La
caché del teléfono se vacía sola en la siguiente sincronización; el script no usa `pm clear`.

## 5. Cómo ejecutarlo

```bash
cd FRONTEND_KOTLIN/project
uv run --group ops python src/ops/validate31.py --entorno dev
```

Variables: `VALIDACION_API_URL`, `VALIDACION_ADMIN_CORREO`, `VALIDACION_ADMIN_PASSWORD` (`ARCHITECTURE.md` §5.11)
y `ANDROID_SERIAL` si hay varios dispositivos. Duración aproximada: 8 minutos, más 15 de la manual C3.
