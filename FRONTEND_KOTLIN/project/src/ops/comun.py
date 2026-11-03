"""Ayudas comunes de los validadores de la app (FRONTEND_KOTLIN).

Contrato común: INFRASTRUCTURA_TERRAFORM/docs/ARCHITECTURE.md §5.11. Lo propio de la app y la tabla de esta API:
FRONTEND_KOTLIN/docs/ARCHITECTURE.md §5.11. Si algo cambia aquí, esa tabla se actualiza en el mismo cambio.

Solo biblioteca estándar. Nunca imprime secretos, tokens ni URLs prefirmadas.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
import urllib.error
import urllib.request
import uuid
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

# --- Constantes -------------------------------------------------------------------------------------------------

PROYECTO = Path(__file__).resolve().parents[2]  # FRONTEND_KOTLIN/project/
RAIZ_REPO = PROYECTO.parents[1]
DIR_INFORMES = PROYECTO / ".validacion"
DIR_TF_DEV = RAIZ_REPO / "INFRASTRUCTURA_TERRAFORM" / "project" / "envs" / "dev"
API_CONFIG = PROYECTO / "app" / "src" / "main" / "java" / "com" / "example" / "myapplication" / "ApiConfig.kt"
PLAN_APP = PROYECTO.parent / "docs" / "PLAN.md"
PLAN_BACKEND = RAIZ_REPO / "BACKEND_FASTAPI" / "docs" / "PLAN.md"  # FE-2.1: estado de BE-2.1 y BE-2.2 (solo docs)
DIR_RESULTADOS_PRUEBAS = PROYECTO / "app" / "build" / "test-results" / "testDebugUnitTest"
PAQUETE = "com.example.myapplication"
ACTIVIDAD = f"{PAQUETE}/.MainActivity"
LOG_APP = "files/logs/app.log"  # relativo a los datos privados de la app (run-as)
ENTORNOS = ("local", "dev")
CUENTA = "648617469176"
REGION = "us-east-1"
SECRETO_ADMIN = "campus-locator/dev/admin-inicial"
USUARIO_VALIDACION = "validacion+user@campus.edu.co"
NOMBRE_USUARIO_VALIDACION = "validacion-user"
LOG_MIGRATE = "/campus-locator/dev/migrate"  # stream migrate/app/<id de la tarea> (backend §5.11)

# --- Excepciones que deciden el código de salida ---------------------------------------------------------------


class Falla(Exception):  # noqa: N818 — nombres del contrato común
    """La comprobación no pasa (código 1). En una precondición, también cuenta como bloqueo (2)."""


class Bloqueo(Exception):  # noqa: N818
    """Otro lote no está listo (código 2)."""


class ErrorConfiguracion(Exception):
    """Falta una herramienta, variable, dispositivo o credencial (código 3)."""


# --- Utilidades ------------------------------------------------------------------------------------------------


def avisar(mensaje: str) -> None:
    """Progreso a stderr (stdout queda para las líneas `[PASA] …`)."""
    print(f"· {mensaje}", file=sys.stderr, flush=True)


def reloj() -> float:
    """Segundos monótonos (las pruebas lo sustituyen por un reloj falso)."""
    return time.monotonic()


def dormir(segundos: float) -> None:
    """`time.sleep` (las pruebas lo sustituyen: con el reloj falso, avanza el reloj)."""
    time.sleep(segundos)


def esperar_enter(instruccion: str) -> None:
    """Paso guiado (FE-3.1): imprime la instrucción por stderr y espera a que la persona pulse Enter en la terminal.

    Sin terminal (entrada estándar cerrada o vacía: EOF) → ErrorConfiguracion. Ctrl+C interrumpe el validador (la
    limpieza corre igual). Las pruebas la sustituyen."""
    avisar(f"PASO GUIADO — {instruccion}")
    avisar("Pulsa Enter aquí cuando esté hecho (Ctrl+C cancela).")
    try:
        linea = sys.stdin.readline()
    except (OSError, ValueError) as e:
        raise ErrorConfiguracion(f"el paso guiado necesita una terminal: {e}") from e
    if linea == "":
        raise ErrorConfiguracion("el paso guiado necesita una terminal: la entrada estándar está cerrada (EOF)")


def lote_hecho(texto_plan: str, lote: str) -> bool:
    """¿La tabla de estado (§3) de un PLAN dice «Hecho» para `lote`?

    Busca una fila `| <lote> | <fase> | Hecho | …`: la tercera celda es el estado. Una fila de §2.1 con el mismo id no
    cuenta (su tercera celda es «Para construir»).
    """
    for linea in texto_plan.splitlines():
        celdas = [c.strip() for c in linea.strip().strip("|").split("|")]
        if len(celdas) >= 3 and celdas[0] == lote and celdas[2] == "Hecho":
            return True
    return False


def resumir(texto: str, limite: int = 300) -> str:
    texto = " ".join((texto or "").split())
    return texto if len(texto) <= limite else texto[: limite - 1] + "…"


@dataclass
class Resultado:
    codigo: int
    salida: str
    error: str

    @property
    def texto(self) -> str:
        return (self.salida + "\n" + self.error).strip()


def ejecutar(
    comando: list[str],
    *,
    entrada: str | None = None,
    timeout: int = 300,
    cwd: Path | None = None,
    entorno: dict[str, str] | None = None,
) -> Resultado:
    """Ejecuta un programa (lista de argumentos) desde `project/` sin imprimir nada.

    Si no está instalado → ErrorConfiguracion. Si no termina en `timeout` s → Falla.
    """
    env = dict(os.environ)
    env.update({"TF_IN_AUTOMATION": "1", "TF_INPUT": "0", "NO_COLOR": "1", "GH_PAGER": "", "PAGER": "cat"})
    if entorno:
        env.update(entorno)
    try:
        r = subprocess.run(
            comando,
            input=entrada,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            cwd=str(cwd or PROYECTO),
            env=env,
            check=False,
        )
    except FileNotFoundError as e:
        raise ErrorConfiguracion(f"no se encontró el programa {comando[0]!r}") from e
    except subprocess.TimeoutExpired as e:
        raise Falla(f"{' '.join(comando[:3])}… no terminó en {timeout} s") from e
    return Resultado(r.returncode, r.stdout or "", r.stderr or "")


def commit_actual() -> str:
    """Commit corto de HEAD, con `-dirty` si hay cambios sin commit en archivos versionados de `project/`.

    `core.autocrlf=input`: la copia de trabajo la sacó el Git de Windows (`autocrlf=true`, archivos con CRLF) y el Git
    de WSL, sin esa opción, vería todos esos archivos como modificados.
    """
    r = ejecutar(["git", "rev-parse", "--short", "HEAD"])
    if r.codigo != 0:
        return "desconocido"
    sucio = ejecutar(["git", "-c", "core.autocrlf=input", "status", "--porcelain", "--untracked-files=no", "--", "."])
    return r.salida.strip() + ("-dirty" if sucio.salida.strip() else "")


# --- URL de la API ---------------------------------------------------------------------------------------------

_PATRON_API_BASE = re.compile(r'const\s+val\s+API_BASE_URL\s*=\s*"([^"]*)"')
_PATRON_BASE = re.compile(r'const\s+val\s+BASE_URL\s*=\s*"([^"]*)"')


def url_api_config(ruta: Path = API_CONFIG) -> str:
    """URL base que usa la app (`ApiConfig.BASE_URL`, con `/v1`), leída del código fuente.

    Exige la forma de FE-1.1: `API_BASE_URL = "https://…"` y `BASE_URL = "$API_BASE_URL/v1"` (o una URL literal).
    Si no tiene esa forma → Falla.
    """
    try:
        texto = ruta.read_text(encoding="utf-8")
    except OSError as e:
        raise Falla(f"no se pudo leer {ruta.name}: {e}") from e
    base = _PATRON_BASE.search(texto)
    if not base:
        raise Falla(f"{ruta.name} no define const val BASE_URL")
    valor = base.group(1)
    if "$API_BASE_URL" in valor or "${API_BASE_URL}" in valor:
        api_base = _PATRON_API_BASE.search(texto)
        if not api_base:
            raise Falla(f"{ruta.name}: BASE_URL usa API_BASE_URL, pero no está definida")
        valor = valor.replace("${API_BASE_URL}", api_base.group(1)).replace("$API_BASE_URL", api_base.group(1))
    if "$" in valor:
        raise Falla(f"{ruta.name}: BASE_URL tiene una plantilla que el validador no sabe resolver: {valor}")
    return valor


def normalizar_url(url: str) -> str:
    return url.strip().rstrip("/")


def comprobar_forma_url(url: str, origen: str) -> str:
    """`https://…/v1` sin barra final; si no → ErrorConfiguracion (es una variable o un output mal puesto)."""
    u = normalizar_url(url)
    if not u.startswith("https://") or not u.endswith("/v1"):
        raise ErrorConfiguracion(f"{origen} debe empezar por https:// y terminar en /v1 (es {u!r})")
    return u


def terraform_output_raw(nombre: str, directorio: Path = DIR_TF_DEV) -> str:
    """`terraform -chdir=<directorio> output -raw <nombre>` (una lectura del estado; no cambia nada).

    Sin terraform, sin `init` o sin credenciales → ErrorConfiguracion. El valor no se imprime aquí.
    """
    if not directorio.is_dir():
        raise ErrorConfiguracion(f"no existe {directorio}")
    r = ejecutar(["terraform", f"-chdir={directorio}", "output", "-raw", nombre], timeout=120)
    if r.codigo != 0:
        raise ErrorConfiguracion(f"terraform output -raw {nombre} falló: {resumir(r.error or r.salida, 200)}")
    valor = r.salida.strip()
    if not valor:
        raise ErrorConfiguracion(f"el output {nombre} está vacío")
    return valor


def url_api_vigente() -> tuple[str, str]:
    """URL base vigente con `/v1` y de dónde salió: el output `api_base_url` + `/v1`, o `VALIDACION_API_URL`.

    Terraform manda (es la fuente de verdad, infra §5.2); `VALIDACION_API_URL` solo se usa si Terraform no está
    disponible. Ninguna de las dos → ErrorConfiguracion.
    """
    try:
        base = terraform_output_raw("api_base_url")
        return comprobar_forma_url(normalizar_url(base) + "/v1", "api_base_url + /v1"), "terraform output api_base_url"
    except ErrorConfiguracion as e_tf:
        variable = os.environ.get("VALIDACION_API_URL", "").strip()
        if variable:
            return comprobar_forma_url(variable, "VALIDACION_API_URL"), "VALIDACION_API_URL"
        raise ErrorConfiguracion(f"sin URL de la API: {e_tf}; define VALIDACION_API_URL") from e_tf


@dataclass
class RespuestaHttp:
    estado: int
    encabezados: dict[str, str]
    cuerpo: str
    duracion_ms: int

    def json(self) -> object:
        try:
            return json.loads(self.cuerpo)
        except ValueError:
            return None


class ErrorRed(Exception):
    """No hubo respuesta HTTP: DNS, TLS, conexión o tiempo agotado."""


def _encabezados(token: str | None, extra: dict[str, str] | None = None) -> dict[str, str]:
    encabezados = {"X-Request-Id": str(uuid.uuid4()), "User-Agent": "validacion-app", **(extra or {})}
    if token:
        encabezados["Authorization"] = f"Bearer {token}"  # nunca se imprime
    return encabezados


def http_get(url: str, *, timeout: float = 15.0, token: str | None = None) -> RespuestaHttp:
    """`GET` con `X-Request-Id` propio (como la app). Una respuesta 4xx/5xx se devuelve; sin respuesta → ErrorRed.

    `token` (FE-2.1) añade `Authorization: Bearer <token>` para las rutas `/v1/admin/…` y `/v1/collect/…`; nunca se
    imprime."""
    peticion = urllib.request.Request(url, headers=_encabezados(token))
    inicio = time.monotonic()
    try:
        with urllib.request.urlopen(peticion, timeout=timeout) as r:  # noqa: S310 — URL https comprobada
            cuerpo = r.read().decode("utf-8", errors="replace")
            return RespuestaHttp(r.status, dict(r.headers.items()), cuerpo, _ms(inicio))
    except urllib.error.HTTPError as e:
        cuerpo = e.read().decode("utf-8", errors="replace")
        return RespuestaHttp(e.code, dict(e.headers.items()), cuerpo, _ms(inicio))
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        motivo = getattr(e, "reason", e)
        raise ErrorRed(f"{type(motivo).__name__}: {resumir(str(motivo), 150)}") from e


def http_post_json(url: str, cuerpo: dict, *, timeout: float = 15.0, token: str | None = None) -> RespuestaHttp:
    """`POST` con cuerpo JSON y `X-Request-Id` propio. 4xx/5xx se devuelven; sin respuesta → ErrorRed.

    Nunca imprime ni devuelve en un error el cuerpo enviado (lleva contraseñas). Un `429` de API Gateway (cuerpo
    `{"message": …}`, infra §5.13) se reintenta tras 1, 2 y 4 s; si no cede, se devuelve el último. `token` (FE-2.1)
    añade `Authorization: Bearer <token>`.
    """
    datos = json.dumps(cuerpo).encode("utf-8")
    respuesta = None
    for espera in (1, 2, 4, None):
        peticion = urllib.request.Request(
            url,
            data=datos,
            method="POST",
            headers=_encabezados(token, {"Content-Type": "application/json"}),
        )
        inicio = time.monotonic()
        try:
            with urllib.request.urlopen(peticion, timeout=timeout) as r:  # noqa: S310 — URL https comprobada
                return RespuestaHttp(
                    r.status, dict(r.headers.items()), r.read().decode("utf-8", errors="replace"), _ms(inicio)
                )
        except urllib.error.HTTPError as e:
            respuesta = RespuestaHttp(
                e.code, dict(e.headers.items()), e.read().decode("utf-8", errors="replace"), _ms(inicio)
            )
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            motivo = getattr(e, "reason", e)
            raise ErrorRed(f"{type(motivo).__name__}: {resumir(str(motivo), 150)}") from e
        cuerpo_json = respuesta.json()
        de_api_gateway = isinstance(cuerpo_json, dict) and "message" in cuerpo_json and "error" not in cuerpo_json
        if respuesta.estado != 429 or not de_api_gateway or espera is None:
            return respuesta
        dormir(espera)
    return respuesta  # pragma: no cover — el bucle siempre devuelve


def http_delete(url: str, *, timeout: float = 15.0, token: str | None = None) -> RespuestaHttp:
    """`DELETE` con `X-Request-Id` propio (FE-3.1: borrar el lugar de prueba). 4xx/5xx se devuelven; sin respuesta →
    ErrorRed. `token` añade `Authorization: Bearer <token>`; nunca se imprime."""
    peticion = urllib.request.Request(url, method="DELETE", headers=_encabezados(token))
    inicio = time.monotonic()
    try:
        with urllib.request.urlopen(peticion, timeout=timeout) as r:  # noqa: S310 — URL https comprobada
            cuerpo = r.read().decode("utf-8", errors="replace")
            return RespuestaHttp(r.status, dict(r.headers.items()), cuerpo, _ms(inicio))
    except urllib.error.HTTPError as e:
        cuerpo = e.read().decode("utf-8", errors="replace")
        return RespuestaHttp(e.code, dict(e.headers.items()), cuerpo, _ms(inicio))
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        motivo = getattr(e, "reason", e)
        raise ErrorRed(f"{type(motivo).__name__}: {resumir(str(motivo), 150)}") from e


@dataclass
class ParteMultipart:
    """Una parte de un `multipart/form-data` (FE-3.2): `nombre` del campo, `datos`, `tipo` (Content-Type) y, si es un
    archivo, `archivo` (filename)."""

    nombre: str
    datos: bytes
    tipo: str = "text/plain; charset=utf-8"
    archivo: str | None = None


def cuerpo_multipart(partes: list[ParteMultipart], limite: str) -> bytes:
    """Cuerpo `multipart/form-data` (RFC 7578) con el separador `limite`, en el orden de `partes`. Lógica pura."""
    salida = bytearray()
    for p in partes:
        disposicion = f'form-data; name="{p.nombre}"'
        if p.archivo is not None:
            disposicion += f'; filename="{p.archivo}"'
        salida += f"--{limite}\r\nContent-Disposition: {disposicion}\r\nContent-Type: {p.tipo}\r\n\r\n".encode()
        salida += p.datos + b"\r\n"
    salida += f"--{limite}--\r\n".encode()
    return bytes(salida)


def http_post_multipart(
    url: str, partes: list[ParteMultipart], *, timeout: float = 15.0, token: str | None = None
) -> RespuestaHttp:
    """`POST multipart/form-data` con `X-Request-Id` propio (FE-3.2: la sonda de `POST /v1/localize` de
    `validate32.py`, que no lleva fotos). 4xx/5xx se devuelven; sin respuesta → ErrorRed. Nunca imprime el cuerpo;
    `token` añade `Authorization: Bearer <token>`."""
    limite = f"validacion-{uuid.uuid4().hex}"
    peticion = urllib.request.Request(
        url,
        data=cuerpo_multipart(partes, limite),
        method="POST",
        headers=_encabezados(token, {"Content-Type": f"multipart/form-data; boundary={limite}"}),
    )
    inicio = time.monotonic()
    try:
        with urllib.request.urlopen(peticion, timeout=timeout) as r:  # noqa: S310 — URL https comprobada
            cuerpo = r.read().decode("utf-8", errors="replace")
            return RespuestaHttp(r.status, dict(r.headers.items()), cuerpo, _ms(inicio))
    except urllib.error.HTTPError as e:
        cuerpo = e.read().decode("utf-8", errors="replace")
        return RespuestaHttp(e.code, dict(e.headers.items()), cuerpo, _ms(inicio))
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        motivo = getattr(e, "reason", e)
        raise ErrorRed(f"{type(motivo).__name__}: {resumir(str(motivo), 150)}") from e


def codigo_error(r: RespuestaHttp) -> str | None:
    """`error.codigo` del formato de error del backend (§5.1), o None."""
    cuerpo = r.json()
    if isinstance(cuerpo, dict) and isinstance(cuerpo.get("error"), dict):
        codigo = cuerpo["error"].get("codigo")
        return codigo if isinstance(codigo, str) else None
    return None


def _ms(inicio: float) -> int:
    return int((time.monotonic() - inicio) * 1000)


# --- AWS (CLI `aws`), Terraform y tareas sueltas de ECS --------------------------------------------------------

_PATRON_ERROR_AWS = re.compile(r"An error occurred \(([A-Za-z0-9_.]+)\)")
_CODIGOS_CREDENCIALES_AWS = {
    "AccessDenied",
    "AccessDeniedException",
    "UnauthorizedOperation",
    "ExpiredToken",
    "ExpiredTokenException",
    "InvalidClientTokenId",
    "UnrecognizedClientException",
    "SignatureDoesNotMatch",
    "AuthFailure",
}
_TEXTOS_CREDENCIALES_AWS = ("Unable to locate credentials", "could not be found", "Token has expired", "SSO session")


class ErrorAws(Falla):
    """Un comando `aws` falló por algo que no son credenciales ni permisos. `.codigo` = el de AWS (o None)."""

    def __init__(self, mensaje: str, codigo: str | None = None) -> None:
        super().__init__(mensaje)
        self.codigo = codigo


def aws(*argumentos: str, timeout: int = 120) -> Resultado:
    """CLI `aws` v2 (con `AWS_PROFILE` del entorno), en `us-east-1`, salida JSON y sin paginador."""
    return ejecutar(["aws", *argumentos, "--region", REGION, "--output", "json", "--no-cli-pager"], timeout=timeout)


def aws_json(*argumentos: str, accion: str, timeout: int = 120, mostrar_error: bool = True) -> object:
    """`aws …` → JSON. Credenciales o permisos → ErrorConfiguracion; otro error → ErrorAws (con su código).

    `mostrar_error=False` no copia el texto de error de la CLI al mensaje (solo el código): para comandos cuyos
    parámetros llevan secretos (p. ej. `CREAR_USUARIO_PASSWORD` en `run-task`).
    """
    r = aws(*argumentos, timeout=timeout)
    if r.codigo != 0:
        m = _PATRON_ERROR_AWS.search(r.error)
        codigo = m.group(1) if m else None
        texto = resumir(r.error or r.salida, 200) if mostrar_error else f"código {codigo or '?'}"
        if codigo in _CODIGOS_CREDENCIALES_AWS or any(t in r.error for t in _TEXTOS_CREDENCIALES_AWS):
            raise ErrorConfiguracion(f"{accion}: credenciales o permisos de AWS ({texto}); ¿AWS_PROFILE?")
        raise ErrorAws(f"{accion}: {texto}", codigo)
    if not r.salida.strip():
        return None
    try:
        return json.loads(r.salida)
    except ValueError as e:
        raise Falla(f"{accion}: la respuesta de aws no es JSON") from e


def cuenta_aws() -> str:
    """ARN de quien llama (`aws sts get-caller-identity`); si la cuenta no es la del proyecto → ErrorConfiguracion."""
    datos = aws_json("sts", "get-caller-identity", accion="aws sts get-caller-identity", timeout=60)
    if not isinstance(datos, dict) or datos.get("Account") != CUENTA:
        cuenta = datos.get("Account") if isinstance(datos, dict) else None
        raise ErrorConfiguracion(f"AWS_PROFILE apunta a la cuenta {cuenta}, no a {CUENTA}")
    return str(datos.get("Arn", ""))


def terraform_outputs(directorio: Path = DIR_TF_DEV) -> dict[str, object]:
    """`terraform -chdir=<directorio> output -json` → `{nombre: valor}`. Sin terraform, `init` o credenciales →
    ErrorConfiguracion. Nunca se imprime."""
    if not directorio.is_dir():
        raise ErrorConfiguracion(f"no existe {directorio}")
    r = ejecutar(["terraform", f"-chdir={directorio}", "output", "-json"], timeout=120)
    if r.codigo != 0:
        raise ErrorConfiguracion(f"terraform output -json falló: {resumir(r.error or r.salida, 200)}")
    try:
        datos = json.loads(r.salida or "{}")
    except ValueError as e:
        raise ErrorConfiguracion("terraform output -json no devolvió JSON") from e
    return {k: (v.get("value") if isinstance(v, dict) else v) for k, v in datos.items()}


def leer_secreto(secreto: str, lote: str = "INF-1.2") -> dict:
    """JSON de un secreto de Secrets Manager. Sin permiso → ErrorConfiguracion; no existe → Bloqueo del `lote`."""
    try:
        valor = aws_json(
            "secretsmanager",
            "get-secret-value",
            "--secret-id",
            secreto,
            "--query",
            "SecretString",
            accion=f"leer el secreto {secreto}",
            timeout=60,
        )
    except ErrorAws as e:
        if e.codigo == "ResourceNotFoundException":
            raise Bloqueo(f"{lote}: no existe el secreto {secreto}") from e
        raise
    try:
        datos = json.loads(valor) if isinstance(valor, str) else None
    except ValueError:
        datos = None
    if not isinstance(datos, dict):
        raise ErrorConfiguracion(f"el secreto {secreto} no es un objeto JSON")
    return datos


def credenciales_admin(entorno: str) -> tuple[str, str]:
    """`(correo, password)` del admin: `VALIDACION_ADMIN_CORREO` y `VALIDACION_ADMIN_PASSWORD` si están las dos; si no
    y es `dev`, las claves `correo` y `password` de `SECRETO_ADMIN` (como `credenciales_admin` del backend, §5.11)."""
    correo = os.environ.get("VALIDACION_ADMIN_CORREO", "").strip()
    password = os.environ.get("VALIDACION_ADMIN_PASSWORD", "")
    if correo and password:
        return correo, password
    if entorno != "dev":
        raise ErrorConfiguracion("define VALIDACION_ADMIN_CORREO y VALIDACION_ADMIN_PASSWORD")
    datos = leer_secreto(SECRETO_ADMIN)
    correo, password = datos.get("correo"), datos.get("password")
    if not isinstance(correo, str) or not isinstance(password, str) or not correo or not password:
        raise ErrorConfiguracion(f"el secreto {SECRETO_ADMIN} no tiene las claves correo y password")
    return correo, password


@dataclass
class ResultadoTarea:
    arn: str
    id: str
    codigo: int | None  # salida del contenedor `app`; None si no llegó a correr
    motivo: str  # stoppedReason de ECS
    eventos: list[str] = field(default_factory=list)  # valores de `evento` de las líneas JSON del log (si se leyó)


def salidas_tarea(outputs: dict[str, object]) -> tuple[str, str, dict]:
    """`(cluster, familia de migrate, red de run-task)` a partir de los outputs de infra §5.2 (si falta → Bloqueo)."""
    faltan = [k for k in ("ecs_cluster", "familias_tarea", "subredes_tareas", "sg_migrate") if not outputs.get(k)]
    if faltan:
        raise Bloqueo(f"INF-1.1/INF-1.3: faltan los outputs {', '.join(faltan)}")
    familias = outputs["familias_tarea"]
    familia = familias.get("migrate") if isinstance(familias, dict) else None
    if not familia:
        raise Bloqueo("INF-1.3: familias_tarea no tiene migrate")
    subredes = outputs["subredes_tareas"]
    red = {
        "awsvpcConfiguration": {
            "subnets": list(subredes) if isinstance(subredes, list) else [str(subredes)],
            "securityGroups": [str(outputs["sg_migrate"])],
            "assignPublicIp": "ENABLED",
        }
    }
    return str(outputs["ecs_cluster"]), str(familia), red


def eventos_log(mensajes: list[str]) -> list[str]:
    """Valores de `evento` de las líneas JSON de un log de §5.10 del backend (las que no son JSON se ignoran)."""
    eventos = []
    for m in mensajes:
        try:
            dato = json.loads(m)
        except ValueError:
            continue
        if isinstance(dato, dict) and isinstance(dato.get("evento"), str):
            eventos.append(dato["evento"])
    return eventos


def tarea_cli(
    outputs: dict[str, object],
    argumentos: list[str],
    entorno: dict[str, str] | None = None,
    *,
    leer_log: bool = True,
    limite_s: int = 900,
) -> ResultadoTarea:
    """`python -m app.cli <argumentos>` en una tarea suelta de la última revisión de `campus-locator-dev-migrate`
    (backend §5.9): Fargate, `subredes_tareas` + `sg_migrate` con IP pública, `--started-by validacion-app`.

    `entorno` va en `containerOverrides.environment` por un archivo temporal (no en la línea de comandos) y nunca se
    imprime; queda visible en `describe-tasks` para quien tenga acceso a la cuenta, así que solo valores de prueba.
    Espera a que pare (`aws ecs wait tasks-stopped`, hasta 10 min) y lee el código del contenedor `app` sin traer los
    *overrides*. Con `leer_log` y código ≠ 0, lee `LOG_MIGRATE` (stream `migrate/app/<id>`, hasta 6 intentos con 5 s).
    """
    cluster, familia, red = salidas_tarea(outputs)
    contenedor: dict[str, object] = {"name": "app", "command": ["python", "-m", "app.cli", *argumentos]}
    if entorno:
        contenedor["environment"] = [{"name": k, "value": v} for k, v in entorno.items()]
    with tempfile.TemporaryDirectory(prefix="validacion-") as carpeta:
        ruta = Path(carpeta) / "overrides.json"
        ruta.write_text(json.dumps({"containerOverrides": [contenedor]}), encoding="utf-8")
        ruta.chmod(0o600)
        lanzada = aws_json(
            "ecs",
            "run-task",
            "--cluster",
            cluster,
            "--task-definition",
            familia,
            "--launch-type",
            "FARGATE",
            "--count",
            "1",
            "--started-by",
            "validacion-app",
            "--network-configuration",
            json.dumps(red),
            "--overrides",
            f"file://{ruta}",
            "--query",
            "{arn: tasks[0].taskArn, fallos: failures}",
            accion=f"ecs run-task ({argumentos[0]})",
            timeout=120,
            mostrar_error=False,
        )
    arn = lanzada.get("arn") if isinstance(lanzada, dict) else None
    if not arn:
        fallos = lanzada.get("fallos") if isinstance(lanzada, dict) else None
        raise Falla(f"ecs run-task ({argumentos[0]}) no lanzó la tarea: {resumir(json.dumps(fallos), 200)}")
    id_tarea = str(arn).rsplit("/", 1)[-1]
    avisar(f"tarea {argumentos[0]} lanzada ({id_tarea}); esperando a que pare")
    espera = aws("ecs", "wait", "tasks-stopped", "--cluster", cluster, "--tasks", str(arn), timeout=limite_s)
    if espera.codigo != 0:
        raise Falla(f"la tarea {argumentos[0]} ({id_tarea}) no se detuvo a tiempo: {resumir(espera.error, 150)}")
    estado = aws_json(
        "ecs",
        "describe-tasks",
        "--cluster",
        cluster,
        "--tasks",
        str(arn),
        "--query",
        "tasks[0].{codigo: containers[?name=='app'] | [0].exitCode, motivo: stoppedReason}",
        accion="ecs describe-tasks",
        timeout=60,
    )
    codigo = estado.get("codigo") if isinstance(estado, dict) else None
    motivo = str(estado.get("motivo") or "") if isinstance(estado, dict) else ""
    resultado = ResultadoTarea(str(arn), id_tarea, codigo if isinstance(codigo, int) else None, motivo)
    if leer_log and resultado.codigo != 0:
        for _ in range(6):
            try:
                mensajes = aws_json(
                    "logs",
                    "get-log-events",
                    "--log-group-name",
                    LOG_MIGRATE,
                    "--log-stream-name",
                    f"migrate/app/{id_tarea}",
                    "--start-from-head",
                    "--query",
                    "events[].message",
                    accion="logs get-log-events",
                    timeout=60,
                )
            except ErrorAws:
                mensajes = None
            if isinstance(mensajes, list) and mensajes:
                resultado.eventos = eventos_log([str(m) for m in mensajes])
                break
            dormir(5)
    return resultado


_EVENTOS_FALLO_CLI = (
    "usuario_rechazado",
    "usuario_no_encontrado",
    "comando_fallido",
    "configuracion_incompleta",
    "base_no_disponible",
)


def motivo_tarea(t: ResultadoTarea) -> str:
    """Por qué un `app.cli` no dio 0: código, eventos de fallo del log (backend §5.9) y `stoppedReason`."""
    eventos = [e for e in t.eventos if e in _EVENTOS_FALLO_CLI]
    partes = [f"código {t.codigo}" if t.codigo is not None else "el contenedor no llegó a correr"]
    if eventos:
        partes.append("eventos " + ", ".join(eventos))
    if t.motivo:
        partes.append(resumir(t.motivo, 120))
    return "; ".join(partes)


def crear_usuario_validacion(outputs: dict[str, object]) -> str:
    """Crea o reactiva `USUARIO_VALIDACION` (rol `user`, nombre `validacion-user`) con `crear-usuario` y una
    contraseña aleatoria `validacion-pw-<uuid>` en `CREAR_USUARIO_PASSWORD`. Devuelve la contraseña (nunca se
    imprime). Si no termina con 0 → Falla con el motivo."""
    password = f"validacion-pw-{uuid.uuid4()}"
    t = tarea_cli(
        outputs,
        ["crear-usuario", "--correo", USUARIO_VALIDACION, "--nombre", NOMBRE_USUARIO_VALIDACION, "--rol", "user"],
        {"CREAR_USUARIO_PASSWORD": password},
    )
    if t.codigo != 0:
        raise Falla(f"crear-usuario {USUARIO_VALIDACION} falló ({motivo_tarea(t)})")
    return password


def desactivar_usuario_validacion(outputs: dict[str, object], *, tolerar_inexistente: bool = True) -> str:
    """`desactivar-usuario --correo USUARIO_VALIDACION`. Con `tolerar_inexistente`, «no existe» (1 con
    `usuario_no_encontrado`) no es un fallo. Si no → Falla con el motivo."""
    t = tarea_cli(outputs, ["desactivar-usuario", "--correo", USUARIO_VALIDACION])
    if t.codigo == 0:
        return f"{USUARIO_VALIDACION} desactivado"
    if tolerar_inexistente and t.codigo == 1 and "usuario_no_encontrado" in t.eventos:
        return f"{USUARIO_VALIDACION} no existía"
    raise Falla(f"desactivar-usuario {USUARIO_VALIDACION} falló ({motivo_tarea(t)})")


# --- Gradle y pruebas unitarias --------------------------------------------------------------------------------


def comando_gradle() -> list[str]:
    """Cómo invocar Gradle.

    `VALIDACION_GRADLE` (separado por espacios; p. ej. `cmd.exe /c .\\gradlew.bat` desde WSL), si no `gradlew.bat`
    en Windows y `bash gradlew` en el resto (el wrapper no tiene el bit de ejecución en Git).
    """
    propio = os.environ.get("VALIDACION_GRADLE", "").strip()
    if propio:
        return propio.split()
    if os.name == "nt":
        return ["cmd", "/c", "gradlew.bat"]
    return ["bash", "gradlew"]


def gradle(*argumentos: str, timeout: int = 1800) -> Resultado:
    return ejecutar([*comando_gradle(), "--console=plain", *argumentos], timeout=timeout)


@dataclass
class ResultadoClase:
    clase: str
    pruebas: int
    fallos: int
    errores: int
    omitidas: int

    @property
    def ok(self) -> bool:
        return self.pruebas >= 1 and self.fallos == 0 and self.errores == 0


def archivo_resultados(clase: str, directorio: Path | None = None) -> Path | None:
    """`TEST-<paquete>.<clase>.xml` de una clase de prueba (por nombre simple), o None."""
    directorio = directorio or DIR_RESULTADOS_PRUEBAS
    candidatos = sorted(directorio.glob(f"TEST-*.{clase}.xml")) if directorio.is_dir() else []
    return candidatos[0] if candidatos else None


def resultados_clase(clase: str, directorio: Path | None = None) -> ResultadoClase | None:
    """Lee el XML JUnit que escribe `testDebugUnitTest` para una clase; None si no existe."""
    archivo = archivo_resultados(clase, directorio)
    if archivo is None:
        return None
    raiz = ET.parse(archivo).getroot()
    return ResultadoClase(
        clase=clase,
        pruebas=int(raiz.get("tests", "0")),
        fallos=int(raiz.get("failures", "0")),
        errores=int(raiz.get("errors", "0")),
        omitidas=int(raiz.get("skipped", "0")),
    )


def borrar_resultados(clases: list[str], directorio: Path | None = None) -> None:
    """Borra los XML de esas clases para no leer los de una ejecución anterior (y obligar a Gradle a repetirlas)."""
    for clase in clases:
        archivo = archivo_resultados(clase, directorio)
        if archivo is not None:
            archivo.unlink()


# --- adb y dispositivo -----------------------------------------------------------------------------------------


def comando_adb() -> list[str]:
    """`VALIDACION_ADB` (p. ej. el `adb.exe` de Windows desde WSL), `adb` del PATH o `$ANDROID_HOME/platform-tools`."""
    propio = os.environ.get("VALIDACION_ADB", "").strip()
    if propio:
        return propio.split()
    encontrado = shutil.which("adb")
    if encontrado:
        return [encontrado]
    for variable in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        sdk = os.environ.get(variable)
        if sdk:
            for nombre in ("adb", "adb.exe"):
                ruta = Path(sdk) / "platform-tools" / nombre
                if ruta.is_file():
                    return [str(ruta)]
    raise ErrorConfiguracion("no se encontró adb: ponlo en el PATH o define VALIDACION_ADB")


def adb(*argumentos: str, timeout: int = 120) -> Resultado:
    """adb contra el dispositivo de `ANDROID_SERIAL` si está definida (si no, el único conectado).

    La entrada estándar va vacía (no es una terminal): así `adb shell` no abre un PTY, que mezclaría stderr con stdout
    y cambiaría los finales de línea.
    """
    serial = os.environ.get("ANDROID_SERIAL", "").strip()
    prefijo = ["-s", serial] if serial else []
    return ejecutar([*comando_adb(), *prefijo, *argumentos], entrada="", timeout=timeout)


def dispositivos(texto_adb_devices: str) -> list[tuple[str, str]]:
    """`[(serial, estado)]` a partir de la salida de `adb devices`."""
    lista = []
    for linea in texto_adb_devices.splitlines()[1:]:
        partes = linea.split()
        if len(partes) >= 2:
            lista.append((partes[0], partes[1]))
    return lista


def dispositivo_fisico() -> str:
    """Serial del dispositivo físico listo, o ErrorConfiguracion (sin dispositivo, varios sin `ANDROID_SERIAL`,
    estado distinto de `device` o un emulador)."""
    r = ejecutar([*comando_adb(), "devices"], timeout=60)
    if r.codigo != 0:
        raise ErrorConfiguracion(f"adb devices falló: {resumir(r.texto, 200)}")
    lista = dispositivos(r.salida)
    serial = os.environ.get("ANDROID_SERIAL", "").strip()
    if serial:
        lista = [d for d in lista if d[0] == serial]
        if not lista:
            raise ErrorConfiguracion(f"ANDROID_SERIAL={serial} no aparece en adb devices")
    if not lista:
        raise ErrorConfiguracion("adb devices no muestra ningún dispositivo")
    if len(lista) > 1:
        raise ErrorConfiguracion("hay varios dispositivos: define ANDROID_SERIAL")
    serial, estado = lista[0]
    if estado != "device":
        raise ErrorConfiguracion(f"el dispositivo está en estado {estado!r} (¿autorizaste la depuración USB?)")
    qemu = adb("shell", "getprop", "ro.kernel.qemu", timeout=30).salida.strip()
    if qemu == "1":
        raise ErrorConfiguracion("el dispositivo es un emulador: los lotes de la app se validan en uno físico")
    return serial


def leer_archivo_app(ruta_relativa: str) -> str | None:
    """Contenido de un archivo privado de la app (`run-as`, solo APK de depuración), o None si no existe."""
    r = adb("exec-out", "run-as", PAQUETE, "cat", ruta_relativa, timeout=60)
    if r.codigo != 0:
        return None
    return r.salida


def listar_archivos_app(ruta_relativa: str) -> list[str] | None:
    """Nombres (ordenados) dentro de una carpeta privada de la app (`run-as … ls -1`, solo APK de depuración), o None
    si la carpeta no existe o no se puede leer (FE-2.3)."""
    r = adb("exec-out", "run-as", PAQUETE, "ls", "-1", ruta_relativa, timeout=60)
    if r.codigo != 0:
        return None
    return sorted(linea.strip() for linea in r.salida.splitlines() if linea.strip())


# --- Manejar la interfaz del teléfono (FE-1.2) -----------------------------------------------------------------

RUTA_UI = "/data/local/tmp/validacion-ui.xml"
MENSAJE_SEGURIDAD_MIUI = (
    "en MIUI/HyperOS activa «Depuración USB (Configuración de seguridad)» en Ajustes → Opciones de desarrollador "
    "(además de «Instalar vía USB») y repite"
)
_PATRON_SEGURIDAD = re.compile(r"SecurityException|INJECT_EVENTS|GRANT_RUNTIME_PERMISSIONS|Permission Denial")
_PATRON_LIMITES = re.compile(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]")
_PATRON_TAMANO = re.compile(r"size:\s*(\d+)x(\d+)")
_PATRON_TECLADO = re.compile(r"\b(mInputShown|mIsInputViewShown|isInputViewShown)=true\b")
# Lo que `adb shell input text` puede recibir sin escapar en el sh del teléfono.
_SEGUROS_INPUT = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789@._-+,:=/")
TECLA_ATRAS = "4"
# Ventanas del sistema cuyos textos sí sirven en un diagnóstico (diálogos de permisos, del instalador, de «no responde»
# y de seguridad de MIUI). Los de cualquier otra app —p. ej. la pantalla de inicio, con las apps del usuario— nunca se
# imprimen (FE-4.1).
PAQUETES_SISTEMA = frozenset(
    {
        "android",
        "com.android.permissioncontroller",
        "com.google.android.permissioncontroller",
        "com.android.packageinstaller",
        "com.google.android.packageinstaller",
        "com.lbe.security.miui",
        "com.miui.securitycenter",
    }
)


def exigir_adb_permitido(r: Resultado, que: str) -> None:
    """Si el teléfono rechazó la orden por seguridad (MIUI/HyperOS sin «Depuración USB (Configuración de seguridad)»:
    `SecurityException`, `INJECT_EVENTS`, `GRANT_RUNTIME_PERMISSIONS`) → ErrorConfiguracion con la solución."""
    if _PATRON_SEGURIDAD.search(r.texto):
        raise ErrorConfiguracion(f"el teléfono no deja a adb {que} (SecurityException): {MENSAJE_SEGURIDAD_MIUI}")


@dataclass(frozen=True)
class Nodo:
    """Un nodo de `uiautomator dump` (solo los visibles: uiautomator omite los que están fuera de la pantalla)."""

    texto: str
    descripcion: str  # content-desc
    clase: str
    limites: tuple[int, int, int, int]  # x1, y1, x2, y2 en píxeles de la pantalla
    habilitado: bool
    contrasena: bool
    paquete: str = ""  # `package` (FE-4.1); "" = desconocido (nodos hechos a mano): cuenta como de la app
    enfocado: bool = False  # `focused` (FE-4.1)

    @property
    def de_la_app(self) -> bool:
        return self.paquete in ("", PAQUETE)

    @property
    def centro(self) -> tuple[int, int]:
        x1, y1, x2, y2 = self.limites
        return (x1 + x2) // 2, (y1 + y2) // 2

    @property
    def es_campo(self) -> bool:
        return self.clase.endswith("EditText")

    def dice(self, valor: str) -> bool:
        return self.texto == valor or self.descripcion == valor

    def contiene(self, fragmento: str) -> bool:
        return fragmento in self.texto or fragmento in self.descripcion


def parsear_ui(xml: str) -> list[Nodo]:
    """Nodos de un XML de `uiautomator dump`, en orden de documento. XML roto → Falla."""
    try:
        raiz = ET.fromstring(xml)
    except ET.ParseError as e:
        raise Falla(f"uiautomator devolvió un XML roto: {e}") from e
    nodos = []
    for e in raiz.iter("node"):
        m = _PATRON_LIMITES.fullmatch(e.get("bounds", ""))
        if not m:
            continue
        x1, y1, x2, y2 = (int(v) for v in m.groups())
        nodos.append(
            Nodo(
                texto=e.get("text", ""),
                descripcion=e.get("content-desc", ""),
                clase=e.get("class", ""),
                limites=(x1, y1, x2, y2),
                habilitado=e.get("enabled", "true") == "true",
                contrasena=e.get("password", "false") == "true",
                paquete=e.get("package", ""),
                enfocado=e.get("focused", "false") == "true",
            )
        )
    return nodos


def de_la_app(nodos: list[Nodo]) -> list[Nodo]:
    """Solo los nodos de la app (`package` = `PAQUETE`, o desconocido)."""
    return [n for n in nodos if n.de_la_app]


def app_en_primer_plano(nodos: list[Nodo]) -> bool:
    """¿El volcado es de la app? (algún nodo suyo; un volcado vacío o de otra app —la pantalla de inicio, un diálogo del
    sistema— no). Antes de pulsar Atrás hay que mirarlo: fuera de la app, Atrás actúa sobre otra cosa (FE-4.1)."""
    return any(n.de_la_app for n in nodos)


def volcar_pantalla(intentos: int = 3) -> list[Nodo]:
    """Lo que se ve ahora en el teléfono: `uiautomator dump` a `RUTA_UI`, `cat` y `rm` en una sola orden (el volcado
    puede llevar lo escrito en un campo: no queda en el teléfono). Reintenta si no sale («could not get idle state»).

    La salida de `uiautomator` («UI hierchary dumped to: …» o «ERROR: …») llega antes del XML y se descarta; si el XML
    no llega, decide el mensaje de la Falla.
    """
    orden = f"uiautomator dump {RUTA_UI} 2>&1; cat {RUTA_UI} 2>/dev/null; rm -f {RUTA_UI}"
    ocupada = False
    for _ in range(intentos):
        r = adb("exec-out", orden, timeout=60)
        inicio, fin = r.salida.find("<hierarchy"), r.salida.rfind("</hierarchy>")
        if inicio >= 0 and fin > inicio:
            return parsear_ui(r.salida[inicio : fin + len("</hierarchy>")])
        ocupada = ocupada or "idle state" in r.texto
        dormir(1)
    if ocupada:
        raise Falla(
            f"uiautomator dump no devolvió la pantalla en {intentos} intentos: «could not get idle state» (la pantalla "
            "no deja de cambiar, p. ej. una animación sin fin)"
        )
    raise Falla(f"uiautomator dump no devolvió la pantalla en {intentos} intentos (¿pantalla bloqueada o apagada?)")


def textos_visibles(nodos: list[Nodo], limite: int = 12) -> str:
    """Textos de la pantalla para un diagnóstico, sin campos de texto (pueden llevar el correo o la contraseña) y solo
    de la app o de un diálogo del sistema (`PAQUETES_SISTEMA`): los de otras apps (la pantalla de inicio lista las apps
    instaladas del usuario) no se imprimen; solo se dice que se omitieron (FE-4.1)."""
    vistos: list[str] = []
    ajenos = 0
    for n in nodos:
        if n.es_campo or n.contrasena:
            continue
        t = (n.texto or n.descripcion).strip()
        if not t:
            continue
        if not n.de_la_app and n.paquete not in PAQUETES_SISTEMA:
            ajenos += 1
        elif t not in vistos:
            vistos.append(t)
    if not vistos and ajenos:
        return "(la app no está en primer plano: se ve otra app o la pantalla de inicio; sus textos no se muestran)"
    texto = ", ".join(f"«{resumir(t, 40)}»" for t in vistos[:limite]) or "(nada legible)"
    return f"{texto} (y {ajenos} textos de otra app, omitidos)" if ajenos else texto


def tocar(nodo: Nodo) -> None:
    """`input tap` en el centro del nodo."""
    x, y = nodo.centro
    r = adb("shell", "input", "tap", str(x), str(y), timeout=30)
    exigir_adb_permitido(r, "tocar la pantalla (input tap)")
    if r.codigo != 0:
        raise Falla(f"adb input tap falló (código {r.codigo})")


def escapar_input_text(texto: str) -> str:
    """Texto para `adb shell input text`: espacio → `%s`; lo demás que no sea `[A-Za-z0-9@._-+,:=/]`, con `\\` delante
    (el `sh` del teléfono lo toma literal). `input text` convierte cualquier `%s` en espacio, así que un texto con
    `%s` no se puede escribir → ErrorConfiguracion. Solo ASCII imprimible (si no → ErrorConfiguracion). El mensaje de
    error nunca lleva el texto."""
    if not texto:
        raise ErrorConfiguracion("input text: texto vacío")
    if "%s" in texto:
        raise ErrorConfiguracion("input text no puede escribir «%s» (lo convierte en espacio)")
    partes = []
    for c in texto:
        if c == " ":
            partes.append("%s")
        elif c in _SEGUROS_INPUT:
            partes.append(c)
        elif " " < c <= "~":
            partes.append("\\" + c)
        else:
            raise ErrorConfiguracion("input text solo escribe ASCII imprimible: el texto tiene otro carácter")
    return "".join(partes)


def escribir_texto(texto: str) -> None:
    """`adb shell input text <texto escapado>` en el campo con el foco. Nunca imprime el texto ni la salida de adb."""
    r = adb("shell", "input", "text", escapar_input_text(texto), timeout=60)
    exigir_adb_permitido(r, "escribir (input text)")
    if r.codigo != 0:
        raise Falla(f"adb input text falló (código {r.codigo})")


def tecla(codigo: str) -> None:
    """`input keyevent <codigo>` (p. ej. `TECLA_ATRAS`)."""
    r = adb("shell", "input", "keyevent", codigo, timeout=30)
    exigir_adb_permitido(r, "pulsar una tecla (input keyevent)")


def teclado_visible() -> bool:
    """¿Está abierto el teclado en pantalla? (`dumpsys input_method`: `mInputShown=true` o similar)."""
    return bool(_PATRON_TECLADO.search(adb("shell", "dumpsys", "input_method", timeout=30).salida))


def tamano_pantalla() -> tuple[int, int]:
    """`(ancho, alto)` en píxeles (`wm size`; si hay `Override size`, ese)."""
    medidas = _PATRON_TAMANO.findall(adb("shell", "wm", "size", timeout=30).salida)
    if not medidas:
        raise Falla("adb shell wm size no dio el tamaño de la pantalla")
    ancho, alto = medidas[-1]
    return int(ancho), int(alto)


def desplazar_hacia_abajo() -> None:
    """Desliza el dedo de abajo arriba por el centro (del 70 % al 30 % del alto): la página baja."""
    ancho, alto = tamano_pantalla()
    x = ancho // 2
    r = adb("shell", "input", "swipe", str(x), str(alto * 7 // 10), str(x), str(alto * 3 // 10), "300", timeout=30)
    exigir_adb_permitido(r, "deslizar (input swipe)")


def desplazar_hacia_arriba() -> None:
    """Desliza el dedo de arriba abajo por el centro (del 30 % al 70 % del alto): la página sube (se ve lo de arriba).
    Empieza lejos del borde superior para no abrir la cortina de notificaciones (FE-4.1)."""
    ancho, alto = tamano_pantalla()
    x = ancho // 2
    r = adb("shell", "input", "swipe", str(x), str(alto * 3 // 10), str(x), str(alto * 7 // 10), "300", timeout=30)
    exigir_adb_permitido(r, "deslizar (input swipe)")


def abrir_app() -> None:
    """`am force-stop` y `am start -W -n ACTIVIDAD` (arranque en frío: `MyApp` borra la sesión, ARCHITECTURE §5.3)."""
    adb("shell", "am", "force-stop", PAQUETE, timeout=30)
    r = adb("shell", "am", "start", "-W", "-n", ACTIVIDAD, timeout=60)
    if r.codigo != 0 or "Error" in r.texto:
        raise Falla(f"am start falló: {resumir(r.texto, 200)}")


def esperar_nodo(encontrar: Callable[[list[Nodo]], Nodo | None], limite_s: float, que: str) -> tuple[Nodo, list[Nodo]]:
    """Vuelca la pantalla cada ~1 s hasta que `encontrar(nodos)` dé un nodo; si no llega en `limite_s` → Falla con lo
    que se veía."""
    fin = reloj() + limite_s
    nodos: list[Nodo] = []
    while True:
        nodos = volcar_pantalla()
        nodo = encontrar(nodos)
        if nodo is not None:
            return nodo, nodos
        if reloj() >= fin:
            raise Falla(f"en {limite_s:.0f} s no apareció {que}; en pantalla: {textos_visibles(nodos)}")
        dormir(1)


def primero(nodos: list[Nodo], *, dice: str | None = None, contiene: str | None = None) -> Nodo | None:
    for n in nodos:
        if (dice is not None and n.dice(dice)) or (contiene is not None and n.contiene(contiene)):
            return n
    return None


def campos_texto(nodos: list[Nodo]) -> list[Nodo]:
    """Los campos de texto visibles, de arriba abajo."""
    return sorted((n for n in nodos if n.es_campo), key=lambda n: (n.limites[1], n.limites[0]))


def abrir_login(limite_s: float = 30) -> None:
    """Abre la app en frío, toca «Acceso administrador» (Inicio, 6.1) y espera el formulario de Login (7.1): dos campos
    y «Iniciar sesión». Los permisos de Inicio deben estar concedidos (si no, el diálogo del sistema lo tapa)."""
    abrir_app()
    acceso, _ = esperar_nodo(lambda ns: primero(ns, dice="Acceso administrador"), limite_s, "«Acceso administrador»")
    tocar(acceso)
    esperar_nodo(
        lambda ns: primero(ns, dice="Iniciar sesión") if len(campos_texto(ns)) >= 2 else None,
        15,
        "el formulario de Login (dos campos e «Iniciar sesión»)",
    )


def _visible_o_sin_teclado(encontrar: Callable[[list[Nodo]], Nodo | None], que: str) -> Nodo:
    """El nodo, en la pantalla actual o tras cerrar el teclado (Atrás solo si está abierto), o Falla."""
    nodos = volcar_pantalla()
    nodo = encontrar(nodos)
    if nodo is None and teclado_visible():
        tecla(TECLA_ATRAS)
        dormir(1)
        nodos = volcar_pantalla()
        nodo = encontrar(nodos)
    if nodo is None:
        raise Falla(f"no se ve {que}; en pantalla: {textos_visibles(nodos)}")
    return nodo


def enviar_credenciales(correo: str, password: str) -> float:
    """En Login: escribe `correo` en el primer campo y `password` en el segundo (`input text`, escapados, nunca
    impresos), toca «Iniciar sesión» y devuelve `reloj()` justo antes del toque. Si el teclado tapa el botón, lo cierra
    con Atrás. «Iniciar sesión» deshabilitado (algún campo quedó vacío) → Falla."""
    campos = campos_texto(volcar_pantalla())
    if len(campos) < 2:
        raise Falla("Login no muestra los dos campos")
    tocar(campos[0])
    dormir(0.5)
    escribir_texto(correo)
    segundo = _visible_o_sin_teclado(lambda ns: (campos_texto(ns)[1:2] or [None])[0], "el campo de la contraseña")
    tocar(segundo)
    dormir(0.5)
    escribir_texto(password)
    boton = _visible_o_sin_teclado(lambda ns: primero(ns, dice="Iniciar sesión"), "«Iniciar sesión»")
    if not boton.habilitado:
        raise Falla("«Iniciar sesión» sigue deshabilitado: algún campo quedó vacío (¿adb input text no escribió?)")
    inicio = reloj()
    tocar(boton)
    return inicio


# --- Validador -------------------------------------------------------------------------------------------------


# --- FE-2.1: embedding en dev, objetos del dataset en S3 y tamaño de un JPEG ---------------------------------------

ZONA_BOGOTA = timezone(timedelta(hours=-5))  # Colombia no tiene horario de verano
HORA_APAGADO_NOCHE = 22  # embedding se apaga solo a las 22:00 de Bogotá (infra §3.4)
NAMESPACE_METRICAS = "campus-locator/dev"
METRICA_ENCENDIDOS = "EmbeddingEncendidos"
ALARMA_INACTIVIDAD = "campus-locator-dev-embedding-inactivo"
CODIGOS_TODAVIA_NO = {"ThrottlingException", "Throttling", "TooManyRequestsException", "RequestLimitExceeded"}


def hora_bogota(ahora: datetime | None = None) -> datetime:
    """Hora de Bogotá (UTC−5 fijo). Las pruebas pasan `ahora` (con zona)."""
    return (ahora or datetime.now(UTC)).astimezone(ZONA_BOGOTA)


def recurso_ecs(cluster: str, servicio: str) -> str:
    return f"service/{cluster}/{servicio}"


class EmbeddingDev:
    """Encender y apagar `embedding` en `dev` con el contrato de infra §5.10, con la CLI `aws` (ADR-FE-15; el backend
    lo reescribe con boto3 como `comun.EmbeddingDev`: las carpetas no comparten código de validación).

    `encender(listo)`: 1) rango 0–1 de `embedding` y `worker` (`register-scalable-target`); 2) latido
    (`put-metric-data` de `EmbeddingEncendidos` = 1); 3) hasta 5 min a que `get-metric-statistics` vea el latido, 60 s
    más y que la alarma `campus-locator-dev-embedding-inactivo` no esté en `ALARM`; 4) `update-service` de `embedding`
    a 1; 5) hasta 10 min desde el paso 1 a un despliegue `PRIMARY` `COMPLETED` con una tarea `HEALTHY` registrada en
    Cloud Map (`servicediscovery list-instances` con su IP privada; no `get-instances-health-status`, trampa de backend
    §5.11); 6) hasta 2 min a que `listo()` sea cierto (en la app: `/v1/health/ready` con `"embedding": "ok"`).
    `apagar()`: rango 0–0 y `desiredCount = 0` de los dos (no espera). Los límites de peticiones de AWS mientras espera
    son «todavía no» (`CODIGOS_TODAVIA_NO`); un permiso que falta es `ErrorConfiguracion`; el resto, `ErrorAws`.
    """

    LIMITE_ALARMA_S = 300
    LIMITE_ENCENDIDO_S = 600
    LIMITE_API_S = 120
    PAUSA_S = 15

    def __init__(self, cluster: str, servicio_embedding: str = "embedding", servicio_worker: str = "worker") -> None:
        self.cluster = cluster
        self.embedding = servicio_embedding
        self.worker = servicio_worker

    def comprobar_inf21(self) -> str:
        """Los objetivos escalables de `embedding` y `worker` existen (los crea INF-2.1); si no → Bloqueo."""
        datos = aws_json(
            "application-autoscaling",
            "describe-scalable-targets",
            "--service-namespace",
            "ecs",
            "--resource-ids",
            recurso_ecs(self.cluster, self.embedding),
            recurso_ecs(self.cluster, self.worker),
            accion="application-autoscaling describe-scalable-targets",
        )
        encontrados = {t.get("ResourceId") for t in (datos or {}).get("ScalableTargets", []) if isinstance(t, dict)}
        faltan = [s for s in (self.embedding, self.worker) if recurso_ecs(self.cluster, s) not in encontrados]
        if faltan:
            raise Bloqueo(f"INF-2.1: no hay objetivo escalable de {', '.join(faltan)}")
        return "objetivos escalables de embedding y worker"

    def _rango(self, servicio: str, maximo: int) -> None:
        aws_json(
            "application-autoscaling",
            "register-scalable-target",
            "--service-namespace",
            "ecs",
            "--scalable-dimension",
            "ecs:service:DesiredCount",
            "--resource-id",
            recurso_ecs(self.cluster, servicio),
            "--min-capacity",
            "0",
            "--max-capacity",
            str(maximo),
            accion=f"register-scalable-target {servicio} 0-{maximo}",
        )

    def _poner(self, servicio: str, replicas: int) -> None:
        aws_json(
            "ecs",
            "update-service",
            "--cluster",
            self.cluster,
            "--service",
            servicio,
            "--desired-count",
            str(replicas),
            "--query",
            "service.desiredCount",
            accion=f"ecs update-service {servicio} → {replicas}",
        )

    def latido(self, cuando: datetime | None = None) -> datetime:
        """`PutMetricData` de `EmbeddingEncendidos` = 1 (`Count`, con `Timestamp` explícito). Devuelve la marca."""
        marca = (cuando or datetime.now(UTC)).replace(microsecond=0)
        aws_json(
            "cloudwatch",
            "put-metric-data",
            "--namespace",
            NAMESPACE_METRICAS,
            "--metric-data",
            f"MetricName={METRICA_ENCENDIDOS},Value=1,Unit=Count,Timestamp={marca.strftime('%Y-%m-%dT%H:%M:%SZ')}",
            accion="cloudwatch put-metric-data",
        )
        return marca

    def _sondear(self, que: str, *argumentos: str) -> object | None:
        """Una llamada de espera: los límites de peticiones son «todavía no» (None); el resto se traduce."""
        try:
            return aws_json(*argumentos, accion=que)
        except ErrorAws as e:
            if e.codigo in CODIGOS_TODAVIA_NO:
                return None
            raise

    def _latido_visto(self, marca: datetime) -> bool:
        inicio = (marca - timedelta(minutes=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
        fin = (marca + timedelta(minutes=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
        datos = self._sondear(
            "cloudwatch get-metric-statistics",
            "cloudwatch",
            "get-metric-statistics",
            "--namespace",
            NAMESPACE_METRICAS,
            "--metric-name",
            METRICA_ENCENDIDOS,
            "--start-time",
            inicio,
            "--end-time",
            fin,
            "--period",
            "60",
            "--statistics",
            "Sum",
        )
        return isinstance(datos, dict) and any((p or {}).get("Sum", 0) >= 1 for p in datos.get("Datapoints", []))

    def _alarma_en_alarm(self) -> bool | None:
        datos = self._sondear(
            "cloudwatch describe-alarms", "cloudwatch", "describe-alarms", "--alarm-names", ALARMA_INACTIVIDAD
        )
        if not isinstance(datos, dict):
            return None
        alarmas = datos.get("MetricAlarms") or []
        if not alarmas:
            raise Bloqueo(f"INF-2.1: no existe la alarma {ALARMA_INACTIVIDAD}")
        return alarmas[0].get("StateValue") == "ALARM"

    def _sano(self) -> tuple[bool, str]:
        """¿Despliegue PRIMARY COMPLETED con una tarea HEALTHY registrada en Cloud Map? `(sí/no, lo que falta)`."""
        servicio = self._sondear(
            "ecs describe-services",
            "ecs",
            "describe-services",
            "--cluster",
            self.cluster,
            "--services",
            self.embedding,
            "--query",
            "services[0].{despliegues: deployments, registros: serviceRegistries}",
        )
        if not isinstance(servicio, dict):
            return False, "describe-services sin respuesta"
        primario = next((d for d in servicio.get("despliegues") or [] if d.get("status") == "PRIMARY"), None)
        if not primario or primario.get("rolloutState") != "COMPLETED":
            return False, "despliegue PRIMARY sin COMPLETED"
        tareas = self._sondear(
            "ecs list-tasks",
            "ecs",
            "list-tasks",
            "--cluster",
            self.cluster,
            "--service-name",
            self.embedding,
            "--desired-status",
            "RUNNING",
            "--query",
            "taskArns",
        )
        if not tareas:
            return False, "sin tareas en marcha"
        detalle = self._sondear(
            "ecs describe-tasks",
            "ecs",
            "describe-tasks",
            "--cluster",
            self.cluster,
            "--tasks",
            *[str(t) for t in tareas],
            "--query",
            "tasks[].{salud: healthStatus, adjuntos: attachments}",
        )
        sanas = [t for t in detalle or [] if isinstance(t, dict) and t.get("salud") == "HEALTHY"]
        if not sanas:
            return False, "sin tarea HEALTHY"
        ips = {
            d.get("value")
            for t in sanas
            for a in t.get("adjuntos") or []
            for d in a.get("details") or []
            if d.get("name") == "privateIPv4Address"
        }
        registros = servicio.get("registros") or []
        arn = registros[0].get("registryArn", "") if registros else ""
        if not arn:
            return True, ""  # sin registro en Cloud Map que mirar
        instancias = self._sondear(
            "servicediscovery list-instances",
            "servicediscovery",
            "list-instances",
            "--service-id",
            arn.rsplit("/", 1)[-1],
            "--query",
            "Instances[].Attributes.AWS_INSTANCE_IPV4",
        )
        if not instancias:
            return False, "Cloud Map sin instancias registradas"
        if ips and not ips.intersection(set(instancias)):
            return False, "Cloud Map sin la IP de la tarea sana"
        return True, ""

    def encender(self, listo: Callable[[], bool]) -> float:
        """El contrato de arriba. Devuelve los segundos que tardó; si no queda sano a tiempo → Bloqueo (INF-2.1)."""
        inicio = reloj()
        for servicio in (self.embedding, self.worker):
            self._rango(servicio, 1)
        marca = self.latido()
        while not self._latido_visto(marca):
            if reloj() - inicio > self.LIMITE_ALARMA_S:
                raise Bloqueo("INF-2.1: CloudWatch no ve el latido de EmbeddingEncendidos en 5 min")
            dormir(self.PAUSA_S)
        dormir(60)
        while self._alarma_en_alarm() is not False:
            if reloj() - inicio > self.LIMITE_ALARMA_S + 60:
                raise Bloqueo(f"INF-2.1: la alarma {ALARMA_INACTIVIDAD} sigue en ALARM")
            dormir(self.PAUSA_S)
        self._poner(self.embedding, 1)
        falta = ""
        while True:
            sano, falta = self._sano()
            if sano:
                break
            if reloj() - inicio > self.LIMITE_ENCENDIDO_S:
                raise Bloqueo(f"INF-2.1: embedding no quedó sano en {self.LIMITE_ENCENDIDO_S // 60} min ({falta})")
            dormir(self.PAUSA_S)
        limite_api = reloj() + self.LIMITE_API_S
        while not listo():
            if reloj() > limite_api:
                raise Bloqueo("BE-2.2: embedding está sano pero /v1/health/ready no dice embedding ok en 2 min")
            dormir(self.PAUSA_S)
        return reloj() - inicio

    def apagar(self) -> None:
        for servicio in (self.embedding, self.worker):
            self._rango(servicio, 0)
            self._poner(servicio, 0)


def dimensiones_jpeg(datos: bytes) -> tuple[int, int] | None:
    """`(ancho, alto)` del marcador SOF de un JPEG (los primeros bytes bastan), o None si no es un JPEG o no llega
    al SOF. Sin Pillow: solo biblioteca estándar."""
    if len(datos) < 4 or datos[0:2] != b"\xff\xd8":
        return None
    i = 2
    sof = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
    while i + 1 < len(datos):
        if datos[i] != 0xFF:
            i += 1
            continue
        marcador = datos[i + 1]
        if marcador == 0xFF:  # relleno
            i += 1
            continue
        if marcador in (0x01, 0xD8) or 0xD0 <= marcador <= 0xD7:
            i += 2
            continue
        if marcador in (0xD9, 0xDA):  # fin o inicio de los datos: ya no hay SOF antes
            return None
        if i + 4 > len(datos):
            return None
        largo = int.from_bytes(datos[i + 2 : i + 4], "big")
        if marcador in sof:
            if i + 9 > len(datos):
                return None
            alto = int.from_bytes(datos[i + 5 : i + 7], "big")
            ancho = int.from_bytes(datos[i + 7 : i + 9], "big")
            return ancho, alto
        i += 2 + largo
    return None


@dataclass
class ObjetoS3:
    clave: str
    bytes: int
    dimensiones: tuple[int, int] | None


_PATRON_RANGO = re.compile(r"/(\d+)\s*$")


def leer_objeto_s3(bucket: str, clave: str, *, primeros: int = 131072) -> ObjetoS3:
    """Tamaño total y dimensiones de un JPEG del bucket sin bajarlo entero: `aws s3api get-object --range
    bytes=0-<primeros-1>` a un temporal (el total sale de `ContentRange`). Solo lectura. No existe → ErrorAws
    (`NoSuchKey`). Nunca usa ni imprime URLs prefirmadas."""
    with tempfile.TemporaryDirectory(prefix="validacion-") as carpeta:
        destino = Path(carpeta) / "objeto.jpg"
        datos = aws_json(
            "s3api",
            "get-object",
            "--bucket",
            bucket,
            "--key",
            clave,
            "--range",
            f"bytes=0-{primeros - 1}",
            str(destino),
            accion=f"s3api get-object {clave}",
        )
        contenido = destino.read_bytes() if destino.is_file() else b""
    rango = str((datos or {}).get("ContentRange") or "")
    m = _PATRON_RANGO.search(rango)
    total = int(m.group(1)) if m else int((datos or {}).get("ContentLength") or len(contenido))
    return ObjetoS3(clave, total, dimensiones_jpeg(contenido))


# --- FE-4.1: subir fotos de prueba por la API de recolección (sin la app) -----------------------------------------


def http_put_bytes(url: str, datos: bytes, encabezados: dict[str, str], *, timeout: float = 60.0) -> RespuestaHttp:
    """`PUT` de `datos` a una URL prefirmada de S3 con **exactamente** los `encabezados` que dio el backend (backend
    §5.4: `Content-Type` va en la firma). Sin `X-Request-Id` ni `Authorization` (como `SubidorS3` de la app). La URL
    lleva la firma en la *query*: nunca se imprime ni va a un mensaje (un error dice solo el tipo). 4xx/5xx se
    devuelven; sin respuesta → ErrorRed."""
    peticion = urllib.request.Request(url, data=datos, method="PUT", headers=dict(encabezados))
    inicio = time.monotonic()
    try:
        with urllib.request.urlopen(peticion, timeout=timeout) as r:  # noqa: S310 — URL https del backend
            return RespuestaHttp(
                r.status, dict(r.headers.items()), r.read().decode("utf-8", errors="replace"), _ms(inicio)
            )
    except urllib.error.HTTPError as e:
        return RespuestaHttp(e.code, dict(e.headers.items()), e.read().decode("utf-8", errors="replace"), _ms(inicio))
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        motivo = getattr(e, "reason", e)
        raise ErrorRed(f"PUT a S3 sin respuesta ({type(motivo).__name__})") from None


# Tabla de Huffman de los coeficientes DC de luminancia (JPEG, anexo K.3) y una de AC con un solo símbolo, EOB (0x00),
# de un bit: los bloques son de un solo tono, así que no hay coeficientes AC.
_DC_BITS = (0, 1, 5, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0)
_DC_VALORES = tuple(range(12))
_AC_BITS = (1,) + (0,) * 15
_AC_VALORES = (0x00,)
_CUANTIZACION = 8  # el coeficiente DC cuantizado queda en el nivel de gris − 128


def _codigos_huffman(bits: tuple[int, ...], valores: tuple[int, ...]) -> dict[int, tuple[int, int]]:
    """Códigos canónicos `{símbolo: (código, longitud)}` de una tabla DHT."""
    codigos: dict[int, tuple[int, int]] = {}
    codigo, k = 0, 0
    for longitud in range(1, 17):
        for _ in range(bits[longitud - 1]):
            codigos[valores[k]] = (codigo, longitud)
            codigo += 1
            k += 1
        codigo <<= 1
    return codigos


class _EscritorBits:
    def __init__(self) -> None:
        self.salida = bytearray()
        self._acumulado = 0
        self._n = 0

    def poner(self, valor: int, longitud: int) -> None:
        for i in range(longitud - 1, -1, -1):
            self._acumulado = (self._acumulado << 1) | ((valor >> i) & 1)
            self._n += 1
            if self._n == 8:
                self.salida.append(self._acumulado)
                if self._acumulado == 0xFF:
                    self.salida.append(0x00)  # relleno de bytes (byte stuffing)
                self._acumulado, self._n = 0, 0

    def cerrar(self) -> bytes:
        if self._n:
            faltan = 8 - self._n
            self.poner((1 << faltan) - 1, faltan)  # se completa con unos
        return bytes(self.salida)


def _segmento(marcador: int, cuerpo: bytes) -> bytes:
    return bytes((0xFF, marcador)) + (len(cuerpo) + 2).to_bytes(2, "big") + cuerpo


def jpeg_sintetico(ancho: int = 640, alto: int = 480, semilla: int = 0) -> bytes:
    """JPEG *baseline* en escala de grises hecho a mano, sin Pillow (FE-4.1): bloques de 8×8 de un solo tono que dibujan
    franjas diagonales según `semilla` (la misma semilla, los mismos bytes; distintas, otros bytes). `ancho` y `alto`
    deben ser múltiplos de 8. 640×480 ocupa ~4 KB; su lado menor (480) cumple el mínimo del `worker` (320, backend
    §5.10). `dimensiones_jpeg` lo lee; la decodificación con libjpeg se prueba si hay Pillow."""
    if ancho <= 0 or alto <= 0 or ancho % 8 or alto % 8:
        raise ValueError("jpeg_sintetico: ancho y alto deben ser múltiplos de 8")
    dc, ac = _codigos_huffman(_DC_BITS, _DC_VALORES), _codigos_huffman(_AC_BITS, _AC_VALORES)
    bits = _EscritorBits()
    anterior = 0
    for by in range(alto // 8):
        for bx in range(ancho // 8):
            nivel = 28 + (bx * 3 + by * 5 + semilla * 37) % 200
            valor = nivel - 128  # DC cuantizado: 8·(nivel − 128) / _CUANTIZACION
            diferencia = valor - anterior
            anterior = valor
            categoria = abs(diferencia).bit_length()
            codigo, longitud = dc[categoria]
            bits.poner(codigo, longitud)
            if categoria:
                bits.poner(diferencia if diferencia >= 0 else diferencia + (1 << categoria) - 1, categoria)
            codigo, longitud = ac[0x00]  # EOB: el resto del bloque es cero
            bits.poner(codigo, longitud)
    salida = bytearray(b"\xff\xd8")
    salida += _segmento(0xE0, b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00")
    salida += _segmento(0xDB, b"\x00" + bytes([_CUANTIZACION] * 64))
    salida += _segmento(0xC0, b"\x08" + alto.to_bytes(2, "big") + ancho.to_bytes(2, "big") + b"\x01\x01\x11\x00")
    salida += _segmento(0xC4, b"\x00" + bytes(_DC_BITS) + bytes(_DC_VALORES))
    salida += _segmento(0xC4, b"\x10" + bytes(_AC_BITS) + bytes(_AC_VALORES))
    salida += _segmento(0xDA, b"\x01\x01\x00\x00\x3f\x00")
    salida += bits.cerrar()
    salida += b"\xff\xd9"
    return bytes(salida)


@dataclass
class _Entrada:
    id: str
    estado: str
    detalle: str = ""
    duracion_ms: int | None = None


@dataclass
class Validador:
    """Ciclo de vida de un validador (contrato común, infra §5.11). Uso: `sys.exit(Validador(...).correr(cuerpo))`."""

    lote: str
    validacion: str
    descripcion: str
    comprobaciones: list[str]
    entornos: tuple[str, ...] = ENTORNOS
    grupos: dict[str, list[str]] = field(default_factory=dict)
    # FE-2.1: argumentos propios del lote (contrato común, infra §5.11), p. ej. `--video`; quedan en `args`.
    argumentos: Callable[[argparse.ArgumentParser], None] | None = None
    # Estado de la ejecución
    entorno: str = ""
    sello: str = ""
    args: argparse.Namespace | None = None
    _solo: set[str] | None = None
    _sin_limpieza: bool = False
    _informe: Path | None = None
    _precondiciones: list[_Entrada] = field(default_factory=list)
    _comprobaciones: list[_Entrada] = field(default_factory=list)
    _manuales: list[dict[str, str]] = field(default_factory=list)
    _limpiezas: list[tuple[str, Callable[[], object]]] = field(default_factory=list)
    _codigo_pre: int = 0

    # --- argumentos

    def _leer_argumentos(self, argv: list[str] | None) -> None:
        p = argparse.ArgumentParser(description=self.descripcion, formatter_class=argparse.RawDescriptionHelpFormatter)
        p.add_argument("--entorno", required=True, choices=ENTORNOS)
        p.add_argument("--informe", type=Path, default=None)
        p.add_argument("--solo", default=None, help="IDs separados por comas: " + ", ".join(self.comprobaciones))
        p.add_argument("--sin-limpieza", action="store_true")
        if self.argumentos is not None:
            self.argumentos(p)
        a = p.parse_args(argv)
        self.args = a
        if a.entorno not in self.entornos:
            raise ErrorConfiguracion(f"{self.lote} no admite --entorno {a.entorno} (admite {', '.join(self.entornos)})")
        self.entorno = a.entorno
        self._informe = a.informe
        self._sin_limpieza = a.sin_limpieza
        if a.solo:
            pedidos = [s.strip() for s in a.solo.split(",") if s.strip()]
            solo: set[str] = set()
            for s in pedidos:
                if s in self.grupos:
                    solo.update(self.grupos[s])
                elif s in self.comprobaciones:
                    solo.add(s)
                else:
                    raise ErrorConfiguracion(f"--solo {s}: no existe (válidos: {', '.join(self.comprobaciones)})")
            self._solo = solo

    # --- API para el cuerpo

    def incluida(self, id_: str) -> bool:
        return self._solo is None or id_ in self._solo

    def alguna_incluida(self, *ids: str) -> bool:
        return any(self.incluida(i) for i in ids)

    def precondicion(self, id_: str, fn: Callable[[], str]) -> bool:
        try:
            detalle = fn()
            self._anotar(self._precondiciones, _Entrada(id_, "pasa", detalle or ""))
            return True
        except (Bloqueo, Falla) as e:
            self._codigo_pre = max(self._codigo_pre, 2)
            self._anotar(self._precondiciones, _Entrada(id_, "falla", str(e)))
        except ErrorConfiguracion as e:
            self._codigo_pre = 3
            self._anotar(self._precondiciones, _Entrada(id_, "falla", str(e)))
        return False

    def precondicion_no_evaluada(self, id_: str, motivo: str) -> None:
        self._anotar(self._precondiciones, _Entrada(id_, "no evaluada", motivo))

    def precondiciones_cumplidas(self) -> bool:
        return self._codigo_pre == 0

    def comprobacion(self, id_: str, fn: Callable[[], str]) -> None:
        if not self.incluida(id_):
            self._anotar(self._comprobaciones, _Entrada(id_, "omitida", "excluida con --solo"))
            return
        inicio = time.monotonic()
        try:
            detalle = fn()
            entrada = _Entrada(id_, "pasa", detalle or "")
        except Falla as e:
            entrada = _Entrada(id_, "falla", str(e))
        except ErrorConfiguracion as e:
            entrada = _Entrada(id_, "error", str(e))
        except Exception as e:  # noqa: BLE001 — cualquier imprevisto es código 3, con su traza en stderr
            traceback.print_exc(file=sys.stderr)
            entrada = _Entrada(id_, "error", f"error inesperado: {type(e).__name__}: {resumir(str(e), 200)}")
        entrada.duracion_ms = _ms(inicio)
        self._anotar(self._comprobaciones, entrada)

    def omitir(self, id_: str, motivo: str) -> None:
        """Comprobación que no aplica en este entorno (p. ej. la que necesita dispositivo en `local`)."""
        self._anotar(self._comprobaciones, _Entrada(id_, "omitida", motivo))

    def manual(self, id_: str, instruccion: str) -> None:
        self._manuales.append({"id": id_, "instruccion": instruccion})
        print(f"[MANUAL] {id_} {instruccion}", flush=True)

    def al_limpiar(self, descripcion: str, fn: Callable[[], object]) -> None:
        self._limpiezas.append((descripcion, fn))

    # --- ciclo

    def correr(self, cuerpo: Callable[[Validador], None], argv: list[str] | None = None) -> int:
        inicio = datetime.now(UTC)
        self.sello = inicio.strftime("%Y%m%d-%H%M%S")
        try:
            self._leer_argumentos(argv)
        except SystemExit as e:  # argparse: --help (0) o error de uso (2 → 3)
            return 0 if e.code == 0 else 3
        except ErrorConfiguracion as e:
            print(f"[ERROR] {e}", flush=True)
            return 3
        error_cuerpo = None
        try:
            cuerpo(self)
        except Exception as e:  # noqa: BLE001
            traceback.print_exc(file=sys.stderr)
            error_cuerpo = f"{type(e).__name__}: {resumir(str(e), 200)}"
            print(f"[ERROR] {error_cuerpo}", flush=True)
        finally:
            self._limpiar()
        codigo = self._codigo(error_cuerpo)
        self._escribir_informe(inicio, codigo)
        return codigo

    def _limpiar(self) -> None:
        if self._sin_limpieza:
            if self._limpiezas:
                avisar("--sin-limpieza: no se limpia")
            return
        for descripcion, fn in reversed(self._limpiezas):
            try:
                fn()
                avisar(f"limpieza: {descripcion}")
            except Exception as e:  # noqa: BLE001
                print(f"[LIMPIEZA] falló {descripcion}: {resumir(str(e), 200)}", flush=True)

    def _codigo(self, error_cuerpo: str | None) -> int:
        if error_cuerpo is not None or self._codigo_pre == 3:
            return 3
        if self._codigo_pre == 2:
            return 2
        estados = {c.estado for c in self._comprobaciones}
        if "error" in estados:
            return 3
        if "falla" in estados:
            return 1
        return 0

    def _anotar(self, lista: list[_Entrada], entrada: _Entrada) -> None:
        lista.append(entrada)
        etiqueta = {"pasa": "PASA", "falla": "FALLA", "error": "ERROR", "omitida": "OMITIDA"}.get(
            entrada.estado, entrada.estado.upper()
        )
        print(f"[{etiqueta}] {entrada.id} {entrada.detalle}".rstrip(), flush=True)

    def _escribir_informe(self, inicio: datetime, codigo: int) -> None:
        resultado = {0: "pasa", 1: "falla", 2: "bloqueado"}.get(codigo, "error")
        datos = {
            "lote": self.lote,
            "validacion": self.validacion,
            "entorno": self.entorno,
            "commit": commit_actual(),
            "inicio": inicio.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "fin": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "resultado": resultado,
            "precondiciones": [{"id": p.id, "estado": p.estado, "detalle": p.detalle} for p in self._precondiciones],
            "comprobaciones": [
                {"id": c.id, "estado": c.estado, "detalle": c.detalle, "duracion_ms": c.duracion_ms}
                for c in self._comprobaciones
            ],
            "manuales": self._manuales,
        }
        ruta = self._informe or DIR_INFORMES / f"{self.lote}-{self.sello}.json"
        try:
            ruta.parent.mkdir(parents=True, exist_ok=True)
            ruta.write_text(json.dumps(datos, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            avisar(f"informe: {ruta}")
        except OSError as e:
            print(f"[ERROR] no se pudo escribir el informe: {e}", flush=True)
        print(f"Resultado: {resultado} (código {codigo})", flush=True)
