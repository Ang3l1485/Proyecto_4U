"""Ayudas comunes de los validadores de INFRASTRUCTURA_TERRAFORM.

Implementa el contrato de ARCHITECTURE.md §5.11:
- argumentos `--entorno {local|dev}`, `--informe RUTA`, `--solo C1,C3` y `--sin-limpieza`;
- orden precondiciones → comprobaciones automáticas → manuales → limpieza (siempre) → informe;
- estados `pasa`, `falla`, `manual`, `omitida` y códigos de salida 0 (pasa), 1 (falla), 2 (bloqueado), 3 (error);
- informe: una línea por comprobación en stdout y un JSON en `project/.validacion/<lote>-<AAAAMMDD-HHMMSS>.json`.

Lo propio de esta carpeta: cuenta 648617469176, región us-east-1, solo entorno `dev`, outputs con
`terraform -chdir=… output -json` y GitHub con la CLI `gh`. Nunca imprime secretos, tokens ni URLs prefirmadas.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator

CUENTA = "648617469176"
REGION = "us-east-1"
ENTORNOS_ADMITIDOS = ("dev",)
PROYECTO = Path(__file__).resolve().parents[2]  # INFRASTRUCTURA_TERRAFORM/project
DIR_INFORMES = PROYECTO / ".validacion"

PASA = "pasa"
FALLA = "falla"
MANUAL = "manual"
OMITIDA = "omitida"

SALIDA_PASA = 0
SALIDA_FALLA = 1
SALIDA_BLOQUEADO = 2
SALIDA_ERROR = 3
RESULTADOS = {
    SALIDA_PASA: "pasa",
    SALIDA_FALLA: "falla",
    SALIDA_BLOQUEADO: "bloqueado",
    SALIDA_ERROR: "error",
}

ERRORES_DE_CREDENCIALES = {
    "403",  # head_object no trae cuerpo: S3 devuelve solo el código HTTP
    "Forbidden",
    "AccessDenied",
    "AccessDeniedException",
    "UnauthorizedOperation",
    "UnrecognizedClientException",
    "InvalidClientTokenId",
    "ExpiredToken",
    "ExpiredTokenException",
    "SignatureDoesNotMatch",
}

PATRON_CREDENCIALES_TERRAFORM = re.compile(
    r"No valid credential sources|NoCredentialProviders|failed to refresh cached credentials|"
    r"ExpiredToken|InvalidClientTokenId|AccessDenied|SSO session",
    re.IGNORECASE,
)
PATRON_SIN_INIT = re.compile(
    r"Backend initialization required|terraform init|has not been initialized|Required plugins are not installed|"
    r"Inconsistent dependency lock file",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------------------------------------------------
# Excepciones: cada una corresponde a un código de salida
# ---------------------------------------------------------------------------------------------------------------------


class Falla(Exception):
    """La comprobación se ejecutó y no pasa (código 1)."""


class Bloqueo(Exception):
    """Una precondición no se cumple porque otro lote o recurso no está listo (código 2)."""


class ErrorConfiguracion(Exception):
    """Faltan credenciales, herramientas o variables, o el uso es incorrecto (código 3)."""


# ---------------------------------------------------------------------------------------------------------------------
# Consola y utilidades
# ---------------------------------------------------------------------------------------------------------------------


def preparar_consola() -> None:
    """En Windows la consola puede no ser UTF-8: se reemplaza lo que no se pueda mostrar en vez de fallar."""
    for flujo in (sys.stdout, sys.stderr):
        try:
            flujo.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass


def avisar(mensaje: str) -> None:
    """Progreso para la persona. Va a stderr: stdout queda con una línea por comprobación."""
    print(f"  · {mensaje}", file=sys.stderr, flush=True)


def resumir(texto: str, limite: int = 300) -> str:
    linea = " ".join(str(texto).split())
    return linea if len(linea) <= limite else linea[: limite - 1] + "…"


def ahora_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def iso(momento: dt.datetime) -> str:
    return momento.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------------------------------------------------
# Procesos externos (gh, terraform, git)
# ---------------------------------------------------------------------------------------------------------------------


@dataclass
class Resultado:
    codigo: int
    salida: str
    error: str

    @property
    def texto(self) -> str:
        return "\n".join(t for t in (self.salida.strip(), self.error.strip()) if t)


def _entorno_proceso() -> dict[str, str]:
    entorno = dict(os.environ)
    entorno.update(
        {
            "NO_COLOR": "1",
            "TF_IN_AUTOMATION": "1",
            "TF_INPUT": "0",
            "GH_PROMPT_DISABLED": "1",
            "GH_NO_UPDATE_NOTIFIER": "1",
            "GH_PAGER": "",
            "AWS_PAGER": "",
        }
    )
    return entorno


def ejecutar(comando: list[str], *, entrada: str | None = None, timeout: float = 300) -> Resultado:
    """Ejecuta un programa desde `project/` y devuelve su salida. No imprime nada."""
    ruta = shutil.which(comando[0])
    if ruta is None:
        raise ErrorConfiguracion(f"no se encuentra «{comando[0]}» en el PATH")
    try:
        proceso = subprocess.run(
            [ruta, *comando[1:]],
            cwd=PROYECTO,
            input=entrada,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=_entorno_proceso(),
        )
    except subprocess.TimeoutExpired as exc:
        raise Falla(f"«{' '.join(comando[:3])} …» no terminó en {timeout:.0f} s") from exc
    return Resultado(proceso.returncode, proceso.stdout or "", proceso.stderr or "")


def commit_actual() -> str:
    """Commit corto de HEAD; con «-dirty» si hay cambios sin commit en archivos versionados de esta carpeta
    (`project/`). Los cambios de otras carpetas del monorepo no afectan a los lotes de infraestructura."""
    try:
        resultado = ejecutar(["git", "rev-parse", "--short", "HEAD"], timeout=30)
        if resultado.codigo != 0:
            return "desconocido"
        cambios = ejecutar(["git", "diff", "--quiet", "HEAD", "--", "."], timeout=30)
    except (ErrorConfiguracion, Falla):
        return "desconocido"
    return resultado.salida.strip() + ("-dirty" if cambios.codigo == 1 else "")


class ErrorGh(Falla):
    """`gh` terminó con error. `http` es el código HTTP si `gh api` lo informó."""

    def __init__(self, argumentos: tuple[str, ...], resultado: Resultado) -> None:
        self.resultado = resultado
        coincidencia = re.search(r"HTTP (\d{3})", resultado.texto)
        self.http = int(coincidencia.group(1)) if coincidencia else None
        super().__init__(f"gh {' '.join(argumentos[:2])}: {resumir(resultado.texto)}")

    @property
    def sin_permiso(self) -> bool:
        """401/403: la sesión de gh no vale o no tiene permiso (código 3, no una falla del lote)."""
        return self.http in (401, 403)


def gh(*argumentos: str, entrada: str | None = None, timeout: float = 120) -> str:
    resultado = ejecutar(["gh", *argumentos], entrada=entrada, timeout=timeout)
    if resultado.codigo != 0:
        raise ErrorGh(argumentos, resultado)
    return resultado.salida


def gh_api(
    ruta: str,
    *,
    metodo: str = "GET",
    cuerpo: Any = None,
    paginar: bool = False,
    jq: str | None = None,
    timeout: float = 120,
) -> Any:
    """Llama a la API REST de GitHub con `gh api`. Devuelve JSON (o el texto de `--jq`)."""
    argumentos = [
        "api", ruta, "--method", metodo,
        "-H", "Accept: application/vnd.github+json",
        "-H", "X-GitHub-Api-Version: 2022-11-28",
    ]
    if paginar:
        argumentos.append("--paginate")
    if jq is not None:
        argumentos += ["--jq", jq]
    entrada = None
    if cuerpo is not None:
        argumentos += ["--input", "-"]
        entrada = json.dumps(cuerpo)
    salida = gh(*argumentos, entrada=entrada, timeout=timeout)
    if jq is not None:
        return salida
    return json.loads(salida) if salida.strip() else None


def terraform_outputs(directorio: str) -> dict[str, Any]:
    """`terraform -chdir=<directorio> output -json` → {nombre: valor}."""
    resultado = ejecutar(["terraform", f"-chdir={directorio}", "output", "-json"], timeout=180)
    if resultado.codigo != 0:
        if PATRON_CREDENCIALES_TERRAFORM.search(resultado.texto):
            raise ErrorConfiguracion(f"terraform no puede leer el estado de {directorio}: {resumir(resultado.texto)}")
        if PATRON_SIN_INIT.search(resultado.texto):
            raise ErrorConfiguracion(f"falta «terraform -chdir={directorio} init» en esta copia: {resumir(resultado.texto)}")
        raise Bloqueo(f"«terraform -chdir={directorio} output -json» falló: {resumir(resultado.texto)}")
    try:
        datos = json.loads(resultado.salida or "{}")
    except json.JSONDecodeError as exc:
        raise Bloqueo(f"«terraform -chdir={directorio} output -json» no devolvió JSON") from exc
    return {nombre: valor.get("value") for nombre, valor in datos.items()}


def terraform_state_pull(directorio: str) -> dict[str, Any]:
    """Estado activo de Terraform (en memoria; nunca se imprime: puede contener secretos)."""
    resultado = ejecutar(["terraform", f"-chdir={directorio}", "state", "pull"], timeout=180)
    if resultado.codigo != 0:
        if PATRON_CREDENCIALES_TERRAFORM.search(resultado.texto):
            raise ErrorConfiguracion(f"terraform no puede leer el estado de {directorio}: {resumir(resultado.texto)}")
        raise Falla(f"«terraform -chdir={directorio} state pull» falló: {resumir(resultado.error or resultado.salida)}")
    try:
        return json.loads(resultado.salida)
    except json.JSONDecodeError as exc:
        raise Falla(f"«terraform -chdir={directorio} state pull» no devolvió JSON") from exc


# ---------------------------------------------------------------------------------------------------------------------
# AWS
# ---------------------------------------------------------------------------------------------------------------------


def sesion_aws() -> Any:
    """Sesión de boto3 con el perfil de la persona (AWS_PROFILE) y la región del proyecto."""
    try:
        import boto3
    except ImportError as exc:
        raise ErrorConfiguracion("falta boto3: ejecuta con «uv run --group ops python …»") from exc
    return boto3.Session(region_name=REGION)


def comprobar_cuenta(sesion: Any) -> str:
    """Devuelve el ARN de quien llama. Se niega a seguir si la cuenta no es la del proyecto."""
    from botocore.exceptions import BotoCoreError, ClientError

    try:
        identidad = sesion.client("sts").get_caller_identity()
    except (BotoCoreError, ClientError) as exc:
        perfil = os.environ.get("AWS_PROFILE", "(AWS_PROFILE sin definir)")
        raise ErrorConfiguracion(f"credenciales de AWS no válidas ({perfil}): {resumir(str(exc))}") from exc
    if identidad["Account"] != CUENTA:
        raise ErrorConfiguracion(
            f"las credenciales son de la cuenta {identidad['Account']}, no de {CUENTA}: el validador no sigue"
        )
    return identidad["Arn"]


def codigo_error_aws(exc: BaseException) -> str:
    respuesta = getattr(exc, "response", None) or {}
    return str(respuesta.get("Error", {}).get("Code", "") or "")


def error_aws(exc: BaseException, accion: str) -> Exception:
    """Traduce un error de boto3: permisos o credenciales → ErrorConfiguracion; lo demás → Falla."""
    codigo = codigo_error_aws(exc)
    if codigo in ERRORES_DE_CREDENCIALES:
        return ErrorConfiguracion(f"{accion}: las credenciales no tienen permiso ({codigo})")
    if not codigo:
        return ErrorConfiguracion(f"{accion}: {resumir(str(exc))}")
    return Falla(f"{accion}: {codigo}")


@contextlib.contextmanager
def errores_aws(accion: str) -> Iterator[None]:
    from botocore.exceptions import BotoCoreError, ClientError

    try:
        yield
    except (ClientError, BotoCoreError) as exc:
        raise error_aws(exc, accion) from exc


# ---------------------------------------------------------------------------------------------------------------------
# Validador: registro de precondiciones y comprobaciones, limpieza e informe
# ---------------------------------------------------------------------------------------------------------------------


@dataclass
class Registro:
    id: str
    estado: str
    detalle: str
    duracion_ms: int | None = None
    bloqueo: bool = False  # precondición: otro lote no está listo → código 2
    error: bool = False  # credenciales, herramientas, uso o fallo inesperado → código 3


class _Parser(argparse.ArgumentParser):
    """argparse sale con 2 ante un error de uso; el contrato reserva el 2 para «bloqueado» y pide 3."""

    def error(self, message: str) -> None:  # type: ignore[override]
        self.print_usage(sys.stderr)
        print(f"{self.prog}: error: {message}", file=sys.stderr)
        sys.exit(SALIDA_ERROR)


class Validador:
    def __init__(
        self,
        *,
        lote: str,
        validacion: str,
        descripcion: str,
        comprobaciones: list[str],
        grupos: dict[str, list[str]] | None = None,
    ) -> None:
        preparar_consola()
        self.lote = lote
        self.validacion = validacion
        self.descripcion = descripcion
        self.ids = comprobaciones
        self.grupos = grupos or {}
        self.inicio = ahora_utc()
        self.sello = self.inicio.strftime("%Y%m%d-%H%M%S")
        self.args: argparse.Namespace | None = None
        self.solo: set[str] | None = None
        self.precondiciones: list[Registro] = []
        self.comprobaciones: list[Registro] = []
        self.manuales: list[dict[str, str]] = []
        self._limpiezas: list[tuple[str, Callable[[], None]]] = []
        self._error_general: str | None = None

    # -- argumentos ---------------------------------------------------------------------------------------------------

    def leer_argumentos(self, argv: list[str] | None = None) -> argparse.Namespace:
        parser = _Parser(description=self.descripcion, formatter_class=argparse.RawDescriptionHelpFormatter)
        parser.add_argument("--entorno", required=True, choices=["local", "dev"], help="entorno a validar (este lote: dev)")
        parser.add_argument("--informe", type=Path, help="ruta del informe JSON (por defecto, project/.validacion/)")
        ids = ", ".join(self.ids + [g for g in self.grupos if g not in self.ids])
        parser.add_argument("--solo", metavar="IDS", help=f"solo estas comprobaciones, separadas por comas ({ids})")
        parser.add_argument("--sin-limpieza", action="store_true", help="no borra los datos de prueba al terminar")
        self.args = parser.parse_args(argv)
        if self.args.solo is not None:
            self.solo = self._resolver_solo(self.args.solo)
        return self.args

    def _resolver_solo(self, texto: str) -> set[str]:
        conocidos = {i.lower(): [i] for i in self.ids}
        conocidos.update({g.lower(): miembros for g, miembros in self.grupos.items()})
        elegidos: set[str] = set()
        for parte in (p.strip() for p in texto.split(",")):
            if not parte:
                continue
            if parte.lower() not in conocidos:
                raise ErrorConfiguracion(f"--solo: «{parte}» no es una comprobación de {self.lote} ({', '.join(self.ids)})")
            elegidos.update(conocidos[parte.lower()])
        if not elegidos:
            raise ErrorConfiguracion("--solo necesita al menos un identificador")
        return elegidos

    def incluida(self, id_: str) -> bool:
        return self.solo is None or id_ in self.solo

    def alguna_incluida(self, *ids: str) -> bool:
        return any(self.incluida(i) for i in ids)

    # -- registro -----------------------------------------------------------------------------------------------------

    def _imprimir(self, registro: Registro) -> None:
        print(f"[{registro.estado.upper()}] {registro.id} {registro.detalle}".rstrip(), flush=True)

    def precondicion(self, id_: str, funcion: Callable[[], str | None]) -> bool:
        try:
            registro = Registro(id_, PASA, funcion() or "")
        except ErrorGh as exc:
            registro = Registro(id_, FALLA, str(exc), bloqueo=not exc.sin_permiso, error=exc.sin_permiso)
        except (Bloqueo, Falla) as exc:
            registro = Registro(id_, FALLA, str(exc), bloqueo=True)
        except ErrorConfiguracion as exc:
            registro = Registro(id_, FALLA, str(exc), error=True)
        except Exception as exc:  # noqa: BLE001 — un fallo inesperado no debe impedir la limpieza ni el informe
            registro = Registro(id_, FALLA, f"error inesperado: {type(exc).__name__}: {resumir(str(exc))}", error=True)
        self.precondiciones.append(registro)
        self._imprimir(registro)
        return registro.estado == PASA

    def precondicion_no_evaluada(self, id_: str, motivo: str) -> None:
        registro = Registro(id_, FALLA, f"no evaluada: {motivo}")
        self.precondiciones.append(registro)
        self._imprimir(registro)

    def precondiciones_cumplidas(self) -> bool:
        return all(r.estado == PASA for r in self.precondiciones)

    def comprobacion(self, id_: str, funcion: Callable[[], str | None]) -> None:
        if not self.incluida(id_):
            registro = Registro(id_, OMITIDA, "excluida con --solo", 0)
        else:
            inicio = time.monotonic()
            try:
                registro = Registro(id_, PASA, funcion() or "")
            except ErrorGh as exc:
                registro = Registro(id_, FALLA, str(exc), error=exc.sin_permiso)
            except (Falla, Bloqueo) as exc:
                registro = Registro(id_, FALLA, str(exc))
            except ErrorConfiguracion as exc:
                registro = Registro(id_, FALLA, str(exc), error=True)
            except Exception as exc:  # noqa: BLE001
                registro = Registro(id_, FALLA, f"error inesperado: {type(exc).__name__}: {resumir(str(exc))}", error=True)
            registro.duracion_ms = int((time.monotonic() - inicio) * 1000)
        self.comprobaciones.append(registro)
        self._imprimir(registro)

    def manual(self, id_: str, instruccion: str) -> None:
        self.manuales.append({"id": id_, "instruccion": instruccion})
        print(f"[MANUAL] {id_} {instruccion}", flush=True)

    def al_limpiar(self, descripcion: str, funcion: Callable[[], None]) -> None:
        """Registra una limpieza. Se ejecutan en orden inverso al registro, también si algo falló."""
        self._limpiezas.append((descripcion, funcion))

    # -- cierre -------------------------------------------------------------------------------------------------------

    def codigo(self) -> int:
        registros = self.precondiciones + self.comprobaciones
        if self._error_general or any(r.error for r in registros):
            return SALIDA_ERROR
        if any(r.bloqueo for r in self.precondiciones):
            return SALIDA_BLOQUEADO
        if any(r.estado == FALLA for r in self.comprobaciones):
            return SALIDA_FALLA
        return SALIDA_PASA

    def _limpiar(self) -> None:
        if not self._limpiezas:
            return
        if self.args is not None and self.args.sin_limpieza:
            for descripcion, _ in self._limpiezas:
                avisar(f"--sin-limpieza: queda {descripcion}")
            return
        for descripcion, funcion in reversed(self._limpiezas):
            try:
                funcion()
                avisar(f"limpieza hecha: {descripcion}")
            except Exception as exc:  # noqa: BLE001
                avisar(f"limpieza incompleta ({descripcion}): {resumir(str(exc))}")
        self._limpiezas.clear()

    def _escribir_informe(self, codigo: int) -> Path:
        fin = ahora_utc()
        informe = {
            "lote": self.lote,
            "validacion": self.validacion,
            "entorno": self.args.entorno if self.args else None,
            "commit": commit_actual(),
            "inicio": iso(self.inicio),
            "fin": iso(fin),
            "resultado": RESULTADOS[codigo],
            "precondiciones": [
                {"id": r.id, "estado": r.estado, "detalle": r.detalle}
                for r in sorted(self.precondiciones, key=lambda r: r.id)
            ],
            "comprobaciones": [
                {"id": r.id, "estado": r.estado, "detalle": r.detalle, "duracion_ms": r.duracion_ms}
                for r in self.comprobaciones
            ],
            "manuales": self.manuales,
        }
        if self._error_general:
            informe["error"] = self._error_general
        ruta = self.args.informe if self.args and self.args.informe else DIR_INFORMES / f"{self.lote}-{self.sello}.json"
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_text(json.dumps(informe, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return ruta

    def correr(self, cuerpo: Callable[[Validador], None], argv: list[str] | None = None) -> int:
        """Lee los argumentos, ejecuta el cuerpo del validador, limpia y escribe el informe. Devuelve el código."""
        try:
            self.leer_argumentos(argv)
            assert self.args is not None
            if self.args.entorno not in ENTORNOS_ADMITIDOS:
                raise ErrorConfiguracion(f"{self.lote} solo admite --entorno {' o '.join(ENTORNOS_ADMITIDOS)}")
            print(f"{self.lote} · {self.validacion} · entorno {self.args.entorno} · {iso(self.inicio)}", file=sys.stderr)
            cuerpo(self)
            if not self.manuales:
                avisar("comprobaciones manuales: ninguna")
        except ErrorConfiguracion as exc:
            self._error_general = str(exc)
            print(f"[ERROR] {exc}", flush=True)
        except KeyboardInterrupt:
            self._error_general = "interrumpido por la persona"
            print("[ERROR] interrumpido por la persona", flush=True)
        except Exception as exc:  # noqa: BLE001 — la limpieza y el informe se hacen igual (código 3)
            self._error_general = f"error inesperado: {type(exc).__name__}: {resumir(str(exc))}"
            print(f"[ERROR] {self._error_general}", flush=True)
        self._limpiar()
        codigo = self.codigo()
        try:
            ruta = self._escribir_informe(codigo)
            destino = f" · informe: {ruta}"
        except OSError as exc:
            destino = f" · no se pudo escribir el informe: {exc}"
        print(f"Resultado: {RESULTADOS[codigo]} (código {codigo}){destino}", flush=True)
        return codigo
