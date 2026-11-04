"""Pruebas de src/ops/comun.py sin red, sin Gradle y sin dispositivo."""

from __future__ import annotations

import json
from pathlib import Path

import comun
import pytest


def test_url_api_config_del_repositorio_tiene_la_forma_esperada():
    url = comun.url_api_config()
    assert url.startswith("https://")
    assert url.endswith("/v1")


@pytest.mark.parametrize(
    ("contenido", "esperada"),
    [
        (
            'object ApiConfig {\n const val API_BASE_URL = "https://x.example.com"\n'
            ' const val BASE_URL = "$API_BASE_URL/v1"\n}',
            "https://x.example.com/v1",
        ),
        ('const val API_BASE_URL = "https://y.com"\nconst val BASE_URL = "${API_BASE_URL}/v1"', "https://y.com/v1"),
        ('const val BASE_URL = "https://literal.com/v1"', "https://literal.com/v1"),
    ],
)
def test_url_api_config_resuelve_la_plantilla(tmp_path: Path, contenido: str, esperada: str):
    archivo = tmp_path / "ApiConfig.kt"
    archivo.write_text(contenido, encoding="utf-8")
    assert comun.url_api_config(archivo) == esperada


def test_url_api_config_sin_base_url_es_falla(tmp_path: Path):
    archivo = tmp_path / "ApiConfig.kt"
    archivo.write_text('const val HOST = "1.2.3.4"', encoding="utf-8")
    with pytest.raises(comun.Falla):
        comun.url_api_config(archivo)


def test_comprobar_forma_url():
    assert comun.comprobar_forma_url("https://a.com/v1/", "X") == "https://a.com/v1"
    with pytest.raises(comun.ErrorConfiguracion):
        comun.comprobar_forma_url("http://a.com/v1", "X")
    with pytest.raises(comun.ErrorConfiguracion):
        comun.comprobar_forma_url("https://a.com", "X")


def test_url_api_vigente_usa_la_variable_si_no_hay_terraform(monkeypatch):
    def sin_terraform(nombre, directorio=None):
        raise comun.ErrorConfiguracion("sin terraform")

    monkeypatch.setattr(comun, "terraform_output_raw", sin_terraform)
    monkeypatch.setenv("VALIDACION_API_URL", "https://z.com/v1")
    assert comun.url_api_vigente() == ("https://z.com/v1", "VALIDACION_API_URL")
    monkeypatch.delenv("VALIDACION_API_URL")
    with pytest.raises(comun.ErrorConfiguracion):
        comun.url_api_vigente()


def test_url_api_vigente_prefiere_terraform(monkeypatch):
    monkeypatch.setattr(comun, "terraform_output_raw", lambda nombre, directorio=None: "https://tf.com/")
    monkeypatch.setenv("VALIDACION_API_URL", "https://otra.com/v1")
    assert comun.url_api_vigente() == ("https://tf.com/v1", "terraform output api_base_url")


def test_resultados_clase(tmp_path: Path):
    (tmp_path / "TEST-com.example.app.MapeoErroresApiTest.xml").write_text(
        '<?xml version="1.0"?><testsuite name="x" tests="14" skipped="0" failures="1" errors="0"></testsuite>',
        encoding="utf-8",
    )
    r = comun.resultados_clase("MapeoErroresApiTest", tmp_path)
    assert (r.pruebas, r.fallos, r.errores) == (14, 1, 0)
    assert not r.ok
    assert comun.resultados_clase("OtraTest", tmp_path) is None
    comun.borrar_resultados(["MapeoErroresApiTest"], tmp_path)
    assert comun.resultados_clase("MapeoErroresApiTest", tmp_path) is None


def test_dispositivos():
    salida = "List of devices attached\nabc123\tdevice\nemulator-5554\toffline\n\n"
    assert comun.dispositivos(salida) == [("abc123", "device"), ("emulator-5554", "offline")]


def test_comando_gradle_y_adb_respetan_las_variables(monkeypatch):
    monkeypatch.setenv("VALIDACION_GRADLE", r"cmd.exe /c .\gradlew.bat")
    assert comun.comando_gradle() == ["cmd.exe", "/c", r".\gradlew.bat"]  # la barra invertida se conserva
    monkeypatch.setenv("VALIDACION_ADB", "/mnt/c/sdk/platform-tools/adb.exe")
    assert comun.comando_adb() == ["/mnt/c/sdk/platform-tools/adb.exe"]


def _validador(**kw):
    return comun.Validador(
        lote="FE-9.9", validacion="validation-9-9", descripcion="x", comprobaciones=["C1", "C2"], **kw
    )


@pytest.mark.parametrize(
    ("cuerpo", "codigo", "resultado"),
    [
        (lambda v: v.comprobacion("C1", lambda: "ok"), 0, "pasa"),
        (lambda v: v.comprobacion("C1", lambda: (_ for _ in ()).throw(comun.Falla("no"))), 1, "falla"),
        (lambda v: v.precondicion("P1", lambda: (_ for _ in ()).throw(comun.Bloqueo("BE-1.1"))), 2, "bloqueado"),
        (lambda v: v.precondicion("P1", lambda: (_ for _ in ()).throw(comun.ErrorConfiguracion("x"))), 3, "error"),
        (lambda v: v.comprobacion("C1", lambda: 1 / 0), 3, "error"),
    ],
)
def test_codigos_de_salida_e_informe(tmp_path: Path, cuerpo, codigo, resultado):
    informe = tmp_path / "i.json"
    v = _validador()
    assert v.correr(cuerpo, ["--entorno", "local", "--informe", str(informe)]) == codigo
    datos = json.loads(informe.read_text(encoding="utf-8"))
    assert datos["resultado"] == resultado
    assert datos["lote"] == "FE-9.9"
    assert datos["entorno"] == "local"


def test_solo_omite_y_rechaza_desconocidos(tmp_path: Path):
    llamadas = []
    v = _validador(grupos={"G": ["C2"]})

    def cuerpo(v):
        v.comprobacion("C1", lambda: llamadas.append("C1") or "ok")
        v.comprobacion("C2", lambda: llamadas.append("C2") or "ok")

    assert v.correr(cuerpo, ["--entorno", "dev", "--solo", "G", "--informe", str(tmp_path / "a.json")]) == 0
    assert llamadas == ["C2"]
    assert _validador().correr(cuerpo, ["--entorno", "dev", "--solo", "C9"]) == 3


def test_entorno_no_admitido_es_3():
    v = comun.Validador(lote="X", validacion="x", descripcion="", comprobaciones=["C1"], entornos=("dev",))
    assert v.correr(lambda v: None, ["--entorno", "local"]) == 3


def test_limpieza_en_orden_inverso_tambien_si_falla(tmp_path: Path):
    orden = []

    def cuerpo(v):
        v.al_limpiar("a", lambda: orden.append("a"))
        v.al_limpiar("b", lambda: orden.append("b"))
        raise RuntimeError("se rompe")

    assert _validador().correr(cuerpo, ["--entorno", "local", "--informe", str(tmp_path / "x.json")]) == 3
    assert orden == ["b", "a"]


def test_commit_actual_ignora_los_finales_de_linea(monkeypatch):
    llamadas = []

    def falso(comando, **kw):
        llamadas.append(comando)
        return comun.Resultado(0, "abc1234\n" if "rev-parse" in comando else "", "")

    monkeypatch.setattr(comun, "ejecutar", falso)
    assert comun.commit_actual() == "abc1234"
    assert llamadas[1][:3] == ["git", "-c", "core.autocrlf=input"]
