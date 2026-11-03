"""Hash de contraseñas con argon2id (`app.seguridad.hash`)."""

from __future__ import annotations

from app.dominio.validaciones import normalizar_correo
from app.seguridad import hash as hash_password


def test_hash_argon2id_con_sal():
    primero = hash_password.calcular("Secreto-123")
    segundo = hash_password.calcular("Secreto-123")
    assert primero.startswith("$argon2id$")
    assert primero != segundo  # sal aleatoria
    assert "Secreto-123" not in primero


def test_verificar():
    guardado = hash_password.calcular("Secreto-123")
    assert hash_password.verificar(guardado, "Secreto-123")
    assert not hash_password.verificar(guardado, "secreto-123")
    assert not hash_password.verificar("no-es-un-hash", "Secreto-123")


def test_normalizar_correo():
    assert normalizar_correo("  Admin@Campus.EDU.co \n") == "admin@campus.edu.co"
