"""Offline-first synchronization, connectivity, and automatic backup runtime."""
from __future__ import annotations

import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

import httpx
from sqlalchemy import func, select

from .models import Customer, Product, Supplier, SyncOutbox, SyncStatus, SystemSetting
from .sync import SyncWorker


class ApiSender:
    ROUTES = {
        "invoice": "sync/sales",
        "invoice_cancelled": "sync/sales",
        "invoice_refunded": "sync/sales",
        "customer": "sync/customers",
        "product": "sync/products",
        "inventory": "sync/inventory",
        "purchase": "sync/purchases",
    }

    def __init__(self, base_url: str, token: str):
        self.base_url = base_url.rstrip("/")
        self.token = token
        if self.base_url.startswith("http://") and "localhost" not in self.base_url and "127.0.0.1" not in self.base_url:
            raise ValueError("Remote synchronization requires HTTPS")

    def __call__(self, job: SyncOutbox, payload: dict) -> dict:
        route = self.ROUTES.get(job.aggregate_type, f"sync/{job.aggregate_type}")
        headers = {"Accept": "application/json", "Idempotency-Key": job.aggregate_uuid}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        response = httpx.post(f"{self.base_url}/{route}", json=payload, headers=headers, timeout=15)
        response.raise_for_status()
        return response.json() if response.content else {}

    def reachable(self) -> bool:
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        response = httpx.get(self.base_url, headers=headers, timeout=8)
        return response.status_code < 500

    def pull(self, cursor: str) -> dict | None:
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        response = httpx.get(f"{self.base_url}/sync/changes", params={"cursor": cursor}, headers=headers, timeout=15)
        if response.status_code == 404:  # Older servers can remain upload-only.
            return None
        response.raise_for_status()
        return response.json()


class AutoBackupWorker(threading.Thread):
    def __init__(self, session_factory, interval_seconds: int, retention: int = 14):
        super().__init__(daemon=True, name="oilmart-backup")
        self.factory = session_factory; self.interval_seconds = interval_seconds; self.retention = retention
        self.stopped = threading.Event(); self.last_backup: datetime | None = None; self.last_error = ""

    def stop(self):
        self.stopped.set()

    def run(self):
        self.run_once()
        while not self.stopped.wait(self.interval_seconds):
            self.run_once()

    def run_once(self):
        engine = self.factory.kw["bind"]
        try:
            if engine.dialect.name != "sqlite":
                self.last_error = "Automatic local backup applies to SQLite; configure pg_dump for PostgreSQL"
                return
            database = engine.url.database
            if not database or database == ":memory:":
                self.last_error = "In-memory databases cannot be backed up"
                return
            backup_dir = Path(os.getenv("OILMART_BACKUP_DIR", str(Path(database).parent / "backups")))
            backup_dir.mkdir(parents=True, exist_ok=True)
            target = backup_dir / f"oilmart-{datetime.now():%Y%m%d-%H%M%S}.db"
            with sqlite3.connect(database) as source, sqlite3.connect(target) as destination:
                source.backup(destination)
            backups = sorted(backup_dir.glob("oilmart-*.db"), key=lambda path: path.stat().st_mtime, reverse=True)
            for old in backups[self.retention:]:
                old.unlink()
            self.last_backup = datetime.now(timezone.utc); self.last_error = ""
        except Exception as exc:
            self.last_error = str(exc)[:250]


class RuntimeCoordinator:
    def __init__(self, session_factory):
        self.factory = session_factory; self.lock = threading.Lock(); self.online = False; self.sync_error = ""
        api_url = os.getenv("OILMART_API_URL", "").strip(); token = os.getenv("OILMART_API_TOKEN", "").strip()
        self.sync_worker = None; self.sender = None; self.monitor_stopped = threading.Event(); self.monitor_thread = None
        if api_url:
            self.sender = ApiSender(api_url, token)
            self.sync_worker = SyncWorker(session_factory, self.sender,
                interval_seconds=max(5, int(os.getenv("OILMART_SYNC_INTERVAL", "30"))), state_callback=self._sync_state)
        self.backup_worker = AutoBackupWorker(session_factory,
            interval_seconds=max(300, int(os.getenv("OILMART_BACKUP_INTERVAL", "21600"))),
            retention=max(1, int(os.getenv("OILMART_BACKUP_RETENTION", "14"))))

    def _sync_state(self, online: bool, error: str):
        with self.lock:
            self.online = online; self.sync_error = error

    def start(self):
        self.backup_worker.start()
        if self.sync_worker:
            self.sync_worker.start()
            self.monitor_thread = threading.Thread(target=self._monitor, daemon=True, name="oilmart-connectivity")
            self.monitor_thread.start()

    def _monitor(self):
        while not self.monitor_stopped.is_set():
            try:
                reachable = bool(self.sender and self.sender.reachable())
                self._sync_state(reachable, "")
                if reachable:
                    self.pull_once()
            except Exception as exc:
                self._sync_state(False, str(exc)[:250])
            self.monitor_stopped.wait(15)

    def pull_once(self):
        if not self.sender:
            return
        with self.factory() as session:
            cursor_row = session.get(SystemSetting, "sync_pull_cursor")
            cursor = cursor_row.value if cursor_row else ""
            response = self.sender.pull(cursor)
            if not response:
                return
            for data in response.get("products", []):
                row = session.scalar(select(Product).where(Product.uuid == data["uuid"])) or Product(uuid=data["uuid"], barcode=data["barcode"], name=data["name"], purchase_price_cents=0, selling_price_cents=0)
                for field in ("barcode","name","brand","purchase_price_cents","selling_price_cents","stock_quantity","low_stock_threshold","active"):
                    if field in data: setattr(row, field, data[field])
                session.add(row)
            for model, key in ((Customer, "customers"), (Supplier, "suppliers")):
                for data in response.get(key, []):
                    row = session.scalar(select(model).where(model.uuid == data["uuid"])) or model(uuid=data["uuid"], name=data["name"])
                    fields=("name","phone","email","address","notes","active","customer_group","credit_limit_cents","credit_balance_cents") if model is Customer else ("name","phone","email","address","notes","active","category","contact_person")
                    for field in fields:
                        if field in data: setattr(row,field,data[field])
                    session.add(row)
            for key, value in response.get("settings", {}).items():
                row=session.get(SystemSetting,key) or SystemSetting(key=key); row.value=str(value); session.add(row)
            next_cursor = str(response.get("next_cursor", cursor))
            cursor_row = cursor_row or SystemSetting(key="sync_pull_cursor")
            cursor_row.value = next_cursor; session.add(cursor_row); session.commit()

    def stop(self):
        self.monitor_stopped.set()
        self.backup_worker.stop()
        if self.sync_worker:
            self.sync_worker.stop()

    def sync_now(self):
        if self.sync_worker:
            threading.Thread(target=lambda: self.sync_worker.run_once(force=True), daemon=True, name="oilmart-sync-now").start()

    def snapshot(self) -> dict:
        with self.factory() as session:
            pending = session.scalar(select(func.count(SyncOutbox.id)).where(SyncOutbox.status == SyncStatus.PENDING)) or 0
            failed = session.scalar(select(func.count(SyncOutbox.id)).where(SyncOutbox.status == SyncStatus.FAILED)) or 0
            synced = session.scalar(select(func.count(SyncOutbox.id)).where(SyncOutbox.status == SyncStatus.SYNCED)) or 0
        with self.lock:
            online, error = self.online, self.sync_error
        backup = self.backup_worker.last_backup
        return {"configured": self.sync_worker is not None, "online": online, "error": error,
            "pending": pending, "failed": failed, "synced": synced,
            "backup": backup, "backup_error": self.backup_worker.last_error}
