from __future__ import annotations

import csv
from pathlib import Path

from sqlalchemy import func, or_, select
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFileDialog, QFormLayout, QFrame, QGridLayout, QHBoxLayout, QHeaderView,
    QInputDialog, QLabel, QLineEdit, QMessageBox, QPushButton, QSpinBox,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from .models import ActivityLog, Category, InventoryMovement, Product, User
from .security import permission_keys
from .ui import money
from .sync import enqueue_outbox


class StockTrend(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent); self.values = [0]; self.setMinimumHeight(150)
    def set_values(self, values): self.values = values or [0]; self.update()
    def paintEvent(self, event):
        painter = QPainter(self); painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(12, 12, -12, -18)
        painter.setPen(QPen(QColor("#e3e9f2"), 1))
        for i in range(4):
            y = rect.top() + i * rect.height() / 3; painter.drawLine(rect.left(), int(y), rect.right(), int(y))
        minimum, maximum = min(self.values), max(self.values)
        span = max(maximum - minimum, 1); step = rect.width() / max(len(self.values) - 1, 1)
        points = [(int(rect.left() + i * step), int(rect.bottom() - ((value - minimum) / span) * rect.height())) for i, value in enumerate(self.values)]
        painter.setPen(QPen(QColor("#1671f8"), 2))
        for first, second in zip(points, points[1:]): painter.drawLine(*first, *second)
        painter.setBrush(QColor("#1671f8"))
        for x, y in points: painter.drawEllipse(x - 3, y - 3, 6, 6)


class ProductDialog(QDialog):
    def __init__(self, session_factory, product: Product | None = None, parent=None):
        super().__init__(parent)
        self.session_factory = session_factory
        self.product = product
        self.setWindowTitle("Edit Product" if product else "Add Product")
        self.setMinimumWidth(500)
        form = QFormLayout(self)
        self.barcode = QLineEdit(product.barcode if product else "")
        self.name = QLineEdit(product.name if product else "")
        self.category = QComboBox()
        with session_factory() as session:
            categories = session.execute(select(Category.id, Category.name).where(
                Category.active.is_(True)).order_by(Category.name)).all()
        for category_id, name in categories:
            self.category.addItem(name, category_id)
        if product:
            index = self.category.findData(product.category_id)
            if index >= 0: self.category.setCurrentIndex(index)
        self.brand = QLineEdit(product.brand if product else "")
        self.purchase = QDoubleSpinBox(); self.purchase.setMaximum(100000000); self.purchase.setDecimals(2); self.purchase.setPrefix("Rs. ")
        self.selling = QDoubleSpinBox(); self.selling.setMaximum(100000000); self.selling.setDecimals(2); self.selling.setPrefix("Rs. ")
        self.stock = QSpinBox(); self.stock.setMaximum(100000000)
        self.reorder = QSpinBox(); self.reorder.setMaximum(100000000)
        self.image = QLineEdit(product.image_path if product else "")
        browse = QPushButton("Browse image")
        browse.clicked.connect(self.browse_image)
        image_row = QHBoxLayout(); image_row.addWidget(self.image); image_row.addWidget(browse)
        if product:
            self.purchase.setValue(product.purchase_price_cents / 100)
            self.selling.setValue(product.selling_price_cents / 100)
            self.stock.setValue(product.stock_quantity)
            self.reorder.setValue(product.low_stock_threshold)
        form.addRow("Barcode", self.barcode); form.addRow("Product name", self.name)
        form.addRow("Category", self.category); form.addRow("Brand", self.brand)
        form.addRow("Cost price", self.purchase); form.addRow("Selling price", self.selling)
        form.addRow("Current stock", self.stock); form.addRow("Reorder level", self.reorder)
        form.addRow("Product image", image_row)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Save)
        buttons.rejected.connect(self.reject); buttons.accepted.connect(self.validate)
        form.addRow(buttons)

    def browse_image(self):
        path, _ = QFileDialog.getOpenFileName(self, "Product image", "", "Images (*.png *.jpg *.jpeg *.webp)")
        if path: self.image.setText(path)

    def validate(self):
        if not self.barcode.text().strip() or not self.name.text().strip():
            QMessageBox.warning(self, "Required", "Barcode and product name are required."); return
        if self.selling.value() <= 0:
            QMessageBox.warning(self, "Invalid price", "Selling price must be greater than zero."); return
        self.accept()

    @property
    def values(self):
        return dict(barcode=self.barcode.text().strip(), name=self.name.text().strip(),
                    category_id=self.category.currentData(), brand=self.brand.text().strip(),
                    purchase_price_cents=int(round(self.purchase.value() * 100)),
                    selling_price_cents=int(round(self.selling.value() * 100)),
                    stock_quantity=self.stock.value(), low_stock_threshold=self.reorder.value(),
                    image_path=self.image.text().strip())


class ProductsPage(QWidget):
    def __init__(self, session_factory, user: User, parent=None):
        super().__init__(parent)
        self.session_factory = session_factory; self.user = user; self.selected_id = None
        with session_factory() as session: self.permissions = permission_keys(session, user)
        root = QVBoxLayout(self); root.setContentsMargins(20, 16, 20, 18); root.setSpacing(14)
        heading = QHBoxLayout(); title = QLabel("Products"); title.setObjectName("title")
        heading.addWidget(title); subtitle = QLabel("Manage inventory items and pricing"); subtitle.setObjectName("muted"); heading.addWidget(subtitle); heading.addStretch()
        root.addLayout(heading)
        self.metrics = QGridLayout(); root.addLayout(self.metrics)
        body = QHBoxLayout(); body.setSpacing(14)
        main = QVBoxLayout(); filters = QGridLayout(); filters.setHorizontalSpacing(10); filters.setVerticalSpacing(10)
        self.search = QLineEdit(); self.search.setPlaceholderText("Scan barcode or search product..."); self.search.textChanged.connect(self.refresh)
        self.category = QComboBox(); self.category.currentIndexChanged.connect(self.refresh)
        self.stock_status = QComboBox(); self.stock_status.addItems(["All Stock Status", "In Stock", "Low Stock", "Out of Stock"]); self.stock_status.currentIndexChanged.connect(self.refresh)
        self.brand = QComboBox(); self.brand.currentIndexChanged.connect(self.refresh)
        self.search.setMinimumWidth(300)
        for control in (self.category, self.stock_status, self.brand): control.setMinimumWidth(150)
        filters.addWidget(self.search, 0, 0, 1, 6)
        filters.addWidget(self.category, 1, 0, 1, 2); filters.addWidget(self.stock_status, 1, 2, 1, 2); filters.addWidget(self.brand, 1, 4, 1, 2)
        add = QPushButton("+ Add Product"); add.setObjectName("primaryButton"); add.clicked.connect(self.add_product); add.setEnabled("product.add" in self.permissions)
        categories = QPushButton("Categories"); categories.clicked.connect(self.add_category)
        import_button = QPushButton("Import"); import_button.clicked.connect(self.import_csv)
        export_button = QPushButton("Export"); export_button.clicked.connect(self.export_csv)
        categories.setEnabled("product.add" in self.permissions)
        import_button.setEnabled("product.add" in self.permissions)
        filters.addWidget(add, 2, 0); filters.addWidget(categories, 2, 1); filters.addWidget(import_button, 2, 2); filters.addWidget(export_button, 2, 3)
        filters.setColumnStretch(0, 1); filters.setColumnStretch(1, 1); filters.setColumnStretch(2, 1); filters.setColumnStretch(3, 1)
        main.addLayout(filters)
        self.table = QTableWidget(0, 10)
        self.table.setHorizontalHeaderLabels(["#", "Product", "Barcode", "Category", "Brand", "Cost Price", "Selling Price", "Stock", "Status", "Actions"])
        header=self.table.horizontalHeader(); header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch); header.setMinimumSectionSize(42)
        for column,width in {0:38,2:92,3:86,4:72,5:92,6:100,7:60,8:82,9:178}.items(): self.table.setColumnWidth(column,width)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(56)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self.selection_changed)
        main.addWidget(self.table)
        self.result_label = QLabel(); main.addWidget(self.result_label)
        body.addLayout(main, 5)
        preview = QFrame(); preview.setObjectName("panel"); preview.setFixedWidth(300); preview_box = QVBoxLayout(preview)
        preview_box.addWidget(QLabel("Product Preview"))
        self.preview_image = QLabel("OIL"); self.preview_image.setAlignment(Qt.AlignmentFlag.AlignCenter); self.preview_image.setFixedHeight(120)
        self.preview_image.setStyleSheet("font-size: 30px; font-weight: 900; color: #126ff5; background:#eef5ff; border-radius:10px;")
        self.preview_name = QLabel("Select a product"); self.preview_name.setMinimumHeight(30); self.preview_name.setStyleSheet("font-size:18px;font-weight:800;color:#0f172a;background:white;")
        self.preview_details = QFrame(); self.preview_details.setStyleSheet("background:white;")
        details_box = QVBoxLayout(self.preview_details); details_box.setContentsMargins(0, 0, 0, 0); details_box.setSpacing(3)
        self.preview_fields = {}
        for key in ("Barcode", "Category", "Brand", "Cost Price", "Selling Price", "Current Stock", "Reorder Level", "Stock Movements"):
            label = QLabel(f"{key}: -"); label.setFixedHeight(20); label.setStyleSheet("color:#334155;background:white;")
            self.preview_fields[key] = label; details_box.addWidget(label)
        self.preview_details.setFixedHeight(181)
        self.edit_button = QPushButton("Edit Product"); self.edit_button.clicked.connect(self.edit_product)
        self.duplicate_button = QPushButton("Duplicate Product"); self.duplicate_button.clicked.connect(self.duplicate_product)
        for widget in (self.preview_image, self.preview_name, self.preview_details, self.edit_button, self.duplicate_button): preview_box.addWidget(widget)
        preview_box.addWidget(QLabel("Stock Trend"))
        self.stock_trend = StockTrend(); self.stock_trend.setFixedHeight(80); preview_box.addWidget(self.stock_trend)
        self.edit_button.setEnabled("product.edit" in self.permissions)
        self.duplicate_button.setEnabled("product.add" in self.permissions)
        preview_box.addStretch(); body.addWidget(preview, 1, Qt.AlignmentFlag.AlignTop)
        root.addLayout(body, 1)
        self.reload_filters(); self.refresh()

    def metric_card(self, title, value, color, pale_color="#f8fafc"):
        frame = QFrame(); frame.setObjectName("card"); box = QHBoxLayout(frame); box.setContentsMargins(16, 16, 16, 16); box.setSpacing(12)
        icon_box = QFrame(); icon_box.setFixedSize(48, 48); icon_box.setStyleSheet(f"background: {pale_color}; border-radius: 12px;")
        icon_layout = QVBoxLayout(icon_box); icon_layout.setContentsMargins(0, 0, 0, 0)
        icon = QLabel("●"); icon.setStyleSheet(f"color:{color};font-size:24px"); icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_layout.addWidget(icon); box.addWidget(icon_box)
        text = QVBoxLayout(); text.setSpacing(4)
        metric_title = QLabel(title); metric_title.setObjectName("metricTitle"); text.addWidget(metric_title)
        val = QLabel(value); val.setObjectName("metricValue")
        val.setStyleSheet("font-size: 20px; font-weight: 800; color: #0f172a;")
        text.addWidget(val)
        box.addLayout(text, 1)
        return frame

    def reload_filters(self):
        with self.session_factory() as session:
            categories = session.execute(select(Category.id, Category.name).where(Category.active.is_(True)).order_by(Category.name)).all()
            brands = session.scalars(select(Product.brand).where(Product.brand != "").distinct().order_by(Product.brand)).all()
        self.category.blockSignals(True); self.category.clear(); self.category.addItem("All Categories", None)
        for category_id, name in categories: self.category.addItem(name, category_id)
        self.category.blockSignals(False); self.brand.blockSignals(True); self.brand.clear(); self.brand.addItem("All Brands", None)
        for brand in brands: self.brand.addItem(brand, brand)
        self.brand.blockSignals(False)

    def refresh_from_database(self):
        self.reload_filters()
        self.refresh()
        self.result_label.setText(f"{self.result_label.text()} — refreshed from database")

    def refresh(self):
        if not hasattr(self, "table"): return
        with self.session_factory() as session:
            query = select(Product, Category.name).outerjoin(Category).where(Product.active.is_(True))
            term = self.search.text().strip()
            if term: query = query.where(or_(Product.name.ilike(f"%{term}%"), Product.barcode.ilike(f"%{term}%")))
            if self.category.currentData(): query = query.where(Product.category_id == self.category.currentData())
            if self.brand.currentData(): query = query.where(Product.brand == self.brand.currentData())
            status = self.stock_status.currentText()
            if status == "In Stock": query = query.where(Product.stock_quantity > Product.low_stock_threshold)
            elif status == "Low Stock": query = query.where(Product.stock_quantity > 0, Product.stock_quantity <= Product.low_stock_threshold)
            elif status == "Out of Stock": query = query.where(Product.stock_quantity <= 0)
            rows = session.execute(query.order_by(Product.name)).all()
            total = session.scalar(select(func.count(Product.id)).where(Product.active.is_(True))) or 0
            category_count = session.scalar(select(func.count(Category.id)).where(Category.active.is_(True))) or 0
            low = session.scalar(select(func.count(Product.id)).where(Product.active.is_(True), Product.stock_quantity <= Product.low_stock_threshold)) or 0
            value = session.scalar(select(func.sum(Product.purchase_price_cents * Product.stock_quantity)).where(Product.active.is_(True))) or 0
        while self.metrics.count():
            item = self.metrics.takeAt(0)
            if item.widget(): item.widget().hide(); item.widget().deleteLater()
        for column, metric in enumerate((("Total Products", str(total), "#1671f8", "#eff6ff"), ("Categories", str(category_count), "#10b981", "#ecfdf5"),
                                         ("Low Stock Items", str(low), "#f59e0b", "#fffbeb"), ("Inventory Value", money(value), "#ef4444", "#fef2f2"))):
            self.metrics.addWidget(self.metric_card(*metric), 0, column)
        self.table.setRowCount(len(rows))
        for row_number, (product, category_name) in enumerate(rows):
            status_text = "Out of Stock" if product.stock_quantity <= 0 else ("Low Stock" if product.stock_quantity <= product.low_stock_threshold else "In Stock")
            values = [row_number + 1, product.name, product.barcode, category_name or "Uncategorized", product.brand or "-",
                      money(product.purchase_price_cents), money(product.selling_price_cents), product.stock_quantity, status_text]
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value)); item.setData(Qt.ItemDataRole.UserRole, product.id if column == 1 else None)
                if column == 8:
                    if value == "In Stock": item.setForeground(QColor("#10b981"))
                    elif value == "Low Stock": item.setForeground(QColor("#f59e0b"))
                    elif value == "Out of Stock": item.setForeground(QColor("#ef4444"))
                self.table.setItem(row_number, column, item)
            actions = QWidget(); action_row = QHBoxLayout(actions); action_row.setContentsMargins(0, 0, 0, 0)

            for text, callback in (("View", self.view_row), ("Edit", self.edit_row), ("Delete", self.delete_row)):
                button = QPushButton(text)
                button.setFixedSize(54,32); button.setStyleSheet("padding: 2px 4px;")
                required = {"Edit": "product.edit", "Delete": "product.delete"}.get(text)
                if required: button.setEnabled(required in self.permissions)
                button.clicked.connect(lambda _checked=False, pid=product.id, fn=callback: fn(pid)); action_row.addWidget(button)
            self.table.setCellWidget(row_number, 9, actions)
            self.table.setRowHeight(row_number, 56)
        self.result_label.setText(f"Showing {len(rows)} of {total} products")

    def selected_product_id(self):
        row = self.table.currentRow(); return None if row < 0 else self.table.item(row, 1).data(Qt.ItemDataRole.UserRole)

    def selection_changed(self):
        product_id = self.selected_product_id()
        if product_id: self.view_row(product_id)

    def view_row(self, product_id):
        self.selected_id = product_id
        with self.session_factory() as session:
            product = session.get(Product, product_id); category = session.get(Category, product.category_id) if product.category_id else None
            movement_rows = session.scalars(select(InventoryMovement.quantity_delta).where(
                InventoryMovement.product_id == product_id).order_by(InventoryMovement.created_at).limit(30)).all()
        self.preview_name.setText(product.name)
        detail_values = {
            "Barcode": product.barcode,
            "Category": category.name if category else "Uncategorized",
            "Brand": product.brand or "-",
            "Cost Price": money(product.purchase_price_cents),
            "Selling Price": money(product.selling_price_cents),
            "Current Stock": f"{product.stock_quantity} Units",
            "Reorder Level": f"{product.low_stock_threshold} Units",
            "Stock Movements": str(len(movement_rows)),
        }
        for key, value in detail_values.items(): self.preview_fields[key].setText(f"{key}: {value}")
        running = max(0, product.stock_quantity - sum(movement_rows)); trend = [running]
        for delta in movement_rows: running += delta; trend.append(running)
        self.stock_trend.set_values(trend)
        if product.image_path and Path(product.image_path).is_file(): self.preview_image.setPixmap(QPixmap(product.image_path).scaled(160, 150, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        else: self.preview_image.setText("OIL")

    def save_dialog(self, product=None):
        dialog = ProductDialog(self.session_factory, product, self)
        if dialog.exec() != QDialog.DialogCode.Accepted: return
        with self.session_factory() as session:
            target = session.get(Product, product.id) if product else Product()
            previous_stock = target.stock_quantity if product else 0
            for key, value in dialog.values.items(): setattr(target, key, value)
            session.add(target)
            try:
                session.flush()
                stock_delta = target.stock_quantity - previous_stock
                if stock_delta:
                    session.add(InventoryMovement(product_id=target.id, quantity_delta=stock_delta,
                                                  reason="opening_stock" if not product else "adjustment"))
                enqueue_outbox(session, "product", target.uuid, {"uuid": target.uuid, "barcode": target.barcode,
                    "name": target.name, "category_id": target.category_id, "brand": target.brand,
                    "purchase_price_cents": target.purchase_price_cents, "selling_price_cents": target.selling_price_cents,
                    "stock_quantity": target.stock_quantity, "low_stock_threshold": target.low_stock_threshold,
                    "active": target.active})
                session.add(ActivityLog(user_id=self.user.id, action="updated product" if product else "created product", module="products", details=target.name)); session.commit()
            except Exception:
                session.rollback(); QMessageBox.warning(self, "Cannot save", "Barcode must be unique."); return
        self.reload_filters(); self.refresh()

    def add_product(self): self.save_dialog()
    def edit_product(self):
        if self.selected_id: self.edit_row(self.selected_id)
    def edit_row(self, product_id):
        with self.session_factory() as session:
            product = session.get(Product, product_id); session.expunge(product)
        self.save_dialog(product)
    def duplicate_product(self):
        if self.selected_id: self.copy_row(self.selected_id)
    def copy_row(self, product_id):
        with self.session_factory() as session:
            original = session.get(Product, product_id)
            copy = Product(barcode=f"{original.barcode}-COPY", name=f"{original.name} Copy", category_id=original.category_id, brand=original.brand,
                           purchase_price_cents=original.purchase_price_cents, selling_price_cents=original.selling_price_cents,
                           stock_quantity=0, low_stock_threshold=original.low_stock_threshold, image_path=original.image_path)
            session.add(copy); session.flush()
            enqueue_outbox(session, "product", copy.uuid, {"uuid":copy.uuid,"barcode":copy.barcode,"name":copy.name,
                "category_id":copy.category_id,"brand":copy.brand,"purchase_price_cents":copy.purchase_price_cents,
                "selling_price_cents":copy.selling_price_cents,"stock_quantity":0,"active":True})
            session.add(ActivityLog(user_id=self.user.id, action="duplicated product", module="products", details=original.name)); session.commit()
        self.refresh()
    def delete_row(self, product_id):
        if QMessageBox.question(self, "Disable product", "Remove this product from active sales?") != QMessageBox.StandardButton.Yes: return
        with self.session_factory() as session:
            product = session.get(Product, product_id); product.active = False
            enqueue_outbox(session, "product", product.uuid, {"uuid": product.uuid, "barcode": product.barcode,
                "name": product.name, "active": False, "stock_quantity": product.stock_quantity})
            session.add(ActivityLog(user_id=self.user.id, action="disabled product", module="products", details=product.name)); session.commit()
        self.refresh()
    def add_category(self):
        name, ok = QInputDialog.getText(self, "New category", "Category name:")
        if not ok or not name.strip(): return
        with self.session_factory() as session:
            session.add(Category(name=name.strip()))
            try: session.commit()
            except Exception: session.rollback(); QMessageBox.warning(self, "Duplicate", "Category already exists."); return
        self.reload_filters(); self.refresh()
    def export_csv(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export Products", "products.csv", "CSV (*.csv)")
        if not path: return
        with self.session_factory() as session: rows = session.execute(select(Product, Category.name).outerjoin(Category).order_by(Product.name)).all()
        with open(path, "w", newline="", encoding="utf-8-sig") as file:
            writer = csv.writer(file); writer.writerow(["barcode", "name", "category", "brand", "cost_cents", "selling_cents", "stock", "reorder_level"])
            for p, category in rows: writer.writerow([p.barcode, p.name, category or "", p.brand, p.purchase_price_cents, p.selling_price_cents, p.stock_quantity, p.low_stock_threshold])
        QMessageBox.information(self, "Exported", f"Products exported to {path}")
    def import_csv(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import Products", "", "CSV (*.csv)")
        if not path: return
        imported = 0
        with open(path, newline="", encoding="utf-8-sig") as file, self.session_factory() as session:
            for row in csv.DictReader(file):
                if session.scalar(select(Product.id).where(Product.barcode == row["barcode"])): continue
                category = session.scalar(select(Category).where(Category.name == row.get("category", "")))
                product=Product(barcode=row["barcode"], name=row["name"], category_id=category.id if category else None,
                    brand=row.get("brand", ""), purchase_price_cents=int(row.get("cost_cents", 0)), selling_price_cents=int(row.get("selling_cents", 0)),
                    stock_quantity=int(row.get("stock", 0)), low_stock_threshold=int(row.get("reorder_level", 5)))
                session.add(product); session.flush(); enqueue_outbox(session,"product",product.uuid,{"uuid":product.uuid,
                    "barcode":product.barcode,"name":product.name,"category_id":product.category_id,"brand":product.brand,
                    "purchase_price_cents":product.purchase_price_cents,"selling_price_cents":product.selling_price_cents,
                    "stock_quantity":product.stock_quantity,"low_stock_threshold":product.low_stock_threshold,"active":True}); imported += 1
            session.add(ActivityLog(user_id=self.user.id, action="imported products", module="products", details=str(imported))); session.commit()
        self.reload_filters(); self.refresh(); QMessageBox.information(self, "Imported", f"Imported {imported} products.")
