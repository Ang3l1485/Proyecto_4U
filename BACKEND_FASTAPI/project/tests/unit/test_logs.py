"""Logs JSON de ARCHITECTURE §5.10."""

from __future__ import annotations

import io
import json
import logging
import re
import uuid

from app.logs import crear_manejador, registrar, request_id_actual

CAMPOS_FIJOS = {"ts", "nivel", "proceso", "request_id", "evento"}


def _capturar(funcion) -> list[dict]:
    flujo = io.StringIO()
    manejador = crear_manejador("worker", flujo)
    logger = logging.getLogger(f"prueba.{uuid.uuid4()}")
    logger.addHandler(manejador)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    funcion(logger)
    return [json.loads(linea) for linea in flujo.getvalue().splitlines()]


def test_una_linea_json_con_los_campos_fijos_y_propios():
    (linea,) = _capturar(lambda log: registrar(log, "video_creado", video_id="abc", total=3))
    assert CAMPOS_FIJOS <= set(linea)
    assert linea["evento"] == "video_creado"
    assert linea["nivel"] == "INFO"
    assert linea["proceso"] == "worker"
    assert linea["request_id"] is None
    assert linea["video_id"] == "abc"
    assert linea["total"] == 3
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z", linea["ts"])


def test_toma_el_request_id_del_contexto():
    token = request_id_actual.set("rid-123")
    try:
        (linea,) = _capturar(lambda log: registrar(log, "algo"))
    finally:
        request_id_actual.reset(token)
    assert linea["request_id"] == "rid-123"


def test_los_campos_propios_no_pisan_los_fijos():
    (linea,) = _capturar(lambda log: registrar(log, "evento_real", proceso="otro", ts="x", request_id="falso"))
    assert linea["evento"] == "evento_real"
    assert linea["proceso"] == "worker"
    assert linea["ts"] != "x"
    assert linea["request_id"] is None


def test_logs_de_terceros_usan_evento_generico():
    (linea,) = _capturar(lambda log: log.warning("Started server process [%d]", 7))
    assert linea["evento"] == "log"
    assert linea["mensaje"] == "Started server process [7]"
    assert linea["nivel"] == "WARNING"


def test_excepcion_en_una_sola_linea():
    def con_error(log):
        try:
            raise ValueError("fallo")
        except ValueError:
            registrar(log, "fallo", logging.ERROR, exc_info=True)

    (linea,) = _capturar(con_error)
    assert "ValueError: fallo" in linea["excepcion"]


def test_cada_peticion_queda_registrada_con_su_request_id(cliente, logs_json):
    rid = str(uuid.uuid4())
    cliente.get("/v1/validacion-ruta-inexistente", headers={"X-Request-Id": rid})
    eventos = [linea for linea in logs_json.lineas if linea["request_id"] == rid]
    assert eventos, "no hay ninguna línea con el request_id"
    for evento in eventos:
        assert CAMPOS_FIJOS <= set(evento)
        assert evento["proceso"] == "api"
    peticion = next(e for e in eventos if e["evento"] == "peticion")
    assert peticion["estado"] == 404
    assert peticion["metodo"] == "GET"
    assert peticion["ruta"] == "/v1/validacion-ruta-inexistente"


def test_la_query_string_no_llega_a_los_logs(cliente, logs_json):
    cliente.get("/v1/health?token=no-debe-aparecer")
    assert "no-debe-aparecer" not in json.dumps(logs_json.lineas)


def test_la_traza_omite_el_detail_de_postgres(logs_json):
    import asyncpg
    from sqlalchemy import exc as sa_exc

    from app.logs import obtener_logger, registrar

    detalle = "Failing row contains (7c1e, admin@campus.edu.co, Administrador, admin,\n$argon2id$v=19$m=65536…)."
    original = asyncpg.exceptions.CheckViolationError('new row for relation "usuarios" violates check constraint')
    original.detail = detalle
    try:
        try:
            raise original
        except asyncpg.exceptions.CheckViolationError as exc:
            raise sa_exc.IntegrityError("INSERT …", None, exc) from exc
    except sa_exc.IntegrityError:
        registrar(obtener_logger("prueba"), "fallo", logging.ERROR, exc_info=True)
    [linea] = [linea for linea in logs_json.lineas if linea["evento"] == "fallo"]
    assert "argon2id" not in linea["excepcion"]
    assert "admin@campus.edu.co" not in linea["excepcion"]
    assert "violates check constraint" in linea["excepcion"]
    assert "(omitido)" in linea["excepcion"]


def test_una_linea_detail_sin_atributo_tambien_se_omite():
    from app.logs import traza_sin_datos

    texto = "Error: duplicate key\nDETAIL:  Key (correo)=(a@b.co) already exists.\nfin"
    assert traza_sin_datos(texto, None) == "Error: duplicate key\nDETAIL: (omitido)\nfin"
