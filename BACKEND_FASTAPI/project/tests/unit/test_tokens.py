"""JWT de sesión (`app.seguridad.tokens`, ARCHITECTURE §5.2) sin base de datos."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from pydantic import SecretStr

from app.config import Settings
from app.dominio.enumerados import RolUsuario
from app.seguridad import tokens

# Como el secreto de infra §5.4: base64 de bytes aleatorios. Se usa como texto, sin decodificar.
CLAVE = base64.b64encode(bytes(range(64))).decode()
USUARIO = uuid.UUID("7c1e0000-0000-4000-8000-000000000001")


@pytest.fixture
def ajustes() -> Settings:
    return Settings(jwt_secret=SecretStr(CLAVE), jwt_ttl_min=720)


def _b64(datos: bytes) -> str:
    return base64.urlsafe_b64encode(datos).rstrip(b"=").decode()


def _partes(token: str) -> tuple[dict, dict]:
    cabecera, carga, _ = token.split(".")
    relleno = lambda s: s + "=" * (-len(s) % 4)  # noqa: E731
    return (
        json.loads(base64.urlsafe_b64decode(relleno(cabecera))),
        json.loads(base64.urlsafe_b64decode(relleno(carga))),
    )


def _firmar_a_mano(cabecera: dict, carga: dict, clave: str) -> str:
    inicio = _b64(json.dumps(cabecera).encode()) + "." + _b64(json.dumps(carga).encode())
    firma = hmac.new(clave.encode(), inicio.encode(), hashlib.sha256).digest()
    return inicio + "." + _b64(firma)


def _emitir(ajustes: Settings, **cambios) -> tokens.TokenEmitido:
    datos = {"usuario_id": USUARIO, "rol": RolUsuario.admin, "nombre": "Alejandro Gómez", "ajustes": ajustes} | cambios
    return tokens.emitir(**datos)


def test_emite_los_claims_de_5_2(ajustes):
    ahora = datetime(2026, 10, 23, 15, 4, 5, 987654, tzinfo=UTC)
    emitido = _emitir(ajustes, ahora=ahora)
    cabecera, carga = _partes(emitido.token)
    assert cabecera == {"alg": "HS256", "typ": "JWT"}
    assert set(carga) == {"iss", "sub", "rol", "nombre", "iat", "exp", "jti"}
    assert carga["iss"] == "campus-locator-api"
    assert carga["sub"] == str(USUARIO)
    assert carga["rol"] == "admin"
    assert carga["nombre"] == "Alejandro Gómez"
    assert carga["iat"] == int(ahora.timestamp())
    assert carga["exp"] - carga["iat"] == 720 * 60
    assert uuid.UUID(carga["jti"]).version == 4 and carga["jti"] == emitido.jti
    assert emitido.expira_en == datetime.fromtimestamp(carga["exp"], UTC)
    assert emitido.expira_en.microsecond == 0


def test_la_clave_se_usa_como_texto_sin_decodificar(ajustes):
    """La firma es HMAC-SHA256 con los bytes UTF-8 de la cadena base64 (infra §5.4), no con los bytes decodificados."""
    token = _emitir(ajustes).token
    inicio, firma = token.rsplit(".", 1)
    esperada = hmac.new(CLAVE.encode("utf-8"), inicio.encode(), hashlib.sha256).digest()
    assert firma == _b64(esperada)


def test_jti_distinto_en_cada_token(ajustes):
    assert _emitir(ajustes).jti != _emitir(ajustes).jti


def test_ttl_sale_de_jwt_ttl_min(ajustes):
    _, carga = _partes(_emitir(ajustes.model_copy(update={"jwt_ttl_min": 5})).token)
    assert carga["exp"] - carga["iat"] == 300


def test_decodifica_un_token_propio(ajustes):
    claims = tokens.decodificar(_emitir(ajustes).token, ajustes)
    assert claims.sub == USUARIO
    assert claims.rol is RolUsuario.admin
    assert claims.nombre == "Alejandro Gómez"
    assert claims.exp - claims.iat == 43200


def test_vencido_es_token_expirado(ajustes):
    token = _emitir(ajustes, ahora=datetime.now(UTC) - timedelta(hours=13)).token
    with pytest.raises(tokens.TokenExpirado):
        tokens.decodificar(token, ajustes)


def test_vencido_por_un_segundo_ya_no_vale(ajustes):
    """Sin margen (`leeway = 0`)."""
    ahora = datetime.now(UTC)
    _, carga = _partes(_emitir(ajustes).token)
    carga |= {"iat": int(ahora.timestamp()) - 61, "exp": int(ahora.timestamp()) - 1}
    with pytest.raises(tokens.TokenExpirado):
        tokens.decodificar(_firmar_a_mano({"alg": "HS256", "typ": "JWT"}, carga, CLAVE), ajustes)


def _variantes_invalidas() -> dict[str, Callable[[str, dict], str]]:
    def firma_cambiada(token: str, _carga: dict) -> str:
        inicio, firma = token.rsplit(".", 1)
        medio = len(firma) // 2
        return f"{inicio}.{firma[:medio]}{'A' if firma[medio] != 'A' else 'B'}{firma[medio + 1 :]}"

    def otra_clave(_token: str, carga: dict) -> str:
        return _firmar_a_mano({"alg": "HS256", "typ": "JWT"}, carga, CLAVE + "x")

    def clave_decodificada(_token: str, carga: dict) -> str:
        inicio = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode()) + "." + _b64(json.dumps(carga).encode())
        firma = hmac.new(base64.b64decode(CLAVE), inicio.encode(), hashlib.sha256).digest()
        return inicio + "." + _b64(firma)

    def alg_none(_token: str, carga: dict) -> str:
        return _b64(b'{"alg":"none","typ":"JWT"}') + "." + _b64(json.dumps(carga).encode()) + "."

    def hs512(_token: str, carga: dict) -> str:
        return jwt.encode(carga, CLAVE, algorithm="HS512")

    def otro_emisor(_token: str, carga: dict) -> str:
        return _firmar_a_mano({"alg": "HS256"}, carga | {"iss": "otro"}, CLAVE)

    def sin_jti(_token: str, carga: dict) -> str:
        return _firmar_a_mano({"alg": "HS256"}, {k: v for k, v in carga.items() if k != "jti"}, CLAVE)

    def sin_rol(_token: str, carga: dict) -> str:
        return _firmar_a_mano({"alg": "HS256"}, {k: v for k, v in carga.items() if k != "rol"}, CLAVE)

    def sub_no_uuid(_token: str, carga: dict) -> str:
        return _firmar_a_mano({"alg": "HS256"}, carga | {"sub": "admin"}, CLAVE)

    def rol_desconocido(_token: str, carga: dict) -> str:
        return _firmar_a_mano({"alg": "HS256"}, carga | {"rol": "root"}, CLAVE)

    def nombre_vacio(_token: str, carga: dict) -> str:
        return _firmar_a_mano({"alg": "HS256"}, carga | {"nombre": ""}, CLAVE)

    return {
        "firma_cambiada": firma_cambiada,
        "otra_clave": otra_clave,
        "clave_decodificada": clave_decodificada,
        "alg_none": alg_none,
        "hs512": hs512,
        "otro_emisor": otro_emisor,
        "sin_jti": sin_jti,
        "sin_rol": sin_rol,
        "sub_no_uuid": sub_no_uuid,
        "rol_desconocido": rol_desconocido,
        "nombre_vacio": nombre_vacio,
        "basura": lambda _t, _c: "esto-no-es-un-jwt",
        "vacio": lambda _t, _c: "",
    }


@pytest.mark.parametrize("variante", sorted(_variantes_invalidas()))
def test_token_alterado_es_token_invalido(ajustes, variante):
    token = _emitir(ajustes).token
    _, carga = _partes(token)
    alterado = _variantes_invalidas()[variante](token, carga)
    with pytest.raises(tokens.TokenInvalido):
        tokens.decodificar(alterado, ajustes)


def test_firma_mala_y_vencido_es_invalido_no_expirado(ajustes):
    """El vencimiento solo cuenta con la firma válida."""
    token = _emitir(ajustes, ahora=datetime.now(UTC) - timedelta(days=2)).token
    with pytest.raises(tokens.TokenInvalido):
        tokens.decodificar(token, ajustes.model_copy(update={"jwt_secret": SecretStr(CLAVE + "x")}))


@pytest.mark.parametrize("secreto", [None, ""])
def test_sin_jwt_secret(secreto):
    ajustes = Settings(jwt_secret=SecretStr(secreto) if secreto is not None else None)
    with pytest.raises(tokens.ClaveNoConfigurada):
        _emitir(ajustes)
    with pytest.raises(tokens.ClaveNoConfigurada):
        tokens.decodificar("a.b.c", ajustes)
