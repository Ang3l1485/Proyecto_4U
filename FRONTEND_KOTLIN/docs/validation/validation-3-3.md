# Validación 3-3 — FE-3.3 Alertas de administración sincronizadas (7.8–7.10)

| Campo | Valor |
|---|---|
| Lote | `FE-3.3` — criterios en [`PLAN.md`](../PLAN.md) §2.2 |
| Script | `project/src/ops/validate33.py` |
| Entornos | `dev` con dispositivo físico |
| Criterios | Automáticos: C1, C2 · Manuales: C3 |

Contrato común de los validadores: `INFRASTRUCTURA_TERRAFORM/docs/ARCHITECTURE.md` §5.11. Lo propio de esta carpeta:
`ARCHITECTURE.md` §5.11.

## 1. Precondiciones

Si alguna no se cumple, el script termina con código 2 y el lote queda `Bloqueado`.

| ID | Qué debe cumplirse | Cómo lo comprueba el script |
|---|---|---|
| P1 | `FE-1.2` en «Hecho»: login de admin contra `dev` | Fila de `FE-1.2` en `PLAN.md` §3 = `Hecho`; `POST /v1/auth/login` con las credenciales de admin responde 200 (con `401`: código 3) |
| P2 | `BE-3.1` en «Hecho»: administración de alertas | Fila en `BACKEND_FASTAPI/docs/PLAN.md` §3 = `Hecho`; `GET /v1/admin/alerts` con token responde 200 y `POST /v1/admin/alerts/sincronizar` con `{"cambios": []}` responde 200 |
| P3 | Dispositivo físico y Gradle | `adb devices` con uno en estado `device` (el de `ANDROID_SERIAL` si hay varios), `ro.kernel.qemu` distinto de `1` y `./gradlew --version` con salida 0 |

## 2. Comprobaciones automáticas

Instala el APK con `./gradlew installDebug` y anota cuántas líneas tiene `files/logs/app.log` (`adb exec-out run-as
com.example.myapplication cat files/logs/app.log`). Los pasos guiados se hacen con la sesión de
`VALIDACION_ADMIN_CORREO`; el script espera Enter tras cada uno.

| ID | Qué hace el script | Pasa si |
|---|---|---|
| C1 | **Paso guiado:** pide iniciar una recolección (7.4, modo «cada 3 s», basta estar quieto), «Agregar alerta aquí» con mensaje `validacion-3-3-c1`, finalizar, abrir «Mapa y alertas» (7.8), ver el marcador y pulsar «Guardar / Sincronizar». Luego consulta `GET /v1/admin/alerts?q=validacion-3-3-c1` | Hay exactamente 1 alerta, activa, a ≤ 30 m de la primera foto del video (`files/recoleccion/rec_NNNN/manifest.json` más reciente) |
| C2 | **Paso guiado:** pide crear en 7.8 una alerta `validacion-3-3-c2`, eliminarla antes de sincronizar y pulsar «Guardar / Sincronizar». Luego consulta `GET /v1/admin/alerts?q=validacion-3-3-c2` y relee `app.log` | No hay ninguna alerta con ese mensaje y las líneas nuevas de `app.log` no tienen nivel `E` ni tag `CRASH` |

## 3. Comprobaciones manuales

Antes de limpiar, el script crea con la API la alerta `validacion-3-3-c3` y espera Enter para que la persona haga C3.

| ID | Qué hace la persona | Evidencia en el PR |
|---|---|---|
| C3 | En 7.8 toca «Ver lista» y, en la Lista de alertas (7.10), busca «validacion-3-3»; abre `validacion-3-3-c3` para editarla y cierra sin guardar | Capturas de 7.10 con `validacion-3-3-c1` y `validacion-3-3-c3` (creada solo en el backend) y del formulario 7.9 abierto con el mensaje de `validacion-3-3-c3` |

## 4. Datos de prueba y limpieza

La persona crea `validacion-3-3-c1` y `validacion-3-3-c2` desde la app; el script crea `validacion-3-3-c3` con
`PUT /v1/admin/alerts/{uuid}`. Al terminar, también si algo falló, borra con `DELETE /v1/admin/alerts/{id}` todas las
alertas de `GET /v1/admin/alerts?q=validacion-3-3`; al empezar, hace lo mismo con los restos de una ejecución
anterior. El video local de C1 lo descarta la persona en 7.5 («Descartar video»); el script no usa `pm clear`.

## 5. Cómo ejecutarlo

```bash
cd FRONTEND_KOTLIN/project
uv run --group ops python src/ops/validate33.py --entorno dev
```

Variables: `VALIDACION_API_URL`, `VALIDACION_ADMIN_CORREO`, `VALIDACION_ADMIN_PASSWORD` (`ARCHITECTURE.md` §5.11)
y `ANDROID_SERIAL` si hay varios dispositivos. Duración aproximada: 12 minutos, incluidos los pasos guiados y C3.
