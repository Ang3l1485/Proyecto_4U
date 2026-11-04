"""Tarea 1: la app se importa sin AWS, sin red y sin cargar el modelo."""

import importlib


def test_importa_app_sin_aws_ni_red():
    main = importlib.import_module("app.main")
    rutas = {r.path for r in main.app.routes}
    assert {"/health", "/predict"} <= rutas


def test_importar_no_carga_el_modelo_ni_la_base():
    import app.embedder as embedder
    import app.model_store as store

    importlib.import_module("app.main")
    assert embedder._model is None
    assert store.is_ready() is False


def test_la_guardia_bloquea_conexiones_externas():
    """Evidencia de que las pruebas no pueden llegar a AWS ni a Internet."""
    import socket

    import pytest

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(RuntimeError, match="Conexión externa bloqueada"):
            s.connect(("db.test.invalid", 5432))
    finally:
        s.close()


def test_las_credenciales_aws_son_ficticias():
    import os

    assert os.environ["AWS_ACCESS_KEY_ID"] == "testing"
    assert os.environ["DB_HOST"] == "db.test.invalid"
    assert "AWS_PROFILE" not in os.environ
