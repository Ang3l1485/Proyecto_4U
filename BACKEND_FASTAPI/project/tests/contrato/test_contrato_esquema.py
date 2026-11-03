"""Contrato: las tablas de ARCHITECTURE §5.7 dicen lo mismo que `app.db.esquema.ESPERADO`.

`verificar-esquema` compara la base con `esquema.py`; esta prueba ata `esquema.py` al documento: mismas tablas y
columnas, mismo tipo, nulo y valor por defecto, mismos tipos enumerados y los índices y restricciones que el documento
nombra existen. Se omite si el documento no está (p. ej. con `project/` copiado solo).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.db import esquema

DOCUMENTO = Path(__file__).resolve().parents[3] / "docs" / "ARCHITECTURE.md"
TIPOS_DOC = {"timestamptz": "timestamp with time zone"}


@pytest.fixture(scope="module")
def seccion() -> str:
    if not DOCUMENTO.is_file():
        pytest.skip(f"no está {DOCUMENTO}")
    texto = DOCUMENTO.read_text(encoding="utf-8")
    return texto[texto.index("### 5.7 ") : texto.index("### 5.8 ")]


def _celdas(fila: str) -> list[str]:
    return [celda.strip() for celda in fila.strip().strip("|").split("|")]


def _nombres(celda: str) -> list[str]:
    return re.findall(r"`([^`]+)`", celda)


def tablas_del_documento(seccion: str) -> dict[str, dict[str, tuple[str, bool, str | None]]]:
    """`{tabla: {columna: (tipo, nulo, defecto)}}` a partir de las tablas «Columna | Tipo | Nulo | Por defecto»."""
    resultado: dict[str, dict[str, tuple[str, bool, str | None]]] = {}
    for bloque in re.split(r"\n\*\*`", seccion)[1:]:
        nombre = bloque.split("`", 1)[0]
        filas = [linea for linea in bloque.splitlines() if linea.startswith("| ")]
        if not filas or _celdas(filas[0])[:4] != ["Columna", "Tipo", "Nulo", "Por defecto"]:
            continue
        columnas: dict[str, tuple[str, bool, str | None]] = {}
        for fila in filas[1:]:
            columna, tipo, nulo, defecto, *_ = _celdas(fila)
            if columna == "PK":
                continue
            (tipo_doc,) = _nombres(tipo)
            defecto_doc = _nombres(defecto)
            for nombre_columna in _nombres(columna):
                columnas[nombre_columna] = (
                    TIPOS_DOC.get(tipo_doc, tipo_doc),
                    nulo == "sí",
                    defecto_doc[0] if defecto_doc else None,
                )
        resultado[nombre] = columnas
    return resultado


def _defecto_legible(defecto: str | None) -> str | None:
    """`'user'::rol_usuario` → `user`; `nextval('x'::regclass)` → `nextval('x')`; `'{}'::text[]` → `'{}'`."""
    if defecto is None:
        return None
    sin_casts = re.sub(r"::[a-z_ ]+(\[\])?", "", defecto)
    if re.fullmatch(r"'[a-z_]+'", sin_casts):
        return sin_casts.strip("'")
    return sin_casts


def test_las_tablas_y_columnas_son_las_del_documento(seccion):
    documento = tablas_del_documento(seccion)
    assert set(documento) == set(esquema.ESPERADO.tablas)
    for tabla, columnas in esquema.ESPERADO.tablas.items():
        esperado = {
            nombre: (columna.tipo, columna.nulo, _defecto_legible(columna.defecto))
            for nombre, columna in columnas.items()
        }
        assert documento[tabla] == esperado, tabla


def test_los_tipos_enumerados_son_los_del_documento(seccion):
    parrafo = seccion[seccion.index("**Tipos enumerados**") : seccion.index("**`usuarios`**")]
    tipos = {
        nombre: tuple(re.findall(r"`([^`]+)`", valores))
        for nombre, valores in re.findall(r"`([a-z_]+)` \(([^)]*)\)", parrafo)
    }
    assert tipos == esquema.ESPERADO.tipos


def test_los_nombres_que_cita_el_documento_existen(seccion):
    tablas = "|".join(esquema.ESPERADO.tablas)
    citados = set(re.findall(rf"`((?:{tablas})_[a-z_0-9]+_(?:key|check|idx|seq|pkey))`", seccion))
    citados |= set(re.findall(r"CREATE INDEX ([a-z_0-9]+)", seccion))
    existentes = set(esquema.ESPERADO.secuencias)
    for por_tabla in (esquema.ESPERADO.restricciones, esquema.ESPERADO.indices):
        for nombres in por_tabla.values():
            existentes |= set(nombres)
    assert citados, "el documento debería citar restricciones e índices"
    assert citados <= existentes, sorted(citados - existentes)


def test_todos_los_indices_estan_en_el_documento(seccion):
    for nombres in esquema.ESPERADO.indices.values():
        for nombre in nombres:
            assert nombre in seccion, nombre
