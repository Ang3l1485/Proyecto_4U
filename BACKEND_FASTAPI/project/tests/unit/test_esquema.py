"""Comparación de catálogos de `app.db.esquema` sin base de datos (lo que lee de PostgreSQL: tests/base/)."""

from __future__ import annotations

import copy

import pytest

from app.db import esquema
from app.db.esquema import Columna, Diferencia
from app.dominio import enumerados
from app.servicios import migracion


@pytest.fixture
def igual() -> esquema.Catalogo:
    """Un catálogo leído idéntico a lo esperado (con la revisión y extensiones de más, que se ignoran)."""
    catalogo = copy.deepcopy(esquema.ESPERADO)
    catalogo.extensiones = {"plpgsql": "1.0", "vector": "0.8.1", "pg_stat_statements": "1.11"}
    catalogo.revision = "0001"
    return catalogo


def _comparar(catalogo: esquema.Catalogo) -> set[tuple[str, str]]:
    return {(d.objeto, d.aspecto) for d in esquema.comparar(esquema.ESPERADO, catalogo, revision="0001")}


def test_un_catalogo_igual_no_tiene_diferencias(igual):
    assert esquema.comparar(esquema.ESPERADO, igual, revision="0001") == []


def test_falta_la_extension_vector(igual):
    del igual.extensiones["vector"]
    assert _comparar(igual) == {("extensión vector", "falta")}


def test_tipos_que_faltan_sobran_o_cambian(igual):
    del igual.tipos["rol_usuario"]
    igual.tipos["estado_video"] = ("pendiente", "procesado")
    igual.tipos["nuevo"] = ("a",)
    igual.otros_tipos = {"dominio_propio"}
    assert _comparar(igual) == {
        ("tipo rol_usuario", "falta"),
        ("tipo estado_video", "valores"),
        ("tipo nuevo", "sobra"),
        ("tipo dominio_propio", "sobra"),
    }


def test_columnas_con_tipo_nulo_defecto_y_generadas(igual):
    alertas = igual.tablas["alertas"]
    alertas["radio_m"] = Columna("integer", nulo=True, defecto=None, generada="a")
    del alertas["mensaje"]
    alertas["extra"] = Columna("text", nulo=True)
    diferencias = esquema.comparar(esquema.ESPERADO, igual, revision="0001")
    assert diferencias == [
        Diferencia("columna alertas.mensaje", "falta", "mensaje", None),
        Diferencia("columna alertas.extra", "sobra", None, "extra"),
        Diferencia("columna alertas.radio_m", "tipo", "smallint", "integer"),
        Diferencia("columna alertas.radio_m", "nulo", "NOT NULL", "nulo"),
        Diferencia("columna alertas.radio_m", "defecto", "15", None),
        Diferencia("columna alertas.radio_m", "generada", None, "a"),
    ]


def test_una_tabla_que_falta_no_repite_sus_columnas(igual):
    del igual.tablas["embeddings"]
    del igual.restricciones["embeddings"]
    del igual.indices["embeddings"]
    assert _comparar(igual) == {("tabla embeddings", "falta")}


def test_restricciones_e_indices(igual):
    igual.restricciones["videos"]["videos_nombre_check"] = "CHECK ((char_length(nombre) <= 80))"
    del igual.restricciones["videos"]["videos_purgado_en_check"]
    igual.indices["usuarios"] = {"usuarios_nombre_idx": "CREATE INDEX …"}
    del igual.indices["embeddings"]["embeddings_hnsw_dinov2_vits14_pp_v1"]
    assert _comparar(igual) == {
        ("restricción videos_nombre_check", "definicion"),
        ("restricción videos_purgado_en_check", "falta"),
        ("índice usuarios_nombre_idx", "sobra"),
        ("índice embeddings_hnsw_dinov2_vits14_pp_v1", "falta"),
    }


def test_secuencias_vistas_funciones_y_triggers(igual):
    igual.secuencias["videos_numero_seq"] = ("bigint", None)
    igual.secuencias["sobrante_seq"] = ("bigint", None)
    igual.vistas = {"v"}
    igual.funciones = {"f()"}
    igual.disparadores = {"videos.t"}
    assert _comparar(igual) == {
        ("secuencia videos_numero_seq", "tipo"),
        ("secuencia videos_numero_seq", "propietaria"),
        ("secuencia sobrante_seq", "sobra"),
        ("vista v", "sobra"),
        ("función f()", "sobra"),
        ("trigger videos.t", "sobra"),
    }


def test_revision_de_alembic(igual):
    igual.revision = None
    assert _comparar(igual) == {("tabla alembic_version", "revision")}
    assert esquema.comparar(esquema.ESPERADO, igual, revision=None) == []


def test_diferencia_como_campos_de_log():
    campos = Diferencia("tabla x", "falta", "x", None).como_campos()
    assert campos == {"objeto": "tabla x", "aspecto": "falta", "esperado": "x", "encontrado": None}


# --- Coherencia con el resto del código ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("tipo", "clase"),
    [
        ("rol_usuario", enumerados.RolUsuario),
        ("categoria_lugar", enumerados.CategoriaLugar),
        ("tipo_alerta", enumerados.TipoAlerta),
        ("prioridad_alerta", enumerados.PrioridadAlerta),
        ("estado_video", enumerados.EstadoVideo),
        ("estado_imagen", enumerados.EstadoImagen),
        ("calidad_imagen", enumerados.CalidadImagen),
    ],
)
def test_los_enumerados_del_dominio_son_los_del_esquema(tipo, clase):
    assert tuple(m.value for m in clase) == esquema.ESPERADO.tipos[tipo]


def test_los_valores_de_eventos_son_los_de_sus_check():
    restricciones = esquema.ESPERADO.restricciones["eventos_localizacion"]
    for columna, clase in (
        ("origen", enumerados.OrigenLocalizacion),
        ("resultado", enumerados.ResultadoLocalizacion),
        ("nivel", enumerados.NivelConfianza),
    ):
        valores = ", ".join(f"'{m.value}'::text" for m in clase)
        assert f"ARRAY[{valores}]" in restricciones[f"eventos_localizacion_{columna}_check"]


def test_el_indice_parcial_es_el_de_la_version_activa():
    from app.config import Settings

    version = Settings().embedding_version_vector
    [definicion] = esquema.ESPERADO.indices["embeddings"].values()
    assert f"WHERE (version_vector = '{version}'::text)" in definicion
    assert "vector(384)" == esquema.ESPERADO.tablas["embeddings"]["vector"].tipo


def test_la_revision_esperada_es_la_ultima_migracion():
    assert migracion.revision_head() == "0001"
    assert migracion.directorio_migraciones().name == "migrations"
