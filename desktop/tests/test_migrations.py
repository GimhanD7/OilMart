from sqlalchemy import inspect, text

from oilmart.db import initialize, make_engine
from oilmart.migrations import current_version, migrate


def test_initialize_applies_all_migrations_once():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    initialize(engine)
    assert current_version(engine) == 2
    assert "schema_migrations" in inspect(engine).get_table_names()
    assert migrate(engine) == []


def test_migration_history_is_recorded():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    assert migrate(engine) == [1, 2]
    with engine.connect() as connection:
        history = connection.execute(
            text("SELECT version, name FROM schema_migrations ORDER BY version")
        ).all()
    assert history == [(1, "initial_schema"), (2, "performance_indexes")]

