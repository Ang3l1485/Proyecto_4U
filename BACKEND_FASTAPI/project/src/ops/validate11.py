"""BE-1.1 — Base del servicio. Comprueba lo desplegado en `dev`: `/v1/health`, formato de error, logs y despliegue.

Documento: BACKEND_FASTAPI/docs/validation/validation-1-1.md · criterios: BACKEND_FASTAPI/docs/PLAN.md §2.2.

    cd BACKEND_FASTAPI/project
    uv run --group ops python src/ops/validate11.py --entorno dev

Variables: AWS_PROFILE (obligatoria) y, opcional, VALIDACION_API_URL (URL base con /v1). No crea datos.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from typing import Any

import comun
from comun import ErrorConfiguracion, Falla, PrecondicionNoCumplida, exigir

LOTE = "BE-1.1"
CLUSTER = "campus-locator-dev"
SERVICIO_API = "api"
CONTENEDOR = "app"
REPOSITORIO_ECR = "campus-locator/backend"
HTTP_API = "campus-locator-dev-api"
GRUPO_LOGS_API = "/campus-locator/dev/api"
RUTA_INEXISTENTE = "/validacion-ruta-inexistente"
CARPETA_PROYECTO = "BACKEND_FASTAPI/project"
CAMPOS_LOG = ("ts", "nivel", "proceso", "request_id", "evento")

ESPERA_LOGS_S = 90
INTERVALO_LOGS_S = 10
MARGEN_RELOJ_MS = 60_000  # tolera relojes desajustados al filtrar CloudWatch por `startTime`
TIMEOUT_HTTP_S = 15


@dataclass
class ImagenDesplegada:
    task_definition: str
    imagen: str
    etiqueta: str | None


class Contexto:
    def __init__(self) -> None:
        self.sesion: Any = None
        self.url_api: str | None = None
        self._clientes: dict[str, Any] = {}
        self._imagen: ImagenDesplegada | None = None
        self._peticion: tuple[str, int] | None = None  # (request_id, inicio en ms)
        self._http: Any = None

    # -- clientes --------------------------------------------------------------------------------------------------
    def aws(self, servicio: str) -> Any:
        if servicio not in self._clientes:
            self._clientes[servicio] = self.sesion.client(servicio)
        return self._clientes[servicio]

    def http(self) -> Any:
        if self._http is None:
            import httpx

            self._http = httpx.Client(timeout=TIMEOUT_HTTP_S, follow_redirects=False)
        return self._http

    def cerrar(self) -> None:
        if self._http is not None:
            self._http.close()

    # -- datos compartidos entre comprobaciones -------------------------------------------------------------------
    def servicio_api(self) -> dict[str, Any]:
        respuesta = self.aws("ecs").describe_services(cluster=CLUSTER, services=[SERVICIO_API])
        servicios = respuesta.get("services", [])
        if not servicios:
            raise Falla(f"el servicio `{SERVICIO_API}` no aparece en `{CLUSTER}`")
        return servicios[0]

    def imagen_desplegada(self) -> ImagenDesplegada:
        """`ecs describe-services` → `taskDefinition` → imagen del contenedor `app` (la etiqueta es el SHA)."""
        if self._imagen is None:
            arn = self.servicio_api().get("taskDefinition")
            exigir(arn, f"el servicio `{SERVICIO_API}` no tiene taskDefinition")
            definicion = self.aws("ecs").describe_task_definition(taskDefinition=arn)["taskDefinition"]
            contenedores = {c.get("name"): c for c in definicion.get("containerDefinitions", [])}
            exigir(CONTENEDOR in contenedores, f"la definición {arn} no tiene contenedor `{CONTENEDOR}`")
            imagen = contenedores[CONTENEDOR].get("image", "")
            self._imagen = ImagenDesplegada(arn, imagen, _etiqueta(imagen))
        return self._imagen

    def peticion_inexistente(self) -> tuple[str, int, Any]:
        """Envía `GET /v1/validacion-ruta-inexistente` con un `X-Request-Id` nuevo (una vez por ejecución)."""
        request_id = str(uuid.uuid4())
        inicio_ms = int(time.time() * 1000) - MARGEN_RELOJ_MS
        respuesta = self.http().get(f"{self.url_api}{RUTA_INEXISTENTE}", headers={"X-Request-Id": request_id})
        self._peticion = (request_id, inicio_ms)
        return request_id, inicio_ms, respuesta

    def peticion_registrada(self) -> tuple[str, int]:
        if self._peticion is None:
            request_id, inicio_ms, _ = self.peticion_inexistente()
            return request_id, inicio_ms
        return self._peticion


def _etiqueta(imagen: str) -> str | None:
    """`…/campus-locator/backend:<sha>` → `<sha>`; sin etiqueta (o por digest) → None."""
    if "@" in imagen:
        return None
    ultimo = imagen.rsplit("/", 1)[-1]
    return ultimo.split(":", 1)[1] if ":" in ultimo else None


def _error_aws(exc: Exception, que: str, lote: str) -> Exception:
    """Traduce un error de AWS de una precondición: permisos → 3; recurso ausente → 2 (el lote `lote`)."""
    if comun.es_acceso_denegado(exc):
        return ErrorConfiguracion(f"sin permiso para {que}: {comun.codigo_error_aws(exc)}")
    return PrecondicionNoCumplida(f"{lote}: {que} ({comun.codigo_error_aws(exc) or type(exc).__name__})")


# --- Precondiciones ----------------------------------------------------------------------------------------------
def p1_credenciales(ctx: Contexto) -> str:
    ctx.sesion = comun.sesion_aws()
    arn = comun.verificar_cuenta(ctx.sesion)
    return f"cuenta {comun.CUENTA_AWS} ({arn.rsplit('/', 1)[-1]})"


def p2_inf13(ctx: Contexto) -> str:
    from botocore.exceptions import ClientError

    try:
        respuesta = ctx.aws("ecs").describe_services(cluster=CLUSTER, services=[SERVICIO_API])
    except ClientError as exc:
        raise _error_aws(exc, f"describir el servicio `{SERVICIO_API}` de `{CLUSTER}`", "INF-1.3") from None
    servicios = respuesta.get("services", [])
    if not servicios or servicios[0].get("status") != "ACTIVE":
        motivo = respuesta.get("failures", [{}])[0].get("reason") if respuesta.get("failures") else "no ACTIVE"
        raise PrecondicionNoCumplida(f"INF-1.3: el servicio `{SERVICIO_API}` no está activo ({motivo})")
    try:
        ctx.aws("ecr").describe_repositories(repositoryNames=[REPOSITORIO_ECR])
    except ClientError as exc:
        raise _error_aws(exc, f"encontrar el repositorio ECR `{REPOSITORIO_ECR}`", "INF-1.3") from None
    return f"servicio `{SERVICIO_API}` ACTIVE y repositorio `{REPOSITORIO_ECR}`"


def p3_inf14(ctx: Contexto) -> str:
    from botocore.exceptions import ClientError

    if os.environ.get("VALIDACION_API_URL", "").strip():
        ctx.url_api = comun.url_api()
        origen = "VALIDACION_API_URL"
    else:
        ctx.url_api = comun.url_api(comun.outputs_terraform())
        origen = "output api_base_url"
    try:
        nombres = [
            api.get("Name")
            for pagina in ctx.aws("apigatewayv2").get_paginator("get_apis").paginate()
            for api in pagina.get("Items", [])
        ]
    except ClientError as exc:
        raise _error_aws(exc, "listar las HTTP API", "INF-1.4") from None
    if HTTP_API not in nombres:
        raise PrecondicionNoCumplida(f"INF-1.4: no existe la HTTP API `{HTTP_API}`")
    return f"{ctx.url_api} ({origen}); HTTP API `{HTTP_API}`"


def p4_grupo_logs(ctx: Contexto) -> str:
    from botocore.exceptions import ClientError

    try:
        nombres = [
            grupo.get("logGroupName")
            for pagina in ctx.aws("logs")
            .get_paginator("describe_log_groups")
            .paginate(logGroupNamePrefix=GRUPO_LOGS_API)
            for grupo in pagina.get("logGroups", [])
        ]
    except ClientError as exc:
        raise _error_aws(exc, f"describir el log group `{GRUPO_LOGS_API}`", "INF-1.3") from None
    if GRUPO_LOGS_API not in nombres:
        raise PrecondicionNoCumplida(f"INF-1.3: no existe el log group `{GRUPO_LOGS_API}`")
    return GRUPO_LOGS_API


def p5_historial_main(ctx: Contexto) -> str:
    try:
        comun.git("fetch", "--quiet", "origin", "main", timeout=180)
    except subprocess.CalledProcessError as exc:
        error = (exc.stderr or "").strip().splitlines()
        raise ErrorConfiguracion(f"`git fetch origin main` falló: {error[-1] if error else exc.returncode}") from None
    except subprocess.TimeoutExpired:
        raise ErrorConfiguracion("`git fetch origin main` no respondió a tiempo") from None
    return "origin/main actualizado"


# --- Comprobaciones ----------------------------------------------------------------------------------------------
def c1_health(ctx: Contexto) -> str:
    desplegada = ctx.imagen_desplegada()
    exigir(desplegada.etiqueta, f"la imagen desplegada no tiene etiqueta: {desplegada.imagen}")
    respuesta = ctx.http().get(f"{ctx.url_api}/health")
    exigir(respuesta.status_code == 200, f"GET /v1/health respondió {respuesta.status_code}")
    try:
        cuerpo = respuesta.json()
    except ValueError:
        raise Falla("GET /v1/health no devolvió JSON") from None
    exigir(isinstance(cuerpo, dict), "GET /v1/health no devolvió un objeto JSON")
    exigir(cuerpo.get("estado") == "ok", f"estado = {cuerpo.get('estado')!r}, se esperaba 'ok'")
    exigir(isinstance(cuerpo.get("version"), str) and cuerpo["version"], "falta `version`")
    commit = cuerpo.get("commit")
    exigir(isinstance(commit, str) and commit, "falta `commit`")
    exigir(
        str(desplegada.etiqueta).startswith(commit),
        f"commit {commit!r} no es prefijo de la etiqueta desplegada {desplegada.etiqueta}",
    )
    return f"200 · version {cuerpo['version']} · commit {commit} = imagen {desplegada.etiqueta}"


def c2a_formato_error(ctx: Contexto) -> str:
    request_id, _, respuesta = ctx.peticion_inexistente()
    exigir(respuesta.status_code == 404, f"respondió {respuesta.status_code}, se esperaba 404")
    try:
        cuerpo = respuesta.json()
    except ValueError:
        raise Falla("el 404 no trae JSON") from None
    exigir(isinstance(cuerpo, dict) and set(cuerpo) == {"error"}, f"el cuerpo debe tener solo `error`: {cuerpo}")
    error = cuerpo["error"]
    exigir(isinstance(error, dict), "`error` no es un objeto")
    exigir(error.get("codigo") == "NO_ENCONTRADO", f"codigo = {error.get('codigo')!r}")
    exigir(isinstance(error.get("mensaje"), str) and error["mensaje"].strip(), "`mensaje` vacío")
    exigir("detalle" in error and (error["detalle"] is None or isinstance(error["detalle"], dict)), "`detalle`")
    devuelto = respuesta.headers.get("X-Request-Id")
    exigir(devuelto == request_id, f"X-Request-Id devuelto {devuelto!r} distinto del enviado")
    return f"404 NO_ENCONTRADO con X-Request-Id {request_id}"


def c2b_logs(ctx: Contexto) -> str:
    request_id, inicio_ms = ctx.peticion_registrada()
    patron = f'{{ $.request_id = "{request_id}" }}'
    limite = time.monotonic() + ESPERA_LOGS_S
    while True:
        eventos = _filtrar_logs(ctx, patron, inicio_ms)
        if eventos or time.monotonic() >= limite:
            break
        time.sleep(INTERVALO_LOGS_S)
    exigir(eventos, f"ningún evento con request_id {request_id} en {GRUPO_LOGS_API} tras {ESPERA_LOGS_S} s")
    for evento in eventos:
        try:
            linea = json.loads(evento.get("message", ""))
        except ValueError:
            raise Falla(f"una línea de log no es JSON: {evento.get('message', '')[:120]!r}") from None
        faltan = [campo for campo in CAMPOS_LOG if campo not in linea]
        exigir(not faltan, f"línea de log sin {', '.join(faltan)}")
        exigir(linea.get("request_id") == request_id, "request_id distinto en la línea de log")
    tipos = sorted({json.loads(e["message"]).get("evento") for e in eventos})
    return f"{len(eventos)} evento(s) con el request_id ({', '.join(map(str, tipos))})"


def _filtrar_logs(ctx: Contexto, patron: str, inicio_ms: int) -> list[dict[str, Any]]:
    eventos: list[dict[str, Any]] = []
    paginador = ctx.aws("logs").get_paginator("filter_log_events")
    for pagina in paginador.paginate(logGroupName=GRUPO_LOGS_API, startTime=inicio_ms, filterPattern=patron):
        eventos.extend(pagina.get("events", []))
    return eventos


def c3a_ultimo_commit(ctx: Contexto) -> str:
    etiqueta = ctx.imagen_desplegada().etiqueta
    exigir(etiqueta, "la imagen desplegada no tiene etiqueta")
    try:
        ultimo = comun.git("log", "-1", "--format=%H", "origin/main", "--", CARPETA_PROYECTO)
    except subprocess.CalledProcessError as exc:
        raise Falla(f"`git log origin/main -- {CARPETA_PROYECTO}` falló ({exc.returncode})") from None
    exigir(ultimo, f"no hay commits en origin/main que toquen {CARPETA_PROYECTO}")
    if etiqueta == ultimo:
        return f"desplegado = último commit de main en {CARPETA_PROYECTO} ({ultimo[:12]})"
    # backend.yml también se dispara con cambios en su propio archivo (infra §3.9): un commit posterior que no toca
    # project/ despliega el mismo código con otro SHA. Vale si está en origin/main y project/ es idéntico.
    exigir(
        re.fullmatch(r"[0-9a-f]{40}", etiqueta),
        f"desplegado {etiqueta} ≠ último commit de main en project/ {ultimo}",
    )
    exigir(
        _git_ok("cat-file", "-e", f"{etiqueta}^{{commit}}"),
        f"desplegado {etiqueta[:12]}: ese commit no está en el historial local de origin/main",
    )
    exigir(
        _git_ok("merge-base", "--is-ancestor", etiqueta, "origin/main"),
        f"desplegado {etiqueta[:12]}: no está en origin/main",
    )
    exigir(
        _git_ok("diff", "--quiet", etiqueta, ultimo, "--", CARPETA_PROYECTO),
        f"desplegado {etiqueta[:12]} ≠ último commit de main en project/ {ultimo[:12]}: "
        f"{CARPETA_PROYECTO} cambió desde entonces",
    )
    return f"desplegado {etiqueta[:12]}: mismo {CARPETA_PROYECTO} que el último commit que lo tocó ({ultimo[:12]})"


def _git_ok(*argumentos: str) -> bool:
    """`git <argumentos>` terminó con 0 (sin git en el PATH: ErrorConfiguracion, código 3)."""
    try:
        comun.git(*argumentos)
    except subprocess.CalledProcessError:
        return False
    return True


def c3b_imagen_ecr(ctx: Contexto) -> str:
    from botocore.exceptions import ClientError

    etiqueta = ctx.imagen_desplegada().etiqueta or ""
    exigir(re.fullmatch(r"[0-9a-f]{40}", etiqueta), f"la etiqueta {etiqueta!r} no es un SHA de 40 caracteres")
    try:
        imagenes = ctx.aws("ecr").describe_images(repositoryName=REPOSITORIO_ECR, imageIds=[{"imageTag": etiqueta}])
    except ClientError as exc:
        raise Falla(f"la imagen {etiqueta} no está en ECR ({comun.codigo_error_aws(exc)})") from None
    exigir(imagenes.get("imageDetails"), f"la imagen {etiqueta} no está en `{REPOSITORIO_ECR}`")
    return f"`{REPOSITORIO_ECR}:{etiqueta[:12]}…` existe"


def c3c_despliegue(ctx: Contexto) -> str:
    servicio = ctx.servicio_api()
    revision = ctx.imagen_desplegada().task_definition
    despliegues = servicio.get("deployments", [])
    exigir(len(despliegues) == 1, f"hay {len(despliegues)} despliegues en curso, se esperaba 1")
    despliegue = despliegues[0]
    exigir(despliegue.get("status") == "PRIMARY", f"status = {despliegue.get('status')}")
    exigir(despliegue.get("rolloutState") == "COMPLETED", f"rolloutState = {despliegue.get('rolloutState')}")
    exigir(despliegue.get("taskDefinition") == revision, f"el despliegue usa {despliegue.get('taskDefinition')}")
    corriendo, deseado = servicio.get("runningCount"), servicio.get("desiredCount")
    exigir(corriendo == deseado == 1, f"runningCount = {corriendo}, desiredCount = {deseado}; se esperaba 1 y 1")
    return f"PRIMARY COMPLETED sobre {revision.rsplit('/', 1)[-1]}, 1/1 tareas"


def main(argv: list[str] | None = None) -> int:
    validador = comun.Validador(lote=LOTE, validacion="validation-1-1", entornos=("dev",), descripcion=__doc__)
    validador.iniciar(argv)
    ctx = Contexto()
    try:
        return validador.ejecutar(
            precondiciones=[
                ("P1", lambda: p1_credenciales(ctx)),
                ("P2", lambda: p2_inf13(ctx)),
                ("P3", lambda: p3_inf14(ctx)),
                ("P4", lambda: p4_grupo_logs(ctx)),
                ("P5", lambda: p5_historial_main(ctx)),
            ],
            comprobaciones=[
                ("C1", lambda: c1_health(ctx)),
                ("C2a", lambda: c2a_formato_error(ctx)),
                ("C2b", lambda: c2b_logs(ctx)),
                ("C3a", lambda: c3a_ultimo_commit(ctx)),
                ("C3b", lambda: c3b_imagen_ecr(ctx)),
                ("C3c", lambda: c3c_despliegue(ctx)),
            ],
            manuales=[],
            limpieza=None,  # no crea datos (validation-1-1.md §4)
        )
    finally:
        ctx.cerrar()


if __name__ == "__main__":
    sys.exit(main())
