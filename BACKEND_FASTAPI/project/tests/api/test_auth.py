"""Login, `requiere_admin` y endpoints reservados sin base de datos (ARCHITECTURE §4.4, §5.2, §5.3)."""

from __future__ import annotations

import base64
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import APIRouter, Depends, FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, SecretStr

from app.config import Settings
from app.dominio.enumerados import RolUsuario
from app.errores import registrar_manejadores
from app.main import crear_app
from app.seguridad import tokens
from app.seguridad.dependencias import requiere_admin

CLAVE = base64.b64encode(b"clave-de-pruebas-de-64-bytes-".ljust(64, b"x")).decode()
RUTA_ADMIN = "/v1/admin/stats/uso"


@pytest.fixture
def ajustes_jwt(ajustes: Settings) -> Settings:
    return ajustes.model_copy(update={"jwt_secret": SecretStr(CLAVE)})


@pytest.fixture
def cliente_jwt(ajustes_jwt):
    with TestClient(crear_app(ajustes_jwt)) as c:
        yield c


def _token(ajustes: Settings, **cambios) -> str:
    datos = {"usuario_id": uuid.uuid4(), "rol": RolUsuario.admin, "nombre": "Admin", "ajustes": ajustes} | cambios
    return tokens.emitir(**datos).token


def _eventos(logs_json, nombre):
    return [linea for linea in logs_json.lineas if linea["evento"] == nombre]


def _error(r) -> str:
    cuerpo = r.json()
    assert set(cuerpo) == {"error"}
    return cuerpo["error"]["codigo"]


# --- requiere_admin ---------------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "encabezados",
    [{}, {"Authorization": "Basic YWRtaW46eA=="}, {"Authorization": "Bearer"}, {"Authorization": "Bearer "}],
)
def test_sin_token_bearer_es_no_autenticado(cliente_jwt, logs_json, encabezados):
    r = cliente_jwt.get(RUTA_ADMIN, headers=encabezados)
    assert r.status_code == 401
    assert _error(r) == "NO_AUTENTICADO"
    assert r.headers["WWW-Authenticate"] == "Bearer"
    assert r.headers["X-Request-Id"]
    [evento] = _eventos(logs_json, "autorizacion_rechazada")
    assert (evento["codigo"], evento["usuario_id"]) == ("NO_AUTENTICADO", None)


def test_sin_token_no_depende_de_la_base(cliente_jwt):
    """La app de pruebas no tiene base (motor `None`): sin token igualmente es 401, no 503."""
    assert cliente_jwt.get(RUTA_ADMIN).status_code == 401


@pytest.mark.parametrize("token", ["basura", "a.b.c", "eyJhbGciOiJIUzI1NiJ9.e30.x"])
def test_token_mal_formado_es_token_invalido(cliente_jwt, token):
    r = cliente_jwt.get(RUTA_ADMIN, headers={"Authorization": f"Bearer {token}"})
    assert (r.status_code, _error(r)) == (401, "TOKEN_INVALIDO")
    assert r.headers["WWW-Authenticate"] == "Bearer"


def test_token_de_otra_clave_es_token_invalido(cliente_jwt, ajustes_jwt):
    otro = _token(ajustes_jwt.model_copy(update={"jwt_secret": SecretStr(CLAVE[::-1])}))
    r = cliente_jwt.get(RUTA_ADMIN, headers={"Authorization": f"Bearer {otro}"})
    assert (r.status_code, _error(r)) == (401, "TOKEN_INVALIDO")


def test_token_vencido_es_token_expirado(cliente_jwt, ajustes_jwt, logs_json):
    vencido = _token(ajustes_jwt, ahora=datetime.now(UTC) - timedelta(hours=13))
    r = cliente_jwt.get(RUTA_ADMIN, headers={"Authorization": f"Bearer {vencido}"})
    assert (r.status_code, _error(r)) == (401, "TOKEN_EXPIRADO")
    assert vencido not in str(logs_json.lineas)


def test_token_valido_sin_base_es_503(cliente_jwt, ajustes_jwt, logs_json):
    """Tras validar el token, `requiere_admin` consulta la base: sin motor, 503 BASE_NO_DISPONIBLE."""
    r = cliente_jwt.get(RUTA_ADMIN, headers={"Authorization": f"Bearer {_token(ajustes_jwt)}"})
    assert (r.status_code, _error(r)) == (503, "BASE_NO_DISPONIBLE")
    [evento] = _eventos(logs_json, "base_no_disponible")
    assert evento["motivo"].startswith("configuracion_incompleta")
    assert evento["nivel"] == "WARNING"


def test_sin_jwt_secret_las_rutas_protegidas_dan_500(cliente, ajustes_jwt, logs_json):
    r = cliente.get(RUTA_ADMIN, headers={"Authorization": f"Bearer {_token(ajustes_jwt)}"})
    assert (r.status_code, _error(r)) == (500, "ERROR_INTERNO")
    [evento] = _eventos(logs_json, "configuracion_incompleta")
    assert evento["faltan"] == ["JWT_SECRET"] and evento["proceso"] == "api"


def test_todas_las_rutas_de_admin_y_collect_exigen_requiere_admin(app, cliente_jwt):
    """Con el OpenAPI (FastAPI 0.143 incluye los routers de forma perezosa: `app.routes` no los lista uno a uno):
    cada operación de `/v1/admin` y `/v1/collect` declara el esquema `jwt` y, sin token, responde 401."""
    operaciones = [
        (metodo.upper(), ruta, datos)
        for ruta, metodos in app.openapi()["paths"].items()
        if ruta.startswith(("/v1/admin", "/v1/collect"))
        for metodo, datos in metodos.items()
    ]
    assert ("GET", "/v1/admin/stats/uso") in [(m, r) for m, r, _ in operaciones]
    for metodo, ruta, datos in operaciones:
        assert {"jwt": []} in datos.get("security", []), (metodo, ruta)
        concreta = ruta.replace("{", "").replace("}", "")  # p. ej. {id} → id: la ruta existe igual para el 401
        r = cliente_jwt.request(metodo, concreta)
        assert (r.status_code, _error(r)) == (401, "NO_AUTENTICADO"), (metodo, ruta)


def test_solo_las_rutas_protegidas_declaran_el_token(app):
    for ruta, metodos in app.openapi()["paths"].items():
        if not ruta.startswith(("/v1/admin", "/v1/collect")):
            assert all("security" not in datos for datos in metodos.values()), ruta


def test_la_autenticacion_va_antes_que_validar_el_cuerpo(ajustes_jwt):
    """Una ruta protegida con cuerpo: sin token responde 401 aunque el cuerpo no sea válido (no 422)."""

    class Cuerpo(BaseModel):
        n: int

    router = APIRouter(prefix="/v1/admin", dependencies=[Depends(requiere_admin)])

    @router.post("/prueba")
    async def prueba(cuerpo: Cuerpo) -> dict:
        return {}

    app = FastAPI()
    app.state.ajustes = ajustes_jwt
    app.state.motor = None
    registrar_manejadores(app)
    app.include_router(router)
    with TestClient(app) as c:
        r = c.post("/v1/admin/prueba", json={"n": "no es un número"})
    assert (r.status_code, _error(r)) == (401, "NO_AUTENTICADO")


def test_una_dependencia_del_router_y_del_endpoint_se_evalua_una_vez():
    """Lo que §4.4 promete para `usuario: UsuarioActual = Depends(requiere_admin)` en un router que ya la tiene."""
    llamadas: list[int] = []

    async def dependencia() -> int:
        llamadas.append(1)
        return len(llamadas)

    router = APIRouter(prefix="/v1/admin", dependencies=[Depends(dependencia)])

    @router.get("/prueba")
    async def prueba(valor: int = Depends(dependencia)) -> dict:
        return {"valor": valor}

    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as c:
        assert c.get("/v1/admin/prueba").json() == {"valor": 1}
    assert llamadas == [1]


# --- login sin base ---------------------------------------------------------------------------------------------
def test_login_sin_base_es_503(cliente_jwt, logs_json):
    r = cliente_jwt.post("/v1/auth/login", json={"identificador": "a@b.co", "password": "x"})
    assert (r.status_code, _error(r)) == (503, "BASE_NO_DISPONIBLE")
    assert _eventos(logs_json, "base_no_disponible")


def test_login_con_la_base_inalcanzable_es_503(ajustes_jwt, logs_json):
    ajustes = ajustes_jwt.model_copy(
        update={
            "db_host": "127.0.0.1",
            "db_port": 1,
            "db_name": "campus_locator",
            "db_user": "campus_app",
            "db_password": SecretStr("no-importa"),
            "db_sslmode": "disable",
            "db_connect_timeout_s": 2,
        }
    )
    with TestClient(crear_app(ajustes)) as c:
        r = c.post("/v1/auth/login", json={"identificador": "a@b.co", "password": "secreta-de-prueba"})
    assert (r.status_code, _error(r)) == (503, "BASE_NO_DISPONIBLE")
    texto = str(logs_json.lineas)
    assert "secreta-de-prueba" not in texto and "no-importa" not in texto


def test_login_sin_jwt_secret_es_500_antes_de_mirar_la_base(cliente, logs_json):
    r = cliente.post("/v1/auth/login", json={"identificador": "a@b.co", "password": "x"})
    assert (r.status_code, _error(r)) == (500, "ERROR_INTERNO")
    assert _eventos(logs_json, "configuracion_incompleta")
    assert not _eventos(logs_json, "base_no_disponible")


@pytest.mark.parametrize(
    ("cuerpo", "campos"),
    [
        ({}, {"identificador", "password"}),
        ({"identificador": "", "password": "x"}, {"identificador"}),
        ({"identificador": "a@b.co", "password": ""}, {"password"}),
        ({"identificador": "a@b.co", "password": "x" * 257}, {"password"}),
        ({"identificador": "a" * 321, "password": "x"}, {"identificador"}),
        ({"identificador": 5, "password": "x"}, {"identificador"}),
        # PostgreSQL rechaza el NUL en `text` (22021): sin esta regla, 500 y sin fila de auditoría.
        ({"identificador": "a\u0000@x.co", "password": "x"}, {"identificador"}),
        ({"identificador": "a@x.co", "password": "x\u0000y"}, {"password"}),
    ],
)
def test_login_con_campos_no_validos_es_422(cliente_jwt, cuerpo, campos):
    r = cliente_jwt.post("/v1/auth/login", json=cuerpo)
    assert (r.status_code, _error(r)) == (422, "VALIDACION")
    assert {c["campo"] for c in r.json()["error"]["detalle"]["campos"]} == campos


def test_login_con_un_sustituto_suelto_es_422(cliente_jwt):
    """Un `\\ud800` no se puede codificar en UTF-8 (ni hashear): Pydantic lo rechaza antes."""
    r = cliente_jwt.post(
        "/v1/auth/login",
        content=b'{"identificador": "a@b.co", "password": "x\\ud800"}',
        headers={"Content-Type": "application/json"},
    )
    assert (r.status_code, _error(r)) == (422, "VALIDACION")


def test_login_con_json_roto_es_400(cliente_jwt):
    r = cliente_jwt.post("/v1/auth/login", content=b"{no", headers={"Content-Type": "application/json"})
    assert (r.status_code, _error(r)) == (400, "SOLICITUD_INVALIDA")


# --- reservados -------------------------------------------------------------------------------------------------
@pytest.mark.parametrize(("metodo", "ruta"), [("GET", "/v1/route"), ("POST", "/v1/eventos")])
def test_reservados_publicos_responden_501_sin_token(cliente, metodo, ruta):
    r = cliente.request(metodo, ruta)
    assert (r.status_code, _error(r)) == (501, "NO_IMPLEMENTADO")


def test_localize_frame_ya_no_es_reservado(cliente):
    """Desde BE-5.1 (0.16.0) `POST /v1/localize/frame` existe: sin cuerpo, `400 FOTOS_INVALIDAS` (no `501`)."""
    r = cliente.post("/v1/localize/frame")
    assert (r.status_code, _error(r)) == (400, "FOTOS_INVALIDAS")
    assert r.json()["error"]["detalle"]["indice"] == 0
