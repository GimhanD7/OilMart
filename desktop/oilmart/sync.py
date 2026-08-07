from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone
from typing import Callable

from sqlalchemy import select

from .models import Invoice, SyncOutbox, SyncStatus


def enqueue_outbox(session, aggregate_type: str, aggregate_uuid: str, payload: dict) -> SyncOutbox:
    """Insert or refresh one durable sync job for a mutable aggregate."""
    encoded = json.dumps(payload, separators=(",", ":"), default=str)
    job = session.scalar(select(SyncOutbox).where(
        SyncOutbox.aggregate_type == aggregate_type,
        SyncOutbox.aggregate_uuid == aggregate_uuid,
    ))
    if job is None:
        job = SyncOutbox(aggregate_type=aggregate_type, aggregate_uuid=aggregate_uuid, payload_json=encoded)
    else:
        job.payload_json = encoded; job.status = SyncStatus.PENDING; job.attempts = 0
        job.last_error = ""; job.next_attempt_at = datetime.now(timezone.utc)
    session.add(job)
    return job


class SyncWorker(threading.Thread):
    def __init__(self, session_factory, sender: Callable[[SyncOutbox, dict], dict], interval_seconds: int = 60,
                 state_callback: Callable[[bool, str], None] | None = None):
        super().__init__(daemon=True, name="oilmart-sync")
        self.session_factory, self.sender, self.interval_seconds = session_factory, sender, interval_seconds
        self.stopped = threading.Event()
        self.run_lock = threading.Lock()
        self.state_callback = state_callback

    def stop(self):
        self.stopped.set()

    def run(self):
        while not self.stopped.is_set():
            self.run_once()
            self.stopped.wait(self.interval_seconds)

    def run_once(self, force: bool = False):
        if not self.run_lock.acquire(blocking=False):
            return
        try:
            self._run_once(force)
        finally:
            self.run_lock.release()

    def _run_once(self, force: bool = False):
        now = datetime.now(timezone.utc)
        with self.session_factory() as session:
            query = select(SyncOutbox).where(SyncOutbox.status != SyncStatus.SYNCED)
            if not force:
                query = query.where(SyncOutbox.next_attempt_at <= now)
            jobs = session.execute(query.order_by(SyncOutbox.id).limit(100)).scalars().all()
            for job in jobs:
                try:
                    result = self.sender(job, json.loads(job.payload_json))
                    job.status, job.last_error = SyncStatus.SYNCED, ""
                    if self.state_callback:
                        self.state_callback(True, "")
                    invoice = session.execute(select(Invoice).where(Invoice.uuid == job.aggregate_uuid)).scalar_one_or_none()
                    if invoice:
                        invoice.cloud_invoice_number = result.get("cloud_invoice_number", invoice.cloud_invoice_number)
                        invoice.sync_status = SyncStatus.SYNCED
                except Exception as exc:
                    job.attempts += 1
                    job.status = SyncStatus.FAILED
                    job.last_error = str(exc)[:1000]
                    job.next_attempt_at = now + timedelta(seconds=min(3600, 2 ** min(job.attempts, 11)))
                    if self.state_callback:
                        self.state_callback(False, str(exc)[:250])
                session.commit()
