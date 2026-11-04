"""Validador de INF-0.2: esqueleto de envs/dev y CI de Terraform.

Documento: INFRASTRUCTURA_TERRAFORM/docs/validation/validation-0-2.md (criterios en docs/PLAN.md §2.3).
Contrato común: docs/ARCHITECTURE.md §5.11.

    cd INFRASTRUCTURA_TERRAFORM/project
    uv run --group ops python src/ops/validate02.py --entorno dev
"""

from __future__ import annotations

import base64
import json
import os
import re
import signal
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from comun import (
    CUENTA,
    PROYECTO,
    REGION,
    Bloqueo,
    ErrorConfiguracion,
    ErrorGh,
    Falla,
    Validador,
    avisar,
    comprobar_cuenta,
    ejecutar,
    errores_aws,
    gh,
    gh_api,
    resumir,
    sesion_aws,
    terraform_outputs,
    terraform_state_pull,
)

LOTE = "INF-0.2"
VALIDACION = "validation-0-2"

WORKFLOW = "infra.yml"
RUTA_MAIN_TF = "INFRASTRUCTURA_TERRAFORM/project/envs/dev/main.tf"
RUTA_WORKFLOW = PROYECTO.parent.parent / ".github" / "workflows" / WORKFLOW
DIR_DEV = "envs/dev"
PREFIJO = "validacion-0-2-"
MARCADOR_COMENTARIO = "<!-- infra-plan envs/dev -->"
BOT = "github-actions[bot]"

BUCKET_ESTADO = f"campus-locator-tfstate-{CUENTA}"
CLAVE_ESTADO = "dev/terraform.tfstate"
CLAVE_BLOQUEO = "dev/terraform.tfstate.tflock"
ROLES_GHA = ("campus-locator-gha-terraform-plan", "campus-locator-gha-terraform")
OUTPUTS_BOOTSTRAP = ("bucket_estado", "rol_gha_terraform_plan_arn", "rol_gha_terraform_arn", "rol_gha_deploy_arn")
ETIQUETAS = {
    "Proyecto": "campus-locator",
    "Entorno": "dev",
    "GestionadoPor": "terraform",
    "Carpeta": "INFRASTRUCTURA_TERRAFORM",
}
TERRAFORM_MINIMA = (1, 10)
CUENTA_AJENA = "000000000000"

# Esperas (segundos).
INTERVALO = 10
ESPERA_ARRANQUE = 5 * 60  # a que GitHub cree la ejecución
ESPERA_CORRIDA = 20 * 60  # a que una ejecución termine
ESPERA_FUSION_MANUAL = 15 * 60  # a que la persona fusione si la protección de main lo exige
ESPERA_APROBACION = 10 * 60  # a que el job de apply quede esperando aprobación
RETENCION_BLOQUEO = 20  # tiempo que el validador retiene el bloqueo con el segundo plan esperando
LOCK_TIMEOUT_ESPERA = "120s"

PASOS_PLAN = ("terraform fmt -check", "tflint", "terraform validate", "terraform plan")
TEXTO_APPLY = "Apply complete! Resources: 0 added, 0 changed, 0 destroyed"
TEXTO_BLOQUEO = "Error acquiring the state lock"
PATRON_COMENTARIO = re.compile(r"^# validacion-0-2 \d{8}-\d{6}[ \t]*\r?\n?", re.MULTILINE)


@dataclass
class Pr:
    numero: int
    rama: str
    sha: str
    url: str
    base_sha: str  # main cuando se abrió el PR: lo único que puede aplicar el apply que aprueba el validador


@dataclass
class Contexto:
    v: Validador
    sesion: Any = None
    repo: str = ""
    usuario: str = ""
    version_tf: str = ""
    bootstrap: dict[str, Any] = field(default_factory=dict)
    pr: Pr | None = None
    pr_listo: str | None = None  # detalle de C1 si el PR pasó
    pr_error: Exception | None = None
    corrida_main: dict[str, Any] | None = None
    entorno_id: int | None = None
    puede_aprobar: bool = False
    bloqueo_id: str | None = None  # ID del .tflock que creó C3b
    bloqueo_etag: str | None = None
    procesos: list[subprocess.Popen] = field(default_factory=list)


# --------------------------------------------------------------------------------------------- utilidades


def dormir(segundos: float) -> None:
    time.sleep(segundos)


def version_tupla(texto: str) -> tuple[int, ...]:
    return tuple(int(p) for p in re.findall(r"\d+", texto)[:3])


def entorno_terraform() -> dict[str, str]:
    env = dict(os.environ)
    env["TF_IN_AUTOMATION"] = "1"
    env["TF_INPUT"] = "0"
    return env


def lanzar(ctx: Contexto, comando: list[str], *, con_entrada: bool = False) -> subprocess.Popen:
    """Arranca un proceso en segundo plano desde project/; su salida va a un archivo temporal (nunca se imprime)."""
    salida = tempfile.TemporaryFile(mode="w+", encoding="utf-8")
    try:
        proceso = subprocess.Popen(
            comando,
            cwd=PROYECTO,
            stdin=subprocess.PIPE if con_entrada else subprocess.DEVNULL,
            stdout=salida,
            stderr=subprocess.STDOUT,
            text=True,
            env=entorno_terraform(),
        )
    except FileNotFoundError as exc:
        salida.close()
        raise ErrorConfiguracion(f"no se encontró {comando[0]}") from exc
    proceso.salida_archivo = salida  # type: ignore[attr-defined]
    ctx.procesos.append(proceso)
    return proceso


def salida_de(proceso: subprocess.Popen) -> str:
    archivo = proceso.salida_archivo  # type: ignore[attr-defined]
    archivo.flush()
    archivo.seek(0)
    return archivo.read()


def interrumpir(proceso: subprocess.Popen) -> None:
    """Detiene un terraform como Ctrl+C (SIGINT), para que suelte el bloqueo; solo lo mata si no responde."""
    if proceso.poll() is not None:
        return
    for senal, espera in ((signal.SIGINT, 30), (signal.SIGTERM, 15), (signal.SIGKILL, 15)):
        proceso.send_signal(senal)
        try:
            proceso.wait(timeout=espera)
            return
        except subprocess.TimeoutExpired:
            continue


def esperar_proceso(proceso: subprocess.Popen, timeout: float, que: str) -> int:
    try:
        return proceso.wait(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        interrumpir(proceso)
        raise Falla(f"{que} no terminó en {int(timeout)} s") from exc


def terminar_procesos(ctx: Contexto) -> None:
    for proceso in ctx.procesos:
        try:
            if proceso.stdin and not proceso.stdin.closed:
                proceso.stdin.close()
        except OSError:
            pass
        interrumpir(proceso)
        archivo = getattr(proceso, "salida_archivo", None)
        if archivo is not None and not archivo.closed:
            archivo.close()


def ultima_linea_error(texto: str) -> str:
    for linea in texto.splitlines():
        if linea.strip().startswith("Error:"):
            return resumir(linea.strip(), 200)
    return resumir(texto.strip().splitlines()[-1] if texto.strip() else "(sin salida)", 200)


# --------------------------------------------------------------------------------------------- GitHub


def corridas(ctx: Contexto, *, rama: str, evento: str, sha: str | None = None) -> list[dict[str, Any]]:
    ruta = f"repos/{ctx.repo}/actions/workflows/{WORKFLOW}/runs?branch={rama}&event={evento}&per_page=50"
    if sha:
        ruta += f"&head_sha={sha}"
    return gh_api(ruta).get("workflow_runs", [])


def esperar_corrida(ctx: Contexto, *, rama: str, evento: str, sha: str) -> dict[str, Any]:
    limite = time.monotonic() + ESPERA_ARRANQUE
    while True:
        encontradas = [c for c in corridas(ctx, rama=rama, evento=evento, sha=sha) if c.get("head_sha") == sha]
        if encontradas:
            corrida = max(encontradas, key=lambda c: c["id"])
            ctx.v.al_limpiar(
                f"cancelar la ejecución {corrida['id']} de {WORKFLOW} si sigue activa",
                lambda id_=corrida["id"]: cancelar_si_activa(ctx, id_),
            )
            return corrida
        if time.monotonic() > limite:
            raise Falla(
                f"{WORKFLOW} no arrancó en {ESPERA_ARRANQUE // 60} min para {sha[:7]} ({evento} en {rama}): "
                f"¿está {WORKFLOW} en main?"
            )
        dormir(INTERVALO)


def esperar_fin(ctx: Contexto, corrida_id: int, que: str) -> dict[str, Any]:
    limite = time.monotonic() + ESPERA_CORRIDA
    while True:
        corrida = gh_api(f"repos/{ctx.repo}/actions/runs/{corrida_id}")
        if corrida.get("status") == "completed":
            return corrida
        if time.monotonic() > limite:
            raise Falla(
                f"{que}: la ejecución {corrida.get('html_url')} sigue «{corrida.get('status')}» tras "
                f"{ESPERA_CORRIDA // 60} min"
            )
        dormir(INTERVALO)


def trabajos(ctx: Contexto, corrida_id: int) -> list[dict[str, Any]]:
    return gh_api(f"repos/{ctx.repo}/actions/runs/{corrida_id}/jobs?per_page=50").get("jobs", [])


def trabajo(ctx: Contexto, corrida_id: int, prefijo: str) -> dict[str, Any]:
    for job in trabajos(ctx, corrida_id):
        if job.get("name", "").startswith(prefijo):
            return job
    raise Falla(f"la ejecución {corrida_id} no tiene un job «{prefijo} …»")


def cancelar_si_activa(ctx: Contexto, corrida_id: int) -> None:
    corrida = gh_api(f"repos/{ctx.repo}/actions/runs/{corrida_id}")
    if corrida.get("status") != "completed":
        gh_api(f"repos/{ctx.repo}/actions/runs/{corrida_id}/cancel", metodo="POST")


def borrar_rama(ctx: Contexto, rama: str) -> None:
    try:
        gh_api(f"repos/{ctx.repo}/git/refs/heads/{rama}", metodo="DELETE")
    except ErrorGh as exc:
        if exc.http not in (404, 422):  # ya no existe
            raise


def cerrar_pr_si_abierto(ctx: Contexto, numero: int) -> None:
    pr = gh_api(f"repos/{ctx.repo}/pulls/{numero}")
    if pr.get("state") == "open":
        gh_api(f"repos/{ctx.repo}/pulls/{numero}", metodo="PATCH", cuerpo={"state": "closed"})


def limpiar_restos(ctx: Contexto) -> None:
    """Cierra PR, borra ramas y cancela ejecuciones que dejaron ejecuciones anteriores de este validador."""
    try:
        abiertos = gh_api(f"repos/{ctx.repo}/pulls?state=open&per_page=100")
        for pr in abiertos:
            rama = pr.get("head", {}).get("ref", "")
            propio = (
                rama.startswith(PREFIJO)
                and ((pr.get("head") or {}).get("repo") or {}).get("full_name") == ctx.repo  # no un fork
                and (pr.get("title") or "").startswith("validacion-0-2 ")
                and (pr.get("user") or {}).get("login") == ctx.usuario
            )
            if propio:
                avisar(f"Restos: cierro el PR #{pr['number']} ({rama})")
                for corrida in corridas(ctx, rama=rama, evento="pull_request"):
                    del_repo = (corrida.get("head_repository") or {}).get("full_name") == ctx.repo
                    if del_repo and corrida.get("status") != "completed":
                        gh_api(f"repos/{ctx.repo}/actions/runs/{corrida['id']}/cancel", metodo="POST")
                gh_api(f"repos/{ctx.repo}/pulls/{pr['number']}", metodo="PATCH", cuerpo={"state": "closed"})
        for ref in gh_api(f"repos/{ctx.repo}/git/matching-refs/heads/{PREFIJO}") or []:
            rama = ref["ref"].removeprefix("refs/heads/")
            avisar(f"Restos: borro la rama {rama}")
            borrar_rama(ctx, rama)
        # Un apply de una ejecución anterior que quedó esperando aprobación retiene la fila de concurrencia de main.
        for corrida in corridas(ctx, rama="main", evento="push"):
            mensaje = (corrida.get("head_commit") or {}).get("message", "")
            if corrida.get("status") in ("waiting", "queued", "pending") and mensaje.startswith("validacion-0-2 "):
                avisar(f"Restos: cancelo la ejecución {corrida['id']} de main que esperaba aprobación")
                gh_api(f"repos/{ctx.repo}/actions/runs/{corrida['id']}/cancel", metodo="POST")
    except ErrorGh as exc:
        if exc.sin_permiso:
            raise
        avisar(f"Aviso: no se pudieron limpiar todos los restos anteriores: {resumir(str(exc), 200)}")


def con_comentario(contenido: str, sello: str) -> str:
    """main.tf con un único comentario de validación al final (sustituye el de una ejecución anterior)."""
    base = PATRON_COMENTARIO.sub("", contenido).rstrip("\r\n")
    return f"{base}\n\n# validacion-0-2 {sello}\n"


def crear_pr(ctx: Contexto) -> Pr:
    v = ctx.v
    rama = f"{PREFIJO}{v.sello}"
    base_sha = gh_api(f"repos/{ctx.repo}/git/ref/heads/main")["object"]["sha"]
    archivo = gh_api(f"repos/{ctx.repo}/contents/{RUTA_MAIN_TF}?ref={base_sha}")
    contenido = base64.b64decode(archivo["content"]).decode("utf-8")

    gh_api(f"repos/{ctx.repo}/git/refs", metodo="POST", cuerpo={"ref": f"refs/heads/{rama}", "sha": base_sha})
    v.al_limpiar(f"borrar la rama {rama} si sigue existiendo", lambda: borrar_rama(ctx, rama))

    commit = gh_api(
        f"repos/{ctx.repo}/contents/{RUTA_MAIN_TF}",
        metodo="PUT",
        cuerpo={
            "message": f"validacion-0-2 {v.sello}",
            "content": base64.b64encode(con_comentario(contenido, v.sello).encode("utf-8")).decode("ascii"),
            "sha": archivo["sha"],
            "branch": rama,
        },
    )
    sha = commit["commit"]["sha"]
    pr = gh_api(
        f"repos/{ctx.repo}/pulls",
        metodo="POST",
        cuerpo={
            "title": f"validacion-0-2 {v.sello}",
            "head": rama,
            "base": "main",
            "body": (
                "PR de prueba de `validate02.py` (INF-0.2, `INFRASTRUCTURA_TERRAFORM/docs/validation/"
                "validation-0-2.md`). El validador lo fusiona o lo cierra solo."
            ),
        },
    )
    v.al_limpiar(f"cerrar el PR #{pr['number']} si sigue abierto", lambda: cerrar_pr_si_abierto(ctx, pr["number"]))
    avisar(f"PR #{pr['number']} abierto: {pr['html_url']}")
    return Pr(numero=pr["number"], rama=rama, sha=sha, url=pr["html_url"], base_sha=base_sha)


def preparar_pr(ctx: Contexto) -> str:
    """Abre el PR de prueba y espera su plan. Lo usan C1 y, si C1 está excluida, C2."""
    if ctx.pr_listo is not None:
        return ctx.pr_listo
    if ctx.pr_error is not None:
        raise Falla("el PR de prueba no pasó (ver C1)")
    try:
        ctx.pr_listo = _preparar_pr(ctx)
        return ctx.pr_listo
    except Exception as exc:
        ctx.pr_error = exc
        raise


def _preparar_pr(ctx: Contexto) -> str:
    ctx.pr = pr = crear_pr(ctx)
    corrida = esperar_corrida(ctx, rama=pr.rama, evento="pull_request", sha=pr.sha)
    avisar(f"Esperando {WORKFLOW} del PR: {corrida['html_url']}")
    corrida = esperar_fin(ctx, corrida["id"], "plan del PR")
    job = trabajo(ctx, corrida["id"], "plan")
    pasos = {p.get("name"): p.get("conclusion") for p in job.get("steps", [])}
    malos = [f"{n}: {pasos.get(n) or 'no se ejecutó'}" for n in PASOS_PLAN if pasos.get(n) != "success"]
    if corrida.get("conclusion") != "success" or malos:
        raise Falla(
            f"{WORKFLOW} terminó «{corrida.get('conclusion')}» ({corrida.get('html_url')})"
            + (f"; pasos: {', '.join(malos)}" if malos else "")
        )
    comentarios = gh_api(f"repos/{ctx.repo}/issues/{pr.numero}/comments?per_page=100")
    del_bot = [
        c
        for c in comentarios
        if (c.get("user") or {}).get("login") == BOT and MARCADOR_COMENTARIO in (c.get("body") or "")
    ]
    if not del_bot:
        raise Falla(f"el PR #{pr.numero} no tiene el comentario del plan de {BOT}")
    cuerpo = del_bot[-1]["body"]
    if "No changes." not in cuerpo:
        resumen = next((linea.strip("* ") for linea in cuerpo.splitlines() if linea.startswith("**")), "")
        raise Falla(
            f"el plan del PR #{pr.numero} no dice «No changes.» ({resumir(resumen, 120)}): ¿falta el primer apply "
            f"de envs/dev o hay cambios sin aplicar en main?"
        )
    return (
        f"PR #{pr.numero}: {WORKFLOW} success (fmt -check, tflint, validate, plan) y comentario de {BOT} "
        f"con «No changes.»"
    )


def fusionar(ctx: Contexto, pr: Pr) -> str:
    cuerpo = {
        "merge_method": "squash",
        "sha": pr.sha,
        "commit_title": f"validacion-0-2 {ctx.v.sello} (#{pr.numero})",
        "commit_message": "Validación automática de INF-0.2 (docs/validation/validation-0-2.md).",
    }
    ultimo: ErrorGh | None = None
    for _ in range(3):
        try:
            sha = gh_api(f"repos/{ctx.repo}/pulls/{pr.numero}/merge", metodo="PUT", cuerpo=cuerpo)["sha"]
            borrar_rama(ctx, pr.rama)
            return sha
        except ErrorGh as exc:
            if exc.sin_permiso or exc.http not in (405, 409, 422):
                raise
            ultimo = exc
            dormir(INTERVALO)
    avisar(
        f"No se pudo fusionar el PR #{pr.numero} ({resumir(str(ultimo), 160)}). Si la protección de main lo exige, "
        f"fusiónalo tú: espero hasta {ESPERA_FUSION_MANUAL // 60} min. {pr.url}"
    )
    limite = time.monotonic() + ESPERA_FUSION_MANUAL
    while time.monotonic() < limite:
        datos = gh_api(f"repos/{ctx.repo}/pulls/{pr.numero}")
        if datos.get("merged"):
            borrar_rama(ctx, pr.rama)
            return datos["merge_commit_sha"]
        if datos.get("state") == "closed":
            raise Falla(f"el PR #{pr.numero} se cerró sin fusionar")
        dormir(INTERVALO)
    raise Falla(f"el PR #{pr.numero} no se fusionó en {ESPERA_FUSION_MANUAL // 60} min")


# --------------------------------------------------------------------------------------------- Terraform y S3


def linaje(directorio: str = DIR_DEV) -> tuple[str | None, int | None]:
    estado = terraform_state_pull(directorio)
    return estado.get("lineage"), estado.get("serial")


def leer_bloqueo(ctx: Contexto) -> dict[str, Any] | None:
    s3 = ctx.sesion.client("s3")
    try:
        respuesta = s3.get_object(Bucket=BUCKET_ESTADO, Key=CLAVE_BLOQUEO)
    except Exception as exc:  # noqa: BLE001 - se clasifica abajo
        if codigo_s3(exc) in ("NoSuchKey", "404", "NotFound"):
            return None
        with errores_aws(f"s3 get-object {CLAVE_BLOQUEO}"):
            raise
    try:
        return json.loads(respuesta["Body"].read())
    except ValueError:
        return {}


def existe_bloqueo(ctx: Contexto) -> bool:
    s3 = ctx.sesion.client("s3")
    try:
        s3.head_object(Bucket=BUCKET_ESTADO, Key=CLAVE_BLOQUEO)
        return True
    except Exception as exc:  # noqa: BLE001
        if codigo_s3(exc) in ("404", "NoSuchKey", "NotFound"):
            return False
        with errores_aws(f"s3 head-object {CLAVE_BLOQUEO}"):
            raise
    return False


def codigo_s3(exc: BaseException) -> str:
    return str(getattr(exc, "response", {}).get("Error", {}).get("Code", ""))


def tomar_bloqueo(ctx: Contexto) -> None:
    """Crea dev/terraform.tfstate.tflock como lo hace Terraform: escritura condicional (If-None-Match: *) con un
    LockInfo propio. Falla si ya existe: nunca se toca un bloqueo ajeno."""
    ctx_id = str(uuid.uuid4())
    info = {
        "ID": ctx_id,
        "Operation": "OperationTypeInvalid",
        "Info": f"validacion-0-2 {ctx.v.sello} (validate02.py, C3b)",
        "Who": f"validacion-0-2@{socket.gethostname()}",
        "Version": ctx.version_tf,
        "Created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "Path": f"{BUCKET_ESTADO}/{CLAVE_ESTADO}",
    }
    s3 = ctx.sesion.client("s3")
    try:
        respuesta = s3.put_object(
            Bucket=BUCKET_ESTADO,
            Key=CLAVE_BLOQUEO,
            Body=json.dumps(info).encode("utf-8"),
            ContentType="application/json",
            ServerSideEncryption="AES256",
            IfNoneMatch="*",
        )
    except Exception as exc:  # noqa: BLE001
        if codigo_s3(exc) in ("PreconditionFailed", "ConditionalRequestConflict", "412", "409"):
            raise Falla(f"{CLAVE_BLOQUEO} ya existe: otro proceso de Terraform tiene el bloqueo; no se toca") from exc
        with errores_aws(f"s3 put-object {CLAVE_BLOQUEO}"):
            raise
    ctx.bloqueo_id, ctx.bloqueo_etag = ctx_id, respuesta.get("ETag")


def liberar_bloqueo_propio(ctx: Contexto) -> None:
    """Borra el .tflock solo si sigue siendo el que creó C3b (mismo ID y, si S3 lo admite, mismo ETag)."""
    if not ctx.bloqueo_id:
        return
    bloqueo = leer_bloqueo(ctx)
    if not bloqueo or bloqueo.get("ID") != ctx.bloqueo_id:
        ctx.bloqueo_id = None
        return
    s3 = ctx.sesion.client("s3")
    try:
        if ctx.bloqueo_etag:
            s3.delete_object(Bucket=BUCKET_ESTADO, Key=CLAVE_BLOQUEO, IfMatch=ctx.bloqueo_etag)
        else:
            s3.delete_object(Bucket=BUCKET_ESTADO, Key=CLAVE_BLOQUEO)
    except Exception as exc:  # noqa: BLE001
        codigo = codigo_s3(exc)
        if codigo == "PreconditionFailed":  # ya no es el nuestro
            ctx.bloqueo_id = None
            return
        if codigo not in ("NotImplemented", "InvalidArgument", "InvalidRequest"):
            with errores_aws(f"s3 delete-object {CLAVE_BLOQUEO}"):
                raise
        s3.delete_object(Bucket=BUCKET_ESTADO, Key=CLAVE_BLOQUEO)  # S3 sin borrado condicional
    ctx.bloqueo_id = None


def plan(*extra: str) -> list[str]:
    return ["terraform", f"-chdir={DIR_DEV}", "plan", "-input=false", "-no-color", *extra]


def bloque_proveedor_aws() -> tuple[Path, str]:
    """Texto del bloque provider "aws" de envs/dev (llaves emparejadas, sin comentarios)."""
    for archivo in sorted((PROYECTO / DIR_DEV).glob("*.tf")):
        texto = archivo.read_text(encoding="utf-8")
        limpio = re.sub(r"(?m)(#|//).*$", "", texto)
        coincidencia = re.search(r'(?m)^\s*provider\s+"aws"\s*\{', limpio)
        if not coincidencia:
            continue
        nivel, inicio = 0, coincidencia.end() - 1
        for posicion in range(inicio, len(limpio)):
            if limpio[posicion] == "{":
                nivel += 1
            elif limpio[posicion] == "}":
                nivel -= 1
                if nivel == 0:
                    return archivo, limpio[inicio : posicion + 1]
        raise Falla(f'{archivo.name}: el bloque provider "aws" no cierra')
    raise Falla(f'ningún archivo de {DIR_DEV} declara provider "aws"')


def recursos_del_estado(modulo: dict[str, Any]) -> list[dict[str, Any]]:
    lista = list(modulo.get("resources", []))
    for hijo in modulo.get("child_modules", []):
        lista.extend(recursos_del_estado(hijo))
    return lista


# --------------------------------------------------------------------------------------------- precondiciones


def p3(ctx: Contexto) -> str:
    ctx.sesion = sesion_aws()
    comprobar_cuenta(ctx.sesion)
    return f"credenciales de la cuenta {CUENTA}"


def p4(ctx: Contexto) -> str:
    estado = ejecutar(["gh", "auth", "status"], timeout=60)
    texto = f"{estado.salida}\n{estado.error}"
    if estado.codigo != 0:
        raise ErrorConfiguracion(f"gh no está autenticado (gh auth login): {resumir(texto.strip(), 160)}")
    bloques = re.split(r"(?=Logged in to )", texto)
    bloque = next((b for b in bloques if "Active account: true" in b), None) or next(
        (b for b in bloques if "Logged in to " in b), texto
    )
    linea = re.search(r"Token scopes:\s*(.*)", bloque)
    if not linea:
        raise ErrorConfiguracion("gh auth status no muestra los scopes del token (se necesitan repo y workflow)")
    scopes = set(re.findall(r"'([^']+)'", linea.group(1))) or {s.strip() for s in linea.group(1).split(",")}
    faltan = sorted({"repo", "workflow"} - scopes)
    if faltan:
        raise ErrorConfiguracion(
            f"al token de gh le faltan los scopes {', '.join(faltan)} (gh auth refresh -s workflow)"
        )
    ctx.usuario = gh_api("user").get("login", "")
    datos = json.loads(gh("repo", "view", "--json", "nameWithOwner,defaultBranchRef"))
    ctx.repo = datos["nameWithOwner"]
    rama = (datos.get("defaultBranchRef") or {}).get("name")
    if rama != "main":
        raise ErrorConfiguracion(f"la rama por defecto de {ctx.repo} es «{rama}», no main")
    return f"gh de {ctx.usuario} con scopes repo y workflow sobre {ctx.repo}"


def p5(ctx: Contexto) -> str:
    resultado = ejecutar(["terraform", "version", "-json"], timeout=60)
    if resultado.codigo != 0:
        raise ErrorConfiguracion(f"terraform version falló: {resumir(resultado.texto, 160)}")
    local = json.loads(resultado.salida).get("terraform_version", "")
    if version_tupla(local)[:2] < TERRAFORM_MINIMA:
        raise ErrorConfiguracion(f"Terraform {local}: el bloqueo nativo en S3 exige ≥ 1.10")
    ctx.version_tf = local
    detalle = f"Terraform {local}"
    en_ci = None
    if RUTA_WORKFLOW.exists():
        en_ci = re.search(r'TF_VERSION:\s*"?([0-9.]+)', RUTA_WORKFLOW.read_text(encoding="utf-8"))
    if en_ci and en_ci.group(1) != local:
        detalle += f" (aviso: {WORKFLOW} usa {en_ci.group(1)}; fmt puede formatear distinto entre versiones)"
    elif en_ci:
        detalle += " (la misma que en CI)"
    return detalle


def p6(ctx: Contexto) -> str:
    resultado = ejecutar(["terraform", f"-chdir={DIR_DEV}", "state", "pull"], timeout=180)
    if resultado.codigo != 0:
        raise ErrorConfiguracion(
            f"terraform -chdir={DIR_DEV} state pull falló (¿falta terraform -chdir={DIR_DEV} init?): "
            f"{ultima_linea_error(resultado.texto)}"
        )
    if not resultado.salida.strip():
        return f"init hecho; todavía no hay estado en {CLAVE_ESTADO} (falta el primer apply de main)"
    serial = json.loads(resultado.salida).get("serial")
    return f"init hecho; estado remoto {CLAVE_ESTADO} con serial {serial}"


def p1(ctx: Contexto) -> str:
    salidas = terraform_outputs("bootstrap")
    faltan = [nombre for nombre in OUTPUTS_BOOTSTRAP if not salidas.get(nombre)]
    if faltan:
        raise Bloqueo(f"faltan outputs de bootstrap: {', '.join(faltan)} (INF-0.1)")
    if salidas["bucket_estado"] != BUCKET_ESTADO:
        raise Bloqueo(f"bucket_estado = {salidas['bucket_estado']}, y envs/dev/backend.tf usa {BUCKET_ESTADO}")
    if salidas.get("github_repo") and salidas["github_repo"] != ctx.repo:
        raise Bloqueo(f"bootstrap confía en {salidas['github_repo']}, pero gh apunta a {ctx.repo}")
    iam = ctx.sesion.client("iam")
    for rol in ROLES_GHA:
        with errores_aws(f"iam get-role {rol}"):
            iam.get_role(RoleName=rol)
    ctx.bootstrap = salidas
    return f"outputs de bootstrap presentes; existen {' y '.join(ROLES_GHA)}"


def p2(ctx: Contexto) -> str:
    variables = json.loads(gh("variable", "list", "--json", "name,value", "-R", ctx.repo))
    valores = {var["name"]: var["value"] for var in variables}
    esperado = {
        "AWS_REGION": REGION,
        "AWS_ROL_TERRAFORM_PLAN_ARN": ctx.bootstrap["rol_gha_terraform_plan_arn"],
        "AWS_ROL_TERRAFORM_ARN": ctx.bootstrap["rol_gha_terraform_arn"],
    }
    malas = [nombre for nombre, valor in esperado.items() if valores.get(nombre) != valor]
    if malas:
        raise Bloqueo(
            f"variables del repositorio ausentes o distintas de bootstrap: {', '.join(malas)} "
            f"(bootstrap/configurar_github.py, INF-0.1)"
        )
    return f"variables {', '.join(esperado)} iguales a los outputs de bootstrap"


# --------------------------------------------------------------------------------------------- comprobaciones


def c1(ctx: Contexto) -> str:
    return preparar_pr(ctx)


def c2a(ctx: Contexto) -> str:
    try:
        preparar_pr(ctx)
    except ErrorGh:
        raise
    except Falla as exc:
        raise Falla(f"no se fusiona: {exc}") from exc
    pr = ctx.pr
    assert pr is not None
    # El validador aprueba solo el apply de su propio commit: si main avanzó, ese apply llevaría cambios ajenos.
    actual = gh_api(f"repos/{ctx.repo}/git/ref/heads/main")["object"]["sha"]
    if actual != pr.base_sha:
        raise Falla(f"main avanzó durante la validación ({pr.base_sha[:7]} → {actual[:7]}): no se fusiona")
    ocupadas = [c for c in corridas(ctx, rama="main", evento="push") if c.get("status") != "completed"]
    if ocupadas:
        raise Falla(
            f"hay una ejecución de {WORKFLOW} activa en main ({ocupadas[0].get('html_url')}): espera a que termine; "
            f"no se fusiona"
        )
    sha = fusionar(ctx, pr)
    padres = [p.get("sha") for p in gh_api(f"repos/{ctx.repo}/git/commits/{sha}").get("parents", [])]
    if padres != [pr.base_sha]:
        raise Falla(
            f"el commit fusionado {sha[:7]} no sale de {pr.base_sha[:7]} (main cambió al fusionar): su apply puede "
            f"llevar cambios ajenos; no se aprueba, revísalo tú"
        )
    avisar(f"PR #{pr.numero} fusionado en main ({sha[:7]}); espero el apply")
    corrida = esperar_corrida(ctx, rama="main", evento="push", sha=sha)
    limite = time.monotonic() + ESPERA_APROBACION
    while corrida.get("status") != "waiting":
        if corrida.get("status") == "completed":
            raise Falla(
                f"la ejecución de main terminó «{corrida.get('conclusion')}» sin esperar aprobación: "
                f"{corrida.get('html_url')}"
            )
        if time.monotonic() > limite:
            raise Falla(
                f"la ejecución de main sigue «{corrida.get('status')}» tras {ESPERA_APROBACION // 60} min "
                f"(¿otra ejecución de main ocupa la fila?): {corrida.get('html_url')}"
            )
        dormir(INTERVALO)
        corrida = gh_api(f"repos/{ctx.repo}/actions/runs/{corrida['id']}")
    ctx.corrida_main = corrida
    pendientes = gh_api(f"repos/{ctx.repo}/actions/runs/{corrida['id']}/pending_deployments") or []
    dev = [p for p in pendientes if (p.get("environment") or {}).get("name") == "dev"]
    if not dev:
        raise Falla(f"la ejecución de main espera, pero no por el entorno dev: {corrida.get('html_url')}")
    job = trabajo(ctx, corrida["id"], "apply")
    ejecutados = [p.get("name") for p in job.get("steps", []) if p.get("status") != "queued"]
    if job.get("status") not in ("waiting", "queued", "pending") or ejecutados:
        raise Falla(
            f"el job de apply está «{job.get('status')}» con pasos {ejecutados}; se esperaba «waiting» sin pasos"
        )
    ctx.entorno_id = dev[0]["environment"]["id"]
    ctx.puede_aprobar = bool(dev[0].get("current_user_can_approve"))
    return f"apply de {sha[:7]} en «waiting»: el entorno dev espera aprobación y no corrió ningún paso"


def c2b(ctx: Contexto) -> str:
    corrida = ctx.corrida_main
    if corrida is None or ctx.entorno_id is None:
        raise Falla("no hay un apply esperando aprobación (C2a no pasó o no se incluyó)")
    if not ctx.puede_aprobar:
        raise Falla("la cuenta de gh no puede aprobar el entorno dev (¿no es revisora o está prevent_self_review?)")
    gh_api(
        f"repos/{ctx.repo}/actions/runs/{corrida['id']}/pending_deployments",
        metodo="POST",
        cuerpo={"environment_ids": [ctx.entorno_id], "state": "approved", "comment": "validacion-0-2"},
    )
    avisar(f"Apply aprobado; espero a que termine: {corrida.get('html_url')}")
    corrida = esperar_fin(ctx, corrida["id"], "apply de main")
    job = trabajo(ctx, corrida["id"], "apply")
    if job.get("conclusion") != "success":
        raise Falla(f"el job de apply terminó «{job.get('conclusion')}»: {job.get('html_url')}")
    log = ""
    for _ in range(6):  # el log puede tardar unos segundos en publicarse
        try:
            log = gh("api", f"repos/{ctx.repo}/actions/jobs/{job['id']}/logs", timeout=180)
        except ErrorGh as exc:
            if exc.sin_permiso:
                raise
            try:
                log = gh("run", "view", "--log", "--job", str(job["id"]), "-R", ctx.repo, timeout=180)
            except ErrorGh as otro:
                if otro.sin_permiso:
                    raise
                log = ""
        if log.strip():
            break
        dormir(INTERVALO)
    if TEXTO_APPLY not in log:
        raise Falla(f"el log del apply no contiene «{TEXTO_APPLY}»: {job.get('html_url')}")
    return f"apply aprobado y terminado con success: «{TEXTO_APPLY}»"


def c3a(ctx: Contexto) -> str:
    antes = linaje()
    procesos = [lanzar(ctx, plan(f"-lock-timeout={LOCK_TIMEOUT_ESPERA}")) for _ in range(2)]
    codigos = [esperar_proceso(p, 300, f"el plan {i + 1}") for i, p in enumerate(procesos)]
    for i, (proceso, codigo) in enumerate(zip(procesos, codigos, strict=True), start=1):
        if codigo != 0:
            raise Falla(f"el plan {i} terminó con {codigo}: {ultima_linea_error(salida_de(proceso))}")
    despues = linaje()
    if antes != despues:
        raise Falla(f"el estado cambió: lineage/serial {antes} → {despues}")
    return f"dos plan simultáneos terminaron con 0; lineage y serial sin cambios (serial {despues[1]})"


def c3b(ctx: Contexto) -> str:
    # Desde Terraform 1.15, terraform console ya no toma el bloqueo: lo toma el validador, igual que Terraform.
    tomar_bloqueo(ctx)
    inmediato = lanzar(ctx, plan("-lock-timeout=0s"))
    paciente = lanzar(ctx, plan(f"-lock-timeout={LOCK_TIMEOUT_ESPERA}"))
    inicio = time.monotonic()
    codigo = esperar_proceso(inmediato, 120, "el plan con -lock-timeout=0s")
    texto = salida_de(inmediato)
    if codigo == 0 or TEXTO_BLOQUEO not in texto:
        raise Falla(
            f"el plan con -lock-timeout=0s terminó con {codigo} sin «{TEXTO_BLOQUEO}»: {ultima_linea_error(texto)}"
        )
    dormir(max(0.0, RETENCION_BLOQUEO - (time.monotonic() - inicio)))
    if paciente.poll() is not None:
        raise Falla(
            f"el plan con -lock-timeout={LOCK_TIMEOUT_ESPERA} terminó ({paciente.returncode}) mientras el validador "
            f"retenía el bloqueo: {ultima_linea_error(salida_de(paciente))}"
        )
    liberar_bloqueo_propio(ctx)
    codigo = esperar_proceso(paciente, 180, f"el plan con -lock-timeout={LOCK_TIMEOUT_ESPERA}")
    if codigo != 0:
        raise Falla(f"el plan que esperaba el bloqueo terminó con {codigo}: {ultima_linea_error(salida_de(paciente))}")
    if existe_bloqueo(ctx):
        raise Falla(f"{CLAVE_BLOQUEO} sigue existiendo después de terminar los dos plan")
    return (
        f"con {CLAVE_BLOQUEO} tomado: -lock-timeout=0s falla con «{TEXTO_BLOQUEO}» y "
        f"-lock-timeout={LOCK_TIMEOUT_ESPERA} espera {RETENCION_BLOQUEO} s, toma el bloqueo al liberarse y termina "
        f"con 0; no queda bloqueo"
    )


def c4a(ctx: Contexto) -> str:
    resultado = ejecutar(plan("-lock=false", "-var", f"aws_account_id={CUENTA_AJENA}"), timeout=300)
    if resultado.codigo == 0:
        raise Falla(f"el plan con aws_account_id={CUENTA_AJENA} terminó con 0")
    if "not allowed" not in resultado.texto or CUENTA not in resultado.texto:
        raise Falla(f"el plan falló, pero no por allowed_account_ids: {ultima_linea_error(resultado.texto)}")
    return f"con allowed_account_ids = [{CUENTA_AJENA}] el proveedor rechaza las credenciales de {CUENTA}"


def c4b(ctx: Contexto) -> str:
    archivo, bloque = bloque_proveedor_aws()
    faltan = [nombre for nombre in ("allowed_account_ids", "default_tags", *ETIQUETAS) if nombre not in bloque]
    if faltan:
        raise Falla(f'{archivo.name}: provider "aws" no declara {", ".join(faltan)}')

    salidas = terraform_outputs(DIR_DEV)
    if salidas.get("cuenta_id") != CUENTA:
        raise Falla(f"output cuenta_id = {salidas.get('cuenta_id')!r}, se esperaba {CUENTA} (¿falta el primer apply?)")

    resultado = ejecutar(["terraform", f"-chdir={DIR_DEV}", "show", "-json", "-no-color"], timeout=180)
    if resultado.codigo != 0:
        raise Falla(f"terraform show -json falló: {ultima_linea_error(resultado.texto)}")
    estado = json.loads(resultado.salida)  # contiene valores sensibles: nunca se imprime
    recursos = recursos_del_estado(estado.get("values", {}).get("root_module", {}))

    etiquetas = next(
        (
            r.get("values", {}).get("tags")
            for r in recursos
            if r.get("mode") == "data" and r.get("type") == "aws_default_tags"
        ),
        None,
    )
    if etiquetas is None:
        raise Falla("el estado no tiene data.aws_default_tags (¿falta el primer apply?)")
    distintas = [k for k, valor in ETIQUETAS.items() if (etiquetas or {}).get(k) != valor]
    if distintas:
        raise Falla(f"default_tags efectivas distintas de §5.1 en: {', '.join(distintas)}")

    gestionados = [r for r in recursos if r.get("mode") == "managed" and "tags_all" in (r.get("values") or {})]
    sin_etiquetas = [
        r.get("address", "?")
        for r in gestionados
        if any(((r["values"].get("tags_all") or {}).get(k)) != valor for k, valor in ETIQUETAS.items())
    ]
    if sin_etiquetas:
        raise Falla(f"recursos sin las etiquetas de §5.1: {', '.join(sin_etiquetas[:10])}")
    return (
        f"{archivo.name} declara allowed_account_ids y default_tags; default_tags efectivas = §5.1; "
        f"cuenta_id = {CUENTA}; {len(gestionados)} recursos con tags_all, todos etiquetados"
    )


# --------------------------------------------------------------------------------------------- ciclo


DE_CONFIGURACION = ("P3", "P4", "P5", "P6")  # credenciales y herramientas: si fallan, código 3 (§5.11)


def como_configuracion(funcion: Any, ctx: Contexto) -> str:
    """Ejecuta una precondición de credenciales o herramientas: cualquier fallo es de configuración (código 3)."""
    try:
        return funcion(ctx)
    except (ErrorConfiguracion, Bloqueo):
        raise
    except Falla as exc:
        raise ErrorConfiguracion(str(exc)) from exc


def cuerpo(v: Validador) -> None:
    ctx = Contexto(v=v)
    orden = [  # credenciales y herramientas (código 3), luego otros lotes (código 2)
        ("P3", p3),
        ("P4", p4),
        ("P5", p5),
        ("P6", p6),
        ("P1", p1),
        ("P2", p2),
    ]
    seguir = True
    for id_, funcion in orden:
        if not seguir:
            v.precondicion_no_evaluada(id_, "una precondición anterior no se cumple")
            continue
        if id_ in DE_CONFIGURACION:
            seguir = v.precondicion(id_, lambda f=funcion: como_configuracion(f, ctx))
        else:
            seguir = v.precondicion(id_, lambda f=funcion: f(ctx))
    if not v.precondiciones_cumplidas():
        return
    # Las limpiezas corren en orden inverso: primero se terminan los procesos y después se libera el bloqueo propio.
    v.al_limpiar("borrar el .tflock que creó esta ejecución, si quedó", lambda: liberar_bloqueo_propio(ctx))
    v.al_limpiar("terminar los procesos de terraform que sigan abiertos", lambda: terminar_procesos(ctx))

    if v.alguna_incluida("C1", "C2a", "C2b"):
        limpiar_restos(ctx)

    v.comprobacion("C1", lambda: c1(ctx))
    v.comprobacion("C2a", lambda: c2a(ctx))
    v.comprobacion("C2b", lambda: c2b(ctx))
    v.comprobacion("C3a", lambda: c3a(ctx))
    v.comprobacion("C3b", lambda: c3b(ctx))
    v.comprobacion("C4a", lambda: c4a(ctx))
    v.comprobacion("C4b", lambda: c4b(ctx))


def main(argv: list[str] | None = None) -> int:
    validador = Validador(
        lote=LOTE,
        validacion=VALIDACION,
        descripcion="INF-0.2: esqueleto de envs/dev y CI de Terraform (infra.yml)",
        comprobaciones=["C1", "C2a", "C2b", "C3a", "C3b", "C4a", "C4b"],
        grupos={"C2": ["C2a", "C2b"], "C3": ["C3a", "C3b"], "C4": ["C4a", "C4b"]},
    )
    return validador.correr(cuerpo, argv)


if __name__ == "__main__":
    sys.exit(main())
