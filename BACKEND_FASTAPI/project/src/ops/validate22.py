"""BE-2.2 — Worker de ingesta. Fotos subidas → `procesada` con vector y miniatura; JPEG corrupto → `error` sin DLQ;
evento duplicado sin segundo vector; `reprocesar_imagen`; y, con `embedding` apagado, mensajes que esperan en la cola
y se procesan al encender.

Documento: BACKEND_FASTAPI/docs/validation/validation-2-2.md · criterios: BACKEND_FASTAPI/docs/PLAN.md §2.2.

    cd BACKEND_FASTAPI/project
    uv run --group ops python src/ops/validate22.py --entorno dev

Variables: AWS_PROFILE (obligatoria); VALIDACION_API_URL, VALIDACION_ADMIN_CORREO y VALIDACION_ADMIN_PASSWORD
(opcionales). Solo `dev` (S3 y SQS no se emulan en local). Empieza antes de las 21:00 de Bogotá: dura 35–60 min y
`embedding` se apaga solo a las 22:00. Enciende `embedding` si está apagado (contrato de infra §5.10) y al terminar lo
deja como lo encontró; C3 lo apaga un rato con `update-service`. Crea el video `validacion-22-<sello>` (6 fotos) y lo
borra con `limpiar-validacion`. Envía a `ingesta` dos mensajes que solo nombran fotos de ese video. Nunca imprime
contraseñas, tokens ni URLs prefirmadas.
"""

from __future__ import annotations

import io
import json
import os
import sys
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import comun
from comun import ErrorConfiguracion, Falla, PrecondicionNoCumplida, exigir, lote_hecho

LOTE = "BE-2.2"
INICIADA_POR = "validate22"
N_FOTOS = 6
LAT, LNG = 1.0, -100.0  # fuera del campus (océano Pacífico)
VERSION_VECTOR = "dinov2-vits14/pp-v1"  # EMBEDDING_VERSION_VECTOR (backend §5.10)
MINIATURA_LADO_PX = 320
NO_ES_JPEG = b"validacion-no-es-jpeg"
LIMITE_PROCESADO_S = 20 * 60  # la subida de `worker` puede tardar de 2 a 15 min (infra ADR-INF-15) + arranque
LIMITE_CONSUMO_S = 5 * 60
LIMITE_APAGADO_S = 5 * 60
GUARDA_APAGADO_S = 45  # espera larga (20 s) + pausa del worker (15 s) + TTL del DNS de embedding (10 s)
MUESTREO_C3_S = 6 * 60  # 2 × visibilidad de `ingesta` (180 s)
PAUSA_MUESTREO_S = 30.0
PAUSA_SONDEO_S = 15.0
HORA_LIMITE = 21  # America/Bogota: empezar antes (P4)
MARGEN_C3_MIN = 25  # C3 necesita ~20 min antes de las 22:00
PLAN_EMBEDDING = comun.RAIZ_REPO / "SERVICE_EMBEDDING" / "docs" / "PLAN.md"


def avisar(mensaje: str) -> None:
    print(mensaje, file=sys.stderr, flush=True)


def _esperar(respuesta: Any, estado: int, que: str) -> Any:
    exigir(respuesta.status_code == estado, f"{que}: {comun.describir_respuesta(respuesta)}, se esperaba {estado}")
    return respuesta.json()


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
        self.logs: Any = None
        self.bucket: str | None = None
        self.url_ingesta: str | None = None
        self.url_dlq: str | None = None
        self.admin: tuple[str, str] | None = None
        self.admin_id: str | None = None
        self.dormir: Callable[[float], None] = time.sleep
        self.ahora: Callable[[], datetime] = lambda: datetime.now(UTC)
        self.http: Any = None
        self.http_s3: Any = None
        self.sello = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        self._outputs: dict[str, Any] | None = None
        self._token: str | None = None
        self.principal: comun.RecorridoPrueba | None = None
        self.creados: list[str] = []
        self.borrados: set[str] = set()
        self.estaba_encendido: bool | None = None  # cómo se encontró `embedding` (P6)
        self.encendido_por_mi = False
        self.vectores: dict[str, str] = {}  # imagen_id → creado_en del vector (segundos Unix, texto de psql), de C1b
        self.dlq_inicial: int | None = None

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
    def nombre(self) -> str:
        return f"{comun.PREFIJO_VALIDACION}22-{self.sello}"

    def semilla(self) -> int:
        return int(self.sello.replace("-", "")) % 1_000_000

    def listo_en_api(self) -> bool:
        return comun.embedding_en_api(self.api) == "ok"

    # -- video de prueba ---------------------------------------------------------------------------------------------
    def asegurar_video(self) -> comun.RecorridoPrueba:
        if self.principal is None:
            recorrido = comun.RecorridoPrueba(
                self.api,
                self.token,
                self.nombre,
                total_fotos=N_FOTOS,
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
        """`orden → ImagenAdmin` del detalle del video."""
        video_id = self.asegurar_video().video_id
        detalle = _esperar(self.pedir("GET", f"/admin/videos/{video_id}"), 200, "GET /v1/admin/videos/{id}")
        return {int(f["orden"]): f for f in detalle.get("fotos", [])}

    def imagen_id(self, orden: int) -> str:
        return str(self.asegurar_video().registro[orden]["id"])

    def esperar_estados(self, ordenes: list[int], estado: str, limite_s: float, que: str) -> dict[int, dict]:
        """Sondea el detalle cada 15 s hasta que las fotos `ordenes` estén en `estado` (o en `error`, que es `Falla`
        si no es lo esperado)."""
        hasta = self.ahora() + timedelta(seconds=limite_s)
        while True:
            fotos = self.fotos()
            actuales = {o: fotos.get(o, {}).get("estado") for o in ordenes}
            if estado != "error":
                for orden, actual in actuales.items():
                    exigir(actual != "error", f"{que}: la foto {orden} quedó en error ({fotos[orden].get('error')!r})")
            if all(actual == estado for actual in actuales.values()):
                return fotos
            if self.ahora() >= hasta:
                raise Falla(f"{que}: tras {limite_s / 60:.0f} min, estados {actuales}, se esperaba {estado}")
            self.dormir(PAUSA_SONDEO_S)

    def asegurar_procesadas(self, ordenes: list[int]) -> None:
        recorrido = self.asegurar_video()
        recorrido.asegurar_subidas(ordenes)
        self.esperar_estados(ordenes, "procesada", LIMITE_PROCESADO_S, "procesado")

    # -- SQL, colas y logs ---------------------------------------------------------------------------------------------
    def sql(self, consulta: str) -> list[list[str]]:
        return [linea.split("|") for linea in self.backend.sql(consulta) if linea.strip()]

    def leer_vectores(self, ids: list[str]) -> dict[str, list[tuple[str, str]]]:
        lista = ", ".join(f"'{uuid.UUID(i)}'" for i in ids)  # UUID validado: sin inyección
        # creado_en en segundos Unix: se compara como número, sin depender del formato de psql
        columnas = "imagen_id, version_vector, extract(epoch FROM creado_en)"
        consulta = f"SELECT {columnas} FROM embeddings WHERE imagen_id IN ({lista}) ORDER BY 1, 2"  # noqa: S608
        filas = self.sql(consulta)
        resultado: dict[str, list[tuple[str, str]]] = {i: [] for i in ids}
        for fila in filas:
            exigir(len(fila) == 3, f"fila de psql inesperada: {'|'.join(fila)[:80]}")
            resultado.setdefault(fila[0], []).append((fila[1], fila[2]))
        return resultado

    def vector_de(self, orden: int) -> str:
        """`creado_en` del (único) vector de la foto, de C1b o con otra consulta (con `--solo`)."""
        imagen_id = self.imagen_id(orden)
        if imagen_id not in self.vectores:
            filas = self.leer_vectores([imagen_id])[imagen_id]
            exigir(len(filas) == 1, f"la foto {orden} tiene {len(filas)} vectores")
            self.vectores[imagen_id] = filas[0][1]
        return self.vectores[imagen_id]

    def dlq(self) -> int:
        return sum(comun.mensajes_cola(self.sqs, self.url_dlq))

    def esperar_evento(self, imagen_id: str, desde: datetime, aceptar: Callable[[dict], bool], que: str) -> dict:
        hasta = self.ahora() + timedelta(seconds=LIMITE_CONSUMO_S)
        while True:
            for evento in comun.eventos_worker(self.logs, imagen_id, desde - timedelta(seconds=60)):
                if aceptar(evento):
                    return evento
            if self.ahora() >= hasta:
                raise Falla(f"{que}: el worker no lo registró en {LIMITE_CONSUMO_S // 60} min")
            self.dormir(PAUSA_SONDEO_S)

    def evento_s3(self, orden: int) -> dict[str, Any]:
        """El evento de S3 de §5.8 para el objeto ya subido de la foto `orden` (ETag y tamaño reales)."""
        clave = f"dataset/{self.asegurar_video().video_id}/{self.imagen_id(orden)}.jpg"
        objeto = comun.head_objeto(self.s3, self.bucket, clave)
        exigir(objeto is not None, f"no existe {clave}")
        registro = {
            "eventName": "ObjectCreated:Put",
            "s3": {
                "bucket": {"name": self.bucket},
                "object": {"key": clave, "size": int(objeto["ContentLength"]), "eTag": objeto["ETag"].strip('"')},
            },
        }
        return {"Records": [registro]}

    # -- embedding ---------------------------------------------------------------------------------------------------
    def asegurar_embedding(self) -> str:
        """Encendido (contrato de §5.10) si no lo está; si ya lo estaba, solo un latido (aleja el apagado por
        inactividad)."""
        datos = self.emb.servicio(comun.SERVICIO_EMBEDDING)
        if int(datos.get("desiredCount", 0)) >= 1 and self.listo_en_api():
            self.emb.latido()
            return "ya encendido (latido publicado)"
        segundos = self.emb.encender(self.listo_en_api)
        return f"encendido en {segundos:.0f} s"

    # -- limpieza ----------------------------------------------------------------------------------------------------
    def restos(self) -> str:
        return comun.borrar_restos(self.api, self.token(), self.backend)

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
        fallo_embedding = False
        try:
            try:
                partes.append(self._restaurar_embedding())
            except Exception as exc:
                fallo_embedding = True
                partes.append(f"embedding NO quedó como estaba ({comun._resumen(exc)}): apágalo a mano (§5 paso 7)")
            pendientes = [v for v in self.creados if v not in self.borrados]
            existentes = [v for v in pendientes if self._existe(v)] if pendientes else []
            if not pendientes:
                partes.append("nada que borrar")
            elif not existentes:
                partes.append("los videos de prueba ya no existen")
            else:
                tarea = comun.limpiar_videos(self.backend, existentes)
                if tarea.codigo != 0:
                    motivo = comun.motivo_cli(tarea)
                    raise Falla(f"{' · '.join(partes)} · limpiar-validacion terminó con {tarea.codigo}: {motivo}")
                self.borrados.update(existentes)
                resumen = comun.linea_limpieza(tarea)
                partes.append(f"videos de prueba borrados: {json.dumps(resumen) if resumen else len(existentes)}")
            if fallo_embedding:
                raise Falla(" · ".join(partes))
            return " · ".join(partes)
        finally:
            if self.api is not None:
                self.api.cerrar()
            if self.principal is not None:
                self.principal.cerrar()

    def _existe(self, video_id: str) -> bool:
        r = self.pedir("GET", f"/admin/videos/{video_id}")
        if r.status_code == 404:
            return False
        exigir(r.status_code == 200, f"GET /v1/admin/videos/{{id}}: {comun.describir_respuesta(r)}")
        return True


# --- Precondiciones ------------------------------------------------------------------------------------------------
def p1_credenciales(ctx: Contexto) -> str:
    ctx.sesion = comun.sesion_aws()
    arn = comun.verificar_cuenta(ctx.sesion)
    ctx.emb = comun.EmbeddingDev(ctx.sesion, dormir=ctx.dormir, reloj=ctx.ahora, avisar=avisar)
    return f"cuenta {comun.CUENTA_AWS} ({arn.rsplit('/', 1)[-1]})"


def p2_recoleccion(ctx: Contexto) -> str:
    import httpx

    url = comun.url_api(None if os.environ.get("VALIDACION_API_URL", "").strip() else ctx.outputs())
    ctx.preparar(url)
    try:
        salud = ctx.api.pedir("GET", "/health")
    except httpx.HTTPError as exc:
        raise PrecondicionNoCumplida(f"BE-1.1: GET /v1/health no respondió ({type(exc).__name__})") from None
    if salud.status_code != 200:
        raise PrecondicionNoCumplida(f"BE-1.1: GET /v1/health respondió {comun.describir_respuesta(salud)}")
    ctx.admin = comun.credenciales_admin(ctx.entorno, ctx.sesion)
    respuesta = ctx.api.login(*ctx.admin)
    if respuesta.status_code == 401:
        raise ErrorConfiguracion("las credenciales del admin no valen (401 CREDENCIALES_INVALIDAS)")
    if respuesta.status_code != 200:
        raise PrecondicionNoCumplida(f"BE-1.3: el login respondió {comun.describir_respuesta(respuesta)}")
    cuerpo = respuesta.json()
    if cuerpo.get("usuario", {}).get("rol") != "admin":
        raise ErrorConfiguracion("el usuario de VALIDACION_ADMIN_* no es admin")
    ctx._token, ctx.admin_id = cuerpo["token"], str(cuerpo["usuario"]["id"])
    elemento = {"orden": 1, "lat": LAT, "lng": LNG, "rumbo": 0.0, "capturada_en": "2026-10-20T14:00:01Z", "bytes": 1}
    r = ctx.pedir("POST", f"/collect/videos/{uuid.uuid4()}/images", json={"imagenes": [elemento]})
    if not (r.status_code == 404 and comun.codigo_error(r) == "NO_ENCONTRADO"):
        raise PrecondicionNoCumplida(f"BE-2.1: images de un video inexistente respondió {comun.describir_respuesta(r)}")
    return f"{url} · commit {salud.json().get('commit')} · login admin 200 · images de un video inexistente → 404"


def p3_embeddings(ctx: Contexto) -> str:
    try:
        texto = PLAN_EMBEDDING.read_text(encoding="utf-8")
    except OSError:
        raise ErrorConfiguracion(f"no se pudo leer {PLAN_EMBEDDING}") from None
    if not lote_hecho(texto, "EMB-2.1"):
        raise PrecondicionNoCumplida("EMB-2.1 no está «Hecho» en SERVICE_EMBEDDING/docs/PLAN.md §3")
    return "EMB-2.1 «Hecho» en SERVICE_EMBEDDING/docs/PLAN.md §3"


def p4_escalado_y_hora(ctx: Contexto) -> str:
    detalle = ctx.emb.comprobar_inf21()
    ahora = comun.hora_bogota(ctx.ahora())
    if ahora.hour >= HORA_LIMITE:
        raise ErrorConfiguracion(
            f"son las {ahora:%H:%M} en Bogotá: empieza antes de las {HORA_LIMITE}:00 (embedding se apaga a las 22:00)"
        )
    return f"INF-2.1: {detalle} · {ahora:%H:%M} en Bogotá (antes de las {HORA_LIMITE}:00)"


def p5_recursos(ctx: Contexto) -> str:
    from botocore.exceptions import ClientError

    outputs = ctx.outputs()
    faltan = [n for n in ("sqs_ingesta_url", "sqs_ingesta_dlq_url", "bucket_dataset") if not outputs.get(n)]
    if faltan:
        raise PrecondicionNoCumplida(f"INF-1.2: faltan los outputs {', '.join(faltan)}")
    ctx.url_ingesta, ctx.url_dlq, ctx.bucket = (
        outputs["sqs_ingesta_url"],
        outputs["sqs_ingesta_dlq_url"],
        outputs["bucket_dataset"],
    )
    ctx.s3, ctx.sqs, ctx.logs = ctx.sesion.client("s3"), ctx.sesion.client("sqs"), ctx.sesion.client("logs")
    comun.comprobar_bucket(ctx.s3, ctx.bucket)
    comun.mensajes_cola(ctx.sqs, ctx.url_ingesta)
    comun.red_tareas(outputs)
    try:
        ctx.backend.imagen(comun.FAMILIA_VALIDACION)
        revision = ctx.backend.revision(comun.FAMILIA_WORKER)
    except ClientError as exc:
        if comun.es_acceso_denegado(exc):
            raise ErrorConfiguracion("sin permiso para describir las definiciones de tarea") from None
        raise PrecondicionNoCumplida(
            f"INF-1.3: falta una definición de tarea ({comun.codigo_error_aws(exc)})"
        ) from None
    except Falla as exc:  # worker con otra imagen que api: backend.yml no desplegó BE-2.2 del todo
        raise PrecondicionNoCumplida(f"BE-2.2 sin desplegar del todo: {exc}") from None
    return (
        f"colas ingesta y DLQ, bucket, {comun.FAMILIA_VALIDACION} y {revision.rsplit('/', 1)[-1]} con la imagen de api"
    )


def p6_embedding(ctx: Contexto) -> str:
    datos = ctx.emb.servicio(comun.SERVICIO_EMBEDDING)
    ctx.estaba_encendido = int(datos.get("desiredCount", 0)) >= 1
    ctx.encendido_por_mi = not ctx.estaba_encendido  # se marca antes de encender: la limpieza lo apaga igual
    try:
        detalle = ctx.asegurar_embedding()
    except Falla as exc:
        raise PrecondicionNoCumplida(f"EMB-2.1/INF-2.1: embedding no quedó listo: {exc}") from None
    return f'embedding {detalle} · /v1/health/ready → "embedding": "ok"'


# --- Comprobaciones ------------------------------------------------------------------------------------------------
def c1a_procesadas(ctx: Contexto) -> str:
    inicio = ctx.ahora()
    ctx.asegurar_procesadas([1, 2, 3])
    minutos = (ctx.ahora() - inicio).total_seconds() / 60
    return f"video {ctx.principal.video_id}: fotos 1–3 subidas y en procesada en {minutos:.1f} min"


def c1b_vectores(ctx: Contexto) -> str:
    ctx.asegurar_procesadas([1, 2, 3])
    ids = [ctx.imagen_id(o) for o in (1, 2, 3)]
    vectores = ctx.leer_vectores(ids)
    for orden, imagen_id in zip((1, 2, 3), ids, strict=True):
        filas = vectores.get(imagen_id, [])
        exigir(len(filas) == 1, f"la foto {orden} tiene {len(filas)} vectores, se esperaba 1")
        exigir(filas[0][0] == VERSION_VECTOR, f"la foto {orden}: version_vector {filas[0][0]!r}")
        ctx.vectores[imagen_id] = filas[0][1]
    return f"un vector por foto con version_vector = {VERSION_VECTOR}"


def c1c_miniaturas(ctx: Contexto) -> str:
    from PIL import Image

    ctx.asegurar_procesadas([1, 2, 3])
    tamanos = []
    for orden in (1, 2, 3):
        clave = f"thumbs/{ctx.principal.video_id}/{ctx.imagen_id(orden)}.jpg"
        try:
            datos = ctx.s3.get_object(Bucket=ctx.bucket, Key=clave)["Body"].read()
        except Exception as exc:
            raise Falla(f"no se pudo leer {clave}: {comun.codigo_error_aws(exc) or type(exc).__name__}") from None
        try:
            imagen = Image.open(io.BytesIO(datos))
            imagen.load()
        except Exception:
            raise Falla(f"{clave} no se decodifica como imagen") from None
        exigir(imagen.format == "JPEG", f"{clave}: formato {imagen.format}")
        exigir(max(imagen.size) <= MINIATURA_LADO_PX, f"{clave}: {imagen.size[0]}×{imagen.size[1]} px")
        tamanos.append(f"{imagen.size[0]}×{imagen.size[1]}")
    return f"3 miniaturas JPEG ({', '.join(tamanos)}), lado mayor ≤ {MINIATURA_LADO_PX} px"


def c2_corrupto(ctx: Contexto) -> str:
    recorrido = ctx.asegurar_video()
    ctx.dlq_inicial = ctx.dlq()
    _esperar(recorrido.registrar([4]), 200, "POST …/images (foto 4)")
    subida = recorrido.registro[4].get("subida")
    exigir(subida, "la foto 4 no recibió URL")
    r = comun.put_prefirmado(recorrido.http_s3, subida, NO_ES_JPEG, que="la foto 4 (no es JPEG)")
    exigir(r.status_code == 200, f"PUT de la foto 4: {r.status_code}, se esperaba 200")
    fotos = ctx.esperar_estados([4], "error", LIMITE_PROCESADO_S, "C2")
    motivo = fotos[4].get("error")
    exigir(isinstance(motivo, str) and motivo.strip(), "la foto 4 está en error sin motivo")
    despues = ctx.dlq()
    exigir(despues == ctx.dlq_inicial, f"la DLQ pasó de {ctx.dlq_inicial} a {despues} mensajes")
    return f"foto 4 en error ({motivo!r}) · DLQ con {despues} mensajes, como antes"


def c4_duplicado(ctx: Contexto) -> str:
    ctx.asegurar_procesadas([1])
    antes = ctx.vector_de(1)
    dlq = ctx.dlq()
    imagen_id = ctx.imagen_id(1)
    envio = ctx.ahora()
    comun.enviar_mensaje(ctx.sqs, ctx.url_ingesta, ctx.evento_s3(1))
    ctx.esperar_evento(
        imagen_id,
        envio,
        lambda e: e.get("evento") == "mensaje_descartado" and e.get("motivo") == "duplicado",
        "evento duplicado de la foto 1",
    )
    filas = ctx.leer_vectores([imagen_id])[imagen_id]
    exigir(len(filas) == 1, f"la foto 1 tiene {len(filas)} vectores tras el duplicado")
    exigir(filas[0][1] == antes, f"creado_en del vector cambió ({antes} → {filas[0][1]})")
    exigir(ctx.dlq() == dlq, "la DLQ cambió")
    return "evento repetido consumido (mensaje_descartado: duplicado) · 1 vector, creado_en sin cambios · DLQ igual"


def c5_reprocesar(ctx: Contexto) -> str:
    ctx.asegurar_procesadas([2])
    antes = ctx.vector_de(2)
    imagen_id = ctx.imagen_id(2)
    envio = ctx.ahora()
    cuerpo = {
        "tipo": "reprocesar_imagen",
        "version": 1,
        "imagen_id": imagen_id,
        "solicitado_por": ctx.admin_id or str(uuid.uuid4()),
        "solicitado_en": envio.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    comun.enviar_mensaje(ctx.sqs, ctx.url_ingesta, cuerpo)
    ctx.esperar_evento(
        imagen_id,
        envio,
        lambda e: e.get("evento") == "imagen_procesada" and e.get("origen") == "reprocesar",
        "reprocesar_imagen de la foto 2",
    )
    union = "embeddings e JOIN imagenes i ON i.id = e.imagen_id"
    filtro = f"e.imagen_id = '{uuid.UUID(imagen_id)}'"  # UUID validado: sin inyección
    consulta = f"SELECT extract(epoch FROM e.creado_en), i.estado FROM {union} WHERE {filtro}"  # noqa: S608
    filas = ctx.sql(consulta)
    exigir(len(filas) == 1, f"la foto 2 tiene {len(filas)} vectores tras reprocesar")
    creado, estado = filas[0][0], filas[0][1]
    exigir(estado == "procesada", f"la foto 2 quedó en {estado}")
    exigir(float(creado) > float(antes), f"creado_en no avanzó ({antes} → {creado}, segundos Unix)")
    ctx.vectores[imagen_id] = creado
    return "vector regenerado (un solo vector, creado_en posterior) · foto 2 procesada"


def c3a_apagado(ctx: Contexto) -> str:
    ahora = comun.hora_bogota(ctx.ahora())
    limite = ahora.replace(hour=comun.HORA_APAGADO_NOCHE, minute=0, second=0, microsecond=0)
    exigir(
        (limite - ahora) >= timedelta(minutes=MARGEN_C3_MIN),
        f"son las {ahora:%H:%M} en Bogotá: C3 necesita {MARGEN_C3_MIN} min antes de las 22:00",
    )
    recorrido = ctx.asegurar_video()
    if ctx.dlq_inicial is None:
        ctx.dlq_inicial = ctx.dlq()
    exigir(ctx.listo_en_api(), 'antes de C3a, /v1/health/ready no dice "embedding": "ok"')
    worker_antes = int(ctx.emb.servicio(comun.SERVICIO_WORKER).get("runningCount", 0))
    ctx.emb.poner(comun.SERVICIO_EMBEDDING, 0)
    hasta = ctx.ahora() + timedelta(seconds=LIMITE_APAGADO_S)
    while not (
        comun.embedding_en_api(ctx.api) == "no_disponible"
        and int(ctx.emb.servicio(comun.SERVICIO_EMBEDDING).get("runningCount", 0)) == 0
    ):
        exigir(ctx.ahora() < hasta, f"embedding no se apagó en {LIMITE_APAGADO_S // 60} min")
        ctx.dormir(PAUSA_SONDEO_S)
    ctx.dormir(GUARDA_APAGADO_S)
    recorrido.asegurar_subidas([5, 6])
    muestras = []
    fin = ctx.ahora() + timedelta(seconds=MUESTREO_C3_S)
    while ctx.ahora() < fin:
        ctx.dormir(PAUSA_MUESTREO_S)
        visibles, en_vuelo = comun.mensajes_cola(ctx.sqs, ctx.url_ingesta)
        muestras.append((visibles, en_vuelo))
        exigir(en_vuelo == 0, f"con embedding apagado hay {en_vuelo} mensajes en vuelo (muestra {len(muestras)})")
        exigir(visibles >= 2, f"solo {visibles} mensajes visibles en ingesta (muestra {len(muestras)})")
    worker_despues = int(ctx.emb.servicio(comun.SERVICIO_WORKER).get("runningCount", 0))
    if worker_antes >= 1:
        exigir(worker_despues >= 1, f"worker pasó de {worker_antes} a {worker_despues} tareas durante C3a")
    fotos = ctx.fotos()
    for orden in (5, 6):
        exigir(fotos[orden]["estado"] != "procesada", f"la foto {orden} se procesó con embedding apagado")
    visibles = min(v for v, _ in muestras)
    return (
        f"{len(muestras)} muestras en {MUESTREO_C3_S // 60} min: ≥ {visibles} visibles y 0 en vuelo · worker con "
        f"{worker_despues} tarea(s) · fotos 5 y 6 sin procesar"
    )


def c3b_encendido(ctx: Contexto) -> str:
    datos = ctx.emb.servicio(comun.SERVICIO_EMBEDDING)
    if int(datos.get("desiredCount", 0)) < 1 or not ctx.listo_en_api():
        ctx.emb.encender(ctx.listo_en_api)
    if ctx.dlq_inicial is None:
        ctx.dlq_inicial = ctx.dlq()
    inicio = ctx.ahora()
    ctx.asegurar_video().asegurar_subidas([5, 6])
    ctx.esperar_estados([5, 6], "procesada", LIMITE_PROCESADO_S, "C3b")
    minutos = (ctx.ahora() - inicio).total_seconds() / 60
    despues = ctx.dlq()
    exigir(despues == ctx.dlq_inicial, f"la DLQ pasó de {ctx.dlq_inicial} a {despues} mensajes")
    return f"embedding ok · fotos 5 y 6 procesadas {minutos:.1f} min después · DLQ con {despues}, como antes"


def main(argv: list[str] | None = None, ctx: Contexto | None = None) -> int:
    validador = comun.Validador(lote=LOTE, validacion="validation-2-2", entornos=("dev",), descripcion=__doc__)
    argumentos = validador.iniciar(argv)
    ctx = ctx or Contexto(argumentos.entorno)
    return validador.ejecutar(
        precondiciones=[
            ("P1", lambda: p1_credenciales(ctx)),
            ("P2", lambda: p2_recoleccion(ctx)),
            ("P3", lambda: p3_embeddings(ctx)),
            ("P4", lambda: p4_escalado_y_hora(ctx)),
            ("P5", lambda: p5_recursos(ctx)),
            ("P6", lambda: p6_embedding(ctx)),
        ],
        preparacion=ctx.restos,
        comprobaciones=[
            ("C1a", lambda: c1a_procesadas(ctx)),
            ("C1b", lambda: c1b_vectores(ctx)),
            ("C1c", lambda: c1c_miniaturas(ctx)),
            ("C2", lambda: c2_corrupto(ctx)),
            ("C4", lambda: c4_duplicado(ctx)),
            ("C5", lambda: c5_reprocesar(ctx)),
            ("C3a", lambda: c3a_apagado(ctx)),
            ("C3b", lambda: c3b_encendido(ctx)),
        ],
        manuales=[],
        limpieza=ctx.limpiar,
    )


if __name__ == "__main__":
    sys.exit(main())
