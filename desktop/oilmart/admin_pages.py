from __future__ import annotations

import csv
import os
import shutil
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_, select
from PyQt6.QtCore import QDate, Qt
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QDateEdit, QDialog, QDialogButtonBox,
    QFileDialog, QFormLayout, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QListWidget, QMessageBox, QPushButton, QSpinBox, QStackedWidget,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from .models import (ActivityLog, BillSetting, Branch, Expense, Invoice, Payment, Product,
    Purchase, Role, SaleItem, SystemSetting, Terminal, User)
from .security import hash_password
from .ui import AdminDialog, money


def named(widget, name):
    widget.setObjectName(name); return widget


def metric(title, value, note=""):
    card = named(QFrame(), "card"); box = QVBoxLayout(card)
    box.addWidget(named(QLabel(title), "metricTitle")); box.addWidget(named(QLabel(value), "metricValue"))
    box.addWidget(named(QLabel(note), "muted")); return card


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
        head=QHBoxLayout(); head.addWidget(named(QLabel("Users"),"title")); head.addStretch()
        add=QPushButton("+ Add User"); add.setObjectName("primaryButton"); add.clicked.connect(self.add); head.addWidget(add)
        export=QPushButton("Export"); export.clicked.connect(self.export); head.addWidget(export); root.addLayout(head)
        self.cards=QGridLayout(); root.addLayout(self.cards)
        filters=QHBoxLayout(); self.search=QLineEdit(); self.search.setPlaceholderText("Search user by name, email or role..."); self.search.textChanged.connect(self.refresh)
        self.filter=QComboBox(); self.filter.addItems(["All Status","Active","Inactive"]); self.filter.currentIndexChanged.connect(self.refresh); filters.addWidget(self.search,1); filters.addWidget(self.filter); root.addLayout(filters)
        self.table=QTableWidget(0,7); self.table.setHorizontalHeaderLabels(["User","Email / Phone","Role","Status","Last Login","Username","Action"]); self.table.horizontalHeader().setSectionResizeMode(0,QHeaderView.ResizeMode.Stretch); root.addWidget(self.table,1)
        foot=QHBoxLayout(); self.result=QLabel(); foot.addWidget(self.result); foot.addStretch(); prev=QPushButton("‹"); prev.clicked.connect(lambda:self.turn(-1)); nxt=QPushButton("›"); nxt.clicked.connect(lambda:self.turn(1)); foot.addWidget(prev); foot.addWidget(nxt); root.addLayout(foot); self.refresh()
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
        if self.filter.currentIndex(): q=q.where(User.active.is_(self.filter.currentIndex()==1))
        return q.order_by(User.display_name)
    def refresh(self):
        with self.factory() as s:
            all_users=s.scalars(select(User)).all(); rows=s.execute(self.query(s)).all()
        while self.cards.count(): w=self.cards.takeAt(0).widget(); w.deleteLater() if w else None
        values=(("Total Users",len(all_users),"All registered users"),("Active Users",sum(u.active for u in all_users),"Available to sign in"),("Inactive Users",sum(not u.active for u in all_users),"Access disabled"),("Admins",sum(role.lower() in ("administrator","super admin") for _,role in rows),"Privileged users"))
        for c,v in enumerate(values): self.cards.addWidget(metric(v[0],str(v[1]),v[2]),0,c)
        start=self.page*self.page_size
        if start>=len(rows) and self.page: self.page-=1; start=self.page*self.page_size
        visible=rows[start:start+self.page_size]; self.table.setRowCount(len(visible))
        for r,(u,role) in enumerate(visible):
            vals=[u.display_name,f"{u.email}\n{u.phone}",role,"Active" if u.active else "Inactive",u.last_login_at.strftime("%Y-%m-%d %H:%M") if u.last_login_at else "Never",u.username]
            for c,v in enumerate(vals): self.table.setItem(r,c,QTableWidgetItem(str(v)))
            box=QWidget(); lay=QHBoxLayout(box); lay.setContentsMargins(0,0,0,0); edit=QPushButton("Edit"); edit.clicked.connect(lambda _,i=u.id:self.edit(i)); toggle=QPushButton("Disable" if u.active else "Enable"); toggle.clicked.connect(lambda _,i=u.id:self.disable(i)); lay.addWidget(edit); lay.addWidget(toggle); self.table.setCellWidget(r,6,box)
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
        head=QHBoxLayout(); head.addWidget(named(QLabel("Reports"),"title")); head.addStretch(); self.start=QDateEdit(QDate.currentDate().addDays(-30)); self.end=QDateEdit(QDate.currentDate()); self.start.setCalendarPopup(True); self.end.setCalendarPopup(True); apply=QPushButton("Apply Filter"); apply.setObjectName("primaryButton"); apply.clicked.connect(self.refresh); export=QPushButton("Export Report"); export.clicked.connect(self.export); head.addWidget(self.start); head.addWidget(self.end); head.addWidget(apply); head.addWidget(export); root.addLayout(head)
        self.cards=QGridLayout(); root.addLayout(self.cards); self.tabs=QComboBox(); self.tabs.addItems(["Report Overview","Daily Sales Report"]); self.tabs.currentIndexChanged.connect(self.refresh); root.addWidget(self.tabs)
        self.table=QTableWidget(); self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch); root.addWidget(self.table,1); self.refresh()
    def data(self):
        start=datetime.combine(self.start.date().toPyDate(),datetime.min.time(),timezone.utc); end=datetime.combine(self.end.date().toPyDate()+timedelta(days=1),datetime.min.time(),timezone.utc)
        with self.factory() as s:
            invoices=s.scalars(select(Invoice).where(Invoice.created_at>=start,Invoice.created_at<end,Invoice.status!="cancelled")).all(); ids=[i.id for i in invoices]
            purchases=s.scalars(select(Purchase).where(Purchase.purchased_at>=start,Purchase.purchased_at<end)).all(); expenses=s.scalars(select(Expense).where(Expense.occurred_at>=start,Expense.occurred_at<end)).all()
            profit=s.scalar(select(func.sum((SaleItem.unit_price_cents-SaleItem.cost_price_cents)*SaleItem.quantity)).where(SaleItem.invoice_id.in_(ids))) if ids else 0
        return invoices,purchases,expenses,profit or 0
    def refresh(self):
        invoices,purchases,expenses,profit=self.data(); sales=sum(i.total_cents for i in invoices); purchase=sum(p.total_cents for p in purchases); expense=sum(e.amount_cents for e in expenses)
        while self.cards.count(): w=self.cards.takeAt(0).widget(); w.deleteLater() if w else None
        for c,v in enumerate((("Total Sales",money(sales)),("Total Purchases",money(purchase)),("Gross Profit",money(profit)),("Total Expenses",money(expense)))): self.cards.addWidget(metric(v[0],v[1],"Selected period"),0,c)
        if self.tabs.currentIndex()==0:
            self.table.setColumnCount(4); self.table.setHorizontalHeaderLabels(["Report Type","Count","Total Amount","Notes"]); rows=[["Total Sales",len(invoices),money(sales),"Paid and pending invoices"],["Total Purchases",len(purchases),money(purchase),"Supplier invoices"],["Gross Profit","-",money(profit),"Sales less product cost"],["Expenses",len(expenses),money(expense),"Recorded expenses"]]
        else:
            daily={}
            for i in invoices:
                key=i.created_at.date(); daily.setdefault(key,[0,0,0]); daily[key][0]+=1; daily[key][1]+=i.total_cents
            self.table.setColumnCount(5); self.table.setHorizontalHeaderLabels(["Date","Orders","Total Sales","Total Profit","Average Order Value"]); rows=[]
            for day,v in sorted(daily.items(),reverse=True): rows.append([day.strftime("%d/%m/%Y"),v[0],money(v[1]),"See overview",money(v[1]//v[0])])
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
        root=QVBoxLayout(self); root.setContentsMargins(20,16,20,18); root.addWidget(named(QLabel("Settings"),"title")); body=QHBoxLayout(); self.menu=QListWidget(); self.menu.setFixedWidth(220); self.stack=QStackedWidget(); body.addWidget(self.menu); body.addWidget(self.stack,1); root.addLayout(body,1)
        sections=[("General",self.general_page()),("Business Info",self.business_page()),("POS Settings",self.pos_page()),("Invoice Settings",self.invoice_page()),("Tax Settings",self.simple_page("Default Tax Rate (%)","tax_rate","0")),("Payment Methods",self.payment_page()),("Users & Roles",self.roles_page()),("Orders & Returns",self.simple_page("Return window (days)","return_window_days","14")),("Backup & Restore",self.backup_page()),("System",self.system_page())]
        for name,page in sections:self.menu.addItem(name);self.stack.addWidget(page)
        self.menu.currentRowChanged.connect(self.stack.setCurrentIndex);self.menu.setCurrentRow(0)
    def get(self,key,default=""):
        with self.factory() as s: row=s.get(SystemSetting,key); return row.value if row else default
    def put(self,values):
        with self.factory() as s:
            for key,value in values.items(): row=s.get(SystemSetting,key) or SystemSetting(key=key); row.value=str(value); s.add(row)
            s.add(ActivityLog(user_id=self.actor.id,action="updated settings",module="settings",details=", ".join(values)));s.commit()
        QMessageBox.information(self,"Settings","Changes saved.")
    def page(self,title): frame=named(QFrame(),"panel"); box=QVBoxLayout(frame); box.addWidget(QLabel(title)); return frame,box
    def general_page(self):
        page,box=self.page("General Settings"); form=QFormLayout(); self.general={}
        choices={"Currency":["Rs. (Sri Lankan Rupee) - LKR","₹ (Indian Rupee) - INR","$ (US Dollar) - USD"],"Date Format":["DD / MM / YYYY","YYYY-MM-DD"],"Time Format":["12 Hour","24 Hour"],"Language":["English","Sinhala","Tamil"],"Time Zone":["(GMT+05:30) Asia/Colombo","UTC"],"Items Per Page":["10","25","50","100"]}
        for key in self.KEYS: combo=QComboBox();combo.addItems(choices[key]);value=self.get(key.lower().replace(" ","_"),choices[key][0]);combo.setCurrentText(value);self.general[key]=combo;form.addRow(key,combo)
        self.toggles={}
        for label,key in (("Enable Notifications","notifications"),("Enable Sound Alerts","sound_alerts"),("Automatically Update Stock","auto_stock")): check=QCheckBox();check.setChecked(self.get(key,"1")=="1");self.toggles[key]=check;form.addRow(label,check)
        box.addLayout(form);save=QPushButton("Save Changes");save.setObjectName("primaryButton");save.clicked.connect(lambda:self.put({**{k.lower().replace(' ','_'):v.currentText() for k,v in self.general.items()},**{k:int(v.isChecked()) for k,v in self.toggles.items()}}));box.addWidget(save,0,Qt.AlignmentFlag.AlignRight);return page
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
        if path: shutil.copy2(self.db_path(),path);QMessageBox.information(self,"Backup","Backup created successfully.")
    def restore(self):
        path,_=QFileDialog.getOpenFileName(self,"Restore database","","SQLite (*.db)")
        if not path:return
        if QMessageBox.question(self,"Restore","Replace the current database? The application must restart.")!=QMessageBox.StandardButton.Yes:return
        safety=self.db_path()+".before-restore";shutil.copy2(self.db_path(),safety);self.factory.kw["bind"].dispose();shutil.copy2(path,self.db_path());QMessageBox.information(self,"Restore","Database restored. Restart OilMart now.")
    def system_page(self):
        page,box=self.page("System");box.addWidget(QLabel(f"Database: {self.db_path()}\nApplication: OilMart POS\nStorage: SQLite offline database\nSync: Pending cloud configuration"));box.addStretch();return page
