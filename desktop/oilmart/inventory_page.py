from __future__ import annotations

from sqlalchemy import func, or_, select
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
    QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMessageBox, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from .models import ActivityLog, InventoryMovement, Product, User
from .security import permission_keys


class StockAdjustmentDialog(QDialog):
    def __init__(self, products, mode="outflow", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Record Stock Outflow" if mode == "outflow" else "Adjust Stock")
        self.setMinimumWidth(560)
        self.mode = mode
        form = QFormLayout(self)
        form.setContentsMargins(24, 24, 24, 24)
        form.setHorizontalSpacing(24)
        form.setVerticalSpacing(16)
        self.product = QComboBox()
        for product in products:
            self.product.addItem(f"{product.name}  ·  {product.stock_quantity} available", product.id)
        self.direction = QComboBox()
        self.direction.addItem("Stock out (reduce quantity)", -1)
        self.direction.addItem("Stock in (increase quantity)", 1)
        if mode == "outflow":
            self.direction.setCurrentIndex(0)
        self.quantity = QSpinBox(); self.quantity.setRange(1, 100000000); self.quantity.setValue(1)
        self.reason = QComboBox()
        self.reason.addItems(["Damaged", "Expired", "Internal use", "Stock correction", "Transfer", "Other"])
        self.notes = QLineEdit(); self.notes.setPlaceholderText("Optional reference or explanation")
        form.addRow("Product", self.product)
        form.addRow("Movement", self.direction)
        form.addRow("Quantity", self.quantity)
        form.addRow("Reason", self.reason)
        form.addRow("Notes", self.notes)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Save)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Save movement")
        buttons.rejected.connect(self.reject); buttons.accepted.connect(self.accept)
        form.addRow(buttons)


class InventoryPage(QWidget):
    def __init__(self, session_factory, user: User, parent=None):
        super().__init__(parent)
        self.session_factory = session_factory; self.user = user
        with session_factory() as session:
            self.permissions = permission_keys(session, user)
        root = QVBoxLayout(self); root.setContentsMargins(20, 16, 20, 18); root.setSpacing(14)
        heading = QHBoxLayout()
        title = QLabel("Inventory"); title.setObjectName("title")
        subtitle = QLabel("Track stock levels, inflows, outflows and adjustments"); subtitle.setObjectName("muted")
        heading.addWidget(title); heading.addWidget(subtitle); heading.addStretch()
        self.outflow_button = QPushButton("− Record Outflow"); self.outflow_button.setObjectName("primaryButton")
        self.outflow_button.setEnabled("stock.adjust" in self.permissions)
        self.outflow_button.clicked.connect(lambda: self.adjust("outflow"))
        adjust_button = QPushButton("± Stock Adjustment"); adjust_button.setEnabled("stock.adjust" in self.permissions)
        adjust_button.clicked.connect(lambda: self.adjust("adjustment"))
        heading.addWidget(self.outflow_button); heading.addWidget(adjust_button)
        root.addLayout(heading)

        self.metrics = QGridLayout(); self.metrics.setSpacing(14); root.addLayout(self.metrics)
        filters = QHBoxLayout()
        self.search = QLineEdit(); self.search.setPlaceholderText("Search product or barcode…"); self.search.setMinimumWidth(280)
        self.search.textChanged.connect(self.refresh)
        self.type_filter = QComboBox(); self.type_filter.addItems(["All Movements", "Stock In", "Stock Out"])
        self.type_filter.setMinimumWidth(160); self.type_filter.currentIndexChanged.connect(self.refresh)
        filters.addWidget(self.search, 1); filters.addWidget(self.type_filter); root.addLayout(filters)

        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(["Date & Time", "Product", "Barcode", "Movement", "Quantity", "Balance", "Reason", "Reference"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False); self.table.verticalHeader().setDefaultSectionSize(44)
        header = self.table.horizontalHeader(); header.setMinimumSectionSize(90)
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)
        root.addWidget(self.table, 1)
        self.result = QLabel(); self.result.setObjectName("muted"); root.addWidget(self.result)
        self.refresh()

    def _card(self, title, value, color):
        card = QFrame(); card.setObjectName("card")
        box = QVBoxLayout(card); box.setContentsMargins(18, 14, 18, 14)
        label = QLabel(title); label.setObjectName("metricTitle")
        number = QLabel(value); number.setObjectName("metricValue"); number.setStyleSheet(f"color:{color};")
        box.addWidget(label); box.addWidget(number)
        return card

    def refresh(self):
        with self.session_factory() as session:
            products = session.scalars(select(Product).where(Product.active.is_(True))).all()
            query = select(InventoryMovement, Product).join(Product).order_by(InventoryMovement.created_at.desc())
            term = self.search.text().strip() if hasattr(self, "search") else ""
            if term:
                query = query.where(or_(Product.name.ilike(f"%{term}%"), Product.barcode.ilike(f"%{term}%")))
            movement_filter = self.type_filter.currentText() if hasattr(self, "type_filter") else "All Movements"
            if movement_filter == "Stock In": query = query.where(InventoryMovement.quantity_delta > 0)
            elif movement_filter == "Stock Out": query = query.where(InventoryMovement.quantity_delta < 0)
            rows = session.execute(query.limit(500)).all()
            in_total = session.scalar(select(func.sum(InventoryMovement.quantity_delta)).where(InventoryMovement.quantity_delta > 0)) or 0
            out_total = -(session.scalar(select(func.sum(InventoryMovement.quantity_delta)).where(InventoryMovement.quantity_delta < 0)) or 0)
        while self.metrics.count():
            item = self.metrics.takeAt(0)
            if item.widget(): item.widget().hide(); item.widget().deleteLater()
        stock = sum(p.stock_quantity for p in products); low = sum(p.stock_quantity <= p.low_stock_threshold for p in products)
        for col, data in enumerate((("Units on Hand", str(stock), "#1671f8"), ("Total Stock In", str(in_total), "#10b981"), ("Total Stock Out", str(out_total), "#ef4444"), ("Low Stock Products", str(low), "#f59e0b"))):
            self.metrics.addWidget(self._card(*data), 0, col)
        balances = {p.id: p.stock_quantity for p in products}
        self.table.setRowCount(len(rows))
        for row, (movement, product) in enumerate(rows):
            direction = "Stock In" if movement.quantity_delta > 0 else "Stock Out"
            reference = f"Sale #{movement.invoice_id}" if movement.invoice_id else (f"Purchase #{movement.purchase_id}" if movement.purchase_id else "Manual")
            values = [movement.created_at.strftime("%d %b %Y  %I:%M %p"), product.name, product.barcode, direction,
                      f"{movement.quantity_delta:+d}", balances.get(product.id, product.stock_quantity), movement.reason.replace("_", " ").title(), reference]
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if column in (3, 4): item.setForeground(Qt.GlobalColor.darkGreen if movement.quantity_delta > 0 else Qt.GlobalColor.red)
                self.table.setItem(row, column, item)
        self.result.setText(f"Showing {len(rows)} movements · latest first")

    def adjust(self, mode):
        with self.session_factory() as session:
            products = session.scalars(select(Product).where(Product.active.is_(True)).order_by(Product.name)).all()
            for product in products: session.expunge(product)
        if not products:
            QMessageBox.information(self, "No products", "Add a product before recording an inventory movement."); return
        dialog = StockAdjustmentDialog(products, mode, self)
        if dialog.exec() != QDialog.DialogCode.Accepted: return
        product_id = dialog.product.currentData(); sign = dialog.direction.currentData(); quantity = dialog.quantity.value()
        with self.session_factory() as session:
            product = session.get(Product, product_id); delta = sign * quantity
            if product.stock_quantity + delta < 0:
                QMessageBox.warning(self, "Insufficient stock", f"Only {product.stock_quantity} units are available."); return
            product.stock_quantity += delta
            reason = dialog.reason.currentText().lower().replace(" ", "_")
            session.add(InventoryMovement(product_id=product.id, quantity_delta=delta, reason=reason))
            detail = f"{product.name}: {delta:+d}; {dialog.notes.text().strip()}".strip("; ")
            session.add(ActivityLog(user_id=self.user.id, action="recorded inventory movement", module="inventory", details=detail))
            session.commit()
        self.refresh()
