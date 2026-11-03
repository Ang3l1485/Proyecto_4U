"""`app.clientes.s3` con botocore simulado (`Stubber`): firma PUT, HEAD (404 y 403 = «no está») y borrado."""

from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit

import anyio
import pytest
from botocore.stub import Stubber

from app.clientes import s3
from app.clientes.s3 import AlmacenS3, FalloS3, ObjetoS3

BUCKET = "campus-locator-dev-dataset-648617469176"
CLAVE = "dataset/9c1d0000-0000-4000-8000-000000000001/a91f0000-0000-4000-8000-000000000002.jpg"
AHORA = datetime(2026, 10, 23, 15, 4, 5, 999999, tzinfo=UTC)


@pytest.fixture
def cliente(monkeypatch):
    """Cliente real de `crear_cliente` con credenciales falsas del entorno (sin perfiles de quien prueba)."""
    for variable in ("AWS_PROFILE", "AWS_SESSION_TOKEN", "AWS_SECURITY_TOKEN"):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIAPRUEBASPRUEBAS00")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "clave-secreta-de-pruebas")
    monkeypatch.setenv("AWS_CONFIG_FILE", "/no/existe")
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", "/no/existe")
    return s3.crear_cliente("us-east-1")


@pytest.fixture
def almacen(cliente):
    return AlmacenS3(BUCKET, cliente=cliente, reloj=lambda: AHORA)


def test_url_put_firmada_con_content_type_y_ttl(almacen):
    firmada = almacen.firmar_put(CLAVE, 900)
    partes = urlsplit(firmada.url)
    consulta = parse_qs(partes.query)
    assert partes.scheme == "https"
    assert partes.netloc == f"{BUCKET}.s3.amazonaws.com"  # direccionamiento virtual (§5.4)
    assert partes.path == f"/{CLAVE}"
    assert consulta["X-Amz-Algorithm"] == ["AWS4-HMAC-SHA256"]
    assert consulta["X-Amz-Expires"] == ["900"]
    assert consulta["X-Amz-SignedHeaders"] == ["content-type;host"]  # Content-Type forma parte de la firma
    assert firmada.expira_en == datetime(2026, 10, 23, 15, 19, 5, tzinfo=UTC)  # sin fracciones, ≤ la real


def test_si_no_se_puede_firmar_es_fallo_s3_sin_url(almacen, monkeypatch):
    def sin_credenciales(*_a, **_k):
        from botocore.exceptions import NoCredentialsError

        raise NoCredentialsError()

    monkeypatch.setattr(almacen.cliente, "generate_presigned_url", sin_credenciales)
    with pytest.raises(FalloS3, match="firmar: NoCredentialsError"):
        almacen.firmar_put(CLAVE, 900)


def test_head_existe_no_existe_y_sin_list_bucket(almacen):
    with Stubber(almacen.cliente) as stub:
        esperado = {"Bucket": BUCKET, "Key": CLAVE}
        stub.add_response(
            "head_object", {"ContentLength": 345678, "ETag": '"9b2cf535f27731c974343645a3985328"'}, esperado
        )
        stub.add_client_error("head_object", "404", http_status_code=404, expected_params=esperado)
        stub.add_client_error("head_object", "403", http_status_code=403, expected_params=esperado)
        stub.add_client_error("head_object", "SlowDown", http_status_code=503, expected_params=esperado)
        assert almacen.consultar(CLAVE) == ObjetoS3(bytes=345678, etag="9b2cf535f27731c974343645a3985328")
        assert almacen.consultar(CLAVE) is None
        assert almacen.consultar(CLAVE) is None  # sin s3:ListBucket, S3 responde 403 a lo que no existe
        with pytest.raises(FalloS3, match="SlowDown") as error:
            almacen.consultar(CLAVE)
        assert "http" not in str(error.value)


def test_borrar_prefijo_lista_y_borra(almacen):
    prefijo = "dataset/9c1d0000-0000-4000-8000-000000000001/"
    claves = [f"{prefijo}{n}.jpg" for n in range(3)]
    with Stubber(almacen.cliente) as stub:
        stub.add_response(
            "list_objects_v2",
            {"Contents": [{"Key": c} for c in claves], "IsTruncated": False, "KeyCount": 3},
            {"Bucket": BUCKET, "Prefix": prefijo},
        )
        stub.add_response(
            "delete_objects",
            {"Deleted": [{"Key": c} for c in claves]},
            {"Bucket": BUCKET, "Delete": {"Objects": [{"Key": c} for c in claves], "Quiet": False}},
        )
        stub.add_response(
            "list_objects_v2", {"IsTruncated": False, "KeyCount": 0}, {"Bucket": BUCKET, "Prefix": prefijo}
        )
        assert almacen.borrar_prefijo(prefijo) == 3
        assert almacen.borrar_prefijo(prefijo) == 0


def test_borrar_con_errores_es_fallo_s3(almacen):
    with Stubber(almacen.cliente) as stub:
        stub.add_response("list_objects_v2", {"Contents": [{"Key": "dataset/x/1.jpg"}], "IsTruncated": False})
        stub.add_response("delete_objects", {"Errors": [{"Key": "dataset/x/1.jpg", "Code": "AccessDenied"}]})
        with pytest.raises(FalloS3, match="AccessDenied"):
            almacen.borrar_prefijo("dataset/x/")
        stub.add_client_error("list_objects_v2", "AccessDenied", http_status_code=403)
        with pytest.raises(FalloS3, match="AccessDenied"):
            almacen.borrar_prefijo("dataset/x/")


class _Lento:
    """Almacén que cuenta cuántos HEAD van a la vez."""

    def __init__(self) -> None:
        import threading

        self.cerrojo = threading.Lock()
        self.a_la_vez = 0
        self.maximo = 0

    def consultar(self, clave: str):
        import time

        with self.cerrojo:
            self.a_la_vez += 1
            self.maximo = max(self.maximo, self.a_la_vez)
        time.sleep(0.02)
        with self.cerrojo:
            self.a_la_vez -= 1
        if clave.endswith("falla"):
            raise FalloS3("head: ClientError: 500")
        return None if clave.endswith("no") else ObjetoS3(bytes=1, etag="e")

    def firmar_put(self, clave: str, ttl_s: int):
        return s3.UrlFirmada(url=f"https://x/{clave}", expira_en=AHORA)


def test_consultar_varios_en_paralelo_y_sin_lanzar():
    almacen = _Lento()
    claves = [f"k{n}" for n in range(20)] + ["k-no", "k-falla", "k0"]
    resultados = anyio.run(lambda: s3.consultar_varios(almacen, claves, concurrencia=4))
    assert len(resultados) == 22  # sin repetir claves
    assert resultados["k-no"] is None and isinstance(resultados["k-falla"], FalloS3)
    assert isinstance(resultados["k3"], ObjetoS3)
    assert 1 < almacen.maximo <= 4


def test_firmar_varios_y_nada_que_hacer():
    almacen = _Lento()
    assert anyio.run(lambda: s3.firmar_puts(almacen, [], 900)) == {}
    assert anyio.run(lambda: s3.consultar_varios(almacen, [])) == {}
    firmadas = anyio.run(lambda: s3.firmar_puts(almacen, ["a", "b"], 900))
    assert set(firmadas) == {"a", "b"}


def _cuerpo(datos: bytes):
    import io

    from botocore.response import StreamingBody

    return StreamingBody(io.BytesIO(datos), len(datos))


def test_descargar_existe_no_existe_403_y_demasiado_grande(almacen):
    from app.clientes.s3 import ObjetoDemasiadoGrande, ObjetoDescargado

    esperado = {"Bucket": BUCKET, "Key": CLAVE}
    with Stubber(almacen.cliente) as stub:
        stub.add_response("get_object", {"Body": _cuerpo(b"jpeg"), "ContentLength": 4, "ETag": '"abc123"'}, esperado)
        stub.add_client_error("get_object", "NoSuchKey", http_status_code=404, expected_params=esperado)
        stub.add_client_error("get_object", "AccessDenied", http_status_code=403, expected_params=esperado)
        stub.add_response("get_object", {"Body": _cuerpo(b"x" * 11), "ContentLength": 11, "ETag": '"e"'}, esperado)
        assert almacen.descargar(CLAVE, 10) == ObjetoDescargado(datos=b"jpeg", etag="abc123")
        assert almacen.descargar(CLAVE, 10) is None
        with pytest.raises(FalloS3, match="AccessDenied"):  # 403 no es «no está» al descargar
            almacen.descargar(CLAVE, 10)
        with pytest.raises(ObjetoDemasiadoGrande) as error:
            almacen.descargar(CLAVE, 10)
        assert error.value.bytes == 11


def test_escribir_miniatura_con_content_type(almacen):
    clave = "thumbs/9c1d0000-0000-4000-8000-000000000001/a91f0000-0000-4000-8000-000000000002.jpg"
    with Stubber(almacen.cliente) as stub:
        esperado = {"Bucket": BUCKET, "Key": clave, "Body": b"mini", "ContentType": "image/jpeg"}
        stub.add_response("put_object", {"ETag": '"e"'}, esperado)
        stub.add_client_error("put_object", "SlowDown", http_status_code=503)
        almacen.escribir(clave, b"mini")
        with pytest.raises(FalloS3, match=r"escribir: .*SlowDown"):
            almacen.escribir(clave, b"mini")


def test_contar_prefijo_solo_lista(almacen):
    with Stubber(almacen.cliente) as stub:
        stub.add_response(
            "list_objects_v2",
            {"Contents": [{"Key": "thumbs/x/1.jpg"}, {"Key": "thumbs/x/2.jpg"}], "IsTruncated": False},
            {"Bucket": BUCKET, "Prefix": "thumbs/x/"},
        )
        stub.add_client_error("list_objects_v2", "AccessDenied", http_status_code=403)
        assert almacen.contar_prefijo("thumbs/x/") == 2
        with pytest.raises(FalloS3, match=r"listar thumbs/x/: .*AccessDenied"):
            almacen.contar_prefijo("thumbs/x/")
