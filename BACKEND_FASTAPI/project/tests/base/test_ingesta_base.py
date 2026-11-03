"""BE-2.2 contra una base real, con S3 (`almacen_falso`) y embeddings simulados: `servicios.ingesta.procesar_lote`
(ARCHITECTURE §4.6, mensajes de §5.8). Cubre en local lo que miden C1–C5 de `validation-2-2.md`."""

from __future__ import annotations

import asyncio
import io
import json
import uuid
from typing import Any

import pytest
from PIL import Image
from sqlalchemy import text

from app.clientes.embedding import EmbeddingNoDisponible, ImagenRechazada, Vectores
from app.clientes.sqs import MensajeSqs
from app.config import Settings
from app.db import sesion
from app.servicios.ingesta import Dependencias, procesar_lote

pytestmark = pytest.mark.base

VERSION = "dinov2-vits14/pp-v1"


def jpeg(semilla: int = 0, ancho: int = 1024, alto: int = 768) -> bytes:
    imagen = Image.new("RGB", (ancho, alto), (semilla % 256, 90, 160))
    salida = io.BytesIO()
    imagen.save(salida, format="JPEG", quality=85)
    return salida.getvalue()


class Embeddings:
    """Doble de `embedding.vectorizar`: vectores unitarios, registra el tamaño de cada lote y puede fallar."""

    def __init__(self, version: str = VERSION) -> None:
        self.version = version
        self.lotes: list[int] = []
        self.fallos: list[Exception] = []

    async def __call__(self, imagenes) -> Vectores:
        self.lotes.append(len(imagenes))
        if self.fallos:
            raise self.fallos.pop(0)
        vectores = []
        for i, _ in enumerate(imagenes):
            vector = [0.0] * 384
            vector[(len(self.lotes) * 10 + i) % 384] = 1.0
            vectores.append(vector)
        return Vectores(version_vector=self.version, dim=384, vectores=vectores)


class Mundo:
    """Base migrada + almacén falso + embeddings falso, y un video con fotos registradas."""

    def __init__(self, ajustes: Settings, almacen) -> None:
        self.ajustes = ajustes
        self.almacen = almacen
        self.embeddings = Embeddings()
        self.mensajes = 0

    def sql(self, sentencia: str, **parametros: Any) -> list[Any]:
        async def correr():
            motor = sesion.crear_motor(self.ajustes, "pruebas")
            try:
                async with motor.begin() as conexion:
                    resultado = await conexion.execute(text(sentencia), parametros)
                    return list(resultado.all()) if resultado.returns_rows else []
            finally:
                await motor.dispose()

        return asyncio.run(correr())

    def video(self, n_fotos: int, *, completa: bool = True) -> tuple[uuid.UUID, list[uuid.UUID]]:
        video_id = self.sql(
            "INSERT INTO videos (nombre, ref_cliente, creado_por, subida_completa_en) "
            "SELECT 'validacion-22', :ref, id, CASE WHEN :completa THEN now() END FROM usuarios LIMIT 1 RETURNING id",
            ref=f"validacion-22-{uuid.uuid4().hex[:8]}",
            completa=completa,
        )[0][0]
        fotos = []
        for orden in range(1, n_fotos + 1):
            imagen_id = uuid.uuid4()
            self.sql(
                "INSERT INTO imagenes (id, video_id, orden, s3_key, lat, lng, capturada_en, bytes_declarados) "
                "VALUES (:id, :v, :o, :k, 1.0, -100.0, now(), 1000)",
                id=imagen_id,
                v=video_id,
                o=orden,
                k=self.clave(video_id, imagen_id),
            )
            fotos.append(imagen_id)
        return video_id, fotos

    @staticmethod
    def clave(video_id, imagen_id) -> str:
        return f"dataset/{video_id}/{imagen_id}.jpg"

    def subir(self, video_id, imagen_id, datos: bytes | None = None) -> MensajeSqs:
        """El `PUT` de la app (en el almacén falso) y el evento de S3 que llegaría a `ingesta`."""
        clave = self.clave(video_id, imagen_id)
        datos = jpeg(self.mensajes) if datos is None else datos
        etag = self.almacen.subir(clave, datos=datos)
        return self.evento(clave, etag, len(datos))

    def evento(self, clave: str, etag: str, size: int) -> MensajeSqs:
        objeto = {"key": clave, "size": size, "eTag": etag}
        cuerpo = {"Records": [{"eventName": "ObjectCreated:Put", "s3": {"bucket": {"name": "b"}, "object": objeto}}]}
        return self.mensaje(json.dumps(cuerpo))

    def mensaje(self, cuerpo: str) -> MensajeSqs:
        self.mensajes += 1
        return MensajeSqs(id=f"m{self.mensajes}", recibo=f"r{self.mensajes}", cuerpo=cuerpo, recepciones=1)

    def reprocesar(self, imagen_id) -> MensajeSqs:
        cuerpo = {
            "tipo": "reprocesar_imagen",
            "version": 1,
            "imagen_id": str(imagen_id),
            "solicitado_por": str(uuid.uuid4()),
            "solicitado_en": "2026-10-25T15:00:00Z",
        }
        return self.mensaje(json.dumps(cuerpo))

    def procesar(self, mensajes: list[MensajeSqs], ajustes: Settings | None = None):
        async def correr():
            usados = ajustes or self.ajustes
            motor = sesion.crear_motor(usados, "worker", pool=2)
            try:
                deps = Dependencias(motor=motor, almacen=self.almacen, ajustes=usados, vectorizar=self.embeddings)
                return await procesar_lote(deps, mensajes)
            finally:
                await motor.dispose()

        return asyncio.run(correr())

    def fotos(self, video_id) -> list[Any]:
        return self.sql(
            "SELECT orden, estado::text, error, etag, ancho, alto, intentos, bytes FROM imagenes WHERE video_id = :v "
            "ORDER BY orden",
            v=video_id,
        )

    def vectores(self, imagen_id) -> list[Any]:
        return self.sql(
            "SELECT version_vector, creado_en FROM embeddings WHERE imagen_id = :i ORDER BY version_vector", i=imagen_id
        )

    def estado_video(self, video_id) -> str:
        return self.sql("SELECT estado::text FROM videos WHERE id = :v", v=video_id)[0][0]


@pytest.fixture
def mundo(base_migrada, almacen_falso) -> Mundo:
    return Mundo(base_migrada, almacen_falso)


def test_c1_fotos_subidas_quedan_procesadas_con_vector_y_miniatura(mundo, logs_json):
    video_id, fotos = mundo.video(5)
    mensajes = [mundo.subir(video_id, imagen_id) for imagen_id in fotos]
    decisiones = mundo.procesar(mensajes)
    assert [d.borrar for d in decisiones] == [True] * 5
    assert mundo.embeddings.lotes == [4, 1]  # WORKER_LOTE_EMBEDDING = 4
    filas = mundo.fotos(video_id)
    assert {f.estado for f in filas} == {"procesada"}
    assert all(f.error is None and (f.ancho, f.alto) == (1024, 768) and f.intentos == 1 for f in filas)
    assert all(f.etag and f.etag.startswith("etag") and f.bytes > 0 for f in filas)
    for imagen_id in fotos:
        assert [v.version_vector for v in mundo.vectores(imagen_id)] == [VERSION]
        miniatura = Image.open(io.BytesIO(mundo.almacen.datos[f"thumbs/{video_id}/{imagen_id}.jpg"]))
        assert miniatura.format == "JPEG" and max(miniatura.size) == 320
    assert mundo.estado_video(video_id) == "procesado"
    eventos = [linea["evento"] for linea in logs_json.lineas]
    assert eventos.count("imagen_procesada") == 5


def test_foto_pendiente_pasa_por_subida_y_el_video_se_recalcula(mundo):
    video_id, fotos = mundo.video(2, completa=True)
    mundo.embeddings.fallos.append(EmbeddingNoDisponible("503 NO_LISTO"))
    decisiones = mundo.procesar([mundo.subir(video_id, fotos[0])])
    assert decisiones[0].borrar is False  # transitorio: el mensaje vuelve a la cola
    filas = mundo.fotos(video_id)
    assert filas[0].estado == "subida" and filas[0].etag == "etag0" and filas[0].bytes > 0
    assert filas[1].estado == "pendiente_subida"
    assert mundo.estado_video(video_id) == "pendiente"
    assert mundo.vectores(fotos[0]) == []


def test_c2_jpeg_corrupto_queda_en_error_y_el_mensaje_se_borra(mundo, logs_json):
    video_id, fotos = mundo.video(2)
    mensajes = [mundo.subir(video_id, fotos[0]), mundo.subir(video_id, fotos[1], datos=b"validacion-no-es-jpeg")]
    decisiones = mundo.procesar(mensajes)
    assert [d.borrar for d in decisiones] == [True, True]
    filas = mundo.fotos(video_id)
    assert filas[0].estado == "procesada"
    assert (filas[1].estado, filas[1].error, filas[1].intentos) == ("error", "no es un JPEG decodificable", 1)
    assert mundo.vectores(fotos[1]) == []
    assert mundo.estado_video(video_id) == "con_errores"
    assert any(linea["evento"] == "imagen_con_error" for linea in logs_json.lineas)


def test_demasiado_grande_y_pequena_son_errores_permanentes(mundo):
    video_id, fotos = mundo.video(2)
    ajustes = mundo.ajustes.model_copy(update={"rec_max_bytes_foto": 2000})
    datos = jpeg(1) + b"\0" * 5000
    decisiones = mundo.procesar([mundo.subir(video_id, fotos[0], datos=datos)], ajustes=ajustes)
    assert decisiones[0].borrar is True
    fila = mundo.fotos(video_id)[0]
    assert (fila.estado, fila.error) == ("error", f"demasiado grande: {len(datos)} bytes (máximo 2000)")
    assert fila.bytes == len(datos)
    decisiones = mundo.procesar([mundo.subir(video_id, fotos[1], datos=jpeg(3, 200, 150))])
    assert decisiones[0].borrar is True
    assert mundo.fotos(video_id)[1].error == "lado menor 150 px (mínimo 320)"


def test_c4_evento_duplicado_no_crea_un_segundo_vector(mundo, logs_json):
    video_id, fotos = mundo.video(1)
    mensaje = mundo.subir(video_id, fotos[0])
    mundo.procesar([mensaje])
    antes = mundo.vectores(fotos[0])
    descargas = len(mundo.almacen.descargadas)
    repetido = mundo.mensaje(mensaje.cuerpo)
    decisiones = mundo.procesar([repetido])
    assert decisiones[0].borrar is True
    assert mundo.vectores(fotos[0]) == antes and len(antes) == 1
    assert len(mundo.almacen.descargadas) == descargas  # ni siquiera lo descarga
    assert mundo.fotos(video_id)[0].intentos == 1
    descartes = [linea for linea in logs_json.lineas if linea["evento"] == "mensaje_descartado"]
    assert descartes and descartes[-1]["motivo"] == "duplicado"


def test_dos_eventos_de_la_misma_foto_en_un_lote_comparten_trabajo(mundo):
    video_id, fotos = mundo.video(1)
    mensaje = mundo.subir(video_id, fotos[0])
    decisiones = mundo.procesar([mensaje, mundo.mensaje(mensaje.cuerpo)])
    assert [d.borrar for d in decisiones] == [True, True]
    assert mundo.embeddings.lotes == [1] and len(mundo.vectores(fotos[0])) == 1


def test_c5_reprocesar_regenera_el_vector(mundo):
    video_id, fotos = mundo.video(1)
    mundo.procesar([mundo.subir(video_id, fotos[0])])
    antes = mundo.vectores(fotos[0])[0].creado_en
    decisiones = mundo.procesar([mundo.reprocesar(fotos[0])])
    assert decisiones[0].borrar is True
    despues = mundo.vectores(fotos[0])
    assert len(despues) == 1 and despues[0].creado_en > antes
    fila = mundo.fotos(video_id)[0]
    assert fila.estado == "procesada" and fila.intentos == 2


def test_un_nuevo_put_con_otro_etag_se_vuelve_a_procesar(mundo):
    video_id, fotos = mundo.video(1)
    mundo.procesar([mundo.subir(video_id, fotos[0], datos=b"validacion-no-es-jpeg")])
    assert mundo.fotos(video_id)[0].estado == "error"
    mundo.procesar([mundo.subir(video_id, fotos[0])])  # la app la vuelve a subir bien
    fila = mundo.fotos(video_id)[0]
    assert (fila.estado, fila.error) == ("procesada", None)
    assert mundo.estado_video(video_id) == "procesado"


def test_mensajes_sin_foto_se_descartan_y_se_borran(mundo, logs_json):
    video_id, _ = mundo.video(1)
    inexistente = mundo.evento(Mundo.clave(video_id, uuid.uuid4()), "e", 10)
    otro_video = mundo.evento(Mundo.clave(uuid.uuid4(), uuid.uuid4()), "e", 10)
    clave_rara = mundo.evento("dataset/validacion-sonda.jpg", "e", 10)
    prueba = mundo.mensaje(json.dumps({"Service": "Amazon S3", "Event": "s3:TestEvent"}))
    basura = mundo.mensaje("no es json")
    reprocesar = mundo.reprocesar(uuid.uuid4())
    decisiones = mundo.procesar([inexistente, otro_video, clave_rara, prueba, basura, reprocesar])
    assert all(d.borrar for d in decisiones)
    assert mundo.embeddings.lotes == [] and mundo.almacen.descargadas == []
    motivos = [linea.get("motivo") for linea in logs_json.lineas if linea["evento"] == "mensaje_descartado"]
    assert motivos.count("imagen_no_existe") == 2 and "video_no_existe" in motivos and "prueba_s3" in motivos
    assert "clave_no_reconocida" in motivos
    assert any(linea["evento"] == "mensaje_no_reconocido" for linea in logs_json.lineas)


def test_video_eliminado_se_descarta(mundo):
    video_id, fotos = mundo.video(1)
    mensaje = mundo.subir(video_id, fotos[0])
    mundo.sql(
        "UPDATE videos SET estado = 'eliminado', eliminado_en = now(), eliminado_por = creado_por WHERE id = :v",
        v=video_id,
    )
    decisiones = mundo.procesar([mensaje])
    assert decisiones[0].borrar is True
    assert mundo.fotos(video_id)[0].estado == "pendiente_subida" and mundo.almacen.descargadas == []


def test_objeto_que_ya_no_esta_se_descarta(mundo):
    video_id, fotos = mundo.video(1)
    mensaje = mundo.subir(video_id, fotos[0])
    del mundo.almacen.objetos[Mundo.clave(video_id, fotos[0])]
    assert mundo.procesar([mensaje])[0].borrar is True
    assert mundo.fotos(video_id)[0].estado == "subida"


def test_version_vector_distinta_no_guarda_y_conserva_el_mensaje(mundo, logs_json):
    video_id, fotos = mundo.video(1)
    mundo.embeddings.version = "otro-modelo/pp-v9"
    decisiones = mundo.procesar([mundo.subir(video_id, fotos[0])])
    assert decisiones[0].borrar is False
    assert mundo.vectores(fotos[0]) == [] and mundo.fotos(video_id)[0].estado == "subida"
    distinta = [linea for linea in logs_json.lineas if linea["evento"] == "version_vector_distinta"]
    assert distinta and distinta[0]["recibida"] == "otro-modelo/pp-v9" and distinta[0]["nivel"] == "ERROR"


def test_imagen_rechazada_por_embeddings_queda_en_error_y_las_demas_siguen(mundo):
    video_id, fotos = mundo.video(3)
    mundo.embeddings.fallos.append(ImagenRechazada(1, "IMAGEN_INVALIDA"))
    decisiones = mundo.procesar([mundo.subir(video_id, f) for f in fotos])
    assert [d.borrar for d in decisiones] == [True, True, True]
    assert mundo.embeddings.lotes == [3, 2]
    estados = [(f.estado, f.error) for f in mundo.fotos(video_id)]
    assert estados == [("procesada", None), ("error", "embeddings la rechazó (IMAGEN_INVALIDA)"), ("procesada", None)]


def test_s3_que_falla_es_transitorio(mundo):
    video_id, fotos = mundo.video(2)
    mensajes = [mundo.subir(video_id, f) for f in fotos]
    mundo.almacen.fallar_descarga.add(Mundo.clave(video_id, fotos[1]))
    decisiones = mundo.procesar(mensajes)
    assert [d.borrar for d in decisiones] == [True, False]
    assert [f.estado for f in mundo.fotos(video_id)] == ["procesada", "subida"]


def test_base_no_disponible_conserva_los_mensajes(mundo):
    video_id, fotos = mundo.video(1)
    mensaje = mundo.subir(video_id, fotos[0])
    sin_base = mundo.ajustes.model_copy(update={"db_port": 1, "db_connect_timeout_s": 2})
    assert mundo.procesar([mensaje], ajustes=sin_base)[0].borrar is False
    assert mundo.procesar([mensaje])[0].borrar is True  # al volver la base, se procesa
