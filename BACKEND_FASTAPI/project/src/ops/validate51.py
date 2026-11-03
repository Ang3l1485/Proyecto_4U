"""BE-5.1 — Corrección visual (`POST /v1/localize/frame`). Una foto igual a una del dataset, con la posición previa
cerca, da esa ubicación (C1); con la posición previa lejos no la da aunque haya otras fotos en el radio (C2); `radio_m`
limita la búsqueda (C3); las peticiones mal formadas dan los errores de §5.3 (C4); cada `200` deja su fila en
`eventos_localizacion` con `origen = frame` y los errores ninguna (C5); el servidor responde en ≤ 1 s (C6).

Documento: BACKEND_FASTAPI/docs/validation/validation-5-1.md · criterios: BACKEND_FASTAPI/docs/PLAN.md §2.2.

    cd BACKEND_FASTAPI/project
    uv run --group ops python src/ops/validate51.py --entorno dev

Variables: AWS_PROFILE (obligatoria); VALIDACION_API_URL, VALIDACION_ADMIN_CORREO y VALIDACION_ADMIN_PASSWORD
(opcionales). Solo `dev`. Empieza antes de las 21:00 de Bogotá: dura 5–25 min. No depende del dataset real: crea su
propio video `validacion-51-<sello>` (4 fotos fuera del campus: 2 en A y 2 en B, 300 m al norte), espera a que el
`worker` las procese y lo borra al terminar; al empezar borra solo los restos `validacion-51-`. Enciende `embedding`
si está apagado y al terminar lo deja como lo encontró. Nunca imprime contraseñas, tokens ni URLs prefirmadas.
"""

from __future__ import annotations

import json
import math
import os
import re
import statistics
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import comun
from comun import ErrorConfiguracion, Falla, PrecondicionNoCumplida, exigir

LOTE = "BE-5.1"
INICIADA_POR = "validate51"
PREFIJO = f"{comun.PREFIJO_VALIDACION}51-"
RUTA_FRAME = "/localize/frame"
FOTOS = (1, 2, 3, 4)
FOTOS_A = (1, 2)  # en A; las 3 y 4, en B
DISTANCIA_B_M = 300.0  # B, al norte de A (fuera de LOC_FRAME_RADIO_MAX_M)
PREVIA_C1_M = 15.0  # C1: la posición previa, al este de A
PREVIA_C2_M = 10.0  # C2: la posición previa, al este de B
PREVIA_C3_M = 60.0  # C3: la posición previa, al sur de A
RADIO_C3_CORTO, RADIO_C3_LARGO = 30.0, 100.0
RADIO_POR_DEFECTO = 40.0  # LOC_FRAME_RADIO_M (§5.10)
ERROR_MAX_M = 10.0
COHERENCIA_M = 1.0  # |distancia_previa_m − haversine(previa, posicion)|
LEJOS_DE_A_M = 100.0  # C2: una posición a más de esto de A no es «la de A»
LATENCIA_MAX_MS = 1000
HORA_LIMITE = 21
LIMITE_PROCESADO_S = 20 * 60
PAUSA_SONDEO_S = 15.0
RADIO_TIERRA_M = 6_371_008.8  # el de `app.dominio.geo` (las carpetas no comparten código; una prueba los compara)
M_POR_GRADO = RADIO_TIERRA_M * math.pi / 180
PLAN_BACKEND = comun.RAIZ_CARPETA / "docs" / "PLAN.md"
CAMPOS_RESPUESTA = {
    "resultado", "posicion", "confianza", "nivel", "distancia_previa_m", "radio_busqueda_m", "imagenes_en_radio",
    "lugar_cercano", "referencias", "version_vector", "latencia_ms",
}  # fmt: skip


def avisar(mensaje: str) -> None:
    print(mensaje, file=sys.stderr, flush=True)


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Copia de `app.dominio.geo.distancia_m` (haversine, radio medio de la Tierra)."""
    fi1, fi2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((fi2 - fi1) / 2) ** 2 + math.cos(fi1) * math.cos(fi2) * math.sin(math.radians(lng2 - lng1) / 2) ** 2
    return 2 * RADIO_TIERRA_M * math.asin(min(1.0, math.sqrt(a)))


def desplazar(lat: float, lng: float, norte_m: float = 0.0, este_m: float = 0.0) -> tuple[float, float]:
    """(lat, lng) movido `norte_m` al norte y `este_m` al este (aproximación local, error < 1 mm a estas distancias)."""
    return lat + norte_m / M_POR_GRADO, lng + este_m / (M_POR_GRADO * math.cos(math.radians(lat)))


def _esperar(respuesta: Any, estado: int, que: str) -> Any:
    exigir(respuesta.status_code == estado, f"{que}: {comun.describir_respuesta(respuesta)}, se esperaba {estado}")
    return respuesta.json() if respuesta.content else None


class RecorridoFrame(comun.RecorridoPrueba):
    """El video de prueba: fotos en color con patrones distintos (`comun.jpeg_patron`, como `validate24.py`) y cada
    una en su coordenada (`coordenadas[orden]`): las de `FOTOS_A` en A y las demás en B."""

    def __init__(self, *args: Any, coordenadas: dict[int, tuple[float, float]], **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.coordenadas = coordenadas

    def foto(self, orden: int) -> bytes:
        if orden not in self._fotos:
            self._fotos[orden] = comun.jpeg_patron(self.semilla * 1000 + orden)
        return self._fotos[orden]

    def elemento(self, orden: int) -> dict[str, Any]:
        lat, lng = self.coordenadas[orden]
        return super().elemento(orden) | {"lat": lat, "lng": lng}


@dataclass
class Respuesta:
    que: str
    codigo: int
    cuerpo: dict[str, Any] = field(default_factory=dict)
    cliente_ms: float | None = None


# --- Contexto ------------------------------------------------------------------------------------------------------
class Contexto:
    def __init__(self, entorno: str = "dev") -> None:
        self.entorno = entorno
        self.sesion: Any = None
        self.api: comun.ClienteApi | None = None
        self.backend: Any = None
        self.emb: Any = None
        self.admin: tuple[str, str] | None = None
        self.dormir: Callable[[float], None] = time.sleep
        self.ahora: Callable[[], datetime] = lambda: datetime.now(UTC)
        self.http: Any = None
        self.http_s3: Any = None
        self.sello = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        self.solo: str | None = None
        self._outputs: dict[str, Any] | None = None
        self._token: str | None = None
        self.recorrido: RecorridoFrame | None = None
        self.procesado_min: float | None = None
        self.borrado = False
        self.estaba_encendido: bool | None = None
        self.encendido_por_mi = False
        self.respuestas: list[Respuesta] = []  # los 200 del frame, en orden (C5 y C6)

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

    def sql(self, consulta: str) -> list[list[str]]:
        return [linea.strip().split("|") for linea in self.backend.sql(consulta) if linea.strip()]

    def listo_en_api(self) -> bool:
        return comun.embedding_en_api(self.api) == "ok"

    @property
    def prefijo(self) -> str:
        return f"{PREFIJO}{self.sello}"

    @property
    def app_version(self) -> str:
        """`validacion-51-<sello>`: marca las filas de `eventos_localizacion` de esta ejecución (C5)."""
        return self.prefijo

    def semilla(self) -> int:
        return int(self.sello.replace("-", "")) % 1_000_000

    def punto_a(self) -> tuple[float, float]:
        """Fuera del campus (océano Pacífico), distinta en cada ejecución y lejos de las de `validate41.py`
        (1.x, −100)."""
        return 2.0 + (self.semilla() % 997) * 0.001, -101.0

    def punto_b(self) -> tuple[float, float]:
        return desplazar(*self.punto_a(), norte_m=DISTANCIA_B_M)

    # -- datos de prueba -------------------------------------------------------------------------------------------
    def asegurar_datos(self) -> RecorridoFrame:
        """Crea el video, sube sus 4 fotos, llama a `complete` y espera a que estén `procesada` (una vez)."""
        if self.recorrido is not None and self.procesado_min is not None:
            return self.recorrido
        if self.recorrido is None:
            a, b = self.punto_a(), self.punto_b()
            coordenadas = {o: (a if o in FOTOS_A else b) for o in FOTOS}
            self.recorrido = RecorridoFrame(
                self.api, self.token, self.prefijo, total_fotos=len(FOTOS), http_s3=self.http_s3, lat=a[0], lng=a[1],
                semilla=self.semilla(), coordenadas=coordenadas,
            )  # fmt: skip
            _esperar(self.recorrido.crear(), 201, "POST /v1/collect/videos")
        inicio = self.ahora()
        self.recorrido.asegurar_subidas(list(FOTOS))
        exigir(self.recorrido.completar().status_code == 200, "POST …/complete no dio 200")
        hasta = inicio + timedelta(seconds=LIMITE_PROCESADO_S)
        while True:
            detalle = _esperar(self.pedir("GET", f"/admin/videos/{self.recorrido.video_id}"), 200, "GET del video")
            estados = {int(f["orden"]): f.get("estado") for f in detalle.get("fotos", [])}
            exigir("error" not in estados.values(), f"una foto de prueba quedó en error: {estados}")
            if len(estados) == len(FOTOS) and set(estados.values()) == {"procesada"}:
                self.procesado_min = (self.ahora() - inicio).total_seconds() / 60
                return self.recorrido
            if self.ahora() >= hasta:
                raise Falla(f"tras {LIMITE_PROCESADO_S // 60} min, estados {estados}")
            self.dormir(PAUSA_SONDEO_S)

    def metadatos(self, previa: tuple[float, float], radio_m: float | None = None, **cambios: Any) -> dict[str, Any]:
        cuerpo: dict[str, Any] = {
            "rumbo": 90.0,
            "posicion_previa": {"lat": previa[0], "lng": previa[1]},
            "app_version": self.app_version,
        }
        if radio_m is not None:
            cuerpo["radio_m"] = radio_m
        return cuerpo | cambios

    def enviar(self, partes: list[Any]) -> Any:
        """`POST /v1/localize/frame` con esas partes (público: sin token)."""
        return self.api.pedir("POST", RUTA_FRAME, files=partes)

    def frame(self, que: str, foto: bytes, metadatos: dict[str, Any]) -> Respuesta:
        """Una petición válida: exige `200` con los campos de §5.3 y la guarda para C5 y C6."""
        partes = [
            ("foto", ("frame.jpg", foto, "image/jpeg")),
            ("metadatos", (None, json.dumps(metadatos).encode("utf-8"), "application/json")),
        ]
        r = self.enviar(partes)
        cuerpo = _esperar(r, 200, f"{que}: POST /v1/localize/frame")
        exigir(isinstance(cuerpo, dict) and set(cuerpo) == CAMPOS_RESPUESTA, f"{que}: campos {sorted(cuerpo or {})}")
        respuesta = Respuesta(que, r.status_code, cuerpo, self.api.ultima_duracion_ms)
        self.respuestas.append(respuesta)
        return respuesta

    # -- embedding, preparación y limpieza ---------------------------------------------------------------------------
    def asegurar_embedding(self) -> str:
        datos = self.emb.servicio(comun.SERVICIO_EMBEDDING)
        if int(datos.get("desiredCount", 0)) >= 1 and self.listo_en_api():
            self.emb.latido()
            return "ya encendido (latido publicado)"
        return f"encendido en {self.emb.encender(self.listo_en_api):.0f} s"

    def restos(self) -> list[dict[str, Any]]:
        """Solo los videos `validacion-51-…` (nombre **y** `ref_cliente`): nunca los de otros lotes ni los reales."""
        return [
            v
            for v in comun.videos_validacion(self.api, self.token())
            if str(v.get("nombre", "")).startswith(PREFIJO) and str(v.get("ref_cliente", "")).startswith(PREFIJO)
        ]

    def preparacion(self) -> str:
        restos = self.restos()
        for video in restos:
            r = self.pedir("DELETE", f"/admin/videos/{video['id']}")
            exigir(r.status_code in (202, 404), f"DELETE de un resto {PREFIJO}: {comun.describir_respuesta(r)}")
        return f"restos {PREFIJO} borrados: {len(restos)}" if restos else f"sin restos {PREFIJO}"

    def _restaurar_embedding(self) -> str:
        if self.emb is None or self.estaba_encendido is None:
            return "embedding sin tocar"
        if self.encendido_por_mi:
            self.emb.apagar()
            return "embedding apagado (lo encendió el validador)"
        return "embedding sigue encendido (como estaba)" if self.estaba_encendido else "embedding sin tocar"

    def _borrar_datos(self) -> str:
        if self.api is None or self.admin is None or self.recorrido is None or self.recorrido.video is None:
            return "sin video de prueba que borrar"
        r = self.pedir("DELETE", f"/admin/videos/{self.recorrido.video_id}")
        exigir(r.status_code in (202, 404), f"DELETE del video de prueba: {comun.describir_respuesta(r)}")
        self.borrado = True
        return "video de prueba borrado (la purga limpia S3)"

    def limpiar(self) -> str:
        partes: list[str] = []
        fallos: list[str] = []
        try:
            for paso in (self._borrar_datos, self._restaurar_embedding):
                try:
                    partes.append(paso())
                except Exception as exc:
                    fallos.append(f"{paso.__name__.strip('_')}: {comun._resumen(exc)}")
            if fallos:
                raise Falla(" · ".join(partes + fallos))
            return " · ".join(partes)
        finally:
            if self.recorrido is not None:
                self.recorrido.cerrar()
            if self.api is not None:
                self.api.cerrar()


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
    faltan = [lote for lote in ("BE-2.2", "BE-4.1") if not comun.lote_hecho(plan, lote)]
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
    return f'BE-2.2 y BE-4.1 «Hecho» · {url} · /v1/health/ready → "db": "ok" · {ahora:%H:%M} en Bogotá'


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
    ctx._token = cuerpo["token"]
    # Sonda sin foto: no llama a embeddings ni escribe evento.
    r = ctx.enviar([("otra", (None, b"validacion-51-sin-foto", "text/plain"))])
    if r.status_code in (404, 501):
        raise PrecondicionNoCumplida(f"BE-5.1 sin desplegar: POST /v1/localize/frame respondió {r.status_code}")
    exigir(
        (r.status_code, comun.codigo_error(r)) == (400, "FOTOS_INVALIDAS"),
        f"POST /v1/localize/frame sin foto: {comun.describir_respuesta(r)}, se esperaba 400 FOTOS_INVALIDAS",
    )
    return "login admin 200 (rol admin) · POST /v1/localize/frame sin foto → 400 FOTOS_INVALIDAS"


def p4_recursos(ctx: Contexto) -> str:
    from botocore.exceptions import ClientError

    comun.red_tareas(ctx.outputs())
    try:
        arn, _ = ctx.backend.imagen(comun.FAMILIA_VALIDACION)
    except ClientError as exc:
        if comun.es_acceso_denegado(exc):
            raise ErrorConfiguracion("sin permiso para describir las definiciones de tarea") from None
        raise PrecondicionNoCumplida(
            f"INF-1.3: falta {comun.FAMILIA_VALIDACION} ({comun.codigo_error_aws(exc)})"
        ) from None
    return f"red de tareas y {str(arn).rsplit('/', 1)[-1]} (SQL de C5)"


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
def _error_a(cuerpo: dict[str, Any], a: tuple[float, float]) -> float:
    pos = cuerpo.get("posicion")
    if cuerpo.get("resultado") != "ok" or not isinstance(pos, dict):
        return math.inf
    return haversine_m(float(pos["lat"]), float(pos["lng"]), *a)


def _exigir_coherente(cuerpo: dict[str, Any], previa: tuple[float, float], que: str) -> float:
    pos = cuerpo["posicion"]
    real = haversine_m(previa[0], previa[1], float(pos["lat"]), float(pos["lng"]))
    exigir(
        abs(float(cuerpo["distancia_previa_m"]) - real) <= COHERENCIA_M,
        f"{que}: distancia_previa_m {cuerpo['distancia_previa_m']} y la distancia real {real:.1f} m no coinciden",
    )
    return real


def c1_cerca(ctx: Contexto) -> str:
    recorrido = ctx.asegurar_datos()
    a = ctx.punto_a()
    previa = desplazar(*a, este_m=PREVIA_C1_M)
    cuerpo = ctx.frame("C1", recorrido.foto(1), ctx.metadatos(previa)).cuerpo
    error = _error_a(cuerpo, a)
    exigir(cuerpo["resultado"] == "ok", f"resultado {cuerpo['resultado']} (se esperaba ok)")
    exigir(error <= ERROR_MAX_M, f"posición a {error:.1f} m de la foto del dataset (máximo {ERROR_MAX_M:g})")
    exigir(cuerpo["nivel"] == "alta", f"nivel {cuerpo['nivel']} con la misma foto (se esperaba alta)")
    exigir(cuerpo["radio_busqueda_m"] == RADIO_POR_DEFECTO, f"radio_busqueda_m {cuerpo['radio_busqueda_m']}")
    exigir(cuerpo["imagenes_en_radio"] >= len(FOTOS_A), f"imagenes_en_radio {cuerpo['imagenes_en_radio']} (≥ 2)")
    real = _exigir_coherente(cuerpo, previa, "C1")
    return (
        f"fotos procesadas en {ctx.procesado_min:.1f} min · previa a {PREVIA_C1_M:g} m: ok a {error:.1f} m de A, "
        f"confianza {cuerpo['confianza']} alta, distancia_previa_m {cuerpo['distancia_previa_m']} (real {real:.1f}), "
        f"imagenes_en_radio {cuerpo['imagenes_en_radio']}, latencia_ms {cuerpo['latencia_ms']}"
    )


def c2_lejos(ctx: Contexto) -> str:
    recorrido = ctx.asegurar_datos()
    a = ctx.punto_a()
    previa = desplazar(*ctx.punto_b(), este_m=PREVIA_C2_M)
    cuerpo = ctx.frame("C2", recorrido.foto(1), ctx.metadatos(previa)).cuerpo
    error = _error_a(cuerpo, a)
    exigir(error > LEJOS_DE_A_M, f"con la previa a {DISTANCIA_B_M:g} m devolvió la posición de A (a {error:.1f} m)")
    exigir(
        cuerpo["imagenes_en_radio"] >= len(FOTOS) - len(FOTOS_A),
        f"imagenes_en_radio {cuerpo['imagenes_en_radio']}: las fotos de B deberían estar en el radio",
    )
    que = "sin_coincidencias" if cuerpo["resultado"] == "sin_coincidencias" else f"ok a {error:.0f} m de A (en B)"
    return (
        f"previa en B ({DISTANCIA_B_M:g} m de A): {que}, nunca A · imagenes_en_radio {cuerpo['imagenes_en_radio']} "
        "(hay dataset en el radio: lo excluye el filtro, no el vacío)"
    )


def c3_radio(ctx: Contexto) -> str:
    recorrido = ctx.asegurar_datos()
    a = ctx.punto_a()
    previa = desplazar(*a, norte_m=-PREVIA_C3_M)
    corto = ctx.frame("C3 corto", recorrido.foto(1), ctx.metadatos(previa, RADIO_C3_CORTO)).cuerpo
    exigir(
        (corto["resultado"], corto["imagenes_en_radio"], corto["radio_busqueda_m"])
        == ("sin_coincidencias", 0, RADIO_C3_CORTO),
        f"radio {RADIO_C3_CORTO:g}: {corto['resultado']}, imagenes_en_radio {corto['imagenes_en_radio']}, "
        f"radio_busqueda_m {corto['radio_busqueda_m']} (se esperaba sin_coincidencias, 0, {RADIO_C3_CORTO:g})",
    )
    largo = ctx.frame("C3 largo", recorrido.foto(1), ctx.metadatos(previa, RADIO_C3_LARGO)).cuerpo
    error = _error_a(largo, a)
    exigir(error <= ERROR_MAX_M, f"radio {RADIO_C3_LARGO:g}: {largo['resultado']} a {error:.1f} m de A")
    exigir(largo["radio_busqueda_m"] == RADIO_C3_LARGO, f"radio_busqueda_m {largo['radio_busqueda_m']}")
    real = _exigir_coherente(largo, previa, "C3")
    return (
        f"previa a {PREVIA_C3_M:g} m de A: radio_m {RADIO_C3_CORTO:g} → sin_coincidencias (0 imágenes) · radio_m "
        f"{RADIO_C3_LARGO:g} → ok a {error:.1f} m de A, distancia_previa_m {largo['distancia_previa_m']} "
        f"(real {real:.1f})"
    )


def _malas(ctx: Contexto) -> list[tuple[str, list[Any], int, str, Any]]:
    """`(qué, partes, estado, código, esperado)`: `esperado` es la lista de campos de un `422` o el `indice` de un
    `400 FOTOS_INVALIDAS`. Ninguna llama a embeddings."""
    foto = comun.jpeg_patron(ctx.semilla() * 1000 + 99)
    previa = desplazar(*ctx.punto_a(), este_m=PREVIA_C1_M)

    def partes(metadatos: Any, fotos: list[Any] | None = None) -> list[Any]:
        lista = fotos if fotos is not None else [("foto", ("frame.jpg", foto, "image/jpeg"))]
        if metadatos is not None:
            lista = [*lista, ("metadatos", (None, json.dumps(metadatos).encode("utf-8"), "application/json"))]
        return lista

    buena = ctx.metadatos(previa)
    sin_previa = {k: v for k, v in buena.items() if k != "posicion_previa"}
    dos = [("foto", ("a.jpg", foto, "image/jpeg")), ("foto", ("b.jpg", foto, "image/jpeg"))]
    png = [("foto", ("frame.png", comun.png_sintetico(), "image/png"))]
    return [
        ("sin metadatos", partes(None), 422, "VALIDACION", ["metadatos"]),
        ("sin posicion_previa", partes(sin_previa), 422, "VALIDACION", ["metadatos.posicion_previa"]),
        ("lat 91", partes(buena | {"posicion_previa": {"lat": 91, "lng": previa[1]}}), 422, "VALIDACION",
         ["metadatos.posicion_previa.lat"]),
        ("radio_m 500", partes(buena | {"radio_m": 500}), 422, "VALIDACION", ["metadatos.radio_m"]),
        ("rumbo 360", partes(buena | {"rumbo": 360}), 422, "VALIDACION", ["metadatos.rumbo"]),
        ("dos fotos", partes(buena, dos), 400, "FOTOS_INVALIDAS", 1),
        ("foto PNG", partes(buena, png), 400, "FOTOS_INVALIDAS", 0),
    ]  # fmt: skip


def c4_errores(ctx: Contexto) -> str:
    vistos = []
    for que, partes, estado, codigo, esperado in _malas(ctx):
        r = ctx.enviar(partes)
        exigir(
            (r.status_code, comun.codigo_error(r)) == (estado, codigo),
            f"{que}: {comun.describir_respuesta(r)}, se esperaba {estado} {codigo}",
        )
        detalle = r.json()["error"].get("detalle") or {}
        if estado == 422:
            campos = [c.get("campo") for c in detalle.get("campos", [])]
            exigir(campos == esperado, f"{que}: campos {campos}, se esperaba {esperado}")
            vistos.append(f"{que} → 422 {campos[0]}")
        else:
            exigir(detalle.get("indice") == esperado, f"{que}: indice {detalle.get('indice')}, se esperaba {esperado}")
            vistos.append(f"{que} → 400 indice {esperado}")
    return " · ".join(vistos)


def _asegurar_respuestas(ctx: Contexto) -> None:
    if not ctx.respuestas:  # con --solo C5 o C6: al menos la petición de C1
        c1_cerca(ctx)


def c5_eventos(ctx: Contexto) -> str:
    _asegurar_respuestas(ctx)
    exigir(re.fullmatch(r"validacion-51-\d{8}-\d{6}", ctx.app_version) is not None, "app_version inesperada")
    filas = ctx.sql(
        "SELECT origen, resultado, fotos_usadas, fotos_con_coincidencia FROM eventos_localizacion "  # noqa: S608
        f"WHERE app_version = '{ctx.app_version}' ORDER BY id"
    )
    esperadas = [r.cuerpo["resultado"] for r in ctx.respuestas]
    exigir(
        len(filas) == len(esperadas),
        f"{len(filas)} filas con app_version = {ctx.app_version} y {len(esperadas)} respuestas 200 (los errores de "
        "C4 no deben dejar fila)",
    )
    for fila, resultado in zip(filas, esperadas, strict=True):
        exigir(fila[0] == "frame", f"fila con origen {fila[0]!r} (se esperaba frame)")
        exigir(fila[1] == resultado, f"fila con resultado {fila[1]!r} y respuesta {resultado!r}")
        coincidencia = "1" if resultado == "ok" else "0"
        exigir(fila[2:] == ["1", coincidencia], f"fila con fotos_usadas/fotos_con_coincidencia {fila[2:]}")
    return (
        f"{len(filas)} filas con origen = frame y fotos_usadas = 1, una por cada 200 y en orden "
        f"({', '.join(esperadas)}); ninguna de los errores"
    )


def c6_latencia(ctx: Contexto) -> str:
    _asegurar_respuestas(ctx)
    latencias = [int(r.cuerpo["latencia_ms"]) for r in ctx.respuestas]
    lentas = [
        f"{r.que}: {r.cuerpo['latencia_ms']} ms" for r in ctx.respuestas if r.cuerpo["latencia_ms"] > LATENCIA_MAX_MS
    ]
    exigir(not lentas, f"latencia_ms > {LATENCIA_MAX_MS}: {', '.join(lentas)}")
    cliente = [r.cliente_ms for r in ctx.respuestas if r.cliente_ms is not None]
    medio = f" · en el cliente, mediana {statistics.median(cliente):.0f} ms (no cuenta)" if cliente else ""
    return (
        f"{len(latencias)} respuestas: latencia_ms mediana {statistics.median(latencias):.0f}, máxima "
        f"{max(latencias)} (≤ {LATENCIA_MAX_MS}){medio}"
    )


def main(argv: list[str] | None = None, ctx: Contexto | None = None) -> int:
    validador = comun.Validador(lote=LOTE, validacion="validation-5-1", entornos=("dev",), descripcion=__doc__)
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
            ("C4", lambda: c4_errores(ctx)),
            ("C1", lambda: c1_cerca(ctx)),
            ("C2", lambda: c2_lejos(ctx)),
            ("C3", lambda: c3_radio(ctx)),
            ("C6", lambda: c6_latencia(ctx)),
            ("C5", lambda: c5_eventos(ctx)),
        ],
        manuales=[],
        limpieza=ctx.limpiar,
    )


if __name__ == "__main__":
    sys.exit(main())
