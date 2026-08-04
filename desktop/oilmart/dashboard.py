from datetime import datetime, timezone

from sqlalchemy import func, select
from PyQt6.QtCore import QByteArray, Qt
from PyQt6.QtGui import QColor, QIcon, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QListWidget, QListWidgetItem,
    QMainWindow, QMessageBox, QPushButton, QStackedWidget, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from .models import Customer, Invoice, Payment, Product, Role, SaleItem, Terminal, User
from .security import permission_keys
from .ui import AdminDialog, PosWidget, UserManagementDialog, money
from .products_page import ProductsPage


STYLE = """
QMainWindow { background: #f7f9fd; color: #15213b; font-family: 'Segoe UI'; }
QFrame#sidebar, QFrame#topbar, QFrame#card, QFrame#panel { background: white; }
QFrame#sidebar { border-right: 1px solid #dde5f1; }
QFrame#topbar { border-bottom: 1px solid #dde5f1; }
QFrame#card, QFrame#panel { border: 1px solid #dde5f1; border-radius: 10px; }
QLabel#brand { font-size: 22px; font-weight: 800; color: #15213a; }
QLabel#brandPos { font-size: 22px; font-weight: 800; color: #1671f8; }
QLabel#title { font-size: 23px; font-weight: 800; color: #111c34; }
QLabel#muted { color: #74819a; }
QLabel#metricTitle { color: #64718a; font-weight: 600; }
QLabel#metricValue { font-size: 21px; font-weight: 800; color: #14213b; }
QLabel#metricTrend { color: #12a96b; font-size: 11px; font-weight: 700; }
QListWidget { border: 0; outline: 0; background: white; padding: 6px; }
QListWidget::item { padding: 13px 12px; margin: 3px 0; border-radius: 9px; color: #26334f; font-size: 14px; font-weight: 600; }
QListWidget::item:selected { color: #1269e8; background: #eaf3ff; font-weight: 700; }
QListWidget::item:hover { background: #f1f6fd; }
QPushButton#logout { color: #e33d50; background: white; border: 1px solid #ffd1d7; border-radius: 8px; padding: 11px; text-align: left; }
QTableWidget { background: white; border: 0; gridline-color: #edf1f7; }
QHeaderView::section { background: white; border: 0; border-bottom: 1px solid #e3e9f2; padding: 8px; color: #68758d; font-weight: 650; }
"""


ICON_PATHS = {
    "drop": '<path d="M12 2C9 7 5 11 5 15a7 7 0 0 0 14 0c0-4-4-8-7-13Z" fill="{color}" stroke="{color}"/><path d="M8 16c.4 2 1.8 3 3.5 3.5" stroke="white"/>',
    "home": '<path d="m3 10 9-7 9 7v10H3Z"/><path d="M9 20v-7h6v7"/><path d="M10 8h4"/>',
    "pos": '<rect x="4" y="3" width="16" height="18" rx="2"/><path d="M8 7h8M8 11h2m4 0h2M8 15h2m4 0h2M8 19h8"/>',
    "products": '<rect x="4" y="3" width="7" height="18" rx="1"/><rect x="13" y="3" width="7" height="18" rx="1"/><path d="M7 7h1m-1 4h1m-1 4h1m8-8h1m-1 4h1m-1 4h1"/>',
    "sales": '<path d="M3 5h7l2 2 2-2h7v15h-7l-2 2-2-2H3Z"/><path d="M12 7v15M6 10h3m6 0h3M6 14h3m6 0h3"/>',
    "purchases": '<path d="M3 4h2l2.4 11h10.8l2-8H6"/><circle cx="9" cy="20" r="1"/><circle cx="18" cy="20" r="1"/>',
    "customers": '<circle cx="9" cy="8" r="3"/><circle cx="17" cy="9" r="2.5"/><path d="M3 20v-2a6 6 0 0 1 12 0v2M15 14a5 5 0 0 1 6 4v2"/>',
    "suppliers": '<circle cx="12" cy="7" r="3"/><path d="M5 21v-2a7 7 0 0 1 14 0v2M8 13l4 3 4-3"/>',
    "inventory": '<path d="M3 8h18v12H3Z"/><path d="m5 8 2-4h10l2 4M8 12v4m4-4v4m4-4v4"/>',
    "reports": '<path d="M5 3h11l3 3v15H5Z"/><path d="M16 3v4h4M8 16l3-3 2 2 3-4"/>',
    "users": '<circle cx="12" cy="7" r="3"/><path d="M5 21v-2a7 7 0 0 1 14 0v2"/>',
    "settings": '<circle cx="12" cy="12" r="3"/><path d="M19 12a7 7 0 0 0-.1-1l2-1.5-2-3.4-2.4 1a8 8 0 0 0-1.7-1L14.5 3h-5L9 6.1a8 8 0 0 0-1.7 1l-2.4-1-2 3.4L5 11a7 7 0 0 0 0 2l-2.1 1.5 2 3.4 2.4-1a8 8 0 0 0 1.7 1l.5 3.1h5l.5-3.1a8 8 0 0 0 1.7-1l2.4 1 2-3.4L18.9 13a7 7 0 0 0 .1-1Z"/>',
}


def line_icon(name: str, color: str = "#667594", size: int = 22) -> QIcon:
    paths = ICON_PATHS[name].format(color=color)
    fill = "none" if name != "drop" else "none"
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" '
           f'fill="{fill}" stroke="{color}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'
           f'{paths}</svg>')
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    QSvgRenderer(QByteArray(svg.encode())).render(painter)
    painter.end()
    return QIcon(pixmap)


def table(headers, rows):
    widget = QTableWidget(len(rows), len(headers))
    widget.setHorizontalHeaderLabels(headers)
    widget.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
    widget.verticalHeader().setVisible(False)
    widget.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    for row_number, values in enumerate(rows):
        for column, value in enumerate(values):
            widget.setItem(row_number, column, QTableWidgetItem(str(value)))
    return widget


class DashboardWidget(QWidget):
    def __init__(self, session_factory, parent=None):
        super().__init__(parent)
        self.session_factory = session_factory
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(18, 16, 18, 18)
        self.layout.setSpacing(14)
        self.refresh()

    def clear(self):
        while self.layout.count():
            item = self.layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self.clear_layout(item.layout())

    def clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self.clear_layout(item.layout())

    def card(self, title, value, color, pale_color, icon_name, trend, trend_color="#12a96b"):
        frame = QFrame(objectName="card")
        frame.setMinimumHeight(112)
        box = QHBoxLayout(frame)
        box.setContentsMargins(14, 14, 14, 14)
        box.setSpacing(12)
        icon_box = QFrame()
        icon_box.setFixedSize(48, 48)
        icon_box.setStyleSheet(f"background: {pale_color}; border: 0; border-radius: 10px;")
        icon_layout = QVBoxLayout(icon_box)
        icon_layout.setContentsMargins(0, 0, 0, 0)
        icon = QLabel()
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setPixmap(line_icon(icon_name, color, 25).pixmap(25, 25))
        icon_layout.addWidget(icon)
        box.addWidget(icon_box)
        text = QVBoxLayout()
        text.setSpacing(3)
        label = QLabel(title, objectName="metricTitle")
        number = QLabel(value, objectName="metricValue")
        trend_label = QLabel(trend, objectName="metricTrend")
        trend_label.setStyleSheet(f"color: {trend_color}; font-size: 11px; font-weight: 700;")
        text.addWidget(label)
        text.addWidget(number)
        text.addWidget(trend_label)
        box.addLayout(text, 1)
        return frame

    def panel(self, title, content):
        frame = QFrame(objectName="panel")
        box = QVBoxLayout(frame)
        heading = QLabel(title)
        heading.setStyleSheet("font-size: 14px; font-weight: 750;")
        box.addWidget(heading); box.addWidget(content)
        return frame

    def refresh(self):
        self.clear()
        today = datetime.now(timezone.utc).date()
        with self.session_factory() as session:
            invoices = session.scalars(select(Invoice).order_by(Invoice.created_at.desc()).limit(100)).all()
            recent = invoices[:5]
            invoice_count = session.scalar(select(func.count(Invoice.id))) or 0
            customer_count = session.scalar(select(func.count(Customer.id))) or 0
            low = session.scalars(select(Product).where(
                Product.active.is_(True), Product.stock_quantity <= Product.low_stock_threshold
            ).order_by(Product.stock_quantity).limit(6)).all()
            low_count = session.scalar(select(func.count(Product.id)).where(
                Product.active.is_(True), Product.stock_quantity <= Product.low_stock_threshold
            )) or 0
            top = session.execute(select(
                SaleItem.product_name, func.sum(SaleItem.quantity), func.sum(SaleItem.line_total_cents)
            ).group_by(SaleItem.product_name).order_by(func.sum(SaleItem.quantity).desc()).limit(5)).all()
            payments = session.execute(select(
                Payment.method, func.sum(Payment.amount_cents)
            ).group_by(Payment.method)).all()
            profit = session.scalar(select(func.sum(
                (SaleItem.unit_price_cents - SaleItem.cost_price_cents) * SaleItem.quantity
            ))) or 0
        today_sales = sum(i.total_cents for i in invoices if i.created_at.date() == today)
        heading = QHBoxLayout()
        heading.addWidget(QLabel("Dashboard", objectName="title"))
        heading.addWidget(QLabel("Overview of your business", objectName="muted"))
        heading.addStretch()
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh)
        heading.addWidget(refresh)
        self.layout.addLayout(heading)
        cards = QGridLayout()
        metrics = [
            ("Today's Sales", money(today_sales), "#1671f8", "#eaf3ff", "purchases", "▲ Live today"),
            ("Total Invoices", str(invoice_count), "#10ad68", "#e9f8f0", "reports", "▲ Completed sales"),
            ("Total Customers", str(customer_count), "#6847f5", "#f0edff", "customers", "▲ Registered"),
            ("Low Stock Items", str(low_count), "#f28a16", "#fff3e2", "inventory", "View items", "#126ff5"),
            ("Gross Profit", money(profit), "#ef4c5d", "#ffedf0", "reports", "▲ Sales margin"),
        ]
        for column, values in enumerate(metrics):
            cards.addWidget(self.card(*values), 0, column)
        self.layout.addLayout(cards)
        middle = QGridLayout()
        middle.addWidget(self.panel("Recent Invoices", table(
            ["Invoice", "Total", "Payment", "Date"],
            [[i.local_invoice_number, money(i.total_cents), i.payment_method.title(),
              i.created_at.strftime("%d %b %H:%M")] for i in recent]
        )), 0, 0)
        middle.addWidget(self.panel("Top Selling Products", table(
            ["Product", "Qty", "Sales"],
            [[name, qty, money(amount or 0)] for name, qty, amount in top]
        )), 0, 1)
        self.layout.addLayout(middle, 1)
        lower = QGridLayout()
        lower.addWidget(self.panel("Low Stock Alert", table(
            ["Product", "Stock", "Minimum", "Status"],
            [[p.name, p.stock_quantity, p.low_stock_threshold, "Low"] for p in low]
        )), 0, 0)
        total_received = sum(amount or 0 for _, amount in payments)
        payment_rows = [[method.title(), money(amount or 0)] for method, amount in payments]
        payment_rows.append(["Total Received", money(total_received)])
        lower.addWidget(self.panel("Payment Summary", table(["Method", "Amount"], payment_rows)), 0, 1)
        lower.setColumnStretch(0, 2); lower.setColumnStretch(1, 1)
        self.layout.addLayout(lower, 1)


class MainWindow(QMainWindow):
    def __init__(self, session_factory, user: User):
        super().__init__()
        self.session_factory = session_factory
        self.user = user
        with session_factory() as session:
            self.permissions = permission_keys(session, user)
            self.role_name = session.scalar(select(Role.name).where(Role.id == user.role_id)) or "User"
            terminal = session.scalar(select(Terminal).where(Terminal.branch_id == user.branch_id).order_by(Terminal.id))
            self.terminal_name = f"{terminal.code} - Main Terminal" if terminal else "No terminal"
        self.setWindowTitle("OilMart POS - Dashboard")
        self.resize(1440, 900)
        self.setMinimumSize(1080, 700)
        self.setStyleSheet(STYLE)
        root_widget = QWidget()
        root = QHBoxLayout(root_widget); root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)
        sidebar = QFrame(objectName="sidebar"); sidebar.setFixedWidth(215)
        side = QVBoxLayout(sidebar); side.setContentsMargins(12, 20, 12, 18)
        brand_row = QHBoxLayout()
        brand_row.setContentsMargins(16, 0, 0, 12)
        drop = QLabel()
        drop.setPixmap(line_icon("drop", "#126ff5", 31).pixmap(31, 31))
        brand_row.addWidget(drop)
        brand_row.addSpacing(5)
        brand_row.addWidget(QLabel("OilMart", objectName="brand"))
        brand_row.addWidget(QLabel("POS", objectName="brandPos"))
        brand_row.addStretch()
        side.addLayout(brand_row); side.addSpacing(12)
        self.nav = QListWidget()
        self.pages = []
        self.nav_icon_names = []
        entries = [
            ("Dashboard", "dashboard.view", "home"), ("POS", "sales.create", "pos"),
            ("Products", "stock.view", "products"), ("Sales", "sales.view", "sales"),
            ("Purchases", "purchase.add", "purchases"), ("Customers", "customer.edit", "customers"),
            ("Suppliers", "supplier.edit", "suppliers"), ("Inventory", "stock.view", "inventory"),
            ("Reports", "reports.view", "reports"), ("Users", "user.edit", "users"),
            ("Settings", "user.roles", "settings"),
        ]
        for label, permission, icon_name in entries:
            if permission in self.permissions:
                self.nav.addItem(QListWidgetItem(line_icon(icon_name), label))
                self.pages.append(label)
                self.nav_icon_names.append(icon_name)
        self.nav.currentRowChanged.connect(self.navigate)
        side.addWidget(self.nav, 1)
        logout = QPushButton("  Logout", objectName="logout")
        logout.setIcon(line_icon("users", "#e33d50"))
        logout.clicked.connect(self.close)
        side.addWidget(logout); root.addWidget(sidebar)
        content = QVBoxLayout(); content.setContentsMargins(0, 0, 0, 0); content.setSpacing(0)
        topbar = QFrame(objectName="topbar"); topbar.setFixedHeight(62)
        top = QHBoxLayout(topbar); top.setContentsMargins(22, 0, 26, 0)
        top.addWidget(QLabel("☰")); top.addStretch(); top.addWidget(QLabel(self.terminal_name)); top.addSpacing(24)
        top.addWidget(QLabel(f"👤  {user.display_name}\n     {self.role_name}")); content.addWidget(topbar)
        self.stack = QStackedWidget(); self.dashboard_view = DashboardWidget(session_factory)
        self.pos_view = PosWidget(session_factory, user)
        self.products_view = ProductsPage(session_factory, user)
        self.stack.addWidget(self.dashboard_view); self.stack.addWidget(self.pos_view); self.stack.addWidget(self.products_view)
        content.addWidget(self.stack); root.addLayout(content, 1); self.setCentralWidget(root_widget)
        self.nav.setCurrentRow(0)

    def navigate(self, index):
        if index < 0: return
        for row, icon_name in enumerate(self.nav_icon_names):
            color = "#126ff5" if row == index else "#667594"
            self.nav.item(row).setIcon(line_icon(icon_name, color))
        page = self.pages[index]
        if page == "Dashboard":
            self.dashboard_view.refresh(); self.stack.setCurrentWidget(self.dashboard_view)
        elif page == "POS":
            if self.pos_view.shift_id is None and not self.pos_view.ensure_shift():
                self.nav.setCurrentRow(self.pages.index("Dashboard")); return
            self.stack.setCurrentWidget(self.pos_view); self.pos_view.search.setFocus()
        elif page == "Products":
            self.products_view.reload_filters(); self.products_view.refresh()
            self.stack.setCurrentWidget(self.products_view)
        elif page == "Users":
            UserManagementDialog(self.session_factory, self.user, self).exec()
            self.nav.setCurrentRow(self.pages.index("Dashboard"))
        elif page == "Settings":
            AdminDialog(self.session_factory, self.user, self).exec()
            self.nav.setCurrentRow(self.pages.index("Dashboard"))
        else:
            QMessageBox.information(self, page, f"{page} workflow will be added in the next desktop milestone.")
            self.nav.setCurrentRow(self.pages.index("Dashboard"))

    def ensure_shift(self):
        return True
