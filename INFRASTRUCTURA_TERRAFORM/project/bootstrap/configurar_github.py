"""Configura en GitHub lo que INF-0.1 no crea con Terraform (ARCHITECTURE §3.9 y §5.9; PLAN INF-0.1).

1. Variables del repositorio (Settings → Variables, no secretos): AWS_REGION, AWS_ROL_TERRAFORM_PLAN_ARN,
   AWS_ROL_TERRAFORM_ARN y AWS_ROL_DEPLOY_ARN, con los outputs de bootstrap.
2. Entorno `dev`: required reviewers (aprobación manual) y deployment branches limitado a la rama `main`.

Es idempotente: se puede repetir tras cada `apply` de bootstrap. Solo usa la biblioteca estándar, `terraform` y `gh`.

Uso, desde INFRASTRUCTURA_TERRAFORM/project/ (AWS_PROFILE con acceso a la cuenta 648617469176, porque los outputs se
leen del estado en S3):

    uv run python bootstrap/configurar_github.py [--revisor LOGIN ...]
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

BOOTSTRAP = Path(__file__).resolve().parent
ENTORNO = "dev"
RAMA = "main"
REGION = "us-east-1"
VARIABLES = {
    "AWS_REGION": None,
    "AWS_ROL_TERRAFORM_PLAN_ARN": "rol_gha_terraform_plan_arn",
    "AWS_ROL_TERRAFORM_ARN": "rol_gha_terraform_arn",
    "AWS_ROL_DEPLOY_ARN": "rol_gha_deploy_arn",
}
AVISO_PLAN = (
    "GitHub solo admite required reviewers en repositorios públicos (cualquier plan) o en privados con GitHub "
    "Enterprise. Con un repositorio privado en Free, Pro o Team, el entorno dev no puede exigir aprobación y "
    "INF-0.1 C3 no se cumple."
)


class Error(Exception):
    pass


def correr(comando: list[str], entrada: str | None = None) -> str:
    ruta = shutil.which(comando[0])
    if ruta is None:
        raise Error(f"no se encuentra «{comando[0]}» en el PATH")
    proceso = subprocess.run(
        [ruta, *comando[1:]],
        input=entrada,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=BOOTSTRAP.parent,
    )
    if proceso.returncode != 0:
        detalle = (proceso.stderr or proceso.stdout).strip()
        raise Error(f"{' '.join(comando[:3])} …: {detalle}")
    return proceso.stdout


def api(ruta: str, metodo: str = "GET", cuerpo: object | None = None) -> object:
    comando = [
        "gh", "api", ruta, "--method", metodo,
        "-H", "Accept: application/vnd.github+json",
        "-H", "X-GitHub-Api-Version: 2022-11-28",
    ]
    entrada = None
    if cuerpo is not None:
        comando += ["--input", "-"]
        entrada = json.dumps(cuerpo)
    salida = correr(comando, entrada)
    return json.loads(salida) if salida.strip() else None


def leer_outputs() -> dict[str, object]:
    datos = json.loads(correr(["terraform", f"-chdir={BOOTSTRAP}", "output", "-json"]) or "{}")
    salidas = {nombre: valor.get("value") for nombre, valor in datos.items()}
    requeridos = [o for o in VARIABLES.values() if o] + ["github_repo"]
    faltan = [o for o in requeridos if not salidas.get(o)]
    if faltan:
        raise Error(
            f"bootstrap no expone {', '.join(faltan)}: ¿está aplicado y con «terraform -chdir=bootstrap init» hecho?"
        )
    return salidas


def configurar_variables(repo: str, salidas: dict[str, object]) -> None:
    for nombre, output in VARIABLES.items():
        valor = REGION if output is None else str(salidas[output])
        correr(["gh", "variable", "set", nombre, "--repo", repo, "--body", valor])
        print(f"  variable {nombre} = {valor}")


def revisores_actuales(repo: str) -> list[dict[str, object]]:
    """Revisores que ya tiene el entorno (vacío si aún no existe)."""
    try:
        entorno = api(f"repos/{repo}/environments/{ENTORNO}")
    except Error as exc:
        if "HTTP 404" in str(exc):
            return []
        raise
    reglas = entorno.get("protection_rules") or []
    regla = next((r for r in reglas if r.get("type") == "required_reviewers"), {})
    return [
        {"type": r["type"], "id": r["reviewer"]["id"]}
        for r in regla.get("reviewers", [])
        if r.get("type") in ("User", "Team") and r.get("reviewer", {}).get("id")
    ]


def configurar_entorno(repo: str, logins: list[str]) -> None:
    # Une los revisores que ya había, quien ejecuta el script y los de --revisor: repetir el script no quita a nadie.
    revisores = revisores_actuales(repo)
    for login in logins:
        nuevo = {"type": "User", "id": api(f"users/{login}")["id"]}
        if nuevo not in revisores:
            revisores.append(nuevo)
    if len(revisores) > 6:
        raise Error(f"GitHub admite como máximo 6 revisores por entorno y quedarían {len(revisores)}")
    cuerpo = {
        "wait_timer": 0,
        # Con un único revisor, este debe poder aprobar sus propios despliegues (INF-0.2 C2 aprueba por la API).
        "prevent_self_review": False,
        "reviewers": revisores,
        "deployment_branch_policy": {"protected_branches": False, "custom_branch_policies": True},
    }
    try:
        api(f"repos/{repo}/environments/{ENTORNO}", "PUT", cuerpo)
    except Error as exc:
        raise Error(f"{exc}\n  {AVISO_PLAN}") from exc

    politicas = api(f"repos/{repo}/environments/{ENTORNO}/deployment-branch-policies?per_page=100")
    tiene_main = False
    for politica in politicas.get("branch_policies", []):
        es_main = politica.get("name") == RAMA and politica.get("type", "branch") == "branch"
        if es_main and not tiene_main:
            tiene_main = True
            continue
        api(f"repos/{repo}/environments/{ENTORNO}/deployment-branch-policies/{politica['id']}", "DELETE")
        print(f"  regla de rama eliminada del entorno {ENTORNO}: {politica.get('name')}")
    if not tiene_main:
        api(
            f"repos/{repo}/environments/{ENTORNO}/deployment-branch-policies",
            "POST",
            {"name": RAMA, "type": "branch"},
        )


def comprobar_entorno(repo: str) -> None:
    entorno = api(f"repos/{repo}/environments/{ENTORNO}")
    reglas = entorno.get("protection_rules") or []
    revisores = next((r for r in reglas if r.get("type") == "required_reviewers"), {})
    nombres = [r.get("reviewer", {}).get("login", "?") for r in revisores.get("reviewers", [])]
    politica = entorno.get("deployment_branch_policy") or {}
    ramas = [
        p.get("name")
        for p in api(f"repos/{repo}/environments/{ENTORNO}/deployment-branch-policies").get("branch_policies", [])
    ]
    print(f"  entorno {ENTORNO}: revisores {nombres or 'ninguno'}; ramas permitidas {ramas or 'todas'}")
    if not nombres:
        raise Error(f"el entorno {ENTORNO} quedó sin required reviewers. {AVISO_PLAN}")
    if not politica.get("custom_branch_policies") or ramas != [RAMA]:
        raise Error(f"el entorno {ENTORNO} no quedó limitado a la rama {RAMA}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--revisor",
        action="append",
        default=[],
        metavar="LOGIN",
        help="usuario de GitHub que también aprueba los despliegues en dev (repetible). Siempre se añade quien "
        "ejecuta el script y se conservan los revisores que ya tenía el entorno",
    )
    args = parser.parse_args()
    for flujo in (sys.stdout, sys.stderr):
        try:
            flujo.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    try:
        salidas = leer_outputs()
        repo = str(salidas["github_repo"])
        print(f"Repositorio: {repo}")
        configurar_variables(repo, salidas)
        logins = [api("user")["login"], *args.revisor]
        configurar_entorno(repo, logins)
        comprobar_entorno(repo)
    except Error as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        if "HTTP 403" in str(exc) or "HTTP 404" in str(exc):
            print(
                "  Las variables y los entornos de un repo personal solo los puede crear su dueño (en una "
                "organización, un admin): ejecuta el script con esa cuenta de gh.",
                file=sys.stderr,
            )
        return 1
    print("Listo. Siguiente paso: uv run --group ops python src/ops/validate01.py --entorno dev")
    return 0


if __name__ == "__main__":
    sys.exit(main())
