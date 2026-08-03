"""Versioned automatic migrations for the offline database."""
from __future__ import annotations

from collections.abc import Callable
from sqlalchemy import Connection, inspect, text

from .models import Base

Migration = tuple[int, str, Callable[[Connection], None]]


def _initial_schema(connection: Connection) -> None:
    Base.metadata.create_all(connection)


def _performance_indexes(connection: Connection) -> None:
    statements = (
        "CREATE INDEX IF NOT EXISTS ix_invoices_created_at ON invoices(created_at)",
        "CREATE INDEX IF NOT EXISTS ix_invoices_sync_status ON invoices(sync_status)",
        "CREATE INDEX IF NOT EXISTS ix_sync_outbox_due ON sync_outbox(status, next_attempt_at)",
        "CREATE INDEX IF NOT EXISTS ix_inventory_movements_product_created ON inventory_movements(product_id, created_at)",
        "CREATE INDEX IF NOT EXISTS ix_activity_logs_module_created ON activity_logs(module, created_at)",
    )
    for statement in statements:
        connection.execute(text(statement))


def _receipt_printer_settings(connection: Connection) -> None:
    columns = {row[1] for row in connection.execute(text("PRAGMA table_info(bill_settings)"))}
    if "printer_name" not in columns:
        connection.execute(text("ALTER TABLE bill_settings ADD COLUMN printer_name VARCHAR(255) NOT NULL DEFAULT ''"))
    if "auto_print" not in columns:
        connection.execute(text("ALTER TABLE bill_settings ADD COLUMN auto_print BOOLEAN NOT NULL DEFAULT 0"))


def _invoice_shift_link(connection: Connection) -> None:
    columns = {row[1] for row in connection.execute(text("PRAGMA table_info(invoices)"))}
    if "shift_id" not in columns:
        connection.execute(text("ALTER TABLE invoices ADD COLUMN shift_id INTEGER REFERENCES shifts(id)"))
    connection.execute(text(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_shifts_terminal_open "
        "ON shifts(terminal_id) WHERE closed_at IS NULL"
    ))


def _login_security(connection: Connection) -> None:
    columns = {row[1] for row in connection.execute(text("PRAGMA table_info(users)"))}
    if "failed_login_attempts" not in columns:
        connection.execute(text("ALTER TABLE users ADD COLUMN failed_login_attempts INTEGER NOT NULL DEFAULT 0"))
    if "locked_until" not in columns:
        connection.execute(text("ALTER TABLE users ADD COLUMN locked_until DATETIME"))
    if "must_change_password" not in columns:
        connection.execute(text("ALTER TABLE users ADD COLUMN must_change_password BOOLEAN NOT NULL DEFAULT 0"))


# Append new migrations here. Released migrations must never be edited.
MIGRATIONS: tuple[Migration, ...] = (
    (1, "initial_schema", _initial_schema),
    (2, "performance_indexes", _performance_indexes),
    (3, "receipt_printer_settings", _receipt_printer_settings),
    (4, "invoice_shift_link", _invoice_shift_link),
    (5, "login_security", _login_security),
)


def migrate(engine) -> list[int]:
    """Apply pending migrations transactionally and return applied versions."""
    applied_now: list[int] = []
    with engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                name VARCHAR(120) NOT NULL,
                applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """))
        applied = {row[0] for row in connection.execute(text("SELECT version FROM schema_migrations"))}
        for version, name, operation in MIGRATIONS:
            if version in applied:
                continue
            operation(connection)
            connection.execute(
                text("INSERT INTO schema_migrations(version, name) VALUES (:version, :name)"),
                {"version": version, "name": name},
            )
            applied_now.append(version)
    return applied_now


def current_version(engine) -> int:
    if "schema_migrations" not in inspect(engine).get_table_names():
        return 0
    with engine.connect() as connection:
        return int(connection.scalar(text("SELECT COALESCE(MAX(version), 0) FROM schema_migrations")) or 0)


def main() -> int:
    """Run migrations manually with ``python -m oilmart.migrations``."""
    from .db import make_engine

    engine = make_engine()
    applied = migrate(engine)
    if applied:
        print(f"Applied database migrations: {', '.join(map(str, applied))}")
    else:
        print(f"Database is up to date (version {current_version(engine)}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
