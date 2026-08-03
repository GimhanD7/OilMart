from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import ActivityLog, Invoice, Shift


class ShiftError(ValueError):
    pass


@dataclass(frozen=True)
class ShiftSummary:
    shift_id: int
    opening_cash_cents: int
    cash_sales_cents: int
    expected_cash_cents: int
    counted_cash_cents: int
    variance_cents: int


def active_shift(session: Session, terminal_id: int) -> Shift | None:
    return session.scalar(select(Shift).where(
        Shift.terminal_id == terminal_id, Shift.closed_at.is_(None)
    ).order_by(Shift.opened_at.desc()))


def open_shift(session: Session, *, user_id: int, terminal_id: int,
               opening_cash_cents: int, now: datetime | None = None) -> Shift:
    if opening_cash_cents < 0:
        raise ShiftError("Opening cash cannot be negative")
    if active_shift(session, terminal_id):
        raise ShiftError("This terminal already has an open shift")
    shift = Shift(user_id=user_id, terminal_id=terminal_id,
                  opening_cash_cents=opening_cash_cents,
                  opened_at=now or datetime.now(timezone.utc))
    session.add(shift)
    session.flush()
    session.add(ActivityLog(user_id=user_id, action="opened shift", module="shifts",
                            details=json.dumps({"shift_id": shift.id, "opening_cash_cents": opening_cash_cents})))
    session.commit()
    return shift


def close_shift(session: Session, *, shift_id: int, user_id: int,
                counted_cash_cents: int, now: datetime | None = None) -> ShiftSummary:
    if counted_cash_cents < 0:
        raise ShiftError("Counted cash cannot be negative")
    shift = session.get(Shift, shift_id)
    if not shift or shift.closed_at is not None:
        raise ShiftError("Shift is not open")
    if shift.user_id != user_id:
        raise ShiftError("Only the cashier who opened the shift can close it")
    cash_sales = session.scalar(select(func.coalesce(func.sum(Invoice.total_cents), 0)).where(
        Invoice.shift_id == shift.id, Invoice.payment_method == "cash"
    )) or 0
    expected = shift.opening_cash_cents + int(cash_sales)
    summary = ShiftSummary(shift.id, shift.opening_cash_cents, int(cash_sales), expected,
                           counted_cash_cents, counted_cash_cents - expected)
    shift.closing_cash_cents = counted_cash_cents
    shift.closed_at = now or datetime.now(timezone.utc)
    session.add(ActivityLog(user_id=user_id, action="closed shift", module="shifts",
                            details=json.dumps(summary.__dict__)))
    session.commit()
    return summary

