from sqlalchemy import select

from oilmart.db import initialize, make_engine
from oilmart.models import Invoice, Product
from oilmart.seed import seed
from oilmart.services import CartLine, checkout, reverse_invoice


def test_refund_restores_stock_and_updates_invoice_atomically():
    factory = initialize(make_engine("sqlite+pysqlite:///:memory:"))
    with factory() as session:
        seed(session)
        product = session.scalar(select(Product).where(Product.barcode == "100001"))
        original_stock = product.stock_quantity
        invoice = checkout(session, terminal_id=1, cashier_id=1,
            lines=[CartLine(product.id, 2)], payment_method="cash", paid_cents=440000)
        assert session.get(Product, product.id).stock_quantity == original_stock - 2
        reverse_invoice(session, invoice_id=invoice.id, user_id=1, action="refunded", reason="Test return")
        assert session.get(Product, product.id).stock_quantity == original_stock
        assert session.get(Invoice, invoice.id).status == "refunded"
