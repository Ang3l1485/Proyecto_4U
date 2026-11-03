"""Esquema inicial (BE-1.2): extensión `vector`, tipos enumerados, tablas, índices y el índice HNSW parcial.

Contrato: BACKEND_FASTAPI/docs/ARCHITECTURE.md §5.7. `python -m app.cli verificar-esquema` compara la base con
`app/db/esquema.py`, que describe exactamente lo que deja esta migración.

Revision ID: 0001
Revises: —
"""

from __future__ import annotations

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

# Una sentencia por elemento: el driver (asyncpg) prepara cada sentencia y no admite varias juntas.
SUBIR = [
    "CREATE EXTENSION IF NOT EXISTS vector",
    # --- Tipos enumerados -------------------------------------------------------------------------------------
    "CREATE TYPE rol_usuario AS ENUM ('user', 'admin')",
    "CREATE TYPE categoria_lugar AS ENUM "
    "('biblioteca', 'cafeteria', 'bano', 'bloque', 'auditorio', 'deportes', 'administracion', 'entrada')",
    "CREATE TYPE tipo_alerta AS ENUM ('agua', 'mobiliario', 'escalones', 'obra', 'vehiculos', 'otro')",
    "CREATE TYPE prioridad_alerta AS ENUM ('normal', 'alta')",
    "CREATE TYPE estado_video AS ENUM ('pendiente', 'procesando', 'procesado', 'con_errores', 'eliminado')",
    "CREATE TYPE estado_imagen AS ENUM ('pendiente_subida', 'subida', 'procesada', 'error')",
    "CREATE TYPE calidad_imagen AS ENUM ('alta', 'normal', 'baja')",
    # --- usuarios ---------------------------------------------------------------------------------------------
    """
    CREATE TABLE usuarios (
        id               uuid        NOT NULL DEFAULT gen_random_uuid(),
        correo           text        NOT NULL,
        nombre           text        NOT NULL,
        rol              rol_usuario NOT NULL DEFAULT 'user',
        hash_password    text        NOT NULL,
        activo           boolean     NOT NULL DEFAULT true,
        creado_en        timestamptz NOT NULL DEFAULT now(),
        ultimo_acceso_en timestamptz,
        CONSTRAINT usuarios_pkey PRIMARY KEY (id),
        CONSTRAINT usuarios_correo_key UNIQUE (correo),
        CONSTRAINT usuarios_correo_check CHECK (correo = lower(btrim(correo)) AND correo <> ''),
        CONSTRAINT usuarios_nombre_check CHECK (btrim(nombre) <> '')
    )
    """,
    # --- lugares ----------------------------------------------------------------------------------------------
    """
    CREATE TABLE lugares (
        id                 uuid             NOT NULL DEFAULT gen_random_uuid(),
        nombre             text             NOT NULL,
        nombre_normalizado text             NOT NULL,
        categoria          categoria_lugar  NOT NULL,
        lat                double precision NOT NULL,
        lng                double precision NOT NULL,
        alias              text[]           NOT NULL DEFAULT '{}',
        descripcion        text,
        referencias        text,
        imagen_key         text,
        creado_en          timestamptz      NOT NULL DEFAULT now(),
        actualizado_en     timestamptz      NOT NULL DEFAULT now(),
        creado_por         uuid             NOT NULL,
        CONSTRAINT lugares_pkey PRIMARY KEY (id),
        CONSTRAINT lugares_nombre_normalizado_key UNIQUE (nombre_normalizado),
        CONSTRAINT lugares_creado_por_fkey FOREIGN KEY (creado_por) REFERENCES usuarios (id),
        CONSTRAINT lugares_nombre_check CHECK (char_length(nombre) BETWEEN 2 AND 80),
        CONSTRAINT lugares_lat_check CHECK (lat BETWEEN '-90' AND '90'),
        CONSTRAINT lugares_lng_check CHECK (lng BETWEEN '-180' AND '180'),
        CONSTRAINT lugares_descripcion_check CHECK (char_length(descripcion) <= 300),
        CONSTRAINT lugares_referencias_check CHECK (char_length(referencias) <= 300),
        CONSTRAINT lugares_imagen_key_check CHECK (imagen_key = 'lugares/' || id::text || '.jpg')
    )
    """,
    # --- alertas ----------------------------------------------------------------------------------------------
    """
    CREATE TABLE alertas (
        id              uuid             NOT NULL DEFAULT gen_random_uuid(),
        lat             double precision NOT NULL,
        lng             double precision NOT NULL,
        mensaje         text             NOT NULL,
        tipo            tipo_alerta      NOT NULL DEFAULT 'otro',
        prioridad       prioridad_alerta NOT NULL DEFAULT 'normal',
        radio_m         smallint         NOT NULL DEFAULT 15,
        activa          boolean          NOT NULL DEFAULT true,
        vigencia_desde  timestamptz,
        vigencia_hasta  timestamptz,
        version         integer          NOT NULL DEFAULT 1,
        creado_en       timestamptz      NOT NULL DEFAULT now(),
        actualizado_en  timestamptz      NOT NULL DEFAULT now(),
        creado_por      uuid             NOT NULL,
        actualizado_por uuid             NOT NULL,
        eliminada_en    timestamptz,
        CONSTRAINT alertas_pkey PRIMARY KEY (id),
        CONSTRAINT alertas_creado_por_fkey FOREIGN KEY (creado_por) REFERENCES usuarios (id),
        CONSTRAINT alertas_actualizado_por_fkey FOREIGN KEY (actualizado_por) REFERENCES usuarios (id),
        CONSTRAINT alertas_lat_check CHECK (lat BETWEEN '-90' AND '90'),
        CONSTRAINT alertas_lng_check CHECK (lng BETWEEN '-180' AND '180'),
        CONSTRAINT alertas_mensaje_check CHECK (char_length(mensaje) BETWEEN 1 AND 200),
        CONSTRAINT alertas_radio_m_check CHECK (radio_m BETWEEN 5 AND 100),
        CONSTRAINT alertas_vigencia_check CHECK (vigencia_hasta > vigencia_desde),
        CONSTRAINT alertas_version_check CHECK (version >= 1)
    )
    """,
    "CREATE INDEX alertas_actualizado_en_idx ON alertas (actualizado_en)",
    # --- videos -----------------------------------------------------------------------------------------------
    "CREATE SEQUENCE videos_numero_seq AS integer",
    """
    CREATE TABLE videos (
        id                     uuid             NOT NULL DEFAULT gen_random_uuid(),
        numero                 integer          NOT NULL DEFAULT nextval('videos_numero_seq'),
        nombre                 text             NOT NULL,
        ref_cliente            text             NOT NULL,
        estado                 estado_video     NOT NULL DEFAULT 'pendiente',
        iniciado_en            timestamptz,
        finalizado_en          timestamptz,
        duracion_s             integer,
        pasos                  integer,
        distancia_m            real,
        inicio_lat             double precision,
        inicio_lng             double precision,
        inicio_rumbo           real,
        total_fotos_declaradas smallint         NOT NULL DEFAULT 0,
        dispositivo            text,
        app_version            text,
        subida_completa_en     timestamptz,
        creado_por             uuid             NOT NULL,
        creado_en              timestamptz      NOT NULL DEFAULT now(),
        actualizado_en         timestamptz      NOT NULL DEFAULT now(),
        eliminado_en           timestamptz,
        eliminado_por          uuid,
        purgado_en             timestamptz,
        CONSTRAINT videos_pkey PRIMARY KEY (id),
        CONSTRAINT videos_numero_key UNIQUE (numero),
        CONSTRAINT videos_creado_por_ref_cliente_key UNIQUE (creado_por, ref_cliente),
        CONSTRAINT videos_creado_por_fkey FOREIGN KEY (creado_por) REFERENCES usuarios (id),
        CONSTRAINT videos_eliminado_por_fkey FOREIGN KEY (eliminado_por) REFERENCES usuarios (id),
        CONSTRAINT videos_nombre_check CHECK (char_length(nombre) BETWEEN 1 AND 40),
        CONSTRAINT videos_ref_cliente_check CHECK (char_length(ref_cliente) BETWEEN 1 AND 40),
        CONSTRAINT videos_duracion_s_check CHECK (duracion_s >= 0),
        CONSTRAINT videos_pasos_check CHECK (pasos >= 0),
        CONSTRAINT videos_distancia_m_check CHECK (distancia_m >= 0),
        CONSTRAINT videos_inicio_check CHECK ((inicio_lat IS NULL) = (inicio_lng IS NULL)),
        CONSTRAINT videos_inicio_lat_check CHECK (inicio_lat BETWEEN '-90' AND '90'),
        CONSTRAINT videos_inicio_lng_check CHECK (inicio_lng BETWEEN '-180' AND '180'),
        CONSTRAINT videos_inicio_rumbo_check CHECK (inicio_rumbo >= 0 AND inicio_rumbo < 360),
        CONSTRAINT videos_total_fotos_declaradas_check CHECK (total_fotos_declaradas BETWEEN 0 AND 200),
        CONSTRAINT videos_eliminado_check CHECK (
            (estado = 'eliminado') = (eliminado_en IS NOT NULL) AND (eliminado_en IS NULL) = (eliminado_por IS NULL)
        ),
        CONSTRAINT videos_purgado_en_check CHECK (purgado_en IS NULL OR eliminado_en IS NOT NULL)
    )
    """,
    "ALTER SEQUENCE videos_numero_seq OWNED BY videos.numero",
    # --- imagenes ---------------------------------------------------------------------------------------------
    """
    CREATE TABLE imagenes (
        id               uuid             NOT NULL DEFAULT gen_random_uuid(),
        video_id         uuid             NOT NULL,
        orden            smallint         NOT NULL,
        s3_key           text             NOT NULL,
        lat              double precision NOT NULL,
        lng              double precision NOT NULL,
        rumbo            real,
        capturada_en     timestamptz      NOT NULL,
        bytes_declarados integer          NOT NULL,
        bytes            integer,
        etag             text,
        ancho            smallint,
        alto             smallint,
        estado           estado_imagen    NOT NULL DEFAULT 'pendiente_subida',
        error            text,
        intentos         smallint         NOT NULL DEFAULT 0,
        calidad          calidad_imagen   NOT NULL DEFAULT 'normal',
        lugar_id         uuid,
        notas            text,
        creado_en        timestamptz      NOT NULL DEFAULT now(),
        actualizado_en   timestamptz      NOT NULL DEFAULT now(),
        CONSTRAINT imagenes_pkey PRIMARY KEY (id),
        CONSTRAINT imagenes_video_id_orden_key UNIQUE (video_id, orden),
        CONSTRAINT imagenes_s3_key_key UNIQUE (s3_key),
        CONSTRAINT imagenes_video_id_fkey FOREIGN KEY (video_id) REFERENCES videos (id) ON DELETE CASCADE,
        CONSTRAINT imagenes_lugar_id_fkey FOREIGN KEY (lugar_id) REFERENCES lugares (id) ON DELETE SET NULL,
        CONSTRAINT imagenes_orden_check CHECK (orden BETWEEN 1 AND 200),
        CONSTRAINT imagenes_s3_key_check CHECK (s3_key = 'dataset/' || video_id::text || '/' || id::text || '.jpg'),
        CONSTRAINT imagenes_lat_check CHECK (lat BETWEEN '-90' AND '90'),
        CONSTRAINT imagenes_lng_check CHECK (lng BETWEEN '-180' AND '180'),
        CONSTRAINT imagenes_rumbo_check CHECK (rumbo >= 0 AND rumbo < 360),
        CONSTRAINT imagenes_bytes_declarados_check CHECK (bytes_declarados > 0),
        CONSTRAINT imagenes_bytes_check CHECK (bytes >= 0),
        CONSTRAINT imagenes_ancho_check CHECK (ancho > 0),
        CONSTRAINT imagenes_alto_check CHECK (alto > 0),
        CONSTRAINT imagenes_error_check CHECK ((estado = 'error') = (error IS NOT NULL)),
        CONSTRAINT imagenes_intentos_check CHECK (intentos >= 0),
        CONSTRAINT imagenes_notas_check CHECK (char_length(notas) <= 500)
    )
    """,
    "CREATE INDEX imagenes_estado_idx ON imagenes (estado)",
    "CREATE INDEX imagenes_lugar_id_idx ON imagenes (lugar_id)",
    # --- embeddings -------------------------------------------------------------------------------------------
    """
    CREATE TABLE embeddings (
        imagen_id      uuid        NOT NULL,
        version_vector text        NOT NULL,
        vector         vector(384) NOT NULL,
        creado_en      timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT embeddings_pkey PRIMARY KEY (imagen_id, version_vector),
        CONSTRAINT embeddings_imagen_id_fkey FOREIGN KEY (imagen_id) REFERENCES imagenes (id) ON DELETE CASCADE
    )
    """,
    # Índice de la versión activa (§5.7, ADR-BE-09). Una versión nueva del modelo llega con su propia migración.
    """
    CREATE INDEX embeddings_hnsw_dinov2_vits14_pp_v1 ON embeddings
        USING hnsw (vector vector_cosine_ops) WITH (m = 16, ef_construction = 64)
        WHERE version_vector = 'dinov2-vits14/pp-v1'
    """,
    # --- eventos_localizacion ---------------------------------------------------------------------------------
    """
    CREATE TABLE eventos_localizacion (
        id                     bigserial,
        creado_en              timestamptz      NOT NULL DEFAULT now(),
        origen                 text             NOT NULL,
        resultado              text             NOT NULL,
        nivel                  text,
        confianza              real,
        lat                    double precision,
        lng                    double precision,
        fotos_usadas           smallint         NOT NULL,
        fotos_con_coincidencia smallint         NOT NULL,
        latencia_ms            integer          NOT NULL,
        version_vector         text             NOT NULL,
        app_version            text,
        CONSTRAINT eventos_localizacion_pkey PRIMARY KEY (id),
        CONSTRAINT eventos_localizacion_origen_check CHECK (origen IN ('escaneo', 'frame')),
        CONSTRAINT eventos_localizacion_resultado_check CHECK (resultado IN ('ok', 'sin_coincidencias', 'error')),
        CONSTRAINT eventos_localizacion_nivel_check CHECK (nivel IN ('alta', 'media', 'baja')),
        CONSTRAINT eventos_localizacion_confianza_check CHECK (confianza >= 0 AND confianza <= 1),
        CONSTRAINT eventos_localizacion_posicion_check CHECK ((lat IS NULL) = (lng IS NULL)),
        CONSTRAINT eventos_localizacion_lat_check CHECK (lat BETWEEN '-90' AND '90'),
        CONSTRAINT eventos_localizacion_lng_check CHECK (lng BETWEEN '-180' AND '180'),
        CONSTRAINT eventos_localizacion_fotos_check CHECK (
            fotos_con_coincidencia >= 0 AND fotos_con_coincidencia <= fotos_usadas
        ),
        CONSTRAINT eventos_localizacion_latencia_ms_check CHECK (latencia_ms >= 0)
    )
    """,
    "CREATE INDEX eventos_localizacion_creado_en_idx ON eventos_localizacion (creado_en)",
    # --- auditoria --------------------------------------------------------------------------------------------
    """
    CREATE TABLE auditoria (
        id         bigserial,
        creado_en  timestamptz NOT NULL DEFAULT now(),
        actor_id   uuid,
        accion     text        NOT NULL,
        entidad    text        NOT NULL,
        entidad_id text,
        detalle    jsonb       NOT NULL DEFAULT '{}',
        CONSTRAINT auditoria_pkey PRIMARY KEY (id),
        CONSTRAINT auditoria_actor_id_fkey FOREIGN KEY (actor_id) REFERENCES usuarios (id),
        CONSTRAINT auditoria_detalle_check CHECK (jsonb_typeof(detalle) = 'object')
    )
    """,
]

# La extensión `vector` se conserva al bajar: puede usarla otra base del servidor y crearla exige privilegios.
BAJAR = [
    "DROP TABLE auditoria",
    "DROP TABLE eventos_localizacion",
    "DROP TABLE embeddings",
    "DROP TABLE imagenes",
    "DROP TABLE videos",
    "DROP TABLE alertas",
    "DROP TABLE lugares",
    "DROP TABLE usuarios",
    "DROP TYPE calidad_imagen",
    "DROP TYPE estado_imagen",
    "DROP TYPE estado_video",
    "DROP TYPE prioridad_alerta",
    "DROP TYPE tipo_alerta",
    "DROP TYPE categoria_lugar",
    "DROP TYPE rol_usuario",
]


def upgrade() -> None:
    for sentencia in SUBIR:
        op.execute(sentencia)


def downgrade() -> None:
    for sentencia in BAJAR:
        op.execute(sentencia)
