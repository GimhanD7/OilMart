from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from oilmart.db import initialize, make_engine
from oilmart.models import InventoryMovement, Product, SyncOutbox, Terminal
from oilmart.seed import seed
from oilmart.services import CartLine, CheckoutError, checkout


@pytest.fixture
def factory():
    factory = initialize(make_engine("sqlite+pysqlite:///:memory:"))
    with factory() as session:
        seed(session)
    return factory


def test_checkout_is_atomic_and_enqueues_sync(factory):
    with factory() as session:
        product = session.scalar(select(Product).where(Product.barcode == "100001"))
        invoice = checkout(session, terminal_id=1, cashier_id=1, lines=[CartLine(product.id, 2)],
                           payment_method="cash", paid_cents=500000,
                           now=datetime(2026, 8, 1, tzinfo=timezone.utc))
        assert invoice.local_invoice_number == "TEMP-POS01-000001"
        assert invoice.total_cents == 440000
        assert session.get(Product, product.id).stock_quantity == 38
        assert session.scalar(select(SyncOutbox).where(SyncOutbox.aggregate_uuid == invoice.uuid))
        assert session.scalar(select(InventoryMovement).where(InventoryMovement.invoice_id == invoice.id)).quantity_delta == -2


def test_insufficient_stock_rolls_back_number_and_stock(factory):
    with factory() as session:
        product = session.scalar(select(Product).where(Product.barcode == "100001"))
        with pytest.raises(CheckoutError):
            checkout(session, terminal_id=1, cashier_id=1, lines=[CartLine(product.id, 999)],
                     payment_method="cash", paid_cents=99999999)
        assert session.get(Product, product.id).stock_quantity == 40
        assert session.get(Terminal, 1).next_invoice_sequence == 1


def test_consecutive_invoice_numbers(factory):
    with factory() as session:
        product = session.scalar(select(Product).where(Product.barcode == "100001"))
        one = checkout(session, terminal_id=1, cashier_id=1, lines=[CartLine(product.id, 1)], payment_method="card", paid_cents=220000)
        two = checkout(session, terminal_id=1, cashier_id=1, lines=[CartLine(product.id, 1)], payment_method="card", paid_cents=220000)
        assert one.uuid != two.uuid
        assert two.local_invoice_number == "TEMP-POS01-000002"

