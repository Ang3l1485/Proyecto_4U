"""BE-1.3 — Autenticación. Login y JWT, misma respuesta ante credenciales malas, usuario inactivo, tokens alterados o
vencidos, permisos de `user` y auditoría de los intentos.

Documento: BACKEND_FASTAPI/docs/validation/validation-1-3.md · criterios: BACKEND_FASTAPI/docs/PLAN.md §2.2.

    cd BACKEND_FASTAPI/project
    uv run --group ops python src/ops/validate13.py --entorno dev
    uv run --group ops python src/ops/validate13.py --entorno local   # con docker compose up en marcha

Variables: AWS_PROFILE (obligatoria en dev); VALIDACION_API_URL, VALIDACION_ADMIN_CORREO y VALIDACION_ADMIN_PASSWORD
(opcionales en dev, obligatorias en local); JWT_SECRET (solo local: la del compose). Crea o reactiva el usuario
`validacion+user@campus.edu.co` (rol `user`) y lo deja desactivado. Nunca imprime contraseñas, tokens ni la clave.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import sys
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any

import comun
from comun import ErrorConfiguracion, Falla, PrecondicionNoCumplida, exigir

LOTE = "BE-1.3"
INICIADA_POR = "validate13"
RUTA_ADMIN = "/admin/stats/uso"  # reservada: exige admin y después responde 501 (ARCHITECTURE §5.3)
EMISOR = "campus-locator-api"
CLAIMS = {"iss", "sub", "rol", "nombre", "iat", "exp", "jti"}
TTL_S = 720 * 60  # JWT_TTL_MIN (§5.10)
MARGEN_AUDITORIA_S = 5  # C6 cuenta las filas desde la hora del servidor en P2 menos este margen
SERVICIOS_COMPOSE = ("db", "api")


# --- JWT, a mano: el validador no usa la misma biblioteca que el backend ------------------------------------------
def _b64_a_bytes(texto: str) -> bytes:
    return base64.urlsafe_b64decode(texto + "=" * (-len(texto) % 4))


def _bytes_a_b64(datos: bytes) -> str:
    return base64.urlsafe_b64encode(datos).rstrip(b"=").decode()


def partes_jwt(token: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """(cabecera, carga) de un JWT; `Falla` si no tiene la forma `a.b.c` con JSON en las dos primeras partes."""
    partes = token.split(".")
    exigir(len(partes) == 3, "el token no tiene tres partes separadas por puntos")
    try:
        cabecera, carga = (json.loads(_b64_a_bytes(parte)) for parte in partes[:2])
    except ValueError:
        raise Falla("la cabecera o la carga del token no son JSON en base64url") from None
    exigir(isinstance(cabecera, dict) and isinstance(carga, dict), "la cabecera o la carga del token no son objetos")
    return cabecera, carga


def firma_valida(token: str, clave: str) -> bool:
    """HMAC-SHA256 con los bytes UTF-8 de `clave` tal cual (infra §5.4: la cadena base64, sin decodificar)."""
    firmado, _, firma = token.rpartition(".")
    esperada = hmac.new(clave.encode("utf-8"), firmado.encode("ascii"), hashlib.sha256).digest()
    try:
        return hmac.compare_digest(esperada, _b64_a_bytes(firma))
    except ValueError:
        return False


def firmar(cabecera: dict[str, Any], carga: dict[str, Any], clave: str) -> str:
    firmado = _bytes_a_b64(json.dumps(cabecera).encode()) + "." + _bytes_a_b64(json.dumps(carga).encode())
    return firmado + "." + _bytes_a_b64(hmac.new(clave.encode("utf-8"), firmado.encode(), hashlib.sha256).digest())


def alterar_firma(token: str) -> str:
    """Cambia un carácter **del medio** de la firma: el último puede codificar solo bits de relleno y no cambiarla."""
    firmado, _, firma = token.rpartition(".")
    medio = len(firma) // 2
    otro = "A" if firma[medio] != "A" else "B"
    return f"{firmado}.{firma[:medio]}{otro}{firma[medio + 1 :]}"


def _iso(segundos: int) -> str:
    return datetime.fromtimestamp(segundos, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# --- Contexto ------------------------------------------------------------------------------------------------------
class Contexto:
    def __init__(self, entorno: str) -> None:
        self.entorno = entorno
        self.sesion: Any = None
        self.api: comun.ClienteApi | None = None
        self.backend: comun.EntornoBackend | None = None
        self.admin: tuple[str, str] | None = None
        self.clave_jwt: str | None = None
        self.inicio: datetime | None = None  # hora del servidor al empezar (encabezado Date de P2)
        self._outputs: dict[str, Any] | None = None
        self._token_admin: str | None = None
        self._password_usuario: str | None = None
        self._token_usuario: str | None = None
        self._cuerpo_401: dict[str, Any] | None = None
        self.usuario_activo = False  # el usuario de prueba quedó activo y hay que desactivarlo al terminar
        self.dormir: Callable[[float], None] = time.sleep
        self.http: Any = None  # las pruebas inyectan uno falso

    def outputs(self) -> dict[str, Any]:
        if self._outputs is None:
            self._outputs = comun.outputs_terraform()
        return self._outputs

    def preparar(self, url: str) -> None:
        self.api = comun.ClienteApi(url, http=self.http, dormir=self.dormir)
        self.backend = comun.EntornoBackend(
            self.entorno, sesion=self.sesion, outputs=self.outputs, iniciada_por=INICIADA_POR, dormir=self.dormir
        )

    def token_admin(self) -> str:
        if self._token_admin is None:
            correo, password = self.admin
            self._token_admin = self.api.token(correo, password, quien="el admin")
        return self._token_admin

    def token_usuario(self) -> str:
        """Crea o reactiva el usuario de prueba (la primera vez) e inicia sesión con él."""
        if self._token_usuario is None:
            if self._password_usuario is None:
                # Antes de lanzar la tarea: si falla después de reactivar al usuario (al esperar o al leer el log), la
                # limpieza lo desactiva igual. Si no llegó a existir, la limpieza lo tolera.
                self.usuario_activo = True
                self._password_usuario = comun.crear_usuario_validacion(self.backend)
            respuesta = self.api.login(comun.USUARIO_VALIDACION, self._password_usuario)
            exigir(
                respuesta.status_code == 200,
                f"el login de {comun.USUARIO_VALIDACION} respondió {comun.describir_respuesta(respuesta)}",
            )
            rol = respuesta.json().get("usuario", {}).get("rol")
            exigir(rol == "user", f"el login de {comun.USUARIO_VALIDACION} devolvió rol {rol!r}, se esperaba 'user'")
            self._token_usuario = respuesta.json()["token"]
        return self._token_usuario

    def cuerpo_401(self) -> dict[str, Any]:
        """El cuerpo de un login con un correo inexistente (C2; si C2 no corrió, se pide aquí)."""
        if self._cuerpo_401 is None:
            respuesta = self.api.login(f"validacion-noexiste-{uuid.uuid4()}@campus.edu.co", _password_prueba())
            exigir(respuesta.status_code == 401, f"login inexistente respondió {comun.describir_respuesta(respuesta)}")
            self._cuerpo_401 = respuesta.json()
        return self._cuerpo_401

    def get_admin(self, token: str) -> Any:
        return self.api.pedir("GET", RUTA_ADMIN, token=token)

    def limpiar(self) -> str:
        try:
            if self.usuario_activo:
                detalle = comun.desactivar_usuario_validacion(self.backend, tolerar_inexistente=True)
                self.usuario_activo = False
                return detalle
            if self._password_usuario is None:
                return "nada que limpiar (no se pidió el usuario de prueba)"
            return f"nada que limpiar ({comun.USUARIO_VALIDACION} ya quedó desactivado)"
        finally:
            if self.api is not None:
                self.api.cerrar()


def _password_prueba() -> str:
    return f"validacion-pw-{uuid.uuid4()}"


def _esperar(respuesta: Any, estado: int, codigo: str, que: str) -> None:
    exigir(
        respuesta.status_code == estado and comun.codigo_error(respuesta) == codigo,
        f"{que}: {comun.describir_respuesta(respuesta)}, se esperaba {estado} {codigo}",
    )


# --- Precondiciones ------------------------------------------------------------------------------------------------
def p1_credenciales(ctx: Contexto) -> str:
    ctx.sesion = comun.sesion_aws()
    arn = comun.verificar_cuenta(ctx.sesion)
    return f"cuenta {comun.CUENTA_AWS} ({arn.rsplit('/', 1)[-1]})"


def p2_be12(ctx: Contexto) -> str:
    """BE-1.2 hecho: `/v1/health/ready` con `"db": "ok"`. Guarda la hora del servidor (encabezado Date) para C6."""
    import httpx

    if ctx.entorno == "local":
        if not os.environ.get("VALIDACION_API_URL", "").strip():
            raise ErrorConfiguracion("en local hace falta VALIDACION_API_URL (p. ej. http://localhost:8000/v1)")
        url = comun.url_api()
    else:
        url = comun.url_api(None if os.environ.get("VALIDACION_API_URL", "").strip() else ctx.outputs())
    ctx.preparar(url)
    try:
        respuesta = ctx.api.pedir("GET", "/health/ready")
    except httpx.HTTPError as exc:
        raise PrecondicionNoCumplida(f"BE-1.1: GET /v1/health/ready no respondió ({type(exc).__name__})") from None
    if respuesta.status_code != 200:
        raise PrecondicionNoCumplida(f"BE-1.2: /v1/health/ready respondió {comun.describir_respuesta(respuesta)}")
    db = respuesta.json().get("db")
    if db != "ok":
        raise PrecondicionNoCumplida(f"BE-1.2: /v1/health/ready dice db = {db!r}")
    try:
        servidor = parsedate_to_datetime(respuesta.headers.get("date", ""))
    except (TypeError, ValueError):
        servidor = None
    ctx.inicio = (servidor or datetime.now(UTC)) - timedelta(seconds=MARGEN_AUDITORIA_S)
    return f"{url} · db ok · hora de referencia {ctx.inicio:%H:%M:%S} UTC"


def p3_admin(ctx: Contexto) -> str:
    ctx.admin = comun.credenciales_admin(ctx.entorno, ctx.sesion)
    de_variables = os.environ.get("VALIDACION_ADMIN_CORREO", "").strip() and os.environ.get("VALIDACION_ADMIN_PASSWORD")
    return f"credenciales del admin desde {'VALIDACION_ADMIN_*' if de_variables else 'el secreto admin-inicial'}"


def p4_clave(ctx: Contexto) -> str:
    if ctx.entorno == "local":
        clave = os.environ.get("JWT_SECRET", "")
        if not clave:
            raise ErrorConfiguracion("en local hace falta JWT_SECRET (la del docker-compose.yml)")
        ctx.clave_jwt = clave
        return "JWT_SECRET del entorno"
    clave = str(comun.leer_secreto(ctx.sesion, comun.SECRETO_JWT).get("secret", ""))
    if not clave:
        raise ErrorConfiguracion(f"el secreto `{comun.SECRETO_JWT}` no tiene la clave `secret`")
    ctx.clave_jwt = clave
    return f"clave del secreto {comun.SECRETO_JWT}"


def p5_tareas(ctx: Contexto) -> str:
    from botocore.exceptions import ClientError

    revisiones = []
    for familia in (comun.FAMILIA_MIGRATE, comun.FAMILIA_VALIDACION):
        try:
            arn, _ = ctx.backend.imagen(familia)
        except ClientError as exc:
            if comun.es_acceso_denegado(exc):
                raise ErrorConfiguracion(f"sin permiso para describir `{familia}`") from None
            raise PrecondicionNoCumplida(f"INF-1.3: no existe la definición `{familia}`") from None
        revisiones.append(arn.rsplit("/", 1)[-1])
    red = comun.red_tareas(ctx.outputs())["awsvpcConfiguration"]
    return f"{', '.join(revisiones)}; subredes {','.join(red['subnets'])} y grupo {red['securityGroups'][0]}"


def p6_compose(ctx: Contexto) -> str:
    resultado = comun.ejecutar_proceso(["docker", "compose", "ps", "--format", "json"], cwd=comun.RAIZ_PROYECTO)
    if resultado.returncode != 0:
        raise ErrorConfiguracion("`docker compose ps` falló: ¿está Docker en marcha?")
    texto = resultado.stdout.strip()
    try:
        datos = json.loads(texto) if texto.startswith("[") else [json.loads(linea) for linea in texto.splitlines()]
    except ValueError:
        raise ErrorConfiguracion("la salida de `docker compose ps --format json` no es JSON") from None
    en_marcha = {d.get("Service") for d in datos if d.get("State") == "running"}
    faltan = [servicio for servicio in SERVICIOS_COMPOSE if servicio not in en_marcha]
    if faltan:
        raise PrecondicionNoCumplida(f"docker compose: no están en marcha {', '.join(faltan)} (`docker compose up -d`)")
    return f"docker compose: {', '.join(sorted(s for s in en_marcha if s))} en marcha"


# --- Comprobaciones ------------------------------------------------------------------------------------------------
def c1_login_admin(ctx: Contexto) -> str:
    correo, password = ctx.admin
    respuesta = ctx.api.login(correo, password)
    if respuesta.status_code == 404:
        raise Falla("POST /v1/auth/login respondió 404: ¿está desplegado BE-1.3 (backend.yml en verde)?")
    exigir(respuesta.status_code == 200, f"login del admin: {comun.describir_respuesta(respuesta)}, se esperaba 200")
    cuerpo = respuesta.json()
    exigir(set(cuerpo) == {"token", "expira_en", "usuario"}, f"campos de la respuesta: {sorted(cuerpo)}")
    usuario = cuerpo["usuario"]
    exigir(set(usuario) == {"id", "nombre", "correo", "rol"}, f"campos de `usuario`: {sorted(usuario)}")
    token = cuerpo["token"]
    cabecera, carga = partes_jwt(token)
    exigir(cabecera.get("alg") == "HS256", f"alg = {cabecera.get('alg')!r}, se esperaba HS256")
    exigir(firma_valida(token, ctx.clave_jwt), "la firma no es HMAC-SHA256 con JWT_SECRET usada como texto")
    exigir(set(carga) == CLAIMS, f"claims {sorted(carga)}, se esperaban {sorted(CLAIMS)}")
    exigir(carga["iss"] == EMISOR, f"iss = {carga['iss']!r}")
    exigir(carga["sub"] == usuario["id"], "sub ≠ usuario.id")
    exigir(carga["rol"] == "admin" == usuario["rol"], f"rol = {carga['rol']!r} / {usuario['rol']!r}")
    exigir(carga["nombre"] == usuario["nombre"], "nombre ≠ usuario.nombre")
    exigir(isinstance(carga["jti"], str) and carga["jti"], "jti vacío")
    exigir(carga["exp"] - carga["iat"] == TTL_S, f"exp − iat = {carga['exp'] - carga['iat']} s, se esperaban {TTL_S}")
    exigir(cuerpo["expira_en"] == _iso(carga["exp"]), f"expira_en = {cuerpo['expira_en']} ≠ exp ({_iso(carga['exp'])})")
    exigir(usuario["correo"] == correo.strip().lower(), "usuario.correo no es el correo normalizado")
    ctx._token_admin = token
    return f"200 · HS256 con JWT_SECRET · claims de §5.2 · sub = usuario.id · rol admin · exp − iat = {TTL_S} s"


def c2_misma_respuesta(ctx: Contexto) -> str:
    correo_admin, _ = ctx.admin
    inexistente = ctx.api.login(f"validacion-noexiste-{uuid.uuid4()}@campus.edu.co", _password_prueba())
    t_inexistente = ctx.api.ultima_duracion_ms
    incorrecta = ctx.api.login(correo_admin, _password_prueba())
    t_incorrecta = ctx.api.ultima_duracion_ms
    _esperar(inexistente, 401, "CREDENCIALES_INVALIDAS", "correo inexistente")
    _esperar(incorrecta, 401, "CREDENCIALES_INVALIDAS", "contraseña incorrecta")
    exigir(inexistente.json() == incorrecta.json(), "los dos 401 tienen cuerpos distintos")
    ctx._cuerpo_401 = inexistente.json()
    return f"401 CREDENCIALES_INVALIDAS con cuerpos idénticos · {t_inexistente} ms y {t_incorrecta} ms (informativo)"


def c5_permisos_user(ctx: Contexto) -> str:
    token_usuario = ctx.token_usuario()
    _esperar(ctx.get_admin(token_usuario), 403, "SIN_PERMISOS", "token user en /v1/admin/stats/uso")
    _esperar(ctx.get_admin(ctx.token_admin()), 501, "NO_IMPLEMENTADO", "token admin en /v1/admin/stats/uso")
    return "login user 200 (rol user) · token user → 403 SIN_PERMISOS · token admin → 501 NO_IMPLEMENTADO"


def c3_usuario_inactivo(ctx: Contexto) -> str:
    token_usuario = ctx.token_usuario()
    detalle = comun.desactivar_usuario_validacion(ctx.backend)
    ctx.usuario_activo = False
    respuesta = ctx.api.login(comun.USUARIO_VALIDACION, ctx._password_usuario)
    _esperar(respuesta, 401, "CREDENCIALES_INVALIDAS", "login del usuario desactivado")
    exigir(respuesta.json() == ctx.cuerpo_401(), "el 401 del usuario inactivo no es idéntico al de C2")
    _esperar(ctx.get_admin(token_usuario), 401, "TOKEN_INVALIDO", "token anterior del usuario desactivado")
    return f"{detalle} · login 401 idéntico al de C2 · token anterior → 401 TOKEN_INVALIDO"


def c4a_firma_alterada(ctx: Contexto) -> str:
    _esperar(ctx.get_admin(alterar_firma(ctx.token_admin())), 401, "TOKEN_INVALIDO", "firma alterada")
    return "firma alterada → 401 TOKEN_INVALIDO"


def c4b_vencido(ctx: Contexto) -> str:
    _, carga = partes_jwt(ctx.token_admin())
    ahora = int(time.time())
    vencido = firmar({"alg": "HS256", "typ": "JWT"}, carga | {"iat": ahora - 7200, "exp": ahora - 3600}, ctx.clave_jwt)
    _esperar(ctx.get_admin(vencido), 401, "TOKEN_EXPIRADO", "token vencido hace 1 h")
    return "firmado con la clave, vencido hace 1 h → 401 TOKEN_EXPIRADO"


def consulta_auditoria(desde: datetime) -> str:
    """Conteos de C6. La fecha la genera el script (no viene de fuera), por eso va como literal."""
    literal = desde.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S+00")
    return (
        "SELECT count(*) FILTER (WHERE actor_id IS NULL), count(*) FILTER (WHERE actor_id IS NOT NULL), "  # noqa: S608
        "count(*) FILTER (WHERE detalle::text LIKE '%validacion-pw-%') FROM auditoria "
        f"WHERE accion = 'usuario.login' AND creado_en >= '{literal}'"
    )


def c6_auditoria(ctx: Contexto) -> str:
    fallidos, correctos = ctx.api.logins_fallidos, ctx.api.logins_ok
    lineas = ctx.backend.sql(consulta_auditoria(ctx.inicio or datetime.now(UTC) - timedelta(minutes=1)))
    filas = [linea.strip().split("|") for linea in lineas if linea.count("|") == 2]
    exigir(filas, "psql no devolvió la fila de conteos")
    try:
        con_fallo, con_exito, con_password = (int(x) for x in filas[-1])
    except ValueError:
        raise Falla("psql devolvió conteos que no son números") from None
    exigir(con_password == 0, f"{con_password} filas de auditoría contienen una contraseña de prueba")
    exigir(con_fallo >= fallidos, f"{con_fallo} intentos fallidos en auditoría, el script hizo {fallidos}")
    exigir(con_exito >= correctos, f"{con_exito} intentos correctos en auditoría, el script hizo {correctos}")
    return (
        f"desde {ctx.inicio:%H:%M:%S} UTC: {con_fallo} fallidos (≥ {fallidos}), {con_exito} correctos "
        f"(≥ {correctos}), 0 con contraseña"
    )


def main(argv: list[str] | None = None, ctx: Contexto | None = None) -> int:
    validador = comun.Validador(lote=LOTE, validacion="validation-1-3", entornos=("dev", "local"), descripcion=__doc__)
    argumentos = validador.iniciar(argv)
    ctx = ctx or Contexto(argumentos.entorno)
    if argumentos.entorno == "dev":
        precondiciones = [
            ("P1", lambda: p1_credenciales(ctx)),
            ("P2", lambda: p2_be12(ctx)),
            ("P3", lambda: p3_admin(ctx)),
            ("P4", lambda: p4_clave(ctx)),
            ("P5", lambda: p5_tareas(ctx)),
        ]
    else:
        precondiciones = [
            ("P2", lambda: p2_be12(ctx)),
            ("P3", lambda: p3_admin(ctx)),
            ("P4", lambda: p4_clave(ctx)),
            ("P6", lambda: p6_compose(ctx)),
        ]
    return validador.ejecutar(
        precondiciones=precondiciones,
        comprobaciones=[
            ("C1", lambda: c1_login_admin(ctx)),
            ("C2", lambda: c2_misma_respuesta(ctx)),
            ("C5", lambda: c5_permisos_user(ctx)),
            ("C3", lambda: c3_usuario_inactivo(ctx)),
            ("C4a", lambda: c4a_firma_alterada(ctx)),
            ("C4b", lambda: c4b_vencido(ctx)),
            ("C6", lambda: c6_auditoria(ctx)),
        ],
        manuales=[],
        limpieza=ctx.limpiar,
    )


if __name__ == "__main__":
    sys.exit(main())
