# Validación 4-1 — FE-4.1 Videos e imágenes contra el backend (7.11–7.14)

| Campo | Valor |
|---|---|
| Lote | `FE-4.1` — criterios en [`PLAN.md`](../PLAN.md) §2.2 |
| Script | `project/src/ops/validate41.py` |
| Entornos | `dev` con dispositivo físico |
| Criterios | Automáticos: C1a, C1b, C3 · Manuales: C2 |

Contrato común de los validadores: `INFRASTRUCTURA_TERRAFORM/docs/ARCHITECTURE.md` §5.11. Lo propio de esta carpeta:
`ARCHITECTURE.md` §5.11.

## 1. Precondiciones

Si alguna no se cumple, el script termina con código 2 y el lote queda `Bloqueado`.

| ID | Qué debe cumplirse | Cómo lo comprueba el script |
|---|---|---|
| P1 | `FE-2.1` en «Hecho»: subida de recorridos y `VideoRepository` compuesto | Fila de `FE-2.1` en `PLAN.md` §3 = `Hecho` |
| P2 | `BE-4.1` en «Hecho»: administración de videos e imágenes | Fila en `BACKEND_FASTAPI/docs/PLAN.md` §3 = `Hecho`; con token de admin, `GET /v1/admin/videos` y `GET /v1/admin/images` responden 200 (sin credenciales válidas: código 3) |
| P3 | Recolección disponible para crear los videos de prueba (BE-2.1) | `POST /v1/collect/videos` con cuerpo `{}` responde `422 VALIDACION` |
| P4 | Dispositivo físico y Gradle | `adb devices` con uno en estado `device` (el de `ANDROID_SERIAL` si hay varios), `ro.kernel.qemu` distinto de `1` y `./gradlew --version` con salida 0 |

## 2. Comprobaciones automáticas

Instala el APK con `./gradlew installDebug` e inicia sesión por la interfaz como en `validation-1-2` C1; lee las
pantallas Compose con `adb shell uiautomator dump`.

| ID | Qué hace el script | Pasa si |
|---|---|---|
| C1a | Busca en `app/src/main/java/` `EdicionesLocales` y las construcciones de `AssetsVideoRepository(` en las `Factory` de `GaleriaViewModel`, `VideosViewModel` y `VideoDetalleViewModel` | No hay ninguna coincidencia |
| C1b | Desde el Panel abre «Videos» (7.13) y luego, con Atrás, «Imágenes» (7.11); lee los contadores «N videos» y «N imágenes» y los compara con `total` de `GET /v1/admin/videos` y `GET /v1/admin/images` | Los dos contadores coinciden y la lista de 7.13 incluye `validacion-4-1-a` y `validacion-4-1-b` |
| C3 | **Paso guiado:** pide abrir `validacion-4-1-a` en 7.14, «Renombrar» a `validacion-4-1-renombrado` y Guardar; espera Enter y consulta `GET /v1/admin/videos/{id}` | `nombre = "validacion-4-1-renombrado"` |

## 3. Comprobaciones manuales

Antes de limpiar, el script espera Enter para que la persona haga C2.

| ID | Qué hace la persona | Evidencia en el PR |
|---|---|---|
| C2 | Sin cerrar la app: en 7.14 abre `validacion-4-1-b`, «Eliminar video», escribe el nombre exacto y confirma; al volver a 7.13 comprueba que no está y abre «Imágenes» (7.11) filtrando por video | Video continuo, sin reiniciar la app: el borrado, 7.13 sin `validacion-4-1-b` y el filtro de video de 7.11 sin él ni sus fotos |

## 4. Datos de prueba y limpieza

Crea con la API de recolección (§5.4 del backend) dos videos, `validacion-4-1-a` y `validacion-4-1-b`
(`ref_cliente` y `nombre` iguales), cada uno con 3 JPEG sintéticos de 640 × 480 generados con Pillow: `POST
/v1/collect/videos`, `POST …/images`, `PUT` a cada URL prefirmada con los encabezados recibidos (sin imprimirlas) y
`POST …/complete`. Al terminar, también si algo falló, borra con `DELETE /v1/admin/videos/{id}` todos los videos de
`GET /v1/admin/videos?q=validacion-4-1` (incluido el renombrado; la purga limpia S3 y sus vectores salen de la
búsqueda al instante). Al empezar, hace lo mismo con los restos de una ejecución anterior. Cierra con
`am force-stop` (sin sesión, 5.3); no usa `pm clear`.

## 5. Cómo ejecutarlo

```bash
cd FRONTEND_KOTLIN/project
uv run --group ops python src/ops/validate41.py --entorno dev
```

Variables: `VALIDACION_API_URL`, `VALIDACION_ADMIN_CORREO`, `VALIDACION_ADMIN_PASSWORD` (`ARCHITECTURE.md` §5.11)
y `ANDROID_SERIAL` si hay varios dispositivos. Duración aproximada: 10 minutos, incluidos el paso guiado y C2.
