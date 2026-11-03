"""Entorno de Alembic del backend (ARCHITECTURE §4.3).

Las migraciones se aplican solo con `python -m app.cli migrar` (§5.9), que abre la conexión, toma el bloqueo de
migración y la entrega aquí en `config.attributes["connection"]`. No hay `alembic.ini`: la conexión sale de las
variables `DB_*` (infra §5.4), igual que en `api` y `worker`.

Las revisiones nuevas se escriben a mano en `versions/` (SQL explícito, como `0001`) y en el mismo cambio se
actualizan `app/db/modelos.py`, `app/db/esquema.py` y ARCHITECTURE §5.7.
"""

from __future__ import annotations

from alembic import context

from app.db.modelos import Base

conexion = context.config.attributes.get("connection")
if conexion is None or context.is_offline_mode():
    raise RuntimeError("Las migraciones se aplican con `python -m app.cli migrar` (BACKEND_FASTAPI ARCHITECTURE §5.9).")

context.configure(connection=conexion, target_metadata=Base.metadata)
with context.begin_transaction():
    context.run_migrations()
