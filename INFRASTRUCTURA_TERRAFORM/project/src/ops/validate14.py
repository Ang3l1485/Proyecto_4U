"""Validador de INF-1.4 — Borde HTTPS (API Gateway).

Documento: docs/validation/validation-1-4.md. Contrato común: docs/ARCHITECTURE.md §5.11.

Uso (desde INFRASTRUCTURA_TERRAFORM/project/):
    uv run --group ops python src/ops/validate14.py --entorno dev [--informe RUTA] [--solo C1,C3] [--sin-limpieza]
"""

from __future__ import annotations

import datetime as dt
import json
import re
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import httpx
from botocore.exceptions import ClientError, WaiterError

import comun

PREFIJO = "campus-locator-dev"
CLUSTER = PREFIJO
NOMBRE_API = f"{PREFIJO}-api"
NOMBRE_VPC_LINK = f"{PREFIJO}-vpclink"
GRUPO_VPC_LINK = f"{PREFIJO}-vpclink"
SUBREDES_PUBLICAS = [f"{PREFIJO}-publica-a", f"{PREFIJO}-publica-b"]
NAMESPACE = "campus-locator.local"
SERVICIO = "api"
REPO_BACKEND = "campus-locator/backend"
ETIQUETA_PRUEBA = "bootstrap"
LOG_APIGW = "/campus-locator/dev/apigw"
RUTA_GENERAL = "ANY /{proxy+}"
RUTA_LOGIN = "POST /v1/auth/login"
THROTTLING = {RUTA_GENERAL: (20, 40), RUTA_LOGIN: (2, 5)}  # (rate, burst), §5.10
CAMPOS_LOG = {
    "requestId",
    "ip",
    "requestTime",
    "httpMethod",
    "routeKey",
    "path",
    "status",
    "responseLength",
    "integrationLatency",
    "integrationStatus",
}
PATRON_URL = re.compile(r"^https://[a-z0-9]+\.execute-api\.us-east-1\.amazonaws\.com$")

ESPERA_ESTABLE_S = 600  # services-stable, máx. 10 min
ESPERA_SANA_S = 300  # tarea HEALTHY tras estabilizarse
ESPERA_CLOUD_MAP_S = 120  # instancia devuelta como sana por Cloud Map
ESPERA_HEALTH_S = 120  # reintentos de GET /v1/health (C1b)
ESPERA_LOG_S = 180  # aparición del access log (C3b)
# C2b. API Gateway aplica el throttling de forma aproximada (lo reparte entre nodos): a 5 req/s casi nada recibe 429.
# Medido el 2026-10-24 contra login (2/5): 23 % de 429 a 10 req/s, 34 % a 20 y 57 % a 50 (ARCHITECTURE §3.3).
LOGIN = {"total": 200, "por_s": 20, "minimo_429": 0.10}
HEALTH = {"total": 100, "por_s": 10}  # C2b
PAUSA_C2B_S = 10


# ---------------------------------------------------------------------------------------------------------------------
# Utilidades (las mismas formas que validate13.py)
# ---------------------------------------------------------------------------------------------------------------------


def llamar(accion: str, fn, *codigos_ausente: str):
    """Ejecuta una llamada de boto3. None si el error es uno de `codigos_ausente`; los demás los traduce
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
        raise comun.ErrorConfiguracion(str(exc)) from exc


def paginar(cliente, operacion: str, clave: str, accion: str, **parametros) -> list:
    def todo():
        elementos = []
        for pagina in cliente.get_paginator(operacion).paginate(**parametros):
            elementos.extend(pagina.get(clave, []))
        return elementos

    return llamar(accion, todo)


def paginar_token(fn, clave: str, accion: str, **parametros) -> list:
    """Paginación por NextToken para las operaciones de apigatewayv2 (no todas tienen paginador en boto3)."""

    def todo():
        elementos, token = [], None
        while True:
            pagina = fn(**parametros, **({"NextToken": token} if token else {}))
            elementos.extend(pagina.get(clave, []))
            token = pagina.get("NextToken")
            if not token:
                return elementos

    return llamar(accion, todo)


def comprobar(problemas: list[str], detalle: str) -> str:
    if problemas:
        raise comun.Falla("; ".join(problemas))
    return detalle


def sin_comodin(arn: str | None) -> str:
    """El ARN de un log group que devuelve DescribeLogGroups termina en «:*»; el de AccessLogSettings, no."""
    return (arn or "").removesuffix(":*")


# ---------------------------------------------------------------------------------------------------------------------
# Estado compartido
# ---------------------------------------------------------------------------------------------------------------------


@dataclass
class Contexto:
    sesion: object = None
    clientes: dict = field(default_factory=dict)
    url: str = ""  # api_base_url
    cloud_map: dict = field(default_factory=dict)  # get-service del servicio api
    api: dict = field(default_factory=dict)  # get-apis de campus-locator-dev-api
    etapa: dict = field(default_factory=dict)  # get-stage $default
    api_lista: str | None = None  # None, "lista" o el error de poner api en 1
    inicio_c1b: dt.datetime | None = None
    request_id: str | None = None  # apigw-requestid de C1b

    def cliente(self, servicio: str):
        if servicio not in self.clientes:
            self.clientes[servicio] = self.sesion.client(servicio, region_name=comun.REGION)
        return self.clientes[servicio]


# ---------------------------------------------------------------------------------------------------------------------
# Precondiciones
# ---------------------------------------------------------------------------------------------------------------------


def p3_credenciales(ctx: Contexto) -> str:
    ctx.sesion = comun.sesion_aws()
    return f"{comun.comprobar_cuenta(ctx.sesion)} (cuenta {comun.CUENTA})"


def servicio_cloud_map(ctx: Contexto, nombre: str, *, en_precondicion: bool) -> dict | None:
    """get-service de <nombre>.campus-locator.local; None si el espacio o el servicio no existen."""
    sd = ctx.cliente("servicediscovery")
    envolver = llamar_precondicion if en_precondicion else llamar
    espacios = envolver(
        "listar espacios de nombres (servicediscovery:ListNamespaces)",
        lambda: [
            n
            for p in sd.get_paginator("list_namespaces").paginate(
                Filters=[{"Name": "TYPE", "Values": ["DNS_PRIVATE"], "Condition": "EQ"}]
            )
            for n in p.get("Namespaces", [])
        ],
    )
    propios = [n for n in espacios if n.get("Name") == NAMESPACE]
    if len(propios) != 1:
        return None
    servicios = envolver(
        "listar servicios de Cloud Map (servicediscovery:ListServices)",
        lambda: [
            s
            for p in sd.get_paginator("list_services").paginate(
                Filters=[{"Name": "NAMESPACE_ID", "Values": [propios[0]["Id"]], "Condition": "EQ"}]
            )
            for s in p.get("Services", [])
        ],
    )
    elegido = next((s for s in servicios if s.get("Name") == nombre), None)
    if elegido is None:
        return None
    return envolver(
        f"describir {nombre}.{NAMESPACE} (servicediscovery:GetService)", lambda: sd.get_service(Id=elegido["Id"])
    )["Service"]


def describir_servicio(ctx: Contexto, *, en_precondicion: bool = False) -> dict | None:
    ecs = ctx.cliente("ecs")
    envolver = llamar_precondicion if en_precondicion else llamar
    respuesta = envolver(
        f"describir el servicio {SERVICIO} (ecs:DescribeServices)",
        lambda: ecs.describe_services(cluster=CLUSTER, services=[SERVICIO]),
        "ClusterNotFoundException",
    )
    activos = [s for s in (respuesta or {}).get("services", []) if s.get("status") == "ACTIVE"]
    return activos[0] if activos else None


def p1_computo(ctx: Contexto) -> str:
    servicio = servicio_cloud_map(ctx, SERVICIO, en_precondicion=True)
    if servicio is None:
        raise comun.Bloqueo(f"INF-1.3 no está aplicado: no existe el servicio de Cloud Map {SERVICIO}.{NAMESPACE}")
    tipos = {r.get("Type") for r in (servicio.get("DnsConfig") or {}).get("DnsRecords", [])}
    if "SRV" not in tipos:
        raise comun.Bloqueo(f"{SERVICIO}.{NAMESPACE} no tiene registro SRV ({sorted(tipos)})")
    if describir_servicio(ctx, en_precondicion=True) is None:
        raise comun.Bloqueo(f"INF-1.3 no está aplicado: no existe el servicio ECS {SERVICIO} en {CLUSTER}")
    ctx.cloud_map = servicio
    return f"{SERVICIO}.{NAMESPACE} con SRV; servicio ECS {SERVICIO} ACTIVE"


def p2_salida(ctx: Contexto) -> str:
    salidas = comun.terraform_outputs("envs/dev")
    url = salidas.get("api_base_url")
    if url is None:
        raise comun.Bloqueo("INF-1.4 no está aplicado en envs/dev: falta el output api_base_url")
    if not isinstance(url, str) or not PATRON_URL.match(url):
        raise comun.Bloqueo(
            f"api_base_url = {url!r}: no tiene la forma https://<id>.execute-api.us-east-1.amazonaws.com"
        )
    ctx.url = url
    return f"api_base_url = {url}"


# ---------------------------------------------------------------------------------------------------------------------
# C1a: API, rutas, integración y VPC Link
# ---------------------------------------------------------------------------------------------------------------------


def ids_por_nombre(ctx: Contexto) -> tuple[list[str], str | None]:
    ec2 = ctx.cliente("ec2")
    subredes = llamar(
        "buscar las subredes públicas (ec2:DescribeSubnets)",
        lambda: ec2.describe_subnets(Filters=[{"Name": "tag:Name", "Values": SUBREDES_PUBLICAS}]),
    )["Subnets"]
    grupos = llamar(
        f"buscar el grupo {GRUPO_VPC_LINK} (ec2:DescribeSecurityGroups)",
        lambda: ec2.describe_security_groups(Filters=[{"Name": "group-name", "Values": [GRUPO_VPC_LINK]}]),
    )["SecurityGroups"]
    return sorted(s["SubnetId"] for s in subredes), (grupos[0]["GroupId"] if len(grupos) == 1 else None)


def c1a_api(ctx: Contexto) -> str:
    gw = ctx.cliente("apigatewayv2")
    apis = [
        a for a in paginar_token(gw.get_apis, "Items", "listar APIs (apigateway:GET)") if a.get("Name") == NOMBRE_API
    ]
    if len(apis) != 1:
        raise comun.Falla(f"{len(apis)} APIs con nombre {NOMBRE_API}; debe haber una")
    ctx.api = api = apis[0]
    problemas = []
    if api.get("ProtocolType") != "HTTP":
        problemas.append(f"ProtocolType {api.get('ProtocolType')}")
    if api.get("ApiEndpoint") != ctx.url:
        problemas.append("ApiEndpoint distinto de api_base_url")

    rutas = paginar_token(gw.get_routes, "Items", "listar rutas (apigateway:GET)", ApiId=api["ApiId"])
    claves = sorted(r.get("RouteKey") for r in rutas)
    if claves != sorted(THROTTLING):
        problemas.append(f"rutas {claves}; se esperan {sorted(THROTTLING)}")
    destinos = {r.get("Target") for r in rutas}
    integraciones = paginar_token(
        gw.get_integrations, "Items", "listar integraciones (apigateway:GET)", ApiId=api["ApiId"]
    )
    if len(destinos) != 1 or len(integraciones) != 1:
        problemas.append(f"{len(destinos)} destinos de ruta y {len(integraciones)} integraciones; se espera una")
        return comprobar(problemas, "")
    integ = integraciones[0]
    if destinos != {f"integrations/{integ['IntegrationId']}"}:
        problemas.append(f"las rutas apuntan a {destinos}, no a la integración {integ['IntegrationId']}")
    if integ.get("IntegrationType") != "HTTP_PROXY" or integ.get("ConnectionType") != "VPC_LINK":
        problemas.append(f"integración {integ.get('IntegrationType')}/{integ.get('ConnectionType')}")
    if integ.get("IntegrationUri") != ctx.cloud_map.get("Arn"):
        problemas.append("IntegrationUri no es el ARN del servicio de Cloud Map api")

    enlaces = paginar_token(gw.get_vpc_links, "Items", "listar VPC Links (apigateway:GET)")
    enlace = next((e for e in enlaces if e.get("VpcLinkId") == integ.get("ConnectionId")), None)
    if enlace is None:
        problemas.append("la integración no usa un VPC Link existente")
        return comprobar(problemas, "")
    subredes, grupo = ids_por_nombre(ctx)
    if enlace.get("Name") != NOMBRE_VPC_LINK:
        problemas.append(f"VPC Link {enlace.get('Name')!r}, no {NOMBRE_VPC_LINK}")
    if enlace.get("VpcLinkStatus") != "AVAILABLE":
        problemas.append(f"VPC Link en {enlace.get('VpcLinkStatus')}")
    if len(subredes) != 2 or sorted(enlace.get("SubnetIds", [])) != subredes:
        problemas.append("las subredes del VPC Link no son publica-a y publica-b")
    if grupo is None or enlace.get("SecurityGroupIds") != [grupo]:
        problemas.append(f"el grupo del VPC Link no es {GRUPO_VPC_LINK}")
    return comprobar(
        problemas,
        f"{NOMBRE_API}: {RUTA_GENERAL} y {RUTA_LOGIN} → HTTP_PROXY por {NOMBRE_VPC_LINK} (AVAILABLE, 2 subredes "
        "públicas) hacia Cloud Map api",
    )


# ---------------------------------------------------------------------------------------------------------------------
# C1b: api en 1 y GET /v1/health desde fuera de AWS
# ---------------------------------------------------------------------------------------------------------------------


def poner_api_en_uno(v, ctx: Contexto) -> None:
    """Sube api a 1 si estaba en 0 (y registra devolverlo a 0), espera services-stable, una tarea HEALTHY y que Cloud
    Map la devuelva como sana."""
    if ctx.api_lista == "lista":
        return
    ecs = ctx.cliente("ecs")
    ecr = ctx.cliente("ecr")
    imagen = llamar(
        f"buscar {REPO_BACKEND}:{ETIQUETA_PRUEBA} (ecr:DescribeImages)",
        lambda: ecr.describe_images(repositoryName=REPO_BACKEND, imageIds=[{"imageTag": ETIQUETA_PRUEBA}]),
        "ImageNotFoundException",
        "RepositoryNotFoundException",
    )
    servicio = describir_servicio(ctx)
    if servicio is None:
        raise comun.Falla(f"no existe el servicio {SERVICIO} en {CLUSTER}")
    if servicio.get("desiredCount", 0) == 0:
        if not imagen or not imagen.get("imageDetails"):
            raise comun.Falla(
                f"falta la imagen de prueba {REPO_BACKEND}:{ETIQUETA_PRUEBA}: publicarla (pruebas/imagen-prueba/README.md)"
            )
        comun.avisar(f"subiendo {SERVICIO} a 1 réplica (al terminar vuelve a 0)…")
        v.al_limpiar(
            f"devolver el servicio {SERVICIO} a 0 réplicas",
            lambda: llamar(
                f"devolver {SERVICIO} a 0 (ecs:UpdateService)",
                lambda: ecs.update_service(cluster=CLUSTER, service=SERVICIO, desiredCount=0),
            ),
        )
        llamar(
            f"subir {SERVICIO} a 1 (ecs:UpdateService)",
            lambda: ecs.update_service(cluster=CLUSTER, service=SERVICIO, desiredCount=1),
        )
    comun.avisar(f"esperando a que {SERVICIO} esté estable (hasta {ESPERA_ESTABLE_S // 60} min)…")
    # WaiterError hereda de BotoCoreError: se captura dentro del with para que cuente como Falla (código 1), no como
    # error de configuración (código 3).
    estable = True
    with comun.errores_aws(f"esperar a {SERVICIO} (ecs:DescribeServices)"):
        try:
            ecs.get_waiter("services_stable").wait(
                cluster=CLUSTER,
                services=[SERVICIO],
                WaiterConfig={"Delay": 15, "MaxAttempts": ESPERA_ESTABLE_S // 15},
            )
        except WaiterError:
            estable = False
    if not estable:
        eventos = "; ".join(e.get("message", "") for e in (describir_servicio(ctx) or {}).get("events", [])[:3])
        raise comun.Falla(f"{SERVICIO} no quedó estable en {ESPERA_ESTABLE_S // 60} min: {comun.resumir(eventos, 400)}")

    limite = time.monotonic() + ESPERA_SANA_S
    while True:
        arns = paginar(
            ecs,
            "list_tasks",
            "taskArns",
            "listar tareas (ecs:ListTasks)",
            cluster=CLUSTER,
            serviceName=SERVICIO,
            desiredStatus="RUNNING",
        )
        tareas = (
            llamar(
                "describir tareas (ecs:DescribeTasks)", lambda a=arns: ecs.describe_tasks(cluster=CLUSTER, tasks=a)
            ).get("tasks", [])
            if arns
            else []
        )
        if any(t.get("lastStatus") == "RUNNING" and t.get("healthStatus") == "HEALTHY" for t in tareas):
            break
        if time.monotonic() > limite:
            vistos = [(t.get("lastStatus"), t.get("healthStatus")) for t in tareas]
            raise comun.Falla(f"{SERVICIO} sin tarea HEALTHY en {ESPERA_SANA_S} s (tareas: {vistos})")
        time.sleep(10)

    sd = ctx.cliente("servicediscovery")
    limite = time.monotonic() + ESPERA_CLOUD_MAP_S
    while True:
        instancias = llamar(
            "descubrir api (servicediscovery:DiscoverInstances)",
            lambda: sd.discover_instances(NamespaceName=NAMESPACE, ServiceName=SERVICIO, HealthStatus="HEALTHY"),
        ).get("Instances", [])
        if instancias:
            break
        if time.monotonic() > limite:
            raise comun.Falla(f"Cloud Map no devuelve ninguna instancia sana de {SERVICIO} en {ESPERA_CLOUD_MAP_S} s")
        time.sleep(10)
    ctx.api_lista = "lista"


def c1b_health(v, ctx: Contexto) -> str:
    poner_api_en_uno(v, ctx)
    ctx.inicio_c1b = comun.ahora_utc()
    comun.avisar(f"GET {ctx.url}/v1/health (reintentos hasta {ESPERA_HEALTH_S} s)…")
    limite = time.monotonic() + ESPERA_HEALTH_S
    ultimo = ""
    with httpx.Client(timeout=10, verify=True) as http:
        while True:
            try:
                r = http.get(f"{ctx.url}/v1/health")
                if r.status_code == 200:
                    ctx.request_id = r.headers.get("apigw-requestid")
                    if not ctx.request_id:
                        raise comun.Falla("200 sin cabecera apigw-requestid")
                    return f"200 por HTTPS (TLS verificado), apigw-requestid {ctx.request_id}"
                ultimo = f"HTTP {r.status_code}"
            except httpx.HTTPError as exc:
                ultimo = type(exc).__name__
            if time.monotonic() > limite:
                raise comun.Falla(f"GET /v1/health no dio 200 en {ESPERA_HEALTH_S} s (último: {ultimo})")
            time.sleep(5)


# ---------------------------------------------------------------------------------------------------------------------
# C2: throttling
# ---------------------------------------------------------------------------------------------------------------------


def leer_etapa(ctx: Contexto) -> dict:
    if not ctx.etapa:
        if not ctx.api:
            c1a_api(ctx)
        gw = ctx.cliente("apigatewayv2")
        ctx.etapa = (
            llamar(
                "leer la etapa $default (apigateway:GET)",
                lambda: gw.get_stage(ApiId=ctx.api["ApiId"], StageName="$default"),
                "NotFoundException",
            )
            or {}
        )
        if not ctx.etapa:
            raise comun.Falla("la API no tiene etapa $default")
    return ctx.etapa


def c2a_etapa(ctx: Contexto) -> str:
    etapa = leer_etapa(ctx)
    problemas = []
    if etapa.get("AutoDeploy") is not True:
        problemas.append("AutoDeploy no es true")
    por_ruta = etapa.get("RouteSettings") or {}
    defecto = etapa.get("DefaultRouteSettings") or {}
    for ruta, (rate, burst) in THROTTLING.items():
        ajustes = por_ruta.get(ruta) or (defecto if ruta == RUTA_GENERAL else {})
        visto = (ajustes.get("ThrottlingRateLimit"), ajustes.get("ThrottlingBurstLimit"))
        if visto != (rate, burst):
            problemas.append(f"{ruta}: throttling {visto}, se espera ({rate}, {burst})")
    return comprobar(problemas, f"$default con AutoDeploy; {RUTA_GENERAL} 20/40, {RUTA_LOGIN} 2/5")


def rafaga(metodo: str, url: str, total: int, por_s: float, **kwargs) -> Counter:
    """Envía `total` peticiones a ritmo constante (`por_s`), en paralelo para que la latencia no frene el ritmo, y
    cuenta los códigos (o el nombre del error de red)."""

    def una(http: httpx.Client) -> str:
        try:
            return str(http.request(metodo, url, **kwargs).status_code)
        except httpx.HTTPError as exc:
            return type(exc).__name__

    with httpx.Client(timeout=15, verify=True) as http, ThreadPoolExecutor(max_workers=20) as hilos:
        inicio = time.monotonic()
        futuros = []
        for i in range(total):
            espera = inicio + i / por_s - time.monotonic()
            if espera > 0:
                time.sleep(espera)
            futuros.append(hilos.submit(una, http))
        return Counter(f.result() for f in futuros)


def c2b_429(ctx: Contexto) -> str:
    comun.avisar(f"{LOGIN['total']} POST /v1/auth/login a {LOGIN['por_s']} req/s…")
    login = rafaga("POST", f"{ctx.url}/v1/auth/login", LOGIN["total"], LOGIN["por_s"], json={})
    time.sleep(PAUSA_C2B_S)
    comun.avisar(f"{HEALTH['total']} GET /v1/health a {HEALTH['por_s']} req/s…")
    salud = rafaga("GET", f"{ctx.url}/v1/health", HEALTH["total"], HEALTH["por_s"])
    problemas = []
    minimo = int(LOGIN["total"] * LOGIN["minimo_429"])
    if login["429"] < minimo:
        problemas.append(f"login: {login['429']} de {LOGIN['total']} con 429 (mínimo {minimo}); códigos {dict(login)}")
    if salud["200"] != HEALTH["total"]:
        problemas.append(f"/v1/health: códigos {dict(salud)}; se esperan {HEALTH['total']} × 200")
    return comprobar(problemas, f"login {dict(login)}; /v1/health {dict(salud)}")


# ---------------------------------------------------------------------------------------------------------------------
# C3: access logs
# ---------------------------------------------------------------------------------------------------------------------


def c3a_destino(ctx: Contexto) -> str:
    ajustes = leer_etapa(ctx).get("AccessLogSettings") or {}
    logs = ctx.cliente("logs")
    grupos = [
        g
        for g in paginar(
            logs,
            "describe_log_groups",
            "logGroups",
            "describir log groups (logs:DescribeLogGroups)",
            logGroupNamePrefix=LOG_APIGW,
        )
        if g.get("logGroupName") == LOG_APIGW
    ]
    if not grupos:
        raise comun.Falla(f"no existe el log group {LOG_APIGW}")
    problemas = []
    if sin_comodin(ajustes.get("DestinationArn")) != sin_comodin(grupos[0].get("arn")):
        problemas.append(f"DestinationArn no es el ARN de {LOG_APIGW}")
    if grupos[0].get("retentionInDays") != 14:
        problemas.append(f"retención {grupos[0].get('retentionInDays')} días, no 14")
    try:
        formato = json.loads(ajustes.get("Format") or "")
    except ValueError:
        formato = None
    if not isinstance(formato, dict) or set(formato) != CAMPOS_LOG:
        problemas.append(
            f"el formato no es el JSON de §5.10 (campos {sorted(formato) if isinstance(formato, dict) else '?'})"
        )
    elif formato.get("requestId") != "$context.requestId":
        problemas.append("requestId no es $context.requestId")
    return comprobar(problemas, f"access logs → {LOG_APIGW} (14 días), formato JSON con los {len(CAMPOS_LOG)} campos")


def c3b_evento(v, ctx: Contexto) -> str:
    if not ctx.request_id:  # C1b no pasó o se excluyó con --solo: la petición se hace aquí
        c1b_health(v, ctx)
    logs = ctx.cliente("logs")
    desde = int((ctx.inicio_c1b - dt.timedelta(seconds=30)).timestamp() * 1000)
    patron = f'{{ $.requestId = "{ctx.request_id}" }}'
    comun.avisar(f"buscando el access log de {ctx.request_id} (hasta {ESPERA_LOG_S // 60} min)…")
    limite = time.monotonic() + ESPERA_LOG_S
    while True:
        eventos = paginar(
            logs,
            "filter_log_events",
            "events",
            f"buscar en {LOG_APIGW} (logs:FilterLogEvents)",
            logGroupName=LOG_APIGW,
            startTime=desde,
            filterPattern=patron,
        )
        if eventos:
            break
        if time.monotonic() > limite:
            raise comun.Falla(f"no apareció en {ESPERA_LOG_S} s ningún evento con requestId {ctx.request_id}")
        time.sleep(15)
    try:
        linea = json.loads(eventos[0].get("message", ""))
    except ValueError as exc:
        raise comun.Falla("el evento no es JSON") from exc
    problemas = []
    faltan = CAMPOS_LOG - set(linea)
    if faltan:
        problemas.append(f"faltan los campos {sorted(faltan)}")
    if linea.get("routeKey") != RUTA_GENERAL:
        problemas.append(f"routeKey = {linea.get('routeKey')!r}")
    if str(linea.get("status")) != "200":
        problemas.append(f"status = {linea.get('status')!r}")
    return comprobar(problemas, f"evento JSON de {ctx.request_id}: routeKey {RUTA_GENERAL}, status 200, 10 campos")


# ---------------------------------------------------------------------------------------------------------------------
# Programa
# ---------------------------------------------------------------------------------------------------------------------


def cuerpo(v) -> None:
    ctx = Contexto()
    if not v.precondicion("P3", lambda: p3_credenciales(ctx)):
        v.precondicion_no_evaluada("P1", "P3 no se cumple (credenciales)")
        v.precondicion_no_evaluada("P2", "P3 no se cumple (credenciales)")
        return
    if not v.precondicion("P1", lambda: p1_computo(ctx)):
        v.precondicion_no_evaluada("P2", "P1 no se cumple")
        return
    if not v.precondicion("P2", lambda: p2_salida(ctx)):
        return

    v.comprobacion("C1a", lambda: c1a_api(ctx))
    v.comprobacion("C1b", lambda: c1b_health(v, ctx))
    v.comprobacion("C2a", lambda: c2a_etapa(ctx))
    v.comprobacion("C2b", lambda: (poner_api_en_uno(v, ctx), c2b_429(ctx))[1])
    v.comprobacion("C3a", lambda: c3a_destino(ctx))
    v.comprobacion("C3b", lambda: c3b_evento(v, ctx))


def main() -> int:
    v = comun.Validador(
        lote="INF-1.4",
        validacion="validation-1-4",
        descripcion="INF-1.4 Borde HTTPS: HTTP API, VPC Link y Cloud Map, /v1/health desde fuera de AWS, throttling "
        "y access logs",
        comprobaciones=["C1a", "C1b", "C2a", "C2b", "C3a", "C3b"],
        grupos={"C1": ["C1a", "C1b"], "C2": ["C2a", "C2b"], "C3": ["C3a", "C3b"]},
    )
    return v.correr(cuerpo)


if __name__ == "__main__":
    sys.exit(main())
