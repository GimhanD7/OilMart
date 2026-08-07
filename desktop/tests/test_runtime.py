import json

from sqlalchemy import func, select

from oilmart.db import initialize, make_engine
from oilmart.models import Product, SyncOutbox, SyncStatus, SystemSetting
from oilmart.runtime import AutoBackupWorker, RuntimeCoordinator
from oilmart.seed import seed
from oilmart.sync import enqueue_outbox


def test_enqueue_refreshes_mutable_job(tmp_path):
    factory = initialize(make_engine(f"sqlite:///{(tmp_path / 'data.db').as_posix()}"))
    with factory() as session:
        enqueue_outbox(session, "product", "product-1", {"name": "First"})
        session.commit()
    with factory() as session:
        job = session.scalar(select(SyncOutbox))
        job.status = SyncStatus.SYNCED
        session.commit()
    with factory() as session:
        enqueue_outbox(session, "product", "product-1", {"name": "Updated"})
        session.commit()
        assert session.scalar(select(func.count(SyncOutbox.id))) == 1
        job = session.scalar(select(SyncOutbox))
        assert job.status == SyncStatus.PENDING
        assert json.loads(job.payload_json)["name"] == "Updated"


def test_automatic_backup_is_valid_sqlite_database(tmp_path, monkeypatch):
    database = tmp_path / "data.db"; backup_dir = tmp_path / "backups"
    factory = initialize(make_engine(f"sqlite:///{database.as_posix()}"))
    with factory() as session:
        seed(session, include_demo_data=False)
    monkeypatch.setenv("OILMART_BACKUP_DIR", str(backup_dir))
    worker = AutoBackupWorker(factory, 3600)
    worker.run_once()
    backups = list(backup_dir.glob("oilmart-*.db"))
    assert len(backups) == 1
    backup_factory = initialize(make_engine(f"sqlite:///{backups[0].as_posix()}"))
    with backup_factory() as session:
        assert session.scalar(select(func.count(SyncOutbox.id))) == 0
    assert worker.last_error == ""


def test_pull_applies_remote_catalog_and_cursor(tmp_path, monkeypatch):
    monkeypatch.delenv("OILMART_API_URL", raising=False)
    factory = initialize(make_engine(f"sqlite:///{(tmp_path / 'data.db').as_posix()}"))
    with factory() as session:
        seed(session, include_demo_data=False)

    class Sender:
        def pull(self, cursor):
            assert cursor == ""
            return {"products": [{"uuid": "remote-1", "barcode": "REMOTE-1", "name": "Remote Oil",
                "selling_price_cents": 250000, "stock_quantity": 8, "active": True}],
                "customers": [], "suppliers": [], "settings": {"currency": "LKR"}, "next_cursor": "cursor-2"}

    runtime = RuntimeCoordinator(factory); runtime.sender = Sender(); runtime.pull_once()
    with factory() as session:
        assert session.scalar(select(Product.name).where(Product.uuid == "remote-1")) == "Remote Oil"
        assert session.get(SystemSetting, "sync_pull_cursor").value == "cursor-2"
