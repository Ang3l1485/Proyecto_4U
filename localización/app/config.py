import math
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore', allow_inf_nan=False)
    qdrant_url: str = 'http://localhost:6333'
    collection: str = 'campus_dinov2_small_v1'
    model_id: str = 'facebook/dinov2-small'
    model_revision: str = 'ed25f3a31f01632728cabb09d1542f84ab7b0056'
    origin_latitude: float = Field(6.201160, ge=-89, le=89)
    origin_longitude: float = Field(-75.578501, ge=-180, le=180)
    top_k: int = Field(10, ge=1, le=100)
    heading_weight: float = Field(0.15, ge=0, le=1)
    gps_sigma: float = Field(8, gt=0)
    vpr_thresholds: list[tuple[float, float]] = [(0.90, 2), (0.80, 4), (0.70, 7)]
    max_vpr_distance: float = Field(50, gt=0)
    idw_neighbors: int = Field(8, ge=1)
    idw_radius: float = Field(100, gt=0)
    idw_epsilon: float = Field(1, gt=0)
    acceleration_sigma: float = Field(2, gt=0)
    session_ttl: float = Field(1800, gt=0)
    max_sessions: int = Field(1000, ge=1)
    max_upload_bytes: int = Field(15000000, gt=0)

    @field_validator('vpr_thresholds')
    @classmethod
    def validate_thresholds(cls, value):
        if not value or any(not math.isfinite(t) or not -1 <= t <= 1 or
                            not math.isfinite(s) or s <= 0 for t, s in value):
            raise ValueError('VPR_THRESHOLDS requiere umbrales entre -1 y 1 y sigmas positivas')
        if len({t for t, _ in value}) != len(value):
            raise ValueError('Los umbrales VPR deben ser distintos')
        return value


settings = Settings()
