import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from PyQt6.QtCore import QByteArray, QDateTime, QTimer, Qt
from PyQt6.QtGui import QColor, QIcon, QPainter, QPixmap, QPen
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import (
    QComboBox, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QListWidget, QListWidgetItem,
    QMainWindow, QMessageBox, QPushButton, QStackedWidget, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from .models import Customer, Invoice, Payment, Product, Role, SaleItem, Terminal, User
from .security import permission_keys
from .ui import AdminDialog, PosWidget, UserManagementDialog, money
from .products_page import ProductsPage
from .sales_page import SalesPage
from .business_pages import DirectoryPage, PurchasesPage
from .inventory_page import InventoryPage
from .admin_pages import ReportsPage, SettingsPage, UsersPage


def _load_dashboard_style() -> str:
    path = os.path.join(os.path.dirname(__file__), "dashboard_style.qss")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return ""

STYLE = _load_dashboard_style()


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


class SalesOverviewChart(QWidget):
    def __init__(self, values=None, parent=None):
        super().__init__(parent)
        self.values = list(values or [0] * 7)
        self.labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        self.setMinimumHeight(200)

    def set_values(self, values):
        self.values = list(values[:7]) + [0] * max(0, 7 - len(values))
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self); painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(20, 20, -20, -30)
        painter.setPen(QPen(QColor("#f1f5f9"), 1))
        for i in range(5):
            y = rect.top() + i * rect.height() / 4; painter.drawLine(rect.left(), int(y), rect.right(), int(y))
        maximum = max(self.values) if self.values else 0
        step = rect.width() / 6
        if maximum <= 0:
            painter.setPen(QColor("#94a3b8"))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "No sales recorded this week")
            painter.setPen(QColor("#64748b"))
            for i, label in enumerate(self.labels):
                painter.drawText(int(rect.left() + i * step - 12), int(rect.bottom() + 20), label)
            return
        points = [(int(rect.left() + i * step), int(rect.bottom() - (value / maximum) * rect.height())) for i, value in enumerate(self.values)]
        
        from PyQt6.QtGui import QPolygonF, QBrush
        from PyQt6.QtCore import QPointF
        poly = QPolygonF([QPointF(points[0][0], rect.bottom())] + [QPointF(x, y) for x, y in points] + [QPointF(points[-1][0], rect.bottom())])
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(37, 99, 235, 20)))
        painter.drawPolygon(poly)
        
        painter.setPen(QPen(QColor("#2563eb"), 2.5))
        for a, b in zip(points, points[1:]): painter.drawLine(a[0], a[1], b[0], b[1])
        painter.setBrush(QColor("#2563eb"))
        for x, y in points: painter.drawEllipse(x - 4, y - 4, 8, 8)
        
        painter.setPen(QColor("#64748b"))
        for i, label in enumerate(self.labels):
            painter.drawText(points[i][0] - 10, int(rect.bottom() + 20), label)

def table(headers, rows):
    widget = QTableWidget(len(rows), len(headers))
    widget.setHorizontalHeaderLabels(headers)
    widget.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    widget.horizontalHeader().setMinimumSectionSize(72)
    widget.verticalHeader().setVisible(False)
    widget.verticalHeader().setDefaultSectionSize(42)
    widget.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    for row_number, values in enumerate(rows):
        for column, value in enumerate(values):
            item = QTableWidgetItem(str(value))
            if str(value) == "Paid" or str(value) == "In Stock":
                item.setForeground(QColor("#10b981"))
            elif str(value) == "Low":
                item.setForeground(QColor("#ef4444"))
            elif str(value) == "Pending":
                item.setForeground(QColor("#f59e0b"))
            widget.setItem(row_number, column, item)
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
                item.widget().hide()
                item.widget().deleteLater()
            elif item.layout():
                self.clear_layout(item.layout())

    def clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
            elif item.layout():
                self.clear_layout(item.layout())

    def card(self, title, value, color, pale_color, icon_name, trend, trend_color="#12a96b"):
        frame = QFrame(); frame.setObjectName("card")
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
        label = QLabel(title); label.setObjectName("metricTitle")
        number = QLabel(value); number.setObjectName("metricValue")
        trend_label = QLabel(trend); trend_label.setObjectName("metricTrend")
        trend_label.setStyleSheet(f"color: {trend_color}; font-size: 11px; font-weight: 700;")
        text.addWidget(label)
        text.addWidget(number)
        text.addWidget(trend_label)
        box.addLayout(text, 1)
        return frame

    def panel(self, title, content):
        frame = QFrame(); frame.setObjectName("panel")
        box = QVBoxLayout(frame)
        box.setContentsMargins(18, 18, 18, 18)
        header = QHBoxLayout()
        heading = QLabel(title)
        heading.setStyleSheet("font-size: 15px; font-weight: 800; color: #0f172a;")
        header.addWidget(heading)
        header.addStretch()
        view_all = QLabel("View all")
        view_all.setStyleSheet("color: #2563eb; font-size: 13px; font-weight: 700;")
        header.addWidget(view_all)
        box.addLayout(header)
        box.addSpacing(10)
        box.addWidget(content)
        return frame

    def refresh(self):
        self.clear()
        today = datetime.now().astimezone().date()
        week_start = today - timedelta(days=today.weekday())
        last_week_start = week_start - timedelta(days=7)
        next_week_start = week_start + timedelta(days=7)
        active_statuses = ("paid", "pending")
        with self.session_factory() as session:
            recent = session.scalars(select(Invoice).order_by(Invoice.created_at.desc()).limit(5)).all()
            period_invoices = session.scalars(select(Invoice).where(
                Invoice.status.in_(active_statuses),
                Invoice.created_at >= datetime.combine(last_week_start, datetime.min.time()),
                Invoice.created_at < datetime.combine(next_week_start, datetime.min.time()),
            )).all()
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
            ).join(Invoice, Invoice.id == SaleItem.invoice_id).where(
                Invoice.status.in_(active_statuses)
            ).group_by(SaleItem.product_name).order_by(func.sum(SaleItem.quantity).desc()).limit(5)).all()
            payments = session.execute(select(
                Payment.method, func.sum(Payment.amount_cents)
            ).join(Invoice, Invoice.id == Payment.invoice_id).where(
                Invoice.status.in_(active_statuses)
            ).group_by(Payment.method)).all()
            profit = session.scalar(select(func.sum(
                (SaleItem.unit_price_cents - SaleItem.cost_price_cents) * SaleItem.quantity
            )).join(Invoice, Invoice.id == SaleItem.invoice_id).where(Invoice.status.in_(active_statuses))) or 0
        current_daily = [0] * 7
        last_daily = [0] * 7
        for invoice in period_invoices:
            invoice_date = invoice.created_at.date()
            if week_start <= invoice_date < next_week_start:
                current_daily[(invoice_date - week_start).days] += invoice.total_cents
            elif last_week_start <= invoice_date < week_start:
                last_daily[(invoice_date - last_week_start).days] += invoice.total_cents
        today_sales = current_daily[today.weekday()]
        this_week_sales = sum(current_daily)
        last_week_sales = sum(last_daily)
        heading = QHBoxLayout()
        dashboard_title = QLabel("Dashboard"); dashboard_title.setObjectName("title"); heading.addWidget(dashboard_title)
        dashboard_subtitle = QLabel("Overview of your business"); dashboard_subtitle.setObjectName("muted"); heading.addWidget(dashboard_subtitle)
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
        middle.setSpacing(16)
        
        sales_panel = QFrame(); sales_panel.setObjectName("panel")
        sales_box = QVBoxLayout(sales_panel); sales_box.setContentsMargins(18, 18, 18, 18)
        sales_header = QHBoxLayout()
        sales_title = QLabel("Sales Overview")
        sales_title.setStyleSheet("font-size: 15px; font-weight: 800; color: #0f172a;")
        sales_header.addWidget(sales_title); sales_header.addStretch()
        combo = QComboBox(); combo.addItem("This Week")
        combo.setStyleSheet("border: 1px solid #e2e8f0; border-radius: 6px; padding: 4px 8px; font-size: 12px; color: #475569; background: white;")
        sales_header.addWidget(combo)
        sales_box.addLayout(sales_header)
        sales_box.addWidget(SalesOverviewChart(current_daily))
        
        stats_row = QHBoxLayout()
        tws = QVBoxLayout(); tws_label = QLabel("This Week Sales"); tws_label.setObjectName("muted"); tws.addWidget(tws_label); v1 = QLabel(money(this_week_sales)); v1.setStyleSheet("font-size: 16px; font-weight: 800; color: #0f172a;"); tws.addWidget(v1)
        lws = QVBoxLayout(); lws_label = QLabel("Last Week Sales"); lws_label.setObjectName("muted"); lws.addWidget(lws_label); v2 = QLabel(money(last_week_sales)); v2.setStyleSheet("font-size: 16px; font-weight: 800; color: #0f172a;"); lws.addWidget(v2)
        stats_row.addLayout(tws); stats_row.addLayout(lws)
        if last_week_sales:
            change = ((this_week_sales - last_week_sales) / last_week_sales) * 100
            trend_text = f"{'▲' if change >= 0 else '▼'} {abs(change):.1f}%"
            trend_color, trend_bg = ("#059669", "#d1fae5") if change >= 0 else ("#dc2626", "#fee2e2")
        elif this_week_sales:
            trend_text, trend_color, trend_bg = "New sales", "#2563eb", "#dbeafe"
        else:
            trend_text, trend_color, trend_bg = "No sales yet", "#64748b", "#f1f5f9"
        trend_lbl = QLabel(trend_text); trend_lbl.setStyleSheet(f"color: {trend_color}; background: {trend_bg}; border-radius: 4px; padding: 6px 10px; font-weight: 700; font-size: 11px;")
        stats_row.addWidget(trend_lbl)
        sales_box.addLayout(stats_row)
        
        middle.addWidget(sales_panel, 0, 0, 1, 2)
        
        middle.addWidget(self.panel("Recent Invoices", table(
            ["Invoice", "Total", "Status"],
            [[i.local_invoice_number, money(i.total_cents), "Paid" if i.status == "paid" else "Pending"] for i in recent]
        )), 0, 2)
        middle.addWidget(self.panel("Top Selling Products", table(
            ["Product", "Qty", "Sales"],
            [[name, qty, money(amount or 0)] for name, qty, amount in top]
        )), 0, 3)
        middle.setColumnStretch(0, 1)
        middle.setColumnStretch(1, 1)
        middle.setColumnStretch(2, 1)
        middle.setColumnStretch(3, 1)
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
        self.setMinimumSize(1180, 760)
        self.setStyleSheet(STYLE)
        root_widget = QWidget()
        root = QHBoxLayout(root_widget); root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)
        sidebar = QFrame(); sidebar.setObjectName("sidebar"); sidebar.setFixedWidth(225)
        side = QVBoxLayout(sidebar); side.setContentsMargins(12, 16, 12, 12)
        brand_row = QHBoxLayout(); brand_row.setSpacing(5)
        brand_row.setContentsMargins(16, 0, 0, 12)
        drop = QLabel()
        drop.setPixmap(line_icon("drop", "#126ff5", 31).pixmap(31, 31))
        brand_row.addWidget(drop)
        brand_row.addSpacing(5)
        brand_name = QLabel("OilMart"); brand_name.setObjectName("brand"); brand_name.setMinimumWidth(82); brand_row.addWidget(brand_name)
        brand_pos = QLabel("POS"); brand_pos.setObjectName("brandPos"); brand_pos.setMinimumWidth(42); brand_row.addWidget(brand_pos)
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
        logout = QPushButton("  Logout"); logout.setObjectName("logout")
        logout.setIcon(line_icon("users", "#e33d50"))
        logout.clicked.connect(self.close)
        side.addWidget(logout); root.addWidget(sidebar)
        content = QVBoxLayout(); content.setContentsMargins(0, 0, 0, 0); content.setSpacing(0)
        topbar = QFrame(); topbar.setObjectName("topbar"); topbar.setFixedHeight(76)
        top = QHBoxLayout(topbar); top.setContentsMargins(22, 0, 22, 0); top.setSpacing(14)
        location = QLabel(self.terminal_name); location.setObjectName("topbarTerminal")
        location.setFixedHeight(38); location.setAlignment(Qt.AlignmentFlag.AlignCenter)
        top.addWidget(location); top.addStretch()
        self.clock = QLabel(); self.clock.setObjectName("topbarClock"); self.clock.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        top.addWidget(self.clock)
        user_icon = QLabel(); user_icon.setPixmap(line_icon("users", "#334155", 24).pixmap(24, 24)); top.addWidget(user_icon)
        identity = QLabel(f"{user.display_name}\n{self.role_name}"); identity.setObjectName("topbarUser"); top.addWidget(identity)
        top_logout = QPushButton("Logout"); top_logout.setObjectName("topbarLogout"); top_logout.clicked.connect(self.close); top.addWidget(top_logout)
        self.clock_timer = QTimer(self); self.clock_timer.timeout.connect(self.update_clock); self.clock_timer.start(1000); self.update_clock()
        content.addWidget(topbar)
        self.stack = QStackedWidget(); self.dashboard_view = DashboardWidget(session_factory)
        self.pos_view = PosWidget(session_factory, user)
        self.products_view = ProductsPage(session_factory, user)
        self.pos_view.open_product_form_callback = self.open_product_form
        self.sales_view = SalesPage(session_factory, user, self.open_pos_page)
        self.purchases_view = PurchasesPage(session_factory, user)
        self.customers_view = DirectoryPage(session_factory, user, "customer")
        self.suppliers_view = DirectoryPage(session_factory, user, "supplier")
        self.inventory_view = InventoryPage(session_factory, user)
        self.reports_view = ReportsPage(session_factory, user)
        self.users_view = UsersPage(session_factory, user)
        self.settings_view = SettingsPage(session_factory, user)
        for page in (self.dashboard_view, self.pos_view, self.products_view, self.sales_view,
                     self.purchases_view, self.customers_view, self.suppliers_view, self.inventory_view,
                     self.reports_view, self.users_view, self.settings_view):
            self.stack.addWidget(page)
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
        elif page == "Sales":
            self.sales_view.refresh()
            self.stack.setCurrentWidget(self.sales_view)
        elif page == "Purchases":
            self.purchases_view.refresh(); self.stack.setCurrentWidget(self.purchases_view)
        elif page == "Customers":
            self.customers_view.reload_groups(); self.customers_view.refresh(); self.stack.setCurrentWidget(self.customers_view)
        elif page == "Suppliers":
            self.suppliers_view.reload_groups(); self.suppliers_view.refresh(); self.stack.setCurrentWidget(self.suppliers_view)
        elif page == "Inventory":
            self.inventory_view.refresh(); self.stack.setCurrentWidget(self.inventory_view)
        elif page == "Reports":
            self.reports_view.refresh(); self.stack.setCurrentWidget(self.reports_view)
        elif page == "Users":
            self.users_view.refresh(); self.stack.setCurrentWidget(self.users_view)
        elif page == "Settings":
            self.stack.setCurrentWidget(self.settings_view)
        else:
            QMessageBox.information(self, page, f"{page} workflow will be added in the next desktop milestone.")
            self.nav.setCurrentRow(self.pages.index("Dashboard"))

    def open_pos_page(self):
        if "POS" in self.pages:
            self.nav.setCurrentRow(self.pages.index("POS"))

    def open_product_form(self):
        if "Products" not in self.pages:
            return
        self.nav.setCurrentRow(self.pages.index("Products"))
        self.products_view.add_product()
        self.products_view.reload_filters(); self.products_view.refresh()
        self.pos_view.reload_categories(); self.pos_view.search_products()

    def update_clock(self):
        now = QDateTime.currentDateTime()
        self.clock.setText(now.toString("ddd, dd MMM yyyy\nh:mm:ss AP"))

    def ensure_shift(self):
        return True
