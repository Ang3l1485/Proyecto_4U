# Validación 2-2 — FE-2.2 Panel con datos reales

| Campo | Valor |
|---|---|
| Lote | `FE-2.2` — criterios en [`PLAN.md`](../PLAN.md) §2.2 |
| Script | `project/src/ops/validate22.py` |
| Entornos | `dev` con dispositivo físico |
| Criterios | Automáticos: C1, C2 · Manuales: ninguno |

Contrato común de los validadores: `INFRASTRUCTURA_TERRAFORM/docs/ARCHITECTURE.md` §5.11. Lo propio de esta carpeta:
`ARCHITECTURE.md` §5.11.

## 1. Precondiciones

Si alguna no se cumple, el script termina con código 2 y el lote queda `Bloqueado`.

| ID | Qué debe cumplirse | Cómo lo comprueba el script |
|---|---|---|
| P1 | `FE-2.1` en «Hecho»: cola local de subida | Fila de `FE-2.1` en `PLAN.md` §3 = `Hecho` |
| P2 | `BE-2.3` en «Hecho»: resumen del panel | Fila en `BACKEND_FASTAPI/docs/PLAN.md` §3 = `Hecho`; `GET /v1/admin/stats` con token de admin responde 200 con `total_fotos`, `total_lugares`, `alertas_activas` y `ultimo_video` (sin credenciales válidas: código 3) |
| P3 | Dispositivo físico y Gradle | `adb devices` con uno en estado `device` (el de `ANDROID_SERIAL` si hay varios), `ro.kernel.qemu` distinto de `1` y `./gradlew --version` con salida 0 |

## 2. Comprobaciones automáticas

Orden: instala el APK (`./gradlew installDebug`), hace el paso guiado de C2, crea los datos de §4 y entra al Panel
iniciando sesión por la interfaz como en `validation-1-2` C1 (`am force-stop`, `am start`, «Acceso administrador»).
Lee el Panel con `adb shell uiautomator dump` (cada dato se anuncia completo, p. ej. «2.842 fotos en el dataset»).

| ID | Qué hace el script | Pasa si |
|---|---|---|
| C1 | Llama a `GET /v1/admin/stats` justo antes y justo después de leer el Panel y compara total de fotos, lugares, alertas activas y último video (número, y fecha de `ultimo_video.creado_en` en la zona horaria del teléfono, `adb shell getprop persist.sys.timezone`, con el formato «Hoy, HH:mm» / «Ayer, HH:mm» / «d MMM, HH:mm» de 5.5) | Las dos respuestas son iguales y los cuatro datos del Panel (quitado el separador de miles) coinciden con ellas; con `ultimo_video = null` el Panel muestra «—» |
| C2 | **Paso guiado:** pide grabar un video de prueba `validacion-2-2` en el sitio (modo «cada 3 s», unos 30 s), «Finalizar» y «Guardar y subir después», y espera Enter. Después cuenta las fotos con `"sync": "pendiente"` en los `files/recoleccion/*/manifest.json` con `"estado": "finalizado"` (§5.10, «Subida de un recorrido») (`adb exec-out run-as com.example.myapplication cat …`) | El dato «fotos pendientes» del Panel es igual a ese conteo y el conteo es ≥ 1 |

## 3. Comprobaciones manuales

Ninguna: todos los criterios son automáticos.

## 4. Datos de prueba y limpieza

Para que C1 no compare solo ceros, si `GET /v1/admin/places` responde 200 (BE-3.1 desplegado) crea con la API un lugar
`validacion-2-2-lugar` (`POST /v1/admin/places`,
categoría `bloque`, coordenada del primer lugar de `GET /v1/places` desplazada 0,0005°) y una alerta activa con
mensaje `validacion-2-2-alerta` (`PUT /v1/admin/alerts/{uuid nuevo}`). Al terminar, también si algo falló, los borra
con `DELETE /v1/admin/places/{id}` y `DELETE /v1/admin/alerts/{id}`. Al empezar, borra los lugares y alertas
`validacion-2-2` que haya dejado una ejecución anterior (`GET /v1/admin/places?q=validacion-2-2`,
`GET /v1/admin/alerts?q=validacion-2-2`). El video local del paso guiado no se sube: la persona lo descarta al
final en 7.5 («Descartar video»); el script no usa `pm clear`. Al cerrar hace `am force-stop`, que deja el teléfono
sin sesión (5.3).

## 5. Cómo ejecutarlo

```bash
cd FRONTEND_KOTLIN/project
uv run --group ops python src/ops/validate22.py --entorno dev
```

Variables: `VALIDACION_API_URL`, `VALIDACION_ADMIN_CORREO`, `VALIDACION_ADMIN_PASSWORD` (`ARCHITECTURE.md` §5.11)
y `ANDROID_SERIAL` si hay varios dispositivos. Duración aproximada: 6 minutos, incluido el paso guiado.
