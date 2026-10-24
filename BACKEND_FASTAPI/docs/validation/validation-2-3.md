# Validación 2-3 — BE-2.3 Resumen del panel

| Campo | Valor |
|---|---|
| Lote | `BE-2.3` — criterios en [`PLAN.md`](../PLAN.md) §2.2 |
| Script | `project/src/ops/validate23.py` |
| Entornos | `dev` (las fotos `procesada` necesitan S3 y SQS, que no se emulan en `local`) |
| Criterios | Automáticos: C1 · Manuales: ninguno |

Contrato común de los validadores: `INFRASTRUCTURA_TERRAFORM/docs/ARCHITECTURE.md` §5.11. Lo propio de esta carpeta:
`ARCHITECTURE.md` §5.11.

## 1. Precondiciones

Si alguna no se cumple, el script termina con código 2 y el lote queda `Bloqueado`.

| ID | Qué debe cumplirse | Cómo lo comprueba el script |
|---|---|---|
| P1 | `AWS_PROFILE` de la cuenta `648617469176` | `aws sts get-caller-identity` → `Account`. Si falla: código 3 (credenciales) |
| P2 | `BE-2.1` en «Hecho»: login y recolección desplegados | `POST /v1/auth/login` (admin, ver §5) → `200`; `POST /v1/collect/videos/<uuid nuevo>/images` con un elemento válido → `404 NO_ENCONTRADO` |
| P3 | `BE-2.2` en «Hecho» y dentro del horario: sin `worker` ninguna foto llega a `procesada` | `PLAN.md` §3 marca BE-2.2 «Hecho»; `GET /v1/health/ready` → `"embedding": "ok"`; hora `America/Bogota` entre 06:00 y 21:45 |
| P4 | `BE-3.1` en «Hecho»: endpoints de lugares y alertas | `PLAN.md` §3 marca BE-3.1 «Hecho»; `GET /v1/admin/places` y `GET /v1/admin/alerts` → `200` |

## 2. Comprobaciones automáticas

| ID | Qué hace el script | Pasa si |
|---|---|---|
| C1a | Lee `GET /v1/admin/stats` (s0); crea el video `validacion-23-<ts>` con 2 JPEG sintéticos (flujo de BE-2.1) y espera a que ambas fotos estén `procesada` en `GET /v1/admin/videos/{id}` (máx. 10 min); tras C1b y C1c lee otra vez (s1) | `s1.total_fotos − s0.total_fotos = 2` |
| C1b | Entre s0 y s1, `POST /v1/admin/places` de `validacion-23-<ts>-a` y `validacion-23-<ts>-b` (`categoria: "bloque"`, coordenadas fuera del campus) | `201` en ambos y `total_lugares` sube en 2 |
| C1c | Entre s0 y s1, `PUT /v1/admin/alerts/{uuid}` de una alerta `activa: true` sin vigencia y de otra `activa: false` (mensajes `validacion-23-<ts>-…`) | `201` en ambas y `alertas_activas` sube en 1 |
| C1d | Compara `ultimo_video` de s1 con el `VideoResumen` del video creado | Mismo `numero` y mismo `creado_en` |

Los totales son globales: el script compara diferencias y supone que nadie más crea ni borra videos, fotos, lugares o
alertas en `dev` durante los minutos que dura. Si una diferencia no cuadra, el detalle muestra s0 y s1 para descartar
actividad ajena antes de repetir.

## 3. Comprobaciones manuales

Ninguna: todos los criterios son automáticos.

## 4. Datos de prueba y limpieza

Crea un video `validacion-23-<AAAAMMDD-HHMMSS>` (`ref_cliente` y `nombre`) con 2 fotos, 2 lugares `validacion-23-<ts>-a`
y `-b`, y 2 alertas con mensaje `validacion-23-<ts>-…`, todo con coordenadas fuera del campus.

Limpieza: `DELETE /v1/admin/alerts/{id}` y `DELETE /v1/admin/places/{id}` de lo creado; el video, como dice backend
`ARCHITECTURE.md` §5.11 (`limpiar-validacion --video <id>`, o `DELETE` si BE-4.1 está «Hecho»). Al empezar borra los
lugares
cuyo nombre empiece por `validacion-` (sin distinguir mayúsculas ni tildes) y las alertas cuyo `mensaje` empiece por
`validacion-` que hayan quedado (listados de `GET /v1/admin/places` y `GET /v1/admin/alerts`), y los videos
`validacion-` con `limpiar-validacion` (o `DELETE` si BE-4.1 está «Hecho»). Las alertas borradas dejan su *tombstone* 90
días (`ALERTAS_TOMBSTONE_DIAS`).

## 5. Cómo ejecutarlo

```bash
cd BACKEND_FASTAPI/project
uv run --group ops python src/ops/validate23.py --entorno dev
```

Variables: `AWS_PROFILE` (obligatoria), `VALIDACION_API_URL`, `VALIDACION_ADMIN_CORREO` y `VALIDACION_ADMIN_PASSWORD`
(opcionales; ver `ARCHITECTURE.md` §5.11). Duración aproximada: 8 minutos.
