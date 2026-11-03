"""Validador de INF-3.1 — Observabilidad y alarmas.

Documento: docs/validation/validation-3-1.md. Contrato común: docs/ARCHITECTURE.md §5.11.

Uso (desde INFRASTRUCTURA_TERRAFORM/project/; dura 10-30 min, hasta ~1 h si las métricas tardan):
    uv run --group ops python src/ops/validate31.py --entorno dev [--informe RUTA] [--solo C1,C3] [--sin-limpieza]

No toca los servicios api, worker ni embedding: C3 lanza una tarea suelta de la definición de validación que sale con
error, con startedBy = validacion-3-1 (la rama de prueba de la regla; ECS no admite group = service:… en una tarea
suelta), y C2 deja un mensaje marcado en una DLQ, que borra al terminar. C1b prueba la rama de los servicios con
events:TestEventPattern.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import sys
import time
from dataclasses import dataclass, field

from botocore.exceptions import WaiterError

import comun
import embedding as emb

PREFIJO = emb.PREFIJO
CLUSTER = emb.CLUSTER
CLUSTER_ARN = f"arn:aws:ecs:{comun.REGION}:{comun.CUENTA}:cluster/{CLUSTER}"
NOMBRE_API = f"{PREFIJO}-api"
TOPIC = f"{PREFIJO}-alertas"
REGLA = f"{PREFIJO}-tarea-detenida"
INSTANCIA = f"{PREFIJO}-db"
ACCION_NOCHE = f"{PREFIJO}-embedding-apagar-noche"
DLQ = {"ingesta": f"{PREFIJO}-ingesta-dlq", "purga": f"{PREFIJO}-purga-dlq"}  # cola y alarma se llaman igual (§5.1)
SALIDA_DLQ = {"ingesta": "sqs_ingesta_dlq_url", "purga": "sqs_purga_dlq_url"}
MARCA = "validacion-3-1"  # también el startedBy de la tarea de prueba, que la regla acepta (§5.10)
CODIGO_PRUEBA = 3  # código de salida del contenedor de la tarea de prueba
STOP_CODES = ("EssentialContainerExited", "TaskFailedToStart")
GRUPOS_REGLA = ("service:api", "service:embedding", "service:worker")
ANTIGUEDAD_RESTO_S = 60 * 60  # una marca de otra ejecución con más de esto es un resto (una ejecución dura < 1 h)
SALIDAS = (
    "sns_alertas_arn",
    "api_base_url",
    "ecs_cluster",
    "familias_tarea",
    "subredes_tareas",
    "sg_migrate",
    "sqs_ingesta_dlq_url",
    "sqs_purga_dlq_url",
)

# Tiempos (validation-3-1 §2). Se leen en tiempo de ejecución: las pruebas locales los acortan.
T = {
    "ok": 10 * 60,  # C2a: espera a que la alarma de una DLQ vacía salga de ALARM antes de usarla
    "alarma": 20 * 60,  # C2a: envío → ALARM (SQS tarda hasta 15 min en publicar de una cola inactiva, §3.4)
    "accion": 2 * 60,  # C2a: ALARM → entrada «Action» en la historia de la alarma
    "sns": 10 * 60,  # C2a, C3b: aviso → NumberOfNotificationsDelivered en CloudWatch
    "tarea": 10 * 60,  # C3a: run-task → STOPPED
    "eventos": 10 * 60,  # C3b: tarea detenida → MatchedEvents e Invocations de la regla
    "leer": 60,  # lectura de una DLQ para borrar mensajes de prueba
    "sondeo": 30,
}
TOLERANCIA_RELOJ = dt.timedelta(seconds=60)  # reloj local frente al de AWS


# ---------------------------------------------------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------------------------------------------------

llamar = emb.llamar


def llamar_precondicion(accion: str, fn, *codigos_ausente: str):
    """Como `llamar`, para las precondiciones: un error de AWS que no es «no existe» es de entorno (código 3)."""
    try:
        return llamar(accion, fn, *codigos_ausente)
    except comun.Falla as exc:
        raise comun.ErrorConfiguracion(str(exc)) from exc


def comprobar(problemas: list[str], detalle: str) -> str:
    if problemas:
        raise comun.Falla("; ".join(problemas))
    return detalle


def minutos(segundos: float) -> str:
    return f"{segundos / 60:.1f} min"


def minuto(momento: dt.datetime) -> dt.datetime:
    return momento.replace(second=0, microsecond=0)


def bogota(momento: dt.datetime) -> str:
    return f"{emb.hora_bogota(momento):%H:%M} de Bogotá"


def id_tarea(arn: str) -> str:
    return arn.rsplit("/", 1)[-1]


def enmascarar(correo: str) -> str:
    """El correo no se imprime entero (el informe puede acabar en un PR público): «fr…@gmail.com»."""
    usuario, _, dominio = correo.partition("@")
    return f"{usuario[:2]}…@{dominio}"


def leer_correo() -> str:
    """correo_alertas de envs/dev/terraform.tfvars (§5.3)."""
    ruta = comun.PROYECTO / "envs" / "dev" / "terraform.tfvars"
    try:
        texto = ruta.read_text(encoding="utf-8")
    except OSError as exc:
        raise comun.ErrorConfiguracion(f"no se puede leer {ruta}: {exc}") from exc
    encontrado = re.search(r'^correo_alertas\s*=\s*"([^"]+)"', texto, flags=re.MULTILINE)
    if not encontrado:
        raise comun.Falla("envs/dev/terraform.tfvars no tiene correo_alertas (§5.3)")
    return encontrado[1]


def alarmas_esperadas(api_id: str) -> dict[str, dict]:
    """Las seis alarmas de §5.1 con los parámetros de §5.10 (ARCHITECTURE §5.12, módulo observabilidad)."""

    def alarma(espacio, metrica, dims, estadistica, periodo, periodos, comparacion, umbral) -> dict:
        return {
            "Namespace": espacio,
            "MetricName": metrica,
            "Dimensions": dims,
            "Statistic": estadistica,
            "Period": periodo,
            "EvaluationPeriods": periodos,
            "DatapointsToAlarm": periodos,
            "ComparisonOperator": comparacion,
            "Threshold": float(umbral),
            "TreatMissingData": "notBreaching",
        }

    dlq = {
        DLQ[c]: alarma(
            "AWS/SQS", "ApproximateNumberOfMessagesVisible", {"QueueName": DLQ[c]}, "Maximum", 60, 1,
            "GreaterThanOrEqualToThreshold", 1,
        )
        for c in DLQ
    }
    return {
        f"{PREFIJO}-api-5xx": alarma(
            "AWS/ApiGateway", "5xx", {"ApiId": api_id}, "Sum", 300, 1, "GreaterThanThreshold", 5
        ),
        **dlq,
        f"{PREFIJO}-embedding-encendida": alarma(
            "AWS/ECS", "CPUUtilization", {"ClusterName": CLUSTER, "ServiceName": "embedding"}, "SampleCount", 3600, 10,
            "GreaterThanThreshold", 0,
        ),
        f"{PREFIJO}-rds-almacenamiento": alarma(
            "AWS/RDS", "FreeStorageSpace", {"DBInstanceIdentifier": INSTANCIA}, "Minimum", 300, 1, "LessThanThreshold",
            4294967296,
        ),
        f"{PREFIJO}-rds-creditos-cpu": alarma(
            "AWS/RDS", "CPUCreditBalance", {"DBInstanceIdentifier": INSTANCIA}, "Minimum", 300, 1, "LessThanThreshold",
            20,
        ),
    }


def patron_esperado() -> dict:
    """Patrón de la regla de §5.10 (las listas se comparan sin orden)."""
    return {
        "source": ["aws.ecs"],
        "detail-type": ["ECS Task State Change"],
        "detail": {
            "clusterArn": [CLUSTER_ARN],
            "lastStatus": ["STOPPED"],
            "stopCode": list(STOP_CODES),
            "$or": [{"group": list(GRUPOS_REGLA)}, {"startedBy": [MARCA]}],
        },
    }


def evento_ecs(group: str, stop_code: str, *, started_by: str = "ecs-svc/1234567890123456789",
               cluster: str = CLUSTER_ARN, last_status: str = "STOPPED") -> dict:
    """Evento `ECS Task State Change` sintético con los campos obligatorios de events:TestEventPattern."""
    return {
        "version": "0",
        "id": "00000000-0000-0000-0000-000000000000",
        "detail-type": "ECS Task State Change",
        "source": "aws.ecs",
        "account": comun.CUENTA,
        "time": "2026-10-26T00:00:00Z",
        "region": comun.REGION,
        "resources": [f"arn:aws:ecs:{comun.REGION}:{comun.CUENTA}:task/{CLUSTER}/{MARCA}"],
        "detail": {
            "clusterArn": cluster,
            "group": group,
            "startedBy": started_by,
            "lastStatus": last_status,
            "desiredStatus": "STOPPED",
            "stopCode": stop_code,
        },
    }


# (descripción, evento, ¿debe avisar?) para C1b: la rama de los servicios, la de la tarea de prueba y lo que no avisa.
CASOS_PATRON = [
    ("worker que termina", evento_ecs("service:worker", "EssentialContainerExited"), True),
    ("api que no arranca", evento_ecs("service:api", "TaskFailedToStart"), True),
    ("embedding que termina", evento_ecs("service:embedding", "EssentialContainerExited"), True),
    ("tarea de prueba de validate31", evento_ecs(f"family:{PREFIJO}-validacion", "EssentialContainerExited",
                                                 started_by=MARCA), True),
    ("migrate que termina (aunque salga con 0)", evento_ecs(f"family:{PREFIJO}-migrate", "EssentialContainerExited",
                                                             started_by="ecs-cli"), False),
    ("tarea de validación de otro validador", evento_ecs(f"family:{PREFIJO}-validacion", "EssentialContainerExited",
                                                         started_by="validacion-1-3"), False),
    ("worker apagado o escalado", evento_ecs("service:worker", "ServiceSchedulerInitiated"), False),
    ("worker de otro clúster", evento_ecs("service:worker", "EssentialContainerExited",
                                          cluster=f"arn:aws:ecs:{comun.REGION}:{comun.CUENTA}:cluster/otro"), False),
    ("worker que se está deteniendo", evento_ecs("service:worker", "EssentialContainerExited",
                                                 last_status="DEPROVISIONING"), False),
]


def normalizar_patron(valor):
    if isinstance(valor, dict):
        return {k: normalizar_patron(v) for k, v in valor.items()}
    if isinstance(valor, list):
        return sorted(json.dumps(normalizar_patron(v), sort_keys=True) for v in valor)
    return valor


def clasificar(cuerpo: str, sello: str) -> str:
    """Mensajes de prueba de C2a: {"validacion": "validacion-3-1-<AAAAMMDD-HHMMSS>"}. «propio» (esta ejecución), «resto»
    (otra con más de una hora) o «ajeno» (lo demás, incluida otra ejecución reciente)."""
    try:
        datos = json.loads(cuerpo)
    except ValueError:
        return "ajeno"
    marca = datos.get("validacion") if isinstance(datos, dict) else None
    m = re.fullmatch(rf"{MARCA}-(\d{{8}}-\d{{6}})", marca if isinstance(marca, str) else "")
    if not m:
        return "ajeno"
    if m[1] == sello:
        return "propio"
    try:
        otro = dt.datetime.strptime(m[1], "%Y%m%d-%H%M%S").replace(tzinfo=dt.UTC)
        propio = dt.datetime.strptime(sello, "%Y%m%d-%H%M%S").replace(tzinfo=dt.UTC)
    except ValueError:
        return "ajeno"
    return "resto" if (propio - otro).total_seconds() > ANTIGUEDAD_RESTO_S else "ajeno"


def como_lista(valor) -> list:
    """En una política de IAM, Action, Resource y cada Principal pueden ser una cadena o una lista."""
    if valor is None:
        return []
    return [valor] if isinstance(valor, str) else list(valor)


def acciones_de(valor) -> list[str]:
    return [a.lower() for a in como_lista(valor)]


def principales(declaracion: dict, tipo: str) -> list[str]:
    principal = declaracion.get("Principal")
    if principal == "*":
        return ["*"] if tipo == "AWS" else []
    return como_lista((principal or {}).get(tipo))


# ---------------------------------------------------------------------------------------------------------------------
# Estado compartido
# ---------------------------------------------------------------------------------------------------------------------


@dataclass
class Contexto:
    sello: str = ""
    sin_limpieza: bool = False
    sesion: object = None
    clientes: dict = field(default_factory=dict)
    salidas: dict = field(default_factory=dict)
    api_id: str = ""
    api_endpoint: str = ""
    topic_arn: str = ""
    correo: str = ""
    pendientes: dict = field(default_factory=dict)  # clave de DLQ → mensajes propios sin borrar
    dlq_usada: str = ""
    aviso_c2: tuple | None = None  # (alarma, momento del paso a ALARM)
    tarea: dict | None = None  # C3: la tarea detenida (describe-tasks)
    error_tarea: Exception | None = None
    t_tarea: dt.datetime | None = None  # C3: justo antes del run-task
    tareas_lanzadas: list = field(default_factory=list)

    def cliente(self, nombre: str):
        if nombre not in self.clientes:
            self.clientes[nombre] = self.sesion.client(nombre, region_name=comun.REGION)
        return self.clientes[nombre]

    def red_tareas(self) -> dict:
        return {
            "awsvpcConfiguration": {
                "subnets": list(self.salidas["subredes_tareas"]),
                "securityGroups": [self.salidas["sg_migrate"]],
                "assignPublicIp": "ENABLED",
            }
        }


# ---------------------------------------------------------------------------------------------------------------------
# Precondiciones
# ---------------------------------------------------------------------------------------------------------------------


def p4_credenciales(ctx: Contexto) -> str:
    ctx.sesion = comun.sesion_aws()
    return f"{comun.comprobar_cuenta(ctx.sesion)} (cuenta {comun.CUENTA})"


def p1_borde(ctx: Contexto) -> str:
    gw = ctx.cliente("apigatewayv2")

    def todas():
        apis, token = [], None
        while True:
            pagina = gw.get_apis(**({"NextToken": token} if token else {}))
            apis += pagina.get("Items", [])
            token = pagina.get("NextToken")
            if not token:
                return apis

    apis = [a for a in llamar_precondicion("listar APIs (apigateway:GET)", todas) if a.get("Name") == NOMBRE_API]
    if not apis:
        raise comun.Bloqueo(f"INF-1.4 no está aplicado: no existe la HTTP API {NOMBRE_API}")
    ctx.api_id, ctx.api_endpoint = apis[0]["ApiId"], apis[0].get("ApiEndpoint", "")
    return f"{NOMBRE_API} ({ctx.api_id})"


def p2_apagado(ctx: Contexto) -> str:
    aas = ctx.cliente("application-autoscaling")
    acciones = llamar_precondicion(
        "leer las acciones programadas de embedding (application-autoscaling:DescribeScheduledActions)",
        lambda: aas.describe_scheduled_actions(ServiceNamespace="ecs", ResourceId=emb.recurso("embedding")),
    ).get("ScheduledActions", [])
    if not any(a.get("ScheduledActionName") == ACCION_NOCHE for a in acciones):
        raise comun.Bloqueo(f"INF-2.1 no está aplicado: falta la acción programada {ACCION_NOCHE}")
    return ACCION_NOCHE


def p3_salidas(ctx: Contexto) -> str:
    ctx.salidas = comun.terraform_outputs("envs/dev")
    if "sns_alertas_arn" not in ctx.salidas:
        raise comun.Bloqueo("INF-3.1 no está aplicado en envs/dev: falta el output sns_alertas_arn")
    faltan = [s for s in SALIDAS if s not in ctx.salidas]
    if not faltan and "validacion" not in (ctx.salidas.get("familias_tarea") or {}):
        faltan.append("familias_tarea.validacion")
    if faltan:
        raise comun.Bloqueo(f"envs/dev no tiene los outputs {', '.join(faltan)}")
    problemas = []
    if ctx.salidas["ecs_cluster"] != CLUSTER:
        problemas.append(f"ecs_cluster = {ctx.salidas['ecs_cluster']!r}, no {CLUSTER}")
    if ctx.salidas["api_base_url"] != ctx.api_endpoint:
        problemas.append(f"api_base_url ({ctx.salidas['api_base_url']}) no es el ApiEndpoint de {NOMBRE_API}")
    for clave, salida in SALIDA_DLQ.items():
        if not str(ctx.salidas[salida]).endswith(f"/{DLQ[clave]}"):
            problemas.append(f"{salida} no apunta a {DLQ[clave]}")
    if not str(ctx.salidas["sns_alertas_arn"]).endswith(f":{TOPIC}"):
        problemas.append(f"sns_alertas_arn no apunta a {TOPIC}")
    if problemas:
        raise comun.Bloqueo("; ".join(problemas))
    ctx.topic_arn = ctx.salidas["sns_alertas_arn"]
    return ", ".join(SALIDAS)


# ---------------------------------------------------------------------------------------------------------------------
# C1: configuración
# ---------------------------------------------------------------------------------------------------------------------


def c1a_alarmas(ctx: Contexto) -> str:
    esperadas = alarmas_esperadas(ctx.api_id)
    cw = ctx.cliente("cloudwatch")
    existentes = {
        a["AlarmName"]: a
        for a in llamar(
            "leer las alarmas (cloudwatch:DescribeAlarms)",
            lambda: cw.describe_alarms(AlarmNames=list(esperadas), AlarmTypes=["MetricAlarm"]),
        ).get("MetricAlarms", [])
    }
    problemas, estados = [], []
    for nombre, esperada in esperadas.items():
        a = existentes.get(nombre)
        if a is None:
            problemas.append(f"no existe la alarma {nombre}")
            continue
        vista = {clave: a.get(clave) for clave in esperada}
        vista["Dimensions"] = {d["Name"]: d["Value"] for d in a.get("Dimensions", [])}
        if vista.get("Threshold") is not None:
            vista["Threshold"] = float(vista["Threshold"])
        distintos = [f"{k} = {vista[k]!r} (se espera {v!r})" for k, v in esperada.items() if vista[k] != v]
        if distintos:
            problemas.append(f"{nombre}: {', '.join(distintos)}")
        if ctx.topic_arn not in (a.get("AlarmActions") or []) or not a.get("ActionsEnabled", True):
            problemas.append(f"{nombre}: acciones {a.get('AlarmActions')}, no avisa a {TOPIC}")
        estados.append(f"{nombre.removeprefix(PREFIJO + '-')} {a.get('StateValue')}")
    return comprobar(
        problemas, f"las 6 alarmas de §5.10 avisan a {TOPIC} con sus umbrales; estados: {', '.join(estados)}"
    )


def c1b_regla(ctx: Contexto) -> str:
    events = ctx.cliente("events")
    regla = llamar(
        f"leer la regla {REGLA} (events:DescribeRule)",
        lambda: events.describe_rule(Name=REGLA),
        "ResourceNotFoundException",
    )
    if regla is None:
        raise comun.Falla(f"no existe la regla {REGLA}")
    problemas = []
    if regla.get("State") != "ENABLED":
        problemas.append(f"la regla está {regla.get('State')}")
    try:
        patron = json.loads(regla.get("EventPattern") or "{}")
    except ValueError:
        patron = {}
    if normalizar_patron(patron) != normalizar_patron(patron_esperado()):
        problemas.append(f"patrón {json.dumps(patron, sort_keys=True)}; se espera {json.dumps(patron_esperado())}")
    # La rama de los servicios no la ejercita C3 (una tarea suelta no puede llevar group = service:…): se prueba el
    # patrón guardado en AWS contra eventos sintéticos (sin efectos).
    for descripcion, evento, debe in CASOS_PATRON:
        resultado = llamar(
            f"probar el patrón de {REGLA} (events:TestEventPattern)",
            lambda e=evento: events.test_event_pattern(EventPattern=regla.get("EventPattern") or "{}", Event=json.dumps(e)),
        ).get("Result")
        if resultado is not debe:
            problemas.append(f"con «{descripcion}» la regla {'no avisaría' if debe else 'avisaría'}")
    destinos = llamar(
        f"leer los destinos de {REGLA} (events:ListTargetsByRule)", lambda: events.list_targets_by_rule(Rule=REGLA)
    ).get("Targets", [])
    if [d.get("Arn") for d in destinos] != [ctx.topic_arn]:
        problemas.append(f"destinos {[d.get('Arn') for d in destinos]}; se espera solo {TOPIC}")
    sns = ctx.cliente("sns")
    atributos = llamar(
        f"leer {TOPIC} (sns:GetTopicAttributes)", lambda: sns.get_topic_attributes(TopicArn=ctx.topic_arn)
    ).get("Attributes", {})
    try:
        declaraciones = json.loads(atributos.get("Policy") or "{}").get("Statement", [])
    except ValueError:
        declaraciones = []
    if isinstance(declaraciones, dict):
        declaraciones = [declaraciones]

    def permite(principal_tipo: str, principal: str) -> list[dict]:
        return [
            d
            for d in declaraciones
            if d.get("Effect") == "Allow"
            and principal in principales(d, principal_tipo)
            and "sns:publish" in acciones_de(d.get("Action"))
            and {ctx.topic_arn, "*"} & set(como_lista(d.get("Resource")))
        ]

    eventbridge = permite("Service", "events.amazonaws.com")
    if not eventbridge:
        problemas.append(f"la política de {TOPIC} no deja publicar a events.amazonaws.com")
    elif not any(regla.get("Arn", "") in json.dumps(d.get("Condition", {})) for d in eventbridge):
        problemas.append(f"la política deja publicar a events.amazonaws.com sin limitarlo a {REGLA}")
    cuenta = [d for d in permite("AWS", "*") if comun.CUENTA in json.dumps(d.get("Condition", {}))]
    if not (permite("Service", "cloudwatch.amazonaws.com") or cuenta):
        problemas.append(f"la política de {TOPIC} no deja publicar a las alarmas (cloudwatch.amazonaws.com ni la cuenta)")
    return comprobar(
        problemas,
        f"{REGLA} ENABLED con el patrón de §5.10 ({', '.join(GRUPOS_REGLA)} o startedBy {MARCA}; "
        f"{', '.join(STOP_CODES)}) → {TOPIC}; TestEventPattern: {len(CASOS_PATRON)} casos como se espera; "
        "la política del topic deja publicar a la regla y a CloudWatch",
    )


def suscripcion(ctx: Contexto) -> str:
    """Comprueba que hay una suscripción email a correo_alertas y que está confirmada. Devuelve su descripción."""
    if not ctx.correo:
        ctx.correo = leer_correo()
    sns = ctx.cliente("sns")

    def todas():
        lista, token = [], None
        while True:
            pagina = sns.list_subscriptions_by_topic(
                TopicArn=ctx.topic_arn, **({"NextToken": token} if token else {})
            )
            lista += pagina.get("Subscriptions", [])
            token = pagina.get("NextToken")
            if not token:
                return lista

    subs = llamar(f"leer las suscripciones de {TOPIC} (sns:ListSubscriptionsByTopic)", todas)
    correo = [
        s for s in subs if s.get("Protocol") == "email" and (s.get("Endpoint") or "").lower() == ctx.correo.lower()
    ]
    oculto = enmascarar(ctx.correo)
    if not correo:
        raise comun.Falla(f"{TOPIC} no tiene una suscripción email a {oculto} (correo_alertas)")
    arn = correo[0].get("SubscriptionArn", "")
    if arn == "PendingConfirmation" or not arn.startswith("arn:"):
        raise comun.Falla(
            f"la suscripción email a {oculto} está pendiente de confirmación: abrir el enlace del correo «AWS "
            "Notification - Subscription Confirmation» (ARCHITECTURE §3.8)"
        )
    atributos = llamar(
        "leer la suscripción (sns:GetSubscriptionAttributes)", lambda: sns.get_subscription_attributes(SubscriptionArn=arn)
    ).get("Attributes", {})
    if atributos.get("PendingConfirmation", "false") != "false":
        raise comun.Falla(f"la suscripción email a {oculto} está pendiente de confirmación")
    return f"suscripción email a {oculto} confirmada"


def c1c_suscripcion(ctx: Contexto) -> str:
    return suscripcion(ctx)


# ---------------------------------------------------------------------------------------------------------------------
# Métricas
# ---------------------------------------------------------------------------------------------------------------------


def puntos(ctx: Contexto, espacio: str, metrica: str, dims: dict, desde: dt.datetime, estadistica: str) -> list[float]:
    """Valores por minuto de una métrica desde el minuto de `desde` (cloudwatch:GetMetricStatistics)."""
    cw = ctx.cliente("cloudwatch")
    respuesta = llamar(
        f"leer {espacio} {metrica} (cloudwatch:GetMetricStatistics)",
        lambda: cw.get_metric_statistics(
            Namespace=espacio,
            MetricName=metrica,
            Dimensions=[{"Name": k, "Value": v} for k, v in dims.items()],
            StartTime=minuto(desde) - dt.timedelta(minutes=1),
            EndTime=comun.ahora_utc() + dt.timedelta(minutes=1),
            Period=60,
            Statistics=[estadistica],
        ),
    )
    return [p.get(estadistica, 0.0) for p in respuesta.get("Datapoints", []) if p["Timestamp"] >= minuto(desde)]


def suma(ctx: Contexto, espacio: str, metrica: str, dims: dict, desde: dt.datetime) -> float:
    return sum(puntos(ctx, espacio, metrica, dims, desde, "Sum"))


def maximos(ctx: Contexto, espacio: str, metrica: str, dims: dict, desde: dt.datetime) -> list[float]:
    return puntos(ctx, espacio, metrica, dims, desde, "Maximum")


def sns_desde(ctx: Contexto, desde: dt.datetime) -> dict[str, float]:
    dims = {"TopicName": TOPIC}
    return {
        clave: suma(ctx, "AWS/SNS", metrica, dims, desde)
        for clave, metrica in (
            ("publicados", "NumberOfMessagesPublished"),
            ("entregados", "NumberOfNotificationsDelivered"),
            ("fallidos", "NumberOfNotificationsFailed"),
        )
    }


def esperar_entregas(ctx: Contexto, desde: dt.datetime, que: str) -> dict[str, float]:
    """Espera a que CloudWatch registre ≥ 1 notificación entregada del topic desde `desde` (minuto completo)."""
    limite = time.monotonic() + T["sns"]
    while True:
        cuenta = sns_desde(ctx, desde)
        if cuenta["entregados"] >= 1 or cuenta["fallidos"] >= 1 or time.monotonic() > limite:
            break
        time.sleep(T["sondeo"])
    if cuenta["fallidos"]:
        raise comun.Falla(
            f"{que}: SNS registró {cuenta['fallidos']:.0f} notificación(es) fallida(s) y "
            f"{cuenta['entregados']:.0f} entregada(s) desde las {bogota(desde)}"
        )
    if cuenta["entregados"] < 1:
        causa = (
            "el topic recibió el aviso pero no lo entregó (¿suscripción sin confirmar? C1c)"
            if cuenta["publicados"]
            else "el topic no recibió ningún mensaje"
        )
        raise comun.Falla(f"{que}: SNS no registró entregas en {minutos(T['sns'])}: {causa}")
    return cuenta


def metrica_regla(ctx: Contexto, metrica: str, desde: dt.datetime) -> float:
    """Métrica de AWS/Events de la regla. En el bus por defecto va con la dimensión RuleName (así la publica hoy la
    cuenta); por si acaso se mira también con EventBusName, y se toma el mayor (no se suman: serían los mismos)."""
    return max(
        suma(ctx, "AWS/Events", metrica, dims, desde)
        for dims in ({"RuleName": REGLA}, {"EventBusName": "default", "RuleName": REGLA})
    )


# ---------------------------------------------------------------------------------------------------------------------
# C2: un mensaje en una DLQ dispara su alarma y llega el correo
# ---------------------------------------------------------------------------------------------------------------------


def contar(ctx: Contexto, clave: str) -> dict[str, int]:
    sqs = ctx.cliente("sqs")
    nombres = {
        "visibles": "ApproximateNumberOfMessages",
        "en_vuelo": "ApproximateNumberOfMessagesNotVisible",
        "retrasados": "ApproximateNumberOfMessagesDelayed",
    }
    atributos = llamar(
        f"contar mensajes de {DLQ[clave]} (sqs:GetQueueAttributes)",
        lambda: sqs.get_queue_attributes(
            QueueUrl=ctx.salidas[SALIDA_DLQ[clave]], AttributeNames=list(nombres.values())
        ),
    ).get("Attributes", {})
    return {corto: int(atributos.get(largo, 0)) for corto, largo in nombres.items()}


def estado_alarma(ctx: Contexto, nombre: str) -> str:
    cw = ctx.cliente("cloudwatch")
    alarmas = llamar(
        f"leer la alarma {nombre} (cloudwatch:DescribeAlarms)",
        lambda: cw.describe_alarms(AlarmNames=[nombre], AlarmTypes=["MetricAlarm"]),
    ).get("MetricAlarms", [])
    if not alarmas:
        raise comun.Falla(f"no existe la alarma {nombre}")
    return alarmas[0].get("StateValue", "")


def lector(ctx: Contexto, clave: str) -> comun.LectorCola:
    return comun.LectorCola(
        ctx.cliente("sqs"), ctx.salidas[SALIDA_DLQ[clave]], DLQ[clave], lambda cuerpo: clasificar(cuerpo, ctx.sello)
    )


def limpiar_restos(ctx: Contexto) -> None:
    """Al empezar: borra de las DLQ los mensajes validacion-3-1 de ejecuciones anteriores (más de una hora). Solo lee
    una DLQ con entre 1 y 10 mensajes visibles y ninguno en vuelo; los ajenos vuelven a la cola enseguida."""
    for clave in DLQ:
        cuenta = contar(ctx, clave)
        if not 1 <= cuenta["visibles"] <= 10 or cuenta["en_vuelo"]:
            continue
        lec = lector(ctx, clave)
        try:
            lec.leer(20)
        finally:
            lec.devolver()
        if lec.borrados:
            comun.avisar(f"borrados {lec.borrados} mensaje(s) {MARCA} de ejecuciones anteriores en {DLQ[clave]}")


def borrar_propios(ctx: Contexto) -> None:
    """Borra los mensajes propios que queden en las DLQ (los ajenos vuelven con visibilidad 0)."""
    for clave, quedan in list(ctx.pendientes.items()):
        if not quedan:
            continue
        lec = lector(ctx, clave)
        try:
            lec.leer(T["leer"], objetivo=quedan)
        finally:
            lec.devolver()
        ctx.pendientes[clave] = max(quedan - lec.borrados, 0)
        if ctx.pendientes[clave]:
            raise comun.Falla(f"no se encontró el mensaje {MARCA} propio en {DLQ[clave]} para borrarlo")
        comun.avisar(f"mensaje {MARCA} borrado de {DLQ[clave]} (su alarma vuelve a OK en unos minutos)")


def elegir_dlq(ctx: Contexto) -> str:
    """Una DLQ vacía cuya alarma no esté en ALARM (si no, el mensaje no cambiaría su estado y no habría aviso)."""
    vistas = {}
    for clave in DLQ:
        mensajes, estado = sum(contar(ctx, clave).values()), estado_alarma(ctx, DLQ[clave])
        if mensajes == 0 and estado != "ALARM":
            return clave
        vistas[clave] = (mensajes, estado)
    vacias = [c for c, (n, _) in vistas.items() if n == 0]
    if not vacias:
        detalle = ", ".join(f"{DLQ[c]}: {n}" for c, (n, _) in vistas.items())
        raise comun.Falla(
            f"las dos DLQ tienen mensajes ajenos ({detalle}) y sus alarmas ya avisaron: revisarlas (re-enviar con "
            "redrive) antes de validar; el validador no toca mensajes ajenos"
        )
    clave = vacias[0]
    comun.avisar(f"{DLQ[clave]} está vacía pero su alarma sigue en ALARM: esperando OK (hasta {minutos(T['ok'])})…")
    limite = time.monotonic() + T["ok"]
    while estado_alarma(ctx, DLQ[clave]) == "ALARM":
        if time.monotonic() > limite:
            raise comun.Falla(f"{DLQ[clave]} está vacía y su alarma sigue en ALARM tras {minutos(T['ok'])}")
        time.sleep(T["sondeo"])
    return clave


def paso_a_alarm(ctx: Contexto, nombre: str, desde: dt.datetime) -> dt.datetime | None:
    """Momento del primer paso a ALARM de la alarma desde `desde` (cloudwatch:DescribeAlarmHistory)."""
    cw = ctx.cliente("cloudwatch")
    historia = llamar(
        f"leer la historia de {nombre} (cloudwatch:DescribeAlarmHistory)",
        lambda: cw.describe_alarm_history(
            AlarmName=nombre, HistoryItemType="StateUpdate", StartDate=desde - TOLERANCIA_RELOJ, MaxRecords=100
        ),
    ).get("AlarmHistoryItems", [])
    pasos = [h["Timestamp"] for h in historia if "to ALARM" in (h.get("HistorySummary") or "")]
    return min(pasos) if pasos else None


def accion_publicada(ctx: Contexto, nombre: str, desde: dt.datetime) -> str:
    """Busca en la historia de la alarma la entrada «Action» del aviso al topic: «ok», «falla: …» o «sin entrada»."""
    cw = ctx.cliente("cloudwatch")
    limite = time.monotonic() + T["accion"]
    while True:
        historia = llamar(
            f"leer las acciones de {nombre} (cloudwatch:DescribeAlarmHistory)",
            lambda: cw.describe_alarm_history(
                AlarmName=nombre, HistoryItemType="Action", StartDate=desde - TOLERANCIA_RELOJ, MaxRecords=100
            ),
        ).get("AlarmHistoryItems", [])
        resumenes = [h.get("HistorySummary") or "" for h in historia]
        fallidas = [r for r in resumenes if "fail" in r.lower()]
        if fallidas:
            return f"falla: {comun.resumir(fallidas[0], 200)}"
        if any(TOPIC in r or "sns" in r.lower() for r in resumenes):
            return "ok"
        if time.monotonic() > limite:
            return "sin entrada"
        time.sleep(T["sondeo"])


def c2a_dlq(ctx: Contexto) -> str:
    suscripcion(ctx)
    clave = elegir_dlq(ctx)
    ctx.dlq_usada = nombre = DLQ[clave]
    sqs = ctx.cliente("sqs")
    t_envio = comun.ahora_utc()
    llamar(
        f"enviar el mensaje de prueba a {nombre} (sqs:SendMessage)",
        lambda: sqs.send_message(
            QueueUrl=ctx.salidas[SALIDA_DLQ[clave]], MessageBody=json.dumps({"validacion": f"{MARCA}-{ctx.sello}"})
        ),
    )
    ctx.pendientes[clave] = ctx.pendientes.get(clave, 0) + 1
    comun.avisar(f"mensaje {MARCA} en {nombre}; esperando a que su alarma pase a ALARM (hasta {minutos(T['alarma'])})…")
    inicio = time.monotonic()
    while (t_alarma := paso_a_alarm(ctx, nombre, t_envio)) is None:
        if time.monotonic() - inicio > T["alarma"]:
            puntos = maximos(ctx, "AWS/SQS", "ApproximateNumberOfMessagesVisible", {"QueueName": nombre}, t_envio)
            visto = "SQS no publicó la métrica de la cola" if not puntos else f"la métrica llegó a {max(puntos):.0f}"
            raise comun.Falla(
                f"{nombre} no pasó a ALARM en {minutos(T['alarma'])} (estado {estado_alarma(ctx, nombre)}; "
                f"desde el envío, {visto})"
            )
        time.sleep(T["sondeo"])
    ctx.aviso_c2 = (nombre, t_alarma)
    accion = accion_publicada(ctx, nombre, t_alarma)
    if accion.startswith("falla"):
        raise comun.Falla(f"{nombre} pasó a ALARM pero no pudo avisar a {TOPIC} ({accion})")
    cuenta = esperar_entregas(ctx, t_alarma, nombre)
    if not ctx.sin_limpieza:
        borrar_propios(ctx)
    retraso = (t_alarma - t_envio).total_seconds()
    nota = "" if accion == "ok" else "; la historia de la alarma no muestra la acción (se comprobó con SNS)"
    return (
        f"{nombre} → ALARM a los {minutos(retraso)} del envío ({bogota(t_alarma)}); SNS: "
        f"{cuenta['entregados']:.0f} entregada(s), 0 fallidas{nota}"
    )


# ---------------------------------------------------------------------------------------------------------------------
# C3: una tarea detenida por error dispara la regla y llega el correo
# ---------------------------------------------------------------------------------------------------------------------


def tareas_vivas(ctx: Contexto) -> list[str]:
    ecs = ctx.cliente("ecs")
    return llamar(
        "listar las tareas de prueba (ecs:ListTasks)",
        lambda: ecs.list_tasks(cluster=CLUSTER, startedBy=MARCA, desiredStatus="RUNNING"),
    ).get("taskArns", [])


def detener_tareas(ctx: Contexto) -> None:
    """Detiene las tareas con startedBy = validacion-3-1 que sigan vivas (normalmente ya se detuvieron solas)."""
    ecs = ctx.cliente("ecs")
    for arn in tareas_vivas(ctx):
        llamar(
            "detener una tarea de prueba (ecs:StopTask)",
            lambda a=arn: ecs.stop_task(cluster=CLUSTER, task=a, reason=f"{MARCA}: limpieza"),
        )
        comun.avisar(f"tarea de prueba {id_tarea(arn)} detenida")


def lanzar_tarea(ctx: Contexto) -> dict:
    """Lanza (una sola vez) la tarea de prueba y espera a que se detenga. Devuelve su describe-tasks."""
    if ctx.error_tarea is not None:
        raise comun.Falla(f"la tarea de prueba no se pudo usar: {ctx.error_tarea}")
    if ctx.tarea is not None:
        return ctx.tarea
    try:
        ecs = ctx.cliente("ecs")
        ctx.t_tarea = comun.ahora_utc()
        respuesta = llamar(
            "lanzar la tarea de prueba (ecs:RunTask)",
            lambda: ecs.run_task(
                cluster=CLUSTER,
                taskDefinition=ctx.salidas["familias_tarea"]["validacion"],
                launchType="FARGATE",
                startedBy=MARCA,  # la rama de prueba de la regla; sin group (queda family:…): service:… da error
                count=1,
                networkConfiguration=ctx.red_tareas(),
                overrides={
                    "containerOverrides": [
                        {
                            "name": "app",
                            "command": ["sh", "-c", f"echo '{MARCA}: sale con error a proposito'; exit {CODIGO_PRUEBA}"],
                        }
                    ]
                },
            ),
        )
        if respuesta.get("failures") or not respuesta.get("tasks"):
            raise comun.Falla(f"run-task falló: {respuesta.get('failures')}")
        arn = respuesta["tasks"][0]["taskArn"]
        ctx.tareas_lanzadas.append(arn)
        comun.avisar(f"tarea de prueba {id_tarea(arn)} lanzada (startedBy {MARCA}); esperando a que se detenga…")
        with comun.errores_aws("esperar la tarea de prueba (ecs:DescribeTasks)"):
            try:
                ecs.get_waiter("tasks_stopped").wait(
                    cluster=CLUSTER, tasks=[arn], WaiterConfig={"Delay": 6, "MaxAttempts": T["tarea"] // 6}
                )
            except WaiterError as exc:
                raise comun.Falla(f"la tarea de prueba no se detuvo en {minutos(T['tarea'])}") from exc
        ctx.tarea = llamar(
            "describir la tarea de prueba (ecs:DescribeTasks)", lambda: ecs.describe_tasks(cluster=CLUSTER, tasks=[arn])
        )["tasks"][0]
        return ctx.tarea
    except Exception as exc:
        ctx.error_tarea = exc
        raise


def c3a_tarea(ctx: Contexto) -> str:
    tarea = lanzar_tarea(ctx)
    app = next((c for c in tarea.get("containers", []) if c.get("name") == "app"), {})
    problemas = []
    if tarea.get("startedBy") != MARCA:
        problemas.append(f"la tarea tiene startedBy {tarea.get('startedBy')!r}, no {MARCA}: la regla no la contaría")
    if tarea.get("stopCode") not in STOP_CODES:
        problemas.append(
            f"stopCode {tarea.get('stopCode')!r} ({comun.resumir(tarea.get('stoppedReason') or '', 120)}), no "
            f"{' ni '.join(STOP_CODES)}"
        )
    segundos = (tarea.get("stoppedAt", comun.ahora_utc()) - ctx.t_tarea).total_seconds()
    return comprobar(
        problemas,
        f"tarea {id_tarea(tarea['taskArn'])} (group {tarea.get('group')}, startedBy {MARCA}) detenida con stopCode "
        f"{tarea.get('stopCode')} (app salió con {app.get('exitCode')}) a los {minutos(segundos)} ({bogota(ctx.t_tarea)})",
    )


def c3b_regla(ctx: Contexto) -> str:
    tarea = lanzar_tarea(ctx)
    desde = ctx.t_tarea
    comun.avisar(f"esperando las métricas de {REGLA} (hasta {minutos(T['eventos'])})…")
    limite = time.monotonic() + T["eventos"]
    while True:
        cuenta = {m: metrica_regla(ctx, m, desde) for m in ("MatchedEvents", "Invocations", "FailedInvocations")}
        listo = cuenta["MatchedEvents"] >= 1 and (cuenta["Invocations"] >= 1 or cuenta["FailedInvocations"] >= 1)
        if listo or time.monotonic() > limite:
            break
        time.sleep(T["sondeo"])
    if cuenta["MatchedEvents"] < 1:
        raise comun.Falla(
            f"{REGLA} no registró ningún evento coincidente en {minutos(T['eventos'])} (la tarea quedó con group "
            f"{tarea.get('group')} y stopCode {tarea.get('stopCode')}; patrón en C1b)"
        )
    if cuenta["FailedInvocations"]:
        raise comun.Falla(
            f"{REGLA}: {cuenta['FailedInvocations']:.0f} invocación(es) fallida(s): EventBridge no pudo publicar en "
            f"{TOPIC} (¿política del topic? C1b)"
        )
    if cuenta["Invocations"] < 1:
        raise comun.Falla(f"{REGLA} coincidió con el evento pero no invocó a su destino")
    regla = (
        f"{REGLA}: {cuenta['MatchedEvents']:.0f} evento(s) coincidente(s), {cuenta['Invocations']:.0f} invocación(es), "
        "0 fallidas"
    )
    try:
        suscripcion(ctx)  # sin confirmar, SNS no entrega: no tiene sentido esperar sus métricas
    except comun.Falla as exc:
        raise comun.Falla(f"{regla}; pero {exc}") from exc
    entregas = esperar_entregas(ctx, tarea.get("stoppedAt") or desde, REGLA)
    return f"{regla}; SNS: {entregas['entregados']:.0f} entregada(s), 0 fallidas"


# ---------------------------------------------------------------------------------------------------------------------
# Programa
# ---------------------------------------------------------------------------------------------------------------------


def manuales(v, ctx: Contexto) -> None:
    try:
        buzon = enmascarar(ctx.correo or leer_correo())
    except (comun.Falla, comun.ErrorConfiguracion):
        buzon = "correo_alertas (§5.3)"
    if v.incluida("C2a"):
        if ctx.aviso_c2:
            alarma, momento = ctx.aviso_c2
            que = f"el correo de CloudWatch «ALARM: \"{alarma}\" …» de las {bogota(momento)}"
        else:
            que = "el correo de CloudWatch con «ALARM» y el nombre de la alarma de la DLQ (C2a no llegó a verlo)"
        v.manual("C2b", f"revisar el buzón de {buzon}: {que}; captura sin datos privados en el PR")
    if v.alguna_incluida("C3a", "C3b"):
        if ctx.tarea:
            que = (
                f"el correo «AWS Notification Message» con el evento ECS Task State Change de la tarea "
                f"{id_tarea(ctx.tarea['taskArn'])} (startedBy {MARCA}, stopCode {ctx.tarea.get('stopCode')})"
            )
        else:
            que = f"el correo con el evento ECS Task State Change de la tarea con startedBy {MARCA} (C3a no la vio detenida)"
        v.manual("C3c", f"revisar el buzón de {buzon}: {que}; captura sin datos privados en el PR")


def cuerpo(v) -> None:
    ctx = Contexto(sello=v.sello, sin_limpieza=bool(v.args and v.args.sin_limpieza))
    if not v.precondicion("P4", lambda: p4_credenciales(ctx)):
        for p in ("P1", "P2", "P3"):
            v.precondicion_no_evaluada(p, "P4 no se cumple (credenciales)")
        return
    if not v.precondicion("P1", lambda: p1_borde(ctx)):
        v.precondicion_no_evaluada("P2", "P1 no se cumple")
        v.precondicion_no_evaluada("P3", "P1 no se cumple")
        return
    if not v.precondicion("P2", lambda: p2_apagado(ctx)):
        v.precondicion_no_evaluada("P3", "P2 no se cumple")
        return
    if not v.precondicion("P3", lambda: p3_salidas(ctx)):
        return

    if v.incluida("C2a"):
        limpiar_restos(ctx)
        v.al_limpiar(f"borrar el mensaje {MARCA} propio de las DLQ", lambda: borrar_propios(ctx))
    if v.alguna_incluida("C3a", "C3b"):
        detener_tareas(ctx)  # restos de una ejecución anterior que no se detuvieron
        v.al_limpiar(f"detener las tareas con startedBy {MARCA} que sigan vivas", lambda: detener_tareas(ctx))

    v.comprobacion("C1a", lambda: c1a_alarmas(ctx))
    v.comprobacion("C1b", lambda: c1b_regla(ctx))
    v.comprobacion("C1c", lambda: c1c_suscripcion(ctx))
    v.comprobacion("C3a", lambda: c3a_tarea(ctx))
    v.comprobacion("C3b", lambda: c3b_regla(ctx))
    v.comprobacion("C2a", lambda: c2a_dlq(ctx))
    manuales(v, ctx)


def main() -> int:
    v = comun.Validador(
        lote="INF-3.1",
        validacion="validation-3-1",
        descripcion="INF-3.1 Observabilidad y alarmas: alarmas de §5.10 y suscripción por correo; un mensaje en una "
        "DLQ dispara su alarma y una tarea detenida por error, la regla de EventBridge (dura 10-30 min)",
        comprobaciones=["C1a", "C1b", "C1c", "C2a", "C3a", "C3b"],
        grupos={"C1": ["C1a", "C1b", "C1c"], "C2": ["C2a"], "C3": ["C3a", "C3b"]},
    )
    return v.correr(cuerpo)


if __name__ == "__main__":
    sys.exit(main())
