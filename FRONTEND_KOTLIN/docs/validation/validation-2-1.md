# Validación 2-1 — FE-2.1 Subida de recorridos y Resumen de video (7.5)

| Campo | Valor |
|---|---|
| Lote | `FE-2.1` — criterios en [`PLAN.md`](../PLAN.md) §2.2 |
| Script | `project/src/ops/validate21.py` |
| Entornos | `dev` con dispositivo físico |
| Criterios | Automáticos: C1, C3, C4 · Manuales: C2 |

Contrato común de los validadores: `INFRASTRUCTURA_TERRAFORM/docs/ARCHITECTURE.md` §5.11. Lo propio de esta carpeta:
`ARCHITECTURE.md` §5.11.

## 1. Precondiciones

Si alguna no se cumple, el script termina con código 2 y el lote queda `Bloqueado`.

| ID | Qué debe cumplirse | Cómo lo comprueba el script |
|---|---|---|
| P1 | `FE-1.2` en «Hecho»: la app inicia sesión contra `dev` | Fila de `FE-1.2` en `PLAN.md` §3 = `Hecho`; `POST /v1/auth/login` con las credenciales de admin responde 200 (con `401`: código 3) |
| P2 | `FE-2.3` en «Hecho»: el PDR que etiqueta las fotos está probado en dispositivo | Fila de `FE-2.3` en `PLAN.md` §3 = `Hecho` con «Última validación» no vacía |
| P3 | `BE-2.1` en «Hecho»: endpoints de recolección | Fila en `BACKEND_FASTAPI/docs/PLAN.md` §3 = `Hecho`; `POST /v1/collect/videos` con token y cuerpo `{}` responde `422 VALIDACION` (existe y no crea nada) |
| P4 | `BE-2.2` en «Hecho» y `embedding` encendido: las fotos pasan a `procesada` | Fila en `BACKEND_FASTAPI/docs/PLAN.md` §3 = `Hecho`; `GET /v1/health/ready` responde `"db": "ok"` y `"embedding": "ok"` (fuera de 06:00–22:00 `America/Bogota` falla) |
| P5 | El recorrido indicado con `--video` existe en el backend (BE-2.1 entrega `GET /v1/admin/videos`) | `GET /v1/admin/videos?q=<nombre>` con token devuelve exactamente un video con ese nombre; sin `--video`: código 3 |

## 2. Comprobaciones automáticas

Antes de ejecutar el script, la persona hace la preparación de §4 (recorrido real y subida con corte de red).

| ID | Qué hace el script | Pasa si |
|---|---|---|
| C1 | Toma el video de P5 y lee `GET /v1/admin/videos/{id}`; espera hasta 15 min, consultando cada 30 s, a que termine la ingesta | `estado = "procesado"`, `total_fotos` ≥ 50 y `conteo.procesada = total_fotos` |
| C3 | Por cada foto de `GET /v1/admin/videos/{id}` descarga `url` (sin imprimirla) y mide el JPEG con Pillow | Todas tienen ≤ 4 194 304 bytes y lado mayor ≤ 1600 px |
| C4 | Busca en `MainActivity.kt` (`AppNav`) el destino de la ruta `admin/recoleccion/resumen` | La ruta compone `ResumenVideoScreen` y no queda el *placeholder* en blanco de §5.8 |

## 3. Comprobaciones manuales

| ID | Qué hace la persona | Evidencia en el PR |
|---|---|---|
| C2 | Durante la subida de la preparación (paso 2 de §4), con el progreso por foto entre 20 % y 60 %, activa el modo avión, cierra la app desde Recientes, espera 10 s, quita el modo avión y vuelve a abrir la app (si pide login, entra) | Video de 7.5 antes del corte y tras reabrir hasta terminar la subida; captura de 7.13 o 7.14 con el mismo número de fotos que muestra 7.5 (sin duplicadas); el informe del script con C1 en `pasa` |

## 4. Datos de prueba y limpieza

**Preparación (persona, antes de ejecutar)**, con la sesión de `VALIDACION_ADMIN_CORREO`:
1. Calibra el paso si hace falta (7.3b) y graba en el campus un recorrido **real** de 60 a 80 fotos (por defecto, una
   cada 5 m) en una zona que todavía no tenga dataset, con un nombre descriptivo (p. ej. «Entrada norte»); al terminar,
   «Finalizar» abre 7.5 (lo confirma C4).
2. En 7.5 toca «Subir y procesar» y haz el corte de red de C2.

**Limpieza:** ninguna. El recorrido es parte del dataset real (lo usan EMB-3.2 y BE-3.2) y se queda; el script solo
lee (contrato común, infra §5.11). Si la validación falla por algo del recorrido (por ejemplo, menos de 50 fotos), la
persona decide si lo conserva o lo borra desde la app cuando exista FE-4.1. La copia local
(`files/recoleccion/rec_NNNN/`) queda con `subida_estado = completada` (§5.10); el script no usa `pm clear`.

## 5. Cómo ejecutarlo

```bash
cd FRONTEND_KOTLIN/project
uv run --group ops python src/ops/validate21.py --entorno dev --video "Entrada norte"
```

Argumento propio: `--video <nombre del recorrido>` (obligatorio). Variables: `VALIDACION_API_URL`,
`VALIDACION_ADMIN_CORREO`, `VALIDACION_ADMIN_PASSWORD` (`ARCHITECTURE.md` §5.11;
en `dev`, si faltan las credenciales, se leen del secreto `campus-locator/dev/admin-inicial` con `AWS_PROFILE`). El
script solo usa la API y el código: no necesita el teléfono conectado. Duración aproximada: 20 minutos de script (la
ingesta domina), más 30 a 45 de preparación caminando.
