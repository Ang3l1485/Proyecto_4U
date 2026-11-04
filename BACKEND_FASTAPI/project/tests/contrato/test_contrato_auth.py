"""Contrato de BE-1.3: lo que dice ARCHITECTURE §5.2, §5.3, §5.6 y §5.10 coincide con el código.

Se omite si el documento no está (p. ej. con `project/` copiado solo).
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

from app.config import Settings
from app.errores import MENSAJE_POR_CODIGO, cuerpo_error
from app.esquemas.auth import LoginPeticion, LoginRespuesta, UsuarioSesion
from app.seguridad import tokens

RAIZ = Path(__file__).resolve().parents[2]
DOCUMENTO = RAIZ.parent / "docs" / "ARCHITECTURE.md"


@pytest.fixture(scope="module")
def documento() -> str:
    if not DOCUMENTO.is_file():
        pytest.skip(f"no está {DOCUMENTO}")
    return DOCUMENTO.read_text(encoding="utf-8")


def _seccion(texto: str, inicio: str, fin: str) -> str:
    return texto[texto.index(inicio) : texto.index(fin, texto.index(inicio))]


def test_claims_de_5_2(documento):
    seccion = _seccion(documento, "### 5.2 ", "### 5.3 ")
    linea = next(linea for linea in seccion.splitlines() if linea.startswith("- Claims"))
    claims = re.findall(r"`([a-z]+)`", linea.split(":", 1)[1].split(".", 1)[0])
    assert claims == list(tokens.CLAIMS)
    assert f'`iss = "{tokens.EMISOR}"`' in seccion


def test_ejemplos_del_login_tienen_los_campos_de_los_esquemas(documento):
    seccion = _seccion(documento, "#### `POST /v1/auth/login`", "#### `POST /v1/localize`")
    peticion, respuesta = (json.loads(b) for b in re.findall(r"```json\n(.*?)\n```", seccion, re.S)[:2])
    assert set(peticion) == set(LoginPeticion.model_fields)
    assert set(respuesta) == set(LoginRespuesta.model_fields)
    assert set(respuesta["usuario"]) == set(UsuarioSesion.model_fields)


def test_cuerpo_fijo_de_credenciales_invalidas(documento):
    seccion = _seccion(documento, "#### `POST /v1/auth/login`", "#### `POST /v1/localize`")
    [literal] = re.findall(r'`(\{"error": \{"codigo": "CREDENCIALES_INVALIDAS".*?\}\})`', seccion)
    codigo = "CREDENCIALES_INVALIDAS"
    assert json.loads(literal) == cuerpo_error(codigo, MENSAJE_POR_CODIGO[codigo])


def test_los_codigos_con_mensaje_estan_en_5_6(documento):
    seccion = _seccion(documento, "### 5.6 ", "### 5.7 ")
    del_documento = set(re.findall(r"`([A-Z_]+)`", seccion))
    assert set(MENSAJE_POR_CODIGO) <= del_documento


def test_parametros_de_5_10(documento):
    seccion = _seccion(documento, "### 5.10 ", "**Formato de log en detalle.**")
    valores = {}
    for fila in seccion.splitlines():
        coincidencia = re.match(r"\| `([A-Z_]+)` \| ([0-9]+)", fila)
        if coincidencia:
            valores[coincidencia.group(1)] = int(coincidencia.group(2))
    ajustes = Settings()
    assert valores["JWT_TTL_MIN"] == ajustes.jwt_ttl_min
    assert valores["LOGIN_HASH_CONCURRENTES"] == ajustes.login_hash_concurrentes
    assert valores["LOGIN_HASH_COLA_MAX"] == ajustes.login_hash_cola_max
    assert valores["LOGIN_HASH_ESPERA_MAX_S"] == ajustes.login_hash_espera_max_s


def test_retry_after_del_503_de_5_3(documento):
    from app.api.v1.auth import REINTENTAR_TRAS_S

    seccion = _seccion(documento, "#### `POST /v1/auth/login`", "#### `POST /v1/localize`")
    assert f"`503 SERVICIO_OCUPADO` con `Retry-After: {REINTENTAR_TRAS_S}`" in seccion


def test_todos_los_eventos_del_codigo_estan_en_5_10(documento):
    seccion = _seccion(documento, "**Eventos de log**", "### 5.11 ")
    documentados = {
        nombre
        for fila in seccion.splitlines()
        if fila.startswith("| `")
        for nombre in re.findall(r"`([a-z0-9_]+)`", fila.split("|")[1])  # p. ej. `s3_fallido` (BE-2.1)
    }
    usados = set()
    for archivo in (RAIZ / "src" / "app").rglob("*.py"):
        for nodo in ast.walk(ast.parse(archivo.read_text(encoding="utf-8"))):  # llamadas reales, no docstrings
            if (
                isinstance(nodo, ast.Call)
                and getattr(nodo.func, "id", getattr(nodo.func, "attr", None)) == "registrar"
                and len(nodo.args) >= 2
                and isinstance(nodo.args[1], ast.Constant)
            ):
                usados.add(nodo.args[1].value)
    assert {"login", "autorizacion_rechazada", "usuario_guardado"} <= usados
    assert usados <= documentados, sorted(usados - documentados)
