# Validación 3-2 — BE-3.2 Localización

| Campo | Valor |
|---|---|
| Lote | `BE-3.2` — criterios en [`PLAN.md`](../PLAN.md) §2.2 |
| Script | `project/src/ops/validate32.py` |
| Entornos | `dev` (necesita el dataset real y el conjunto de `evaluacion/` en S3) |
| Criterios | Automáticos: C1, C2, C3, C4, C5, C6 · Manuales: ninguno |

Contrato común de los validadores: `INFRASTRUCTURA_TERRAFORM/docs/ARCHITECTURE.md` §5.11. Lo propio de esta carpeta:
`ARCHITECTURE.md` §5.11.

## 1. Precondiciones

Si alguna no se cumple, el script termina con código 2 y el lote queda `Bloqueado`.

| ID | Qué debe cumplirse | Cómo lo comprueba el script |
|---|---|---|
| P1 | `AWS_PROFILE` de la cuenta `648617469176` | `aws sts get-caller-identity` → `Account`. Si falla: código 3 (credenciales) |
| P2 | `BE-2.2` y `BE-3.1` en «Hecho» | `PLAN.md` §3 marca ambos «Hecho»; `GET /v1/places` → `200` con `total` ≥ 1 |
| P3 | `EMB-3.1` en «Hecho» y embeddings encendido | `SERVICE_EMBEDDING/docs/PLAN.md` §3 marca EMB-3.1 «Hecho»; `GET /v1/health/ready` → `"embedding": "ok"`; hora `America/Bogota` entre 06:00 y 21:30 |
| P4 | `EMB-3.2` en «Hecho»: conjunto de consulta publicado | `SERVICE_EMBEDDING/docs/PLAN.md` §3 marca EMB-3.2 «Hecho»; `s3api list-objects-v2 --bucket campus-locator-dev-dataset-648617469176 --prefix evaluacion/ --delimiter /` → toma la última `<version_conjunto>` (orden lexicográfico); `s3api get-object` de su `puntos.json` con ≥ 10 puntos cuyas fotos existen |
| P5 | Dataset real del campus (`FE-2.1` en «Hecho») | `FRONTEND_KOTLIN/docs/PLAN.md` §3 marca FE-2.1 «Hecho»; SQL `SELECT count(*) FROM embeddings e JOIN imagenes i ON i.id = e.imagen_id JOIN videos v ON v.id = i.video_id WHERE i.estado = 'procesada' AND v.estado <> 'eliminado' AND v.nombre NOT LIKE 'validacion-%'` > 0 |
| P6 | ECS Exec disponible en `api` (para C4c) | `ecs describe-services --cluster campus-locator-dev --services api` → `enableExecuteCommand = true` |

## 2. Comprobaciones automáticas

| ID | Qué hace el script | Pasa si |
|---|---|---|
| C1 | SQL `SELECT i.lat, i.lng FROM imagenes i JOIN videos v ON v.id = i.video_id WHERE i.estado = 'procesada' AND v.estado <> 'eliminado'` para saber qué puntos de `puntos.json` tienen dataset (alguna imagen a ≤ 30 m). Por cada uno: reduce sus fotos a lado mayor 1024 px y calidad 85 (§5.3), toma hasta 5 y envía `POST /v1/localize` (`fotos` + `metadatos` = `{"rumbos": [<de puntos.json o null>…], "origen": "escaneo", "app_version": "validacion-32"}`); error = haversine (R = 6 371 008,8 m) entre `posicion` y la coordenada real; `sin_coincidencias` cuenta como error infinito | ≥ 10 puntos evaluados y error mediano ≤ 15 m |
| C2 | Revisa todas las respuestas de C1 y C3 con `nivel = "alta"` | Ninguna con error > 30 m |
| C3 | Comprueba el tamaño de `embedding` (`describe-services` → `describe-task-definition`: `cpu = "1024"`, `memory = "3072"`, `runningCount = 1`) y que `ingesta` tiene 0 mensajes; hace 3 peticiones de calentamiento y luego 100 peticiones secuenciales de 5 fotos recorriendo los puntos de C1, midiendo en el cliente el tiempo de cada una | Las 100 dan `200` y el p95 (valor 95 de las 100 ordenadas) es ≤ 5 000 ms |
| C4a | Calcula el MD5 de cada foto enviada en C1, C3 y C5; `s3api list-objects-v2` de todo el bucket (paginado) | Ningún `ETag` coincide con esos MD5 |
| C4b | `logs filter-log-events` de `/campus-locator/dev/api`, `/campus-locator/dev/apigw` y `/campus-locator/dev/embedding` desde el inicio | Ningún evento contiene `/9j/` (comienzo de un JPEG en base64) ni pesa más de 16 KB |
| C4c | `ecs execute-command --cluster campus-locator-dev --task <tarea de api> --container app --interactive --command "find / -xdev -type f -newermt '<inicio>' -size +50k"` | Salida vacía |
| C5 | Toma los puntos de `puntos.json` a más de 150 m de toda imagen `procesada` (consulta de C1) y envía sus fotos como en C1 | Todas `200` con `resultado = "sin_coincidencias"`, `confianza = 0` y `posicion = null`. Sin puntos así, falla con «conjunto sin puntos fuera de cobertura» |
| C6 | Lee `docs/ARCHITECTURE.md` y `docs/CHANGELOG.md` | En §5.10 las filas de `LOC_SIM_MIN / LOC_SIM_ALTA` y de los cortes de nivel ya no dicen «Iniciales»; la versión del encabezado es mayor que 0.2.0 y una entrada de `CHANGELOG.md` tiene «Lote que la motivó» = BE-3.2 |

SQL = tarea `campus-locator-dev-validacion` con `psql -tAc`, como en [`validation-1-2.md`](./validation-1-2.md) §2. Las
peticiones van de una en una (como una persona que escanea); el detalle de C3 incluye también p50 y la mediana de
`latencia_ms` informada por la API.

## 3. Comprobaciones manuales

Ninguna: todos los criterios son automáticos.

## 4. Datos de prueba y limpieza

No crea datos de prueba en la API ni en el bucket. Cada localización deja una fila anónima en `eventos_localizacion`
(≈ 130 por ejecución, reconocibles por `app_version = "validacion-32"`); no hay endpoint para borrarlas y caducan a
los 180 días (`EVENTOS_RETENCION_DIAS`). El conjunto de `evaluacion/` se descarga en `project/.validacion/` (ignorada
por
Git) y se borra al terminar, también si algo falló. Nunca escribe en `evaluacion/`. No hay restos que limpiar al
empezar.

## 5. Cómo ejecutarlo

```bash
cd BACKEND_FASTAPI/project
uv run --group ops python src/ops/validate32.py --entorno dev
```

Variables: `AWS_PROFILE` (obligatoria; además de lo de §5.11 necesita leer `evaluacion/` y usar ECS Exec) y
`VALIDACION_API_URL` (opcional); ver `ARCHITECTURE.md` §5.11. No usa credenciales de admin. Duración aproximada:
15 minutos.
