"""`ColaHash`: tope de verificaciones argon2id en espera y plazo para el turno (ARCHITECTURE §4.4, §5.10)."""

from __future__ import annotations

import time

import anyio
import pytest

from app.seguridad import hash as hash_password
from app.servicios.autenticacion import ColaHash, Saturado


def test_la_cola_llena_rechaza_sin_esperar():
    cola = ColaHash(concurrentes=2, cola_max=1, espera_max_s=5)
    for _ in range(3):
        cola.reservar()
    with pytest.raises(Saturado) as error:
        cola.reservar()
    assert error.value.motivo == "cola_llena"
    cola.liberar()
    cola.reservar()  # al liberar un puesto, vuelve a admitir


def test_sin_turno_a_tiempo_es_espera_agotada_y_libera_los_puestos(monkeypatch):
    def lento(_hash: str, _password: str) -> bool:
        time.sleep(0.5)
        return True

    monkeypatch.setattr(hash_password, "verificar", lento)
    cola = ColaHash(concurrentes=1, cola_max=5, espera_max_s=0.1)
    resultados: list[object] = []

    async def intento() -> None:
        cola.reservar()
        try:
            resultados.append(await cola.verificar("h", "p"))
        except Saturado as exc:
            resultados.append(exc.motivo)

    async def principal() -> None:
        async with anyio.create_task_group() as grupo:
            grupo.start_soon(intento)
            await anyio.sleep(0.05)
            grupo.start_soon(intento)

    anyio.run(principal)
    assert resultados == ["espera_agotada", True]
    assert cola.dentro == 0


def test_verifica_y_libera(monkeypatch):
    monkeypatch.setattr(hash_password, "verificar", lambda h, p: (h, p) == ("h", "p"))
    cola = ColaHash(concurrentes=1, cola_max=0, espera_max_s=1)

    async def principal() -> list[bool]:
        resultados = []
        for password in ("p", "q"):
            cola.reservar()
            resultados.append(await cola.verificar("h", password))
        return resultados

    assert anyio.run(principal) == [True, False]
    assert cola.dentro == 0
