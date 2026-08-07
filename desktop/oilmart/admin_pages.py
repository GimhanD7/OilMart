from __future__ import annotations

import csv
import os
import shutil
import sqlite3
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_, select
from PyQt6.QtCore import QDate, Qt, QPropertyAnimation, QEasingCurve, pyqtProperty, QRect, QSize, QPoint, QPointF
from PyQt6.QtGui import QPainter, QColor, QPainterPath, QIcon
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QDateEdit, QDialog, QDialogButtonBox,
    QFileDialog, QFormLayout, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QSpinBox, QStackedWidget,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget, QSizePolicy)

from .models import (ActivityLog, BillSetting, Branch, Expense, Invoice, Payment, Product,
    Purchase, Role, SaleItem, SystemSetting, Terminal, User)
from .security import hash_password
from .ui import AdminDialog, money


def named(widget, name):
    widget.setObjectName(name); return widget


class ToggleSwitch(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent); self.setFixedSize(44, 24); self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._checked = False; self._position = 2
        self.anim = QPropertyAnimation(self, b"position"); self.anim.setEasingCurve(QEasingCurve.Type.InOutSine); self.anim.setDuration(200)
    @pyqtProperty(int)
    def position(self): return self._position
    @position.setter
    def position(self, pos): self._position = pos; self.update()
    def isChecked(self): return self._checked
    def setChecked(self, checked):
        self._checked = checked; self.anim.setStartValue(self._position)
        self.anim.setEndValue(22 if checked else 2); self.anim.start()
    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton: self.setChecked(not self._checked)
        super().mouseReleaseEvent(e)
    def paintEvent(self, e):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath(); path.addRoundedRect(0, 0, self.width(), self.height(), 12, 12)
        p.fillPath(path, QColor("#1671f8") if self._checked else QColor("#cbd5e1"))
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor("white"))
        p.drawEllipse(self._position, 2, 20, 20)


class LineChartWidget(QWidget):
    def __init__(self, data_points, parent=None):
        super().__init__(parent); self.setMinimumHeight(200); self.data_points = data_points or [0, 0]
    def paintEvent(self, e):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        margin = 30; pw = w - 2 * margin; ph = h - 2 * margin
        if not self.data_points: return
        max_val = max(self.data_points) or 1
        path = QPainterPath(); fill_path = QPainterPath()
        
        step_x = pw / (len(self.data_points) - 1) if len(self.data_points) > 1 else pw
        def pt(i, v): return QPointF(float(margin + i * step_x), float(margin + ph - (v / max_val) * ph))
        
        start = pt(0, self.data_points[0])
        path.moveTo(start); fill_path.moveTo(start.x(), margin + ph); fill_path.lineTo(start)
        
        for i, v in enumerate(self.data_points):
            p_curr = pt(i, v)
            if i > 0: path.lineTo(p_curr); fill_path.lineTo(p_curr)
            
        fill_path.lineTo(p_curr.x(), margin + ph); fill_path.lineTo(start.x(), margin + ph)
        
        # Fill area
        bg_color = QColor("#1671f8"); bg_color.setAlpha(20)
        p.fillPath(fill_path, bg_color)
        
        # Draw line
        pen = p.pen(); pen.setColor(QColor("#1671f8")); pen.setWidth(3); p.setPen(pen)
        p.drawPath(path)
        
        # Draw points
        p.setBrush(QColor("white")); pen.setWidth(2); p.setPen(pen)
        for i, v in enumerate(self.data_points): p.drawEllipse(pt(i, v), 5, 5)


def metric(title, value, note=""):
    card = named(QFrame(), "statCard"); box = QVBoxLayout(card)
    box.addWidget(named(QLabel(title), "statTitle")); box.addWidget(named(QLabel(value), "statValue"))
    
    trend = QHBoxLayout(); trend.setContentsMargins(0, 0, 0, 0)
    trend.addWidget(named(QLabel(note), "statNote")); trend.addStretch()
    
    box.addLayout(trend); return card


def password_error(value):
    if len(value) < 5 or not any(c.isupper() for c in value) or not any(c.islower() for c in value) or not any(c.isdigit() for c in value):
        return "Use at least 5 characters with upper-case, lower-case, and a number."
    return ""


class UserEditor(QDialog):
    def __init__(self, factory, actor, user_id=None, parent=None):
        super().__init__(parent); self.factory=factory; self.actor=actor; self.user_id=user_id
        self.setWindowTitle("Edit User" if user_id else "Add New User"); self.resize(820, 600)
        root=QVBoxLayout(self); root.addWidget(named(QLabel(self.windowTitle()), "title"))
        form=QGridLayout(); self.fields={}
        labels=("Full Name","Email","Phone Number","Username","Password","Confirm Password")
        for i,label in enumerate(labels):
            edit=QLineEdit(); edit.setPlaceholderText(label); self.fields[label]=edit
            if "Password" in label: edit.setEchoMode(QLineEdit.EchoMode.Password)
            r=i//2*2; c=i%2; form.addWidget(QLabel(label+" *"),r,c); form.addWidget(edit,r+1,c)
        root.addLayout(form); root.addWidget(QLabel("Role & Permissions"))
        role_row=QHBoxLayout(); self.role=QComboBox(); self.status=QComboBox(); self.status.addItems(["Active","Inactive"])
        with factory() as s:
            for role in s.scalars(select(Role).order_by(Role.name)): self.role.addItem(role.name,role.id)
            if user_id:
                u=s.get(User,user_id)
                self.fields["Full Name"].setText(u.display_name); self.fields["Email"].setText(u.email)
                self.fields["Phone Number"].setText(u.phone); self.fields["Username"].setText(u.username)
                self.role.setCurrentIndex(max(0,self.role.findData(u.role_id))); self.status.setCurrentIndex(0 if u.active else 1)
        role_row.addWidget(self.role); role_row.addWidget(self.status); root.addLayout(role_row)
        self.permissions=QLabel("Permissions are inherited from the selected role."); self.permissions.setWordWrap(True); root.addWidget(self.permissions)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel|QDialogButtonBox.StandardButton.Save)
        buttons.rejected.connect(self.reject); buttons.accepted.connect(self.save); root.addStretch(); root.addWidget(buttons)
    def save(self):
        f=self.fields; required=["Full Name","Username"] + ([] if self.user_id else ["Password","Confirm Password"])
        if any(not f[x].text().strip() for x in required): QMessageBox.warning(self,"Required","Complete all required fields."); return
        password=f["Password"].text()
        if password or f["Confirm Password"].text():
            if password != f["Confirm Password"].text(): QMessageBox.warning(self,"Password","Passwords do not match."); return
            error=password_error(password)
            if error: QMessageBox.warning(self,"Password",error); return
        with self.factory() as s:
            duplicate=s.scalar(select(User).where(User.username==f["Username"].text().strip(), User.id != (self.user_id or -1)))
            if duplicate: QMessageBox.warning(self,"Username","That username already exists."); return
            u=s.get(User,self.user_id) if self.user_id else User(branch_id=self.actor.branch_id,password_hash="",display_name="",username="",role_id=self.role.currentData())
            u.display_name=f["Full Name"].text().strip(); u.email=f["Email"].text().strip(); u.phone=f["Phone Number"].text().strip()
            u.username=f["Username"].text().strip(); u.role_id=self.role.currentData(); u.active=self.status.currentIndex()==0
            if password: u.password_hash=hash_password(password); u.must_change_password=not bool(self.user_id)
            s.add(u); s.flush(); s.add(ActivityLog(user_id=self.actor.id,action="updated user" if self.user_id else "created user",module="users",details=u.username)); s.commit()
        self.accept()


class UsersPage(QWidget):
    def __init__(self,factory,actor,parent=None):
        super().__init__(parent); self.factory=factory; self.actor=actor; self.page=0; self.page_size=10
        root=QVBoxLayout(self); root.setContentsMargins(20,16,20,18)
        head=QHBoxLayout(); head.setSpacing(12)
        title_box=QVBoxLayout(); title_box.setSpacing(4)
        title_box.addWidget(named(QLabel("Users"),"title")); title_box.addWidget(named(QLabel("Home > Users"),"muted"))
        head.addLayout(title_box); head.addStretch()
        add=QPushButton("+ Add User"); add.setObjectName("primaryButton"); add.clicked.connect(self.add); head.addWidget(add)
        export=QPushButton("Export"); export.clicked.connect(self.export); head.addWidget(export); root.addLayout(head)
        self.cards=QGridLayout(); root.addLayout(self.cards)
        
        filters=QHBoxLayout(); filters.setContentsMargins(0, 16, 0, 16)
        self.search=QLineEdit(); self.search.setPlaceholderText("Search user by name, email or role..."); self.search.textChanged.connect(self.refresh)
        self.filter=QPushButton("Filter"); filters.addWidget(self.search,1); filters.addWidget(self.filter); root.addLayout(filters)
        
        self.table=QTableWidget(0,7); self.table.setHorizontalHeaderLabels(["User","Role","Phone","Status","Last Login","Username","Action"])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setMinimumSectionSize(105)
        root.addWidget(self.table,1)
        
        foot=QHBoxLayout(); foot.setContentsMargins(0, 16, 0, 0)
        self.result=QLabel(); self.result.setObjectName("muted"); foot.addWidget(self.result); foot.addStretch()
        pag_box=QHBoxLayout(); pag_box.setSpacing(8)
        prev=QPushButton("‹"); prev.setObjectName("pageBtn"); prev.clicked.connect(lambda:self.turn(-1))
        nxt=QPushButton("›"); nxt.setObjectName("pageBtn"); nxt.clicked.connect(lambda:self.turn(1))
        pag_box.addWidget(prev); pag_box.addWidget(named(QPushButton("1"), "pageBtnActive")); pag_box.addWidget(nxt); foot.addLayout(pag_box)
        foot.addStretch()
        
        rows_per_page=QHBoxLayout(); rows_per_page.addWidget(named(QLabel("Rows per page:"), "muted"))
        combo=QComboBox(); combo.addItems(["10","20","50"]); rows_per_page.addWidget(combo)
        foot.addLayout(rows_per_page); root.addLayout(foot); self.refresh()
    
    def turn(self,d): self.page=max(0,self.page+d); self.refresh()
    def add(self):
        if UserEditor(self.factory,self.actor,parent=self).exec(): self.refresh()
    def edit(self,user_id):
        if UserEditor(self.factory,self.actor,user_id,self).exec(): self.refresh()
    def disable(self,user_id):
        if user_id==self.actor.id: QMessageBox.warning(self,"User","You cannot disable your own account."); return
        with self.factory() as s:
            u=s.get(User,user_id); u.active=not u.active; s.add(ActivityLog(user_id=self.actor.id,action="changed user status",module="users",details=u.username)); s.commit()
        self.refresh()
    def query(self,s):
        q=select(User,Role.name).join(Role,Role.id==User.role_id); term=self.search.text().strip()
        if term: q=q.where(or_(User.display_name.ilike(f"%{term}%"),User.email.ilike(f"%{term}%"),User.username.ilike(f"%{term}%"),Role.name.ilike(f"%{term}%")))
        return q.order_by(User.display_name)
    def refresh(self):
        with self.factory() as s:
            all_users=s.scalars(select(User)).all(); rows=s.execute(self.query(s)).all()
        while self.cards.count():
            w=self.cards.takeAt(0).widget()
            if w: w.hide(); w.deleteLater()
        active_count=sum(bool(u.active) for u in all_users); inactive_count=len(all_users)-active_count
        with self.factory() as s:
            admin_count=s.scalar(select(func.count(User.id)).join(Role).where(func.lower(Role.name).in_(("administrator","super admin")))) or 0
        values=(("Total Users",len(all_users),"All registered users"),("Active Users",active_count,"Enabled accounts"),("Inactive Users",inactive_count,"Disabled accounts"),("Admins",admin_count,"Administrator accounts"))
        for c,v in enumerate(values): self.cards.addWidget(metric(v[0],str(v[1]),v[2]),0,c)
        start=self.page*self.page_size
        if start>=len(rows) and self.page: self.page-=1; start=self.page*self.page_size
        visible=rows[start:start+self.page_size]; self.table.setRowCount(len(visible))
        for r,(u,role) in enumerate(visible):
            # User Avatar + Name
            user_w = QWidget(); l = QHBoxLayout(user_w); l.setContentsMargins(8,4,8,4); l.setSpacing(12)
            av = QLabel("".join([p[0].upper() for p in u.display_name.split()[:2]] if u.display_name else u.username[:2].upper()))
            av.setFixedSize(36,36); av.setAlignment(Qt.AlignmentFlag.AlignCenter); av.setStyleSheet(f"background: #1671f8; color: white; border-radius: 18px; font-weight: bold; font-size: 13px;")
            l.addWidget(av); l.addWidget(QLabel(u.display_name)); l.addStretch(); self.table.setCellWidget(r, 0, user_w)
            
            self.table.setItem(r,1,QTableWidgetItem(str(role)))
            self.table.setItem(r,2,QTableWidgetItem(str(u.phone)))
            
            # Status Badge
            status_w = QWidget(); sl = QHBoxLayout(status_w); sl.setContentsMargins(8,4,8,4)
            badge = QLabel("Active" if u.active else "Inactive"); badge.setObjectName("statusActive" if u.active else "statusInactive")
            sl.addWidget(badge); sl.addStretch(); self.table.setCellWidget(r, 3, status_w)
            
            self.table.setItem(r,4,QTableWidgetItem(u.last_login_at.strftime("%d/%m/%Y %I:%M %p") if u.last_login_at else "Never"))
            self.table.setItem(r,5,QTableWidgetItem(str(u.username)))
            
            box=QWidget(); lay=QHBoxLayout(box); lay.setContentsMargins(8,4,8,4); lay.setSpacing(4)
            edit=QPushButton("✎"); edit.setObjectName("actionBtn"); edit.setFixedSize(32,32); edit.clicked.connect(lambda _,i=u.id:self.edit(i))
            toggle=QPushButton("🗑"); toggle.setObjectName("actionBtn"); toggle.setFixedSize(32,32); toggle.clicked.connect(lambda _,i=u.id:self.disable(i))
            toggle.setStyleSheet("color: #ef4444;" if u.active else "")
            lay.addWidget(edit); lay.addWidget(toggle); lay.addStretch(); self.table.setCellWidget(r,6,box)
            self.table.setRowHeight(r, 56)
        self.result.setText(f"Showing {start+1 if visible else 0} to {start+len(visible)} of {len(rows)} users")
    def export(self):
        path,_=QFileDialog.getSaveFileName(self,"Export users","users.csv","CSV (*.csv)")
        if not path:return
        with self.factory() as s: rows=s.execute(self.query(s)).all()
        with open(path,"w",newline="",encoding="utf-8-sig") as f:
            out=csv.writer(f); out.writerow(["Name","Email","Phone","Username","Role","Status","Last Login"])
            for u,role in rows: out.writerow([u.display_name,u.email,u.phone,u.username,role,"Active" if u.active else "Inactive",u.last_login_at or ""])


class ReportsPage(QWidget):
    def __init__(self,factory,actor,parent=None):
        super().__init__(parent); self.factory=factory; self.actor=actor
        root=QVBoxLayout(self); root.setContentsMargins(20,16,20,18)
        
        head=QHBoxLayout(); head.setSpacing(12)
        title_box=QVBoxLayout(); title_box.setSpacing(4)
        title_box.addWidget(named(QLabel("Reports"),"title")); title_box.addWidget(named(QLabel("Home > Reports"),"muted"))
        head.addLayout(title_box); head.addStretch()
        
        filter_btn=QPushButton("Filter"); filter_btn.setIcon(QIcon.fromTheme("view-filter")) # fallback to system icon if available
        export=QPushButton("Export Report"); export.clicked.connect(self.export)
        head.addWidget(filter_btn); head.addWidget(export); root.addLayout(head)
        
        filters=QHBoxLayout(); filters.setContentsMargins(0, 16, 0, 16); filters.setSpacing(16)
        
        # Date range picker
        date_lay = QVBoxLayout(); date_lay.setSpacing(4); date_lay.addWidget(named(QLabel("Date Range"), "settingLabel"))
        date_box = QHBoxLayout()
        self.start=QDateEdit(QDate.currentDate().addDays(-30)); self.end=QDateEdit(QDate.currentDate())
        self.start.setCalendarPopup(True); self.end.setCalendarPopup(True)
        date_box.addWidget(self.start); date_box.addWidget(QLabel("-")); date_box.addWidget(self.end)
        date_lay.addLayout(date_box); filters.addLayout(date_lay)
        
        # Terminal combo
        term_lay = QVBoxLayout(); term_lay.setSpacing(4); term_lay.addWidget(named(QLabel("Terminal"), "settingLabel"))
        self.terminal_combo = QComboBox(); self.terminal_combo.addItems(["All Terminals"])
        term_lay.addWidget(self.terminal_combo); filters.addLayout(term_lay)
        
        # Payment combo
        pay_lay = QVBoxLayout(); pay_lay.setSpacing(4); pay_lay.addWidget(named(QLabel("Payment Method"), "settingLabel"))
        self.payment_combo = QComboBox(); self.payment_combo.addItems(["All Payment Methods"])
        pay_lay.addWidget(self.payment_combo); filters.addLayout(pay_lay)
        
        apply=QPushButton("Apply Filter"); apply.setObjectName("primaryButton"); apply.clicked.connect(self.refresh)
        filters.addStretch(); filters.addWidget(apply, 0, Qt.AlignmentFlag.AlignBottom)
        root.addLayout(filters)
        
        self.cards=QGridLayout(); root.addLayout(self.cards)
        
        chart_row = QHBoxLayout(); chart_row.setContentsMargins(0, 16, 0, 16)
        
        # Sales Overview chart
        chart_frame = named(QFrame(), "statCard"); chart_lay = QVBoxLayout(chart_frame)
        chart_lay.addWidget(named(QLabel("Sales Overview"), "settingsSectionTitle"))
        self.chart = LineChartWidget([0, 0])
        chart_lay.addWidget(self.chart); chart_row.addWidget(chart_frame, 2)
        
        # Top Selling Products
        top_frame = named(QFrame(), "statCard"); top_lay = QVBoxLayout(top_frame)
        top_lay.addWidget(named(QLabel("Top Selling Products"), "settingsSectionTitle"))
        self.top_list = QListWidget(); self.top_list.setObjectName("settingsMenu")
        top_lay.addWidget(self.top_list); chart_row.addWidget(top_frame, 1)
        
        root.addLayout(chart_row)
        
        self.table=QTableWidget(); self.table.verticalHeader().setVisible(False); self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        root.addWidget(named(QLabel("Report Summary"), "settingsSectionTitle"))
        root.addWidget(self.table,1); self.refresh()
        
    def data(self):
        start=datetime.combine(self.start.date().toPyDate(),datetime.min.time(),timezone.utc); end=datetime.combine(self.end.date().toPyDate()+timedelta(days=1),datetime.min.time(),timezone.utc)
        with self.factory() as s:
            invoices=s.scalars(select(Invoice).where(Invoice.created_at>=start,Invoice.created_at<end,Invoice.status!="cancelled")).all(); ids=[i.id for i in invoices]
            purchases=s.scalars(select(Purchase).where(Purchase.purchased_at>=start,Purchase.purchased_at<end)).all(); expenses=s.scalars(select(Expense).where(Expense.occurred_at>=start,Expense.occurred_at<end)).all()
            profit=s.scalar(select(func.sum((SaleItem.unit_price_cents-SaleItem.cost_price_cents)*SaleItem.quantity)).where(SaleItem.invoice_id.in_(ids))) if ids else 0
        return invoices,purchases,expenses,profit or 0
    def refresh(self):
        invoices,purchases,expenses,profit=self.data()
        sales=sum(i.total_cents for i in invoices); purchase=sum(p.total_cents for p in purchases); expense=sum(e.amount_cents for e in expenses)
        while self.cards.count():
            w=self.cards.takeAt(0).widget()
            if w: w.hide(); w.deleteLater()
        cards=(("Total Sales",money(sales),f"{len(invoices)} invoices"),("Total Purchases",money(purchase),f"{len(purchases)} purchases"),("Total Profit",money(profit),"Sales margin"),("Total Expenses",money(expense),f"{len(expenses)} expenses"))
        for c,v in enumerate(cards): self.cards.addWidget(metric(v[0],v[1],v[2]),0,c)

        end_date=self.end.date().toPyDate(); start_date=self.start.date().toPyDate()
        bucket_count=min(max(1,(end_date-start_date).days+1),31); bucket_start=end_date-timedelta(days=bucket_count-1); buckets=[0]*bucket_count
        for invoice in invoices:
            idx=(invoice.created_at.date()-bucket_start).days
            if 0 <= idx < bucket_count: buckets[idx]+=invoice.total_cents
        self.chart.data_points=buckets; self.chart.update()
        with self.factory() as s:
            top=s.execute(select(SaleItem.product_name,func.sum(SaleItem.quantity),func.sum(SaleItem.line_total_cents)).where(SaleItem.invoice_id.in_([i.id for i in invoices])).group_by(SaleItem.product_name).order_by(func.sum(SaleItem.line_total_cents).desc()).limit(5)).all() if invoices else []
        self.top_list.clear()
        for name,qty,total in top: self.top_list.addItem(f"{name}   {qty} sold   {money(total or 0)}")
        if not top: self.top_list.addItem("No sales in this date range")

        self.table.setColumnCount(3); self.table.setHorizontalHeaderLabels(["Report Type","Count","Total Amount"])
        rows=[["Total Sales",len(invoices),money(sales)],["Total Purchases",len(purchases),money(purchase)],["Total Profit","-",money(profit)],["Total Expenses",len(expenses),money(expense)]]
        self.table.setRowCount(len(rows))
        for r,row in enumerate(rows):
            for c,v in enumerate(row): self.table.setItem(r,c,QTableWidgetItem(str(v)))
    def export(self):
        path,_=QFileDialog.getSaveFileName(self,"Export report","sales-report.csv","CSV (*.csv)")
        if not path:return
        with open(path,"w",newline="",encoding="utf-8-sig") as f:
            out=csv.writer(f); out.writerow([self.table.horizontalHeaderItem(c).text() for c in range(self.table.columnCount())])
            for r in range(self.table.rowCount()): out.writerow([self.table.item(r,c).text() for c in range(self.table.columnCount())])


class SettingsPage(QWidget):
    KEYS=("Currency","Date Format","Time Format","Language","Time Zone","Items Per Page")
    def __init__(self,factory,actor,parent=None):
        super().__init__(parent); self.factory=factory; self.actor=actor
        root=QVBoxLayout(self); root.setContentsMargins(20,16,20,18)
        head=QVBoxLayout(); head.setSpacing(4)
        head.addWidget(named(QLabel("Settings"),"title"))
        head.addWidget(named(QLabel("Home > Settings"),"muted")); root.addLayout(head)
        
        body=QHBoxLayout(); body.setContentsMargins(0, 16, 0, 0)
        self.menu=QListWidget(); self.menu.setObjectName("settingsMenu")
        self.menu.setFixedWidth(220); self.stack=QStackedWidget(); body.addWidget(self.menu); body.addWidget(self.stack,1); root.addLayout(body,1)
        
        sections=[("General",self.general_page()),("Business Info",self.business_page()),("POS Settings",self.pos_page()),("Invoice Settings",self.invoice_page()),("Tax Settings",self.simple_page("Default Tax Rate (%)","tax_rate","0")),("Payment Methods",self.payment_page()),("Users & Roles",self.roles_page()),("Orders & Returns",self.simple_page("Return window (days)","return_window_days","14")),("Backup & Restore",self.backup_page()),("System",self.system_page())]
        for name,page in sections:
            item = QListWidgetItem(name); self.menu.addItem(item)
            self.stack.addWidget(page)
        self.menu.currentRowChanged.connect(self.stack.setCurrentIndex);self.menu.setCurrentRow(0)
    
    def get(self,key,default=""):
        with self.factory() as s: row=s.get(SystemSetting,key); return row.value if row else default
    
    def put(self,values):
        with self.factory() as s:
            for key,value in values.items(): row=s.get(SystemSetting,key) or SystemSetting(key=key); row.value=str(value); s.add(row)
            s.add(ActivityLog(user_id=self.actor.id,action="updated settings",module="settings",details=", ".join(values)));s.commit()
        QMessageBox.information(self,"Settings","Changes saved.")
    def page(self,title,desc=""):
        frame=named(QFrame(),"statCard"); box=QVBoxLayout(frame); box.setContentsMargins(28,24,28,24); box.setSpacing(8); box.setAlignment(Qt.AlignmentFlag.AlignTop)
        head=QVBoxLayout(); head.setSpacing(4)
        head.addWidget(named(QLabel(title),"settingsSectionTitle"))
        if desc: head.addWidget(named(QLabel(desc),"settingsSectionDesc"))
        box.addLayout(head); return frame,box
    
    def setting_row(self, label, desc, widget):
        row = named(QFrame(), "settingRow"); row.setFixedHeight(64); lay = QHBoxLayout(row); lay.setContentsMargins(0, 6, 0, 6); lay.setSpacing(20)
        text_lay = QVBoxLayout(); text_lay.setSpacing(4)
        title=named(QLabel(label), "settingLabel"); title.setStyleSheet("color:#0f172a;font-weight:700;"); text_lay.addWidget(title)
        if desc:
            sub=named(QLabel(desc), "settingSub"); sub.setStyleSheet("color:#64748b;"); text_lay.addWidget(sub)
        lay.addLayout(text_lay,1); widget.setMinimumHeight(38); lay.addWidget(widget,0,Qt.AlignmentFlag.AlignVCenter)
        return row
    
    def general_page(self):
        page,box=self.page("General Settings", "Configure general preferences for your OilMart POS system.")
        self.general={}
        choices={"Currency":["Rs. (Sri Lankan Rupee) - LKR","₹ (Indian Rupee) - INR","$ (US Dollar) - USD"],"Date Format":["DD / MM / YYYY","YYYY-MM-DD"],"Time Format":["12 Hour (02:30 PM)","24 Hour"],"Language":["English","Sinhala","Tamil"],"Time Zone":["(GMT+05:30) Asia/Colombo","(GMT+05:30) Asia/Kolkata","UTC"],"Items Per Page":["10","25","50","100"]}
        descs={"Currency":"Select your default currency","Date Format":"Choose your preferred date format","Time Format":"Choose your preferred time format","Language":"Select the application language","Time Zone":"Select your default time zone","Items Per Page":"Set number of items per table page"}
        for key in self.KEYS:
            combo=QComboBox();combo.addItems(choices[key]);combo.setMinimumWidth(300)
            value=self.get(key.lower().replace(" ","_"),choices[key][0]);combo.setCurrentText(value)
            self.general[key]=combo; box.addWidget(self.setting_row(key, descs[key], combo))
        self.toggles={}
        for label,desc,key in (("Enable Notifications","Receive system and activity notifications","notifications"),("Enable Sound Alerts","Play sound for notifications and alerts","sound_alerts"),("Automatically Update Stock","Update product stock automatically on sales","auto_stock")):
            check=ToggleSwitch(); check.setChecked(self.get(key,"1")=="1")
            self.toggles[key]=check; box.addWidget(self.setting_row(label, desc, check))
        
        foot=QHBoxLayout(); foot.addStretch()
        save=QPushButton("Save Changes");save.setObjectName("primaryButton")
        save.clicked.connect(lambda:self.put({**{k.lower().replace(' ','_'):v.currentText() for k,v in self.general.items()},**{k:int(v.isChecked()) for k,v in self.toggles.items()}}))
        foot.addWidget(save); box.addLayout(foot); return page
    def business_page(self):
        page,box=self.page("Business Information"); form=QFormLayout(); self.business={}
        with self.factory() as s:b=s.get(Branch,self.actor.branch_id)
        for label,attr in (("Business Name","name"),("Business Email","email"),("Phone Number","phone"),("Alternate Phone","alternate_phone"),("Business Address","address"),("City","city"),("Postal Code","postal_code"),("Tax Number","tax_number"),("NTN / GST Number","gst_number"),("Business Logo","logo_path")):
            edit=QLineEdit(getattr(b,attr,""));self.business[attr]=edit;form.addRow(label,edit)
        browse=QPushButton("Change Logo");browse.clicked.connect(self.choose_logo);form.addRow("",browse);box.addLayout(form);save=QPushButton("Save Changes");save.setObjectName("primaryButton");save.clicked.connect(self.save_business);box.addWidget(save,0,Qt.AlignmentFlag.AlignRight);return page
    def choose_logo(self):
        path,_=QFileDialog.getOpenFileName(self,"Business logo","","Images (*.png *.jpg *.jpeg *.svg)")
        if path:self.business["logo_path"].setText(path)
    def save_business(self):
        with self.factory() as s:
            b=s.get(Branch,self.actor.branch_id)
            for k,w in self.business.items():setattr(b,k,w.text().strip())
            s.add(ActivityLog(user_id=self.actor.id,action="updated business information",module="settings"));s.commit()
        QMessageBox.information(self,"Business Information","Changes saved.")
    def pos_page(self): return self.simple_page("POS Settings - Terminal name","terminal_name","Main Terminal")
    def invoice_page(self):
        page,box=self.page("Invoice Settings");form=QFormLayout();
        with self.factory() as s: setting=s.scalar(select(BillSetting).where(BillSetting.branch_id==self.actor.branch_id))
        self.header=QLineEdit(setting.header_text if setting else "OilMart");self.footer=QLineEdit(setting.footer_text if setting else "Thank you");self.copies=QSpinBox();self.copies.setValue(setting.copies if setting else 1);form.addRow("Header",self.header);form.addRow("Footer",self.footer);form.addRow("Copies",self.copies);box.addLayout(form);save=QPushButton("Save Changes");save.clicked.connect(self.save_invoice);box.addWidget(save);return page
    def save_invoice(self):
        with self.factory() as s:
            row=s.scalar(select(BillSetting).where(BillSetting.branch_id==self.actor.branch_id)) or BillSetting(branch_id=self.actor.branch_id);row.header_text=self.header.text();row.footer_text=self.footer.text();row.copies=self.copies.value();s.add(row);s.commit()
        QMessageBox.information(self,"Invoice Settings","Changes saved.")
    def simple_page(self,title,key,default):
        page,box=self.page(title);edit=QLineEdit(self.get(key,default));box.addWidget(edit);save=QPushButton("Save Changes");save.clicked.connect(lambda:self.put({key:edit.text()}));box.addWidget(save);return page
    def payment_page(self):
        page,box=self.page("Payment Methods");checks={}
        for key in ("Cash","Card","Credit","Other"): c=QCheckBox(key);c.setChecked(self.get("payment_"+key.lower(),"1")=="1");checks[key]=c;box.addWidget(c)
        save=QPushButton("Save Changes");save.clicked.connect(lambda:self.put({"payment_"+k.lower():int(v.isChecked()) for k,v in checks.items()}));box.addWidget(save);return page
    def roles_page(self):
        page,box=self.page("Users & Roles");box.addWidget(QLabel("Manage role permissions and administrator access."));button=QPushButton("Open Role Manager");button.clicked.connect(lambda:AdminDialog(self.factory,self.actor,self).exec());box.addWidget(button);return page
    def backup_page(self):
        page,box=self.page("Backup & Restore");backup=QPushButton("Create Database Backup");backup.clicked.connect(self.backup);restore=QPushButton("Restore Database Backup");restore.clicked.connect(self.restore);box.addWidget(backup);box.addWidget(restore);box.addStretch();return page
    def db_path(self): return self.factory.kw["bind"].url.database
    def backup(self):
        path,_=QFileDialog.getSaveFileName(self,"Database backup",f"oilmart-backup-{datetime.now():%Y%m%d-%H%M}.db","SQLite (*.db)")
        if not path:return
        engine=self.factory.kw["bind"]
        if engine.dialect.name!="sqlite": QMessageBox.information(self,"Backup","Use pg_dump or your PostgreSQL provider's managed backup service.");return
        with sqlite3.connect(self.db_path()) as source, sqlite3.connect(path) as destination: source.backup(destination)
        QMessageBox.information(self,"Backup","Backup created successfully.")
    def restore(self):
        path,_=QFileDialog.getOpenFileName(self,"Restore database","","SQLite (*.db)")
        if not path:return
        if QMessageBox.question(self,"Restore","Replace the current database? The application must restart.")!=QMessageBox.StandardButton.Yes:return
        safety=self.db_path()+".before-restore";shutil.copy2(self.db_path(),safety);self.factory.kw["bind"].dispose();shutil.copy2(path,self.db_path());QMessageBox.information(self,"Restore","Database restored. Restart OilMart now.")
    def system_page(self):
        page,box=self.page("System");box.addWidget(QLabel(f"Database: {self.db_path()}\nApplication: OilMart POS\nStorage: SQLite offline database\nSync: Pending cloud configuration"));box.addStretch();return page
