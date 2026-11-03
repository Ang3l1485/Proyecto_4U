"""BE-2.3 — Resumen del panel. `GET /v1/admin/stats`: `total_fotos` sube con las fotos de un video de prueba cuando
llegan a `procesada` (no antes), `total_lugares` sube y baja con los lugares de prueba, y `ultimo_video` es el video
recién creado; la respuesta tiene exactamente los campos de §5.5 y `alertas_activas` es un entero ≥ 0 (con datos lo
comprueba BE-3.3 C5).

Documento: BACKEND_FASTAPI/docs/validation/validation-2-3.md · criterios: BACKEND_FASTAPI/docs/PLAN.md §2.2.

    cd BACKEND_FASTAPI/project
    uv run --group ops python src/ops/validate23.py --entorno dev

Variables: AWS_PROFILE (obligatoria); VALIDACION_API_URL, VALIDACION_ADMIN_CORREO y VALIDACION_ADMIN_PASSWORD
(opcionales). Solo `dev` (las fotos `procesada` necesitan S3, SQS y el `worker`, que no se emulan en local). Empieza
antes de las 21:00 de Bogotá: dura 10–40 min y `embedding` se apaga solo a las 22:00. Enciende `embedding` si está
apagado (contrato de infra §5.10) y al terminar lo deja como lo encontró. Crea el video `validacion-23-<sello>` (2
fotos) y lo borra con `limpiar-validacion`; crea los lugares `validacion-23-<sello> a` y `… b` y los borra. Nunca
imprime contraseñas, tokens ni URLs prefirmadas.
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

LOTE = "BE-2.3"
INICIADA_POR = "validate23"
ORDENES = (1, 2)
LAT, LNG = 1.0, -100.0  # fuera del campus (océano Pacífico): videos y lugares de prueba
LIMITE_COLA_S = 15 * 60  # C1a espera a que `ingesta` se vacíe antes de leer s0 (fotos ajenas a medio procesar)
LIMITE_PROCESADO_S = 20 * 60  # la subida de `worker` puede tardar de 2 a 15 min (infra ADR-INF-15) + arranque
PAUSA_SONDEO_S = 15.0
HORA_LIMITE = 21  # America/Bogota: empezar antes (P2)
PLAN_BACKEND = comun.RAIZ_CARPETA / "docs" / "PLAN.md"


def avisar(mensaje: str) -> None:
    print(mensaje, file=sys.stderr, flush=True)


def incluida(solo: str | None, id_: str) -> bool:
    """¿`--solo` incluye `id_`? (La misma regla que `comun.Validador`: `C1` incluye `C1a`, `C1b` y `C1c`.)"""
    if not solo:
        return True
    elegidas = {parte.strip() for parte in solo.split(",") if parte.strip()}
    criterio = re.match(r"([A-Z]+\d+)", id_)
    return id_ in elegidas or (criterio is not None and criterio.group(1) in elegidas)


def _esperar(respuesta: Any, estado: int, que: str) -> Any:
    exigir(respuesta.status_code == estado, f"{que}: {comun.describir_respuesta(respuesta)}, se esperaba {estado}")
    return respuesta.json() if estado != 204 else None


# --- Contexto ------------------------------------------------------------------------------------------------------
class Contexto:
    def __init__(self, entorno: str = "dev") -> None:
        self.entorno = entorno
        self.sesion: Any = None
        self.api: comun.ClienteApi | None = None
        self.backend: comun.EntornoBackend | None = None
        self.emb: comun.EmbeddingDev | None = None
        self.s3: Any = None
        self.sqs: Any = None
        self.bucket: str | None = None
        self.url_ingesta: str | None = None
        self.admin: tuple[str, str] | None = None
        self.dormir: Callable[[float], None] = time.sleep
        self.ahora: Callable[[], datetime] = lambda: datetime.now(UTC)
        self.http: Any = None
        self.http_s3: Any = None
        self.sello = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        self.solo: str | None = None
        self._outputs: dict[str, Any] | None = None
        self._token: str | None = None
        self.recorrido: comun.RecorridoPrueba | None = None
        self.creados: list[str] = []  # videos de prueba
        self.borrados: set[str] = set()
        self.lugares: list[str] = []  # ids de los lugares de prueba creados (también si se borraron después)
        self.estaba_encendido: bool | None = None  # cómo se encontró `embedding` (P5)
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

    def token(self) -> str:
        if self._token is None:
            correo, password = self.admin
            self._token = self.api.token(correo, password, quien="el admin")
        return self._token

    def pedir(self, metodo: str, ruta: str, **kwargs: Any) -> Any:
        return self.api.pedir(metodo, ruta, token=self.token(), **kwargs)

    @property
    def prefijo(self) -> str:
        return f"{comun.PREFIJO_VALIDACION}23-{self.sello}"

    def semilla(self) -> int:
        return int(self.sello.replace("-", "")) % 1_000_000

    def listo_en_api(self) -> bool:
        return comun.embedding_en_api(self.api) == "ok"

    # -- lecturas ----------------------------------------------------------------------------------------------------
    def resumen(self, que: str) -> dict[str, Any]:
        """`GET /v1/admin/stats` (`comun.resumen_panel`: los cuatro campos de §5.5 y los totales enteros ≥ 0)."""
        return comun.resumen_panel(self.api, self.token(), que=f"GET /v1/admin/stats ({que})")

    def esperar_ingesta_vacia(self) -> str:
        """Hasta `LIMITE_COLA_S` a que `ingesta` no tenga mensajes (visibles ni en vuelo): si el `worker` procesara
        fotos ajenas entre s0 y s1, `total_fotos` subiría de más."""
        inicio = self.ahora()
        hasta = inicio + timedelta(seconds=LIMITE_COLA_S)
        while True:
            visibles, en_vuelo = comun.mensajes_cola(self.sqs, self.url_ingesta)
            if visibles + en_vuelo == 0:
                minutos = (self.ahora() - inicio).total_seconds() / 60
                return "ingesta vacía" if minutos < 0.01 else f"ingesta vacía tras {minutos:.1f} min"
            if self.ahora() >= hasta:
                raise Falla(
                    f"ingesta sigue con {visibles} visibles y {en_vuelo} en vuelo tras {LIMITE_COLA_S // 60} min: "
                    "el worker procesaría fotos ajenas durante C1a (espera a que se vacíe y repite)"
                )
            self.dormir(PAUSA_SONDEO_S)

    # -- video de prueba ---------------------------------------------------------------------------------------------
    def asegurar_video(self) -> comun.RecorridoPrueba:
        if self.recorrido is None:
            recorrido = comun.RecorridoPrueba(
                self.api,
                self.token,
                self.prefijo,
                total_fotos=len(ORDENES),
                http_s3=self.http_s3,
                lat=LAT,
                lng=LNG,
                semilla=self.semilla(),
            )
            _esperar(recorrido.crear(), 201, "POST /v1/collect/videos")
            self.creados.append(recorrido.video_id)
            self.recorrido = recorrido
        return self.recorrido

    def estados(self) -> dict[int, dict[str, Any]]:
        video_id = self.asegurar_video().video_id
        detalle = _esperar(self.pedir("GET", f"/admin/videos/{video_id}"), 200, "GET /v1/admin/videos/{id}")
        return {int(f["orden"]): f for f in detalle.get("fotos", [])}

    def esperar_procesadas(self) -> float:
        """Sondea cada 15 s hasta que las fotos de `ORDENES` estén `procesada`. Devuelve los minutos."""
        inicio = self.ahora()
        hasta = inicio + timedelta(seconds=LIMITE_PROCESADO_S)
        while True:
            fotos = self.estados()
            estados = {o: fotos.get(o, {}).get("estado") for o in ORDENES}
            for orden, estado in estados.items():
                exigir(estado != "error", f"la foto {orden} quedó en error ({fotos[orden].get('error')!r})")
            if all(estado == "procesada" for estado in estados.values()):
                return (self.ahora() - inicio).total_seconds() / 60
            if self.ahora() >= hasta:
                raise Falla(f"tras {LIMITE_PROCESADO_S // 60} min, estados {estados}, se esperaba procesada")
            self.dormir(PAUSA_SONDEO_S)

    # -- lugares de prueba -------------------------------------------------------------------------------------------
    def crear_lugar(self, sufijo: str) -> str:
        cuerpo = {"nombre": f"{self.prefijo} {sufijo}", "categoria": "bloque", "lat": LAT, "lng": LNG}
        respuesta = self.pedir("POST", comun.RUTA_LUGARES_ADMIN, json=cuerpo)
        if respuesta.status_code == 201:
            self.lugares.append(str(respuesta.json().get("id")))
        lugar = _esperar(respuesta, 201, f"POST /v1/admin/places «{cuerpo['nombre']}»")
        return str(lugar["id"])

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
        return " · ".join(
            (
                comun.borrar_restos(self.api, self.token(), self.backend),
                comun.borrar_lugares_restos(self.api, self.token()),
            )
        )

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

    def _borrar_lugares(self) -> str:
        propios = [str(lugar["id"]) for lugar in comun.lugares_validacion(self.api, self.token(), self.prefijo)]
        if not propios and not self.lugares:
            return "sin lugares de prueba"
        comun.borrar_lugares(self.api, self.token(), [*propios, *(i for i in self.lugares if i not in propios)])
        return f"lugares de prueba borrados: {len(propios)}"

    def _borrar_videos(self) -> str:
        pendientes = [v for v in self.creados if v not in self.borrados]
        if not pendientes:
            return "sin videos de prueba"
        existentes = [v for v in pendientes if self._existe(v)]
        if not existentes:
            return "los videos de prueba ya no existen"
        tarea = comun.limpiar_videos(self.backend, existentes)
        if tarea.codigo != 0:
            raise Falla(f"limpiar-validacion terminó con {tarea.codigo}: {comun.motivo_cli(tarea)}")
        self.borrados.update(existentes)
        resumen = comun.linea_limpieza(tarea)
        return f"videos de prueba borrados: {json.dumps(resumen) if resumen else len(existentes)}"

    def limpiar(self) -> str:
        partes: list[str] = []
        fallos: list[str] = []
        try:
            try:
                partes.append(self._restaurar_embedding())
            except Exception as exc:
                fallos.append(f"embedding NO quedó como estaba ({comun._resumen(exc)}): apágalo a mano (§5 paso 7)")
            if self.api is not None and self._token is not None:  # sin sesión de admin no se creó nada
                for paso, nombre in ((self._borrar_videos, "videos"), (self._borrar_lugares, "lugares")):
                    try:
                        partes.append(paso())
                    except Exception as exc:
                        fallos.append(f"{nombre}: {comun._resumen(exc)}")
            if fallos:
                raise Falla(" · ".join(partes + fallos))
            return " · ".join(partes)
        finally:
            if self.api is not None:
                self.api.cerrar()
            if self.recorrido is not None:
                self.recorrido.cerrar()


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
    faltan = [lote for lote in ("BE-2.2", "BE-3.1") if not comun.lote_hecho(plan, lote)]
    if faltan:
        raise PrecondicionNoCumplida(f"{' y '.join(faltan)} no está «Hecho» en BACKEND_FASTAPI/docs/PLAN.md §3")
    ahora = comun.hora_bogota(ctx.ahora())
    if incluida(ctx.solo, "C1a") and ahora.hour >= HORA_LIMITE:
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
    return f'BE-2.2 y BE-3.1 «Hecho» · {url} · /v1/health/ready → "db": "ok" · {ahora:%H:%M} en Bogotá'


def p3_login_y_endpoints(ctx: Contexto) -> str:
    ctx.admin = comun.credenciales_admin(ctx.entorno, ctx.sesion)
    respuesta = ctx.api.login(*ctx.admin)
    if respuesta.status_code == 401:
        raise ErrorConfiguracion("las credenciales del admin no valen (401 CREDENCIALES_INVALIDAS)")
    if respuesta.status_code != 200:
        raise PrecondicionNoCumplida(f"BE-1.3: el login respondió {comun.describir_respuesta(respuesta)}")
    cuerpo = respuesta.json()
    if (cuerpo.get("usuario") or {}).get("rol") != "admin":
        raise ErrorConfiguracion("el usuario de VALIDACION_ADMIN_* no es admin")
    ctx._token = cuerpo["token"]
    stats = ctx.pedir("GET", comun.RUTA_STATS)
    if stats.status_code == 404:
        raise PrecondicionNoCumplida("BE-2.3 sin desplegar: GET /v1/admin/stats respondió 404")
    if stats.status_code != 200:
        raise PrecondicionNoCumplida(f"GET /v1/admin/stats respondió {comun.describir_respuesta(stats)}")
    lugares = ctx.pedir("GET", comun.RUTA_LUGARES_ADMIN)
    if lugares.status_code != 200:
        raise PrecondicionNoCumplida(f"BE-3.1: GET /v1/admin/places respondió {comun.describir_respuesta(lugares)}")
    return "login admin 200 (rol admin) · GET /v1/admin/stats → 200 · GET /v1/admin/places → 200"


def p4_recursos(ctx: Contexto) -> str:
    from botocore.exceptions import ClientError

    outputs = ctx.outputs()
    faltan = [n for n in ("bucket_dataset", "sqs_ingesta_url") if not outputs.get(n)]
    if faltan:
        raise PrecondicionNoCumplida(f"INF-1.2: faltan los outputs {', '.join(faltan)}")
    ctx.bucket, ctx.url_ingesta = outputs["bucket_dataset"], outputs["sqs_ingesta_url"]
    ctx.s3, ctx.sqs = ctx.sesion.client("s3"), ctx.sesion.client("sqs")
    comun.comprobar_bucket(ctx.s3, ctx.bucket)
    comun.mensajes_cola(ctx.sqs, ctx.url_ingesta)  # permiso de lectura de la cola (si no, 3 aquí y no en C1a)
    comun.red_tareas(outputs)
    try:
        worker = ctx.backend.revision(comun.FAMILIA_WORKER)
    except ClientError as exc:
        if comun.es_acceso_denegado(exc):
            raise ErrorConfiguracion("sin permiso para describir las definiciones de tarea") from None
        raise PrecondicionNoCumplida(
            f"INF-1.3: falta una definición de tarea ({comun.codigo_error_aws(exc)})"
        ) from None
    except Falla as exc:  # worker con otra imagen que api: backend.yml no terminó
        raise PrecondicionNoCumplida(f"BE-2.3 sin desplegar del todo: {exc}") from None
    detalle = f"bucket, ingesta y {worker.rsplit('/', 1)[-1]} con la imagen de api"
    if incluida(ctx.solo, "C1a"):
        detalle += f" · INF-2.1: {ctx.emb.comprobar_inf21()}"
    return detalle


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
def c1a_total_fotos(ctx: Contexto) -> str:
    cola = ctx.esperar_ingesta_vacia()
    s0 = ctx.resumen("s0")
    recorrido = ctx.asegurar_video()
    registro = recorrido.registrar(list(ORDENES))
    _esperar(registro, 200, "POST …/images")
    pendientes = ctx.resumen("con las fotos registradas")
    exigir(
        pendientes["total_fotos"] == s0["total_fotos"],
        f"con 2 fotos pendiente_subida, total_fotos pasó de {s0['total_fotos']} a {pendientes['total_fotos']} "
        "(solo cuentan las procesada)",
    )
    for orden in ORDENES:
        r = recorrido.subir(orden)
        exigir(r.status_code == 200, f"PUT de la foto {orden}: {r.status_code}, se esperaba 200")
    minutos = ctx.esperar_procesadas()
    s1 = ctx.resumen("s1")
    diferencia = s1["total_fotos"] - s0["total_fotos"]
    exigir(
        diferencia == len(ORDENES),
        f"total_fotos s0 = {s0['total_fotos']}, s1 = {s1['total_fotos']}: subió {diferencia}, se esperaba "
        f"{len(ORDENES)} (¿actividad ajena en dev? s0 = {json.dumps(s0)}, s1 = {json.dumps(s1)})",
    )
    return (
        f"{cola} · total_fotos s0 = {s0['total_fotos']} · con 2 fotos registradas sin subir, igual · fotos 1–2 en "
        f"procesada en {minutos:.1f} min · s1 = {s1['total_fotos']} (+{diferencia})"
    )


def c1b_total_lugares(ctx: Contexto) -> str:
    antes = ctx.resumen("antes de los lugares")
    ctx.crear_lugar("a")
    b = ctx.crear_lugar("b")
    con_dos = ctx.resumen("con los dos lugares")
    subida = con_dos["total_lugares"] - antes["total_lugares"]
    exigir(
        subida == 2,
        f"total_lugares {antes['total_lugares']} → {con_dos['total_lugares']} al crear 2 lugares, se esperaba +2",
    )
    _esperar(ctx.pedir("DELETE", f"{comun.RUTA_LUGARES_ADMIN}/{b}"), 204, "DELETE del lugar b")
    con_uno = ctx.resumen("tras borrar uno")
    exigir(
        con_uno["total_lugares"] == con_dos["total_lugares"] - 1,
        f"total_lugares {con_dos['total_lugares']} → {con_uno['total_lugares']} al borrar 1, se esperaba −1",
    )
    return (
        f"total_lugares {antes['total_lugares']} → {con_dos['total_lugares']} (+2, lugares a y b) → "
        f"{con_uno['total_lugares']} (−1, b borrado)"
    )


def c1c_ultimo_video(ctx: Contexto) -> str:
    video = ctx.asegurar_video().video
    resumen = ctx.resumen("C1c")
    ultimo = resumen["ultimo_video"]
    exigir(isinstance(ultimo, dict), f"ultimo_video = {ultimo!r}, se esperaba el video de prueba")
    exigir(set(ultimo) == comun.CAMPOS_ULTIMO_VIDEO, f"campos de ultimo_video: {sorted(ultimo)}")
    exigir(
        isinstance(ultimo["creado_en"], str) and comun.PATRON_FECHA_UTC.match(ultimo["creado_en"]),
        f"ultimo_video.creado_en = {ultimo['creado_en']!r}: se esperaba UTC con Z y sin fracciones (§5.1)",
    )
    esperado = {"numero": video["numero"], "creado_en": video["creado_en"]}
    exigir(
        ultimo == esperado,
        f"ultimo_video = {json.dumps(ultimo)}, se esperaba el del video de prueba {json.dumps(esperado)} "
        "(¿otro video creado en dev durante la ejecución?)",
    )
    return (
        f"ultimo_video = numero {ultimo['numero']}, creado_en {ultimo['creado_en']} (el video de prueba) · "
        f"alertas_activas = {resumen['alertas_activas']} (entero ≥ 0) · campos exactos de §5.5"
    )


def main(argv: list[str] | None = None, ctx: Contexto | None = None) -> int:
    validador = comun.Validador(lote=LOTE, validacion="validation-2-3", entornos=("dev",), descripcion=__doc__)
    argumentos = validador.iniciar(argv)
    ctx = ctx or Contexto(argumentos.entorno)
    ctx.solo = argumentos.solo
    precondiciones = [
        ("P1", lambda: p1_credenciales(ctx)),
        ("P2", lambda: p2_lotes_y_hora(ctx)),
        ("P3", lambda: p3_login_y_endpoints(ctx)),
        ("P4", lambda: p4_recursos(ctx)),
    ]
    if incluida(ctx.solo, "C1a"):  # solo C1a necesita fotos procesadas
        precondiciones.append(("P5", lambda: p5_embedding(ctx)))
    return validador.ejecutar(
        precondiciones=precondiciones,
        preparacion=ctx.preparacion,
        comprobaciones=[
            ("C1a", lambda: c1a_total_fotos(ctx)),
            ("C1b", lambda: c1b_total_lugares(ctx)),
            ("C1c", lambda: c1c_ultimo_video(ctx)),
        ],
        manuales=[],
        limpieza=ctx.limpiar,
    )


if __name__ == "__main__":
    sys.exit(main())
