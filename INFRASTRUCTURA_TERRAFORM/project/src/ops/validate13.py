"""Validador de INF-1.3 — Cómputo.

Documento: docs/validation/validation-1-3.md. Contrato común: docs/ARCHITECTURE.md §5.11.

Uso (desde INFRASTRUCTURA_TERRAFORM/project/):
    uv run --group ops python src/ops/validate13.py --entorno dev [--informe RUTA] [--solo C1,C3] [--sin-limpieza]
"""

from __future__ import annotations

import re
import sys
import time
from dataclasses import dataclass, field

from botocore.exceptions import ClientError, WaiterError

import comun

PREFIJO = "campus-locator-dev"
CLUSTER = PREFIJO
INSTANCIA = f"{PREFIJO}-db"
SECRETO_DB = "campus-locator/dev/db"
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
BUCKET = f"{PREFIJO}-dataset-{comun.CUENTA}"
BUCKET_ARN = f"arn:aws:s3:::{BUCKET}"
BUCKET_ESTADO = f"campus-locator-tfstate-{comun.CUENTA}"
REPOS = {"backend": "campus-locator/backend", "embedding": "campus-locator/embedding"}
ETIQUETA_PRUEBA = "bootstrap"
SERVICIOS = {"api": "api", "worker": "worker", "embedding": "embedding"}
FAMILIAS = {p: f"{PREFIJO}-{p}" for p in ("api", "worker", "embedding", "migrate", "validacion")}
NAMESPACE = "campus-locator.local"
EMBEDDING_DNS = f"embedding.{NAMESPACE}"
GRUPO_API = f"{PREFIJO}-api"
SUBRED_TAREAS = f"{PREFIJO}-publica-a"
LOG_VALIDACION = "/campus-locator/dev/validacion"
INICIADO_POR = "validacion-1-3"
ROLES = {p: f"{PREFIJO}-tarea-{p}" for p in ("api", "worker", "embedding", "migrate")}
ROL_EJECUCION = f"{PREFIJO}-ecs-ejecucion"
BOOTSTRAP = {
    "rol_gha_terraform_plan_arn": "campus-locator-gha-terraform-plan",
    "rol_gha_terraform_arn": "campus-locator-gha-terraform",
    "rol_gha_deploy_arn": "campus-locator-gha-deploy",
}
GITHUB_REPO = "Ang3l1485/Proyecto_4U"
LIMITE_ROLES = "campus-locator-limite-roles"

ESPERA_ESTABLE_S = 600  # services-stable, máx. 10 min (validation-1-3 §2)
ESPERA_SANA_S = 300  # healthStatus = HEALTHY tras estabilizarse (start period de embedding: 180 s)
ESPERA_TAREA_S = 600  # tarea de validación hasta STOPPED
ESPERA_CLOUD_MAP_S = 120  # registro de la instancia en Cloud Map


# ---------------------------------------------------------------------------------------------------------------------
# Utilidades (las mismas formas que validate12.py)
# ---------------------------------------------------------------------------------------------------------------------


def llamar(accion: str, fn, *codigos_ausente: str):
    """Ejecuta una llamada de boto3. Devuelve None si el error es uno de `codigos_ausente`; los demás los traduce
    comun.errores_aws (permisos → código 3; el resto → Falla)."""
    with comun.errores_aws(accion):
        try:
            return fn()
        except ClientError as exc:
            if comun.codigo_error_aws(exc) in codigos_ausente:
                return None
            raise


def llamar_precondicion(accion: str, fn, *codigos_ausente: str):
    """Como `llamar`, para las precondiciones: un error de AWS que no es «no existe» es de entorno (código 3)."""
    try:
        return llamar(accion, fn, *codigos_ausente)
    except comun.Falla as exc:
        if isinstance(exc, comun.Bloqueo):
            raise
        raise comun.ErrorConfiguracion(str(exc)) from exc


def paginar(cliente, operacion: str, clave: str, accion: str, **parametros) -> list:
    def todo():
        elementos = []
        for pagina in cliente.get_paginator(operacion).paginate(**parametros):
            elementos.extend(pagina.get(clave, []))
        return elementos

    return llamar(accion, todo)


def comprobar(problemas: list[str], detalle: str) -> str:
    if problemas:
        raise comun.Falla("; ".join(problemas))
    return detalle


def etiquetas_de(lista: list | None) -> dict:
    return {e.get("Key"): e.get("Value") for e in (lista or [])}


def ip_privada(tarea: dict) -> str | None:
    for adjunto in tarea.get("attachments", []):
        if adjunto.get("type") != "ElasticNetworkInterface":
            continue
        for d in adjunto.get("details", []):
            if d.get("name") == "privateIPv4Address":
                return d.get("value")
    return None


def id_tarea(arn: str) -> str:
    return arn.rsplit("/", 1)[-1]


# ---------------------------------------------------------------------------------------------------------------------
# Estado compartido
# ---------------------------------------------------------------------------------------------------------------------


@dataclass
class Servicio:
    """Resultado de poner un servicio en 1 (C1a/C1b para api; C2/C6 para embedding). Se hace una sola vez."""

    estado: str | None = None  # None, "listo" o "fallido"
    error: BaseException | None = None
    servicio: dict = field(default_factory=dict)
    tarea: dict = field(default_factory=dict)
    ip: str | None = None


@dataclass
class Contexto:
    sesion: object = None
    clientes: dict = field(default_factory=dict)
    salidas: dict = field(default_factory=dict)  # terraform output de envs/dev
    servicios: dict = field(default_factory=dict)  # nombre → Servicio
    tareas_lanzadas: list = field(default_factory=list)  # ARN de tareas de validación propias

    def cliente(self, servicio: str):
        if servicio not in self.clientes:
            self.clientes[servicio] = self.sesion.client(servicio, region_name=comun.REGION)
        return self.clientes[servicio]

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


def p3_credenciales(ctx: Contexto) -> str:
    ctx.sesion = comun.sesion_aws()
    return f"{comun.comprobar_cuenta(ctx.sesion)} (cuenta {comun.CUENTA})"


def p1_datos(ctx: Contexto) -> str:
    rds = ctx.cliente("rds")
    respuesta = llamar_precondicion(
        f"describir {INSTANCIA} (rds:DescribeDBInstances)",
        lambda: rds.describe_db_instances(DBInstanceIdentifier=INSTANCIA),
        "DBInstanceNotFound",
        "DBInstanceNotFoundFault",
    )
    if not respuesta or not respuesta.get("DBInstances"):
        raise comun.Bloqueo(f"INF-1.2 no está aplicado: no existe {INSTANCIA}")
    estado = respuesta["DBInstances"][0].get("DBInstanceStatus")
    if estado != "available":
        raise comun.Bloqueo(f"{INSTANCIA} está en {estado!r}, no available")
    secretos = ctx.cliente("secretsmanager")
    if (
        llamar_precondicion(
            f"describir {SECRETO_DB} (secretsmanager:DescribeSecret)",
            lambda: secretos.describe_secret(SecretId=SECRETO_DB),
            "ResourceNotFoundException",
        )
        is None
    ):
        raise comun.Bloqueo(f"INF-1.2 no está aplicado: no existe {SECRETO_DB}")
    sqs = ctx.cliente("sqs")
    for clave in ("ingesta", "purga"):
        nombre = COLAS[clave]
        if (
            llamar_precondicion(
                f"obtener la URL de {nombre} (sqs:GetQueueUrl)",
                lambda n=nombre: sqs.get_queue_url(QueueName=n),
                "AWS.SimpleQueueService.NonExistentQueue",
                "QueueDoesNotExist",
            )
            is None
        ):
            raise comun.Bloqueo(f"INF-1.2 no está aplicado: no existe {nombre}")
    return f"{INSTANCIA} available, {SECRETO_DB}, ingesta y purga"


def p2_salidas(ctx: Contexto) -> str:
    ctx.salidas = comun.terraform_outputs("envs/dev")
    faltan = [s for s in ("ecs_cluster", "familias_tarea", "subredes_tareas", "sg_migrate") if s not in ctx.salidas]
    if not faltan and "validacion" not in (ctx.salidas.get("familias_tarea") or {}):
        faltan.append("familias_tarea.validacion")
    if faltan:
        raise comun.Bloqueo(f"INF-1.3 no está aplicado en envs/dev: faltan los outputs {', '.join(faltan)}")
    return "ecs_cluster, familias_tarea (con validacion), subredes_tareas y sg_migrate"


# ---------------------------------------------------------------------------------------------------------------------
# Servicios en 1 (C1, C2, C6)
# ---------------------------------------------------------------------------------------------------------------------


def describir_servicio(ctx: Contexto, nombre: str) -> dict:
    ecs = ctx.cliente("ecs")
    respuesta = llamar(
        f"describir el servicio {nombre} (ecs:DescribeServices)",
        lambda: ecs.describe_services(cluster=CLUSTER, services=[nombre]),
        "ClusterNotFoundException",
    )
    servicios = [s for s in (respuesta or {}).get("services", []) if s.get("status") == "ACTIVE"]
    if not servicios:
        raise comun.Falla(f"no existe el servicio {nombre} en {CLUSTER}")
    return servicios[0]


def tareas_en_marcha(ctx: Contexto, **filtro) -> list[dict]:
    ecs = ctx.cliente("ecs")
    arns = paginar(
        ecs,
        "list_tasks",
        "taskArns",
        "listar tareas (ecs:ListTasks)",
        cluster=CLUSTER,
        desiredStatus="RUNNING",
        **filtro,
    )
    if not arns:
        return []
    return llamar(
        "describir tareas (ecs:DescribeTasks)", lambda: ecs.describe_tasks(cluster=CLUSTER, tasks=arns[:100])
    ).get("tasks", [])


def poner_en_uno(v, ctx: Contexto, nombre: str) -> Servicio:
    """Sube el servicio a 1 si estaba en 0 (y registra devolverlo a 0), espera services-stable y una tarea sana."""
    estado = ctx.servicios.setdefault(nombre, Servicio())
    if estado.estado == "listo":
        return estado
    if estado.estado == "fallido":
        raise estado.error
    try:
        ecs = ctx.cliente("ecs")
        servicio = describir_servicio(ctx, nombre)
        if servicio.get("desiredCount", 0) == 0:
            comun.avisar(f"subiendo {nombre} a 1 réplica (al terminar vuelve a 0)…")
            v.al_limpiar(
                f"devolver el servicio {nombre} a 0 réplicas",
                lambda: llamar(
                    f"devolver {nombre} a 0 (ecs:UpdateService)",
                    lambda: ecs.update_service(cluster=CLUSTER, service=nombre, desiredCount=0),
                ),
            )
            llamar(
                f"subir {nombre} a 1 (ecs:UpdateService)",
                lambda: ecs.update_service(cluster=CLUSTER, service=nombre, desiredCount=1),
            )
        comun.avisar(f"esperando a que {nombre} esté estable (hasta {ESPERA_ESTABLE_S // 60} min)…")
        # WaiterError hereda de BotoCoreError: se captura dentro del with para que cuente como Falla, no como error
        # de configuración.
        estable = True
        with comun.errores_aws(f"esperar a {nombre} (ecs:DescribeServices)"):
            try:
                ecs.get_waiter("services_stable").wait(
                    cluster=CLUSTER,
                    services=[nombre],
                    WaiterConfig={"Delay": 15, "MaxAttempts": ESPERA_ESTABLE_S // 15},
                )
            except WaiterError:
                estable = False
        if not estable:
            servicio = describir_servicio(ctx, nombre)
            eventos = "; ".join(e.get("message", "") for e in servicio.get("events", [])[:3])
            raise comun.Falla(
                f"{nombre} no quedó estable en {ESPERA_ESTABLE_S // 60} min: {comun.resumir(eventos, 400)}"
            )

        limite = time.monotonic() + ESPERA_SANA_S
        while True:
            tareas = tareas_en_marcha(ctx, serviceName=nombre)
            sanas = [t for t in tareas if t.get("lastStatus") == "RUNNING" and t.get("healthStatus") == "HEALTHY"]
            requiere_salud = nombre != "worker"
            if sanas or (tareas and not requiere_salud):
                break
            if time.monotonic() > limite:
                vistos = [(t.get("lastStatus"), t.get("healthStatus")) for t in tareas]
                raise comun.Falla(f"{nombre} sin tarea HEALTHY en {ESPERA_SANA_S} s (tareas: {vistos})")
            time.sleep(10)
        estado.tarea = (sanas or tareas)[0]
        estado.ip = ip_privada(estado.tarea)
        estado.servicio = describir_servicio(ctx, nombre)
        estado.estado = "listo"
        return estado
    except BaseException as exc:
        estado.estado, estado.error = "fallido", exc
        raise


# ---------------------------------------------------------------------------------------------------------------------
# Tarea de validación (§5.11)
# ---------------------------------------------------------------------------------------------------------------------


def parar_tareas_propias(ctx: Contexto, solo_las_mias: bool) -> None:
    """Detiene las tareas RUNNING con startedBy = validacion-1-3 (al empezar: restos; al limpiar: las propias)."""
    ecs = ctx.cliente("ecs")
    for tarea in tareas_en_marcha(ctx, startedBy=INICIADO_POR):
        if solo_las_mias and tarea["taskArn"] not in ctx.tareas_lanzadas:
            continue
        llamar(
            "detener una tarea de validación (ecs:StopTask)",
            lambda a=tarea["taskArn"]: ecs.stop_task(cluster=CLUSTER, task=a, reason="validate13: limpieza"),
        )
        comun.avisar(f"tarea de validación {id_tarea(tarea['taskArn'])} detenida")


def lanzar_validacion(ctx: Contexto, guion: str, que: str) -> tuple[int | None, str]:
    """Lanza la tarea de validación con `sh -c guion`, espera STOPPED y devuelve (código de app, log). El log no se
    imprime: lo analiza quien llama."""
    ecs = ctx.cliente("ecs")
    respuesta = llamar(
        f"lanzar la tarea de validación para {que} (ecs:RunTask)",
        lambda: ecs.run_task(
            cluster=CLUSTER,
            taskDefinition=ctx.salidas["familias_tarea"]["validacion"],
            launchType="FARGATE",
            startedBy=INICIADO_POR,
            count=1,
            networkConfiguration=ctx.red_tareas(),
            overrides={"containerOverrides": [{"name": "app", "command": ["sh", "-c", guion]}]},
        ),
    )
    if respuesta.get("failures") or not respuesta.get("tasks"):
        raise comun.Falla(f"run-task falló: {respuesta.get('failures')}")
    arn = respuesta["tasks"][0]["taskArn"]
    ctx.tareas_lanzadas.append(arn)
    comun.avisar(f"tarea de validación {id_tarea(arn)} ({que}) lanzada; esperando a que termine…")
    with comun.errores_aws("esperar la tarea de validación (ecs:DescribeTasks)"):
        try:
            ecs.get_waiter("tasks_stopped").wait(
                cluster=CLUSTER, tasks=[arn], WaiterConfig={"Delay": 6, "MaxAttempts": ESPERA_TAREA_S // 6}
            )
        except WaiterError as exc:
            raise comun.Falla(f"la tarea de validación no terminó en {ESPERA_TAREA_S // 60} min") from exc
    tarea = llamar(
        "describir la tarea de validación (ecs:DescribeTasks)",
        lambda: ecs.describe_tasks(cluster=CLUSTER, tasks=[arn]),
    )["tasks"][0]
    app = next((c for c in tarea.get("containers", []) if c.get("name") == "app"), {})
    codigo = app.get("exitCode")
    if codigo is None:
        raise comun.Falla(
            f"la tarea de validación no llegó a ejecutar app: {tarea.get('stoppedReason')} {app.get('reason') or ''}"
        )
    return codigo, leer_log(ctx, f"validacion/app/{id_tarea(arn)}")


def leer_log(ctx: Contexto, stream: str) -> str:
    logs = ctx.cliente("logs")
    limite = time.monotonic() + 30  # los eventos pueden tardar unos segundos en aparecer
    while True:
        respuesta = llamar(
            f"leer {LOG_VALIDACION} (logs:GetLogEvents)",
            lambda: logs.get_log_events(logGroupName=LOG_VALIDACION, logStreamName=stream, startFromHead=True),
            "ResourceNotFoundException",
        )
        lineas = [e.get("message", "") for e in (respuesta or {}).get("events", [])]
        if lineas or time.monotonic() > limite:
            return "\n".join(lineas)
        time.sleep(5)


# ---------------------------------------------------------------------------------------------------------------------
# C1: api con la imagen de prueba y Cloud Map SRV
# ---------------------------------------------------------------------------------------------------------------------


def comprobar_imagenes(ctx: Contexto) -> None:
    ecr = ctx.cliente("ecr")
    faltan = []
    for repo in REPOS.values():
        respuesta = llamar(
            f"buscar {repo}:{ETIQUETA_PRUEBA} (ecr:DescribeImages)",
            lambda r=repo: ecr.describe_images(repositoryName=r, imageIds=[{"imageTag": ETIQUETA_PRUEBA}]),
            "ImageNotFoundException",
            "RepositoryNotFoundException",
        )
        if not respuesta or not respuesta.get("imageDetails"):
            faltan.append(f"{repo}:{ETIQUETA_PRUEBA}")
    if faltan:
        raise comun.Falla(
            f"falta la imagen de prueba en {', '.join(faltan)}: publicarla (pruebas/imagen-prueba/README.md)"
        )


def c1a_api(v, ctx: Contexto) -> str:
    comprobar_imagenes(ctx)
    api = poner_en_uno(v, ctx, "api")
    problemas = []
    if api.servicio.get("runningCount") != 1:
        problemas.append(f"runningCount = {api.servicio.get('runningCount')}")
    primario = next((d for d in api.servicio.get("deployments", []) if d.get("status") == "PRIMARY"), {})
    if primario.get("rolloutState") != "COMPLETED":
        problemas.append(f"despliegue {primario.get('rolloutState')}, no COMPLETED")
    if api.tarea.get("healthStatus") != "HEALTHY":
        problemas.append(f"tarea {api.tarea.get('healthStatus')}")
    return comprobar(problemas, f"imagen bootstrap en los dos repositorios; api estable, 1 tarea HEALTHY ({api.ip})")


def servicio_cloud_map(ctx: Contexto, nombre: str) -> dict:
    sd = ctx.cliente("servicediscovery")
    espacios = paginar(
        sd,
        "list_namespaces",
        "Namespaces",
        "listar espacios de nombres (servicediscovery:ListNamespaces)",
        Filters=[{"Name": "TYPE", "Values": ["DNS_PRIVATE"], "Condition": "EQ"}],
    )
    propios = [n for n in espacios if n.get("Name") == NAMESPACE]
    if len(propios) != 1:
        raise comun.Falla(f"{len(propios)} espacios de nombres privados {NAMESPACE}; debe haber uno")
    servicios = paginar(
        sd,
        "list_services",
        "Services",
        "listar servicios de Cloud Map (servicediscovery:ListServices)",
        Filters=[{"Name": "NAMESPACE_ID", "Values": [propios[0]["Id"]], "Condition": "EQ"}],
    )
    elegido = next((s for s in servicios if s.get("Name") == nombre), None)
    if elegido is None:
        raise comun.Falla(f"no existe el servicio de Cloud Map {nombre}.{NAMESPACE}")
    return llamar(
        f"describir {nombre}.{NAMESPACE} (servicediscovery:GetService)",
        lambda: sd.get_service(Id=elegido["Id"]),
    )["Service"]


def c1b_cloud_map(v, ctx: Contexto) -> str:
    api = poner_en_uno(v, ctx, "api")
    sd = ctx.cliente("servicediscovery")
    servicio = servicio_cloud_map(ctx, "api")
    tipos = {r.get("Type") for r in (servicio.get("DnsConfig") or {}).get("DnsRecords", [])}
    if "SRV" not in tipos:
        raise comun.Falla(f"api.{NAMESPACE} tiene registros {sorted(tipos)}, sin SRV")
    limite = time.monotonic() + ESPERA_CLOUD_MAP_S
    while True:
        instancias = paginar(
            sd,
            "list_instances",
            "Instances",
            "listar instancias de api (servicediscovery:ListInstances)",
            ServiceId=servicio["Id"],
        )
        registradas = [i.get("Attributes", {}) for i in instancias]
        coincide = any(
            a.get("AWS_INSTANCE_IPV4") == api.ip and a.get("AWS_INSTANCE_PORT") == "8000" for a in registradas
        )
        descubiertas = llamar(
            "descubrir api (servicediscovery:DiscoverInstances)",
            lambda: sd.discover_instances(NamespaceName=NAMESPACE, ServiceName="api", HealthStatus="HEALTHY"),
        ).get("Instances", [])
        sana = any((i.get("Attributes") or {}).get("AWS_INSTANCE_IPV4") == api.ip for i in descubiertas)
        if coincide and sana:
            return f"registros {sorted(tipos)}; instancia {api.ip}:8000 registrada y devuelta como sana"
        if time.monotonic() > limite:
            raise comun.Falla(
                f"en {ESPERA_CLOUD_MAP_S} s la instancia {api.ip}:8000 no apareció registrada (vista: {coincide}) "
                f"y sana (vista: {sana}); registradas: "
                f"{[(a.get('AWS_INSTANCE_IPV4'), a.get('AWS_INSTANCE_PORT')) for a in registradas]}"
            )
        time.sleep(10)


# ---------------------------------------------------------------------------------------------------------------------
# C2 y C6: embedding
# ---------------------------------------------------------------------------------------------------------------------


def c2_dns_embedding(v, ctx: Contexto) -> str:
    comprobar_imagenes(ctx)
    emb = poner_en_uno(v, ctx, "embedding")
    servicio = servicio_cloud_map(ctx, "embedding")
    registros = [(r.get("Type"), r.get("TTL")) for r in (servicio.get("DnsConfig") or {}).get("DnsRecords", [])]
    if ("A", 10) not in registros:
        raise comun.Falla(f"{EMBEDDING_DNS} tiene registros {registros}; falta A con TTL 10")
    codigo, log = lanzar_validacion(ctx, f"nslookup {EMBEDDING_DNS}", "nslookup")
    direcciones = set(re.findall(r"Address:\s*([0-9.]+)\s*$", log, flags=re.MULTILINE))
    if codigo != 0:
        raise comun.Falla(f"nslookup salió con {codigo}: {comun.resumir(log, 300)}")
    if emb.ip not in direcciones:
        raise comun.Falla(f"{EMBEDDING_DNS} resolvió {sorted(direcciones)}, no la IP de la tarea ({emb.ip})")
    return f"{EMBEDDING_DNS} → {emb.ip} desde la tarea de validación; registro A con TTL 10"


def c6_embedding_fargate(v, ctx: Contexto) -> str:
    comprobar_imagenes(ctx)
    tarea = poner_en_uno(v, ctx, "embedding").tarea
    problemas = []
    if tarea.get("launchType") != "FARGATE":
        problemas.append(f"launchType {tarea.get('launchType')}")
    if str(tarea.get("cpu")) != "2048" or str(tarea.get("memory")) != "4096":
        problemas.append(f"cpu/memory {tarea.get('cpu')}/{tarea.get('memory')}, no 2048/4096")
    if tarea.get("healthStatus") != "HEALTHY":
        problemas.append(f"healthStatus {tarea.get('healthStatus')}")
    return comprobar(problemas, "embedding en FARGATE con 2 vCPU / 4 GB, HEALTHY")


# ---------------------------------------------------------------------------------------------------------------------
# C3: simulación de IAM
# ---------------------------------------------------------------------------------------------------------------------


def arn_rol(nombre: str) -> str:
    return f"arn:aws:iam::{comun.CUENTA}:role/{nombre}"


def arn_cola(clave: str) -> str:
    return f"arn:aws:sqs:{comun.REGION}:{comun.CUENTA}:{COLAS[clave]}"


def objeto(clave: str) -> str:
    return f"{BUCKET_ARN}/{clave}"


def contexto_prefijo(prefijo: str) -> list[dict]:
    return [{"ContextKeyName": "s3:prefix", "ContextKeyValues": [prefijo], "ContextKeyType": "string"}]


# Cada caso: (acciones, recurso, contexto)
def casos_permitidos() -> dict[str, list[tuple]]:
    s3_api = ["s3:GetObject", "s3:PutObject"]
    s3_worker = ["s3:DeleteObject", "s3:GetObject", "s3:PutObject"]
    prefijos = ["dataset/x.jpg", "thumbs/x.jpg", "lugares/x.jpg"]
    sqs_worker = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:ChangeMessageVisibility", "sqs:GetQueueAttributes"]
    return {
        "api": [(s3_api, objeto(p), None) for p in prefijos]
        + [(["sqs:SendMessage"], arn_cola(c), None) for c in ("purga", "ingesta")]
        + [(["ssmmessages:CreateControlChannel"], "*", None)],
        "worker": [(s3_worker, objeto(p), None) for p in prefijos]
        + [(["s3:ListBucket"], BUCKET_ARN, contexto_prefijo("dataset/x"))]
        + [(sqs_worker, arn_cola(c), None) for c in ("ingesta", "purga")],
    }


def casos_denegados(secretos: dict) -> dict[str, list[tuple]]:
    dlq = ["sqs:SendMessage", "sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:PurgeQueue"]
    comunes = (
        [(dlq, arn_cola(c), None) for c in ("ingesta_dlq", "purga_dlq")]
        + [(["s3:GetObject", "s3:PutObject"], f"arn:aws:s3:::{BUCKET_ESTADO}/dev/terraform.tfstate", None)]
        + [(["s3:ListBucket"], f"arn:aws:s3:::{BUCKET_ESTADO}", None)]
        + [(["secretsmanager:GetSecretValue"], arn, None) for arn in secretos.values()]
        + [
            (
                ["ecs:RunTask"],
                f"arn:aws:ecs:{comun.REGION}:{comun.CUENTA}:task-definition/{FAMILIAS['migrate']}:1",
                None,
            )
        ]
        + [(["iam:PassRole"], arn_rol(ROL_EJECUCION), None)]
        + [(["s3:GetObject"], objeto("evaluacion/x.jpg"), None)]
    )
    permitidos = casos_permitidos()
    todos_los_de_c3a = permitidos["api"] + permitidos["worker"]
    return {
        "api": comunes
        + [(["s3:DeleteObject"], objeto("dataset/x.jpg"), None)]
        + [(["s3:ListBucket"], BUCKET_ARN, contexto_prefijo("dataset/x"))]
        + [(["sqs:ReceiveMessage"], arn_cola("ingesta"), None)],
        "worker": comunes
        + [(["s3:ListBucket"], BUCKET_ARN, contexto_prefijo("evaluacion/x"))]
        + [(["sqs:SendMessage"], arn_cola(c), None) for c in ("ingesta", "purga")],
        "embedding": comunes + todos_los_de_c3a,
        "migrate": comunes + todos_los_de_c3a,
    }


def simular(ctx: Contexto, rol: str, casos: list[tuple]) -> list[tuple[str, str, str]]:
    """Devuelve [(acción, recurso, decisión)] de cada caso."""
    iam = ctx.cliente("iam")
    resultados = []
    for acciones, recurso, contexto in casos:
        parametros = {"PolicySourceArn": arn_rol(ROLES[rol]), "ActionNames": acciones, "ResourceArns": [recurso]}
        if contexto:
            parametros["ContextEntries"] = contexto
        respuesta = llamar(
            f"simular {ROLES[rol]} (iam:SimulatePrincipalPolicy)",
            lambda p=parametros: iam.simulate_principal_policy(**p),
            "NoSuchEntity",
        )
        if respuesta is None:
            raise comun.Falla(f"no existe el rol {ROLES[rol]}")
        for r in respuesta.get("EvaluationResults", []):
            resultados.append((r.get("EvalActionName"), recurso, r.get("EvalDecision")))
    return resultados


def c3a_permitidos(ctx: Contexto) -> str:
    problemas, total = [], 0
    for rol, casos in casos_permitidos().items():
        for accion, recurso, decision in simular(ctx, rol, casos):
            total += 1
            if decision != "allowed":
                problemas.append(f"{rol}: {accion} en {recurso.rsplit(':', 1)[-1]} → {decision}")
    return comprobar(problemas, f"{total} acciones de §5.8 permitidas a api y worker")


def c3b_denegados(ctx: Contexto) -> str:
    problemas, total = [], 0
    secretos = ctx.salidas.get("secretos") or {}
    if set(secretos) != set(SECRETOS):
        raise comun.Falla(f"output secretos con claves {sorted(secretos)}")
    for rol, casos in casos_denegados(secretos).items():
        for accion, recurso, decision in simular(ctx, rol, casos):
            total += 1
            if decision not in ("implicitDeny", "explicitDeny"):
                problemas.append(f"{rol}: {accion} en {recurso.rsplit(':', 1)[-1]} → {decision}")
    iam = ctx.cliente("iam")
    for rol in ("embedding", "migrate"):
        adjuntas = paginar(
            iam,
            "list_attached_role_policies",
            "AttachedPolicies",
            f"listar políticas de {ROLES[rol]} (iam:ListAttachedRolePolicies)",
            RoleName=ROLES[rol],
        )
        en_linea = paginar(
            iam,
            "list_role_policies",
            "PolicyNames",
            f"listar políticas en línea de {ROLES[rol]} (iam:ListRolePolicies)",
            RoleName=ROLES[rol],
        )
        if adjuntas or en_linea:
            problemas.append(f"{ROLES[rol]} tiene políticas: {[p.get('PolicyName') for p in adjuntas] + en_linea}")
    return comprobar(
        problemas, f"{total} acciones fuera de §5.8 denegadas; tarea-embedding y tarea-migrate sin políticas"
    )


# ---------------------------------------------------------------------------------------------------------------------
# C4: outputs
# ---------------------------------------------------------------------------------------------------------------------

SALIDAS_DEV = [
    "ecr_backend_url",
    "ecr_embedding_url",
    "ecs_cluster",
    "ecs_servicios",
    "familias_tarea",
    "subredes_tareas",
    "sg_migrate",
    "bucket_dataset",
    "sqs_ingesta_url",
    "sqs_purga_url",
    "sqs_ingesta_dlq_url",
    "sqs_purga_dlq_url",
    "rds_endpoint",
    "secretos",
    "embedding_dns",
]


def c4_salidas(ctx: Contexto) -> str:
    s = ctx.salidas
    problemas = [f"falta el output {n}" for n in SALIDAS_DEV if n not in s]
    if problemas:
        raise comun.Falla("; ".join(problemas))
    ecs, ec2, sqs, rds, ecr, sm, iam = (
        ctx.cliente(c) for c in ("ecs", "ec2", "sqs", "rds", "ecr", "secretsmanager", "iam")
    )

    if s["ecs_cluster"] != CLUSTER:
        problemas.append(f"ecs_cluster = {s['ecs_cluster']!r}")
    else:
        clusters = llamar(
            "describir el clúster (ecs:DescribeClusters)", lambda: ecs.describe_clusters(clusters=[CLUSTER])
        )
        if not any(c.get("status") == "ACTIVE" for c in clusters.get("clusters", [])):
            problemas.append(f"el clúster {CLUSTER} no está ACTIVE")
    if s["ecs_servicios"] != SERVICIOS:
        problemas.append(f"ecs_servicios = {s['ecs_servicios']}")
    if s["familias_tarea"] != FAMILIAS:
        problemas.append(f"familias_tarea = {s['familias_tarea']}")
    else:
        for familia in FAMILIAS.values():
            if (
                llamar(
                    f"describir {familia} (ecs:DescribeTaskDefinition)",
                    lambda f=familia: ecs.describe_task_definition(taskDefinition=f),
                    "ClientException",
                )
                is None
            ):
                problemas.append(f"no existe la familia {familia}")

    subredes = llamar(
        "buscar publica-a (ec2:DescribeSubnets)",
        lambda: ec2.describe_subnets(Filters=[{"Name": "tag:Name", "Values": [SUBRED_TAREAS]}]),
    )["Subnets"]
    if [x["SubnetId"] for x in subredes] != list(s["subredes_tareas"]):
        problemas.append(f"subredes_tareas no es [ID de {SUBRED_TAREAS}]")
    grupos = llamar(
        "buscar el grupo -api (ec2:DescribeSecurityGroups)",
        lambda: ec2.describe_security_groups(Filters=[{"Name": "group-name", "Values": [GRUPO_API]}]),
    )["SecurityGroups"]
    if [g["GroupId"] for g in grupos] != [s["sg_migrate"]]:
        problemas.append(f"sg_migrate no es el ID de {GRUPO_API}")

    if s["bucket_dataset"] != BUCKET:
        problemas.append(f"bucket_dataset = {s['bucket_dataset']!r}")
    for clave, nombre in COLAS.items():
        url = llamar(
            f"obtener la URL de {nombre} (sqs:GetQueueUrl)",
            lambda n=nombre: sqs.get_queue_url(QueueName=n),
            "AWS.SimpleQueueService.NonExistentQueue",
            "QueueDoesNotExist",
        )
        if not url or url["QueueUrl"] != s[f"sqs_{clave}_url"]:
            problemas.append(f"sqs_{clave}_url no es la URL de {nombre}")
    instancia = llamar(
        f"describir {INSTANCIA} (rds:DescribeDBInstances)",
        lambda: rds.describe_db_instances(DBInstanceIdentifier=INSTANCIA),
    )["DBInstances"][0]
    if (instancia.get("Endpoint") or {}).get("Address") != s["rds_endpoint"]:
        problemas.append("rds_endpoint no es Endpoint.Address")
    if set(s["secretos"]) != set(SECRETOS):
        problemas.append(f"secretos con claves {sorted(s['secretos'])}")
    else:
        for clave, nombre in SECRETOS.items():
            descripcion = llamar(
                f"describir {nombre} (secretsmanager:DescribeSecret)",
                lambda n=nombre: sm.describe_secret(SecretId=n),
                "ResourceNotFoundException",
            )
            if not descripcion or descripcion.get("ARN") != s["secretos"][clave]:
                problemas.append(f"secretos.{clave} no es el ARN de {nombre}")
    if s["embedding_dns"] != EMBEDDING_DNS:
        problemas.append(f"embedding_dns = {s['embedding_dns']!r}")
    for clave, repo in REPOS.items():
        respuesta = llamar(
            f"describir {repo} (ecr:DescribeRepositories)",
            lambda r=repo: ecr.describe_repositories(repositoryNames=[r]),
            "RepositoryNotFoundException",
        )
        uri = ((respuesta or {}).get("repositories") or [{}])[0].get("repositoryUri")
        if uri != s[f"ecr_{clave}_url"]:
            problemas.append(f"ecr_{clave}_url no es el repositoryUri de {repo}")

    b = comun.terraform_outputs("bootstrap")
    for salida, rol in BOOTSTRAP.items():
        if b.get(salida) != arn_rol(rol):
            problemas.append(f"bootstrap: {salida} no es el ARN de {rol}")
        elif llamar(f"describir {rol} (iam:GetRole)", lambda r=rol: iam.get_role(RoleName=r), "NoSuchEntity") is None:
            problemas.append(f"no existe el rol {rol}")
    if b.get("bucket_estado") != BUCKET_ESTADO:
        problemas.append(f"bootstrap: bucket_estado = {b.get('bucket_estado')!r}")
    if b.get("github_repo") != GITHUB_REPO:
        problemas.append(f"bootstrap: github_repo = {b.get('github_repo')!r}")
    limite = f"arn:aws:iam::{comun.CUENTA}:policy/{LIMITE_ROLES}"
    if b.get("limite_roles_arn") != limite:
        problemas.append("bootstrap: limite_roles_arn no es el ARN de campus-locator-limite-roles")
    else:
        for rol in [ROL_EJECUCION, *ROLES.values()]:
            datos = llamar(f"describir {rol} (iam:GetRole)", lambda r=rol: iam.get_role(RoleName=r), "NoSuchEntity")
            frontera = ((datos or {}).get("Role", {}).get("PermissionsBoundary") or {}).get("PermissionsBoundaryArn")
            if frontera != limite:
                problemas.append(f"{rol} sin el permissions boundary {LIMITE_ROLES}")
    return comprobar(
        problemas,
        f"{len(SALIDAS_DEV)} outputs de envs/dev y 6 de bootstrap coherentes; los 5 roles de ECS con el boundary",
    )


# ---------------------------------------------------------------------------------------------------------------------
# C5: base con TLS y pgvector desde la VPC
# ---------------------------------------------------------------------------------------------------------------------

GUION_C5 = r"""set -e
psql "sslmode=require" -v ON_ERROR_STOP=1 -At \
  -c "SELECT 'SSL=' || ssl FROM pg_stat_ssl WHERE pid = pg_backend_pid()" \
  -c "CREATE EXTENSION IF NOT EXISTS vector" \
  -c "SELECT 'VECTOR=' || extversion FROM pg_extension WHERE extname = 'vector'"
if psql "sslmode=disable" -At -c 'SELECT 1' 2>/tmp/sin_tls; then
  echo "SIN_TLS=aceptada"
  exit 1
fi
echo "SIN_TLS=rechazada $(tr '\n' ' ' </tmp/sin_tls)"
"""


def version(texto: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", texto)[:3])


def c5_base(ctx: Contexto) -> str:
    codigo, log = lanzar_validacion(ctx, GUION_C5, "psql")
    ssl = re.search(r"^SSL=(\w+)", log, flags=re.MULTILINE)
    vector = re.search(r"^VECTOR=([\d.]+)", log, flags=re.MULTILINE)
    sin_tls = re.search(r"^SIN_TLS=(\w+)(.*)$", log, flags=re.MULTILINE)
    problemas = []
    if codigo != 0:
        problemas.append(f"app salió con {codigo}")
    if not ssl or ssl[1] not in ("t", "true"):  # boolean || text da «true» (no «t», que es lo que imprime psql)
        problemas.append(f"la conexión con sslmode=require no usa TLS ({ssl[1] if ssl else 'sin resultado'})")
    if not vector or version(vector[1]) < (0, 8, 0):
        problemas.append(f"extensión vector {vector[1] if vector else 'no creada'}; se exige ≥ 0.8.0")
    if not sin_tls or sin_tls[1] != "rechazada":
        problemas.append("la conexión sin TLS no fue rechazada")
    elif not re.search(r"no encryption|SSL off|pg_hba\.conf", sin_tls[2]):
        problemas.append(f"la conexión sin TLS falló por otro motivo: {comun.resumir(sin_tls[2].strip(), 200)}")
    if problemas and not (ssl or vector or sin_tls):
        problemas.append(f"log: {comun.resumir(log, 300)}")
    return comprobar(
        problemas,
        f"ssl = {ssl[1] if ssl else '?'}, vector {vector[1] if vector else '?'}, "
        "sin TLS rechazada (no pg_hba.conf entry … no encryption)",
    )


# ---------------------------------------------------------------------------------------------------------------------
# Programa
# ---------------------------------------------------------------------------------------------------------------------


def cuerpo(v) -> None:
    ctx = Contexto()
    if not v.precondicion("P3", lambda: p3_credenciales(ctx)):
        v.precondicion_no_evaluada("P1", "P3 no se cumple (credenciales)")
        v.precondicion_no_evaluada("P2", "P3 no se cumple (credenciales)")
        return
    if not v.precondicion("P1", lambda: p1_datos(ctx)):
        v.precondicion_no_evaluada("P2", "P1 no se cumple")
        return
    if not v.precondicion("P2", lambda: p2_salidas(ctx)):
        return

    if v.alguna_incluida("C2", "C5"):
        parar_tareas_propias(ctx, solo_las_mias=False)  # restos de otra ejecución
        v.al_limpiar(
            "detener las tareas de validación propias que sigan en marcha",
            lambda: parar_tareas_propias(ctx, solo_las_mias=True),
        )

    v.comprobacion("C1a", lambda: c1a_api(v, ctx))
    v.comprobacion("C1b", lambda: c1b_cloud_map(v, ctx))
    v.comprobacion("C2", lambda: c2_dns_embedding(v, ctx))
    v.comprobacion("C3a", lambda: c3a_permitidos(ctx))
    v.comprobacion("C3b", lambda: c3b_denegados(ctx))
    v.comprobacion("C4", lambda: c4_salidas(ctx))
    v.comprobacion("C5", lambda: c5_base(ctx))
    v.comprobacion("C6", lambda: c6_embedding_fargate(v, ctx))


def main() -> int:
    v = comun.Validador(
        lote="INF-1.3",
        validacion="validation-1-3",
        descripcion="INF-1.3 Cómputo: api y embedding con la imagen de prueba, Cloud Map, IAM de tareas, outputs, "
        "base con TLS y pgvector desde la VPC",
        comprobaciones=["C1a", "C1b", "C2", "C3a", "C3b", "C4", "C5", "C6"],
        grupos={"C1": ["C1a", "C1b"], "C3": ["C3a", "C3b"]},
    )
    return v.correr(cuerpo)


if __name__ == "__main__":
    sys.exit(main())
