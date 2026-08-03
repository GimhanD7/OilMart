from sqlalchemy import select

from oilmart.db import initialize, make_engine
from oilmart.models import Product
from oilmart.seed import seed
from oilmart.services import CartLine, checkout
from oilmart.shifts import ShiftError, close_shift, open_shift


def test_shift_cash_reconciliation():
    factory = initialize(make_engine("sqlite+pysqlite:///:memory:"))
    with factory() as session:
        seed(session)
        shift = open_shift(session, user_id=1, terminal_id=1, opening_cash_cents=10000)
        product = session.scalar(select(Product).where(Product.barcode == "100001"))
        checkout(session, terminal_id=1, cashier_id=1, shift_id=shift.id,
                 lines=[CartLine(product.id, 1)], payment_method="cash", paid_cents=220000)
        summary = close_shift(session, shift_id=shift.id, user_id=1, counted_cash_cents=230000)
        assert summary.expected_cash_cents == 230000
        assert summary.variance_cents == 0


def test_only_one_open_shift_per_terminal():
    factory = initialize(make_engine("sqlite+pysqlite:///:memory:"))
    with factory() as session:
        seed(session)
        open_shift(session, user_id=1, terminal_id=1, opening_cash_cents=0)
        try:
            open_shift(session, user_id=1, terminal_id=1, opening_cash_cents=0)
        except ShiftError:
            pass
        else:
            raise AssertionError("second open shift should fail")
