"""Modelos SQLAlchemy del esquema de ARCHITECTURE §5.7.

Describen las mismas tablas, restricciones e índices que la migración `0001` (las pruebas comprueban que
`Base.metadata.create_all` deja exactamente `app.db.esquema.ESPERADO`). El esquema de la base lo cambian solo las
migraciones de `migrations/`; estos modelos son la vista de la aplicación y se actualizan en el mismo cambio.

Convenciones:
- Nombres de restricciones e índices como los pone PostgreSQL (`<tabla>_pkey`, `_<columnas>_key`, `_fkey`, `_idx`,
  `_<nombre>_check`), porque `verificar-esquema` también compara nombres.
- `actualizado_en` lo mantiene la aplicación (`onupdate`); no hay *triggers*.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    DDL,
    REAL,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Double,
    Enum,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Sequence,
    SmallInteger,
    Text,
    UniqueConstraint,
    event,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import UserDefinedType

from app.dominio.enumerados import (
    CalidadImagen,
    CategoriaLugar,
    EstadoImagen,
    EstadoVideo,
    PrioridadAlerta,
    RolUsuario,
    TipoAlerta,
)

DIMENSION_VECTOR = 384  # DINOv2 ViT-S/14 (embeddings §5.3); normalizado L2

CONVENCION_NOMBRES = {
    "pk": "%(table_name)s_pkey",
    "uq": "%(table_name)s_%(column_0_N_name)s_key",
    "fk": "%(table_name)s_%(column_0_N_name)s_fkey",
    "ix": "%(table_name)s_%(column_0_N_name)s_idx",
    "ck": "%(table_name)s_%(constraint_name)s_check",
}


class Vector(UserDefinedType):
    """`vector(n)` de pgvector, sin depender del paquete `pgvector` (que arrastra numpy a la imagen).

    Se envía y se lee como texto (`[0.1,0.2,…]`): asyncpg usa el formato de texto para los tipos que no conoce.
    """

    cache_ok = True

    def __init__(self, dimension: int) -> None:
        self.dimension = dimension

    def get_col_spec(self, **_: Any) -> str:
        return f"vector({self.dimension})"

    def bind_processor(self, dialect: Any):
        def procesar(valor: Any) -> str | None:
            if valor is None:
                return None
            return "[" + ",".join(repr(float(x)) for x in valor) + "]"

        return procesar

    def result_processor(self, dialect: Any, coltype: Any):
        def procesar(valor: Any) -> list[float] | None:
            if valor is None:
                return None
            if isinstance(valor, str):
                return [float(x) for x in valor.strip("[]").split(",") if x]
            return [float(x) for x in valor]

        return procesar


def _enum(clase: type, nombre: str) -> Enum:
    return Enum(clase, name=nombre, values_callable=lambda e: [m.value for m in e], validate_strings=True)


def _check(expresion: str, nombre: str) -> CheckConstraint:
    return CheckConstraint(expresion, name=nombre)


def _lat_lng(lat: str = "lat", lng: str = "lng", prefijo: str = "") -> tuple[CheckConstraint, CheckConstraint]:
    return (
        _check(f"{lat} BETWEEN '-90' AND '90'", f"{prefijo}lat"),
        _check(f"{lng} BETWEEN '-180' AND '180'", f"{prefijo}lng"),
    )


def _id() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))


def _creado_en() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


def _actualizado_en() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


def _fecha_nula() -> Mapped[datetime | None]:
    return mapped_column(DateTime(timezone=True), nullable=True)


def _usuario(nulo: bool = False) -> Mapped[Any]:
    return mapped_column(UUID(as_uuid=True), ForeignKey("usuarios.id"), nullable=nulo)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=CONVENCION_NOMBRES)


class Usuario(Base):
    __tablename__ = "usuarios"
    __table_args__ = (
        UniqueConstraint("correo"),
        _check("correo = lower(btrim(correo)) AND correo <> ''", "correo"),
        _check("btrim(nombre) <> ''", "nombre"),
    )

    id: Mapped[uuid.UUID] = _id()
    correo: Mapped[str] = mapped_column(Text, nullable=False)
    nombre: Mapped[str] = mapped_column(Text, nullable=False)
    rol: Mapped[RolUsuario] = mapped_column(_enum(RolUsuario, "rol_usuario"), nullable=False, server_default="user")
    hash_password: Mapped[str] = mapped_column(Text, nullable=False)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    creado_en: Mapped[datetime] = _creado_en()
    ultimo_acceso_en: Mapped[datetime | None] = _fecha_nula()


class Lugar(Base):
    __tablename__ = "lugares"
    __table_args__ = (
        UniqueConstraint("nombre_normalizado"),
        _check("char_length(nombre) BETWEEN 2 AND 80", "nombre"),
        *_lat_lng(),
        _check("char_length(descripcion) <= 300", "descripcion"),
        _check("char_length(referencias) <= 300", "referencias"),
        _check("imagen_key = 'lugares/' || id::text || '.jpg'", "imagen_key"),
    )

    id: Mapped[uuid.UUID] = _id()
    nombre: Mapped[str] = mapped_column(Text, nullable=False)
    nombre_normalizado: Mapped[str] = mapped_column(Text, nullable=False)
    categoria: Mapped[CategoriaLugar] = mapped_column(_enum(CategoriaLugar, "categoria_lugar"), nullable=False)
    lat: Mapped[float] = mapped_column(Double, nullable=False)
    lng: Mapped[float] = mapped_column(Double, nullable=False)
    alias: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default=text("'{}'"))
    descripcion: Mapped[str | None] = mapped_column(Text)
    referencias: Mapped[str | None] = mapped_column(Text)
    imagen_key: Mapped[str | None] = mapped_column(Text)
    creado_en: Mapped[datetime] = _creado_en()
    actualizado_en: Mapped[datetime] = _actualizado_en()
    creado_por: Mapped[uuid.UUID] = _usuario()


class Alerta(Base):
    __tablename__ = "alertas"
    __table_args__ = (
        *_lat_lng(),
        _check("char_length(mensaje) BETWEEN 1 AND 200", "mensaje"),
        _check("radio_m BETWEEN 5 AND 100", "radio_m"),
        _check("vigencia_hasta > vigencia_desde", "vigencia"),
        _check("version >= 1", "version"),
        Index(None, "actualizado_en"),
    )

    id: Mapped[uuid.UUID] = _id()  # la app puede generarlo (ADR-BE-10)
    lat: Mapped[float] = mapped_column(Double, nullable=False)
    lng: Mapped[float] = mapped_column(Double, nullable=False)
    mensaje: Mapped[str] = mapped_column(Text, nullable=False)
    tipo: Mapped[TipoAlerta] = mapped_column(_enum(TipoAlerta, "tipo_alerta"), nullable=False, server_default="otro")
    prioridad: Mapped[PrioridadAlerta] = mapped_column(
        _enum(PrioridadAlerta, "prioridad_alerta"), nullable=False, server_default="normal"
    )
    radio_m: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("15"))
    activa: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    vigencia_desde: Mapped[datetime | None] = _fecha_nula()
    vigencia_hasta: Mapped[datetime | None] = _fecha_nula()
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    creado_en: Mapped[datetime] = _creado_en()
    actualizado_en: Mapped[datetime] = _actualizado_en()
    creado_por: Mapped[uuid.UUID] = _usuario()
    actualizado_por: Mapped[uuid.UUID] = _usuario()
    eliminada_en: Mapped[datetime | None] = _fecha_nula()


SECUENCIA_NUMERO_VIDEO = Sequence("videos_numero_seq", data_type=Integer, metadata=Base.metadata)


class Video(Base):
    __tablename__ = "videos"
    __table_args__ = (
        UniqueConstraint("numero"),
        UniqueConstraint("creado_por", "ref_cliente"),
        _check("char_length(nombre) BETWEEN 1 AND 40", "nombre"),
        _check("char_length(ref_cliente) BETWEEN 1 AND 40", "ref_cliente"),
        _check("duracion_s >= 0", "duracion_s"),
        _check("pasos >= 0", "pasos"),
        _check("distancia_m >= 0", "distancia_m"),
        _check("(inicio_lat IS NULL) = (inicio_lng IS NULL)", "inicio"),
        *_lat_lng("inicio_lat", "inicio_lng", "inicio_"),
        _check("inicio_rumbo >= 0 AND inicio_rumbo < 360", "inicio_rumbo"),
        _check("total_fotos_declaradas BETWEEN 0 AND 200", "total_fotos_declaradas"),
        _check(
            "(estado = 'eliminado') = (eliminado_en IS NOT NULL) AND (eliminado_en IS NULL) = (eliminado_por IS NULL)",
            "eliminado",
        ),
        _check("purgado_en IS NULL OR eliminado_en IS NOT NULL", "purgado_en"),
    )

    id: Mapped[uuid.UUID] = _id()
    numero: Mapped[int] = mapped_column(Integer, nullable=False, server_default=SECUENCIA_NUMERO_VIDEO.next_value())
    nombre: Mapped[str] = mapped_column(Text, nullable=False)
    ref_cliente: Mapped[str] = mapped_column(Text, nullable=False)
    estado: Mapped[EstadoVideo] = mapped_column(
        _enum(EstadoVideo, "estado_video"), nullable=False, server_default="pendiente"
    )
    iniciado_en: Mapped[datetime | None] = _fecha_nula()
    finalizado_en: Mapped[datetime | None] = _fecha_nula()
    duracion_s: Mapped[int | None] = mapped_column(Integer)
    pasos: Mapped[int | None] = mapped_column(Integer)
    distancia_m: Mapped[float | None] = mapped_column(REAL)
    inicio_lat: Mapped[float | None] = mapped_column(Double)
    inicio_lng: Mapped[float | None] = mapped_column(Double)
    inicio_rumbo: Mapped[float | None] = mapped_column(REAL)
    total_fotos_declaradas: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("0"))
    dispositivo: Mapped[str | None] = mapped_column(Text)
    app_version: Mapped[str | None] = mapped_column(Text)
    subida_completa_en: Mapped[datetime | None] = _fecha_nula()
    creado_por: Mapped[uuid.UUID] = _usuario()
    creado_en: Mapped[datetime] = _creado_en()
    actualizado_en: Mapped[datetime] = _actualizado_en()
    eliminado_en: Mapped[datetime | None] = _fecha_nula()
    eliminado_por: Mapped[uuid.UUID | None] = _usuario(nulo=True)
    purgado_en: Mapped[datetime | None] = _fecha_nula()


# Como en la migración: la secuencia pertenece a la columna (se borra con ella).
event.listen(Video.__table__, "after_create", DDL("ALTER SEQUENCE videos_numero_seq OWNED BY videos.numero"))


class Imagen(Base):
    __tablename__ = "imagenes"
    __table_args__ = (
        UniqueConstraint("video_id", "orden"),
        UniqueConstraint("s3_key"),
        _check("orden BETWEEN 1 AND 200", "orden"),
        _check("s3_key = 'dataset/' || video_id::text || '/' || id::text || '.jpg'", "s3_key"),
        *_lat_lng(),
        _check("rumbo >= 0 AND rumbo < 360", "rumbo"),
        _check("bytes_declarados > 0", "bytes_declarados"),
        _check("bytes >= 0", "bytes"),
        _check("ancho > 0", "ancho"),
        _check("alto > 0", "alto"),
        _check("(estado = 'error') = (error IS NOT NULL)", "error"),
        _check("intentos >= 0", "intentos"),
        _check("char_length(notas) <= 500", "notas"),
        Index(None, "estado"),
        Index(None, "lugar_id"),
    )

    id: Mapped[uuid.UUID] = _id()
    video_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("videos.id", ondelete="CASCADE"), nullable=False
    )
    orden: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    s3_key: Mapped[str] = mapped_column(Text, nullable=False)
    lat: Mapped[float] = mapped_column(Double, nullable=False)
    lng: Mapped[float] = mapped_column(Double, nullable=False)
    rumbo: Mapped[float | None] = mapped_column(REAL)
    capturada_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    bytes_declarados: Mapped[int] = mapped_column(Integer, nullable=False)
    bytes: Mapped[int | None] = mapped_column(Integer)
    etag: Mapped[str | None] = mapped_column(Text)
    ancho: Mapped[int | None] = mapped_column(SmallInteger)
    alto: Mapped[int | None] = mapped_column(SmallInteger)
    estado: Mapped[EstadoImagen] = mapped_column(
        _enum(EstadoImagen, "estado_imagen"), nullable=False, server_default="pendiente_subida"
    )
    error: Mapped[str | None] = mapped_column(Text)
    intentos: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("0"))
    calidad: Mapped[CalidadImagen] = mapped_column(
        _enum(CalidadImagen, "calidad_imagen"), nullable=False, server_default="normal"
    )
    lugar_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("lugares.id", ondelete="SET NULL")
    )
    notas: Mapped[str | None] = mapped_column(Text)
    creado_en: Mapped[datetime] = _creado_en()
    actualizado_en: Mapped[datetime] = _actualizado_en()


class Embedding(Base):
    __tablename__ = "embeddings"
    __table_args__ = (
        # Índice de la versión activa (§5.7, ADR-BE-09): toda consulta vectorial filtra por la misma versión, escrita
        # como literal (sale de EMBEDDING_VERSION_VECTOR) para que el planificador use este índice parcial.
        Index(
            "embeddings_hnsw_dinov2_vits14_pp_v1",
            "vector",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"vector": "vector_cosine_ops"},
            postgresql_where=text("version_vector = 'dinov2-vits14/pp-v1'"),
        ),
    )

    imagen_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("imagenes.id", ondelete="CASCADE"), primary_key=True
    )
    version_vector: Mapped[str] = mapped_column(Text, primary_key=True)
    vector: Mapped[list[float]] = mapped_column(Vector(DIMENSION_VECTOR), nullable=False)
    creado_en: Mapped[datetime] = _creado_en()


class EventoLocalizacion(Base):
    """Evento anónimo de `/v1/localize` (ADR-BE-06): sin IP, sin identificador del dispositivo, sin fotos."""

    __tablename__ = "eventos_localizacion"
    __table_args__ = (
        _check("origen IN ('escaneo', 'frame')", "origen"),
        _check("resultado IN ('ok', 'sin_coincidencias', 'error')", "resultado"),
        _check("nivel IN ('alta', 'media', 'baja')", "nivel"),
        _check("confianza >= 0 AND confianza <= 1", "confianza"),
        _check("(lat IS NULL) = (lng IS NULL)", "posicion"),
        *_lat_lng(),
        _check("fotos_con_coincidencia >= 0 AND fotos_con_coincidencia <= fotos_usadas", "fotos"),
        _check("latencia_ms >= 0", "latencia_ms"),
        Index(None, "creado_en"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    creado_en: Mapped[datetime] = _creado_en()
    origen: Mapped[str] = mapped_column(Text, nullable=False)
    resultado: Mapped[str] = mapped_column(Text, nullable=False)
    nivel: Mapped[str | None] = mapped_column(Text)
    confianza: Mapped[float | None] = mapped_column(REAL)
    lat: Mapped[float | None] = mapped_column(Double)
    lng: Mapped[float | None] = mapped_column(Double)
    fotos_usadas: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    fotos_con_coincidencia: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    latencia_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    version_vector: Mapped[str] = mapped_column(Text, nullable=False)
    app_version: Mapped[str | None] = mapped_column(Text)


class Auditoria(Base):
    __tablename__ = "auditoria"
    __table_args__ = (_check("jsonb_typeof(detalle) = 'object'", "detalle"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    creado_en: Mapped[datetime] = _creado_en()
    actor_id: Mapped[uuid.UUID | None] = _usuario(nulo=True)  # nulo en logins fallidos
    accion: Mapped[str] = mapped_column(Text, nullable=False)
    entidad: Mapped[str] = mapped_column(Text, nullable=False)
    entidad_id: Mapped[str | None] = mapped_column(Text)
    detalle: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'"))
