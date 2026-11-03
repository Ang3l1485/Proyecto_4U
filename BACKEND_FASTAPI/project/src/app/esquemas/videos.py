"""Peticiones y respuestas de recolección y de videos (ARCHITECTURE §5.4 y §5.5), BE-2.1; desde BE-4.1, también las de
administración de videos e imágenes (`VideoRenombrar`, `VideoBorrado`, `ImagenEditar`, `ImagenesLote`,
`LoteResultado`, `ImagenDetalle`).

Las peticiones ignoran los campos de más (`extra="ignore"`) y pasan todo texto por `texto_admitido` (§4.4). Los límites
que son parámetros de §5.10 (`REC_MAX_LOTE`, `REC_MAX_FOTOS_VIDEO`, `REC_MAX_BYTES_FOTO`, `PAGINA_MAX`) no están aquí:
los comprueba el servicio con los `Settings` (si cambia el parámetro, cambia el límite sin tocar el código).
"""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.dominio.enumerados import CalidadImagen, EstadoImagen, EstadoVideo
from app.dominio.recoleccion import como_real
from app.esquemas.comun import FechaConZona, FechaUtc, Referencia, texto_admitido

#: Longitudes de §5.4 (en caracteres, tras recortar los espacios de alrededor).
NOMBRE_VIDEO_MAX = 40
REF_CLIENTE_MAX = 40
DISPOSITIVO_MAX = 200
APP_VERSION_MAX = 40
TOTAL_FOTOS_MAX = 200  # `videos_total_fotos_declaradas_check` (§5.7)
ENTERO_MAX = 2_147_483_647  # columnas `integer` de §5.7
DISTANCIA_MAX_M = 1_000_000.0
Q_MAX = 100
#: Tope fijo de elementos de `images` (el `REC_MAX_LOTE` inicial de §5.10): Pydantic no valida cuerpos más grandes.
#: `REC_MAX_LOTE` solo puede bajarlo (el servicio lo comprueba con los `Settings`).
LOTE_TOPE = 50


def _rumbo(valor: float | None) -> float | None:
    """[0, 360) también después de guardarlo como `real` (359,9999999 se guardaría como 360)."""
    if valor is not None and not (0 <= valor < 360 and 0 <= como_real(valor) < 360):
        raise ValueError("Debe estar en [0, 360).")
    return valor


def _recortado(valor: str, maximo: int, *, obligatorio: bool) -> str | None:
    texto = texto_admitido(valor).strip()
    if not texto:
        if obligatorio:
            raise ValueError("No puede estar vacío.")
        return None
    if len(texto) > maximo:
        raise ValueError(f"Debe tener como máximo {maximo} caracteres tras recortar los espacios.")
    return texto


# --- Objetos comunes ------------------------------------------------------------------------------------------------
class Coordenada(BaseModel):
    model_config = ConfigDict(extra="ignore")

    lat: float = Field(ge=-90, le=90, allow_inf_nan=False)
    lng: float = Field(ge=-180, le=180, allow_inf_nan=False)


class InicioRecorrido(Coordenada):
    """`inicio` de §5.4 y §5.5: coordenada y rumbo (norte verdadero, [0, 360), o `null`) del primer paso."""

    rumbo: float | None = Field(default=None, allow_inf_nan=False)

    @field_validator("rumbo")
    @classmethod
    def _validar_rumbo(cls, valor: float | None) -> float | None:
        return _rumbo(valor)


class ConteoFotos(BaseModel):
    """Fotos del video por estado: siempre las cuatro claves."""

    model_config = ConfigDict(extra="forbid")

    pendiente_subida: int
    subida: int
    procesada: int
    error: int


# --- POST /v1/collect/videos ----------------------------------------------------------------------------------------
class VideoCrear(BaseModel):
    """`ref_cliente` es obligatorio (1–40 tras recortar); `nombre` opcional (1–40 tras recortar; vacío o ausente →
    `video_<numero>`). El resto es opcional."""

    model_config = ConfigDict(extra="ignore")

    ref_cliente: str
    nombre: str | None = None
    iniciado_en: FechaConZona | None = None
    finalizado_en: FechaConZona | None = None
    duracion_s: int | None = Field(default=None, ge=0, le=ENTERO_MAX)
    distancia_m: float | None = Field(default=None, ge=0, le=DISTANCIA_MAX_M, allow_inf_nan=False)
    pasos: int | None = Field(default=None, ge=0, le=ENTERO_MAX)
    inicio: InicioRecorrido | None = None
    total_fotos: int = Field(default=0, ge=0, le=TOTAL_FOTOS_MAX)
    dispositivo: str | None = None
    app_version: str | None = None

    @field_validator("ref_cliente")
    @classmethod
    def _ref_cliente(cls, valor: str) -> str:
        return _recortado(valor, REF_CLIENTE_MAX, obligatorio=True)  # type: ignore[return-value]

    @field_validator("nombre")
    @classmethod
    def _nombre(cls, valor: str | None) -> str | None:
        return None if valor is None else _recortado(valor, NOMBRE_VIDEO_MAX, obligatorio=False)

    @field_validator("dispositivo")
    @classmethod
    def _dispositivo(cls, valor: str | None) -> str | None:
        return None if valor is None else _recortado(valor, DISPOSITIVO_MAX, obligatorio=False)

    @field_validator("app_version")
    @classmethod
    def _app_version(cls, valor: str | None) -> str | None:
        return None if valor is None else _recortado(valor, APP_VERSION_MAX, obligatorio=False)

    @model_validator(mode="after")
    def _fechas(self) -> VideoCrear:
        if self.iniciado_en and self.finalizado_en and self.finalizado_en < self.iniciado_en:
            raise ValueError("finalizado_en no puede ser anterior a iniciado_en.")
        return self


# --- POST /v1/collect/videos/{id}/images ----------------------------------------------------------------------------
class ImagenRegistro(Coordenada):
    """Una foto del lote. `orden` ≥ 1 (el máximo es `REC_MAX_FOTOS_VIDEO`) y `bytes` > 0 (el máximo es
    `REC_MAX_BYTES_FOTO`): los máximos los comprueba el servicio."""

    orden: int = Field(ge=1, le=32_767)
    rumbo: float | None = Field(default=None, allow_inf_nan=False)
    capturada_en: FechaConZona
    bytes: int = Field(gt=0, le=ENTERO_MAX)

    @field_validator("rumbo")
    @classmethod
    def _validar_rumbo(cls, valor: float | None) -> float | None:
        return _rumbo(valor)


class ImagenesRegistrar(BaseModel):
    model_config = ConfigDict(extra="ignore")

    imagenes: list[ImagenRegistro] = Field(min_length=1, max_length=LOTE_TOPE)


class SubidaPut(BaseModel):
    """Cómo subir la foto: `PUT` a `url` con **exactamente** `encabezados` y el JPEG como cuerpo (§5.4)."""

    model_config = ConfigDict(extra="forbid")

    metodo: Literal["PUT"] = "PUT"
    url: str = Field(description="URL prefirmada (no se registra en ningún log)")
    encabezados: dict[str, str]
    expira_en: FechaUtc


class ImagenRegistrada(BaseModel):
    model_config = ConfigDict(extra="forbid")

    orden: int
    id: uuid.UUID
    estado: EstadoImagen
    subida: SubidaPut | None


class ImagenesRegistradas(BaseModel):
    model_config = ConfigDict(extra="forbid")

    imagenes: list[ImagenRegistrada]


# --- POST /v1/collect/videos/{id}/complete --------------------------------------------------------------------------
class SubidaCompletada(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    estado: EstadoVideo
    conteo: ConteoFotos


# --- §5.5: VideoResumen, ImagenAdmin y detalle ----------------------------------------------------------------------
class VideoResumen(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    numero: int
    nombre: str
    ref_cliente: str
    estado: EstadoVideo
    creado_en: FechaUtc
    iniciado_en: FechaUtc | None
    finalizado_en: FechaUtc | None
    duracion_s: int | None
    distancia_m: float | None
    pasos: int | None
    inicio: InicioRecorrido | None
    total_fotos: int
    conteo: ConteoFotos
    creado_por: Referencia


class ImagenAdmin(BaseModel):
    """Desde BE-4.1, `url` (original) y `url_miniatura` son prefirmadas GET de `PRESIGN_GET_TTL_S` (`null` si el objeto
    aún no existe o no se pudo firmar) y `url_expira_en` es su vencimiento (`null` sin ninguna URL), §5.5."""

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    video_id: uuid.UUID
    orden: int
    lat: float
    lng: float
    rumbo: float | None
    capturada_en: FechaUtc
    estado: EstadoImagen
    error: str | None
    calidad: CalidadImagen
    lugar: Referencia | None
    notas: str | None
    url: str | None = None
    url_miniatura: str | None = None
    url_expira_en: FechaUtc | None = None


class VideoDetalle(VideoResumen):
    fotos: list[ImagenAdmin]


# --- Administración de videos e imágenes (BE-4.1, §5.5) -----------------------------------------------------------
NOTAS_MAX = 500  # `imagenes.notas` (§5.7)
LOTE_IMAGENES_MAX = 200


class VideoRenombrar(BaseModel):
    """`PATCH /v1/admin/videos/{id}`: `nombre` de 1 a 40 caracteres tras recortar (aquí vacío no vale)."""

    model_config = ConfigDict(extra="ignore")

    nombre: str

    @field_validator("nombre")
    @classmethod
    def _nombre(cls, valor: str) -> str:
        return _recortado(valor, NOMBRE_VIDEO_MAX, obligatorio=True)  # type: ignore[return-value]


class VideoBorrado(BaseModel):
    """`DELETE /v1/admin/videos/{id}` → `202`. Repetir da la misma respuesta (`fotos_retiradas`, de la auditoría)."""

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    estado: Literal["eliminado"] = "eliminado"
    fotos_retiradas: int
    purga: Literal["programada"] = "programada"


class ImagenEditar(BaseModel):
    """`PATCH /v1/admin/images/{id}`: cualquiera de `lat`+`lng` (juntos), `lugar_id` (o `null`), `calidad`, `notas`
    (≤ 500 tras recortar; vacío o `null` = sin notas). Lo que no se envía no cambia; el router usa `model_fields_set`
    para distinguir «ausente» de `null`."""

    model_config = ConfigDict(extra="ignore")

    lat: float | None = Field(default=None, ge=-90, le=90, allow_inf_nan=False)
    lng: float | None = Field(default=None, ge=-180, le=180, allow_inf_nan=False)
    lugar_id: uuid.UUID | None = None
    calidad: CalidadImagen | None = None
    notas: str | None = None

    @field_validator("notas")
    @classmethod
    def _notas(cls, valor: str | None) -> str | None:
        return None if valor is None else _recortado(valor, NOTAS_MAX, obligatorio=False)


class ImagenesLote(BaseModel):
    """`POST /v1/admin/images/lote`. `reasignar` exige la clave `lugar_id` (un id o `null` = quitar el lugar)."""

    model_config = ConfigDict(extra="ignore")

    accion: Literal["eliminar", "reasignar"]
    ids: list[uuid.UUID] = Field(min_length=1, max_length=LOTE_IMAGENES_MAX)
    lugar_id: uuid.UUID | None = None


class FallidaLote(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    codigo: str


class LoteResultado(BaseModel):
    model_config = ConfigDict(extra="forbid")

    procesadas: int
    fallidas: list[FallidaLote]


class ReferenciaVideo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    numero: int
    nombre: str


class VectorImagen(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version_vector: str
    creado_en: FechaUtc


class ImagenDetalle(ImagenAdmin):
    """`GET /v1/admin/images/{id}`: `ImagenAdmin` + `video` + `vector` (el de `EMBEDDING_VERSION_VECTOR`, o `null`)."""

    video: ReferenciaVideo
    vector: VectorImagen | None
