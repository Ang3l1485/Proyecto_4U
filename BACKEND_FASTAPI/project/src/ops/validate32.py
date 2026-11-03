"""BE-3.2 — Localización (`POST /v1/localize`). Con el conjunto de consulta de EMB-3.2 (`evaluacion/` del bucket) y el
dataset real del campus: error mediano ≤ 15 m en ≥ 10 puntos con dataset (C1), ninguna respuesta `alta` con más de
30 m de error (C2), p95 de `integrationLatency` ≤ 1 s (C3), ninguna foto de consulta en S3, en los logs ni en el disco
de `api` (C4), `sin_coincidencias` lejos del dataset (C5) y los umbrales calibrados en ARCHITECTURE §5.10 (C6).

Documento: BACKEND_FASTAPI/docs/validation/validation-3-2.md · criterios: BACKEND_FASTAPI/docs/PLAN.md §2.2.

    cd BACKEND_FASTAPI/project
    uv run --group ops python src/ops/validate32.py --entorno dev

Variables: AWS_PROFILE (obligatoria; lee `evaluacion/`, lanza la tarea de validación y usa ECS Exec, que necesita el
Session Manager plugin de la CLI de AWS) y VALIDACION_API_URL (opcional). No usa credenciales de admin. Solo `dev`.
Empieza antes de las 21:00 de Bogotá: `embedding` se apaga solo a las 22:00; si está apagado lo enciende (contrato de
infra §5.10) y al terminar lo deja como lo encontró. No crea datos de prueba: cada localización deja una fila anónima
en `eventos_localizacion` con `app_version = "validacion-32"`. Las fotos del conjunto se descargan y reducen en
memoria (nada en disco). Nunca imprime tokens ni URLs prefirmadas.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import os
import re
import shutil
import statistics
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import comun
from comun import ErrorConfiguracion, Falla, PrecondicionNoCumplida, exigir

LOTE = "BE-3.2"
INICIADA_POR = "validate32"
VERSION_VECTOR = "dinov2-vits14/pp-v1"  # EMBEDDING_VERSION_VECTOR (backend §5.10)
APP_VERSION = "validacion-32"  # `app_version` de los metadatos: reconoce las filas de eventos_localizacion
RUTA_LOCALIZAR = "/localize"
HORA_LIMITE = 21  # America/Bogota: empezar antes (P2)
RADIO_TIERRA_M = 6_371_008.8
DATASET_CERCA_M = 30.0  # punto con dataset: alguna imagen indexada a ≤ 30 m (C1)
LEJOS_M = 150.0  # punto fuera de cobertura: todas las imágenes a más de 150 m (C5)
PUNTOS_MIN = 10
ERROR_MEDIANO_MAX_M = 15.0
ERROR_ALTA_MAX_M = 30.0
FOTOS_POR_CONSULTA = 5  # LOC_MAX_FOTOS
LADO_MAX_PX = 1024  # como la app (§5.3): lado mayor 1024 px, calidad 85, sin EXIF
CALIDAD_JPEG = 85
LOC_MAX_BYTES_FOTO = 1_572_864
PETICIONES_C3 = 100
CALENTAMIENTO_C3 = 3
P95_MAX_MS = 1000
ESPERA_LOGS_C3_S = 120  # los access logs llegan a CloudWatch con retraso
REINTENTOS_LOGS_C3 = 3
PAUSA_LOGS_C3_S = 30.0
CPU_EMBEDDING, MEMORIA_EMBEDDING = "2048", "4096"  # infra ADR-INF-14
EVENTO_MAX_BYTES = 16_384
MARGEN_LOGS_S = 60  # C4b y C3 leen los logs desde 60 s antes (por si el reloj local va adelantado)
TAMANO_C4C = "+50k"
#: Rutas que C4c no cuenta: los logs del agente de ECS Exec, que corre dentro del contenedor (a verificar en dev).
EXCLUIDOS_C4C = ("/var/log/amazon/",)
TIMEOUT_EXEC_S = 120
PREFIJO_EVALUACION = "evaluacion/"
PATRON_VERSION = re.compile(r"\d{4}-\d{2}[a-z]")  # `version_conjunto` (embeddings §5.9)
LOG_APIGW = "/campus-locator/dev/apigw"
GRUPOS_LOG_C4B = (comun.LOG_API, LOG_APIGW, comun.LOG_EMBEDDING)
#: Las que envían localizaciones (necesitan `embedding`; C4a, si no se envió nada antes, envía las de C1).
COMPROBACIONES_QUE_LOCALIZAN = ("C1", "C2", "C3", "C4a", "C5")
PLAN_BACKEND = comun.RAIZ_CARPETA / "docs" / "PLAN.md"
PLAN_EMBEDDING = comun.RAIZ_REPO / "SERVICE_EMBEDDING" / "docs" / "PLAN.md"
PLAN_FRONTEND = comun.RAIZ_REPO / "FRONTEND_KOTLIN" / "docs" / "PLAN.md"
ARQUITECTURA = comun.RAIZ_CARPETA / "docs" / "ARCHITECTURE.md"
CAMBIOS = comun.RAIZ_CARPETA / "docs" / "CHANGELOG.md"
#: Versión de ARCHITECTURE que construyó BE-3.2 con los umbrales sin calibrar: C6 exige una posterior.
VERSION_SIN_CALIBRAR = (0, 12, 0)
#: Coordenadas (redondeadas a 5 decimales, ~1 m) de las imágenes que puede devolver la búsqueda: `procesada`, con
#: vector de la versión activa, de videos no borrados y que no son de validación. Una línea `lat|lng` por posición.
SQL_DATASET = (
    "SELECT DISTINCT round(i.lat::numeric, 5), round(i.lng::numeric, 5) FROM imagenes i "
    "JOIN videos v ON v.id = i.video_id JOIN embeddings e ON e.imagen_id = i.id "
    "WHERE e.version_vector = 'dinov2-vits14/pp-v1' AND i.estado = 'procesada' AND v.estado <> 'eliminado' "
    "AND v.nombre NOT LIKE 'validacion-%'"
)


def avisar(mensaje: str) -> None:
    print(mensaje, file=sys.stderr, flush=True)


def incluida(solo: str | None, id_: str) -> bool:
    """¿`--solo` incluye `id_`? (La regla de `comun.Validador`: `C4` incluye `C4a`, `C4b` y `C4c`.)"""
    if not solo:
        return True
    elegidas = {parte.strip() for parte in solo.split(",") if parte.strip()}
    criterio = re.match(r"([A-Z]+\d+)", id_)
    return id_ in elegidas or (criterio is not None and criterio.group(1) in elegidas)


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Círculo máximo con R = 6 371 008,8 m (la de `app.dominio.geo`, copiada: no se importa el backend)."""
    fi1, fi2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((fi2 - fi1) / 2) ** 2 + math.cos(fi1) * math.cos(fi2) * math.sin(math.radians(lng2 - lng1) / 2) ** 2
    return 2 * RADIO_TIERRA_M * math.asin(min(1.0, math.sqrt(a)))


def preparar_foto(datos: bytes) -> bytes:
    """Como la app (§5.3) y la herramienta de embeddings (`preparar_foto`): orientación EXIF aplicada, RGB, lado mayor ≤
    1024 px (Lanczos, sin ampliar), JPEG calidad 85 y sin EXIF. Más de 1,5 MB → `Falla`."""
    from PIL import Image, ImageOps

    try:
        with Image.open(io.BytesIO(datos)) as original:
            imagen = ImageOps.exif_transpose(original).convert("RGB")
    except Exception as exc:
        raise Falla(f"una foto del conjunto no se pudo abrir ({type(exc).__name__})") from None
    imagen.thumbnail((LADO_MAX_PX, LADO_MAX_PX), Image.Resampling.LANCZOS)
    salida = io.BytesIO()
    imagen.save(salida, format="JPEG", quality=CALIDAD_JPEG)
    preparada = salida.getvalue()
    exigir(len(preparada) <= LOC_MAX_BYTES_FOTO, f"una foto reducida pesa {len(preparada)} bytes (> 1,5 MB)")
    return preparada


def md5(datos: bytes) -> str:
    return hashlib.md5(datos, usedforsecurity=False).hexdigest()


def _error_aws(exc: Exception, que: str) -> Exception:
    if comun.es_acceso_denegado(exc):
        return ErrorConfiguracion(f"sin permiso para {que} ({comun.codigo_error_aws(exc)})")
    return Falla(f"{que}: {type(exc).__name__} {comun.codigo_error_aws(exc)}".strip())


def _leer(ruta: Any) -> str:
    try:
        return ruta.read_text(encoding="utf-8")
    except OSError:
        raise ErrorConfiguracion(f"no se pudo leer {ruta}") from None


def percentil(valores: list[float], p: float) -> float:
    """Rango más cercano: el valor en la posición ⌈p/100 · n⌉ de los n ordenados (con 100 valores, p95 = el 95.º)."""
    ordenados = sorted(valores)
    return ordenados[max(1, math.ceil(p / 100 * len(ordenados))) - 1]


# --- Conjunto de evaluación -----------------------------------------------------------------------------------------
@dataclass
class Punto:
    id: str
    lat: float
    lng: float
    fotos: list[tuple[str, float | None]] = field(default_factory=list)  # (archivo, rumbo), en el orden de puntos.json
    distancia_m: float = math.inf  # a la imagen indexada más cercana (P5)


@dataclass(frozen=True)
class Consulta:
    punto: Punto
    fotos: list[bytes]
    rumbos: list[float | None]


@dataclass(frozen=True)
class Respuesta:
    """Una localización enviada por el validador y lo que se midió de ella."""

    que: str  # C1, C3 o C5
    punto: str
    codigo: int
    cuerpo: dict[str, Any]
    error_m: float  # haversine a la coordenada real; infinito con `sin_coincidencias`
    request_id: str | None
    cliente_ms: int | None

    @property
    def nivel(self) -> str | None:
        return self.cuerpo.get("nivel")


def puntos_de(datos: Any) -> list[Punto]:
    """Los puntos de `puntos.json` (embeddings §5.9) con sus fotos; solo lo que usa este validador (`id`, `lat`,
    `lng`; `archivo`, `punto`, `rumbo`). Algo que no tenga esa forma → `PrecondicionNoCumplida` (EMB-3.2)."""
    try:
        puntos = {p["id"]: Punto(str(p["id"]), float(p["lat"]), float(p["lng"])) for p in datos["puntos"]}
        for foto in datos["fotos"]:
            rumbo = foto.get("rumbo")
            puntos[foto["punto"]].fotos.append((str(foto["archivo"]), None if rumbo is None else float(rumbo)))
    except (KeyError, TypeError, ValueError) as exc:
        raise PrecondicionNoCumplida(f"EMB-3.2: puntos.json no tiene la forma de embeddings §5.9 ({exc!r})") from None
    return list(puntos.values())


# --- Contexto ------------------------------------------------------------------------------------------------------
class Contexto:
    def __init__(self, entorno: str = "dev") -> None:
        self.entorno = entorno
        self.sesion: Any = None
        self.api: comun.ClienteApi | None = None
        self.backend: comun.EntornoBackend | None = None
        self.emb: comun.EmbeddingDev | None = None
        self.s3: Any = None
        self.logs: Any = None
        self.ecs: Any = None
        self.sqs: Any = None
        self.bucket: str | None = None
        self.dormir: Callable[[float], None] = time.sleep
        self.ahora: Callable[[], datetime] = lambda: datetime.now(UTC)
        self.http: Any = None
        self.hay_plugin: Callable[[], bool] = lambda: bool(
            shutil.which("session-manager-plugin") and shutil.which("aws")
        )
        self.exec: Callable[[str, str], str] = self._exec_aws
        self.solo: str | None = None
        self.inicio: datetime | None = None
        self._outputs: dict[str, Any] | None = None
        self.version_conjunto: str | None = None
        self.puntos: list[Punto] = []
        self.coordenadas: list[tuple[float, float]] = []
        self._preparadas: dict[str, bytes] = {}
        self.respuestas: dict[str, list[Respuesta]] = {"C1": [], "C3": [], "C5": []}
        self.hechas: set[str] = set()  # lotes de peticiones ya intentados (no se repiten con --solo)
        self.inicio_c3: datetime | None = None  # justo antes de las 100 peticiones medidas de C3
        self.md5_enviados: set[str] = set()
        self.estaba_encendido: bool | None = None
        self.encendido_por_mi = False

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

    def listo_en_api(self) -> bool:
        return comun.embedding_en_api(self.api) == "ok"

    def asegurar_embedding(self) -> str:
        datos = self.emb.servicio(comun.SERVICIO_EMBEDDING)
        if int(datos.get("desiredCount", 0)) >= 1 and self.listo_en_api():
            self.emb.latido()
            return "ya encendido (latido publicado)"
        segundos = self.emb.encender(self.listo_en_api)
        return f"encendido en {segundos:.0f} s"

    def _exec_aws(self, tarea: str, comando: str) -> str:
        """`aws ecs execute-command --interactive` en el contenedor `app` de `tarea`: la salida (stdout y stderr)."""
        proceso = comun.ejecutar_proceso(
            [
                "aws", "ecs", "execute-command", "--region", comun.REGION_AWS, "--cluster", comun.CLUSTER,
                "--task", tarea, "--container", comun.CONTENEDOR, "--interactive", "--command", comando,
            ],
            timeout=TIMEOUT_EXEC_S,
        )  # fmt: skip
        if proceso.returncode != 0:
            lineas = [linea.strip() for linea in (proceso.stderr or proceso.stdout).splitlines() if linea.strip()]
            raise Falla(f"ecs execute-command terminó con {proceso.returncode}: {(lineas or ['sin salida'])[-1][:200]}")
        return proceso.stdout + "\n" + proceso.stderr

    # -- conjunto ----------------------------------------------------------------------------------------------------
    def foto(self, archivo: str) -> bytes:
        """La foto `evaluacion/<version>/<archivo>`, descargada y reducida como la app (en memoria, una vez)."""
        if archivo not in self._preparadas:
            clave = f"{PREFIJO_EVALUACION}{self.version_conjunto}/{archivo}"
            try:
                datos = self.s3.get_object(Bucket=self.bucket, Key=clave)["Body"].read()
            except Exception as exc:
                raise _error_aws(exc, f"s3 get-object {clave}") from None
            self._preparadas[archivo] = preparar_foto(datos)
        return self._preparadas[archivo]

    def consulta(self, punto: Punto) -> Consulta:
        elegidas = punto.fotos[:FOTOS_POR_CONSULTA]
        return Consulta(punto, [self.foto(a) for a, _ in elegidas], [r for _, r in elegidas])

    def con_dataset(self) -> list[Punto]:
        return [p for p in self.puntos if p.fotos and p.distancia_m <= DATASET_CERCA_M]

    def lejanos(self) -> list[Punto]:
        return [p for p in self.puntos if p.fotos and p.distancia_m > LEJOS_M]

    # -- localizar ---------------------------------------------------------------------------------------------------
    def localizar(self, consulta: Consulta, que: str, *, guardar: bool = True) -> Respuesta:
        files: list[Any] = [("fotos", (f"{i}.jpg", f, "image/jpeg")) for i, f in enumerate(consulta.fotos)]
        metadatos = {"rumbos": consulta.rumbos, "origen": "escaneo", "app_version": APP_VERSION}
        files.append(("metadatos", (None, json.dumps(metadatos).encode("utf-8"), "application/json")))
        self.md5_enviados.update(md5(f) for f in consulta.fotos)
        r = self.api.pedir("POST", RUTA_LOCALIZAR, files=files)
        cuerpo: dict[str, Any] = {}
        if r.status_code == 200:
            try:
                cuerpo = r.json()
            except ValueError:
                cuerpo = {}
        error = math.inf
        posicion = cuerpo.get("posicion")
        if cuerpo.get("resultado") == "ok" and isinstance(posicion, dict):
            try:
                error = haversine_m(float(posicion["lat"]), float(posicion["lng"]), consulta.punto.lat,
                                    consulta.punto.lng)  # fmt: skip
            except (KeyError, TypeError, ValueError):
                error = math.inf
        respuesta = Respuesta(
            que=que,
            punto=consulta.punto.id,
            codigo=r.status_code,
            cuerpo=cuerpo,
            error_m=error,
            request_id=(r.headers or {}).get("apigw-requestid"),
            cliente_ms=self.api.ultima_duracion_ms,
        )
        if guardar:
            self.respuestas[que].append(respuesta)
        exigir(
            r.status_code == 200,
            f"{que}: POST /v1/localize del punto {consulta.punto.id} → {comun.describir_respuesta(r)}, se esperaba 200",
        )
        exigir(
            cuerpo.get("resultado") in ("ok", "sin_coincidencias"),
            f"{que}: el punto {consulta.punto.id} respondió resultado = {cuerpo.get('resultado')!r}",
        )
        return respuesta

    def asegurar_c1(self) -> list[Respuesta]:
        if "C1" not in self.hechas:
            self.hechas.add("C1")
            for punto in self.con_dataset():
                self.localizar(self.consulta(punto), "C1")
        return self.respuestas["C1"]

    def consultas_c3(self) -> list[Consulta]:
        return [c for c in (self.consulta(p) for p in self.con_dataset()) if len(c.fotos) == FOTOS_POR_CONSULTA]

    def asegurar_c3(self) -> list[Respuesta]:
        """Las 3 de calentamiento y las 100 medidas (de una en una, recorriendo los puntos de C1 con 5 fotos)."""
        if "C3" not in self.hechas:
            self.hechas.add("C3")
            consultas = self.consultas_c3()
            exigir(consultas, "C3: ningún punto con dataset tiene 5 fotos")
            for i in range(CALENTAMIENTO_C3):
                self.localizar(consultas[i % len(consultas)], "C3", guardar=False)
            self.inicio_c3 = self.ahora()
            for i in range(PETICIONES_C3):
                self.localizar(consultas[i % len(consultas)], "C3")
        return self.respuestas["C3"]

    def latencias_apigw(self, ids: set[str], desde: datetime) -> dict[str, int]:
        """`requestId → integrationLatency` (ms) de los access logs de API Gateway (infra §5.10; valores en texto)."""
        encontradas: dict[str, int] = {}
        for mensaje in comun.mensajes_log(self.logs, LOG_APIGW, desde - timedelta(seconds=MARGEN_LOGS_S)):
            try:
                linea = json.loads(mensaje)
            except ValueError:
                continue
            if isinstance(linea, dict) and linea.get("requestId") in ids:
                valor = str(linea.get("integrationLatency", ""))
                if valor.isdigit():
                    encontradas[linea["requestId"]] = int(valor)
        return encontradas

    # -- limpieza ----------------------------------------------------------------------------------------------------
    def _restaurar_embedding(self) -> str:
        if self.emb is None or self.estaba_encendido is None:
            return "embedding sin tocar"
        if self.encendido_por_mi:
            self.emb.apagar()
            return "embedding apagado (lo encendió el validador)"
        if self.estaba_encendido:
            if int(self.emb.servicio(comun.SERVICIO_EMBEDDING).get("desiredCount", 0)) < 1:
                self.emb.encender(self.listo_en_api)
                return "embedding vuelto a encender (estaba encendido)"
            return "embedding sigue encendido (como estaba)"
        return "embedding sin tocar"

    def limpiar(self) -> str:
        partes: list[str] = []
        try:
            try:
                partes.append(self._restaurar_embedding())
            except Exception as exc:
                raise Falla(
                    f"embedding NO quedó como estaba ({comun._resumen(exc)}): apágalo a mano (§5 paso 6)"
                ) from None
            enviadas = sum(len(v) for v in self.respuestas.values())
            partes.append(f"{len(self._preparadas)} fotos del conjunto descartadas de la memoria")
            partes.append(f"{enviadas} localizaciones medidas (filas app_version = {APP_VERSION})")
            return " · ".join(partes)
        finally:
            self._preparadas.clear()
            if self.api is not None:
                self.api.cerrar()


# --- Precondiciones ------------------------------------------------------------------------------------------------
def p1_credenciales(ctx: Contexto) -> str:
    ctx.sesion = comun.sesion_aws()
    arn = comun.verificar_cuenta(ctx.sesion)
    ctx.emb = comun.EmbeddingDev(ctx.sesion, dormir=ctx.dormir, reloj=ctx.ahora, avisar=avisar)
    detalle = f"cuenta {comun.CUENTA_AWS} ({arn.rsplit('/', 1)[-1]})"
    if incluida(ctx.solo, "C4c"):
        if not ctx.hay_plugin():
            raise ErrorConfiguracion(
                "falta `aws` o el Session Manager plugin (`session-manager-plugin`) en el PATH: C4c usa ECS Exec"
            )
        detalle += " · aws y session-manager-plugin en el PATH"
    return detalle


def p2_lotes_y_hora(ctx: Contexto) -> str:
    import httpx

    ctx.inicio = ctx.ahora()
    plan = _leer(PLAN_BACKEND)
    for lote in ("BE-2.2", "BE-2.4", "BE-3.1"):
        if not comun.lote_hecho(plan, lote):
            raise PrecondicionNoCumplida(f"{lote} no está «Hecho» en BACKEND_FASTAPI/docs/PLAN.md §3")
    ahora = comun.hora_bogota(ctx.ahora())
    if ahora.hour >= HORA_LIMITE:
        raise ErrorConfiguracion(
            f"son las {ahora:%H:%M} en Bogotá: empieza antes de las {HORA_LIMITE}:00 (embedding se apaga a las 22:00)"
        )
    url = comun.url_api(None if os.environ.get("VALIDACION_API_URL", "").strip() else ctx.outputs())
    ctx.preparar(url)
    try:
        listo = ctx.api.pedir("GET", "/health/ready")
    except httpx.HTTPError as exc:
        raise PrecondicionNoCumplida(f"BE-1.1: GET /v1/health/ready no respondió ({type(exc).__name__})") from None
    if listo.status_code != 200 or listo.json().get("db") != "ok":
        raise PrecondicionNoCumplida(f"BE-1.2: GET /v1/health/ready respondió {comun.describir_respuesta(listo)}")
    return (
        f'BE-2.2, BE-2.4 y BE-3.1 «Hecho» · {url} · /v1/health/ready → "db": "ok" · {ahora:%H:%M} en Bogotá '
        f"(antes de las {HORA_LIMITE}:00)"
    )


def p3_desplegado(ctx: Contexto) -> str:
    # Sin parte `fotos`: no llama a embeddings ni escribe en eventos_localizacion. Antes de BE-3.2, la ruta no existe.
    r = ctx.api.pedir("POST", RUTA_LOCALIZAR, files=[("otra", (None, b"validacion-sin-fotos", "text/plain"))])
    if r.status_code == 404:
        raise PrecondicionNoCumplida("BE-3.2 sin desplegar: POST /v1/localize respondió 404")
    if not (r.status_code == 400 and comun.codigo_error(r) == "FOTOS_INVALIDAS"):
        raise PrecondicionNoCumplida(f"POST /v1/localize sin fotos respondió {comun.describir_respuesta(r)}")
    lugares = ctx.api.pedir("GET", comun.RUTA_LUGARES)
    if lugares.status_code != 200:
        raise PrecondicionNoCumplida(f"BE-3.1: GET /v1/places respondió {comun.describir_respuesta(lugares)}")
    total = lugares.json().get("total")
    detalle = f"POST /v1/localize sin fotos → 400 FOTOS_INVALIDAS · GET /v1/places → 200 ({total} lugares)"
    if incluida(ctx.solo, "C4c"):
        ctx.ecs = ctx.sesion.client("ecs")
        try:
            servicios = ctx.ecs.describe_services(cluster=comun.CLUSTER, services=[comun.SERVICIO_API])["services"]
        except Exception as exc:
            raise _error_aws(exc, "ecs describe-services api") from None
        if not servicios or not servicios[0].get("enableExecuteCommand"):
            raise PrecondicionNoCumplida("INF-1.3: el servicio api no tiene ECS Exec (enableExecuteCommand)")
        detalle += " · api con ECS Exec"
    return detalle


def p4_conjunto(ctx: Contexto) -> str:
    texto = _leer(PLAN_EMBEDDING)
    for lote in ("EMB-3.1", "EMB-3.2"):
        if not comun.lote_hecho(texto, lote):
            raise PrecondicionNoCumplida(f"{lote} no está «Hecho» en SERVICE_EMBEDDING/docs/PLAN.md §3")
    outputs = ctx.outputs()
    if not outputs.get("bucket_dataset"):
        raise PrecondicionNoCumplida("INF-1.2: falta el output bucket_dataset")
    ctx.bucket = outputs["bucket_dataset"]
    ctx.s3, ctx.logs = ctx.sesion.client("s3"), ctx.sesion.client("logs")
    try:
        prefijos = ctx.s3.list_objects_v2(Bucket=ctx.bucket, Prefix=PREFIJO_EVALUACION, Delimiter="/")
    except Exception as exc:
        raise _error_aws(exc, f"s3 list-objects-v2 {PREFIJO_EVALUACION}") from None
    versiones = sorted(
        v
        for v in (p["Prefix"][len(PREFIJO_EVALUACION) :].rstrip("/") for p in prefijos.get("CommonPrefixes", []))
        if PATRON_VERSION.fullmatch(v)
    )
    if not versiones:
        raise PrecondicionNoCumplida("EMB-3.2: no hay ningún conjunto en evaluacion/<AAAA-MM><letra>/")
    ctx.version_conjunto = versiones[-1]
    clave = f"{PREFIJO_EVALUACION}{ctx.version_conjunto}/puntos.json"
    try:
        datos = json.loads(ctx.s3.get_object(Bucket=ctx.bucket, Key=clave)["Body"].read())
    except ValueError:
        raise PrecondicionNoCumplida(f"EMB-3.2: {clave} no es JSON") from None
    except Exception as exc:
        if comun.codigo_error_aws(exc) in {"NoSuchKey", "404"}:
            raise PrecondicionNoCumplida(f"EMB-3.2: falta {clave}") from None
        raise _error_aws(exc, f"s3 get-object {clave}") from None
    puntos = puntos_de(datos)
    existentes = set(comun.claves_s3(ctx.s3, ctx.bucket, f"{PREFIJO_EVALUACION}{ctx.version_conjunto}/fotos/"))
    prefijo = f"{PREFIJO_EVALUACION}{ctx.version_conjunto}/"
    faltan = 0
    for punto in puntos:
        todas = punto.fotos
        punto.fotos = [(a, r) for a, r in todas if prefijo + a in existentes]
        faltan += len(todas) - len(punto.fotos)
    ctx.puntos = [p for p in puntos if p.fotos]
    if len(ctx.puntos) < PUNTOS_MIN:
        raise PrecondicionNoCumplida(
            f"EMB-3.2: {clave} tiene {len(ctx.puntos)} puntos con fotos en S3, se necesitan ≥ {PUNTOS_MIN}"
        )
    fotos = sum(len(p.fotos) for p in ctx.puntos)
    aviso = f" ({faltan} fotos de puntos.json no están en S3)" if faltan else ""
    return (
        f"EMB-3.1 y EMB-3.2 «Hecho» · conjunto {ctx.version_conjunto}: {len(ctx.puntos)} puntos, {fotos} fotos{aviso}"
    )


def p5_dataset(ctx: Contexto) -> str:
    from botocore.exceptions import ClientError

    if not comun.lote_hecho(_leer(PLAN_FRONTEND), "FE-2.1"):
        raise PrecondicionNoCumplida("FE-2.1 no está «Hecho» en FRONTEND_KOTLIN/docs/PLAN.md §3 (sin dataset real)")
    comun.red_tareas(ctx.outputs())
    try:
        ctx.backend.imagen(comun.FAMILIA_VALIDACION)
    except ClientError as exc:
        if comun.es_acceso_denegado(exc):
            raise ErrorConfiguracion("sin permiso para describir la tarea de validación") from None
        raise PrecondicionNoCumplida(
            f"INF-1.3: falta {comun.FAMILIA_VALIDACION} ({comun.codigo_error_aws(exc)})"
        ) from None
    coordenadas = []
    for linea in ctx.backend.sql(SQL_DATASET):
        partes = linea.strip().split("|")
        if len(partes) == 2:
            try:
                coordenadas.append((float(partes[0]), float(partes[1])))
            except ValueError:
                continue
    if not coordenadas:
        raise PrecondicionNoCumplida("FE-2.1: no hay imágenes indexadas del dataset real (procesada, sin validacion-)")
    ctx.coordenadas = coordenadas
    for punto in ctx.puntos:
        punto.distancia_m = min(haversine_m(punto.lat, punto.lng, lat, lng) for lat, lng in coordenadas)
    con, lejos = len(ctx.con_dataset()), len(ctx.lejanos())
    return (
        f"FE-2.1 «Hecho» · {len(coordenadas)} posiciones indexadas · puntos con dataset (≤ 30 m): {con} · "
        f"fuera de cobertura (> 150 m): {lejos} · intermedios: {len(ctx.puntos) - con - lejos}"
    )


def p6_embedding(ctx: Contexto) -> str:
    if not any(incluida(ctx.solo, id_) for id_ in COMPROBACIONES_QUE_LOCALIZAN):
        return "no hace falta: ninguna comprobación incluida localiza (embedding sin tocar)"
    datos = ctx.emb.servicio(comun.SERVICIO_EMBEDDING)
    ctx.estaba_encendido = int(datos.get("desiredCount", 0)) >= 1
    ctx.encendido_por_mi = not ctx.estaba_encendido  # se marca antes de encender: la limpieza lo apaga igual
    try:
        detalle = ctx.asegurar_embedding()
    except Falla as exc:
        raise PrecondicionNoCumplida(f"EMB-2.1/INF-2.1: embedding no quedó listo: {exc}") from None
    return f'embedding {detalle} · /v1/health/ready → "embedding": "ok"'


# --- Comprobaciones ------------------------------------------------------------------------------------------------
def _niveles(respuestas: list[Respuesta]) -> str:
    cuenta = {n: sum(r.nivel == n for r in respuestas) for n in ("alta", "media", "baja")}
    sin = sum(r.cuerpo.get("resultado") == "sin_coincidencias" for r in respuestas)
    return f"alta/media/baja/sin_coincidencias = {cuenta['alta']}/{cuenta['media']}/{cuenta['baja']}/{sin}"


def _m(valor: float) -> str:
    return "∞" if math.isinf(valor) else f"{valor:.1f}"


def c1_error_mediano(ctx: Contexto) -> str:
    puntos = ctx.con_dataset()
    exigir(len(puntos) >= PUNTOS_MIN, f"{len(puntos)} puntos con dataset (≤ 30 m), se necesitan ≥ {PUNTOS_MIN}")
    respuestas = ctx.asegurar_c1()
    errores = [r.error_m for r in respuestas]
    mediana = statistics.median(errores)
    con_lugar = sum(bool(r.cuerpo.get("lugar_cercano")) for r in respuestas)
    detalle = (
        f"{len(respuestas)} puntos con dataset · error mediano {_m(mediana)} m (máx. {ERROR_MEDIANO_MAX_M:g}) · "
        f"p90 {_m(percentil(errores, 90))} m · {_niveles(respuestas)} · con lugar_cercano: {con_lugar}"
    )
    exigir(mediana <= ERROR_MEDIANO_MAX_M, detalle)
    return detalle


def c3_latencia(ctx: Contexto) -> str:
    from botocore.exceptions import ClientError

    servicio = ctx.emb.servicio(comun.SERVICIO_EMBEDDING)
    exigir(int(servicio.get("runningCount", 0)) == 1, f"embedding con runningCount = {servicio.get('runningCount')}")
    ecs = ctx.ecs or ctx.sesion.client("ecs")
    try:
        definicion = ecs.describe_task_definition(taskDefinition=servicio["taskDefinition"])["taskDefinition"]
    except (ClientError, KeyError) as exc:
        raise Falla(f"no se pudo describir la tarea de embedding ({type(exc).__name__})") from None
    tamano = (str(definicion.get("cpu")), str(definicion.get("memory")))
    exigir(tamano == (CPU_EMBEDDING, MEMORIA_EMBEDDING), f"embedding con cpu/memory = {tamano}, se esperaba 2048/4096")
    visibles, en_vuelo = comun.mensajes_cola(ctx.sqs or ctx.sesion.client("sqs"), ctx.outputs()["sqs_ingesta_url"])
    exigir(visibles + en_vuelo == 0, f"ingesta tiene {visibles} mensajes visibles y {en_vuelo} en vuelo: el worker "
                                     "competiría por embedding")  # fmt: skip
    respuestas = ctx.asegurar_c3()
    exigir(len(respuestas) == PETICIONES_C3, f"solo {len(respuestas)} de {PETICIONES_C3} peticiones dieron 200")
    ids = {r.request_id for r in respuestas if r.request_id}
    exigir(len(ids) == PETICIONES_C3, f"{PETICIONES_C3 - len(ids)} respuestas sin encabezado apigw-requestid distinto")
    ctx.dormir(ESPERA_LOGS_C3_S)
    latencias: dict[str, int] = {}
    for intento in range(REINTENTOS_LOGS_C3):
        latencias = ctx.latencias_apigw(ids, ctx.inicio_c3 or ctx.ahora())
        if len(latencias) == len(ids) or intento == REINTENTOS_LOGS_C3 - 1:
            break
        ctx.dormir(PAUSA_LOGS_C3_S)
    exigir(len(latencias) == len(ids), f"{len(ids) - len(latencias)} de {len(ids)} peticiones sin línea en {LOG_APIGW}")
    valores = list(latencias.values())
    p95 = percentil(valores, 95)
    api_ms = [r.cuerpo.get("latencia_ms") for r in respuestas if isinstance(r.cuerpo.get("latencia_ms"), int)]
    cliente = [r.cliente_ms for r in respuestas if r.cliente_ms is not None]
    mediana_api = statistics.median(api_ms) if api_ms else "—"
    p95_cliente = percentil(cliente, 95) if cliente else "—"
    detalle = (
        f"embedding 2048/4096 con 1 tarea · ingesta vacía · {PETICIONES_C3} × 200 · integrationLatency p50 "
        f"{percentil(valores, 50)} ms, p95 {p95} ms (máx. {P95_MAX_MS}) · latencia_ms (API) mediana {mediana_api} · "
        f"p95 en el cliente {p95_cliente} ms (no cuenta)"
    )
    exigir(p95 <= P95_MAX_MS, detalle)
    return detalle


def c5_sin_cobertura(ctx: Contexto) -> str:
    puntos = ctx.lejanos()
    exigir(puntos, "conjunto sin puntos fuera de cobertura (todas las imágenes a más de 150 m)")
    if "C5" not in ctx.hechas:
        ctx.hechas.add("C5")
        for punto in puntos:
            ctx.localizar(ctx.consulta(punto), "C5")
    respuestas = ctx.respuestas["C5"]
    for r in respuestas:
        exigir(
            r.cuerpo.get("resultado") == "sin_coincidencias"
            and r.cuerpo.get("confianza") == 0
            and r.cuerpo.get("posicion") is None,
            f"el punto {r.punto} (a {_m(next(p.distancia_m for p in puntos if p.id == r.punto))} m del dataset) dio "
            f"resultado = {r.cuerpo.get('resultado')!r}, confianza = {r.cuerpo.get('confianza')!r}",
        )
    return f"{len(respuestas)} puntos fuera de cobertura → 200 sin_coincidencias, confianza 0 y posicion null"


def c2_alta_sin_error_grande(ctx: Contexto) -> str:
    respuestas = [*ctx.asegurar_c1(), *ctx.asegurar_c3()]
    altas = [r for r in respuestas if r.nivel == "alta"]
    malas = sorted((r for r in altas if r.error_m > ERROR_ALTA_MAX_M), key=lambda r: -r.error_m)
    maximo = max((r.error_m for r in altas), default=0.0)
    exigir(
        not malas,
        f"{len(malas)} respuestas de nivel alta con error > {ERROR_ALTA_MAX_M:g} m, p. ej. punto {malas[0].punto} "
        f"({malas[0].que}) a {_m(malas[0].error_m)} m"
        if malas
        else "",
    )
    return (
        f"{len(altas)} respuestas de nivel alta (de {len(respuestas)}: C1 y C3) · error máximo {_m(maximo)} m "
        f"(máx. {ERROR_ALTA_MAX_M:g})"
    )


def _etags_bucket(s3: Any, bucket: str) -> dict[str, str]:
    """`ETag` (sin comillas, en minúsculas) → clave, de todo el bucket (`list-objects-v2` paginado)."""
    etags: dict[str, str] = {}
    try:
        for pagina in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=""):
            for objeto in pagina.get("Contents", []):
                etags[str(objeto.get("ETag", "")).strip('"').lower()] = objeto["Key"]
    except Exception as exc:
        raise _error_aws(exc, f"s3 list-objects-v2 {bucket}") from None
    return etags


def c4a_nada_en_s3(ctx: Contexto) -> str:
    if not ctx.md5_enviados:
        ctx.asegurar_c1()  # con --solo C4: algo que buscar
    etags = _etags_bucket(ctx.s3, ctx.bucket)
    iguales = sorted(etags[m] for m in ctx.md5_enviados if m in etags)
    exigir(not iguales, f"{len(iguales)} fotos de consulta están en el bucket, p. ej. {', '.join(iguales[:3])}")
    return f"{len(ctx.md5_enviados)} fotos enviadas · {len(etags)} objetos en el bucket · ningún ETag coincide"


def c4b_logs(ctx: Contexto) -> str:
    desde = (ctx.inicio or ctx.ahora()) - timedelta(seconds=MARGEN_LOGS_S)
    resumen = []
    for grupo in GRUPOS_LOG_C4B:
        mensajes = comun.mensajes_log(ctx.logs, grupo, desde)
        con_jpeg = sum("/9j/" in m for m in mensajes)
        grandes = sum(len(m.encode("utf-8")) > EVENTO_MAX_BYTES for m in mensajes)
        exigir(not con_jpeg, f"{grupo}: {con_jpeg} eventos contienen /9j/ (un JPEG en base64)")
        exigir(not grandes, f"{grupo}: {grandes} eventos pesan más de {EVENTO_MAX_BYTES // 1024} KB")
        resumen.append(f"{len(mensajes)} en {grupo.rsplit('/', 1)[-1]}")
    return f"eventos desde el inicio: {', '.join(resumen)}; ninguno con /9j/ ni de más de 16 KB"


def c4c_disco(ctx: Contexto) -> str:
    ecs = ctx.ecs or ctx.sesion.client("ecs")
    try:
        tareas = ecs.list_tasks(cluster=comun.CLUSTER, serviceName=comun.SERVICIO_API, desiredStatus="RUNNING")
    except Exception as exc:
        raise _error_aws(exc, "ecs list-tasks api") from None
    arns = tareas.get("taskArns", [])
    exigir(arns, "el servicio api no tiene tareas en marcha")
    desde = int((ctx.inicio or ctx.ahora()).timestamp())
    comando = f"find / -xdev -type f -newermt @{desde} -size {TAMANO_C4C}"
    for arn in arns:
        salida = ctx.exec(arn, comando)
        rutas = [linea.strip() for linea in salida.splitlines() if linea.strip().startswith("/")]
        rutas = [r for r in rutas if not r.startswith(EXCLUIDOS_C4C)]
        if rutas:
            raise Falla(f"tarea {arn.rsplit('/', 1)[-1]}: {len(rutas)} archivos > 50 KB nuevos, p. ej. {rutas[0]}")
    return f"{len(arns)} tarea(s) de api: `{comando}` sin archivos (salvo {', '.join(EXCLUIDOS_C4C)})"


_VERSION = re.compile(r"Versión del documento \| \*\*(\d+)\.(\d+)\.(\d+)\*\*")
_ENTRADA = re.compile(r"^## \[(\d+)\.(\d+)\.(\d+)\]", re.M)


def c6_umbrales_registrados(ctx: Contexto) -> str:
    arquitectura, cambios = _leer(ARQUITECTURA), _leer(CAMBIOS)
    try:
        seccion = arquitectura[arquitectura.index("### 5.10 ") : arquitectura.index("### 5.11 ")]
    except ValueError:
        raise Falla("ARCHITECTURE.md sin §5.10 o §5.11") from None
    filas = [f for f in seccion.splitlines() if f.startswith(("| `LOC_SIM_MIN`", "| `LOC_NIVEL_ALTA_MIN`"))]
    exigir(len(filas) == 2, f"§5.10: {len(filas)} filas de LOC_SIM_MIN y de los cortes de nivel, se esperaban 2")
    iniciales = [f.split("|")[1].strip() for f in filas if "inicial" in f.lower()]
    exigir(not iniciales, f"§5.10 todavía dice «Iniciales» en {' y '.join(iniciales)}: falta calibrar (EMB-3.2)")
    encabezado = _VERSION.search(arquitectura)
    exigir(encabezado, "ARCHITECTURE.md sin «Versión del documento»")
    version = tuple(int(x) for x in encabezado.groups())
    exigir(version > VERSION_SIN_CALIBRAR, f"ARCHITECTURE {'.'.join(map(str, version))}: no es posterior a 0.12.0")
    marcas = list(_ENTRADA.finditer(cambios))
    calibraciones = []
    for i, marca in enumerate(marcas):
        entrada = cambios[marca.start() : marcas[i + 1].start() if i + 1 < len(marcas) else len(cambios)]
        lote = next((linea for linea in entrada.splitlines() if "Lote que la motivó" in linea), "")
        numero = tuple(int(x) for x in marca.groups())
        if numero > VERSION_SIN_CALIBRAR and "BE-3.2" in lote and "calibr" in entrada.lower():
            calibraciones.append(".".join(map(str, numero)))
    exigir(calibraciones, "CHANGELOG sin una entrada posterior a 0.12.0 de BE-3.2 con la calibración")
    return f"§5.10 sin «Iniciales» · ARCHITECTURE {'.'.join(map(str, version))} · CHANGELOG {calibraciones[0]} (BE-3.2)"


def main(argv: list[str] | None = None, ctx: Contexto | None = None) -> int:
    validador = comun.Validador(lote=LOTE, validacion="validation-3-2", entornos=("dev",), descripcion=__doc__)
    argumentos = validador.iniciar(argv)
    ctx = ctx or Contexto(argumentos.entorno)
    ctx.solo = argumentos.solo
    return validador.ejecutar(
        precondiciones=[
            ("P1", lambda: p1_credenciales(ctx)),
            ("P2", lambda: p2_lotes_y_hora(ctx)),
            ("P3", lambda: p3_desplegado(ctx)),
            ("P4", lambda: p4_conjunto(ctx)),
            ("P5", lambda: p5_dataset(ctx)),
            ("P6", lambda: p6_embedding(ctx)),
        ],
        comprobaciones=[
            ("C1", lambda: c1_error_mediano(ctx)),
            ("C3", lambda: c3_latencia(ctx)),
            ("C5", lambda: c5_sin_cobertura(ctx)),
            ("C2", lambda: c2_alta_sin_error_grande(ctx)),
            ("C4a", lambda: c4a_nada_en_s3(ctx)),
            ("C4b", lambda: c4b_logs(ctx)),
            ("C4c", lambda: c4c_disco(ctx)),
            ("C6", lambda: c6_umbrales_registrados(ctx)),
        ],
        manuales=[],
        limpieza=ctx.limpiar,
    )


if __name__ == "__main__":
    sys.exit(main())
