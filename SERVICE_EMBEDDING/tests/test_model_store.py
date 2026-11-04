"""Tarea 3: carga única del store en memoria (HU-020, escenario 1)."""

import numpy as np
import pytest


@pytest.fixture
def cargas_falsas(store_vacio, monkeypatch):
    contador = {"modelo": 0, "refs": 0, "nombres": 0}
    matriz = np.eye(2, dtype=np.float32)
    meta = [{"id": 1, "id_point": 1, "image_name": "a.png"},
            {"id": 2, "id_point": 2, "image_name": "b.png"}]
    nombres = {1: "Biblioteca", 2: "Cafeteria"}

    def modelo():
        contador["modelo"] += 1

    def refs():
        contador["refs"] += 1
        return matriz, meta

    def noms():
        contador["nombres"] += 1
        return nombres

    monkeypatch.setattr(store_vacio, "_load_model", modelo)
    monkeypatch.setattr(store_vacio, "fetch_reference_embeddings", refs)
    monkeypatch.setattr(store_vacio, "fetch_location_names", noms)
    return store_vacio, contador, (matriz, meta, nombres)


def test_load_deja_el_store_listo(cargas_falsas):
    store, contador, (matriz, meta, nombres) = cargas_falsas
    assert store.is_ready() is False
    store.load()
    assert store.is_ready() is True
    assert store.get_ref_matrix() is matriz
    assert store.get_ref_meta() is meta
    assert store.get_location_names() is nombres
    assert contador == {"modelo": 1, "refs": 1, "nombres": 1}


def test_load_dos_veces_no_recarga(cargas_falsas):
    store, contador, _ = cargas_falsas
    store.load()
    store.load()
    assert contador == {"modelo": 1, "refs": 1, "nombres": 1}


def test_si_falla_la_base_el_store_no_queda_listo(store_vacio, monkeypatch):
    def falla():
        raise ConnectionError("sin base")

    monkeypatch.setattr(store_vacio, "_load_model", lambda: None)
    monkeypatch.setattr(store_vacio, "fetch_reference_embeddings", falla)
    with pytest.raises(ConnectionError):
        store_vacio.load()
    assert store_vacio.is_ready() is False
