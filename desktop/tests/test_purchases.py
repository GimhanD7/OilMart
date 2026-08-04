from sqlalchemy import select

from oilmart.db import initialize, make_engine
from oilmart.models import Product, Purchase, Supplier
from oilmart.seed import seed
from oilmart.services import PurchaseLine, create_purchase


def test_purchase_increases_stock_and_records_balance():
    factory = initialize(make_engine("sqlite+pysqlite:///:memory:"))
    with factory() as session:
        seed(session)
        supplier = Supplier(name="Test Supplier")
        session.add(supplier); session.commit()
        product = session.scalar(select(Product).where(Product.barcode == "100001"))
        before = product.stock_quantity
        purchase = create_purchase(session, supplier_id=supplier.id, user_id=1,
            lines=[PurchaseLine(product.id, 5, 150000)], paid_cents=300000)
        assert session.get(Product, product.id).stock_quantity == before + 5
        assert purchase.total_cents == 750000
        assert purchase.paid_cents == 300000
        assert purchase.status == "partial"
        assert session.scalar(select(Purchase)).invoice_number.startswith("PUR-")
