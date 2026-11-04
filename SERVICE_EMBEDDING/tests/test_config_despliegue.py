"""
Tarea 5: coherencia entre config.py, Dockerfile y ecs/task_definition.json
(HU-020, escenarios 5 y 6). Solo lee archivos del repositorio.
"""

import json
import re

import pytest

from tests.conftest import RAIZ

PALABRAS_SECRETAS = ("PASSWORD", "PASSWD", "SECRET", "TOKEN", "ACCESS_KEY", "PRIVATE")


@pytest.fixture(scope="module")
def dockerfile() -> str:
    return (RAIZ / "Dockerfile").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def task_def() -> dict:
    return json.loads((RAIZ / "ecs" / "task_definition.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def contenedor(task_def) -> dict:
    assert len(task_def["containerDefinitions"]) == 1
    return task_def["containerDefinitions"][0]


@pytest.fixture(scope="module")
def entorno(contenedor) -> dict:
    return {e["name"]: e["value"] for e in contenedor.get("environment", [])}


def _modelo_por_defecto_en_config() -> str:
    fuente = (RAIZ / "app" / "config.py").read_text(encoding="utf-8")
    m = re.search(r'CLIP_MODEL_ID\s*=\s*os\.environ\.get\(\s*"CLIP_MODEL_ID"\s*,\s*"([^"]+)"', fuente)
    assert m, "No se encontró el valor por defecto de CLIP_MODEL_ID en config.py"
    return m.group(1)


# --------------------------------------------------------------------------- #
# Mismo modelo en todas partes                                                #
# --------------------------------------------------------------------------- #
def test_mismo_modelo_en_config_y_task_definition(entorno):
    assert entorno["CLIP_MODEL_ID"] == _modelo_por_defecto_en_config()


def test_el_dockerfile_precarga_el_mismo_modelo(dockerfile):
    modelo = _modelo_por_defecto_en_config()
    precargados = set(re.findall(r"from_pretrained\('([^']+)'\)", dockerfile))
    assert precargados == {modelo}


# --------------------------------------------------------------------------- #
# Imagen Docker                                                               #
# --------------------------------------------------------------------------- #
def test_dockerfile_expone_8080_y_uvicorn_escucha_ahi(dockerfile):
    assert re.search(r"^EXPOSE\s+8080\s*$", dockerfile, re.MULTILINE)
    cmd = re.search(r"^CMD\s+(\[.*\])\s*$", dockerfile, re.MULTILINE)
    assert cmd, "El Dockerfile no tiene CMD en formato JSON"
    args = json.loads(cmd.group(1))
    assert args[:2] == ["uvicorn", "app.main:app"]
    assert args[args.index("--port") + 1] == "8080"
    assert args[args.index("--host") + 1] == "0.0.0.0"


def test_dockerfile_no_corre_como_root(dockerfile):
    usuarios = re.findall(r"^USER\s+(\S+)", dockerfile, re.MULTILINE)
    assert usuarios, "El Dockerfile no define USER"
    assert usuarios[-1] not in {"root", "0"}


def test_dockerfile_no_copia_secretos(dockerfile):
    copias = re.findall(r"^COPY\s+(.+)$", dockerfile, re.MULTILINE)
    assert not any(".env" in c.split() or "terraform.tfvars" in c for c in copias)


# --------------------------------------------------------------------------- #
# Definición de tarea ECS                                                     #
# --------------------------------------------------------------------------- #
def test_task_definition_sin_secretos_en_variables(entorno, contenedor):
    sospechosas = [n for n in entorno if any(p in n.upper() for p in PALABRAS_SECRETAS)]
    assert sospechosas == []
    assert "secrets" not in contenedor  # la autenticación a la base es por rol IAM


def test_task_definition_usa_rol_de_tarea_para_iam(task_def):
    assert task_def["taskRoleArn"].startswith("arn:aws:iam::")
    assert task_def["executionRoleArn"].startswith("arn:aws:iam::")


def test_task_definition_recursos_fargate(task_def):
    assert task_def["requiresCompatibilities"] == ["FARGATE"]
    assert task_def["cpu"] == "2048"
    assert task_def["memory"] == "4096"


def test_task_definition_define_las_variables_que_lee_config(entorno):
    fuente = (RAIZ / "app" / "config.py").read_text(encoding="utf-8")
    leidas = set(re.findall(r'os\.environ(?:\.get\(|\[)\s*"([A-Z_]+)"', fuente))
    # Las que usa el servicio de predicción (las de S3 eran del job por lotes anterior).
    usadas_por_api = {
        "DB_HOST", "DB_PORT", "DB_USER", "DB_NAME", "DB_REGION",
        "EMBEDDINGS_TABLE", "LOCATIONS_TABLE", "CLIP_MODEL_ID",
    }
    assert usadas_por_api <= leidas
    assert usadas_por_api <= set(entorno)
