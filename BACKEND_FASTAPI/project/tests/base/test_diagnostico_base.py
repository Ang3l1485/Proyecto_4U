"""BE-2.4 contra una base real: `POST /v1/admin/diagnostico/vecinos` y `db.consultas.buscar_vecinos` (ARCHITECTURE §4.8,
§5.5). Embeddings simulado con un vector que depende de los bytes (la misma foto da el mismo vector). Cubre en local lo
que miden C1–C4 de `validation-2-4.md`."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import math
import random
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from pydantic import SecretStr
from sqlalchemy import text

from app import cli
from app.clientes import embedding
from app.config import Settings
from app.db import consultas, sesion
from app.esquemas.diagnostico import VecinosRespuesta
from app.main import crear_app

pytestmark = pytest.mark.base

ADMIN = "admin.pruebas@campus.edu.co"
PASSWORD_ADMIN = "Pruebas-admin-123"
USUARIO = "validacion+user@campus.edu.co"
PASSWORD_USUARIO = "validacion-pw-usuario-de-pruebas"
CLAVE = base64.b64encode(b"clave-de-pruebas-del-diagnostico".ljust(64, b"d")).decode()
VERSION = "dinov2-vits14/pp-v1"
RUTA = "/v1/admin/diagnostico/vecinos"


def jpeg(semilla: int, ancho: int = 640, alto: int = 480) -> bytes:
    salida = io.BytesIO()
    Image.new("RGB", (ancho, alto), (semilla % 256, (semilla * 7) % 256, 90)).save(salida, format="JPEG")
    return salida.getvalue()


def vector_de(datos: bytes) -> list[float]:
    """Vector unitario de 384 componentes derivado del SHA-256 de los bytes: la misma foto, el mismo vector; fotos
    distintas, vectores casi ortogonales (similitud ~0)."""
    azar = random.Random(hashlib.sha256(datos).digest())  # noqa: S311 (no es criptografía)
    vector = [azar.gauss(0, 1) for _ in range(384)]
    norma = math.sqrt(sum(x * x for x in vector))
    return [x / norma for x in vector]


class Embeddings:
    """Doble de `app.clientes.embedding.vectorizar` (se sustituye con `monkeypatch` en el módulo)."""

    def __init__(self, version: str = VERSION) -> None:
        self.version = version
        self.llamadas: list[dict[str, Any]] = []
        self.fallo: Exception | None = None

    async def __call__(self, ajustes, imagenes, *, prioridad="baja", transporte=None, request_id=None):
        self.llamadas.append({"n": len(imagenes), "prioridad": prioridad, "request_id": request_id})
        if self.fallo is not None:
            raise self.fallo
        return embedding.Vectores(
            version_vector=self.version, dim=384, vectores=[vector_de(d) for d in imagenes], tiempos_ms={}
        )


async def _sql(ajustes: Settings, sentencia: str, parametros: dict | None = None) -> list[Any]:
    motor = sesion.crear_motor(ajustes, "pruebas")
    try:
        async with motor.begin() as conexion:
            resultado = await conexion.execute(text(sentencia), parametros or {})
            return list(resultado.all()) if resultado.returns_rows else []
    finally:
        await motor.dispose()


def sql(ajustes: Settings, sentencia: str, **parametros: Any) -> list[Any]:
    return asyncio.run(_sql(ajustes, sentencia, parametros))


def indexar(ajustes: Settings, fotos: list[bytes], *, version: str = VERSION, rumbo: float | None = 340.3) -> dict:
    """Un video con una imagen `procesada` por foto (coordenadas fuera del campus) y su vector en `embeddings`.
    Devuelve `{"video_id", "imagenes": [imagen_id…]}` en el orden de `fotos`."""
    video_id = sql(
        ajustes,
        "INSERT INTO videos (nombre, ref_cliente, creado_por) "
        "SELECT 'validacion-24', :ref, id FROM usuarios LIMIT 1 RETURNING id",
        ref=f"validacion-24-{uuid.uuid4().hex[:8]}",
    )[0][0]
    imagenes = []
    for orden, datos in enumerate(fotos, start=1):
        imagen_id = uuid.uuid4()
        sql(
            ajustes,
            "INSERT INTO imagenes (id, video_id, orden, s3_key, lat, lng, rumbo, capturada_en, bytes_declarados, "
            "estado, intentos) VALUES (:id, :v, :o, :k, :lat, -100.0, :rumbo, now(), 1000, 'procesada', 1)",
            id=imagen_id,
            v=video_id,
            o=orden,
            k=f"dataset/{video_id}/{imagen_id}.jpg",
            lat=1.0 + orden * 0.0001,
            rumbo=rumbo,
        )
        sql(
            ajustes,
            "INSERT INTO embeddings (imagen_id, version_vector, vector) VALUES (:i, :ver, CAST(:vec AS vector))",
            i=imagen_id,
            ver=version,
            vec=consultas.texto_vector(vector_de(datos)),
        )
        imagenes.append(imagen_id)
    return {"video_id": video_id, "imagenes": imagenes}


@pytest.fixture
def ajustes_diag(base_migrada: Settings) -> Settings:
    return base_migrada.model_copy(update={"jwt_secret": SecretStr(CLAVE)})


@pytest.fixture
def emb(monkeypatch) -> Embeddings:
    doble = Embeddings()
    monkeypatch.setattr(embedding, "vectorizar", doble)
    return doble


@pytest.fixture
def api(ajustes_diag, emb):
    with TestClient(crear_app(ajustes_diag)) as cliente:
        r = cliente.post("/v1/auth/login", json={"identificador": ADMIN, "password": PASSWORD_ADMIN})
        assert r.status_code == 200, r.text
        cliente.headers["Authorization"] = f"Bearer {r.json()['token']}"
        yield cliente


def consultar(api: TestClient, foto: bytes | None, k: Any = None, *, tipo: str = "image/jpeg", parte: str = "foto"):
    files = [] if foto is None else [(parte, ("consulta.jpg", foto, tipo))]
    params = {} if k is None else {"k": k}
    if not files:  # httpx no manda multipart sin partes: una parte de texto con otro nombre
        files = [("otra", (None, b"nada", "text/plain"))]
    return api.post(RUTA, params=params, files=files)


def _error(r) -> tuple[int, str, Any]:
    cuerpo = r.json()["error"]
    return r.status_code, cuerpo["codigo"], cuerpo["detalle"]


# --- C1 y C2: vecinos -------------------------------------------------------------------------------------------------
def test_la_misma_foto_sale_primera_con_su_video_y_similitud_1(api, ajustes_diag, emb):
    fotos = [jpeg(1), jpeg(2), jpeg(3)]
    datos = indexar(ajustes_diag, fotos)
    r = consultar(api, fotos[1], k=5)
    assert r.status_code == 200, r.text
    cuerpo = VecinosRespuesta.model_validate(r.json())
    assert (cuerpo.version_vector, cuerpo.k, len(cuerpo.vecinos)) == (VERSION, 5, 3)  # el índice tiene 3
    primero = cuerpo.vecinos[0]
    assert primero.imagen_id == datos["imagenes"][1] and primero.video_id == datos["video_id"]
    assert primero.similitud >= 0.999999
    assert (primero.lat, primero.lng, primero.rumbo, primero.lugar_id) == (1.0 + 2 * 0.0001, -100.0, 340.3, None)
    similitudes = [v.similitud for v in cuerpo.vecinos]
    assert similitudes == sorted(similitudes, reverse=True)
    assert cuerpo.latencia_ms >= 0
    # prioridad baja (no compite con /v1/localize) y el X-Request-Id de la petición llega a embeddings
    assert emb.llamadas == [{"n": 1, "prioridad": "baja", "request_id": r.headers["X-Request-Id"]}]


def test_k_vecinos_ordenados_sin_umbral_y_k_1_empieza_igual(api, ajustes_diag):
    indexar(ajustes_diag, [jpeg(s) for s in range(10, 18)])  # 8 vectores
    ajena = jpeg(999)  # no está en el índice: similitudes ~0, muy por debajo de LOC_SIM_MIN (0,55)
    por_k = {}
    for k in (1, 5, 50):
        r = consultar(api, ajena, k=k)
        assert r.status_code == 200, r.text
        vecinos = r.json()["vecinos"]
        por_k[k] = [v["imagen_id"] for v in vecinos]
        assert [v["similitud"] for v in vecinos] == sorted((v["similitud"] for v in vecinos), reverse=True)
        assert any(v["similitud"] < 0.55 for v in vecinos)  # no se filtra por LOC_SIM_MIN
    assert (len(por_k[1]), len(por_k[5]), len(por_k[50])) == (1, 5, 8)
    assert por_k[5][0] == por_k[1][0] and por_k[50][:5] == por_k[5]


def test_k_por_defecto_es_5(api, ajustes_diag):
    indexar(ajustes_diag, [jpeg(s) for s in range(20, 27)])
    r = consultar(api, jpeg(21))
    assert r.status_code == 200 and r.json()["k"] == 5 and len(r.json()["vecinos"]) == 5


def test_sin_dataset_la_lista_va_vacia(api):
    r = consultar(api, jpeg(1), k=3)
    assert r.status_code == 200 and r.json()["vecinos"] == []


def test_solo_cuentan_los_vectores_de_la_version_activa(api, ajustes_diag):
    foto = jpeg(5)
    otra = indexar(ajustes_diag, [foto], version="dinov2-vitb14/pp-v1")
    activa = indexar(ajustes_diag, [jpeg(6)])
    vecinos = consultar(api, foto, k=10).json()["vecinos"]
    assert [v["imagen_id"] for v in vecinos] == [str(activa["imagenes"][0])]
    assert str(otra["imagenes"][0]) not in {v["imagen_id"] for v in vecinos}


def test_rumbo_nulo_y_lugar(api, ajustes_diag):
    datos = indexar(ajustes_diag, [jpeg(7)], rumbo=None)
    lugar = sql(
        ajustes_diag,
        "INSERT INTO lugares (nombre, nombre_normalizado, categoria, lat, lng, creado_por) "
        "SELECT 'Biblioteca', 'biblioteca', 'biblioteca', 1.0, -100.0, id FROM usuarios LIMIT 1 RETURNING id",
    )[0][0]
    sql(ajustes_diag, "UPDATE imagenes SET lugar_id = :l WHERE id = :i", l=lugar, i=datos["imagenes"][0])
    [vecino] = consultar(api, jpeg(7), k=1).json()["vecinos"]
    assert vecino["rumbo"] is None and vecino["lugar_id"] == str(lugar)


# --- C3: errores ------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("k", [0, 51, "abc", -1, "5.5"])
def test_k_fuera_de_1_a_50_es_422(api, emb, k):
    status, codigo, detalle = _error(consultar(api, jpeg(1), k=k))
    assert (status, codigo) == (422, "VALIDACION")
    assert [c["campo"] for c in detalle["campos"]] == ["k"]
    assert emb.llamadas == []


def _png() -> bytes:
    salida = io.BytesIO()
    Image.new("RGB", (64, 48), (1, 2, 3)).save(salida, format="PNG")
    return salida.getvalue()


@pytest.mark.parametrize(
    ("foto", "tipo", "parte", "motivo"),
    [
        (None, "image/jpeg", "foto", "falta la parte foto"),
        (b"x", "image/jpeg", "otra", "falta la parte foto"),
        ("png", "image/png", "foto", "tipo image/png"),
        ("png", "image/jpeg", "foto", "no es un JPEG"),
        (b"", "image/jpeg", "foto", "vacía"),
        ("grande", "image/jpeg", "foto", "pesa 1600000 bytes (máximo 1572864)"),
        ("enorme", "image/jpeg", "foto", "la petición pasa de"),
    ],
)
def test_partes_que_no_valen_son_400_fotos_invalidas_con_indice_0(api, emb, foto, tipo, parte, motivo):
    base = jpeg(3)
    datos = {
        "png": _png(),
        "grande": base + b"\0" * (1_600_000 - len(base)),  # cabe en el cuerpo, no en LOC_MAX_BYTES_FOTO
        "enorme": base + b"\0" * (1_677_722 - len(base)),  # 1,6 MiB: pasa del tope del cuerpo
    }.get(foto, foto)
    r = consultar(api, datos, k=5, tipo=tipo, parte=parte)
    status, codigo, detalle = _error(r)
    assert (status, codigo, detalle["indice"]) == (400, "FOTOS_INVALIDAS", 0), r.text
    assert motivo in detalle["motivo"]
    assert emb.llamadas == []


def test_dos_partes_foto_es_400_con_indice_1(api, emb):
    files = [("foto", ("a.jpg", jpeg(1), "image/jpeg")), ("foto", ("b.jpg", jpeg(2), "image/jpeg"))]
    status, codigo, detalle = _error(api.post(RUTA, files=files))
    assert (status, codigo, detalle["indice"]) == (400, "FOTOS_INVALIDAS", 1)
    assert emb.llamadas == []


def test_cuerpo_que_no_es_multipart_es_400_fotos_invalidas(api):
    status, codigo, detalle = _error(api.post(RUTA, json={"foto": "no"}))
    assert (status, codigo, detalle["indice"]) == (400, "FOTOS_INVALIDAS", 0)


def test_multipart_roto_es_400_solicitud_invalida(api):
    cuerpo = b'--limite\r\nContent-Disposition: form-data; name="foto"\r\n\r\n\xff\xd8\xff sin cierre'
    r = api.post(RUTA, content=cuerpo, headers={"Content-Type": "multipart/form-data; boundary=limite"})
    assert _error(r)[:2] == (400, "SOLICITUD_INVALIDA")


def test_otras_partes_se_ignoran(api, ajustes_diag):
    indexar(ajustes_diag, [jpeg(8)])
    files = [("nota", (None, b"hola", "text/plain")), ("foto", ("c.jpg", jpeg(8), "image/jpeg; charset=binary"))]
    r = api.post(RUTA, files=files)
    assert r.status_code == 200 and len(r.json()["vecinos"]) == 1


def test_un_usuario_user_recibe_403_y_sin_token_401(ajustes_diag, emb, monkeypatch):
    monkeypatch.setenv(cli.VARIABLE_PASSWORD, PASSWORD_USUARIO)
    argumentos = ["crear-usuario", "--correo", USUARIO, "--nombre", "validacion-usuario", "--rol", "user"]
    assert cli.main(argumentos, ajustes=ajustes_diag) == 0
    with TestClient(crear_app(ajustes_diag)) as cliente:
        files = [("foto", ("c.jpg", jpeg(1), "image/jpeg"))]
        sin_token = cliente.post(RUTA, files=files)
        assert _error(sin_token)[:2] == (401, "NO_AUTENTICADO")
        token = cliente.post("/v1/auth/login", json={"identificador": USUARIO, "password": PASSWORD_USUARIO})
        r = cliente.post(RUTA, files=files, headers={"Authorization": f"Bearer {token.json()['token']}"})
        assert _error(r)[:2] == (403, "SIN_PERMISOS")
    assert emb.llamadas == []


def test_sin_embedding_es_503(ajustes_diag, logs_json):
    """Sin `EMBEDDING_URL` (o apagado), el cliente real lanza `EmbeddingNoDisponible`."""
    with TestClient(crear_app(ajustes_diag)) as cliente:
        token = cliente.post("/v1/auth/login", json={"identificador": ADMIN, "password": PASSWORD_ADMIN}).json()
        r = cliente.post(
            RUTA,
            files=[("foto", ("c.jpg", jpeg(1), "image/jpeg"))],
            headers={"Authorization": f"Bearer {token['token']}"},
        )
    assert _error(r)[:2] == (503, "EMBEDDING_NO_DISPONIBLE")
    [evento] = [e for e in logs_json.lineas if e["evento"] == "embedding_no_disponible"]
    assert evento["motivo"] == "sin EMBEDDING_URL" and evento["nivel"] == "WARNING"


@pytest.mark.parametrize(
    ("fallo", "esperado"),
    [
        (embedding.ImagenRechazada(0, "IMAGEN_INVALIDA"), (400, "FOTOS_INVALIDAS")),
        (embedding.EmbeddingNoDisponible("503 SATURADO"), (503, "EMBEDDING_NO_DISPONIBLE")),
        (embedding.RespuestaNoValida("200 sin version_vector"), (503, "EMBEDDING_NO_DISPONIBLE")),
    ],
)
def test_errores_de_embeddings(api, emb, fallo, esperado):
    emb.fallo = fallo
    status, codigo, detalle = _error(consultar(api, jpeg(1), k=5))
    assert (status, codigo) == esperado
    if status == 400:
        assert detalle == {"indice": 0, "motivo": "embeddings la rechazó (IMAGEN_INVALIDA)"}


def test_version_vector_distinta_es_503_y_no_busca(api, ajustes_diag, emb, logs_json):
    indexar(ajustes_diag, [jpeg(1)])
    emb.version = "dinov2-vitb14/pp-v1"
    assert _error(consultar(api, jpeg(1), k=5))[:2] == (503, "EMBEDDING_NO_DISPONIBLE")
    [evento] = [e for e in logs_json.lineas if e["evento"] == "version_vector_distinta"]
    assert (evento["esperada"], evento["recibida"], evento["proceso"]) == (VERSION, "dinov2-vitb14/pp-v1", "api")


# --- C4: nada queda guardado ------------------------------------------------------------------------------------------
def test_no_escribe_en_la_base_ni_deja_la_foto_en_los_logs(api, ajustes_diag, logs_json):
    indexar(ajustes_diag, [jpeg(1), jpeg(2)])
    conteos = "SELECT (SELECT count(*) FROM eventos_localizacion), (SELECT count(*) FROM auditoria)"
    antes = sql(ajustes_diag, conteos)
    foto = jpeg(1)
    assert consultar(api, foto, k=2).status_code == 200
    assert sql(ajustes_diag, conteos) == antes
    texto = "\n".join(str(linea) for linea in logs_json.lineas)
    assert "/9j/" not in texto and base64.b64encode(foto[:30]).decode() not in texto
    assert all(len(str(linea)) < 16_384 for linea in logs_json.lineas)
    [evento] = [e for e in logs_json.lineas if e["evento"] == "vecinos_consultados"]
    assert (evento["k"], evento["devueltos"], evento["bytes"]) == (2, 2, len(foto))
    assert evento["similitud_max"] >= 0.999999 and evento["latencia_ms"] >= evento["busqueda_ms"]


# --- La consulta (db.consultas) ---------------------------------------------------------------------------------------
async def _plan_y_ef(ajustes: Settings, k: int, ef: int) -> tuple[str, str, str]:
    motor = sesion.crear_motor(ajustes, "pruebas")
    try:
        async with sesion.transaccion(motor) as conexion:
            await consultas.fijar_ef_search(conexion, max(ef, k))
            await conexion.execute(text("SET LOCAL enable_seqscan = off"))
            vector = consultas.texto_vector(vector_de(b"consulta"))
            plan = await conexion.execute(text("EXPLAIN " + consultas.sql_vecinos(VERSION)), {"vector": vector, "k": k})
            lineas = "\n".join(fila[0] for fila in plan.all())
            dentro = (await conexion.execute(text("SHOW hnsw.ef_search"))).scalar_one()
        async with sesion.transaccion(motor) as conexion:
            fuera = (await conexion.execute(text("SELECT current_setting('hnsw.ef_search', true)"))).scalar_one()
        return lineas, dentro, fuera
    finally:
        await motor.dispose()


def test_la_consulta_usa_el_indice_parcial_y_ef_search_solo_en_la_transaccion(ajustes_diag):
    indexar(ajustes_diag, [jpeg(s) for s in range(30, 40)])
    plan, dentro, fuera = asyncio.run(_plan_y_ef(ajustes_diag, k=80, ef=64))
    assert "embeddings_hnsw_dinov2_vits14_pp_v1" in plan, plan
    assert dentro == "80"  # max(LOC_EF_SEARCH, k)
    assert fuera in ("40", None)  # el valor por defecto de pgvector (o sin cargar): SET LOCAL no sale de la transacción


def test_buscar_vecinos_con_varios_vectores_y_version_no_admitida(ajustes_diag):
    fotos = [jpeg(s) for s in range(40, 44)]
    datos = indexar(ajustes_diag, fotos)

    async def correr():
        motor = sesion.crear_motor(ajustes_diag, "pruebas")
        try:
            async with sesion.transaccion(motor) as conexion:
                return await consultas.buscar_vecinos(
                    conexion, [vector_de(fotos[0]), vector_de(fotos[3])], k=2, version_vector=VERSION, ef_search=64
                )
        finally:
            await motor.dispose()

    uno, otro = asyncio.run(correr())
    assert [v.imagen_id for v in uno][:1] == [datos["imagenes"][0]] and len(uno) == 2
    assert [v.imagen_id for v in otro][:1] == [datos["imagenes"][3]]
    assert uno[0].distancia == pytest.approx(0.0, abs=1e-6) and uno[0].similitud == pytest.approx(1.0, abs=1e-6)
    with pytest.raises(ValueError, match="formato"):
        consultas.literal_version("x'; DROP TABLE embeddings; --")
