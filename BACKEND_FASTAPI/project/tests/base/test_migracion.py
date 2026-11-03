"""`python -m app.cli migrar` y `verificar-esquema` contra una base real (ARCHITECTURE §4.3, §5.7, §5.9)."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from alembic import command
from pydantic import SecretStr
from sqlalchemy import text

from app import cli
from app.config import Settings
from app.db import esquema, modelos, sesion
from app.seguridad import hash as hash_password
from app.servicios import migracion

pytestmark = pytest.mark.base

ADMIN = "admin.pruebas@campus.edu.co"


async def _consultar(ajustes: Settings, sentencias: list[str]) -> list[Any]:
    """Ejecuta las sentencias en orden y devuelve las filas de la última."""
    motor = sesion.crear_motor(ajustes, "pruebas")
    try:
        async with motor.begin() as conexion:
            resultado = None
            for sentencia in sentencias:
                resultado = await conexion.execute(text(sentencia))
            return list(resultado.all()) if resultado is not None and resultado.returns_rows else []
    finally:
        await motor.dispose()


def consultar(ajustes: Settings, *sentencias: str) -> list[Any]:
    return asyncio.run(_consultar(ajustes, list(sentencias)))


def eventos(logs_json, nombre: str) -> list[dict]:
    return [linea for linea in logs_json.lineas if linea["evento"] == nombre]


# --- migrar -------------------------------------------------------------------------------------------------------
def test_migrar_en_base_vacia_crea_el_esquema_y_el_admin(base_vacia, logs_json):
    assert cli.main(["migrar"], ajustes=base_vacia) == 0

    [terminada] = eventos(logs_json, "migracion_terminada")
    assert terminada["revision_anterior"] is None
    assert terminada["revision"] == migracion.revision_head() == "0001"
    assert terminada["aplicada"] is True
    assert terminada["admin_inicial"] == "creado"
    [(correo, nombre, rol, activo, hash_guardado, usuario_id)] = consultar(
        base_vacia, "SELECT correo, nombre, rol::text, activo, hash_password, id::text FROM usuarios"
    )
    assert (correo, nombre, rol, activo) == (ADMIN, "Administrador", "admin", True)
    assert terminada["usuario_id"] == usuario_id
    assert hash_guardado.startswith("$argon2id$")
    assert hash_password.verificar(hash_guardado, "Pruebas-admin-123")
    texto_logs = "\n".join(map(str, logs_json.lineas))
    assert "Pruebas-admin-123" not in texto_logs
    assert hash_guardado not in texto_logs


def test_migrar_es_idempotente(base_migrada, logs_json):
    assert cli.main(["migrar"], ajustes=base_migrada) == 0
    [terminada] = eventos(logs_json, "migracion_terminada")
    assert terminada["revision_anterior"] == terminada["revision"] == "0001"
    assert terminada["aplicada"] is False
    assert terminada["admin_inicial"] == "ya_habia_admin"
    assert "usuario_id" not in terminada
    assert consultar(base_migrada, "SELECT count(*) FROM usuarios") == [(1,)]


def test_el_correo_del_admin_se_normaliza(base_vacia):
    ajustes = base_vacia.model_copy(update={"admin_inicial_correo": "  Admin.Pruebas@Campus.EDU.co "})
    assert cli.main(["migrar"], ajustes=ajustes) == 0
    assert consultar(ajustes, "SELECT correo FROM usuarios") == [(ADMIN,)]


def test_un_admin_desactivado_no_se_vuelve_a_crear(base_migrada):
    consultar(base_migrada, "UPDATE usuarios SET activo = false")
    assert cli.main(["migrar"], ajustes=base_migrada) == 0
    assert consultar(base_migrada, "SELECT count(*), bool_or(activo) FROM usuarios") == [(1, False)]


def test_sin_admin_inicial_configurado_termina_con_3_y_deja_el_esquema(base_vacia, logs_json):
    ajustes = base_vacia.model_copy(update={"admin_inicial_correo": None, "admin_inicial_password": None})
    assert cli.main(["migrar"], ajustes=ajustes) == 3
    [evento] = eventos(logs_json, "configuracion_incompleta")
    assert evento["faltan"] == ["ADMIN_INICIAL_CORREO", "ADMIN_INICIAL_PASSWORD"]
    assert consultar(ajustes, "SELECT version_num FROM alembic_version") == [("0001",)]
    # Con las variables, la siguiente ejecución completa el trabajo.
    assert cli.main(["migrar"], ajustes=base_vacia) == 0


def test_correo_del_admin_ocupado_por_un_user_falla_con_1(base_vacia, logs_json):
    ajustes = base_vacia.model_copy(update={"admin_inicial_correo": None})
    assert cli.main(["migrar"], ajustes=ajustes) == 3
    consultar(
        base_vacia,
        "INSERT INTO usuarios (correo, nombre, rol, hash_password) "
        "VALUES ('admin.pruebas@campus.edu.co', 'Persona', 'user', 'x')",
    )
    assert cli.main(["migrar"], ajustes=base_vacia) == 1
    [fallida] = eventos(logs_json, "migracion_fallida")
    assert "ConflictoAdminInicial" in fallida["motivo"]
    assert consultar(base_vacia, "SELECT rol::text FROM usuarios") == [("user",)]


def test_un_fallo_al_crear_el_admin_no_deja_el_hash_ni_el_correo_en_el_log(base_vacia, logs_json):
    ajustes = base_vacia.model_copy(update={"admin_inicial_correo": None})
    assert cli.main(["migrar"], ajustes=ajustes) == 3
    consultar(base_vacia, "ALTER TABLE usuarios ADD CONSTRAINT bloqueo_check CHECK (rol <> 'admin')")
    assert cli.main(["migrar"], ajustes=base_vacia) == 1
    [fallida] = eventos(logs_json, "migracion_fallida")
    assert "bloqueo_check" in fallida["motivo"]
    assert "excepcion" in fallida
    texto = "\n".join(map(str, logs_json.lineas))
    assert "$argon2id$" not in texto
    assert ADMIN not in texto


def test_verificar_espera_a_un_migrar_en_curso(base_migrada, logs_json, monkeypatch):
    import asyncpg

    monkeypatch.setattr(migracion, "ESPERA_BLOQUEO_S", 1)

    async def con_migrar_en_curso():
        # Otra sesión con el bloqueo de `migrar` tomado, como un despliegue a medias.
        otra = await asyncpg.connect(
            host=base_migrada.db_host,
            port=base_migrada.db_port,
            user=base_migrada.db_user,
            password=base_migrada.db_password.get_secret_value(),
            database=base_migrada.db_name,
        )
        try:
            await otra.execute("SELECT pg_advisory_lock($1)", migracion.CLAVE_BLOQUEO)
            return await asyncio.to_thread(cli.main, ["verificar-esquema"], base_migrada)
        finally:
            await otra.close()

    assert asyncio.run(con_migrar_en_curso()) == 2
    assert "LockNotAvailableError" in eventos(logs_json, "verificacion_fallida")[0]["motivo"]
    assert eventos(logs_json, "esquema_verificado") == []
    # Sin el bloqueo, verifica con normalidad.
    assert cli.main(["verificar-esquema"], ajustes=base_migrada) == 0


def test_sin_permiso_connect_es_base_no_disponible(base_migrada, logs_json):
    import uuid as uuid_

    rol = f"sin_connect_{uuid_.uuid4().hex[:8]}"
    consultar(
        base_migrada,
        f"CREATE ROLE {rol} LOGIN PASSWORD 'sin-connect'",
        f'REVOKE CONNECT ON DATABASE "{base_migrada.db_name}" FROM PUBLIC',
    )
    try:
        ajustes = base_migrada.model_copy(update={"db_user": rol, "db_password": SecretStr("sin-connect")})
        assert cli.main(["verificar-esquema"], ajustes=ajustes) == 2
        assert "InsufficientPrivilegeError" in eventos(logs_json, "base_no_disponible")[0]["motivo"]
    finally:
        consultar(base_migrada, f'GRANT CONNECT ON DATABASE "{base_migrada.db_name}" TO PUBLIC', f"DROP ROLE {rol}")


def test_dos_migrar_a_la_vez_se_ejecutan_en_fila(base_vacia):
    async def dos_a_la_vez():
        motores = [sesion.crear_motor(base_vacia, "migrate") for _ in range(2)]
        try:
            return await asyncio.gather(*(migracion.migrar(motor, base_vacia) for motor in motores))
        finally:
            for motor in motores:
                await motor.dispose()

    resultados = asyncio.run(dos_a_la_vez())
    assert sorted(r.revision_anterior or "" for r in resultados) == ["", "0001"]
    assert sorted(r.admin_inicial for r in resultados) == ["creado", "ya_habia_admin"]
    assert consultar(base_vacia, "SELECT count(*) FROM usuarios") == [(1,)]


def test_bajar_la_migracion_deja_la_base_vacia(base_migrada):
    async def bajar():
        motor = sesion.crear_motor(base_migrada, "migrate")
        try:
            async with motor.begin() as conexion:

                def ejecutar(conexion_sync):
                    configuracion = migracion.configuracion_alembic()
                    configuracion.attributes["connection"] = conexion_sync
                    command.downgrade(configuracion, "base")

                await conexion.run_sync(ejecutar)
        finally:
            await motor.dispose()

    asyncio.run(bajar())
    assert consultar(
        base_migrada,
        "SELECT count(*) FROM pg_class WHERE relnamespace = 'public'::regnamespace "
        "AND relkind IN ('r', 'S') AND relname <> 'alembic_version'",
    ) == [(0,)]
    assert cli.main(["migrar"], ajustes=base_migrada) == 0


# --- verificar-esquema --------------------------------------------------------------------------------------------
def test_verificar_tras_migrar_coincide(base_migrada, logs_json):
    assert cli.main(["verificar-esquema"], ajustes=base_migrada) == 0
    assert eventos(logs_json, "esquema_diferencia") == []
    [verificado] = eventos(logs_json, "esquema_verificado")
    assert verificado["resultado"] == "coincide"
    assert verificado["diferencias"] == 0
    assert verificado["revision"] == verificado["revision_esperada"] == "0001"
    assert verificado["pgvector"]


def test_verificar_base_sin_migrar_difiere(base_vacia, logs_json):
    assert cli.main(["verificar-esquema"], ajustes=base_vacia) == 1
    diferencias = {(d["objeto"], d["aspecto"]) for d in eventos(logs_json, "esquema_diferencia")}
    assert ("extensión vector", "falta") in diferencias
    assert ("tabla usuarios", "falta") in diferencias
    assert ("tipo rol_usuario", "falta") in diferencias
    assert ("tabla alembic_version", "revision") in diferencias
    [verificado] = eventos(logs_json, "esquema_verificado")
    assert verificado["resultado"] == "difiere"
    assert verificado["diferencias"] == len(eventos(logs_json, "esquema_diferencia"))
    assert verificado["nivel"] == "WARNING"


def test_verificar_detecta_cambios_a_mano(base_migrada, logs_json):
    consultar(
        base_migrada,
        "ALTER TABLE alertas ALTER COLUMN radio_m DROP DEFAULT",
        "ALTER TABLE lugares ALTER COLUMN descripcion SET NOT NULL",
        "ALTER TABLE imagenes ALTER COLUMN notas TYPE varchar(500)",
        "ALTER TABLE videos DROP CONSTRAINT videos_eliminado_check",
        "ALTER TABLE videos ADD COLUMN extra integer",
        "ALTER TYPE calidad_imagen ADD VALUE 'pesima'",
        "DROP INDEX imagenes_estado_idx",
        "CREATE INDEX usuarios_nombre_idx ON usuarios (nombre)",
        "ALTER TABLE usuarios DROP CONSTRAINT usuarios_nombre_check",
        "ALTER TABLE usuarios ADD CONSTRAINT usuarios_nombre_check CHECK (char_length(nombre) > 1)",
        "CREATE TABLE sobrante (x integer)",
        "CREATE VIEW vista_sobrante AS SELECT 1 AS uno",
        "CREATE FUNCTION f_sobrante() RETURNS integer LANGUAGE sql AS 'SELECT 1'",
        "CREATE TYPE tipo_sobrante AS (a integer)",
        "UPDATE alembic_version SET version_num = '0000'",
    )
    assert cli.main(["verificar-esquema"], ajustes=base_migrada) == 1
    encontradas = {(d["objeto"], d["aspecto"]): d for d in eventos(logs_json, "esquema_diferencia")}
    esperadas = {
        ("columna alertas.radio_m", "defecto"),
        ("columna lugares.descripcion", "nulo"),
        ("columna imagenes.notas", "tipo"),
        ("restricción imagenes_notas_check", "definicion"),  # el CHECK pasa a llevar el cast a text
        ("restricción videos_eliminado_check", "falta"),
        ("columna videos.extra", "sobra"),
        ("tipo calidad_imagen", "valores"),
        ("índice imagenes_estado_idx", "falta"),
        ("índice usuarios_nombre_idx", "sobra"),
        ("restricción usuarios_nombre_check", "definicion"),
        ("tabla sobrante", "sobra"),
        ("vista vista_sobrante", "sobra"),
        ("función f_sobrante()", "sobra"),
        ("tipo tipo_sobrante", "sobra"),
        ("tabla alembic_version", "revision"),
    }
    assert set(encontradas) == esperadas
    assert encontradas[("columna alertas.radio_m", "defecto")]["esperado"] == "15"
    assert encontradas[("columna alertas.radio_m", "defecto")]["encontrado"] is None
    assert encontradas[("columna lugares.descripcion", "nulo")]["encontrado"] == "NOT NULL"
    assert encontradas[("tipo calidad_imagen", "valores")]["encontrado"] == "alta, normal, baja, pesima"
    assert encontradas[("tabla alembic_version", "revision")]["encontrado"] == "0000"
    for diferencia in encontradas.values():
        assert diferencia["nivel"] == "WARNING"
        assert set(diferencia) >= {"objeto", "aspecto", "esperado", "encontrado"}


def test_verificar_no_modifica_nada(base_migrada):
    sql = "SELECT count(*) FROM pg_class WHERE relnamespace = 'public'::regnamespace"
    antes = consultar(base_migrada, sql)
    assert cli.main(["verificar-esquema"], ajustes=base_migrada) == 0
    assert consultar(base_migrada, sql) == antes


# --- modelos ------------------------------------------------------------------------------------------------------
def test_los_modelos_describen_exactamente_el_esquema(base_vacia):
    async def crear_y_leer():
        motor = sesion.crear_motor(base_vacia, "pruebas")
        try:
            async with motor.begin() as conexion:
                await conexion.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
                await conexion.run_sync(modelos.Base.metadata.create_all)
            async with motor.connect() as conexion:
                return await esquema.leer_catalogo(conexion)
        finally:
            await motor.dispose()

    catalogo = asyncio.run(crear_y_leer())
    assert esquema.comparar(esquema.ESPERADO, catalogo, revision=None) == []


# --- reglas de §5.7 -----------------------------------------------------------------------------------------------
VIDEO = (
    "INSERT INTO videos (id, nombre, ref_cliente, creado_por) "
    "SELECT '9c1d0000-0000-4000-8000-000000000001', 'video_1', 'rec_0001', id FROM usuarios"
)
IMAGEN = (
    "INSERT INTO imagenes (id, video_id, orden, s3_key, lat, lng, capturada_en, bytes_declarados) VALUES "
    "('a91f0000-0000-4000-8000-000000000001', '9c1d0000-0000-4000-8000-000000000001', 1, "
    "'dataset/9c1d0000-0000-4000-8000-000000000001/a91f0000-0000-4000-8000-000000000001.jpg', "
    "6.2001, -75.5786, now(), 345678)"
)


def test_valores_por_defecto_de_un_video_y_una_imagen(base_migrada):
    consultar(base_migrada, VIDEO, IMAGEN)
    assert consultar(
        base_migrada,
        "SELECT v.numero, v.estado::text, v.total_fotos_declaradas, i.estado::text, i.calidad::text, i.intentos "
        "FROM videos v JOIN imagenes i ON i.video_id = v.id",
    ) == [(1, "pendiente", 0, "pendiente_subida", "normal", 0)]


@pytest.mark.parametrize(
    ("sentencia", "restriccion"),
    [
        ("UPDATE imagenes SET s3_key = 'dataset/otro.jpg'", "imagenes_s3_key_check"),
        ("UPDATE imagenes SET estado = 'error'", "imagenes_error_check"),
        ("UPDATE imagenes SET rumbo = 360", "imagenes_rumbo_check"),
        ("UPDATE imagenes SET orden = 201", "imagenes_orden_check"),
        ("UPDATE imagenes SET lat = 90.5", "imagenes_lat_check"),
        ("UPDATE videos SET estado = 'eliminado'", "videos_eliminado_check"),
        ("UPDATE videos SET purgado_en = now()", "videos_purgado_en_check"),
        ("UPDATE videos SET inicio_lat = 6.2", "videos_inicio_check"),
        ("UPDATE videos SET nombre = ''", "videos_nombre_check"),
        ("UPDATE usuarios SET correo = 'Mayus@campus.edu.co'", "usuarios_correo_check"),
    ],
)
def test_las_restricciones_rechazan_datos_incoherentes(base_migrada, sentencia, restriccion):
    from sqlalchemy.exc import IntegrityError

    consultar(base_migrada, VIDEO, IMAGEN)
    with pytest.raises(IntegrityError) as error:
        consultar(base_migrada, sentencia)
    assert restriccion in str(error.value)


def test_borrado_coherente_de_un_video_y_cascada(base_migrada):
    consultar(base_migrada, VIDEO, IMAGEN)
    consultar(
        base_migrada,
        "UPDATE videos SET estado = 'eliminado', eliminado_en = now(), eliminado_por = creado_por",
        "UPDATE videos SET purgado_en = now()",
        "DELETE FROM videos",
    )
    assert consultar(base_migrada, "SELECT count(*) FROM imagenes") == [(0,)]


def test_alerta_con_vigencia_y_valores_por_defecto(base_migrada):
    consultar(
        base_migrada,
        "INSERT INTO alertas (lat, lng, mensaje, creado_por, actualizado_por, vigencia_desde) "
        "SELECT 6.2011, -75.579, 'validacion-alerta', id, id, now() FROM usuarios",
    )
    assert consultar(base_migrada, "SELECT tipo::text, prioridad::text, radio_m, activa, version FROM alertas") == [
        ("otro", "normal", 15, True, 1)
    ]
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError, match="alertas_vigencia_check"):
        consultar(base_migrada, "UPDATE alertas SET vigencia_hasta = vigencia_desde")


def test_vector_de_384_ida_y_vuelta(base_migrada):
    from sqlalchemy import select

    vector = [0.0] * 384
    vector[0], vector[1] = 0.6, 0.8

    async def ida_y_vuelta():
        motor = sesion.crear_motor(base_migrada, "pruebas")
        try:
            async with motor.begin() as conexion:
                await conexion.execute(text(VIDEO))
                await conexion.execute(text(IMAGEN))
                await conexion.execute(
                    modelos.Embedding.__table__.insert().values(
                        imagen_id="a91f0000-0000-4000-8000-000000000001",
                        version_vector="dinov2-vits14/pp-v1",
                        vector=vector,
                    )
                )
                fila = (await conexion.execute(select(modelos.Embedding.vector))).scalar_one()
                distancia = (
                    await conexion.execute(
                        text("SELECT vector <=> CAST(:q AS vector) FROM embeddings"),
                        {"q": "[" + ",".join(["0.6", "0.8"] + ["0"] * 382) + "]"},
                    )
                ).scalar_one()
                return fila, distancia
        finally:
            await motor.dispose()

    leido, distancia = asyncio.run(ida_y_vuelta())
    assert leido == pytest.approx(vector)
    assert distancia == pytest.approx(0.0, abs=1e-6)
