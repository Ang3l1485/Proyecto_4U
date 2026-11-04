"""Reglas de la recolección del dataset sin infraestructura (ARCHITECTURE §4.5, §5.4, §5.5).

Python puro (regla de `dominio/`, §4.1): lo usan `servicios/recoleccion.py`, `servicios/videos.py`,
`servicios/limpieza.py` y, desde BE-2.2, el `worker`.

- Claves de S3 (infra §5.5): `clave_dataset`, `clave_miniatura` e `ids_de_clave` (la inversa, para los eventos de S3).
- `Conteo` de fotos por estado y `estado_video(conteo, subida_completa)`: el estado del video se deriva siempre de esos
  dos datos (ADR-BE-14).
- `es_dato_de_validacion(nombre, ref_cliente)`: qué videos puede borrar `limpiar-validacion` (§5.9).
- `como_real(x)`: el valor que guarda una columna `real` (float32), para validar rangos antes de escribir.
"""

from __future__ import annotations

import re
import struct
import uuid
from dataclasses import dataclass

from app.dominio.enumerados import EstadoImagen, EstadoVideo

#: Prefijo de los datos de prueba de los validadores (infra §5.11, backend §5.11).
PREFIJO_VALIDACION = "validacion-"
PREFIJO_DATASET = "dataset/"
PREFIJO_MINIATURAS = "thumbs/"
#: Encabezados exactos que la app debe enviar en el `PUT` prefirmado (§5.4): forman parte de la firma.
TIPO_JPEG = "image/jpeg"
ENCABEZADOS_PUT = {"Content-Type": TIPO_JPEG}

_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
_CLAVE_DATASET = re.compile(rf"dataset/({_UUID})/({_UUID})\.jpg")


def clave_dataset(video_id: uuid.UUID, imagen_id: uuid.UUID) -> str:
    """`dataset/{video_id}/{imagen_id}.jpg` (infra §5.5; `imagenes_s3_key_check` de §5.7)."""
    return f"{PREFIJO_DATASET}{video_id}/{imagen_id}.jpg"


def clave_miniatura(video_id: uuid.UUID, imagen_id: uuid.UUID) -> str:
    """`thumbs/{video_id}/{imagen_id}.jpg` (infra §5.5): la escribe el `worker` (BE-2.2)."""
    return f"{PREFIJO_MINIATURAS}{video_id}/{imagen_id}.jpg"


def prefijos_del_video(video_id: uuid.UUID) -> tuple[str, str]:
    """Los dos prefijos de S3 que pueden tener objetos de un video (`dataset/{id}/` y `thumbs/{id}/`)."""
    return f"{PREFIJO_DATASET}{video_id}/", f"{PREFIJO_MINIATURAS}{video_id}/"


def ids_de_clave(clave: str) -> tuple[uuid.UUID, uuid.UUID] | None:
    """`(video_id, imagen_id)` de una clave `dataset/…` ya decodificada (`unquote_plus`), o `None` si no tiene esa forma
    exacta (UUID en minúsculas)."""
    coincidencia = _CLAVE_DATASET.fullmatch(clave)
    if coincidencia is None:
        return None
    return uuid.UUID(coincidencia.group(1)), uuid.UUID(coincidencia.group(2))


@dataclass(frozen=True)
class Conteo:
    """Fotos de un video por estado (`conteo` de §5.4 y §5.5)."""

    pendiente_subida: int = 0
    subida: int = 0
    procesada: int = 0
    error: int = 0

    @classmethod
    def desde(cls, por_estado: dict[str, int]) -> Conteo:
        """A partir de `{estado: n}` (p. ej. un `GROUP BY estado`); los estados ausentes cuentan 0."""
        return cls(**{estado.value: int(por_estado.get(estado.value, 0)) for estado in EstadoImagen})

    @property
    def total(self) -> int:
        return self.pendiente_subida + self.subida + self.procesada + self.error

    def como_dict(self) -> dict[str, int]:
        return {estado.value: getattr(self, estado.value) for estado in EstadoImagen}


def estado_video(conteo: Conteo, subida_completa: bool) -> EstadoVideo:
    """Estado de un video no eliminado (§5.5, ADR-BE-14):

    - `pendiente`: la app no ha llamado a `complete` (`subida_completa = False`) o queda alguna foto `pendiente_subida`;
    - `procesando`: subida completa y alguna foto `subida` (el `worker` aún no la procesó);
    - `con_errores`: subida completa, ninguna `subida` y al menos una en `error`;
    - `procesado`: subida completa y todas `procesada` (también con 0 fotos).
    """
    if not subida_completa or conteo.pendiente_subida > 0:
        return EstadoVideo.pendiente
    if conteo.subida > 0:
        return EstadoVideo.procesando
    if conteo.error > 0:
        return EstadoVideo.con_errores
    return EstadoVideo.procesado


def es_dato_de_validacion(nombre: str, ref_cliente: str) -> bool:
    """¿Lo puede borrar `limpiar-validacion`? Solo si `nombre` **y** `ref_cliente` empiezan por `validacion-`."""
    return nombre.startswith(PREFIJO_VALIDACION) and ref_cliente.startswith(PREFIJO_VALIDACION)


def como_real(valor: float) -> float:
    """El valor que guarda PostgreSQL en una columna `real` (float32). Un rumbo de 359,999999 se guarda como 360,0 y
    violaría `rumbo < 360`: los esquemas comprueban el rango sobre este valor (§5.4)."""
    return struct.unpack("f", struct.pack("f", valor))[0]


def real_legible(valor: float | None) -> float | None:
    """Un `real` leído de la base (p. ej. 340.29998779296875) con las menos cifras que lo representan como float32
    (340.3), para la API. Nunca cambia el valor guardado: 359.99997 no se redondea a 360."""
    if valor is None:
        return None
    guardado = como_real(valor)
    for cifras in range(1, 10):
        corto = float(f"{valor:.{cifras}g}")
        if como_real(corto) == guardado:
            return corto
    return valor
