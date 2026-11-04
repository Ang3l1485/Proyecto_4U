"""Pruebas de validate31.py (INF-3.1) contra el AWS falso de falsos.py, con reloj falso (las esperas no tardan).

Uso (desde INFRASTRUCTURA_TERRAFORM/project/): uv run --group ops --group pruebas pytest tests/ops -q
"""

from __future__ import annotations

import datetime as dt
import json
import sys

import pytest

import comun
import falsos
import validate31


@pytest.fixture
def mundo(monkeypatch, tmp_path):
    m = falsos.Mundo()
    reloj = falsos.Reloj(m)
    monkeypatch.setattr(comun, "time", reloj)
    monkeypatch.setattr(validate31, "time", reloj)
    monkeypatch.setattr(comun, "ahora_utc", m.ahora)
    monkeypatch.setattr(comun, "sesion_aws", lambda: falsos.Sesion(m))
    monkeypatch.setattr(comun, "commit_actual", lambda: "prueba")
    m.salidas = falsos.salidas()
    monkeypatch.setattr(comun, "terraform_outputs", lambda directorio: m.salidas)
    monkeypatch.setattr(validate31, "leer_correo", lambda: falsos.CORREO)
    m.informe = tmp_path / "informe.json"
    return m


def correr(m, monkeypatch, *extra: str) -> tuple[int, dict]:
    monkeypatch.setattr(sys, "argv", ["validate31.py", "--entorno", "dev", "--informe", str(m.informe), *extra])
    codigo = validate31.main()
    return codigo, json.loads(m.informe.read_text(encoding="utf-8"))


def estados(informe: dict) -> dict[str, str]:
    return {r["id"]: r["estado"] for r in informe["precondiciones"] + informe["comprobaciones"]}


def detalle(informe: dict, id_: str) -> str:
    return next(r["detalle"] for r in informe["precondiciones"] + informe["comprobaciones"] if r["id"] == id_)


def cuerpo_propio(sello: str) -> str:
    return json.dumps({"validacion": f"validacion-3-1-{sello}"})


# ---------------------------------------------------------------------------------------------------------------------
# Todo bien
# ---------------------------------------------------------------------------------------------------------------------


def test_todo_bien(mundo, monkeypatch, capsys):
    codigo, informe = correr(mundo, monkeypatch)
    salida = capsys.readouterr()
    assert codigo == 0, salida.out
    assert set(estados(informe).values()) == {"pasa"}
    assert [r["id"] for r in informe["comprobaciones"]] == ["C1a", "C1b", "C1c", "C3a", "C3b", "C2a"]
    assert [r["id"] for r in informe["manuales"]] == ["C2b", "C3c"]
    # C2: un mensaje en ingesta-dlq, la alarma avisó y el mensaje se borró
    assert len(mundo.enviados) == 1 and mundo.enviados[0][0].endswith("campus-locator-dev-ingesta-dlq")
    assert mundo.borrados == [mundo.enviados[0][1]]
    assert all(not mensajes for mensajes in mundo.colas.values())
    assert "campus-locator-dev-ingesta-dlq → ALARM" in detalle(informe, "C2a")
    # C3: tarea de la definición de validación, sin group (ECS no admite service:…) y con startedBy validacion-3-1, que
    # sale con error; no toca los servicios
    (args,) = mundo.run_task_args
    assert args["taskDefinition"] == "campus-locator-dev-validacion"
    assert "group" not in args and args["startedBy"] == "validacion-3-1"
    assert args["overrides"]["containerOverrides"][0]["command"][-1].endswith("exit 3")
    assert "group family:campus-locator-dev-validacion" in detalle(informe, "C3a")
    assert "EssentialContainerExited" in detalle(informe, "C3a")
    assert "TestEventPattern: 9 casos como se espera" in detalle(informe, "C1b")
    # El correo no se imprime entero
    assert falsos.CORREO not in salida.out + salida.err + json.dumps(informe)
    assert "pe…@example.com" in salida.out


def test_solo_c1_no_crea_nada(mundo, monkeypatch):
    codigo, informe = correr(mundo, monkeypatch, "--solo", "C1")
    assert codigo == 0
    assert estados(informe)["C2a"] == "omitida" and estados(informe)["C3a"] == "omitida"
    assert mundo.enviados == [] and mundo.run_task_args == []
    assert informe["manuales"] == []


def test_c3b_solo_lanza_la_tarea(mundo, monkeypatch):
    codigo, informe = correr(mundo, monkeypatch, "--solo", "C3b")
    assert codigo == 0
    assert estados(informe)["C3b"] == "pasa" and estados(informe)["C3a"] == "omitida"
    assert len(mundo.run_task_args) == 1


def test_sin_limpieza_deja_el_mensaje(mundo, monkeypatch, capsys):
    codigo, _ = correr(mundo, monkeypatch, "--solo", "C2", "--sin-limpieza")
    assert codigo == 0
    assert mundo.borrados == []
    assert "--sin-limpieza: queda" in capsys.readouterr().err


# ---------------------------------------------------------------------------------------------------------------------
# Precondiciones
# ---------------------------------------------------------------------------------------------------------------------


def test_otra_cuenta_es_error_de_configuracion(mundo, monkeypatch):
    mundo.cuenta = "111111111111"
    codigo, informe = correr(mundo, monkeypatch)
    assert codigo == 3
    assert estados(informe)["P4"] == "falla"
    assert mundo.enviados == [] and mundo.run_task_args == []


def test_sin_api_bloquea(mundo, monkeypatch):
    mundo.apis = []
    codigo, informe = correr(mundo, monkeypatch)
    assert codigo == 2
    assert "INF-1.4 no está aplicado" in detalle(informe, "P1")


def test_sin_apagado_nocturno_bloquea(mundo, monkeypatch):
    mundo.acciones_noche = []
    codigo, informe = correr(mundo, monkeypatch)
    assert codigo == 2
    assert "INF-2.1 no está aplicado" in detalle(informe, "P2")


def test_sin_output_sns_bloquea(mundo, monkeypatch):
    mundo.salidas = falsos.salidas(sns_alertas_arn=None)
    codigo, informe = correr(mundo, monkeypatch)
    assert codigo == 2
    assert "falta el output sns_alertas_arn" in detalle(informe, "P3")
    assert mundo.enviados == [] and mundo.run_task_args == []


# ---------------------------------------------------------------------------------------------------------------------
# C1: configuración
# ---------------------------------------------------------------------------------------------------------------------


def test_c1a_umbral_y_accion(mundo, monkeypatch):
    mundo.alarmas["campus-locator-dev-api-5xx"]["Threshold"] = 10.0
    mundo.alarmas["campus-locator-dev-rds-creditos-cpu"]["AlarmActions"] = []
    del mundo.alarmas["campus-locator-dev-embedding-encendida"]
    codigo, informe = correr(mundo, monkeypatch, "--solo", "C1a")
    assert codigo == 1
    texto = detalle(informe, "C1a")
    assert "api-5xx: Threshold = 10.0 (se espera 5.0)" in texto
    assert "rds-creditos-cpu: acciones [], no avisa" in texto
    assert "no existe la alarma campus-locator-dev-embedding-encendida" in texto


def test_c1a_no_confunde_las_alarmas_de_escalado(mundo, monkeypatch):
    # Una alarma de escalado de INF-2.1 con el mismo prefijo no cuenta ni estorba.
    mundo.alarmas["campus-locator-dev-worker-cola-ingesta"] = {"AlarmName": "campus-locator-dev-worker-cola-ingesta"}
    codigo, _ = correr(mundo, monkeypatch, "--solo", "C1a")
    assert codigo == 0


@pytest.mark.parametrize(
    "romper, esperado",
    [
        (lambda m: m.regla.update(State="DISABLED"), "la regla está DISABLED"),
        (
            lambda m: m.regla.update(EventPattern=json.dumps(falsos.patron_0_14())),
            "con «tarea de prueba de validate31» la regla no avisaría",
        ),
        (
            # Sin la condición de grupo ni de startedBy: avisaría de cualquier tarea del clúster
            lambda m: m.regla.update(
                EventPattern=json.dumps(
                    {**falsos.patron_bien(), "detail": {k: v for k, v in falsos.patron_bien()["detail"].items() if k != "$or"}}
                )
            ),
            "con «migrate que termina (aunque salga con 0)» la regla avisaría",
        ),
        (lambda m: setattr(m, "destinos", []), "destinos []"),
        (lambda m: m.politica["Statement"].pop(2), "no deja publicar a events.amazonaws.com"),
        (lambda m: setattr(m, "regla", None), "no existe la regla"),
    ],
)
def test_c1b_detecta(mundo, monkeypatch, romper, esperado):
    romper(mundo)
    codigo, informe = correr(mundo, monkeypatch, "--solo", "C1b")
    assert codigo == 1
    assert esperado in detalle(informe, "C1b")


def test_c1b_sin_permiso_para_las_alarmas(mundo, monkeypatch):
    mundo.politica["Statement"] = [s for s in mundo.politica["Statement"] if s["Sid"] == "EventBridge"]
    codigo, informe = correr(mundo, monkeypatch, "--solo", "C1b")
    assert codigo == 1
    assert "no deja publicar a las alarmas" in detalle(informe, "C1b")


def test_suscripcion_pendiente(mundo, monkeypatch):
    mundo.pendiente = True
    codigo, informe = correr(mundo, monkeypatch)
    assert codigo == 1
    e = estados(informe)
    assert e["C1c"] == "falla" and e["C2a"] == "falla" and e["C3b"] == "falla"
    assert "pendiente de confirmación" in detalle(informe, "C1c")
    assert "pendiente de confirmación" in detalle(informe, "C2a")
    assert mundo.enviados == []  # C2a no envía nada si nadie recibiría el correo
    # C3b dice que la regla funcionó y por qué no llegaría el correo, sin esperar las métricas de SNS
    assert "1 invocación(es)" in detalle(informe, "C3b") and "pendiente de confirmación" in detalle(informe, "C3b")
    assert mundo.mono - 1000 < 10 * 60  # sin las esperas de SNS (10 min) de C3b ni de C2a


def test_sin_suscripcion_al_correo(mundo, monkeypatch):
    mundo.suscripciones = [{"Protocol": "email", "Endpoint": "otra@example.com", "SubscriptionArn": "arn:x"}]
    codigo, informe = correr(mundo, monkeypatch, "--solo", "C1c")
    assert codigo == 1
    assert "no tiene una suscripción email a pe…@example.com" in detalle(informe, "C1c")


# ---------------------------------------------------------------------------------------------------------------------
# C2: DLQ
# ---------------------------------------------------------------------------------------------------------------------


def test_c2_usa_purga_si_ingesta_tiene_ajenos(mundo, monkeypatch):
    sqs = falsos.Sqs(mundo)
    url_ingesta = mundo.salidas["sqs_ingesta_dlq_url"]
    sqs.send_message(QueueUrl=url_ingesta, MessageBody='{"Records": "fallo real"}')
    mundo.alarmas["campus-locator-dev-ingesta-dlq"]["StateValue"] = "ALARM"
    mundo.enviados.clear()
    codigo, informe = correr(mundo, monkeypatch, "--solo", "C2")
    assert codigo == 0
    assert mundo.enviados[0][0].endswith("campus-locator-dev-purga-dlq")
    # El ajeno sigue en su cola, visible, y se recibió como mucho una vez (limpieza de restos al empezar)
    (ajeno,) = mundo.colas[url_ingesta]
    assert ajeno["visible_desde"] <= mundo.t and ajeno["recibido"] <= 1
    assert "campus-locator-dev-purga-dlq → ALARM" in detalle(informe, "C2a")


def test_c2_falla_si_las_dos_dlq_tienen_ajenos(mundo, monkeypatch):
    sqs = falsos.Sqs(mundo)
    for url in mundo.colas:
        sqs.send_message(QueueUrl=url, MessageBody="ajeno")
    for nombre in ("campus-locator-dev-ingesta-dlq", "campus-locator-dev-purga-dlq"):
        mundo.alarmas[nombre]["StateValue"] = "ALARM"
    mundo.enviados.clear()
    codigo, informe = correr(mundo, monkeypatch, "--solo", "C2")
    assert codigo == 1
    assert "las dos DLQ tienen mensajes ajenos" in detalle(informe, "C2a")
    assert mundo.enviados == [] and mundo.borrados == []
    assert all(len(mensajes) == 1 for mensajes in mundo.colas.values())


def test_c2_espera_ok_de_una_dlq_vacia_en_alarm(mundo, monkeypatch):
    for nombre in ("campus-locator-dev-ingesta-dlq", "campus-locator-dev-purga-dlq"):
        mundo.alarmas[nombre]["StateValue"] = "ALARM"
    codigo, informe = correr(mundo, monkeypatch, "--solo", "C2")
    # El mundo falso la pasa a OK en la primera actualización (cola vacía)
    assert codigo == 0, detalle(informe, "C2a")


def test_c2_borra_restos_viejos_y_no_los_recientes(mundo, monkeypatch):
    sqs = falsos.Sqs(mundo)
    url = mundo.salidas["sqs_ingesta_dlq_url"]
    viejo = (mundo.t - dt.timedelta(hours=2)).strftime("%Y%m%d-%H%M%S")
    reciente = (mundo.t - dt.timedelta(minutes=5)).strftime("%Y%m%d-%H%M%S")
    sqs.send_message(QueueUrl=url, MessageBody=cuerpo_propio(viejo))
    sqs.send_message(QueueUrl=url, MessageBody=cuerpo_propio(reciente))
    mundo.enviados.clear()
    codigo, _ = correr(mundo, monkeypatch, "--solo", "C2")
    assert codigo == 0
    assert cuerpo_propio(viejo) in mundo.borrados
    assert [m["Body"] for m in mundo.colas[url]] == [cuerpo_propio(reciente)]  # de otra ejecución reciente: ajeno
    assert mundo.enviados[0][0].endswith("campus-locator-dev-purga-dlq")


def test_c2_alarma_que_no_dispara(mundo, monkeypatch):
    mundo.alarma_dispara = False
    codigo, informe = correr(mundo, monkeypatch, "--solo", "C2")
    assert codigo == 1
    assert "no pasó a ALARM en 20.0 min" in detalle(informe, "C2a")
    assert mundo.borrados == [mundo.enviados[0][1]]  # la limpieza borra el mensaje igual


def test_c2_accion_fallida(mundo, monkeypatch):
    mundo.accion_ok = False
    codigo, informe = correr(mundo, monkeypatch, "--solo", "C2")
    assert codigo == 1
    assert "no pudo avisar" in detalle(informe, "C2a")
    assert mundo.borrados == [mundo.enviados[0][1]]


def test_c2_tolera_metricas_lentas(mundo, monkeypatch):
    mundo.retraso_alarma = 15 * 60
    mundo.retraso_metricas = 8 * 60
    codigo, informe = correr(mundo, monkeypatch, "--solo", "C2")
    assert codigo == 0, detalle(informe, "C2a")


# ---------------------------------------------------------------------------------------------------------------------
# C3: tarea detenida por error
# ---------------------------------------------------------------------------------------------------------------------


def test_c3_parada_que_no_es_error(mundo, monkeypatch):
    mundo.stop_code = "ServiceSchedulerInitiated"
    codigo, informe = correr(mundo, monkeypatch, "--solo", "C3")
    assert codigo == 1
    assert "stopCode 'ServiceSchedulerInitiated'" in detalle(informe, "C3a")
    assert "no registró ningún evento coincidente" in detalle(informe, "C3b")


def test_c3_con_el_patron_viejo_no_casa(mundo, monkeypatch):
    # La regla de 0.14.0 (solo group = service:…) no casa con la tarea de prueba: C3b lo detecta
    mundo.regla["EventPattern"] = json.dumps(falsos.patron_0_14())
    codigo, informe = correr(mundo, monkeypatch, "--solo", "C3")
    assert codigo == 1
    assert estados(informe)["C3a"] == "pasa"
    assert "no registró ningún evento coincidente" in detalle(informe, "C3b")


def test_c3_run_task_que_falla(mundo, monkeypatch):
    mundo.run_task_falla = "ClusterNotFoundException"
    codigo, informe = correr(mundo, monkeypatch, "--solo", "C3")
    assert codigo == 1
    assert "(ecs:RunTask): ClusterNotFoundException" in detalle(informe, "C3a")
    assert "no se pudo usar" in detalle(informe, "C3b")
    assert len(mundo.run_task_args) == 1  # C3b no lo reintenta


def test_el_falso_rechaza_group_de_servicio_como_ecs(mundo):
    # Lo que respondió ECS en dev el 2026-10-26 (CloudTrail): una tarea suelta no puede llevar group = service:…
    with pytest.raises(Exception, match="Invalid namespace for group."):
        falsos.Ecs(mundo).run_task(taskDefinition="x", group="service:worker")


def test_c3_sin_permiso_de_eventbridge_en_el_topic(mundo, monkeypatch):
    mundo.politica["Statement"].pop(2)
    codigo, informe = correr(mundo, monkeypatch, "--solo", "C3")
    assert codigo == 1
    assert estados(informe)["C3a"] == "pasa"
    assert "invocación(es) fallida(s)" in detalle(informe, "C3b")


def test_c3_detiene_tareas_vivas_al_limpiar(mundo, monkeypatch):
    mundo.dura_tarea = 10**6  # no se detiene sola
    monkeypatch.setitem(validate31.T, "tarea", 60)
    codigo, informe = correr(mundo, monkeypatch, "--solo", "C3a")
    assert codigo == 1
    assert "no se detuvo" in detalle(informe, "C3a")
    (tarea,) = mundo.tareas.values()
    assert tarea["lastStatus"] == "STOPPED" and tarea["stopCode"] == "UserInitiated"


# ---------------------------------------------------------------------------------------------------------------------
# Piezas
# ---------------------------------------------------------------------------------------------------------------------


def test_clasificar():
    sello = "20261028-150000"
    assert validate31.clasificar(cuerpo_propio(sello), sello) == "propio"
    assert validate31.clasificar(cuerpo_propio("20261028-130000"), sello) == "resto"
    assert validate31.clasificar(cuerpo_propio("20261028-145000"), sello) == "ajeno"
    assert validate31.clasificar('{"Records": []}', sello) == "ajeno"
    assert validate31.clasificar("no es json", sello) == "ajeno"
    assert validate31.clasificar('{"validacion": "validacion-2-1-20261028-130000"}', sello) == "ajeno"


def test_casos_del_patron_y_patron_esperado_concuerdan():
    # Los casos de C1b dan lo esperado con patron_esperado() y con el patrón del módulo (patron_bien)
    for patron in (validate31.patron_esperado(), falsos.patron_bien()):
        for descripcion, evento, debe in validate31.CASOS_PATRON:
            assert falsos.coincide(patron, evento) is debe, descripcion
    assert validate31.normalizar_patron(validate31.patron_esperado()) == validate31.normalizar_patron(
        falsos.patron_bien()
    )


def test_enmascarar():
    assert validate31.enmascarar("persona@example.com") == "pe…@example.com"


def test_alarmas_esperadas_coinciden_con_el_mundo():
    vistas = falsos.alarmas_bien()
    for nombre, esperada in validate31.alarmas_esperadas(falsos.API_ID).items():
        a = vistas[nombre]
        assert {d["Name"]: d["Value"] for d in a["Dimensions"]} == esperada["Dimensions"]
        assert a["Threshold"] == esperada["Threshold"]
