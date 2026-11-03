"""Parámetros de ARCHITECTURE §5.10 y lectura de variables (§5.9)."""

from __future__ import annotations

import pytest

from app.config import Settings

VALORES_5_10 = {
    "jwt_ttl_min": 720,
    "embedding_version_vector": "dinov2-vits14/pp-v1",
    "embedding_timeout_s": 5,
    "embedding_connect_timeout_s": 3,
    "loc_max_fotos": 5,
    "loc_max_bytes_foto": 1_572_864,
    "loc_top_k": 10,
    "loc_ef_search": 64,
    "loc_sim_min": 0.55,
    "loc_sim_alta": 0.80,
    "loc_radio_grupo_m": 20,
    "loc_peso_exponente": 4,
    "loc_radio_min_m": 5,
    "loc_nivel_alta_min": 0.70,
    "loc_nivel_media_min": 0.45,
    "loc_dispersion_rumbo_max": 30,
    "loc_lugar_cercano_m": 60,
    "loc_referencias_m": 150,
    "loc_referencias_max": 3,
    "rec_max_fotos_video": 200,
    "rec_max_lote": 50,
    "rec_max_bytes_foto": 4_194_304,
    "rec_lado_min_px": 320,
    "presign_put_ttl_s": 900,
    "presign_get_ttl_s": 3600,
    "miniatura_lado_px": 320,
    "miniatura_calidad": 80,
    "worker_max_mensajes": 10,
    "worker_lote_embedding": 4,
    "worker_lado_embedding_px": 1024,
    "worker_espera_embedding_s": 15,
    "reconciliador_cada_min": 10,
    "alertas_tombstone_dias": 90,
    "eventos_retencion_dias": 180,
    "pagina_por_defecto": 24,
    "pagina_max": 100,
    "db_pool_api": 5,
    "db_pool_api_desborde": 5,
    "db_pool_worker": 2,
    "db_connect_timeout_s": 5,
}


@pytest.fixture
def entorno_limpio(monkeypatch):
    for nombre in [*VALORES_5_10, "app_commit", "log_level", "embedding_url", "db_host"]:
        monkeypatch.delenv(nombre.upper(), raising=False)
    return monkeypatch


def test_valores_iniciales_de_5_10(entorno_limpio):
    ajustes = Settings()
    for nombre, valor in VALORES_5_10.items():
        assert getattr(ajustes, nombre) == pytest.approx(valor), nombre


def test_un_parametro_se_sobrescribe_con_su_variable(entorno_limpio):
    entorno_limpio.setenv("LOC_TOP_K", "12")
    entorno_limpio.setenv("DB_HOST", "campus-locator-dev-db.example")
    ajustes = Settings()
    assert ajustes.loc_top_k == 12
    assert ajustes.db_host == "campus-locator-dev-db.example"


def test_secretos_no_se_muestran(entorno_limpio):
    entorno_limpio.setenv("JWT_SECRET", "super-secreto")
    ajustes = Settings()
    assert "super-secreto" not in repr(ajustes)
    assert ajustes.jwt_secret is not None
    assert ajustes.jwt_secret.get_secret_value() == "super-secreto"


@pytest.mark.parametrize(
    ("commit", "corto"),
    [("0123456789ABCDEF0123456789abcdef01234567", "0123456"), ("local", "local"), ("desconocido", "desconocido")],
)
def test_commit_corto(commit, corto):
    assert Settings(app_commit=commit).commit_corto == corto


def test_url_de_embedding_sin_barra_final_y_vacia_es_none():
    assert Settings(embedding_url="http://embedding:8080/").embedding_url == "http://embedding:8080"
    assert Settings(embedding_url="  ").embedding_url is None


def test_nivel_de_log_invalido_cae_en_info():
    assert Settings(log_level="ruidoso").log_level == "INFO"
    assert Settings(log_level="debug").log_level == "DEBUG"
