"""BE-3.2 contra una base real: `POST /v1/localize` (ARCHITECTURE §4.10, §5.3). Embeddings simulado con vectores
elegidos a mano (`EmbeddingsFijos`): cada foto de consulta tiene su eje (`eje(i)`) y cada imagen del dataset se indexa
con la similitud que se quiera respecto a una foto (`con_similitud`), en coordenadas propias (`indexar_en`), así se
prueban el agrupamiento, el contexto y `eventos_localizacion` sin `embedding` ni dataset real."""

from __future__ import annotations

import asyncio
import base64
import io
import json
import math
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import text

from app.clientes import embedding
from app.config import Settings
from app.db import consultas, sesion
from app.dominio import geo
from app.dominio.lugares import normalizar_nombre
from app.esquemas.localizacion import LocalizacionRespuesta
from app.main import crear_app

pytestmark = pytest.mark.base

VERSION = "dinov2-vits14/pp-v1"
RUTA = "/v1/localize"
DIM = 384
LAT0, LNG0 = 6.2001, -75.5786  # coordenadas de prueba (las pruebas usan una base efímera)
M_POR_GRADO = geo.RADIO_TIERRA_M * math.pi / 180


def norte(metros: float, lat: float = LAT0) -> float:
    return lat + metros / M_POR_GRADO


def este(metros: float, lat: float = LAT0, lng: float = LNG0) -> float:
    return lng + metros / (M_POR_GRADO * math.cos(math.radians(lat)))


def jpeg(semilla: int, ancho: int = 320, alto: int = 240) -> bytes:
    salida = io.BytesIO()
    Image.new("RGB", (ancho, alto), (semilla % 256, (semilla * 7) % 256, 33)).save(salida, format="JPEG")
    return salida.getvalue()


def eje(i: int) -> list[float]:
    vector = [0.0] * DIM
    vector[i] = 1.0
    return vector


_libres = iter(range(100, DIM))


def con_similitud(i: int, similitud: float) -> list[float]:
    """Vector unitario con similitud coseno `similitud` con `eje(i)` y 0 con los demás ejes de consulta (0–9)."""
    otro = eje(next(_libres))
    resto = math.sqrt(max(0.0, 1 - similitud**2))
    return [similitud * a + resto * b for a, b in zip(eje(i), otro, strict=True)]


class EmbeddingsFijos:
    """Doble de `app.clientes.embedding.vectorizar`: la foto `fotos[i]` (por sus bytes) da `eje(i)`; una foto que no
    está en `vectores` da un eje sin dataset (el 50 + un contador)."""

    def __init__(self) -> None:
        self.vectores: dict[bytes, list[float]] = {}
        self.version = VERSION
        self.llamadas: list[dict[str, Any]] = []
        self.fallo: Exception | None = None
        self._sueltos = 50

    def registrar(self, fotos: list[bytes]) -> None:
        for i, foto in enumerate(fotos):
            self.vectores[foto] = eje(i)

    def _vector(self, foto: bytes) -> list[float]:
        if foto not in self.vectores:
            self.vectores[foto] = eje(self._sueltos)
            self._sueltos += 1
        return self.vectores[foto]

    async def __call__(self, ajustes, imagenes, *, prioridad="baja", transporte=None, request_id=None):
        self.llamadas.append({"n": len(imagenes), "prioridad": prioridad, "request_id": request_id})
        if self.fallo is not None:
            raise self.fallo
        return embedding.Vectores(
            version_vector=self.version, dim=DIM, vectores=[self._vector(f) for f in imagenes], tiempos_ms={}
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


def indexar_en(ajustes: Settings, filas: list[tuple[list[float], float, float, float | None]]) -> list[uuid.UUID]:
    """Un video `validacion-32` con una imagen `procesada` y su vector por fila `(vector, lat, lng, rumbo)`."""
    video_id = sql(
        ajustes,
        "INSERT INTO videos (nombre, ref_cliente, creado_por) "
        "SELECT 'validacion-32', :ref, id FROM usuarios LIMIT 1 RETURNING id",
        ref=f"validacion-32-{uuid.uuid4().hex[:8]}",
    )[0][0]
    ids = []
    for orden, (vector, lat, lng, rumbo) in enumerate(filas, start=1):
        imagen_id = uuid.uuid4()
        sql(
            ajustes,
            "INSERT INTO imagenes (id, video_id, orden, s3_key, lat, lng, rumbo, capturada_en, bytes_declarados, "
            "estado, intentos) VALUES (:id, :v, :o, :k, :lat, :lng, :rumbo, now(), 1000, 'procesada', 1)",
            id=imagen_id,
            v=video_id,
            o=orden,
            k=f"dataset/{video_id}/{imagen_id}.jpg",
            lat=lat,
            lng=lng,
            rumbo=rumbo,
        )
        sql(
            ajustes,
            "INSERT INTO embeddings (imagen_id, version_vector, vector) VALUES (:i, :ver, CAST(:vec AS vector))",
            i=imagen_id,
            ver=VERSION,
            vec=consultas.texto_vector(vector),
        )
        ids.append(imagen_id)
    return ids


def crear_lugar(ajustes: Settings, nombre: str, lat: float, lng: float) -> uuid.UUID:
    return sql(
        ajustes,
        "INSERT INTO lugares (nombre, nombre_normalizado, categoria, lat, lng, creado_por) "
        "SELECT :n, :nn, 'bloque', :lat, :lng, id FROM usuarios LIMIT 1 RETURNING id",
        n=nombre,
        nn=normalizar_nombre(nombre),
        lat=lat,
        lng=lng,
    )[0][0]


def eventos(ajustes: Settings) -> list[Any]:
    return sql(
        ajustes,
        "SELECT origen, resultado, nivel, confianza, lat, lng, fotos_usadas, fotos_con_coincidencia, latencia_ms, "
        "version_vector, app_version FROM eventos_localizacion ORDER BY id",
    )


@pytest.fixture
def emb(monkeypatch) -> EmbeddingsFijos:
    doble = EmbeddingsFijos()
    monkeypatch.setattr(embedding, "vectorizar", doble)
    return doble


@pytest.fixture
def api(base_migrada, emb):
    with TestClient(crear_app(base_migrada)) as cliente:
        yield cliente


def localizar(
    api: TestClient,
    fotos: list[bytes],
    rumbos: list[float | None] | None = None,
    *,
    metadatos: Any = "auto",
    tipo: str = "image/jpeg",
    extra: list | None = None,
    **kwargs: Any,
):
    files: list = [("fotos", (f"{i}.jpg", f, tipo)) for i, f in enumerate(fotos)]
    if metadatos == "auto":
        metadatos = {"rumbos": rumbos if rumbos is not None else [None] * len(fotos), "origen": "escaneo"}
    if metadatos is not None:
        cuerpo = metadatos if isinstance(metadatos, bytes) else json.dumps(metadatos).encode()
        files.append(("metadatos", (None, cuerpo, "application/json")))
    files += extra or []
    if not files:
        files = [("otra", (None, b"nada", "text/plain"))]
    return api.post(RUTA, files=files, **kwargs)


def _error(r) -> tuple[int, str, Any]:
    cuerpo = r.json()["error"]
    return r.status_code, cuerpo["codigo"], cuerpo["detalle"]


# --- ok, contexto y evento -------------------------------------------------------------------------------------------
def _escena(ajustes: Settings) -> dict[str, Any]:
    """Grupo A alrededor de (LAT0, LNG0) con las tres fotos y grupo B a 200 m al norte con la foto 0."""
    filas = [
        (con_similitud(0, 0.92), norte(0), LNG0, 84.0),
        (con_similitud(1, 0.85), norte(4), LNG0, 176.0),
        (con_similitud(2, 0.80), norte(-3), este(2), None),
        (con_similitud(0, 0.60), norte(200), LNG0, 10.0),
        (con_similitud(1, 0.40), norte(-500), LNG0, 0.0),  # por debajo de LOC_SIM_MIN: no cuenta
    ]
    ids = indexar_en(ajustes, filas)
    lugares = {
        "biblioteca": crear_lugar(ajustes, "Biblioteca Central", norte(12), LNG0),
        "bloque": crear_lugar(ajustes, "Bloque de los Trillizos", LAT0, este(35)),
        "lejano": crear_lugar(ajustes, "Coliseo", norte(500), LNG0),
    }
    return {"ids": ids, "lugares": lugares}


def test_ok_con_posicion_confianza_correccion_y_contexto(api, base_migrada, emb):
    escena = _escena(base_migrada)
    fotos = [jpeg(1), jpeg(2), jpeg(3)]
    emb.registrar(fotos)
    r = localizar(api, fotos, [90.0, 180.0, None])
    assert r.status_code == 200, r.text
    cuerpo = LocalizacionRespuesta.model_validate(r.json())
    assert (cuerpo.resultado, cuerpo.nivel, cuerpo.version_vector) == ("ok", "alta", VERSION)
    # s = 1, c = 3/3, m = (2,57 − 0,60) / 2,57 → 0,5 + 0,3 + 0,1533 = 0,9533 → 0,95 (truncada)
    assert cuerpo.confianza == 0.95
    assert (cuerpo.fotos_usadas, cuerpo.fotos_con_coincidencia) == (3, 3)
    assert geo.distancia_m(cuerpo.posicion.lat, cuerpo.posicion.lng, LAT0, LNG0) < 3
    assert cuerpo.posicion.radio_m >= 5.0 and cuerpo.posicion.lat == round(cuerpo.posicion.lat, 6)
    assert cuerpo.correccion_rumbo_grados == -5.0  # (84 − 90) y (176 − 180)
    assert cuerpo.lugar_cercano.id == escena["lugares"]["biblioteca"] and 8 < cuerpo.lugar_cercano.distancia_m < 16
    [referencia] = cuerpo.referencias  # el Coliseo queda a ~500 m
    assert referencia.id == escena["lugares"]["bloque"] and referencia.nombre == "Bloque de los Trillizos"
    assert 30 < referencia.distancia_m < 40 and 80 < referencia.rumbo_grados < 100
    assert referencia.distancia_m == round(referencia.distancia_m, 1)
    # una sola llamada a embeddings, con prioridad alta y el X-Request-Id de la petición
    assert emb.llamadas == [{"n": 3, "prioridad": "alta", "request_id": r.headers["X-Request-Id"]}]
    [fila] = eventos(base_migrada)
    assert fila.origen == "escaneo" and fila.resultado == "ok" and fila.nivel == "alta"
    assert fila.confianza == pytest.approx(0.95, abs=1e-6)
    assert (fila.lat, fila.lng) == (round(cuerpo.posicion.lat, 5), round(cuerpo.posicion.lng, 5))
    assert (fila.fotos_usadas, fila.fotos_con_coincidencia, fila.latencia_ms) == (3, 3, cuerpo.latencia_ms)
    assert (fila.version_vector, fila.app_version) == (VERSION, None)


def test_sin_dataset_es_sin_coincidencias_y_deja_su_evento(api, base_migrada, emb):
    r = localizar(api, [jpeg(1), jpeg(2)], [10.0, None], metadatos={"rumbos": [10.0, None], "origen": "escaneo",
                                                                     "app_version": " 0.9.0 "})  # fmt: skip
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["resultado"] == "sin_coincidencias" and cuerpo["confianza"] == 0
    for campo in ("posicion", "nivel", "correccion_rumbo_grados", "lugar_cercano"):
        assert cuerpo[campo] is None, campo
    assert cuerpo["referencias"] == [] and (cuerpo["fotos_usadas"], cuerpo["fotos_con_coincidencia"]) == (2, 0)
    [fila] = eventos(base_migrada)
    assert (fila.resultado, fila.nivel, fila.lat, fila.lng) == ("sin_coincidencias", None, None, None)
    assert fila.confianza == 0
    assert fila.app_version == "0.9.0"


def test_una_foto_sin_relacion_con_el_dataset_es_sin_coincidencias(api, base_migrada, emb):
    indexar_en(base_migrada, [(con_similitud(0, 0.95), LAT0, LNG0, None)])
    r = localizar(api, [jpeg(77)])  # no registrada: su eje no se parece a nada del índice
    assert r.status_code == 200 and r.json()["resultado"] == "sin_coincidencias"


def test_un_grupo_lejano_con_una_sola_foto_pierde_contra_el_que_reune_varias(api, base_migrada, emb):
    """La foto 0 coincide mejor con B (0,95) pero las fotos 1 y 2 coinciden con A: gana A (0,70 + 0,70 + 0,65)."""
    indexar_en(
        base_migrada,
        [
            (con_similitud(0, 0.95), norte(300), LNG0, None),
            (con_similitud(1, 0.70), norte(0), LNG0, None),
            (con_similitud(2, 0.70), norte(5), LNG0, None),
            (con_similitud(0, 0.65), norte(-5), LNG0, None),
        ],
    )
    fotos = [jpeg(11), jpeg(12), jpeg(13)]
    emb.registrar(fotos)
    cuerpo = localizar(api, fotos).json()
    assert cuerpo["resultado"] == "ok" and cuerpo["fotos_con_coincidencia"] == 3
    assert geo.distancia_m(cuerpo["posicion"]["lat"], cuerpo["posicion"]["lng"], norte(0), LNG0) < 6
    assert cuerpo["correccion_rumbo_grados"] is None and cuerpo["lugar_cercano"] is None


def test_es_publico_e_ignora_un_token_no_valido(api, base_migrada, emb):
    r = localizar(api, [jpeg(1)], headers={"Authorization": "Bearer no-es-un-token"})
    assert r.status_code == 200 and r.json()["resultado"] == "sin_coincidencias"


def test_otras_partes_se_ignoran_y_el_orden_de_las_fotos_es_el_de_llegada(api, base_migrada, emb):
    indexar_en(base_migrada, [(con_similitud(1, 0.9), LAT0, LNG0, 100.0)])
    fotos = [jpeg(21), jpeg(22)]
    emb.registrar(fotos)  # la segunda foto (índice 1) es la que coincide
    files = [
        ("fotos", ("a.jpg", fotos[0], "image/jpeg")),
        ("nota", (None, b"hola", "text/plain")),
        ("metadatos", (None, json.dumps({"rumbos": [None, 90.0], "origen": "escaneo", "otro": 1}).encode(), None)),
        ("fotos", ("b.jpg", fotos[1], "image/jpeg; charset=binary")),
    ]
    r = api.post(RUTA, files=files)
    assert r.status_code == 200, r.text
    assert r.json()["fotos_con_coincidencia"] == 1 and r.json()["fotos_usadas"] == 2


# --- 400 FOTOS_INVALIDAS, 400 SOLICITUD_INVALIDA y 422 VALIDACION ---------------------------------------------------
def _png() -> bytes:
    salida = io.BytesIO()
    Image.new("RGB", (64, 48), (1, 2, 3)).save(salida, format="PNG")
    return salida.getvalue()


@pytest.mark.parametrize(
    ("caso", "indice", "motivo"),
    [
        ("sin_fotos", 0, "falta la parte fotos"),
        ("seis_fotos", 5, "como mucho 5 fotos"),
        ("png_en_la_tercera", 2, "tipo image/png"),
        ("vacia_en_la_segunda", 1, "vacía"),
        ("grande_en_la_segunda", 1, "pesa 1600000 bytes (máximo 1572864)"),
        ("no_jpeg", 0, "no es un JPEG"),
        ("cuerpo_enorme", 0, "la petición pasa de 7929856 bytes"),
        ("rumbos_de_mas", 2, "rumbos tiene 3 elementos y hay 2 fotos"),
        ("rumbos_de_menos", 1, "rumbos tiene 1 elementos y hay 3 fotos"),
    ],
)
def test_fotos_invalidas_con_el_indice_de_la_foto(api, emb, caso, indice, motivo):
    base = jpeg(3)
    grande = base + b"\0" * (1_600_000 - len(base))
    if caso == "sin_fotos":
        r = localizar(api, [], metadatos={"rumbos": [], "origen": "escaneo"})
    elif caso == "seis_fotos":
        r = localizar(api, [jpeg(i) for i in range(6)])
    elif caso == "png_en_la_tercera":
        files = [("fotos", (f"{i}.jpg", jpeg(i), "image/jpeg")) for i in range(2)]
        files += [("fotos", ("2.png", _png(), "image/png"))]
        files += [("metadatos", (None, b'{"rumbos": [null, null, null], "origen": "escaneo"}', "application/json"))]
        r = api.post(RUTA, files=files)
    elif caso == "vacia_en_la_segunda":
        r = localizar(api, [base, b""])
    elif caso == "grande_en_la_segunda":
        r = localizar(api, [base, grande])
    elif caso == "no_jpeg":
        r = localizar(api, [_png()])
    elif caso == "cuerpo_enorme":
        r = localizar(api, [grande] * 5)  # 8 000 000 bytes > 5 × 1 572 864 + 65 536
    elif caso == "rumbos_de_mas":
        r = localizar(api, [jpeg(1), jpeg(2)], [1.0, 2.0, 3.0])
    else:
        r = localizar(api, [jpeg(1), jpeg(2), jpeg(3)], [1.0])
    status, codigo, detalle = _error(r)
    assert (status, codigo, detalle["indice"]) == (400, "FOTOS_INVALIDAS", indice), r.text
    assert motivo in detalle["motivo"]
    assert emb.llamadas == []


def test_cuerpo_que_no_es_multipart_y_multipart_roto(api, emb):
    status, codigo, detalle = _error(api.post(RUTA, json={"fotos": []}))
    assert (status, codigo, detalle["indice"]) == (400, "FOTOS_INVALIDAS", 0)
    cuerpo = b'--limite\r\nContent-Disposition: form-data; name="fotos"\r\n\r\n\xff\xd8\xff sin cierre'
    r = api.post(RUTA, content=cuerpo, headers={"Content-Type": "multipart/form-data; boundary=limite"})
    assert _error(r)[:2] == (400, "SOLICITUD_INVALIDA")
    assert emb.llamadas == []


@pytest.mark.parametrize(
    ("metadatos", "campos"),
    [
        (None, ["metadatos"]),
        ([1, 2], ["metadatos"]),
        ({"origen": "escaneo"}, ["metadatos.rumbos"]),
        ({"rumbos": [10.0, 360.0], "origen": "escaneo"}, ["metadatos.rumbos.1"]),
        ({"rumbos": [10.0, -1], "origen": "escaneo"}, ["metadatos.rumbos.1"]),
        ({"rumbos": [None, "abc"], "origen": "escaneo"}, ["metadatos.rumbos.1"]),
        ({"rumbos": [None, None], "origen": "frame"}, ["metadatos.origen"]),
        ({"rumbos": [None, None]}, ["metadatos.origen"]),
        ({"rumbos": [None, None], "origen": "escaneo", "app_version": "x" * 41}, ["metadatos.app_version"]),
        ({"rumbos": [None, None], "origen": "escaneo", "app_version": "a\u0000b"}, ["metadatos.app_version"]),
        (b'{"rumbos": [NaN, null], "origen": "escaneo"}', ["metadatos.rumbos.0"]),
        (b"x" * 16_385, ["metadatos"]),
    ],
)
def test_metadatos_que_no_valen_son_422(api, emb, metadatos, campos):
    status, codigo, detalle = _error(localizar(api, [jpeg(1), jpeg(2)], metadatos=metadatos))
    assert (status, codigo) == (422, "VALIDACION")
    assert [c["campo"] for c in detalle["campos"]] == campos
    assert emb.llamadas == []


def test_dos_partes_metadatos_es_422(api, emb):
    extra = [("metadatos", (None, b'{"rumbos": [null], "origen": "escaneo"}', "application/json"))]
    status, codigo, detalle = _error(localizar(api, [jpeg(1)], extra=extra))
    assert (status, codigo, detalle["campos"][0]["campo"]) == (422, "VALIDACION", "metadatos")


@pytest.mark.parametrize("cuerpo", [b"{no es json", b"\xff\xfe\x00", b"[" * 10_000])  # el último: RecursionError
def test_metadatos_que_no_son_json_es_400_solicitud_invalida(api, emb, cuerpo):
    assert _error(localizar(api, [jpeg(1)], metadatos=cuerpo))[:2] == (400, "SOLICITUD_INVALIDA")
    assert emb.llamadas == []


# --- Embeddings ------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("fallo", "esperado"),
    [
        (embedding.ImagenRechazada(2, "IMAGEN_INVALIDA"), (400, "FOTOS_INVALIDAS")),
        (embedding.EmbeddingNoDisponible("503 SATURADO"), (503, "EMBEDDING_NO_DISPONIBLE")),
        (embedding.RespuestaNoValida("200 sin version_vector"), (503, "EMBEDDING_NO_DISPONIBLE")),
    ],
)
def test_errores_de_embeddings_no_dejan_evento(api, base_migrada, emb, fallo, esperado):
    emb.fallo = fallo
    status, codigo, detalle = _error(localizar(api, [jpeg(1), jpeg(2), jpeg(3)]))
    assert (status, codigo) == esperado
    if status == 400:
        assert detalle == {"indice": 2, "motivo": "embeddings la rechazó (IMAGEN_INVALIDA)"}
    assert eventos(base_migrada) == []


def test_version_vector_distinta_es_503_sin_buscar_ni_escribir(api, base_migrada, emb, logs_json):
    emb.version = "dinov2-vitb14/pp-v1"
    assert _error(localizar(api, [jpeg(1)]))[:2] == (503, "EMBEDDING_NO_DISPONIBLE")
    [evento] = [e for e in logs_json.lineas if e["evento"] == "version_vector_distinta"]
    assert (evento["esperada"], evento["recibida"]) == (VERSION, "dinov2-vitb14/pp-v1")
    assert eventos(base_migrada) == []


def test_sin_embedding_url_es_503(base_migrada, logs_json):
    with TestClient(crear_app(base_migrada)) as cliente:
        r = localizar(cliente, [jpeg(1)])
    assert _error(r)[:2] == (503, "EMBEDDING_NO_DISPONIBLE")
    [evento] = [e for e in logs_json.lineas if e["evento"] == "embedding_no_disponible"]
    assert evento["motivo"] == "sin EMBEDDING_URL" and evento["nivel"] == "WARNING"


def test_tope_total_de_embeddings(api, base_migrada, emb, monkeypatch):
    from app.servicios import localizar as servicio

    async def lento(ajustes, imagenes, **_):
        await asyncio.sleep(1)

    monkeypatch.setattr(embedding, "vectorizar", lento)
    monkeypatch.setattr(servicio, "TOPE_EMBEDDING_S", 0.05)
    assert _error(localizar(api, [jpeg(1)]))[:2] == (503, "EMBEDDING_NO_DISPONIBLE")


# --- Privacidad (C4 en local) ----------------------------------------------------------------------------------------
def test_la_foto_no_llega_a_los_logs_y_el_evento_de_log_no_lleva_la_posicion(api, base_migrada, emb, logs_json):
    _escena(base_migrada)
    fotos = [jpeg(1), jpeg(2), jpeg(3)]
    emb.registrar(fotos)
    assert localizar(api, fotos, [90.0, 180.0, None]).status_code == 200
    texto = "\n".join(json.dumps(linea) for linea in logs_json.lineas)
    assert "/9j/" not in texto and base64.b64encode(fotos[0][:30]).decode() not in texto
    assert all(len(json.dumps(linea).encode()) < 16_384 for linea in logs_json.lineas)
    [evento] = [e for e in logs_json.lineas if e["evento"] == "localizacion_calculada"]
    assert (evento["resultado"], evento["nivel_confianza"], evento["confianza"]) == ("ok", "alta", 0.95)
    assert (evento["fotos_usadas"], evento["fotos_con_coincidencia"], evento["grupos"]) == (3, 3, 2)
    assert evento["coincidencias"] == 4 and evento["bytes"] == sum(map(len, fotos))
    assert evento["latencia_ms"] >= evento["busqueda_ms"] >= 0
    assert not {"lat", "lng", "posicion"} & set(evento)
    assert str(LAT0)[:5] not in json.dumps(evento)
