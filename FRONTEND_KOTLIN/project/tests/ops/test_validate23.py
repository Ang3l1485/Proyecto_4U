"""Pruebas de validate23.py con Gradle y adb simulados (sin teléfono ni JDK)."""

from __future__ import annotations

import json
from pathlib import Path

import comun
import pytest
import validate23

PREFS = """<?xml version='1.0' encoding='utf-8' standalone='yes' ?>
<map>
    <string name="longitud_paso_m">0.7098</string>
    <int name="pasos" value="47" />
    <string name="distancia_m">33.36</string>
    <long name="fecha_ms" value="1761400000000" />
</map>
"""  # 1761400000000 ms = 2025-10-25 08:46 Bogotá

JS_BUENO = """// Reutiliza MapaBase (mapa_base.js): iniciar, crearMapa y esc. Antes: base.crearMapa( (no existe)
(function () {
  const base = MapaBase.iniciar({ puente: 'RecoleccionBridge' });
  if (!base.leaflet) return;
  /* no usar base.crearMapa(...) */
  const url = 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png'; // base.crearMapa( en comentario
  const mapa = MapaBase.crearMapa({ centro: [6.2, -75.57], zoom: 17 });
})();
"""


class _Simulado:
    """Gradle y adb falsos para recorrer `main()` entero."""

    def __init__(
        self,
        tmp_path: Path,
        *,
        casos=None,
        fallos=None,
        omitidas=None,
        sin_xml=(),
        codigo_tests=0,
        instalar="",
        dispositivo=True,
        prefs=PREFS,
        recorridos=None,
    ):
        self.tmp = tmp_path
        self.casos = casos or {
            "CalibracionPasoTest": 13,
            "StepDetectorTest": 11,
            "DisparadorCapturaTest": 10,
            "DerivaTest": 6,
        }
        self.fallos = fallos or {}
        self.omitidas = omitidas or {}
        self.sin_xml = set(sin_xml)
        self.codigo_tests = codigo_tests
        self.instalar = instalar
        self.dispositivo = dispositivo
        self.prefs = prefs
        self.recorridos = (
            recorridos
            if recorridos is not None
            else {
                "rec_0001": {"estado": "finalizado", "photos": [{}] * 23},
                "rec_0002": {"estado": "en_curso", "photos": [{}] * 5, "progress": {"lat": 6.2, "lng": -75.5}},
            }
        )
        self.gradle_llamadas: list[tuple[str, ...]] = []
        self.adb_llamadas: list[tuple[str, ...]] = []
        self.assets = tmp_path / "assets"
        self.assets.mkdir()
        for nombre in validate23.ARCHIVOS_C2:
            (self.assets / nombre).write_text(JS_BUENO, encoding="utf-8")

    def instalar_en(self, monkeypatch):
        monkeypatch.setattr(comun, "DIR_RESULTADOS_PRUEBAS", self.tmp)
        monkeypatch.setattr(validate23, "DIR_ASSETS", self.assets)
        monkeypatch.setattr(comun, "gradle", self.gradle)
        monkeypatch.setattr(comun, "adb", self.adb)
        monkeypatch.setattr(comun, "dispositivo_fisico", self.dispositivo_fisico)
        monkeypatch.setattr(comun, "commit_actual", lambda: "abc1234")

    def gradle(self, *args, timeout=0):
        self.gradle_llamadas.append(args)
        if "testDebugUnitTest" in args:
            for clase, n in self.casos.items():
                if clase in self.sin_xml:
                    continue
                (self.tmp / f"TEST-com.example.myapplication.x.{clase}.xml").write_text(
                    f'<testsuite tests="{n}" failures="{self.fallos.get(clase, 0)}" errors="0" '
                    f'skipped="{self.omitidas.get(clase, 0)}"/>',
                    encoding="utf-8",
                )
            return comun.Resultado(self.codigo_tests, "BUILD", "")
        if "installDebug" in args:
            return comun.Resultado(1 if self.instalar else 0, self.instalar or "Installed on 1 device.", "")
        return comun.Resultado(0, "Gradle 8.7\nJVM:          21.0.11 (JetBrains s.r.o. 21.0.11+1-b1163.116)\n", "")

    def dispositivo_fisico(self):
        if not self.dispositivo:
            raise comun.ErrorConfiguracion("adb devices no muestra ningún dispositivo")
        return "SERIAL1"

    def adb(self, *args, timeout=0):
        self.adb_llamadas.append(args)
        if args[:2] == ("shell", "getprop"):
            valor = {"ro.product.model": "23028RA60L", "ro.build.version.release": "14", "ro.build.version.sdk": "34"}
            return comun.Resultado(0, valor.get(args[2], "") + "\n", "")
        if args[:3] == ("exec-out", "run-as", comun.PAQUETE):
            orden, ruta = args[3], args[-1]
            if orden == "ls":
                if ruta == validate23.DIR_RECOLECCION and self.recorridos:
                    return comun.Resultado(0, "\n".join(self.recorridos) + "\n", "")
                return comun.Resultado(1, "", f"ls: {ruta}: No such file or directory")
            if orden == "cat" and ruta == validate23.PREFS_CALIBRACION:
                return comun.Resultado(0, self.prefs, "") if self.prefs else comun.Resultado(1, "", "No such file")
            if orden == "cat" and ruta.endswith("/manifest.json"):
                carpeta = ruta.split("/")[-2]
                return comun.Resultado(0, json.dumps(self.recorridos[carpeta]), "")
        return comun.Resultado(0, "", "")


def _correr(tmp_path, entorno, argv_extra=()):
    informe = tmp_path / "informe.json"
    codigo = validate23.main(["--entorno", entorno, "--informe", str(informe), *argv_extra])
    return codigo, json.loads(informe.read_text(encoding="utf-8"))


def _estados(datos):
    return {e["id"]: e["estado"] for e in datos["precondiciones"] + datos["comprobaciones"]}


# --- piezas puras --------------------------------------------------------------------------------------------------


def test_quitar_comentarios_respeta_cadenas():
    js = "a = 'x // no' + \"/* tampoco */\"; // fuera\nb = `y`; /* bloque\nde dos */ c = 1;"
    assert validate23.quitar_comentarios_js(js) == "a = 'x // no' + \"/* tampoco */\"; \nb = `y`; \n c = 1;"


def test_llamadas_crear_mapa_ignora_comentarios_y_mapabase():
    assert validate23.llamadas_crear_mapa(JS_BUENO) == (1, 0)
    assert validate23.llamadas_crear_mapa("const m = base.crearMapa({});") == (0, 1)
    assert validate23.llamadas_crear_mapa("const m = base . crearMapa ({}); x.base.crearMapa(1)") == (0, 1)


def test_leer_calibracion():
    c = validate23.leer_calibracion(PREFS)
    assert c is not None
    assert (c.longitud_m, c.pasos, c.distancia_m, c.fecha_ms) == (0.7098, 47, 33.36, 1761400000000)
    assert c.en_rango
    assert not c.posterior_al_cambio  # 2025-10-25 es anterior al 2026-10-12
    texto = validate23.describir_calibracion(c)
    assert "0.710 m" in texto and "47 pasos en 33.4 m" in texto and "no: recalibrar" in texto


def test_calibracion_posterior_al_cambio_y_fuera_de_rango():
    reciente = PREFS.replace("1761400000000", "1792900000000").replace("0.7098", "1.5")  # 2026-10-25
    c = validate23.leer_calibracion(reciente)
    assert c is not None and c.posterior_al_cambio and not c.en_rango
    assert "fuera de 0.40–1.20 m" in validate23.describir_calibracion(c)


def test_sin_calibracion():
    assert validate23.leer_calibracion(None) is None
    assert validate23.leer_calibracion("<map></map>") is None
    assert validate23.leer_calibracion("<map><string name=") is None
    assert "ninguna" in validate23.describir_calibracion(None)


def test_leer_manifest():
    assert validate23.leer_manifest('{"estado": "en_curso", "photos": [{}, {}], "progress": {}}') == (
        "en_curso",
        2,
        True,
    )
    assert validate23.leer_manifest('{"photos": 3}') == ("?", 0, False)
    assert validate23.leer_manifest("no es json") is None
    assert validate23.leer_manifest(None) is None


def test_listar_archivos_app(monkeypatch):
    llamadas = []

    def adb(*args, timeout=0):
        llamadas.append(args)
        return comun.Resultado(0, "rec_0002\nrec_0001\n\n", "")

    monkeypatch.setattr(comun, "adb", adb)
    assert comun.listar_archivos_app("files/recoleccion") == ["rec_0001", "rec_0002"]
    assert llamadas == [("exec-out", "run-as", comun.PAQUETE, "ls", "-1", "files/recoleccion")]
    monkeypatch.setattr(comun, "adb", lambda *a, timeout=0: comun.Resultado(1, "", "No such file"))
    assert comun.listar_archivos_app("files/recoleccion") is None


# --- main() entero ---------------------------------------------------------------------------------------------


def test_local_pasa_sin_telefono(tmp_path, monkeypatch, capsys):
    sim = _Simulado(tmp_path)
    sim.instalar_en(monkeypatch)
    codigo, datos = _correr(tmp_path, "local")
    assert codigo == 0
    assert _estados(datos) == {"P1": "pasa", "C1": "pasa", "C2": "pasa"}
    assert sim.adb_llamadas == []
    assert [m["id"] for m in datos["manuales"]] == ["C3", "C4", "C5"]
    assert "entorno local" in datos["manuales"][0]["instruccion"]
    detalle_c1 = datos["comprobaciones"][0]["detalle"]
    assert "CalibracionPasoTest 13/13" in detalle_c1 and "DerivaTest 6/6" in detalle_c1
    pruebas = next(a for a in sim.gradle_llamadas if "testDebugUnitTest" in a)
    assert pruebas.count("--tests") == 4
    assert "[PASA] C2 recoleccion_mapa.js 1× MapaBase.crearMapa" in capsys.readouterr().out


def test_dev_instala_sin_borrar_datos_e_imprime_el_contexto(tmp_path, monkeypatch):
    sim = _Simulado(tmp_path)
    sim.instalar_en(monkeypatch)
    codigo, datos = _correr(tmp_path, "dev")
    assert codigo == 0
    assert _estados(datos) == {"P1": "pasa", "P2": "pasa", "C1": "pasa", "C2": "pasa"}
    assert ("installDebug",) in sim.gradle_llamadas
    assert not any("clear" in " ".join(a) for a in sim.adb_llamadas)  # nunca pm clear
    texto = datos["manuales"][0]["instruccion"]
    assert "23028RA60L, Android 14 (SDK 34)" in texto
    assert "longitud_paso_m 0.710 m" in texto
    assert "rec_0002 (en_curso, 5 fotos, con progress)" in texto
    assert "--es ruta mapa" in texto
    assert "am kill" in datos["manuales"][1]["instruccion"]
    assert "dumpsys sensorservice" in datos["manuales"][2]["instruccion"]


def test_dev_sin_calibracion_ni_recorridos(tmp_path, monkeypatch):
    sim = _Simulado(tmp_path, prefs="", recorridos={})
    sim.instalar_en(monkeypatch)
    codigo, datos = _correr(tmp_path, "dev")
    assert codigo == 0
    texto = datos["manuales"][0]["instruccion"]
    assert "calibración guardada: ninguna" in texto and "recorridos locales (files/recoleccion): ninguno" in texto


def test_dev_sin_dispositivo_es_codigo_3(tmp_path, monkeypatch):
    sim = _Simulado(tmp_path, dispositivo=False)
    sim.instalar_en(monkeypatch)
    codigo, datos = _correr(tmp_path, "dev")
    assert codigo == 3
    assert _estados(datos) == {"P1": "pasa", "P2": "falla"}
    assert not any("testDebugUnitTest" in a for a in sim.gradle_llamadas)


def test_install_restringido_en_miui_es_codigo_3(tmp_path, monkeypatch):
    sim = _Simulado(tmp_path, instalar="Failure [INSTALL_FAILED_USER_RESTRICTED: Install canceled by user]")
    sim.instalar_en(monkeypatch)
    codigo, datos = _correr(tmp_path, "dev")
    assert codigo == 3
    assert datos["resultado"] == "error"


@pytest.mark.parametrize(
    ("opciones", "esperado"),
    [
        ({"fallos": {"DerivaTest": 1}}, "DerivaTest: 6 casos (mínimo 4), 1 fallos"),
        ({"omitidas": {"StepDetectorTest": 2}}, "2 omitidos"),
        ({"sin_xml": ["DisparadorCapturaTest"], "codigo_tests": 1}, "DisparadorCapturaTest: sin resultados"),
        (
            {"casos": {"CalibracionPasoTest": 3, "StepDetectorTest": 11, "DisparadorCapturaTest": 10, "DerivaTest": 6}},
            "CalibracionPasoTest: 3 casos (mínimo 8)",
        ),
        ({"codigo_tests": 1}, "Gradle salió con 1"),
    ],
)
def test_c1_falla(tmp_path, monkeypatch, opciones, esperado):
    sim = _Simulado(tmp_path, **opciones)
    sim.instalar_en(monkeypatch)
    codigo, datos = _correr(tmp_path, "dev")
    assert codigo == 1
    c1 = datos["comprobaciones"][0]
    assert c1["estado"] == "falla" and esperado in c1["detalle"]
    assert ("installDebug",) not in sim.gradle_llamadas  # no instala si una automática falla
    assert "APK sin instalar: C1 no pasan" in datos["manuales"][0]["instruccion"]


def test_c2_falla_con_base_crear_mapa(tmp_path, monkeypatch):
    sim = _Simulado(tmp_path)
    sim.instalar_en(monkeypatch)
    (sim.assets / "calibracion_mapa.js").write_text("const map = base.crearMapa({ zoom: 18 });\n", encoding="utf-8")
    codigo, datos = _correr(tmp_path, "local")
    assert codigo == 1
    c2 = datos["comprobaciones"][1]
    assert c2["estado"] == "falla" and "calibracion_mapa.js: 1 llamada(s) a base.crearMapa(" in c2["detalle"]


def test_c2_falla_si_falta_el_archivo(tmp_path, monkeypatch):
    sim = _Simulado(tmp_path)
    sim.instalar_en(monkeypatch)
    (sim.assets / "recoleccion_mapa.js").unlink()
    codigo, datos = _correr(tmp_path, "local")
    assert codigo == 1
    assert "no existe app/src/main/assets/recoleccion_mapa.js" in datos["comprobaciones"][1]["detalle"]


def test_solo_c2_no_ejecuta_gradle_de_pruebas(tmp_path, monkeypatch):
    sim = _Simulado(tmp_path)
    sim.instalar_en(monkeypatch)
    codigo, datos = _correr(tmp_path, "dev", ["--solo", "C2"])
    assert codigo == 0
    assert _estados(datos)["C1"] == "omitida"
    assert not any("testDebugUnitTest" in a for a in sim.gradle_llamadas)
    assert ("installDebug",) in sim.gradle_llamadas
