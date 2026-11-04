"""BE-3.3 sin base: reglas de `dominio.alertas`, esquemas de `esquemas.alertas` (ARCHITECTURE §5.3, §5.5) y el bucle
de la limpieza diaria de *tombstones* (§4.11)."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.db import sesion
from app.dominio import alertas as dominio
from app.dominio.enumerados import PrioridadAlerta, TipoAlerta
from app.esquemas.alertas import AlertaEntrada, Cambio, SincronizarPeticion
from app.servicios import alertas as servicio

AHORA = datetime(2026, 10, 26, 15, 0, 0, 500_000, tzinfo=UTC)


def entrada(**cambios) -> dict:
    return {"lat": 6.2011, "lng": -75.579, "mensaje": "Ten cuidado, hay un lago"} | cambios


def campos_con_error(error: ValidationError) -> set[str]:
    return {".".join(str(p) for p in e["loc"]) for e in error.errors()}


# --- If-Match ------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize(("texto", "version"), [("3", 3), ('"3"', 3), ("  12 ", 12), ('"2147483647"', 2_147_483_647)])
def test_if_match_admite_el_entero_solo_o_entre_comillas(texto, version):
    assert dominio.leer_if_match(texto) == version


@pytest.mark.parametrize("texto", ["", "0", "*", "-1", "3.0", 'W/"3"', '"3', '3"', '"1", "2"', "2147483648", "abc"])
def test_if_match_no_valido(texto):
    with pytest.raises(ValueError, match="versión de la alerta"):
        dominio.leer_if_match(texto)


# --- Diferencias ----------------------------------------------------------------------------------------------------
def test_foto_completa_sin_desde_con_desde_futuro_o_mas_viejo_que_los_tombstones():
    assert dominio.pide_foto_completa(None, AHORA, 90)
    assert dominio.pide_foto_completa(AHORA + timedelta(seconds=1), AHORA, 90)
    assert not dominio.pide_foto_completa(AHORA.replace(microsecond=0), AHORA, 90)  # un generado_en recién salido
    limite = AHORA - timedelta(days=90) + timedelta(seconds=dominio.MARGEN_DESDE_S)
    assert not dominio.pide_foto_completa(limite, AHORA, 90)
    assert dominio.pide_foto_completa(limite - timedelta(seconds=1), AHORA, 90)


def test_el_corte_tiene_el_margen():
    assert dominio.corte_desde(AHORA) == AHORA - timedelta(seconds=60) and dominio.MARGEN_DESDE_S == 60


def test_campos_cambiados_en_el_orden_de_la_auditoria():
    guardado = SimpleNamespace(**AlertaEntrada.model_validate(entrada()).valores())
    nuevo = AlertaEntrada.model_validate(entrada(radio_m=20, mensaje="otro", tipo="agua")).valores()
    assert dominio.campos_cambiados(guardado, nuevo) == ["mensaje", "tipo", "radio_m"]
    assert dominio.campos_cambiados(guardado, AlertaEntrada.model_validate(entrada()).valores()) == []
    assert tuple(AlertaEntrada.model_fields) == dominio.CAMPOS


@pytest.mark.parametrize(
    ("q", "esperado"),
    [(None, True), ("", True), ("   ", True), ("LAGO", True), ("cuidádo,  HAY", True), ("validacion-", False)],
)
def test_coincide_sin_tildes_ni_mayusculas(q, esperado):
    assert dominio.coincide("Ten cuidado, hay un lago", q) is esperado


# --- AlertaEntrada --------------------------------------------------------------------------------------------------
def test_alerta_entrada_valores_por_defecto_y_recorte():
    datos = AlertaEntrada.model_validate(entrada(mensaje="  hola  ", id=str(uuid.uuid4()), version=7, extra=1))
    assert datos.valores() == {
        "lat": 6.2011,
        "lng": -75.579,
        "mensaje": "hola",
        "tipo": TipoAlerta.otro,
        "prioridad": PrioridadAlerta.normal,
        "radio_m": 15,
        "activa": True,
        "vigencia_desde": None,
        "vigencia_hasta": None,
    }


def test_null_es_el_valor_por_defecto():
    datos = AlertaEntrada.model_validate(entrada(tipo=None, prioridad=None, radio_m=None, activa=None))
    assert (datos.tipo, datos.prioridad, datos.radio_m, datos.activa) == (
        TipoAlerta.otro,
        PrioridadAlerta.normal,
        15,
        True,
    )


@pytest.mark.parametrize(
    ("cambios", "campo"),
    [
        ({"mensaje": "   "}, "mensaje"),
        ({"mensaje": "x" * 201}, "mensaje"),
        ({"mensaje": "a\x00b"}, "mensaje"),
        ({"radio_m": 4}, "radio_m"),
        ({"radio_m": 101}, "radio_m"),
        ({"radio_m": 15.5}, "radio_m"),
        ({"lat": 91}, "lat"),
        ({"lng": float("nan")}, "lng"),
        ({"tipo": "charco"}, "tipo"),
        ({"prioridad": "urgente"}, "prioridad"),
        ({"vigencia_desde": "2026-10-28T10:00:00"}, "vigencia_desde"),  # sin zona
        ({"vigencia_desde": "2026-10-28T10:00:00Z", "vigencia_hasta": "2026-10-28T10:00:00Z"}, "vigencia_hasta"),
        ({"vigencia_desde": "2026-10-28T10:00:00.2Z", "vigencia_hasta": "2026-10-28T10:00:00.7Z"}, "vigencia_hasta"),
    ],
)
def test_alerta_entrada_no_valida(cambios, campo):
    with pytest.raises(ValidationError) as error:
        AlertaEntrada.model_validate(entrada(**cambios))
    assert campos_con_error(error.value) == {campo}


def test_vigencias_en_utc_sin_fracciones():
    datos = AlertaEntrada.model_validate(
        entrada(vigencia_desde="2026-10-28T10:00:00.9-05:00", vigencia_hasta="2026-10-29T00:00:00Z", mensaje="x" * 200)
    )
    assert datos.vigencia_desde == datetime(2026, 10, 28, 15, 0, 0, tzinfo=UTC)
    assert datos.vigencia_hasta == datetime(2026, 10, 29, 0, 0, 0, tzinfo=UTC)


def test_mensaje_con_espacios_internos_se_conserva():
    assert AlertaEntrada.model_validate(entrada(mensaje=" a   b ")).mensaje == "a   b"


# --- sincronizar ---------------------------------------------------------------------------------------------------
def test_cambios_validos_y_el_resto_de_la_alerta_sin_validar():
    a, b = uuid.uuid4(), uuid.uuid4()
    peticion = SincronizarPeticion.model_validate(
        {
            "cambios": [
                {"op": "upsert", "alerta": {"id": str(a), "radio_m": 500, "mensaje": ""}},
                {"op": "eliminar", "id": str(b), "alerta": None},
            ]
        }
    )
    upsert, eliminar = peticion.cambios
    assert (upsert.alerta_id, eliminar.alerta_id) == (a, b)
    assert upsert.alerta.entrada() == {"radio_m": 500, "mensaje": ""}  # se valida cambio por cambio, en el servicio


@pytest.mark.parametrize(
    ("cambio", "campo"),
    [
        ({"op": "crear", "id": str(uuid.uuid4())}, "cambios.0.op"),
        ({"id": str(uuid.uuid4())}, "cambios.0.op"),
        ({"op": "upsert"}, "cambios.0"),
        ({"op": "eliminar"}, "cambios.0"),
        ({"op": "eliminar", "id": "no-es-uuid"}, "cambios.0.id"),
        ({"op": "upsert", "alerta": {"mensaje": "sin id"}}, "cambios.0.alerta.id"),
        ({"op": "upsert", "alerta": "texto"}, "cambios.0.alerta"),
    ],
)
def test_sobre_no_valido_es_422_de_la_peticion(cambio, campo):
    with pytest.raises(ValidationError) as error:
        SincronizarPeticion.model_validate({"cambios": [cambio]})
    assert campos_con_error(error.value) == {campo}


@pytest.mark.parametrize("n", [0, 101])
def test_entre_1_y_100_cambios(n):
    cambios = [{"op": "eliminar", "id": str(uuid.uuid4())} for _ in range(n)]
    with pytest.raises(ValidationError) as error:
        SincronizarPeticion.model_validate({"cambios": cambios})
    assert campos_con_error(error.value) == {"cambios"}
    if cambios:
        assert len(SincronizarPeticion.model_validate({"cambios": cambios[:100]}).cambios) == 100


def test_cambio_upsert_con_id_de_mas_usa_el_de_la_alerta():
    a, otro = uuid.uuid4(), uuid.uuid4()
    cambio = Cambio.model_validate({"op": "upsert", "id": str(otro), "alerta": {"id": str(a)}})
    assert cambio.alerta_id == a


# --- Limpieza diaria -----------------------------------------------------------------------------------------------
class Parar(Exception):
    pass


def test_limpieza_diaria_espera_purga_cada_intervalo_y_sigue_tras_un_fallo(logs_json):
    esperas: list[float] = []
    llamadas: list[int] = []
    resultados = [3, sesion.BaseNoDisponible("ConnectionRefusedError: sin base"), RuntimeError("raro"), 0]

    async def dormir(segundos: float) -> None:
        esperas.append(segundos)
        if len(esperas) > len(resultados):
            raise Parar

    async def purgar(motor, dias: int) -> int:
        llamadas.append(dias)
        resultado = resultados[len(llamadas) - 1]
        if isinstance(resultado, Exception):
            raise resultado
        return resultado

    with pytest.raises(Parar):
        asyncio.run(servicio.limpieza_diaria(object(), 90, dormir=dormir, purgar=purgar))
    assert esperas == [60.0, 86400.0, 86400.0, 86400.0, 86400.0]
    assert llamadas == [90, 90, 90, 90]
    propios = ("alertas_purgadas", "limpieza_fallida")
    eventos = [(linea["evento"], linea["nivel"]) for linea in logs_json.lineas if linea["evento"] in propios]
    assert eventos == [
        ("alertas_purgadas", "INFO"),
        ("limpieza_fallida", "WARNING"),
        ("limpieza_fallida", "ERROR"),
        ("alertas_purgadas", "INFO"),
    ]
    purgadas = [linea for linea in logs_json.lineas if linea["evento"] == "alertas_purgadas"]
    assert [(p["borradas"], p["dias"]) for p in purgadas] == [(3, 90), (0, 90)]
    fallidas = [linea for linea in logs_json.lineas if linea["evento"] == "limpieza_fallida"]
    assert fallidas[0]["tarea"] == "tombstones_alertas" and "sin base" in fallidas[0]["motivo"]
    assert "excepcion" in fallidas[1] and "RuntimeError" in fallidas[1]["motivo"]


def test_la_limpieza_se_cancela_sin_ruido(logs_json):
    async def principal() -> None:
        tarea = asyncio.create_task(servicio.limpieza_diaria(object(), 90, espera_inicial_s=3600))
        await asyncio.sleep(0)
        tarea.cancel()
        with pytest.raises(asyncio.CancelledError):
            await tarea

    asyncio.run(principal())
    assert [linea for linea in logs_json.lineas if "limpieza" in linea["evento"] or "purgadas" in linea["evento"]] == []
