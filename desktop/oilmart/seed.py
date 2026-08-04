from sqlalchemy import select

from .models import BillSetting, Branch, Category, Permission, Product, Role, RolePermission, Terminal, User
from .security import hash_password, verify_password

PERMISSIONS = ["dashboard.view", "reports.view", "sales.create", "sales.edit", "sales.cancel",
 "sales.refund", "sales.view", "invoice.print", "invoice.reprint", "stock.view", "product.add",
 "product.edit", "product.delete", "stock.adjust", "purchase.add", "purchase.edit", "purchase.delete",
 "customer.add", "customer.edit", "customer.delete", "customer.credit", "supplier.add", "supplier.edit",
 "supplier.delete", "expense.add", "expense.edit", "expense.approve", "user.create", "user.edit",
 "user.delete", "user.password", "user.roles", "settings.bill", "settings.system", "settings.backup"]


def seed(session):
    if session.scalar(select(Branch.id).limit(1)):
        categories = {category.name: category for category in session.scalars(select(Category)).all()}
        for name in ("Engine Oils", "Gear Oils", "Coolants", "Brake Fluids", "ATF Oils", "Filters", "Other"):
            if name not in categories:
                category = Category(name=name)
                session.add(category)
                categories[name] = category
        session.flush()
        for product in session.scalars(select(Product).where(Product.category_id.is_(None))).all():
            product.category_id = categories["Engine Oils"].id
        # Upgrade existing installations safely: a factory-password account must
        # replace it at its next successful login.
        admin = session.scalar(select(User).where(User.username == "admin"))
        if admin and verify_password("ChangeMe123!", admin.password_hash) and not admin.must_change_password:
            admin.must_change_password = True
            session.commit()
        else:
            session.commit()
        return
    branch = Branch(code="COL01", name="OilMart Colombo")
    session.add(branch); session.flush()
    terminal = Terminal(branch_id=branch.id, code="POS01")
    
    super_admin_role = Role(name="Super Admin")
    admin_role = Role(name="Admin")
    cashier_role = Role(name="Cashier")
    session.add_all([terminal, super_admin_role, admin_role, cashier_role]); session.flush()
    
    permissions = [Permission(key=p) for p in PERMISSIONS]
    session.add_all(permissions); session.flush()
    
    session.add_all(RolePermission(role_id=super_admin_role.id, permission_id=p.id) for p in permissions)
    
    admin_perms = [p for p in permissions if p.key not in ["user.roles", "settings.system"]]
    session.add_all(RolePermission(role_id=admin_role.id, permission_id=p.id) for p in admin_perms)
    
    cashier_perms = [p for p in permissions if p.key in ["sales.create", "sales.view", "invoice.print", "stock.view"]]
    session.add_all(RolePermission(role_id=cashier_role.id, permission_id=p.id) for p in cashier_perms)

    session.add(User(username="admin", display_name="Administrator", password_hash=hash_password("ChangeMe123!"),
                     role_id=super_admin_role.id, branch_id=branch.id, must_change_password=True))
    session.add(BillSetting(branch_id=branch.id))
    categories = [Category(name=name) for name in
                  ("Engine Oils", "Gear Oils", "Coolants", "Brake Fluids", "ATF Oils", "Filters", "Other")]
    session.add_all(categories); session.flush()
    engine_oils = categories[0]
    session.add_all([
        Product(barcode="100001", name="Engine Oil 1L", category_id=engine_oils.id, purchase_price_cents=180000, selling_price_cents=220000, stock_quantity=40),
        Product(barcode="100002", name="Engine Oil 4L", category_id=engine_oils.id, purchase_price_cents=620000, selling_price_cents=750000, stock_quantity=20),
    ])
    session.commit()
