"""BE-3.3 contra una base real: `GET /v1/alerts` (foto completa y diferencias), `/v1/admin/alerts` (lista, `PUT` con
`If-Match`, `DELETE` con *tombstone*, `sincronizar`), la auditoría, `alertas_activas` del resumen (C5) y la purga de
*tombstones* (ARCHITECTURE §4.11, §5.3, §5.5, §5.7)."""

from __future__ import annotations

import asyncio
import base64
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import text

from app.config import Settings
from app.db import sesion
from app.dominio.alertas import CAMPOS
from app.esquemas.alertas import Alerta, AlertaAdmin, AlertaEntrada, AlertasRespuesta, ListaAlertas
from app.main import crear_app
from app.servicios import alertas

pytestmark = pytest.mark.base

ADMIN = "admin.pruebas@campus.edu.co"
PASSWORD_ADMIN = "Pruebas-admin-123"
CLAVE = base64.b64encode(b"clave-de-pruebas-de-alertas".ljust(64, b"z")).decode()
FORMATO = "%Y-%m-%dT%H:%M:%SZ"


async def _consultar(ajustes: Settings, sentencia: str, parametros: dict) -> list[Any]:
    motor = sesion.crear_motor(ajustes, "pruebas")
    try:
        async with motor.begin() as conexion:
            resultado = await conexion.execute(text(sentencia), parametros)
            return list(resultado.all()) if resultado.returns_rows else []
    finally:
        await motor.dispose()


def sql(ajustes: Settings, sentencia: str, **parametros: Any) -> list[Any]:
    return asyncio.run(_consultar(ajustes, sentencia, parametros))


@pytest.fixture
def ajustes_al(base_migrada: Settings) -> Settings:
    return base_migrada.model_copy(update={"jwt_secret": SecretStr(CLAVE)})


@pytest.fixture
def api(ajustes_al):
    with TestClient(crear_app(ajustes_al)) as cliente:
        r = cliente.post("/v1/auth/login", json={"identificador": ADMIN, "password": PASSWORD_ADMIN})
        assert r.status_code == 200, r.text
        cliente.headers["Authorization"] = f"Bearer {r.json()['token']}"
        yield cliente


def entrada(mensaje: str = "Ten cuidado, hay un lago", **cambios: Any) -> dict[str, Any]:
    return {"lat": 6.2011, "lng": -75.579, "mensaje": mensaje} | cambios


def poner(api: TestClient, alerta_id: uuid.UUID | str, *, if_match: str | None = None, **cambios: Any) -> Any:
    encabezados = {"If-Match": if_match} if if_match is not None else {}
    return api.put(f"/v1/admin/alerts/{alerta_id}", json=entrada(**cambios), headers=encabezados)


def crear(api: TestClient, **cambios: Any) -> dict[str, Any]:
    alerta_id = uuid.uuid4()
    r = poner(api, alerta_id, **cambios)
    assert r.status_code == 201, r.text
    return r.json()


def foto(api: TestClient, desde: str | None = None) -> dict[str, Any]:
    r = api.get("/v1/alerts", params={} if desde is None else {"desde": desde})
    assert r.status_code == 200, r.text
    AlertasRespuesta.model_validate(r.json())
    return r.json()


def auditoria(ajustes: Settings, accion: str) -> list[Any]:
    return sql(
        ajustes,
        "SELECT actor_id, entidad, entidad_id, detalle FROM auditoria WHERE accion = :a ORDER BY id",
        a=accion,
    )


def fila(ajustes: Settings, alerta_id: str) -> Any:
    [resultado] = sql(
        ajustes,
        "SELECT version, eliminada_en, actualizado_en, creado_por, actualizado_por FROM alertas WHERE id = :i",
        i=uuid.UUID(alerta_id),
    )
    return resultado


def eventos(logs_json, nombre: str) -> list[dict]:
    return [linea for linea in logs_json.lineas if linea["evento"] == nombre]


def hora_base(ajustes: Settings) -> datetime:
    return sql(ajustes, "SELECT now()")[0][0]


# --- PUT ------------------------------------------------------------------------------------------------------------
def test_put_crea_con_201_version_1_y_auditoria(api, ajustes_al, logs_json):
    alerta_id = uuid.uuid4()
    r = poner(api, alerta_id, mensaje="  Ten cuidado, hay un lago  ", tipo="agua", prioridad="alta", extra=1)
    assert r.status_code == 201, r.text
    cuerpo = r.json()
    AlertaAdmin.model_validate(cuerpo)
    assert set(cuerpo) == set(AlertaAdmin.model_fields)
    assert cuerpo["id"] == str(alerta_id) and cuerpo["mensaje"] == "Ten cuidado, hay un lago"
    assert (cuerpo["tipo"], cuerpo["prioridad"], cuerpo["radio_m"], cuerpo["activa"]) == ("agua", "alta", 15, True)
    assert cuerpo["vigencia_desde"] is None and cuerpo["vigencia_hasta"] is None
    assert cuerpo["version"] == 1 and cuerpo["creado_en"] == cuerpo["actualizado_en"]
    assert cuerpo["creado_por"] == cuerpo["actualizado_por"] and cuerpo["creado_por"]["nombre"] == "Administrador"
    [(actor, entidad, entidad_id, detalle)] = auditoria(ajustes_al, "alerta.upsert")
    assert (str(actor), entidad, entidad_id) == (cuerpo["creado_por"]["id"], "alerta", str(alerta_id))
    assert detalle == {
        "operacion": "crear",
        "version": 1,
        "cambios": list(CAMPOS),
        "origen": "put",
        "mensaje": "Ten cuidado, hay un lago",
    }
    [evento] = eventos(logs_json, "alerta_guardada")
    assert (evento["operacion"], evento["alerta_id"], evento["version"]) == ("crear", str(alerta_id), 1)
    assert "lago" not in str(evento)


def test_put_reemplaza_todo_y_sin_cambios_no_escribe(api, ajustes_al):
    alerta = crear(api, tipo="obra", radio_m=30, vigencia_desde="2026-11-01T00:00:00Z")
    r = poner(api, alerta["id"], mensaje="Otro mensaje", radio_m=20)  # lo que no se envía vuelve a su valor por defecto
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert (cuerpo["mensaje"], cuerpo["tipo"], cuerpo["radio_m"], cuerpo["vigencia_desde"]) == (
        "Otro mensaje",
        "otro",
        20,
        None,
    )
    assert cuerpo["version"] == 2 and cuerpo["creado_en"] == alerta["creado_en"]
    assert cuerpo["actualizado_en"] >= alerta["actualizado_en"]
    detalles = [d for *_, d in auditoria(ajustes_al, "alerta.upsert")]
    assert detalles[1] == {
        "operacion": "editar",
        "version": 2,
        "cambios": ["mensaje", "tipo", "radio_m", "vigencia_desde"],
        "origen": "put",
    }

    sql(ajustes_al, "UPDATE alertas SET actualizado_en = '2026-01-01T00:00:00Z'")
    igual = poner(api, alerta["id"], mensaje="  Otro mensaje ", radio_m=20, tipo=None)
    assert igual.status_code == 200
    assert igual.json()["version"] == 2 and igual.json()["actualizado_en"] == "2026-01-01T00:00:00Z"
    assert len(auditoria(ajustes_al, "alerta.upsert")) == 2


def test_if_match(api, ajustes_al):
    alerta = crear(api)
    r = poner(api, alerta["id"], if_match="1", radio_m=25)
    assert r.status_code == 200 and r.json()["version"] == 2
    viejo = poner(api, alerta["id"], if_match="1", radio_m=90)
    assert viejo.status_code == 409 and viejo.json()["error"] == {
        "codigo": "CONFLICTO_VERSION",
        "mensaje": viejo.json()["error"]["mensaje"],
        "detalle": None,
    }
    assert fila(ajustes_al, alerta["id"]).version == 2
    assert poner(api, alerta["id"], if_match='"2"', radio_m=30).json()["version"] == 3
    nueva = uuid.uuid4()
    r = poner(api, nueva, if_match="1")
    assert r.status_code == 409 and r.json()["error"]["codigo"] == "CONFLICTO_VERSION"
    assert sql(ajustes_al, "SELECT count(*) FROM alertas WHERE id = :i", i=nueva)[0][0] == 0
    for valor in ("abc", "0", "*", 'W/"3"'):
        r = poner(api, alerta["id"], if_match=valor)
        assert r.status_code == 422, valor
        assert r.json()["error"]["detalle"]["campos"][0]["campo"] == "If-Match"


@pytest.mark.parametrize(
    ("cambios", "campo"),
    [
        ({"mensaje": " "}, "mensaje"),
        ({"mensaje": "x" * 201}, "mensaje"),
        ({"mensaje": "a\x00b"}, "mensaje"),
        ({"radio_m": 4}, "radio_m"),
        ({"radio_m": 101}, "radio_m"),
        ({"lat": -91}, "lat"),
        ({"tipo": "charco"}, "tipo"),
        ({"vigencia_desde": "2026-11-02T00:00:00Z", "vigencia_hasta": "2026-11-01T00:00:00Z"}, "vigencia_hasta"),
        ({"vigencia_desde": "2026-11-02T00:00:00"}, "vigencia_desde"),
    ],
)
def test_put_no_valido_es_422_sin_escribir(api, ajustes_al, cambios, campo):
    r = poner(api, uuid.uuid4(), **cambios)
    assert r.status_code == 422, r.text
    assert [c["campo"] for c in r.json()["error"]["detalle"]["campos"]] == [campo]
    assert sql(ajustes_al, "SELECT count(*) FROM alertas")[0][0] == 0


def test_put_con_id_que_no_es_uuid_es_422(api):
    r = api.put("/v1/admin/alerts/no-es-uuid", json=entrada())
    assert r.status_code == 422 and r.json()["error"]["detalle"]["campos"][0]["campo"] == "alerta_id"


def test_vigencias_se_guardan_en_utc_sin_fracciones(api):
    alerta = crear(api, vigencia_desde="2026-11-01T10:00:00.75-05:00", vigencia_hasta="2026-11-02T00:00:00.1Z")
    assert (alerta["vigencia_desde"], alerta["vigencia_hasta"]) == ("2026-11-01T15:00:00Z", "2026-11-02T00:00:00Z")
    assert (
        poner(api, alerta["id"], vigencia_desde="2026-11-01T15:00:00Z", vigencia_hasta="2026-11-02T00:00:00Z").json()[
            "version"
        ]
        == 1
    )  # lo mismo sin fracciones: sin cambios


def test_dos_put_a_la_vez_del_mismo_id_nuevo(ajustes_al):
    """Una crea y la otra reemplaza (la que pierde el `INSERT … ON CONFLICT` espera y la bloquea), sin errores."""
    alerta_id = uuid.uuid4()
    [(admin,)] = sql(ajustes_al, "SELECT id FROM usuarios LIMIT 1")

    async def dos() -> list[alertas.Guardado]:
        motor = sesion.crear_motor(ajustes_al, "pruebas", pool=2)
        try:
            return await asyncio.gather(
                *(
                    alertas.guardar(
                        motor,
                        usuario_id=admin,
                        alerta_id=alerta_id,
                        datos=AlertaEntrada.model_validate(entrada(radio_m=radio)),
                    )
                    for radio in (10, 20)
                )
            )
        finally:
            await motor.dispose()

    resultados = asyncio.run(dos())
    assert sorted(r.operacion for r in resultados) == ["crear", "editar"]
    assert fila(ajustes_al, str(alerta_id)).version == 2


# --- DELETE ---------------------------------------------------------------------------------------------------------
def test_delete_deja_tombstone_y_es_idempotente(api, ajustes_al, logs_json):
    alerta = crear(api)
    r = api.delete(f"/v1/admin/alerts/{alerta['id']}")
    assert r.status_code == 204 and r.content == b""
    borrada = fila(ajustes_al, alerta["id"])
    assert borrada.version == 2 and borrada.eliminada_en is not None and borrada.eliminada_en == borrada.actualizado_en
    [(_, _, entidad_id, detalle)] = auditoria(ajustes_al, "alerta.eliminar")
    assert entidad_id == alerta["id"]
    assert detalle == {"version": 2, "mensaje": "Ten cuidado, hay un lago", "origen": "delete"}

    assert api.delete(f"/v1/admin/alerts/{alerta['id']}").status_code == 204
    desconocida = uuid.uuid4()
    assert api.delete(f"/v1/admin/alerts/{desconocida}").status_code == 204
    assert fila(ajustes_al, alerta["id"]).version == 2
    assert sql(ajustes_al, "SELECT count(*) FROM alertas WHERE id = :i", i=desconocida)[0][0] == 0
    assert len(auditoria(ajustes_al, "alerta.eliminar")) == 1
    assert [e["existia"] for e in eventos(logs_json, "alerta_eliminada")] == [True, False, False]
    assert api.get("/v1/admin/alerts").json() == {"items": [], "total": 0}
    assert api.delete("/v1/admin/alerts/no-es-uuid").status_code == 422


def test_put_de_una_borrada_la_restaura_con_201(api, ajustes_al):
    alerta = crear(api)
    api.delete(f"/v1/admin/alerts/{alerta['id']}")
    r = poner(api, alerta["id"], mensaje="Volvió")
    assert r.status_code == 201, r.text
    assert r.json()["version"] == 3 and r.json()["creado_en"] == alerta["creado_en"]
    assert fila(ajustes_al, alerta["id"]).eliminada_en is None
    *_, (_, _, _, detalle) = auditoria(ajustes_al, "alerta.upsert")
    assert detalle == {
        "operacion": "restaurar",
        "version": 3,
        "cambios": ["mensaje"],
        "origen": "put",
        "mensaje": "Volvió",
    }
    assert [a["id"] for a in foto(api)["alertas"]] == [alerta["id"]]


# --- GET /v1/alerts --------------------------------------------------------------------------------------------------
def test_foto_completa_activas_sin_borrar_con_cualquier_vigencia(api, ajustes_al):
    activa = crear(api, mensaje="activa")
    futura = crear(api, mensaje="futura", vigencia_desde="2099-01-01T00:00:00Z", vigencia_hasta="2099-01-02T00:00:00Z")
    pasada = crear(api, mensaje="pasada", vigencia_hasta="2000-01-01T00:00:00Z")
    crear(api, mensaje="inactiva", activa=False)
    borrada = crear(api, mensaje="borrada")
    api.delete(f"/v1/admin/alerts/{borrada['id']}")
    with TestClient(crear_app(ajustes_al)) as anonimo:
        r = anonimo.get("/v1/alerts", headers={"Authorization": "Bearer no-es-un-token"})
    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["completo"] is True and cuerpo["eliminadas"] == []
    assert datetime.strptime(cuerpo["generado_en"], FORMATO)  # UTC, Z, sin fracciones
    assert [a["id"] for a in cuerpo["alertas"]] == [activa["id"], futura["id"], pasada["id"]]  # por actualizado_en
    assert all(set(a) == set(Alerta.model_fields) for a in cuerpo["alertas"])
    assert cuerpo["alertas"][1]["vigencia_desde"] == "2099-01-01T00:00:00Z"


def test_diferencias_dejan_la_cache_igual_a_la_foto_completa(api):
    """C1 de validation-3-3 con la base: la caché de la app (reemplaza por id, quita inactivas y eliminadas)."""
    quedara = crear(api, mensaje="se queda")
    se_borra = crear(api, mensaje="se borra")
    se_apaga = crear(api, mensaje="se apaga")
    inicial = foto(api)
    cache = {a["id"]: a for a in inicial["alertas"]}

    nueva = crear(api, mensaje="nueva")
    poner(api, quedara["id"], mensaje="se queda editada")
    poner(api, se_apaga["id"], mensaje="se apaga", activa=False)
    api.delete(f"/v1/admin/alerts/{se_borra['id']}")
    diferencia = foto(api, inicial["generado_en"])
    assert diferencia["completo"] is False
    assert {a["id"] for a in diferencia["alertas"]} >= {nueva["id"], quedara["id"], se_apaga["id"]}
    assert se_borra["id"] in diferencia["eliminadas"]
    assert se_borra["id"] not in {a["id"] for a in diferencia["alertas"]}
    for alerta in diferencia["alertas"]:
        if alerta["activa"]:
            cache[alerta["id"]] = alerta
        else:
            cache.pop(alerta["id"], None)
    for alerta_id in diferencia["eliminadas"]:
        cache.pop(alerta_id, None)
    final = foto(api)
    assert {i: a["version"] for i, a in cache.items()} == {a["id"]: a["version"] for a in final["alertas"]}
    assert set(cache) == {quedara["id"], nueva["id"]}


def test_la_diferencia_lleva_el_margen_de_60_s(api, ajustes_al):
    dentro, fuera, borrada = crear(api, mensaje="dentro"), crear(api, mensaje="fuera"), crear(api, mensaje="borrada")
    api.delete(f"/v1/admin/alerts/{borrada['id']}")
    desde = hora_base(ajustes_al).replace(microsecond=0)
    for alerta, segundos in ((dentro, 30), (fuera, 61)):
        t = desde - timedelta(seconds=segundos)
        sql(ajustes_al, "UPDATE alertas SET actualizado_en = :t WHERE id = :i", t=t, i=uuid.UUID(alerta["id"]))
    t = desde - timedelta(seconds=59)
    sql(
        ajustes_al,
        "UPDATE alertas SET actualizado_en = :t, eliminada_en = :e WHERE id = :i",
        t=t,
        e=t,
        i=uuid.UUID(borrada["id"]),
    )
    diferencia = foto(api, desde.strftime(FORMATO))
    assert [a["id"] for a in diferencia["alertas"]] == [dentro["id"]]
    assert diferencia["eliminadas"] == [borrada["id"]]


@pytest.mark.parametrize(("dias", "completo"), [(-91, True), (-89, False), (1, True)])
def test_desde_viejo_o_futuro_da_la_foto_completa(api, ajustes_al, dias, completo):
    activa = crear(api)
    sql(ajustes_al, "UPDATE alertas SET actualizado_en = now() - interval '200 days'")
    desde = (hora_base(ajustes_al) + timedelta(days=dias)).strftime(FORMATO)
    cuerpo = foto(api, desde)
    assert cuerpo["completo"] is completo
    assert [a["id"] for a in cuerpo["alertas"]] == ([activa["id"]] if completo else [])


# --- GET /v1/admin/alerts --------------------------------------------------------------------------------------------
def test_admin_lista_filtra_y_ordena_por_modificacion(api, ajustes_al):
    a = crear(api, mensaje="Café cerrado por obra", tipo="obra", prioridad="alta")
    b = crear(api, mensaje="Bancas nuevas", tipo="mobiliario", activa=False)
    c = crear(api, mensaje="Lago sin baranda", tipo="agua")
    borrada = crear(api, mensaje="Café borrado")
    api.delete(f"/v1/admin/alerts/{borrada['id']}")
    for alerta, dia in ((a, 1), (b, 3), (c, 2)):
        t = datetime(2026, 10, dia, tzinfo=UTC)
        sql(ajustes_al, "UPDATE alertas SET actualizado_en = :t WHERE id = :i", t=t, i=uuid.UUID(alerta["id"]))

    def ids(**params: Any) -> list[str]:
        r = api.get("/v1/admin/alerts", params=params)
        assert r.status_code == 200, r.text
        cuerpo = r.json()
        ListaAlertas.model_validate(cuerpo)
        assert cuerpo["total"] == len(cuerpo["items"])
        return [item["id"] for item in cuerpo["items"]]

    assert ids() == [b["id"], c["id"], a["id"]]
    assert ids(q="  CAFE ") == [a["id"]]
    assert ids(tipo="agua") == [c["id"]]
    assert ids(prioridad="alta") == [a["id"]]
    assert ids(activa="false") == [b["id"]]
    assert ids(q="   ") == [b["id"], c["id"], a["id"]]
    for params, campo in (({"q": "x" * 101}, "q"), ({"q": "a\x00b"}, "q"), ({"tipo": "charco"}, "tipo")):
        r = api.get("/v1/admin/alerts", params=params)
        assert r.status_code == 422 and r.json()["error"]["detalle"]["campos"][0]["campo"] == campo


# --- sincronizar -----------------------------------------------------------------------------------------------------
def test_sincronizar_aplica_cada_cambio_por_separado(api, ajustes_al, logs_json):
    a, b, desconocida = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    d = crear(api, mensaje="se elimina")
    cambios = [
        {"op": "upsert", "alerta": {"id": str(a)} | entrada("A válida")},
        {"op": "upsert", "alerta": {"id": str(b)} | entrada("B no válida", radio_m=500)},
        {"op": "eliminar", "id": d["id"]},
        {"op": "eliminar", "id": str(desconocida)},
        {"op": "upsert", "alerta": {"id": str(a), "version": 99} | entrada("A editada")},
    ]
    r = api.post("/v1/admin/alerts/sincronizar", json={"cambios": cambios})
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert set(cuerpo) == {"generado_en", "resultados"} and datetime.strptime(cuerpo["generado_en"], FORMATO)
    assert [(x["id"], x["op"], x["estado"], x["codigo"]) for x in cuerpo["resultados"]] == [
        (str(a), "upsert", "ok", None),
        (str(b), "upsert", "error", "VALIDACION"),
        (d["id"], "eliminar", "ok", None),
        (str(desconocida), "eliminar", "ok", None),
        (str(a), "upsert", "ok", None),
    ]
    assert fila(ajustes_al, str(a)).version == 2
    assert fila(ajustes_al, d["id"]).eliminada_en is not None
    assert sql(ajustes_al, "SELECT count(*) FROM alertas WHERE id IN (:b, :x)", b=b, x=desconocida)[0][0] == 0
    origenes = [detalle["origen"] for *_, detalle in auditoria(ajustes_al, "alerta.upsert")]
    assert origenes == ["put", "sincronizar", "sincronizar"]
    assert [detalle["origen"] for *_, detalle in auditoria(ajustes_al, "alerta.eliminar")] == ["sincronizar"]
    [evento] = eventos(logs_json, "alertas_sincronizadas")
    assert (evento["cambios"], evento["ok"], evento["errores"]) == (5, 4, 1)
    assert [x["mensaje"] for x in api.get("/v1/admin/alerts").json()["items"]] == ["A editada"]


def test_sincronizar_con_el_sobre_no_valido_es_422_y_no_aplica_nada(api, ajustes_al):
    cambios = [
        {"op": "upsert", "alerta": {"id": str(uuid.uuid4())} | entrada()},
        {"op": "mover", "id": str(uuid.uuid4())},
    ]
    r = api.post("/v1/admin/alerts/sincronizar", json={"cambios": cambios})
    assert r.status_code == 422 and r.json()["error"]["detalle"]["campos"][0]["campo"] == "cambios.1.op"
    assert sql(ajustes_al, "SELECT count(*) FROM alertas")[0][0] == 0
    vacio = api.post("/v1/admin/alerts/sincronizar", json={"cambios": []})
    assert vacio.status_code == 422 and vacio.json()["error"]["detalle"]["campos"][0]["campo"] == "cambios"


# --- Resumen del panel (C5) y purga ---------------------------------------------------------------------------------
def test_alertas_activas_del_resumen_sube_con_una_activa_y_no_con_una_inactiva(api):
    def activas() -> int:
        r = api.get("/v1/admin/stats")
        assert r.status_code == 200
        return r.json()["alertas_activas"]

    s0 = activas()
    activa = crear(api)
    crear(api, activa=False)
    assert activas() - s0 == 1
    poner(api, activa["id"], activa=False)
    assert activas() == s0
    poner(api, activa["id"])
    api.delete(f"/v1/admin/alerts/{activa['id']}")
    assert activas() == s0


def test_purgar_tombstones_borra_solo_las_viejas(api, ajustes_al):
    vieja, reciente, viva = crear(api, mensaje="vieja"), crear(api, mensaje="reciente"), crear(api, mensaje="viva")
    api.delete(f"/v1/admin/alerts/{vieja['id']}")
    api.delete(f"/v1/admin/alerts/{reciente['id']}")
    sql(ajustes_al, "UPDATE alertas SET actualizado_en = now() - interval '200 days'")
    sql(
        ajustes_al,
        "UPDATE alertas SET eliminada_en = now() - interval '91 days' WHERE id = :i",
        i=uuid.UUID(vieja["id"]),
    )
    sql(
        ajustes_al,
        "UPDATE alertas SET eliminada_en = now() - interval '89 days' WHERE id = :i",
        i=uuid.UUID(reciente["id"]),
    )

    async def purgar() -> int:
        motor = sesion.crear_motor(ajustes_al, "pruebas")
        try:
            return await alertas.purgar_tombstones(motor, 90)
        finally:
            await motor.dispose()

    assert asyncio.run(purgar()) == 1
    quedan = {str(f[0]) for f in sql(ajustes_al, "SELECT id FROM alertas")}
    assert quedan == {reciente["id"], viva["id"]}
    assert asyncio.run(purgar()) == 0
