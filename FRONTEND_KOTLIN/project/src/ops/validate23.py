"""Validador de FE-2.3 — Pruebas en dispositivo y robustez de la recolección.

Documento: FRONTEND_KOTLIN/docs/validation/validation-2-3.md. Entornos: local (C1 y C2, sin teléfono) y dev (además
instala el APK de depuración con installDebug, conservando los datos, e imprime modelo, Android, la calibración
guardada y los recorridos locales para las comprobaciones manuales C3–C5). No llama a la API ni a AWS y nunca usa
`pm clear` (borraría la calibración `campus_calibracion`).
"""

from __future__ import annotations

import json
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

import comun

CLASES_C1 = ["CalibracionPasoTest", "StepDetectorTest", "DisparadorCapturaTest", "DerivaTest"]
MINIMO_CASOS = {"CalibracionPasoTest": 8, "StepDetectorTest": 6, "DisparadorCapturaTest": 6, "DerivaTest": 4}
DIR_ASSETS = comun.PROYECTO / "app" / "src" / "main" / "assets"
ARCHIVOS_C2 = ["recoleccion_mapa.js", "calibracion_mapa.js"]
PREFS_CALIBRACION = "shared_prefs/campus_calibracion.xml"  # CalibracionPasoRepository (ARCHITECTURE §5.6)
DIR_RECOLECCION = "files/recoleccion"  # RecoleccionRepositoryLocal (ARCHITECTURE §5.6)
CAMBIO_DETECTOR = date(2026, 10, 12)  # ADR-FE-04: calibraciones de ese día o antes hay que rehacerlas
ZONA_BOGOTA = timezone(timedelta(hours=-5))  # sin horario de verano
LONGITUD_MIN_M, LONGITUD_MAX_M, LONGITUD_GENERICA_M = 0.40, 1.20, 0.72  # CalibracionPaso y PdrEngine (§5.7, §5.2)

_PATRON_MAPABASE = re.compile(r"\bMapaBase\s*\.\s*crearMapa\s*\(")
_PATRON_BASE = re.compile(r"(?<![\w$.])base\s*\.\s*crearMapa\s*\(")


# --- C2: llamadas a crearMapa en el JS ----------------------------------------------------------------------------


def quitar_comentarios_js(texto: str) -> str:
    """Quita los comentarios `//` y `/* */` de un JS respetando las cadenas ('…', "…", `…`). Los saltos de línea de
    los comentarios de bloque se conservan. No entiende expresiones regulares literales (no las hay en esas páginas)."""
    salida: list[str] = []
    i, n = 0, len(texto)
    while i < n:
        c = texto[i]
        if c in "'\"`":
            fin = i + 1
            while fin < n and texto[fin] != c:
                fin += 2 if texto[fin] == "\\" else 1
            salida.append(texto[i : fin + 1])
            i = fin + 1
        elif texto.startswith("//", i):
            fin = texto.find("\n", i)
            i = n if fin < 0 else fin
        elif texto.startswith("/*", i):
            fin = texto.find("*/", i + 2)
            fin = n if fin < 0 else fin + 2
            salida.append("\n" * texto.count("\n", i, fin))
            i = fin
        else:
            salida.append(c)
            i += 1
    return "".join(salida)


def llamadas_crear_mapa(texto_js: str) -> tuple[int, int]:
    """`(MapaBase.crearMapa(…), base.crearMapa(…))` en el código, sin contar comentarios (ARCHITECTURE §5.9)."""
    codigo = quitar_comentarios_js(texto_js)
    return len(_PATRON_MAPABASE.findall(codigo)), len(_PATRON_BASE.findall(codigo))


# --- Datos del teléfono para las manuales ------------------------------------------------------------------------


@dataclass
class Calibracion:
    longitud_m: float
    pasos: int | None
    distancia_m: float | None
    fecha_ms: int | None

    @property
    def fecha(self) -> datetime | None:
        return datetime.fromtimestamp(self.fecha_ms / 1000, ZONA_BOGOTA) if self.fecha_ms else None

    @property
    def posterior_al_cambio(self) -> bool:
        return self.fecha is not None and self.fecha.date() > CAMBIO_DETECTOR

    @property
    def en_rango(self) -> bool:
        return LONGITUD_MIN_M <= self.longitud_m <= LONGITUD_MAX_M


def leer_calibracion(xml: str | None) -> Calibracion | None:
    """SharedPreferences `campus_calibracion`: `longitud_paso_m` y `distancia_m` como `<string>`, `pasos` `<int>` y
    `fecha_ms` `<long>`. None sin archivo, sin `longitud_paso_m` o con XML ilegible."""
    if not xml or "<map" not in xml:
        return None
    try:
        raiz = ET.fromstring(xml[xml.index("<map") :].strip())
    except ET.ParseError:
        return None
    valores: dict[str, str] = {}
    for nodo in raiz:
        nombre = nodo.get("name")
        if nombre:
            valor = nodo.get("value")
            valores[nombre] = valor if valor is not None else (nodo.text or "")

    def decimal(clave: str) -> float | None:
        try:
            return float(valores[clave])
        except (KeyError, ValueError):
            return None

    def entero(clave: str) -> int | None:
        try:
            return int(valores[clave])
        except (KeyError, ValueError):
            return None

    longitud = decimal("longitud_paso_m")
    if longitud is None:
        return None
    return Calibracion(
        longitud_m=longitud, pasos=entero("pasos"), distancia_m=decimal("distancia_m"), fecha_ms=entero("fecha_ms")
    )


def describir_calibracion(c: Calibracion | None) -> str:
    if c is None:
        return f"calibración guardada: ninguna (la app usa el valor genérico de {LONGITUD_GENERICA_M:.2f} m)"
    partes = [f"calibración guardada: longitud_paso_m {c.longitud_m:.3f} m"]
    if c.pasos is not None and c.distancia_m is not None:
        partes.append(f"{c.pasos} pasos en {c.distancia_m:.1f} m")
    fecha = c.fecha
    if fecha is not None:
        cuando = "sí" if c.posterior_al_cambio else "no: recalibrar"
        partes.append(
            f"fecha_ms {c.fecha_ms} ({fecha:%Y-%m-%d %H:%M} Bogotá; posterior al {CAMBIO_DETECTOR}: {cuando})"
        )
    if not c.en_rango:
        partes.append(
            f"fuera de {LONGITUD_MIN_M:.2f}–{LONGITUD_MAX_M:.2f} m: la app la ignora y usa {LONGITUD_GENERICA_M}"
        )
    return ", ".join(partes)


@dataclass
class Recorrido:
    id: str
    estado: str
    fotos: int
    con_progreso: bool


def leer_manifest(texto: str | None) -> tuple[str, int, bool] | None:
    """`(estado, fotos, tiene progress)` de un `manifest.json` de `files/recoleccion/` (ARCHITECTURE §5.6)."""
    if not texto:
        return None
    try:
        datos = json.loads(texto)
    except json.JSONDecodeError:
        return None
    if not isinstance(datos, dict):
        return None
    fotos = datos.get("photos")
    return str(datos.get("estado") or "?"), len(fotos) if isinstance(fotos, list) else 0, "progress" in datos


def recorridos_locales() -> list[Recorrido]:
    """Los `rec_NNNN` del teléfono con su estado; manifests ilegibles salen como `estado = 'ilegible'`."""
    nombres = comun.listar_archivos_app(DIR_RECOLECCION) or []
    lista = []
    for nombre in nombres:
        if not nombre.startswith("rec_"):
            continue
        leido = leer_manifest(comun.leer_archivo_app(f"{DIR_RECOLECCION}/{nombre}/manifest.json"))
        estado, fotos, progreso = leido if leido else ("ilegible", 0, False)
        lista.append(Recorrido(nombre, estado, fotos, progreso))
    return lista


def describir_recorridos(lista: list[Recorrido]) -> str:
    if not lista:
        return f"recorridos locales ({DIR_RECOLECCION}): ninguno"
    partes = []
    for r in lista:
        extra = ", con progress" if r.con_progreso else ""
        partes.append(f"{r.id} ({r.estado}, {r.fotos} fotos{extra})")
    return f"recorridos locales ({DIR_RECOLECCION}): " + "; ".join(partes)


# --- Instrucciones de las manuales (validation-2-3 §3) ------------------------------------------------------------


def instrucciones(contexto: str) -> dict[str, str]:
    prefijo = f"[{contexto}] " if contexto else ""
    adb_paquete = f"adb shell run-as {comun.PAQUETE}"
    return {
        "C3": (
            f"{prefijo}Recalibra en 7.3b (Panel → Recolector → «Calibrar mi paso») con una pasada A→B de ≥ 30 m y "
            "guarda. En un recorrido conocido de ≥ 100 m con puntos marcados: (a) mapa público "
            f"(`adb shell am force-stop {comun.PAQUETE}` y `adb shell am start -n {comun.ACTIVIDAD} --es ruta mapa`; "
            "toca el inicio, ▶ y camina); (b) 7.3: punto, rumbo, coordenadas, dial y brújula; (c) 7.4 «Cada 5 m». "
            "Mide el error final. Evidencia: tabla «Registro de pruebas en dispositivo» en "
            "docs/validation/evidencia/fe-2-3/ (validation-2-3 §3)"
        ),
        "C4": (
            f"{prefijo}7.4 en «Cada 3 s», quieto: espera ≥ 5 fotos, pulsa Inicio del sistema y "
            f"`adb shell am kill {comun.PAQUETE}`. Abre la app: 7.4 vuelve en pausa con «Grabación retomada…» "
            "(si sale Inicio, entra como admin → Recolector → «Retomar …»); Reanudar, otras 5 fotos, Finalizar. "
            f"Evidencia: video, `{adb_paquete} ls {DIR_RECOLECCION}/` (una sola rec_NNNN nueva) y su manifest.json "
            "con fotos seguidas"
        ),
        "C5": (
            f"{prefijo}Con la calibración en CAMINANDO y, aparte, con el mapa público siguiendo pasos: Inicio del "
            "sistema, espera 10 s y `adb shell dumpsys sensorservice` (sin conexiones activas de "
            f"{comun.PAQUETE}); `adb exec-out run-as {comun.PAQUETE} tail -n 20 {comun.LOG_APP}` con «I/Pdr … sensores "
            "quitados»; vuelve a la app. Evidencia: ambas salidas en segundo plano y en primer plano"
        ),
    }


def main(argv: list[str] | None = None) -> int:
    v = comun.Validador(
        lote="FE-2.3",
        validacion="validation-2-3",
        descripcion=__doc__ or "",
        comprobaciones=["C1", "C2"],
    )
    datos: dict[str, str] = {}
    pasaron: set[str] = set()  # comprobaciones automáticas que pasaron (decide si se instala el APK)

    # --- precondiciones ----------------------------------------------------------------------------------------

    def p1_gradle() -> str:
        r = comun.gradle("--version", timeout=600)
        if r.codigo != 0:
            raise comun.ErrorConfiguracion(
                f"{' '.join(comun.comando_gradle())} --version falló: {comun.resumir(r.texto)}"
            )
        jvm = re.search(r"^JVM:\s+(.+)$", r.salida, re.MULTILINE)
        version = re.search(r"^Gradle (\S+)", r.salida, re.MULTILINE)
        return f"Gradle {version.group(1) if version else '?'}, JVM {jvm.group(1).strip() if jvm else '?'}"

    def p2_dispositivo() -> str:
        serial = comun.dispositivo_fisico()
        modelo = comun.adb("shell", "getprop", "ro.product.model", timeout=30).salida.strip() or "?"
        android = comun.adb("shell", "getprop", "ro.build.version.release", timeout=30).salida.strip() or "?"
        sdk = comun.adb("shell", "getprop", "ro.build.version.sdk", timeout=30).salida.strip() or "?"
        datos["telefono"] = f"{modelo}, Android {android} (SDK {sdk})"
        return f"{modelo} (Android {android}, SDK {sdk}, serial {serial})"

    # --- comprobaciones -----------------------------------------------------------------------------------------

    def c1_pruebas() -> str:
        comun.borrar_resultados(CLASES_C1)
        argumentos = ["testDebugUnitTest"]
        for clase in CLASES_C1:
            argumentos += ["--tests", f"*.{clase}"]
        r = comun.gradle(*argumentos, timeout=1800)
        partes = []
        for clase in CLASES_C1:
            res = comun.resultados_clase(clase)
            if res is None:
                raise comun.Falla(
                    f"{clase}: sin resultados; Gradle salió con {r.codigo}: {comun.resumir(r.texto[-600:], 300)}"
                )
            if not res.ok or res.omitidas or res.pruebas < MINIMO_CASOS[clase]:
                raise comun.Falla(
                    f"{clase}: {res.pruebas} casos (mínimo {MINIMO_CASOS[clase]}), {res.fallos} fallos, "
                    f"{res.errores} errores, {res.omitidas} omitidos"
                )
            partes.append(f"{clase} {res.pruebas}/{res.pruebas}")
        if r.codigo != 0:
            raise comun.Falla(f"Gradle salió con {r.codigo}: {comun.resumir(r.texto[-600:], 300)}")
        pasaron.add("C1")
        minimos = ", ".join(str(MINIMO_CASOS[c]) for c in CLASES_C1)
        return f"{', '.join(partes)} (mínimos {minimos})"

    def c2_mapa_base() -> str:
        partes = []
        for nombre in ARCHIVOS_C2:
            ruta = DIR_ASSETS / nombre
            if not ruta.is_file():
                raise comun.Falla(f"no existe app/src/main/assets/{nombre}")
            buenas, malas = llamadas_crear_mapa(ruta.read_text(encoding="utf-8"))
            if malas:
                raise comun.Falla(f"{nombre}: {malas} llamada(s) a base.crearMapa( (debe ser MapaBase.crearMapa, §5.9)")
            if not buenas:
                raise comun.Falla(f"{nombre}: ninguna llamada a MapaBase.crearMapa(")
            partes.append(f"{nombre} {buenas}× MapaBase.crearMapa")
        pasaron.add("C2")
        return f"{'; '.join(partes)}; ninguna base.crearMapa"

    # --- apoyo a las manuales (solo dev) -----------------------------------------------------------------------

    def preparar_telefono() -> str:
        """installDebug (conserva los datos; nunca `pm clear`) y lo que la persona anota en la evidencia."""
        comun.avisar("instalando el APK de depuración (installDebug, conserva los datos)")
        r = comun.gradle("installDebug", timeout=1800)
        if "INSTALL_FAILED_USER_RESTRICTED" in r.texto:
            raise comun.ErrorConfiguracion(
                "installDebug: INSTALL_FAILED_USER_RESTRICTED — en MIUI/HyperOS activa «Instalar vía USB» en Opciones "
                "de desarrollador y acepta el diálogo de instalación en el teléfono"
            )
        if r.codigo != 0:
            raise comun.ErrorConfiguracion(f"installDebug falló: {comun.resumir(r.texto[-600:], 300)}")
        calibracion = describir_calibracion(leer_calibracion(comun.leer_archivo_app(PREFS_CALIBRACION)))
        recorridos = describir_recorridos(recorridos_locales())
        for linea in (f"teléfono: {datos.get('telefono', '?')}", calibracion, recorridos):
            comun.avisar(linea)
        return f"{datos.get('telefono', '?')}; {calibracion}; {recorridos}"

    def cuerpo(v: comun.Validador) -> None:
        dev = v.entorno == "dev"
        if not v.precondicion("P1", p1_gradle):
            return
        if dev and not v.precondicion("P2", p2_dispositivo):
            return

        v.comprobacion("C1", c1_pruebas)
        v.comprobacion("C2", c2_mapa_base)

        if not dev:
            contexto = "entorno local: sin datos del teléfono"
        elif fallidas := [c for c in ("C1", "C2") if v.incluida(c) and c not in pasaron]:
            contexto = f"APK sin instalar: {' y '.join(fallidas)} no pasan"
        else:
            contexto = preparar_telefono()
        for id_, texto in instrucciones(contexto).items():
            v.manual(id_, texto)

    return v.correr(cuerpo, argv)


if __name__ == "__main__":
    sys.exit(main())
