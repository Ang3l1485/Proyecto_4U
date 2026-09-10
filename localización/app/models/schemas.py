import math
from pydantic import BaseModel, ConfigDict, Field, field_validator


class Position(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class Coordinates(BaseModel):
    gps: Position
    reference: Position


class Metadata(BaseModel):
    model_config = ConfigDict(extra='allow', allow_inf_nan=False)
    pointId: str = Field(min_length=1, pattern=r'\S')
    block: str = ''
    coordinates: Coordinates
    compassHeadingDegrees: float
    compassDirection: str | None = None
    floor: int | str | None = None

    @field_validator('compassHeadingDegrees')
    @classmethod
    def normalize_heading(cls, value):
        if not math.isfinite(value):
            raise ValueError('compassHeadingDegrees debe ser finito')
        return value % 360


class ImageMetadata(BaseModel):
    model_config = ConfigDict(extra='allow')
    metadata: Metadata
    quality: dict = Field(default_factory=dict)
    wasQualityOverride: bool = False
