from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone
from typing import Callable

from sqlalchemy import select

from .models import Invoice, SyncOutbox, SyncStatus


class SyncWorker(threading.Thread):
    def __init__(self, session_factory, sender: Callable[[dict], dict], interval_seconds: int = 60):
        super().__init__(daemon=True, name="oilmart-sync")
        self.session_factory, self.sender, self.interval_seconds = session_factory, sender, interval_seconds
        self.stopped = threading.Event()

    def stop(self):
        self.stopped.set()

    def run(self):
        while not self.stopped.is_set():
            self.run_once()
            self.stopped.wait(self.interval_seconds)

    def run_once(self):
        now = datetime.now(timezone.utc)
        with self.session_factory() as session:
            jobs = session.execute(select(SyncOutbox).where(
                SyncOutbox.status != SyncStatus.SYNCED, SyncOutbox.next_attempt_at <= now
            ).order_by(SyncOutbox.id).limit(100)).scalars().all()
            for job in jobs:
                try:
                    result = self.sender(json.loads(job.payload_json))
                    job.status, job.last_error = SyncStatus.SYNCED, ""
                    invoice = session.execute(select(Invoice).where(Invoice.uuid == job.aggregate_uuid)).scalar_one_or_none()
                    if invoice:
                        invoice.cloud_invoice_number = result.get("cloud_invoice_number", invoice.cloud_invoice_number)
                        invoice.sync_status = SyncStatus.SYNCED
                except Exception as exc:
                    job.attempts += 1
                    job.status = SyncStatus.FAILED
                    job.last_error = str(exc)[:1000]
                    job.next_attempt_at = now + timedelta(seconds=min(3600, 2 ** min(job.attempts, 11)))
                session.commit()

