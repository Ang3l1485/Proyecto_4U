# Validación 3-2 — EMB-3.2 Conjunto de evaluación y calibración

| Campo | Valor |
|---|---|
| Lote | `EMB-3.2` — criterios en [`PLAN.md`](../PLAN.md) §2.2 |
| Script | `project/src/ops/validate32.py` |
| Entornos | `dev` (**cierra el lote**): el conjunto vive en el bucket de `dev` y el dataset indexado, en el backend de `dev`. `local` no aplica: no usa el contenedor |
| Criterios | Automáticos: C1, C2 · Manuales: C3 |

Contrato común de los validadores: `INFRASTRUCTURA_TERRAFORM/docs/ARCHITECTURE.md` §5.11. Lo propio de esta carpeta:
`ARCHITECTURE.md` §5.8.

## 1. Precondiciones

Si alguna no se cumple, el script termina con código 2 y el lote queda `Bloqueado`.

| ID | Qué debe cumplirse | Cómo lo comprueba el script |
|---|---|---|
| P1 | `EMB-2.1` en «Hecho»: vectores `dinov2-vitb14/pp-v1` estables (§5.3, §5.4) | Fila EMB-2.1 de `docs/PLAN.md` §3 en `Hecho` |
| P2 | `BE-2.2` y `FE-2.1` en «Hecho»: un dataset **real** del campus indexado con la misma `version_vector` | Con `VALIDACION_API_URL` y `VALIDACION_ADMIN_*` (backend §5.11): `POST /v1/auth/login`; `GET /v1/admin/videos` → al menos un video `procesado` cuyo nombre no empieza por `validacion-`; `GET /v1/admin/images?estado=procesada&por_pagina=1` y `GET /v1/admin/images/{id}` → `vector.version_vector = dinov2-vitb14/pp-v1` |
| P2b | `BE-2.4` en «Hecho»: el endpoint de vecinos responde | `POST /v1/admin/diagnostico/vecinos?k=5` con la primera imagen de `project/tests/golden/` → `200` con `version_vector = dinov2-vitb14/pp-v1` y `vecinos` no vacío (backend §5.5) |
| P3 | Conjunto de fotos de consulta subido a `evaluacion/` (infra §5.5) | `s3api list-objects-v2 --bucket campus-locator-dev-dataset-648617469176 --prefix evaluacion/ --delimiter /` → al menos un `evaluacion/<version_conjunto>/`; `s3api head-object` de su `puntos.json` |
| P4 | `AWS_PROFILE` de la cuenta `648617469176` con lectura de `evaluacion/` | `sts get-caller-identity` → `Account`. Sin variable, con credenciales inválidas o sin permiso de lectura: código 3 (§5.11) |

## 2. Comprobaciones automáticas

| ID | Qué hace el script | Pasa si |
|---|---|---|
| C1 | Para el `<version_conjunto>` que cita el informe de C2: `s3api get-object` de `evaluacion/<version_conjunto>/puntos.json` (formato de §5.9) y `s3api list-objects-v2` de `evaluacion/<version_conjunto>/fotos/`; con `GET /v1/admin/images?estado=procesada` (todas las páginas) calcula la distancia de cada punto a la imagen del dataset más cercana | ≥ 50 entradas en `fotos` repartidas en ≥ 10 puntos a ≤ 30 m del dataset, y ≥ 1 punto con ≥ 3 fotos a > 150 m de toda imagen; cada `archivo` existe en el bucket y cada `punto` está en `puntos`; cada punto tiene una coordenada WGS84 válida (convenciones de backend §5.1) |
| C2 | Toma el informe más reciente de `evaluacion/*/informes/dinov2-vitb14_pp-v1-<AAAAMMDD>.json` que genera `project/tools/evaluacion/` (formato de §5.9) | Cita `<version_conjunto>` y `version_vector = dinov2-vitb14/pp-v1`; `recall_1_15m` y `recall_5_15m` en [0, 1], con el primero ≤ el segundo; `fotos` igual al número de fotos de puntos con dataset que cuenta C1; `similitud.mismo_lugar` y `similitud.otro_lugar` con p10 ≤ p50 ≤ p90; `recomendado` con los cuatro valores presentes |

## 3. Comprobaciones manuales

| ID | Qué hace la persona | Evidencia en el PR |
|---|---|---|
| C3 | Revisa en el informe los valores recomendados de `LOC_SIM_MIN` y `LOC_SIM_ALTA` (0 < `LOC_SIM_MIN` < `LOC_SIM_ALTA` ≤ 1; hoy 0,55 / 0,80) y de los cortes de nivel (0 < `media` < `alta` < 1; hoy `alta` ≥ 0,70 y `media` ≥ 0,45), todos de backend §5.10, y los entrega a quien lleva BE-3.2, que los registra en esa sección | Enlace al informe y a la entrega a BE-3.2 (*issue* o PR del backend) con los valores recomendados |

## 4. Datos de prueba y limpieza

Solo lee: no crea datos (el servicio no guarda nada, §5.8) ni lanza tareas sueltas, así que no hay restos que limpiar
entre ejecuciones. Nunca escribe en `evaluacion/` (lo escriben personas del equipo, infra §5.5) y lee `puntos.json` en
memoria. No imprime el token ni las URL prefirmadas (`url`, `url_miniatura`) que devuelve `GET /v1/admin/images/{id}`.

## 5. Cómo ejecutarlo

```bash
cd SERVICE_EMBEDDING/project
uv run --group ops python src/ops/validate32.py --entorno dev
```

Variables: `AWS_PROFILE` (§5.8); `VALIDACION_API_URL`, `VALIDACION_ADMIN_CORREO` y `VALIDACION_ADMIN_PASSWORD`, tal como
las define `BACKEND_FASTAPI/docs/ARCHITECTURE.md` §5.11 (también listadas en §5.8). Duración aproximada:
1–2 min.
