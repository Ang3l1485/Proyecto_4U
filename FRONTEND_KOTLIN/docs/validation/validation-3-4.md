# Validación 3-4 — FE-3.4 Lugares de administración (7.6, 7.7)

| Campo | Valor |
|---|---|
| Lote | `FE-3.4` — criterios en [`PLAN.md`](../PLAN.md) §2.2 |
| Script | `project/src/ops/validate34.py` |
| Entornos | `dev` con dispositivo físico |
| Criterios | Automáticos: C1a, C1b, C2 · Manuales: C3 |

Contrato común de los validadores: `INFRASTRUCTURA_TERRAFORM/docs/ARCHITECTURE.md` §5.11. Lo propio de esta carpeta:
`ARCHITECTURE.md` §5.11.

## 1. Precondiciones

Si alguna no se cumple, el script termina con código 2 y el lote queda `Bloqueado`.

| ID | Qué debe cumplirse | Cómo lo comprueba el script |
|---|---|---|
| P1 | `FE-1.2` en «Hecho»: login de admin contra `dev` | Fila de `FE-1.2` en `PLAN.md` §3 = `Hecho`; `POST /v1/auth/login` con las credenciales de admin responde 200 (con `401`: código 3) |
| P2 | `BE-3.1` en «Hecho»: CRUD de lugares | Fila en `BACKEND_FASTAPI/docs/PLAN.md` §3 = `Hecho`; `GET /v1/admin/places` con token y `GET /v1/places` responden 200 |
| P4 | Dispositivo físico y Gradle | `adb devices` con uno en estado `device` (el de `ANDROID_SERIAL` si hay varios), `ro.kernel.qemu` distinto de `1` y `./gradlew --version` con salida 0 |

## 2. Comprobaciones automáticas

Instala el APK con `./gradlew installDebug`. Los pasos guiados se hacen con la sesión de `VALIDACION_ADMIN_CORREO`;
el script espera Enter tras cada uno.

| ID | Qué hace el script | Pasa si |
|---|---|---|
| C1a | **Paso guiado:** pide crear en 7.6 → «Nuevo lugar» (7.7) el lugar `validacion-3-4-lugar`, categoría Bloque, alias `validacion`, con una coordenada elegida en el mapa de 7.7 a más de 60 m de otros lugares, y guardar; el script lee la coordenada que muestra el formulario (`uiautomator dump`). Luego consulta `GET /v1/places` y `GET /v1/places?lat=<lat>&lng=<lng>` | El lugar aparece una vez con `categoria = "bloque"` y, con su propia coordenada, `distancia_m` < 1 |
| C1b | **Paso guiado:** pide abrir Selección de destino (por voz «dos» o con la acción de TalkBack «Ir a un lugar»); escribe `validacion-3-4` en el buscador (`adb shell input text`) y lee la lista con `uiautomator dump` | Hay una fila (`FilaLugar`) con «validacion-3-4-lugar, Bloque» |
| C2 | `GET /v1/places?lat=<lat>&lng=<lng>` con la coordenada que mostró el formulario en C1a | El primer elemento es `validacion-3-4-lugar` y su `distancia_m` es < 1 |

## 3. Comprobaciones manuales

Antes de limpiar, el script crea con la API el lugar `validacion-3-4-dup` y espera Enter para que la persona haga C3.

| ID | Qué hace la persona | Evidencia en el PR |
|---|---|---|
| C3 | En 7.7 crea un lugar nuevo con nombre `VALIDACIÓN-3-4-DUP` (mayúsculas y tilde), cualquier coordenada, y pulsa Guardar | Captura del formulario con el mensaje del campo nombre (`409 NOMBRE_DUPLICADO`, `detalle.campos`) y sin volver a 7.6 |

## 4. Datos de prueba y limpieza

La persona crea `validacion-3-4-lugar` desde la app y el script crea `validacion-3-4-dup` con `POST /v1/admin/places`.
Al terminar, también si algo falló, borra con `DELETE /v1/admin/places/{id}` todo lo de
`GET /v1/admin/places?q=validacion-3-4` (sus imágenes, si las hubiera, quedan sin lugar); al empezar, hace lo mismo
con los restos de una ejecución anterior. En el teléfono no borra nada; no usa `pm clear`.

## 5. Cómo ejecutarlo

```bash
cd FRONTEND_KOTLIN/project
uv run --group ops python src/ops/validate34.py --entorno dev
```

Variables: `VALIDACION_API_URL`, `VALIDACION_ADMIN_CORREO`, `VALIDACION_ADMIN_PASSWORD` (`ARCHITECTURE.md` §5.11)
y `ANDROID_SERIAL` si hay varios dispositivos. Duración aproximada: 10 minutos.
