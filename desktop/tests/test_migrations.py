from sqlalchemy import inspect, text

from oilmart.db import initialize, make_engine
from oilmart.migrations import current_version, migrate


def test_initialize_applies_all_migrations_once():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    initialize(engine)
    assert current_version(engine) == 11
    assert "schema_migrations" in inspect(engine).get_table_names()
    assert migrate(engine) == []


def test_migration_history_is_recorded():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    assert migrate(engine) == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]
    with engine.connect() as connection:
        history = connection.execute(
            text("SELECT version, name FROM schema_migrations ORDER BY version")
        ).all()
    assert history == [
        (1, "initial_schema"),
        (2, "performance_indexes"),
        (3, "receipt_printer_settings"),
        (4, "invoice_shift_link"),
        (5, "login_security"),
        (6, "product_categories"),
        (7, "product_catalog_fields"),
        (8, "invoice_status"),
        (9, "business_partners_and_purchases"),
        (10, "administration_pages"),
        (11, "remove_untouched_legacy_demo_products"),
    ]
