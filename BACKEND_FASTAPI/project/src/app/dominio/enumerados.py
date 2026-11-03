"""Valores enumerados de los contratos (ARCHITECTURE §5.3–§5.5 y §5.7).

Python puro (regla de `dominio/`, §4.1): los modelos de la base, los esquemas Pydantic y la lógica los importan de aquí.
El nombre de cada miembro es su valor, en minúsculas (§5.1).
"""

from __future__ import annotations

from enum import StrEnum


# --- Tipos enumerados de PostgreSQL (§5.7) ------------------------------------------------------------------------
class RolUsuario(StrEnum):
    user = "user"
    admin = "admin"


class CategoriaLugar(StrEnum):
    biblioteca = "biblioteca"
    cafeteria = "cafeteria"
    bano = "bano"
    bloque = "bloque"
    auditorio = "auditorio"
    deportes = "deportes"
    administracion = "administracion"
    entrada = "entrada"


class TipoAlerta(StrEnum):
    agua = "agua"
    mobiliario = "mobiliario"
    escalones = "escalones"
    obra = "obra"
    vehiculos = "vehiculos"
    otro = "otro"


class PrioridadAlerta(StrEnum):
    normal = "normal"
    alta = "alta"


class EstadoVideo(StrEnum):
    pendiente = "pendiente"
    procesando = "procesando"
    procesado = "procesado"
    con_errores = "con_errores"
    eliminado = "eliminado"


class EstadoImagen(StrEnum):
    pendiente_subida = "pendiente_subida"
    subida = "subida"
    procesada = "procesada"
    error = "error"


class CalidadImagen(StrEnum):
    alta = "alta"
    normal = "normal"
    baja = "baja"


# --- Valores de `eventos_localizacion` (texto con CHECK en §5.7, no tipos de PostgreSQL) -----------------------------
class OrigenLocalizacion(StrEnum):
    escaneo = "escaneo"
    frame = "frame"


class ResultadoLocalizacion(StrEnum):
    ok = "ok"
    sin_coincidencias = "sin_coincidencias"
    error = "error"


class NivelConfianza(StrEnum):
    alta = "alta"
    media = "media"
    baja = "baja"
