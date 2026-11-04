"""Validador de INF-1.2 — Datos y secretos.

Documento: docs/validation/validation-1-2.md. Contrato común: docs/ARCHITECTURE.md §5.11.

Uso (desde INFRASTRUCTURA_TERRAFORM/project/):
    uv run --group ops python src/ops/validate12.py --entorno dev [--informe RUTA] [--solo C1,C3] [--sin-limpieza]
"""

from __future__ import annotations

import base64
import binascii
import json
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import unquote_plus

from botocore.exceptions import ClientError

import comun

PREFIJO = "campus-locator-dev"
VPC = f"{PREFIJO}-vpc"
AZ = "us-east-1a"
SUBREDES_PRIVADAS = {"privada-a": f"{PREFIJO}-privada-a", "privada-b": f"{PREFIJO}-privada-b"}
GRUPOS = {"rds": f"{PREFIJO}-rds", "api": f"{PREFIJO}-api", "worker": f"{PREFIJO}-worker"}

BUCKET = f"{PREFIJO}-dataset-{comun.CUENTA}"
BUCKET_ARN = f"arn:aws:s3:::{BUCKET}"
INSTANCIA = f"{PREFIJO}-db"
GRUPO_SUBREDES_DB = f"{PREFIJO}-db"
GRUPO_PARAMETROS = f"{PREFIJO}-pg17"
FAMILIA_PARAMETROS = "postgres17"
BASE = "campus_locator"
USUARIO = "campus_app"
COLAS = {
    "ingesta": f"{PREFIJO}-ingesta",
    "purga": f"{PREFIJO}-purga",
    "ingesta_dlq": f"{PREFIJO}-ingesta-dlq",
    "purga_dlq": f"{PREFIJO}-purga-dlq",
}
SECRETOS = {
    "db": "campus-locator/dev/db",
    "jwt": "campus-locator/dev/jwt",
    "admin_inicial": "campus-locator/dev/admin-inicial",
}
CORREO_ADMIN = "admin@campus.edu.co"
ETIQUETAS = {
    "Proyecto": "campus-locator",
    "Entorno": "dev",
    "GestionadoPor": "terraform",
    "Carpeta": "INFRASTRUCTURA_TERRAFORM",
}

PREFIJOS_PRUEBA = ("dataset/validacion-", "thumbs/validacion-")
PATRON_PRUEBA = re.compile(r"^(?:dataset|thumbs)/validacion-(\d{8}-\d{6})/")
ANTIGUEDAD_RESTO_S = 15 * 60  # un validacion-… de otro sello solo es «resto» si es 15 min más antiguo que el propio
MAX_MENSAJES_PREVIOS = 10  # con más mensajes visibles en ingesta, C1/C2 no leen la cola
ESPERA_C1_S = 90  # máximo para que llegue el evento de c1.jpg
ESPERA_C2_S = 30  # lectura extra tras el evento de c1.jpg
OCULTAR_S = 300  # visibilidad de lo que se recibe; los mensajes ajenos se devuelven al terminar de leer
CLUSTER = PREFIJO  # clúster de ECS de INF-1.3 (§5.1)

# Imágenes de 8×8 px generadas una vez con Pillow (JPEG y PNG válidos).
JPEG = base64.b64decode(
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDABALDA4MChAODQ4SERATGCgaGBYWGDEjJR0oOjM9PDkzODdASFxOQERXRTc4UG1RV19iZ2hnPk1x"
    "eXBkeFxlZ2P/2wBDARESEhgVGC8aGi9jQjhCY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2P/wAAR"
    "CAAIAAgDASIAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAT/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/8QAFAEBAAAAAAAAAAAAAAAAAAAA"
    "Bf/EABQRAQAAAAAAAAAAAAAAAAAAAAD/2gAMAwEAAhEDEQA/AIwDIl//2Q=="
)
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAgAAAAICAIAAABLbSncAAAAFUlEQVR42mPUqDjBgA0wMeAAg1MCABznAXiY7kjRAAAAAElFTkSuQmCC"
)


# ---------------------------------------------------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------------------------------------------------


def llamar(accion: str, fn, *codigos_ausente: str):
    """Ejecuta una llamada de boto3. Devuelve None si el error es uno de `codigos_ausente` (recurso que no existe);
    los demás errores los traduce comun.errores_aws (permisos → código 3; el resto → Falla)."""
    with comun.errores_aws(accion):
        try:
            return fn()
        except ClientError as exc:
            if comun.codigo_error_aws(exc) in codigos_ausente:
                return None
            raise


def llamar_precondicion(accion: str, fn):
    """Como `llamar`, para las precondiciones: un error de AWS que no es «no existe» (cuota, 5xx, red) es de entorno
    (código 3), no un lote sin terminar (código 2, que solo dan los Bloqueo de las propias precondiciones)."""
    try:
        return llamar(accion, fn)
    except comun.Falla as exc:
        if isinstance(exc, comun.Bloqueo):
            raise
        raise comun.ErrorConfiguracion(str(exc)) from exc


def paginar(cliente, operacion: str, clave: str, accion: str, *codigos_ausente: str, **parametros) -> list | None:
    def todo():
        elementos = []
        for pagina in cliente.get_paginator(operacion).paginate(**parametros):
            elementos.extend(pagina.get(clave, []))
        return elementos

    return llamar(accion, todo, *codigos_ausente)


def como_lista(valor) -> list:
    if valor is None:
        return []
    return valor if isinstance(valor, list) else [valor]


def etiquetas_de(lista: list | None) -> dict:
    return {e.get("Key"): e.get("Value") for e in (lista or [])}


def comprobar(problemas: list[str], detalle: str) -> str:
    if problemas:
        raise comun.Falla("; ".join(problemas))
    return detalle


def es_de_prueba(clave: str, sello: str) -> bool:
    """¿Es una clave de prueba que este validador puede borrar? Las de su propio sello y las de otro sello con más
    de 15 min de antigüedad (restos de una ejecución anterior). Las recientes de otro sello son de una ejecución en
    curso (o de otro validador) y no se tocan."""
    coincidencia = PATRON_PRUEBA.match(clave)
    if not coincidencia:
        return False
    if coincidencia[1] == sello:
        return True
    try:
        otro = datetime.strptime(coincidencia[1], "%Y%m%d-%H%M%S")
        propio = datetime.strptime(sello, "%Y%m%d-%H%M%S")
    except ValueError:
        return False
    return (propio - otro).total_seconds() > ANTIGUEDAD_RESTO_S


@dataclass
class Evento:
    nombre: str
    clave: str
    llegada: float


def analizar_mensaje(cuerpo: str, sello: str) -> tuple[str, list[Evento]]:
    """Clasifica un mensaje de ingesta: ("prueba_s3", []) para el s3:TestEvent del bucket del dataset,
    ("validacion", eventos) si todos sus registros son de claves de prueba borrables (`es_de_prueba`) de ese bucket,
    o ("ajeno", []) para cualquier otra cosa, incluido un mensaje que no se entiende."""
    try:
        datos = json.loads(cuerpo)
        if not isinstance(datos, dict):
            return "ajeno", []
        if datos.get("Event") == "s3:TestEvent" and datos.get("Bucket") == BUCKET:
            return "prueba_s3", []
        registros = datos.get("Records")
        if not isinstance(registros, list) or not registros:
            return "ajeno", []
        eventos = []
        for registro in registros:
            bucket = registro["s3"]["bucket"]["name"]
            clave = unquote_plus(registro["s3"]["object"]["key"])
            if bucket != BUCKET or not es_de_prueba(clave, sello):
                return "ajeno", []
            eventos.append(Evento(str(registro.get("eventName", "")), clave, time.monotonic()))
        return "validacion", eventos
    except Exception:  # cuerpo inesperado: nunca se borra
        return "ajeno", []


class LectorIngesta:
    """Lee `ingesta` sin estropear lo ajeno: borra los eventos de claves de prueba (`es_de_prueba`) y el
    s3:TestEvent del bucket; los mensajes ajenos los deja ocultos hasta `devolver`, que los hace visibles de nuevo.
    Así cada mensaje ajeno se recibe como mucho una vez por ejecución."""

    def __init__(self, sqs, url: str, sello: str):
        self.sqs = sqs
        self.url = url
        self.sello = sello
        self.eventos: list[Evento] = []
        self.ajenos: dict[str, str] = {}  # MessageId → ReceiptHandle
        self.pruebas_s3 = 0

    def evento(self, clave: str) -> Evento | None:
        return next((e for e in self.eventos if e.clave == clave), None)

    def leer(self, segundos: float, hasta=None, parar_si_vacia: bool = False) -> None:
        limite = time.monotonic() + segundos
        while not (hasta and hasta()):
            restante = limite - time.monotonic()
            if restante <= 0:
                return
            espera = 1 if parar_si_vacia else max(1, min(20, int(restante)))
            respuesta = llamar(
                "leer la cola ingesta (sqs:ReceiveMessage)",
                lambda espera=espera: self.sqs.receive_message(
                    QueueUrl=self.url,
                    MaxNumberOfMessages=10,
                    WaitTimeSeconds=espera,
                    VisibilityTimeout=OCULTAR_S,
                ),
            )
            mensajes = respuesta.get("Messages", [])
            if not mensajes and parar_si_vacia:
                return
            # Primero se registra todo el lote (los ajenos quedan apuntados para devolverlos) y después se borra.
            propios = []
            for mensaje in mensajes:
                tipo, eventos = analizar_mensaje(mensaje.get("Body", ""), self.sello)
                if tipo == "ajeno":
                    self.ajenos[mensaje["MessageId"]] = mensaje["ReceiptHandle"]
                    continue
                propios.append(mensaje)
                self.eventos.extend(eventos)
                self.pruebas_s3 += tipo == "prueba_s3"
            if propios:
                self._borrar(propios)

    def _borrar(self, mensajes: list[dict]) -> None:
        entradas = [{"Id": str(i), "ReceiptHandle": m["ReceiptHandle"]} for i, m in enumerate(mensajes)]
        respuesta = llamar(
            "borrar mensajes de prueba de ingesta (sqs:DeleteMessage)",
            lambda: self.sqs.delete_message_batch(QueueUrl=self.url, Entries=entradas),
        )
        for fallo in respuesta.get("Failed", []):
            comun.avisar(f"no se pudo borrar un mensaje de prueba de ingesta: {fallo.get('Code')}")

    def devolver(self) -> None:
        """Hace visibles de nuevo los mensajes ajenos recibidos. No lanza excepciones (se usa al limpiar)."""
        pendientes = list(self.ajenos.values())
        self.ajenos.clear()
        devueltos = 0
        for inicio in range(0, len(pendientes), 10):
            entradas = [
                {"Id": str(i), "ReceiptHandle": r, "VisibilityTimeout": 0}
                for i, r in enumerate(pendientes[inicio : inicio + 10])
            ]
            try:
                respuesta = self.sqs.change_message_visibility_batch(QueueUrl=self.url, Entries=entradas)
                devueltos += len(respuesta.get("Successful", []))
            except Exception as exc:  # noqa: BLE001 — limpieza: avisar y seguir
                comun.avisar(f"no se pudieron devolver mensajes ajenos a ingesta: {comun.resumir(str(exc), 200)}")
        if pendientes:
            comun.avisar(
                f"{devueltos} de {len(pendientes)} mensaje(s) ajeno(s) devuelto(s) a ingesta (cada uno suma una "
                f"recepción; los no devueltos vuelven solos a los {OCULTAR_S} s)"
            )

    def cerrar(self, clave_c1: str, subido: bool) -> None:
        """Limpieza: si c1.jpg se subió y su evento no llegó, lee 20 s más para borrar eventos de prueba tardíos (los
        ajenos ya recibidos siguen ocultos y no se vuelven a recibir); después, siempre, devuelve los ajenos."""
        try:
            if subido and self.evento(clave_c1) is None:
                self.leer(20)
        except Exception as exc:  # noqa: BLE001 — limpieza: avisar y seguir
            comun.avisar(f"no se pudo terminar de leer ingesta: {comun.resumir(str(exc), 200)}")
        finally:
            self.devolver()


# ---------------------------------------------------------------------------------------------------------------------
# Estado compartido entre comprobaciones
# ---------------------------------------------------------------------------------------------------------------------


@dataclass
class Contexto:
    sesion: object = None
    clientes: dict = field(default_factory=dict)
    subredes: dict = field(default_factory=dict)  # privada-a/-b → ID
    grupos: dict = field(default_factory=dict)  # rds/api/worker → ID
    _instancia: dict | None = None
    _colas: dict = field(default_factory=dict)  # clave → (url, atributos)
    # C1/C2
    sello: str = ""
    claves: dict = field(default_factory=dict)
    lector: LectorIngesta | None = None
    creados: list = field(default_factory=list)
    fase_subida: str | None = None  # None, "hecha" o "fallida"
    error_subida: BaseException | None = None
    t_subida: float = 0.0

    def cliente(self, servicio: str):
        if servicio not in self.clientes:
            self.clientes[servicio] = self.sesion.client(servicio, region_name=comun.REGION)
        return self.clientes[servicio]

    def instancia(self) -> dict:
        if self._instancia is None:
            rds = self.cliente("rds")
            respuesta = llamar(
                f"describir la instancia {INSTANCIA} (rds:DescribeDBInstances)",
                lambda: rds.describe_db_instances(DBInstanceIdentifier=INSTANCIA),
                "DBInstanceNotFound",
                "DBInstanceNotFoundFault",
            )
            if not respuesta or not respuesta.get("DBInstances"):
                raise comun.Falla(f"no existe la instancia {INSTANCIA}")
            self._instancia = respuesta["DBInstances"][0]
        return self._instancia

    def cola(self, clave: str) -> tuple[str, dict]:
        if clave not in self._colas:
            sqs = self.cliente("sqs")
            nombre = COLAS[clave]
            respuesta = llamar(
                f"obtener la URL de {nombre} (sqs:GetQueueUrl)",
                lambda: sqs.get_queue_url(QueueName=nombre),
                "AWS.SimpleQueueService.NonExistentQueue",
                "QueueDoesNotExist",
            )
            if respuesta is None:
                raise comun.Falla(f"no existe la cola {nombre}")
            url = respuesta["QueueUrl"]
            atributos = llamar(
                f"leer los atributos de {nombre} (sqs:GetQueueAttributes)",
                lambda: sqs.get_queue_attributes(QueueUrl=url, AttributeNames=["All"]),
            )
            self._colas[clave] = (url, atributos.get("Attributes", {}))
        return self._colas[clave]


# ---------------------------------------------------------------------------------------------------------------------
# Precondiciones
# ---------------------------------------------------------------------------------------------------------------------


def p2_credenciales(ctx: Contexto) -> str:
    ctx.sesion = comun.sesion_aws()
    arn = comun.comprobar_cuenta(ctx.sesion)
    secretos = ctx.cliente("secretsmanager")
    llamar_precondicion("listar secretos (secretsmanager:ListSecrets)", lambda: secretos.list_secrets(MaxResults=1))
    return f"{arn} (cuenta {comun.CUENTA})"


def p1_red(ctx: Contexto) -> str:
    ec2 = ctx.cliente("ec2")
    vpcs = llamar_precondicion(
        "buscar la VPC (ec2:DescribeVpcs)",
        lambda: ec2.describe_vpcs(Filters=[{"Name": "tag:Name", "Values": [VPC]}]),
    )["Vpcs"]
    if len(vpcs) != 1:
        raise comun.Bloqueo(f"INF-1.1 no está aplicado: {len(vpcs)} VPC con Name = {VPC}")
    vpc = vpcs[0]["VpcId"]

    subredes = llamar_precondicion(
        "buscar las subredes privadas (ec2:DescribeSubnets)",
        lambda: ec2.describe_subnets(
            Filters=[
                {"Name": "vpc-id", "Values": [vpc]},
                {"Name": "tag:Name", "Values": list(SUBREDES_PRIVADAS.values())},
            ]
        ),
    )["Subnets"]
    por_nombre = {}
    for subred in subredes:
        nombre = etiquetas_de(subred.get("Tags")).get("Name")
        por_nombre.setdefault(nombre, []).append(subred["SubnetId"])
    for clave, nombre in SUBREDES_PRIVADAS.items():
        if len(por_nombre.get(nombre, [])) != 1:
            raise comun.Bloqueo(f"INF-1.1 no está aplicado: {len(por_nombre.get(nombre, []))} subredes {nombre}")
        ctx.subredes[clave] = por_nombre[nombre][0]

    grupos = llamar_precondicion(
        "buscar los grupos de seguridad (ec2:DescribeSecurityGroups)",
        lambda: ec2.describe_security_groups(
            Filters=[
                {"Name": "vpc-id", "Values": [vpc]},
                {"Name": "group-name", "Values": list(GRUPOS.values())},
            ]
        ),
    )["SecurityGroups"]
    por_nombre = {g["GroupName"]: g["GroupId"] for g in grupos}
    faltan = [nombre for nombre in GRUPOS.values() if nombre not in por_nombre]
    if faltan:
        raise comun.Bloqueo(f"INF-1.1 no está aplicado: faltan los grupos {', '.join(faltan)}")
    ctx.grupos = {clave: por_nombre[nombre] for clave, nombre in GRUPOS.items()}
    return f"{VPC}, privada-a, privada-b y los grupos -rds, -api y -worker"


# ---------------------------------------------------------------------------------------------------------------------
# C1 y C2: notificación S3 → ingesta
# ---------------------------------------------------------------------------------------------------------------------


def borrar_objetos(s3, claves: list[str]) -> None:
    for inicio in range(0, len(claves), 1000):
        lote = claves[inicio : inicio + 1000]
        if not lote:
            continue
        respuesta = s3.delete_objects(Bucket=BUCKET, Delete={"Objects": [{"Key": c} for c in lote], "Quiet": True})
        for error in respuesta.get("Errors", []):
            comun.avisar(f"no se pudo borrar s3://{BUCKET}/{error.get('Key')}: {error.get('Code')}")


def limpiar_restos(ctx: Contexto) -> None:
    """Borra objetos de prueba de ejecuciones anteriores (`es_de_prueba`, solo bajo dataset/ y thumbs/)."""
    s3 = ctx.cliente("s3")
    for prefijo in PREFIJOS_PRUEBA:
        objetos = paginar(
            s3,
            "list_objects_v2",
            "Contents",
            f"listar s3://{BUCKET}/{prefijo} (s3:ListBucket)",
            "NoSuchBucket",
            Bucket=BUCKET,
            Prefix=prefijo,
        )
        claves = [o["Key"] for o in objetos or [] if es_de_prueba(o["Key"], ctx.sello)]
        if claves:
            comun.avisar(f"borrando {len(claves)} objeto(s) de ejecuciones anteriores bajo {prefijo}")
            llamar("borrar restos (s3:DeleteObject)", lambda c=claves: borrar_objetos(s3, c))


def comprobar_que_nadie_consume(ctx: Contexto) -> None:
    """Desde INF-1.3, el servicio worker consume ingesta: si está en marcha se llevaría los eventos de prueba (C1
    fallaría y C2 podría pasar en falso). Antes de INF-1.3 el clúster no existe y no hay nada que comprobar."""
    ecs = ctx.cliente("ecs")
    respuesta = llamar(
        f"consultar el servicio worker de {CLUSTER} (ecs:DescribeServices)",
        lambda: ecs.describe_services(cluster=CLUSTER, services=["worker"]),
        "ClusterNotFoundException",
    )
    for servicio in (respuesta or {}).get("services", []):
        cuenta = {k: servicio.get(k, 0) for k in ("desiredCount", "runningCount", "pendingCount")}
        if servicio.get("status") == "ACTIVE" and any(cuenta.values()):
            raise comun.Falla(
                f"el servicio worker está en marcha ({cuenta}): consumiría los eventos de prueba. Ejecutar C1 y C2 "
                "fuera del horario de INF-2.1, con worker en 0 (validation-1-2 §4)"
            )


def preparar_cola(ctx: Contexto, lector: LectorIngesta) -> None:
    """Antes de subir nada: ingesta solo puede tener restos de prueba o el s3:TestEvent. Con mensajes reales, leerla
    les gastaría reintentos (maxReceiveCount = 5 → DLQ), así que C1 y C2 no siguen."""
    sqs = ctx.cliente("sqs")
    nombres = (
        "ApproximateNumberOfMessages",
        "ApproximateNumberOfMessagesNotVisible",
        "ApproximateNumberOfMessagesDelayed",
    )
    atributos = llamar(
        "contar los mensajes de ingesta (sqs:GetQueueAttributes)",
        lambda: sqs.get_queue_attributes(QueueUrl=lector.url, AttributeNames=list(nombres)),
    ).get("Attributes", {})
    visibles, en_vuelo, retrasados = (int(atributos.get(n, 0)) for n in nombres)
    if en_vuelo or retrasados or visibles > MAX_MENSAJES_PREVIOS:
        raise comun.Falla(
            f"ingesta tiene {visibles} mensaje(s) visible(s), {en_vuelo} en proceso y {retrasados} retrasado(s): "
            "C1 y C2 no leen la cola para no gastar reintentos de mensajes reales. Repetir con la cola vacía "
            f"(los mensajes en proceso de una ejecución anterior vuelven a los {OCULTAR_S} s; validation-1-2 §4)"
        )
    if visibles:
        lector.leer(30, parar_si_vacia=True)
        if lector.ajenos:
            cuantos = len(lector.ajenos)
            lector.devolver()
            raise comun.Falla(
                f"ingesta tiene {cuantos} mensaje(s) que no son de prueba (ya devueltos a la cola): C1 y C2 no siguen "
                "para no gastarles reintentos. Repetir cuando la cola esté vacía (validation-1-2 §4)"
            )
    if lector.pruebas_s3 or lector.eventos:
        comun.avisar(
            f"borrados de ingesta: {lector.pruebas_s3} s3:TestEvent y {len(lector.eventos)} evento(s) de prueba "
            "antiguos"
        )
    lector.eventos.clear()


def subir(ctx: Contexto, clave: str, cuerpo: bytes, tipo: str) -> None:
    s3 = ctx.cliente("s3")
    ctx.creados.append(clave)  # antes del PUT: si responde con error pero el objeto quedó, la limpieza lo borra igual
    llamar(
        f"subir s3://{BUCKET}/{clave} (s3:PutObject)",
        lambda: s3.put_object(Bucket=BUCKET, Key=clave, Body=cuerpo, ContentType=tipo),
    )


def fase_subida(v, ctx: Contexto) -> None:
    """Sube los objetos de prueba y espera el evento de c1.jpg. La comparten C1 y C2; se hace una sola vez."""
    if ctx.fase_subida == "hecha":
        return
    if ctx.fase_subida == "fallida":
        raise ctx.error_subida
    try:
        comprobar_que_nadie_consume(ctx)
        limpiar_restos(ctx)
        url, _ = ctx.cola("ingesta")
        ctx.lector = LectorIngesta(ctx.cliente("sqs"), url, ctx.sello)
        lector = ctx.lector
        v.al_limpiar(
            "borrar eventos de prueba tardíos y devolver los mensajes ajenos a ingesta",
            lambda: lector.cerrar(ctx.claves["c1"], ctx.claves["c1"] in ctx.creados),
        )
        preparar_cola(ctx, lector)
        v.al_limpiar(
            "borrar los objetos de prueba de S3",
            lambda: llamar(
                "borrar los objetos de prueba (s3:DeleteObject)",
                lambda: borrar_objetos(ctx.cliente("s3"), list(ctx.creados)),
            ),
        )
        if v.incluida("C2"):
            subir(ctx, ctx.claves["c2_png"], PNG, "image/png")
            subir(ctx, ctx.claves["c2_thumb"], JPEG, "image/jpeg")
        subir(ctx, ctx.claves["c1"], JPEG, "image/jpeg")
        ctx.t_subida = time.monotonic()
        comun.avisar(f"esperando el evento de {ctx.claves['c1']} en ingesta (hasta {ESPERA_C1_S} s)…")
        lector.leer(ESPERA_C1_S, hasta=lambda: lector.evento(ctx.claves["c1"]) is not None)
        if not v.incluida("C2"):
            terminar_lectura(ctx)
        ctx.fase_subida = "hecha"
    except BaseException as exc:
        ctx.fase_subida, ctx.error_subida = "fallida", exc
        raise


def terminar_lectura(ctx: Contexto) -> None:
    """Tras la última lectura: si el evento de c1 llegó, no hay nada más que esperar y los ajenos vuelven ya a la
    cola (si no llegó, la limpieza lee 20 s más y los devuelve después, para no recibirlos dos veces)."""
    if ctx.lector.evento(ctx.claves["c1"]) is not None:
        ctx.lector.devolver()


def c1_notificacion(v, ctx: Contexto) -> str:
    fase_subida(v, ctx)
    clave = ctx.claves["c1"]
    evento = ctx.lector.evento(clave)
    if evento is None:
        raise comun.Falla(f"no llegó a ingesta el evento de {clave} en {ESPERA_C1_S} s")
    if not evento.nombre.startswith("ObjectCreated:"):
        raise comun.Falla(f"el evento de {clave} es {evento.nombre!r}, no ObjectCreated:*")
    return f"{evento.nombre} de {clave} en {evento.llegada - ctx.t_subida:.0f} s"


def c2_filtros(v, ctx: Contexto) -> str:
    fase_subida(v, ctx)
    comun.avisar(f"leyendo ingesta {ESPERA_C2_S} s más por si llegan eventos de .png o de thumbs/…")
    ctx.lector.leer(ESPERA_C2_S)
    terminar_lectura(ctx)
    indebidas = sorted(
        {e.clave for e in ctx.lector.eventos if e.clave in (ctx.claves["c2_png"], ctx.claves["c2_thumb"])}
    )
    if indebidas:
        raise comun.Falla(f"llegaron eventos que el filtro debía descartar: {', '.join(indebidas)}")
    if ctx.lector.evento(ctx.claves["c1"]) is None:
        raise comun.Falla(
            f"no llegó el evento de {ctx.claves['c1']}: sin él, que no lleguen los de c2 no prueba los filtros"
        )
    return f"sin eventos de {ctx.claves['c2_png']} ni de {ctx.claves['c2_thumb']}"


# ---------------------------------------------------------------------------------------------------------------------
# C3 y C4: RDS
# ---------------------------------------------------------------------------------------------------------------------


def c3a_rds_privada(ctx: Contexto) -> str:
    instancia = ctx.instancia()
    problemas = []
    if instancia.get("PubliclyAccessible") is not False:
        problemas.append("PubliclyAccessible no es false")
    if instancia.get("AvailabilityZone") != AZ:
        problemas.append(f"zona {instancia.get('AvailabilityZone')}, no {AZ}")
    grupo_subredes = instancia.get("DBSubnetGroup") or {}
    if grupo_subredes.get("DBSubnetGroupName") != GRUPO_SUBREDES_DB:
        problemas.append(f"grupo de subredes {grupo_subredes.get('DBSubnetGroupName')}, no {GRUPO_SUBREDES_DB}")
    subredes = {s.get("SubnetIdentifier") for s in grupo_subredes.get("Subnets", [])}
    if subredes != set(ctx.subredes.values()):
        problemas.append("el grupo de subredes no es exactamente privada-a y privada-b")
    grupos = {g.get("VpcSecurityGroupId") for g in instancia.get("VpcSecurityGroups", [])}
    if grupos != {ctx.grupos["rds"]}:
        problemas.append(f"grupos de seguridad {sorted(grupos)}; debe ser solo {GRUPOS['rds']}")

    ec2 = ctx.cliente("ec2")
    reglas = paginar(
        ec2,
        "describe_security_group_rules",
        "SecurityGroupRules",
        "leer las reglas del grupo -rds (ec2:DescribeSecurityGroupRules)",
        Filters=[{"Name": "group-id", "Values": [ctx.grupos["rds"]]}],
    )
    permitidos = {ctx.grupos["api"]: "-api", ctx.grupos["worker"]: "-worker"}
    origenes = set()
    for regla in reglas:
        if regla.get("IsEgress"):
            continue
        rango = regla.get("CidrIpv4") or regla.get("CidrIpv6") or regla.get("PrefixListId")
        referido = (regla.get("ReferencedGroupInfo") or {}).get("GroupId")
        if rango:
            problemas.append(f"regla entrante {regla.get('SecurityGroupRuleId')} abierta a {rango}")
        elif referido not in permitidos:
            problemas.append(f"regla entrante {regla.get('SecurityGroupRuleId')} desde {referido}")
        elif (regla.get("IpProtocol"), regla.get("FromPort"), regla.get("ToPort")) != ("tcp", 5432, 5432):
            problemas.append(f"regla entrante {regla.get('SecurityGroupRuleId')} no es 5432/tcp")
        else:
            origenes.add(permitidos[referido])
    return comprobar(
        problemas,
        f"sin acceso público, en {AZ}, subredes privada-a/-b, entrada solo 5432/tcp desde "
        f"{', '.join(sorted(origenes)) or 'ningún grupo'} (estado {instancia.get('DBInstanceStatus')})",
    )


def c3b_tls(ctx: Contexto) -> str:
    instancia = ctx.instancia()
    rds = ctx.cliente("rds")
    problemas = []
    parametros = paginar(
        rds,
        "describe_db_parameters",
        "Parameters",
        f"leer los parámetros de {GRUPO_PARAMETROS} (rds:DescribeDBParameters)",
        "DBParameterGroupNotFound",
        "DBParameterGroupNotFoundFault",
        DBParameterGroupName=GRUPO_PARAMETROS,
    )  # sin filtrar por Source: un valor igual al de por defecto puede figurar como "system"
    if parametros is None:
        raise comun.Falla(f"no existe el grupo de parámetros {GRUPO_PARAMETROS}")
    force_ssl = next((p for p in parametros if p.get("ParameterName") == "rds.force_ssl"), {})
    if force_ssl.get("ParameterValue") != "1":
        problemas.append(f"rds.force_ssl = {force_ssl.get('ParameterValue')!r} en {GRUPO_PARAMETROS}, no '1'")
    grupos = [
        (g.get("DBParameterGroupName"), g.get("ParameterApplyStatus")) for g in instancia.get("DBParameterGroups", [])
    ]
    if grupos != [(GRUPO_PARAMETROS, "in-sync")]:
        problemas.append(f"grupos de parámetros de la instancia {grupos}; debe ser [({GRUPO_PARAMETROS!r}, 'in-sync')]")
    return comprobar(problemas, f"rds.force_ssl = 1 en {GRUPO_PARAMETROS}, aplicado (in-sync)")


ATRIBUTOS_INSTANCIA = {
    "DBInstanceClass": "db.t4g.micro",
    "StorageType": "gp3",
    "MaxAllocatedStorage": 50,
    "StorageEncrypted": True,
    "MultiAZ": False,
    "DeletionProtection": True,
    "BackupRetentionPeriod": 7,
    "PreferredBackupWindow": "07:00-07:30",
    "PreferredMaintenanceWindow": "sun:08:00-sun:09:00",
    "AutoMinorVersionUpgrade": True,
    "CopyTagsToSnapshot": True,
    "DBName": BASE,
    "MasterUsername": USUARIO,
}


def c5d_instancia(ctx: Contexto) -> str:
    instancia = ctx.instancia()
    problemas = [
        f"{campo} = {instancia.get(campo)!r}, no {esperado!r}"
        for campo, esperado in ATRIBUTOS_INSTANCIA.items()
        if instancia.get(campo) != esperado
    ]
    if not isinstance(instancia.get("AllocatedStorage"), int) or instancia["AllocatedStorage"] < 20:
        problemas.append(f"AllocatedStorage = {instancia.get('AllocatedStorage')!r}, menos de 20 GB")
    if (instancia.get("Endpoint") or {}).get("Port") != 5432:
        problemas.append(f"puerto {(instancia.get('Endpoint') or {}).get('Port')!r}, no 5432")
    return comprobar(
        problemas,
        f"db.t4g.micro, gp3 {instancia.get('AllocatedStorage')}→50 GB cifrados, una zona, protección contra borrado, "
        "copias 7 días y ventanas de §5.10",
    )


def c4_version(ctx: Contexto) -> str:
    instancia = ctx.instancia()
    motor, version = instancia.get("Engine"), str(instancia.get("EngineVersion", ""))
    coincidencia = re.match(r"^(\d+)\.(\d+)", version)
    if motor != "postgres":
        raise comun.Falla(f"motor {motor!r}, no postgres")
    if not coincidencia or int(coincidencia[1]) != 17 or int(coincidencia[2]) < 1:
        raise comun.Falla(f"versión {version!r}; se exige 17.x con x ≥ 1 (pgvector 0.8)")
    return f"postgres {version}"


# ---------------------------------------------------------------------------------------------------------------------
# C5: secretos, bucket y colas
# ---------------------------------------------------------------------------------------------------------------------


def leer_secreto(ctx: Contexto, nombre: str) -> dict | None:
    """Devuelve el JSON del secreto o None si no existe. Nunca imprime el valor."""
    secretos = ctx.cliente("secretsmanager")
    respuesta = llamar(
        f"leer {nombre} (secretsmanager:GetSecretValue)",
        lambda: secretos.get_secret_value(SecretId=nombre),
        "ResourceNotFoundException",
    )
    if respuesta is None:
        return None
    try:
        valor = json.loads(respuesta.get("SecretString") or "")
    except ValueError:
        raise comun.Falla(f"{nombre} no contiene un objeto JSON") from None
    if not isinstance(valor, dict):
        raise comun.Falla(f"{nombre} no contiene un objeto JSON")
    return valor


def c5a_secretos(ctx: Contexto) -> str:
    problemas = []
    valores = {}
    for clave, nombre in SECRETOS.items():
        try:
            valores[clave] = leer_secreto(ctx, nombre)
        except comun.Falla as exc:
            problemas.append(str(exc))
            continue
        if valores[clave] is None:
            problemas.append(f"no existe {nombre}")

    db = valores.get("db")
    if db is not None:
        claves = {"host", "port", "dbname", "username", "password"}
        if set(db) != claves:
            problemas.append(f"{SECRETOS['db']}: claves {sorted(db)}; deben ser {sorted(claves)}")
        endpoint = (ctx.instancia().get("Endpoint") or {}).get("Address")
        if db.get("host") != endpoint:
            problemas.append(f"{SECRETOS['db']}: host no es el endpoint de {INSTANCIA}")
        if type(db.get("port")) is not int or db.get("port") != 5432:
            problemas.append(f"{SECRETOS['db']}: port no es el número 5432")
        if db.get("dbname") != BASE or db.get("username") != USUARIO:
            problemas.append(f"{SECRETOS['db']}: dbname/username no son {BASE}/{USUARIO}")
        if not isinstance(db.get("password"), str) or not db.get("password"):
            problemas.append(f"{SECRETOS['db']}: password vacío")

    jwt = valores.get("jwt")
    if jwt is not None:
        if set(jwt) != {"secret"}:
            problemas.append(f"{SECRETOS['jwt']}: claves {sorted(jwt)}; debe ser solo secret")
        try:
            largo = len(base64.b64decode(str(jwt.get("secret", "")), validate=True))
        except (binascii.Error, ValueError):
            largo = -1
        if largo != 64:
            problemas.append(f"{SECRETOS['jwt']}: secret no es base64 de 64 bytes")

    admin = valores.get("admin_inicial")
    if admin is not None:
        if set(admin) != {"correo", "password"}:
            problemas.append(f"{SECRETOS['admin_inicial']}: claves {sorted(admin)}; deben ser correo y password")
        if admin.get("correo") != CORREO_ADMIN:
            problemas.append(f"{SECRETOS['admin_inicial']}: correo no es {CORREO_ADMIN}")
        if not isinstance(admin.get("password"), str) or not admin.get("password"):
            problemas.append(f"{SECRETOS['admin_inicial']}: password vacío")
    return comprobar(problemas, "db, jwt y admin-inicial con las claves de §5.4 (valores no impresos)")


def c5b_bucket(ctx: Contexto) -> str:
    s3 = ctx.cliente("s3")
    if (
        llamar(f"comprobar s3://{BUCKET} (s3:ListBucket)", lambda: s3.head_bucket(Bucket=BUCKET), "404", "NoSuchBucket")
        is None
    ):
        raise comun.Falla(f"no existe el bucket {BUCKET}")
    problemas = []

    cifrado = llamar(
        "leer el cifrado (s3:GetEncryptionConfiguration)",
        lambda: s3.get_bucket_encryption(Bucket=BUCKET),
        "ServerSideEncryptionConfigurationNotFoundError",
    )
    reglas = ((cifrado or {}).get("ServerSideEncryptionConfiguration") or {}).get("Rules", [])
    algoritmos = [(r.get("ApplyServerSideEncryptionByDefault") or {}).get("SSEAlgorithm") for r in reglas]
    if algoritmos != ["AES256"]:
        problemas.append(f"cifrado {algoritmos}, no SSE-S3 (AES256)")

    bloqueo = llamar(
        "leer Block Public Access (s3:GetBucketPublicAccessBlock)",
        lambda: s3.get_public_access_block(Bucket=BUCKET),
        "NoSuchPublicAccessBlockConfiguration",
    )
    indicadores = (bloqueo or {}).get("PublicAccessBlockConfiguration") or {}
    esperados = ("BlockPublicAcls", "IgnorePublicAcls", "BlockPublicPolicy", "RestrictPublicBuckets")
    if not all(indicadores.get(i) is True for i in esperados):
        problemas.append("Block Public Access incompleto")

    propiedad = llamar(
        "leer la propiedad de objetos (s3:GetBucketOwnershipControls)",
        lambda: s3.get_bucket_ownership_controls(Bucket=BUCKET),
        "OwnershipControlsNotFoundError",
    )
    reglas = ((propiedad or {}).get("OwnershipControls") or {}).get("Rules", [])
    if [r.get("ObjectOwnership") for r in reglas] != ["BucketOwnerEnforced"]:
        problemas.append("la propiedad de objetos no es BucketOwnerEnforced")

    versionado = llamar("leer el versionado (s3:GetBucketVersioning)", lambda: s3.get_bucket_versioning(Bucket=BUCKET))
    if versionado.get("Status"):
        problemas.append(f"versionado {versionado.get('Status')}; no debe haberse activado nunca")

    if llamar("leer CORS (s3:GetBucketCORS)", lambda: s3.get_bucket_cors(Bucket=BUCKET), "NoSuchCORSConfiguration"):
        problemas.append("tiene configuración CORS")

    ciclo = llamar(
        "leer el ciclo de vida (s3:GetLifecycleConfiguration)",
        lambda: s3.get_bucket_lifecycle_configuration(Bucket=BUCKET),
        "NoSuchLifecycleConfiguration",
    )
    reglas = (ciclo or {}).get("Rules", [])
    if len(reglas) != 1:
        problemas.append(f"{len(reglas)} reglas de ciclo de vida; debe haber una")
    else:
        regla = reglas[0]
        filtro = regla.get("Filter")
        todo_el_bucket = regla.get("Prefix", "") == "" and filtro in (None, {}, {"Prefix": ""})
        if (
            regla.get("Status") != "Enabled"
            or (regla.get("AbortIncompleteMultipartUpload") or {}).get("DaysAfterInitiation") != 7
            or not todo_el_bucket
        ):
            problemas.append(
                "la regla de ciclo de vida no aborta a los 7 días las subidas multiparte de todo el bucket"
            )
        if any(
            k in regla
            for k in ("Expiration", "Transitions", "NoncurrentVersionExpiration", "NoncurrentVersionTransitions")
        ):
            problemas.append("la regla de ciclo de vida expira o mueve objetos")

    url, atributos = ctx.cola("ingesta")
    notificacion = llamar(
        "leer la notificación (s3:GetBucketNotification)",
        lambda: s3.get_bucket_notification_configuration(Bucket=BUCKET),
    )
    colas = notificacion.get("QueueConfigurations", [])
    otras = (
        notificacion.get("TopicConfigurations")
        or notificacion.get("LambdaFunctionConfigurations")
        or "EventBridgeConfiguration" in notificacion
    )
    if len(colas) != 1 or otras:
        problemas.append(
            f"la notificación debe ser una sola, hacia ingesta ({len(colas)} hacia colas; otras: {bool(otras)})"
        )
    else:
        cola = colas[0]
        filtros = {
            str(r.get("Name", "")).lower(): r.get("Value")
            for r in ((cola.get("Filter") or {}).get("Key") or {}).get("FilterRules", [])
        }
        if cola.get("Events") != ["s3:ObjectCreated:*"]:
            problemas.append(f"eventos de la notificación {cola.get('Events')}")
        if filtros != {"prefix": "dataset/", "suffix": ".jpg"}:
            problemas.append(f"filtros de la notificación {filtros}")
        if cola.get("QueueArn") != atributos.get("QueueArn"):
            problemas.append("la notificación no apunta a la cola ingesta")

    politica = llamar(
        "leer la política (s3:GetBucketPolicy)", lambda: s3.get_bucket_policy(Bucket=BUCKET), "NoSuchBucketPolicy"
    )
    declaraciones = como_lista(json.loads(politica["Policy"]).get("Statement")) if politica else []
    solo_tls = any(
        d.get("Effect") == "Deny"
        and d.get("Principal") in ("*", {"AWS": "*"})
        and "s3:*" in como_lista(d.get("Action"))
        and {BUCKET_ARN, f"{BUCKET_ARN}/*"} <= set(como_lista(d.get("Resource")))
        and como_lista(((d.get("Condition") or {}).get("Bool") or {}).get("aws:SecureTransport")) == ["false"]
        for d in declaraciones
    )
    if not solo_tls:
        problemas.append("la política no deniega las peticiones sin TLS")
    if any(d.get("Effect") == "Allow" for d in declaraciones):
        problemas.append("la política concede permisos (Allow)")
    return comprobar(
        problemas,
        "SSE-S3, Block Public Access, BucketOwnerEnforced, sin versionado ni CORS, multiparte 7 días, solo TLS y "
        "notificación ObjectCreated dataset/*.jpg → ingesta",
    )


def politica_ingesta_correcta(politica: str, cola_arn: str) -> str | None:
    """Devuelve None si la política solo concede sqs:SendMessage a S3 desde el bucket del dataset; si no, el motivo."""
    try:
        declaraciones = como_lista(json.loads(politica).get("Statement"))
    except (ValueError, AttributeError):
        return "la política de ingesta no es JSON"
    if len(declaraciones) != 1:
        return f"la política de ingesta tiene {len(declaraciones)} declaraciones; debe tener una"
    d = declaraciones[0]
    condicion = d.get("Condition") or {}
    origen = (condicion.get("ArnEquals") or condicion.get("ArnLike") or {}).get("aws:SourceArn")
    cuenta = (condicion.get("StringEquals") or {}).get("aws:SourceAccount")
    if d.get("Effect") != "Allow":
        return "la declaración de ingesta no es Allow"
    if como_lista((d.get("Principal") or {}).get("Service") if isinstance(d.get("Principal"), dict) else None) != [
        "s3.amazonaws.com"
    ] or set(d.get("Principal")) != {"Service"}:
        return "el principal de la política de ingesta no es solo s3.amazonaws.com"
    if como_lista(d.get("Action")) != ["sqs:SendMessage"]:
        return f"la política de ingesta concede {como_lista(d.get('Action'))}"
    if como_lista(d.get("Resource")) != [cola_arn]:
        return "el recurso de la política de ingesta no es la cola"
    if como_lista(origen) != [BUCKET_ARN] or como_lista(cuenta) != [str(comun.CUENTA)]:
        return "la política de ingesta no exige aws:SourceArn = el bucket y aws:SourceAccount = la cuenta"
    return None


def c5c_colas(ctx: Contexto) -> str:
    problemas = []
    atributos = {}
    for clave in COLAS:
        try:
            atributos[clave] = ctx.cola(clave)[1]
        except comun.Falla as exc:
            problemas.append(str(exc))
    if problemas:
        raise comun.Falla("; ".join(problemas))

    for clave, visibilidad in (("ingesta", "180"), ("purga", "300")):
        a, dlq = atributos[clave], atributos[f"{clave}_dlq"]
        nombre = COLAS[clave]
        if a.get("VisibilityTimeout") != visibilidad:
            problemas.append(f"{nombre}: VisibilityTimeout {a.get('VisibilityTimeout')}, no {visibilidad}")
        if a.get("MessageRetentionPeriod") != "345600":
            problemas.append(f"{nombre}: retención {a.get('MessageRetentionPeriod')}, no 345600")
        if a.get("ReceiveMessageWaitTimeSeconds") != "20":
            problemas.append(f"{nombre}: espera larga {a.get('ReceiveMessageWaitTimeSeconds')}, no 20")
        try:
            redrive = json.loads(a.get("RedrivePolicy") or "{}")
        except ValueError:
            redrive = {}
        if redrive.get("deadLetterTargetArn") != dlq.get("QueueArn") or str(redrive.get("maxReceiveCount")) != "5":
            problemas.append(f"{nombre}: RedrivePolicy no es 5 recepciones → {COLAS[clave + '_dlq']}")
    for clave in ("ingesta_dlq", "purga_dlq"):
        a = atributos[clave]
        if a.get("MessageRetentionPeriod") != "1209600":
            problemas.append(f"{COLAS[clave]}: retención {a.get('MessageRetentionPeriod')}, no 1209600")
        if a.get("RedrivePolicy"):
            problemas.append(f"{COLAS[clave]}: una DLQ no debe tener RedrivePolicy")
    for clave, a in atributos.items():
        if a.get("SqsManagedSseEnabled") != "true":
            problemas.append(f"{COLAS[clave]}: sin SSE-SQS")
        if clave != "ingesta" and a.get("Policy"):
            problemas.append(f"{COLAS[clave]}: no debe tener política de recurso")
    motivo = politica_ingesta_correcta(atributos["ingesta"].get("Policy") or "{}", atributos["ingesta"].get("QueueArn"))
    if motivo:
        problemas.append(motivo)
    return comprobar(problemas, "visibilidad, retención, espera larga, DLQ, SSE-SQS y política de ingesta según §5.6")


# ---------------------------------------------------------------------------------------------------------------------
# C6: etiquetas
# ---------------------------------------------------------------------------------------------------------------------


def c6_etiquetas(ctx: Contexto) -> str:
    rds, s3, sqs, secretos = (ctx.cliente(s) for s in ("rds", "s3", "sqs", "secretsmanager"))
    recursos: dict[str, dict | None] = {}

    instancia = ctx.instancia()
    recursos[f"instancia {INSTANCIA}"] = etiquetas_de(instancia.get("TagList"))
    grupos = llamar(
        f"describir {GRUPO_PARAMETROS} (rds:DescribeDBParameterGroups)",
        lambda: rds.describe_db_parameter_groups(DBParameterGroupName=GRUPO_PARAMETROS),
        "DBParameterGroupNotFound",
        "DBParameterGroupNotFoundFault",
    )
    subredes = llamar(
        f"describir {GRUPO_SUBREDES_DB} (rds:DescribeDBSubnetGroups)",
        lambda: rds.describe_db_subnet_groups(DBSubnetGroupName=GRUPO_SUBREDES_DB),
        "DBSubnetGroupNotFoundFault",
        "DBSubnetGroupNotFound",
    )
    problemas = []
    for nombre, respuesta, lista, campo_arn in (
        (f"grupo de parámetros {GRUPO_PARAMETROS}", grupos, "DBParameterGroups", "DBParameterGroupArn"),
        (f"grupo de subredes {GRUPO_SUBREDES_DB}", subredes, "DBSubnetGroups", "DBSubnetGroupArn"),
    ):
        if not respuesta or not respuesta.get(lista):
            problemas.append(f"no existe el {nombre}")
            continue
        elemento = respuesta[lista][0]
        if campo_arn == "DBParameterGroupArn" and elemento.get("DBParameterGroupFamily") != FAMILIA_PARAMETROS:
            problemas.append(f"{nombre}: familia {elemento.get('DBParameterGroupFamily')}, no {FAMILIA_PARAMETROS}")
        arn = elemento[campo_arn]
        recursos[nombre] = etiquetas_de(
            llamar(
                f"leer etiquetas de {nombre} (rds:ListTagsForResource)",
                lambda a=arn: rds.list_tags_for_resource(ResourceName=a),
            ).get("TagList")
        )

    etiquetas_bucket = llamar(
        "leer etiquetas del bucket (s3:GetBucketTagging)", lambda: s3.get_bucket_tagging(Bucket=BUCKET), "NoSuchTagSet"
    )
    recursos[f"bucket {BUCKET}"] = etiquetas_de((etiquetas_bucket or {}).get("TagSet"))

    for clave, nombre in COLAS.items():
        url, _ = ctx.cola(clave)
        recursos[f"cola {nombre}"] = llamar(
            f"leer etiquetas de {nombre} (sqs:ListQueueTags)", lambda u=url: sqs.list_queue_tags(QueueUrl=u)
        ).get("Tags", {})

    for nombre in SECRETOS.values():
        descripcion = llamar(
            f"describir {nombre} (secretsmanager:DescribeSecret)",
            lambda n=nombre: secretos.describe_secret(SecretId=n),
            "ResourceNotFoundException",
        )
        if descripcion is None:
            problemas.append(f"no existe el secreto {nombre}")
            continue
        recursos[f"secreto {nombre}"] = etiquetas_de(descripcion.get("Tags"))

    for nombre, etiquetas in recursos.items():
        faltan = [f"{k}={v}" for k, v in ETIQUETAS.items() if etiquetas.get(k) != v]
        if faltan:
            problemas.append(f"{nombre} sin {', '.join(faltan)}")
    return comprobar(problemas, f"{len(recursos)} recursos con las cuatro etiquetas de §5.1")


# ---------------------------------------------------------------------------------------------------------------------
# Programa
# ---------------------------------------------------------------------------------------------------------------------


def cuerpo(v) -> None:
    ctx = Contexto()
    if not v.precondicion("P2", lambda: p2_credenciales(ctx)):
        v.precondicion_no_evaluada("P1", "P2 no se cumple (credenciales)")
        return
    if not v.precondicion("P1", lambda: p1_red(ctx)):
        return

    ctx.sello = v.sello
    ctx.claves = {
        "c1": f"dataset/validacion-{v.sello}/c1.jpg",
        "c2_png": f"dataset/validacion-{v.sello}/c2.png",
        "c2_thumb": f"thumbs/validacion-{v.sello}/c2.jpg",
    }
    v.comprobacion("C1", lambda: c1_notificacion(v, ctx))
    v.comprobacion("C2", lambda: c2_filtros(v, ctx))
    v.comprobacion("C3a", lambda: c3a_rds_privada(ctx))
    v.comprobacion("C3b", lambda: c3b_tls(ctx))
    v.comprobacion("C4", lambda: c4_version(ctx))
    v.comprobacion("C5a", lambda: c5a_secretos(ctx))
    v.comprobacion("C5b", lambda: c5b_bucket(ctx))
    v.comprobacion("C5c", lambda: c5c_colas(ctx))
    v.comprobacion("C5d", lambda: c5d_instancia(ctx))
    v.comprobacion("C6", lambda: c6_etiquetas(ctx))


def main() -> int:
    v = comun.Validador(
        lote="INF-1.2",
        validacion="validation-1-2",
        descripcion="INF-1.2 Datos y secretos: notificación S3 → SQS, RDS privada con TLS, secretos, bucket y colas",
        comprobaciones=["C1", "C2", "C3a", "C3b", "C4", "C5a", "C5b", "C5c", "C5d", "C6"],
        grupos={"C3": ["C3a", "C3b"], "C5": ["C5a", "C5b", "C5c", "C5d"]},
    )
    return v.correr(cuerpo)


if __name__ == "__main__":
    sys.exit(main())
