"""El esquema de ARCHITECTURE §5.7 en forma comprobable, y su comparación con el catálogo de una base.

`python -m app.cli verificar-esquema` lee el catálogo (`pg_catalog`) del esquema `public` y lo compara con `ESPERADO`.
Las pruebas comprueban que la migración (`migrations/`) y los modelos (`app.db.modelos`) dejan exactamente esto, así
que una diferencia en `dev` señala una base que alguien cambió a mano o una migración que no se aplicó.

Qué se compara:
- extensiones requeridas (`vector`; las demás se ignoran: no son objetos del esquema);
- tipos enumerados (valores y orden) y cualquier otro tipo propio del esquema (sobra);
- tablas, columnas (tipo, nulo, valor por defecto, identidad o generada), restricciones (`pg_get_constraintdef`),
  índices (`pg_get_indexdef`) y secuencias (tipo y columna dueña);
- vistas, funciones y *triggers* propios del esquema (no hay ninguno: si aparecen, sobran);
- la revisión de `alembic_version`, que debe ser la última de las migraciones de la imagen.

`alembic_version` y los objetos que pertenecen a una extensión quedan fuera. Los textos de definición son los que
devuelve PostgreSQL 17 (RDS y CI): `verificar-esquema` y estas pruebas comparan textos del catálogo, no SQL escrito a
mano.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

TABLA_ALEMBIC = "alembic_version"


@dataclass(frozen=True)
class Columna:
    tipo: str
    nulo: bool = False
    defecto: str | None = None
    generada: str = ""  # `attidentity` o `attgenerated` (vacío = columna normal)


@dataclass(frozen=True)
class Diferencia:
    objeto: str
    aspecto: str
    esperado: str | None
    encontrado: str | None

    def como_campos(self) -> dict[str, Any]:
        return {
            "objeto": self.objeto,
            "aspecto": self.aspecto,
            "esperado": self.esperado,
            "encontrado": self.encontrado,
        }


@dataclass
class Catalogo:
    extensiones: dict[str, str] = field(default_factory=dict)  # nombre → versión
    tipos: dict[str, tuple[str, ...]] = field(default_factory=dict)  # enumerado → valores en orden
    otros_tipos: set[str] = field(default_factory=set)
    tablas: dict[str, dict[str, Columna]] = field(default_factory=dict)
    restricciones: dict[str, dict[str, str]] = field(default_factory=dict)  # tabla → nombre → definición
    indices: dict[str, dict[str, str]] = field(default_factory=dict)  # tabla → nombre → definición
    secuencias: dict[str, tuple[str, str | None]] = field(default_factory=dict)  # nombre → (tipo, tabla.columna)
    vistas: set[str] = field(default_factory=set)
    funciones: set[str] = field(default_factory=set)
    disparadores: set[str] = field(default_factory=set)
    revision: str | None = None
    servidor: str | None = None


# --- Lo esperado (§5.7) -------------------------------------------------------------------------------------------
def _c(tipo: str, *, nulo: bool = False, defecto: str | None = None) -> Columna:
    return Columna(tipo=tipo, nulo=nulo, defecto=defecto)


UUID_ID = _c("uuid", defecto="gen_random_uuid()")
AHORA = _c("timestamp with time zone", defecto="now()")
FECHA_NULA = _c("timestamp with time zone", nulo=True)
LAT = "CHECK (((lat >= '-90'::double precision) AND (lat <= '90'::double precision)))"
LNG = "CHECK (((lng >= '-180'::double precision) AND (lng <= '180'::double precision)))"

EXTENSIONES_REQUERIDAS = ("vector",)

ESPERADO = Catalogo(
    extensiones={nombre: "" for nombre in EXTENSIONES_REQUERIDAS},
    tipos={
        "rol_usuario": ("user", "admin"),
        "categoria_lugar": (
            "biblioteca",
            "cafeteria",
            "bano",
            "bloque",
            "auditorio",
            "deportes",
            "administracion",
            "entrada",
        ),
        "tipo_alerta": ("agua", "mobiliario", "escalones", "obra", "vehiculos", "otro"),
        "prioridad_alerta": ("normal", "alta"),
        "estado_video": ("pendiente", "procesando", "procesado", "con_errores", "eliminado"),
        "estado_imagen": ("pendiente_subida", "subida", "procesada", "error"),
        "calidad_imagen": ("alta", "normal", "baja"),
    },
    tablas={
        "usuarios": {
            "id": UUID_ID,
            "correo": _c("text"),
            "nombre": _c("text"),
            "rol": _c("rol_usuario", defecto="'user'::rol_usuario"),
            "hash_password": _c("text"),
            "activo": _c("boolean", defecto="true"),
            "creado_en": AHORA,
            "ultimo_acceso_en": FECHA_NULA,
        },
        "lugares": {
            "id": UUID_ID,
            "nombre": _c("text"),
            "nombre_normalizado": _c("text"),
            "categoria": _c("categoria_lugar"),
            "lat": _c("double precision"),
            "lng": _c("double precision"),
            "alias": _c("text[]", defecto="'{}'::text[]"),
            "descripcion": _c("text", nulo=True),
            "referencias": _c("text", nulo=True),
            "imagen_key": _c("text", nulo=True),
            "creado_en": AHORA,
            "actualizado_en": AHORA,
            "creado_por": _c("uuid"),
        },
        "alertas": {
            "id": UUID_ID,
            "lat": _c("double precision"),
            "lng": _c("double precision"),
            "mensaje": _c("text"),
            "tipo": _c("tipo_alerta", defecto="'otro'::tipo_alerta"),
            "prioridad": _c("prioridad_alerta", defecto="'normal'::prioridad_alerta"),
            "radio_m": _c("smallint", defecto="15"),
            "activa": _c("boolean", defecto="true"),
            "vigencia_desde": FECHA_NULA,
            "vigencia_hasta": FECHA_NULA,
            "version": _c("integer", defecto="1"),
            "creado_en": AHORA,
            "actualizado_en": AHORA,
            "creado_por": _c("uuid"),
            "actualizado_por": _c("uuid"),
            "eliminada_en": FECHA_NULA,
        },
        "videos": {
            "id": UUID_ID,
            "numero": _c("integer", defecto="nextval('videos_numero_seq'::regclass)"),
            "nombre": _c("text"),
            "ref_cliente": _c("text"),
            "estado": _c("estado_video", defecto="'pendiente'::estado_video"),
            "iniciado_en": FECHA_NULA,
            "finalizado_en": FECHA_NULA,
            "duracion_s": _c("integer", nulo=True),
            "pasos": _c("integer", nulo=True),
            "distancia_m": _c("real", nulo=True),
            "inicio_lat": _c("double precision", nulo=True),
            "inicio_lng": _c("double precision", nulo=True),
            "inicio_rumbo": _c("real", nulo=True),
            "total_fotos_declaradas": _c("smallint", defecto="0"),
            "dispositivo": _c("text", nulo=True),
            "app_version": _c("text", nulo=True),
            "subida_completa_en": FECHA_NULA,
            "creado_por": _c("uuid"),
            "creado_en": AHORA,
            "actualizado_en": AHORA,
            "eliminado_en": FECHA_NULA,
            "eliminado_por": _c("uuid", nulo=True),
            "purgado_en": FECHA_NULA,
        },
        "imagenes": {
            "id": UUID_ID,
            "video_id": _c("uuid"),
            "orden": _c("smallint"),
            "s3_key": _c("text"),
            "lat": _c("double precision"),
            "lng": _c("double precision"),
            "rumbo": _c("real", nulo=True),
            "capturada_en": _c("timestamp with time zone"),
            "bytes_declarados": _c("integer"),
            "bytes": _c("integer", nulo=True),
            "etag": _c("text", nulo=True),
            "ancho": _c("smallint", nulo=True),
            "alto": _c("smallint", nulo=True),
            "estado": _c("estado_imagen", defecto="'pendiente_subida'::estado_imagen"),
            "error": _c("text", nulo=True),
            "intentos": _c("smallint", defecto="0"),
            "calidad": _c("calidad_imagen", defecto="'normal'::calidad_imagen"),
            "lugar_id": _c("uuid", nulo=True),
            "notas": _c("text", nulo=True),
            "creado_en": AHORA,
            "actualizado_en": AHORA,
        },
        "embeddings": {
            "imagen_id": _c("uuid"),
            "version_vector": _c("text"),
            "vector": _c("vector(384)"),
            "creado_en": AHORA,
        },
        "eventos_localizacion": {
            "id": _c("bigint", defecto="nextval('eventos_localizacion_id_seq'::regclass)"),
            "creado_en": AHORA,
            "origen": _c("text"),
            "resultado": _c("text"),
            "nivel": _c("text", nulo=True),
            "confianza": _c("real", nulo=True),
            "lat": _c("double precision", nulo=True),
            "lng": _c("double precision", nulo=True),
            "fotos_usadas": _c("smallint"),
            "fotos_con_coincidencia": _c("smallint"),
            "latencia_ms": _c("integer"),
            "version_vector": _c("text"),
            "app_version": _c("text", nulo=True),
        },
        "auditoria": {
            "id": _c("bigint", defecto="nextval('auditoria_id_seq'::regclass)"),
            "creado_en": AHORA,
            "actor_id": _c("uuid", nulo=True),
            "accion": _c("text"),
            "entidad": _c("text"),
            "entidad_id": _c("text", nulo=True),
            "detalle": _c("jsonb", defecto="'{}'::jsonb"),
        },
    },
    restricciones={
        "usuarios": {
            "usuarios_pkey": "PRIMARY KEY (id)",
            "usuarios_correo_key": "UNIQUE (correo)",
            "usuarios_correo_check": "CHECK (((correo = lower(btrim(correo))) AND (correo <> ''::text)))",
            "usuarios_nombre_check": "CHECK ((btrim(nombre) <> ''::text))",
        },
        "lugares": {
            "lugares_pkey": "PRIMARY KEY (id)",
            "lugares_nombre_normalizado_key": "UNIQUE (nombre_normalizado)",
            "lugares_creado_por_fkey": "FOREIGN KEY (creado_por) REFERENCES usuarios(id)",
            "lugares_nombre_check": "CHECK (((char_length(nombre) >= 2) AND (char_length(nombre) <= 80)))",
            "lugares_lat_check": LAT,
            "lugares_lng_check": LNG,
            "lugares_descripcion_check": "CHECK ((char_length(descripcion) <= 300))",
            "lugares_referencias_check": "CHECK ((char_length(referencias) <= 300))",
            "lugares_imagen_key_check": "CHECK ((imagen_key = (('lugares/'::text || (id)::text) || '.jpg'::text)))",
        },
        "alertas": {
            "alertas_pkey": "PRIMARY KEY (id)",
            "alertas_creado_por_fkey": "FOREIGN KEY (creado_por) REFERENCES usuarios(id)",
            "alertas_actualizado_por_fkey": "FOREIGN KEY (actualizado_por) REFERENCES usuarios(id)",
            "alertas_lat_check": LAT,
            "alertas_lng_check": LNG,
            "alertas_mensaje_check": "CHECK (((char_length(mensaje) >= 1) AND (char_length(mensaje) <= 200)))",
            "alertas_radio_m_check": "CHECK (((radio_m >= 5) AND (radio_m <= 100)))",
            "alertas_vigencia_check": "CHECK ((vigencia_hasta > vigencia_desde))",
            "alertas_version_check": "CHECK ((version >= 1))",
        },
        "videos": {
            "videos_pkey": "PRIMARY KEY (id)",
            "videos_numero_key": "UNIQUE (numero)",
            "videos_creado_por_ref_cliente_key": "UNIQUE (creado_por, ref_cliente)",
            "videos_creado_por_fkey": "FOREIGN KEY (creado_por) REFERENCES usuarios(id)",
            "videos_eliminado_por_fkey": "FOREIGN KEY (eliminado_por) REFERENCES usuarios(id)",
            "videos_nombre_check": "CHECK (((char_length(nombre) >= 1) AND (char_length(nombre) <= 40)))",
            "videos_ref_cliente_check": (
                "CHECK (((char_length(ref_cliente) >= 1) AND (char_length(ref_cliente) <= 40)))"
            ),
            "videos_duracion_s_check": "CHECK ((duracion_s >= 0))",
            "videos_pasos_check": "CHECK ((pasos >= 0))",
            "videos_distancia_m_check": "CHECK ((distancia_m >= (0)::double precision))",
            "videos_inicio_check": "CHECK (((inicio_lat IS NULL) = (inicio_lng IS NULL)))",
            "videos_inicio_lat_check": (
                "CHECK (((inicio_lat >= '-90'::double precision) AND (inicio_lat <= '90'::double precision)))"
            ),
            "videos_inicio_lng_check": (
                "CHECK (((inicio_lng >= '-180'::double precision) AND (inicio_lng <= '180'::double precision)))"
            ),
            "videos_inicio_rumbo_check": (
                "CHECK (((inicio_rumbo >= (0)::double precision) AND (inicio_rumbo < (360)::double precision)))"
            ),
            "videos_total_fotos_declaradas_check": (
                "CHECK (((total_fotos_declaradas >= 0) AND (total_fotos_declaradas <= 200)))"
            ),
            "videos_eliminado_check": (
                "CHECK ((((estado = 'eliminado'::estado_video) = (eliminado_en IS NOT NULL)) "
                "AND ((eliminado_en IS NULL) = (eliminado_por IS NULL))))"
            ),
            "videos_purgado_en_check": "CHECK (((purgado_en IS NULL) OR (eliminado_en IS NOT NULL)))",
        },
        "imagenes": {
            "imagenes_pkey": "PRIMARY KEY (id)",
            "imagenes_video_id_orden_key": "UNIQUE (video_id, orden)",
            "imagenes_s3_key_key": "UNIQUE (s3_key)",
            "imagenes_video_id_fkey": "FOREIGN KEY (video_id) REFERENCES videos(id) ON DELETE CASCADE",
            "imagenes_lugar_id_fkey": "FOREIGN KEY (lugar_id) REFERENCES lugares(id) ON DELETE SET NULL",
            "imagenes_orden_check": "CHECK (((orden >= 1) AND (orden <= 200)))",
            "imagenes_s3_key_check": (
                "CHECK ((s3_key = (((('dataset/'::text || (video_id)::text) || '/'::text) || (id)::text) "
                "|| '.jpg'::text)))"
            ),
            "imagenes_lat_check": LAT,
            "imagenes_lng_check": LNG,
            "imagenes_rumbo_check": "CHECK (((rumbo >= (0)::double precision) AND (rumbo < (360)::double precision)))",
            "imagenes_bytes_declarados_check": "CHECK ((bytes_declarados > 0))",
            "imagenes_bytes_check": "CHECK ((bytes >= 0))",
            "imagenes_ancho_check": "CHECK ((ancho > 0))",
            "imagenes_alto_check": "CHECK ((alto > 0))",
            "imagenes_error_check": "CHECK (((estado = 'error'::estado_imagen) = (error IS NOT NULL)))",
            "imagenes_intentos_check": "CHECK ((intentos >= 0))",
            "imagenes_notas_check": "CHECK ((char_length(notas) <= 500))",
        },
        "embeddings": {
            "embeddings_pkey": "PRIMARY KEY (imagen_id, version_vector)",
            "embeddings_imagen_id_fkey": "FOREIGN KEY (imagen_id) REFERENCES imagenes(id) ON DELETE CASCADE",
        },
        "eventos_localizacion": {
            "eventos_localizacion_pkey": "PRIMARY KEY (id)",
            "eventos_localizacion_origen_check": "CHECK ((origen = ANY (ARRAY['escaneo'::text, 'frame'::text])))",
            "eventos_localizacion_resultado_check": (
                "CHECK ((resultado = ANY (ARRAY['ok'::text, 'sin_coincidencias'::text, 'error'::text])))"
            ),
            "eventos_localizacion_nivel_check": (
                "CHECK ((nivel = ANY (ARRAY['alta'::text, 'media'::text, 'baja'::text])))"
            ),
            "eventos_localizacion_confianza_check": (
                "CHECK (((confianza >= (0)::double precision) AND (confianza <= (1)::double precision)))"
            ),
            "eventos_localizacion_posicion_check": "CHECK (((lat IS NULL) = (lng IS NULL)))",
            "eventos_localizacion_lat_check": LAT,
            "eventos_localizacion_lng_check": LNG,
            "eventos_localizacion_fotos_check": (
                "CHECK (((fotos_con_coincidencia >= 0) AND (fotos_con_coincidencia <= fotos_usadas)))"
            ),
            "eventos_localizacion_latencia_ms_check": "CHECK ((latencia_ms >= 0))",
        },
        "auditoria": {
            "auditoria_pkey": "PRIMARY KEY (id)",
            "auditoria_actor_id_fkey": "FOREIGN KEY (actor_id) REFERENCES usuarios(id)",
            "auditoria_detalle_check": "CHECK ((jsonb_typeof(detalle) = 'object'::text))",
        },
    },
    indices={
        "alertas": {
            "alertas_actualizado_en_idx": (
                "CREATE INDEX alertas_actualizado_en_idx ON public.alertas USING btree (actualizado_en)"
            ),
        },
        "imagenes": {
            "imagenes_estado_idx": "CREATE INDEX imagenes_estado_idx ON public.imagenes USING btree (estado)",
            "imagenes_lugar_id_idx": "CREATE INDEX imagenes_lugar_id_idx ON public.imagenes USING btree (lugar_id)",
        },
        "embeddings": {
            "embeddings_hnsw_dinov2_vits14_pp_v1": (
                "CREATE INDEX embeddings_hnsw_dinov2_vits14_pp_v1 ON public.embeddings USING hnsw "
                "(vector vector_cosine_ops) WITH (m='16', ef_construction='64') "
                "WHERE (version_vector = 'dinov2-vits14/pp-v1'::text)"
            ),
        },
        "eventos_localizacion": {
            "eventos_localizacion_creado_en_idx": (
                "CREATE INDEX eventos_localizacion_creado_en_idx ON public.eventos_localizacion USING btree (creado_en)"
            ),
        },
    },
    secuencias={
        "videos_numero_seq": ("integer", "videos.numero"),
        "eventos_localizacion_id_seq": ("bigint", "eventos_localizacion.id"),
        "auditoria_id_seq": ("bigint", "auditoria.id"),
    },
)


# --- Lectura del catálogo -----------------------------------------------------------------------------------------
# Los objetos que pertenecen a una extensión (tipos y funciones de `vector`) tienen una dependencia `deptype = 'e'`.
_SQL = {
    "extensiones": "SELECT extname, extversion FROM pg_extension",
    "tipos": """
        SELECT t.typname, array_agg(e.enumlabel::text ORDER BY e.enumsortorder)
        FROM pg_type t JOIN pg_enum e ON e.enumtypid = t.oid
        WHERE t.typnamespace = 'public'::regnamespace
        GROUP BY t.typname
    """,
    "otros_tipos": """
        SELECT t.typname
        FROM pg_type t LEFT JOIN pg_class c ON c.oid = t.typrelid
        WHERE t.typnamespace = 'public'::regnamespace
          AND t.typtype <> 'e' AND t.typcategory <> 'A'
          AND (t.typrelid = 0 OR c.relkind = 'c')
          AND NOT EXISTS (SELECT 1 FROM pg_depend d
                          WHERE d.classid = 'pg_type'::regclass AND d.objid = t.oid AND d.deptype = 'e')
    """,
    "relaciones": """
        SELECT c.relname, c.relkind::text
        FROM pg_class c
        WHERE c.relnamespace = 'public'::regnamespace AND c.relkind IN ('r', 'p', 'v', 'm', 'f')
          AND NOT EXISTS (SELECT 1 FROM pg_depend d
                          WHERE d.classid = 'pg_class'::regclass AND d.objid = c.oid AND d.deptype = 'e')
    """,
    "columnas": """
        SELECT c.relname, a.attname, format_type(a.atttypid, a.atttypmod), a.attnotnull,
               pg_get_expr(d.adbin, d.adrelid), a.attidentity::text || a.attgenerated::text
        FROM pg_attribute a
        JOIN pg_class c ON c.oid = a.attrelid
        LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum
        WHERE c.relnamespace = 'public'::regnamespace AND c.relkind IN ('r', 'p')
          AND a.attnum > 0 AND NOT a.attisdropped
    """,
    "restricciones": """
        SELECT c.relname, k.conname, pg_get_constraintdef(k.oid)
        FROM pg_constraint k JOIN pg_class c ON c.oid = k.conrelid
        WHERE c.relnamespace = 'public'::regnamespace AND k.contype IN ('p', 'u', 'f', 'c', 'x', 't')
    """,
    "indices": """
        SELECT t.relname, i.relname, pg_get_indexdef(i.oid)
        FROM pg_index x
        JOIN pg_class i ON i.oid = x.indexrelid
        JOIN pg_class t ON t.oid = x.indrelid
        WHERE t.relnamespace = 'public'::regnamespace
          AND NOT EXISTS (SELECT 1 FROM pg_constraint k
                          WHERE k.conindid = x.indexrelid AND k.contype IN ('p', 'u', 'x'))
    """,
    "secuencias": """
        SELECT c.relname, format_type(s.seqtypid, NULL),
               (SELECT t.relname || '.' || a.attname
                FROM pg_depend d
                JOIN pg_class t ON t.oid = d.refobjid
                JOIN pg_attribute a ON a.attrelid = d.refobjid AND a.attnum = d.refobjsubid
                WHERE d.classid = 'pg_class'::regclass AND d.objid = c.oid
                  AND d.refclassid = 'pg_class'::regclass AND d.refobjsubid > 0 AND d.deptype IN ('a', 'i')
                LIMIT 1)
        FROM pg_class c JOIN pg_sequence s ON s.seqrelid = c.oid
        WHERE c.relnamespace = 'public'::regnamespace
    """,
    "funciones": """
        SELECT p.proname || '(' || pg_get_function_identity_arguments(p.oid) || ')'
        FROM pg_proc p
        WHERE p.pronamespace = 'public'::regnamespace
          AND NOT EXISTS (SELECT 1 FROM pg_depend d
                          WHERE d.classid = 'pg_proc'::regclass AND d.objid = p.oid AND d.deptype = 'e')
    """,
    "disparadores": """
        SELECT c.relname || '.' || g.tgname
        FROM pg_trigger g JOIN pg_class c ON c.oid = g.tgrelid
        WHERE c.relnamespace = 'public'::regnamespace AND NOT g.tgisinternal
    """,
}


async def leer_revision(conexion: AsyncConnection) -> str | None:
    """Revisión de `alembic_version` (`None` en una base sin migrar; varias cabezas, separadas por comas)."""
    if (await conexion.execute(text("SELECT to_regclass('public.alembic_version')"))).scalar() is None:
        return None
    versiones = (await conexion.execute(text("SELECT version_num FROM alembic_version"))).scalars().all()
    return ",".join(sorted(versiones)) or None


async def _filas(conexion: AsyncConnection, clave: str) -> list[tuple[Any, ...]]:
    resultado = await conexion.execute(text(_SQL[clave]))
    return [tuple(fila) for fila in resultado.all()]


async def leer_catalogo(conexion: AsyncConnection) -> Catalogo:
    """Lee el esquema `public` de la base (solo consultas al catálogo: no modifica nada)."""
    cat = Catalogo()
    cat.servidor = (await conexion.execute(text("SHOW server_version"))).scalar_one()
    cat.extensiones = {nombre: version for nombre, version in await _filas(conexion, "extensiones")}
    cat.tipos = {nombre: tuple(valores) for nombre, valores in await _filas(conexion, "tipos")}
    cat.otros_tipos = {nombre for (nombre,) in await _filas(conexion, "otros_tipos")}
    for nombre, tipo in await _filas(conexion, "relaciones"):
        if nombre == TABLA_ALEMBIC:
            continue
        if tipo in ("r", "p"):
            cat.tablas.setdefault(nombre, {})
        else:
            cat.vistas.add(nombre)
    for tabla, columna, tipo, no_nulo, defecto, generada in await _filas(conexion, "columnas"):
        if tabla in cat.tablas:
            cat.tablas[tabla][columna] = Columna(tipo=tipo, nulo=not no_nulo, defecto=defecto, generada=generada)
    for tabla, nombre, definicion in await _filas(conexion, "restricciones"):
        if tabla != TABLA_ALEMBIC:
            cat.restricciones.setdefault(tabla, {})[nombre] = definicion
    for tabla, nombre, definicion in await _filas(conexion, "indices"):
        if tabla != TABLA_ALEMBIC:
            cat.indices.setdefault(tabla, {})[nombre] = definicion
    for nombre, tipo, duena in await _filas(conexion, "secuencias"):
        cat.secuencias[nombre] = (tipo, duena)
    cat.funciones = {firma for (firma,) in await _filas(conexion, "funciones")}
    cat.disparadores = {nombre for (nombre,) in await _filas(conexion, "disparadores")}
    cat.revision = await leer_revision(conexion)
    return cat


# --- Comparación --------------------------------------------------------------------------------------------------
def _texto_nulo(nulo: bool) -> str:
    return "nulo" if nulo else "NOT NULL"


def _comparar_nombres(
    objeto: Callable[[str], str], esperados: Mapping[str, Any], encontrados: Mapping[str, Any]
) -> tuple[list[Diferencia], list[str]]:
    """Faltan y sobran por nombre; devuelve también los nombres presentes en ambos (ordenados)."""
    diferencias = [Diferencia(objeto(n), "falta", n, None) for n in sorted(set(esperados) - set(encontrados))]
    diferencias += [Diferencia(objeto(n), "sobra", None, n) for n in sorted(set(encontrados) - set(esperados))]
    return diferencias, sorted(set(esperados) & set(encontrados))


def _prefijo(clase: str) -> Callable[[str], str]:
    return lambda nombre: f"{clase} {nombre}"


def _comparar_definiciones(
    clase: str, esperadas: Mapping[str, str], encontradas: Mapping[str, str]
) -> list[Diferencia]:
    diferencias, comunes = _comparar_nombres(_prefijo(clase), esperadas, encontradas)
    for nombre in comunes:
        if esperadas[nombre] != encontradas[nombre]:
            diferencias.append(Diferencia(f"{clase} {nombre}", "definicion", esperadas[nombre], encontradas[nombre]))
    return diferencias


def comparar(esperado: Catalogo, encontrado: Catalogo, *, revision: str | None) -> list[Diferencia]:
    """Diferencias entre lo esperado y el catálogo leído. `revision=None` no comprueba `alembic_version`."""
    diferencias: list[Diferencia] = []

    for nombre in sorted(set(esperado.extensiones) - set(encontrado.extensiones)):
        diferencias.append(Diferencia(f"extensión {nombre}", "falta", nombre, None))

    nuevas, comunes = _comparar_nombres(_prefijo("tipo"), esperado.tipos, encontrado.tipos)
    diferencias += nuevas
    for nombre in comunes:
        if esperado.tipos[nombre] != encontrado.tipos[nombre]:
            diferencias.append(
                Diferencia(
                    f"tipo {nombre}", "valores", ", ".join(esperado.tipos[nombre]), ", ".join(encontrado.tipos[nombre])
                )
            )
    diferencias += [Diferencia(f"tipo {n}", "sobra", None, n) for n in sorted(encontrado.otros_tipos)]

    nuevas, tablas = _comparar_nombres(_prefijo("tabla"), esperado.tablas, encontrado.tablas)
    diferencias += nuevas
    for tabla in tablas:
        nuevas, columnas = _comparar_nombres(
            lambda columna, tabla=tabla: f"columna {tabla}.{columna}", esperado.tablas[tabla], encontrado.tablas[tabla]
        )
        diferencias += nuevas
        for columna in columnas:
            esp, enc = esperado.tablas[tabla][columna], encontrado.tablas[tabla][columna]
            objeto = f"columna {tabla}.{columna}"
            if esp.tipo != enc.tipo:
                diferencias.append(Diferencia(objeto, "tipo", esp.tipo, enc.tipo))
            if esp.nulo != enc.nulo:
                diferencias.append(Diferencia(objeto, "nulo", _texto_nulo(esp.nulo), _texto_nulo(enc.nulo)))
            if esp.defecto != enc.defecto:
                diferencias.append(Diferencia(objeto, "defecto", esp.defecto, enc.defecto))
            if esp.generada != enc.generada:
                diferencias.append(Diferencia(objeto, "generada", esp.generada or None, enc.generada or None))
        diferencias += _comparar_definiciones(
            "restricción", esperado.restricciones.get(tabla, {}), encontrado.restricciones.get(tabla, {})
        )
        diferencias += _comparar_definiciones(
            "índice", esperado.indices.get(tabla, {}), encontrado.indices.get(tabla, {})
        )
    # Restricciones e índices de tablas que sobran ya quedan cubiertos por «tabla … sobra».

    nuevas, secuencias = _comparar_nombres(_prefijo("secuencia"), esperado.secuencias, encontrado.secuencias)
    diferencias += nuevas
    for nombre in secuencias:
        (tipo_e, duena_e), (tipo_f, duena_f) = esperado.secuencias[nombre], encontrado.secuencias[nombre]
        if tipo_e != tipo_f:
            diferencias.append(Diferencia(f"secuencia {nombre}", "tipo", tipo_e, tipo_f))
        if duena_e != duena_f:
            diferencias.append(Diferencia(f"secuencia {nombre}", "propietaria", duena_e, duena_f))

    diferencias += [Diferencia(f"vista {n}", "sobra", None, n) for n in sorted(encontrado.vistas)]
    diferencias += [Diferencia(f"función {n}", "sobra", None, n) for n in sorted(encontrado.funciones)]
    diferencias += [Diferencia(f"trigger {n}", "sobra", None, n) for n in sorted(encontrado.disparadores)]

    if revision is not None and encontrado.revision != revision:
        diferencias.append(Diferencia(f"tabla {TABLA_ALEMBIC}", "revision", revision, encontrado.revision))
    return diferencias
