"""BE-2.1 — Recolección. Crear un video, pedir URLs prefirmadas, subir JPEG a S3, idempotencia, URL vencida, `complete`
con el paso a `subida` sin `worker`, lectura del panel y `limpiar-validacion`.

Documento: BACKEND_FASTAPI/docs/validation/validation-2-1.md · criterios: BACKEND_FASTAPI/docs/PLAN.md §2.2.

    cd BACKEND_FASTAPI/project
    uv run --group ops python src/ops/validate21.py --entorno dev

Variables: AWS_PROFILE (obligatoria); VALIDACION_API_URL, VALIDACION_ADMIN_CORREO y VALIDACION_ADMIN_PASSWORD
(opcionales). Solo `dev`: S3 no se emula en local. Dura unos 20–25 min (C3a espera a que venza una URL de 900 s,
medido con la hora de S3). Crea los videos `validacion-21-<sello>` y `…-b` y los borra con `limpiar-validacion` (tarea
suelta de `worker`); al video ajeno de C6b solo le aplica `--simular`. Nunca imprime contraseñas, tokens ni URLs
prefirmadas: de cada `PUT` solo informa el código de estado.
"""

from __future__ import annotations

import json
import os
import sys
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import comun
from comun import ErrorConfiguracion, Falla, PrecondicionNoCumplida, exigir

LOTE = "BE-2.1"
INICIADA_POR = "validate21"
N_FOTOS = 4
TODAS = list(range(1, N_FOTOS + 1))
LAT, LNG = 1.0, -100.0  # fuera del campus (océano Pacífico): no se mezcla con el dataset real
MARGEN_VENCIMIENTO_S = 10
AVISO_CADA_S = 60.0
ESTADOS_FOTO = ("pendiente_subida", "subida", "procesada", "error")
CAMPOS_RESUMEN = {
    "id",
    "numero",
    "nombre",
    "ref_cliente",
    "estado",
    "creado_en",
    "iniciado_en",
    "finalizado_en",
    "duracion_s",
    "distancia_m",
    "pasos",
    "inicio",
    "total_fotos",
    "conteo",
    "creado_por",
}
CAMPOS_IMAGEN = {
    "id",
    "video_id",
    "orden",
    "lat",
    "lng",
    "rumbo",
    "capturada_en",
    "estado",
    "error",
    "calidad",
    "lugar",
    "notas",
    "url",
    "url_miniatura",
    "url_expira_en",
}


def avisar(mensaje: str) -> None:
    """Progreso a stderr (stdout queda para las líneas `[PASA] …`)."""
    print(mensaje, file=sys.stderr, flush=True)


def _fecha(texto: Any) -> datetime:
    try:
        return datetime.fromisoformat(str(texto).replace("Z", "+00:00"))
    except ValueError:
        raise Falla(f"fecha no ISO-8601: {texto!r}") from None


def _iso(momento: datetime) -> str:
    return momento.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _esperar(respuesta: Any, estado: int, que: str) -> Any:
    if respuesta.status_code == 404 and comun.codigo_error(respuesta) == "NO_ENCONTRADO" and estado != 404:
        raise Falla(f"{que}: 404 NO_ENCONTRADO (¿está desplegado BE-2.1? ¿terminó backend.yml?)")
    exigir(respuesta.status_code == estado, f"{que}: {comun.describir_respuesta(respuesta)}, se esperaba {estado}")
    return respuesta.json()


def _conteo_valido(conteo: Any, que: str) -> dict[str, int]:
    exigir(isinstance(conteo, dict) and set(conteo) == set(ESTADOS_FOTO), f"{que}: claves de conteo {conteo!r}")
    return {clave: int(conteo[clave]) for clave in ESTADOS_FOTO}


def _texto_conteo(conteo: dict[str, int]) -> str:
    return " ".join(f"{clave}={conteo[clave]}" for clave in ESTADOS_FOTO)


def estado_esperado(conteo: dict[str, int], subida_completa: bool = True) -> str:
    """El estado del video que exige §5.5 para un conteo (ADR-BE-14), escrito aparte del backend."""
    if not subida_completa or conteo["pendiente_subida"]:
        return "pendiente"
    if conteo["subida"]:
        return "procesando"
    return "con_errores" if conteo["error"] else "procesado"


def _solo_avanzo_el_worker(antes: dict[str, int], despues: dict[str, int]) -> bool:
    """¿La diferencia se explica solo por el `worker` (fotos `subida` que pasaron a `procesada` o `error`)?"""
    avance = antes["subida"] - despues["subida"]
    return (
        avance >= 0
        and despues["pendiente_subida"] == antes["pendiente_subida"]
        and despues["procesada"] + despues["error"] - antes["procesada"] - antes["error"] == avance
    )


# --- Contexto ------------------------------------------------------------------------------------------------------
class Contexto:
    def __init__(self, entorno: str = "dev") -> None:
        self.entorno = entorno
        self.sesion: Any = None
        self.api: comun.ClienteApi | None = None
        self.backend: comun.EntornoBackend | None = None
        self.s3: Any = None
        self.bucket: str | None = None
        self.admin: tuple[str, str] | None = None
        self.admin_id: str | None = None
        self.dormir: Callable[[float], None] = time.sleep
        self.ahora: Callable[[], datetime] = lambda: datetime.now(UTC)
        self.desfase_s = 0.0  # hora de S3 − hora local (P4; se vuelve a medir antes del PUT de C3a)
        self.http: Any = None  # cliente de la API (las pruebas inyectan uno falso)
        self.http_s3: Any = None  # cliente de los PUT a S3 (ídem)
        self.sello = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        self._outputs: dict[str, Any] | None = None
        self._token: str | None = None
        self.principal: comun.RecorridoPrueba | None = None
        self.registro_c1b: dict[int, dict[str, Any]] = {}  # respuesta de C1b (la URL de la foto 4 la usa C3a)
        self.ultimo_conteo: dict[str, int] | None = None
        self.creados: list[str] = []
        self.borrados: set[str] = set()

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

    def ahora_s3(self) -> datetime:
        """Hora de S3 estimada con el reloj local corregido (el de WSL puede ir atrasado)."""
        return self.ahora() + timedelta(seconds=self.desfase_s)

    @property
    def nombre(self) -> str:
        return f"{comun.PREFIJO_VALIDACION}21-{self.sello}"

    def recorrido(self, nombre: str, total: int, semilla: int) -> comun.RecorridoPrueba:
        return comun.RecorridoPrueba(
            self.api, self.token, nombre, total_fotos=total, http_s3=self.http_s3, lat=LAT, lng=LNG, semilla=semilla
        )

    def semilla(self) -> int:
        return int(self.sello.replace("-", ""))

    # -- pasos compartidos (cada comprobación prepara lo que le falta, así `--solo` funciona) --------------------------
    def asegurar_video(self) -> comun.RecorridoPrueba:
        if self.principal is None:
            recorrido = self.recorrido(self.nombre, N_FOTOS, self.semilla())
            _esperar(recorrido.crear(), 201, "POST /v1/collect/videos")
            self.creados.append(recorrido.video_id)
            self.principal = recorrido
        return self.principal

    def asegurar_registro(self) -> dict[int, dict[str, Any]]:
        """C1b: las 4 fotos registradas (se guarda esa respuesta) y las 1–3 subidas con sus URL de C1b."""
        recorrido = self.asegurar_video()
        if not self.registro_c1b:
            _esperar(recorrido.registrar(TODAS), 200, "POST …/images")
            self.registro_c1b = {orden: dict(imagen) for orden, imagen in recorrido.registro.items()}
            for orden in range(1, N_FOTOS):
                r = recorrido.subir(orden)
                exigir(r.status_code == 200, f"PUT de la foto {orden}: {r.status_code}, se esperaba 200")
        return self.registro_c1b

    def asegurar_todas_subidas(self) -> comun.RecorridoPrueba:
        """Las 4 subidas (si C3b no corrió, la foto 4 con una URL nueva, sin esperar a que venza la de C1b)."""
        self.asegurar_registro()
        self.principal.asegurar_subidas(TODAS)
        return self.principal

    def completar(self) -> dict[str, Any]:
        return _esperar(self.asegurar_video().completar(), 200, "POST …/complete")

    def existe(self, video_id: str) -> bool:
        r = self.pedir("GET", f"/admin/videos/{video_id}")
        if r.status_code == 404:
            return False
        exigir(r.status_code == 200, f"GET /v1/admin/videos/{{id}}: {comun.describir_respuesta(r)}")
        return True

    # -- preparación y limpieza ---------------------------------------------------------------------------------------
    def restos(self) -> str:
        return comun.borrar_restos(self.api, self.token(), self.backend)

    def limpiar(self) -> str:
        try:
            pendientes = [v for v in self.creados if v not in self.borrados]
            if not pendientes:
                return "nada que limpiar"
            if self.api is None or self.backend is None:
                return f"no se pudo limpiar (sin cliente): quedan {', '.join(pendientes)}"
            existentes = [v for v in pendientes if self.existe(v)]
            if not existentes:
                return "nada que limpiar (los videos de prueba ya no existen)"
            tarea = comun.limpiar_videos(self.backend, existentes)
            if tarea.codigo != 0:
                raise Falla(f"limpiar-validacion terminó con {tarea.codigo}: {comun.motivo_cli(tarea)}")
            self.borrados.update(existentes)
            resumen = comun.linea_limpieza(tarea)
            if resumen is None:  # la tarea salió con 0: el log pudo llegar incompleto, no es un fallo
                return f"videos de prueba borrados: {len(existentes)} (tarea 0, sin línea LIMPIEZA en el log)"
            return f"videos de prueba borrados: {json.dumps(resumen)}"
        finally:
            if self.api is not None:
                self.api.cerrar()
            if self.principal is not None:
                self.principal.cerrar()
            elif self.http_s3 is not None:
                self.http_s3.close()


# --- Precondiciones ------------------------------------------------------------------------------------------------
def p1_credenciales(ctx: Contexto) -> str:
    ctx.sesion = comun.sesion_aws()
    arn = comun.verificar_cuenta(ctx.sesion)
    return f"cuenta {comun.CUENTA_AWS} ({arn.rsplit('/', 1)[-1]})"


def p2_api(ctx: Contexto) -> str:
    import httpx

    url = comun.url_api(None if os.environ.get("VALIDACION_API_URL", "").strip() else ctx.outputs())
    ctx.preparar(url)
    try:
        respuesta = ctx.api.pedir("GET", "/health")
    except httpx.HTTPError as exc:
        raise PrecondicionNoCumplida(f"BE-1.1: GET /v1/health no respondió ({type(exc).__name__})") from None
    if respuesta.status_code != 200:
        raise PrecondicionNoCumplida(f"BE-1.1: GET /v1/health respondió {comun.describir_respuesta(respuesta)}")
    return f"{url} · commit {respuesta.json().get('commit')}"


def p3_admin(ctx: Contexto) -> str:
    ctx.admin = comun.credenciales_admin(ctx.entorno, ctx.sesion)
    correo, password = ctx.admin
    respuesta = ctx.api.login(correo, password)
    if respuesta.status_code == 404:
        raise PrecondicionNoCumplida("BE-1.3: POST /v1/auth/login respondió 404")
    if respuesta.status_code == 401:
        raise ErrorConfiguracion("las credenciales del admin no valen (401 CREDENCIALES_INVALIDAS)")
    if respuesta.status_code != 200:
        raise PrecondicionNoCumplida(f"BE-1.3: el login respondió {comun.describir_respuesta(respuesta)}")
    cuerpo = respuesta.json()
    rol = cuerpo.get("usuario", {}).get("rol")
    if rol != "admin":
        raise ErrorConfiguracion(f"el usuario de VALIDACION_ADMIN_* tiene rol {rol!r}, no admin")
    ctx._token = cuerpo["token"]
    ctx.admin_id = str(cuerpo["usuario"]["id"])
    return "login del admin 200 (rol admin)"


def p4_bucket(ctx: Contexto) -> str:
    ctx.bucket = ctx.outputs().get("bucket_dataset")
    if not ctx.bucket:
        raise PrecondicionNoCumplida("INF-1.2: falta el output `bucket_dataset`")
    ctx.s3 = ctx.sesion.client("s3")
    detalle = comun.comprobar_bucket(ctx.s3, ctx.bucket)
    ctx.desfase_s = comun.desfase_s3_s(ctx.s3, ctx.bucket, ctx.ahora)
    return f"{detalle} · reloj local {ctx.desfase_s:+.0f} s respecto a S3"


def p5_tareas(ctx: Contexto) -> str:
    from botocore.exceptions import ClientError

    try:
        arn = ctx.backend.revision(comun.FAMILIA_WORKER)
    except ClientError as exc:
        if comun.es_acceso_denegado(exc):
            raise ErrorConfiguracion(f"sin permiso para describir `{comun.FAMILIA_WORKER}` o el servicio api") from None
        raise PrecondicionNoCumplida(f"INF-1.3: no existe la definición `{comun.FAMILIA_WORKER}`") from None
    except Falla as exc:  # imágenes distintas: backend.yml no actualizó worker
        raise PrecondicionNoCumplida(f"BE-2.1 sin desplegar del todo: {exc}") from None
    red = comun.red_tareas(ctx.outputs())["awsvpcConfiguration"]
    return (
        f"{arn.rsplit('/', 1)[-1]} con la imagen de api; subredes {','.join(red['subnets'])} y grupo "
        f"{red['securityGroups'][0]}"
    )


# --- Comprobaciones ------------------------------------------------------------------------------------------------
def c1a_crear(ctx: Contexto) -> str:
    video = ctx.asegurar_video().video
    exigir(set(video) == CAMPOS_RESUMEN, f"campos de VideoResumen: {sorted(video)}")
    exigir(video["estado"] == "pendiente", f"estado {video['estado']!r}, se esperaba 'pendiente'")
    exigir(video["nombre"] == ctx.nombre and video["ref_cliente"] == ctx.nombre, "nombre o ref_cliente distintos")
    exigir(video["total_fotos"] == N_FOTOS, f"total_fotos {video['total_fotos']}")
    conteo = _conteo_valido(video["conteo"], "C1a")
    exigir(sum(conteo.values()) == 0, f"conteo de un video nuevo: {_texto_conteo(conteo)}")
    if ctx.admin_id:
        exigir(video["creado_por"]["id"] == ctx.admin_id, "creado_por.id no es el admin que inició sesión")
    return f"201 · video {video['id']} número {video['numero']} · estado pendiente · creado_por = admin"


def c1b_urls_y_put(ctx: Contexto) -> str:
    registro = ctx.asegurar_registro()
    exigir(sorted(registro) == TODAS, f"órdenes devueltos: {sorted(registro)}")
    ahora = ctx.ahora_s3()
    for orden, imagen in registro.items():
        exigir(imagen["estado"] == "pendiente_subida", f"foto {orden}: estado {imagen['estado']!r}")
        subida = imagen.get("subida") or {}
        exigir(subida.get("metodo") == "PUT", f"foto {orden}: subida.metodo {subida.get('metodo')!r}")
        exigir(
            subida.get("encabezados") == comun.ENCABEZADOS_PUT, f"foto {orden}: encabezados {subida.get('encabezados')}"
        )
        exigir(_fecha(subida.get("expira_en")) > ahora, f"foto {orden}: expira_en no está en el futuro")
        exigir(str(subida.get("url", "")).startswith("https://"), f"foto {orden}: la URL no es https")
    exigir(len({i["id"] for i in registro.values()}) == N_FOTOS, "ids de foto repetidos")
    return f"4 fotos pendiente_subida con PUT y {comun.ENCABEZADOS_PUT} · PUT de las fotos 1–3: 200, 200, 200"


def c1c_objetos(ctx: Contexto) -> str:
    registro = ctx.asegurar_registro()
    recorrido = ctx.principal
    for orden in range(1, N_FOTOS):
        clave = f"dataset/{recorrido.video_id}/{registro[orden]['id']}.jpg"
        objeto = comun.head_objeto(ctx.s3, ctx.bucket, clave)
        exigir(objeto is not None, f"no existe {clave}")
        exigir(objeto.get("ContentType") == "image/jpeg", f"{clave}: ContentType {objeto.get('ContentType')!r}")
        enviados = len(recorrido.foto(orden))
        exigir(
            objeto.get("ContentLength") == enviados,
            f"{clave}: ContentLength {objeto.get('ContentLength')} ≠ {enviados} bytes enviados",
        )
    return f"3 objetos dataset/{recorrido.video_id}/<imagen_id>.jpg con image/jpeg y el tamaño enviado"


def c2a_crear_otra_vez(ctx: Contexto) -> str:
    recorrido = ctx.asegurar_video()
    primero = dict(recorrido.video)
    cuerpo = _esperar(recorrido.crear(), 200, "POST /v1/collect/videos repetido")
    exigir(cuerpo["id"] == primero["id"], "el video repetido tiene otro id")
    exigir(cuerpo["numero"] == primero["numero"], "el video repetido tiene otro número")
    return f"200 con el mismo id y número ({primero['numero']})"


def c2b_registrar_otra_vez(ctx: Contexto) -> str:
    registro = ctx.asegurar_registro()
    cuerpo = _esperar(ctx.principal.registrar(TODAS), 200, "POST …/images repetido")
    nuevo = {int(i["orden"]): i for i in cuerpo.get("imagenes", [])}
    exigir(sorted(nuevo) == TODAS, f"órdenes devueltos: {sorted(nuevo)}")
    for orden in TODAS:
        exigir(nuevo[orden]["id"] == registro[orden]["id"], f"la foto {orden} cambió de id")
    for orden in range(1, N_FOTOS):
        exigir(nuevo[orden]["subida"] is None, f"la foto {orden} (ya en S3) recibió otra URL")
        exigir(nuevo[orden]["estado"] != "pendiente_subida", f"foto {orden}: sigue pendiente_subida tras el HEAD")
    exigir(nuevo[N_FOTOS]["subida"] is not None, f"la foto {N_FOTOS} (sin subir) no recibió URL")
    return "mismos ids · fotos 1–3 en subida sin URL (HEAD) · foto 4 con URL nueva"


def c2c_put_repetido(ctx: Contexto) -> str:
    registro = ctx.asegurar_registro()
    recorrido = ctx.principal
    r = recorrido.subir(1, registro[1]["subida"])
    exigir(r.status_code == 200, f"PUT repetido de la foto 1: {r.status_code}, se esperaba 200")
    claves = comun.claves_s3(ctx.s3, ctx.bucket, f"dataset/{recorrido.video_id}/")
    esperadas = len(recorrido.subidas)
    exigir(
        len(claves) == esperadas, f"{len(claves)} objetos bajo dataset/{recorrido.video_id}/, se esperaban {esperadas}"
    )
    return f"PUT repetido 200 · {len(claves)} objetos (sin duplicados)"


def c3a_url_vencida(ctx: Contexto) -> str:
    """Espera con la hora de S3 (reloj local + desfase medido con el `Date` de S3) y vuelve a medir el desfase justo
    antes del `PUT`: un reloj local atrasado (WSL tras suspender) haría el `PUT` antes de tiempo y S3 lo aceptaría."""
    registro = ctx.asegurar_registro()
    subida = registro[N_FOTOS]["subida"]
    vence = _fecha(subida["expira_en"])
    objetivo = vence + timedelta(seconds=MARGEN_VENCIMIENTO_S)
    avisar(
        f"C3a: esperando a que venza la URL de la foto {N_FOTOS} ({_iso(vence)} + {MARGEN_VENCIMIENTO_S} s, hora de S3)"
    )
    for _ in range(3):  # tras esperar, vuelve a medir el desfase; casi siempre basta una vuelta
        while (falta := (objetivo - ctx.ahora_s3()).total_seconds()) > 0:
            ctx.dormir(min(falta, AVISO_CADA_S))
            if (resto := (objetivo - ctx.ahora_s3()).total_seconds()) > 0:
                avisar(f"C3a: faltan {int(resto)} s")
        ctx.desfase_s = comun.desfase_s3_s(ctx.s3, ctx.bucket, ctx.ahora)
        if ctx.ahora_s3() >= objetivo:
            break
    r = ctx.principal.subir(N_FOTOS, subida)
    texto = getattr(r, "text", "") or ""
    if r.status_code == 200:
        raise Falla(
            "el PUT con la URL vencida dio 200: S3 aún no la daba por vencida (¿reloj?); la foto 4 quedó subida"
        )
    exigir(r.status_code == 403, f"PUT con la URL vencida: {r.status_code}, se esperaba 403")
    exigir("<Code>AccessDenied</Code>" in texto, "el 403 de S3 no trae <Code>AccessDenied</Code>")
    exigir("Request has expired" in texto, "el 403 de S3 no dice `Request has expired`")
    return (
        f"URL vencida ({_iso(vence)}) → 403 AccessDenied «Request has expired» (desfase local {ctx.desfase_s:+.0f} s)"
    )


def c3b_url_nueva(ctx: Contexto) -> str:
    registro = ctx.asegurar_registro()
    recorrido = ctx.principal
    cuerpo = _esperar(recorrido.registrar([N_FOTOS]), 200, f"POST …/images (solo orden {N_FOTOS})")
    imagen = cuerpo["imagenes"][0]
    subida = imagen.get("subida")
    exigir(imagen["id"] == registro[N_FOTOS]["id"], f"la foto {N_FOTOS} cambió de id")
    exigir(subida, f"la foto {N_FOTOS} no recibió URL nueva")
    exigir(_fecha(subida["expira_en"]) > ctx.ahora_s3(), "expira_en de la URL nueva no está en el futuro")
    r = recorrido.subir(N_FOTOS, subida)
    exigir(r.status_code == 200, f"PUT con la URL nueva: {r.status_code}, se esperaba 200")
    clave = f"dataset/{recorrido.video_id}/{imagen['id']}.jpg"
    exigir(comun.head_objeto(ctx.s3, ctx.bucket, clave) is not None, f"no existe {clave} tras el PUT")
    return f"URL nueva (vence {_iso(_fecha(subida['expira_en']))}) · PUT 200 · objeto en S3"


def c4_complete(ctx: Contexto) -> str:
    recorrido = ctx.asegurar_todas_subidas()
    primera = ctx.completar()
    segunda = ctx.completar()
    conteos = []
    for numero, cuerpo in ((1, primera), (2, segunda)):
        exigir(set(cuerpo) == {"id", "estado", "conteo"}, f"complete {numero}: campos {sorted(cuerpo)}")
        exigir(cuerpo["id"] == recorrido.video_id, f"complete {numero}: otro id")
        conteo = _conteo_valido(cuerpo["conteo"], f"complete {numero}")
        exigir(sum(conteo.values()) == N_FOTOS, f"complete {numero}: suma {sum(conteo.values())} ≠ {N_FOTOS}")
        exigir(conteo["pendiente_subida"] == 0, f"complete {numero}: {_texto_conteo(conteo)}")
        esperado = estado_esperado(conteo)
        exigir(
            cuerpo["estado"] == esperado,
            f"complete {numero}: estado {cuerpo['estado']!r} con {_texto_conteo(conteo)}, §5.5 exige {esperado!r}",
        )
        conteos.append(conteo)
    ctx.ultimo_conteo = conteos[-1]
    return f"200 dos veces · {_texto_conteo(conteos[-1])} · estado {segunda['estado']} (el de §5.5)"


def c5_panel(ctx: Contexto) -> str:
    if ctx.ultimo_conteo is None:
        ctx.asegurar_todas_subidas()
        ctx.ultimo_conteo = _conteo_valido(ctx.completar()["conteo"], "complete")
    video_id = ctx.principal.video_id
    detalle = _esperar(ctx.pedir("GET", f"/admin/videos/{video_id}"), 200, "GET /v1/admin/videos/{id}")
    exigir(set(detalle) == CAMPOS_RESUMEN | {"fotos"}, f"campos del detalle: {sorted(detalle)}")
    ordenes = [foto["orden"] for foto in detalle["fotos"]]
    exigir(ordenes == TODAS, f"fotos en orden {ordenes}")
    for foto in detalle["fotos"]:
        exigir(set(foto) == CAMPOS_IMAGEN, f"campos de ImagenAdmin: {sorted(foto)}")
        exigir(foto["video_id"] == video_id, "una foto del detalle es de otro video")
    conteo = _conteo_valido(detalle["conteo"], "detalle")
    nota = "igual que C4"
    if conteo != ctx.ultimo_conteo:
        exigir(
            _solo_avanzo_el_worker(ctx.ultimo_conteo, conteo),
            f"conteo del detalle {_texto_conteo(conteo)} ≠ C4 {_texto_conteo(ctx.ultimo_conteo)}",
        )
        nota = "cambió solo por el worker"
    listado = _esperar(ctx.pedir("GET", "/admin/videos", params={"q": ctx.nombre}), 200, "GET /v1/admin/videos?q=")
    exigir(any(v.get("id") == video_id for v in listado.get("items", [])), "el listado con q=<nombre> no lo incluye")
    return f"detalle con fotos 1–4 en orden · conteo {_texto_conteo(conteo)} ({nota}) · q=<nombre> lo encuentra"


def c6a_limpiar(ctx: Contexto) -> str:
    recorrido = ctx.recorrido(f"{ctx.nombre}-b", 1, ctx.semilla() + 1)
    try:
        _esperar(recorrido.crear(), 201, "POST /v1/collect/videos (video -b)")
        video_id = recorrido.video_id
        ctx.creados.append(video_id)
        _esperar(recorrido.registrar([1]), 200, "POST …/images (video -b)")
        r = recorrido.subir(1)
        exigir(r.status_code == 200, f"PUT de la foto del video -b: {r.status_code}")
    finally:
        if ctx.http_s3 is None:
            recorrido.cerrar()
    exigir(len(comun.claves_s3(ctx.s3, ctx.bucket, f"dataset/{video_id}/")) == 1, "el objeto del video -b no está")
    tarea = comun.limpiar_videos(ctx.backend, [video_id])
    exigir(tarea.codigo == 0, f"limpiar-validacion --video terminó con {tarea.codigo}: {comun.motivo_cli(tarea)}")
    resumen = comun.linea_limpieza(tarea)
    exigir(resumen is not None, "el log de limpiar-validacion no tiene la línea `LIMPIEZA {…}` (tras reintentar)")
    exigir(resumen.get("videos") == 1, f"LIMPIEZA {resumen}: se esperaba videos = 1")
    exigir(int(resumen.get("objetos", 0)) >= 1, f"LIMPIEZA {resumen}: se esperaba objetos ≥ 1")
    ctx.borrados.add(video_id)
    r = ctx.pedir("GET", f"/admin/videos/{video_id}")
    exigir(
        r.status_code == 404 and comun.codigo_error(r) == "NO_ENCONTRADO",
        f"GET del video borrado: {comun.describir_respuesta(r)}, se esperaba 404 NO_ENCONTRADO",
    )
    quedan = comun.claves_s3(ctx.s3, ctx.bucket, f"dataset/{video_id}/")
    exigir(not quedan, f"quedan {len(quedan)} objetos bajo dataset/{video_id}/")
    return f"tarea 0 · LIMPIEZA {json.dumps(resumen)} · GET 404 · 0 objetos"


def video_ajeno(ctx: Contexto) -> dict[str, Any] | None:
    """Un video que `limpiar-validacion` debe negarse a borrar (sin el prefijo en `nombre` o en `ref_cliente`)."""
    pagina = 1
    while True:
        cuerpo = _esperar(
            ctx.pedir("GET", "/admin/videos", params={"pagina": pagina, "por_pagina": 100}), 200, "GET /v1/admin/videos"
        )
        for video in cuerpo.get("items", []):
            nombre, ref = str(video.get("nombre", "")), str(video.get("ref_cliente", ""))
            if not (nombre.startswith(comun.PREFIJO_VALIDACION) and ref.startswith(comun.PREFIJO_VALIDACION)):
                return video
        if pagina * int(cuerpo.get("por_pagina") or 100) >= int(cuerpo.get("total") or 0):
            return None
        pagina += 1


def c6b_negarse(ctx: Contexto) -> str:
    inexistente = str(uuid.uuid4())
    tarea = comun.limpiar_videos(ctx.backend, [inexistente])
    exigir(tarea.codigo == 1, f"limpiar-validacion con un id inexistente terminó con {tarea.codigo}, se esperaba 1")
    exigir(tarea.eventos("limpieza_rechazada"), "el log no tiene el evento limpieza_rechazada")
    ajeno = video_ajeno(ctx)
    if ajeno is None:
        return "id inexistente → código 1 (limpieza_rechazada) · no hay videos sin el prefijo para probar la negativa"
    # Nunca se apunta la orden real a un video ajeno: `--simular` hace las mismas comprobaciones sin borrar nada.
    tarea = comun.limpiar_videos(ctx.backend, [str(ajeno["id"])], simular=True)
    exigir(
        tarea.codigo == 1, f"limpiar-validacion --simular de un video ajeno terminó con {tarea.codigo}, se esperaba 1"
    )
    exigir(tarea.eventos("limpieza_rechazada"), "la simulación con un video ajeno no dio limpieza_rechazada")
    exigir(ctx.existe(str(ajeno["id"])), f"el video ajeno {ajeno['id']} ya no existe")
    return f"id inexistente → 1 · video ajeno n.º {ajeno.get('numero')} con --simular → 1 y sigue existiendo (200)"


def main(argv: list[str] | None = None, ctx: Contexto | None = None) -> int:
    validador = comun.Validador(lote=LOTE, validacion="validation-2-1", entornos=("dev",), descripcion=__doc__)
    argumentos = validador.iniciar(argv)
    ctx = ctx or Contexto(argumentos.entorno)
    return validador.ejecutar(
        precondiciones=[
            ("P1", lambda: p1_credenciales(ctx)),
            ("P2", lambda: p2_api(ctx)),
            ("P3", lambda: p3_admin(ctx)),
            ("P4", lambda: p4_bucket(ctx)),
            ("P5", lambda: p5_tareas(ctx)),
        ],
        preparacion=ctx.restos,
        comprobaciones=[
            ("C1a", lambda: c1a_crear(ctx)),
            ("C1b", lambda: c1b_urls_y_put(ctx)),
            ("C1c", lambda: c1c_objetos(ctx)),
            ("C2a", lambda: c2a_crear_otra_vez(ctx)),
            ("C2b", lambda: c2b_registrar_otra_vez(ctx)),
            ("C2c", lambda: c2c_put_repetido(ctx)),
            ("C3a", lambda: c3a_url_vencida(ctx)),
            ("C3b", lambda: c3b_url_nueva(ctx)),
            ("C4", lambda: c4_complete(ctx)),
            ("C5", lambda: c5_panel(ctx)),
            ("C6a", lambda: c6a_limpiar(ctx)),
            ("C6b", lambda: c6b_negarse(ctx)),
        ],
        manuales=[],
        limpieza=ctx.limpiar,
    )


if __name__ == "__main__":
    sys.exit(main())
