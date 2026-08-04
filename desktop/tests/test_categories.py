from sqlalchemy import select

from oilmart.db import initialize, make_engine
from oilmart.models import Category, Product
from oilmart.seed import seed


def test_seeded_products_have_database_categories():
    factory = initialize(make_engine("sqlite+pysqlite:///:memory:"))
    with factory() as session:
        seed(session)
        categories = session.scalars(select(Category).order_by(Category.name)).all()
        product = session.scalar(select(Product).where(Product.barcode == "100001"))
        assert len(categories) >= 7
        assert product.category_id is not None
        assert session.get(Category, product.category_id).name == "Engine Oils"


def test_new_product_can_reference_new_category():
    factory = initialize(make_engine("sqlite+pysqlite:///:memory:"))
    with factory() as session:
        seed(session)
        category = Category(name="Car Care")
        session.add(category)
        session.flush()
        product = Product(barcode="CAR001", name="Car Shampoo", category_id=category.id,
                          purchase_price_cents=50000, selling_price_cents=75000, stock_quantity=10)
        session.add(product)
        session.commit()
        assert session.scalar(select(Product).where(Product.barcode == "CAR001")).category_id == category.id
