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


def _product_categories(connection: Connection) -> None:
    connection.execute(text(
        "CREATE TABLE IF NOT EXISTS categories ("
        "id INTEGER PRIMARY KEY, name VARCHAR(100) NOT NULL UNIQUE, active BOOLEAN NOT NULL DEFAULT 1)"
    ))
    columns = {row[1] for row in connection.execute(text("PRAGMA table_info(products)"))}
    if "category_id" not in columns:
        connection.execute(text("ALTER TABLE products ADD COLUMN category_id INTEGER REFERENCES categories(id)"))
    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_products_category_id ON products(category_id)"))


def _product_catalog_fields(connection: Connection) -> None:
    columns = {row[1] for row in connection.execute(text("PRAGMA table_info(products)"))}
    if "brand" not in columns:
        connection.execute(text("ALTER TABLE products ADD COLUMN brand VARCHAR(100) NOT NULL DEFAULT ''"))
    if "image_path" not in columns:
        connection.execute(text("ALTER TABLE products ADD COLUMN image_path VARCHAR(500) NOT NULL DEFAULT ''"))
    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_products_brand ON products(brand)"))


def _invoice_status(connection: Connection) -> None:
    columns = {row[1] for row in connection.execute(text("PRAGMA table_info(invoices)"))}
    if "status" not in columns:
        connection.execute(text("ALTER TABLE invoices ADD COLUMN status VARCHAR(20) NOT NULL DEFAULT 'paid'"))
    connection.execute(text("UPDATE invoices SET status='pending' WHERE payment_method='credit' AND status='paid'"))
    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_invoices_status ON invoices(status)"))


def _business_partners_and_purchases(connection: Connection) -> None:
    customer_columns = {row[1] for row in connection.execute(text("PRAGMA table_info(customers)"))}
    additions = {
        "email": "VARCHAR(160) NOT NULL DEFAULT ''", "address": "VARCHAR(255) NOT NULL DEFAULT ''",
        "customer_group": "VARCHAR(80) NOT NULL DEFAULT 'Retail'", "notes": "TEXT NOT NULL DEFAULT ''",
        "active": "BOOLEAN NOT NULL DEFAULT 1",
    }
    for name, definition in additions.items():
        if name not in customer_columns: connection.execute(text(f"ALTER TABLE customers ADD COLUMN {name} {definition}"))
    Supplier = Base.metadata.tables["suppliers"]
    Purchase = Base.metadata.tables["purchases"]
    PurchaseItem = Base.metadata.tables["purchase_items"]
    Supplier.create(connection, checkfirst=True); Purchase.create(connection, checkfirst=True); PurchaseItem.create(connection, checkfirst=True)
    movement_columns = {row[1] for row in connection.execute(text("PRAGMA table_info(inventory_movements)"))}
    if "purchase_id" not in movement_columns:
        connection.execute(text("ALTER TABLE inventory_movements ADD COLUMN purchase_id INTEGER REFERENCES purchases(id)"))
    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_purchases_supplier_date ON purchases(supplier_id, purchased_at)"))


def _administration_pages(connection: Connection) -> None:
    branch_columns = {row[1] for row in connection.execute(text("PRAGMA table_info(branches)"))}
    for name, definition in {
        "email": "VARCHAR(160) NOT NULL DEFAULT ''", "alternate_phone": "VARCHAR(30) NOT NULL DEFAULT ''",
        "city": "VARCHAR(80) NOT NULL DEFAULT ''", "postal_code": "VARCHAR(20) NOT NULL DEFAULT ''",
        "tax_number": "VARCHAR(60) NOT NULL DEFAULT ''", "gst_number": "VARCHAR(60) NOT NULL DEFAULT ''",
        "logo_path": "VARCHAR(500) NOT NULL DEFAULT ''",
    }.items():
        if name not in branch_columns:
            connection.execute(text(f"ALTER TABLE branches ADD COLUMN {name} {definition}"))
    user_columns = {row[1] for row in connection.execute(text("PRAGMA table_info(users)"))}
    for name, definition in {"email": "VARCHAR(160) NOT NULL DEFAULT ''", "phone": "VARCHAR(30) NOT NULL DEFAULT ''", "last_login_at": "DATETIME"}.items():
        if name not in user_columns:
            connection.execute(text(f"ALTER TABLE users ADD COLUMN {name} {definition}"))
    Base.metadata.tables["system_settings"].create(connection, checkfirst=True)
    Base.metadata.tables["expenses"].create(connection, checkfirst=True)


def _remove_untouched_legacy_demo_products(connection: Connection) -> None:
    """Remove only the two unmistakable, unreferenced products from old demo builds."""
    connection.execute(text("""
        DELETE FROM products
        WHERE (
            (barcode='100001' AND name='Engine Oil 1L' AND purchase_price_cents=180000
             AND selling_price_cents=220000 AND stock_quantity=40)
            OR
            (barcode='100002' AND name='Engine Oil 4L' AND purchase_price_cents=620000
             AND selling_price_cents=750000 AND stock_quantity=20)
        )
        AND COALESCE(brand, '') IN ('', 'OilMart')
        AND NOT EXISTS (SELECT 1 FROM sale_items WHERE sale_items.product_id=products.id)
        AND NOT EXISTS (SELECT 1 FROM purchase_items WHERE purchase_items.product_id=products.id)
        AND NOT EXISTS (SELECT 1 FROM inventory_movements WHERE inventory_movements.product_id=products.id)
    """))


# Append new migrations here. Released migrations must never be edited.
MIGRATIONS: tuple[Migration, ...] = (
    (1, "initial_schema", _initial_schema),
    (2, "performance_indexes", _performance_indexes),
    (3, "receipt_printer_settings", _receipt_printer_settings),
    (4, "invoice_shift_link", _invoice_shift_link),
    (5, "login_security", _login_security),
    (6, "product_categories", _product_categories),
    (7, "product_catalog_fields", _product_catalog_fields),
    (8, "invoice_status", _invoice_status),
    (9, "business_partners_and_purchases", _business_partners_and_purchases),
    (10, "administration_pages", _administration_pages),
    (11, "remove_untouched_legacy_demo_products", _remove_untouched_legacy_demo_products),
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
