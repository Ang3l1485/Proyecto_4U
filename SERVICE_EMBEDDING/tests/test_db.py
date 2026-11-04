"""
Tareas 3 y 4: lectura de referencias desde Aurora y conexión con token IAM
(HU-020, escenarios 1 y 6). boto3 y psycopg2 se sustituyen: no hay AWS ni base real.
"""

import numpy as np
import pytest

import app.db as db
from app import config


class CursorFalso:
    def __init__(self, filas, registro):
        self._filas = filas
        self._registro = registro

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql):
        self._registro["sql"].append(sql)

    def fetchall(self):
        return self._filas


class ConexionFalsa:
    def __init__(self, filas, registro):
        self._filas = filas
        self._registro = registro

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def cursor(self, cursor_factory=None):
        self._registro["cursor_factory"].append(cursor_factory)
        return CursorFalso(self._filas, self._registro)


@pytest.fixture
def base_falsa(monkeypatch):
    """Sustituye get_connection; devuelve (configurar_filas, registro)."""
    registro = {"sql": [], "cursor_factory": []}
    estado = {"filas": []}
    monkeypatch.setattr(db, "get_connection", lambda: ConexionFalsa(estado["filas"], registro))

    def configurar(filas):
        estado["filas"][:] = filas

    return configurar, registro


# --------------------------------------------------------------------------- #
# Tarea 3: fetch_reference_embeddings / fetch_location_names                  #
# --------------------------------------------------------------------------- #
FILAS_EMB = [
    {"id": 1, "id_point": 3, "image_name": "a.png", "embedding": "[3.0, 4.0, 0.0]"},
    {"id": 2, "id_point": 3, "image_name": "b.png", "embedding": "[0.0, 0.0, 2.5]"},
    {"id": 3, "id_point": 5, "image_name": "c.png", "embedding": "[1e-1, -2E-1, 0.2]"},
]


def test_referencias_texto_a_matriz_float32(base_falsa):
    configurar, _ = base_falsa
    configurar(FILAS_EMB)
    matriz, meta = db.fetch_reference_embeddings()
    assert matriz.shape == (3, 3)
    assert matriz.dtype == np.float32
    np.testing.assert_allclose(matriz[0], [0.6, 0.8, 0.0], atol=1e-6)


def test_referencias_quedan_con_norma_1(base_falsa):
    configurar, _ = base_falsa
    configurar(FILAS_EMB)
    matriz, _ = db.fetch_reference_embeddings()
    np.testing.assert_allclose(np.linalg.norm(matriz, axis=1), 1.0, atol=1e-6)


def test_producto_punto_igual_a_coseno(base_falsa):
    configurar, _ = base_falsa
    configurar(FILAS_EMB)
    matriz, _ = db.fetch_reference_embeddings()
    crudos = np.array([[3.0, 4.0, 0.0], [0.1, -0.2, 0.2]])
    coseno = crudos[0] @ crudos[1] / (np.linalg.norm(crudos[0]) * np.linalg.norm(crudos[1]))
    assert float(matriz[0] @ matriz[2]) == pytest.approx(coseno, abs=1e-6)


def test_vector_de_norma_cero_no_se_divide(base_falsa):
    configurar, _ = base_falsa
    configurar([{"id": 1, "id_point": 1, "image_name": "z.png", "embedding": "[0.0, 0.0, 0.0]"}])
    matriz, _ = db.fetch_reference_embeddings()
    assert np.all(np.isfinite(matriz))
    np.testing.assert_array_equal(matriz[0], [0.0, 0.0, 0.0])


def test_metadatos_en_el_mismo_orden_que_la_matriz(base_falsa):
    configurar, _ = base_falsa
    configurar(FILAS_EMB)
    _, meta = db.fetch_reference_embeddings()
    assert meta == [
        {"id": 1, "id_point": 3, "image_name": "a.png"},
        {"id": 2, "id_point": 3, "image_name": "b.png"},
        {"id": 3, "id_point": 5, "image_name": "c.png"},
    ]


def test_referencias_consulta_la_tabla_configurada(base_falsa):
    configurar, registro = base_falsa
    configurar(FILAS_EMB)
    db.fetch_reference_embeddings()
    assert registro["sql"] == [
        f"SELECT id, id_point, image_name, embedding FROM {config.EMBEDDINGS_TABLE};"
    ]
    assert registro["cursor_factory"] == [db.RealDictCursor]


def test_nombres_de_lugares(base_falsa):
    configurar, registro = base_falsa
    configurar([{"id": 1, "name": "Biblioteca"}, {"id": 2, "name": "Cafeteria"}])
    assert db.fetch_location_names() == {1: "Biblioteca", 2: "Cafeteria"}
    assert registro["sql"] == [f"SELECT id, name FROM {config.LOCATIONS_TABLE};"]


# --------------------------------------------------------------------------- #
# Tarea 4: conexión con token IAM y SSL                                       #
# --------------------------------------------------------------------------- #
class ClienteRDSFalso:
    def __init__(self, registro):
        self._registro = registro

    def generate_db_auth_token(self, **kwargs):
        self._registro["token_kwargs"] = kwargs
        return "TOKEN-IAM-FALSO"


@pytest.fixture
def aws_falso(monkeypatch):
    registro = {}

    def client(servicio, **kwargs):
        registro["servicio"] = servicio
        registro["client_kwargs"] = kwargs
        return ClienteRDSFalso(registro)

    def connect(**kwargs):
        registro["connect_kwargs"] = kwargs
        return object()

    monkeypatch.setattr(db.boto3, "client", client)
    monkeypatch.setattr(db.psycopg2, "connect", connect)
    return registro


def test_token_iam_se_pide_a_rds_con_la_configuracion(aws_falso):
    token = db._generate_iam_token()
    assert token == "TOKEN-IAM-FALSO"
    assert aws_falso["servicio"] == "rds"
    assert aws_falso["client_kwargs"] == {"region_name": config.DB_REGION}
    assert aws_falso["token_kwargs"] == {
        "DBHostname": config.DB_HOST,
        "Port": config.DB_PORT,
        "DBUsername": config.DB_USER,
        "Region": config.DB_REGION,
    }


def test_conexion_usa_el_token_como_password_y_exige_ssl(aws_falso):
    db.get_connection()
    assert aws_falso["connect_kwargs"] == {
        "host": config.DB_HOST,
        "port": config.DB_PORT,
        "user": config.DB_USER,
        "password": "TOKEN-IAM-FALSO",
        "dbname": config.DB_NAME,
        "sslmode": "require",
    }


def test_cada_conexion_pide_un_token_nuevo(aws_falso, monkeypatch):
    tokens = iter(["T1", "T2"])
    monkeypatch.setattr(db, "_generate_iam_token", lambda: next(tokens))
    db.get_connection()
    assert aws_falso["connect_kwargs"]["password"] == "T1"
    db.get_connection()
    assert aws_falso["connect_kwargs"]["password"] == "T2"
