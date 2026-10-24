# Validación 1-1 — FE-1.1 Cliente HTTP, conexión real y CI

| Campo | Valor |
|---|---|
| Lote | `FE-1.1` — criterios en [`PLAN.md`](../PLAN.md) §2.2 |
| Script | `project/src/ops/validate11.py` |
| Entornos | `dev` con dispositivo físico |
| Criterios | Automáticos: C2, C3, C4 · Manuales: C1 |

Contrato común de los validadores: `INFRASTRUCTURA_TERRAFORM/docs/ARCHITECTURE.md` §5.11. Lo propio de esta carpeta:
`ARCHITECTURE.md` §5.11.

## 1. Precondiciones

Si alguna no se cumple, el script termina con código 2 y el lote queda `Bloqueado`.

| ID | Qué debe cumplirse | Cómo lo comprueba el script |
|---|---|---|
| P1 | `INF-1.4` en «Hecho»: el borde HTTPS de API Gateway responde | `VALIDACION_API_URL` empieza por `https://` y termina en `/v1` (sin la variable: código 3); `GET {VALIDACION_API_URL}/health` no da error de DNS, TLS ni conexión |
| P2 | `BE-1.1` en «Hecho»: salud del backend desplegada | `GET {VALIDACION_API_URL}/health` responde 200 con `"estado": "ok"` |
| P3 | Dispositivo físico conectado | `adb devices` muestra uno en estado `device` (el de `ANDROID_SERIAL` si hay varios) y `adb shell getprop ro.kernel.qemu` no devuelve `1` |
| P4 | Gradle y la CLI de GitHub listos | `./gradlew --version` y `gh auth status` terminan con 0 |

## 2. Comprobaciones automáticas

| ID | Qué hace el script | Pasa si |
|---|---|---|
| C2 | `./gradlew testDebugUnitTest --tests '*.MapeoErroresApiTest' --tests '*.MapeoDatosApiTest'` | Sale con 0, cada clase ejecutó ≥ 1 caso y no hay fallos (la revisión del PR confirma que cubren las dos tablas de §5.10) |
| C3 | Comprueba que existe `.github/workflows/frontend.yml` en la raíz del monorepo y consulta `gh run list --workflow frontend.yml --event pull_request --branch <rama actual> --limit 1 --json conclusion,headSha` (el workflow solo corre si el PR toca `FRONTEND_KOTLIN/project/**`) | La última ejecución es del commit actual (`headSha` = `git rev-parse HEAD`) y su `conclusion` es `success` |
| C4 | Extrae la URL base de `ApiConfig.kt` y la compara con el output vigente (`terraform -chdir=../../INFRASTRUCTURA_TERRAFORM/project/envs/dev output -raw api_base_url` + `/v1`, infra §5.2; sin acceso a Terraform, con `VALIDACION_API_URL`); luego llama a `GET <URL de ApiConfig.kt>/health` | Las dos URL coinciden (sin barra final), terminan en `/v1` y la llamada responde 200 |

## 3. Comprobaciones manuales

| ID | Qué hace la persona | Evidencia en el PR |
|---|---|---|
| C1 | Con el APK que instaló el script, abre la app en Inicio con Wi-Fi o datos y espera 20 s (el sondeo es cada 15 s; 5.5, «Inicio»). Activa el modo avión y espera 20 s; desactívalo y espera otros 20 s | Video corto o tres capturas de la barra inferior de Inicio: «Conectado», «Sin conexión» con el modo avión visible y de nuevo «Conectado» |

## 4. Datos de prueba y limpieza

No crea nada en el backend: solo hace `GET /v1/health`. En el dispositivo instala el APK de depuración con
`./gradlew installDebug` antes de las comprobaciones (conserva los datos de la app) y no usa `pm clear`. No deja
restos, así que no hay nada que limpiar de ejecuciones anteriores.

## 5. Cómo ejecutarlo

```bash
cd FRONTEND_KOTLIN/project
uv run --group ops python src/ops/validate11.py --entorno dev
```

Variables: `VALIDACION_API_URL` (`ARCHITECTURE.md` §5.11), `AWS_PROFILE` para leer el output de Terraform en C4,
`ANDROID_SERIAL` si hay varios dispositivos y `gh` autenticado con acceso al repositorio. Duración aproximada: 5
minutos, más 2 de la comprobación manual.
