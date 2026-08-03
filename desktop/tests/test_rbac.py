import pytest
from sqlalchemy import select

from oilmart.db import initialize, make_engine
from oilmart.models import Product, Role, User
from oilmart.security import PermissionDenied, hash_password, permission_keys
from oilmart.seed import seed
from oilmart.services import CartLine, checkout, create_customer


def rbac_factory():
    factory = initialize(make_engine("sqlite+pysqlite:///:memory:"))
    with factory() as session:
        seed(session)
        cashier_role = session.scalar(select(Role).where(Role.name == "Cashier"))
        viewer_role = Role(name="Viewer")
        session.add(viewer_role)
        session.flush()
        session.add_all([
            User(username="cashier", password_hash=hash_password("CashierPassword1"),
                 display_name="Cashier", role_id=cashier_role.id, branch_id=1),
            User(username="viewer", password_hash=hash_password("ViewerPassword1"),
                 display_name="Viewer", role_id=viewer_role.id, branch_id=1),
        ])
        session.commit()
    return factory


def test_role_permissions_are_loaded_for_login_session():
    factory = rbac_factory()
    with factory() as session:
        cashier = session.scalar(select(User).where(User.username == "cashier"))
        assert permission_keys(session, cashier) == {
            "sales.create", "sales.view", "invoice.print", "stock.view"
        }


def test_user_without_sales_permission_cannot_bypass_ui():
    factory = rbac_factory()
    with factory() as session:
        viewer = session.scalar(select(User).where(User.username == "viewer"))
        product = session.scalar(select(Product).where(Product.barcode == "100001"))
        with pytest.raises(PermissionDenied, match="sales.create"):
            checkout(session, terminal_id=1, cashier_id=viewer.id,
                     lines=[CartLine(product.id, 1)], payment_method="cash", paid_cents=220000)


def test_cashier_cannot_create_customers_or_make_credit_sales():
    factory = rbac_factory()
    with factory() as session:
        cashier = session.scalar(select(User).where(User.username == "cashier"))
        with pytest.raises(PermissionDenied, match="customer.add"):
            create_customer(session, user_id=cashier.id, name="Blocked")
        product = session.scalar(select(Product).where(Product.barcode == "100001"))
        with pytest.raises(PermissionDenied, match="customer.credit"):
            checkout(session, terminal_id=1, cashier_id=cashier.id,
                     lines=[CartLine(product.id, 1)], payment_method="credit", paid_cents=0,
                     customer_id=1)
