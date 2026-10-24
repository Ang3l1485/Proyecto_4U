"""Validador del lote INF-0.1 — Bootstrap de la cuenta.

Documento: INFRASTRUCTURA_TERRAFORM/docs/validation/validation-0-1.md · criterios: docs/PLAN.md §2.3 ·
contrato común: docs/ARCHITECTURE.md §5.11.

Uso, desde INFRASTRUCTURA_TERRAFORM/project/ (dentro de un clon del repositorio, con AWS_PROFILE y `gh` autenticado):

    uv run --group ops python src/ops/validate01.py --entorno dev [--informe RUTA] [--solo C1,C4] [--sin-limpieza]

En AWS solo lee. En GitHub crea, por la API, la rama validacion-0-1-<AAAAMMDD-HHMMSS> con un workflow de prueba y un
PR; al terminar cancela su ejecución, cierra el PR y borra la rama.
"""

from __future__ import annotations

import base64
import json
import re
import sys
import time
import urllib.parse
from dataclasses import dataclass, field
from typing import Any

import comun
from comun import (
    CUENTA,
    REGION,
    Bloqueo,
    ErrorConfiguracion,
    ErrorGh,
    Falla,
    avisar,
    errores_aws,
    gh,
    gh_api,
    resumir,
)

LOTE = "INF-0.1"
VALIDACION = "validation-0-1"
COMPROBACIONES = ["C1", "C2", "C3", "C4a", "C4b", "C4c", "C5"]
GRUPOS = {"C4": ["C4a", "C4b", "C4c"]}

BUCKET_ESTADO = f"campus-locator-tfstate-{CUENTA}"
CLAVE_ESTADO = "bootstrap/terraform.tfstate"
PRESUPUESTO = "campus-locator-mensual"
ENTORNO_GITHUB = "dev"

PREFIJO_RAMA = "validacion-0-1-"
RUTA_WORKFLOW = ".github/workflows/validacion-0-1.yml"
PROVEEDOR_OIDC = "token.actions.githubusercontent.com"
ARN_PROVEEDOR = f"arn:aws:iam::{CUENTA}:oidc-provider/{PROVEEDOR_OIDC}"
MENSAJE_STS = "Not authorized to perform sts:AssumeRoleWithWebIdentity"

# clave → (nombre del rol, sufijo del sub, output de bootstrap, variable del repositorio)
ROLES = {
    "plan": ("campus-locator-gha-terraform-plan", ":pull_request", "rol_gha_terraform_plan_arn", "AWS_ROL_TERRAFORM_PLAN_ARN"),
    "terraform": ("campus-locator-gha-terraform", f":environment:{ENTORNO_GITHUB}", "rol_gha_terraform_arn", "AWS_ROL_TERRAFORM_ARN"),
    "deploy": ("campus-locator-gha-deploy", ":ref:refs/heads/main", "rol_gha_deploy_arn", "AWS_ROL_DEPLOY_ARN"),
}
AVISOS_ESPERADOS = {("ACTUAL", 50.0), ("ACTUAL", 80.0), ("FORECASTED", 100.0)}

ESPERA_INICIO_S = 180
ESPERA_FIN_S = 15 * 60
INTERVALO_S = 10

# Workflow de prueba (validation-0-1 §2, C2 y C4). Solo existe en la rama temporal; nunca llega a main.
# El primer paso de «plan» imprime el claim sub del token OIDC (no el token) para diagnosticar el formato del sub.
WORKFLOW = """\
# Creado por INFRASTRUCTURA_TERRAFORM/project/src/ops/validate01.py (validacion-0-1 __SELLO__).
# Solo existe en la rama temporal validacion-0-1-*: nunca llega a main y el validador la borra al terminar.
name: validacion-0-1
on:
  pull_request:
permissions:
  id-token: write
  contents: read
jobs:
  plan:
    runs-on: ubuntu-latest
    steps:
      - name: sub del token OIDC (solo el claim, nunca el token)
        continue-on-error: true
        run: |
          TOKEN="$(curl -sSf -H "Authorization: bearer ${ACTIONS_ID_TOKEN_REQUEST_TOKEN}" "${ACTIONS_ID_TOKEN_REQUEST_URL}&audience=sts.amazonaws.com" | python3 -c 'import json,sys; print(json.load(sys.stdin)["value"])')"
          python3 -c 'import base64,json,sys; p=sys.argv[1].split(".")[1]; p+="="*(-len(p)%4); print("oidc-sub=" + json.loads(base64.urlsafe_b64decode(p))["sub"])' "$TOKEN"
      - name: credenciales (gha-terraform-plan)
        uses: aws-actions/configure-aws-credentials@v6
        with:
          role-to-assume: ${{ vars.AWS_ROL_TERRAFORM_PLAN_ARN }}
          aws-region: ${{ vars.AWS_REGION }}
          mask-aws-account-id: false
      - name: identidad
        run: aws sts get-caller-identity
  sin-terraform:
    runs-on: ubuntu-latest
    steps:
      - name: credenciales (gha-terraform sin entorno, debe fallar)
        uses: aws-actions/configure-aws-credentials@v6
        with:
          role-to-assume: ${{ vars.AWS_ROL_TERRAFORM_ARN }}
          aws-region: ${{ vars.AWS_REGION }}
          retry-max-attempts: 1
  sin-deploy:
    runs-on: ubuntu-latest
    steps:
      - name: credenciales (gha-deploy desde un PR, debe fallar)
        uses: aws-actions/configure-aws-credentials@v6
        with:
          role-to-assume: ${{ vars.AWS_ROL_DEPLOY_ARN }}
          aws-region: ${{ vars.AWS_REGION }}
          retry-max-attempts: 1
  dev-desde-pr:
    runs-on: ubuntu-latest
    environment: dev
    steps:
      - name: credenciales (gha-terraform con entorno dev, no debe llegar a ejecutarse)
        uses: aws-actions/configure-aws-credentials@v6
        with:
          role-to-assume: ${{ vars.AWS_ROL_TERRAFORM_ARN }}
          aws-region: ${{ vars.AWS_REGION }}
          retry-max-attempts: 1
"""


# ---------------------------------------------------------------------------------------------------------------------
# Estado compartido entre pasos
# ---------------------------------------------------------------------------------------------------------------------


@dataclass
class Ejecucion:
    """La rama, el PR y la ejecución del workflow de prueba que comparten C2, C4b y C4c."""

    repo: str
    rama: str
    pr: int | None = None
    run_id: int | None = None
    lista: bool = False  # la ejecución terminó y sus jobs están leídos
    trabajos: dict[str, dict[str, Any]] = field(default_factory=dict)
    logs: dict[str, str] = field(default_factory=dict)

    def trabajo(self, nombre: str) -> dict[str, Any]:
        if nombre not in self.trabajos:
            raise Falla(f"la ejecución {self.run_id} no tiene el job «{nombre}» (jobs: {sorted(self.trabajos)})")
        return self.trabajos[nombre]

    def log(self, nombre: str) -> str:
        """Log de un job terminado. Se lee por la API del job y no con «gh run view --log --job», que se niega
        mientras la ejecución entera no termina (pasa si «dev-desde-pr» se queda esperando aprobación)."""
        if nombre not in self.logs:
            job_id = str(self.trabajo(nombre)["id"])
            comandos = (
                ["gh", "api", f"repos/{self.repo}/actions/jobs/{job_id}/logs"],
                ["gh", "run", "view", "--repo", self.repo, "--log", "--job", job_id],
            )
            texto = ""
            for intento in range(6):  # los logs tardan unos segundos en estar disponibles tras terminar
                resultado = comun.ejecutar(comandos[intento % 2], timeout=120)
                if resultado.codigo == 0 and resultado.salida.strip():
                    texto = resultado.salida
                    break
                time.sleep(5)
            if not texto:
                raise Falla(f"no se pudo leer el log del job «{nombre}» ({job_id})")
            self.logs[nombre] = texto
        return self.logs[nombre]


@dataclass
class Contexto:
    validador: comun.Validador
    sesion: Any = None
    repo: str = ""
    prefijos_sub: list[str] = field(default_factory=list)  # [clásico, inmutable] del segmento «repo» del sub
    outputs: dict[str, Any] = field(default_factory=dict)
    ejecucion: Ejecucion | None = None
    error_ejecucion: Exception | None = None
    sub_observado: str | None = None


# ---------------------------------------------------------------------------------------------------------------------
# Precondiciones
# ---------------------------------------------------------------------------------------------------------------------


def p1_repositorio(ctx: Contexto) -> str:
    try:
        datos = json.loads(gh("repo", "view", "--json", "nameWithOwner,defaultBranchRef,visibility"))
    except ErrorGh as exc:
        if re.search(r"not a git repository|no git remotes|none of the git remotes", exc.resultado.texto, re.IGNORECASE):
            raise ErrorConfiguracion(f"ejecuta el validador desde un clon del repositorio con remoto en GitHub: {exc}") from exc
        if exc.sin_permiso:
            raise
        raise Bloqueo(f"«gh repo view» no encuentra el repositorio desde esta copia: {exc}") from exc
    repo = datos["nameWithOwner"]
    rama = (datos.get("defaultBranchRef") or {}).get("name")
    if rama != "main":
        raise Bloqueo(f"la rama por defecto de {repo} es «{rama}», no «main»")
    info = gh_api(f"repos/{repo}")
    propietario, nombre = repo.split("/", 1)
    ctx.repo = repo
    ctx.prefijos_sub = [repo, f"{propietario}@{info['owner']['id']}/{nombre}@{info['id']}"]
    visibilidad = str(datos.get("visibility", "?")).lower()
    return f"{repo} (rama por defecto main, {visibilidad})"


def p2_credenciales_aws(ctx: Contexto) -> str:
    ctx.sesion = comun.sesion_aws()
    comun.comprobar_cuenta(ctx.sesion)
    return f"cuenta {CUENTA}"


def p3_sesion_gh(ctx: Contexto) -> str:
    # --active: con varias cuentas en github.com, solo cuenta la activa (gh ≥ 2.40; si no existe, sin él).
    resultado = comun.ejecutar(["gh", "auth", "status", "--active", "--hostname", "github.com"], timeout=60)
    if resultado.codigo != 0 and "unknown flag" in resultado.texto:
        resultado = comun.ejecutar(["gh", "auth", "status", "--hostname", "github.com"], timeout=60)
    if resultado.codigo != 0:
        raise ErrorConfiguracion(f"gh no está autenticado en github.com → gh auth login -s repo,workflow ({resumir(resultado.texto, 160)})")
    scopes = _scopes(resultado.texto)
    if scopes is None:
        cabeceras = comun.ejecutar(["gh", "api", "-i", "user"], timeout=60)
        coincidencia = re.search(r"^x-oauth-scopes:\s*(.*)$", cabeceras.salida, re.IGNORECASE | re.MULTILINE)
        scopes = {s.strip() for s in coincidencia.group(1).split(",")} if coincidencia else None
    if scopes is None:
        raise ErrorConfiguracion("no se pudieron leer los scopes del token de gh (¿token fine-grained?): usa gh auth login -s repo,workflow")
    faltan = {"repo", "workflow"} - scopes
    if faltan:
        raise ErrorConfiguracion(f"al token de gh le faltan los scopes {sorted(faltan)} → gh auth refresh -s repo,workflow")
    return "gh autenticado con scopes repo y workflow"


def _scopes(texto: str) -> set[str] | None:
    for linea in texto.splitlines():
        if "token scopes" in linea.lower():
            return set(re.findall(r"'([^']+)'", linea)) or {s.strip() for s in linea.split(":", 1)[1].split(",")}
    return None


def p4_outputs_bootstrap(ctx: Contexto) -> str:
    salidas = comun.terraform_outputs("bootstrap")
    requeridos = [rol[2] for rol in ROLES.values()] + ["bucket_estado", "github_repo"]
    faltan = [nombre for nombre in requeridos if not salidas.get(nombre)]
    if faltan:
        raise Bloqueo(f"bootstrap no expone {', '.join(faltan)} (¿aplicado?)")
    if salidas["bucket_estado"] != BUCKET_ESTADO:
        raise Bloqueo(f"bucket_estado = {salidas['bucket_estado']}, se espera {BUCKET_ESTADO}")
    if salidas["github_repo"] != ctx.repo:
        raise Bloqueo(f"github_repo de bootstrap es «{salidas['github_repo']}» y el repositorio es «{ctx.repo}» (cuentan las mayúsculas)")
    for nombre_rol, _, output, _ in ROLES.values():
        esperado = f"arn:aws:iam::{CUENTA}:role/{nombre_rol}"
        if salidas[output] != esperado:
            raise Bloqueo(f"{output} = {salidas[output]}, se espera {esperado}")
    ctx.outputs = salidas
    return f"outputs de bootstrap completos; github_repo = {ctx.repo}"


def p5_variables_repositorio(ctx: Contexto) -> str:
    try:
        datos = json.loads(gh("variable", "list", "--repo", ctx.repo, "--json", "name,value"))
    except ErrorGh as exc:
        if exc.sin_permiso:
            raise ErrorConfiguracion(
                f"tu cuenta de gh no puede leer las variables de {ctx.repo}: en un repo personal solo puede su dueño "
                f"(en una organización, un admin) → ejecuta el validador con esa cuenta ({exc})"
            ) from exc
        raise
    actuales = {d["name"]: d.get("value") for d in datos}
    esperadas = {"AWS_REGION": REGION} | {variable: ctx.outputs[output] for _, _, output, variable in ROLES.values()}
    problemas = []
    for nombre, valor in esperadas.items():
        if nombre not in actuales:
            problemas.append(f"falta {nombre}")
        elif actuales[nombre] != valor:
            problemas.append(f"{nombre} = {actuales[nombre]} (se espera {valor})")
    if problemas:
        raise Bloqueo("variables del repositorio: " + "; ".join(problemas) + " → uv run python bootstrap/configurar_github.py")
    return "AWS_REGION y las tres variables de roles coinciden con bootstrap"


# ---------------------------------------------------------------------------------------------------------------------
# Rama, PR y ejecución del workflow de prueba (C2, C4b, C4c)
# ---------------------------------------------------------------------------------------------------------------------


def cancelar_ejecuciones(repo: str, rama: str) -> None:
    datos = gh_api(f"repos/{repo}/actions/runs?branch={urllib.parse.quote(rama)}&per_page=50")
    for run in datos.get("workflow_runs", []):
        if run.get("status") != "completed":
            try:
                gh_api(f"repos/{repo}/actions/runs/{run['id']}/cancel", metodo="POST")
            except ErrorGh as exc:
                if exc.http != 409:  # 409 = ya terminó
                    raise


def cerrar_pr(repo: str, numero: int) -> None:
    gh_api(f"repos/{repo}/pulls/{numero}", metodo="PATCH", cuerpo={"state": "closed"})


def borrar_rama(repo: str, rama: str) -> None:
    try:
        gh_api(f"repos/{repo}/git/refs/heads/{urllib.parse.quote(rama)}", metodo="DELETE")
    except ErrorGh as exc:
        if exc.http not in (404, 422):  # 422 = la referencia ya no existe
            raise


def limpiar_restos(ctx: Contexto) -> None:
    """Cierra los PR y borra las ramas validacion-0-1-* que dejaron ejecuciones anteriores."""
    repo = ctx.repo
    limpiadas: set[str] = set()
    prs = json.loads(gh("pr", "list", "--repo", repo, "--state", "open", "--json", "number,headRefName", "--limit", "200"))
    for pr in prs:
        if pr["headRefName"].startswith(PREFIJO_RAMA):
            cancelar_ejecuciones(repo, pr["headRefName"])
            cerrar_pr(repo, pr["number"])
            limpiadas.add(pr["headRefName"])
    ramas = gh_api(f"repos/{repo}/branches?per_page=100", paginar=True, jq=".[].name").split()
    for rama in ramas:
        if rama.startswith(PREFIJO_RAMA):
            cancelar_ejecuciones(repo, rama)
            borrar_rama(repo, rama)
            limpiadas.add(rama)
    if limpiadas:
        avisar(f"restos de ejecuciones anteriores limpiados: {', '.join(sorted(limpiadas))}")


def limpiar_ejecucion(ejecucion: Ejecucion) -> None:
    errores = []
    for paso in (
        lambda: cancelar_ejecuciones(ejecucion.repo, ejecucion.rama),
        lambda: cerrar_pr(ejecucion.repo, ejecucion.pr) if ejecucion.pr else None,
        lambda: borrar_rama(ejecucion.repo, ejecucion.rama),
    ):
        try:
            paso()
        except Exception as exc:  # noqa: BLE001 — se intenta cada paso aunque falle el anterior
            errores.append(resumir(str(exc), 160))
    if errores:
        raise Falla("; ".join(errores))


def ejecucion(ctx: Contexto) -> Ejecucion:
    """Crea la rama, el workflow y el PR una sola vez y espera a que la ejecución termine."""
    if ctx.error_ejecucion is not None:
        raise Falla(f"no hay ejecución del workflow de prueba: {ctx.error_ejecucion}")
    if ctx.ejecucion is not None and ctx.ejecucion.lista:
        return ctx.ejecucion
    try:
        return _lanzar_y_esperar(ctx)
    except Exception as exc:  # se guarda para no crear una segunda rama en la siguiente comprobación
        ctx.error_ejecucion = exc
        raise


def _lanzar_y_esperar(ctx: Contexto) -> Ejecucion:
    sello = ctx.validador.sello
    repo = ctx.repo
    ej = Ejecucion(repo=repo, rama=f"{PREFIJO_RAMA}{sello}")
    ctx.ejecucion = ej

    sha_main = gh_api(f"repos/{repo}/git/ref/heads/main")["object"]["sha"]
    gh_api(f"repos/{repo}/git/refs", metodo="POST", cuerpo={"ref": f"refs/heads/{ej.rama}", "sha": sha_main})
    ctx.validador.al_limpiar(f"la rama {ej.rama}, su PR y su ejecución", lambda: limpiar_ejecucion(ej))
    avisar(f"rama {ej.rama} creada desde main")

    cuerpo: dict[str, Any] = {
        "message": f"validacion-0-1 {sello}",
        "content": base64.b64encode(WORKFLOW.replace("__SELLO__", sello).encode("utf-8")).decode("ascii"),
        "branch": ej.rama,
    }
    try:  # si el archivo ya existiera en main, la API exige su sha para reemplazarlo
        existente = gh_api(f"repos/{repo}/contents/{RUTA_WORKFLOW}?ref={urllib.parse.quote(ej.rama)}")
        cuerpo["sha"] = existente["sha"]
    except ErrorGh as exc:
        if exc.http != 404:
            raise
    gh_api(f"repos/{repo}/contents/{RUTA_WORKFLOW}", metodo="PUT", cuerpo=cuerpo)

    pr = gh_api(
        f"repos/{repo}/pulls",
        metodo="POST",
        cuerpo={
            "title": f"validacion-0-1 {sello}",
            "head": ej.rama,
            "base": "main",
            "body": "PR temporal de `INFRASTRUCTURA_TERRAFORM/project/src/ops/validate01.py` (INF-0.1). "
            "El validador lo cierra y borra la rama al terminar. **No fusionar.**",
        },
    )
    ej.pr = int(pr["number"])
    avisar(f"PR #{ej.pr} abierto; esperando la ejecución de validacion-0-1 (5–10 min)…")

    ej.run_id = _esperar_inicio(repo, ej.rama)
    _esperar_fin(repo, ej.run_id)
    trabajos = gh_api(f"repos/{repo}/actions/runs/{ej.run_id}/jobs?per_page=100")["jobs"]
    ej.trabajos = {t["name"]: t for t in trabajos}
    ej.lista = True
    return ej


def _esperar_inicio(repo: str, rama: str) -> int:
    limite = time.monotonic() + ESPERA_INICIO_S
    while time.monotonic() < limite:
        datos = gh_api(f"repos/{repo}/actions/runs?branch={urllib.parse.quote(rama)}&event=pull_request&per_page=20")
        for run in datos.get("workflow_runs", []):
            if "validacion-0-1.yml" in str(run.get("path", "")) or run.get("name") == "validacion-0-1":
                return int(run["id"])
        time.sleep(INTERVALO_S)
    raise Falla(f"GitHub no lanzó validacion-0-1 en {ESPERA_INICIO_S} s (¿Actions desactivado en el repositorio?)")


def _esperar_fin(repo: str, run_id: int) -> None:
    """Espera a que la ejecución termine. Si solo queda «dev-desde-pr» esperando aprobación, no espera más:
    eso ya es un fallo de C4c (el entorno dev admitió la rama del PR) y la limpieza cancelará la ejecución."""
    limite = time.monotonic() + ESPERA_FIN_S
    ultimo = None
    while time.monotonic() < limite:
        run = gh_api(f"repos/{repo}/actions/runs/{run_id}")
        estado = run.get("status")
        if estado == "completed":
            return
        if estado != ultimo:
            avisar(f"ejecución {run_id}: {estado}")
            ultimo = estado
        if estado == "waiting":
            trabajos = gh_api(f"repos/{repo}/actions/runs/{run_id}/jobs?per_page=100")["jobs"]
            otros = [t for t in trabajos if t["name"] != "dev-desde-pr"]
            if otros and all(t.get("status") == "completed" for t in otros):
                return
        time.sleep(INTERVALO_S)
    raise Falla(f"la ejecución {run_id} no terminó en {ESPERA_FIN_S // 60} min")


# ---------------------------------------------------------------------------------------------------------------------
# Trust policies
# ---------------------------------------------------------------------------------------------------------------------


def politica_confianza(ctx: Contexto, clave: str) -> dict[str, Any]:
    from botocore.exceptions import ClientError

    nombre = ROLES[clave][0]
    try:
        documento = ctx.sesion.client("iam").get_role(RoleName=nombre)["Role"]["AssumeRolePolicyDocument"]
    except ClientError as exc:
        if comun.codigo_error_aws(exc) == "NoSuchEntity":
            raise Falla(f"no existe el rol {nombre}") from exc
        raise comun.error_aws(exc, f"iam get-role {nombre}") from exc
    if isinstance(documento, str):
        documento = json.loads(urllib.parse.unquote(documento))
    return documento


def analizar_confianza(documento: dict[str, Any]) -> tuple[list[str], list[str], list[str]]:
    """Devuelve (subs, auds, problemas) de un trust policy de GitHub OIDC."""
    sentencias = documento.get("Statement", [])
    if isinstance(sentencias, dict):
        sentencias = [sentencias]
    subs: list[str] = []
    auds: list[str] = []
    problemas: list[str] = []
    for numero, sentencia in enumerate(sentencias, 1):
        if sentencia.get("Effect") != "Allow":
            continue
        principal = sentencia.get("Principal")
        if not isinstance(principal, dict) or set(principal) != {"Federated"}:
            problemas.append(f"sentencia {numero}: el principal no es solo el proveedor OIDC ({principal})")
            federados: list[str] = []
        else:
            federados = _lista(principal["Federated"])
        if any(f != ARN_PROVEEDOR for f in federados):
            problemas.append(f"sentencia {numero}: confía en {federados}, no solo en {ARN_PROVEEDOR}")
        acciones = _lista(sentencia.get("Action"))
        if acciones != ["sts:AssumeRoleWithWebIdentity"]:
            problemas.append(f"sentencia {numero}: acciones {acciones}")
        tiene_sub = False
        for operador, pares in (sentencia.get("Condition") or {}).items():
            for clave, valores in pares.items():
                if clave == f"{PROVEEDOR_OIDC}:sub":
                    tiene_sub = True
                    subs.extend(_lista(valores))
                elif clave == f"{PROVEEDOR_OIDC}:aud":
                    auds.extend(_lista(valores))
                else:
                    continue
                if operador != "StringEquals":
                    problemas.append(f"sentencia {numero}: {clave.split(':')[-1]} con {operador} (debe ser StringEquals)")
        if not tiene_sub:
            problemas.append(f"sentencia {numero}: sin condición sub")
    comodines = [v for v in subs + auds if "*" in v or "?" in v]
    if comodines:
        problemas.append(f"comodines en las condiciones: {comodines}")
    return subs, auds, problemas


def _lista(valor: Any) -> list[str]:
    if valor is None:
        return []
    return [valor] if isinstance(valor, str) else [str(v) for v in valor]


# ---------------------------------------------------------------------------------------------------------------------
# Comprobaciones
# ---------------------------------------------------------------------------------------------------------------------


def c1_estado_remoto(ctx: Contexto) -> str:
    from botocore.exceptions import ClientError

    s3 = ctx.sesion.client("s3")
    try:
        cabecera = s3.head_object(Bucket=BUCKET_ESTADO, Key=CLAVE_ESTADO)
    except ClientError as exc:
        if comun.codigo_error_aws(exc) in {"404", "NoSuchKey", "NotFound", "NoSuchBucket"}:
            raise Falla(f"no existe s3://{BUCKET_ESTADO}/{CLAVE_ESTADO} (¿falta terraform -chdir=bootstrap init -migrate-state?)") from exc
        raise comun.error_aws(exc, "s3api head-object del estado") from exc

    problemas = []
    with errores_aws("s3api get-object del estado"):
        remoto = json.loads(s3.get_object(Bucket=BUCKET_ESTADO, Key=CLAVE_ESTADO)["Body"].read())
    activo = comun.terraform_state_pull("bootstrap")
    if (remoto.get("lineage"), remoto.get("serial")) != (activo.get("lineage"), activo.get("serial")):
        problemas.append(
            f"el estado que usa terraform (serial {activo.get('serial')}) no es el del bucket (serial "
            f"{remoto.get('serial')}, lineage {'igual' if remoto.get('lineage') == activo.get('lineage') else 'distinto'}): "
            "¿falta migrar el estado o queda un backend_override.tf?"
        )

    with errores_aws("s3api get-bucket-versioning"):
        versionado = s3.get_bucket_versioning(Bucket=BUCKET_ESTADO).get("Status")
    if versionado != "Enabled":
        problemas.append(f"versionado = {versionado or 'nunca activado'}")

    try:
        reglas = s3.get_bucket_encryption(Bucket=BUCKET_ESTADO)["ServerSideEncryptionConfiguration"]["Rules"]
    except ClientError as exc:
        if comun.codigo_error_aws(exc) != "ServerSideEncryptionConfigurationNotFoundError":
            raise comun.error_aws(exc, "s3api get-bucket-encryption") from exc
        reglas = []
    algoritmos = {r.get("ApplyServerSideEncryptionByDefault", {}).get("SSEAlgorithm") for r in reglas} - {None}
    if not algoritmos & {"AES256", "aws:kms", "aws:kms:dsse"}:
        problemas.append("el bucket no tiene regla de cifrado por defecto")
    if not cabecera.get("ServerSideEncryption"):
        problemas.append("el objeto no tiene ServerSideEncryption")

    with errores_aws("s3api list-object-versions"):
        respuesta = s3.list_object_versions(Bucket=BUCKET_ESTADO, Prefix=CLAVE_ESTADO)
    versiones = [v for v in respuesta.get("Versions", []) if v.get("Key") == CLAVE_ESTADO]
    if not versiones:
        problemas.append("el objeto no tiene versiones")

    if problemas:
        raise Falla("; ".join(problemas))
    return (
        f"s3://{BUCKET_ESTADO}/{CLAVE_ESTADO} es el estado activo (serial {activo.get('serial')}); versionado; "
        f"cifrado {'/'.join(sorted(algoritmos))} y objeto {cabecera['ServerSideEncryption']}; {len(versiones)} versión(es)"
    )


def c2_plan_desde_pr(ctx: Contexto) -> str:
    ej = ejecucion(ctx)
    job = ej.trabajo("plan")
    log = ej.log("plan")
    coincidencia = re.search(r"oidc-sub=(repo:\S+)", log)
    if coincidencia:
        ctx.sub_observado = coincidencia.group(1)
    nota = f"; el token trae sub={ctx.sub_observado}" if ctx.sub_observado else ""
    if job.get("conclusion") != "success":
        raise Falla(f"el job plan del PR #{ej.pr} terminó «{job.get('conclusion')}»{nota}")
    arn = re.search(rf"arn:aws:sts::{CUENTA}:assumed-role/campus-locator-gha-terraform-plan/[^\s\"',]+", log)
    if not arn:
        raise Falla(f"el log del job plan no muestra un Arn de campus-locator-gha-terraform-plan en {CUENTA}{nota}")
    return f"PR #{ej.pr}: el job plan asumió {arn.group(0)}{nota}"


def c3_entorno_dev(ctx: Contexto) -> str:
    repo = ctx.repo
    problemas: list[str] = []
    avisos: list[str] = []
    try:
        entorno = gh_api(f"repos/{repo}/environments/{ENTORNO_GITHUB}")
    except ErrorGh as exc:
        if exc.http == 404:
            raise Falla(f"no existe el entorno {ENTORNO_GITHUB} en GitHub → uv run python bootstrap/configurar_github.py") from exc
        raise

    reglas = entorno.get("protection_rules") or []
    revisores = next((r for r in reglas if r.get("type") == "required_reviewers"), None) or {}
    personas = [r for r in revisores.get("reviewers", []) if r.get("type") == "User"]
    if not personas:
        problemas.append(
            f"{ENTORNO_GITHUB} no exige la aprobación de al menos una persona (required_reviewers); "
            "en repos privados solo existe con GitHub Enterprise"
        )
    elif revisores.get("prevent_self_review") and len(personas) == 1:
        avisos.append("prevent_self_review activo con un único revisor: no podrá aprobar sus propios apply (INF-0.2 C2)")

    politica = entorno.get("deployment_branch_policy") or {}
    if not (politica.get("custom_branch_policies") is True and politica.get("protected_branches") is False):
        problemas.append(f"deployment_branch_policy = {politica or 'todas las ramas'} (debe ser custom_branch_policies)")
    else:
        lista = gh_api(f"repos/{repo}/environments/{ENTORNO_GITHUB}/deployment-branch-policies").get("branch_policies", [])
        reglas_rama = [(p.get("name"), p.get("type", "branch")) for p in lista]
        if reglas_rama != [("main", "branch")]:
            problemas.append(f"las reglas de rama de {ENTORNO_GITHUB} son {reglas_rama or 'ninguna'}; debe haber solo «main»")

    subs, _, problemas_confianza = analizar_confianza(politica_confianza(ctx, "terraform"))
    esperados = [f"repo:{p}{ROLES['terraform'][1]}" for p in ctx.prefijos_sub]
    if len(subs) != 1 or subs[0] not in esperados:
        problemas.append(f"campus-locator-gha-terraform confía en sub={subs}; se espera uno solo de {esperados}")
    problemas += [f"campus-locator-gha-terraform: {p}" for p in problemas_confianza]

    if problemas:
        raise Falla("; ".join(problemas))
    detalle = (
        f"{ENTORNO_GITHUB}: {len(personas)} revisor(es) y solo la rama main; "
        f"campus-locator-gha-terraform solo confía en {subs[0]}"
    )
    return detalle + (f" · aviso: {'; '.join(avisos)}" if avisos else "")


def c4a_trust_policies(ctx: Contexto) -> str:
    problemas: list[str] = []
    prefijos_usados: dict[str, str] = {}
    for clave, (nombre, sufijo, _, _) in ROLES.items():
        try:
            subs, auds, problemas_rol = analizar_confianza(politica_confianza(ctx, clave))
        except Falla as exc:
            problemas.append(str(exc))
            continue
        problemas += [f"{nombre}: {p}" for p in problemas_rol]
        if auds != ["sts.amazonaws.com"]:
            problemas.append(f"{nombre}: aud = {auds} (se espera solo sts.amazonaws.com)")
        candidatos = {f"repo:{p}{sufijo}": p for p in ctx.prefijos_sub}
        if len(subs) != 1 or subs[0] not in candidatos:
            problemas.append(f"{nombre}: sub = {subs}; se espera uno solo de {list(candidatos)}")
        else:
            prefijos_usados[nombre] = candidatos[subs[0]]

    if len(set(prefijos_usados.values())) > 1:
        problemas.append(f"los roles no usan el mismo formato de sub: {prefijos_usados}")
    if ctx.sub_observado and prefijos_usados:
        prefijo_token = ctx.sub_observado.removeprefix("repo:").removesuffix(ROLES["plan"][1])
        distintos = {n: p for n, p in prefijos_usados.items() if p != prefijo_token}
        if distintos:
            problemas.append(
                f"GitHub emite sub=repo:{prefijo_token}:…, pero {sorted(distintos)} confían en otro formato "
                "(variable github_ids de bootstrap, README «Formato del sub»)"
            )

    if problemas:
        raise Falla("; ".join(problemas))
    prefijo = next(iter(prefijos_usados.values()))
    return f"los 3 roles confían solo en {PROVEEDOR_OIDC} con aud=sts.amazonaws.com y un único sub repo:{prefijo}:… sin comodines"


def c4b_pr_sin_entorno(ctx: Contexto) -> str:
    ej = ejecucion(ctx)
    problemas: list[str] = []
    for nombre, rol in (("sin-terraform", "gha-terraform"), ("sin-deploy", "gha-deploy")):
        job = ej.trabajo(nombre)
        if job.get("conclusion") != "failure":
            problemas.append(f"{nombre} terminó «{job.get('conclusion')}»: un PR sin entorno pudo asumir {rol}")
            continue
        fallido = next((p for p in job.get("steps", []) if p.get("conclusion") == "failure"), None)
        if fallido is None or not str(fallido.get("name", "")).startswith("credenciales"):
            problemas.append(f"{nombre} falló en «{(fallido or {}).get('name', '?')}», no en el paso de credenciales")
        if MENSAJE_STS not in ej.log(nombre):
            problemas.append(f"el log de {nombre} no contiene «{MENSAJE_STS}»")
    if problemas:
        raise Falla("; ".join(problemas))
    return f"sin-terraform y sin-deploy rechazados por AWS en el paso de credenciales ({MENSAJE_STS})"


def c4c_pr_con_entorno(ctx: Contexto) -> str:
    ej = ejecucion(ctx)
    job = ej.trabajo("dev-desde-pr")
    problemas: list[str] = []
    if job.get("status") != "completed" or job.get("conclusion") != "failure":
        problemas.append(
            f"dev-desde-pr quedó {job.get('status')}/{job.get('conclusion')}: el entorno {ENTORNO_GITHUB} admite la rama del PR"
        )
    ejecutados = [
        p.get("name")
        for p in job.get("steps", [])
        if p.get("conclusion") not in (None, "skipped") and str(p.get("name", "")).startswith("credenciales")
    ]
    if ejecutados:
        problemas.append(f"dev-desde-pr ejecutó {ejecutados}")
    anotaciones = gh_api(f"repos/{ej.repo}/check-runs/{job['id']}/annotations") or []
    texto = " | ".join(str(a.get("message", "")) for a in anotaciones)
    if not re.search(rf"not allowed to deploy to {ENTORNO_GITHUB}|protection rules", texto, re.IGNORECASE):
        problemas.append(f"ninguna anotación menciona las reglas del entorno: «{resumir(texto, 200) or 'sin anotaciones'}»")
    if problemas:
        raise Falla("; ".join(problemas))
    return f"dev-desde-pr rechazado por GitHub sin ejecutar pasos: «{resumir(texto, 160)}»"


def correo_alertas() -> str:
    ruta = comun.PROYECTO / "bootstrap" / "terraform.tfvars"
    try:
        texto = ruta.read_text(encoding="utf-8")
    except OSError as exc:
        raise ErrorConfiguracion(f"no se puede leer {ruta}: {exc}") from exc
    coincidencia = re.search(r'^\s*correo_alertas\s*=\s*"([^"]+)"', texto, re.MULTILINE)
    correo = coincidencia.group(1).strip() if coincidencia else ""
    if "@" not in correo or "<" in correo:
        raise ErrorConfiguracion("correo_alertas no está definido en bootstrap/terraform.tfvars")
    return correo


def c5_presupuesto(ctx: Contexto) -> str:
    from botocore.exceptions import ClientError

    correo = correo_alertas()
    budgets = ctx.sesion.client("budgets")
    try:
        presupuesto = budgets.describe_budget(AccountId=CUENTA, BudgetName=PRESUPUESTO)["Budget"]
    except ClientError as exc:
        if comun.codigo_error_aws(exc) == "NotFoundException":
            raise Falla(f"no existe el presupuesto {PRESUPUESTO}") from exc
        raise comun.error_aws(exc, "budgets describe-budget") from exc

    problemas: list[str] = []
    limite = presupuesto.get("BudgetLimit") or {}
    if presupuesto.get("BudgetType") != "COST":
        problemas.append(f"BudgetType = {presupuesto.get('BudgetType')}")
    if presupuesto.get("TimeUnit") != "MONTHLY":
        problemas.append(f"TimeUnit = {presupuesto.get('TimeUnit')}")
    if float(limite.get("Amount") or 0) != 100 or limite.get("Unit") != "USD":
        problemas.append(f"límite = {limite.get('Amount')} {limite.get('Unit')} (se espera 100 USD)")

    with errores_aws("budgets describe-notifications-for-budget"):
        avisos = budgets.describe_notifications_for_budget(AccountId=CUENTA, BudgetName=PRESUPUESTO).get("Notifications", [])
    encontrados = []
    for aviso in avisos:
        clave = (aviso.get("NotificationType"), float(aviso.get("Threshold", -1)))
        # Budgets omite ThresholdType en la respuesta cuando es PERCENTAGE, su valor por defecto.
        tipo_umbral = aviso.get("ThresholdType") or "PERCENTAGE"
        descripcion = f"{clave[0]} {aviso.get('ComparisonOperator')} {aviso.get('Threshold')} {tipo_umbral}"
        if tipo_umbral != "PERCENTAGE" or aviso.get("ComparisonOperator") != "GREATER_THAN" or clave not in AVISOS_ESPERADOS:
            problemas.append(f"aviso inesperado: {descripcion}")
            continue
        encontrados.append(clave)
        suscriptores: list[dict[str, Any]] = []
        for notificacion in ({**aviso, "ThresholdType": tipo_umbral}, aviso):
            try:
                suscriptores = budgets.describe_subscribers_for_notification(
                    AccountId=CUENTA, BudgetName=PRESUPUESTO, Notification=notificacion
                ).get("Subscribers", [])
            except ClientError as exc:
                if comun.codigo_error_aws(exc) != "NotFoundException":
                    raise comun.error_aws(exc, "budgets describe-subscribers-for-notification") from exc
            if suscriptores:
                break
        correos = [s.get("Address", "").lower() for s in suscriptores if s.get("SubscriptionType") == "EMAIL"]
        if correos != [correo.lower()]:
            problemas.append(f"aviso {clave[0]} > {clave[1]:g} %: {len(correos)} suscriptor(es) EMAIL, se espera solo correo_alertas")
    if len(avisos) != 3 or sorted(encontrados) != sorted(AVISOS_ESPERADOS):
        problemas.append(f"hay {len(avisos)} aviso(s); se esperan exactamente ACTUAL > 50, ACTUAL > 80 y FORECASTED > 100")

    if problemas:
        raise Falla("; ".join(problemas))
    return f"{PRESUPUESTO}: COST, MONTHLY, 100 USD; avisos ACTUAL > 50, ACTUAL > 80 y FORECASTED > 100 al correo_alertas (EMAIL)"


# ---------------------------------------------------------------------------------------------------------------------
# Orden del validador
# ---------------------------------------------------------------------------------------------------------------------


def cuerpo(v: comun.Validador) -> None:
    ctx = Contexto(validador=v)

    # Credenciales primero (código 3): sin ellas no se puede comprobar nada más.
    credenciales_ok = v.precondicion("P2", lambda: p2_credenciales_aws(ctx))
    gh_ok = v.precondicion("P3", lambda: p3_sesion_gh(ctx))
    pendientes = [("P1", p1_repositorio), ("P4", p4_outputs_bootstrap), ("P5", p5_variables_repositorio)]
    if not (credenciales_ok and gh_ok):
        for id_, _ in pendientes:
            v.precondicion_no_evaluada(id_, "faltan credenciales (P2/P3)")
        return
    for posicion, (id_, funcion) in enumerate(pendientes):
        if not v.precondicion(id_, lambda f=funcion: f(ctx)):
            for siguiente, _ in pendientes[posicion + 1 :]:
                v.precondicion_no_evaluada(siguiente, f"depende de {id_}")
            return

    if v.alguna_incluida("C2", "C4b", "C4c"):
        try:
            limpiar_restos(ctx)
        except Exception as exc:  # noqa: BLE001 — no impide validar; la próxima ejecución lo vuelve a intentar
            avisar(f"no se pudieron limpiar restos anteriores: {type(exc).__name__}: {resumir(str(exc), 160)}")

    v.comprobacion("C1", lambda: c1_estado_remoto(ctx))
    v.comprobacion("C2", lambda: c2_plan_desde_pr(ctx))
    v.comprobacion("C3", lambda: c3_entorno_dev(ctx))
    v.comprobacion("C4a", lambda: c4a_trust_policies(ctx))
    v.comprobacion("C4b", lambda: c4b_pr_sin_entorno(ctx))
    v.comprobacion("C4c", lambda: c4c_pr_con_entorno(ctx))
    v.comprobacion("C5", lambda: c5_presupuesto(ctx))


def main(argv: list[str] | None = None) -> int:
    validador = comun.Validador(
        lote=LOTE,
        validacion=VALIDACION,
        descripcion=__doc__ or "",
        comprobaciones=COMPROBACIONES,
        grupos=GRUPOS,
    )
    return validador.correr(cuerpo, argv)


if __name__ == "__main__":
    sys.exit(main())
