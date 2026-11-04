"""Localización (ARCHITECTURE §4.10, §5.3 `POST /v1/localize`), BE-3.2, y corrección visual (§4.14, §5.3
`POST /v1/localize/frame`), BE-5.1.

`localizar(motor, ajustes, fotos, rumbos, *, origen, app_version, inicio, request_id=None, vectorizar=None)` →
`ResultadoLocalizar`:
1. Vectoriza las 1–5 fotos en **una** llamada a `POST /v1/embed` con prioridad `alta`, con un tope total de
   `TOPE_EMBEDDING_S` (el de BE-2.4: los plazos de httpx son por fase, §4.6).
2. Compara la `version_vector` devuelta con `EMBEDDING_VERSION_VECTOR`: si no coincide, `VersionVectorDistinta` (no
   se busca con un vector incomparable).
3. En **una** transacción: `db.consultas.buscar_vecinos` (un vector por foto, `LOC_TOP_K`, `LOC_EF_SEARCH`), el
   algoritmo de `dominio.localizacion` (Python puro, microsegundos), los lugares (`lugares.leer_todos`, solo si hay
   posición) y la fila anónima de `eventos_localizacion` (§5.7). Si la escritura o el `COMMIT` fallan, la petición
   responde `503 BASE_NO_DISPONIBLE`: la respuesta y la tabla no se contradicen.

`localizar_frame(motor, ajustes, foto, rumbo, *, lat, lng, radio_m, app_version, inicio, request_id=None,
vectorizar=None)` → `ResultadoFrame` (BE-5.1): los mismos pasos con **una** foto, salvo que la búsqueda es
`db.consultas.buscar_vecinos_en_radio` (exacta, solo imágenes a ≤ `radio_m` de (`lat`, `lng`), ADR-BE-21), añade
`distancia_previa_m` (de la posición previa a la calculada) e `imagenes_en_radio`, y el evento lleva `origen = frame`.

Las fotos no se guardan en ningún sitio ni se registran (ADR-BE-06). Excepciones (las traduce el router, §5.3):
`EmbeddingNoDisponible`, `ImagenRechazada` y `RespuestaNoValida` de `app.clientes.embedding`,
`servicios.diagnostico.VersionVectorDistinta` y `BaseNoDisponible` (de `sesion.transaccion`).
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass

import anyio
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.clientes import embedding
from app.config import Settings
from app.db import consultas, sesion
from app.db.modelos import EventoLocalizacion
from app.dominio import geo, localizacion
from app.dominio.enumerados import OrigenLocalizacion
from app.esquemas.localizacion import DECIMALES_EVENTO
from app.servicios import lugares
from app.servicios.diagnostico import TOPE_EMBEDDING_S, Vectorizar, VersionVectorDistinta

__all__ = [
    "ResultadoFrame",
    "ResultadoLocalizar",
    "VersionVectorDistinta",
    "localizar",
    "localizar_frame",
    "parametros_de",
]


@dataclass(frozen=True)
class ResultadoLocalizar:
    localizacion: localizacion.Localizacion
    lugar_cercano: localizacion.LugarContexto | None
    referencias: list[localizacion.LugarContexto]
    version_vector: str
    embedding_ms: int
    busqueda_ms: int
    latencia_ms: int


@dataclass(frozen=True)
class ResultadoFrame:
    """BE-5.1. `distancia_previa_m` (sin redondear) es `None` sin posición; `radio_busqueda_m` es el radio usado."""

    localizacion: localizacion.Localizacion
    lugar_cercano: localizacion.LugarContexto | None
    referencias: list[localizacion.LugarContexto]
    distancia_previa_m: float | None
    radio_busqueda_m: float
    imagenes_en_radio: int
    version_vector: str
    embedding_ms: int
    busqueda_ms: int
    latencia_ms: int


def parametros_de(ajustes: Settings) -> localizacion.Parametros:
    """Los `LOC_*` de §5.10 que usa el algoritmo."""
    return localizacion.Parametros(
        sim_min=ajustes.loc_sim_min,
        sim_alta=ajustes.loc_sim_alta,
        radio_grupo_m=ajustes.loc_radio_grupo_m,
        peso_exponente=ajustes.loc_peso_exponente,
        radio_min_m=ajustes.loc_radio_min_m,
        nivel_alta_min=ajustes.loc_nivel_alta_min,
        nivel_media_min=ajustes.loc_nivel_media_min,
        dispersion_rumbo_max=ajustes.loc_dispersion_rumbo_max,
        lugar_cercano_m=ajustes.loc_lugar_cercano_m,
        referencias_m=ajustes.loc_referencias_m,
        referencias_max=ajustes.loc_referencias_max,
    )


def _ms(desde: float) -> int:
    return max(0, int((time.perf_counter() - desde) * 1000))


async def _vectorizar(
    ajustes: Settings, fotos: Sequence[bytes], *, request_id: str | None, vectorizar: Vectorizar | None
) -> tuple[embedding.Vectores, int]:
    """Pasos 1 y 2: **una** llamada a embeddings (prioridad `alta`, tope `TOPE_EMBEDDING_S`) y la versión comprobada.
    Devuelve los vectores y `embedding_ms`."""

    async def por_defecto(imagenes: Sequence[bytes]) -> embedding.Vectores:
        return await embedding.vectorizar(ajustes, imagenes, prioridad="alta", request_id=request_id)

    llamar = vectorizar or por_defecto
    marca = time.perf_counter()
    try:
        with anyio.fail_after(TOPE_EMBEDDING_S):
            vectores = await llamar(list(fotos))
    except TimeoutError:
        raise embedding.EmbeddingNoDisponible(f"sin respuesta en {TOPE_EMBEDDING_S:g} s (tope total)") from None
    embedding_ms = _ms(marca)
    if vectores.version_vector != ajustes.embedding_version_vector:
        raise VersionVectorDistinta(ajustes.embedding_version_vector, vectores.version_vector)
    return vectores, embedding_ms


async def _contexto(
    conexion: AsyncConnection, resultado: localizacion.Localizacion, parametros: localizacion.Parametros
) -> tuple[localizacion.LugarContexto | None, list[localizacion.LugarContexto]]:
    """Paso 9: lugar cercano y referencias, solo si hay posición (si no, no se leen los lugares)."""
    if resultado.posicion is None:
        return None, []
    return localizacion.contexto(resultado.posicion, await lugares.leer_todos(conexion), parametros)


async def _guardar_evento(
    conexion: AsyncConnection,
    ajustes: Settings,
    resultado: localizacion.Localizacion,
    *,
    origen: str,
    app_version: str | None,
    latencia_ms: int,
) -> None:
    """Paso 10: la fila anónima de `eventos_localizacion` (§5.7), en la transacción de la búsqueda."""
    pos = resultado.posicion
    await conexion.execute(
        insert(EventoLocalizacion).values(
            origen=origen,
            resultado=str(resultado.resultado),
            nivel=None if resultado.nivel is None else str(resultado.nivel),
            confianza=resultado.confianza,
            lat=None if pos is None else round(pos.lat, DECIMALES_EVENTO),
            lng=None if pos is None else round(pos.lng, DECIMALES_EVENTO),
            fotos_usadas=resultado.fotos_usadas,
            fotos_con_coincidencia=resultado.fotos_con_coincidencia,
            latencia_ms=latencia_ms,
            version_vector=ajustes.embedding_version_vector,
            app_version=app_version,
        )
    )


async def localizar(
    motor: AsyncEngine,
    ajustes: Settings,
    fotos: Sequence[bytes],
    rumbos: Sequence[float | None],
    *,
    origen: str,
    app_version: str | None,
    inicio: float,
    request_id: str | None = None,
    vectorizar: Vectorizar | None = None,
) -> ResultadoLocalizar:
    """Lo del docstring del módulo. `inicio` es el `time.perf_counter()` del principio del endpoint (para
    `latencia_ms`); `vectorizar` sustituye a `embedding.vectorizar` en las pruebas."""
    vectores, embedding_ms = await _vectorizar(ajustes, fotos, request_id=request_id, vectorizar=vectorizar)
    parametros = parametros_de(ajustes)
    marca = time.perf_counter()
    async with sesion.transaccion(motor) as conexion:
        vecinos = await consultas.buscar_vecinos(
            conexion,
            vectores.vectores,
            k=ajustes.loc_top_k,
            version_vector=ajustes.embedding_version_vector,
            ef_search=ajustes.loc_ef_search,
        )
        resultado = localizacion.localizar(vecinos, rumbos, parametros)
        cercano, referencias = await _contexto(conexion, resultado, parametros)
        busqueda_ms = _ms(marca)
        latencia_ms = _ms(inicio)
        await _guardar_evento(
            conexion, ajustes, resultado, origen=origen, app_version=app_version, latencia_ms=latencia_ms
        )
    return ResultadoLocalizar(
        localizacion=resultado,
        lugar_cercano=cercano,
        referencias=referencias,
        version_vector=ajustes.embedding_version_vector,
        embedding_ms=embedding_ms,
        busqueda_ms=busqueda_ms,
        latencia_ms=latencia_ms,
    )


async def localizar_frame(
    motor: AsyncEngine,
    ajustes: Settings,
    foto: bytes,
    rumbo: float | None,
    *,
    lat: float,
    lng: float,
    radio_m: float,
    app_version: str | None,
    inicio: float,
    request_id: str | None = None,
    vectorizar: Vectorizar | None = None,
) -> ResultadoFrame:
    """BE-5.1 (docstring del módulo). (`lat`, `lng`) es la posición previa y `radio_m` el radio ya decidido por el
    router (el enviado o `LOC_FRAME_RADIO_M`). El evento lleva `origen = frame`."""
    vectores, embedding_ms = await _vectorizar(ajustes, [foto], request_id=request_id, vectorizar=vectorizar)
    parametros = parametros_de(ajustes)
    marca = time.perf_counter()
    async with sesion.transaccion(motor) as conexion:
        vecinos, en_radio = await consultas.buscar_vecinos_en_radio(
            conexion,
            vectores.vectores[0],
            lat=lat,
            lng=lng,
            radio_m=radio_m,
            k=ajustes.loc_top_k,
            version_vector=ajustes.embedding_version_vector,
        )
        resultado = localizacion.localizar([vecinos], [rumbo], parametros)
        cercano, referencias = await _contexto(conexion, resultado, parametros)
        pos = resultado.posicion
        distancia = None if pos is None else geo.distancia_m(lat, lng, pos.lat, pos.lng)
        busqueda_ms = _ms(marca)
        latencia_ms = _ms(inicio)
        await _guardar_evento(
            conexion,
            ajustes,
            resultado,
            origen=OrigenLocalizacion.frame.value,
            app_version=app_version,
            latencia_ms=latencia_ms,
        )
    return ResultadoFrame(
        localizacion=resultado,
        lugar_cercano=cercano,
        referencias=referencias,
        distancia_previa_m=distancia,
        radio_busqueda_m=radio_m,
        imagenes_en_radio=en_radio,
        version_vector=ajustes.embedding_version_vector,
        embedding_ms=embedding_ms,
        busqueda_ms=busqueda_ms,
        latencia_ms=latencia_ms,
    )
