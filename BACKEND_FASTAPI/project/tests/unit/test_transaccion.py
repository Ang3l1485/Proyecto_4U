"""`sesion.es_fallo_de_base` y `sesion.transaccion` sin base de datos (ARCHITECTURE §4.4)."""

from __future__ import annotations

import asyncio

import asyncpg
import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import exc as sa_exc

from app.config import Settings
from app.db import sesion
from app.errores import ErrorApi


def _con_causa(exc: BaseException, causa: BaseException) -> BaseException:
    exc.__cause__ = causa
    return exc


@pytest.mark.parametrize(
    "error",
    [
        ConnectionResetError("reset"),
        sa_exc.OperationalError("SELECT 1", {}, ConnectionResetError("reset")),
        asyncpg.exceptions.AdminShutdownError("57P01"),
        sesion.BaseNoDisponible("x"),
    ],
)
def test_errores_de_la_base_o_la_red(error):
    assert sesion.es_fallo_de_base(error)


@pytest.mark.parametrize(
    "error",
    [
        # Un timeout de httpx (embeddings) cuya cadena lleva un OSError o un TimeoutError no es de la base.
        _con_causa(httpx.ConnectTimeout("t"), TimeoutError("t")),
        _con_causa(httpx.ConnectError("c"), ConnectionRefusedError("c")),
        _con_causa(ErrorApi(503, "EMBEDDING_NO_DISPONIBLE"), OSError("red")),
        TimeoutError("asyncio.timeout suelto"),
        sa_exc.IntegrityError("INSERT", {}, Exception("duplicada")),
        FileNotFoundError("migrations"),
        ValueError("otro"),
    ],
)
def test_otros_errores_no_son_de_la_base(error):
    assert not sesion.es_fallo_de_base(error)


def test_transaccion_convierte_el_fallo_al_abrir():
    ajustes = Settings(
        db_host="127.0.0.1",
        db_port=1,
        db_name="n",
        db_user="u",
        db_password=SecretStr("p"),
        db_sslmode="disable",
        db_connect_timeout_s=2,
    )

    async def probar():
        motor = sesion.crear_motor(ajustes, "pruebas")
        try:
            async with sesion.transaccion(motor):
                pytest.fail("no debería entrar")
        finally:
            await motor.dispose()

    with pytest.raises(sesion.BaseNoDisponible):
        asyncio.run(probar())
