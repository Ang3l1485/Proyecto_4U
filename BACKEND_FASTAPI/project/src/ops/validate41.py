"""BE-4.1 — Administración de videos e imágenes, y purga. Tras borrar un video sus fotos dejan de salir en la búsqueda
desde la llamada siguiente (C1); sus objetos de S3 desaparecen con la purga (C2); con el `worker` apagado el
reconciliador re-encola y, al volver, no quedan huérfanos (C3); renombrar y borrar quedan en `auditoria` (C4); las
respuestas cumplen §5.5 (C5).

Documento: BACKEND_FASTAPI/docs/validation/validation-4-1.md · criterios: BACKEND_FASTAPI/docs/PLAN.md §2.2.

    cd BACKEND_FASTAPI/project
    uv run --group ops python src/ops/validate41.py --entorno dev

Variables: AWS_PROFILE (obligatoria; también suspende y reanuda el escalado de `worker`); VALIDACION_API_URL,
VALIDACION_ADMIN_CORREO y VALIDACION_ADMIN_PASSWORD (opcionales). Solo `dev`. Empieza antes de las 21:00 de Bogotá:
dura 35–60 min. Enciende `embedding` si está apagado y al terminar lo deja como lo encontró. Mientras corre C3 la
ingesta de `dev` queda detenida. Crea los videos `validacion-41-<sello>` (6 fotos) y `…-b` (2 fotos) y el lugar
`validacion-41-<sello>`, y los borra. Nunca imprime contraseñas, tokens ni URLs prefirmadas.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import comun
from comun import ErrorConfiguracion, Falla, PrecondicionNoCumplida, exigir

LOTE = "BE-4.1"
INICIADA_POR = "validate41"
FOTOS_V1 = (1, 2, 3, 4, 5, 6)
FOTOS_V2 = (1, 2)
VECINOS_C1 = (1, 2, 3)
K_C1 = 5
HORA_LIMITE = 21
LIMITE_PROCESADO_S = 20 * 60
LIMITE_PURGA_S = 10 * 60  # C2 y C3c
LIMITE_RECONCILIADOR_S = 21 * 60  # C3b: dos ciclos de RECONCILIADOR_CADA_MIN sobre el umbral de 10 min
LIMITE_WORKER_PARADO_S = 5 * 60
PAUSA_SONDEO_S = 15.0
PAUSA_PURGA_S = 30.0
MARGEN_LOGS_S = 60
PLAN_BACKEND = comun.RAIZ_CARPETA / "docs" / "PLAN.md"
RUTA_IMAGENES = "/admin/images"
DIMENSION_WORKER = "ecs:service:DesiredCount"
#: Campos exactos de §5.5 (los del backend se copian aquí: las carpetas no comparten código de validación).
CAMPOS_VIDEO = {
    "id", "numero", "nombre", "ref_cliente", "estado", "creado_en", "iniciado_en", "finalizado_en", "duracion_s",
    "distancia_m", "pasos", "inicio", "total_fotos", "conteo", "creado_por",
}  # fmt: skip
CAMPOS_IMAGEN = {
    "id", "video_id", "orden", "lat", "lng", "rumbo", "capturada_en", "estado", "error", "calidad", "lugar", "notas",
    "url", "url_miniatura", "url_expira_en",
}  # fmt: skip
CAMPOS_PAGINA = {"items", "total", "pagina", "por_pagina"}
CAMPOS_BORRADO = {"id", "estado", "fotos_retiradas", "purga"}
ESTADOS_VIDEO = {"pendiente", "procesando", "procesado", "con_errores", "eliminado"}
ESTADOS_IMAGEN = {"pendiente_subida", "subida", "procesada", "error"}
SUSPENDIDO = {"DynamicScalingInSuspended": True, "DynamicScalingOutSuspended": True, "ScheduledScalingSuspended": True}
REANUDADO = {k: False for k in SUSPENDIDO}


def avisar(mensaje: str) -> None:
    print(mensaje, file=sys.stderr, flush=True)


def _esperar(respuesta: Any, estado: int, que: str) -> Any:
    exigir(respuesta.status_code == estado, f"{que}: {comun.describir_respuesta(respuesta)}, se esperaba {estado}")
    return respuesta.json() if respuesta.content else None


def incluida(solo: str | None, id_: str) -> bool:
    if not solo:
        return True
    elegidas = {parte.strip() for parte in solo.split(",") if parte.strip()}
    criterio = re.match(r"([A-Z]+\d+)", id_)
    return id_ in elegidas or (criterio is not None and criterio.group(1) in elegidas)


def exigir_video(cuerpo: Any, que: str) -> None:
    exigir(isinstance(cuerpo, dict), f"{que}: no es un objeto")
    campos = set(cuerpo) - {"fotos"}
    exigir(campos == CAMPOS_VIDEO, f"{que}: campos {sorted(campos ^ CAMPOS_VIDEO)} de más o de menos")
    exigir(cuerpo["estado"] in ESTADOS_VIDEO, f"{que}: estado {cuerpo['estado']!r}")
    exigir(set(cuerpo["conteo"]) == ESTADOS_IMAGEN, f"{que}: conteo {sorted(cuerpo['conteo'])}")
    exigir(re.fullmatch(comun.PATRON_FECHA_UTC, cuerpo["creado_en"]) is not None, f"{que}: creado_en con otro formato")


def exigir_imagen(cuerpo: Any, que: str, extra: set[str] | None = None) -> None:
    exigir(isinstance(cuerpo, dict), f"{que}: no es un objeto")
    esperados = CAMPOS_IMAGEN | (extra or set())
    exigir(set(cuerpo) == esperados, f"{que}: campos {sorted(set(cuerpo) ^ esperados)} de más o de menos")
    exigir(cuerpo["estado"] in ESTADOS_IMAGEN, f"{que}: estado {cuerpo['estado']!r}")
    exigir(cuerpo["calidad"] in {"alta", "normal", "baja"}, f"{que}: calidad {cuerpo['calidad']!r}")


class RecorridoPatrones(comun.RecorridoPrueba):
    """Fotos en color con patrones distintos (`comun.jpeg_patron`), como en `validate24.py`: C1 necesita que cada foto
    sea su propio primer vecino."""

    def foto(self, orden: int) -> bytes:
        if orden not in self._fotos:
            self._fotos[orden] = comun.jpeg_patron(self.semilla * 1000 + orden)
        return self._fotos[orden]


# --- Contexto ------------------------------------------------------------------------------------------------------
class Contexto:
    def __init__(self, entorno: str = "dev") -> None:
        self.entorno = entorno
        self.sesion: Any = None
        self.api: comun.ClienteApi | None = None
        self.backend: Any = None
        self.emb: Any = None
        self.s3: Any = None
        self.sqs: Any = None
        self.logs: Any = None
        self.bucket: str | None = None
        self.url_purga: str | None = None
        self.url_purga_dlq: str | None = None
        self.admin: tuple[str, str] | None = None
        self.admin_id: str | None = None
        self.dormir: Callable[[float], None] = time.sleep
        self.ahora: Callable[[], datetime] = lambda: datetime.now(UTC)
        self.http: Any = None
        self.http_s3: Any = None
        self.sello = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        self.solo: str | None = None
        self._outputs: dict[str, Any] | None = None
        self._token: str | None = None
        self.recorridos: dict[str, RecorridoPatrones] = {}
        self.borrados: set[str] = set()  # videos con DELETE 202
        self.lugar_id: str | None = None
        self.estaba_encendido: bool | None = None
        self.encendido_por_mi = False
        self.escalado_suspendido_por_mi = False
        self.worker_deseado: int | None = None
        self.dlq_inicial: int | None = None
        self.respuestas: dict[str, Any] = {}  # lo que C5a revisa (detalle de V1, PATCH, DELETE)
        self.renombrado: str | None = None

    # -- infraestructura -------------------------------------------------------------------------------------------
    def outputs(self) -> dict[str, Any]:
        if self._outputs is None:
            self._outputs = comun.outputs_terraform()
        return self._outputs

    def preparar(self, url: str) -> None:
        self.api = comun.ClienteApi(url, http=self.http, dormir=self.dormir)
        self.backend = comun.EntornoBackend(
            self.entorno, sesion=self.sesion, outputs=self.outputs, iniciada_por=INICIADA_POR, dormir=self.dormir
        )

    def token(self) -> str:
        if self._token is None:
            self._token = self.api.token(*self.admin, quien="el admin")
        return self._token

    def pedir(self, metodo: str, ruta: str, **kwargs: Any) -> Any:
        return self.api.pedir(metodo, ruta, token=self.token(), **kwargs)

    def semilla(self) -> int:
        return int(self.sello.replace("-", "")) % 1_000_000

    def coordenada(self) -> tuple[float, float]:
        """Una coordenada fuera del campus distinta en cada ejecución (C1 no encuentra restos de otras pruebas)."""
        return 1.0 + (self.semilla() % 997) * 0.001, -100.0

    @property
    def prefijo(self) -> str:
        return f"{comun.PREFIJO_VALIDACION}41-{self.sello}"

    def listo_en_api(self) -> bool:
        return comun.embedding_en_api(self.api) == "ok"

    # -- AWS (las pruebas sustituyen estos métodos) -----------------------------------------------------------------
    def claves(self, prefijo: str) -> list[str]:
        return comun.claves_s3(self.s3, self.bucket, prefijo)

    def mensajes_purga(self) -> int:
        return comun.mensajes_cola(self.sqs, self.url_purga)[0]

    def mensajes_dlq(self) -> int:
        visibles, en_vuelo = comun.mensajes_cola(self.sqs, self.url_purga_dlq)
        return visibles + en_vuelo

    def sql(self, consulta: str) -> list[list[str]]:
        return [linea.strip().split("|") for linea in self.backend.sql(consulta) if linea.strip()]

    def eventos_api(self, evento: str, desde: datetime) -> list[dict[str, Any]]:
        encontrados = []
        for mensaje in comun.mensajes_log(self.logs, comun.LOG_API, desde):
            try:
                linea = json.loads(mensaje)
            except ValueError:
                continue
            if isinstance(linea, dict) and linea.get("evento") == evento:
                encontrados.append(linea)
        return encontrados

    def _escalado(self) -> Any:
        return self.emb.aws("application-autoscaling")

    def escalado_worker_suspendido(self) -> bool:
        try:
            objetivos = self._escalado().describe_scalable_targets(
                ServiceNamespace="ecs", ResourceIds=[comun.recurso_ecs(comun.SERVICIO_WORKER)]
            )["ScalableTargets"]
        except Exception as exc:
            raise comun._errores_aws(exc, "describe-scalable-targets de worker") from None
        if not objetivos:
            raise PrecondicionNoCumplida("INF-2.1: worker no tiene objetivo escalable")
        return any(objetivos[0].get("SuspendedState", {}).values())

    def suspender_escalado_worker(self, suspender: bool) -> None:
        try:
            self._escalado().register_scalable_target(
                ServiceNamespace="ecs",
                ResourceId=comun.recurso_ecs(comun.SERVICIO_WORKER),
                ScalableDimension=DIMENSION_WORKER,
                SuspendedState=SUSPENDIDO if suspender else REANUDADO,
            )
        except Exception as exc:
            raise comun._errores_aws(exc, "register-scalable-target de worker") from None

    def worker(self) -> dict[str, Any]:
        return self.emb.servicio(comun.SERVICIO_WORKER)

    def descargar(self, url: str) -> tuple[int, str]:
        import httpx

        http = self.http_s3 or httpx.Client(timeout=60)
        try:
            r = http.request("GET", url)
        except Exception as exc:
            raise Falla(f"GET de la miniatura: {type(exc).__name__} (sin respuesta de S3)") from None
        return r.status_code, r.headers.get("content-type", "")

    # -- datos de prueba -------------------------------------------------------------------------------------------
    def recorrido(self, clave: str, fotos: tuple[int, ...]) -> RecorridoPatrones:
        if clave not in self.recorridos:
            lat, lng = self.coordenada()
            nombre = self.prefijo if clave == "V1" else f"{self.prefijo}-b"
            recorrido = RecorridoPatrones(
                self.api, self.token, nombre, total_fotos=len(fotos), http_s3=self.http_s3, lat=lat, lng=lng,
                semilla=self.semilla() + (0 if clave == "V1" else 500_000),
            )  # fmt: skip
            _esperar(recorrido.crear(), 201, f"POST /v1/collect/videos ({clave})")
            self.recorridos[clave] = recorrido
        return self.recorridos[clave]

    def fotos(self, clave: str) -> dict[int, dict[str, Any]]:
        video_id = self.recorridos[clave].video_id
        detalle = _esperar(self.pedir("GET", f"/admin/videos/{video_id}"), 200, f"GET /v1/admin/videos/{{{clave}}}")
        return {int(f["orden"]): f for f in detalle.get("fotos", [])}

    def asegurar_procesadas(self, clave: str, fotos: tuple[int, ...]) -> float:
        recorrido = self.recorrido(clave, fotos)
        inicio = self.ahora()
        recorrido.asegurar_subidas(list(fotos))
        if recorrido.completar().status_code != 200:
            raise Falla(f"POST …/complete de {clave} no dio 200")
        hasta = inicio + timedelta(seconds=LIMITE_PROCESADO_S)
        while True:
            estados = {o: f.get("estado") for o, f in self.fotos(clave).items() if o in fotos}
            exigir("error" not in estados.values(), f"{clave}: una foto quedó en error: {estados}")
            if set(estados.values()) == {"procesada"} and len(estados) == len(fotos):
                return (self.ahora() - inicio).total_seconds() / 60
            if self.ahora() >= hasta:
                raise Falla(f"{clave}: tras {LIMITE_PROCESADO_S // 60} min, estados {estados}")
            self.dormir(PAUSA_SONDEO_S)

    def asegurar_lugar(self) -> str:
        if self.lugar_id is None:
            lat, lng = self.coordenada()
            cuerpo = {"nombre": self.prefijo, "categoria": "bloque", "lat": lat, "lng": lng}
            self.lugar_id = _esperar(self.pedir("POST", comun.RUTA_LUGARES_ADMIN, json=cuerpo), 201, "POST lugar")["id"]
        return self.lugar_id

    def borrar_video(self, clave: str) -> dict[str, Any]:
        video_id = self.recorridos[clave].video_id
        cuerpo = _esperar(
            self.pedir("DELETE", f"/admin/videos/{video_id}"), 202, f"DELETE /v1/admin/videos/{{{clave}}}"
        )
        self.borrados.add(video_id)
        return cuerpo

    def esperar_purga(self, clave: str, limite_s: float = LIMITE_PURGA_S) -> float:
        video_id = self.recorridos[clave].video_id
        inicio = self.ahora()
        while True:
            restantes = len(self.claves(f"dataset/{video_id}/")) + len(self.claves(f"thumbs/{video_id}/"))
            if restantes == 0:
                break
            if (self.ahora() - inicio).total_seconds() >= limite_s:
                raise Falla(f"{clave}: tras {limite_s / 60:.0f} min quedan {restantes} objetos en S3")
            self.dormir(PAUSA_PURGA_S)
        filas = self.sql(f"SELECT purgado_en IS NOT NULL FROM videos WHERE id = '{uuid.UUID(video_id)}'")  # noqa: S608
        exigir(filas == [["t"]], f"{clave}: objetos borrados pero purgado_en sigue nulo ({filas})")
        return (self.ahora() - inicio).total_seconds() / 60

    # -- embedding, preparación y limpieza ---------------------------------------------------------------------------
    def asegurar_embedding(self) -> str:
        datos = self.emb.servicio(comun.SERVICIO_EMBEDDING)
        if int(datos.get("desiredCount", 0)) >= 1 and self.listo_en_api():
            self.emb.latido()
            return "ya encendido (latido publicado)"
        return f"encendido en {self.emb.encender(self.listo_en_api):.0f} s"

    def preparacion(self) -> str:
        partes = []
        if self.escalado_worker_suspendido():
            self.suspender_escalado_worker(False)
            partes.append("escalado de worker reanudado (lo dejó suspendido una ejecución anterior)")
        restos = comun.videos_validacion(self.api, self.token())
        for video in restos:
            _esperar(self.pedir("DELETE", f"/admin/videos/{video['id']}"), 202, "DELETE de un resto validacion-")
        partes.append(f"restos validacion- borrados: {len(restos)}" if restos else "sin restos validacion-")
        partes.append(comun.borrar_lugares_restos(self.api, self.token()))
        self.dlq_inicial = self.mensajes_dlq()
        partes.append(f"DLQ de purga: {self.dlq_inicial}")
        return " · ".join(partes)

    def _restaurar_embedding(self) -> str:
        if self.emb is None or self.estaba_encendido is None:
            return "embedding sin tocar"
        if self.encendido_por_mi:
            self.emb.apagar()
            return "embedding apagado (lo encendió el validador)"
        if self.estaba_encendido and int(self.emb.servicio(comun.SERVICIO_EMBEDDING).get("desiredCount", 0)) < 1:
            self.emb.encender(self.listo_en_api)
            return "embedding vuelto a encender (estaba encendido)"
        return "embedding sigue encendido (como estaba)" if self.estaba_encendido else "embedding sin tocar"

    def _restaurar_worker(self) -> str:
        if not self.escalado_suspendido_por_mi:
            return "escalado de worker sin tocar"
        self.suspender_escalado_worker(False)
        self.escalado_suspendido_por_mi = False
        if self.worker_deseado and int(self.worker().get("desiredCount", 0)) < self.worker_deseado:
            self.emb.poner(comun.SERVICIO_WORKER, self.worker_deseado)
        return "escalado de worker reanudado"

    def limpiar(self) -> str:
        partes: list[str] = []
        fallos: list[str] = []
        pasos = [self._restaurar_worker, self._restaurar_embedding, self._borrar_datos]
        try:
            for paso in pasos:
                try:
                    partes.append(paso())
                except Exception as exc:
                    fallos.append(f"{paso.__name__.strip('_')}: {comun._resumen(exc)}")
            if fallos:
                raise Falla(" · ".join(partes + fallos))
            return " · ".join(partes)
        finally:
            if self.api is not None:
                self.api.cerrar()
            for recorrido in self.recorridos.values():
                recorrido.cerrar()

    def _borrar_datos(self) -> str:
        if self.api is None or self.admin is None:
            return "nada que borrar"
        videos = 0
        for recorrido in self.recorridos.values():
            if recorrido.video_id and recorrido.video_id not in self.borrados:
                r = self.pedir("DELETE", f"/admin/videos/{recorrido.video_id}")
                exigir(r.status_code in (202, 404), f"DELETE del video de prueba: {comun.describir_respuesta(r)}")
                videos += 1
        lugares = comun.borrar_lugares(self.api, self.token(), [self.lugar_id] if self.lugar_id else [])
        return f"videos de prueba borrados al final: {videos} (la purga limpia S3) · lugares: {lugares}"


# --- Precondiciones ------------------------------------------------------------------------------------------------
def p1_credenciales(ctx: Contexto) -> str:
    ctx.sesion = comun.sesion_aws()
    arn = comun.verificar_cuenta(ctx.sesion)
    ctx.emb = comun.EmbeddingDev(ctx.sesion, dormir=ctx.dormir, reloj=ctx.ahora, avisar=avisar)
    return f"cuenta {comun.CUENTA_AWS} ({arn.rsplit('/', 1)[-1]})"


def p2_lotes_y_hora(ctx: Contexto) -> str:
    import httpx

    try:
        plan = PLAN_BACKEND.read_text(encoding="utf-8")
    except OSError:
        raise ErrorConfiguracion(f"no se pudo leer {PLAN_BACKEND}") from None
    faltan = [lote for lote in ("BE-2.2", "BE-2.4") if not comun.lote_hecho(plan, lote)]
    if faltan:
        raise PrecondicionNoCumplida(f"{' y '.join(faltan)} sin «Hecho» en BACKEND_FASTAPI/docs/PLAN.md §3")
    ahora = comun.hora_bogota(ctx.ahora())
    if ahora.hour >= HORA_LIMITE:
        raise ErrorConfiguracion(f"son las {ahora:%H:%M} en Bogotá: empieza antes de las {HORA_LIMITE}:00")
    url = comun.url_api(None if os.environ.get("VALIDACION_API_URL", "").strip() else ctx.outputs())
    ctx.preparar(url)
    try:
        listo = ctx.api.pedir("GET", "/health/ready")
    except httpx.HTTPError as exc:
        raise PrecondicionNoCumplida(f"BE-1.1: GET /v1/health/ready no respondió ({type(exc).__name__})") from None
    if listo.status_code != 200 or listo.json().get("db") != "ok":
        raise PrecondicionNoCumplida(f"BE-1.2: GET /v1/health/ready respondió {comun.describir_respuesta(listo)}")
    return f'BE-2.2 y BE-2.4 «Hecho» · {url} · /v1/health/ready → "db": "ok" · {ahora:%H:%M} en Bogotá'


def p3_login_y_desplegado(ctx: Contexto) -> str:
    ctx.admin = comun.credenciales_admin(ctx.entorno, ctx.sesion)
    respuesta = ctx.api.login(*ctx.admin)
    if respuesta.status_code == 401:
        raise ErrorConfiguracion("las credenciales del admin no valen (401 CREDENCIALES_INVALIDAS)")
    if respuesta.status_code != 200:
        raise PrecondicionNoCumplida(f"BE-1.3: el login respondió {comun.describir_respuesta(respuesta)}")
    cuerpo = respuesta.json()
    if cuerpo.get("usuario", {}).get("rol") != "admin":
        raise ErrorConfiguracion("el usuario de VALIDACION_ADMIN_* no es admin")
    ctx._token, ctx.admin_id = cuerpo["token"], cuerpo["usuario"].get("id")
    r = ctx.pedir("GET", RUTA_IMAGENES, params={"por_pagina": 1})
    if r.status_code == 404:
        raise PrecondicionNoCumplida("BE-4.1 sin desplegar: GET /v1/admin/images respondió 404")
    exigir(r.status_code == 200, f"GET /v1/admin/images: {comun.describir_respuesta(r)}")
    return "login admin 200 (rol admin) · GET /v1/admin/images → 200"


def p4_recursos(ctx: Contexto) -> str:
    from botocore.exceptions import ClientError

    outputs = ctx.outputs()
    for nombre in ("bucket_dataset", "sqs_purga_url", "sqs_purga_dlq_url"):
        if not outputs.get(nombre):
            raise PrecondicionNoCumplida(f"INF-1.2: falta el output {nombre}")
    ctx.bucket, ctx.url_purga, ctx.url_purga_dlq = (
        outputs["bucket_dataset"], outputs["sqs_purga_url"], outputs["sqs_purga_dlq_url"],
    )  # fmt: skip
    ctx.s3, ctx.sqs, ctx.logs = ctx.sesion.client("s3"), ctx.sesion.client("sqs"), ctx.sesion.client("logs")
    comun.comprobar_bucket(ctx.s3, ctx.bucket)
    comun.red_tareas(outputs)
    try:
        ctx.backend.imagen(comun.FAMILIA_VALIDACION)
        worker = ctx.backend.revision(comun.FAMILIA_WORKER)
    except ClientError as exc:
        if comun.es_acceso_denegado(exc):
            raise ErrorConfiguracion("sin permiso para describir las definiciones de tarea") from None
        raise PrecondicionNoCumplida(
            f"INF-1.3: falta una definición de tarea ({comun.codigo_error_aws(exc)})"
        ) from None
    except Falla as exc:
        raise PrecondicionNoCumplida(f"BE-4.1 sin desplegar del todo: {exc}") from None
    ctx.mensajes_purga()
    inf21 = ctx.emb.comprobar_inf21()
    ctx.escalado_worker_suspendido()
    return f"bucket, purga y su DLQ, {worker.rsplit('/', 1)[-1]} con la imagen de api · INF-2.1: {inf21}"


def p5_embedding(ctx: Contexto) -> str:
    datos = ctx.emb.servicio(comun.SERVICIO_EMBEDDING)
    ctx.estaba_encendido = int(datos.get("desiredCount", 0)) >= 1
    ctx.encendido_por_mi = not ctx.estaba_encendido
    try:
        detalle = ctx.asegurar_embedding()
    except Falla as exc:
        raise PrecondicionNoCumplida(f"EMB-2.1/INF-2.1: embedding no quedó listo: {exc}") from None
    return f'embedding {detalle} · /v1/health/ready → "embedding": "ok"'


# --- Comprobaciones ------------------------------------------------------------------------------------------------
def _asegurar_v1(ctx: Contexto) -> RecorridoPatrones:
    if "V1" not in ctx.recorridos or "detalle_v1" not in ctx.respuestas:
        minutos = ctx.asegurar_procesadas("V1", FOTOS_V1)
        ctx.respuestas["minutos_v1"] = minutos
        video_id = ctx.recorridos["V1"].video_id
        ctx.respuestas["detalle_v1"] = _esperar(ctx.pedir("GET", f"/admin/videos/{video_id}"), 200, "detalle de V1")
    return ctx.recorridos["V1"]


def c5b_imagenes(ctx: Contexto) -> str:
    v1 = _asegurar_v1(ctx)
    ids = {o: str(v1.registro[o]["id"]) for o in FOTOS_V1}
    lugar_id = ctx.asegurar_lugar()
    pagina = _esperar(ctx.pedir("GET", RUTA_IMAGENES, params={"video_id": v1.video_id}), 200, "GET /v1/admin/images")
    exigir(
        set(pagina) == CAMPOS_PAGINA and pagina["total"] == len(FOTOS_V1), f"lista de V1: total {pagina.get('total')}"
    )
    exigir([i["orden"] for i in pagina["items"]] == list(FOTOS_V1), "lista de V1 fuera de orden")
    for item in pagina["items"]:
        exigir_imagen(item, f"imagen {item.get('orden')} de la lista")
    detalle = _esperar(ctx.pedir("GET", f"{RUTA_IMAGENES}/{ids[1]}"), 200, "GET /v1/admin/images/{foto 1}")
    exigir_imagen(detalle, "detalle de la foto 1", {"video", "vector"})
    exigir((detalle["vector"] or {}).get("version_vector"), "la foto 1 (procesada) sin vector")
    exigir(detalle["video"]["id"] == v1.video_id, "detalle de la foto 1 con otro video")
    exigir(detalle["url_miniatura"], "la foto 1 (procesada) sin url_miniatura")
    codigo, tipo = ctx.descargar(detalle["url_miniatura"])
    exigir(codigo == 200 and tipo.startswith("image/jpeg"), f"miniatura de la foto 1: {codigo} {tipo!r}")
    lat, lng = detalle["lat"] + 0.000045, detalle["lng"]  # ≈ 5 m al norte
    cambios = {
        "lat": lat,
        "lng": lng,
        "lugar_id": lugar_id,
        "calidad": "baja",
        "notas": comun.PREFIJO_VALIDACION + "41",
    }
    editada = _esperar(ctx.pedir("PATCH", f"{RUTA_IMAGENES}/{ids[4]}", json=cambios), 200, "PATCH foto 4")
    exigir_imagen(editada, "PATCH foto 4")
    exigir(
        (editada["lat"], editada["calidad"], editada["notas"], (editada["lugar"] or {}).get("id"))
        == (lat, "baja", cambios["notas"], lugar_id),
        "PATCH foto 4 sin los valores nuevos",
    )
    reasignar = {"accion": "reasignar", "ids": [ids[1], ids[2]], "lugar_id": lugar_id}
    lote = _esperar(ctx.pedir("POST", f"{RUTA_IMAGENES}/lote", json=reasignar), 200, "lote reasignar")
    exigir(lote == {"procesadas": 2, "fallidas": []}, f"lote reasignar: {lote}")
    ajeno = str(uuid.uuid4())
    eliminar = {"accion": "eliminar", "ids": [ids[6], ajeno]}
    lote = _esperar(ctx.pedir("POST", f"{RUTA_IMAGENES}/lote", json=eliminar), 200, "lote eliminar")
    exigir(lote == {"procesadas": 1, "fallidas": [{"id": ajeno, "codigo": "NO_ENCONTRADO"}]}, f"lote eliminar: {lote}")
    _esperar(ctx.pedir("POST", f"{RUTA_IMAGENES}/{ids[4]}/reprocesar"), 202, "reprocesar foto 4")
    exigir(ctx.fotos("V1")[4]["estado"] in ("subida", "procesada"), "la foto 4 no volvió a subida")
    _esperar(ctx.pedir("DELETE", f"{RUTA_IMAGENES}/{ids[5]}"), 204, "DELETE foto 5")
    _esperar(ctx.pedir("DELETE", f"{RUTA_IMAGENES}/{ids[5]}"), 404, "DELETE foto 5 repetido")
    return (
        f"V1 con {len(FOTOS_V1)} fotos procesadas en {ctx.respuestas['minutos_v1']:.1f} min · lista y detalle con los "
        "campos de §5.5 (vector y miniatura 200 image/jpeg) · PATCH foto 4 · lote reasignar 2/0 y eliminar 1/1 "
        "(NO_ENCONTRADO) · reprocesar 202 · DELETE 204 y luego 404"
    )


def c4a_renombrar(ctx: Contexto) -> str:
    v1 = _asegurar_v1(ctx)
    ctx.renombrado = f"{ctx.prefijo}-renombrado"[:40]
    cuerpo = _esperar(
        ctx.pedir("PATCH", f"/admin/videos/{v1.video_id}", json={"nombre": ctx.renombrado}), 200, "PATCH V1"
    )
    exigir(cuerpo.get("nombre") == ctx.renombrado, f"PATCH V1 devolvió el nombre {cuerpo.get('nombre')!r}")
    ctx.respuestas["patch_v1"] = cuerpo
    return f"PATCH /v1/admin/videos/{{V1}} → 200 con el nombre nuevo ({len(ctx.renombrado)} caracteres)"


def _vecinos_de(ctx: Contexto, orden: int) -> list[dict[str, Any]]:
    foto = ctx.recorridos["V1"].foto(orden)
    cuerpo = _esperar(comun.pedir_vecinos(ctx.api, ctx.token(), foto, k=K_C1), 200, f"vecinos de la foto {orden}")
    return cuerpo.get("vecinos") or []


def c1a_propias_primeras(ctx: Contexto) -> str:
    v1 = _asegurar_v1(ctx)
    similitudes = []
    for orden in VECINOS_C1:
        vecinos = _vecinos_de(ctx, orden)
        exigir(vecinos, f"la foto {orden} no tiene vecinos")
        primero = vecinos[0]
        exigir(
            primero.get("imagen_id") == str(v1.registro[orden]["id"]) and primero.get("video_id") == v1.video_id,
            f"la foto {orden}: el primer vecino es {primero.get('imagen_id')}, no ella misma",
        )
        similitudes.append(primero.get("similitud"))
    return f"fotos {VECINOS_C1} son su propio primer vecino (similitud {similitudes})"


def c1b_borrado_sale_de_la_busqueda(ctx: Contexto) -> str:
    v1 = _asegurar_v1(ctx)
    cuerpo = ctx.borrar_video("V1")
    exigir(set(cuerpo) == CAMPOS_BORRADO, f"DELETE V1: campos {sorted(cuerpo)}")
    exigir((cuerpo["estado"], cuerpo["purga"]) == ("eliminado", "programada"), f"DELETE V1: {cuerpo}")
    ctx.respuestas["delete_v1"] = cuerpo
    for orden in VECINOS_C1:
        propios = [v for v in _vecinos_de(ctx, orden) if v.get("video_id") == v1.video_id]
        exigir(not propios, f"tras el DELETE, la foto {orden} sigue encontrando {len(propios)} fotos de V1")
    return (
        f"DELETE → 202 {cuerpo['fotos_retiradas']} fotos retiradas · ningún vecino de V1 en las 3 consultas siguientes"
    )


def c4b_auditoria(ctx: Contexto) -> str:
    v1 = _asegurar_v1(ctx)
    exigir(v1.video_id in ctx.borrados, "depende de C1b, que no borró V1")
    filas = ctx.sql(
        "SELECT accion, actor_id FROM auditoria WHERE entidad_id = "  # noqa: S608
        f"'{uuid.UUID(v1.video_id)}' AND accion IN ('video.renombrar', 'video.eliminar') ORDER BY id"
    )
    acciones = sorted(fila[0] for fila in filas)
    exigir(acciones == ["video.eliminar", "video.renombrar"], f"filas de auditoria de V1: {acciones}")
    exigir(all(fila[1] == ctx.admin_id for fila in filas), "las filas de auditoria no tienen al admin como actor")
    return "auditoria: video.renombrar y video.eliminar de V1, una cada una, con actor_id = el admin"


def c5a_contrato_videos(ctx: Contexto) -> str:
    v1 = _asegurar_v1(ctx)
    detalle = ctx.respuestas["detalle_v1"]
    exigir_video(detalle, "detalle de V1")
    for foto in detalle["fotos"]:
        exigir_imagen(foto, f"foto {foto.get('orden')} del detalle de V1")
    if "patch_v1" in ctx.respuestas:
        exigir_video(ctx.respuestas["patch_v1"], "respuesta del PATCH")
    pagina = _esperar(
        ctx.pedir("GET", "/admin/videos", params={"q": comun.PREFIJO_VALIDACION, "orden": "fecha", "dir": "desc"}),
        200,
        "GET /v1/admin/videos",
    )
    exigir(set(pagina) == CAMPOS_PAGINA, f"página con campos {sorted(pagina)}")
    for video in pagina["items"]:
        exigir_video(video, "elemento de la lista")
    if v1.video_id in ctx.borrados:
        repetido = _esperar(ctx.pedir("DELETE", f"/admin/videos/{v1.video_id}"), 202, "DELETE V1 repetido")
        exigir(repetido == ctx.respuestas.get("delete_v1"), f"DELETE repetido distinto: {repetido}")
        _esperar(ctx.pedir("GET", f"/admin/videos/{v1.video_id}"), 404, "GET V1 borrado")
    return "detalle, PATCH y lista con los campos de §5.5 · DELETE repetido igual · GET del video borrado → 404"


def c2_purga(ctx: Contexto) -> str:
    _asegurar_v1(ctx)
    if ctx.recorridos["V1"].video_id not in ctx.borrados:
        ctx.borrar_video("V1")
    minutos = ctx.esperar_purga("V1")
    return f"dataset/ y thumbs/ de V1 vacíos en {minutos:.1f} min · purgado_en no nulo"


def c3_reconciliador(ctx: Contexto) -> str:
    minutos = ctx.asegurar_procesadas("V2", FOTOS_V2)
    v2 = ctx.recorridos["V2"]
    exigir(ctx.claves(f"dataset/{v2.video_id}/"), "V2 sin objetos en S3 antes de borrarlo")
    ctx.worker_deseado = max(1, int(ctx.worker().get("desiredCount", 0)))
    ctx.escalado_suspendido_por_mi = True  # antes de suspender: la limpieza lo reanuda aunque falle a medias
    ctx.suspender_escalado_worker(True)
    ctx.emb.poner(comun.SERVICIO_WORKER, 0)
    inicio = ctx.ahora()
    while int(ctx.worker().get("runningCount", 0)) > 0:
        if (ctx.ahora() - inicio).total_seconds() >= LIMITE_WORKER_PARADO_S:
            raise Falla("worker no llegó a 0 tareas en 5 min")
        ctx.dormir(PAUSA_SONDEO_S)
    # C3a: borrar con el worker apagado deja el mensaje en la cola.
    borrado_en = ctx.ahora()
    ctx.borrar_video("V2")
    ctx.dormir(PAUSA_PURGA_S)  # los contadores de SQS llegan con retraso
    anotados = ctx.mensajes_purga()
    exigir(anotados >= 1, f"purga con {anotados} mensajes visibles tras borrar V2 (se esperaba ≥ 1)")
    # C3b: el reconciliador vuelve a encolar mientras los objetos siguen en S3.
    reencolados: list[dict[str, Any]] = []
    while not reencolados:
        if (ctx.ahora() - borrado_en).total_seconds() >= LIMITE_RECONCILIADOR_S:
            raise Falla(f"tras {LIMITE_RECONCILIADOR_S // 60} min, ningún purgas_reencoladas con enviados ≥ 1")
        ctx.dormir(PAUSA_PURGA_S)
        desde = borrado_en - timedelta(seconds=MARGEN_LOGS_S)
        reencolados = [e for e in ctx.eventos_api("purgas_reencoladas", desde) if int(e.get("enviados", 0)) >= 1]
    despues = ctx.mensajes_purga()
    exigir(ctx.claves(f"dataset/{v2.video_id}/"), "los objetos de V2 desaparecieron con el worker apagado")
    # C3c: con el worker de vuelta, purga sin huérfanos ni DLQ.
    ctx.suspender_escalado_worker(False)
    ctx.escalado_suspendido_por_mi = False
    ctx.emb.poner(comun.SERVICIO_WORKER, 1)
    minutos_purga = ctx.esperar_purga("V2")
    dlq = ctx.mensajes_dlq()
    exigir(dlq <= (ctx.dlq_inicial or 0), f"DLQ de purga: {ctx.dlq_inicial} → {dlq}")
    return (
        f"V2 procesado en {minutos:.1f} min · worker en 0 · DELETE V2 → 202, purga con {anotados} mensajes · "
        f"reconciliador: {reencolados[0].get('enviados')} reenviados ({despues} visibles) con los objetos aún en S3 · "
        f"worker de vuelta: V2 purgado en {minutos_purga:.1f} min, DLQ {dlq}"
    )


def main(argv: list[str] | None = None, ctx: Contexto | None = None) -> int:
    validador = comun.Validador(lote=LOTE, validacion="validation-4-1", entornos=("dev",), descripcion=__doc__)
    argumentos = validador.iniciar(argv)
    ctx = ctx or Contexto(argumentos.entorno)
    ctx.solo = argumentos.solo
    return validador.ejecutar(
        precondiciones=[
            ("P1", lambda: p1_credenciales(ctx)),
            ("P2", lambda: p2_lotes_y_hora(ctx)),
            ("P3", lambda: p3_login_y_desplegado(ctx)),
            ("P4", lambda: p4_recursos(ctx)),
            ("P5", lambda: p5_embedding(ctx)),
        ],
        preparacion=ctx.preparacion,
        comprobaciones=[
            ("C5b", lambda: c5b_imagenes(ctx)),
            ("C4a", lambda: c4a_renombrar(ctx)),
            ("C1a", lambda: c1a_propias_primeras(ctx)),
            ("C1b", lambda: c1b_borrado_sale_de_la_busqueda(ctx)),
            ("C4b", lambda: c4b_auditoria(ctx)),
            ("C5a", lambda: c5a_contrato_videos(ctx)),
            ("C2", lambda: c2_purga(ctx)),
            ("C3", lambda: c3_reconciliador(ctx)),
        ],
        manuales=[],
        limpieza=ctx.limpiar,
    )


if __name__ == "__main__":
    sys.exit(main())
