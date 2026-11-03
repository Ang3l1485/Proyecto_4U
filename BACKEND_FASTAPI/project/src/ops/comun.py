"""Ayudas comunes de los validadores del backend (`validate<fase><n>.py`).

Implementa el contrato común de `INFRASTRUCTURA_TERRAFORM/docs/ARCHITECTURE.md` §5.11 (argumentos, orden de
ejecución, estados, códigos de salida e informe JSON) y lo propio del backend de `BACKEND_FASTAPI/docs/ARCHITECTURE.md`
§5.11 (URL de la API, credenciales de AWS).

Uso típico en un validador:

    validador = Validador(lote="BE-1.1", validacion="validation-1-1", entornos=("dev",), descripcion=__doc__)
    ctx = validador.iniciar()
    sys.exit(validador.ejecutar(
        precondiciones=[("P1", lambda: ...)],
        comprobaciones=[("C1", lambda: ...)],
        manuales=[],
        limpieza=None,
    ))

Cada función de precondición o comprobación devuelve un texto corto (el `detalle`) y señala problemas lanzando:
- `Falla` → la comprobación queda en `falla` (código 1);
- `PrecondicionNoCumplida` → otro lote no está listo (código 2);
- `ErrorConfiguracion` → uso, configuración, credenciales o herramientas (código 3).

Reglas (§5.11): nunca imprimir secretos, tokens ni URLs prefirmadas; ser idempotente; limpiar siempre lo creado.

Además (tabla completa en backend §5.11): tareas sueltas de ECS (BE-1.2) y, desde BE-1.3, secretos y credenciales del
admin, `ClienteApi` (login con pausa y reintentos de 429 de API Gateway), `EntornoBackend` (`python -m app.cli` y SQL
en `local` o `dev`) y el usuario de prueba `validacion+user@campus.edu.co`; recolección (BE-2.1), `embedding` y colas
(BE-2.2), vecinos (BE-2.4), lugares de prueba (BE-3.1), el resumen del panel (BE-2.3) y alertas de prueba (BE-3.3).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import traceback
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# --- Constantes del proyecto (infra §3.1, §5.1) -------------------------------------------------------------------
CUENTA_AWS = "648617469176"
REGION_AWS = "us-east-1"

RAIZ_PROYECTO = Path(__file__).resolve().parents[2]  # BACKEND_FASTAPI/project
RAIZ_CARPETA = RAIZ_PROYECTO.parent  # BACKEND_FASTAPI
RAIZ_REPO = RAIZ_CARPETA.parent  # raíz del monorepo
DIR_TERRAFORM_DEV = RAIZ_REPO / "INFRASTRUCTURA_TERRAFORM" / "project" / "envs" / "dev"
DIR_INFORMES = RAIZ_PROYECTO / ".validacion"

PASA, FALLA, MANUAL, OMITIDA = "pasa", "falla", "manual", "omitida"
CODIGO_RESULTADO = {0: "pasa", 1: "falla", 2: "bloqueado", 3: "error"}


# --- Excepciones -------------------------------------------------------------------------------------------------
class Falla(Exception):
    """La comprobación no se cumple."""


class PrecondicionNoCumplida(Exception):
    """Otro lote no está listo: código 2 (`Bloqueado`)."""


class ErrorConfiguracion(Exception):
    """Error de uso, configuración, credenciales o herramientas: código 3."""


def exigir(condicion: object, mensaje: str) -> None:
    """Lanza `Falla(mensaje)` si `condicion` es falsa."""
    if not condicion:
        raise Falla(mensaje)


# --- Resultados e informe ----------------------------------------------------------------------------------------
@dataclass
class Resultado:
    id: str
    estado: str
    detalle: str = ""
    duracion_ms: int | None = None


@dataclass
class Manual:
    id: str
    instruccion: str


@dataclass
class _Estado:
    precondiciones: list[Resultado] = field(default_factory=list)
    comprobaciones: list[Resultado] = field(default_factory=list)
    manuales: list[Manual] = field(default_factory=list)
    codigo_precondicion: int = 0


def _ahora() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _imprimir(estado: str, id_: str, detalle: str) -> None:
    print(f"[{estado.upper()}] {id_} {detalle}".rstrip(), flush=True)


def _criterio(id_: str) -> str:
    """`C2a` → `C2` (las comprobaciones con letra pertenecen al criterio del PLAN)."""
    coincidencia = re.match(r"([A-Z]+\d+)", id_)
    return coincidencia.group(1) if coincidencia else id_


class Validador:
    def __init__(self, *, lote: str, validacion: str, entornos: Sequence[str], descripcion: str | None = None) -> None:
        self.lote = lote
        self.validacion = validacion
        self.entornos = tuple(entornos)
        self.descripcion = (descripcion or "").strip()
        self.args: argparse.Namespace | None = None
        self._estado = _Estado()
        self._inicio = _ahora()
        self._solo: set[str] | None = None

    # -- argumentos ----------------------------------------------------------------------------------------------
    def crear_parser(self) -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(
            description=f"Validador de {self.lote} ({self.validacion}.md). {self.descripcion}".strip(),
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
        parser.add_argument("--entorno", required=True, choices=("local", "dev"), help="Entorno a validar")
        parser.add_argument("--informe", type=Path, help="Ruta del informe JSON (por defecto, project/.validacion/)")
        parser.add_argument("--solo", help="Solo estas comprobaciones, separadas por comas (p. ej. C1,C3)")
        parser.add_argument("--sin-limpieza", action="store_true", help="No borrar los datos de prueba al terminar")
        return parser

    def iniciar(self, argv: Sequence[str] | None = None, parser: argparse.ArgumentParser | None = None):
        """Lee los argumentos. Termina con código 3 si el entorno no está admitido por el documento."""
        _utf8_en_consola()
        parser = parser or self.crear_parser()
        try:
            self.args = parser.parse_args(argv)
        except SystemExit as salida:  # argparse sale con 2 en error de uso; el contrato pide 3
            raise SystemExit(0 if salida.code == 0 else 3) from None
        if self.args.entorno not in self.entornos:
            print(f"{self.lote} solo admite el entorno: {', '.join(self.entornos)} (ver {self.validacion}.md).")
            raise SystemExit(3)
        if self.args.solo:
            self._solo = {parte.strip() for parte in self.args.solo.split(",") if parte.strip()}
        print(f"== {self.lote} · {self.validacion} · entorno {self.args.entorno}", flush=True)
        return self.args

    def _incluida(self, id_: str) -> bool:
        return self._solo is None or id_ in self._solo or _criterio(id_) in self._solo

    # -- ejecución -----------------------------------------------------------------------------------------------
    def ejecutar(
        self,
        *,
        precondiciones: Iterable[tuple[str, Callable[[], str | None]]],
        comprobaciones: Iterable[tuple[str, Callable[[], str | None]]],
        manuales: Iterable[tuple[str, str]] = (),
        limpieza: Callable[[], str | None] | None = None,
        preparacion: Callable[[], str | None] | None = None,
    ) -> int:
        """Orden de §5.11: precondiciones → automáticas → manuales → limpieza (siempre) → informe.

        `preparacion` (BE-2.1) corre una vez si las precondiciones pasan y antes de las comprobaciones (p. ej. borrar
        restos `validacion-` de una ejecución interrumpida). Imprime `[PREPARACION] <detalle>`; si falla, imprime
        `[PREPARACION] falló: …` y sigue (no cambia el código de salida).
        """
        if self.args is None:
            raise RuntimeError("Llama a iniciar() antes de ejecutar()")
        try:
            if self._precondiciones(precondiciones):
                if preparacion is not None:
                    self._preparar(preparacion)
                for id_, funcion in comprobaciones:
                    self._comprobacion(id_, funcion)
                for id_, instruccion in manuales:
                    self._estado.manuales.append(Manual(id_, instruccion))
                    _imprimir(MANUAL, id_, instruccion)
        finally:
            self._limpiar(limpieza)
        return self._informe()

    def _precondiciones(self, precondiciones: Iterable[tuple[str, Callable[[], str | None]]]) -> bool:
        for id_, funcion in precondiciones:
            try:
                detalle = funcion() or ""
            except PrecondicionNoCumplida as exc:
                self._registrar_precondicion(id_, FALLA, f"{exc} (bloqueado)", 2)
                return False
            except ErrorConfiguracion as exc:
                self._registrar_precondicion(id_, FALLA, f"{exc} (configuración)", 3)
                return False
            except Exception as exc:
                self._registrar_precondicion(id_, FALLA, f"error inesperado: {_resumen(exc)}", 3)
                traceback.print_exc()
                return False
            self._registrar_precondicion(id_, PASA, detalle, 0)
        return True

    def _registrar_precondicion(self, id_: str, estado: str, detalle: str, codigo: int) -> None:
        self._estado.precondiciones.append(Resultado(id_, estado, detalle))
        self._estado.codigo_precondicion = max(self._estado.codigo_precondicion, codigo)
        _imprimir(estado, id_, detalle)

    def _comprobacion(self, id_: str, funcion: Callable[[], str | None]) -> None:
        if not self._incluida(id_):
            resultado = Resultado(id_, OMITIDA, "excluida con --solo")
        else:
            inicio = time.perf_counter()
            try:
                resultado = Resultado(id_, PASA, funcion() or "")
            except Falla as exc:
                resultado = Resultado(id_, FALLA, str(exc))
            except Exception as exc:
                resultado = Resultado(id_, FALLA, f"error inesperado: {_resumen(exc)}")
            resultado.duracion_ms = int((time.perf_counter() - inicio) * 1000)
        self._estado.comprobaciones.append(resultado)
        _imprimir(resultado.estado, id_, resultado.detalle)

    def _preparar(self, preparacion: Callable[[], str | None]) -> None:
        try:
            print(f"[PREPARACION] {preparacion() or 'hecha'}", flush=True)
        except Exception as exc:
            print(f"[PREPARACION] falló: {_resumen(exc)}", flush=True)

    def _limpiar(self, limpieza: Callable[[], str | None] | None) -> None:
        if limpieza is None:
            return
        if self.args is not None and self.args.sin_limpieza:
            print("[LIMPIEZA] omitida (--sin-limpieza)", flush=True)
            return
        try:
            detalle = limpieza() or "hecha"
            print(f"[LIMPIEZA] {detalle}", flush=True)
        except Exception as exc:
            print(f"[LIMPIEZA] falló: {_resumen(exc)}", flush=True)

    # -- informe -------------------------------------------------------------------------------------------------
    def codigo_salida(self) -> int:
        if self._estado.codigo_precondicion:
            return self._estado.codigo_precondicion
        return 1 if any(r.estado == FALLA for r in self._estado.comprobaciones) else 0

    def _informe(self) -> int:
        codigo = self.codigo_salida()
        assert self.args is not None  # noqa: S101 (iniciar() ya se llamó)
        datos: dict[str, Any] = {
            "lote": self.lote,
            "validacion": self.validacion,
            "entorno": self.args.entorno,
            "commit": commit_local(),
            "inicio": self._inicio,
            "fin": _ahora(),
            "resultado": CODIGO_RESULTADO[codigo],
            "precondiciones": [_sin_nulos(asdict(r)) for r in self._estado.precondiciones],
            "comprobaciones": [_sin_nulos(asdict(r)) for r in self._estado.comprobaciones],
            "manuales": [asdict(m) for m in self._estado.manuales],
        }
        ruta = self.args.informe or DIR_INFORMES / f"{self.lote}-{datetime.now(UTC):%Y%m%d-%H%M%S}.json"
        try:
            ruta.parent.mkdir(parents=True, exist_ok=True)
            ruta.write_text(json.dumps(datos, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            destino = str(ruta)
        except OSError as exc:
            destino = f"no se pudo escribir ({exc})"
        print(f"== Resultado: {datos['resultado']} (código {codigo}) · informe: {destino}", flush=True)
        return codigo


def _sin_nulos(datos: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in datos.items() if v is not None}


def _resumen(exc: BaseException) -> str:
    texto = str(exc).strip().splitlines()[0] if str(exc).strip() else ""
    return f"{type(exc).__name__}: {texto}" if texto else type(exc).__name__


def _utf8_en_consola() -> None:
    """En Windows la consola puede no ser UTF-8: evita que un acento rompa la salida."""
    for flujo in (sys.stdout, sys.stderr):
        reconfigurar = getattr(flujo, "reconfigure", None)
        if reconfigurar is not None:
            try:
                reconfigurar(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


# --- Procesos externos (git, terraform, docker) ------------------------------------------------------------------
def ejecutar_proceso(
    argumentos: Sequence[str],
    *,
    cwd: Path | None = None,
    timeout: float = 600,
    entorno: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Como `ejecutar_comando`, pero devuelve el resultado con su código en vez de lanzar si no es 0.

    `entorno` añade variables al entorno del proceso hijo (sobre el actual): así un secreto llega al proceso sin
    aparecer en la línea de comandos (p. ej. `docker compose run -e VARIABLE`, que toma el valor de ahí).
    """
    ejecutable = shutil.which(argumentos[0])
    if ejecutable is None:
        raise ErrorConfiguracion(f"no se encontró `{argumentos[0]}` en el PATH")
    try:
        return subprocess.run(
            [ejecutable, *argumentos[1:]],
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            env={**os.environ, **entorno} if entorno else None,
        )
    except subprocess.TimeoutExpired:
        raise Falla(f"`{' '.join(argumentos[:4])} …` no terminó en {int(timeout)} s") from None


def ejecutar_comando(argumentos: Sequence[str], *, cwd: Path | None = None, timeout: float = 120) -> str:
    """Ejecuta un comando y devuelve su salida estándar. Herramienta ausente → `ErrorConfiguracion`.

    Un código distinto de 0 lanza `subprocess.CalledProcessError` (cada validador decide qué significa).
    """
    ejecutable = shutil.which(argumentos[0])
    if ejecutable is None:
        raise ErrorConfiguracion(f"no se encontró `{argumentos[0]}` en el PATH")
    resultado = subprocess.run(
        [ejecutable, *argumentos[1:]],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )
    if resultado.returncode != 0:
        raise subprocess.CalledProcessError(resultado.returncode, argumentos, resultado.stdout, resultado.stderr)
    return resultado.stdout


def git(*argumentos: str, timeout: float = 120) -> str:
    return ejecutar_comando(["git", *argumentos], cwd=RAIZ_REPO, timeout=timeout).strip()


def commit_local() -> str | None:
    """SHA corto del `HEAD` local (para el informe)."""
    try:
        return git("rev-parse", "--short", "HEAD") or None
    except (ErrorConfiguracion, subprocess.CalledProcessError, OSError, subprocess.TimeoutExpired):
        return None


def outputs_terraform(directorio: Path = DIR_TERRAFORM_DEV) -> dict[str, Any]:
    """`terraform -chdir=<dir> output -json` → `{nombre: valor}`.

    Requiere `terraform init` hecho en ese directorio con acceso al estado remoto (infra §3.9).
    """
    if not directorio.is_dir():
        raise ErrorConfiguracion(f"no existe {directorio}")
    try:
        salida = ejecutar_comando(["terraform", f"-chdir={directorio}", "output", "-json"], timeout=180)
    except subprocess.CalledProcessError as exc:
        error = (exc.stderr or "").strip().splitlines()
        raise ErrorConfiguracion(
            f"`terraform output` falló en {directorio} ({error[-1] if error else exc.returncode}); "
            "¿falta `terraform init` o credenciales del estado?"
        ) from None
    except subprocess.TimeoutExpired:
        raise ErrorConfiguracion("`terraform output` no respondió a tiempo") from None
    datos = json.loads(salida or "{}")
    return {nombre: valor.get("value") for nombre, valor in datos.items()}


# --- AWS ---------------------------------------------------------------------------------------------------------
def sesion_aws():
    """Sesión de boto3 con `AWS_PROFILE` (obligatoria en `dev`, backend §5.11) en `us-east-1`."""
    perfil = os.environ.get("AWS_PROFILE", "").strip()
    if not perfil:
        raise ErrorConfiguracion("falta la variable AWS_PROFILE")
    try:
        import boto3
        from botocore.exceptions import ProfileNotFound
    except ImportError:
        raise ErrorConfiguracion("falta boto3: ejecuta con `uv run --group ops …`") from None
    try:
        return boto3.Session(profile_name=perfil, region_name=REGION_AWS)
    except ProfileNotFound:
        raise ErrorConfiguracion(f"el perfil de AWS `{perfil}` no existe") from None


def verificar_cuenta(sesion) -> str:
    """Comprueba que las credenciales sean de la cuenta del proyecto. Devuelve el ARN de quien llama."""
    from botocore.exceptions import BotoCoreError, ClientError

    try:
        identidad = sesion.client("sts").get_caller_identity()
    except (BotoCoreError, ClientError) as exc:
        raise ErrorConfiguracion(f"credenciales de AWS no válidas: {_resumen(exc)}") from None
    if identidad.get("Account") != CUENTA_AWS:
        raise ErrorConfiguracion(f"las credenciales son de la cuenta {identidad.get('Account')}, no de {CUENTA_AWS}")
    return identidad.get("Arn", "")


def codigo_error_aws(exc: BaseException) -> str:
    """Código de un `ClientError` de botocore (`AccessDenied`, `RepositoryNotFoundException`…), o ''."""
    respuesta = getattr(exc, "response", None) or {}
    return str(respuesta.get("Error", {}).get("Code", ""))


def es_acceso_denegado(exc: BaseException) -> bool:
    codigo = codigo_error_aws(exc)
    return codigo in {"AccessDenied", "AccessDeniedException", "UnauthorizedOperation", "ExpiredToken"} or (
        "AccessDenied" in codigo
    )


# --- Tareas sueltas de ECS (backend §5.11) -----------------------------------------------------------------------
CLUSTER = "campus-locator-dev"
CONTENEDOR = "app"
FAMILIA_MIGRATE = "campus-locator-dev-migrate"
FAMILIA_VALIDACION = "campus-locator-dev-validacion"
FAMILIA_WORKER = "campus-locator-dev-worker"  # BE-2.1: `limpiar-validacion` (rol que puede borrar en S3)
#: Log group y `awslogs-stream-prefix` de cada familia (infra §5.1): el stream es `<prefijo>/app/<id de la tarea>`.
LOGS_TAREA = {
    FAMILIA_MIGRATE: ("/campus-locator/dev/migrate", "migrate"),
    FAMILIA_VALIDACION: ("/campus-locator/dev/validacion", "validacion"),
    FAMILIA_WORKER: ("/campus-locator/dev/worker", "worker"),
}
ESPERA_TAREA_S = 900
PAUSA_LOGS_S = 5.0
INTENTOS_LOGS = 12


@dataclass
class ResultadoTarea:
    """Una tarea suelta ya detenida: código de salida del contenedor `app` (None si no llegó a correr) y su log."""

    arn: str
    definicion: str
    codigo: int | None
    motivo: str
    lineas: list[str] = field(default_factory=list)

    @property
    def id(self) -> str:
        return self.arn.rsplit("/", 1)[-1]

    def eventos(self, nombre: str | None = None) -> list[dict[str, Any]]:
        """Líneas JSON del log (§5.10), opcionalmente solo las de un `evento`."""
        encontrados = []
        for linea in self.lineas:
            try:
                datos = json.loads(linea)
            except ValueError:
                continue
            if isinstance(datos, dict) and (nombre is None or datos.get("evento") == nombre):
                encontrados.append(datos)
        return encontrados


def red_tareas(outputs: dict[str, Any]) -> dict[str, Any]:
    """`networkConfiguration` de `run-task` con los outputs `subredes_tareas` y `sg_migrate` (infra §5.2)."""
    subredes, grupo = outputs.get("subredes_tareas"), outputs.get("sg_migrate")
    if not subredes or not grupo:
        raise PrecondicionNoCumplida("INF-1.1: faltan los outputs `subredes_tareas` o `sg_migrate`")
    if isinstance(subredes, str):
        subredes = [s for s in subredes.split(",") if s]
    return {"awsvpcConfiguration": {"subnets": list(subredes), "securityGroups": [grupo], "assignPublicIp": "ENABLED"}}


def _error_aws_tarea(exc: Exception, que: str) -> Exception:
    if es_acceso_denegado(exc):
        return ErrorConfiguracion(f"sin permiso para {que}: {codigo_error_aws(exc)}")
    return Falla(f"{que}: {codigo_error_aws(exc) or _resumen(exc)}")


def lanzar_tarea(
    ecs: Any,
    logs: Any,
    *,
    definicion: str,
    red: dict[str, Any],
    familia: str,
    comando: Sequence[str] | None = None,
    iniciada_por: str = "validacion",
    espera_s: float = ESPERA_TAREA_S,
    dormir: Callable[[float], None] = time.sleep,
    entorno: Mapping[str, str] | None = None,
    log_completo: Callable[[int | None, list[str]], bool] | None = None,
) -> ResultadoTarea:
    """`ecs run-task` (Fargate) de `definicion` (familia o ARN de una revisión), espera a que pare y lee su log.

    Con `comando`, sobrescribe el del contenedor `app`; con `entorno`, le añade variables (`environment` del
    *override*). Los valores de `entorno` no se imprimen, pero quedan en la descripción de la tarea (`describe-tasks`)
    para quien tenga acceso a la cuenta: solo valores de prueba. `familia` elige el log group y el prefijo de §5.1.
    """
    from botocore.exceptions import ClientError, WaiterError

    peticion: dict[str, Any] = {
        "cluster": CLUSTER,
        "launchType": "FARGATE",
        "taskDefinition": definicion,
        "networkConfiguration": red,
        "count": 1,
        "startedBy": iniciada_por[:36],
    }
    sobrescritura: dict[str, Any] = {"name": CONTENEDOR}
    if comando is not None:
        sobrescritura["command"] = list(comando)
    if entorno:
        sobrescritura["environment"] = [{"name": nombre, "value": valor} for nombre, valor in entorno.items()]
    if len(sobrescritura) > 1:
        peticion["overrides"] = {"containerOverrides": [sobrescritura]}
    try:
        respuesta = ecs.run_task(**peticion)
    except ClientError as exc:
        raise _error_aws_tarea(exc, f"lanzar {definicion.rsplit('/', 1)[-1]}") from None
    tareas = respuesta.get("tasks") or []
    if not tareas:
        fallos = "; ".join(f"{f.get('arn', '')} {f.get('reason', '')}".strip() for f in respuesta.get("failures", []))
        raise Falla(f"run-task no lanzó la tarea ({fallos or 'sin motivo'})")
    arn = tareas[0]["taskArn"]
    try:
        ecs.get_waiter("tasks_stopped").wait(
            cluster=CLUSTER, tasks=[arn], WaiterConfig={"Delay": 6, "MaxAttempts": max(1, int(espera_s // 6))}
        )
    except WaiterError:
        raise Falla(f"la tarea {arn.rsplit('/', 1)[-1]} no se detuvo en {int(espera_s)} s") from None
    descrita = ecs.describe_tasks(cluster=CLUSTER, tasks=[arn])["tasks"][0]
    contenedor = next((c for c in descrita.get("containers", []) if c.get("name") == CONTENEDOR), {})
    resultado = ResultadoTarea(
        arn=arn,
        definicion=descrita.get("taskDefinitionArn", definicion),
        codigo=contenedor.get("exitCode"),
        motivo=contenedor.get("reason") or descrita.get("stoppedReason", ""),
    )
    grupo, prefijo = LOGS_TAREA[familia]
    completo = None if log_completo is None else (lambda lineas: log_completo(resultado.codigo, lineas))
    resultado.lineas = leer_log(logs, grupo, f"{prefijo}/{CONTENEDOR}/{resultado.id}", dormir=dormir, completo=completo)
    return resultado


def leer_log(
    logs: Any,
    grupo: str,
    stream: str,
    *,
    intentos: int = INTENTOS_LOGS,
    pausa_s: float = PAUSA_LOGS_S,
    dormir: Callable[[float], None] = time.sleep,
    completo: Callable[[list[str]], bool] | None = None,
) -> list[str]:
    """Mensajes de un stream de CloudWatch Logs, desde el principio. El log de una tarea tarda unos segundos en
    aparecer tras detenerse (y sus líneas pueden llegar en varias tandas): reintenta mientras el stream no exista, esté
    vacío o, con `completo`, mientras `completo(mensajes)` sea falso. Agotados los intentos devuelve lo último leído
    (`[]` si nunca apareció)."""
    from botocore.exceptions import ClientError

    ultimos: list[str] = []
    for intento in range(intentos):
        mensajes: list[str] = []
        token: str | None = None
        try:
            while True:
                argumentos = {"logGroupName": grupo, "logStreamName": stream, "startFromHead": True}
                if token:
                    argumentos["nextToken"] = token
                pagina = logs.get_log_events(**argumentos)
                mensajes += [evento.get("message", "") for evento in pagina.get("events", [])]
                siguiente = pagina.get("nextForwardToken")
                if not siguiente or siguiente == token:
                    break
                token = siguiente
        except ClientError as exc:
            if codigo_error_aws(exc) != "ResourceNotFoundException":
                raise _error_aws_tarea(exc, f"leer {grupo} {stream}") from None
        if mensajes:
            ultimos = mensajes
            if completo is None or completo(mensajes):
                return mensajes
        if intento < intentos - 1:
            dormir(pausa_s)
    return ultimos


# --- API del backend ---------------------------------------------------------------------------------------------
def url_api(outputs: dict[str, Any] | None = None) -> str:
    """URL base con `/v1` (backend §5.11): `VALIDACION_API_URL` o el output `api_base_url` de infra + `/v1`."""
    explicita = os.environ.get("VALIDACION_API_URL", "").strip()
    if explicita:
        return explicita.rstrip("/")
    base = (outputs or {}).get("api_base_url")
    if not base:
        raise PrecondicionNoCumplida("INF-1.4: falta el output `api_base_url`")
    return str(base).rstrip("/") + "/v1"


# --- Secretos y credenciales (BE-1.3) -----------------------------------------------------------------------------
SECRETO_ADMIN = "campus-locator/dev/admin-inicial"
SECRETO_JWT = "campus-locator/dev/jwt"


def leer_secreto(sesion: Any, secreto: str, *, lote: str = "INF-1.2") -> dict[str, Any]:
    """JSON de un secreto de Secrets Manager (infra §5.4). Sin permiso → `ErrorConfiguracion`; no existe o no se
    puede leer → `PrecondicionNoCumplida` del `lote` que lo crea. Nunca imprime el valor."""
    from botocore.exceptions import ClientError

    try:
        texto = sesion.client("secretsmanager").get_secret_value(SecretId=secreto)["SecretString"]
    except ClientError as exc:
        if es_acceso_denegado(exc):
            raise ErrorConfiguracion(f"sin permiso para leer el secreto `{secreto}`: {codigo_error_aws(exc)}") from None
        raise PrecondicionNoCumplida(
            f"{lote}: no se pudo leer el secreto `{secreto}` ({codigo_error_aws(exc)})"
        ) from None
    try:
        datos = json.loads(texto)
    except ValueError:
        raise ErrorConfiguracion(f"el secreto `{secreto}` no es un objeto JSON") from None
    if not isinstance(datos, dict):
        raise ErrorConfiguracion(f"el secreto `{secreto}` no es un objeto JSON")
    return datos


def credenciales_admin(entorno: str, sesion: Any = None) -> tuple[str, str]:
    """`(correo, contraseña)` del admin (backend §5.11): `VALIDACION_ADMIN_CORREO` y `VALIDACION_ADMIN_PASSWORD`; si
    falta alguna y el entorno es `dev`, las claves `correo` y `password` del secreto `admin-inicial`."""
    correo = os.environ.get("VALIDACION_ADMIN_CORREO", "").strip()
    password = os.environ.get("VALIDACION_ADMIN_PASSWORD", "")
    if correo and password:
        return correo, password
    if entorno == "dev" and sesion is not None:
        datos = leer_secreto(sesion, SECRETO_ADMIN)
        correo, password = str(datos.get("correo", "")).strip(), str(datos.get("password", ""))
        if not (correo and password):
            raise ErrorConfiguracion(f"el secreto `{SECRETO_ADMIN}` no tiene las claves `correo` y `password`")
        return correo, password
    raise ErrorConfiguracion("faltan VALIDACION_ADMIN_CORREO y VALIDACION_ADMIN_PASSWORD")


# --- Cliente de la API (BE-1.3) -----------------------------------------------------------------------------------
PAUSA_LOGIN_S = 0.6  # throttling de POST /v1/auth/login en dev: 2 req/s, ráfaga 5 (infra §5.10)
ESPERAS_429_S = (1.0, 2.0, 4.0, 8.0)
#: `500 {"message": "Internal Server Error"}` de API Gateway = `api` sin instancias en Cloud Map (infra §5.13): la
#: petición no llegó al backend y repetirla es seguro. Los 500 del backend (formato §5.1) no se repiten.
ESPERAS_500_GW_S = (2.0, 4.0, 8.0)
TIMEOUT_HTTP_S = 15.0


def es_respuesta_api_gateway(respuesta: Any) -> bool:
    """¿La generó API Gateway (`{"message": …}`, infra §5.13) y no el backend (`{"error": …}`, backend §5.1)?"""
    try:
        cuerpo = respuesta.json()
    except ValueError:
        return False
    return isinstance(cuerpo, dict) and "message" in cuerpo and "error" not in cuerpo


def codigo_error(respuesta: Any) -> str | None:
    """`error.codigo` de una respuesta con el formato del backend (§5.1); `None` si no lo tiene."""
    try:
        cuerpo = respuesta.json()
    except ValueError:
        return None
    error = cuerpo.get("error") if isinstance(cuerpo, dict) else None
    return error.get("codigo") if isinstance(error, dict) else None


def describir_respuesta(respuesta: Any) -> str:
    """`401 CREDENCIALES_INVALIDAS`, `429 (API Gateway)` o `502`: para los detalles, sin el cuerpo."""
    if es_respuesta_api_gateway(respuesta):
        return f"{respuesta.status_code} (API Gateway)"
    codigo = codigo_error(respuesta)
    return f"{respuesta.status_code} {codigo}" if codigo else str(respuesta.status_code)


class ClienteApi:
    """Peticiones a la API del backend con los reintentos que exige `dev` (backend §5.11).

    - `pedir(metodo, ruta, token=None, **kwargs)`: `ruta` relativa a la URL base con `/v1` (p. ej. `/auth/login`);
      con `token`, añade `Authorization: Bearer`. Un `429` **de API Gateway** se reintenta tras 1, 2, 4 y 8 s, y un
      `500` **de API Gateway** (sin instancias de `api`) tras 2, 4 y 8 s; los del backend (formato §5.1), no. Devuelve
      la respuesta de httpx (la última, si los reintentos se agotan). `ultima_duracion_ms` es lo que tardó el último
      intento; `reintentos_429` y `reintentos_500` cuentan los repetidos.
    - `login(correo, password)`: `POST /auth/login`, con al menos `PAUSA_LOGIN_S` entre dos logins (el throttling de
      esa ruta en dev es de 2 req/s). `logins_ok` y `logins_fallidos` cuentan los 200 y los 401.
    - `token(correo, password, quien=…)`: el `token` de un login con 200, o `Falla` con el código recibido.
    Nunca imprime tokens, contraseñas ni cuerpos.
    """

    def __init__(
        self,
        url_base: str,
        *,
        http: Any = None,
        dormir: Callable[[float], None] = time.sleep,
        reloj: Callable[[], float] = time.monotonic,
    ) -> None:
        self.url_base = url_base.rstrip("/")
        self._http = http
        self.dormir = dormir
        self.reloj = reloj
        self._ultimo_login: float | None = None
        self.reintentos_429 = 0
        self.reintentos_500 = 0
        self.ultima_duracion_ms: int | None = None
        self.logins_ok = 0
        self.logins_fallidos = 0

    @property
    def http(self) -> Any:
        if self._http is None:
            import httpx

            self._http = httpx.Client(timeout=TIMEOUT_HTTP_S, follow_redirects=False)
        return self._http

    def pedir(self, metodo: str, ruta: str, *, token: str | None = None, **kwargs: Any) -> Any:
        encabezados = dict(kwargs.pop("headers", None) or {})
        if token is not None:
            encabezados["Authorization"] = f"Bearer {token}"
        esperas = {429: list(ESPERAS_429_S), 500: list(ESPERAS_500_GW_S)}
        while True:
            inicio = self.reloj()
            respuesta = self.http.request(metodo, f"{self.url_base}{ruta}", headers=encabezados, **kwargs)
            self.ultima_duracion_ms = int((self.reloj() - inicio) * 1000)
            pendientes = esperas.get(respuesta.status_code)
            if pendientes and es_respuesta_api_gateway(respuesta):
                if respuesta.status_code == 429:
                    self.reintentos_429 += 1
                else:
                    self.reintentos_500 += 1
                self.dormir(pendientes.pop(0))
                continue
            return respuesta

    def login(self, correo: str, password: str) -> Any:
        if self._ultimo_login is not None:
            espera = self._ultimo_login + PAUSA_LOGIN_S - self.reloj()
            if espera > 0:
                self.dormir(espera)
        try:
            respuesta = self.pedir("POST", "/auth/login", json={"identificador": correo, "password": password})
        finally:
            self._ultimo_login = self.reloj()
        if respuesta.status_code == 200:
            self.logins_ok += 1
        elif respuesta.status_code == 401:
            self.logins_fallidos += 1
        return respuesta

    def token(self, correo: str, password: str, *, quien: str = "el usuario") -> str:
        respuesta = self.login(correo, password)
        if respuesta.status_code == 404:
            raise Falla(f"POST /v1/auth/login respondió 404: ¿está desplegado BE-1.3? (login de {quien})")
        if respuesta.status_code != 200:
            raise Falla(f"el login de {quien} respondió {describir_respuesta(respuesta)}")
        token = respuesta.json().get("token")
        if not isinstance(token, str) or not token:
            raise Falla(f"el login de {quien} respondió 200 sin `token`")
        return token

    def cerrar(self) -> None:
        if self._http is not None:
            self._http.close()


# --- Comandos de la CLI y SQL en local o dev (BE-1.3) ---------------------------------------------------------------
SERVICIO_API = "api"
#: Servicio de `docker compose` con el que se corre la CLI en `local`, según la familia que se usaría en `dev`.
SERVICIO_COMPOSE = {FAMILIA_MIGRATE: "api", FAMILIA_WORKER: "worker"}
CLI_COMPOSE = ["docker", "compose", "run", "--rm", "-T"]
PSQL_COMPOSE = ["docker", "compose", "exec", "-T", "db", "psql", "-U", "campus_app", "-d", "campus_locator", "-tAc"]
#: Eventos de la CLI (§5.10) que explican un código distinto de 0, en orden de preferencia.
EVENTOS_DE_FALLO = (
    "base_no_disponible",
    "configuracion_incompleta",
    "comando_fallido",
    "usuario_rechazado",
    "usuario_no_encontrado",
    "migracion_fallida",
    "verificacion_fallida",
    "limpieza_rechazada",
    "s3_fallido",
)


def motivo_cli(resultado: ResultadoTarea) -> str:
    """Por qué un `python -m app.cli` no terminó con 0, a partir de sus eventos (sin secretos)."""
    for nombre in EVENTOS_DE_FALLO:
        for evento in resultado.eventos(nombre):
            extra = evento.get("motivo") or ", ".join(evento.get("faltan", []))
            return f"{nombre}: {extra}".rstrip(": ")[:300]
    if resultado.codigo is None:
        return f"la tarea no llegó a ejecutar el contenedor ({resultado.motivo or 'sin motivo'})"
    return resultado.motivo[:300] if resultado.motivo else "sin eventos en el log"


class EntornoBackend:
    """`python -m app.cli …` y consultas SQL de solo lectura en el entorno del validador (backend §5.11).

    - `local`: `docker compose run --rm -T [-e VAR…] api python -m app.cli …` y `docker compose exec -T db psql …`,
      desde `project/` (el compose tiene que estar levantado).
    - `dev`: tarea suelta con la última revisión de `campus-locator-dev-migrate` (que tiene que llevar la misma imagen
      que el servicio `api`: si no, `Falla`, porque `backend.yml` no terminó) y, para SQL, con
      `campus-locator-dev-validacion` (`psql -tAc`).

    `cli(argumentos, entorno=None, familia=FAMILIA_MIGRATE)` devuelve un `ResultadoTarea` (`codigo`, `lineas`,
    `eventos()`); los valores de `entorno` llegan al proceso sin pasar por la línea de comandos en local y como
    `environment` del *override* en dev. Con `familia=FAMILIA_WORKER` (BE-2.1, `limpiar-validacion`) usa la última
    revisión de `campus-locator-dev-worker` (también con la imagen de `api`) y, en local, el servicio `worker`.
    `log_completo(codigo, lineas)` (dev) hace que la lectura del log reintente hasta que sea cierto (p. ej.
    `fin_limpieza`: la línea `LIMPIEZA {…}` llega después del evento JSON).
    `sql(consulta)` devuelve las líneas de `psql` o lanza `Falla` si `psql` no termina con 0.
    """

    def __init__(
        self,
        entorno: str,
        *,
        sesion: Any = None,
        outputs: Callable[[], dict[str, Any]] | None = None,
        iniciada_por: str = "validacion",
        dormir: Callable[[float], None] = time.sleep,
    ) -> None:
        self.entorno = entorno
        self.sesion = sesion
        self._outputs = outputs or outputs_terraform
        self.iniciada_por = iniciada_por
        self.dormir = dormir
        self._clientes: dict[str, Any] = {}
        self._revisiones: dict[str, str] = {}

    def aws(self, servicio: str) -> Any:
        if servicio not in self._clientes:
            self._clientes[servicio] = self.sesion.client(servicio)
        return self._clientes[servicio]

    def imagen(self, definicion: str) -> tuple[str, str]:
        """(ARN de la revisión, imagen del contenedor `app`) de una familia o revisión."""
        datos = self.aws("ecs").describe_task_definition(taskDefinition=definicion)["taskDefinition"]
        contenedores = {c.get("name"): c for c in datos.get("containerDefinitions", [])}
        exigir(CONTENEDOR in contenedores, f"{definicion} no tiene contenedor `{CONTENEDOR}`")
        return datos["taskDefinitionArn"], contenedores[CONTENEDOR].get("image", "")

    def revision(self, familia: str = FAMILIA_MIGRATE) -> str:
        """ARN de la última revisión de `familia`, que debe usar la misma imagen que el servicio `api` (si no,
        `Falla`: `backend.yml` no terminó)."""
        if familia not in self._revisiones:
            arn, imagen = self.imagen(familia)
            servicios = self.aws("ecs").describe_services(cluster=CLUSTER, services=[SERVICIO_API])["services"]
            exigir(servicios, f"el servicio `{SERVICIO_API}` no aparece en `{CLUSTER}`")
            desplegada = self.imagen(servicios[0]["taskDefinition"])[1]
            exigir(
                imagen == desplegada,
                f"{arn.rsplit('/', 1)[-1]} y el servicio `api` usan imágenes distintas: ¿terminó backend.yml en main?",
            )
            self._revisiones[familia] = arn
        return self._revisiones[familia]

    def revision_migrate(self) -> str:
        return self.revision(FAMILIA_MIGRATE)

    def cli(
        self,
        argumentos: Sequence[str],
        *,
        entorno: Mapping[str, str] | None = None,
        familia: str = FAMILIA_MIGRATE,
        log_completo: Callable[[int | None, list[str]], bool] | None = None,
    ) -> ResultadoTarea:
        comando = ["python", "-m", "app.cli", *argumentos]
        if self.entorno == "local":
            variables = [parte for nombre in (entorno or {}) for parte in ("-e", nombre)]
            servicio = SERVICIO_COMPOSE.get(familia, SERVICIO_API)
            proceso = ejecutar_proceso(
                [*CLI_COMPOSE, *variables, servicio, *comando], cwd=RAIZ_PROYECTO, entorno=entorno
            )
            error = [linea for linea in proceso.stderr.splitlines() if linea.strip()]
            return ResultadoTarea(
                arn="local",
                definicion="docker compose",
                codigo=proceso.returncode,
                motivo=error[-1].strip() if error else "",
                lineas=proceso.stdout.splitlines(),
            )
        return lanzar_tarea(
            self.aws("ecs"),
            self.aws("logs"),
            definicion=self.revision(familia),
            red=red_tareas(self._outputs()),
            familia=familia,
            comando=comando,
            iniciada_por=self.iniciada_por,
            dormir=self.dormir,
            entorno=entorno,
            log_completo=log_completo,
        )

    def sql(self, consulta: str) -> list[str]:
        if self.entorno == "local":
            proceso = ejecutar_proceso([*PSQL_COMPOSE, consulta], cwd=RAIZ_PROYECTO)
            codigo, lineas, motivo = proceso.returncode, proceso.stdout.splitlines(), proceso.stderr
        else:
            resultado = lanzar_tarea(
                self.aws("ecs"),
                self.aws("logs"),
                definicion=FAMILIA_VALIDACION,
                red=red_tareas(self._outputs()),
                familia=FAMILIA_VALIDACION,
                comando=["psql", "-tAc", consulta],
                iniciada_por=self.iniciada_por,
                dormir=self.dormir,
            )
            codigo, lineas, motivo = resultado.codigo, resultado.lineas, resultado.motivo
        if codigo != 0:
            texto = [linea.strip() for linea in (motivo or "\n".join(lineas)).splitlines() if linea.strip()]
            raise Falla(f"psql terminó con {codigo}: {(texto[-1] if texto else 'sin salida')[:200]}")
        return lineas


# --- JPEG sintético (BE-2.1) ----------------------------------------------------------------------------------------
#: Tabla de Huffman DC de luminancia estándar (JPEG, anexo K.3): longitudes 1–16 y símbolos (categorías 0–11).
_DC_BITS = (0, 1, 5, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0)
_DC_VALORES = tuple(range(12))


def _codigos_huffman(bits: Sequence[int], valores: Sequence[int]) -> dict[int, tuple[int, int]]:
    """`{símbolo: (código, longitud)}` canónicos a partir de las longitudes (JPEG, anexo C)."""
    codigos, codigo, k = {}, 0, 0
    for longitud, cuantos in enumerate(bits, start=1):
        for _ in range(cuantos):
            codigos[valores[k]] = (codigo, longitud)
            codigo, k = codigo + 1, k + 1
        codigo <<= 1
    return codigos


def jpeg_sintetico(ancho: int = 1024, alto: int = 768, semilla: int = 0) -> bytes:
    """JPEG *baseline* en escala de grises, sin Pillow: cada bloque de 8×8 tiene un tono uniforme (solo el coeficiente
    DC; los AC son cero y se codifican con un EOB de un bit). Decodificable por libjpeg/Pillow; la misma `semilla` da
    los mismos bytes y semillas distintas, imágenes (y ETag) distintas. 1024×768 ocupa unos 10–20 KB."""
    import math
    import random

    azar = random.Random(semilla)  # noqa: S311 (imagen de prueba, no criptografía)
    fase_x, fase_y = azar.uniform(0, 6.3), azar.uniform(0, 6.3)
    bloques_x, bloques_y = math.ceil(ancho / 8), math.ceil(alto / 8)
    dc = _codigos_huffman(_DC_BITS, _DC_VALORES)
    salida = bytearray()
    acumulado, n_bits = 0, 0

    def escribir(codigo: int, longitud: int) -> None:
        nonlocal acumulado, n_bits
        acumulado, n_bits = (acumulado << longitud) | codigo, n_bits + longitud
        while n_bits >= 8:
            n_bits -= 8
            byte = (acumulado >> n_bits) & 0xFF
            salida.append(byte)
            if byte == 0xFF:  # relleno obligatorio dentro de los datos codificados
                salida.append(0x00)
        acumulado &= (1 << n_bits) - 1

    anterior = 0
    for by in range(bloques_y):
        for bx in range(bloques_x):
            # Tono del bloque (−128…127 tras restar 128): ondas suaves más ruido de la semilla.
            tono = 70 * math.sin(bx / 9 + fase_x) + 40 * math.cos(by / 6 + fase_y) + azar.randint(-15, 15)
            valor = max(-128, min(127, round(tono)))  # con cuantización DC = 8, el coeficiente cuantizado es el tono
            diferencia, anterior = valor - anterior, valor
            categoria = abs(diferencia).bit_length()
            escribir(*dc[categoria])
            if categoria:
                escribir(diferencia if diferencia >= 0 else diferencia + (1 << categoria) - 1, categoria)
            escribir(0, 1)  # EOB con la tabla AC de un solo símbolo (código `0`)
    if n_bits:
        escribir((1 << (8 - n_bits)) - 1, 8 - n_bits)  # completar el último byte con unos

    def segmento(marcador: int, datos: bytes) -> bytes:
        return bytes((0xFF, marcador)) + (len(datos) + 2).to_bytes(2, "big") + datos

    cuantizacion = bytes([0x00, 8] + [1] * 63)
    return b"".join(
        [
            b"\xff\xd8",
            segmento(0xE0, b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"),
            segmento(0xDB, cuantizacion),
            segmento(0xC0, bytes([8]) + alto.to_bytes(2, "big") + ancho.to_bytes(2, "big") + bytes([1, 1, 0x11, 0])),
            segmento(0xC4, bytes([0x00, *_DC_BITS, *_DC_VALORES])),
            segmento(0xC4, bytes([0x10, 1] + [0] * 15 + [0x00])),
            segmento(0xDA, bytes([1, 1, 0x00, 0, 63, 0])),
            bytes(salida),
            b"\xff\xd9",
        ]
    )


# --- Recolección: S3, limpieza y recorrido de prueba (BE-2.1) -------------------------------------------------------
PREFIJO_VALIDACION = "validacion-"
ENCABEZADOS_PUT = {"Content-Type": "image/jpeg"}
TIMEOUT_PUT_S = 60.0
#: Líneas de texto que imprime `limpiar-validacion` al terminar con 0 (§5.9).
LINEA_LIMPIEZA, LINEA_SIMULACION = "LIMPIEZA ", "SIMULACION "


def put_prefirmado(http: Any, subida: Mapping[str, Any], cuerpo: bytes, *, que: str) -> Any:
    """`PUT` a `subida["url"]` con **exactamente** `subida["encabezados"]` y `cuerpo`; devuelve la respuesta de httpx
    (`status_code`, `text`). Cualquier excepción → `Falla("PUT de <que>: <clase>")` sin su mensaje, que podría llevar la
    URL prefirmada. `http` es un `httpx.Client` o, en las pruebas, un objeto con `request()`."""
    try:
        return http.request("PUT", subida["url"], headers=dict(subida["encabezados"]), content=cuerpo)
    except Exception as exc:
        raise Falla(f"PUT de {que}: {type(exc).__name__} (sin respuesta de S3)") from None


def _error_s3(exc: Exception, que: str) -> Exception:
    if es_acceso_denegado(exc) or codigo_error_aws(exc) in {"403", "Forbidden"}:
        return ErrorConfiguracion(f"sin permiso para {que}: {codigo_error_aws(exc)}")
    return Falla(f"{que}: {codigo_error_aws(exc) or _resumen(exc)}")


def head_objeto(s3: Any, bucket: str, clave: str) -> dict[str, Any] | None:
    """`head-object`: la respuesta (`ContentType`, `ContentLength`…) o `None` si no existe (404). 403 →
    `ErrorConfiguracion` (a quien valida le falta `s3:GetObject` o `s3:ListBucket`); otro error → `Falla`."""
    from botocore.exceptions import ClientError

    try:
        return s3.head_object(Bucket=bucket, Key=clave)
    except ClientError as exc:
        if codigo_error_aws(exc) in {"404", "NoSuchKey", "NotFound"}:
            return None
        raise _error_s3(exc, f"head-object {clave}") from None


def claves_s3(s3: Any, bucket: str, prefijo: str) -> list[str]:
    """Claves bajo `prefijo` (`list-objects-v2`, todas las páginas). Sin permiso → `ErrorConfiguracion`; otro error →
    `Falla`."""
    from botocore.exceptions import ClientError

    claves: list[str] = []
    try:
        for pagina in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefijo):
            claves += [objeto["Key"] for objeto in pagina.get("Contents", [])]
    except ClientError as exc:
        raise _error_s3(exc, f"list-objects-v2 {prefijo}") from None
    return claves


def comprobar_bucket(s3: Any, bucket: str) -> str:
    """Precondición de S3 de un validador: `head-bucket`, `list-objects-v2 --max-keys 1` en `dataset/` y `head-object`
    de una clave que no existe (404 esperado). Bucket inexistente → `PrecondicionNoCumplida` (INF-1.2); permisos →
    `ErrorConfiguracion`. Devuelve el detalle."""
    import uuid

    from botocore.exceptions import ClientError

    try:
        s3.head_bucket(Bucket=bucket)
    except ClientError as exc:
        if codigo_error_aws(exc) in {"404", "NoSuchBucket", "NotFound"}:
            raise PrecondicionNoCumplida(f"INF-1.2: no existe el bucket {bucket}") from None
        raise _error_s3(exc, f"head-bucket {bucket}") from None
    try:
        s3.list_objects_v2(Bucket=bucket, Prefix="dataset/", MaxKeys=1)
    except ClientError as exc:
        raise _error_s3(exc, f"list-objects-v2 en {bucket}") from None
    sonda = f"dataset/{PREFIJO_VALIDACION}sonda-{uuid.uuid4()}.jpg"
    exigir(head_objeto(s3, bucket, sonda) is None, f"la clave de sonda {sonda} existe")
    return f"bucket {bucket}: head-bucket, list-objects-v2 y head-object (404) permitidos"


def hora_s3(s3: Any, bucket: str) -> datetime:
    """Hora de S3: el encabezado `Date` (resolución de 1 s) de un `head-bucket`. `Falla` si no viene."""
    from email.utils import parsedate_to_datetime

    respuesta = s3.head_bucket(Bucket=bucket)
    fecha = (respuesta.get("ResponseMetadata", {}).get("HTTPHeaders") or {}).get("date")
    if not fecha:
        raise Falla("head-bucket no devolvió el encabezado Date")
    return parsedate_to_datetime(fecha).astimezone(UTC)


def desfase_s3_s(s3: Any, bucket: str, ahora: Callable[[], datetime]) -> float:
    """Segundos que hay que sumar al reloj local para tener la hora de S3 (positivo si el local va atrasado, como pasa
    en WSL tras suspender el equipo). Precisión ±1 s."""
    return (hora_s3(s3, bucket) - ahora()).total_seconds()


def _eventos_de(lineas: Iterable[str]) -> list[dict[str, Any]]:
    encontrados = []
    for linea in lineas:
        try:
            datos = json.loads(linea)
        except ValueError:
            continue
        if isinstance(datos, dict):
            encontrados.append(datos)
    return encontrados


def fin_limpieza(codigo: int | None, lineas: Sequence[str]) -> bool:
    """¿Está entero el log de un `limpiar-validacion`? Con 0, cuando aparece la línea `LIMPIEZA`/`SIMULACION` (se
    imprime después del evento JSON); con otro código, cuando aparece su evento de fallo; sin código, ya."""
    if codigo is None or any(linea.startswith((LINEA_LIMPIEZA, LINEA_SIMULACION)) for linea in lineas):
        return True
    return codigo != 0 and any(e.get("evento") in EVENTOS_DE_FALLO for e in _eventos_de(lineas))


def limpiar_videos(
    backend: EntornoBackend, video_ids: Sequence[str] | None = None, *, simular: bool = False
) -> ResultadoTarea:
    """`limpiar-validacion [--video ID …] [--simular]` con la definición de `worker` (`backend.cli`), leyendo el log
    hasta `fin_limpieza`. `video_ids=None` = sin `--video` (todos los `validacion-`); una lista vacía no lanza nada y
    devuelve un resultado con código 0 y sin líneas (nunca equivale a «todos»)."""
    if video_ids is not None and not video_ids:
        return ResultadoTarea(arn="no-lanzada", definicion="", codigo=0, motivo="sin videos")
    argumentos = ["limpiar-validacion"]
    for video_id in video_ids or []:
        argumentos += ["--video", str(video_id)]
    if simular:
        argumentos.append("--simular")
    return backend.cli(argumentos, familia=FAMILIA_WORKER, log_completo=fin_limpieza)


def linea_limpieza(tarea: ResultadoTarea, prefijo: str = LINEA_LIMPIEZA) -> dict[str, Any] | None:
    """El JSON de la línea `LIMPIEZA {…}` (o `SIMULACION {…}`) del log, o `None` si no está o no es JSON."""
    for linea in tarea.lineas:
        if linea.startswith(prefijo):
            try:
                datos = json.loads(linea.removeprefix(prefijo))
            except ValueError:
                return None
            return datos if isinstance(datos, dict) else None
    return None


def videos_validacion(api: ClienteApi, token: str) -> list[dict[str, Any]]:
    """Los `VideoResumen` con `nombre` **y** `ref_cliente` que empiezan por `validacion-` (lo mismo que borraría
    `limpiar-validacion` sin `--video`), recorriendo todas las páginas de `GET /v1/admin/videos?q=validacion-`. Un
    estado distinto de 200 → `Falla`."""
    encontrados: list[dict[str, Any]] = []
    pagina = 1
    while True:
        r = api.pedir(
            "GET", "/admin/videos", token=token, params={"q": PREFIJO_VALIDACION, "pagina": pagina, "por_pagina": 100}
        )
        exigir(r.status_code == 200, f"GET /v1/admin/videos?q={PREFIJO_VALIDACION}: {describir_respuesta(r)}")
        cuerpo = r.json()
        encontrados += [
            v
            for v in cuerpo.get("items", [])
            if str(v.get("nombre", "")).startswith(PREFIJO_VALIDACION)
            and str(v.get("ref_cliente", "")).startswith(PREFIJO_VALIDACION)
        ]
        if pagina * int(cuerpo.get("por_pagina") or 100) >= int(cuerpo.get("total") or 0):
            return encontrados
        pagina += 1


def borrar_restos(api: ClienteApi, token: str, backend: EntornoBackend) -> str:
    """Preparación de los validadores que crean videos: si hay restos `validacion-` (`videos_validacion`), lanza
    `limpiar-validacion` sin `--video`. Devuelve el detalle; `Falla` si la tarea no termina con 0."""
    restos = videos_validacion(api, token)
    if not restos:
        return "sin restos validacion- de ejecuciones anteriores"
    tarea = limpiar_videos(backend, None)
    exigir(tarea.codigo == 0, f"limpiar-validacion terminó con {tarea.codigo}: {motivo_cli(tarea)}")
    resumen = linea_limpieza(tarea)
    if resumen is None:
        return f"restos borrados: {len(restos)} videos (la tarea salió con 0; sin línea LIMPIEZA en el log)"
    return f"restos borrados: {json.dumps(resumen)}"


class RecorridoPrueba:
    """Un video de prueba `validacion-…` y sus fotos, por la API de §5.4 y los `PUT` prefirmados.

    - `RecorridoPrueba(api, token, nombre, total_fotos=4, http_s3=None, lat=1.0, lng=-100.0, semilla=0)`: `token` es
      una función que devuelve el token del admin; `nombre` se usa también como `ref_cliente` (lleva el prefijo).
    - `crear()` → respuesta de `POST /collect/videos` (con 201 o 200 guarda `video`; su `id` en `video_id`).
    - `registrar(ordenes)` → respuesta de `POST …/images`; con 200 guarda cada elemento en `registro[orden]`.
    - `subir(orden, subida=None)` → respuesta del `PUT` (por defecto con la `subida` de `registro[orden]` y
      `foto(orden)`); con 200 añade `orden` a `subidas`. Sin `subida` → `Falla`.
    - `asegurar_subidas(ordenes)`: registra (pidiendo URL nueva) y sube las que no estén en `subidas`; `Falla` si una
      respuesta no es 200. Para validadores que solo necesitan fotos subidas (BE-2.2).
    - `completar()` → respuesta de `POST …/complete`. `foto(orden)` → `jpeg_sintetico` (1024×768, semilla
      `semilla * 1000 + orden`); `elemento(orden)` → el elemento de `images` (rumbo 0/90/180/270, `bytes` reales).
    - `cerrar()` cierra el cliente de los `PUT` (lo crea con 60 s si no se pasó `http_s3`).
    """

    RUMBOS = (0.0, 90.0, 180.0, 270.0)

    def __init__(
        self,
        api: ClienteApi,
        token: Callable[[], str],
        nombre: str,
        *,
        total_fotos: int = 4,
        http_s3: Any = None,
        lat: float = 1.0,
        lng: float = -100.0,
        semilla: int = 0,
    ) -> None:
        exigir(
            nombre.startswith(PREFIJO_VALIDACION), f"el nombre de un video de prueba empieza por {PREFIJO_VALIDACION}"
        )
        self.api, self.token, self.nombre = api, token, nombre
        self.total_fotos, self.lat, self.lng, self.semilla = total_fotos, lat, lng, semilla
        self._http_s3 = http_s3
        self.video: dict[str, Any] | None = None
        self.registro: dict[int, dict[str, Any]] = {}
        self.subidas: set[int] = set()
        self._fotos: dict[int, bytes] = {}

    @property
    def video_id(self) -> str:
        exigir(self.video is not None, f"el video {self.nombre} no se ha creado")
        return str(self.video["id"])

    @property
    def http_s3(self) -> Any:
        if self._http_s3 is None:
            import httpx

            self._http_s3 = httpx.Client(timeout=TIMEOUT_PUT_S, follow_redirects=False)
        return self._http_s3

    def cuerpo(self) -> dict[str, Any]:
        return {
            "ref_cliente": self.nombre,
            "nombre": self.nombre,
            "iniciado_en": "2026-10-20T14:00:00Z",
            "finalizado_en": "2026-10-20T14:02:00Z",
            "duracion_s": 120,
            "distancia_m": 85.5,
            "pasos": 110,
            "inicio": {"lat": self.lat, "lng": self.lng, "rumbo": 0.0},
            "total_fotos": self.total_fotos,
            "dispositivo": "validador",
            "app_version": "validacion",
        }

    def crear(self) -> Any:
        r = self.api.pedir("POST", "/collect/videos", token=self.token(), json=self.cuerpo())
        if r.status_code in (200, 201):
            self.video = r.json()
        return r

    def foto(self, orden: int) -> bytes:
        if orden not in self._fotos:
            self._fotos[orden] = jpeg_sintetico(1024, 768, semilla=self.semilla * 1000 + orden)
        return self._fotos[orden]

    def elemento(self, orden: int) -> dict[str, Any]:
        return {
            "orden": orden,
            "lat": self.lat + orden * 0.0001,
            "lng": self.lng,
            "rumbo": self.RUMBOS[(orden - 1) % len(self.RUMBOS)],
            "capturada_en": f"2026-10-20T14:00:{orden % 60:02d}Z",
            "bytes": len(self.foto(orden)),
        }

    def registrar(self, ordenes: Sequence[int]) -> Any:
        r = self.api.pedir(
            "POST",
            f"/collect/videos/{self.video_id}/images",
            token=self.token(),
            json={"imagenes": [self.elemento(o) for o in ordenes]},
        )
        if r.status_code == 200:
            for imagen in r.json().get("imagenes", []):
                self.registro[int(imagen["orden"])] = imagen
        return r

    def subir(self, orden: int, subida: Mapping[str, Any] | None = None) -> Any:
        subida = subida if subida is not None else (self.registro.get(orden) or {}).get("subida")
        exigir(subida, f"la foto {orden} no tiene `subida`")
        r = put_prefirmado(self.http_s3, subida, self.foto(orden), que=f"la foto {orden} de {self.nombre}")
        if r.status_code == 200:
            self.subidas.add(orden)
        return r

    def asegurar_subidas(self, ordenes: Sequence[int]) -> None:
        faltan = [o for o in ordenes if o not in self.subidas]
        if not faltan:
            return
        r = self.registrar(faltan)
        exigir(r.status_code == 200, f"POST …/images: {describir_respuesta(r)}")
        for orden in faltan:
            if self.registro[orden].get("subida") is None:  # ya estaba en S3 (HEAD) o procesada
                self.subidas.add(orden)
                continue
            r = self.subir(orden)
            exigir(r.status_code == 200, f"PUT de la foto {orden}: {r.status_code}, se esperaba 200")

    def completar(self) -> Any:
        return self.api.pedir("POST", f"/collect/videos/{self.video_id}/complete", token=self.token())

    def cerrar(self) -> None:
        if self._http_s3 is not None:
            self._http_s3.close()


# --- Usuario de prueba `validacion+user@campus.edu.co` (backend §5.11) ------------------------------------------------
USUARIO_VALIDACION = "validacion+user@campus.edu.co"
NOMBRE_USUARIO_VALIDACION = "validacion-usuario"


def crear_usuario_validacion(backend: EntornoBackend) -> str:
    """Crea o reactiva el usuario de prueba (rol `user`) con una contraseña aleatoria `validacion-pw-<uuid>`, que pasa
    en `CREAR_USUARIO_PASSWORD` y devuelve (nunca se imprime). `Falla` si `crear-usuario` no termina con 0."""
    import uuid

    password = f"validacion-pw-{uuid.uuid4()}"
    resultado = backend.cli(
        ["crear-usuario", "--correo", USUARIO_VALIDACION, "--nombre", NOMBRE_USUARIO_VALIDACION, "--rol", "user"],
        entorno={"CREAR_USUARIO_PASSWORD": password},
    )
    if resultado.codigo != 0:
        raise Falla(f"crear-usuario terminó con {resultado.codigo}: {motivo_cli(resultado)}")
    return password


def desactivar_usuario_validacion(backend: EntornoBackend, *, tolerar_inexistente: bool = False) -> str:
    """`desactivar-usuario` del usuario de prueba; devuelve un detalle corto o lanza `Falla`.

    Con `tolerar_inexistente` (la limpieza), que el usuario no exista (código 1 con `usuario_no_encontrado`: el
    `crear-usuario` falló antes de crearlo) no es un fallo."""
    resultado = backend.cli(["desactivar-usuario", "--correo", USUARIO_VALIDACION])
    if tolerar_inexistente and resultado.codigo == 1 and resultado.eventos("usuario_no_encontrado"):
        return f"{USUARIO_VALIDACION} no existe: nada que desactivar"
    if resultado.codigo != 0:
        raise Falla(f"desactivar-usuario terminó con {resultado.codigo}: {motivo_cli(resultado)}")
    evento = next(iter(resultado.eventos("usuario_desactivado")), {})
    previo = " (ya lo estaba)" if evento.get("ya_estaba_inactivo") else ""
    return f"{USUARIO_VALIDACION} desactivado{previo}"


# --- `embedding` en dev y colas (BE-2.2; infra §5.10 y §5.11) ---------------------------------------------------------
#: Colombia no tiene horario de verano: America/Bogota es UTC−5 todo el año (sin depender de tzdata en Windows).
ZONA_BOGOTA = timezone(timedelta(hours=-5), "America/Bogota")
HORA_APAGADO_NOCHE = 22  # acciones `*-apagar-noche` (infra §5.10)
SERVICIO_EMBEDDING = "embedding"
SERVICIO_WORKER = "worker"
ALARMA_INACTIVIDAD = "campus-locator-dev-embedding-inactivo"
POLITICA_WORKER_COLA = "campus-locator-dev-worker-cola"
ACCION_NOCHE_EMBEDDING = "campus-locator-dev-embedding-apagar-noche"
METRICA_ESPACIO = "campus-locator/dev"
METRICA_ENCENDIDOS = "EmbeddingEncendidos"
LIMITE_ALARMA_S = 300  # paso 3 del contrato: hasta 5 min a la muestra y a la alarma
LIMITE_ENCENDIDO_S = 600  # paso 5: hasta 10 min desde el paso 1
PAUSA_SONDEO_S = 15.0
LOG_WORKER = "/campus-locator/dev/worker"
#: Errores de AWS que, mientras `embedding` arranca, significan «todavía no» y no un fallo (BE-2.2, 0.9.1): los límites
#: de peticiones e `InstanceNotFound` (desde 0.9.2 ya no se llama a `get-instances-health-status`, que lo daba siempre).
CODIGOS_TODAVIA_NO = frozenset(
    {"InstanceNotFound", "ThrottlingException", "Throttling", "TooManyRequestsException", "RequestLimitExceeded"}
)


def ips_privadas(tarea: Mapping[str, Any]) -> set[str]:
    """IPs privadas de una tarea de `describe-tasks` (Fargate, `awsvpc`): el detalle `privateIPv4Address` de sus
    *attachments* `ElasticNetworkInterface`. Vacío si no las trae."""
    return {
        str(d.get("value"))
        for a in tarea.get("attachments", [])
        if a.get("type") == "ElasticNetworkInterface"
        for d in a.get("details", [])
        if d.get("name") == "privateIPv4Address" and d.get("value")
    }


def hora_bogota(ahora: datetime | None = None) -> datetime:
    return (ahora or datetime.now(UTC)).astimezone(ZONA_BOGOTA)


def recurso_ecs(servicio: str) -> str:
    """`ResourceId` de Application Auto Scaling de un servicio del clúster."""
    return f"service/{CLUSTER}/{servicio}"


def embedding_en_api(api: ClienteApi) -> str | None:
    """El campo `embedding` de `GET /v1/health/ready` (`ok` | `no_disponible`), o `None` si no respondió 200."""
    try:
        r = api.pedir("GET", "/health/ready")
    except Exception:
        return None
    if r.status_code != 200:
        return None
    try:
        return r.json().get("embedding")
    except ValueError:
        return None


def _errores_aws(exc: Exception, que: str) -> Exception:
    if es_acceso_denegado(exc):
        return ErrorConfiguracion(f"sin permiso para {que} ({codigo_error_aws(exc)})")
    return Falla(f"{que}: {type(exc).__name__} {codigo_error_aws(exc)}".strip())


class EmbeddingDev:
    """Encender y apagar `embedding` en `dev` con el contrato de infra §5.10 (lo que hace `embedding.py` de infra,
    reescrito aquí: las carpetas no comparten código de validación, infra §5.11).

    - `comprobar_inf21()` → detalle: objetivos escalables de `embedding` y `worker`, la política
      `campus-locator-dev-worker-cola` y la acción `campus-locator-dev-embedding-apagar-noche`; si falta algo,
      `PrecondicionNoCumplida` (INF-2.1).
    - `servicio(nombre)` → el `describe-services` de `embedding` o `worker` (`desiredCount`, `runningCount`…).
    - `latido()`: `PutMetricData` de `EmbeddingEncendidos` = 1 (`Count`, sin dimensiones, con marca de tiempo
      explícita) en `campus-locator/dev`. Devuelve la marca.
    - `encender(listo_en_api)` → segundos: pasos 1–5 del contrato (rango 0-1 de `embedding` y `worker`, latido,
      esperar a que `GetMetricStatistics` lo vea, un minuto más y la alarma `embedding-inactivo` fuera de `ALARM`
      —hasta 5 min—, `desiredCount = 1`, y hasta 10 min desde el paso 1 a tarea `HEALTHY`, despliegue `COMPLETED` e
      instancia sana en Cloud Map) y, además, hasta 2 min más a que `listo_en_api()` sea cierto (`api` lo ve por DNS).
      Si no llega: `Falla`. «Instancia en Cloud Map» = la IP privada de la tarea `HEALTHY` en `AWS_INSTANCE_IPV4` de
      `servicediscovery list-instances` (el servicio de Cloud Map no tiene configuración de salud). Mientras espera,
      los límites de peticiones de AWS (`CODIGOS_TODAVIA_NO`) son «todavía no», no un error (`_sondear`).
    - `apagar()`: rango 0-0 y `desiredCount = 0` de `embedding` y `worker` (no espera a que paren).
    - `poner(nombre, n)`: solo `UpdateService` (C3a de BE-2.2 apaga `embedding` así, sin tocar los rangos).
    """

    def __init__(
        self,
        sesion: Any,
        *,
        dormir: Callable[[float], None] = time.sleep,
        reloj: Callable[[], datetime] = lambda: datetime.now(UTC),
        avisar: Callable[[str], None] | None = None,
    ) -> None:
        self.sesion = sesion
        self.dormir = dormir
        self.reloj = reloj
        self.avisar = avisar or (lambda texto: print(texto, file=sys.stderr, flush=True))
        self._clientes: dict[str, Any] = {}

    def aws(self, servicio: str) -> Any:
        if servicio not in self._clientes:
            self._clientes[servicio] = self.sesion.client(servicio)
        return self._clientes[servicio]

    # -- lectura ---------------------------------------------------------------------------------------------------
    def servicio(self, nombre: str) -> dict[str, Any]:
        try:
            servicios = self.aws("ecs").describe_services(cluster=CLUSTER, services=[nombre])["services"]
        except Exception as exc:
            raise _errores_aws(exc, f"ecs describe-services {nombre}") from None
        if not servicios:
            raise PrecondicionNoCumplida(f"INF-1.3: no existe el servicio `{nombre}` en `{CLUSTER}`")
        return servicios[0]

    def comprobar_inf21(self) -> str:
        escalado = self.aws("application-autoscaling")
        try:
            objetivos = escalado.describe_scalable_targets(
                ServiceNamespace="ecs", ResourceIds=[recurso_ecs(SERVICIO_EMBEDDING), recurso_ecs(SERVICIO_WORKER)]
            )["ScalableTargets"]
            politicas = escalado.describe_scaling_policies(
                ServiceNamespace="ecs", ResourceId=recurso_ecs(SERVICIO_WORKER)
            )["ScalingPolicies"]
            acciones = escalado.describe_scheduled_actions(
                ServiceNamespace="ecs", ResourceId=recurso_ecs(SERVICIO_EMBEDDING)
            )["ScheduledActions"]
        except Exception as exc:
            raise _errores_aws(exc, "application-autoscaling describe-*") from None
        recursos = {o.get("ResourceId") for o in objetivos}
        faltan = [s for s in (SERVICIO_EMBEDDING, SERVICIO_WORKER) if recurso_ecs(s) not in recursos]
        if faltan:
            raise PrecondicionNoCumplida(f"INF-2.1: sin objetivo escalable de {', '.join(faltan)}")
        if POLITICA_WORKER_COLA not in {p.get("PolicyName") for p in politicas}:
            raise PrecondicionNoCumplida(f"INF-2.1: falta la política `{POLITICA_WORKER_COLA}`")
        if ACCION_NOCHE_EMBEDDING not in {a.get("ScheduledActionName") for a in acciones}:
            raise PrecondicionNoCumplida(f"INF-2.1: falta la acción programada `{ACCION_NOCHE_EMBEDDING}`")
        return f"objetivos de embedding y worker, {POLITICA_WORKER_COLA} y {ACCION_NOCHE_EMBEDDING}"

    @staticmethod
    def _sondear(que: str, llamada: Callable[[], Any]) -> tuple[Any, str | None]:
        """Una llamada de AWS mientras se espera a que `embedding` quede sano: `(respuesta, None)`, o `(None, motivo)`
        si la respuesta significa «todavía no» (`InstanceNotFound` de Cloud Map: la tarea aún no se registró; o un
        límite de peticiones de AWS) y hay que seguir esperando. Un permiso que falta → `ErrorConfiguracion`; otro
        error → `Falla` (nunca una excepción de botocore sin traducir)."""
        try:
            return llamada(), None
        except Exception as exc:
            codigo = codigo_error_aws(exc)
            if codigo in CODIGOS_TODAVIA_NO:
                return None, f"{que}: {codigo} (aún no)"
            raise _errores_aws(exc, que) from None

    def _sano_en_ecs(self) -> str | None:
        """`None` si `embedding` tiene una tarea `HEALTHY`, el despliegue `PRIMARY` `COMPLETED` y esa tarea registrada
        en Cloud Map (`list-instances` con su IP privada; si la tarea no trae IP, basta ≥ 1 instancia); si no, lo que
        falta. El *throttling* es «falta», no un error (`_sondear`)."""
        ecs = self.aws("ecs")
        respuesta, pendiente = self._sondear(
            "ecs describe-services embedding",
            lambda: ecs.describe_services(cluster=CLUSTER, services=[SERVICIO_EMBEDDING]),
        )
        if pendiente:
            return pendiente
        if not respuesta.get("services"):
            raise PrecondicionNoCumplida(f"INF-1.3: no existe el servicio `{SERVICIO_EMBEDDING}` en `{CLUSTER}`")
        datos = respuesta["services"][0]
        primario = next((d for d in datos.get("deployments", []) if d.get("status") == "PRIMARY"), {})
        if primario.get("rolloutState") != "COMPLETED" or int(datos.get("runningCount", 0)) < 1:
            return f"despliegue {primario.get('rolloutState')} con {datos.get('runningCount', 0)} tareas"
        respuesta, pendiente = self._sondear(
            "ecs list-tasks embedding",
            lambda: ecs.list_tasks(cluster=CLUSTER, serviceName=SERVICIO_EMBEDDING, desiredStatus="RUNNING"),
        )
        if pendiente:
            return pendiente
        tareas = respuesta.get("taskArns") or []
        if not tareas:
            return "sin tareas RUNNING"
        respuesta, pendiente = self._sondear(
            "ecs describe-tasks embedding", lambda: ecs.describe_tasks(cluster=CLUSTER, tasks=tareas)
        )
        if pendiente:
            return pendiente
        sanas = [t for t in respuesta.get("tasks", []) if t.get("healthStatus") == "HEALTHY"]  # paradas: `failures`
        if not sanas:
            return f"tareas {[t.get('healthStatus') for t in respuesta.get('tasks', [])]}"
        registros = datos.get("serviceRegistries") or []
        if registros:
            # El servicio de Cloud Map de `embedding` no tiene configuración de salud (comprobado en dev, 0.9.2):
            # `get-instances-health-status` responde `InstanceNotFound` siempre. Se mira que la tarea sana esté
            # registrada: `list-instances` con su IP privada en `AWS_INSTANCE_IPV4`.
            servicio_id = registros[0]["registryArn"].rsplit("/", 1)[-1]
            respuesta, pendiente = self._sondear(
                "servicediscovery list-instances",
                lambda: self.aws("servicediscovery").list_instances(ServiceId=servicio_id),
            )
            if pendiente:
                return pendiente
            registradas = {
                (i.get("Attributes") or {}).get("AWS_INSTANCE_IPV4") for i in respuesta.get("Instances", [])
            } - {None}
            if not respuesta.get("Instances"):
                return "Cloud Map sin instancias registradas"
            ips = {ip for t in sanas for ip in ips_privadas(t)}
            if ips and not ips & registradas:
                return f"Cloud Map sin la IP de la tarea sana ({len(registradas)} instancia(s) con otra IP)"
        return None

    # -- escritura -------------------------------------------------------------------------------------------------
    def _registrar(self, servicio: str, maximo: int) -> None:
        try:
            self.aws("application-autoscaling").register_scalable_target(
                ServiceNamespace="ecs",
                ResourceId=recurso_ecs(servicio),
                ScalableDimension="ecs:service:DesiredCount",
                MinCapacity=0,
                MaxCapacity=maximo,
            )
        except Exception as exc:
            raise _errores_aws(exc, f"register-scalable-target {servicio}") from None

    def poner(self, servicio: str, replicas: int) -> None:
        try:
            self.aws("ecs").update_service(cluster=CLUSTER, service=servicio, desiredCount=replicas)
        except Exception as exc:
            raise _errores_aws(exc, f"ecs update-service {servicio}") from None

    def latido(self) -> datetime:
        marca = self.reloj().astimezone(UTC).replace(microsecond=0)
        try:
            self.aws("cloudwatch").put_metric_data(
                Namespace=METRICA_ESPACIO,
                MetricData=[{"MetricName": METRICA_ENCENDIDOS, "Value": 1.0, "Unit": "Count", "Timestamp": marca}],
            )
        except Exception as exc:
            raise _errores_aws(exc, "cloudwatch put-metric-data") from None
        return marca

    def _muestra_vista(self, marca: datetime) -> bool:
        datos, pendiente = self._sondear(
            "cloudwatch get-metric-statistics",
            lambda: self.aws("cloudwatch").get_metric_statistics(
                Namespace=METRICA_ESPACIO,
                MetricName=METRICA_ENCENDIDOS,
                StartTime=marca - timedelta(minutes=2),
                EndTime=marca + timedelta(minutes=2),
                Period=60,
                Statistics=["Sum"],
            ),
        )
        if pendiente:
            return False
        return any(float(p.get("Sum", 0)) >= 1 for p in datos.get("Datapoints", []))

    def _alarma_en_alarm(self) -> bool:
        datos, pendiente = self._sondear(
            "cloudwatch describe-alarms",
            lambda: self.aws("cloudwatch").describe_alarms(AlarmNames=[ALARMA_INACTIVIDAD]),
        )
        if pendiente:
            return True  # sin respuesta, se sigue esperando como si siguiera en ALARM
        alarmas = datos.get("MetricAlarms", [])
        return bool(alarmas) and alarmas[0].get("StateValue") == "ALARM"

    def _esperar(self, condicion: Callable[[], bool], hasta: datetime) -> bool:
        while True:
            if condicion():
                return True
            if self.reloj() >= hasta:
                return False
            self.dormir(PAUSA_SONDEO_S)

    def encender(self, listo_en_api: Callable[[], bool]) -> float:
        inicio = self.reloj()
        self.avisar("embedding: encendiendo (contrato de infra §5.10)")
        self._registrar(SERVICIO_EMBEDDING, 1)
        self._registrar(SERVICIO_WORKER, 1)
        marca = self.latido()
        limite_alarma = self.reloj() + timedelta(seconds=LIMITE_ALARMA_S)
        exigir(
            self._esperar(lambda: self._muestra_vista(marca), limite_alarma),
            f"CloudWatch no devolvió la muestra de {METRICA_ENCENDIDOS} en {LIMITE_ALARMA_S // 60} min",
        )
        self.dormir(60.0)
        exigir(
            self._esperar(lambda: not self._alarma_en_alarm(), limite_alarma),
            f"la alarma {ALARMA_INACTIVIDAD} siguió en ALARM {LIMITE_ALARMA_S // 60} min tras el latido",
        )
        self.poner(SERVICIO_EMBEDDING, 1)
        falta: dict[str, str | None] = {"que": None}

        def sano() -> bool:
            falta["que"] = self._sano_en_ecs()
            return falta["que"] is None

        exigir(
            self._esperar(sano, inicio + timedelta(seconds=LIMITE_ENCENDIDO_S)),
            f"embedding no quedó sano en {LIMITE_ENCENDIDO_S // 60} min: {falta['que']}",
        )
        exigir(
            self._esperar(listo_en_api, self.reloj() + timedelta(minutes=2)),
            'embedding sano en ECS pero /v1/health/ready no dice "embedding": "ok" tras 2 min',
        )
        segundos = (self.reloj() - inicio).total_seconds()
        self.avisar(f"embedding: encendido en {segundos:.0f} s")
        return segundos

    def apagar(self) -> None:
        self._registrar(SERVICIO_EMBEDDING, 0)
        self._registrar(SERVICIO_WORKER, 0)
        self.poner(SERVICIO_EMBEDDING, 0)
        self.poner(SERVICIO_WORKER, 0)


def mensajes_cola(sqs: Any, url: str) -> tuple[int, int]:
    """`(visibles, en vuelo)` de una cola (`ApproximateNumberOfMessages` y `…NotVisible`: aproximados y con retraso)."""
    try:
        atributos = sqs.get_queue_attributes(
            QueueUrl=url, AttributeNames=["ApproximateNumberOfMessages", "ApproximateNumberOfMessagesNotVisible"]
        )["Attributes"]
    except Exception as exc:
        raise _errores_aws(exc, "sqs get-queue-attributes") from None
    visibles = int(atributos.get("ApproximateNumberOfMessages", 0))
    return visibles, int(atributos.get("ApproximateNumberOfMessagesNotVisible", 0))


def enviar_mensaje(sqs: Any, url: str, cuerpo: Mapping[str, Any]) -> str:
    """`SendMessage` con el cuerpo en JSON; devuelve el `MessageId`."""
    try:
        return sqs.send_message(QueueUrl=url, MessageBody=json.dumps(cuerpo))["MessageId"]
    except Exception as exc:
        raise _errores_aws(exc, "sqs send-message") from None


def eventos_worker(logs: Any, imagen_id: str, desde: datetime) -> list[dict[str, Any]]:
    """Las líneas JSON de `/campus-locator/dev/worker` con `imagen_id` igual al dado, desde `desde`
    (`filter-log-events` con el id entre comillas; todas las páginas)."""
    eventos: list[dict[str, Any]] = []
    argumentos: dict[str, Any] = {
        "logGroupName": LOG_WORKER,
        "startTime": int(desde.timestamp() * 1000),
        "filterPattern": f'"{imagen_id}"',
    }
    try:
        while True:
            pagina = logs.filter_log_events(**argumentos)
            eventos += _eventos_de(e.get("message", "") for e in pagina.get("events", []))
            siguiente = pagina.get("nextToken")
            if not siguiente:
                return [e for e in eventos if e.get("imagen_id") == imagen_id]
            argumentos["nextToken"] = siguiente
    except Exception as exc:
        raise _errores_aws(exc, f"logs filter-log-events {LOG_WORKER}") from None


# --- Estado de otros lotes y diagnóstico de búsqueda (BE-2.4; ARCHITECTURE §5.5 y §5.11) ------------------------------
RUTA_VECINOS = "/admin/diagnostico/vecinos"
LOG_API = "/campus-locator/dev/api"
LOG_EMBEDDING = "/campus-locator/dev/embedding"


def lote_hecho(texto: str, lote: str) -> bool:
    """¿La fila de `lote` en la tabla de estado (§3) de un PLAN dice «Hecho» en su tercera columna? (Una fila de §2.1
    con el mismo id no cuenta.) Lo usan `validate22.py` (EMB-2.1) y `validate24.py` (BE-2.2)."""
    patron = re.compile(rf"^\|\s*{re.escape(lote)}\s*\|[^|]*\|\s*Hecho\s*\|", re.MULTILINE)
    return bool(patron.search(texto))


def jpeg_patron(semilla: int, ancho: int = 1024, alto: int = 768, *, calidad: int = 90) -> bytes:
    """JPEG en color hecho con Pillow, con un patrón que depende de `semilla % 4` (0 franjas, 1 tablero, 2 círculos
    concéntricos, 3 figuras sueltas), colores al azar con esa semilla y 12 líneas encima. La misma semilla da los
    mismos bytes. Semillas con distinto `semilla % 4` dan imágenes muy distintas para el modelo (BE-2.4 C1: cada foto
    debe ser su propio primer vecino). 1024×768 ocupa unos 30–200 KB."""
    import io
    import random

    from PIL import Image, ImageDraw

    azar = random.Random(semilla)  # noqa: S311 (no es criptografía)

    def color() -> tuple[int, int, int]:
        return (azar.randrange(256), azar.randrange(256), azar.randrange(256))

    imagen = Image.new("RGB", (ancho, alto), color())
    dibujo = ImageDraw.Draw(imagen)
    patron = semilla % 4
    if patron == 0:
        paso = azar.randrange(24, 120)
        for x in range(0, ancho, paso * 2):
            dibujo.rectangle([x, 0, x + paso - 1, alto], fill=color())
    elif patron == 1:
        lado = azar.randrange(40, 160)
        for y in range(0, alto, lado):
            for x in range(0, ancho, lado):
                if (x // lado + y // lado) % 2 == 0:
                    dibujo.rectangle([x, y, x + lado - 1, y + lado - 1], fill=color())
    elif patron == 2:
        cx, cy, paso = azar.randrange(ancho), azar.randrange(alto), azar.randrange(30, 90)
        for radio in range(max(ancho, alto), 0, -paso):
            dibujo.ellipse([cx - radio, cy - radio, cx + radio, cy + radio], fill=color())
    else:
        for _ in range(40):
            x0, y0 = azar.randrange(ancho), azar.randrange(alto)
            caja = [x0, y0, x0 + azar.randrange(20, 300), y0 + azar.randrange(20, 300)]
            (dibujo.ellipse if azar.random() < 0.5 else dibujo.rectangle)(caja, fill=color())
    for _ in range(12):
        puntos = [(azar.randrange(ancho), azar.randrange(alto)), (azar.randrange(ancho), azar.randrange(alto))]
        dibujo.line(puntos, fill=color(), width=azar.randrange(2, 12))
    salida = io.BytesIO()
    imagen.save(salida, format="JPEG", quality=calidad)
    return salida.getvalue()


def jpeg_ruido(semilla: int, ancho: int = 512, alto: int = 384) -> bytes:
    """JPEG de ruido RGB aleatorio con esa semilla (Pillow, calidad 85; 512×384 ocupa ~150–250 KB): una foto sin
    relación con ningún dataset (BE-2.4 C2)."""
    import io
    import random

    from PIL import Image

    azar = random.Random(semilla)  # noqa: S311
    imagen = Image.frombytes("RGB", (ancho, alto), azar.randbytes(ancho * alto * 3))
    salida = io.BytesIO()
    imagen.save(salida, format="JPEG", quality=85)
    return salida.getvalue()


def png_sintetico(ancho: int = 320, alto: int = 240) -> bytes:
    """Un PNG pequeño (Pillow): una parte que no es JPEG (BE-2.4 C3b)."""
    import io

    from PIL import Image

    salida = io.BytesIO()
    Image.new("RGB", (ancho, alto), (30, 120, 200)).save(salida, format="PNG")
    return salida.getvalue()


def jpeg_relleno(n_bytes: int) -> bytes:
    """Un JPEG válido (`jpeg_sintetico` de 64×48) seguido de ceros hasta `n_bytes` (relleno tras el EOI): una foto que
    pasa de `LOC_MAX_BYTES_FOTO` sin generar una imagen enorme (BE-2.4 C3b)."""
    base = jpeg_sintetico(64, 48, semilla=1)
    exigir(n_bytes >= len(base), f"jpeg_relleno: {n_bytes} bytes no caben ni el JPEG base ({len(base)})")
    return base + b"\0" * (n_bytes - len(base))


def pedir_vecinos(
    api: ClienteApi,
    token: str | None,
    foto: bytes,
    *,
    k: Any = None,
    tipo: str = "image/jpeg",
    parte: str = "foto",
) -> Any:
    """`POST /v1/admin/diagnostico/vecinos[?k=…]` con `foto` como única parte `parte` (`consulta.jpg`, `tipo`), como la
    envía la herramienta de evaluación de embeddings. `token=None` = sin `Authorization`. Devuelve la respuesta."""
    parametros = {} if k is None else {"k": k}
    return api.pedir(
        "POST", RUTA_VECINOS, token=token, params=parametros, files=[(parte, ("consulta.jpg", foto, tipo))]
    )


def mensajes_log(logs: Any, grupo: str, desde: datetime) -> list[str]:
    """Todos los mensajes de un log group desde `desde` (`filter-log-events` sin patrón, todas las páginas). Sin
    permiso → `ErrorConfiguracion`; otro error → `Falla`."""
    mensajes: list[str] = []
    argumentos: dict[str, Any] = {"logGroupName": grupo, "startTime": int(desde.timestamp() * 1000)}
    try:
        while True:
            pagina = logs.filter_log_events(**argumentos)
            mensajes += [e.get("message", "") for e in pagina.get("events", [])]
            siguiente = pagina.get("nextToken")
            if not siguiente:
                return mensajes
            argumentos["nextToken"] = siguiente
    except Exception as exc:
        raise _errores_aws(exc, f"logs filter-log-events {grupo}") from None


# --- Lugares de prueba (BE-3.1; ARCHITECTURE §5.3, §5.5 y §5.11) ------------------------------------------------------
RUTA_LUGARES = "/places"
RUTA_LUGARES_ADMIN = "/admin/places"
#: Campos exactos de `LugarPublico` (§5.3) y `LugarAdmin` (§5.5).
CAMPOS_LUGAR_PUBLICO = frozenset(
    {"id", "nombre", "categoria", "lat", "lng", "alias", "descripcion", "referencias", "imagen_url", "distancia_m"}
)
CAMPOS_LUGAR_ADMIN = (CAMPOS_LUGAR_PUBLICO - {"distancia_m"}) | {"creado_en", "actualizado_en", "total_fotos"}


def normalizar_nombre(texto: str) -> str:
    """La regla de §5.5 para comparar nombres de lugares (copia, sin importar el backend): NFKD sin marcas combinantes,
    `casefold()` y los espacios reducidos a uno, sin espacios alrededor. «Café  Norte» → `cafe norte`."""
    import unicodedata

    sin_marcas = "".join(c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c))
    return " ".join(sin_marcas.casefold().split())


def lugares_validacion(api: ClienteApi, token: str, prefijo: str = PREFIJO_VALIDACION) -> list[dict[str, Any]]:
    """Los `LugarAdmin` cuyo nombre normalizado empieza por `prefijo` (por defecto `validacion-`), de
    `GET /v1/admin/places?q=<prefijo>`. No 200 → `Falla`."""
    clave = normalizar_nombre(prefijo)
    respuesta = api.pedir("GET", RUTA_LUGARES_ADMIN, token=token, params={"q": clave})
    exigir(respuesta.status_code == 200, f"GET /v1/admin/places respondió {describir_respuesta(respuesta)}")
    items = respuesta.json().get("items", [])
    return [lugar for lugar in items if normalizar_nombre(str(lugar.get("nombre", ""))).startswith(clave)]


def borrar_lugares(api: ClienteApi, token: str, ids: Iterable[str]) -> int:
    """`DELETE /v1/admin/places/{id}` de cada id (sin repetir). Devuelve cuántos; un código distinto de 204 →
    `Falla` (204 también si ya no existía, §5.5)."""
    vistos: list[str] = []
    for lugar_id in ids:
        if lugar_id in vistos:
            continue
        respuesta = api.pedir("DELETE", f"{RUTA_LUGARES_ADMIN}/{lugar_id}", token=token)
        exigir(respuesta.status_code == 204, f"DELETE de un lugar de prueba respondió {describir_respuesta(respuesta)}")
        vistos.append(lugar_id)
    return len(vistos)


def borrar_lugares_restos(api: ClienteApi, token: str) -> str:
    """La `preparacion` de los validadores que crean lugares: borra los `validacion-` que haya dejado cualquier
    ejecución interrumpida. Devuelve `sin lugares validacion- …` o `lugares validacion- borrados: n`."""
    restos = lugares_validacion(api, token)
    if not restos:
        return "sin lugares validacion- de ejecuciones anteriores"
    return f"lugares validacion- borrados: {borrar_lugares(api, token, [str(lugar['id']) for lugar in restos])}"


# --- Resumen del panel (BE-2.3; ARCHITECTURE §5.5 y §5.11) -----------------------------------------------------------
RUTA_STATS = "/admin/stats"
#: Campos exactos de la respuesta de `GET /v1/admin/stats` y de su `ultimo_video` (§5.5).
CAMPOS_RESUMEN = frozenset({"total_fotos", "total_lugares", "alertas_activas", "ultimo_video"})
CAMPOS_ULTIMO_VIDEO = frozenset({"numero", "creado_en"})
#: Fecha de salida de §5.1: UTC con `Z` y sin fracciones.
PATRON_FECHA_UTC = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")


def resumen_panel(api: ClienteApi, token: str, que: str = "GET /v1/admin/stats") -> dict[str, Any]:
    """`GET /v1/admin/stats` → el cuerpo. `Falla` (con `que` en el mensaje) si no es 200, si los campos no son
    exactamente `CAMPOS_RESUMEN` o si un total no es un entero ≥ 0. No mira `ultimo_video` por dentro (cada validador
    sabe qué espera). Lo usan `validate23.py` (C1) y BE-3.3 C5 (`alertas_activas`)."""
    respuesta = api.pedir("GET", RUTA_STATS, token=token)
    exigir(respuesta.status_code == 200, f"{que}: {describir_respuesta(respuesta)}, se esperaba 200")
    cuerpo = respuesta.json()
    exigir(isinstance(cuerpo, dict) and set(cuerpo) == CAMPOS_RESUMEN, f"{que}: campos {sorted(cuerpo or {})}")
    for campo in ("total_fotos", "total_lugares", "alertas_activas"):
        valor = cuerpo[campo]
        exigir(
            isinstance(valor, int) and not isinstance(valor, bool) and valor >= 0,
            f"{que}: {campo} = {valor!r}, se esperaba un entero ≥ 0",
        )
    return cuerpo


# --- Alertas de prueba (BE-3.3; ARCHITECTURE §5.3, §5.5 y §5.11) ----------------------------------------------------
RUTA_ALERTAS = "/alerts"
RUTA_ALERTAS_ADMIN = "/admin/alerts"
RUTA_SINCRONIZAR = "/admin/alerts/sincronizar"
#: Campos exactos de `Alerta` (§5.3), `AlertaAdmin` (§5.5) y de la respuesta de `GET /v1/alerts`.
CAMPOS_ALERTA = frozenset(
    {
        "id",
        "lat",
        "lng",
        "mensaje",
        "tipo",
        "prioridad",
        "radio_m",
        "activa",
        "vigencia_desde",
        "vigencia_hasta",
        "actualizado_en",
        "version",
    }
)
CAMPOS_ALERTA_ADMIN = CAMPOS_ALERTA | {"creado_en", "creado_por", "actualizado_por"}
CAMPOS_FOTO_ALERTAS = frozenset({"generado_en", "completo", "alertas", "eliminadas"})


def alertas_validacion(api: ClienteApi, token: str, prefijo: str = PREFIJO_VALIDACION) -> list[dict[str, Any]]:
    """Las `AlertaAdmin` (sin borrar) cuyo `mensaje` empieza por `prefijo` (por defecto `validacion-`), de
    `GET /v1/admin/alerts?q=<prefijo>` (busca contenido sin tildes ni mayúsculas; aquí se exige el comienzo). No 200 →
    `Falla`."""
    respuesta = api.pedir("GET", RUTA_ALERTAS_ADMIN, token=token, params={"q": prefijo})
    exigir(respuesta.status_code == 200, f"GET /v1/admin/alerts respondió {describir_respuesta(respuesta)}")
    clave = normalizar_nombre(prefijo)
    items = respuesta.json().get("items", [])
    return [alerta for alerta in items if normalizar_nombre(str(alerta.get("mensaje", ""))).startswith(clave)]


def borrar_alertas(api: ClienteApi, token: str, ids: Iterable[str]) -> int:
    """`DELETE /v1/admin/alerts/{id}` de cada id (sin repetir). Devuelve cuántos; un código distinto de 204 → `Falla`
    (204 también si no existe o ya estaba borrada, §5.5)."""
    vistos: list[str] = []
    for alerta_id in ids:
        if alerta_id in vistos:
            continue
        respuesta = api.pedir("DELETE", f"{RUTA_ALERTAS_ADMIN}/{alerta_id}", token=token)
        exigir(
            respuesta.status_code == 204, f"DELETE de una alerta de prueba respondió {describir_respuesta(respuesta)}"
        )
        vistos.append(alerta_id)
    return len(vistos)


def borrar_alertas_restos(api: ClienteApi, token: str) -> str:
    """La `preparacion` de quien crea alertas: borra las `validacion-` (de cualquier lote) que haya dejado una ejecución
    interrumpida. Devuelve `sin alertas validacion- …` o `alertas validacion- borradas: n`. Dejan su *tombstone*
    `ALERTAS_TOMBSTONE_DIAS` (§5.10)."""
    restos = alertas_validacion(api, token)
    if not restos:
        return "sin alertas validacion- de ejecuciones anteriores"
    return f"alertas validacion- borradas: {borrar_alertas(api, token, [str(alerta['id']) for alerta in restos])}"
