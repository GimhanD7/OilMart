"""One-time transfer of an OilMart database between SQLAlchemy backends."""
from __future__ import annotations

import argparse
import os

from sqlalchemy import func, select, text

from .db import make_engine
from .migrations import migrate
from .models import Base, Branch


def transfer(source_url: str, target_url: str) -> dict[str, int]:
    """Copy all application tables into an empty target database."""
    if source_url == target_url:
        raise ValueError("Source and target database URLs must be different")
    source = make_engine(source_url)
    target = make_engine(target_url)
    migrate(source)
    migrate(target)
    with target.connect() as connection:
        if connection.scalar(select(func.count(Branch.id))):
            raise ValueError("Target database is not empty; transfer was cancelled")

    copied: dict[str, int] = {}
    with source.connect() as source_connection, target.begin() as target_connection:
        for table in Base.metadata.sorted_tables:
            rows = [dict(row) for row in source_connection.execute(select(table)).mappings()]
            if rows:
                target_connection.execute(table.insert(), rows)
            copied[table.name] = len(rows)

        if target.dialect.name == "postgresql":
            for table in Base.metadata.sorted_tables:
                if "id" not in table.c:
                    continue
                sequence = target_connection.scalar(
                    text("SELECT pg_get_serial_sequence(:table_name, 'id')"),
                    {"table_name": table.name},
                )
                if sequence:
                    maximum = target_connection.scalar(select(func.max(table.c.id)))
                    target_connection.execute(
                        text("SELECT setval(CAST(:sequence AS regclass), :value, :called)"),
                        {"sequence": sequence, "value": maximum or 1, "called": maximum is not None},
                    )
    source.dispose()
    target.dispose()
    return copied


def main() -> int:
    parser = argparse.ArgumentParser(description="Copy an OilMart database into an empty database")
    parser.add_argument("--source", default=os.getenv("OILMART_SOURCE_DB_URL"), help="Source SQLAlchemy URL")
    parser.add_argument("--target", default=os.getenv("OILMART_TARGET_DB_URL"), help="Target SQLAlchemy URL")
    args = parser.parse_args()
    if not args.source or not args.target:
        parser.error("provide --source and --target, or set OILMART_SOURCE_DB_URL and OILMART_TARGET_DB_URL")
    copied = transfer(args.source, args.target)
    print(f"Transferred {sum(copied.values())} rows across {len(copied)} tables.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
