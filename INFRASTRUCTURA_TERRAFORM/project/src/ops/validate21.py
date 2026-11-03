"""Validador de INF-2.1 — Encendido de embedding y escalado del worker.

Documento: docs/validation/validation-2-1.md. Contrato común: docs/ARCHITECTURE.md §5.11.

Uso (desde INFRASTRUCTURA_TERRAFORM/project/; dura 1,5-2 h y debe empezar entre las 06:00 y las 19:30 de Bogotá):
    uv run --group ops python src/ops/validate21.py --entorno dev [--informe RUTA] [--solo C1,C3] [--sin-limpieza]
"""

from __future__ import annotations

import datetime as dt
import json
import re
import sys
import time
from dataclasses import dataclass, field

import comun
import embedding as emb

PREFIJO = emb.PREFIJO
CLUSTER = emb.CLUSTER
LOG_APIGW = "/campus-locator/dev/apigw"
FILTRO = f"{PREFIJO}-localize"
METRICA_LOCALIZE = "LocalizePeticiones"
ESPACIO = emb.ESPACIO_METRICAS
ALARMA_INACTIVIDAD = emb.ALARMA_INACTIVIDAD
ALARMA_SUBIDA = {c: f"{PREFIJO}-worker-cola-{c}" for c in ("ingesta", "purga")}
ALARMA_VACIAS = f"{PREFIJO}-worker-colas-vacias"
POLITICA_APAGAR = f"{PREFIJO}-embedding-apagar"
POLITICA_SUBIR = f"{PREFIJO}-worker-cola"
POLITICA_BAJAR = f"{PREFIJO}-worker-colas-vacias"
ACCIONES_NOCHE = {s: f"{PREFIJO}-{s}-apagar-noche" for s in emb.ESCALADOS}
BUCKET = f"{PREFIJO}-dataset-{comun.CUENTA}"
MARCA = "validacion-2-1"
VISIBLE, EN_VUELO = "ApproximateNumberOfMessagesVisible", "ApproximateNumberOfMessagesNotVisible"
WORKER_BAJAR_MIN = 15  # §5.10

# Tiempos (validation-2-1 §2). Se leen en tiempo de ejecución: las pruebas locales los acortan.
T = {
    "sano": 600,  # C1a: encender → sano
    "apagado": 600,  # C1b
    "subida": 20 * 60,  # C3b: worker 0 → 1
    "bajada": 35 * 60,  # C3b: espera máxima de worker 1 → 0 desde que las colas quedan vacías
    "bajada_min": 12 * 60,  # C3b: ventana en la que debe bajar
    "bajada_max": 30 * 60,
    "inactividad": 70 * 60,  # C2b: espera máxima del apagado por inactividad desde la última actividad
    "inactividad_min": 43 * 60,  # C2b: ventana en la que debe apagarse
    "inactividad_max": 60 * 60,
    "cpu_silencio": 3 * 60,  # C4: sin muestras de CPU de embedding desde hace al menos esto
    "cpu_espera": 10 * 60,
    "metrica_cola": 15 * 60,  # C4: SQS publica los mensajes de prueba
    "observar": 5 * 60,  # C4: observación extra
    "vaciar": 180,  # borrar los mensajes propios y que SQS cuente 0
    "sondeo": 30,
    "sondeo_largo": 60,
}
ANTIGUEDAD_RESTO_S = 15 * 60
OCULTAR_S = 120  # visibilidad de lo que se recibe; los ajenos se devuelven al terminar de leer
HORARIO = (dt.time(6, 0), dt.time(19, 30))  # P5: hora de Bogotá para empezar si se incluye C2b, C3b o C4
HORA_LIMITE_CORTA = dt.time(21, 40)  # P5: solo C1 (sin las esperas largas)
LARGAS = ("C2b", "C3b", "C4")
CAMBIAN = ("C1a", "C1b", "C2b", "C3b", "C4")

# Líneas de access log de prueba para C2a (formato de §5.10: todos los valores son cadenas).
LINEAS_PRUEBA = [
    ("POST", "/v1/localize", True),
    ("GET", "/v1/localize", False),
    ("POST", "/v1/auth/login", False),
    ("POST", "/v1/localize/x", False),
    ("PUT", "/v1/localize", False),
]


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


def leer_tfvars() -> dict:
    """apagado_embedding de envs/dev/terraform.tfvars (§5.3): zona, noche (None si es null) e inactividad_min."""
    ruta = comun.PROYECTO / "envs" / "dev" / "terraform.tfvars"
    try:
        texto = ruta.read_text(encoding="utf-8")
    except OSError as exc:
        raise comun.ErrorConfiguracion(f"no se puede leer {ruta}: {exc}") from exc
    bloque = re.search(r"^apagado_embedding\s*=\s*\{(.*?)^\}", texto, flags=re.DOTALL | re.MULTILINE)
    if not bloque:
        raise comun.Falla("envs/dev/terraform.tfvars no tiene apagado_embedding (§5.3)")
    cuerpo = bloque[1]
    zona = re.search(r'^\s*zona\s*=\s*"([^"]+)"', cuerpo, flags=re.MULTILINE)
    noche = re.search(r'^\s*noche\s*=\s*(null|"([^"]+)")', cuerpo, flags=re.MULTILINE)
    inactividad = re.search(r"^\s*inactividad_min\s*=\s*(\d+)", cuerpo, flags=re.MULTILINE)
    if not (zona and inactividad):
        raise comun.Falla("apagado_embedding sin zona o inactividad_min en envs/dev/terraform.tfvars")
    return {
        "zona": zona[1],
        "noche": noche[2] if noche and noche[1] != "null" else None,
        "inactividad_min": int(inactividad[1]),
    }


def cuerpo_mensaje(sello: str, n: int) -> str:
    """Mensaje de prueba con la forma de s3:TestEvent (el worker real lo borra sin hacer nada, BACKEND §5.8)."""
    return json.dumps(
        {
            "Service": "Amazon S3",
            "Event": "s3:TestEvent",
            "Time": comun.iso(comun.ahora_utc()),
            "Bucket": BUCKET,
            "RequestId": f"{MARCA}-{sello}-{n}",
            "HostId": MARCA,
        }
    )


def clasificar(cuerpo: str, sello: str) -> str:
    """«propio» (de esta ejecución), «resto» (de otra con más de 15 min) o «ajeno» (todo lo demás, incluido lo que no
    se entiende y lo de otra ejecución reciente)."""
    try:
        datos = json.loads(cuerpo)
        marca = datos.get("RequestId", "") if isinstance(datos, dict) and datos.get("Event") == "s3:TestEvent" else ""
    except ValueError:
        return "ajeno"
    m = re.fullmatch(rf"{MARCA}-(\d{{8}}-\d{{6}})-\d+", marca or "")
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


# ---------------------------------------------------------------------------------------------------------------------
# Estado compartido
# ---------------------------------------------------------------------------------------------------------------------


@dataclass
class Contexto:
    sesion: object = None
    op: emb.Operador | None = None
    salidas: dict = field(default_factory=dict)
    urls: dict = field(default_factory=dict)  # ingesta/purga → URL
    sello: str = ""
    enviados: int = 0  # mensajes propios enviados (numeración)
    borrados: int = 0  # mensajes propios borrados por el validador
    t_vacia: dt.datetime | None = None  # C3b: las colas quedaron vacías
    alarmas: dict = field(default_factory=dict)
    politicas: dict = field(default_factory=dict)

    def cliente(self, nombre: str):
        return self.op.cliente(nombre)


# ---------------------------------------------------------------------------------------------------------------------
# Precondiciones
# ---------------------------------------------------------------------------------------------------------------------


def p4_credenciales(ctx: Contexto) -> str:
    ctx.sesion = comun.sesion_aws()
    arn = comun.comprobar_cuenta(ctx.sesion)
    ctx.op = emb.Operador(ctx.sesion)
    return f"{arn} (cuenta {comun.CUENTA})"


def p5_horario(v, ctx: Contexto) -> str:
    ahora = emb.hora_bogota()
    if v.alguna_incluida(*LARGAS):
        if not HORARIO[0] <= ahora.time() <= HORARIO[1]:
            raise comun.ErrorConfiguracion(
                f"son las {ahora:%H:%M} en Bogotá: con C2b, C3b o C4 hay que empezar entre las "
                f"{HORARIO[0]:%H:%M} y las {HORARIO[1]:%H:%M} (dura ~2 h y el apagado de las 22:00 daría FALLA falsos)"
            )
    elif v.alguna_incluida("C1a", "C1b") and ahora.time() > HORA_LIMITE_CORTA:
        raise comun.ErrorConfiguracion(f"son las {ahora:%H:%M} en Bogotá: C1 debe empezar antes de las 21:40")
    if not v.alguna_incluida(*CAMBIAN):
        return f"{ahora:%H:%M} en Bogotá; solo lectura"
    ocupados = []
    for nombre in emb.ESCALADOS:
        try:
            servicio = ctx.op.servicio(nombre)
        except comun.Bloqueo:
            continue  # lo dice P1
        except comun.Falla as exc:
            raise comun.ErrorConfiguracion(str(exc)) from exc
        if servicio.get("desiredCount", 0) or servicio.get("runningCount", 0):
            ocupados.append(
                f"{nombre} (deseadas {servicio.get('desiredCount', 0)}, en marcha {servicio.get('runningCount', 0)})"
            )
    if ocupados:
        raise comun.ErrorConfiguracion(
            f"{', '.join(ocupados)} en marcha: alguien lo está usando. Repetir con los dos en 0 (embedding.py estado)"
        )
    return f"{ahora:%H:%M} en Bogotá; embedding y worker en 0"


def p1_servicios(ctx: Contexto) -> str:
    for nombre in emb.ESCALADOS:
        try:
            ctx.op.servicio(nombre)
        except comun.Falla as exc:
            raise comun.ErrorConfiguracion(str(exc)) from exc
    return f"servicios worker y embedding ACTIVE en {CLUSTER}"


def p2_borde(ctx: Contexto) -> str:
    logs = ctx.cliente("logs")
    grupos = llamar_precondicion(
        "describir log groups (logs:DescribeLogGroups)",
        lambda: logs.describe_log_groups(logGroupNamePrefix=LOG_APIGW),
    ).get("logGroups", [])
    if not any(g.get("logGroupName") == LOG_APIGW for g in grupos):
        raise comun.Bloqueo(f"INF-1.4 no está aplicado: no existe el log group {LOG_APIGW}")
    ctx.salidas = comun.terraform_outputs("envs/dev")
    if "api_base_url" not in ctx.salidas:
        raise comun.Bloqueo("INF-1.4 no está aplicado en envs/dev: falta el output api_base_url")
    return f"{LOG_APIGW} y output api_base_url"


def p3_salidas(ctx: Contexto) -> str:
    faltan = [s for s in ("ecs_cluster", "ecs_servicios", "sqs_ingesta_url", "sqs_purga_url") if s not in ctx.salidas]
    if faltan:
        raise comun.Bloqueo(f"envs/dev no tiene los outputs {', '.join(faltan)}")
    if ctx.salidas["ecs_cluster"] != CLUSTER:
        raise comun.Bloqueo(f"ecs_cluster = {ctx.salidas['ecs_cluster']!r}, no {CLUSTER}")
    ctx.urls = {"ingesta": ctx.salidas["sqs_ingesta_url"], "purga": ctx.salidas["sqs_purga_url"]}
    return "ecs_cluster, ecs_servicios, sqs_ingesta_url y sqs_purga_url"


# ---------------------------------------------------------------------------------------------------------------------
# Lectura de la configuración (C2a, C3a)
# ---------------------------------------------------------------------------------------------------------------------


def alarma(ctx: Contexto, nombre: str) -> dict:
    if nombre not in ctx.alarmas:
        a = ctx.op.alarma(nombre)
        if a is None:
            raise comun.Falla(f"no existe la alarma {nombre}")
        ctx.alarmas[nombre] = a
    return ctx.alarmas[nombre]


def politica(ctx: Contexto, servicio: str, nombre: str) -> dict:
    if nombre not in ctx.politicas:
        aas = ctx.cliente("application-autoscaling")
        politicas = llamar(
            f"leer la política {nombre} (application-autoscaling:DescribeScalingPolicies)",
            lambda: aas.describe_scaling_policies(
                ServiceNamespace="ecs", ResourceId=emb.recurso(servicio), PolicyNames=[nombre]
            ),
        ).get("ScalingPolicies", [])
        if len(politicas) != 1:
            raise comun.Falla(f"no existe la política {nombre} sobre {servicio}")
        ctx.politicas[nombre] = politicas[0]
    return ctx.politicas[nombre]


def metricas_de(a: dict) -> tuple[str, dict]:
    """(expresión que devuelve datos, {id: (espacio, métrica, dimensiones, estadística, periodo)})."""
    expresion, metricas = "", {}
    for q in a.get("Metrics", []):
        if q.get("ReturnData") and q.get("Expression"):
            expresion = q["Expression"]
        elif "MetricStat" in q:
            ms = q["MetricStat"]
            dims = {d["Name"]: d["Value"] for d in ms["Metric"].get("Dimensions", [])}
            metricas[q["Id"]] = (
                ms["Metric"].get("Namespace"),
                ms["Metric"].get("MetricName"),
                dims,
                ms.get("Stat"),
                ms.get("Period"),
            )
    return expresion, metricas


def revisar_alarma(
    a: dict, *, comparacion: str, periodos: int, puntos: int, esperadas: set, politica_arn: str
) -> list[str]:
    """Problemas de una alarma de expresión: comparación con umbral 0,5, M de N, métricas (espacio, métrica,
    dimensiones) a 60 s, todas usadas en la expresión, y su única acción, la política."""
    nombre = a.get("AlarmName")
    problemas = []
    if (a.get("ComparisonOperator"), a.get("Threshold")) != (comparacion, 0.5):
        problemas.append(f"{nombre}: {a.get('ComparisonOperator')} {a.get('Threshold')}, se espera {comparacion} 0.5")
    if (a.get("EvaluationPeriods"), a.get("DatapointsToAlarm")) != (periodos, puntos):
        problemas.append(
            f"{nombre}: {a.get('DatapointsToAlarm')} de {a.get('EvaluationPeriods')} periodos, se esperan {puntos} de {periodos}"
        )
    expresion, metricas = metricas_de(a)
    vistas = {(e, m, tuple(sorted(d.items()))) for e, m, d, _, _ in metricas.values()}
    if vistas != esperadas:
        problemas.append(f"{nombre}: métricas {sorted(vistas)}; se esperan {sorted(esperadas)}")
    if any(p != 60 for *_, p in metricas.values()):
        problemas.append(f"{nombre}: algún periodo no es de 60 s")
    sin_usar = [i for i in metricas if not re.search(rf"\b{re.escape(i)}\b", expresion)]
    if not expresion or sin_usar:
        problemas.append(f"{nombre}: la expresión {expresion!r} no usa {sin_usar}")
    if a.get("AlarmActions") != [politica_arn] or not a.get("ActionsEnabled", True):
        problemas.append(f"{nombre}: acciones {a.get('AlarmActions')}, se espera solo la política")
    return problemas


def pasos_todo(capacidad: int) -> list[dict]:
    """Los dos pasos de una política de escalado.tf: por debajo y por encima del umbral, la misma capacidad."""
    return [
        {"MetricIntervalUpperBound": 0.0, "ScalingAdjustment": capacidad},
        {"MetricIntervalLowerBound": 0.0, "ScalingAdjustment": capacidad},
    ]


def revisar_politica(p: dict, *, agregacion: str, capacidad: int) -> list[str]:
    """Problemas de una política: StepScaling de capacidad exacta, su agregación y dos pasos que cubren todos los
    valores con `capacidad` (el resultado no depende de qué muestras agregue Application Auto Scaling)."""
    nombre = p.get("PolicyName")
    conf = p.get("StepScalingPolicyConfiguration") or {}
    problemas = []
    if p.get("PolicyType") != "StepScaling" or conf.get("AdjustmentType") != "ExactCapacity":
        problemas.append(f"{nombre}: {p.get('PolicyType')}/{conf.get('AdjustmentType')}, no StepScaling/ExactCapacity")
    if conf.get("MetricAggregationType") != agregacion:
        problemas.append(f"{nombre}: agregación {conf.get('MetricAggregationType')}, no {agregacion}")
    pasos = sorted(conf.get("StepAdjustments", []), key=lambda x: sorted(x))
    esperados = sorted(pasos_todo(capacidad), key=lambda x: sorted(x))
    if pasos != esperados:
        problemas.append(f"{nombre}: pasos {pasos}, se esperan {esperados}")
    return problemas


def esperadas_colas() -> set:
    return {
        ("AWS/SQS", metrica, (("QueueName", emb.COLAS[c]),))
        for c in ("ingesta", "purga")
        for metrica in (VISIBLE, EN_VUELO)
    }


def cpu(servicio: str) -> tuple:
    return ("AWS/ECS", "CPUUtilization", (("ClusterName", CLUSTER), ("ServiceName", servicio)))


# ---------------------------------------------------------------------------------------------------------------------
# C2a: configuración del apagado de embedding
# ---------------------------------------------------------------------------------------------------------------------


def linea_log(metodo: str, ruta: str) -> str:
    return json.dumps(
        {
            "requestId": "validacion=",
            "ip": "192.0.2.1",
            "requestTime": "25/Oct/2026:12:00:00 +0000",
            "httpMethod": metodo,
            "routeKey": "ANY /{proxy+}",
            "path": ruta,
            "status": "200",
            "responseLength": "2",
            "integrationLatency": "100",
            "integrationStatus": "200",
        }
    )


def c2a_configuracion(ctx: Contexto) -> str:
    tf = leer_tfvars()
    problemas = []
    logs = ctx.cliente("logs")
    filtros = llamar(
        f"leer filtros de {LOG_APIGW} (logs:DescribeMetricFilters)",
        lambda: logs.describe_metric_filters(logGroupName=LOG_APIGW, filterNamePrefix=FILTRO),
        "ResourceNotFoundException",
    )
    filtros = [f for f in (filtros or {}).get("metricFilters", []) if f.get("filterName") == FILTRO]
    if len(filtros) != 1:
        problemas.append(f"no existe el filtro {FILTRO} en {LOG_APIGW}")
    else:
        transf = filtros[0].get("metricTransformations", [])
        if [(t.get("metricName"), t.get("metricNamespace"), t.get("metricValue")) for t in transf] != [
            (METRICA_LOCALIZE, ESPACIO, "1")
        ]:
            problemas.append(f"{FILTRO} publica {transf}; se espera {METRICA_LOCALIZE} = 1 en {ESPACIO}")
        prueba = llamar(
            "probar el filtro (logs:TestMetricFilter)",
            lambda: logs.test_metric_filter(
                filterPattern=filtros[0].get("filterPattern", ""),
                logEventMessages=[linea_log(m, r) for m, r, _ in LINEAS_PRUEBA],
            ),
        )
        casan = {x.get("eventMessage") for x in prueba.get("matches", [])}
        vistas = [f"{m} {r}" for m, r, _ in LINEAS_PRUEBA if linea_log(m, r) in casan]
        if vistas != [f"{m} {r}" for m, r, casa in LINEAS_PRUEBA if casa]:
            problemas.append(f"{FILTRO} cuenta {vistas}; debe contar solo POST /v1/localize")

    n = tf["inactividad_min"]
    pol_apagar = politica(ctx, "embedding", POLITICA_APAGAR)
    problemas += revisar_politica(pol_apagar, agregacion="Minimum", capacidad=0)
    problemas += revisar_alarma(
        alarma(ctx, ALARMA_INACTIVIDAD),
        comparacion="LessThanThreshold",
        periodos=n,
        puntos=n,
        esperadas={
            (ESPACIO, METRICA_LOCALIZE, ()),
            (ESPACIO, emb.METRICA_ENCENDIDOS, ()),
            *esperadas_colas(),
            cpu("embedding"),
        },
        politica_arn=pol_apagar.get("PolicyARN"),
    )

    for servicio in emb.ESCALADOS:
        if ctx.op.objetivo(servicio) is None:
            problemas.append(f"falta el objetivo escalable de {servicio}")
    if tf["noche"] is None:
        problemas.append("apagado_embedding.noche = null en envs/dev/terraform.tfvars: C2 exige la acción nocturna")
    else:
        acciones = {a.get("ScheduledActionName"): a for a in ctx.op.acciones_noche()}
        for servicio, nombre in ACCIONES_NOCHE.items():
            a = acciones.get(nombre)
            if a is None:
                problemas.append(f"no existe la acción {nombre}")
                continue
            accion = a.get("ScalableTargetAction") or {}
            visto = (
                a.get("ResourceId"),
                a.get("Schedule"),
                a.get("Timezone"),
                accion.get("MinCapacity"),
                accion.get("MaxCapacity"),
            )
            if visto != (emb.recurso(servicio), tf["noche"], tf["zona"], 0, 0):
                problemas.append(
                    f"{nombre}: {visto}; se espera {(emb.recurso(servicio), tf['noche'], tf['zona'], 0, 0)}"
                )
    return comprobar(
        problemas,
        f"{FILTRO} cuenta solo POST /v1/localize; {ALARMA_INACTIVIDAD} {n} de {n} min sobre uso y colas → "
        f"{POLITICA_APAGAR} (exacta 0); {', '.join(ACCIONES_NOCHE.values())} {tf['noche']} {tf['zona']} → 0-0",
    )


# ---------------------------------------------------------------------------------------------------------------------
# C3a: configuración del escalado de worker
# ---------------------------------------------------------------------------------------------------------------------


def c3a_configuracion(ctx: Contexto) -> str:
    problemas = []
    subir = politica(ctx, "worker", POLITICA_SUBIR)
    bajar = politica(ctx, "worker", POLITICA_BAJAR)
    problemas += revisar_politica(subir, agregacion="Maximum", capacidad=1)
    problemas += revisar_politica(bajar, agregacion="Minimum", capacidad=0)
    for clave, nombre in ALARMA_SUBIDA.items():
        a = alarma(ctx, nombre)
        problemas += revisar_alarma(
            a,
            comparacion="GreaterThanThreshold",
            periodos=10,
            puntos=1,
            esperadas={("AWS/SQS", VISIBLE, (("QueueName", emb.COLAS[clave]),)), cpu("embedding")},
            politica_arn=subir.get("PolicyARN"),
        )
        expresion, _ = metricas_de(a)
        if "AND" not in expresion.upper() and "&&" not in expresion:
            problemas.append(f"{nombre}: la expresión {expresion!r} no condiciona la subida a embedding")
    problemas += revisar_alarma(
        alarma(ctx, ALARMA_VACIAS),
        comparacion="LessThanThreshold",
        periodos=WORKER_BAJAR_MIN,
        puntos=WORKER_BAJAR_MIN,
        esperadas={*esperadas_colas(), cpu("worker")},
        politica_arn=bajar.get("PolicyARN"),
    )
    return comprobar(
        problemas,
        f"{', '.join(ALARMA_SUBIDA.values())} (cola con mensajes y embedding corriendo, 1 de 10 min) → {POLITICA_SUBIR} "
        f"(exacta 1); {ALARMA_VACIAS} ({WORKER_BAJAR_MIN} min sin mensajes) → {POLITICA_BAJAR} (exacta 0)",
    )


# ---------------------------------------------------------------------------------------------------------------------
# C1: encendido y apagado
# ---------------------------------------------------------------------------------------------------------------------


def rangos(ctx: Contexto) -> dict:
    rango = {}
    for servicio in emb.ESCALADOS:
        o = ctx.op.objetivo(servicio)
        rango[servicio] = (o.get("MinCapacity"), o.get("MaxCapacity")) if o else None
    return rango


def c1a_encender(ctx: Contexto) -> str:
    segundos = ctx.op.encender(esperar=True, limite_s=T["sano"])
    servicio = ctx.op.servicio("embedding")
    rango = rangos(ctx)
    problemas = []
    if servicio.get("runningCount") != 1:
        problemas.append(f"runningCount {servicio.get('runningCount')}")
    if any(r != (0, 1) for r in rango.values()):
        problemas.append(f"rangos {rango}; se espera 0-1 en los dos")
    return comprobar(
        problemas, f"sano en {minutos(segundos)} (tarea HEALTHY, despliegue COMPLETED, Cloud Map sana); rango 0-1"
    )


def c1b_apagar(ctx: Contexto) -> str:
    segundos = ctx.op.apagar(esperar=True, limite_s=T["apagado"])
    emb_s, wrk_s = ctx.op.servicio("embedding"), ctx.op.servicio("worker")
    rango = rangos(ctx)
    problemas = []
    if (emb_s.get("desiredCount"), emb_s.get("runningCount")) != (0, 0):
        problemas.append(f"embedding deseadas {emb_s.get('desiredCount')}, en marcha {emb_s.get('runningCount')}")
    if wrk_s.get("desiredCount") != 0:
        problemas.append(f"worker deseadas {wrk_s.get('desiredCount')}")
    if any(r != (0, 0) for r in rango.values()):
        problemas.append(f"rangos {rango}; se espera 0-0 en los dos")
    return comprobar(problemas, f"embedding 0/0 y worker en 0 en {minutos(segundos)}; rango 0-0 en los dos")


# ---------------------------------------------------------------------------------------------------------------------
# Mensajes de prueba, servicios y métricas (C3b, C2b, C4)
# ---------------------------------------------------------------------------------------------------------------------


def lector(ctx: Contexto, clave: str) -> comun.LectorCola:
    """Lector de la cola (comun.LectorCola, §5.11) que borra los mensajes validacion-2-1 propios y los restos."""
    return comun.LectorCola(
        ctx.cliente("sqs"),
        ctx.urls[clave],
        emb.COLAS[clave],
        lambda cuerpo: clasificar(cuerpo, ctx.sello),
        ocultar_s=OCULTAR_S,
    )


def limpiar_restos(ctx: Contexto) -> None:
    """Al empezar: borra de ingesta los mensajes validacion-2-1 de ejecuciones anteriores. No lee si hay mensajes en
    vuelo (alguien los procesa) o más de 10 visibles (no son restos); los ajenos vuelven enseguida a la cola."""
    cuenta = ctx.op.cola("ingesta")
    if not cuenta["visibles"] or cuenta["en_vuelo"] or cuenta["visibles"] > 10:
        return
    lec = lector(ctx, "ingesta")
    try:
        lec.leer(20)
    finally:
        lec.devolver()
    if lec.borrados:
        comun.avisar(f"borrados {lec.borrados} mensaje(s) {MARCA} de ejecuciones anteriores en ingesta")


def borrar_propios(ctx: Contexto) -> int:
    """Borra los mensajes propios que queden en ingesta (los ajenos vuelven a la cola). Devuelve cuántos borró."""
    lec = lector(ctx, "ingesta")
    try:
        lec.leer(T["vaciar"], objetivo=None)
    finally:
        lec.devolver()
    ctx.borrados += lec.borrados
    return lec.borrados


def pendientes(ctx: Contexto) -> int:
    """Mensajes propios enviados que el validador no ha borrado (el worker real también los borra)."""
    return max(ctx.enviados - ctx.borrados, 0)


def colas_ocupadas(ctx: Contexto) -> dict:
    """{cola: cuenta} de las que no están vacías (visibles, en vuelo o retrasados)."""
    return {c: n for c in emb.COLAS if any((n := ctx.op.cola(c)).values())}


def quitar_propios(ctx: Contexto) -> dict:
    """Si ingesta tiene mensajes y quedan propios sin borrar (de una comprobación anterior que falló), los borra y espera
    a que las colas cuenten 0 (vaciar, que falla si quedan ajenos; anota el momento como último uso). No lee la cola si
    todos los propios están borrados: cada lectura suma una recepción a los ajenos. Devuelve las colas ocupadas."""
    ocupadas = colas_ocupadas(ctx)
    if "ingesta" in ocupadas and pendientes(ctx):
        ctx.t_vacia = vaciar(ctx)  # los contadores de SQS tardan hasta ~1 min; los mensajes contaron como uso
        return {}
    return ocupadas


def enviar(ctx: Contexto, cuantos: int = 3) -> dt.datetime:
    sqs = ctx.cliente("sqs")
    momento = comun.ahora_utc()
    for _ in range(cuantos):
        ctx.enviados += 1
        llamar(
            "enviar un mensaje de prueba a ingesta (sqs:SendMessage)",
            lambda n=ctx.enviados: sqs.send_message(
                QueueUrl=ctx.urls["ingesta"], MessageBody=cuerpo_mensaje(ctx.sello, n)
            ),
        )
    return momento


def vaciar(ctx: Contexto) -> dt.datetime:
    """Borra los mensajes propios (la imagen bootstrap no consume) y espera a que las dos colas cuenten 0. Devuelve el
    último uso: cuándo borró el último mensaje propio (los contadores de SQS tardan hasta ~1 min en bajar) o, si ya no
    estaban (los borró el worker real), cuándo las colas cuentan 0. Lee la cola como mucho 3 veces (cada lectura suma
    una recepción a los ajenos); falla si quedan mensajes ajenos."""
    limite = time.monotonic() + T["vaciar"]
    lecturas = 0
    ultimo_borrado = None
    while True:
        if pendientes(ctx) and lecturas < 3:
            if borrar_propios(ctx) and not pendientes(ctx):
                ultimo_borrado = comun.ahora_utc()
            lecturas += 1
        restantes = colas_ocupadas(ctx)
        if not restantes:
            return ultimo_borrado or comun.ahora_utc()
        if time.monotonic() > limite:
            raise comun.Falla(
                f"las colas no quedan vacías ({restantes}; {ctx.borrados} de {ctx.enviados} mensajes propios "
                "borrados): hay mensajes ajenos y el worker de prueba no los consume"
            )
        time.sleep(10)


def actividades(ctx: Contexto, servicio: str, desde: dt.datetime) -> list[dict]:
    aas = ctx.cliente("application-autoscaling")

    def todas():
        elementos = []
        for pagina in aas.get_paginator("describe_scaling_activities").paginate(
            ServiceNamespace="ecs", ResourceId=emb.recurso(servicio), ScalableDimension=emb.DIMENSION
        ):
            elementos.extend(pagina.get("ScalingActivities", []))
        return elementos

    lista = llamar(f"leer actividades de {servicio} (application-autoscaling:DescribeScalingActivities)", todas)
    return [a for a in lista if a.get("StartTime") and a["StartTime"] >= desde]


ESTADOS_VALIDOS = ("Pending", "InProgress", "Successful")  # ECS tarda ~30 s en dar por cumplida una actividad


def actividad_de(lista: list[dict], *nombres: str) -> dict | None:
    """La actividad más antigua que no falló (Pending, InProgress o Successful) cuya Cause cita alguno de los nombres
    (alarma o política) completo: worker-cola es prefijo de worker-cola-ingesta y de worker-colas-vacias."""
    patrones = [re.compile(rf"{re.escape(n)}(?![-\w])") for n in nombres]
    candidatas = [
        a
        for a in lista
        if a.get("StatusCode") in ESTADOS_VALIDOS and any(p.search(a.get("Cause") or "") for p in patrones)
    ]
    return min(candidatas, key=lambda a: a["StartTime"]) if candidatas else None


def actividad_esperada(ctx: Contexto, servicio: str, desde: dt.datetime, *nombres: str) -> tuple[list, dict | None]:
    """Lee las actividades hasta encontrar la de los nombres; lo reintenta 3 min, porque desiredCount cambia al empezar
    la actividad y esta puede tardar en listarse."""
    limite = time.monotonic() + 180
    while True:
        lista = actividades(ctx, servicio, desde)
        actividad = actividad_de(lista, *nombres)
        if actividad or time.monotonic() > limite:
            return lista, actividad
        time.sleep(15)


def deseadas(ctx: Contexto, servicio: str) -> int:
    return ctx.op.servicio(servicio).get("desiredCount", 0)


def asegurar_encendido(ctx: Contexto) -> None:
    """Enciende embedding (como embedding.py encender) si no está en 1 y sano (§5.11)."""
    servicio = ctx.op.servicio("embedding")
    if servicio.get("desiredCount", 0) >= 1 and ctx.op.sano()[0]:
        return
    comun.avisar("encendiendo embedding (como embedding.py encender)…")
    ctx.op.encender(esperar=True, limite_s=T["sano"])


# ---------------------------------------------------------------------------------------------------------------------
# C3b: worker sube con mensajes y baja tras vaciarse las colas
# ---------------------------------------------------------------------------------------------------------------------


def c3b_worker(ctx: Contexto) -> str:
    asegurar_encendido(ctx)
    ocupadas = colas_ocupadas(ctx)
    if ocupadas:
        raise comun.Falla(f"hay mensajes ajenos en {ocupadas}: el worker de prueba no los consume y no bajaría")
    if deseadas(ctx, "worker"):
        raise comun.Falla("worker ya está en marcha antes de enviar los mensajes")
    t_envio = enviar(ctx)
    inicio = time.monotonic()
    comun.avisar(f"3 mensajes en ingesta; esperando a que worker suba (hasta {minutos(T['subida'])})…")
    while deseadas(ctx, "worker") < 1:
        if time.monotonic() - inicio > T["subida"]:
            raise comun.Falla(
                f"worker no subió en {minutos(T['subida'])} con mensajes en ingesta y embedding encendido"
            )
        if ctx.op.servicio("embedding").get("desiredCount", 0) < 1:
            raise comun.Falla("embedding se apagó mientras se esperaba la subida de worker")
        time.sleep(T["sondeo"])
    subida = time.monotonic() - inicio
    ctx.t_vacia = vaciar(ctx)
    comun.avisar(
        f"worker en 1 a los {minutos(subida)}; colas vacías: esperando la bajada (hasta {minutos(T['bajada'])})…"
    )
    inicio_bajada = time.monotonic()
    while deseadas(ctx, "worker") >= 1:
        if time.monotonic() - inicio_bajada > T["bajada"]:
            raise comun.Falla(f"worker sigue en 1 {minutos(T['bajada'])} después de vaciarse las colas")
        time.sleep(T["sondeo"])
    lista, bajada = actividad_esperada(ctx, "worker", t_envio, ALARMA_VACIAS, POLITICA_BAJAR)
    if bajada is None:
        raise comun.Falla("worker bajó a 0 sin una actividad de la alarma de colas vacías (Application Auto Scaling)")
    segundos = (bajada["StartTime"] - ctx.t_vacia).total_seconds()
    problemas = []
    if not T["bajada_min"] <= segundos <= T["bajada_max"]:
        problemas.append(
            f"worker bajó a los {minutos(segundos)} de vaciarse las colas; se espera entre "
            f"{minutos(T['bajada_min'])} y {minutos(T['bajada_max'])}"
        )
    if actividad_de(lista, ALARMA_SUBIDA["ingesta"], POLITICA_SUBIR) is None:
        problemas.append("la subida no la hizo la alarma de ingesta (sin actividad Successful que la cite)")
    return comprobar(
        problemas,
        f"worker 0 → 1 a los {minutos(subida)} de enviar 3 mensajes; 1 → 0 a los {minutos(segundos)} de vaciarse "
        f"las colas ({ALARMA_VACIAS})",
    )


# ---------------------------------------------------------------------------------------------------------------------
# C2b: apagado por inactividad
# ---------------------------------------------------------------------------------------------------------------------


def c2b_inactividad(ctx: Contexto) -> str:
    asegurar_encendido(ctx)
    ocupadas = quitar_propios(ctx)
    if ocupadas:
        raise comun.Falla(f"las colas no están vacías ({ocupadas}): embedding no puede quedar inactivo")
    referencias = [t for t in (ctx.t_vacia, ctx.op.t_latido) if t]
    t0 = max(referencias) if referencias else comun.ahora_utc()
    limite = t0 + dt.timedelta(seconds=T["inactividad"])
    comun.avisar(
        f"esperando el apagado por inactividad: hasta {emb.hora_bogota(limite):%H:%M} de Bogotá "
        f"({minutos(T['inactividad'])} desde la última actividad, {emb.hora_bogota(t0):%H:%M})…"
    )
    while True:
        if deseadas(ctx, "embedding") == 0:
            lista, actividad = actividad_esperada(ctx, "embedding", t0, ALARMA_INACTIVIDAD, POLITICA_APAGAR)
            if actividad:
                break
            otras = "; ".join(comun.resumir(a.get("Cause", ""), 120) for a in lista) or "ninguna actividad"
            raise comun.Falla(f"embedding quedó en 0 sin la política de inactividad ({otras})")
        if comun.ahora_utc() > limite:
            uso = suma_metrica(ctx, ESPACIO, METRICA_LOCALIZE, {}, t0)
            raise comun.Falla(
                f"embedding sigue encendido {minutos(T['inactividad'])} después de la última actividad; estado de "
                f"{ALARMA_INACTIVIDAD}: {ctx.op.alarma(ALARMA_INACTIVIDAD).get('StateValue')}; "
                f"{METRICA_LOCALIZE} en ese intervalo: {uso}"
            )
        time.sleep(T["sondeo_largo"])
    segundos = (actividad["StartTime"] - t0).total_seconds()
    estado = ctx.op.alarma(ALARMA_INACTIVIDAD).get("StateValue")
    problemas = []
    if not T["inactividad_min"] <= segundos <= T["inactividad_max"]:
        problemas.append(
            f"se apagó a los {minutos(segundos)} de la última actividad; se espera entre "
            f"{minutos(T['inactividad_min'])} y {minutos(T['inactividad_max'])}"
        )
    return comprobar(
        problemas,
        f"embedding → 0 a los {minutos(segundos)} sin uso ({ALARMA_INACTIVIDAD} → {POLITICA_APAGAR}; alarma ahora {estado})",
    )


def suma_metrica(ctx: Contexto, espacio: str, nombre: str, dims: dict, desde: dt.datetime) -> float | None:
    datos = puntos_metrica(ctx, espacio, nombre, dims, "Sum", desde)
    return sum(v for _, v in datos) if datos else 0.0


def puntos_metrica(ctx: Contexto, espacio: str, nombre: str, dims: dict, estadistica: str, desde: dt.datetime) -> list:
    cw = ctx.cliente("cloudwatch")
    respuesta = llamar(
        f"leer {espacio} {nombre} (cloudwatch:GetMetricStatistics)",
        lambda: cw.get_metric_statistics(
            Namespace=espacio,
            MetricName=nombre,
            Dimensions=[{"Name": k, "Value": v} for k, v in dims.items()],
            StartTime=desde - dt.timedelta(minutes=1),
            EndTime=comun.ahora_utc() + dt.timedelta(minutes=1),
            Period=60,
            Statistics=[estadistica],
        ),
    )
    return sorted((p["Timestamp"], p.get(estadistica, 0.0)) for p in respuesta.get("Datapoints", []))


# ---------------------------------------------------------------------------------------------------------------------
# C4: con embedding apagado, worker no arranca
# ---------------------------------------------------------------------------------------------------------------------


def c4_sin_embedding(ctx: Contexto) -> str:
    notas = []
    if deseadas(ctx, "embedding"):
        # Como el apagado por inactividad: solo desiredCount; el rango de worker sigue en 0-1.
        comun.avisar("embedding sigue en 1: se pone en 0 como lo haría la política de inactividad…")
        ctx.op.poner("embedding", 0)
        notas.append("embedding puesto en 0 por el validador (C2b no lo apagó)")
    ocupadas = quitar_propios(ctx)
    if ocupadas:
        raise comun.Falla(f"hay mensajes ajenos en {ocupadas}: con ellos no se puede observar a worker")
    rango_worker = rangos(ctx)["worker"]
    if rango_worker != (0, 1):
        ctx.op.registrar("worker", 1)
        notas.append(f"rango de worker {rango_worker} → 0-1, como tras un apagado por inactividad")
    if deseadas(ctx, "worker"):
        raise comun.Falla("worker está en marcha antes de empezar")
    inicio = time.monotonic()
    while True:
        s = ctx.op.servicio("embedding")
        if s.get("runningCount", 0) == 0 and s.get("pendingCount", 0) == 0:
            break
        if time.monotonic() - inicio > T["apagado"]:
            raise comun.Falla("embedding no terminó de apagarse")
        time.sleep(T["sondeo"])
    comun.avisar(f"esperando a que la CPU de embedding lleve {minutos(T['cpu_silencio'])} sin datos…")
    dims_cpu = {"ClusterName": CLUSTER, "ServiceName": "embedding"}
    inicio = time.monotonic()
    while True:
        puntos = puntos_metrica(
            ctx, "AWS/ECS", "CPUUtilization", dims_cpu, "SampleCount", comun.ahora_utc() - dt.timedelta(minutes=20)
        )
        ultimo = puntos[-1][0] if puntos else None
        if ultimo is None or (comun.ahora_utc() - ultimo).total_seconds() >= T["cpu_silencio"]:
            break
        if time.monotonic() - inicio > T["cpu_espera"]:
            raise comun.Falla(f"la CPU de embedding sigue publicando datos (último {ultimo:%H:%M} UTC)")
        time.sleep(T["sondeo"])
    ocupadas = colas_ocupadas(ctx)
    if ocupadas:
        raise comun.Falla(f"hay mensajes ajenos en {ocupadas}")

    t_envio = enviar(ctx)
    minuto_envio = t_envio.replace(second=0, microsecond=0)
    comun.avisar(f"3 mensajes en ingesta; esperando a que SQS los publique (hasta {minutos(T['metrica_cola'])})…")
    inicio = time.monotonic()
    visto = None
    subidas = []
    while visto is None:
        if deseadas(ctx, "worker"):
            subidas.append(comun.ahora_utc())
            break
        datos = puntos_metrica(ctx, "AWS/SQS", VISIBLE, {"QueueName": emb.COLAS["ingesta"]}, "Maximum", t_envio)
        visto = next((t for t, v in datos if t >= minuto_envio and v >= 1), None)
        if visto is None and time.monotonic() - inicio > T["metrica_cola"]:
            raise comun.Falla(
                f"SQS no publicó los mensajes en {minutos(T['metrica_cola'])}: no se puede saber si la alarma los vio"
            )
        if visto is None:
            time.sleep(T["sondeo"])
    fin = time.monotonic() + T["observar"]
    while not subidas and time.monotonic() < fin:
        if deseadas(ctx, "worker"):
            subidas.append(comun.ahora_utc())
            break
        time.sleep(T["sondeo"])

    cw = ctx.cliente("cloudwatch")
    historia = llamar(
        f"leer la historia de {ALARMA_SUBIDA['ingesta']} (cloudwatch:DescribeAlarmHistory)",
        lambda: cw.describe_alarm_history(
            AlarmName=ALARMA_SUBIDA["ingesta"], HistoryItemType="StateUpdate", StartDate=t_envio, MaxRecords=100
        ),
    ).get("AlarmHistoryItems", [])
    a_alarm = [h for h in historia if "to ALARM" in (h.get("HistorySummary") or "")]
    subidas_aas = [
        a
        for a in actividades(ctx, "worker", t_envio)
        if a.get("StatusCode") in ESTADOS_VALIDOS and "desired count to 1" in (a.get("Description") or "")
    ]
    vaciar(ctx)
    problemas = []
    if subidas:
        problemas.append(f"worker subió a 1 con embedding apagado ({subidas[0]:%H:%M:%S} UTC)")
    if a_alarm:
        problemas.append(f"{ALARMA_SUBIDA['ingesta']} pasó a ALARM ({a_alarm[0].get('Timestamp')})")
    if subidas_aas:
        problemas.append(
            f"Application Auto Scaling registró una subida: {comun.resumir(subidas_aas[0].get('Cause', ''), 160)}"
        )
    if problemas:
        raise comun.Falla("; ".join(problemas + notas))
    detalle = (
        f"worker siguió en 0 con 3 mensajes en ingesta y embedding apagado (SQS los publicó {visto:%H:%M} UTC, "
        f"observado {minutos(T['observar'])} más); {ALARMA_SUBIDA['ingesta']} sin ALARM"
    )
    return detalle + (f" ({'; '.join(notas)})" if notas else "")


# ---------------------------------------------------------------------------------------------------------------------
# Programa
# ---------------------------------------------------------------------------------------------------------------------


def apagar_al_terminar(ctx: Contexto) -> None:
    ctx.op.apagar(esperar=False)


def limpiar_mensajes(ctx: Contexto) -> None:
    if not pendientes(ctx):
        return
    borrados = borrar_propios(ctx)
    if borrados:
        comun.avisar(f"borrados {borrados} mensaje(s) {MARCA} propios que quedaban en ingesta")


def cuerpo(v) -> None:
    ctx = Contexto(sello=v.sello)
    if not v.precondicion("P4", lambda: p4_credenciales(ctx)):
        for p in ("P5", "P1", "P2", "P3"):
            v.precondicion_no_evaluada(p, "P4 no se cumple (credenciales)")
        return
    if not v.precondicion("P5", lambda: p5_horario(v, ctx)):
        for p in ("P1", "P2", "P3"):
            v.precondicion_no_evaluada(p, "P5 no se cumple")
        return
    if not v.precondicion("P1", lambda: p1_servicios(ctx)):
        v.precondicion_no_evaluada("P2", "P1 no se cumple")
        v.precondicion_no_evaluada("P3", "P1 no se cumple")
        return
    if not v.precondicion("P2", lambda: p2_borde(ctx)):
        v.precondicion_no_evaluada("P3", "P2 no se cumple")
        return
    if not v.precondicion("P3", lambda: p3_salidas(ctx)):
        return

    if v.alguna_incluida(*CAMBIAN):
        v.al_limpiar("dejar embedding y worker apagados (embedding.py apagar)", lambda: apagar_al_terminar(ctx))
    if v.alguna_incluida("C3b", "C4"):
        limpiar_restos(ctx)  # también «despierta» las colas para que SQS publique sus métricas (§3.4)
        v.al_limpiar(f"borrar los mensajes {MARCA} propios de ingesta", lambda: limpiar_mensajes(ctx))

    v.comprobacion("C2a", lambda: c2a_configuracion(ctx))
    v.comprobacion("C3a", lambda: c3a_configuracion(ctx))
    v.comprobacion("C1a", lambda: c1a_encender(ctx))
    v.comprobacion("C1b", lambda: c1b_apagar(ctx))
    v.comprobacion("C3b", lambda: c3b_worker(ctx))
    v.comprobacion("C2b", lambda: c2b_inactividad(ctx))
    v.comprobacion("C4", lambda: c4_sin_embedding(ctx))


def main() -> int:
    v = comun.Validador(
        lote="INF-2.1",
        validacion="validation-2-1",
        descripcion="INF-2.1 Encendido de embedding y escalado del worker: embedding.py, apagado por inactividad y a "
        "las 22:00, worker por cola solo con embedding encendido (dura 1,5-2 h)",
        comprobaciones=["C1a", "C1b", "C2a", "C2b", "C3a", "C3b", "C4"],
        grupos={"C1": ["C1a", "C1b"], "C2": ["C2a", "C2b"], "C3": ["C3a", "C3b"]},
    )
    return v.correr(cuerpo)


if __name__ == "__main__":
    sys.exit(main())
