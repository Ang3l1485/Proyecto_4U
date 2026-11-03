"""BE-3.1 — Lugares. CRUD de `/v1/admin/places` visto también en `GET /v1/places`, orden por distancia y por nombre,
nombre único sin distinguir mayúsculas, tildes ni espacios (`409 NOMBRE_DUPLICADO`), validación y autenticación.

Documento: BACKEND_FASTAPI/docs/validation/validation-3-1.md · criterios: BACKEND_FASTAPI/docs/PLAN.md §2.2.

    cd BACKEND_FASTAPI/project
    uv run --group ops python src/ops/validate31.py --entorno dev
    uv run --group ops python src/ops/validate31.py --entorno local   # con docker compose (db y api) en marcha

Variables: AWS_PROFILE (obligatoria en dev); VALIDACION_API_URL, VALIDACION_ADMIN_CORREO y VALIDACION_ADMIN_PASSWORD
(opcionales en dev, obligatorias en local). Crea lugares `validacion-31-<AAAAMMDD-HHMMSS> …` en (0.001, 0.001), fuera
del campus, y los borra al terminar. Nunca imprime contraseñas ni tokens.
"""

from __future__ import annotations

import os
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import comun
from comun import ErrorConfiguracion, PrecondicionNoCumplida, exigir

LOTE = "BE-3.1"
LAT, LNG = 0.001, 0.001  # fuera del campus (validation-3-1 §4)
DISTANCIA_ESTE_M = 111.2  # 0,001° de longitud a 0,001° de latitud (haversine, radio medio 6 371 008,8 m)
TOLERANCIA_M = 0.5


def _definiciones(prefijo: str) -> dict[str, dict[str, Any]]:
    """Cuerpos de `LugarEntrada` de cada lugar de prueba (validation-3-1 §2)."""
    return {
        "A": {
            "nombre": f"{prefijo} Biblioteca Lago",
            "categoria": "biblioteca",
            "lat": LAT,
            "lng": LNG,
            "alias": ["validacion biblioteca", "validacion lago"],
            "descripcion": "validacion-31 lugar de prueba",
            "referencias": "validacion-31 junto a nada",
        },
        "B": {"nombre": f"{prefijo} Bloque Sur", "categoria": "bloque", "lat": LAT, "lng": LNG},
        "C": {"nombre": f"{prefijo} Entrada Este", "categoria": "entrada", "lat": LAT, "lng": LNG + 0.001},
        "D": {"nombre": f"{prefijo} Cafe Norte", "categoria": "cafeteria", "lat": LAT, "lng": LNG},
    }


# --- Contexto ------------------------------------------------------------------------------------------------------
class Contexto:
    def __init__(self, entorno: str) -> None:
        self.entorno = entorno
        self.sesion: Any = None
        self.api: comun.ClienteApi | None = None
        self.admin: tuple[str, str] | None = None
        self.sello = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        self.creados: dict[str, str] = {}  # clave (A, B…) → id
        self.otros_ids: list[str] = []  # lugares creados cuando se esperaba un rechazo (backend defectuoso)
        self._outputs: dict[str, Any] | None = None
        self._token: str | None = None
        self.dormir: Callable[[float], None] = time.sleep
        self.http: Any = None  # las pruebas inyectan uno

    @property
    def prefijo(self) -> str:
        return f"{comun.PREFIJO_VALIDACION}31-{self.sello}"

    @property
    def definiciones(self) -> dict[str, dict[str, Any]]:
        return _definiciones(self.prefijo)

    def outputs(self) -> dict[str, Any]:
        if self._outputs is None:
            self._outputs = comun.outputs_terraform()
        return self._outputs

    def token(self) -> str:
        if self._token is None:
            correo, password = self.admin
            self._token = self.api.token(correo, password, quien="el admin")
        return self._token

    def pedir(self, metodo: str, ruta: str, *, con_token: bool = True, **kwargs: Any) -> Any:
        return self.api.pedir(metodo, ruta, token=self.token() if con_token else None, **kwargs)

    def crear(self, cuerpo: dict[str, Any]) -> Any:
        """`POST /v1/admin/places`; con `201` apunta el id para la limpieza."""
        respuesta = self.pedir("POST", comun.RUTA_LUGARES_ADMIN, json=cuerpo)
        if respuesta.status_code == 201:
            self.otros_ids.append(str(respuesta.json().get("id")))
        return respuesta

    def lugar(self, clave: str) -> dict[str, Any]:
        """El `LugarAdmin` del lugar de prueba `clave`, creándolo si aún no existe (así `--solo` funciona)."""
        if clave not in self.creados:
            respuesta = self.crear(self.definiciones[clave])
            exigir(
                respuesta.status_code == 201,
                f"POST del lugar {clave}: {comun.describir_respuesta(respuesta)}, se esperaba 201",
            )
            self.creados[clave] = str(respuesta.json()["id"])
            return respuesta.json()
        return self.buscar_admin(self.creados[clave]) or {"id": self.creados[clave]}

    def publico(self, *, con_token: bool = False, **parametros: Any) -> list[dict[str, Any]]:
        respuesta = self.pedir("GET", comun.RUTA_LUGARES, con_token=con_token, params=parametros)
        exigir(respuesta.status_code == 200, f"GET /v1/places respondió {comun.describir_respuesta(respuesta)}")
        cuerpo = respuesta.json()
        items = cuerpo.get("items", [])
        exigir(set(cuerpo) == {"items", "total"}, f"campos de GET /v1/places: {sorted(cuerpo)}")
        exigir(cuerpo["total"] == len(items), f"total = {cuerpo['total']} con {len(items)} items")
        return items

    def admin_lista(self, q: str | None = None) -> list[dict[str, Any]]:
        parametros = {} if q is None else {"q": q}
        respuesta = self.pedir("GET", comun.RUTA_LUGARES_ADMIN, params=parametros)
        exigir(respuesta.status_code == 200, f"GET /v1/admin/places respondió {comun.describir_respuesta(respuesta)}")
        cuerpo = respuesta.json()
        exigir(cuerpo.get("total") == len(cuerpo.get("items", [])), "total ≠ número de items en /v1/admin/places")
        return cuerpo["items"]

    def buscar_admin(self, lugar_id: str) -> dict[str, Any] | None:
        return next((lugar for lugar in self.admin_lista(self.prefijo) if lugar.get("id") == lugar_id), None)

    def limpiar(self) -> str:
        try:
            if self.api is None or self._token is None:  # sin sesión de admin no se pudo crear nada
                return "nada que limpiar (no se llegó a iniciar sesión)"
            # Los que siguen existiendo (todos llevan el prefijo de esta ejecución) más los apuntados, por si acaso:
            # el DELETE de uno que ya no existe también da 204 (§5.5) y no se cuenta.
            propios = [lugar["id"] for lugar in comun.lugares_validacion(self.api, self.token(), self.prefijo)]
            apuntados = [i for i in (*self.creados.values(), *self.otros_ids) if i not in propios]
            if not propios and not apuntados:
                return "nada que limpiar (no se creó ningún lugar)"
            comun.borrar_lugares(self.api, self.token(), [*propios, *apuntados])
            return f"lugares de prueba borrados: {len(propios)}"
        finally:
            if self.api is not None:
                self.api.cerrar()


def _esperar(respuesta: Any, estado: int, codigo: str | None, que: str) -> None:
    obtenido = comun.codigo_error(respuesta)
    exigir(
        respuesta.status_code == estado and (codigo is None or obtenido == codigo),
        f"{que}: {comun.describir_respuesta(respuesta)}, se esperaba {estado}{' ' + codigo if codigo else ''}",
    )


def _campos_422(respuesta: Any) -> list[str]:
    try:
        return [c.get("campo") for c in respuesta.json()["error"]["detalle"]["campos"]]
    except (KeyError, TypeError, ValueError):
        return []


def _coincide(lugar: dict[str, Any], cuerpo: dict[str, Any], que: str) -> None:
    """Los campos de `LugarEntrada` de `lugar` son los enviados (los ausentes: `alias` = [] y textos `null`)."""
    esperado = {
        "nombre": cuerpo["nombre"],
        "categoria": cuerpo["categoria"],
        "lat": cuerpo["lat"],
        "lng": cuerpo["lng"],
        "alias": cuerpo.get("alias") or [],
        "descripcion": cuerpo.get("descripcion"),
        "referencias": cuerpo.get("referencias"),
    }
    distintos = sorted(campo for campo, valor in esperado.items() if lugar.get(campo) != valor)
    exigir(not distintos, f"{que}: campos distintos de lo enviado: {distintos}")


def _por_id(items: list[dict[str, Any]], lugar_id: str) -> dict[str, Any] | None:
    return next((lugar for lugar in items if lugar.get("id") == lugar_id), None)


# --- Precondiciones ------------------------------------------------------------------------------------------------
def p1_credenciales(ctx: Contexto) -> str:
    ctx.sesion = comun.sesion_aws()
    arn = comun.verificar_cuenta(ctx.sesion)
    return f"cuenta {comun.CUENTA_AWS} ({arn.rsplit('/', 1)[-1]})"


def p2_api(ctx: Contexto) -> str:
    """URL de la API y `/v1/health/ready` con `"db": "ok"` (BE-1.2)."""
    import httpx

    if ctx.entorno == "local":
        if not os.environ.get("VALIDACION_API_URL", "").strip():
            raise ErrorConfiguracion("en local hace falta VALIDACION_API_URL (p. ej. http://localhost:8000/v1)")
        url = comun.url_api()
    else:
        url = comun.url_api(None if os.environ.get("VALIDACION_API_URL", "").strip() else ctx.outputs())
    ctx.api = comun.ClienteApi(url, http=ctx.http, dormir=ctx.dormir)
    try:
        respuesta = ctx.api.pedir("GET", "/health/ready")
    except httpx.HTTPError as exc:
        raise PrecondicionNoCumplida(f"BE-1.1: GET /v1/health/ready no respondió ({type(exc).__name__})") from None
    if respuesta.status_code != 200:
        raise PrecondicionNoCumplida(f"BE-1.2: /v1/health/ready respondió {comun.describir_respuesta(respuesta)}")
    db = respuesta.json().get("db")
    if db != "ok":
        raise PrecondicionNoCumplida(f"BE-1.2: /v1/health/ready dice db = {db!r}")
    return f'{url} · /v1/health/ready → "db": "ok"'


def p3_admin_y_lugares(ctx: Contexto) -> str:
    """Login de admin (BE-1.3) y `GET /v1/places` desplegado (BE-3.1)."""
    ctx.admin = comun.credenciales_admin(ctx.entorno, ctx.sesion)
    correo, password = ctx.admin
    respuesta = ctx.api.login(correo, password)
    if respuesta.status_code == 404:
        raise PrecondicionNoCumplida("BE-1.3: POST /v1/auth/login respondió 404")
    if respuesta.status_code == 401:
        raise ErrorConfiguracion("el login del admin respondió 401: revisa VALIDACION_ADMIN_* o el secreto")
    if respuesta.status_code != 200:
        raise PrecondicionNoCumplida(f"BE-1.3: el login del admin respondió {comun.describir_respuesta(respuesta)}")
    rol = (respuesta.json().get("usuario") or {}).get("rol")
    if rol != "admin":
        raise ErrorConfiguracion(f"el usuario de VALIDACION_ADMIN_* tiene rol {rol!r}, no admin")
    ctx._token = respuesta.json()["token"]
    lugares = ctx.api.pedir("GET", comun.RUTA_LUGARES)
    if lugares.status_code == 404:
        raise PrecondicionNoCumplida("BE-3.1 sin desplegar: GET /v1/places respondió 404")
    if lugares.status_code != 200:
        raise PrecondicionNoCumplida(f"GET /v1/places respondió {comun.describir_respuesta(lugares)}")
    return f"login admin 200 (rol admin) · GET /v1/places → 200 ({lugares.json().get('total')} lugares)"


def preparacion(ctx: Contexto) -> str:
    return comun.borrar_lugares_restos(ctx.api, ctx.token())


# --- C1: crear, editar y borrar, visto en las dos lecturas --------------------------------------------------------
def c1a_crear(ctx: Contexto) -> str:
    cuerpo = ctx.definiciones["A"]
    lugar = ctx.lugar("A")
    exigir(set(lugar) == comun.CAMPOS_LUGAR_ADMIN, f"campos de LugarAdmin: {sorted(lugar)}")
    _coincide(lugar, cuerpo, "POST")
    exigir(lugar["imagen_url"] is None and lugar["total_fotos"] == 0, "imagen_url o total_fotos no son null y 0")
    exigir(lugar["creado_en"] == lugar["actualizado_en"], "creado_en ≠ actualizado_en en un lugar nuevo")
    publico = _por_id(ctx.publico(), lugar["id"])
    exigir(publico is not None, "el lugar creado no sale en GET /v1/places")
    exigir(set(publico) == comun.CAMPOS_LUGAR_PUBLICO, f"campos de LugarPublico: {sorted(publico)}")
    _coincide(publico, cuerpo, "GET /v1/places")
    exigir(publico["distancia_m"] is None, "distancia_m no es null sin posición")
    q = f"{ctx.prefijo.upper().replace('VALIDACION', 'VALIDACIÓN')} BIBLIOTECA"
    encontrados = ctx.admin_lista(q)
    exigir(_por_id(encontrados, lugar["id"]) is not None, f"GET /v1/admin/places?q={q} no lo encuentra")
    return f"POST → 201 LugarAdmin · en GET /v1/places (distancia_m null) · GET /v1/admin/places?q={q} lo encuentra"


def c1b_editar(ctx: Contexto) -> str:
    original = ctx.lugar("A")
    cuerpo = {
        "nombre": f"{ctx.prefijo} Bibliotéca Lago",  # el mismo nombre normalizado: no es un duplicado de sí mismo
        "categoria": "bloque",
        "lat": LAT + 0.0001,
        "lng": LNG + 0.0002,
        "alias": ["validacion bloque"],
        "referencias": "validacion-31 editada",
    }
    respuesta = ctx.pedir("PUT", f"{comun.RUTA_LUGARES_ADMIN}/{original['id']}", json=cuerpo)
    _esperar(respuesta, 200, None, "PUT del lugar A")
    lugar = respuesta.json()
    _coincide(lugar, cuerpo, "PUT")
    if "creado_en" in original:
        exigir(lugar["creado_en"] == original["creado_en"], "PUT cambió creado_en")
    exigir(lugar["actualizado_en"] >= lugar["creado_en"], "actualizado_en anterior a creado_en")
    publico = _por_id(ctx.publico(), original["id"])
    exigir(publico is not None, "tras el PUT el lugar no sale en GET /v1/places")
    _coincide(publico, cuerpo, "GET /v1/places tras el PUT")
    en_admin = ctx.buscar_admin(original["id"])
    exigir(en_admin is not None, "tras el PUT el lugar no sale en GET /v1/admin/places")
    _coincide(en_admin, cuerpo, "GET /v1/admin/places tras el PUT")
    return (
        "PUT → 200 con nombre con tilde (mismo nombre), categoría, posición, alias y textos nuevos, en las dos lecturas"
    )


def c1c_borrar(ctx: Contexto) -> str:
    lugar_id = ctx.lugar("A")["id"]
    ruta = f"{comun.RUTA_LUGARES_ADMIN}/{lugar_id}"
    _esperar(ctx.pedir("DELETE", ruta), 204, None, "DELETE del lugar A")
    exigir(_por_id(ctx.publico(), lugar_id) is None, "tras el DELETE el lugar sigue en GET /v1/places")
    exigir(ctx.buscar_admin(lugar_id) is None, "tras el DELETE el lugar sigue en GET /v1/admin/places")
    _esperar(ctx.pedir("PUT", ruta, json=ctx.definiciones["A"]), 404, "NO_ENCONTRADO", "PUT del lugar borrado")
    _esperar(ctx.pedir("DELETE", ruta), 204, None, "DELETE repetido")
    del ctx.creados["A"]
    return "DELETE → 204 · fuera de las dos lecturas · PUT → 404 NO_ENCONTRADO · DELETE repetido → 204"


# --- C2: orden por distancia y por nombre, filtro de categoría -----------------------------------------------------
def c2a_distancia(ctx: Contexto) -> str:
    b, c = ctx.lugar("B")["id"], ctx.lugar("C")["id"]
    items = ctx.publico(lat=LAT, lng=LNG)
    distancias = [lugar.get("distancia_m") for lugar in items]
    exigir(all(isinstance(d, int | float) for d in distancias), "con posición algún lugar trae distancia_m null")
    exigir(distancias == sorted(distancias), "con posición los lugares no van de menor a mayor distancia_m")
    exigir(items and items[0]["id"] == b, "el lugar guardado en la posición consultada no sale primero")
    exigir(items[0]["distancia_m"] < 1, f"distancia_m del primero = {items[0]['distancia_m']}, se esperaba < 1")
    lugar_c = _por_id(items, c)
    exigir(lugar_c is not None, "el lugar C no sale con posición")
    exigir(
        abs(lugar_c["distancia_m"] - DISTANCIA_ESTE_M) <= TOLERANCIA_M,
        f"distancia_m de C = {lugar_c['distancia_m']}, se esperaba {DISTANCIA_ESTE_M} ± {TOLERANCIA_M}",
    )
    return (
        f"?lat={LAT}&lng={LNG} → {len(items)} lugares de menor a mayor distancia · B primero con "
        f"{items[0]['distancia_m']} m · C a {lugar_c['distancia_m']} m"
    )


def c2b_categoria(ctx: Contexto) -> str:
    b, c = ctx.lugar("B")["id"], ctx.lugar("C")["id"]
    items = ctx.publico(lat=LAT, lng=LNG, categoria="entrada")
    exigir(all(lugar.get("categoria") == "entrada" for lugar in items), "categoria=entrada trae otras categorías")
    exigir(_por_id(items, c) is not None and _por_id(items, b) is None, "categoria=entrada no filtra B y C bien")
    return f"?lat={LAT}&lng={LNG}&categoria=entrada → lugares: {len(items)}, todos entrada (C sí, B no)"


def c2c_nombre(ctx: Contexto) -> str:
    b, c = ctx.lugar("B")["id"], ctx.lugar("C")["id"]
    items = ctx.publico(con_token=False)
    exigir(all(lugar.get("distancia_m") is None for lugar in items), "sin posición algún lugar trae distancia_m")
    claves = [(comun.normalizar_nombre(lugar["nombre"]), lugar["id"]) for lugar in items]
    exigir(claves == sorted(claves), "sin posición los lugares no van por nombre normalizado")
    ids = [lugar["id"] for lugar in items]
    exigir(b in ids and c in ids and ids.index(b) < ids.index(c), "sin posición B no va antes que C")
    return f"sin posición → {len(items)} lugares por nombre normalizado, distancia_m null"


# --- C3: nombre único sin distinguir mayúsculas, tildes ni espacios --------------------------------------------------
def c3a_mayusculas(ctx: Contexto) -> str:
    ctx.lugar("D")
    nombre = f"{ctx.prefijo.upper()} CAFE NORTE"
    _esperar(ctx.crear(ctx.definiciones["D"] | {"nombre": nombre}), 409, "NOMBRE_DUPLICADO", f"POST «{nombre}»")
    return f"«{ctx.definiciones['D']['nombre']}» → 201 · «{nombre}» → 409 NOMBRE_DUPLICADO"


def c3b_tildes_y_espacios(ctx: Contexto) -> str:
    d = ctx.lugar("D")["id"]
    con_tilde = f"{ctx.prefijo} Café Norte"
    con_espacios = f"  {ctx.prefijo}   Cafe  Norte "
    for nombre in (con_tilde, con_espacios):
        _esperar(ctx.crear(ctx.definiciones["D"] | {"nombre": nombre}), 409, "NOMBRE_DUPLICADO", f"POST «{nombre}»")
    iguales = ctx.admin_lista(f"{ctx.prefijo} cafe norte")
    exigir([lugar["id"] for lugar in iguales] == [d], f"hay {len(iguales)} lugares «… Cafe Norte», se esperaba 1")
    return f"«{con_tilde}» y «{con_espacios.strip()}» con espacios de más → 409 NOMBRE_DUPLICADO · sigue habiendo 1"


def c3c_al_editar(ctx: Contexto) -> str:
    ctx.lugar("D")
    b = ctx.lugar("B")
    nombre = f"{ctx.prefijo} CAFÉ NORTE"
    cuerpo = ctx.definiciones["B"] | {"nombre": nombre}
    _esperar(ctx.pedir("PUT", f"{comun.RUTA_LUGARES_ADMIN}/{b['id']}", json=cuerpo), 409, "NOMBRE_DUPLICADO", "PUT")
    en_admin = ctx.buscar_admin(b["id"])
    exigir(en_admin is not None and en_admin["nombre"] == ctx.definiciones["B"]["nombre"], "el PUT rechazado cambió B")
    return f"PUT de B con «{nombre}» → 409 NOMBRE_DUPLICADO y B sin cambios"


# --- C4: validación y autenticación ---------------------------------------------------------------------------------
def c4a_validacion(ctx: Contexto) -> str:
    casos: list[tuple[str, Any, str]] = [
        ("GET ?lat sin lng", ctx.pedir("GET", comun.RUTA_LUGARES, con_token=False, params={"lat": LAT}), "lng"),
        ("GET ?categoria=cocina", ctx.pedir("GET", comun.RUTA_LUGARES, params={"categoria": "cocina"}), "categoria"),
    ]
    base = ctx.definiciones["D"] | {"nombre": f"{ctx.prefijo} Invalido"}
    for que, cambio, campo in (
        ("POST nombre de 1 carácter", {"nombre": "x"}, "nombre"),
        ("POST lat 91", {"lat": 91}, "lat"),
        ("POST 21 alias", {"alias": ["validacion"] * 21}, "alias"),
    ):
        casos.append((que, ctx.crear(base | cambio), campo))
    casos.append(("PUT id que no es UUID", ctx.pedir("PUT", f"{comun.RUTA_LUGARES_ADMIN}/no-es-uuid", json=base), ""))
    for que, respuesta, campo in casos:
        _esperar(respuesta, 422, "VALIDACION", que)
        if campo:
            exigir(campo in _campos_422(respuesta), f"{que}: detalle.campos = {_campos_422(respuesta)}, falta {campo}")
    return f"{len(casos)} entradas no válidas → 422 VALIDACION con el campo en detalle.campos"


def c4b_autenticacion(ctx: Contexto) -> str:
    cuerpo = ctx.definiciones["D"] | {"nombre": f"{ctx.prefijo} Sin Token"}
    _esperar(ctx.pedir("GET", comun.RUTA_LUGARES_ADMIN, con_token=False), 401, "NO_AUTENTICADO", "GET admin sin token")
    sin_token = ctx.pedir("POST", comun.RUTA_LUGARES_ADMIN, con_token=False, json=cuerpo)
    if sin_token.status_code == 201:
        ctx.otros_ids.append(str(sin_token.json().get("id")))
    _esperar(sin_token, 401, "NO_AUTENTICADO", "POST sin token")
    malo = ctx.api.pedir("GET", comun.RUTA_LUGARES, headers={"Authorization": "Bearer no-es-un-token"})
    _esperar(malo, 200, None, "GET /v1/places con un token no válido")
    return "sin token: GET y POST /v1/admin/places → 401 NO_AUTENTICADO · GET /v1/places con token no válido → 200"


def main(argv: list[str] | None = None, ctx: Contexto | None = None) -> int:
    validador = comun.Validador(lote=LOTE, validacion="validation-3-1", entornos=("dev", "local"), descripcion=__doc__)
    argumentos = validador.iniciar(argv)
    ctx = ctx or Contexto(argumentos.entorno)
    precondiciones = [("P2", lambda: p2_api(ctx)), ("P3", lambda: p3_admin_y_lugares(ctx))]
    if argumentos.entorno == "dev":
        precondiciones.insert(0, ("P1", lambda: p1_credenciales(ctx)))
    return validador.ejecutar(
        precondiciones=precondiciones,
        preparacion=lambda: preparacion(ctx),
        comprobaciones=[
            ("C1a", lambda: c1a_crear(ctx)),
            ("C1b", lambda: c1b_editar(ctx)),
            ("C1c", lambda: c1c_borrar(ctx)),
            ("C2a", lambda: c2a_distancia(ctx)),
            ("C2b", lambda: c2b_categoria(ctx)),
            ("C2c", lambda: c2c_nombre(ctx)),
            ("C3a", lambda: c3a_mayusculas(ctx)),
            ("C3b", lambda: c3b_tildes_y_espacios(ctx)),
            ("C3c", lambda: c3c_al_editar(ctx)),
            ("C4a", lambda: c4a_validacion(ctx)),
            ("C4b", lambda: c4b_autenticacion(ctx)),
        ],
        manuales=[],
        limpieza=ctx.limpiar,
    )


if __name__ == "__main__":
    sys.exit(main())
