"""Algoritmo de localización v1 (`app.dominio.localizacion`, ARCHITECTURE §4.10, ADR-BE-18): filtro, agrupamiento con
centroide sin ponderar, puntuación, margen, posición, confianza truncada, niveles, corrección de rumbo y contexto."""

from __future__ import annotations

import math
from dataclasses import dataclass

import pytest

from app.dominio import geo, localizacion
from app.dominio.enumerados import NivelConfianza, ResultadoLocalizacion
from app.dominio.localizacion import Coincidencia, Parametros

LAT0, LNG0 = 6.2, -75.58
M_POR_GRADO = geo.RADIO_TIERRA_M * math.pi / 180  # ~111 195 m por grado de latitud
P = Parametros()  # los valores iniciales de §5.10


@dataclass(frozen=True)
class V:
    """Un vecino como los de `db.consultas.Vecino` (solo lo que lee el algoritmo)."""

    lat: float
    lng: float
    similitud: float
    rumbo: float | None = None


def norte(metros: float) -> float:
    return LAT0 + metros / M_POR_GRADO


def v(metros_norte: float, similitud: float, rumbo: float | None = None) -> V:
    return V(norte(metros_norte), LNG0, similitud, rumbo)


@dataclass(frozen=True)
class Lugar:
    nombre: str
    lat: float
    lng: float


# --- Paso 3: filtro y orden -------------------------------------------------------------------------------------------
def test_filtra_por_sim_min_y_ordena_de_mayor_a_menor_con_desempate_por_llegada():
    vecinos = [[v(0, 0.70), v(1, 0.54)], [v(2, 0.90), v(3, 0.70)], [v(4, 0.55)]]
    ordenadas = localizacion.coincidencias(vecinos, 0.55)
    assert [(c.foto, c.similitud) for c in ordenadas] == [(1, 0.90), (0, 0.70), (1, 0.70), (2, 0.55)]


@pytest.mark.parametrize("vecinos", [[], [[]], [[], []], [[v(0, 0.54)], [v(5, 0.10)]]])
def test_sin_vecinos_sobre_el_umbral_es_sin_coincidencias(vecinos):
    r = localizacion.localizar(vecinos, [None] * len(vecinos), P)
    assert r.resultado is ResultadoLocalizacion.sin_coincidencias
    assert (r.posicion, r.nivel, r.correccion_rumbo_grados, r.confianza) == (None, None, None, 0.0)
    assert (r.fotos_usadas, r.fotos_con_coincidencia, r.coincidencias, r.grupos) == (len(vecinos), 0, 0, 0)


# --- Paso 4: agrupamiento ---------------------------------------------------------------------------------------------
def _c(metros: float, similitud: float, foto: int = 0, rumbo: float | None = None) -> Coincidencia:
    return Coincidencia(foto=foto, lat=norte(metros), lng=LNG0, similitud=similitud, rumbo=rumbo)


def test_el_centroide_es_la_media_sin_ponderar_recalculada_al_anadir():
    """A (0 m) abre el grupo; B (18 m) entra y el centroide pasa a 9 m; C (25 m) está a 16 m de ese centroide y entra.
    Con el centroide fijo en A (25 m ≥ 20) o ponderado por similitud⁴ (≈ 2,5 m → 22,5 m) C abriría otro grupo."""
    grupos = localizacion.agrupar([_c(0, 0.95), _c(18, 0.60), _c(25, 0.58)], 20.0)
    assert len(grupos) == 1 and len(grupos[0].miembros) == 3
    assert grupos[0].lat == pytest.approx(norte((0 + 18 + 25) / 3), abs=1e-12)
    assert grupos[0].lng == pytest.approx(LNG0)


def test_estrictamente_a_menos_del_radio():
    a, b = norte(0), norte(10)
    radio = geo.distancia_m(a, LNG0, b, LNG0)  # la distancia exacta entre los dos
    assert len(localizacion.agrupar([_c(0, 0.9), _c(10, 0.8)], radio)) == 2
    assert len(localizacion.agrupar([_c(0, 0.9), _c(10, 0.8)], radio + 1e-6)) == 1


def test_entra_en_el_primer_grupo_creado_aunque_otro_este_mas_cerca():
    grupos = localizacion.agrupar([_c(0, 0.9), _c(30, 0.85), _c(16, 0.8)], 20.0)
    assert [len(g.miembros) for g in grupos] == [2, 1]  # 16 m: a 16 del primero y a 14 del segundo
    assert grupos[0].miembros[-1].similitud == 0.8


# --- Paso 5: puntuación y mejor grupo --------------------------------------------------------------------------------
def test_la_puntuacion_suma_la_mejor_similitud_de_cada_foto():
    g = localizacion.Grupo()
    for c in (_c(0, 0.9, foto=0), _c(1, 0.8, foto=0), _c(2, 0.7, foto=1)):
        g.anadir(c)
    assert g.puntuacion == pytest.approx(1.6) and g.fotos == {0, 1} and g.similitud_max == 0.9


def test_a_igualdad_de_puntuacion_gana_el_creado_antes():
    grupos = localizacion.agrupar([_c(0, 0.8, foto=0), _c(100, 0.8, foto=1)], 20.0)
    mejor, p1, p2 = localizacion.mejor_grupo(grupos)
    assert mejor is grupos[0] and p1 == p2 == pytest.approx(0.8)


# --- Pasos 6 y 7: posición, confianza y nivel ------------------------------------------------------------------------
def test_un_solo_grupo_margen_1_y_radio_minimo():
    r = localizacion.localizar([[v(0, 0.80)]], [None], P)
    assert r.resultado is ResultadoLocalizacion.ok and r.grupos == 1
    assert (r.posicion.lat, r.posicion.lng) == (pytest.approx(norte(0)), pytest.approx(LNG0))
    assert r.posicion.radio_m == P.radio_min_m  # un miembro: desviación 0 → mínimo
    # s = (0,80 − 0,55) / (0,80 − 0,55) = 1; c = 1/1; m = 1 → 1,00
    assert (r.s, r.c, r.m, r.confianza, r.nivel) == (1.0, 1.0, 1.0, 1.0, NivelConfianza.alta)


def test_margen_entre_los_dos_mejores_grupos_y_fraccion_de_fotos():
    # foto 0 → grupo A (0 m, 0,70); foto 1 → grupo A (5 m, 0,65) y grupo B (100 m, 0,60); foto 2 sin vecinos
    vecinos = [[v(0, 0.70)], [v(5, 0.65), v(100, 0.60)], [v(300, 0.30)]]
    r = localizacion.localizar(vecinos, [None, None, None], P)
    p1, p2 = 0.70 + 0.65, 0.60
    s = (0.70 - 0.55) / (0.80 - 0.55)
    c = 2 / 3
    m = (p1 - p2) / p1
    assert (r.s, r.c, r.m) == (pytest.approx(s), pytest.approx(c), pytest.approx(m))
    assert r.confianza == math.floor((0.5 * s + 0.3 * c + 0.2 * m) * 100) / 100  # 0,61
    assert r.nivel is NivelConfianza.media
    assert (r.fotos_usadas, r.fotos_con_coincidencia, r.coincidencias, r.grupos) == (3, 2, 3, 2)
    assert r.similitud_max == 0.70


def test_posicion_ponderada_por_similitud_a_la_cuarta_y_radio_ponderado():
    r = localizacion.localizar([[v(0, 0.90), v(18, 0.60)]], [None], P)
    w0, w1 = 0.90**4, 0.60**4
    esperada = (w0 * norte(0) + w1 * norte(18)) / (w0 + w1)
    assert r.posicion.lat == pytest.approx(esperada, abs=1e-12)
    d0 = geo.distancia_m(esperada, LNG0, norte(0), LNG0)
    d1 = geo.distancia_m(esperada, LNG0, norte(18), LNG0)
    radio = math.sqrt((w0 * d0**2 + w1 * d1**2) / (w0 + w1))
    assert r.posicion.radio_m == pytest.approx(max(radio, P.radio_min_m))


def test_radio_con_dos_miembros_iguales_es_la_mitad_de_la_separacion():
    r = localizacion.localizar([[v(0, 0.7), v(18, 0.7)]], [None], P)
    assert r.posicion.lat == pytest.approx(norte(9)) and r.posicion.radio_m == pytest.approx(9.0, abs=1e-3)


def test_s_es_1_si_sim_alta_no_supera_sim_min():
    r = localizacion.localizar([[v(0, 0.56)]], [None], Parametros(sim_min=0.55, sim_alta=0.55))
    assert r.s == 1.0


@pytest.mark.parametrize(
    ("valor", "esperado"),
    [(0.29, 0.29), (0.6999, 0.69), (0.70, 0.70), (0.789, 0.78), (1.2, 1.0), (-0.1, 0.0), (0.0, 0.0)],
)
def test_la_confianza_se_trunca_a_dos_decimales(valor, esperado):
    assert localizacion.truncar_confianza(valor) == esperado


@pytest.mark.parametrize(
    ("confianza", "nivel"),
    [
        (0.70, NivelConfianza.alta),
        (0.69, NivelConfianza.media),
        (0.45, NivelConfianza.media),
        (0.44, NivelConfianza.baja),
    ],
)
def test_cortes_de_nivel(confianza, nivel):
    assert localizacion.nivel_de(confianza, P) is nivel


# --- Paso 8: corrección de rumbo -------------------------------------------------------------------------------------
def test_correccion_media_de_las_diferencias_con_dos_o_mas_fotos():
    vecinos = [[v(0, 0.9, rumbo=84.0)], [v(2, 0.8, rumbo=176.0)]]
    r = localizacion.localizar(vecinos, [90.0, 180.0], P)
    assert r.correccion_rumbo_grados == pytest.approx(-5.0)  # −6 y −4


def test_la_diferencia_pasa_por_el_norte():
    assert localizacion.diferencia_angular(355.0, 5.0) == pytest.approx(-10.0)
    assert localizacion.diferencia_angular(5.0, 355.0) == pytest.approx(10.0)
    assert localizacion.diferencia_angular(0.0, 180.0) == pytest.approx(180.0)  # (−180, 180]
    vecinos = [[v(0, 0.9, rumbo=355.0)], [v(2, 0.8, rumbo=5.0)]]
    r = localizacion.localizar(vecinos, [5.0, 355.0], P)  # −10 y +10: media 0, dispersión ~10°
    assert r.correccion_rumbo_grados == pytest.approx(0.0, abs=1e-9)


@pytest.mark.parametrize(
    ("rumbos_dataset", "rumbos_telefono"),
    [
        ((84.0,), (90.0,)),  # una sola foto
        ((84.0, 176.0), (90.0, None)),  # el teléfono no dio el rumbo de la segunda
        ((84.0, None), (90.0, 180.0)),  # la foto del dataset no tenía rumbo
        ((0.0, 90.0), (0.0, 0.0)),  # diferencias 0 y 90: dispersión ~49° > 30°
    ],
)
def test_sin_correccion(rumbos_dataset, rumbos_telefono):
    vecinos = [[v(i * 2, 0.9 - i * 0.1, rumbo=r)] for i, r in enumerate(rumbos_dataset)]
    r = localizacion.localizar(vecinos, list(rumbos_telefono), P)
    assert r.resultado is ResultadoLocalizacion.ok and r.correccion_rumbo_grados is None


def test_usa_la_mejor_coincidencia_con_rumbo_de_cada_foto():
    # foto 0: la mejor (0,95) sin rumbo → cuenta la siguiente con rumbo (0,90, diferencia −6); foto 1: −4
    vecinos = [[v(0, 0.95), v(1, 0.90, rumbo=84.0), v(2, 0.85, rumbo=0.0)], [v(3, 0.8, rumbo=176.0)]]
    r = localizacion.localizar(vecinos, [90.0, 180.0], P)
    assert r.correccion_rumbo_grados == pytest.approx(-5.0)


def test_solo_cuentan_las_fotos_del_mejor_grupo():
    # la foto 1 solo coincide con otro grupo (200 m): no aporta diferencia → una sola → None
    vecinos = [[v(0, 0.9, rumbo=84.0), v(3, 0.85, rumbo=84.0)], [v(200, 0.6, rumbo=176.0)]]
    r = localizacion.localizar(vecinos, [90.0, 180.0], P)
    assert r.fotos_con_coincidencia == 1 and r.correccion_rumbo_grados is None


# --- Paso 9: contexto -------------------------------------------------------------------------------------------------
def test_lugar_cercano_y_referencias_sin_repetirlo():
    pos = localizacion.Posicion(norte(0), LNG0, 5.0)
    lugares = [Lugar(f"L{d}", norte(d), LNG0) for d in (160, 10, 70, 40, 100, 140)]
    cercano, referencias = localizacion.contexto(pos, lugares, P)
    assert cercano.lugar.nombre == "L10" and cercano.distancia_m == pytest.approx(10.0, abs=1e-3)
    assert [r.lugar.nombre for r in referencias] == ["L40", "L70", "L100"]  # ≤ 150 m, como mucho 3
    assert all(r.rumbo_grados == pytest.approx(0.0, abs=1e-9) for r in referencias)  # al norte


def test_sin_lugar_a_60_m_las_referencias_empiezan_por_el_mas_cercano():
    pos = localizacion.Posicion(LAT0, LNG0, 5.0)
    este = Lugar("Este", LAT0, LNG0 + 80 / (M_POR_GRADO * math.cos(math.radians(LAT0))))
    lejos = Lugar("Lejos", norte(151), LNG0)
    cercano, referencias = localizacion.contexto(pos, [lejos, este], P)
    assert cercano is None and [r.lugar.nombre for r in referencias] == ["Este"]
    assert referencias[0].rumbo_grados == pytest.approx(90.0, abs=0.01)


def test_a_igualdad_de_distancia_manda_el_orden_de_los_lugares():
    pos = localizacion.Posicion(LAT0, LNG0, 5.0)
    a, b = Lugar("A", norte(20), LNG0), Lugar("B", norte(20), LNG0)
    cercano, referencias = localizacion.contexto(pos, [a, b], P)
    assert cercano.lugar is a and [r.lugar for r in referencias] == [b]


def test_sin_lugares():
    assert localizacion.contexto(localizacion.Posicion(LAT0, LNG0, 5.0), [], P) == (None, [])
