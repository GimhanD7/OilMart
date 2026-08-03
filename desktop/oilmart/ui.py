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

MODERN_STYLE = """
QWidget {
    font-family: 'Segoe UI', 'Inter', sans-serif;
    font-size: 14px;
    color: #1f2937;
    background-color: #f9fafb;
}

QMainWindow {
    background-color: #f3f4f6;
}

QDialog {
    background-color: #ffffff;
}

QLabel {
    background: transparent;
}

QLabel#titleLabel {
    font-size: 22px;
    font-weight: bold;
    color: #111827;
}

QLabel#subtitleLabel {
    font-size: 14px;
    color: #6b7280;
}

QLabel#totalLabel {
    font-size: 24px;
    font-weight: bold;
    color: #059669;
}

QLabel#errorLabel {
    color: #ef4444;
    font-size: 13px;
}

QLineEdit, QComboBox, QSpinBox {
    padding: 10px 14px;
    border: 1px solid #d1d5db;
    border-radius: 6px;
    background-color: #ffffff;
    selection-background-color: #3b82f6;
}

QLineEdit:focus, QComboBox:focus, QSpinBox:focus {
    border: 1px solid #3b82f6;
    outline: none;
}

QPushButton {
    padding: 10px 18px;
    background-color: #ffffff;
    border: 1px solid #d1d5db;
    border-radius: 6px;
    color: #374151;
    font-weight: 500;
}

QPushButton:hover {
    background-color: #f3f4f6;
}

QPushButton:pressed {
    background-color: #e5e7eb;
}

QPushButton:default, QPushButton#primaryButton {
    background-color: #10b981;
    border: 1px solid #059669;
    color: white;
}

QPushButton:default:hover, QPushButton#primaryButton:hover {
    background-color: #059669;
}

QPushButton:default:pressed, QPushButton#primaryButton:pressed {
    background-color: #047857;
}

QPushButton:disabled {
    background-color: #e5e7eb;
    border: 1px solid #d1d5db;
    color: #9ca3af;
}

QTableWidget {
    background-color: #ffffff;
    border: 1px solid #e5e7eb;
    border-radius: 6px;
    gridline-color: #f3f4f6;
    selection-background-color: #eff6ff;
    selection-color: #1e3a8a;
    outline: 0;
}

QHeaderView::section {
    background-color: #f9fafb;
    padding: 10px;
    border: none;
    border-bottom: 1px solid #e5e7eb;
    border-right: 1px solid #e5e7eb;
    font-weight: 600;
    color: #4b5563;
}

QScrollBar:vertical {
    border: none;
    background: #f3f4f6;
    width: 10px;
    margin: 0px 0px 0px 0px;
}
QScrollBar::handle:vertical {
    background: #d1d5db;
    min-height: 20px;
    border-radius: 5px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}

QScrollBar:horizontal {
    border: none;
    background: #f3f4f6;
    height: 10px;
    margin: 0px 0px 0px 0px;
}
QScrollBar::handle:horizontal {
    background: #d1d5db;
    min-width: 20px;
    border-radius: 5px;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0px;
}
"""


def money(cents: int) -> str:
    return f"Rs. {cents / 100:,.2f}"


class LoginDialog(QDialog):
    def __init__(self, session_factory):
        super().__init__()
        self.session_factory = session_factory
        self.user: User | None = None
        self.setWindowTitle("OilMart POS — Sign in")
        self.setMinimumWidth(400)
        self.setStyleSheet(MODERN_STYLE)
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(32, 32, 32, 32)
        title = QLabel("OilMart POS")
        title.setObjectName("titleLabel")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle = QLabel("Sign in to start billing")
        subtitle.setObjectName("subtitleLabel")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        form = QFormLayout()
        form.setVerticalSpacing(12)
        self.username = QLineEdit("admin")
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setPlaceholderText("Password")
        self.password.returnPressed.connect(self.authenticate)
        form.addRow("Username", self.username)
        form.addRow("Password", self.password)
        layout.addLayout(form)
        self.error = QLabel("")
        self.error.setObjectName("errorLabel")
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
        self.setStyleSheet(MODERN_STYLE)
        self.setMinimumWidth(400)
        form = QFormLayout(self)
        form.setContentsMargins(24, 24, 24, 24)
        form.setVerticalSpacing(16)
        total = QLabel(money(total_cents))
        total.setObjectName("totalLabel")
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
        self.setStyleSheet(MODERN_STYLE)
        self._build_ui()
        self.search_products()

    def _build_ui(self):
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(20)
        header = QHBoxLayout()
        title = QLabel("OilMart POS")
        title.setObjectName("titleLabel")
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
        divider.setStyleSheet("color: #e5e7eb;")
        right = QVBoxLayout()
        right.setSpacing(12)
        cart_title = QLabel("Current sale")
        cart_title.setObjectName("titleLabel")
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
        self.total.setObjectName("totalLabel")
        right.addWidget(self.total)
        self.checkout_button = QPushButton("PAY / COMPLETE SALE")
        self.checkout_button.setObjectName("primaryButton")
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

