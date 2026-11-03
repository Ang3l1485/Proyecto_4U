"""Petición y respuesta de `POST /v1/auth/login` (ARCHITECTURE §5.3)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.dominio.enumerados import RolUsuario
from app.dominio.validaciones import IDENTIFICADOR_MAX, PASSWORD_MAX, motivo_texto_no_admitido


class LoginPeticion(BaseModel):
    """Los campos de más se ignoran. `identificador` se compara sin espacios alrededor y en minúsculas. Un carácter NUL
    (o un sustituto suelto) en cualquiera de los dos es `422 VALIDACION`: no llega a la base."""

    model_config = ConfigDict(extra="ignore")

    identificador: str = Field(min_length=1, max_length=IDENTIFICADOR_MAX, description="Correo del usuario")
    password: str = Field(min_length=1, max_length=PASSWORD_MAX, description="Contraseña (no se recorta)")

    @field_validator("identificador", "password")
    @classmethod
    def _texto_admitido(cls, valor: str) -> str:
        motivo = motivo_texto_no_admitido(valor)
        if motivo is not None:
            raise ValueError(motivo)
        return valor


class UsuarioSesion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    nombre: str
    correo: str = Field(description="Como está guardado: sin espacios alrededor y en minúsculas")
    rol: RolUsuario


class LoginRespuesta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(description="JWT HS256 de §5.2, para `Authorization: Bearer <token>`")
    expira_en: datetime = Field(description="`exp` del token, ISO-8601 en UTC con `Z`")
    usuario: UsuarioSesion
