"""Contrato común de los validadores (infra ARCHITECTURE §5.11): orden, estados, códigos de salida e informe."""

from __future__ import annotations

import json

import pytest

import comun
from comun import ErrorConfiguracion, Falla, PrecondicionNoCumplida, Validador


def _validador(tmp_path, *argumentos: str) -> Validador:
    v = Validador(lote="BE-9.9", validacion="validation-9-9", entornos=("dev",))
    v.iniciar(["--entorno", "dev", "--informe", str(tmp_path / "informe.json"), *argumentos])
    return v


def _informe(tmp_path) -> dict:
    return json.loads((tmp_path / "informe.json").read_text(encoding="utf-8"))


def test_todo_pasa_da_0_e_informe_completo(tmp_path, capsys):
    v = _validador(tmp_path)
    codigo = v.ejecutar(
        precondiciones=[("P1", lambda: "ok")],
        comprobaciones=[("C1", lambda: "bien"), ("C2a", lambda: None)],
        manuales=[("C3", "Mira la pantalla")],
    )
    assert codigo == 0
    salida = capsys.readouterr().out
    assert "[PASA] P1 ok" in salida
    assert "[PASA] C1 bien" in salida
    assert "[MANUAL] C3 Mira la pantalla" in salida
    informe = _informe(tmp_path)
    assert informe["lote"] == "BE-9.9"
    assert informe["validacion"] == "validation-9-9"
    assert informe["entorno"] == "dev"
    assert informe["resultado"] == "pasa"
    assert [c["id"] for c in informe["comprobaciones"]] == ["C1", "C2a"]
    assert all("duracion_ms" in c for c in informe["comprobaciones"])
    assert informe["manuales"] == [{"id": "C3", "instruccion": "Mira la pantalla"}]
    assert informe["inicio"].endswith("Z") and informe["fin"].endswith("Z")


def test_una_falla_da_1_y_sigue_con_las_demas(tmp_path):
    vistas = []

    def falla():
        raise Falla("no cumple")

    def explota():
        raise RuntimeError("bug")

    v = _validador(tmp_path)
    codigo = v.ejecutar(
        precondiciones=[],
        comprobaciones=[("C1", falla), ("C2", explota), ("C3", lambda: vistas.append("C3"))],
    )
    assert codigo == 1
    assert vistas == ["C3"]
    estados = {c["id"]: c["estado"] for c in _informe(tmp_path)["comprobaciones"]}
    assert estados == {"C1": "falla", "C2": "falla", "C3": "pasa"}
    assert _informe(tmp_path)["resultado"] == "falla"


@pytest.mark.parametrize(
    ("excepcion", "codigo", "resultado"),
    [
        (PrecondicionNoCumplida("INF-1.3 no listo"), 2, "bloqueado"),
        (ErrorConfiguracion("falta AWS_PROFILE"), 3, "error"),
        (RuntimeError("inesperado"), 3, "error"),
    ],
)
def test_precondicion_que_no_se_cumple_detiene_y_limpia(tmp_path, excepcion, codigo, resultado):
    limpiezas = []

    def p2():
        raise excepcion

    v = _validador(tmp_path)
    obtenido = v.ejecutar(
        precondiciones=[("P1", lambda: "ok"), ("P2", p2), ("P3", lambda: pytest.fail("no debe correr"))],
        comprobaciones=[("C1", lambda: pytest.fail("no debe correr"))],
        limpieza=lambda: limpiezas.append("hecha"),
    )
    assert obtenido == codigo
    assert limpiezas == ["hecha"]
    informe = _informe(tmp_path)
    assert informe["resultado"] == resultado
    assert [p["id"] for p in informe["precondiciones"]] == ["P1", "P2"]
    assert informe["comprobaciones"] == []


def test_solo_filtra_por_criterio(tmp_path):
    v = _validador(tmp_path, "--solo", "C2,C3b")
    v.ejecutar(
        precondiciones=[],
        comprobaciones=[(i, lambda: "x") for i in ("C1", "C2a", "C2b", "C3a", "C3b")],
    )
    estados = {c["id"]: c["estado"] for c in _informe(tmp_path)["comprobaciones"]}
    assert estados == {"C1": "omitida", "C2a": "pasa", "C2b": "pasa", "C3a": "omitida", "C3b": "pasa"}


def test_sin_limpieza(tmp_path):
    limpiezas = []
    v = _validador(tmp_path, "--sin-limpieza")
    v.ejecutar(precondiciones=[], comprobaciones=[], limpieza=lambda: limpiezas.append(1))
    assert limpiezas == []


def test_entorno_no_admitido_o_argumentos_malos_dan_3():
    v = Validador(lote="BE-9.9", validacion="validation-9-9", entornos=("dev",))
    with pytest.raises(SystemExit) as salida:
        v.iniciar(["--entorno", "local"])
    assert salida.value.code == 3
    with pytest.raises(SystemExit) as salida:
        Validador(lote="X", validacion="y", entornos=("dev",)).iniciar(["--desconocido"])
    assert salida.value.code == 3


def test_url_api(monkeypatch):
    monkeypatch.delenv("VALIDACION_API_URL", raising=False)
    assert comun.url_api({"api_base_url": "https://abc.execute-api.us-east-1.amazonaws.com/"}) == (
        "https://abc.execute-api.us-east-1.amazonaws.com/v1"
    )
    with pytest.raises(PrecondicionNoCumplida):
        comun.url_api({})
    monkeypatch.setenv("VALIDACION_API_URL", "http://localhost:8000/v1/")
    assert comun.url_api({}) == "http://localhost:8000/v1"


def test_sesion_aws_exige_perfil(monkeypatch):
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    with pytest.raises(ErrorConfiguracion):
        comun.sesion_aws()
