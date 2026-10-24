"""Validador del lote INF-1.1 — Red y grupos de seguridad.

Documento: docs/validation/validation-1-1.md. Contrato común: docs/ARCHITECTURE.md §5.11.

Solo lee la API de EC2 y los outputs de envs/dev, y ejecuta un `terraform plan`, que toma y libera el bloqueo del
estado. No crea datos de prueba ni modifica recursos.

Uso (desde INFRASTRUCTURA_TERRAFORM/project):
    uv run --group ops python src/ops/validate11.py --entorno dev [--informe RUTA] [--solo C2,C3a] [--sin-limpieza]
"""

from __future__ import annotations

import os
import re
import signal
import subprocess
import sys
import tempfile
from typing import Any

import comun

LOTE = "INF-1.1"
VALIDACION = "validation-1-1"
PREFIJO = "campus-locator-dev"
DIR_DEV = "envs/dev"
BUCKET_ESTADO = f"campus-locator-tfstate-{comun.CUENTA}"
CLAVE_ESTADO = "dev/terraform.tfstate"
TIEMPO_PLAN = 600  # s
TIEMPO_SIGINT = 120  # s que se espera a que terraform suelte el bloqueo tras SIGINT

# §3.2 y §5.1
NOMBRE_VPC = f"{PREFIJO}-vpc"
CIDR_VPC = "10.20.0.0/16"
SUBREDES = {
    f"{PREFIJO}-publica-a": ("10.20.0.0/24", "us-east-1a"),
    f"{PREFIJO}-publica-b": ("10.20.1.0/24", "us-east-1b"),
    f"{PREFIJO}-privada-a": ("10.20.10.0/24", "us-east-1a"),
    f"{PREFIJO}-privada-b": ("10.20.11.0/24", "us-east-1b"),
}
PUBLICAS = (f"{PREFIJO}-publica-a", f"{PREFIJO}-publica-b")
PRIVADAS = (f"{PREFIJO}-privada-a", f"{PREFIJO}-privada-b")
SERVICIO_S3 = f"com.amazonaws.{comun.REGION}.s3"
ESTADOS_ENDPOINT_IGNORADOS = {"deleting", "deleted", "failed", "rejected", "expired"}
ETIQUETAS = {
    "Proyecto": "campus-locator",
    "Entorno": "dev",
    "GestionadoPor": "terraform",
    "Carpeta": "INFRASTRUCTURA_TERRAFORM",
}

# §5.7: (grupo, sentido, protocolo, puerto desde, puerto hasta, origen o destino)
GRUPOS = ("vpclink", "api", "worker", "embedding", "rds")
TODO_IPV4 = "cidr:0.0.0.0/0"
REGLAS_ESPERADAS = frozenset(
    {
        ("vpclink", "salida", "tcp", 8000, 8000, "grupo:api"),
        ("api", "entrada", "tcp", 8000, 8000, "grupo:vpclink"),
        ("api", "salida", "todo", None, None, TODO_IPV4),
        ("worker", "salida", "todo", None, None, TODO_IPV4),
        ("embedding", "entrada", "tcp", 8080, 8080, "grupo:api"),
        ("embedding", "entrada", "tcp", 8080, 8080, "grupo:worker"),
        ("embedding", "salida", "todo", None, None, TODO_IPV4),
        ("rds", "entrada", "tcp", 5432, 5432, "grupo:api"),
        ("rds", "entrada", "tcp", 5432, 5432, "grupo:worker"),
    }
)
PROTOCOLOS = {"-1": "todo", "6": "tcp", "17": "udp", "1": "icmp"}

COMPROBACIONES = ["C1", "C2a", "C2b", "C2c", "C2d", "C2e", "C3a", "C3b", "C4", "C5"]
GRUPOS_SOLO = {"C2": ["C2a", "C2b", "C2c", "C2d", "C2e"], "C3": ["C3a", "C3b"]}


# --- ayudas -------------------------------------------------------------------------------------------------------


def etiquetas(recurso: dict[str, Any]) -> dict[str, str]:
    return {t["Key"]: t["Value"] for t in recurso.get("Tags") or []}


def nombre(recurso: dict[str, Any]) -> str | None:
    return etiquetas(recurso).get("Name")


def lista(elementos: list[str], limite: int = 6) -> str:
    if len(elementos) <= limite:
        return "; ".join(elementos)
    return "; ".join(elementos[:limite]) + f"; … y {len(elementos) - limite} más"


def terraform_plan(argumentos: list[str]) -> comun.Resultado:
    """`terraform plan` que suelta el bloqueo del estado aunque se interrumpa el validador.

    - terraform corre en su propia sesión (POSIX) o grupo de procesos (Windows): el Ctrl+C de la terminal solo llega a
      Python, que le reenvía SIGINT (CTRL_BREAK en Windows, que Go recibe como interrupción) y espera a que termine.
      `ejecutar` lo mataría al instante y dejaría el `.tflock`.
    - Su salida va a archivos temporales, no a tuberías: si Python muere igual (SIGKILL), terraform no recibe SIGPIPE
      y termina el `plan` por su cuenta, liberando el bloqueo.
    """
    comando = ["terraform", *argumentos]
    aislar: dict[str, Any] = (
        {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
    )
    with tempfile.TemporaryFile() as salida, tempfile.TemporaryFile() as error:
        try:
            proceso = subprocess.Popen(
                comando,
                cwd=comun.PROYECTO,
                env=comun._entorno_proceso(),
                stdin=subprocess.DEVNULL,
                stdout=salida,
                stderr=error,
                **aislar,
            )
        except FileNotFoundError as exc:
            raise comun.ErrorConfiguracion("no se encontró `terraform` en el PATH") from exc
        try:
            proceso.wait(timeout=TIEMPO_PLAN)
        except KeyboardInterrupt:
            _detener(proceso)
            raise
        except subprocess.TimeoutExpired as exc:
            _detener(proceso)
            raise comun.Falla(f"terraform plan no terminó en {TIEMPO_PLAN} s") from exc
        return comun.Resultado(proceso.returncode, _leer(salida), _leer(error))


def _leer(archivo: Any) -> str:
    archivo.seek(0)
    return archivo.read().decode("utf-8", errors="replace")


def _detener(proceso: subprocess.Popen[bytes]) -> None:
    """Interrumpe terraform y espera a que suelte el bloqueo; mientras, ignora más Ctrl+C, SIGTERM y SIGHUP."""
    if proceso.poll() is not None:
        return
    comun.avisar("Deteniendo terraform con una interrupción para que libere el bloqueo del estado (hasta 120 s)…")
    senales = [signal.SIGINT, signal.SIGTERM] + ([signal.SIGHUP] if hasattr(signal, "SIGHUP") else [])
    anteriores = {s: signal.signal(s, signal.SIG_IGN) for s in senales}
    try:
        proceso.send_signal(signal.CTRL_BREAK_EVENT if os.name == "nt" else signal.SIGINT)
        try:
            proceso.wait(timeout=TIEMPO_SIGINT)
        except subprocess.TimeoutExpired:
            comun.avisar(
                f"terraform no terminó en {TIEMPO_SIGINT} s: se mata; revisa si quedó dev/terraform.tfstate.tflock"
            )
            proceso.kill()
            proceso.wait()
    finally:
        for senal, anterior in anteriores.items():
            signal.signal(senal, anterior)


def paginar(cliente: Any, operacion: str, clave: str, **argumentos: Any) -> list[dict[str, Any]]:
    with comun.errores_aws(f"ec2 {operacion}"):
        paginas = cliente.get_paginator(operacion).paginate(**argumentos)
        return [elemento for pagina in paginas for elemento in pagina.get(clave, [])]


class Red:
    """Consultas a EC2, guardadas en cuanto salen bien (un error se vuelve a intentar en la siguiente comprobación)."""

    def __init__(self, sesion: Any) -> None:
        self.ec2 = sesion.client("ec2")
        self._cache: dict[str, Any] = {}

    def _una_vez(self, clave: str, funcion: Any) -> Any:
        if clave not in self._cache:
            self._cache[clave] = funcion()
        return self._cache[clave]

    def filtro_vpc(self) -> list[dict[str, Any]]:
        return [{"Name": "vpc-id", "Values": [self.vpc()["VpcId"]]}]

    def vpc(self) -> dict[str, Any]:
        def buscar() -> dict[str, Any]:
            vpcs = paginar(self.ec2, "describe_vpcs", "Vpcs", Filters=[{"Name": "tag:Name", "Values": [NOMBRE_VPC]}])
            if not vpcs:
                raise comun.Falla(f"no existe la VPC con Name = {NOMBRE_VPC}")
            if len(vpcs) > 1:
                ids = ", ".join(v["VpcId"] for v in vpcs)
                raise comun.Falla(
                    f"hay {len(vpcs)} VPC con Name = {NOMBRE_VPC} ({ids}); ¿restos de otro intento (R11)?"
                )
            return vpcs[0]

        return self._una_vez("vpc", buscar)

    def subredes(self) -> list[dict[str, Any]]:
        return self._una_vez(
            "subredes", lambda: paginar(self.ec2, "describe_subnets", "Subnets", Filters=self.filtro_vpc())
        )

    def subred(self, nombre_subred: str) -> dict[str, Any]:
        halladas = [s for s in self.subredes() if nombre(s) == nombre_subred]
        if len(halladas) != 1:
            raise comun.Falla(f"se esperaba una subred {nombre_subred} y hay {len(halladas)}")
        return halladas[0]

    def tablas(self) -> list[dict[str, Any]]:
        return self._una_vez(
            "tablas", lambda: paginar(self.ec2, "describe_route_tables", "RouteTables", Filters=self.filtro_vpc())
        )

    def tabla_de(self, nombre_subred: str) -> dict[str, Any]:
        """Tabla asociada a la subred o, si no tiene, la principal de la VPC."""
        id_subred = self.subred(nombre_subred)["SubnetId"]
        asociadas = [
            t for t in self.tablas() if any(a.get("SubnetId") == id_subred for a in t.get("Associations") or [])
        ]
        if asociadas:
            return asociadas[0]
        principales = [t for t in self.tablas() if any(a.get("Main") for a in t.get("Associations") or [])]
        if not principales:
            raise comun.Falla(f"{nombre_subred} no tiene tabla asociada y la VPC no tiene tabla principal")
        return principales[0]

    def tabla_publica(self) -> dict[str, Any]:
        a, b = (self.tabla_de(n) for n in PUBLICAS)
        if a["RouteTableId"] != b["RouteTableId"]:
            raise comun.Falla(f"las subredes públicas usan tablas distintas ({a['RouteTableId']}, {b['RouteTableId']})")
        return a

    def igws(self) -> list[dict[str, Any]]:
        return self._una_vez(
            "igws",
            lambda: paginar(
                self.ec2,
                "describe_internet_gateways",
                "InternetGateways",
                Filters=[{"Name": "attachment.vpc-id", "Values": [self.vpc()["VpcId"]]}],
            ),
        )

    def endpoints_s3(self) -> list[dict[str, Any]]:
        """Endpoints de S3 de la VPC, sin los borrados o fallidos (EC2 los sigue listando un tiempo)."""

        def buscar() -> list[dict[str, Any]]:
            endpoints = paginar(
                self.ec2,
                "describe_vpc_endpoints",
                "VpcEndpoints",
                Filters=[*self.filtro_vpc(), {"Name": "service-name", "Values": [SERVICIO_S3]}],
            )
            return [e for e in endpoints if str(e.get("State", "")).lower() not in ESTADOS_ENDPOINT_IGNORADOS]

        return self._una_vez("endpoints_s3", buscar)

    def grupos_vpc(self) -> list[dict[str, Any]]:
        return self._una_vez(
            "grupos_vpc",
            lambda: paginar(self.ec2, "describe_security_groups", "SecurityGroups", Filters=self.filtro_vpc()),
        )

    def grupos(self) -> dict[str, dict[str, Any]]:
        """Los cinco grupos de §5.7 por nombre corto. Falla si falta alguno."""
        por_nombre = {g["GroupName"]: g for g in self.grupos_vpc()}
        faltan = [f"{PREFIJO}-{c}" for c in GRUPOS if f"{PREFIJO}-{c}" not in por_nombre]
        if faltan:
            raise comun.Falla(f"faltan grupos de seguridad en la VPC: {', '.join(faltan)}")
        return {c: por_nombre[f"{PREFIJO}-{c}"] for c in GRUPOS}

    def grupo_default(self) -> dict[str, Any]:
        defaults = [g for g in self.grupos_vpc() if g["GroupName"] == "default"]
        if len(defaults) != 1:
            raise comun.Falla(f"se esperaba un grupo default en la VPC y hay {len(defaults)}")
        return defaults[0]

    def reglas(self) -> list[dict[str, Any]]:
        """Reglas de todos los grupos de la VPC."""

        def buscar() -> list[dict[str, Any]]:
            ids = [g["GroupId"] for g in self.grupos_vpc()]
            reglas: list[dict[str, Any]] = []
            for inicio in range(0, len(ids), 100):
                reglas += paginar(
                    self.ec2,
                    "describe_security_group_rules",
                    "SecurityGroupRules",
                    Filters=[{"Name": "group-id", "Values": ids[inicio : inicio + 100]}],
                )
            return reglas

        return self._una_vez("reglas", buscar)

    def nombres_cortos(self) -> dict[str, str]:
        """ID de grupo → nombre corto (vpclink, api…) o el nombre del grupo si no es de §5.7."""
        cortos = {}
        for g in self.grupos_vpc():
            nombre_grupo = g["GroupName"]
            corto = nombre_grupo.removeprefix(f"{PREFIJO}-")
            cortos[g["GroupId"]] = corto if corto in GRUPOS else nombre_grupo
        return cortos


def normalizar(regla: dict[str, Any], cortos: dict[str, str]) -> tuple[Any, ...]:
    grupo = cortos.get(regla["GroupId"], regla["GroupId"])
    sentido = "salida" if regla.get("IsEgress") else "entrada"
    protocolo = PROTOCOLOS.get(str(regla.get("IpProtocol")), str(regla.get("IpProtocol")))
    desde = hasta = None
    if protocolo != "todo":
        desde, hasta = regla.get("FromPort"), regla.get("ToPort")
    if regla.get("ReferencedGroupInfo", {}).get("GroupId"):
        referido = regla["ReferencedGroupInfo"]["GroupId"]
        otro = f"grupo:{cortos.get(referido, referido)}"
    elif regla.get("CidrIpv4"):
        otro = f"cidr:{regla['CidrIpv4']}"
    elif regla.get("CidrIpv6"):
        otro = f"cidr6:{regla['CidrIpv6']}"
    elif regla.get("PrefixListId"):
        otro = f"lista:{regla['PrefixListId']}"
    else:
        otro = "?"
    return (grupo, sentido, protocolo, desde, hasta, otro)


def describir(regla: tuple[Any, ...]) -> str:
    grupo, sentido, protocolo, desde, hasta, otro = regla
    puertos = "" if desde is None else (f"/{desde}" if desde == hasta else f"/{desde}-{hasta}")
    flecha = "←" if sentido == "entrada" else "→"
    return f"{grupo} {sentido} {protocolo}{puertos} {flecha} {otro.split(':', 1)[-1]}"


# --- cuerpo -------------------------------------------------------------------------------------------------------


def cuerpo(v: comun.Validador) -> None:
    contexto: dict[str, Any] = {}

    def p2() -> str:
        sesion = comun.sesion_aws()
        arn = comun.comprobar_cuenta(sesion)
        contexto["sesion"] = sesion
        return f"cuenta {comun.CUENTA} ({arn})"

    def p1() -> str:
        r = comun.ejecutar(["terraform", f"-chdir={DIR_DEV}", "init", "-input=false", "-lockfile=readonly"])
        if r.codigo != 0:
            if comun.PATRON_CREDENCIALES_TERRAFORM.search(r.texto):
                raise comun.ErrorConfiguracion(f"terraform init sin credenciales válidas: {comun.resumir(r.texto)}")
            if re.search(r"NoSuchBucket|bucket does not exist", r.texto, re.IGNORECASE):
                raise comun.Bloqueo(f"no existe el bucket de estado {BUCKET_ESTADO}: falta INF-0.1/INF-0.2")
            # Lock, versión de Terraform, módulos o red de la copia local: configuración (código 3), no otro lote.
            raise comun.ErrorConfiguracion(f"terraform -chdir={DIR_DEV} init falla: {comun.resumir(r.texto)}")
        s3 = contexto["sesion"].client("s3")
        try:
            s3.head_object(Bucket=BUCKET_ESTADO, Key=CLAVE_ESTADO)
        except Exception as exc:  # noqa: BLE001 — se traduce abajo
            if comun.codigo_error_aws(exc) in {"404", "NoSuchKey", "NotFound", "NoSuchBucket"}:
                raise comun.Bloqueo(
                    f"no existe s3://{BUCKET_ESTADO}/{CLAVE_ESTADO}: falta el primer apply de INF-0.2"
                ) from exc
            traducido = comun.error_aws(exc, "s3 head-object del estado de dev")
            if isinstance(traducido, comun.ErrorConfiguracion):
                raise traducido from exc
            raise comun.ErrorConfiguracion(str(traducido)) from exc  # red u otro fallo local: no es otro lote
        return f"envs/dev inicializado; s3://{BUCKET_ESTADO}/{CLAVE_ESTADO} existe"

    # Credenciales primero (código 3), luego el lote anterior (código 2).
    if not v.precondicion("P2", p2):
        v.precondicion_no_evaluada("P1", "P2 no pasó")
        return
    if not v.precondicion("P1", p1):
        return

    red = Red(contexto["sesion"])

    def c1() -> str:
        r = terraform_plan(
            [f"-chdir={DIR_DEV}", "plan", "-input=false", "-detailed-exitcode", "-lock-timeout=60s", "-no-color"]
        )
        if r.codigo == 0:
            return "plan sin cambios"
        if r.codigo == 2:
            resumen = re.search(r"Plan: \d+ to add, \d+ to change, \d+ to destroy", r.salida)
            if resumen:
                detalle = resumen.group(0)
            elif "Changes to Outputs" in r.salida:
                detalle = "solo cambian outputs"
            else:
                detalle = "hay cambios"
            raise comun.Falla(f"el plan no está vacío ({detalle}): ¿falta el apply de main o hay deriva?")
        if comun.PATRON_CREDENCIALES_TERRAFORM.search(r.texto):
            raise comun.ErrorConfiguracion(f"terraform plan sin credenciales válidas: {comun.resumir(r.texto)}")
        if "Error acquiring the state lock" in r.texto:
            raise comun.Falla("otro proceso retiene el bloqueo del estado de dev desde hace más de 60 s")
        raise comun.Falla(f"terraform plan terminó con {r.codigo}: {comun.resumir(r.error or r.salida)}")

    def c2a() -> str:
        vpc = red.vpc()
        problemas = []
        if vpc.get("CidrBlock") != CIDR_VPC:
            problemas.append(f"CidrBlock = {vpc.get('CidrBlock')} (se espera {CIDR_VPC})")
        for atributo, clave in (("enableDnsSupport", "EnableDnsSupport"), ("enableDnsHostnames", "EnableDnsHostnames")):
            with comun.errores_aws("ec2 describe-vpc-attribute"):
                valor = red.ec2.describe_vpc_attribute(VpcId=vpc["VpcId"], Attribute=atributo)[clave]["Value"]
            if valor is not True:
                problemas.append(f"{atributo} = {valor}")
        if problemas:
            raise comun.Falla(f"{vpc['VpcId']}: {lista(problemas)}")
        return f"{vpc['VpcId']} {CIDR_VPC}, enableDnsSupport y enableDnsHostnames en true"

    def c2b() -> str:
        subredes = red.subredes()
        problemas = []
        for nombre_subred, (cidr, zona) in SUBREDES.items():
            halladas = [s for s in subredes if nombre(s) == nombre_subred]
            if len(halladas) != 1:
                problemas.append(f"{nombre_subred}: hay {len(halladas)}")
                continue
            s = halladas[0]
            if s.get("CidrBlock") != cidr or s.get("AvailabilityZone") != zona:
                problemas.append(
                    f"{nombre_subred}: {s.get('CidrBlock')} en {s.get('AvailabilityZone')} (se espera {cidr} en {zona})"
                )
        sobran = [f"{nombre(s) or '(sin Name)'} {s['SubnetId']}" for s in subredes if nombre(s) not in SUBREDES]
        if sobran:
            problemas.append(f"subredes de más: {', '.join(sobran)}")
        if problemas:
            raise comun.Falla(lista(problemas))
        return "4 subredes con los CIDR y las zonas de §5.1"

    def c2c() -> str:
        igws = red.igws()
        if len(igws) != 1:
            raise comun.Falla(f"se esperaba un Internet Gateway en la VPC y hay {len(igws)}")
        igw = igws[0]["InternetGatewayId"]
        problemas = []
        publica = red.tabla_publica()
        hacia_igw = [
            r
            for r in publica.get("Routes") or []
            if r.get("DestinationCidrBlock") == "0.0.0.0/0" and r.get("GatewayId") == igw and r.get("State") == "active"
        ]
        if not hacia_igw:
            problemas.append(f"la tabla pública {publica['RouteTableId']} no tiene 0.0.0.0/0 → {igw} activa")
        tablas_privadas: dict[str, dict[str, Any]] = {}
        for nombre_subred in PRIVADAS:
            tabla = red.tabla_de(nombre_subred)
            tablas_privadas.setdefault(tabla["RouteTableId"], tabla)
        for tabla in tablas_privadas.values():
            no_locales = [
                r.get("DestinationCidrBlock") or r.get("DestinationPrefixListId") or r.get("DestinationIpv6CidrBlock")
                for r in tabla.get("Routes") or []
                if r.get("GatewayId") != "local"
            ]
            if no_locales:
                problemas.append(
                    f"la tabla de las privadas {tabla['RouteTableId']} tiene rutas además de local: "
                    f"{', '.join(map(str, no_locales))}"
                )
        nats = paginar(red.ec2, "describe_nat_gateways", "NatGateways", Filter=red.filtro_vpc())
        activos = [n["NatGatewayId"] for n in nats if n.get("State") in ("pending", "available")]
        if activos:
            problemas.append(f"hay NAT Gateway: {', '.join(activos)}")
        if problemas:
            raise comun.Falla(lista(problemas))
        return f"públicas → {publica['RouteTableId']} con 0.0.0.0/0 → {igw}; privadas solo con local; sin NAT"

    def c2d() -> str:
        endpoints = red.endpoints_s3()
        if len(endpoints) != 1:
            raise comun.Falla(f"se esperaba un endpoint de {SERVICIO_S3} y hay {len(endpoints)}")
        ep = endpoints[0]
        publica = red.tabla_publica()["RouteTableId"]
        problemas = []
        if ep.get("VpcEndpointType") != "Gateway":
            problemas.append(f"VpcEndpointType = {ep.get('VpcEndpointType')}")
        if str(ep.get("State", "")).lower() != "available":
            problemas.append(f"State = {ep.get('State')}")
        if sorted(ep.get("RouteTableIds") or []) != [publica]:
            problemas.append(f"RouteTableIds = {ep.get('RouteTableIds')} (se espera [{publica}])")
        if problemas:
            raise comun.Falla(f"{ep['VpcEndpointId']}: {lista(problemas)}")
        return f"{ep['VpcEndpointId']} Gateway, available, en la tabla pública"

    def c2e() -> str:
        recursos: list[tuple[str, dict[str, Any], str | None]] = [(f"VPC {red.vpc()['VpcId']}", red.vpc(), NOMBRE_VPC)]
        for nombre_subred in SUBREDES:
            s = red.subred(nombre_subred)
            recursos.append((f"subred {s['SubnetId']}", s, nombre_subred))
        for igw in red.igws():
            recursos.append((f"IGW {igw['InternetGatewayId']}", igw, f"{PREFIJO}-igw"))
        vistas = set()
        for nombres_subredes, esperado in ((PUBLICAS, f"{PREFIJO}-publica"), (PRIVADAS, f"{PREFIJO}-privada")):
            for nombre_subred in nombres_subredes:
                tabla = red.tabla_de(nombre_subred)
                principal = any(a.get("Main") for a in tabla.get("Associations") or [])
                if tabla["RouteTableId"] in vistas or principal:
                    continue  # la principal no la crea este lote
                vistas.add(tabla["RouteTableId"])
                recursos.append((f"tabla {tabla['RouteTableId']}", tabla, esperado))
        for ep in red.endpoints_s3():
            recursos.append((f"endpoint {ep['VpcEndpointId']}", ep, f"{PREFIJO}-s3"))
        grupos = red.grupos()
        for corto, g in grupos.items():
            recursos.append((f"grupo {g['GroupName']}", g, f"{PREFIJO}-{corto}"))
        default = red.grupo_default()
        recursos.append((f"grupo default {default['GroupId']}", default, f"{PREFIJO}-default"))
        ids_grupos = {g["GroupId"] for g in grupos.values()}
        reglas = [r for r in red.reglas() if r["GroupId"] in ids_grupos]
        for regla in reglas:
            recursos.append((f"regla {regla['SecurityGroupRuleId']}", regla, None))

        problemas = []
        for descripcion, recurso, nombre_esperado in recursos:
            actuales = etiquetas(recurso)
            malas = [k for k, valor in ETIQUETAS.items() if actuales.get(k) != valor]
            if malas:
                problemas.append(f"{descripcion}: falta o difiere {', '.join(malas)}")
            if nombre_esperado and actuales.get("Name") != nombre_esperado:
                problemas.append(f"{descripcion}: Name = {actuales.get('Name')} (se espera {nombre_esperado})")
        if problemas:
            raise comun.Falla(lista(problemas))
        return f"{len(recursos)} recursos con las cuatro etiquetas de §5.1 y su Name"

    def c3a() -> str:
        grupos = red.grupos()
        cortos = red.nombres_cortos()
        ids = {g["GroupId"] for g in grupos.values()}
        halladas = [normalizar(r, cortos) for r in red.reglas() if r["GroupId"] in ids]
        conjunto = set(halladas)
        faltan = sorted(REGLAS_ESPERADAS - conjunto, key=str)
        sobran = sorted(conjunto - REGLAS_ESPERADAS, key=str)
        problemas = [f"falta {describir(r)}" for r in faltan] + [f"sobra {describir(r)}" for r in sobran]
        if len(halladas) != len(conjunto):
            problemas.append("hay reglas repetidas")
        if problemas:
            raise comun.Falla(lista(problemas, limite=10))
        return f"5 grupos con exactamente las {len(REGLAS_ESPERADAS)} reglas de §5.7"

    def c3b() -> str:
        default = red.grupo_default()
        reglas = [normalizar(r, red.nombres_cortos()) for r in red.reglas() if r["GroupId"] == default["GroupId"]]
        if reglas:
            raise comun.Falla(
                f"el grupo default {default['GroupId']} tiene reglas: {lista([describir(r) for r in reglas])}"
            )
        return f"grupo default {default['GroupId']} sin reglas"

    def c4() -> str:
        cortos = red.nombres_cortos()
        abiertas = [
            f"{describir(normalizar(r, cortos))} ({r['SecurityGroupRuleId']})"
            for r in red.reglas()
            if not r.get("IsEgress") and (r.get("CidrIpv4") == "0.0.0.0/0" or r.get("CidrIpv6") == "::/0")
        ]
        if abiertas:
            raise comun.Falla(f"reglas entrantes abiertas a internet: {lista(abiertas)}")
        return f"{len(red.grupos_vpc())} grupos de la VPC sin entrada desde 0.0.0.0/0 ni ::/0"

    def c5() -> str:
        salidas = comun.terraform_outputs(DIR_DEV)
        publica_a = red.subred(PUBLICAS[0])["SubnetId"]
        api = red.grupos()["api"]["GroupId"]
        problemas = []
        if salidas.get("subredes_tareas") != [publica_a]:
            problemas.append(f"subredes_tareas = {salidas.get('subredes_tareas')} (se espera [{publica_a}])")
        if salidas.get("sg_migrate") != api:
            problemas.append(f"sg_migrate = {salidas.get('sg_migrate')} (se espera {api}, {PREFIJO}-api)")
        if problemas:
            raise comun.Falla(lista(problemas))
        return f"subredes_tareas = [{publica_a}] (publica-a); sg_migrate = {api} ({PREFIJO}-api)"

    for id_, funcion in (
        ("C1", c1),
        ("C2a", c2a),
        ("C2b", c2b),
        ("C2c", c2c),
        ("C2d", c2d),
        ("C2e", c2e),
        ("C3a", c3a),
        ("C3b", c3b),
        ("C4", c4),
        ("C5", c5),
    ):
        v.comprobacion(id_, funcion)


def main(argv: list[str] | None = None) -> int:
    validador = comun.Validador(
        lote=LOTE,
        validacion=VALIDACION,
        descripcion="INF-1.1 — Red y grupos de seguridad (docs/validation/validation-1-1.md)",
        comprobaciones=COMPROBACIONES,
        grupos=GRUPOS_SOLO,
    )
    return validador.correr(cuerpo, argv)


if __name__ == "__main__":
    sys.exit(main())
