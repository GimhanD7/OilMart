from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import or_, select

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction, QFont
from PyQt6.QtWidgets import (
    QAbstractItemView, QApplication, QComboBox, QDialog, QDialogButtonBox,
    QFormLayout, QFrame, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMainWindow, QMessageBox, QPushButton, QSpinBox, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from .models import Product, Terminal, User
from .security import verify_password
from .services import CartLine, CheckoutError, checkout


def money(cents: int) -> str:
    return f"Rs. {cents / 100:,.2f}"


class LoginDialog(QDialog):
    def __init__(self, session_factory):
        super().__init__()
        self.session_factory = session_factory
        self.user: User | None = None
        self.setWindowTitle("OilMart POS — Sign in")
        self.setMinimumWidth(400)
        layout = QVBoxLayout(self)
        title = QLabel("OilMart POS")
        title.setFont(QFont("Segoe UI", 22, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle = QLabel("Sign in to start billing")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        form = QFormLayout()
        self.username = QLineEdit("admin")
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setPlaceholderText("Password")
        self.password.returnPressed.connect(self.authenticate)
        form.addRow("Username", self.username)
        form.addRow("Password", self.password)
        layout.addLayout(form)
        self.error = QLabel("")
        self.error.setStyleSheet("color: #ef4444")
        layout.addWidget(self.error)
        button = QPushButton("Sign in")
        button.setDefault(True)
        button.clicked.connect(self.authenticate)
        layout.addWidget(button)

    def authenticate(self):
        with self.session_factory() as session:
            user = session.scalar(select(User).where(User.username == self.username.text().strip()))
            if not user or not user.active or not verify_password(self.password.text(), user.password_hash):
                self.error.setText("Invalid username or password")
                self.password.selectAll()
                return
            session.expunge(user)
            self.user = user
        self.accept()


class PaymentDialog(QDialog):
    def __init__(self, total_cents: int, parent=None):
        super().__init__(parent)
        self.total_cents = total_cents
        self.setWindowTitle("Complete payment")
        form = QFormLayout(self)
        total = QLabel(money(total_cents))
        total.setFont(QFont("Segoe UI", 18, QFont.Weight.Bold))
        self.method = QComboBox()
        self.method.addItems(["Cash", "Card", "Credit"])
        self.paid = QLineEdit(f"{total_cents / 100:.2f}")
        self.method.currentTextChanged.connect(self._method_changed)
        form.addRow("Total", total)
        form.addRow("Method", self.method)
        form.addRow("Amount received", self.paid)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self._validate)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _method_changed(self, method: str):
        self.paid.setEnabled(method == "Cash")
        if method != "Cash":
            self.paid.setText(f"{self.total_cents / 100:.2f}")

    def _validate(self):
        try:
            paid = int(round(float(self.paid.text()) * 100))
        except ValueError:
            QMessageBox.warning(self, "Invalid amount", "Enter a valid payment amount.")
            return
        if self.method.currentText() != "Credit" and paid < self.total_cents:
            QMessageBox.warning(self, "Insufficient payment", "Amount received is less than the total.")
            return
        self.accept()

    @property
    def result_data(self) -> tuple[str, int]:
        return self.method.currentText().lower(), int(round(float(self.paid.text()) * 100))


@dataclass
class CartEntry:
    product: Product
    quantity: int = 1


class PosWindow(QMainWindow):
    def __init__(self, session_factory, user: User):
        super().__init__()
        self.session_factory = session_factory
        self.user = user
        self.cart: dict[int, CartEntry] = {}
        self.setWindowTitle(f"OilMart POS — {user.display_name}")
        self.resize(1200, 760)
        self._build_ui()
        self.search_products()

    def _build_ui(self):
        central = QWidget()
        root = QVBoxLayout(central)
        header = QHBoxLayout()
        title = QLabel("OilMart POS")
        title.setFont(QFont("Segoe UI", 20, QFont.Weight.Bold))
        header.addWidget(title)
        header.addStretch()
        header.addWidget(QLabel(f"Cashier: {self.user.display_name}"))
        root.addLayout(header)

        body = QHBoxLayout()
        left = QVBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Scan barcode or search product name…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.search_products)
        self.search.returnPressed.connect(self.add_first_result)
        left.addWidget(self.search)
        self.products = QTableWidget(0, 4)
        self.products.setHorizontalHeaderLabels(["Product", "Barcode", "Price", "Stock"])
        self.products.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.products.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.products.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.products.doubleClicked.connect(self.add_selected_product)
        left.addWidget(self.products)
        add = QPushButton("Add selected product")
        add.clicked.connect(self.add_selected_product)
        left.addWidget(add)

        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.VLine)
        right = QVBoxLayout()
        cart_title = QLabel("Current sale")
        cart_title.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
        right.addWidget(cart_title)
        self.cart_table = QTableWidget(0, 4)
        self.cart_table.setHorizontalHeaderLabels(["Item", "Qty", "Price", "Amount"])
        self.cart_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.cart_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.cart_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        right.addWidget(self.cart_table)
        controls = QHBoxLayout()
        minus = QPushButton("− Qty")
        plus = QPushButton("+ Qty")
        remove = QPushButton("Remove")
        clear = QPushButton("Clear sale")
        minus.clicked.connect(lambda: self.change_quantity(-1))
        plus.clicked.connect(lambda: self.change_quantity(1))
        remove.clicked.connect(self.remove_selected)
        clear.clicked.connect(self.clear_cart)
        for button in (minus, plus, remove, clear):
            controls.addWidget(button)
        right.addLayout(controls)
        self.total = QLabel("Total: Rs. 0.00")
        self.total.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.total.setFont(QFont("Segoe UI", 22, QFont.Weight.Bold))
        right.addWidget(self.total)
        self.checkout_button = QPushButton("PAY / COMPLETE SALE")
        self.checkout_button.setMinimumHeight(52)
        self.checkout_button.setEnabled(False)
        self.checkout_button.clicked.connect(self.complete_sale)
        right.addWidget(self.checkout_button)

        body.addLayout(left, 3)
        body.addWidget(divider)
        body.addLayout(right, 2)
        root.addLayout(body)
        self.setCentralWidget(central)
        self.statusBar().showMessage("Offline mode — ready")
        exit_action = QAction("Exit", self)
        exit_action.triggered.connect(QApplication.instance().quit)
        self.menuBar().addMenu("File").addAction(exit_action)
        self.setStyleSheet("""
            QWidget { font-family: 'Segoe UI'; font-size: 14px; }
            QLineEdit, QComboBox { padding: 9px; }
            QPushButton { padding: 9px 14px; }
            QPushButton:default, QPushButton#checkout { background: #16a34a; color: white; }
            QHeaderView::section { padding: 8px; font-weight: bold; }
        """)
        self.search.setFocus()

    def search_products(self):
        term = self.search.text().strip()
        with self.session_factory() as session:
            query = select(Product).where(Product.active.is_(True))
            if term:
                query = query.where(or_(Product.name.ilike(f"%{term}%"), Product.barcode.ilike(f"%{term}%")))
            rows = session.execute(query.order_by(Product.name).limit(100)).scalars().all()
            for product in rows:
                session.expunge(product)
        self.products.setRowCount(len(rows))
        for row, product in enumerate(rows):
            values = (product.name, product.barcode, money(product.selling_price_cents), str(product.stock_quantity))
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole, product if column == 0 else None)
                self.products.setItem(row, column, item)

    def add_first_result(self):
        if self.products.rowCount():
            self.products.selectRow(0)
            self.add_selected_product()

    def add_selected_product(self):
        row = self.products.currentRow()
        if row < 0:
            return
        product = self.products.item(row, 0).data(Qt.ItemDataRole.UserRole)
        existing = self.cart.get(product.id)
        quantity = (existing.quantity if existing else 0) + 1
        if quantity > product.stock_quantity:
            QMessageBox.warning(self, "Stock unavailable", f"Only {product.stock_quantity} units are available.")
            return
        self.cart[product.id] = CartEntry(product, quantity)
        self.refresh_cart()
        self.search.clear()
        self.search.setFocus()

    def refresh_cart(self):
        entries = list(self.cart.values())
        self.cart_table.setRowCount(len(entries))
        total = 0
        for row, entry in enumerate(entries):
            amount = entry.product.selling_price_cents * entry.quantity
            total += amount
            values = (entry.product.name, str(entry.quantity), money(entry.product.selling_price_cents), money(amount))
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole, entry.product.id if column == 0 else None)
                self.cart_table.setItem(row, column, item)
        self.total.setText(f"Total: {money(total)}")
        self.checkout_button.setEnabled(bool(entries))

    def _selected_cart_id(self) -> int | None:
        row = self.cart_table.currentRow()
        return None if row < 0 else self.cart_table.item(row, 0).data(Qt.ItemDataRole.UserRole)

    def change_quantity(self, delta: int):
        product_id = self._selected_cart_id()
        if product_id is None:
            return
        entry = self.cart[product_id]
        new_quantity = entry.quantity + delta
        if new_quantity <= 0:
            self.cart.pop(product_id)
        elif new_quantity <= entry.product.stock_quantity:
            entry.quantity = new_quantity
        else:
            QMessageBox.warning(self, "Stock unavailable", "Quantity exceeds available stock.")
        self.refresh_cart()

    def remove_selected(self):
        product_id = self._selected_cart_id()
        if product_id is not None:
            self.cart.pop(product_id, None)
            self.refresh_cart()

    def clear_cart(self):
        if self.cart and QMessageBox.question(self, "Clear sale", "Remove all items from this sale?") == QMessageBox.StandardButton.Yes:
            self.cart.clear()
            self.refresh_cart()

    def complete_sale(self):
        total = sum(x.product.selling_price_cents * x.quantity for x in self.cart.values())
        dialog = PaymentDialog(total, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        method, paid = dialog.result_data
        with self.session_factory() as session:
            terminal_id = session.scalar(select(Terminal.id).where(Terminal.branch_id == self.user.branch_id).order_by(Terminal.id))
            try:
                invoice = checkout(session, terminal_id=terminal_id, cashier_id=self.user.id,
                    lines=[CartLine(p, e.quantity) for p, e in self.cart.items()],
                    payment_method=method, paid_cents=paid)
            except CheckoutError as exc:
                QMessageBox.warning(self, "Sale not completed", str(exc))
                self.search_products()
                return
            except Exception as exc:
                QMessageBox.critical(self, "Database error", f"The sale was rolled back.\n\n{exc}")
                return
        change = max(0, paid - invoice.total_cents) if method == "cash" else 0
        QMessageBox.information(self, "Sale completed",
            f"Invoice: {invoice.local_invoice_number}\nTotal: {money(invoice.total_cents)}\nChange: {money(change)}\n\nSaved offline and queued for sync.")
        self.cart.clear()
        self.refresh_cart()
        self.search_products()
        self.statusBar().showMessage(f"Completed {invoice.local_invoice_number}", 8000)

