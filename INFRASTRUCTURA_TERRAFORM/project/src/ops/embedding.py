"""Encendido, apagado y estado de embedding (ARCHITECTURE §3.4, §5.10, ADR-INF-14, ADR-INF-15; INF-2.1).

Uso (desde INFRASTRUCTURA_TERRAFORM/project/, con AWS_PROFILE):
    uv run --group ops python src/ops/embedding.py encender [--sin-esperar]
    uv run --group ops python src/ops/embedding.py apagar [--sin-esperar]
    uv run --group ops python src/ops/embedding.py estado

- encender: rango 0-1 en los objetivos de Application Auto Scaling de embedding y worker; una muestra de
  EmbeddingEncendidos (campus-locator/dev), que cuenta como uso; espera a que la alarma embedding-inactivo la haya
  visto y no esté en ALARM (si lo estuviera, su política volvería a poner embedding en 0) y pone embedding en 1. Por
  defecto espera hasta 10 min (contados desde el principio) a que esté sano: tarea HEALTHY, despliegue COMPLETED e
  instancia sana en Cloud Map.
- apagar: rango 0-0 y desiredCount 0 en embedding y worker (los mensajes esperan en las colas). Por defecto espera a
  que no quede ninguna tarea de los dos.
- estado: solo lee (servicios, rangos, alarmas, colas y apagado nocturno).

Códigos de salida: 0 hecho; 1 no quedó como se pedía en el tiempo de espera; 2 falta un lote (INF-1.3 o INF-2.1 sin
aplicar); 3 credenciales, permisos o uso. No imprime secretos ni URLs prefirmadas.

validate21.py y otros validadores de esta carpeta importan `Operador` en vez de repetir estos pasos (§5.11).
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
import time
from collections.abc import Callable

from botocore.exceptions import ClientError

import comun

PREFIJO = "campus-locator-dev"
CLUSTER = PREFIJO
NAMESPACE = "campus-locator.local"
ESCALADOS = ("embedding", "worker")
DIMENSION = "ecs:service:DesiredCount"
ESPACIO_METRICAS = "campus-locator/dev"
METRICA_ENCENDIDOS = "EmbeddingEncendidos"
ALARMA_INACTIVIDAD = f"{PREFIJO}-embedding-inactivo"
ALARMAS_WORKER = (f"{PREFIJO}-worker-cola-ingesta", f"{PREFIJO}-worker-cola-purga", f"{PREFIJO}-worker-colas-vacias")
COLAS = {"ingesta": f"{PREFIJO}-ingesta", "purga": f"{PREFIJO}-purga"}

ESPERA_SANO_S = 600  # encender → sano (PLAN INF-2.1 C1: ≤ 10 min)
ESPERA_ALARMA_S = 300  # la alarma de inactividad sale de ALARM tras la muestra de EmbeddingEncendidos (~1-3 min)
ESPERA_APAGADO_S = 600
SONDEO_S = 15


def recurso(servicio: str) -> str:
    return f"service/{CLUSTER}/{servicio}"


def llamar(accion: str, fn: Callable, *codigos_ausente: str):
    """Ejecuta una llamada de boto3. None si el error es uno de `codigos_ausente`; los demás los traduce
    comun.errores_aws (permisos o credenciales → código 3; el resto → Falla)."""
    with comun.errores_aws(accion):
        try:
            return fn()
        except ClientError as exc:
            if comun.codigo_error_aws(exc) in codigos_ausente:
                return None
            raise


def hora_bogota(momento: dt.datetime | None = None) -> dt.datetime:
    """Hora de Bogotá. Sin base de zonas (Windows sin tzdata) usa UTC-5: Colombia no tiene horario de verano."""
    momento = momento or comun.ahora_utc()
    try:
        from zoneinfo import ZoneInfo

        return momento.astimezone(ZoneInfo("America/Bogota"))
    except Exception:  # noqa: BLE001 — ZoneInfoNotFoundError u otra ausencia de la base de zonas
        return momento.astimezone(dt.timezone(dt.timedelta(hours=-5)))


class Operador:
    """Las operaciones de embedding.py sobre una sesión de boto3 ya comprobada (comun.comprobar_cuenta)."""

    def __init__(self, sesion, avisar: Callable[[str], None] = comun.avisar) -> None:
        self.sesion = sesion
        self.avisar = avisar
        self._clientes: dict = {}
        self.t_latido: dt.datetime | None = None  # última muestra de EmbeddingEncendidos publicada

    def cliente(self, nombre: str):
        if nombre not in self._clientes:
            self._clientes[nombre] = self.sesion.client(nombre, region_name=comun.REGION)
        return self._clientes[nombre]

    # -- lectura ------------------------------------------------------------------------------------------------------

    def servicio(self, nombre: str) -> dict:
        respuesta = llamar(
            f"describir el servicio {nombre} (ecs:DescribeServices)",
            lambda: self.cliente("ecs").describe_services(cluster=CLUSTER, services=[nombre]),
            "ClusterNotFoundException",
        )
        activos = [s for s in (respuesta or {}).get("services", []) if s.get("status") == "ACTIVE"]
        if not activos:
            raise comun.Bloqueo(f"INF-1.3 no está aplicado: no existe el servicio {nombre} en {CLUSTER}")
        return activos[0]

    def objetivo(self, nombre: str) -> dict | None:
        respuesta = llamar(
            f"leer el objetivo escalable de {nombre} (application-autoscaling:DescribeScalableTargets)",
            lambda: self.cliente("application-autoscaling").describe_scalable_targets(
                ServiceNamespace="ecs", ResourceIds=[recurso(nombre)], ScalableDimension=DIMENSION
            ),
        )
        objetivos = respuesta.get("ScalableTargets", [])
        return objetivos[0] if objetivos else None

    def alarma(self, nombre: str) -> dict | None:
        respuesta = llamar(
            f"leer la alarma {nombre} (cloudwatch:DescribeAlarms)",
            lambda: self.cliente("cloudwatch").describe_alarms(AlarmNames=[nombre], AlarmTypes=["MetricAlarm"]),
        )
        alarmas = respuesta.get("MetricAlarms", [])
        return alarmas[0] if alarmas else None

    def tareas(self, nombre: str) -> list[dict]:
        ecs = self.cliente("ecs")
        arns = llamar(
            f"listar tareas de {nombre} (ecs:ListTasks)",
            lambda: ecs.list_tasks(cluster=CLUSTER, serviceName=nombre, desiredStatus="RUNNING"),
        ).get("taskArns", [])
        if not arns:
            return []
        return llamar(
            f"describir tareas de {nombre} (ecs:DescribeTasks)", lambda: ecs.describe_tasks(cluster=CLUSTER, tasks=arns)
        ).get("tasks", [])

    def instancias_sanas(self, nombre: str) -> list[dict]:
        respuesta = llamar(
            f"descubrir {nombre}.{NAMESPACE} (servicediscovery:DiscoverInstances)",
            lambda: self.cliente("servicediscovery").discover_instances(
                NamespaceName=NAMESPACE, ServiceName=nombre, HealthStatus="HEALTHY"
            ),
            "NamespaceNotFound",
            "ServiceNotFound",
        )
        return (respuesta or {}).get("Instances", [])

    def cola(self, clave: str) -> dict[str, int]:
        """Mensajes visibles, en vuelo y retrasados de una cola (§5.6). GetQueueAttributes la «despierta» (§3.4)."""
        sqs = self.cliente("sqs")
        url = llamar(
            f"buscar la cola {COLAS[clave]} (sqs:GetQueueUrl)", lambda: sqs.get_queue_url(QueueName=COLAS[clave])
        )
        nombres = {
            "visibles": "ApproximateNumberOfMessages",
            "en_vuelo": "ApproximateNumberOfMessagesNotVisible",
            "retrasados": "ApproximateNumberOfMessagesDelayed",
        }
        atributos = llamar(
            f"contar mensajes de {COLAS[clave]} (sqs:GetQueueAttributes)",
            lambda: sqs.get_queue_attributes(QueueUrl=url["QueueUrl"], AttributeNames=list(nombres.values())),
        ).get("Attributes", {})
        return {corto: int(atributos.get(largo, 0)) for corto, largo in nombres.items()}

    def acciones_noche(self) -> list[dict]:
        aas = self.cliente("application-autoscaling")
        acciones = []
        for nombre in ESCALADOS:
            acciones += llamar(
                f"leer las acciones programadas de {nombre} (application-autoscaling:DescribeScheduledActions)",
                lambda n=nombre: aas.describe_scheduled_actions(ServiceNamespace="ecs", ResourceId=recurso(n)),
            ).get("ScheduledActions", [])
        return acciones

    def sano(self) -> tuple[bool, str]:
        """¿embedding sano? runningCount ≥ 1, despliegue PRIMARY COMPLETED, tarea HEALTHY e instancia sana en Cloud
        Map. Devuelve también un detalle corto de lo que falta."""
        servicio = self.servicio("embedding")
        primario = next((d for d in servicio.get("deployments", []) if d.get("status") == "PRIMARY"), {})
        tareas = self.tareas("embedding")
        sanas = [t for t in tareas if t.get("lastStatus") == "RUNNING" and t.get("healthStatus") == "HEALTHY"]
        instancias = self.instancias_sanas("embedding") if sanas else []
        faltan = []
        if servicio.get("desiredCount", 0) < 1:
            faltan.append("desiredCount 0")
        if servicio.get("runningCount", 0) < 1:
            faltan.append(f"runningCount {servicio.get('runningCount', 0)}")
        if primario.get("rolloutState") != "COMPLETED":
            faltan.append(f"despliegue {primario.get('rolloutState')}")
        if not sanas:
            faltan.append(f"tareas {[(t.get('lastStatus'), t.get('healthStatus')) for t in tareas]}")
        elif not instancias:
            faltan.append("sin instancia sana en Cloud Map")
        return not faltan, "; ".join(faltan)

    # -- cambios ------------------------------------------------------------------------------------------------------

    def registrar(self, nombre: str, maximo: int) -> None:
        """Rango 0-maximo del objetivo de nombre. Nunca lo crea: si falta, INF-2.1 no está aplicado (crearlo aquí lo
        dejaría fuera de Terraform)."""
        if self.objetivo(nombre) is None:
            raise comun.Bloqueo(f"INF-2.1 no está aplicado: falta el objetivo escalable de {nombre}")
        llamar(
            f"poner {nombre} en 0-{maximo} (application-autoscaling:RegisterScalableTarget)",
            lambda: self.cliente("application-autoscaling").register_scalable_target(
                ServiceNamespace="ecs",
                ResourceId=recurso(nombre),
                ScalableDimension=DIMENSION,
                MinCapacity=0,
                MaxCapacity=maximo,
            ),
        )

    def poner(self, nombre: str, replicas: int) -> None:
        llamar(
            f"poner {nombre} en {replicas} (ecs:UpdateService)",
            lambda: self.cliente("ecs").update_service(cluster=CLUSTER, service=nombre, desiredCount=replicas),
        )

    def publicar_encendido(self) -> None:
        """Una muestra de EmbeddingEncendidos con marca de tiempo explícita: latido_visible la busca en ese minuto, sin
        depender de que el reloj local coincida con el de AWS."""
        momento = comun.ahora_utc()
        llamar(
            f"publicar {METRICA_ENCENDIDOS} (cloudwatch:PutMetricData)",
            lambda: self.cliente("cloudwatch").put_metric_data(
                Namespace=ESPACIO_METRICAS,
                MetricData=[{"MetricName": METRICA_ENCENDIDOS, "Timestamp": momento, "Value": 1, "Unit": "Count"}],
            ),
        )
        self.t_latido = momento

    def latido_visible(self) -> bool:
        """¿CloudWatch ya devuelve la muestra de EmbeddingEncendidos publicada por publicar_encendido?"""
        desde = self.t_latido.replace(second=0, microsecond=0)
        respuesta = llamar(
            f"leer {METRICA_ENCENDIDOS} (cloudwatch:GetMetricStatistics)",
            lambda: self.cliente("cloudwatch").get_metric_statistics(
                Namespace=ESPACIO_METRICAS,
                MetricName=METRICA_ENCENDIDOS,
                Dimensions=[],
                StartTime=desde - dt.timedelta(minutes=1),
                EndTime=comun.ahora_utc() + dt.timedelta(minutes=1),
                Period=60,
                Statistics=["Sum"],
            ),
        )
        return any(p.get("Timestamp") >= desde and p.get("Sum", 0) >= 1 for p in respuesta.get("Datapoints", []))

    def esperar_alarma(self, limite_s: float = ESPERA_ALARMA_S) -> None:
        """Espera a que la alarma embedding-inactivo haya visto el encendido: que CloudWatch devuelva la muestra de
        EmbeddingEncendidos, que pase un minuto (una evaluación de la alarma con ella) y que no esté en ALARM. Sin esto,
        una alarma a punto de pasar a ALARM (45 min sin uso) apagaría embedding justo después de encenderlo."""
        inicio = time.monotonic()
        visible_desde = None
        avisado = False
        while True:
            alarma = self.alarma(ALARMA_INACTIVIDAD)
            if alarma is None:
                raise comun.Bloqueo(f"INF-2.1 no está aplicado: falta la alarma {ALARMA_INACTIVIDAD}")
            if visible_desde is None and self.latido_visible():
                visible_desde = time.monotonic()
            if (
                visible_desde is not None
                and time.monotonic() - visible_desde >= 60
                and alarma.get("StateValue") != "ALARM"
            ):
                return
            if time.monotonic() - inicio > limite_s:
                raise comun.Falla(
                    f"{ALARMA_INACTIVIDAD} no vio el encendido en {limite_s / 60:.0f} min (muestra de "
                    f"{METRICA_ENCENDIDOS} {'visible' if visible_desde else 'sin aparecer'}; alarma en "
                    f"{alarma.get('StateValue')}): no se enciende, su política lo volvería a apagar"
                )
            if not avisado:
                self.avisar(f"esperando a que {ALARMA_INACTIVIDAD} vea el encendido (1-3 min)…")
                avisado = True
            time.sleep(SONDEO_S)

    def encender(self, esperar: bool = True, limite_s: float = ESPERA_SANO_S) -> float:
        """Enciende embedding (contrato de ARCHITECTURE §5.10). Devuelve los segundos hasta sano (o hasta ponerlo en 1
        con esperar=False). Falla si no queda sano dentro de limite_s, contados desde el principio."""
        inicio = time.monotonic()
        for nombre in ESCALADOS:
            self.servicio(nombre)  # Bloqueo si INF-1.3 no está aplicado
        aviso_noche = self.aviso_noche()
        if aviso_noche:
            self.avisar(aviso_noche)
        for nombre in ESCALADOS:
            self.registrar(nombre, 1)
        self.publicar_encendido()
        self.esperar_alarma()
        self.poner("embedding", 1)
        if not esperar:
            return time.monotonic() - inicio
        self.avisar(f"esperando a que embedding esté sano (hasta {limite_s / 60:.0f} min desde el encendido)…")
        detalle = ""
        while True:
            listo, detalle = self.sano()
            transcurrido = time.monotonic() - inicio
            if listo:
                return transcurrido
            if transcurrido > limite_s:
                eventos = "; ".join(e.get("message", "") for e in self.servicio("embedding").get("events", [])[:3])
                raise comun.Falla(
                    f"embedding no quedó sano en {limite_s / 60:.0f} min ({detalle}); eventos: {comun.resumir(eventos, 300)}"
                )
            time.sleep(SONDEO_S)

    def apagar(self, esperar: bool = True, limite_s: float = ESPERA_APAGADO_S) -> float:
        """Rango 0-0 y desiredCount 0 en embedding y worker. Sin objetivos (INF-2.1 sin aplicar) solo pone 0."""
        inicio = time.monotonic()
        for nombre in ESCALADOS:
            if self.objetivo(nombre) is None:
                self.avisar(f"{nombre} no tiene objetivo escalable (INF-2.1 sin aplicar): solo desiredCount 0")
            else:
                self.registrar(nombre, 0)
            self.poner(nombre, 0)
        if not esperar:
            return time.monotonic() - inicio
        while True:
            vivos = {}
            for nombre in ESCALADOS:
                s = self.servicio(nombre)
                cuenta = s.get("desiredCount", 0) + s.get("runningCount", 0) + s.get("pendingCount", 0)
                if cuenta:
                    vivos[nombre] = (s.get("desiredCount", 0), s.get("runningCount", 0), s.get("pendingCount", 0))
            if not vivos:
                return time.monotonic() - inicio
            if time.monotonic() - inicio > limite_s:
                raise comun.Falla(
                    f"tras {limite_s / 60:.0f} min quedan tareas (deseadas, en marcha, pendientes): {vivos}"
                )
            time.sleep(SONDEO_S)

    # -- estado -------------------------------------------------------------------------------------------------------

    def aviso_noche(self) -> str | None:
        """Aviso si el apagado nocturno llega en menos de 30 min (solo entiende cron(M H * * ? *))."""
        for accion in self.acciones_noche():
            if accion.get("ScheduledActionName") != f"{PREFIJO}-embedding-apagar-noche":
                continue
            m = re.fullmatch(r"cron\((\d+) (\d+) \* \* \? \*\)", accion.get("Schedule", ""))
            if not m:
                return None
            ahora = hora_bogota()
            corte = ahora.replace(hour=int(m[2]), minute=int(m[1]), second=0, microsecond=0)
            minutos = (corte - ahora).total_seconds() / 60
            if 0 <= minutos < 30:
                return f"aviso: el apagado nocturno ({corte:%H:%M} {accion.get('Timezone')}) llega en {minutos:.0f} min"
        return None

    def resumen(self) -> list[str]:
        lineas = []
        for nombre in ESCALADOS:
            s = self.servicio(nombre)
            obj = self.objetivo(nombre)
            rango = f"rango {obj['MinCapacity']}-{obj['MaxCapacity']}" if obj else "sin objetivo escalable"
            cuentas = f"deseadas {s.get('desiredCount', 0)}, en marcha {s.get('runningCount', 0)}, pendientes {s.get('pendingCount', 0)}"
            if nombre == "embedding":
                if s.get("desiredCount", 0) >= 1:
                    listo, falta = self.sano()
                    situacion = "encendido y sano" if listo else f"arrancando ({falta})"
                else:
                    situacion = "apagándose" if s.get("runningCount", 0) or s.get("pendingCount", 0) else "apagado"
            else:
                situacion = "en marcha" if s.get("desiredCount", 0) else "en 0"
            lineas.append(f"{nombre}: {situacion} · {cuentas} · {rango}")
        for nombre in (ALARMA_INACTIVIDAD, *ALARMAS_WORKER):
            a = self.alarma(nombre)
            if a is None:
                lineas.append(f"alarma {nombre}: no existe (INF-2.1 sin aplicar)")
                continue
            desde = a.get("StateUpdatedTimestamp")
            desde = f" desde {hora_bogota(desde):%Y-%m-%d %H:%M} (Bogotá)" if isinstance(desde, dt.datetime) else ""
            lineas.append(f"alarma {nombre}: {a.get('StateValue')}{desde}")
        for clave, nombre in COLAS.items():
            c = self.cola(clave)
            lineas.append(
                f"cola {nombre}: {c['visibles']} visibles, {c['en_vuelo']} en vuelo, {c['retrasados']} retrasados"
            )
        acciones = self.acciones_noche()
        if acciones:
            for a in acciones:
                lineas.append(
                    f"apagado nocturno {a.get('ScheduledActionName')}: {a.get('Schedule')} {a.get('Timezone')}"
                )
        else:
            lineas.append("apagado nocturno: ninguno")
        return lineas


# ---------------------------------------------------------------------------------------------------------------------
# Programa
# ---------------------------------------------------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    comun.preparar_consola()
    parser = comun._Parser(description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    ordenes = parser.add_subparsers(dest="orden", required=True)
    for orden, ayuda in (
        ("encender", "enciende embedding y espera a que esté sano"),
        ("apagar", "apaga embedding y worker"),
    ):
        sub = ordenes.add_parser(orden, help=ayuda)
        sub.add_argument("--sin-esperar", action="store_true", help="no espera a que termine")
    ordenes.add_parser("estado", help="muestra el estado (solo lee)")
    args = parser.parse_args(argv)
    try:
        sesion = comun.sesion_aws()
        comun.comprobar_cuenta(sesion)
        op = Operador(sesion)
        if args.orden == "estado":
            for linea in op.resumen():
                print(linea, flush=True)
        elif args.orden == "encender":
            segundos = op.encender(esperar=not args.sin_esperar)
            if args.sin_esperar:
                print(
                    "embedding: encendido (desiredCount 1); tarda 2-3 min en estar sano: embedding.py estado",
                    flush=True,
                )
            else:
                print(f"embedding: encendido y sano en {segundos / 60:.1f} min", flush=True)
        else:
            segundos = op.apagar(esperar=not args.sin_esperar)
            print(
                "embedding y worker: rango 0-0 y desiredCount 0"
                + ("" if args.sin_esperar else f"; sin tareas en {segundos / 60:.1f} min"),
                flush=True,
            )
        return comun.SALIDA_PASA
    except comun.ErrorConfiguracion as exc:
        print(f"[ERROR] {exc}", flush=True)
        return comun.SALIDA_ERROR
    except comun.Bloqueo as exc:
        print(f"[BLOQUEADO] {exc}", flush=True)
        return comun.SALIDA_BLOQUEADO
    except comun.Falla as exc:
        print(f"[FALLA] {exc}", flush=True)
        return comun.SALIDA_FALLA
    except KeyboardInterrupt:
        print("[ERROR] interrumpido: revisa cómo quedó con «embedding.py estado»", flush=True)
        return comun.SALIDA_ERROR


if __name__ == "__main__":
    sys.exit(main())
