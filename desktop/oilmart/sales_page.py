from __future__ import annotations

import csv
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_, select
from PyQt6.QtCore import QDate, Qt
from PyQt6.QtGui import QColor, QPainter, QPen, QTextDocument
from PyQt6.QtPrintSupport import QPrintDialog, QPrinter
from PyQt6.QtWidgets import (
    QAbstractItemView, QComboBox, QDateEdit, QDialog, QFileDialog, QFrame,
    QGridLayout, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit, QMessageBox,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from .models import Customer, Invoice, Payment, SaleItem, User
from .receipt import PrinterError, print_receipt, receipt_data, render_receipt
from .models import BillSetting, Branch
from .security import PermissionDenied, permission_keys
from .services import CheckoutError, reverse_invoice
from .ui import ReceiptDialog, money


class SalesTrend(QWidget):
    def __init__(self, parent=None): super().__init__(parent); self.values = [0]; self.setMinimumHeight(180)
    def set_values(self, values): self.values = values or [0]; self.update()
    def paintEvent(self, event):
        painter = QPainter(self); painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(16, 16, -12, -22)
        painter.setPen(QPen(QColor("#e3e9f2"), 1))
        for i in range(4):
            y = rect.top() + i * rect.height() / 3; painter.drawLine(rect.left(), int(y), rect.right(), int(y))
        maximum = max(max(self.values), 1); step = rect.width() / max(len(self.values) - 1, 1)
        points = [(int(rect.left() + i * step), int(rect.bottom() - value / maximum * rect.height())) for i, value in enumerate(self.values)]
        painter.setPen(QPen(QColor("#1671f8"), 3))
        for a, b in zip(points, points[1:]): painter.drawLine(*a, *b)
        painter.setBrush(QColor("#1671f8"))
        for x, y in points: painter.drawEllipse(x - 4, y - 4, 8, 8)


class InvoiceDetailsDialog(QDialog):
    def __init__(self, session_factory, invoice_id, parent=None):
        super().__init__(parent); self.setWindowTitle("Invoice Details"); self.resize(760, 520)
        layout = QVBoxLayout(self)
        with session_factory() as session:
            invoice = session.get(Invoice, invoice_id)
            customer = session.get(Customer, invoice.customer_id) if invoice.customer_id else None
            cashier = session.get(User, invoice.cashier_id)
            items = list(invoice.items)
        title = QLabel(invoice.local_invoice_number); title.setStyleSheet("font-size:22px;font-weight:800")
        layout.addWidget(title)
        layout.addWidget(QLabel(f"Date: {invoice.created_at.strftime('%Y-%m-%d %H:%M')}   |   Customer: {customer.name if customer else 'Walk-in Customer'}   |   Cashier: {cashier.display_name}\nPayment: {invoice.payment_method.title()}   |   Status: {invoice.status.title()}"))
        table = QTableWidget(len(items), 4); table.setHorizontalHeaderLabels(["Item", "Qty", "Unit Price", "Amount"])
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for row, item in enumerate(items):
            for column, value in enumerate((item.product_name, item.quantity, money(item.unit_price_cents), money(item.line_total_cents))): table.setItem(row, column, QTableWidgetItem(str(value)))
        layout.addWidget(table)
        total = QLabel(f"Subtotal: {money(invoice.subtotal_cents)}   Discount: {money(invoice.discount_cents)}   Tax: {money(invoice.tax_cents)}\nTotal: {money(invoice.total_cents)}")
        total.setAlignment(Qt.AlignmentFlag.AlignRight); total.setStyleSheet("font-size:18px;font-weight:800"); layout.addWidget(total)
        close = QPushButton("Close"); close.clicked.connect(self.accept); layout.addWidget(close)


class SalesPage(QWidget):
    def __init__(self, session_factory, user: User, open_pos_callback=None, parent=None):
        super().__init__(parent); self.session_factory = session_factory; self.user = user; self.open_pos_callback = open_pos_callback
        with session_factory() as session: self.permissions = permission_keys(session, user)
        root = QVBoxLayout(self); root.setContentsMargins(20, 16, 20, 18); root.setSpacing(14)
        heading = QHBoxLayout(); heading.addWidget(QLabel("Sales", objectName="title")); heading.addWidget(QLabel("Track invoices, payments and transaction history", objectName="muted")); heading.addStretch(); root.addLayout(heading)
        self.metrics = QGridLayout(); root.addLayout(self.metrics)
        body = QHBoxLayout(); main = QVBoxLayout(); filters = QHBoxLayout()
        self.search = QLineEdit(); self.search.setPlaceholderText("Search invoice, customer or product..."); self.search.textChanged.connect(self.refresh)
        self.from_date = QDateEdit(); self.from_date.setCalendarPopup(True); self.from_date.setDate(QDate.currentDate().addDays(-30)); self.from_date.dateChanged.connect(self.refresh)
        self.to_date = QDateEdit(); self.to_date.setCalendarPopup(True); self.to_date.setDate(QDate.currentDate()); self.to_date.dateChanged.connect(self.refresh)
        self.method = QComboBox(); self.method.addItems(["All Payment Methods", "Cash", "Card", "Credit"]); self.method.currentIndexChanged.connect(self.refresh)
        self.cashier = QComboBox(); self.cashier.currentIndexChanged.connect(self.refresh)
        self.status = QComboBox(); self.status.addItems(["All Status", "Paid", "Pending", "Cancelled", "Refunded"]); self.status.currentIndexChanged.connect(self.refresh)
        for widget in (self.search, self.from_date, self.to_date, self.method, self.cashier, self.status): filters.addWidget(widget)
        new_sale = QPushButton("+ New Sale"); new_sale.setObjectName("primaryButton"); new_sale.clicked.connect(self.new_sale)
        export = QPushButton("Export"); export.clicked.connect(self.export_csv)
        print_report = QPushButton("Print Report"); print_report.clicked.connect(self.print_report)
        filters.addWidget(new_sale); filters.addWidget(export); filters.addWidget(print_report); main.addLayout(filters)
        self.table = QTableWidget(0, 9); self.table.setHorizontalHeaderLabels(["Invoice No", "Date & Time", "Customer", "Cashier", "Payment", "Items", "Total", "Status", "Actions"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch); self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows); self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        main.addWidget(self.table); self.result_label = QLabel(); main.addWidget(self.result_label); body.addLayout(main, 4)
        right = QVBoxLayout(); trend_panel = QFrame(objectName="panel"); trend_box = QVBoxLayout(trend_panel); trend_box.addWidget(QLabel("Sales Trend (Last 7 Days)")); self.trend = SalesTrend(); trend_box.addWidget(self.trend); right.addWidget(trend_panel)
        payment_panel = QFrame(objectName="panel"); self.payment_box = QVBoxLayout(payment_panel); self.payment_box.addWidget(QLabel("Payment Method Breakdown")); right.addWidget(payment_panel)
        best_panel = QFrame(objectName="panel"); self.best_label = QLabel(); best_box = QVBoxLayout(best_panel); best_box.addWidget(QLabel("Best Sales Day")); best_box.addWidget(self.best_label); right.addWidget(best_panel); right.addStretch(); body.addLayout(right, 1)
        root.addLayout(body, 1); self.reload_cashiers(); self.refresh()

    def card(self, title, value, color, note=""):
        frame = QFrame(objectName="card"); box = QVBoxLayout(frame); icon = QLabel("●"); icon.setStyleSheet(f"color:{color};font-size:20px"); box.addWidget(icon); box.addWidget(QLabel(title, objectName="metricTitle")); box.addWidget(QLabel(value, objectName="metricValue")); box.addWidget(QLabel(note, objectName="muted")); return frame
    def reload_cashiers(self):
        with self.session_factory() as session: users = session.execute(select(User.id, User.display_name).order_by(User.display_name)).all()
        self.cashier.blockSignals(True); self.cashier.addItem("All Cashiers", None)
        for user_id, name in users: self.cashier.addItem(name, user_id)
        self.cashier.blockSignals(False)
    def query(self, session):
        query = select(Invoice, Customer.name, User.display_name, func.count(SaleItem.id)).outerjoin(Customer, Customer.id == Invoice.customer_id).join(User, User.id == Invoice.cashier_id).outerjoin(SaleItem, SaleItem.invoice_id == Invoice.id).group_by(Invoice.id)
        term = self.search.text().strip()
        if term: query = query.where(or_(Invoice.local_invoice_number.ilike(f"%{term}%"), Customer.name.ilike(f"%{term}%"), SaleItem.product_name.ilike(f"%{term}%")))
        query = query.where(func.date(Invoice.created_at) >= self.from_date.date().toString("yyyy-MM-dd"), func.date(Invoice.created_at) <= self.to_date.date().toString("yyyy-MM-dd"))
        if self.method.currentIndex() > 0: query = query.where(Invoice.payment_method == self.method.currentText().lower())
        if self.cashier.currentData(): query = query.where(Invoice.cashier_id == self.cashier.currentData())
        if self.status.currentIndex() > 0: query = query.where(Invoice.status == self.status.currentText().lower())
        return query.order_by(Invoice.created_at.desc())
    def refresh(self):
        if not hasattr(self, "table"): return
        today = datetime.now(timezone.utc).date()
        with self.session_factory() as session:
            rows = session.execute(self.query(session)).all()
            all_invoices = session.scalars(select(Invoice)).all()
            payment_rows = session.execute(select(Payment.method, func.sum(Payment.amount_cents)).join(Invoice).where(~Invoice.status.in_(["cancelled", "refunded"])).group_by(Payment.method)).all()
        today_sales = sum(i.total_cents for i in all_invoices if i.created_at.date() == today and i.status not in {"cancelled", "refunded"}); revenue = sum(i.total_cents for i in all_invoices if i.status not in {"cancelled", "refunded"}); paid = sum(i.status == "paid" for i in all_invoices); pending = sum(i.status == "pending" for i in all_invoices)
        while self.metrics.count():
            item = self.metrics.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        metrics = [("Today's Sales", money(today_sales), "#1671f8", "Live today"), ("Total Invoices", str(len(all_invoices)), "#10ad68", "All transactions"), ("Paid Invoices", str(paid), "#7b4af5", "Completed"), ("Pending Payments", str(pending), "#f28a16", "Credit invoices"), ("Total Revenue", money(revenue), "#10ad68", "Net active sales")]
        for column, metric in enumerate(metrics): self.metrics.addWidget(self.card(*metric), 0, column)
        self.table.setRowCount(len(rows))
        for row_number, (invoice, customer_name, cashier_name, item_count) in enumerate(rows):
            values = [invoice.local_invoice_number, invoice.created_at.strftime("%d %b %Y %H:%M"), customer_name or "Walk-in Customer", cashier_name, invoice.payment_method.title(), item_count, money(invoice.total_cents), invoice.status.title()]
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value)); item.setData(Qt.ItemDataRole.UserRole, invoice.id if column == 0 else None); self.table.setItem(row_number, column, item)
            actions = QWidget(); action_row = QHBoxLayout(actions); action_row.setContentsMargins(0, 0, 0, 0)
            for text, fn in (("View", self.view_invoice), ("Print", self.print_invoice), ("Cancel", self.cancel_invoice), ("Refund", self.refund_invoice)):
                button = QPushButton(text); required = {"Cancel": "sales.cancel", "Refund": "sales.refund", "Print": "invoice.reprint"}.get(text)
                if required: button.setEnabled(required in self.permissions and invoice.status not in {"cancelled", "refunded"})
                button.clicked.connect(lambda _checked=False, iid=invoice.id, callback=fn: callback(iid)); action_row.addWidget(button)
            self.table.setCellWidget(row_number, 8, actions)
        self.result_label.setText(f"Showing {len(rows)} invoices")
        daily = defaultdict(int)
        for invoice in all_invoices:
            if invoice.status not in {"cancelled", "refunded"}: daily[invoice.created_at.date()] += invoice.total_cents
        days = [today - timedelta(days=offset) for offset in reversed(range(7))]; self.trend.set_values([daily[day] for day in days])
        while self.payment_box.count() > 1:
            item = self.payment_box.takeAt(1)
            if item.widget(): item.widget().deleteLater()
            elif item.layout():
                while item.layout().count():
                    child = item.layout().takeAt(0)
                    if child.widget(): child.widget().deleteLater()
        for method, amount in payment_rows:
            row = QHBoxLayout(); row.addWidget(QLabel(method.title())); row.addStretch(); row.addWidget(QLabel(money(amount or 0))); self.payment_box.addLayout(row)
        if daily:
            best_day, amount = max(daily.items(), key=lambda pair: pair[1]); count = sum(i.created_at.date() == best_day for i in all_invoices); self.best_label.setText(f"{best_day.strftime('%A, %d %b %Y')}\n{money(amount)}\n{count} invoices")
        else: self.best_label.setText("No sales yet")
    def new_sale(self):
        if self.open_pos_callback: self.open_pos_callback()
    def view_invoice(self, invoice_id): InvoiceDetailsDialog(self.session_factory, invoice_id, self).exec()
    def print_invoice(self, invoice_id): ReceiptDialog(self.session_factory, invoice_id, self).exec()
    def reverse(self, invoice_id, action):
        reason, ok = QInputDialog.getText(self, action.title(), f"Reason for {action}:")
        if not ok or not reason.strip(): return
        try:
            with self.session_factory() as session: reverse_invoice(session, invoice_id=invoice_id, user_id=self.user.id, action=action, reason=reason)
        except (CheckoutError, PermissionDenied, ValueError) as exc: QMessageBox.warning(self, "Cannot update invoice", str(exc)); return
        self.refresh()
    def cancel_invoice(self, invoice_id): self.reverse(invoice_id, "cancelled")
    def refund_invoice(self, invoice_id): self.reverse(invoice_id, "refunded")
    def export_csv(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export Sales", "sales.csv", "CSV (*.csv)")
        if not path: return
        with self.session_factory() as session: rows = session.execute(self.query(session)).all()
        with open(path, "w", newline="", encoding="utf-8-sig") as file:
            writer = csv.writer(file); writer.writerow(["invoice", "date", "customer", "cashier", "payment", "items", "total_cents", "status"])
            for invoice, customer, cashier, count in rows: writer.writerow([invoice.local_invoice_number, invoice.created_at.isoformat(), customer or "Walk-in", cashier, invoice.payment_method, count, invoice.total_cents, invoice.status])
        QMessageBox.information(self, "Exported", f"Sales exported to {path}")
    def print_report(self):
        with self.session_factory() as session: rows = session.execute(self.query(session)).all()
        html = "<h1>OilMart Sales Report</h1><table border='1' cellspacing='0' cellpadding='5'><tr><th>Invoice</th><th>Date</th><th>Customer</th><th>Total</th><th>Status</th></tr>" + "".join(f"<tr><td>{i.local_invoice_number}</td><td>{i.created_at:%Y-%m-%d %H:%M}</td><td>{c or 'Walk-in'}</td><td>{money(i.total_cents)}</td><td>{i.status.title()}</td></tr>" for i,c,_,_ in rows) + "</table>"
        document = QTextDocument(); document.setHtml(html); printer = QPrinter(QPrinter.PrinterMode.HighResolution); dialog = QPrintDialog(printer, self)
        if dialog.exec() == QDialog.DialogCode.Accepted: document.print(printer)
