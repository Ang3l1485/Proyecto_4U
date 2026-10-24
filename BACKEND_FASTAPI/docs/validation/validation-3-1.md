# Validación 3-1 — BE-3.1 Lugares y alertas

| Campo | Valor |
|---|---|
| Lote | `BE-3.1` — criterios en [`PLAN.md`](../PLAN.md) §2.2 |
| Script | `project/src/ops/validate31.py` |
| Entornos | `dev`, `local` (ningún criterio depende de S3 ni SQS) |
| Criterios | Automáticos: C1, C2, C3, C4, C5 · Manuales: ninguno |

Contrato común de los validadores: `INFRASTRUCTURA_TERRAFORM/docs/ARCHITECTURE.md` §5.11. Lo propio de esta carpeta:
`ARCHITECTURE.md` §5.11.

## 1. Precondiciones

Si alguna no se cumple, el script termina con código 2 y el lote queda `Bloqueado`.

| ID | Qué debe cumplirse | Cómo lo comprueba el script |
|---|---|---|
| P1 | Solo `dev`: `AWS_PROFILE` de la cuenta `648617469176` (para leer el secreto del admin y el output `api_base_url`) | `aws sts get-caller-identity` → `Account`. Si falla: código 3 (credenciales) |
| P2 | URL de la API | `VALIDACION_API_URL` o, en `dev`, el output `api_base_url` + `/v1`; `GET /v1/health` → `200` |
| P3 | `BE-1.3` en «Hecho»: login de admin | `POST /v1/auth/login` con `VALIDACION_ADMIN_*` (en `dev`, o el secreto `campus-locator/dev/admin-inicial`) → `200` con `usuario.rol = "admin"` |

## 2. Comprobaciones automáticas

| ID | Qué hace el script | Pasa si |
|---|---|---|
| C1a | Toma `GET /v1/alerts` sin `desde` como caché inicial y guarda `generado_en`; crea con `PUT /v1/admin/alerts/{uuid}` la alerta `{"lat": 0.001, "lng": 0.001, "mensaje": "validacion-31-<ts> creada", "tipo": "obra", "radio_m": 15}`; pide `GET /v1/alerts?desde=<generado_en>` y la aplica | Caché inicial con `completo = true`; `PUT` `201` con `version = 1`; la diferencia trae `completo = false` y la alerta |
| C1b | `PUT` del mismo id con `mensaje` `validacion-31-<ts> editada`, `radio_m: 20` e `If-Match: 1`; aplica la diferencia siguiente | `200` con `version = 2`; la diferencia trae la versión 2 |
| C1c | `DELETE /v1/admin/alerts/{id}`; aplica la diferencia siguiente | `204`; la diferencia trae el id en `eliminadas` |
| C1d | Aplica cada diferencia como la app (reemplaza por `id`, quita `eliminadas` y descarta `activa = false`; no filtra por vigencia, porque la foto completa incluye vigencias futuras) y compara con un `GET /v1/alerts` final sin `desde` | El mapa `id → version` de la caché es igual al de la foto completa |
| C2 | `DELETE /v1/admin/alerts/{uuid4 nuevo}` | `204` |
| C3a | `POST /v1/admin/places` con `{"nombre": "validacion-31-<ts> Cafe Norte", "categoria": "cafeteria", "lat": 0.001, "lng": 0.001}`; luego otro con `nombre` `VALIDACION-31-<ts> CAFE NORTE` | `201` y después `409 NOMBRE_DUPLICADO` |
| C3b | Mismo `POST` con `nombre` `validacion-31-<ts> Café Norte` | `409 NOMBRE_DUPLICADO` |
| C4 | `PUT` de la alerta `validacion-31-<ts> futura` con `activa: true`, `vigencia_desde` = ahora + 2 días y `vigencia_hasta` = ahora + 3 días; `GET /v1/alerts` sin `desde` | La alerta está en `alertas` con sus dos fechas |
| C5 | Crea con `PUT` la alerta D; `POST /v1/admin/alerts/sincronizar` con `{"cambios": [{"op": "upsert", "alerta": {A válida}}, {"op": "upsert", "alerta": {B con "radio_m": 500}}, {"op": "eliminar", "id": "<D>"}]}`; después `GET /v1/admin/alerts` | `200`; por `id`: A `ok`, B `error` con `codigo = "VALIDACION"`, D `ok`; en el listado está A y no están B ni D |

Entre cada cambio y la diferencia que lo recoge espera 1 s (`generado_en` y `desde` tienen resolución de segundos).
Todas las alertas de prueba (A, B, D incluidas) llevan `mensaje` que empieza por `validacion-31-<ts>`.

## 3. Comprobaciones manuales

Ninguna: todos los criterios son automáticos.

## 4. Datos de prueba y limpieza

Crea alertas con `mensaje` `validacion-31-<ts>…` y un lugar `validacion-31-<ts> Cafe Norte`, en la coordenada
`(0.001, 0.001)`, fuera del campus, para que ninguna app de `dev` los anuncie ni los proponga como destino cercano.

Limpieza: `DELETE /v1/admin/alerts/{id}` de cada alerta de `GET /v1/admin/alerts` cuyo `mensaje` empiece por
`validacion-`, y `DELETE /v1/admin/places/{id}` de cada lugar de `GET /v1/admin/places` cuyo nombre, en minúsculas y sin
tildes, empiece por `validacion-`. El mismo barrido se hace al empezar, por si una ejecución anterior dejó restos. Las
alertas borradas dejan su *tombstone* 90 días (`ALERTAS_TOMBSTONE_DIAS`); no tiene contenido y no se puede quitar antes.

## 5. Cómo ejecutarlo

```bash
cd BACKEND_FASTAPI/project
uv run --group ops python src/ops/validate31.py --entorno dev
uv run --group ops python src/ops/validate31.py --entorno local   # con docker compose up en marcha
```

Variables: `AWS_PROFILE` (obligatoria en `dev`), `VALIDACION_API_URL`, `VALIDACION_ADMIN_CORREO` y
`VALIDACION_ADMIN_PASSWORD` (opcionales en `dev`, obligatorias en `local`); ver `ARCHITECTURE.md` §5.11. Duración
aproximada: 2 minutos.
