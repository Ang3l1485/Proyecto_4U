"""Algoritmo de localización v1 (ARCHITECTURE §4.10, ADR-BE-08, ADR-BE-18), BE-3.2. Python puro (regla de `dominio/`,
§4.1): recibe los vecinos de cada foto (lo que devuelve `db.consultas.buscar_vecinos`) y los rumbos de la consulta, y
devuelve la posición, la confianza, el nivel y la corrección de rumbo. El contexto (lugar cercano y referencias) va
aparte, en `contexto`, porque necesita los lugares de la base.

Pasos (los de §4.10, con los detalles que fija ADR-BE-18):
3. `coincidencias`: vecinos con `similitud ≥ LOC_SIM_MIN`, recorridos de mayor a menor similitud. A igualdad, el orden
   de llegada: foto 0, 1… y, dentro de cada foto, el orden de `buscar_vecinos` (orden estable de `sorted`).
4. `agrupar`: cada coincidencia entra en el **primer** grupo (por orden de creación) cuyo centroide esté a menos de
   `LOC_RADIO_GRUPO_M` (`geo.distancia_m`, estrictamente menor), o abre uno nuevo. Centroide = media **sin ponderar**
   de la latitud y de la longitud de sus miembros, recalculada al añadir cada uno (decisión del maestro, a confirmar por
   el usuario: la misma que simula EMB-3.2).
5. Puntuación de un grupo = suma, por cada foto de la consulta, de la mejor similitud que esa foto aporta al grupo. El
   mejor grupo es el de mayor puntuación; a igualdad, el creado antes.
6. Posición = media de latitud y longitud de los miembros del mejor grupo ponderada por `similitud ^
   LOC_PESO_EXPONENTE`. Radio = raíz de la media ponderada (mismos pesos) del cuadrado de la distancia de cada miembro a
   la posición, con mínimo `LOC_RADIO_MIN_M`.
7. Confianza = `0,5·s + 0,3·c + 0,2·m`: `s` = (mejor similitud del grupo − `LOC_SIM_MIN`) / (`LOC_SIM_ALTA` −
   `LOC_SIM_MIN`) acotada a [0, 1] (1 si `LOC_SIM_ALTA` ≤ `LOC_SIM_MIN`); `c` = fotos con alguna coincidencia en el
   grupo / fotos de la consulta; `m` = (p₁ − p₂) / p₁ con p₁ y p₂ las dos mejores puntuaciones (1 con un solo grupo;
   decisión del maestro, a confirmar por el usuario). Se **trunca** a 2 decimales (`DECIMALES_CONFIANZA`) y el nivel se
   decide con el valor truncado: `alta` ≥ `LOC_NIVEL_ALTA_MIN`, `media` ≥ `LOC_NIVEL_MEDIA_MIN`, si no `baja`.
8. Corrección de rumbo: por cada foto con rumbo informado y alguna coincidencia del mejor grupo **con rumbo**, la de
   mayor similitud da la diferencia `rumbo del dataset − rumbo del teléfono`, llevada a (−180, 180]. Con ≥ 2
   diferencias y desviación estándar circular `√(−2·ln R)` ≤ `LOC_DISPERSION_RUMBO_MAX` (R = longitud media del
   resultante), la corrección es su media circular; si no, `None`.

Sin coincidencias tras el filtro (o con el índice vacío): `resultado = sin_coincidencias`, confianza 0 y sin posición.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol

from app.dominio import geo
from app.dominio.enumerados import NivelConfianza, ResultadoLocalizacion

#: Cifras decimales de `confianza` (se trunca, no se redondea: así una confianza mostrada nunca cruza un corte).
DECIMALES_CONFIANZA = 2


class VecinoBuscado(Protocol):
    """Lo que el algoritmo lee de cada vecino (`db.consultas.Vecino` lo cumple)."""

    lat: float
    lng: float
    similitud: float
    rumbo: float | None


class LugarConPosicion(Protocol):
    """Lo que `contexto` lee de cada lugar (`servicios.lugares.LugarRef` lo cumple)."""

    lat: float
    lng: float


@dataclass(frozen=True)
class Parametros:
    """Los parámetros `LOC_*` de §5.10 que usa el algoritmo (los da `Settings`; ver `servicios.localizar`)."""

    sim_min: float = 0.55
    sim_alta: float = 0.80
    radio_grupo_m: float = 20.0
    peso_exponente: float = 4.0
    radio_min_m: float = 5.0
    nivel_alta_min: float = 0.70
    nivel_media_min: float = 0.45
    dispersion_rumbo_max: float = 30.0
    lugar_cercano_m: float = 60.0
    referencias_m: float = 150.0
    referencias_max: int = 3


@dataclass(frozen=True)
class Coincidencia:
    """Un vecino que pasó el umbral, con la foto de la consulta (índice 0…n−1) que lo trajo."""

    foto: int
    lat: float
    lng: float
    similitud: float
    rumbo: float | None


@dataclass
class Grupo:
    """Coincidencias cercanas entre sí. `lat`/`lng` = centroide sin ponderar (media de sus miembros)."""

    miembros: list[Coincidencia] = field(default_factory=list)
    lat: float = 0.0
    lng: float = 0.0

    def anadir(self, coincidencia: Coincidencia) -> None:
        self.miembros.append(coincidencia)
        n = len(self.miembros)
        self.lat = sum(m.lat for m in self.miembros) / n
        self.lng = sum(m.lng for m in self.miembros) / n

    def mejor_por_foto(self) -> dict[int, float]:
        mejores: dict[int, float] = {}
        for m in self.miembros:
            if m.similitud > mejores.get(m.foto, -math.inf):
                mejores[m.foto] = m.similitud
        return mejores

    @property
    def puntuacion(self) -> float:
        return sum(self.mejor_por_foto().values())

    @property
    def fotos(self) -> set[int]:
        return {m.foto for m in self.miembros}

    @property
    def similitud_max(self) -> float:
        return max(m.similitud for m in self.miembros)


@dataclass(frozen=True)
class Posicion:
    lat: float
    lng: float
    radio_m: float


@dataclass(frozen=True)
class Localizacion:
    """Resultado del algoritmo (valores sin redondear, salvo `confianza`, ya truncada)."""

    resultado: ResultadoLocalizacion
    posicion: Posicion | None
    confianza: float
    nivel: NivelConfianza | None
    correccion_rumbo_grados: float | None
    fotos_usadas: int
    fotos_con_coincidencia: int
    coincidencias: int
    grupos: int
    similitud_max: float | None
    s: float = 0.0
    c: float = 0.0
    m: float = 0.0


@dataclass(frozen=True)
class LugarContexto:
    """Un lugar cerca de la posición: el objeto original (`LugarRef`), su distancia (m) y el rumbo desde la posición."""

    lugar: LugarConPosicion
    distancia_m: float
    rumbo_grados: float


# --- Pasos ----------------------------------------------------------------------------------------------------------
def coincidencias(vecinos_por_foto: Sequence[Sequence[VecinoBuscado]], sim_min: float) -> list[Coincidencia]:
    """Paso 3: los vecinos con `similitud ≥ sim_min`, de mayor a menor similitud (a igualdad, orden de llegada)."""
    todas = [
        Coincidencia(foto=i, lat=v.lat, lng=v.lng, similitud=v.similitud, rumbo=v.rumbo)
        for i, vecinos in enumerate(vecinos_por_foto)
        for v in vecinos
        if v.similitud >= sim_min
    ]
    return sorted(todas, key=lambda c: -c.similitud)


def agrupar(coincidencias_ordenadas: Sequence[Coincidencia], radio_m: float) -> list[Grupo]:
    """Paso 4: el primer grupo cuyo centroide está a menos de `radio_m`, o uno nuevo. Grupos en orden de creación."""
    grupos: list[Grupo] = []
    for coincidencia in coincidencias_ordenadas:
        destino = next(
            (g for g in grupos if geo.distancia_m(g.lat, g.lng, coincidencia.lat, coincidencia.lng) < radio_m), None
        )
        if destino is None:
            destino = Grupo()
            grupos.append(destino)
        destino.anadir(coincidencia)
    return grupos


def mejor_grupo(grupos: Sequence[Grupo]) -> tuple[Grupo, float, float | None]:
    """Paso 5: `(mejor grupo, p₁, p₂)`; a igualdad de puntuación, el creado antes. `p₂ = None` con un solo grupo."""
    puntuaciones = [g.puntuacion for g in grupos]
    indice = 0
    for i, p in enumerate(puntuaciones):
        if p > puntuaciones[indice]:
            indice = i
    resto = [p for i, p in enumerate(puntuaciones) if i != indice]
    return grupos[indice], puntuaciones[indice], (max(resto) if resto else None)


def posicion(grupo: Grupo, peso_exponente: float, radio_min_m: float) -> Posicion:
    """Paso 6: media ponderada por `similitud ^ peso_exponente` y radio (desviación ponderada, mínimo `radio_min_m`)."""
    pesos = [max(m.similitud, 0.0) ** peso_exponente for m in grupo.miembros]
    total = sum(pesos)
    if total <= 0:  # solo con un LOC_SIM_MIN ≤ 0: sin pesos, el centroide sin ponderar
        pesos, total = [1.0] * len(grupo.miembros), float(len(grupo.miembros))
    lat = sum(w * m.lat for w, m in zip(pesos, grupo.miembros, strict=True)) / total
    lng = sum(w * m.lng for w, m in zip(pesos, grupo.miembros, strict=True)) / total
    varianza = sum(w * geo.distancia_m(lat, lng, m.lat, m.lng) ** 2 for w, m in zip(pesos, grupo.miembros, strict=True))
    return Posicion(lat=lat, lng=lng, radio_m=max(math.sqrt(varianza / total), radio_min_m))


def truncar_confianza(valor: float) -> float:
    """Trunca a `DECIMALES_CONFIANZA` decimales en [0, 1]. El `round(…, 6)` previo evita que 0,29 (28,999999…·0,01 en
    coma flotante) se trunque a 0,28."""
    escala = 10**DECIMALES_CONFIANZA
    return min(1.0, max(0.0, math.floor(round(valor * escala, 6)) / escala))


def nivel_de(confianza: float, parametros: Parametros) -> NivelConfianza:
    if confianza >= parametros.nivel_alta_min:
        return NivelConfianza.alta
    if confianza >= parametros.nivel_media_min:
        return NivelConfianza.media
    return NivelConfianza.baja


def diferencia_angular(a: float, b: float) -> float:
    """`a − b` llevada a (−180, 180]."""
    d = (a - b) % 360.0
    return d - 360.0 if d > 180.0 else d


def correccion_rumbo(grupo: Grupo, rumbos: Sequence[float | None], dispersion_max: float) -> float | None:
    """Paso 8: media circular de las diferencias `rumbo del dataset − rumbo del teléfono` (una por foto), o `None`."""
    diferencias: list[float] = []
    for foto in sorted(grupo.fotos):
        rumbo_telefono = rumbos[foto] if foto < len(rumbos) else None
        con_rumbo = [m for m in grupo.miembros if m.foto == foto and m.rumbo is not None]
        if rumbo_telefono is None or not con_rumbo:
            continue
        mejor = max(con_rumbo, key=lambda m: m.similitud)  # a igualdad, el primero (orden de agrupación)
        diferencias.append(diferencia_angular(mejor.rumbo, rumbo_telefono))
    if len(diferencias) < 2:
        return None
    seno = sum(math.sin(math.radians(d)) for d in diferencias) / len(diferencias)
    coseno = sum(math.cos(math.radians(d)) for d in diferencias) / len(diferencias)
    r = math.hypot(seno, coseno)
    if r <= 1e-12:
        return None
    dispersion = math.degrees(math.sqrt(max(0.0, -2.0 * math.log(min(1.0, r)))))
    if dispersion > dispersion_max:
        return None
    media = math.degrees(math.atan2(seno, coseno))
    return 180.0 if media <= -180.0 else media


def localizar(
    vecinos_por_foto: Sequence[Sequence[VecinoBuscado]], rumbos: Sequence[float | None], parametros: Parametros
) -> Localizacion:
    """Pasos 3–8 de §4.10 para una consulta de `len(vecinos_por_foto)` fotos."""
    fotos_usadas = len(vecinos_por_foto)
    ordenadas = coincidencias(vecinos_por_foto, parametros.sim_min)
    if not ordenadas or fotos_usadas == 0:
        return Localizacion(
            resultado=ResultadoLocalizacion.sin_coincidencias,
            posicion=None,
            confianza=0.0,
            nivel=None,
            correccion_rumbo_grados=None,
            fotos_usadas=fotos_usadas,
            fotos_con_coincidencia=0,
            coincidencias=0,
            grupos=0,
            similitud_max=None,
        )
    grupos = agrupar(ordenadas, parametros.radio_grupo_m)
    grupo, p1, p2 = mejor_grupo(grupos)
    rango = parametros.sim_alta - parametros.sim_min
    s = 1.0 if rango <= 0 else min(1.0, max(0.0, (grupo.similitud_max - parametros.sim_min) / rango))
    c = len(grupo.fotos) / fotos_usadas
    if p2 is None:
        m = 1.0
    else:
        m = (p1 - p2) / p1 if p1 > 0 else 0.0
    confianza = truncar_confianza(0.5 * s + 0.3 * c + 0.2 * m)
    return Localizacion(
        resultado=ResultadoLocalizacion.ok,
        posicion=posicion(grupo, parametros.peso_exponente, parametros.radio_min_m),
        confianza=confianza,
        nivel=nivel_de(confianza, parametros),
        correccion_rumbo_grados=correccion_rumbo(grupo, rumbos, parametros.dispersion_rumbo_max),
        fotos_usadas=fotos_usadas,
        fotos_con_coincidencia=len(grupo.fotos),
        coincidencias=len(ordenadas),
        grupos=len(grupos),
        similitud_max=ordenadas[0].similitud,
        s=s,
        c=c,
        m=m,
    )


def contexto(
    pos: Posicion, lugares: Sequence[LugarConPosicion], parametros: Parametros
) -> tuple[LugarContexto | None, list[LugarContexto]]:
    """Paso 9: el lugar más cercano a ≤ `LOC_LUGAR_CERCANO_M` y hasta `LOC_REFERENCIAS_MAX` referencias a ≤
    `LOC_REFERENCIAS_M`, sin repetir el cercano, por distancia (a igualdad, el orden de `lugares`: nombre normalizado
    e id, el de `leer_todos`). `rumbo_grados` = rumbo inicial desde la posición hacia el lugar, en [0, 360)."""
    medidos = sorted(
        (
            LugarContexto(
                lugar=lugar,
                distancia_m=geo.distancia_m(pos.lat, pos.lng, lugar.lat, lugar.lng),
                rumbo_grados=geo.rumbo_grados(pos.lat, pos.lng, lugar.lat, lugar.lng),
            )
            for lugar in lugares
        ),
        key=lambda x: x.distancia_m,
    )
    cercano = medidos[0] if medidos and medidos[0].distancia_m <= parametros.lugar_cercano_m else None
    referencias = [x for x in medidos if x is not cercano and x.distancia_m <= parametros.referencias_m][
        : max(0, parametros.referencias_max)
    ]
    return cercano, referencias
