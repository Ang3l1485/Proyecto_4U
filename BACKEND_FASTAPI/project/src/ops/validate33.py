"""BE-3.3 — Alertas. Caché de la app por diferencias (`GET /v1/alerts?desde=`) igual a la foto completa tras crear,
editar (con `If-Match` y `409 CONFLICTO_VERSION`) y borrar; `DELETE` idempotente; vigencia futura en la foto completa;
`sincronizar` cambio por cambio; y `alertas_activas` de `GET /v1/admin/stats`.

Documento: BACKEND_FASTAPI/docs/validation/validation-3-3.md · criterios: BACKEND_FASTAPI/docs/PLAN.md §2.2.

    cd BACKEND_FASTAPI/project
    uv run --group ops python src/ops/validate33.py --entorno dev
    uv run --group ops python src/ops/validate33.py --entorno local   # con docker compose (db y api) en marcha

Variables: AWS_PROFILE (obligatoria en dev); VALIDACION_API_URL, VALIDACION_ADMIN_CORREO y VALIDACION_ADMIN_PASSWORD
(opcionales en dev, obligatorias en local). Crea alertas con mensaje `validacion-33-<AAAAMMDD-HHMMSS> …` en (0.001,
0.001), fuera del campus, con ids que genera él mismo, y las borra al terminar (quedan sus tombstones 90 días). Nunca
imprime contraseñas ni tokens.
"""

from __future__ import annotations

import os
import re
import sys
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import comun
from comun import ErrorConfiguracion, Falla, PrecondicionNoCumplida, exigir

LOTE = "BE-3.3"
LAT, LNG = 0.001, 0.001  # fuera del campus (validation-3-3 §4)
PLAN_BACKEND = comun.RAIZ_CARPETA / "docs" / "PLAN.md"
RADIO_FUERA_DE_RANGO = 500  # B de C4: `radio_m` en [5, 100] (§5.5)


def incluida(solo: str | None, id_: str) -> bool:
    """¿`--solo` incluye `id_`? (La regla de `comun.Validador`: `C1` incluye `C1a` … `C1d`.)"""
    if not solo:
        return True
    elegidas = {parte.strip() for parte in solo.split(",") if parte.strip()}
    criterio = re.match(r"([A-Z]+\d+)", id_)
    return id_ in elegidas or (criterio is not None and criterio.group(1) in elegidas)


def aplicar(cache: dict[str, dict[str, Any]], respuesta: dict[str, Any]) -> None:
    """Aplica una respuesta de `GET /v1/alerts` a la caché `id → Alerta` como la app (§5.3; FRONTEND §5.10, «Alertas
    sin conexión»): `completo` la reemplaza; si no, reemplaza por `id`, quita las que llegan con `activa = false` y las
    de `eliminadas`. No filtra por vigencia (la evalúa la app al anunciar)."""
    if respuesta["completo"]:
        cache.clear()
        cache.update({alerta["id"]: alerta for alerta in respuesta["alertas"]})
        return
    for alerta in respuesta["alertas"]:
        if alerta["activa"]:
            cache[alerta["id"]] = alerta
        else:
            cache.pop(alerta["id"], None)
    for alerta_id in respuesta["eliminadas"]:
        cache.pop(alerta_id, None)


def versiones(alertas: Any) -> dict[str, int]:
    """`{id: version}` de una lista o de los valores de una caché."""
    return {alerta["id"]: alerta["version"] for alerta in alertas}


def fecha(valor: datetime) -> str:
    """Fecha de entrada en el formato de salida de §5.1 (UTC, `Z`, sin fracciones): así se compara con lo devuelto."""
    return valor.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# --- Contexto ------------------------------------------------------------------------------------------------------
class Contexto:
    def __init__(self, entorno: str) -> None:
        self.entorno = entorno
        self.solo: str | None = None
        self.sesion: Any = None
        self.api: comun.ClienteApi | None = None
        self.admin: tuple[str, str] | None = None
        self.sello = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        self.ids: dict[str, str] = {}  # clave (A, B…) → id que generó el validador (se apunta antes del PUT)
        self.cache: dict[str, dict[str, Any]] | None = None
        self.generado_en: str | None = None
        self.n_inicial = 0
        self.hechas: set[str] = set()  # pasos de C1 terminados sin fallar (C1b necesita C1a…)
        self.intentadas: set[str] = set()  # pasos de C1 empezados
        self._outputs: dict[str, Any] | None = None
        self._token: str | None = None
        self.dormir: Callable[[float], None] = time.sleep
        self.ahora: Callable[[], datetime] = lambda: datetime.now(UTC)
        self.http: Any = None  # las pruebas inyectan uno
        self.plan = PLAN_BACKEND

    @property
    def prefijo(self) -> str:
        return f"{comun.PREFIJO_VALIDACION}33-{self.sello}"

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

    def id_de(self, clave: str) -> str:
        """El id (UUID v4, lo genera el validador como la app) de la alerta de prueba `clave`."""
        if clave not in self.ids:
            self.ids[clave] = str(uuid.uuid4())
        return self.ids[clave]

    def cuerpo(self, clave: str, texto: str, **cambios: Any) -> dict[str, Any]:
        """Un `AlertaEntrada` con mensaje `<prefijo> <texto>` en (LAT, LNG)."""
        return {"lat": LAT, "lng": LNG, "mensaje": f"{self.prefijo} {texto}"} | cambios

    def poner(self, clave: str, cuerpo: dict[str, Any], *, if_match: str | None = None) -> Any:
        """`PUT /v1/admin/alerts/{id de clave}` (con `If-Match` si se pasa)."""
        encabezados = {"If-Match": if_match} if if_match is not None else {}
        return self.pedir("PUT", f"{comun.RUTA_ALERTAS_ADMIN}/{self.id_de(clave)}", json=cuerpo, headers=encabezados)

    def crear(self, clave: str, cuerpo: dict[str, Any]) -> dict[str, Any]:
        """`PUT` de una alerta nueva: exige `201` y devuelve la `AlertaAdmin`."""
        respuesta = self.poner(clave, cuerpo)
        _esperar(respuesta, 201, None, f"PUT de la alerta {clave} (nueva)")
        return respuesta.json()

    def foto(self, desde: str | None = None) -> dict[str, Any]:
        """`GET /v1/alerts[?desde=…]` sin token (es público): exige `200` y la forma de §5.3."""
        parametros = {} if desde is None else {"desde": desde}
        que = "GET /v1/alerts" + ("?desde=…" if desde else "")
        respuesta = self.pedir("GET", comun.RUTA_ALERTAS, con_token=False, params=parametros)
        _esperar(respuesta, 200, None, que)
        cuerpo = respuesta.json()
        exigir(set(cuerpo) == comun.CAMPOS_FOTO_ALERTAS, f"{que}: campos {sorted(cuerpo)}")
        exigir(
            comun.PATRON_FECHA_UTC.match(str(cuerpo["generado_en"])) is not None,
            f"{que}: generado_en = {cuerpo['generado_en']!r}, se esperaba AAAA-MM-DDTHH:MM:SSZ",
        )
        for alerta in cuerpo["alertas"]:
            exigir(set(alerta) == comun.CAMPOS_ALERTA, f"{que}: campos de Alerta {sorted(alerta)}")
        return cuerpo

    def asegurar_cache(self) -> int:
        """La caché inicial = la foto completa (la primera vez). Devuelve cuántas alertas trajo esa foto."""
        if self.cache is None:
            inicial = self.foto()
            exigir(inicial["completo"] is True, "GET /v1/alerts sin desde: completo no es true")
            exigir(inicial["eliminadas"] == [], "GET /v1/alerts sin desde: eliminadas no está vacía")
            self.cache = {}
            aplicar(self.cache, inicial)
            self.generado_en = inicial["generado_en"]
            self.n_inicial = len(inicial["alertas"])
        return self.n_inicial

    def diferencia(self) -> dict[str, Any]:
        """`GET /v1/alerts?desde=<último generado_en>`, aplicada a la caché (exige `completo = false`)."""
        self.asegurar_cache()
        respuesta = self.foto(self.generado_en)
        exigir(respuesta["completo"] is False, f"GET /v1/alerts?desde={self.generado_en}: completo no es false")
        aplicar(self.cache, respuesta)
        self.generado_en = respuesta["generado_en"]
        return respuesta

    def admin_lista(self, q: str | None = None) -> list[dict[str, Any]]:
        parametros = {} if q is None else {"q": q}
        respuesta = self.pedir("GET", comun.RUTA_ALERTAS_ADMIN, params=parametros)
        _esperar(respuesta, 200, None, "GET /v1/admin/alerts")
        cuerpo = respuesta.json()
        exigir(cuerpo.get("total") == len(cuerpo.get("items", [])), "total ≠ número de items en /v1/admin/alerts")
        return cuerpo["items"]

    def limpiar(self) -> str:
        try:
            if self.api is None or self._token is None:  # sin sesión de admin no se pudo crear nada
                return "nada que limpiar (no se llegó a iniciar sesión)"
            # Las que siguen vivas con el prefijo de esta ejecución más los ids apuntados (el DELETE de uno que no
            # existe o ya está borrado también da 204, §5.5, y no se cuenta).
            propias = [alerta["id"] for alerta in comun.alertas_validacion(self.api, self.token(), self.prefijo)]
            apuntadas = [i for i in self.ids.values() if i not in propias]
            if not propias and not apuntadas:
                return "nada que limpiar (no se creó ninguna alerta)"
            comun.borrar_alertas(self.api, self.token(), [*propias, *apuntadas])
            return f"alertas de prueba borradas: {len(propias)}"
        finally:
            if self.api is not None:
                self.api.cerrar()


def _esperar(respuesta: Any, estado: int, codigo: str | None, que: str) -> None:
    obtenido = comun.codigo_error(respuesta)
    exigir(
        respuesta.status_code == estado and (codigo is None or obtenido == codigo),
        f"{que}: {comun.describir_respuesta(respuesta)}, se esperaba {estado}{' ' + codigo if codigo else ''}",
    )


def _coincide(alerta: dict[str, Any], cuerpo: dict[str, Any], que: str) -> None:
    """Los campos de `AlertaEntrada` de `alerta` son los enviados (los ausentes, con su valor por defecto)."""
    esperado = {
        "lat": cuerpo["lat"],
        "lng": cuerpo["lng"],
        "mensaje": cuerpo["mensaje"],
        "tipo": cuerpo.get("tipo", "otro"),
        "prioridad": cuerpo.get("prioridad", "normal"),
        "radio_m": cuerpo.get("radio_m", 15),
        "activa": cuerpo.get("activa", True),
        "vigencia_desde": cuerpo.get("vigencia_desde"),
        "vigencia_hasta": cuerpo.get("vigencia_hasta"),
    }
    distintos = sorted(campo for campo, valor in esperado.items() if alerta.get(campo) != valor)
    exigir(not distintos, f"{que}: campos distintos de lo enviado: {distintos}")


def _por_id(alertas: list[dict[str, Any]], alerta_id: str) -> dict[str, Any] | None:
    return next((alerta for alerta in alertas if alerta.get("id") == alerta_id), None)


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


def p3_admin_y_alertas(ctx: Contexto) -> str:
    """Login de admin (BE-1.3) y BE-3.3 desplegado (`GET /v1/alerts` y `GET /v1/admin/alerts`)."""
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
    publicas = ctx.api.pedir("GET", comun.RUTA_ALERTAS)
    if publicas.status_code == 404:
        raise PrecondicionNoCumplida("BE-3.3 sin desplegar: GET /v1/alerts respondió 404")
    if publicas.status_code != 200:
        raise PrecondicionNoCumplida(f"GET /v1/alerts respondió {comun.describir_respuesta(publicas)}")
    admin = ctx.pedir("GET", comun.RUTA_ALERTAS_ADMIN)
    if admin.status_code != 200:
        raise PrecondicionNoCumplida(f"BE-3.3: GET /v1/admin/alerts respondió {comun.describir_respuesta(admin)}")
    n = len(publicas.json().get("alertas", []))
    return f"login admin 200 (rol admin) · GET /v1/alerts → 200 ({n} activas) · GET /v1/admin/alerts → 200"


def p4_resumen(ctx: Contexto) -> str:
    """Solo con C5: BE-2.3 «Hecho» en PLAN §3 (en `dev`) y `GET /v1/admin/stats` → 200."""
    detalle = []
    if ctx.entorno == "dev":
        try:
            plan = ctx.plan.read_text(encoding="utf-8")
        except OSError:
            raise ErrorConfiguracion(f"no se pudo leer {ctx.plan}") from None
        if not comun.lote_hecho(plan, "BE-2.3"):
            raise PrecondicionNoCumplida("BE-2.3 no está «Hecho» en BACKEND_FASTAPI/docs/PLAN.md §3 (C5)")
        detalle.append("BE-2.3 «Hecho»")
    stats = ctx.pedir("GET", comun.RUTA_STATS)
    if stats.status_code == 404:
        raise PrecondicionNoCumplida("BE-2.3 sin desplegar: GET /v1/admin/stats respondió 404")
    if stats.status_code != 200:
        raise PrecondicionNoCumplida(f"GET /v1/admin/stats respondió {comun.describir_respuesta(stats)}")
    detalle.append("GET /v1/admin/stats → 200")
    return " · ".join(detalle)


def preparacion(ctx: Contexto) -> str:
    return comun.borrar_alertas_restos(ctx.api, ctx.token())


# --- C1: crear, editar y borrar, sincronizado por diferencias -------------------------------------------------------
def _requiere(ctx: Contexto, *pasos: str) -> None:
    """Hace los pasos de C1 que falten (para `--solo C1c`, p. ej.); sus comprobaciones fallan igual que solas. Un paso
    que ya se intentó y falló no se repite (dejaría la alerta en otro estado): la comprobación falla por él."""
    for paso in pasos:
        if paso in ctx.hechas:
            continue
        if paso in ctx.intentadas:
            raise Falla(f"depende de {paso}, que falló")
        PASOS_C1[paso](ctx)


def c1a_crear(ctx: Contexto) -> str:
    ctx.intentadas.add("C1a")
    n_inicial = ctx.asegurar_cache()
    exigir(all(a["activa"] for a in ctx.cache.values()), "la foto completa trae alertas con activa = false")
    cuerpo = ctx.cuerpo("A", "creada", tipo="obra", radio_m=15)
    alerta = ctx.crear("A", cuerpo)
    exigir(set(alerta) == comun.CAMPOS_ALERTA_ADMIN, f"campos de AlertaAdmin: {sorted(alerta)}")
    _coincide(alerta, cuerpo, "PUT (nueva)")
    exigir(alerta["id"] == ctx.id_de("A"), "el PUT devolvió otro id que el de la ruta")
    exigir(alerta["version"] == 1, f"version = {alerta['version']}, se esperaba 1")
    exigir(alerta["creado_en"] == alerta["actualizado_en"], "creado_en ≠ actualizado_en en una alerta nueva")
    exigir(
        alerta["creado_por"] == alerta["actualizado_por"] and set(alerta["creado_por"]) == {"id", "nombre"},
        "creado_por y actualizado_por no son el mismo {id, nombre}",
    )
    diferencia = ctx.diferencia()
    nueva = _por_id(diferencia["alertas"], ctx.id_de("A"))
    exigir(nueva is not None, "la diferencia tras crear no trae la alerta")
    exigir(nueva["version"] == 1, f"la diferencia trae la versión {nueva['version']}, se esperaba 1")
    ctx.hechas.add("C1a")
    return (
        f"foto completa con {n_inicial} activas · PUT → 201 version 1 · "
        "GET ?desde=<generado_en> → completo false con la alerta"
    )


def c1b_editar(ctx: Contexto) -> str:
    _requiere(ctx, "C1a")
    ctx.intentadas.add("C1b")
    cuerpo = ctx.cuerpo("A", "editada", tipo="obra", radio_m=20)
    respuesta = ctx.poner("A", cuerpo, if_match="1")
    _esperar(respuesta, 200, None, "PUT de A con If-Match: 1")
    alerta = respuesta.json()
    _coincide(alerta, cuerpo, "PUT con If-Match")
    exigir(alerta["version"] == 2, f"version = {alerta['version']} tras editar, se esperaba 2")
    viejo = ctx.poner("A", ctx.cuerpo("A", "editada otra vez", tipo="obra"), if_match="1")
    _esperar(viejo, 409, "CONFLICTO_VERSION", "PUT de A con If-Match: 1 (ya está en la versión 2)")
    diferencia = ctx.diferencia()
    editada = _por_id(diferencia["alertas"], ctx.id_de("A"))
    exigir(editada is not None, "la diferencia tras editar no trae la alerta")
    exigir(editada["version"] == 2, f"la diferencia trae la versión {editada['version']}, se esperaba 2")
    exigir(editada["mensaje"] == cuerpo["mensaje"], "la diferencia no trae el mensaje editado (¿aplicó el 409?)")
    ctx.hechas.add("C1b")
    return "PUT If-Match: 1 → 200 version 2 · otro PUT If-Match: 1 → 409 CONFLICTO_VERSION · la diferencia trae la v2"


def c1c_borrar(ctx: Contexto) -> str:
    _requiere(ctx, "C1a", "C1b")
    ctx.intentadas.add("C1c")
    ruta = f"{comun.RUTA_ALERTAS_ADMIN}/{ctx.id_de('A')}"
    _esperar(ctx.pedir("DELETE", ruta), 204, None, "DELETE de A")
    diferencia = ctx.diferencia()
    exigir(ctx.id_de("A") in diferencia["eliminadas"], "la diferencia tras borrar no trae el id en eliminadas")
    exigir(_por_id(diferencia["alertas"], ctx.id_de("A")) is None, "la alerta borrada sigue en alertas")
    _esperar(ctx.pedir("DELETE", ruta), 204, None, "DELETE repetido de A")
    exigir(_por_id(ctx.admin_lista(ctx.prefijo), ctx.id_de("A")) is None, "la borrada sigue en GET /v1/admin/alerts")
    ctx.hechas.add("C1c")
    return "DELETE → 204 · la diferencia trae el id en eliminadas · DELETE repetido → 204 · fuera del panel"


def c1d_cache(ctx: Contexto) -> str:
    _requiere(ctx, "C1a", "C1b", "C1c")
    final = ctx.foto()
    exigir(final["completo"] is True and final["eliminadas"] == [], "la foto final no es completa")
    cache, completa = versiones(ctx.cache.values()), versiones(final["alertas"])
    if cache != completa:
        sobran = sorted(set(cache) - set(completa))
        faltan = sorted(set(completa) - set(cache))
        distintas = sorted(i for i in set(cache) & set(completa) if cache[i] != completa[i])
        raise Falla(f"caché ≠ foto completa: sobran {sobran}, faltan {faltan}, otra versión {distintas}")
    exigir(ctx.id_de("A") not in cache, "la alerta borrada sigue en la caché")
    return f"caché por diferencias = foto completa ({len(cache)} alertas, mismo id → version)"


PASOS_C1: dict[str, Callable[[Contexto], str]] = {"C1a": c1a_crear, "C1b": c1b_editar, "C1c": c1c_borrar}


# --- C2 a C5 ---------------------------------------------------------------------------------------------------------
def c2_borrar_desconocida(ctx: Contexto) -> str:
    desconocida = str(uuid.uuid4())
    antes = ctx.foto()["generado_en"]
    _esperar(ctx.pedir("DELETE", f"{comun.RUTA_ALERTAS_ADMIN}/{desconocida}"), 204, None, "DELETE de un id desconocido")
    diferencia = ctx.foto(antes)
    exigir(desconocida not in diferencia["eliminadas"], "un id desconocido salió en eliminadas (dejó un tombstone)")
    return "DELETE de un UUID que no existe → 204, sin tombstone"


def c3_vigencia_futura(ctx: Contexto) -> str:
    ahora = ctx.ahora().replace(microsecond=0)
    desde, hasta = fecha(ahora + timedelta(days=2)), fecha(ahora + timedelta(days=3))
    cuerpo = ctx.cuerpo("F", "futura", activa=True, vigencia_desde=desde, vigencia_hasta=hasta)
    alerta = ctx.crear("F", cuerpo)
    _coincide(alerta, cuerpo, "PUT de la alerta futura")
    publica = _por_id(ctx.foto()["alertas"], ctx.id_de("F"))
    exigir(publica is not None, "la alerta activa de vigencia futura no sale en la foto completa")
    en_foto = (publica["vigencia_desde"], publica["vigencia_hasta"])
    exigir(
        en_foto == (desde, hasta),
        f"vigencia en la foto: {' – '.join(map(str, en_foto))}, se esperaba {desde} – {hasta}",
    )
    return f"vigencia {desde} – {hasta} → en la foto completa con sus dos fechas"


def c4_sincronizar(ctx: Contexto) -> str:
    ctx.crear("D", ctx.cuerpo("D", "para borrar", tipo="mobiliario"))
    a, b, d = ctx.id_de("A2"), ctx.id_de("B"), ctx.id_de("D")
    cuerpo = {
        "cambios": [
            {"op": "upsert", "alerta": {"id": a} | ctx.cuerpo("A2", "sincronizada", tipo="agua", prioridad="alta")},
            {"op": "upsert", "alerta": {"id": b} | ctx.cuerpo("B", "no valida", radio_m=RADIO_FUERA_DE_RANGO)},
            {"op": "eliminar", "id": d},
        ]
    }
    respuesta = ctx.pedir("POST", comun.RUTA_SINCRONIZAR, json=cuerpo)
    _esperar(respuesta, 200, None, "POST /v1/admin/alerts/sincronizar")
    datos = respuesta.json()
    exigir(set(datos) == {"generado_en", "resultados"}, f"campos de la respuesta: {sorted(datos)}")
    exigir(comun.PATRON_FECHA_UTC.match(str(datos["generado_en"])) is not None, "generado_en sin el formato de §5.1")
    obtenidos = [(r.get("id"), r.get("op"), r.get("estado"), r.get("codigo")) for r in datos["resultados"]]
    esperados = [(a, "upsert", "ok", None), (b, "upsert", "error", "VALIDACION"), (d, "eliminar", "ok", None)]
    exigir(obtenidos == esperados, f"resultados {obtenidos}, se esperaba {esperados}")
    panel = ctx.admin_lista(ctx.prefijo)
    exigir(_por_id(panel, a) is not None, "la alerta del upsert válido no está en GET /v1/admin/alerts")
    exigir(_por_id(panel, b) is None, "la alerta del upsert no válido se guardó")
    exigir(_por_id(panel, d) is None, "la alerta eliminada sigue en GET /v1/admin/alerts")
    return "upsert válido → ok · upsert con radio_m 500 → error VALIDACION · eliminar → ok · panel: A sí, B y D no"


def c5_resumen(ctx: Contexto) -> str:
    s0 = comun.resumen_panel(ctx.api, ctx.token(), "GET /v1/admin/stats (antes)")
    ctx.crear("G", ctx.cuerpo("G", "activa", activa=True))
    ctx.crear("H", ctx.cuerpo("H", "inactiva", activa=False))
    s1 = comun.resumen_panel(ctx.api, ctx.token(), "GET /v1/admin/stats (después)")
    diferencia = s1["alertas_activas"] - s0["alertas_activas"]
    exigir(
        diferencia == 1,
        f"alertas_activas {s0['alertas_activas']} → {s1['alertas_activas']} ({diferencia:+d}), se esperaba +1 "
        "(¿alguien más creó o borró alertas en este momento?)",
    )
    return (
        f"alertas_activas {s0['alertas_activas']} → {s1['alertas_activas']} (+1) con una activa y una inactiva nuevas"
    )


def main(argv: list[str] | None = None, ctx: Contexto | None = None) -> int:
    validador = comun.Validador(lote=LOTE, validacion="validation-3-3", entornos=("dev", "local"), descripcion=__doc__)
    argumentos = validador.iniciar(argv)
    ctx = ctx or Contexto(argumentos.entorno)
    ctx.solo = argumentos.solo
    precondiciones = [("P2", lambda: p2_api(ctx)), ("P3", lambda: p3_admin_y_alertas(ctx))]
    if argumentos.entorno == "dev":
        precondiciones.insert(0, ("P1", lambda: p1_credenciales(ctx)))
    if incluida(ctx.solo, "C5"):
        precondiciones.append(("P4", lambda: p4_resumen(ctx)))
    return validador.ejecutar(
        precondiciones=precondiciones,
        preparacion=lambda: preparacion(ctx),
        comprobaciones=[
            ("C1a", lambda: c1a_crear(ctx)),
            ("C1b", lambda: c1b_editar(ctx)),
            ("C1c", lambda: c1c_borrar(ctx)),
            ("C1d", lambda: c1d_cache(ctx)),
            ("C2", lambda: c2_borrar_desconocida(ctx)),
            ("C3", lambda: c3_vigencia_futura(ctx)),
            ("C4", lambda: c4_sincronizar(ctx)),
            ("C5", lambda: c5_resumen(ctx)),
        ],
        manuales=[],
        limpieza=ctx.limpiar,
    )


if __name__ == "__main__":
    sys.exit(main())
