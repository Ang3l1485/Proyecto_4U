"""`app.clientes.sqs` con botocore simulado (`Stubber`): recibir, borrar y devolver (BE-2.2)."""

from __future__ import annotations

import pytest
from botocore.stub import Stubber

from app.clientes import sqs
from app.clientes.sqs import ColaSqs, FalloSqs, MensajeSqs

URL = "https://sqs.us-east-1.amazonaws.com/648617469176/campus-locator-dev-ingesta"


@pytest.fixture
def cola(monkeypatch):
    for variable in ("AWS_PROFILE", "AWS_SESSION_TOKEN", "AWS_SECURITY_TOKEN"):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIAPRUEBASPRUEBAS00")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "clave-secreta-de-pruebas")
    monkeypatch.setenv("AWS_CONFIG_FILE", "/no/existe")
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", "/no/existe")
    return ColaSqs(URL, cliente=sqs.crear_cliente("us-east-1"))


def test_recibir_con_espera_larga_y_contador_de_recepciones(cola):
    esperado = {
        "QueueUrl": URL,
        "MaxNumberOfMessages": 10,
        "WaitTimeSeconds": 20,
        "MessageSystemAttributeNames": ["ApproximateReceiveCount"],
    }
    with Stubber(cola.cliente) as stub:
        mensaje = {
            "MessageId": "m1",
            "ReceiptHandle": "r1",
            "Body": "{}",
            "Attributes": {"ApproximateReceiveCount": "3"},
        }
        stub.add_response("receive_message", {"Messages": [mensaje]}, esperado)
        stub.add_response("receive_message", {}, esperado)
        assert cola.recibir(25, 30) == [MensajeSqs(id="m1", recibo="r1", cuerpo="{}", recepciones=3)]  # topes 10 y 20
        assert cola.recibir(10, 20) == []


def test_borrar_devolver_y_errores(cola):
    with Stubber(cola.cliente) as stub:
        stub.add_response("delete_message", {}, {"QueueUrl": URL, "ReceiptHandle": "r1"})
        stub.add_response(
            "change_message_visibility", {}, {"QueueUrl": URL, "ReceiptHandle": "r2", "VisibilityTimeout": 0}
        )
        stub.add_client_error("delete_message", "ReceiptHandleIsInvalid", http_status_code=400)
        stub.add_client_error("receive_message", "AccessDenied", http_status_code=403)
        cola.borrar("r1")
        cola.devolver("r2")
        with pytest.raises(FalloSqs, match=r"borrar: .*ReceiptHandleIsInvalid"):
            cola.borrar("r3")
        with pytest.raises(FalloSqs, match=r"recibir: .*AccessDenied"):
            cola.recibir(10, 20)
