"""Partes del validador de BE-1.1 que no necesitan AWS."""

from __future__ import annotations

import pytest

import comun
import validate11
from comun import Falla

SHA = "0123456789abcdef0123456789abcdef01234567"
REPO = "648617469176.dkr.ecr.us-east-1.amazonaws.com/campus-locator/backend"


@pytest.mark.parametrize(
    ("imagen", "etiqueta"),
    [
        (f"{REPO}:{SHA}", SHA),
        (f"{REPO}:bootstrap", "bootstrap"),
        (REPO, None),
        (f"{REPO}@sha256:abcd", None),
        ("localhost:5000/backend:v1", "v1"),
    ],
)
def test_etiqueta_de_la_imagen(imagen, etiqueta):
    assert validate11._etiqueta(imagen) == etiqueta


def test_solo_admite_dev():
    with pytest.raises(SystemExit) as salida:
        validate11.main(["--entorno", "local"])
    assert salida.value.code == 3


def test_sin_aws_profile_termina_con_3(tmp_path, monkeypatch):
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    assert validate11.main(["--entorno", "dev", "--informe", str(tmp_path / "i.json")]) == 3


# --- C3a: lo desplegado es el contenido actual de project/ en main --------------------------------------------------
PROYECTO = "BACKEND_FASTAPI/project/app.py"


@pytest.fixture
def historial(tmp_path, monkeypatch):
    """Repositorio git temporal en lugar del monorepo; `commit(ruta)` devuelve el SHA nuevo."""
    raiz = tmp_path / "repo"
    raiz.mkdir()

    def git(*argumentos: str) -> str:
        orden = ["git", "-c", "user.email=validacion@campus.edu.co", "-c", "user.name=validacion", *argumentos]
        return comun.ejecutar_comando(orden, cwd=raiz).strip()

    def commit(ruta: str) -> str:
        archivo = raiz / ruta
        archivo.parent.mkdir(parents=True, exist_ok=True)
        archivo.write_text(f"{archivo.read_text() if archivo.exists() else ''}+\n")
        git("add", "-A")
        git("commit", "-qm", ruta)
        return git("rev-parse", "HEAD")

    git("init", "-q", "-b", "main")
    monkeypatch.setattr(comun, "RAIZ_REPO", raiz)
    return git, commit


def c3a(git, etiqueta: str) -> str:
    git("update-ref", "refs/remotes/origin/main", "main")
    ctx = validate11.Contexto()
    ctx._imagen = validate11.ImagenDesplegada(
        "arn:…:task-definition/campus-locator-dev-api:2", f"{REPO}:{etiqueta}", etiqueta
    )
    return validate11.c3a_ultimo_commit(ctx)


def test_c3a_pasa_con_el_ultimo_commit_que_toco_project(historial):
    git, commit = historial
    sha = commit(PROYECTO)
    assert "desplegado = último commit" in c3a(git, sha)


def test_c3a_acepta_un_commit_posterior_que_solo_toca_el_workflow(historial):
    git, commit = historial
    commit(PROYECTO)
    sha = commit(".github/workflows/backend.yml")
    assert "mismo BACKEND_FASTAPI/project" in c3a(git, sha)


def test_c3a_falla_si_project_cambio_despues(historial):
    git, commit = historial
    sha = commit(PROYECTO)
    commit(PROYECTO)
    with pytest.raises(Falla, match="cambió desde entonces"):
        c3a(git, sha)


def test_c3a_falla_con_la_imagen_bootstrap(historial):
    git, commit = historial
    commit(PROYECTO)
    with pytest.raises(Falla, match="desplegado bootstrap"):
        c3a(git, "bootstrap")


def test_c3a_falla_si_el_commit_desplegado_no_esta_en_main(historial):
    git, commit = historial
    commit(PROYECTO)
    git("checkout", "-qb", "otra")
    sha = commit("README.md")
    git("checkout", "-q", "main")
    with pytest.raises(Falla, match="no está en origin/main"):
        c3a(git, sha)


def test_c3a_falla_si_el_commit_desplegado_no_existe(historial):
    git, commit = historial
    commit(PROYECTO)
    with pytest.raises(Falla, match="historial local"):
        c3a(git, "f" * 40)
