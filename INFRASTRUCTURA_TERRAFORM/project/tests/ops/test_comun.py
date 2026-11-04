"""Pruebas de comun.LectorCola (movida desde validate21.py en INF-3.1) y de su uso en validate21.py."""

from __future__ import annotations

import datetime as dt
import json

import pytest

import comun
import falsos
import validate21

SELLO = "20261028-150000"
URL = f"{falsos.URL_COLA}campus-locator-dev-ingesta"


def mensaje_21(sello: str, n: int = 1) -> str:
    return json.dumps({"Event": "s3:TestEvent", "RequestId": f"validacion-2-1-{sello}-{n}"})


@pytest.fixture
def mundo(monkeypatch):
    m = falsos.Mundo()
    m.colas[URL] = []
    monkeypatch.setattr(comun, "time", falsos.Reloj(m))
    monkeypatch.setattr(comun, "ahora_utc", m.ahora)
    return m


def test_lector_borra_propios_y_restos_y_devuelve_ajenos(mundo):
    sqs = falsos.Sqs(mundo)
    viejo = (mundo.t - dt.timedelta(hours=1)).strftime("%Y%m%d-%H%M%S")
    for cuerpo in (mensaje_21(SELLO), mensaje_21(viejo), '{"Records": []}', "no es json"):
        sqs.send_message(QueueUrl=URL, MessageBody=cuerpo)
    clasificados = {"propio": 0, "resto": 0, "ajeno": 0}

    def clasificar(cuerpo: str) -> str:
        clase = validate21.clasificar(cuerpo, SELLO)
        clasificados[clase] += 1
        return clase

    lec = comun.LectorCola(sqs, URL, "campus-locator-dev-ingesta", clasificar, ocultar_s=120)
    lec.leer(20)
    assert lec.borrados == 2 and len(lec.ajenos) == 2
    restantes = mundo.colas[URL]
    assert all(m["visible_desde"] > mundo.t for m in restantes)  # ocultos hasta devolver
    lec.devolver()
    assert [m["Body"] for m in restantes] == ['{"Records": []}', "no es json"]
    assert all(m["visible_desde"] <= mundo.t and m["recibido"] == 1 for m in restantes)
    assert clasificados == {"propio": 1, "resto": 1, "ajeno": 2}


def test_lector_con_objetivo_para_al_llegar(mundo):
    sqs = falsos.Sqs(mundo)
    for n in range(3):
        sqs.send_message(QueueUrl=URL, MessageBody=mensaje_21(SELLO, n))
    lec = comun.LectorCola(sqs, URL, "cola", lambda c: "propio")
    lec.leer(20, objetivo=1)
    assert lec.borrados == 3  # una lectura trae hasta 10: borra lo que recibió en esa lectura
    assert mundo.colas[URL] == []


def test_lector_traduce_errores_de_permiso(mundo):
    class SinPermiso(falsos.Sqs):
        def receive_message(self, **_):
            raise falsos.error("AccessDenied", "ReceiveMessage")

    lec = comun.LectorCola(SinPermiso(mundo), URL, "cola", lambda c: "propio")
    with pytest.raises(comun.ErrorConfiguracion):
        lec.leer(20)


# ---------------------------------------------------------------------------------------------------------------------
# error_aws: código y Error.Message (desde 0.14.1)
# ---------------------------------------------------------------------------------------------------------------------


def test_error_aws_lleva_el_mensaje():
    exc = falsos.error("InvalidParameterException", "RunTask", "Invalid namespace for group.")
    traducido = comun.error_aws(exc, "lanzar la tarea (ecs:RunTask)")
    assert isinstance(traducido, comun.Falla)
    assert str(traducido) == "lanzar la tarea (ecs:RunTask): InvalidParameterException: Invalid namespace for group."


def test_error_aws_sin_mensaje_o_igual_al_codigo():
    assert str(comun.error_aws(falsos.error("Throttling"), "x")) == "x: Throttling"
    sin_mensaje = falsos.error("Throttling")
    sin_mensaje.response["Error"].pop("Message")
    assert str(comun.error_aws(sin_mensaje, "x")) == "x: Throttling"


def test_error_aws_de_permisos_es_configuracion_con_mensaje():
    exc = falsos.error("AccessDeniedException", "PutRule", "User: arn:aws:iam::1:user/a is not authorized")
    traducido = comun.error_aws(exc, "crear (events:PutRule)")
    assert isinstance(traducido, comun.ErrorConfiguracion)
    assert "(AccessDeniedException: User: arn:aws:iam::1:user/a is not authorized)" in str(traducido)


def test_error_aws_no_muestra_llaves_ni_firmas():
    exc = falsos.error(
        "SignatureDoesNotMatch",
        "GetObject",
        "llave AKIAABCDEFGHIJKLMNOP en https://b.s3.amazonaws.com/k?X-Amz-Credential=AKIAX%2F1&X-Amz-Signature=abc123 x",
    )
    texto = str(comun.error_aws(exc, "leer"))
    assert "AKIAABCDEFGHIJKLMNOP" not in texto and "abc123" not in texto and "X-Amz-Credential=AKIAX" not in texto
    assert "SignatureDoesNotMatch" in texto


def test_errores_aws_traduce_dentro_del_with():
    with pytest.raises(comun.Falla, match="InvalidParameterException: Invalid namespace for group."):
        with comun.errores_aws("lanzar"):
            raise falsos.error("InvalidParameterException", "RunTask", "Invalid namespace for group.")


def test_validate21_usa_el_lector_comun(mundo):
    sqs = falsos.Sqs(mundo)
    sqs.send_message(QueueUrl=URL, MessageBody=mensaje_21(SELLO))
    sqs.send_message(QueueUrl=URL, MessageBody="ajeno")

    class Op:
        def cliente(self, nombre):
            assert nombre == "sqs"
            return sqs

    ctx = validate21.Contexto(sello=SELLO, op=Op(), urls={"ingesta": URL, "purga": URL})
    lec = validate21.lector(ctx, "ingesta")
    assert isinstance(lec, comun.LectorCola) and lec.ocultar_s == validate21.OCULTAR_S
    lec.leer(20)
    lec.devolver()
    assert mundo.borrados == [mensaje_21(SELLO)]
    assert [m["Body"] for m in mundo.colas[URL]] == ["ajeno"]
