"""BE-2.4 — Diagnóstico de búsqueda (vecinos). Una foto del dataset sale como su propio primer vecino; la respuesta trae
`k` vecinos ordenados sin filtrar por `LOC_SIM_MIN`; `k` fuera de rango, partes que no valen y un token `user` dan los
errores de §5.5; la foto de consulta no queda en S3, en los logs ni en `eventos_localizacion`.

Documento: BACKEND_FASTAPI/docs/validation/validation-2-4.md · criterios: BACKEND_FASTAPI/docs/PLAN.md §2.2.

    cd BACKEND_FASTAPI/project
    uv run --group ops python src/ops/validate24.py --entorno dev

Variables: AWS_PROFILE (obligatoria); VALIDACION_API_URL, VALIDACION_ADMIN_CORREO y VALIDACION_ADMIN_PASSWORD
(opcionales). Solo `dev` (S3, SQS y el `worker` no se emulan en local). Empieza antes de las 21:00 de Bogotá: dura
15–40 min y `embedding` se apaga solo a las 22:00. Enciende `embedding` si está apagado (contrato de infra §5.10) y al
terminar lo deja como lo encontró. Crea el video `validacion-24-<sello>` (3 fotos) y lo borra con
`limpiar-validacion`; crea o reactiva `validacion+user@campus.edu.co` y lo desactiva. Nunca imprime contraseñas,
tokens ni URLs prefirmadas.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import comun
from comun import ErrorConfiguracion, Falla, PrecondicionNoCumplida, exigir

LOTE = "BE-2.4"
INICIADA_POR = "validate24"
ORDENES = (1, 2, 3)
LAT, LNG = 1.0, -100.0  # fuera del campus (océano Pacífico)
VERSION_VECTOR = "dinov2-vits14/pp-v1"  # EMBEDDING_VERSION_VECTOR (backend §5.10)
SIMILITUD_PROPIA_MIN = 0.95
LOC_SIM_MIN = 0.55  # inicial (§5.10): solo se anota como evidencia en C2a
K_C1 = 5
K_MAX = 50
TAM_GRANDE = 1_677_722  # 1,6 MiB: pasa de LOC_MAX_BYTES_FOTO (1 572 864)
EVENTO_MAX_BYTES = 16_384
LIMITE_PROCESADO_S = 20 * 60  # la subida de `worker` puede tardar de 2 a 15 min (infra ADR-INF-15) + arranque
PAUSA_SONDEO_S = 15.0
HORA_LIMITE = 21  # America/Bogota: empezar antes (P2)
MARGEN_LOGS_S = 60  # C4b lee los logs desde 60 s antes del inicio (por si el reloj local va adelantado)
PLAN_BACKEND = comun.RAIZ_CARPETA / "docs" / "PLAN.md"
GRUPOS_LOG = (comun.LOG_API, comun.LOG_EMBEDDING)
#: Una línea `eventos|vectores` de `psql -tAc` (la versión, la de `VERSION_VECTOR`, escrita como literal).
SQL_CONTEOS = (
    "SELECT (SELECT count(*) FROM eventos_localizacion), "
    "(SELECT count(*) FROM embeddings WHERE version_vector = 'dinov2-vits14/pp-v1')"
)


def avisar(mensaje: str) -> None:
    print(mensaje, file=sys.stderr, flush=True)


def _esperar(respuesta: Any, estado: int, que: str) -> Any:
    exigir(respuesta.status_code == estado, f"{que}: {comun.describir_respuesta(respuesta)}, se esperaba {estado}")
    return respuesta.json()


def incluida(solo: str | None, id_: str) -> bool:
    """¿`--solo` incluye `id_`? (La misma regla que `comun.Validador`: `C4` incluye `C4a` y `C4b`.)"""
    if not solo:
        return True
    elegidas = {parte.strip() for parte in solo.split(",") if parte.strip()}
    criterio = re.match(r"([A-Z]+\d+)", id_)
    return id_ in elegidas or (criterio is not None and criterio.group(1) in elegidas)


class RecorridoPatrones(comun.RecorridoPrueba):
    """`RecorridoPrueba` con fotos en color y patrones distintos (`comun.jpeg_patron`): con la escala de grises de
    `jpeg_sintetico`, las tres fotos podrían parecerse demasiado para el modelo."""

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
        self.backend: comun.EntornoBackend | None = None
        self.emb: comun.EmbeddingDev | None = None
        self.s3: Any = None
        self.logs: Any = None
        self.bucket: str | None = None
        self.admin: tuple[str, str] | None = None
        self.dormir: Callable[[float], None] = time.sleep
        self.ahora: Callable[[], datetime] = lambda: datetime.now(UTC)
        self.http: Any = None
        self.http_s3: Any = None
        self.sello = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        self.solo: str | None = None
        self.inicio: datetime | None = None
        self._outputs: dict[str, Any] | None = None
        self._token: str | None = None
        self.principal: RecorridoPatrones | None = None
        self.creados: list[str] = []
        self.borrados: set[str] = set()
        self.procesadas: set[int] = set()  # órdenes de C1 que llegaron a `procesada` (vector nuevo en el índice)
        self.estaba_encendido: bool | None = None  # cómo se encontró `embedding` (P5)
        self.encendido_por_mi = False
        self.usuario_pudo_quedar_activo = False
        self.claves_iniciales: set[str] | None = None
        self.conteos_iniciales: tuple[int, int] | None = None  # (eventos_localizacion, vectores de la versión activa)
        self.n_contado: int | None = None  # N contado con SQL cuando no hay lecturas iniciales (--solo)
        self.respuestas_c2: dict[int, list[dict[str, Any]]] = {}

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
            correo, password = self.admin
            self._token = self.api.token(correo, password, quien="el admin")
        return self._token

    def pedir(self, metodo: str, ruta: str, **kwargs: Any) -> Any:
        return self.api.pedir(metodo, ruta, token=self.token(), **kwargs)

    def vecinos(self, foto: bytes, k: Any = None, **kwargs: Any) -> Any:
        return comun.pedir_vecinos(self.api, kwargs.pop("token", self.token()), foto, k=k, **kwargs)

    @property
    def nombre(self) -> str:
        return f"{comun.PREFIJO_VALIDACION}24-{self.sello}"

    def semilla(self) -> int:
        return int(self.sello.replace("-", "")) % 1_000_000

    def listo_en_api(self) -> bool:
        return comun.embedding_en_api(self.api) == "ok"

    # -- video de prueba ---------------------------------------------------------------------------------------------
    def asegurar_video(self) -> RecorridoPatrones:
        if self.principal is None:
            recorrido = RecorridoPatrones(
                self.api,
                self.token,
                self.nombre,
                total_fotos=len(ORDENES),
                http_s3=self.http_s3,
                lat=LAT,
                lng=LNG,
                semilla=self.semilla(),
            )
            _esperar(recorrido.crear(), 201, "POST /v1/collect/videos")
            self.creados.append(recorrido.video_id)
            self.principal = recorrido
        return self.principal

    def fotos(self) -> dict[int, dict[str, Any]]:
        video_id = self.asegurar_video().video_id
        detalle = _esperar(self.pedir("GET", f"/admin/videos/{video_id}"), 200, "GET /v1/admin/videos/{id}")
        return {int(f["orden"]): f for f in detalle.get("fotos", [])}

    def asegurar_procesadas(self) -> float:
        """Sube las fotos de C1 (si faltan) y espera a que estén `procesada`. Devuelve los minutos que tardó."""
        if self.procesadas == set(ORDENES):
            return 0.0
        inicio = self.ahora()
        self.asegurar_video().asegurar_subidas(list(ORDENES))
        hasta = inicio + timedelta(seconds=LIMITE_PROCESADO_S)
        while True:
            fotos = self.fotos()
            estados = {o: fotos.get(o, {}).get("estado") for o in ORDENES}
            self.procesadas = {o for o, estado in estados.items() if estado == "procesada"}
            for orden, estado in estados.items():
                exigir(estado != "error", f"la foto {orden} quedó en error ({fotos[orden].get('error')!r})")
            if self.procesadas == set(ORDENES):
                return (self.ahora() - inicio).total_seconds() / 60
            if self.ahora() >= hasta:
                raise Falla(f"tras {LIMITE_PROCESADO_S // 60} min, estados {estados}, se esperaba procesada")
            self.dormir(PAUSA_SONDEO_S)

    # -- lecturas para C2 y C4a --------------------------------------------------------------------------------------
    def conteos(self) -> tuple[int, int]:
        """`(eventos_localizacion, vectores de la versión activa)` con la tarea de validación (`psql -tAc`)."""
        lineas = [linea for linea in self.backend.sql(SQL_CONTEOS) if linea.strip()]
        exigir(len(lineas) == 1, f"psql devolvió {len(lineas)} líneas para los conteos")
        partes = lineas[0].strip().split("|")
        exigir(len(partes) == 2 and all(p.isdigit() for p in partes), f"conteos inesperados: {lineas[0][:80]!r}")
        return int(partes[0]), int(partes[1])

    def claves(self) -> set[str]:
        return set(comun.claves_s3(self.s3, self.bucket, ""))

    def lecturas_iniciales(self) -> str:
        self.claves_iniciales = self.claves()
        self.conteos_iniciales = self.conteos()
        eventos, vectores = self.conteos_iniciales
        return (
            f"lecturas iniciales: {len(self.claves_iniciales)} objetos en S3, eventos_localizacion = {eventos}, "
            f"{vectores} vectores {VERSION_VECTOR}"
        )

    def n_indice(self) -> int:
        """Vectores de la versión activa que ve el endpoint: los iniciales más las fotos de C1 ya procesadas (sin otra
        tarea); sin lecturas iniciales, se cuentan ahora."""
        if self.conteos_iniciales is not None:
            return self.conteos_iniciales[1] + len(self.procesadas)
        if self.n_contado is None:
            self.n_contado = self.conteos()[1]
        return self.n_contado

    # -- embedding ---------------------------------------------------------------------------------------------------
    def asegurar_embedding(self) -> str:
        datos = self.emb.servicio(comun.SERVICIO_EMBEDDING)
        if int(datos.get("desiredCount", 0)) >= 1 and self.listo_en_api():
            self.emb.latido()
            return "ya encendido (latido publicado)"
        segundos = self.emb.encender(self.listo_en_api)
        return f"encendido en {segundos:.0f} s"

    # -- preparación y limpieza --------------------------------------------------------------------------------------
    def preparacion(self) -> str:
        partes = [comun.borrar_restos(self.api, self.token(), self.backend)]
        if incluida(self.solo, "C4a"):
            partes.append(self.lecturas_iniciales())
        return " · ".join(partes)

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

    def _existe(self, video_id: str) -> bool:
        r = self.pedir("GET", f"/admin/videos/{video_id}")
        if r.status_code == 404:
            return False
        exigir(r.status_code == 200, f"GET /v1/admin/videos/{{id}}: {comun.describir_respuesta(r)}")
        return True

    def limpiar(self) -> str:
        partes: list[str] = []
        fallos: list[str] = []
        try:
            try:
                partes.append(self._restaurar_embedding())
            except Exception as exc:
                fallos.append(f"embedding NO quedó como estaba ({comun._resumen(exc)}): apágalo a mano (§5 paso 7)")
            try:
                pendientes = [v for v in self.creados if v not in self.borrados]
                existentes = [v for v in pendientes if self._existe(v)] if pendientes else []
                if not pendientes:
                    partes.append("nada que borrar")
                elif not existentes:
                    partes.append("los videos de prueba ya no existen")
                else:
                    tarea = comun.limpiar_videos(self.backend, existentes)
                    if tarea.codigo != 0:
                        raise Falla(f"limpiar-validacion terminó con {tarea.codigo}: {comun.motivo_cli(tarea)}")
                    self.borrados.update(existentes)
                    resumen = comun.linea_limpieza(tarea)
                    partes.append(f"videos de prueba borrados: {json.dumps(resumen) if resumen else len(existentes)}")
            except Exception as exc:
                fallos.append(f"videos: {comun._resumen(exc)}")
            if self.usuario_pudo_quedar_activo:
                try:
                    partes.append(comun.desactivar_usuario_validacion(self.backend, tolerar_inexistente=True))
                    self.usuario_pudo_quedar_activo = False
                except Exception as exc:
                    fallos.append(f"usuario: {comun._resumen(exc)}")
            if fallos:
                raise Falla(" · ".join(partes + fallos))
            return " · ".join(partes)
        finally:
            if self.api is not None:
                self.api.cerrar()
            if self.principal is not None:
                self.principal.cerrar()


# --- Precondiciones ------------------------------------------------------------------------------------------------
def p1_credenciales(ctx: Contexto) -> str:
    ctx.sesion = comun.sesion_aws()
    arn = comun.verificar_cuenta(ctx.sesion)
    ctx.emb = comun.EmbeddingDev(ctx.sesion, dormir=ctx.dormir, reloj=ctx.ahora, avisar=avisar)
    return f"cuenta {comun.CUENTA_AWS} ({arn.rsplit('/', 1)[-1]})"


def p2_ingesta_y_hora(ctx: Contexto) -> str:
    import httpx

    ctx.inicio = ctx.ahora()
    try:
        plan = PLAN_BACKEND.read_text(encoding="utf-8")
    except OSError:
        raise ErrorConfiguracion(f"no se pudo leer {PLAN_BACKEND}") from None
    if not comun.lote_hecho(plan, "BE-2.2"):
        raise PrecondicionNoCumplida("BE-2.2 no está «Hecho» en BACKEND_FASTAPI/docs/PLAN.md §3")
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
    return f'BE-2.2 «Hecho» · {url} · /v1/health/ready → "db": "ok" · {ahora:%H:%M} en Bogotá (antes de las 21:00)'


def p3_login_y_endpoint(ctx: Contexto) -> str:
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
    # Sin parte `foto`: no llama a embeddings. Con la imagen anterior a BE-2.4, la ruta no existe (404).
    r = ctx.vecinos(b"validacion-sin-foto", parte="otra", tipo="text/plain")
    if r.status_code == 404:
        raise PrecondicionNoCumplida("BE-2.4 sin desplegar: POST /v1/admin/diagnostico/vecinos respondió 404")
    if not (r.status_code == 400 and comun.codigo_error(r) == "FOTOS_INVALIDAS"):
        raise PrecondicionNoCumplida(f"POST …/diagnostico/vecinos sin foto respondió {comun.describir_respuesta(r)}")
    return "login admin 200 (rol admin) · POST /v1/admin/diagnostico/vecinos sin foto → 400 FOTOS_INVALIDAS"


def p4_recursos(ctx: Contexto) -> str:
    from botocore.exceptions import ClientError

    outputs = ctx.outputs()
    if not outputs.get("bucket_dataset"):
        raise PrecondicionNoCumplida("INF-1.2: falta el output bucket_dataset")
    ctx.bucket = outputs["bucket_dataset"]
    ctx.s3, ctx.logs = ctx.sesion.client("s3"), ctx.sesion.client("logs")
    comun.comprobar_bucket(ctx.s3, ctx.bucket)
    comun.red_tareas(outputs)
    try:
        ctx.backend.imagen(comun.FAMILIA_VALIDACION)
        migrate = ctx.backend.revision(comun.FAMILIA_MIGRATE)
        worker = ctx.backend.revision(comun.FAMILIA_WORKER)
    except ClientError as exc:
        if comun.es_acceso_denegado(exc):
            raise ErrorConfiguracion("sin permiso para describir las definiciones de tarea") from None
        raise PrecondicionNoCumplida(
            f"INF-1.3: falta una definición de tarea ({comun.codigo_error_aws(exc)})"
        ) from None
    except Falla as exc:  # migrate o worker con otra imagen que api: backend.yml no terminó
        raise PrecondicionNoCumplida(f"BE-2.4 sin desplegar del todo: {exc}") from None
    inf21 = ctx.emb.comprobar_inf21()
    return (
        f"bucket, {comun.FAMILIA_VALIDACION}, {migrate.rsplit('/', 1)[-1]} y {worker.rsplit('/', 1)[-1]} con la "
        f"imagen de api · INF-2.1: {inf21}"
    )


def p5_embedding(ctx: Contexto) -> str:
    datos = ctx.emb.servicio(comun.SERVICIO_EMBEDDING)
    ctx.estaba_encendido = int(datos.get("desiredCount", 0)) >= 1
    ctx.encendido_por_mi = not ctx.estaba_encendido  # se marca antes de encender: la limpieza lo apaga igual
    try:
        detalle = ctx.asegurar_embedding()
    except Falla as exc:
        raise PrecondicionNoCumplida(f"EMB-2.1/INF-2.1: embedding no quedó listo: {exc}") from None
    return f'embedding {detalle} · /v1/health/ready → "embedding": "ok"'


# --- Comprobaciones ------------------------------------------------------------------------------------------------
def _vecinos_de(r: Any, que: str) -> list[dict[str, Any]]:
    cuerpo = _esperar(r, 200, que)
    exigir(cuerpo.get("version_vector") == VERSION_VECTOR, f"{que}: version_vector {cuerpo.get('version_vector')!r}")
    vecinos = cuerpo.get("vecinos")
    exigir(isinstance(vecinos, list), f"{que}: sin lista `vecinos`")
    similitudes = [v.get("similitud") for v in vecinos]
    exigir(all(isinstance(s, int | float) for s in similitudes), f"{que}: similitudes no numéricas")
    exigir(similitudes == sorted(similitudes, reverse=True), f"{que}: vecinos sin ordenar de mayor a menor similitud")
    return vecinos


def c1_propia_primera(ctx: Contexto) -> str:
    minutos = ctx.asegurar_procesadas()
    recorrido = ctx.asegurar_video()
    similitudes = []
    for orden in ORDENES:
        imagen_id = str(recorrido.registro[orden]["id"])
        vecinos = _vecinos_de(ctx.vecinos(recorrido.foto(orden), k=K_C1), f"foto {orden} con k={K_C1}")
        exigir(vecinos, f"la foto {orden} no tiene vecinos")
        primero = vecinos[0]
        exigir(
            primero.get("imagen_id") == imagen_id,
            f"la foto {orden}: el primer vecino es {primero.get('imagen_id')} (similitud {primero.get('similitud')}),"
            f" no ella misma",
        )
        exigir(primero.get("video_id") == recorrido.video_id, f"la foto {orden}: video_id {primero.get('video_id')}")
        exigir(
            primero["similitud"] >= SIMILITUD_PROPIA_MIN,
            f"la foto {orden}: similitud consigo misma {primero['similitud']} < {SIMILITUD_PROPIA_MIN}",
        )
        similitudes.append(f"{primero['similitud']:.4f}")
    return (
        f"video {recorrido.video_id}: fotos 1–3 en procesada en {minutos:.1f} min · cada una es su primer vecino "
        f"(similitud {', '.join(similitudes)}) · version_vector = {VERSION_VECTOR}"
    )


def _consulta_c2(ctx: Contexto) -> bytes:
    return comun.jpeg_ruido(ctx.semilla())


def _respuesta_c2(ctx: Contexto, k: int) -> list[dict[str, Any]]:
    if k not in ctx.respuestas_c2:
        ctx.respuestas_c2[k] = _vecinos_de(ctx.vecinos(_consulta_c2(ctx), k=k), f"foto sin relación con k={k}")
    return ctx.respuestas_c2[k]


def c2a_k_vecinos_sin_umbral(ctx: Contexto) -> str:
    ctx.emb.latido()  # tras la espera de C1: aleja el apagado por inactividad (infra §5.11)
    n = ctx.n_indice()
    vecinos = _respuesta_c2(ctx, K_C1)
    esperado = min(K_C1, n)
    exigir(len(vecinos) == esperado, f"k={K_C1} → {len(vecinos)} vecinos, se esperaban min({K_C1}, N={n}) = {esperado}")
    bajo = [v["similitud"] for v in vecinos if v["similitud"] < LOC_SIM_MIN]
    rango = f"{vecinos[-1]['similitud']:.4f}–{vecinos[0]['similitud']:.4f}" if vecinos else "sin vecinos"
    return (
        f"N = {n} vectores en el índice · k={K_C1} → {len(vecinos)} vecinos ordenados (similitud {rango}; "
        f"{len(bajo)} por debajo de LOC_SIM_MIN = {LOC_SIM_MIN}, no se descartan)"
    )


def c2b_k_1_y_50(ctx: Contexto) -> str:
    n = ctx.n_indice()
    uno, cinco, cincuenta = _respuesta_c2(ctx, 1), _respuesta_c2(ctx, K_C1), _respuesta_c2(ctx, K_MAX)
    exigir(len(uno) == min(1, n), f"k=1 → {len(uno)} vecinos")
    exigir(len(cincuenta) == min(K_MAX, n), f"k={K_MAX} → {len(cincuenta)} vecinos, se esperaban {min(K_MAX, n)}")
    if n:
        exigir(cinco and uno[0]["imagen_id"] == cinco[0]["imagen_id"], "el primer vecino de k=1 y de k=5 difiere")
    return f"k=1 → {len(uno)} y k={K_MAX} → {len(cincuenta)} vecinos (N = {n}), ordenados; k=1 y k=5 empiezan igual"


def _error_esperado(r: Any, estado: int, codigo: str, que: str) -> dict[str, Any]:
    exigir(
        r.status_code == estado and comun.codigo_error(r) == codigo,
        f"{que}: {comun.describir_respuesta(r)}, se esperaba {estado} {codigo}",
    )
    return r.json()["error"].get("detalle") or {}


def c3a_k_fuera_de_rango(ctx: Contexto) -> str:
    foto = comun.jpeg_patron(ctx.semilla() * 1000 + 9)
    for k in (0, 51, "abc"):
        detalle = _error_esperado(ctx.vecinos(foto, k=k), 422, "VALIDACION", f"k={k}")
        campos = [c.get("campo") for c in detalle.get("campos", [])]
        exigir("k" in campos, f"k={k}: detalle.campos = {campos}, se esperaba que nombrara k")
    return "k=0, k=51 y k=abc → 422 VALIDACION con detalle.campos = [k]"


def c3b_partes_invalidas(ctx: Contexto) -> str:
    casos = [
        ("sin parte foto", {"foto": b"validacion-sin-foto", "parte": "otra", "tipo": "text/plain"}),
        ("parte PNG", {"foto": comun.png_sintetico(), "tipo": "image/png"}),
        (f"JPEG de {TAM_GRANDE} bytes", {"foto": comun.jpeg_relleno(TAM_GRANDE)}),
    ]
    for que, argumentos in casos:
        foto = argumentos.pop("foto")
        detalle = _error_esperado(ctx.vecinos(foto, k=K_C1, **argumentos), 400, "FOTOS_INVALIDAS", que)
        exigir(detalle.get("indice") == 0, f"{que}: detalle.indice = {detalle.get('indice')}, se esperaba 0")
    return "sin parte foto, parte PNG y JPEG de 1,6 MB → 400 FOTOS_INVALIDAS con detalle.indice = 0"


def c3c_permisos(ctx: Contexto) -> str:
    foto = comun.jpeg_patron(ctx.semilla() * 1000 + 9)
    # Antes de lanzar crear-usuario: la limpieza lo desactiva aunque la tarea falle a medias.
    ctx.usuario_pudo_quedar_activo = True
    password = comun.crear_usuario_validacion(ctx.backend)
    token_user = ctx.api.token(comun.USUARIO_VALIDACION, password, quien=comun.USUARIO_VALIDACION)
    _error_esperado(ctx.vecinos(foto, k=K_C1, token=token_user), 403, "SIN_PERMISOS", "con el token user")
    _error_esperado(ctx.vecinos(foto, k=K_C1, token=None), 401, "NO_AUTENTICADO", "sin Authorization")
    return f"token de {comun.USUARIO_VALIDACION} → 403 SIN_PERMISOS · sin token → 401 NO_AUTENTICADO"


def c4a_nada_guardado(ctx: Contexto) -> str:
    exigir(
        ctx.claves_iniciales is not None and ctx.conteos_iniciales is not None,
        "faltan las lecturas iniciales (falló la preparación: mira [PREPARACION])",
    )
    finales = ctx.claves()
    nuevas = sorted(finales - ctx.claves_iniciales)
    prefijos = tuple(f"{p}/{v}/" for v in ctx.creados for p in ("dataset", "thumbs"))
    ajenas = [c for c in nuevas if not c.startswith(prefijos)] if prefijos else nuevas
    exigir(not ajenas, f"{len(ajenas)} claves nuevas fuera del video de prueba, p. ej. {', '.join(ajenas[:3])}")
    eventos, vectores = ctx.conteos()
    eventos_0, vectores_0 = ctx.conteos_iniciales
    exigir(eventos == eventos_0, f"eventos_localizacion pasó de {eventos_0} a {eventos} (¿alguien localizó en dev?)")
    esperados = vectores_0 + len(ctx.procesadas)
    exigir(
        vectores == esperados,
        f"vectores {VERSION_VECTOR}: {vectores_0} → {vectores}, se esperaban {esperados} (¿ingesta ajena en dev?)",
    )
    return (
        f"{len(nuevas)} claves nuevas, todas de dataset/ y thumbs/ del video de prueba · eventos_localizacion = "
        f"{eventos}, sin cambios · vectores {vectores_0} → {vectores} (+{len(ctx.procesadas)}: las fotos de C1)"
    )


def c4b_logs(ctx: Contexto) -> str:
    desde = (ctx.inicio or ctx.ahora()) - timedelta(seconds=MARGEN_LOGS_S)
    resumen = []
    for grupo in GRUPOS_LOG:
        mensajes = comun.mensajes_log(ctx.logs, grupo, desde)
        con_jpeg = sum("/9j/" in m for m in mensajes)
        grandes = sum(len(m.encode("utf-8")) > EVENTO_MAX_BYTES for m in mensajes)
        exigir(not con_jpeg, f"{grupo}: {con_jpeg} eventos contienen /9j/ (un JPEG en base64)")
        exigir(not grandes, f"{grupo}: {grandes} eventos pesan más de {EVENTO_MAX_BYTES // 1024} KB")
        resumen.append(f"{len(mensajes)} en {grupo.rsplit('/', 1)[-1]}")
    return f"eventos desde el inicio: {' y '.join(resumen)}; ninguno con /9j/ ni de más de 16 KB"


def main(argv: list[str] | None = None, ctx: Contexto | None = None) -> int:
    validador = comun.Validador(lote=LOTE, validacion="validation-2-4", entornos=("dev",), descripcion=__doc__)
    argumentos = validador.iniciar(argv)
    ctx = ctx or Contexto(argumentos.entorno)
    ctx.solo = argumentos.solo
    return validador.ejecutar(
        precondiciones=[
            ("P1", lambda: p1_credenciales(ctx)),
            ("P2", lambda: p2_ingesta_y_hora(ctx)),
            ("P3", lambda: p3_login_y_endpoint(ctx)),
            ("P4", lambda: p4_recursos(ctx)),
            ("P5", lambda: p5_embedding(ctx)),
        ],
        preparacion=ctx.preparacion,
        comprobaciones=[
            ("C1", lambda: c1_propia_primera(ctx)),
            ("C2a", lambda: c2a_k_vecinos_sin_umbral(ctx)),
            ("C2b", lambda: c2b_k_1_y_50(ctx)),
            ("C3a", lambda: c3a_k_fuera_de_rango(ctx)),
            ("C3b", lambda: c3b_partes_invalidas(ctx)),
            ("C3c", lambda: c3c_permisos(ctx)),
            ("C4a", lambda: c4a_nada_guardado(ctx)),
            ("C4b", lambda: c4b_logs(ctx)),
        ],
        manuales=[],
        limpieza=ctx.limpiar,
    )


if __name__ == "__main__":
    sys.exit(main())
