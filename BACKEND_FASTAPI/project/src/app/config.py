"""Configuración del backend.

Lee las variables que inyecta la infraestructura (`INFRASTRUCTURA_TERRAFORM/docs/ARCHITECTURE.md` §5.4) y los
parámetros operativos del backend (`BACKEND_FASTAPI/docs/ARCHITECTURE.md` §5.10). Cada parámetro tiene su valor
inicial aquí y puede sobrescribirse con una variable de entorno del mismo nombre (§5.9).

Ninguna variable es obligatoria para arrancar: cada lote exige las suyas cuando las usa. Las `DB_*` las exigen la
CLI (`migrar`, `verificar-esquema`) y `GET /v1/health/ready`, que sin ellas responde `503 BASE_NO_DISPONIBLE`.
"""

from __future__ import annotations

import re
from functools import lru_cache

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_SHA = re.compile(r"[0-9a-f]{7,40}")
_NIVELES_LOG = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}


class Settings(BaseSettings):
    """Valores de configuración. Los nombres de campo coinciden (sin distinguir mayúsculas) con las variables."""

    model_config = SettingsConfigDict(case_sensitive=False, extra="ignore", frozen=True)

    # --- Infra §5.4: variables en texto plano -------------------------------------------------------------------
    app_env: str = "local"
    aws_region: str = "us-east-1"
    log_level: str = "INFO"
    db_host: str | None = None
    db_port: int = 5432
    db_name: str | None = None
    db_user: str | None = None
    db_sslmode: str = "require"
    s3_bucket_dataset: str | None = None
    sqs_url_ingesta: str | None = None
    sqs_url_purga: str | None = None
    embedding_url: str | None = None

    # --- Infra §5.4: secretos (Secrets Manager → variables) ---------------------------------------------------
    db_password: SecretStr | None = None
    jwt_secret: SecretStr | None = None
    admin_inicial_correo: str | None = None
    admin_inicial_password: SecretStr | None = None

    # --- Fijada en la imagen (Dockerfile, --build-arg GIT_COMMIT) ---------------------------------------------
    app_commit: str = "desconocido"

    # --- Backend §5.10: parámetros operativos -----------------------------------------------------------------
    jwt_ttl_min: int = 720
    # Verificaciones argon2id a la vez en `api` (cada una usa 64 MiB; la tarea tiene 0,5 GB), cuántas más pueden esperar
    # turno y cuánto como mucho; si no, 503 SERVICIO_OCUPADO (§4.4). BE-1.3
    login_hash_concurrentes: int = 2
    login_hash_cola_max: int = 8
    login_hash_espera_max_s: float = 10.0
    embedding_version_vector: str = "dinov2-vits14/pp-v1"
    embedding_timeout_s: float = 5.0
    embedding_connect_timeout_s: float = 3.0
    loc_max_fotos: int = 5
    loc_max_bytes_foto: int = 1_572_864
    loc_top_k: int = 10
    loc_ef_search: int = 64
    loc_sim_min: float = 0.55
    loc_sim_alta: float = 0.80
    loc_radio_grupo_m: float = 20.0
    loc_peso_exponente: float = 4.0
    loc_radio_min_m: float = 5.0
    # «Cortes de nivel» de §5.10: alta ≥ 0,70 · media ≥ 0,45 · baja < 0,45
    loc_nivel_alta_min: float = 0.70
    loc_nivel_media_min: float = 0.45
    loc_dispersion_rumbo_max: float = 30.0
    loc_lugar_cercano_m: float = 60.0
    loc_referencias_m: float = 150.0
    loc_referencias_max: int = 3
    # `POST /v1/localize/frame` (BE-5.1): radio por defecto alrededor de `posicion_previa` y rango admitido (ADR-BE-21)
    loc_frame_radio_m: float = 40.0
    loc_frame_radio_min_m: float = 10.0
    loc_frame_radio_max_m: float = 100.0
    rec_max_fotos_video: int = 200
    rec_max_lote: int = 50
    rec_max_bytes_foto: int = 4_194_304
    rec_lado_min_px: int = 320
    presign_put_ttl_s: int = 900
    presign_get_ttl_s: int = 3600
    miniatura_lado_px: int = 320
    miniatura_calidad: int = 80
    worker_max_mensajes: int = 10
    worker_lote_embedding: int = 4
    worker_lado_embedding_px: int = 1024
    worker_espera_embedding_s: float = 15.0
    reconciliador_cada_min: int = 10
    alertas_tombstone_dias: int = 90
    eventos_retencion_dias: int = 180
    pagina_por_defecto: int = 24
    pagina_max: int = 100
    # «DB_POOL (api / worker)» de §5.10: 5 + 5 de desborde / 2
    db_pool_api: int = 5
    db_pool_api_desborde: int = 5
    db_pool_worker: int = 2
    # Tiempo máximo para abrir una conexión (asyncpg espera 60 s por defecto) y para el `SELECT 1` de /v1/health/ready
    db_connect_timeout_s: float = 5.0

    @field_validator("log_level")
    @classmethod
    def _normalizar_nivel(cls, valor: str) -> str:
        nivel = valor.strip().upper()
        return nivel if nivel in _NIVELES_LOG else "INFO"

    @field_validator("embedding_url")
    @classmethod
    def _sin_barra_final(cls, valor: str | None) -> str | None:
        if valor is None or not valor.strip():
            return None
        return valor.strip().rstrip("/")

    @property
    def commit_corto(self) -> str:
        """SHA corto (7) del commit desplegado; si no parece un SHA, el valor tal cual (p. ej. `local`)."""
        commit = self.app_commit.strip().lower()
        return commit[:7] if _SHA.fullmatch(commit) else self.app_commit.strip()

    @property
    def es_produccion(self) -> bool:
        return self.app_env.strip().lower() == "prod"


@lru_cache
def get_settings() -> Settings:
    """Configuración del proceso (se lee una vez)."""
    return Settings()
