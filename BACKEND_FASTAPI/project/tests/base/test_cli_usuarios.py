"""`crear-usuario` y `desactivar-usuario` contra una base real (ARCHITECTURE §4.4, §5.9)."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from sqlalchemy import text

from app import cli
from app.config import Settings
from app.db import sesion
from app.dominio.enumerados import RolUsuario
from app.seguridad import hash as hash_password
from app.servicios import usuarios

pytestmark = pytest.mark.base

ADMIN = "admin.pruebas@campus.edu.co"
OTRO = "otro.admin@campus.edu.co"
CORREO = "validacion+user@campus.edu.co"


async def _consultar(ajustes: Settings, sentencia: str, parametros: dict) -> list[Any]:
    motor = sesion.crear_motor(ajustes, "pruebas")
    try:
        async with motor.begin() as conexion:
            resultado = await conexion.execute(text(sentencia), parametros)
            return list(resultado.all()) if resultado.returns_rows else []
    finally:
        await motor.dispose()


def consultar(ajustes: Settings, sentencia: str, **parametros: Any) -> list[Any]:
    return asyncio.run(_consultar(ajustes, sentencia, parametros))


def eventos(logs_json, nombre: str) -> list[dict]:
    return [linea for linea in logs_json.lineas if linea["evento"] == nombre]


def crear(ajustes, monkeypatch, password: str, *argumentos: str) -> int:
    monkeypatch.setenv(cli.VARIABLE_PASSWORD, password)
    return cli.main(["crear-usuario", *argumentos], ajustes=ajustes)


def usuario(ajustes: Settings, correo: str = CORREO) -> tuple:
    [fila] = consultar(
        ajustes,
        "SELECT id::text, correo, nombre, rol::text, activo, hash_password FROM usuarios WHERE correo = :c",
        c=correo,
    )
    return tuple(fila)


def auditoria(ajustes: Settings) -> list[tuple]:
    return [
        tuple(f)
        for f in consultar(
            ajustes,
            "SELECT accion, actor_id, entidad, entidad_id, detalle::text FROM auditoria "
            "WHERE accion LIKE 'usuario.%' AND accion <> 'usuario.login' ORDER BY id",
        )
    ]


def test_crea_actualiza_y_reactiva(base_migrada, monkeypatch, logs_json):
    assert (
        crear(
            base_migrada,
            monkeypatch,
            "primera-clave",
            "--correo",
            "  Validacion+User@Campus.EDU.co",
            "--nombre",
            " Persona ",
        )
        == 0
    )
    uid, correo, nombre, rol, activo, h = usuario(base_migrada)
    assert (correo, nombre, rol, activo) == (CORREO, "Persona", "user", True)
    assert h.startswith("$argon2id$") and hash_password.verificar(h, "primera-clave")
    [guardado] = eventos(logs_json, "usuario_guardado")
    assert {k: guardado[k] for k in ("resultado", "usuario_id", "rol", "reactivado")} == {
        "resultado": "creado",
        "usuario_id": uid,
        "rol": "user",
        "reactivado": False,
    }
    assert "rol_anterior" not in guardado

    assert cli.main(["desactivar-usuario", "--correo", CORREO], ajustes=base_migrada) == 0
    assert usuario(base_migrada)[4] is False
    assert cli.main(["desactivar-usuario", "--correo", CORREO], ajustes=base_migrada) == 0  # ya lo estaba: 0
    desactivados = eventos(logs_json, "usuario_desactivado")
    assert [(e["usuario_id"], e["ya_estaba_inactivo"]) for e in desactivados] == [(uid, False), (uid, True)]

    assert (
        crear(base_migrada, monkeypatch, "segunda-clave", "--correo", CORREO, "--nombre", "Otra", "--rol", "admin") == 0
    )
    uid2, _, nombre, rol, activo, h = usuario(base_migrada)
    assert (uid2, nombre, rol, activo) == (uid, "Otra", "admin", True)
    assert hash_password.verificar(h, "segunda-clave") and not hash_password.verificar(h, "primera-clave")
    actualizado = eventos(logs_json, "usuario_guardado")[-1]
    assert (actualizado["resultado"], actualizado["reactivado"], actualizado["rol_anterior"]) == (
        "actualizado",
        True,
        "user",
    )

    assert auditoria(base_migrada) == [
        ("usuario.crear", None, "usuario", uid, '{"rol": "user", "origen": "cli", "reactivado": false}'),
        ("usuario.desactivar", None, "usuario", uid, '{"origen": "cli", "ya_estaba_inactivo": false}'),
        ("usuario.desactivar", None, "usuario", uid, '{"origen": "cli", "ya_estaba_inactivo": true}'),
        (
            "usuario.actualizar",
            None,
            "usuario",
            uid,
            '{"rol": "admin", "origen": "cli", "reactivado": true, "rol_anterior": "user"}',
        ),
    ]
    texto = str(logs_json.lineas) + str(auditoria(base_migrada))
    assert "primera-clave" not in texto and "segunda-clave" not in texto and "$argon2id$" not in texto


def test_desactivar_un_correo_desconocido_termina_con_1(base_migrada, logs_json):
    assert cli.main(["desactivar-usuario", "--correo", "nadie@campus.edu.co"], ajustes=base_migrada) == 1
    [evento] = eventos(logs_json, "usuario_no_encontrado")
    assert evento["nivel"] == "WARNING"
    assert "nadie@" not in str(logs_json.lineas)


def test_no_quita_el_rol_al_ultimo_admin(base_migrada, monkeypatch, logs_json):
    antes = usuario(base_migrada, ADMIN)
    assert (
        crear(base_migrada, monkeypatch, "Pruebas-admin-123", "--correo", ADMIN, "--nombre", "X", "--rol", "user") == 1
    )
    [rechazo] = eventos(logs_json, "usuario_rechazado")
    assert "admin" in rechazo["motivo"] and rechazo["nivel"] == "ERROR"
    assert usuario(base_migrada, ADMIN) == antes
    assert auditoria(base_migrada) == []
    # Con otro admin, sí.
    assert (
        crear(
            base_migrada,
            monkeypatch,
            "Otro-admin-123",
            "--correo",
            "otro@campus.edu.co",
            "--nombre",
            "Otro",
            "--rol",
            "admin",
        )
        == 0
    )
    assert (
        crear(base_migrada, monkeypatch, "Pruebas-admin-123", "--correo", ADMIN, "--nombre", "X", "--rol", "user") == 0
    )
    assert usuario(base_migrada, ADMIN)[3] == "user"
    # Y `migrar` sigue en orden: hay una fila admin, no intenta crear el admin inicial.
    assert cli.main(["migrar"], ajustes=base_migrada) == 0


def test_desactivar_al_admin_no_lo_revive_migrar(base_migrada, monkeypatch):
    assert (
        crear(base_migrada, monkeypatch, "Otro-admin-123", "--correo", OTRO, "--nombre", "Otro", "--rol", "admin") == 0
    )
    assert cli.main(["desactivar-usuario", "--correo", ADMIN], ajustes=base_migrada) == 0
    assert cli.main(["migrar"], ajustes=base_migrada) == 0
    assert consultar(base_migrada, "SELECT correo, activo FROM usuarios ORDER BY correo") == [
        (ADMIN, False),
        (OTRO, True),
    ]


def test_no_desactiva_al_ultimo_admin_activo(base_migrada, monkeypatch, logs_json):
    assert cli.main(["desactivar-usuario", "--correo", ADMIN], ajustes=base_migrada) == 1
    [rechazo] = eventos(logs_json, "usuario_rechazado")
    assert "admin activo" in rechazo["motivo"]
    assert usuario(base_migrada, ADMIN)[4] is True
    assert auditoria(base_migrada) == []


def test_un_admin_inactivo_no_cuenta_como_otro_admin(base_migrada, monkeypatch):
    assert (
        crear(base_migrada, monkeypatch, "Otro-admin-123", "--correo", OTRO, "--nombre", "Otro", "--rol", "admin") == 0
    )
    assert cli.main(["desactivar-usuario", "--correo", OTRO], ajustes=base_migrada) == 0
    # Queda una fila admin más, pero inactiva: el admin inicial es el último activo.
    assert (
        crear(base_migrada, monkeypatch, "Pruebas-admin-123", "--correo", ADMIN, "--nombre", "X", "--rol", "user") == 1
    )
    assert cli.main(["desactivar-usuario", "--correo", ADMIN], ajustes=base_migrada) == 1
    assert usuario(base_migrada, ADMIN)[3:5] == ("admin", True)


def test_sin_rol_un_usuario_existente_conserva_el_suyo(base_migrada, monkeypatch, logs_json):
    assert crear(base_migrada, monkeypatch, "Nueva-clave-123", "--correo", ADMIN, "--nombre", "Administradora") == 0
    _, _, nombre, rol, activo, h = usuario(base_migrada, ADMIN)
    assert (nombre, rol, activo) == ("Administradora", "admin", True)
    assert hash_password.verificar(h, "Nueva-clave-123")
    guardado = eventos(logs_json, "usuario_guardado")[-1]
    assert (guardado["rol"], guardado["rol_anterior"]) == ("admin", "admin")
    # Y uno nuevo sin --rol es `user`.
    assert crear(base_migrada, monkeypatch, "otra-clave-123", "--correo", CORREO, "--nombre", "P") == 0
    assert usuario(base_migrada)[3] == "user"


def _a_la_vez(ajustes: Settings, *operaciones) -> list[object]:
    """Ejecuta las operaciones de `usuarios` a la vez, cada una con su motor (su conexión), y devuelve lo que dio cada
    una (el resultado o la excepción)."""

    async def principal():
        motores = [sesion.crear_motor(ajustes, "pruebas") for _ in operaciones]
        try:
            return await asyncio.gather(
                *(operacion(motor) for operacion, motor in zip(operaciones, motores, strict=True)),
                return_exceptions=True,
            )
        finally:
            for motor in motores:
                await motor.dispose()

    return asyncio.run(principal())


def test_dos_degradaciones_a_la_vez_no_dejan_sin_admin(base_migrada, monkeypatch):
    assert (
        crear(base_migrada, monkeypatch, "Otro-admin-123", "--correo", OTRO, "--nombre", "Otro", "--rol", "admin") == 0
    )
    resultados = _a_la_vez(
        base_migrada,
        *(
            lambda motor, correo=correo: usuarios.crear_o_actualizar(
                motor, correo=correo, nombre="X", rol=RolUsuario.user, password="Una-clave-123"
            )
            for correo in (ADMIN, OTRO)
        ),
    )
    assert sorted(type(r).__name__ for r in resultados) == ["UltimoAdmin", "UsuarioGuardado"]
    assert consultar(base_migrada, "SELECT count(*) FROM usuarios WHERE rol = 'admin' AND activo") == [(1,)]


def test_dos_creaciones_del_mismo_correo_a_la_vez(base_migrada):
    resultados = _a_la_vez(
        base_migrada,
        *(
            lambda motor: usuarios.crear_o_actualizar(
                motor, correo=CORREO, nombre="P", rol=None, password="Una-clave-123"
            )
            for _ in range(2)
        ),
    )
    assert sorted(r.resultado for r in resultados) == ["actualizado", "creado"]
    assert consultar(base_migrada, "SELECT count(*) FROM usuarios WHERE correo = :c", c=CORREO) == [(1,)]


def test_sin_esquema_termina_con_1_y_comando_fallido(base_vacia, monkeypatch, logs_json):
    assert crear(base_vacia, monkeypatch, "una-clave-larga", "--correo", CORREO, "--nombre", "P") == 1
    [evento] = eventos(logs_json, "comando_fallido")
    assert evento["comando"] == "crear-usuario" and "usuarios" in evento["motivo"]
    assert "una-clave-larga" not in str(logs_json.lineas)
