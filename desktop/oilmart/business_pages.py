from __future__ import annotations

import csv
from datetime import datetime, timezone

from sqlalchemy import func, or_, select
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QFrame,
    QGridLayout, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit,
    QFileDialog, QMessageBox, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from .models import ActivityLog, Customer, Invoice, Product, Purchase, PurchaseItem, Supplier, User
from .security import permission_keys
from .services import PurchaseLine, create_purchase
from .ui import money


def named(widget, object_name):
    widget.setObjectName(object_name)
    return widget


class PartnerDialog(QDialog):
    def __init__(self, kind, partner=None, parent=None):
        super().__init__(parent); self.kind = kind; self.setWindowTitle(f"{'Edit' if partner else 'Add'} {kind.title()}")
        form = QFormLayout(self); self.name = QLineEdit(partner.name if partner else ""); self.phone = QLineEdit(partner.phone if partner else ""); self.email = QLineEdit(partner.email if partner else ""); self.address = QLineEdit(partner.address if partner else "")
        self.group = QLineEdit((partner.customer_group if kind == "customer" else partner.category) if partner else ("Retail" if kind == "customer" else "General"))
        self.notes = QLineEdit(partner.notes if partner else "")
        for label, widget in (("Name", self.name), ("Group" if kind == "customer" else "Category", self.group), ("Phone", self.phone), ("Email", self.email), ("Address", self.address), ("Notes", self.notes)): form.addRow(label, widget)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Save); buttons.rejected.connect(self.reject); buttons.accepted.connect(self.validate); form.addRow(buttons)
    def validate(self):
        if not self.name.text().strip(): QMessageBox.warning(self, "Required", "Name is required."); return
        self.accept()
    @property
    def values(self): return dict(name=self.name.text().strip(), phone=self.phone.text().strip(), email=self.email.text().strip(), address=self.address.text().strip(), notes=self.notes.text().strip(), **({"customer_group": self.group.text().strip()} if self.kind == "customer" else {"category": self.group.text().strip()}))


class PartnerDetailsDialog(QDialog):
    def __init__(self, session_factory, kind, partner_id, parent=None):
        super().__init__(parent); self.resize(1000, 650); self.setWindowTitle(f"{kind.title()} Details")
        layout = QVBoxLayout(self)
        with session_factory() as session:
            if kind == "customer":
                partner = session.get(Customer, partner_id); transactions = session.scalars(select(Invoice).where(Invoice.customer_id == partner_id).order_by(Invoice.created_at.desc())).all()
                total = sum(i.total_cents for i in transactions); paid = sum(i.total_cents for i in transactions if i.status == "paid"); outstanding = partner.credit_balance_cents
                rows = [[i.local_invoice_number, i.created_at.strftime("%Y-%m-%d"), money(i.total_cents), i.status.title()] for i in transactions]
                group = partner.customer_group
            else:
                partner = session.get(Supplier, partner_id); transactions = session.scalars(select(Purchase).where(Purchase.supplier_id == partner_id).order_by(Purchase.purchased_at.desc())).all()
                total = sum(p.total_cents for p in transactions); paid = sum(p.paid_cents for p in transactions); outstanding = total - paid
                rows = [[p.invoice_number, p.purchased_at.strftime("%Y-%m-%d"), money(p.total_cents), p.status.title()] for p in transactions]
                group = partner.category
        heading = QHBoxLayout(); avatar = QLabel("".join(word[0] for word in partner.name.split()[:2]).upper()); avatar.setStyleSheet("font-size:28px;font-weight:800;background:#eaf3ff;border-radius:30px;padding:15px"); heading.addWidget(avatar); heading.addWidget(QLabel(f"{partner.name}\n{group}\n{partner.phone}\n{partner.email}\n{partner.address}")); heading.addStretch(); layout.addLayout(heading)
        metrics = QGridLayout()
        for column, (title, value) in enumerate((("Total Purchases" if kind == "supplier" else "Total Sales", money(total)), ("Total Paid", money(paid)), ("Outstanding", money(outstanding)), ("Total Invoices", str(len(transactions))))):
            card = named(QFrame(), "card"); box = QVBoxLayout(card); box.addWidget(named(QLabel(title), "metricTitle")); box.addWidget(named(QLabel(value), "metricValue")); metrics.addWidget(card, 0, column)
        layout.addLayout(metrics); layout.addWidget(QLabel("Recent Invoices"))
        table = QTableWidget(len(rows), 4); table.setHorizontalHeaderLabels(["Invoice No", "Date", "Total Amount", "Status"]); table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for r, values in enumerate(rows):
            for c, value in enumerate(values): table.setItem(r, c, QTableWidgetItem(str(value)))
        layout.addWidget(table); close = QPushButton("Close"); close.clicked.connect(self.accept); layout.addWidget(close)


class DirectoryPage(QWidget):
    def __init__(self, session_factory, user, kind, parent=None):
        super().__init__(parent); self.session_factory = session_factory; self.user = user; self.kind = kind; self.Model = Customer if kind == "customer" else Supplier
        with session_factory() as session: self.permissions = permission_keys(session, user)
        root = QVBoxLayout(self); root.setContentsMargins(20, 16, 20, 18); root.setSpacing(14)
        heading = QHBoxLayout(); heading.addWidget(named(QLabel(f"{kind.title()}s"), "title")); heading.addWidget(named(QLabel(f"Manage {kind} accounts and balances"), "muted")); heading.addStretch(); add = QPushButton(f"+ Add {kind.title()}"); add.setObjectName("primaryButton"); add.clicked.connect(self.add_partner); import_button = QPushButton("Import"); import_button.clicked.connect(self.import_csv); export_button = QPushButton("Export"); export_button.clicked.connect(self.export_csv); heading.addWidget(add); heading.addWidget(import_button); heading.addWidget(export_button); root.addLayout(heading)
        self.metrics = QGridLayout(); root.addLayout(self.metrics); filters = QHBoxLayout(); self.search = QLineEdit(); self.search.setPlaceholderText(f"Search {kind} by name, phone or email..."); self.search.textChanged.connect(self.refresh); self.group = QComboBox(); self.group.currentIndexChanged.connect(self.refresh); self.status = QComboBox(); self.status.addItems(["All Status", "Active", "Disabled"]); self.status.currentIndexChanged.connect(self.refresh); filters.addWidget(self.search, 1); filters.addWidget(self.group); filters.addWidget(self.status); root.addLayout(filters)
        self.table = QTableWidget(0, 8); self.table.setHorizontalHeaderLabels(["#", kind.title(), "Group" if kind == "customer" else "Category", "Phone", "Email", "Outstanding", "Status", "Actions"]); self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch); root.addWidget(self.table, 1); self.result = QLabel(); root.addWidget(self.result); self.reload_groups(); self.refresh()
    def reload_groups(self):
        field = Customer.customer_group if self.kind == "customer" else Supplier.category
        with self.session_factory() as session: groups = session.scalars(select(field).distinct().order_by(field)).all()
        self.group.blockSignals(True); self.group.clear(); self.group.addItem("All Groups" if self.kind == "customer" else "All Categories", None)
        for group in groups: self.group.addItem(group, group)
        self.group.blockSignals(False)
    def refresh(self):
        if not hasattr(self, "table"): return
        with self.session_factory() as session:
            query = select(self.Model); term = self.search.text().strip()
            if term: query = query.where(or_(self.Model.name.ilike(f"%{term}%"), self.Model.phone.ilike(f"%{term}%"), self.Model.email.ilike(f"%{term}%")))
            field = Customer.customer_group if self.kind == "customer" else Supplier.category
            if self.group.currentData(): query = query.where(field == self.group.currentData())
            if self.status.currentIndex() > 0: query = query.where(self.Model.active.is_(self.status.currentText() == "Active"))
            partners = session.scalars(query.order_by(self.Model.name)).all()
            if self.kind == "customer":
                balances = {p.id: p.credit_balance_cents for p in partners}; total_received = session.scalar(select(func.sum(Invoice.total_cents)).where(Invoice.status == "paid")) or 0
            else:
                balances = {p.id: (session.scalar(select(func.sum(Purchase.total_cents - Purchase.paid_cents)).where(Purchase.supplier_id == p.id)) or 0) for p in partners}; total_received = session.scalar(select(func.sum(Purchase.paid_cents))) or 0
        active = sum(p.active for p in partners); credit = sum(balances[p.id] > 0 for p in partners)
        while self.metrics.count():
            item = self.metrics.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        for col, (title, value, color) in enumerate(((f"Total {self.kind.title()}s", str(len(partners)), "#1671f8"), ("Active", str(active), "#10ad68"), ("Credit Accounts", str(credit), "#f28a16"), ("Total Paid", money(total_received), "#7b4af5"))):
            card = named(QFrame(), "card"); box = QVBoxLayout(card); dot = QLabel("●"); dot.setStyleSheet(f"color:{color};font-size:20px"); box.addWidget(dot); box.addWidget(named(QLabel(title), "metricTitle")); box.addWidget(named(QLabel(value), "metricValue")); self.metrics.addWidget(card, 0, col)
        self.table.setRowCount(len(partners))
        for r, partner in enumerate(partners):
            group = partner.customer_group if self.kind == "customer" else partner.category; values = [r + 1, partner.name, group, partner.phone, partner.email, money(balances[partner.id]), "Active" if partner.active else "Disabled"]
            for c, value in enumerate(values): item = QTableWidgetItem(str(value)); item.setData(Qt.ItemDataRole.UserRole, partner.id if c == 1 else None); self.table.setItem(r, c, item)
            actions = QWidget(); action = QHBoxLayout(actions); action.setContentsMargins(0, 0, 0, 0); view = QPushButton("View"); view.clicked.connect(lambda _=False, pid=partner.id: self.view(pid)); edit = QPushButton("Edit"); edit.clicked.connect(lambda _=False, pid=partner.id: self.edit(pid)); action.addWidget(view); action.addWidget(edit); self.table.setCellWidget(r, 7, actions)
        self.result.setText(f"Showing {len(partners)} {self.kind}s")
    def add_partner(self): self.save()
    def edit(self, partner_id):
        with self.session_factory() as session: partner = session.get(self.Model, partner_id); session.expunge(partner)
        self.save(partner)
    def save(self, partner=None):
        dialog = PartnerDialog(self.kind, partner, self)
        if dialog.exec() != QDialog.DialogCode.Accepted: return
        with self.session_factory() as session:
            target = session.get(self.Model, partner.id) if partner else self.Model()
            for key, value in dialog.values.items(): setattr(target, key, value)
            session.add(target)
            try: session.flush(); session.add(ActivityLog(user_id=self.user.id, action=f"{'updated' if partner else 'created'} {self.kind}", module=f"{self.kind}s", details=target.name)); session.commit()
            except Exception: session.rollback(); QMessageBox.warning(self, "Cannot save", "Name must be unique."); return
        self.reload_groups(); self.refresh()
    def view(self, partner_id): PartnerDetailsDialog(self.session_factory, self.kind, partner_id, self).exec()
    def export_csv(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export", f"{self.kind}s.csv", "CSV (*.csv)")
        if not path: return
        with self.session_factory() as session: partners = session.scalars(select(self.Model).order_by(self.Model.name)).all()
        with open(path, "w", newline="", encoding="utf-8-sig") as file:
            writer = csv.writer(file); writer.writerow(["name", "group", "phone", "email", "address", "notes", "active"])
            for p in partners: writer.writerow([p.name, p.customer_group if self.kind == "customer" else p.category, p.phone, p.email, p.address, p.notes, int(p.active)])
    def import_csv(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import", "", "CSV (*.csv)")
        if not path: return
        imported = 0
        with open(path, newline="", encoding="utf-8-sig") as file, self.session_factory() as session:
            for row in csv.DictReader(file):
                if not row.get("name"): continue
                values = dict(name=row["name"], phone=row.get("phone", ""), email=row.get("email", ""), address=row.get("address", ""), notes=row.get("notes", ""), active=row.get("active", "1") != "0")
                values["customer_group" if self.kind == "customer" else "category"] = row.get("group", "Retail" if self.kind == "customer" else "General")
                session.add(self.Model(**values)); imported += 1
            session.add(ActivityLog(user_id=self.user.id, action=f"imported {self.kind}s", module=f"{self.kind}s", details=str(imported)))
            try: session.commit()
            except Exception as exc: session.rollback(); QMessageBox.warning(self, "Import failed", str(exc)); return
        self.reload_groups(); self.refresh(); QMessageBox.information(self, "Imported", f"Imported {imported} {self.kind}s.")


class NewPurchaseDialog(QDialog):
    def __init__(self, session_factory, user, parent=None):
        super().__init__(parent); self.session_factory = session_factory; self.user = user; self.lines = []; self.setWindowTitle("New Purchase"); self.resize(900, 650)
        root = QVBoxLayout(self); form = QFormLayout(); self.supplier = QComboBox()
        with session_factory() as session: suppliers = session.execute(select(Supplier.id, Supplier.name).where(Supplier.active.is_(True)).order_by(Supplier.name)).all()
        for supplier_id, name in suppliers: self.supplier.addItem(name, supplier_id)
        self.reference = QLineEdit(); self.discount = QDoubleSpinBox(); self.discount.setMaximum(100000000); self.tax = QDoubleSpinBox(); self.tax.setMaximum(100000000); self.paid = QDoubleSpinBox(); self.paid.setMaximum(100000000)
        form.addRow("Supplier", self.supplier); form.addRow("Reference", self.reference); form.addRow("Discount (Rs.)", self.discount); form.addRow("Tax (Rs.)", self.tax); form.addRow("Paid (Rs.)", self.paid); root.addLayout(form)
        add = QPushButton("+ Add Item"); add.clicked.connect(self.add_item); root.addWidget(add)
        self.table = QTableWidget(0, 5); self.table.setHorizontalHeaderLabels(["Product", "Qty", "Unit Cost", "Amount", "Remove"]); self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch); root.addWidget(self.table)
        self.summary = QLabel("Total: Rs. 0.00"); self.summary.setAlignment(Qt.AlignmentFlag.AlignRight); self.summary.setObjectName("metricValue"); root.addWidget(self.summary)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Save); buttons.rejected.connect(self.reject); buttons.accepted.connect(self.save); root.addWidget(buttons)
    def add_item(self):
        with self.session_factory() as session: products = session.scalars(select(Product).where(Product.active.is_(True)).order_by(Product.name)).all()
        name, ok = QInputDialog.getItem(self, "Add item", "Product", [p.name for p in products], 0, False)
        if not ok: return
        product = next(p for p in products if p.name == name); qty, ok = QInputDialog.getInt(self, "Add item", "Quantity", 1, 1, 1000000)
        if not ok: return
        cost, ok = QInputDialog.getDouble(self, "Add item", "Unit cost (Rs.)", product.purchase_price_cents / 100, 0, 100000000, 2)
        if not ok: return
        self.lines.append(PurchaseLine(product.id, qty, int(round(cost * 100)))); self.refresh()
    def refresh(self):
        self.table.setRowCount(len(self.lines)); total = 0
        with self.session_factory() as session:
            for r, line in enumerate(self.lines):
                product = session.get(Product, line.product_id); amount = line.quantity * line.unit_cost_cents; total += amount
                for c, value in enumerate((product.name, line.quantity, money(line.unit_cost_cents), money(amount))): self.table.setItem(r, c, QTableWidgetItem(str(value)))
                remove = QPushButton("Remove"); remove.clicked.connect(lambda _=False, row=r: self.remove(row)); self.table.setCellWidget(r, 4, remove)
        total = total - int(self.discount.value() * 100) + int(self.tax.value() * 100); self.summary.setText(f"Total: {money(total)}")
    def remove(self, row): self.lines.pop(row); self.refresh()
    def save(self):
        if not self.lines: QMessageBox.warning(self, "Items required", "Add at least one product."); return
        try:
            with self.session_factory() as session: create_purchase(session, supplier_id=self.supplier.currentData(), user_id=self.user.id, lines=self.lines, paid_cents=int(self.paid.value()*100), discount_cents=int(self.discount.value()*100), tax_cents=int(self.tax.value()*100), reference=self.reference.text())
        except Exception as exc: QMessageBox.warning(self, "Cannot save purchase", str(exc)); return
        self.accept()


class PurchasesPage(QWidget):
    def __init__(self, session_factory, user, parent=None):
        super().__init__(parent); self.session_factory = session_factory; self.user = user
        root = QVBoxLayout(self); root.setContentsMargins(20, 16, 20, 18); heading = QHBoxLayout(); heading.addWidget(named(QLabel("Purchases"), "title")); heading.addWidget(named(QLabel("Manage supplier invoices and incoming stock"), "muted")); heading.addStretch(); add = QPushButton("+ New Purchase"); add.setObjectName("primaryButton"); add.clicked.connect(self.new_purchase); export = QPushButton("Export"); export.clicked.connect(self.export_csv); heading.addWidget(add); heading.addWidget(export); root.addLayout(heading)
        self.metrics = QGridLayout(); root.addLayout(self.metrics); self.search = QLineEdit(); self.search.setPlaceholderText("Search purchase by invoice or supplier..."); self.search.textChanged.connect(self.refresh); root.addWidget(self.search)
        self.table = QTableWidget(0, 8); self.table.setHorizontalHeaderLabels(["#", "Invoice No", "Supplier", "Date", "Items", "Total", "Paid / Due", "Status"]); self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch); root.addWidget(self.table, 1); self.result = QLabel(); root.addWidget(self.result); self.refresh()
    def refresh(self):
        if not hasattr(self, "table"): return
        with self.session_factory() as session:
            query = select(Purchase, Supplier.name, func.count(PurchaseItem.id)).join(Supplier).outerjoin(PurchaseItem).group_by(Purchase.id); term = self.search.text().strip()
            if term: query = query.where(or_(Purchase.invoice_number.ilike(f"%{term}%"), Supplier.name.ilike(f"%{term}%")))
            rows = session.execute(query.order_by(Purchase.purchased_at.desc())).all()
        total = sum(p.total_cents for p,_,_ in rows); paid = sum(p.paid_cents for p,_,_ in rows); due = total-paid
        while self.metrics.count():
            item=self.metrics.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        for c,(title,value) in enumerate((("Total Purchases",money(total)),("Total Paid",money(paid)),("Total Due",money(due)),("Total Invoices",str(len(rows))))): card=named(QFrame(), "card"); box=QVBoxLayout(card); box.addWidget(named(QLabel(title), "metricTitle")); box.addWidget(named(QLabel(value), "metricValue")); self.metrics.addWidget(card,0,c)
        self.table.setRowCount(len(rows))
        for r,(purchase,supplier,count) in enumerate(rows):
            values=[r+1,purchase.invoice_number,supplier,purchase.purchased_at.strftime("%Y-%m-%d"),count,money(purchase.total_cents),f"{money(purchase.paid_cents)} / {money(purchase.total_cents-purchase.paid_cents)}",purchase.status.title()]
            for c,value in enumerate(values): self.table.setItem(r,c,QTableWidgetItem(str(value)))
        self.result.setText(f"Showing {len(rows)} purchases")
    def new_purchase(self):
        dialog=NewPurchaseDialog(self.session_factory,self.user,self)
        if dialog.exec()==QDialog.DialogCode.Accepted: self.refresh()
    def export_csv(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export Purchases", "purchases.csv", "CSV (*.csv)")
        if not path: return
        with self.session_factory() as session: rows = session.execute(select(Purchase, Supplier.name).join(Supplier).order_by(Purchase.purchased_at)).all()
        with open(path, "w", newline="", encoding="utf-8-sig") as file:
            writer = csv.writer(file); writer.writerow(["invoice", "supplier", "date", "total_cents", "paid_cents", "due_cents", "status", "reference"])
            for purchase, supplier in rows: writer.writerow([purchase.invoice_number, supplier, purchase.purchased_at.isoformat(), purchase.total_cents, purchase.paid_cents, purchase.total_cents-purchase.paid_cents, purchase.status, purchase.reference])
