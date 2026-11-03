"""AWS falso para probar los validadores sin tocar la cuenta (INF-3.1; ARCHITECTURE §5.11).

`Mundo` guarda el estado (alarmas, topic, regla, colas, tareas, métricas) y un reloj falso: `dormir(s)` avanza el
reloj y simula lo que haría AWS en ese tiempo (alarmas de las DLQ que pasan a ALARM y avisan al topic, tareas que se
detienen y disparan la regla, métricas que aparecen con retraso). `Sesion(mundo).client(nombre)` devuelve un cliente
falso con las operaciones de boto3 que usan los validadores. Los interruptores del mundo (`retraso_alarma`,
`accion_ok`, `pendiente`, `stop_code`, `run_task_falla`…) fuerzan los casos de falla.
"""

from __future__ import annotations

import datetime as dt
import itertools
import json
from collections import defaultdict

from botocore.exceptions import ClientError, WaiterError

CUENTA = "648617469176"
REGION = "us-east-1"
P = "campus-locator-dev"
TOPIC_ARN = f"arn:aws:sns:{REGION}:{CUENTA}:{P}-alertas"
REGLA = f"{P}-tarea-detenida"
REGLA_ARN = f"arn:aws:events:{REGION}:{CUENTA}:rule/{REGLA}"
CLUSTER_ARN = f"arn:aws:ecs:{REGION}:{CUENTA}:cluster/{P}"
API_ID = "fuzq99kddb"
URL_COLA = f"https://sqs.{REGION}.amazonaws.com/{CUENTA}/"
CORREO = "persona@example.com"


def error(codigo: str, operacion: str = "Operacion", mensaje: str | None = None) -> ClientError:
    """ClientError de boto3 con `Error.Code` y `Error.Message` (por defecto, el mismo código)."""
    return ClientError({"Error": {"Code": codigo, "Message": mensaje or codigo}}, operacion)


def alarmas_bien(api_id: str = API_ID) -> dict[str, dict]:
    """Las seis alarmas como las crea el módulo observabilidad (forma de cloudwatch:DescribeAlarms)."""

    def alarma(nombre, espacio, metrica, dims, estadistica, periodo, periodos, comparacion, umbral):
        return {
            "AlarmName": f"{P}-{nombre}",
            "Namespace": espacio,
            "MetricName": metrica,
            "Dimensions": [{"Name": k, "Value": v} for k, v in dims.items()],
            "Statistic": estadistica,
            "Period": periodo,
            "EvaluationPeriods": periodos,
            "DatapointsToAlarm": periodos,
            "ComparisonOperator": comparacion,
            "Threshold": float(umbral),
            "TreatMissingData": "notBreaching",
            "AlarmActions": [TOPIC_ARN],
            "ActionsEnabled": True,
            "StateValue": "OK",
        }

    lista = [
        alarma("api-5xx", "AWS/ApiGateway", "5xx", {"ApiId": api_id}, "Sum", 300, 1, "GreaterThanThreshold", 5),
        alarma("ingesta-dlq", "AWS/SQS", "ApproximateNumberOfMessagesVisible", {"QueueName": f"{P}-ingesta-dlq"},
               "Maximum", 60, 1, "GreaterThanOrEqualToThreshold", 1),
        alarma("purga-dlq", "AWS/SQS", "ApproximateNumberOfMessagesVisible", {"QueueName": f"{P}-purga-dlq"},
               "Maximum", 60, 1, "GreaterThanOrEqualToThreshold", 1),
        alarma("embedding-encendida", "AWS/ECS", "CPUUtilization", {"ClusterName": P, "ServiceName": "embedding"},
               "SampleCount", 3600, 10, "GreaterThanThreshold", 0),
        alarma("rds-almacenamiento", "AWS/RDS", "FreeStorageSpace", {"DBInstanceIdentifier": f"{P}-db"}, "Minimum",
               300, 1, "LessThanThreshold", 4294967296),
        alarma("rds-creditos-cpu", "AWS/RDS", "CPUCreditBalance", {"DBInstanceIdentifier": f"{P}-db"}, "Minimum", 300,
               1, "LessThanThreshold", 20),
    ]
    return {a["AlarmName"]: a for a in lista}


def politica_bien() -> dict:
    """La política que genera el módulo (data aws_iam_policy_document.alertas)."""
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "Cuenta",
                "Effect": "Allow",
                "Principal": {"AWS": "*"},
                "Action": ["SNS:AddPermission", "SNS:DeleteTopic", "SNS:GetTopicAttributes",
                           "SNS:ListSubscriptionsByTopic", "SNS:Publish", "SNS:RemovePermission",
                           "SNS:SetTopicAttributes", "SNS:Subscribe"],
                "Resource": TOPIC_ARN,
                "Condition": {"StringEquals": {"AWS:SourceOwner": CUENTA}},
            },
            {
                "Sid": "CloudWatch",
                "Effect": "Allow",
                "Principal": {"Service": "cloudwatch.amazonaws.com"},
                "Action": "sns:Publish",
                "Resource": TOPIC_ARN,
                "Condition": {
                    "StringEquals": {"aws:SourceAccount": CUENTA},
                    "ArnLike": {"aws:SourceArn": f"arn:aws:cloudwatch:{REGION}:{CUENTA}:alarm:*"},
                },
            },
            {
                "Sid": "EventBridge",
                "Effect": "Allow",
                "Principal": {"Service": "events.amazonaws.com"},
                "Action": "sns:Publish",
                "Resource": TOPIC_ARN,
                "Condition": {"ArnEquals": {"aws:SourceArn": REGLA_ARN}},
            },
        ],
    }


def patron_bien() -> dict:
    """El patrón que genera el módulo desde 0.15.0 (jsonencode ordena las claves: `$or` va primero)."""
    return {
        "detail": {
            "$or": [
                {"group": ["service:api", "service:embedding", "service:worker"]},
                {"startedBy": ["validacion-3-1"]},
            ],
            "clusterArn": [CLUSTER_ARN],
            "lastStatus": ["STOPPED"],
            "stopCode": ["EssentialContainerExited", "TaskFailedToStart"],
        },
        "detail-type": ["ECS Task State Change"],
        "source": ["aws.ecs"],
    }


def patron_0_14() -> dict:
    """El patrón de 0.14.0, solo con la rama de los servicios (para las pruebas de un patrón viejo)."""
    patron = patron_bien()
    patron["detail"].pop("$or")
    patron["detail"]["group"] = ["service:api", "service:embedding", "service:worker"]
    return patron


def coincide(patron, evento) -> bool:
    """Coincidencia exacta de EventBridge (listas de valores, objetos anidados y `$or`: lo que usa la regla)."""
    for clave, esperado in patron.items():
        if clave == "$or":
            if not any(coincide(rama, evento) for rama in esperado):
                return False
        elif isinstance(esperado, dict):
            if not isinstance(evento.get(clave), dict) or not coincide(esperado, evento[clave]):
                return False
        elif evento.get(clave) not in esperado:
            return False
    return True


class Mundo:
    def __init__(self) -> None:
        self.t = dt.datetime(2026, 10, 28, 15, 0, 0, tzinfo=dt.UTC)
        self.mono = 1000.0
        self.ids = itertools.count(1)
        # Estado
        self.apis = [{"ApiId": API_ID, "Name": f"{P}-api", "ApiEndpoint": f"https://{API_ID}.execute-api.us-east-1.amazonaws.com"}]
        self.acciones_noche = [{"ScheduledActionName": f"{P}-embedding-apagar-noche"}]
        self.alarmas = alarmas_bien()
        self.historia: dict[str, list[dict]] = defaultdict(list)
        self.regla = {"Name": REGLA, "Arn": REGLA_ARN, "State": "ENABLED", "EventPattern": json.dumps(patron_bien())}
        self.destinos = [{"Id": "sns-alertas", "Arn": TOPIC_ARN}]
        self.politica = politica_bien()
        self.suscripciones = [{"Protocol": "email", "Endpoint": CORREO, "SubscriptionArn": f"{TOPIC_ARN}:1234"}]
        self.pendiente = False
        self.colas: dict[str, list[dict]] = {f"{URL_COLA}{P}-ingesta-dlq": [], f"{URL_COLA}{P}-purga-dlq": []}
        self.borrados: list[str] = []  # cuerpos borrados
        self.metricas: list[tuple] = []  # (espacio, métrica, dims frozenset, momento, valor)
        self.tareas: dict[str, dict] = {}
        self.run_task_args: list[dict] = []
        self.enviados: list[tuple] = []
        # Comportamiento
        self.retraso_alarma = 180  # s desde que una DLQ tiene mensajes hasta ALARM
        self.alarma_dispara = True
        self.accion_ok = True
        self.retraso_metricas = 120  # s hasta que CloudWatch devuelve un dato
        self.stop_code = "EssentialContainerExited"
        self.dura_tarea = 45
        self.run_task_falla: str | None = None  # código de error que devuelve run_task
        self.cuenta = CUENTA
        self.desde_mensajes: dict[str, dt.datetime] = {}

    # -- reloj ---------------------------------------------------------------------------------------------------------

    def ahora(self) -> dt.datetime:
        return self.t

    def monotonic(self) -> float:
        return self.mono

    def dormir(self, segundos: float) -> None:
        paso = 5.0
        restante = float(segundos)
        while restante > 0:
            d = min(paso, restante)
            self.t += dt.timedelta(seconds=d)
            self.mono += d
            restante -= d
            self.actualizar()

    # -- simulación ----------------------------------------------------------------------------------------------------

    def metrica(self, espacio: str, nombre: str, dims: dict, valor: float, momento: dt.datetime | None = None) -> None:
        self.metricas.append((espacio, nombre, frozenset(dims.items()), momento or self.t, valor))

    def publicar_sns(self) -> None:
        dims = {"TopicName": f"{P}-alertas"}
        self.metrica("AWS/SNS", "NumberOfMessagesPublished", dims, 1)
        if not self.pendiente:
            self.metrica("AWS/SNS", "NumberOfNotificationsDelivered", dims, 1)

    def visibles(self, url: str) -> int:
        return sum(1 for m in self.colas[url] if m["visible_desde"] <= self.t)

    def actualizar(self) -> None:
        for url in self.colas:
            nombre = url.rsplit("/", 1)[-1]
            alarma = self.alarmas.get(nombre)
            visibles = self.visibles(url)
            if visibles:
                self.desde_mensajes.setdefault(url, self.t)
                self.metrica("AWS/SQS", "ApproximateNumberOfMessagesVisible", {"QueueName": nombre}, visibles)
            else:
                self.desde_mensajes.pop(url, None)
            if alarma is None:
                continue
            if visibles and self.alarma_dispara and alarma["StateValue"] != "ALARM":
                if (self.t - self.desde_mensajes[url]).total_seconds() >= self.retraso_alarma:
                    self.cambiar(alarma, "ALARM")
            elif not visibles and alarma["StateValue"] == "ALARM":
                self.cambiar(alarma, "OK")
        for tarea in self.tareas.values():
            if tarea["lastStatus"] != "STOPPED" and (self.t - tarea["createdAt"]).total_seconds() >= self.dura_tarea:
                self.detener(tarea, self.stop_code, "Essential container in task exited")

    def cambiar(self, alarma: dict, estado: str) -> None:
        anterior = alarma["StateValue"]
        alarma["StateValue"] = estado
        self.historia[alarma["AlarmName"]].append(
            {"Timestamp": self.t, "HistoryItemType": "StateUpdate",
             "HistorySummary": f"Alarm updated from {anterior} to {estado}"}
        )
        if estado == "ALARM":
            if self.accion_ok:
                resumen = f"Successfully executed action {TOPIC_ARN}"
                self.publicar_sns()
            else:
                resumen = f"Failed to execute action {TOPIC_ARN}. Received error: not authorized"
            self.historia[alarma["AlarmName"]].append(
                {"Timestamp": self.t, "HistoryItemType": "Action", "HistorySummary": resumen}
            )

    def detener(self, tarea: dict, stop_code: str, razon: str) -> None:
        tarea.update(lastStatus="STOPPED", desiredStatus="STOPPED", stopCode=stop_code, stoppedReason=razon,
                     stoppedAt=self.t)
        if stop_code == "EssentialContainerExited":
            tarea["containers"][0]["exitCode"] = 3
        evento = {
            "source": "aws.ecs",
            "detail-type": "ECS Task State Change",
            "detail": {"clusterArn": CLUSTER_ARN, "lastStatus": "STOPPED", "stopCode": stop_code,
                       "group": tarea["group"], "startedBy": tarea["startedBy"]},
        }
        if self.regla["State"] == "ENABLED" and coincide(json.loads(self.regla["EventPattern"]), evento):
            dims = {"RuleName": REGLA}
            self.metrica("AWS/Events", "MatchedEvents", dims, 1)
            destinos_sns = [d for d in self.destinos if d["Arn"] == TOPIC_ARN]
            permitido = any(
                d.get("Principal", {}).get("Service") == "events.amazonaws.com" for d in self.politica["Statement"]
            )
            for _ in destinos_sns:
                if permitido:
                    self.metrica("AWS/Events", "Invocations", dims, 1)
                    self.publicar_sns()
                else:
                    self.metrica("AWS/Events", "FailedInvocations", dims, 1)


class Cliente:
    def __init__(self, mundo: Mundo) -> None:
        self.m = mundo


class Sts(Cliente):
    def get_caller_identity(self):
        return {"Account": self.m.cuenta, "Arn": f"arn:aws:iam::{self.m.cuenta}:user/prueba"}


class ApiGatewayV2(Cliente):
    def get_apis(self, **_):
        return {"Items": list(self.m.apis)}


class AutoScaling(Cliente):
    def describe_scheduled_actions(self, ServiceNamespace, ResourceId):  # noqa: N803
        return {"ScheduledActions": list(self.m.acciones_noche) if ResourceId.endswith("/embedding") else []}


class CloudWatch(Cliente):
    def describe_alarms(self, AlarmNames, AlarmTypes=None):  # noqa: N803
        return {"MetricAlarms": [dict(self.m.alarmas[n]) for n in AlarmNames if n in self.m.alarmas]}

    def describe_alarm_history(self, AlarmName, HistoryItemType, StartDate, MaxRecords=100):  # noqa: N803
        return {
            "AlarmHistoryItems": [
                h for h in self.m.historia[AlarmName]
                if h["HistoryItemType"] == HistoryItemType and h["Timestamp"] >= StartDate
            ][:MaxRecords]
        }

    def get_metric_statistics(self, Namespace, MetricName, Dimensions, StartTime, EndTime, Period, Statistics):  # noqa: N803
        dims = frozenset((d["Name"], d["Value"]) for d in Dimensions)
        por_minuto: dict[dt.datetime, list[float]] = defaultdict(list)
        for espacio, nombre, d, momento, valor in self.m.metricas:
            if (espacio, nombre, d) != (Namespace, MetricName, dims):
                continue
            if (self.m.t - momento).total_seconds() < self.m.retraso_metricas:
                continue  # todavía no publicado
            if StartTime <= momento < EndTime:
                por_minuto[momento.replace(second=0, microsecond=0)].append(valor)
        estadistica = Statistics[0]
        agregar = {"Sum": sum, "Maximum": max, "Minimum": min, "SampleCount": len}[estadistica]
        return {"Datapoints": [{"Timestamp": t, estadistica: float(agregar(v))} for t, v in por_minuto.items()]}


class Events(Cliente):
    def describe_rule(self, Name):  # noqa: N803
        if self.m.regla is None or self.m.regla["Name"] != Name:
            raise error("ResourceNotFoundException", "DescribeRule")
        return dict(self.m.regla, EventBusName="default")

    def list_targets_by_rule(self, Rule):  # noqa: N803
        return {"Targets": list(self.m.destinos)}

    def test_event_pattern(self, EventPattern, Event):  # noqa: N803
        evento = json.loads(Event)
        for campo in ("id", "account", "source", "time", "region", "resources", "detail-type"):
            if campo not in evento:  # obligatorios en AWS
                raise error("InvalidEventPatternException", "TestEventPattern", f"falta {campo}")
        return {"Result": coincide(json.loads(EventPattern), evento)}


class Sns(Cliente):
    def get_topic_attributes(self, TopicArn):  # noqa: N803
        return {"Attributes": {"TopicArn": TopicArn, "Policy": json.dumps(self.m.politica)}}

    def list_subscriptions_by_topic(self, TopicArn, NextToken=None):  # noqa: N803
        subs = []
        for s in self.m.suscripciones:
            s = dict(s, TopicArn=TopicArn)
            if self.m.pendiente:
                s["SubscriptionArn"] = "PendingConfirmation"
            subs.append(s)
        return {"Subscriptions": subs}

    def get_subscription_attributes(self, SubscriptionArn):  # noqa: N803
        return {"Attributes": {"PendingConfirmation": "true" if self.m.pendiente else "false"}}


class Sqs(Cliente):
    def get_queue_attributes(self, QueueUrl, AttributeNames):  # noqa: N803
        mensajes = self.m.colas[QueueUrl]
        visibles = self.m.visibles(QueueUrl)
        return {
            "Attributes": {
                "ApproximateNumberOfMessages": str(visibles),
                "ApproximateNumberOfMessagesNotVisible": str(len(mensajes) - visibles),
                "ApproximateNumberOfMessagesDelayed": "0",
            }
        }

    def send_message(self, QueueUrl, MessageBody):  # noqa: N803
        n = next(self.m.ids)
        self.m.colas[QueueUrl].append(
            {"MessageId": f"m{n}", "Body": MessageBody, "visible_desde": self.m.t, "recibido": 0, "handle": None}
        )
        self.m.enviados.append((QueueUrl, MessageBody))
        self.m.actualizar()
        return {"MessageId": f"m{n}"}

    def receive_message(self, QueueUrl, MaxNumberOfMessages=1, WaitTimeSeconds=0, VisibilityTimeout=30):  # noqa: N803
        salida = []
        for m in self.m.colas[QueueUrl]:
            if len(salida) >= MaxNumberOfMessages:
                break
            if m["visible_desde"] <= self.m.t:
                m["handle"] = f"h{next(self.m.ids)}"
                m["recibido"] += 1
                m["visible_desde"] = self.m.t + dt.timedelta(seconds=VisibilityTimeout)
                salida.append({"MessageId": m["MessageId"], "ReceiptHandle": m["handle"], "Body": m["Body"]})
        return {"Messages": salida} if salida else {}

    def delete_message_batch(self, QueueUrl, Entries):  # noqa: N803
        ok = []
        for e in Entries:
            for m in list(self.m.colas[QueueUrl]):
                if m["handle"] == e["ReceiptHandle"]:
                    self.m.colas[QueueUrl].remove(m)
                    self.m.borrados.append(m["Body"])
                    ok.append({"Id": e["Id"]})
        return {"Successful": ok, "Failed": []}

    def change_message_visibility_batch(self, QueueUrl, Entries):  # noqa: N803
        for e in Entries:
            for m in self.m.colas[QueueUrl]:
                if m["handle"] == e["ReceiptHandle"]:
                    m["visible_desde"] = self.m.t + dt.timedelta(seconds=e["VisibilityTimeout"])
        return {"Successful": [{"Id": e["Id"]} for e in Entries]}


class Esperador:
    def __init__(self, mundo: Mundo) -> None:
        self.m = mundo

    def wait(self, cluster, tasks, WaiterConfig):  # noqa: N803
        for _ in range(WaiterConfig["MaxAttempts"]):
            if all(self.m.tareas[a]["lastStatus"] == "STOPPED" for a in tasks):
                return
            self.m.dormir(WaiterConfig["Delay"])
        raise WaiterError(name="TasksStopped", reason="Max attempts exceeded", last_response={})


class Ecs(Cliente):
    def run_task(self, **kw):
        self.m.run_task_args.append(kw)
        if str(kw.get("group", "")).startswith("service:"):
            # Lo que respondió ECS en dev el 2026-10-26 a group = service:worker (CloudTrail, RunTask)
            raise error("InvalidParameterException", "RunTask", "Invalid namespace for group.")
        if self.m.run_task_falla:
            raise error(self.m.run_task_falla, "RunTask")
        n = next(self.m.ids)
        arn = f"arn:aws:ecs:{REGION}:{CUENTA}:task/{P}/tarea{n:04d}"
        grupo = kw.get("group") or f"family:{kw['taskDefinition']}"
        self.m.tareas[arn] = {
            "taskArn": arn, "group": grupo, "startedBy": kw.get("startedBy"), "lastStatus": "PROVISIONING",
            "desiredStatus": "RUNNING", "createdAt": self.m.t, "containers": [{"name": "app"}],
        }
        return {"tasks": [dict(self.m.tareas[arn])], "failures": []}

    def get_waiter(self, nombre):
        assert nombre == "tasks_stopped"
        return Esperador(self.m)

    def describe_tasks(self, cluster, tasks):
        return {"tasks": [dict(self.m.tareas[a]) for a in tasks if a in self.m.tareas]}

    def list_tasks(self, cluster, startedBy=None, desiredStatus="RUNNING", **_):  # noqa: N803
        return {
            "taskArns": [
                a for a, t in self.m.tareas.items()
                if t["startedBy"] == startedBy and t["desiredStatus"] == desiredStatus
            ]
        }

    def stop_task(self, cluster, task, reason):
        self.m.detener(self.m.tareas[task], "UserInitiated", reason)
        return {"task": dict(self.m.tareas[task])}


CLIENTES = {
    "sts": Sts,
    "apigatewayv2": ApiGatewayV2,
    "application-autoscaling": AutoScaling,
    "cloudwatch": CloudWatch,
    "events": Events,
    "sns": Sns,
    "sqs": Sqs,
    "ecs": Ecs,
}


class Sesion:
    def __init__(self, mundo: Mundo) -> None:
        self.m = mundo

    def client(self, nombre: str, region_name: str | None = None):
        return CLIENTES[nombre](self.m)


class Reloj:
    """Sustituto del módulo `time` dentro de comun y validate31."""

    def __init__(self, mundo: Mundo) -> None:
        self.m = mundo

    def monotonic(self) -> float:
        return self.m.monotonic()

    def sleep(self, segundos: float) -> None:
        self.m.dormir(segundos)


def salidas(**cambios) -> dict:
    base = {
        "sns_alertas_arn": TOPIC_ARN,
        "api_base_url": f"https://{API_ID}.execute-api.us-east-1.amazonaws.com",
        "ecs_cluster": P,
        "familias_tarea": {"api": f"{P}-api", "validacion": f"{P}-validacion"},
        "subredes_tareas": ["subnet-1"],
        "sg_migrate": "sg-1",
        "sqs_ingesta_dlq_url": f"{URL_COLA}{P}-ingesta-dlq",
        "sqs_purga_dlq_url": f"{URL_COLA}{P}-purga-dlq",
    }
    base.update(cambios)
    return {k: v for k, v in base.items() if v is not None}
