"""BE-1.3 contra una base real: login, auditoría y `requiere_admin` (ARCHITECTURE §4.4, §5.2, §5.3, §5.7)."""

from __future__ import annotations

import asyncio
import base64
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import text

from app import cli
from app.config import Settings
from app.db import sesion
from app.dominio.enumerados import RolUsuario
from app.esquemas.auth import LoginRespuesta
from app.esquemas.errores import ErrorRespuesta
from app.main import crear_app
from app.seguridad import hash as hash_password
from app.seguridad import tokens

pytestmark = pytest.mark.base

ADMIN = "admin.pruebas@campus.edu.co"
PASSWORD_ADMIN = "Pruebas-admin-123"
USUARIO = "validacion+user@campus.edu.co"
PASSWORD_USUARIO = "validacion-pw-usuario-de-pruebas"
CLAVE = base64.b64encode(b"clave-de-pruebas-de-la-base-".ljust(64, b"y")).decode()
RUTA_ADMIN = "/v1/admin/stats/uso"


async def _consultar(ajustes: Settings, sentencia: str, parametros: dict | None = None) -> list[Any]:
    motor = sesion.crear_motor(ajustes, "pruebas")
    try:
        async with motor.begin() as conexion:
            resultado = await conexion.execute(text(sentencia), parametros or {})
            return list(resultado.all()) if resultado.returns_rows else []
    finally:
        await motor.dispose()


def consultar(ajustes: Settings, sentencia: str, **parametros: Any) -> list[Any]:
    return asyncio.run(_consultar(ajustes, sentencia, parametros))


@pytest.fixture
def ajustes_auth(base_migrada: Settings) -> Settings:
    return base_migrada.model_copy(update={"jwt_secret": SecretStr(CLAVE)})


@pytest.fixture
def cliente_auth(ajustes_auth):
    with TestClient(crear_app(ajustes_auth)) as c:
        yield c


def crear_usuario(ajustes: Settings, monkeypatch, correo: str, password: str, rol: str = "user", nombre="Persona"):
    monkeypatch.setenv(cli.VARIABLE_PASSWORD, password)
    assert cli.main(["crear-usuario", "--correo", correo, "--nombre", nombre, "--rol", rol], ajustes=ajustes) == 0


def login(cliente: TestClient, identificador: str, password: str):
    return cliente.post("/v1/auth/login", json={"identificador": identificador, "password": password})


def auditoria(ajustes: Settings) -> list[Any]:
    return consultar(
        ajustes,
        "SELECT actor_id::text, entidad, entidad_id, detalle::text FROM auditoria "
        "WHERE accion = 'usuario.login' ORDER BY id",
    )


def _claims(token: str) -> dict:
    carga = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(carga + "=" * (-len(carga) % 4)))


# --- C1 ---------------------------------------------------------------------------------------------------------
def test_login_correcto_devuelve_token_con_los_claims(cliente_auth, ajustes_auth, logs_json):
    r = login(cliente_auth, "  Admin.Pruebas@Campus.EDU.co ", PASSWORD_ADMIN)
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    LoginRespuesta.model_validate(cuerpo)
    [(usuario_id, ultimo_acceso)] = consultar(
        ajustes_auth, "SELECT id::text, ultimo_acceso_en FROM usuarios WHERE correo = :c", c=ADMIN
    )
    assert cuerpo["usuario"] == {"id": usuario_id, "nombre": "Administrador", "correo": ADMIN, "rol": "admin"}
    assert ultimo_acceso is not None
    claims = _claims(cuerpo["token"])
    assert set(claims) == set(tokens.CLAIMS)
    assert claims["sub"] == usuario_id and claims["rol"] == "admin" and claims["nombre"] == "Administrador"
    assert claims["exp"] - claims["iat"] == 43200
    assert cuerpo["expira_en"] == datetime.fromtimestamp(claims["exp"], UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert tokens.decodificar(cuerpo["token"], ajustes_auth).sub == uuid.UUID(usuario_id)
    assert auditoria(ajustes_auth) == [(usuario_id, "usuario", usuario_id, '{"resultado": "exito"}')]
    [evento] = [linea for linea in logs_json.lineas if linea["evento"] == "login"]
    assert (evento["resultado"], evento["usuario_id"], evento["nivel"]) == ("exito", usuario_id, "INFO")
    texto = str(logs_json.lineas)
    assert PASSWORD_ADMIN not in texto and cuerpo["token"] not in texto


# --- C2 y C3: misma respuesta y mismo trabajo ---------------------------------------------------------------------
def test_correo_inexistente_password_incorrecta_e_inactivo_responden_igual(
    cliente_auth, ajustes_auth, monkeypatch, logs_json
):
    crear_usuario(ajustes_auth, monkeypatch, USUARIO, PASSWORD_USUARIO)
    assert cli.main(["desactivar-usuario", "--correo", USUARIO], ajustes=ajustes_auth) == 0

    llamadas: list[str] = []
    verificar = hash_password.verificar

    def espia(hash_guardado: str, password: str) -> bool:
        llamadas.append(hash_guardado)
        return verificar(hash_guardado, password)

    monkeypatch.setattr(hash_password, "verificar", espia)
    respuestas = [
        login(cliente_auth, "validacion-noexiste@campus.edu.co", "validacion-pw-cualquiera"),
        login(cliente_auth, ADMIN, "validacion-pw-incorrecta"),
        login(cliente_auth, USUARIO, PASSWORD_USUARIO),  # contraseña correcta, usuario inactivo
    ]
    assert {r.status_code for r in respuestas} == {401}
    cuerpos = [r.json() for r in respuestas]
    assert cuerpos[0] == cuerpos[1] == cuerpos[2]
    ErrorRespuesta.model_validate(cuerpos[0])
    assert cuerpos[0]["error"]["codigo"] == "CREDENCIALES_INVALIDAS"
    assert cuerpos[0]["error"]["detalle"] is None
    assert {k.lower() for k in respuestas[0].headers} == {k.lower() for k in respuestas[1].headers}

    # Un solo argon2id por intento; con el correo desconocido, contra el hash ficticio.
    assert len(llamadas) == 3
    assert llamadas[0] == hash_password.hash_ficticio()
    assert llamadas[1] != llamadas[0] and llamadas[2] not in (llamadas[0], llamadas[1])

    [(id_admin,)] = consultar(ajustes_auth, "SELECT id::text FROM usuarios WHERE correo = :c", c=ADMIN)
    [(id_usuario,)] = consultar(ajustes_auth, "SELECT id::text FROM usuarios WHERE correo = :c", c=USUARIO)
    assert auditoria(ajustes_auth) == [
        (None, "usuario", None, '{"motivo": "correo_desconocido", "resultado": "fallo"}'),
        (None, "usuario", id_admin, '{"motivo": "password_incorrecta", "resultado": "fallo"}'),
        (None, "usuario", id_usuario, '{"motivo": "usuario_inactivo", "resultado": "fallo"}'),
    ]
    [(con_password,)] = consultar(ajustes_auth, "SELECT count(*) FROM auditoria WHERE detalle::text LIKE '%pw-%'")
    assert con_password == 0
    texto = str(logs_json.lineas)
    assert "validacion-pw-" not in texto and "validacion-noexiste" not in texto
    eventos = [linea for linea in logs_json.lineas if linea["evento"] == "login"]
    assert [(e["resultado"], e["motivo"], e["nivel"]) for e in eventos] == [
        ("fallo", "correo_desconocido", "WARNING"),
        ("fallo", "password_incorrecta", "WARNING"),
        ("fallo", "usuario_inactivo", "WARNING"),
    ]


def test_un_nul_en_el_identificador_es_422_y_no_llega_a_la_base(cliente_auth, ajustes_auth, logs_json):
    r = login(cliente_auth, "admin.pruebas\u0000@campus.edu.co", PASSWORD_ADMIN)
    assert (r.status_code, r.json()["error"]["codigo"]) == (422, "VALIDACION")
    assert r.json()["error"]["detalle"]["campos"] == [
        {"campo": "identificador", "motivo": "No puede contener el carácter NUL."}
    ]
    assert auditoria(ajustes_auth) == []
    assert not [linea for linea in logs_json.lineas if linea["evento"] in ("error_api", "error_no_controlado")]


def test_con_la_cola_del_hash_llena_responde_503_sin_tocar_la_base(cliente_auth, ajustes_auth, logs_json):
    cola = cliente_auth.app.state.cola_hash
    cola.dentro = cola.concurrentes + cola.cola_max  # simula intentos dentro
    r = login(cliente_auth, ADMIN, PASSWORD_ADMIN)
    assert (r.status_code, r.json()["error"]["codigo"]) == (503, "SERVICIO_OCUPADO")
    assert r.headers["Retry-After"] == "5"
    ErrorRespuesta.model_validate(r.json())
    assert auditoria(ajustes_auth) == []  # no se comprobó ninguna contraseña: no se anota (§5.7)
    [evento] = [linea for linea in logs_json.lineas if linea["evento"] == "login"]
    assert (evento["resultado"], evento["motivo"], evento["nivel"]) == ("rechazado", "cola_llena", "WARNING")
    cola.dentro = 0
    assert login(cliente_auth, ADMIN, PASSWORD_ADMIN).status_code == 200
    assert cola.dentro == 0


def test_el_login_tambien_da_token_a_un_user(cliente_auth, ajustes_auth, monkeypatch):
    crear_usuario(ajustes_auth, monkeypatch, USUARIO, PASSWORD_USUARIO)
    r = login(cliente_auth, USUARIO, PASSWORD_USUARIO)
    assert r.status_code == 200
    assert r.json()["usuario"]["rol"] == "user"
    assert _claims(r.json()["token"])["rol"] == "user"


# --- C3, C5: requiere_admin contra la base ------------------------------------------------------------------------
def _get_admin(cliente: TestClient, token: str):
    return cliente.get(RUTA_ADMIN, headers={"Authorization": f"Bearer {token}"})


def test_admin_pasa_user_no_y_desactivado_pierde_el_token(cliente_auth, ajustes_auth, monkeypatch, logs_json):
    crear_usuario(ajustes_auth, monkeypatch, USUARIO, PASSWORD_USUARIO)
    token_admin = login(cliente_auth, ADMIN, PASSWORD_ADMIN).json()["token"]
    token_user = login(cliente_auth, USUARIO, PASSWORD_USUARIO).json()["token"]

    r = _get_admin(cliente_auth, token_admin)
    assert (r.status_code, r.json()["error"]["codigo"]) == (501, "NO_IMPLEMENTADO")
    r = _get_admin(cliente_auth, token_user)
    assert (r.status_code, r.json()["error"]["codigo"]) == (403, "SIN_PERMISOS")
    assert "WWW-Authenticate" not in r.headers

    assert cli.main(["desactivar-usuario", "--correo", USUARIO], ajustes=ajustes_auth) == 0
    r = _get_admin(cliente_auth, token_user)  # un user desactivado: 401, no 403
    assert (r.status_code, r.json()["error"]["codigo"]) == (401, "TOKEN_INVALIDO")

    # Reactivarlo (crear-usuario) devuelve la validez a sus tokens sin vencer (§5.2, consecuencia documentada).
    crear_usuario(ajustes_auth, monkeypatch, USUARIO, PASSWORD_USUARIO)
    assert _get_admin(cliente_auth, token_user).status_code == 403

    rechazos = [linea["codigo"] for linea in logs_json.lineas if linea["evento"] == "autorizacion_rechazada"]
    assert rechazos == ["SIN_PERMISOS", "TOKEN_INVALIDO", "SIN_PERMISOS"]
    assert token_admin not in str(logs_json.lineas)


def test_admin_degradado_o_desconocido(cliente_auth, ajustes_auth, monkeypatch):
    crear_usuario(ajustes_auth, monkeypatch, "otro.admin@campus.edu.co", "Otro-admin-123", rol="admin")
    token = login(cliente_auth, "otro.admin@campus.edu.co", "Otro-admin-123").json()["token"]
    assert _get_admin(cliente_auth, token).status_code == 501
    crear_usuario(ajustes_auth, monkeypatch, "otro.admin@campus.edu.co", "Otro-admin-123", rol="user")
    r = _get_admin(cliente_auth, token)  # el token dice admin, la base ya no
    assert (r.status_code, r.json()["error"]["codigo"]) == (403, "SIN_PERMISOS")

    falso = tokens.emitir(usuario_id=uuid.uuid4(), rol=RolUsuario.admin, nombre="Nadie", ajustes=ajustes_auth).token
    r = _get_admin(cliente_auth, falso)
    assert (r.status_code, r.json()["error"]["codigo"]) == (401, "TOKEN_INVALIDO")


def test_token_vencido_de_un_admin_real(cliente_auth, ajustes_auth):
    [(usuario_id,)] = consultar(ajustes_auth, "SELECT id::text FROM usuarios WHERE correo = :c", c=ADMIN)
    vencido = tokens.emitir(
        usuario_id=uuid.UUID(usuario_id),
        rol=RolUsuario.admin,
        nombre="Administrador",
        ajustes=ajustes_auth,
        ahora=datetime.now(UTC) - timedelta(hours=13),
    ).token
    r = _get_admin(cliente_auth, vencido)
    assert (r.status_code, r.json()["error"]["codigo"]) == (401, "TOKEN_EXPIRADO")


# --- transaccion ----------------------------------------------------------------------------------------------------
def test_transaccion_convierte_una_conexion_perdida_y_deshace(ajustes_auth):
    async def probar():
        motor = sesion.crear_motor(ajustes_auth, "pruebas")
        try:
            with pytest.raises(sesion.BaseNoDisponible) as error:
                async with sesion.transaccion(motor) as conexion:
                    await conexion.execute(text("UPDATE usuarios SET nombre = 'cambiado'"))
                    await conexion.execute(text("SELECT pg_terminate_backend(pg_backend_pid())"))
            return str(error.value)
        finally:
            await motor.dispose()

    motivo = asyncio.run(probar())
    assert "AdminShutdown" in motivo or "Connection" in motivo
    assert consultar(ajustes_auth, "SELECT count(*) FROM usuarios WHERE nombre = 'cambiado'") == [(0,)]


def test_transaccion_deja_pasar_los_errores_de_sentencias(ajustes_auth):
    from sqlalchemy.exc import ProgrammingError

    async def probar():
        motor = sesion.crear_motor(ajustes_auth, "pruebas")
        try:
            async with sesion.transaccion(motor) as conexion:
                await conexion.execute(text("SELECT * FROM tabla_que_no_existe"))
        finally:
            await motor.dispose()

    with pytest.raises(ProgrammingError):
        asyncio.run(probar())
