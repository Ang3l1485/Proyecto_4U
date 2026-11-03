"""Validador de FE-2.1 — Subida de recorridos y Resumen de video (7.5).

Documento: FRONTEND_KOTLIN/docs/validation/validation-2-1.md. Entornos: local (C2a, C3a y C4: pruebas en la JVM y
comprobación estática; sin teléfono, API ni AWS) y dev (además C1, C2b y C3b sobre el recorrido real `--video`, que
la persona grabó y subió desde el teléfono). En dev: inicia sesión como admin con POST /v1/auth/login, lee el video
con GET /v1/admin/videos y /v1/admin/videos/{id}, enciende `embedding` si el video aún no está procesado (y lo apaga al
terminar si lo encendió él) y mide cada foto subida leyendo su objeto en S3 con la CLI `aws` (solo lectura). No crea
ni borra datos del backend y no necesita el teléfono. Nunca imprime contraseñas, tokens ni URLs prefirmadas.
"""

from __future__ import annotations

import re
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from urllib.parse import quote

import comun

CLASES_C2A = ["SubidaRecorridoTest", "ColaSubidaTest", "AlmacenRecorridosTest"]
CLASES_C3A = ["RecodificacionFotoTest"]
MINIMO_CASOS = {
    "SubidaRecorridoTest": 10,
    "ColaSubidaTest": 6,
    "AlmacenRecorridosTest": 10,
    "RecodificacionFotoTest": 8,
}
MAIN_ACTIVITY = (
    comun.PROYECTO / "app" / "src" / "main" / "java" / "com" / "example" / "myapplication" / "MainActivity.kt"
)
RUTA_RESUMEN = "admin/recoleccion/resumen"
MINIMO_FOTOS = 50  # C1 (PLAN §2.2)
BYTES_MAX = 4_194_304  # C3 y REC_MAX_BYTES_FOTO del backend (§5.10)
LADO_MAX_PX = 1600  # C3
LIMITE_PROCESADO_S = 15 * 60  # C1: espera de la ingesta
PAUSA_PROCESADO_S = 30
HORA_LIMITE = (21, 30)  # Bogotá: después no se enciende embedding (se apaga solo a las 22:00)
PATRON_REF_CLIENTE = re.compile(r"^rec_\d{4}$")
HILOS_S3 = 4


@dataclass
class Contexto:
    url: str = ""
    token: str = ""
    bucket: str = ""
    cluster: str = ""
    servicios: dict = field(default_factory=dict)
    video_id: str = ""
    nombre: str = ""
    detalle: dict | None = None
    gradle: comun.Resultado | None = None
    embedding_encendido_por_mi: bool = False


# --- piezas puras ----------------------------------------------------------------------------------------------


def conteo_de(detalle: dict) -> dict[str, int]:
    """Las cuatro claves de `conteo` (backend §5.5) como enteros (0 si faltan)."""
    c = detalle.get("conteo") if isinstance(detalle.get("conteo"), dict) else {}
    return {k: int(c.get(k) or 0) for k in ("pendiente_subida", "subida", "procesada", "error")}


def describir_conteo(c: dict[str, int]) -> str:
    return ", ".join(f"{k} {c[k]}" for k in ("pendiente_subida", "subida", "procesada", "error"))


def bloque_ruta(texto: str, ruta: str, *, exacta: bool = False) -> str | None:
    """El texto de `composable("<ruta>…")` (con `exacta`, `composable("<ruta>")`) hasta el siguiente `composable(` (o
    el final), o None si no está."""
    resto = r'"' if exacta else r'[^"]*"'
    m = re.search(r'composable\(\s*"' + re.escape(ruta) + resto, texto)
    if not m:
        return None
    siguiente = texto.find("composable(", m.end())
    return texto[m.start() : siguiente if siguiente >= 0 else len(texto)]


def comprobar_ruta_resumen(texto: str) -> str:
    """C4: la ruta de 7.5 compone `ResumenVideoScreen`, no queda el placeholder vacío y «Finalizar» (onFinalizado de
    7.4) navega a ella (ARCHITECTURE §5.8). Si no → Falla."""
    if re.search(r'composable\(\s*"' + re.escape(RUTA_RESUMEN) + r'"\s*\)\s*\{\s*(/\*.*?\*/)?\s*\}', texto, re.DOTALL):
        raise comun.Falla(f"queda el placeholder vacío de {RUTA_RESUMEN} en AppNav")
    bloque = bloque_ruta(texto, RUTA_RESUMEN)
    if bloque is None:
        raise comun.Falla(f"AppNav no registra la ruta {RUTA_RESUMEN}")
    if "ResumenVideoScreen(" not in bloque:
        raise comun.Falla(f"la ruta {RUTA_RESUMEN} no compone ResumenVideoScreen")
    recoleccion = bloque_ruta(texto, "admin/recoleccion", exacta=True)
    m = re.search(r"onFinalizado\s*=\s*\{(.*?)\n\s*\},", recoleccion or "", re.DOTALL)
    if not m or f'navigate("{RUTA_RESUMEN}' not in m.group(1):
        raise comun.Falla(f"onFinalizado de RecoleccionScreen (7.4) no navega a {RUTA_RESUMEN}")
    ruta = re.search(r'composable\(\s*"(' + re.escape(RUTA_RESUMEN) + r'[^"]*)"', bloque)
    return f"ruta {ruta.group(1) if ruta else RUTA_RESUMEN} → ResumenVideoScreen; onFinalizado de 7.4 navega a ella"


def video_exacto(items: list, nombre: str) -> list[dict]:
    """Los videos de una página de `GET /v1/admin/videos?q=` cuyo `nombre` es exactamente [nombre] (sin espacios
    alrededor; el `q` del backend busca «contiene» sin distinguir mayúsculas)."""
    buscado = nombre.strip()
    return [v for v in items if isinstance(v, dict) and str(v.get("nombre") or "").strip() == buscado]


def instruccion_c2(contexto: str) -> str:
    prefijo = f"[{contexto}] " if contexto else ""
    return (
        f"{prefijo}Durante la subida de la preparación (validation-2-1 §5, paso 9), con el progreso de 7.5 entre "
        "20 % y 60 %: modo avión, cerrar la app desde Recientes, esperar 10 s, quitar el modo avión, abrir la app, "
        "entrar como admin; el Panel muestra «Subida pendiente…» o «Subiendo…»: tocarla y esperar en 7.5 a «Subido». "
        "Evidencia en "
        "docs/validation/evidencia/fe-2-1/: video de 7.5 antes del corte y tras reabrir, `c2-manifest.json` del "
        "recorrido (subida_estado completada, todas sync subida) y captura de 7.13 con el mismo número de fotos que 7.5"
    )


# --- validador ---------------------------------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    def argumentos(p) -> None:
        p.add_argument("--video", default=None, help="nombre exacto del recorrido real subido (obligatorio en dev)")
        p.add_argument(
            "--minimo-fotos",
            type=int,
            default=MINIMO_FOTOS,
            help=f"fotos registradas mínimas para C1 (por defecto {MINIMO_FOTOS}, PLAN §2.2)",
        )

    v = comun.Validador(
        lote="FE-2.1",
        validacion="validation-2-1",
        descripcion=__doc__ or "",
        comprobaciones=["C1", "C2a", "C2b", "C3a", "C3b", "C4"],
        grupos={"C2": ["C2a", "C2b"], "C3": ["C3a", "C3b"]},
        argumentos=argumentos,
    )
    ctx = Contexto()

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

    def p2_video_y_aws() -> str:
        nombre = (v.args.video if v.args else None) or ""
        if not nombre.strip():
            raise comun.ErrorConfiguracion("en dev hace falta --video <nombre del recorrido subido>")
        ctx.nombre = nombre.strip()
        if not v.alguna_incluida("C1", "C3b"):
            return f"--video «{ctx.nombre}»; AWS no hace falta (C1 y C3b excluidas)"
        arn = comun.cuenta_aws()
        outputs = comun.terraform_outputs()
        faltan = [k for k in ("bucket_dataset", "ecs_cluster", "ecs_servicios") if not outputs.get(k)]
        if faltan:
            raise comun.Bloqueo(f"INF-1.2/INF-1.3: faltan los outputs {', '.join(faltan)}")
        ctx.bucket = str(outputs["bucket_dataset"])
        ctx.cluster = str(outputs["ecs_cluster"])
        servicios = outputs["ecs_servicios"]
        ctx.servicios = servicios if isinstance(servicios, dict) else {}
        return f"--video «{ctx.nombre}»; cuenta {comun.CUENTA} ({arn.rsplit(':', 1)[-1]}); bucket y servicios de ECS"

    def p3_login() -> str:
        if not comun.lote_hecho(comun.PLAN_APP.read_text(encoding="utf-8"), "FE-1.2"):
            raise comun.Bloqueo("FE-1.2 no está «Hecho» en PLAN.md §3")
        url, origen = comun.url_api_vigente()
        ctx.url = url
        try:
            r = comun.http_get(f"{url}/health")
        except comun.ErrorRed as e:
            raise comun.Bloqueo(f"INF-1.4: GET /v1/health sin respuesta ({e})") from e
        cuerpo = r.json()
        if r.estado != 200 or not isinstance(cuerpo, dict) or cuerpo.get("estado") != "ok":
            raise comun.Bloqueo(f"BE-1.1: GET /v1/health respondió {r.estado}")
        correo, password = comun.credenciales_admin(v.entorno)
        try:
            r = comun.http_post_json(f"{url}/auth/login", {"identificador": correo, "password": password})
        except comun.ErrorRed as e:
            raise comun.Bloqueo(f"INF-1.4: POST /v1/auth/login sin respuesta ({e})") from e
        if r.estado == 401:
            raise comun.ErrorConfiguracion(
                f"las credenciales del admin no sirven (401 {comun.codigo_error(r)}): revisa VALIDACION_ADMIN_* o "
                f"{comun.SECRETO_ADMIN}"
            )
        cuerpo = r.json()
        if r.estado != 200 or not isinstance(cuerpo, dict) or not cuerpo.get("token"):
            raise comun.Bloqueo(
                f"BE-1.3: POST /v1/auth/login respondió {r.estado} {comun.codigo_error(r) or ''}".rstrip()
            )
        usuario = cuerpo.get("usuario") if isinstance(cuerpo.get("usuario"), dict) else {}
        if usuario.get("rol") != "admin":
            raise comun.ErrorConfiguracion(f"la cuenta {correo} no tiene rol admin")
        ctx.token = str(cuerpo["token"])
        return f"FE-1.2 Hecho; {origen}; GET /v1/health -> 200; login admin 200 ({correo})"

    def p4_fe23() -> str:
        texto = comun.PLAN_APP.read_text(encoding="utf-8")
        # La fila de estado (§3) es `| FE-2.3 | <fase> | <estado> | …`; la de §2.1 tiene el nombre en la 2.ª celda.
        filas = (
            [c.strip() for c in linea.strip().strip("|").split("|")]
            for linea in texto.splitlines()
            if linea.strip().startswith("| FE-2.3 |")
        )
        celdas = next((c for c in filas if len(c) >= 5 and c[1].isdigit()), [])
        if len(celdas) < 5 or celdas[2] != "Hecho" or celdas[4] in ("", "—"):
            raise comun.Bloqueo("FE-2.3 no está «Hecho» con «Última validación» en PLAN.md §3 (el PDR sin probar)")
        return f"FE-2.3 Hecho ({celdas[4]})"

    def p5_be21() -> str:
        if not comun.lote_hecho(comun.PLAN_BACKEND.read_text(encoding="utf-8"), "BE-2.1"):
            raise comun.Bloqueo("BE-2.1 no está «Hecho» en BACKEND_FASTAPI/docs/PLAN.md §3")
        try:
            r = comun.http_post_json(f"{ctx.url}/collect/videos", {}, token=ctx.token)
        except comun.ErrorRed as e:
            raise comun.Bloqueo(f"BE-2.1: POST /v1/collect/videos sin respuesta ({e})") from e
        if r.estado != 422 or comun.codigo_error(r) != "VALIDACION":
            raise comun.Bloqueo(f"BE-2.1: POST /v1/collect/videos {{}} respondió {r.estado} {comun.codigo_error(r)}")
        return "BE-2.1 Hecho; POST /v1/collect/videos {} -> 422 VALIDACION (no crea nada)"

    def salud_lista() -> dict:
        try:
            r = comun.http_get(f"{ctx.url}/health/ready")
        except comun.ErrorRed as e:
            raise comun.Bloqueo(f"BE-1.1: GET /v1/health/ready sin respuesta ({e})") from e
        cuerpo = r.json()
        if r.estado != 200 or not isinstance(cuerpo, dict):
            raise comun.Bloqueo(f"BE-1.2: GET /v1/health/ready respondió {r.estado} {comun.codigo_error(r) or ''}")
        return cuerpo

    def p6_be22() -> str:
        if not comun.lote_hecho(comun.PLAN_BACKEND.read_text(encoding="utf-8"), "BE-2.2"):
            raise comun.Bloqueo("BE-2.2 no está «Hecho» en BACKEND_FASTAPI/docs/PLAN.md §3")
        cuerpo = salud_lista()
        if cuerpo.get("db") != "ok":
            raise comun.Bloqueo(f"BE-1.2: /v1/health/ready dice db {cuerpo.get('db')!r}")
        return f"BE-2.2 Hecho; /v1/health/ready db ok, embedding {cuerpo.get('embedding')}"

    def p7_video() -> str:
        q = quote(ctx.nombre)
        r = comun.http_get(f"{ctx.url}/admin/videos?q={q}&por_pagina=100", token=ctx.token)
        cuerpo = r.json()
        if r.estado != 200 or not isinstance(cuerpo, dict):
            raise comun.Bloqueo(f"BE-2.1: GET /v1/admin/videos respondió {r.estado} {comun.codigo_error(r) or ''}")
        exactos = video_exacto(cuerpo.get("items") or [], ctx.nombre)
        if not exactos:
            raise comun.ErrorConfiguracion(
                f"no hay ningún video llamado «{ctx.nombre}» en el backend: ¿terminó la subida desde 7.5 "
                "(validation-2-1 §5, paso 9)? ¿el nombre es exacto?"
            )
        if len(exactos) > 1:
            lista = ", ".join(f"n.º {e.get('numero')} ({e.get('ref_cliente')})" for e in exactos)
            raise comun.ErrorConfiguracion(f"hay {len(exactos)} videos llamados «{ctx.nombre}» ({lista}): renombra uno")
        ctx.video_id = str(exactos[0].get("id"))
        detalle = leer_detalle()
        return (
            f"«{ctx.nombre}»: n.º {detalle.get('numero')}, ref_cliente {detalle.get('ref_cliente')}, estado "
            f"{detalle.get('estado')}, {len(detalle.get('fotos') or [])} fotos"
        )

    def leer_detalle() -> dict:
        r = comun.http_get(f"{ctx.url}/admin/videos/{ctx.video_id}", token=ctx.token)
        cuerpo = r.json()
        if r.estado != 200 or not isinstance(cuerpo, dict):
            raise comun.Falla(f"GET /v1/admin/videos/{{id}} respondió {r.estado} {comun.codigo_error(r) or ''}")
        ctx.detalle = cuerpo
        return cuerpo

    def p8_embedding() -> str:
        if not v.incluida("C1"):
            return "no hace falta (C1 excluida)"
        if (ctx.detalle or {}).get("estado") == "procesado":
            return "no hace falta: el video ya está procesado"
        if salud_lista().get("embedding") == "ok":
            comun.EmbeddingDev(ctx.cluster, *servicios()).latido()
            return "ya estaba encendido (latido publicado)"
        ahora = comun.hora_bogota()
        if (ahora.hour, ahora.minute) >= HORA_LIMITE:
            raise comun.ErrorConfiguracion(
                f"son las {ahora:%H:%M} en Bogotá: después de las {HORA_LIMITE[0]}:{HORA_LIMITE[1]:02d} no se enciende "
                "embedding (se apaga solo a las 22:00). Repite mañana"
            )
        emb = comun.EmbeddingDev(ctx.cluster, *servicios())
        emb.comprobar_inf21()
        # Antes de encender: la limpieza lo apaga aunque el encendido falle a medias (infra §5.11).
        ctx.embedding_encendido_por_mi = True
        v.al_limpiar("apagar embedding (lo encendió el validador)", emb.apagar)
        comun.avisar("encendiendo embedding (3–6 min; infra §5.10)")
        segundos = emb.encender(lambda: salud_lista().get("embedding") == "ok")
        return f"encendido por el validador en {segundos:.0f} s (se apaga al terminar)"

    def servicios() -> tuple[str, str]:
        return str(ctx.servicios.get("embedding") or "embedding"), str(ctx.servicios.get("worker") or "worker")

    # --- comprobaciones ----------------------------------------------------------------------------------------

    def pruebas() -> comun.Resultado:
        if ctx.gradle is None:
            clases = [c for c in CLASES_C2A if v.incluida("C2a")] + [c for c in CLASES_C3A if v.incluida("C3a")]
            comun.borrar_resultados(clases)
            argumentos_gradle = ["testDebugUnitTest"]
            for clase in clases:
                argumentos_gradle += ["--tests", f"*.{clase}"]
            ctx.gradle = comun.gradle(*argumentos_gradle, timeout=1800)
        return ctx.gradle

    def pruebas_clases(clases: list[str]) -> str:
        r = pruebas()
        partes = []
        for clase in clases:
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
        minimos = ", ".join(str(MINIMO_CASOS[c]) for c in clases)
        return f"{', '.join(partes)} (mínimos {minimos})"

    def c1_procesado() -> str:
        inicio = comun.reloj()
        while True:
            detalle = leer_detalle()
            estado = detalle.get("estado")
            c = conteo_de(detalle)
            registradas = sum(c.values())
            if estado == "con_errores":
                errores = [f.get("error") for f in detalle.get("fotos") or [] if f.get("estado") == "error"]
                ejemplo = f" (p. ej. «{errores[0]}»)" if errores and errores[0] else ""
                raise comun.Falla(f"estado con_errores: {c['error']} foto(s) en error{ejemplo}; {describir_conteo(c)}")
            if estado == "procesado":
                break
            if comun.reloj() - inicio >= LIMITE_PROCESADO_S:
                pista = " (¿terminó la subida en el teléfono?)" if estado == "pendiente" else ""
                raise comun.Falla(
                    f"en {LIMITE_PROCESADO_S // 60} min el video no llegó a procesado: estado {estado}{pista}; "
                    f"{describir_conteo(c)}"
                )
            comun.avisar(f"C1: estado {estado}; {describir_conteo(c)}; nueva consulta en {PAUSA_PROCESADO_S} s")
            comun.dormir(PAUSA_PROCESADO_S)
        minimo = getattr(v.args, "minimo_fotos", None) or MINIMO_FOTOS
        if registradas < minimo:
            raise comun.Falla(f"procesado, pero con {registradas} fotos (mínimo {minimo})")
        if c["procesada"] != registradas:
            raise comun.Falla(f"procesado, pero procesada {c['procesada']} de {registradas}")
        segundos = comun.reloj() - inicio
        return f"estado procesado; {registradas} fotos, procesada {c['procesada']} (esperó {segundos:.0f} s)"

    def c2b_sin_duplicados() -> str:
        detalle = ctx.detalle or leer_detalle()
        ref = str(detalle.get("ref_cliente") or "")
        if not PATRON_REF_CLIENTE.match(ref):
            raise comun.Falla(f"ref_cliente {ref!r} no es el id local rec_NNNN de la app")
        fotos = detalle.get("fotos") or []
        ordenes = [f.get("orden") for f in fotos]
        repetidos = sorted({o for o in ordenes if ordenes.count(o) > 1})
        if repetidos:
            raise comun.Falla(f"órdenes repetidos: {repetidos}")
        registradas = sum(conteo_de(detalle).values())
        total = detalle.get("total_fotos")
        if not (len(fotos) == registradas == total):
            raise comun.Falla(f"{len(fotos)} fotos en el detalle, {registradas} en el conteo y total_fotos {total}")
        return f"ref_cliente {ref}; {registradas} fotos = total_fotos, órdenes sin repetir"

    def c3b_limites() -> str:
        detalle = ctx.detalle or leer_detalle()
        fotos = detalle.get("fotos") or []
        if not fotos:
            raise comun.Falla("el video no tiene fotos")
        claves = [f"dataset/{ctx.video_id}/{f.get('id')}.jpg" for f in fotos]
        with ThreadPoolExecutor(max_workers=HILOS_S3) as hilos:
            objetos = list(hilos.map(lambda clave: comun.leer_objeto_s3(ctx.bucket, clave), claves))
        malos = []
        for o in objetos:
            if o.dimensiones is None:
                malos.append(f"{o.clave.rsplit('/', 1)[-1]}: no es un JPEG legible")
            elif o.bytes > BYTES_MAX or max(o.dimensiones) > LADO_MAX_PX:
                malos.append(f"{o.clave.rsplit('/', 1)[-1]}: {o.bytes} B, {o.dimensiones[0]}×{o.dimensiones[1]} px")
        if malos:
            raise comun.Falla(f"{len(malos)} foto(s) fuera de límites: {'; '.join(malos[:5])}")
        max_bytes = max(o.bytes for o in objetos)
        max_lado = max(max(o.dimensiones) for o in objetos if o.dimensiones)
        return (
            f"{len(objetos)} fotos en S3: máx. {max_bytes} B (límite {BYTES_MAX}) y máx. {max_lado} px de lado mayor "
            f"(límite {LADO_MAX_PX})"
        )

    def c4_ruta() -> str:
        try:
            texto = MAIN_ACTIVITY.read_text(encoding="utf-8")
        except OSError as e:
            raise comun.Falla(f"no se pudo leer MainActivity.kt: {e}") from e
        return comprobar_ruta_resumen(texto)

    def cuerpo(v: comun.Validador) -> None:
        dev = v.entorno == "dev"
        if not v.precondicion("P1", p1_gradle):
            return
        if dev:
            pasos = [
                ("P2", p2_video_y_aws),
                ("P3", p3_login),
                ("P4", p4_fe23),
                ("P5", p5_be21),
                ("P6", p6_be22),
                ("P7", p7_video),
                ("P8", p8_embedding),
            ]
            for i, (id_, fn) in enumerate(pasos):
                if not v.precondicion(id_, fn):
                    for siguiente, _ in pasos[i + 1 :]:
                        v.precondicion_no_evaluada(siguiente, f"{id_} no se cumple")
                    return

        if dev:
            v.comprobacion("C1", c1_procesado)
        else:
            v.omitir("C1", "solo en dev (necesita el recorrido real en el backend)")
        v.comprobacion("C2a", lambda: pruebas_clases(CLASES_C2A))
        if dev:
            v.comprobacion("C2b", c2b_sin_duplicados)
        else:
            v.omitir("C2b", "solo en dev")
        v.comprobacion("C3a", lambda: pruebas_clases(CLASES_C3A))
        if dev:
            v.comprobacion("C3b", c3b_limites)
        else:
            v.omitir("C3b", "solo en dev (lee los objetos del video en S3)")
        v.comprobacion("C4", c4_ruta)

        contexto = (
            f"video «{ctx.nombre}» ({ctx.video_id}), estado {(ctx.detalle or {}).get('estado')}"
            if dev
            else "entorno local: sin backend"
        )
        v.manual("C2c", instruccion_c2(contexto))

    return v.correr(cuerpo, argv)


if __name__ == "__main__":
    sys.exit(main())
