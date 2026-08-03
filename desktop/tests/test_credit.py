import pytest
from sqlalchemy import select

from oilmart.db import initialize, make_engine
from oilmart.models import Customer, Product
from oilmart.seed import seed
from oilmart.services import CartLine, CheckoutError, checkout


def factory_with_customer(limit=500000):
    factory = initialize(make_engine("sqlite+pysqlite:///:memory:"))
    with factory() as session:
        seed(session)
        customer = Customer(name="Credit Customer", phone="0770000000", credit_limit_cents=limit)
        session.add(customer)
        session.commit()
    return factory


def test_credit_sale_requires_customer():
    factory = factory_with_customer()
    with factory() as session:
        product = session.scalar(select(Product).where(Product.barcode == "100001"))
        with pytest.raises(CheckoutError, match="Select a customer"):
            checkout(session, terminal_id=1, cashier_id=1, lines=[CartLine(product.id, 1)],
                     payment_method="credit", paid_cents=0)


def test_credit_balance_updates_and_limit_is_enforced():
    factory = factory_with_customer(limit=300000)
    with factory() as session:
        product = session.scalar(select(Product).where(Product.barcode == "100001"))
        customer = session.scalar(select(Customer))
        checkout(session, terminal_id=1, cashier_id=1, customer_id=customer.id,
                 lines=[CartLine(product.id, 1)], payment_method="credit", paid_cents=0)
        assert session.get(Customer, customer.id).credit_balance_cents == 220000
        with pytest.raises(CheckoutError, match="credit limit exceeded"):
            checkout(session, terminal_id=1, cashier_id=1, customer_id=customer.id,
                     lines=[CartLine(product.id, 1)], payment_method="credit", paid_cents=0)
