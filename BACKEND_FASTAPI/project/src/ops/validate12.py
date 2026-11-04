"""BE-1.2 — Base de datos y migraciones. `migrar` dos veces, `verificar-esquema`, admin inicial y `/v1/health/ready`.

Documento: BACKEND_FASTAPI/docs/validation/validation-1-2.md · criterios: BACKEND_FASTAPI/docs/PLAN.md §2.2.

    cd BACKEND_FASTAPI/project
    uv run --group ops python src/ops/validate12.py --entorno dev
    uv run --group ops python src/ops/validate12.py --entorno local   # con docker compose up en marcha

Variables: AWS_PROFILE (obligatoria en dev), VALIDACION_API_URL (opcional en dev, obligatoria en local) y
VALIDACION_ADMIN_CORREO (solo local, para C3). No crea datos: las tareas sueltas solo dejan sus logs.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from collections.abc import Callable
from typing import Any

import comun
from comun import ErrorConfiguracion, Falla, PrecondicionNoCumplida, exigir

LOTE = "BE-1.2"
SERVICIO_API = "api"
INSTANCIA_RDS = "campus-locator-dev-db"
SECRETOS = ("campus-locator/dev/db", "campus-locator/dev/admin-inicial")
SECRETO_ADMIN = "campus-locator/dev/admin-inicial"
VERSION_PG_MINIMA = (17, 1)
COMANDO_VERIFICAR = ["python", "-m", "app.cli", "verificar-esquema"]
INICIADA_POR = "validate12"
TIMEOUT_HTTP_S = 15
MAX_DIFERENCIAS_DETALLE = 10
# local: servicios de project/docker-compose.yml
SERVICIOS_COMPOSE = ("db", "api")
CLI_COMPOSE = ["docker", "compose", "run", "--rm", "-T", "api", "python", "-m", "app.cli"]
PSQL_COMPOSE = ["docker", "compose", "exec", "-T", "db", "psql", "-U", "campus_app", "-d", "campus_locator", "-tAc"]


class Contexto:
    def __init__(self, entorno: str) -> None:
        self.entorno = entorno
        self.sesion: Any = None
        self.url_api: str | None = None
        self.definicion_migrate: str | None = None  # ARN de la revisión que se lanza en C1 y C2
        self._outputs: dict[str, Any] | None = None
        self._clientes: dict[str, Any] = {}
        self._http: Any = None
        self.dormir: Callable[[float], None] = time.sleep  # esperas entre reintentos (las pruebas no esperan)

    def aws(self, servicio: str) -> Any:
        if servicio not in self._clientes:
            self._clientes[servicio] = self.sesion.client(servicio)
        return self._clientes[servicio]

    def outputs(self) -> dict[str, Any]:
        if self._outputs is None:
            self._outputs = comun.outputs_terraform()
        return self._outputs

    def http(self) -> Any:
        if self._http is None:
            import httpx

            self._http = httpx.Client(timeout=TIMEOUT_HTTP_S, follow_redirects=False)
        return self._http

    def cerrar(self) -> None:
        if self._http is not None:
            self._http.close()

    # -- ECS --------------------------------------------------------------------------------------------------------
    def imagen_contenedor(self, definicion: str) -> tuple[str, str]:
        """(ARN de la revisión, imagen del contenedor `app`) de una familia o revisión."""
        datos = self.aws("ecs").describe_task_definition(taskDefinition=definicion)["taskDefinition"]
        contenedores = {c.get("name"): c for c in datos.get("containerDefinitions", [])}
        exigir(comun.CONTENEDOR in contenedores, f"{definicion} no tiene contenedor `{comun.CONTENEDOR}`")
        return datos["taskDefinitionArn"], contenedores[comun.CONTENEDOR].get("image", "")

    def imagen_api(self) -> str:
        servicios = self.aws("ecs").describe_services(cluster=comun.CLUSTER, services=[SERVICIO_API])["services"]
        exigir(servicios, f"el servicio `{SERVICIO_API}` no aparece en `{comun.CLUSTER}`")
        return self.imagen_contenedor(servicios[0]["taskDefinition"])[1]

    def tarea(self, familia: str, definicion: str, comando: list[str] | None = None) -> comun.ResultadoTarea:
        return comun.lanzar_tarea(
            self.aws("ecs"),
            self.aws("logs"),
            definicion=definicion,
            red=comun.red_tareas(self.outputs()),
            familia=familia,
            comando=comando,
            iniciada_por=INICIADA_POR,
            dormir=self.dormir,
        )

    def revision_migrate(self) -> str:
        """Última revisión ACTIVE de `campus-locator-dev-migrate`; debe llevar la imagen de `api` (paso 2 de §5.9)."""
        if self.definicion_migrate is None:
            arn, imagen = self.imagen_contenedor(comun.FAMILIA_MIGRATE)
            desplegada = self.imagen_api()
            exigir(
                imagen == desplegada,
                f"{_corto(arn)} usa {_etiqueta(imagen)} y `api` usa {_etiqueta(desplegada)}: "
                "¿terminó backend.yml en main con el paso migrate?",
            )
            self.definicion_migrate = arn
        return self.definicion_migrate


def _corto(arn: str) -> str:
    return arn.rsplit("/", 1)[-1]


def _etiqueta(imagen: str) -> str:
    ultimo = imagen.rsplit("/", 1)[-1]
    etiqueta = ultimo.split(":", 1)[1] if ":" in ultimo else ultimo
    return etiqueta[:12]


def _version(texto: str) -> tuple[int, ...]:
    return tuple(int(parte) for parte in re.findall(r"\d+", texto)[:2])


def _error_aws(exc: Exception, que: str, lote: str) -> Exception:
    """Error de AWS en una precondición: permisos → 3; recurso ausente → 2 (el lote `lote` no está listo)."""
    if comun.es_acceso_denegado(exc):
        return ErrorConfiguracion(f"sin permiso para {que}: {comun.codigo_error_aws(exc)}")
    return PrecondicionNoCumplida(f"{lote}: {que} ({comun.codigo_error_aws(exc) or type(exc).__name__})")


def _resumir(texto: str, limite: int = 200) -> str:
    lineas = [linea.strip() for linea in texto.strip().splitlines() if linea.strip()]
    return (lineas[-1] if lineas else "sin salida")[:limite]


def _eventos_json(texto: str) -> list[dict[str, Any]]:
    resultado = comun.ResultadoTarea(arn="local", definicion="local", codigo=None, motivo="")
    resultado.lineas = texto.splitlines()
    return resultado.eventos()


def _motivo_fallo(eventos: list[dict[str, Any]], codigo: int | None, motivo_tarea: str = "") -> str:
    """Resumen del porqué de un código ≠ 0 a partir de los eventos de la CLI (§5.10)."""
    for nombre in ("base_no_disponible", "configuracion_incompleta", "migracion_fallida", "verificacion_fallida"):
        for evento in eventos:
            if evento.get("evento") == nombre:
                extra = evento.get("motivo") or ", ".join(evento.get("faltan", []))
                return f"{nombre}: {extra}"[:300]
    if codigo is None:
        return f"la tarea no llegó a ejecutar el contenedor ({motivo_tarea or 'sin motivo'})"
    return "sin eventos en el log"


# --- Precondiciones ----------------------------------------------------------------------------------------------
def p1_credenciales(ctx: Contexto) -> str:
    ctx.sesion = comun.sesion_aws()
    arn = comun.verificar_cuenta(ctx.sesion)
    return f"cuenta {comun.CUENTA_AWS} ({arn.rsplit('/', 1)[-1]})"


def p2_be11(ctx: Contexto) -> str:
    """BE-1.1 hecho: `api` responde `/v1/health` (en dev, con el commit de la imagen desplegada)."""
    import httpx

    if ctx.entorno == "local":
        if not os.environ.get("VALIDACION_API_URL", "").strip():
            raise ErrorConfiguracion("en local hace falta VALIDACION_API_URL (p. ej. http://localhost:8000/v1)")
        ctx.url_api = comun.url_api()
    else:
        ctx.url_api = comun.url_api(None if os.environ.get("VALIDACION_API_URL", "").strip() else ctx.outputs())
    try:
        respuesta = ctx.http().get(f"{ctx.url_api}/health")
    except httpx.HTTPError as exc:
        raise PrecondicionNoCumplida(f"BE-1.1: GET /v1/health no respondió ({type(exc).__name__})") from None
    if respuesta.status_code != 200:
        raise PrecondicionNoCumplida(f"BE-1.1: GET /v1/health respondió {respuesta.status_code}")
    commit = str(respuesta.json().get("commit", ""))
    if ctx.entorno == "local":
        return f"{ctx.url_api} · commit {commit}"
    from botocore.exceptions import ClientError

    try:
        imagen = ctx.imagen_api()
    except ClientError as exc:
        raise _error_aws(exc, f"describir el servicio `{SERVICIO_API}`", "BE-1.1") from None
    etiqueta = imagen.rsplit(":", 1)[-1] if ":" in imagen.rsplit("/", 1)[-1] else ""
    if not commit or not etiqueta.startswith(commit):
        raise PrecondicionNoCumplida(f"BE-1.1: /v1/health dice commit {commit!r} y la imagen de `api` es {etiqueta!r}")
    return f"{ctx.url_api} · commit {commit} = imagen de `api`"


def p3_inf12(ctx: Contexto) -> str:
    from botocore.exceptions import ClientError

    try:
        instancias = ctx.aws("rds").describe_db_instances(DBInstanceIdentifier=INSTANCIA_RDS)["DBInstances"]
    except ClientError as exc:
        raise _error_aws(exc, f"describir la instancia `{INSTANCIA_RDS}`", "INF-1.2") from None
    instancia = instancias[0]
    estado, version = instancia.get("DBInstanceStatus"), str(instancia.get("EngineVersion", ""))
    if estado != "available":
        raise PrecondicionNoCumplida(f"INF-1.2: `{INSTANCIA_RDS}` está `{estado}`, no `available`")
    if _version(version) < VERSION_PG_MINIMA:
        raise PrecondicionNoCumplida(f"INF-1.2: PostgreSQL {version} < 17.1 (sin pgvector 0.8)")
    for secreto in SECRETOS:
        try:
            ctx.aws("secretsmanager").describe_secret(SecretId=secreto)
        except ClientError as exc:
            raise _error_aws(exc, f"describir el secreto `{secreto}`", "INF-1.2") from None
    return f"`{INSTANCIA_RDS}` available, PostgreSQL {version}; secretos db y admin-inicial"


def p4_tareas(ctx: Contexto) -> str:
    from botocore.exceptions import ClientError

    revisiones = []
    for familia in (comun.FAMILIA_MIGRATE, comun.FAMILIA_VALIDACION):
        try:
            arn, _ = ctx.imagen_contenedor(familia)
        except ClientError as exc:
            raise _error_aws(exc, f"describir la definición `{familia}`", "INF-1.3") from None
        revisiones.append(_corto(arn))
    red = comun.red_tareas(ctx.outputs())["awsvpcConfiguration"]
    return f"{', '.join(revisiones)}; subredes {','.join(red['subnets'])} y grupo {red['securityGroups'][0]}"


def p5_compose(ctx: Contexto) -> str:
    resultado = comun.ejecutar_proceso(["docker", "compose", "ps", "--format", "json"], cwd=comun.RAIZ_PROYECTO)
    if resultado.returncode != 0:
        raise ErrorConfiguracion(f"`docker compose ps` falló: {_resumir(resultado.stderr)}")
    texto = resultado.stdout.strip()
    try:  # Compose v2 imprime un objeto por línea (antes, una lista)
        datos = json.loads(texto) if texto.startswith("[") else [json.loads(linea) for linea in texto.splitlines()]
    except ValueError:
        raise ErrorConfiguracion("la salida de `docker compose ps --format json` no es JSON") from None
    en_marcha = {d.get("Service") for d in datos if d.get("State") == "running"}
    faltan = [servicio for servicio in SERVICIOS_COMPOSE if servicio not in en_marcha]
    if faltan:
        raise PrecondicionNoCumplida(f"docker compose: no están en marcha {', '.join(faltan)} (`docker compose up -d`)")
    return f"docker compose: {', '.join(sorted(s for s in en_marcha if s))} en marcha"


# --- Comprobaciones ----------------------------------------------------------------------------------------------
def _cli_local(comando: str) -> tuple[int, list[dict[str, Any]]]:
    resultado = comun.ejecutar_proceso([*CLI_COMPOSE, comando], cwd=comun.RAIZ_PROYECTO)
    return resultado.returncode, _eventos_json(resultado.stdout)


def c1_migrar_dos_veces(ctx: Contexto) -> str:
    """Dos `migrar` seguidos con salida 0; el segundo no aplica nada (idempotente)."""
    ejecuciones: list[tuple[int | None, list[dict[str, Any]], str, str]] = []
    for _ in range(2):
        if ctx.entorno == "local":
            codigo, eventos = _cli_local("migrar")
            ejecuciones.append((codigo, eventos, "", "docker compose run"))
        else:
            r = ctx.tarea(comun.FAMILIA_MIGRATE, ctx.revision_migrate())
            ejecuciones.append((r.codigo, r.eventos(), r.motivo, f"tarea {r.id[:12]}"))
        codigo, eventos, motivo, donde = ejecuciones[-1]
        exigir(
            codigo == 0,
            f"migrar #{len(ejecuciones)} ({donde}) terminó con {codigo}: {_motivo_fallo(eventos, codigo, motivo)}",
        )
    terminadas = [
        next((e for e in ev if e.get("evento") == "migracion_terminada"), None) for _, ev, _, _ in ejecuciones
    ]
    segunda = terminadas[1]
    if segunda is not None:
        exigir(segunda.get("aplicada") is False, f"el segundo migrar volvió a aplicar migraciones: {segunda}")
    revision = (segunda or {}).get("revision", "?")
    admin = ", ".join(str((t or {}).get("admin_inicial", "?")) for t in terminadas)
    origen = _corto(ctx.definicion_migrate) if ctx.definicion_migrate else "docker compose"
    return f"2 × migrar con salida 0 ({origen}); revisión {revision}; admin inicial: {admin}"


def c2_verificar_esquema(ctx: Contexto) -> str:
    if ctx.entorno == "local":
        codigo, eventos = _cli_local("verificar-esquema")
        motivo_tarea = ""
    else:
        r = ctx.tarea(comun.FAMILIA_MIGRATE, ctx.revision_migrate(), COMANDO_VERIFICAR)
        codigo, eventos, motivo_tarea = r.codigo, r.eventos(), r.motivo
    verificado = next((e for e in eventos if e.get("evento") == "esquema_verificado"), {})
    if codigo == 0:
        return (
            f"coincide con §5.7 · revisión {verificado.get('revision', '?')} · PostgreSQL "
            f"{str(verificado.get('servidor', '?')).split(' ')[0]} · pgvector {verificado.get('pgvector', '?')}"
        )
    if codigo == 1:
        diferencias = [e for e in eventos if e.get("evento") == "esquema_diferencia"]
        lista = "; ".join(
            f"{d.get('objeto')} {d.get('aspecto')} ({d.get('esperado')} → {d.get('encontrado')})"
            for d in diferencias[:MAX_DIFERENCIAS_DETALLE]
        )
        resto = len(diferencias) - MAX_DIFERENCIAS_DETALLE
        raise Falla(
            f"difiere en {verificado.get('diferencias', len(diferencias))}: {lista or 'sin detalle en el log'}"
            + (f"; y {resto} más" if resto > 0 else "")
        )
    raise Falla(f"verificar-esquema terminó con {codigo}: {_motivo_fallo(eventos, codigo, motivo_tarea)}")


def _sql_admin(correo: str) -> str:
    literal = correo.replace("'", "''")
    return f"SELECT count(*) FROM usuarios WHERE rol = 'admin' AND activo AND correo = '{literal}'"  # noqa: S608


def c3_admin_inicial(ctx: Contexto) -> str:
    if ctx.entorno == "local":
        correo = os.environ.get("VALIDACION_ADMIN_CORREO", "").strip().lower()
        if not correo:
            raise ErrorConfiguracion(
                "en local hace falta VALIDACION_ADMIN_CORREO (el ADMIN_INICIAL_CORREO del compose)"
            )
        resultado = comun.ejecutar_proceso([*PSQL_COMPOSE, _sql_admin(correo)], cwd=comun.RAIZ_PROYECTO)
        codigo, lineas = resultado.returncode, resultado.stdout.splitlines()
        origen = "VALIDACION_ADMIN_CORREO"
    else:
        secreto = ctx.aws("secretsmanager").get_secret_value(SecretId=SECRETO_ADMIN)
        correo = str(json.loads(secreto["SecretString"]).get("correo", "")).strip().lower()
        exigir(correo, f"el secreto `{SECRETO_ADMIN}` no tiene la clave `correo`")
        r = ctx.tarea(comun.FAMILIA_VALIDACION, comun.FAMILIA_VALIDACION, ["psql", "-tAc", _sql_admin(correo)])
        codigo, lineas = r.codigo, r.lineas
        origen = f"secreto admin-inicial · tarea {r.id[:12]}"
    exigir(codigo == 0, f"psql terminó con {codigo}: {_resumir(chr(10).join(lineas))}")
    numeros = [linea.strip() for linea in lineas if linea.strip().isdigit()]
    exigir(numeros, "psql no devolvió un número")
    exigir(numeros[-1] == "1", f"hay {numeros[-1]} admin(s) activos con el correo del admin inicial, se esperaba 1")
    return f"1 usuario admin activo con el correo del admin inicial ({origen})"


def c4_ready(ctx: Contexto) -> str:
    respuesta = ctx.http().get(f"{ctx.url_api}/health/ready")
    try:
        cuerpo = respuesta.json()
    except ValueError:
        raise Falla(f"/v1/health/ready respondió {respuesta.status_code} sin JSON") from None
    if respuesta.status_code != 200:
        codigo = cuerpo.get("error", {}).get("codigo") if isinstance(cuerpo, dict) else None
        raise Falla(f"/v1/health/ready respondió {respuesta.status_code} {codigo or cuerpo}")
    exigir(cuerpo.get("estado") == "ok", f"estado = {cuerpo.get('estado')!r}")
    exigir(cuerpo.get("db") == "ok", f"db = {cuerpo.get('db')!r}, se esperaba 'ok'")
    return f"200 · db ok · embedding {cuerpo.get('embedding')}"


def main(argv: list[str] | None = None, ctx: Contexto | None = None) -> int:
    validador = comun.Validador(lote=LOTE, validacion="validation-1-2", entornos=("dev", "local"), descripcion=__doc__)
    argumentos = validador.iniciar(argv)
    ctx = ctx or Contexto(argumentos.entorno)
    if argumentos.entorno == "dev":
        precondiciones = [
            ("P1", lambda: p1_credenciales(ctx)),
            ("P2", lambda: p2_be11(ctx)),
            ("P3", lambda: p3_inf12(ctx)),
            ("P4", lambda: p4_tareas(ctx)),
        ]
    else:
        precondiciones = [("P2", lambda: p2_be11(ctx)), ("P5", lambda: p5_compose(ctx))]
    try:
        return validador.ejecutar(
            precondiciones=precondiciones,
            comprobaciones=[
                ("C1", lambda: c1_migrar_dos_veces(ctx)),
                ("C2", lambda: c2_verificar_esquema(ctx)),
                ("C3", lambda: c3_admin_inicial(ctx)),
                ("C4", lambda: c4_ready(ctx)),
            ],
            manuales=[],
            limpieza=None,  # no crea datos (validation-1-2.md §4)
        )
    finally:
        ctx.cerrar()


if __name__ == "__main__":
    sys.exit(main())
