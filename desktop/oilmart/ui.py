from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import or_, select

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction, QFont
from PyQt6.QtWidgets import (
    QAbstractItemView, QApplication, QComboBox, QDialog, QDialogButtonBox,
    QFormLayout, QFrame, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMainWindow, QMessageBox, QPushButton, QSpinBox, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget, QListWidget, QInputDialog,
    QPlainTextEdit, QCheckBox, QDoubleSpinBox, QGridLayout, QScrollArea
)

from .models import ActivityLog, BillSetting, Branch, Category, Customer, Invoice, Product, Terminal, User, Role, Permission, RolePermission
from .receipt import PrinterError, print_receipt, receipt_data, render_receipt
from .security import PermissionDenied, authenticate, change_password, hash_password, permission_keys
from .services import CartLine, CheckoutError, checkout, create_customer
from .shifts import ShiftError, active_shift, close_shift, open_shift

import os

def _load_style() -> str:
    path = os.path.join(os.path.dirname(__file__), "style.qss")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return ""

MODERN_STYLE = _load_style()

def money(cents: int) -> str:
    return f"Rs. {cents / 100:,.2f}"


class ChangePasswordDialog(QDialog):
    def __init__(self, parent=None, *, title="Create your new password", temporary=False):
        super().__init__(parent)
        self.new_password = ""
        self.setWindowTitle("Change temporary password")
        self.setMinimumWidth(480)
        self.setStyleSheet(MODERN_STYLE)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.setSpacing(14)
        heading = QLabel(title)
        heading.setObjectName("titleLabel")
        layout.addWidget(heading)
        instructions = QLabel(
            (("The user will be required to change this password at first login.\n" if temporary else
              "Your temporary password must be changed before continuing.\n")) +
            "Use at least 5 characters, including an upper-case letter, "
            "a lower-case letter, and a number."
        )
        instructions.setWordWrap(True)
        layout.addWidget(instructions)
        form = QFormLayout()
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setPlaceholderText("New password")
        self.confirm = QLineEdit()
        self.confirm.setEchoMode(QLineEdit.EchoMode.Password)
        self.confirm.setPlaceholderText("Enter the same password again")
        self.confirm.returnPressed.connect(self.validate)
        form.addRow("Temporary password" if temporary else "New password", self.password)
        form.addRow("Re-enter password", self.confirm)
        layout.addLayout(form)
        self.error = QLabel("")
        self.error.setObjectName("errorLabel")
        self.error.setWordWrap(True)
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Change password")
        buttons.accepted.connect(self.validate)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.password.setFocus()

    def validate(self):
        password = self.password.text()
        if len(password) < 5:
            self.error.setText("Password must contain at least 5 characters.")
        elif not any(char.isupper() for char in password):
            self.error.setText("Add at least one upper-case letter.")
        elif not any(char.islower() for char in password):
            self.error.setText("Add at least one lower-case letter.")
        elif not any(char.isdigit() for char in password):
            self.error.setText("Add at least one number.")
        elif password != self.confirm.text():
            self.error.setText("The two passwords do not match.")
        else:
            self.new_password = password
            self.accept()
            return
        self.password.selectAll()
        self.password.setFocus()


class LoginDialog(QDialog):
    def __init__(self, session_factory):
        super().__init__()
        self.session_factory = session_factory
        self.user: User | None = None
        self.setWindowTitle("OilMart POS — Sign In")
        self.setFixedSize(1000, 650)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.CustomizeWindowHint | Qt.WindowType.WindowCloseButtonHint)
        
        LIGHT_STYLE = """
        QDialog { background-color: #f8fafc; }
        QLabel { color: #1e293b; font-family: 'Inter', 'Segoe UI', sans-serif; }
        QLineEdit { 
            padding: 6px 16px; 
            min-height: 32px;
            border: 1px solid #cbd5e1; 
            border-radius: 8px; 
            background-color: #ffffff; 
            color: #0f172a; 
            font-size: 14px;
        }
        QLineEdit:focus { border: 1px solid #3b82f6; outline: none; }
        QPushButton#signInBtn { 
            background-color: #2563eb; 
            color: white; 
            border: none; 
            border-radius: 8px; 
            padding: 8px; 
            min-height: 32px;
            font-weight: bold; 
            font-size: 15px; 
        }
        QPushButton#signInBtn:hover { background-color: #1d4ed8; }
        QPushButton#qrBtn {
            background-color: transparent;
            color: #475569;
            border: 1px solid #cbd5e1;
            border-radius: 8px;
            padding: 8px;
            min-height: 32px;
            font-weight: 500;
        }
        QPushButton#qrBtn:hover { background-color: #f1f5f9; }
        QCheckBox { color: #475569; font-weight: 500; }
        """
        self.setStyleSheet(LIGHT_STYLE)

        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        left_pane = QWidget()
        left_pane.setStyleSheet("background-color: #ffffff;")
        left_layout = QVBoxLayout(left_pane)
        left_layout.setContentsMargins(60, 60, 60, 60)
        left_layout.setSpacing(16)

        brand = QHBoxLayout()
        icon = QLabel("💧")
        icon.setStyleSheet("font-size: 32px;")
        brand_label = QLabel("OilMart POS")
        brand_label.setStyleSheet("font-size: 28px; font-weight: 900; color: #0f172a;")
        brand.addWidget(icon)
        brand.addWidget(brand_label)
        brand.addStretch()
        left_layout.addLayout(brand)
        
        left_layout.addSpacing(20)
        
        welcome = QLabel("Welcome back!")
        welcome.setStyleSheet("font-size: 24px; font-weight: bold;")
        left_layout.addWidget(welcome)
        sub = QLabel("Sign in to continue to your account")
        sub.setStyleSheet("color: #64748b; font-size: 14px;")
        left_layout.addWidget(sub)

        left_layout.addSpacing(10)

        user_label = QLabel("Username")
        user_label.setStyleSheet("font-size: 13px; font-weight: 600;")
        left_layout.addWidget(user_label)
        self.username = QLineEdit("admin")
        self.username.setPlaceholderText("Enter username")
        left_layout.addWidget(self.username)

        pass_label = QLabel("Password")
        pass_label.setStyleSheet("font-size: 13px; font-weight: 600;")
        left_layout.addWidget(pass_label)
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setPlaceholderText("Enter password")
        self.password.returnPressed.connect(self.authenticate)
        left_layout.addWidget(self.password)

        options_layout = QHBoxLayout()
        rem_check = QCheckBox("Remember me")
        rem_check.setChecked(True)
        options_layout.addWidget(rem_check)
        forgot_btn = QPushButton("Forgot password?")
        forgot_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        forgot_btn.setStyleSheet("color: #2563eb; background: transparent; border: none; text-align: right; font-weight: 500;")
        options_layout.addWidget(forgot_btn, alignment=Qt.AlignmentFlag.AlignRight)
        left_layout.addLayout(options_layout)

        self.error = QLabel("")
        self.error.setStyleSheet("color: #ef4444; font-size: 13px; font-weight: 600;")
        left_layout.addWidget(self.error)

        sign_in = QPushButton("Sign In →")
        sign_in.setObjectName("signInBtn")
        sign_in.setCursor(Qt.CursorShape.PointingHandCursor)
        sign_in.clicked.connect(self.authenticate)
        left_layout.addWidget(sign_in)

        div_layout = QHBoxLayout()
        line1 = QFrame(); line1.setFrameShape(QFrame.Shape.HLine); line1.setStyleSheet("color: #e2e8f0;")
        or_label = QLabel("or"); or_label.setStyleSheet("color: #94a3b8; font-size: 12px;")
        line2 = QFrame(); line2.setFrameShape(QFrame.Shape.HLine); line2.setStyleSheet("color: #e2e8f0;")
        div_layout.addWidget(line1); div_layout.addWidget(or_label); div_layout.addWidget(line2)
        left_layout.addLayout(div_layout)

        qr_btn = QPushButton("Scan QR Code to Login")
        qr_btn.setObjectName("qrBtn")
        qr_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        left_layout.addWidget(qr_btn)
        
        left_layout.addStretch()

        footer = QHBoxLayout()
        f1 = QLabel("© 2026 OilMart POS. All rights reserved.")
        f1.setStyleSheet("color: #94a3b8; font-size: 11px;")
        f2 = QLabel("Version 1.0.0")
        f2.setStyleSheet("color: #94a3b8; font-size: 11px;")
        footer.addWidget(f1); footer.addStretch(); footer.addWidget(f2)
        left_layout.addLayout(footer)

        right_pane = QLabel()
        right_pane.setStyleSheet("background-color: #f8fafc;")
        from PyQt6.QtGui import QPixmap
        import os
        img_path = r"C:\Users\gimha\.gemini\antigravity-ide\brain\4342073d-9fca-4e32-8bed-bbb48403916a\pos_promo_graphic_1785783539852.png"
        if os.path.exists(img_path):
            pixmap = QPixmap(img_path)
            scaled = pixmap.scaled(500, 650, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
            right_pane.setPixmap(scaled)
            right_pane.setAlignment(Qt.AlignmentFlag.AlignCenter)
        else:
            right_pane.setText("Manage your business with confidence")
            right_pane.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        main_layout.addWidget(left_pane, 1)
        main_layout.addWidget(right_pane, 1)

    def authenticate(self):
        with self.session_factory() as session:
            user, error = authenticate(session, self.username.text(), self.password.text())
            if user is None:
                self.error.setText(error)
                self.password.selectAll()
                return
            if user.must_change_password:
                password_dialog = ChangePasswordDialog(self)
                if password_dialog.exec() != QDialog.DialogCode.Accepted:
                    self.error.setText("You must change the temporary administrator password")
                    return
                try:
                    change_password(session, user, self.password.text(), password_dialog.new_password)
                except ValueError as exc:
                    self.error.setText(str(exc))
                    return
            session.expunge(user)
            self.user = user
        self.accept()


class PaymentDialog(QDialog):
    def __init__(self, total_cents: int, parent=None, initial_method: str = "Cash"):
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
        self.method.setCurrentText(initial_method)
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


class ReceiptDialog(QDialog):
    def __init__(self, session_factory, invoice_id: int, parent=None):
        super().__init__(parent)
        self.session_factory = session_factory
        self.invoice_id = invoice_id
        self.setWindowTitle("Receipt preview & thermal printing")
        self.setStyleSheet(MODERN_STYLE)
        self.resize(580, 720)
        layout = QVBoxLayout(self)
        title = QLabel("Thermal receipt")
        title.setObjectName("titleLabel")
        layout.addWidget(title)

        form = QFormLayout()
        self.printer_name = QLineEdit()
        self.printer_name.setPlaceholderText("Windows printer name, e.g. EPSON TM-T20III")
        self.paper_width = QComboBox()
        self.paper_width.addItems(["58mm", "80mm"])
        self.copies = QSpinBox()
        self.copies.setRange(1, 5)
        self.auto_print = QCheckBox("Automatically print after each completed sale")
        form.addRow("Printer", self.printer_name)
        form.addRow("Paper width", self.paper_width)
        form.addRow("Copies", self.copies)
        form.addRow("", self.auto_print)
        layout.addLayout(form)

        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setStyleSheet("font-family: Consolas, monospace; background: white;")
        layout.addWidget(self.preview)
        buttons = QHBoxLayout()
        save = QPushButton("Save settings")
        save.clicked.connect(lambda: self.save_settings(notify=True))
        print_button = QPushButton("Print receipt")
        print_button.setObjectName("primaryButton")
        print_button.clicked.connect(self.print_now)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        buttons.addWidget(save)
        buttons.addStretch()
        buttons.addWidget(print_button)
        buttons.addWidget(close)
        layout.addLayout(buttons)
        self.paper_width.currentTextChanged.connect(self.refresh_preview)
        self._load()

    def _load(self):
        with self.session_factory() as session:
            invoice = session.get(Invoice, self.invoice_id)
            branch = session.get(Branch, invoice.branch_id)
            cashier = session.get(User, invoice.cashier_id)
            settings = session.scalar(select(BillSetting).where(BillSetting.branch_id == invoice.branch_id))
            self.data = receipt_data(invoice, branch, cashier)
            self.header_text = settings.header_text
            self.footer_text = settings.footer_text
            self.show_tax = settings.show_tax
            self.show_discount = settings.show_discount
            self.printer_name.setText(settings.printer_name)
            self.paper_width.setCurrentText(f"{settings.paper_width_mm}mm")
            self.copies.setValue(settings.copies)
            self.auto_print.setChecked(settings.auto_print)
        self.refresh_preview()

    def _settings_view(self):
        return type("ReceiptSettings", (), {
            "paper_width_mm": int(self.paper_width.currentText().removesuffix("mm")),
            "header_text": self.header_text,
            "footer_text": self.footer_text,
            "show_tax": self.show_tax,
            "show_discount": self.show_discount,
        })()

    def refresh_preview(self):
        self.receipt_text = render_receipt(self.data, self._settings_view())
        self.preview.setPlainText(self.receipt_text)

    def save_settings(self, notify=True):
        with self.session_factory() as session:
            invoice = session.get(Invoice, self.invoice_id)
            settings = session.scalar(select(BillSetting).where(BillSetting.branch_id == invoice.branch_id))
            settings.printer_name = self.printer_name.text().strip()
            settings.paper_width_mm = int(self.paper_width.currentText().removesuffix("mm"))
            settings.copies = self.copies.value()
            settings.auto_print = self.auto_print.isChecked()
            session.commit()
        if notify:
            QMessageBox.information(self, "Saved", "Receipt printer settings saved.")

    def print_now(self):
        self.save_settings(notify=False)
        try:
            print_receipt(self.printer_name.text().strip(), self.receipt_text, self.copies.value())
        except PrinterError as exc:
            QMessageBox.warning(self, "Printing failed", str(exc))
            return
        QMessageBox.information(self, "Printed", "Receipt sent to the thermal printer.")


class UserManagementDialog(QDialog):
    def __init__(self, session_factory, current_user: User, parent=None):
        super().__init__(parent)
        self.session_factory = session_factory
        self.current_user = current_user
        self.setWindowTitle("User Management")
        self.setMinimumSize(900, 560)
        self.setStyleSheet(MODERN_STYLE)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        title = QLabel("All Users")
        title.setObjectName("titleLabel")
        layout.addWidget(title)
        subtitle = QLabel("Create accounts, assign roles, and control login access.")
        subtitle.setObjectName("subtitleLabel")
        layout.addWidget(subtitle)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["Username", "Display name", "Role", "Branch", "Status", "Password"]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table)
        controls = QHBoxLayout()
        add = QPushButton("Add user")
        add.setObjectName("primaryButton")
        add.clicked.connect(self.add_user)
        role = QPushButton("Change role")
        role.clicked.connect(self.change_role)
        status = QPushButton("Enable / disable")
        status.clicked.connect(self.toggle_status)
        reset = QPushButton("Reset password")
        reset.clicked.connect(self.reset_password)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        for button in (add, role, status, reset):
            controls.addWidget(button)
        controls.addStretch()
        controls.addWidget(close)
        layout.addLayout(controls)
        self.refresh()

    def refresh(self):
        with self.session_factory() as session:
            rows = session.execute(
                select(User, Role.name, Branch.name)
                .join(Role, Role.id == User.role_id)
                .join(Branch, Branch.id == User.branch_id)
                .order_by(User.username)
            ).all()
        self.table.setRowCount(len(rows))
        for row_number, (user, role_name, branch_name) in enumerate(rows):
            values = (
                user.username, user.display_name, role_name, branch_name,
                "Active" if user.active else "Disabled",
                "Change required" if user.must_change_password else "Configured",
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, user.id)
                self.table.setItem(row_number, column, item)

    def selected_user_id(self) -> int | None:
        row = self.table.currentRow()
        return None if row < 0 else self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)

    def _temporary_password(self, title: str) -> str | None:
        dialog = ChangePasswordDialog(self, title=title, temporary=True)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        return dialog.new_password

    def add_user(self):
        username, ok = QInputDialog.getText(self, "Add user", "Username:")
        if not ok or not username.strip():
            return
        display_name, ok = QInputDialog.getText(self, "Add user", "Display name:")
        if not ok or not display_name.strip():
            return
        with self.session_factory() as session:
            roles = session.scalars(select(Role).order_by(Role.name)).all()
        role_name, ok = QInputDialog.getItem(self, "Add user", "Role:", [r.name for r in roles], 0, False)
        if not ok:
            return
        password = self._temporary_password("Add user")
        if password is None:
            return
        role = next(r for r in roles if r.name == role_name)
        with self.session_factory() as session:
            user = User(username=username.strip(), display_name=display_name.strip(),
                        password_hash=hash_password(password), role_id=role.id,
                        branch_id=self.current_user.branch_id, must_change_password=True)
            session.add(user)
            try:
                session.flush()
                session.add(ActivityLog(user_id=self.current_user.id, action="created user",
                    module="administration", details=f"{user.username} ({role.name})"))
                session.commit()
            except Exception:
                session.rollback()
                QMessageBox.warning(self, "Cannot create user", "That username may already be in use.")
                return
        self.refresh()

    def change_role(self):
        user_id = self.selected_user_id()
        if user_id is None:
            QMessageBox.information(self, "Select user", "Select a user first.")
            return
        with self.session_factory() as session:
            user = session.get(User, user_id)
            roles = session.scalars(select(Role).order_by(Role.name)).all()
            current = next((i for i, role in enumerate(roles) if role.id == user.role_id), 0)
            role_name, ok = QInputDialog.getItem(
                self, "Change role", f"Role for {user.username}:", [r.name for r in roles], current, False
            )
            if not ok:
                return
            role = next(r for r in roles if r.name == role_name)
            user.role_id = role.id
            session.add(ActivityLog(user_id=self.current_user.id, action="changed user role",
                module="administration", details=f"{user.username}: {role.name}"))
            session.commit()
        self.refresh()

    def toggle_status(self):
        user_id = self.selected_user_id()
        if user_id is None:
            QMessageBox.information(self, "Select user", "Select a user first.")
            return
        if user_id == self.current_user.id:
            QMessageBox.warning(self, "Not allowed", "You cannot disable your own account.")
            return
        with self.session_factory() as session:
            user = session.get(User, user_id)
            user.active = not user.active
            session.add(ActivityLog(user_id=self.current_user.id, action="enabled user" if user.active else "disabled user",
                                    module="administration", details=user.username))
            session.commit()
        self.refresh()

    def reset_password(self):
        user_id = self.selected_user_id()
        if user_id is None:
            QMessageBox.information(self, "Select user", "Select a user first.")
            return
        password = self._temporary_password("Reset password")
        if password is None:
            return
        with self.session_factory() as session:
            user = session.get(User, user_id)
            user.password_hash = hash_password(password)
            user.must_change_password = True
            user.failed_login_attempts = 0
            user.locked_until = None
            session.add(ActivityLog(user_id=self.current_user.id, action="reset user password",
                                    module="administration", details=user.username))
            session.commit()
        self.refresh()
        QMessageBox.information(self, "Password reset", "The user must change this password at next login.")


class AdminDialog(QDialog):
    def __init__(self, session_factory, current_user: User, parent=None):
        super().__init__(parent)
        self.session_factory = session_factory
        self.current_user = current_user
        self.setWindowTitle("Administration")
        self.setStyleSheet(MODERN_STYLE)
        self.setMinimumSize(700, 500)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)
        
        title = QLabel("Role & Permission Management")
        title.setObjectName("titleLabel")
        layout.addWidget(title)
        
        split = QHBoxLayout()
        
        left = QVBoxLayout()
        left.addWidget(QLabel("Roles"))
        self.roles_list = QListWidget()
        self.roles_list.currentRowChanged.connect(self._role_selected)
        left.addWidget(self.roles_list)
        
        add_role_btn = QPushButton("Add Role")
        add_role_btn.clicked.connect(self._add_role)
        left.addWidget(add_role_btn)
        add_user_btn = QPushButton("Add User")
        add_user_btn.clicked.connect(self._add_user)
        left.addWidget(add_user_btn)
        split.addLayout(left, 1)
        
        right = QVBoxLayout()
        right.addWidget(QLabel("Permissions"))
        self.perms_table = QTableWidget(0, 2)
        self.perms_table.setHorizontalHeaderLabels(["Enabled", "Permission Key"])
        self.perms_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.perms_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        right.addWidget(self.perms_table)
        
        self.save_btn = QPushButton("Save Permissions")
        self.save_btn.setObjectName("primaryButton")
        self.save_btn.clicked.connect(self._save_permissions)
        self.save_btn.setEnabled(False)
        right.addWidget(self.save_btn)
        split.addLayout(right, 2)
        
        layout.addLayout(split)
        
        self.roles_data = []
        self.perms_data = []
        self._load_data()
        
    def _load_data(self):
        with self.session_factory() as session:
            self.roles_data = session.scalars(select(Role).order_by(Role.id)).all()
            for r in self.roles_data: session.expunge(r)
            self.perms_data = session.scalars(select(Permission).order_by(Permission.key)).all()
            for p in self.perms_data: session.expunge(p)
            
        self.roles_list.clear()
        for role in self.roles_data:
            self.roles_list.addItem(role.name)
            
        self.perms_table.setRowCount(len(self.perms_data))
        for row, p in enumerate(self.perms_data):
            chk = QTableWidgetItem("")
            chk.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            chk.setCheckState(Qt.CheckState.Unchecked)
            self.perms_table.setItem(row, 0, chk)
            lbl = QTableWidgetItem(p.key)
            lbl.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.perms_table.setItem(row, 1, lbl)
            
    def _role_selected(self, idx: int):
        if idx < 0:
            self.save_btn.setEnabled(False)
            return
        self.save_btn.setEnabled(True)
        role = self.roles_data[idx]
        with self.session_factory() as session:
            role_perms = session.scalars(select(RolePermission.permission_id).where(RolePermission.role_id == role.id)).all()
            role_perms_set = set(role_perms)
            
        for row, p in enumerate(self.perms_data):
            chk = self.perms_table.item(row, 0)
            chk.setCheckState(Qt.CheckState.Checked if p.id in role_perms_set else Qt.CheckState.Unchecked)
            
    def _add_role(self):
        name, ok = QInputDialog.getText(self, "New Role", "Role Name:")
        if ok and name.strip():
            with self.session_factory() as session:
                new_role = Role(name=name.strip())
                session.add(new_role)
                try:
                    session.flush()
                    session.add(ActivityLog(user_id=self.current_user.id, action="created role",
                                            module="administration", details=new_role.name))
                    session.commit()
                except Exception as e:
                    session.rollback()
                    QMessageBox.warning(self, "Error", f"Could not create role: {e}")
                    return
            self._load_data()

    def _add_user(self):
        username, ok = QInputDialog.getText(self, "New user", "Username:")
        if not ok or not username.strip():
            return
        display_name, ok = QInputDialog.getText(self, "New user", "Display name:")
        if not ok or not display_name.strip():
            return
        role_names = [role.name for role in self.roles_data]
        role_name, ok = QInputDialog.getItem(self, "New user", "Role:", role_names, 0, False)
        if not ok:
            return
        password_dialog = ChangePasswordDialog(self, title="Create temporary password", temporary=True)
        if password_dialog.exec() != QDialog.DialogCode.Accepted:
            return
        password = password_dialog.new_password
        role = next(role for role in self.roles_data if role.name == role_name)
        with self.session_factory() as session:
            user = User(username=username.strip(), display_name=display_name.strip(),
                        password_hash=hash_password(password), role_id=role.id,
                        branch_id=self.current_user.branch_id, must_change_password=True)
            session.add(user)
            try:
                session.flush()
                session.add(ActivityLog(user_id=self.current_user.id, action="created user",
                                        module="administration",
                                        details=f"{user.username} ({role.name})"))
                session.commit()
            except Exception as exc:
                session.rollback()
                QMessageBox.warning(self, "Cannot create user", str(exc))
                return
        QMessageBox.information(self, "User created", "User can now sign in and must change the temporary password.")
            
    def _save_permissions(self):
        idx = self.roles_list.currentRow()
        if idx < 0: return
        role = self.roles_data[idx]
        
        selected_perm_ids = []
        for row, p in enumerate(self.perms_data):
            if self.perms_table.item(row, 0).checkState() == Qt.CheckState.Checked:
                selected_perm_ids.append(p.id)
        selected_keys = {p.key for p in self.perms_data if p.id in selected_perm_ids}
        if role.id == self.current_user.role_id and "user.roles" not in selected_keys:
            QMessageBox.warning(self, "Permission required",
                                "You cannot remove role-management permission from your own role.")
            return
                
        with self.session_factory() as session:
            session.execute(RolePermission.__table__.delete().where(RolePermission.role_id == role.id))
            session.add_all(RolePermission(role_id=role.id, permission_id=pid) for pid in selected_perm_ids)
            session.add(ActivityLog(user_id=self.current_user.id, action="updated role permissions",
                                    module="administration", details=f"{role.name}: {', '.join(sorted(selected_keys))}"))
            session.commit()
            
        QMessageBox.information(self, "Saved", "Permissions updated successfully.")


@dataclass
class CartEntry:
    product: Product
    quantity: int = 1


class ProductCard(QFrame):
    def __init__(self, product: Product, add_callback, parent=None):
        super().__init__(parent)
        self.setObjectName("productCard")
        self.setMinimumSize(155, 190)
        self.setMaximumHeight(215)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 10)
        layout.setSpacing(5)
        product_art = QLabel("OIL")
        product_art.setAlignment(Qt.AlignmentFlag.AlignCenter)
        product_art.setFixedHeight(70)
        product_art.setStyleSheet(
            "font-size: 22px; font-weight: 900; color: #126ff5; "
            "background: #eef5ff; border: 1px solid #dbeafe; border-radius: 10px;"
        )
        name = QLabel(product.name)
        name.setObjectName("productName")
        name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name.setWordWrap(True)
        price = QLabel(money(product.selling_price_cents))
        price.setObjectName("productPrice")
        price.setAlignment(Qt.AlignmentFlag.AlignCenter)
        stock = QLabel(f"●  Stock: {product.stock_quantity}")
        stock.setObjectName("stockLabel")
        stock.setAlignment(Qt.AlignmentFlag.AlignCenter)
        add = QPushButton("＋ Add")
        add.setEnabled(product.stock_quantity > 0)
        add.clicked.connect(lambda _checked=False: add_callback(product))
        layout.addWidget(product_art)
        layout.addWidget(name)
        layout.addWidget(price)
        layout.addWidget(stock)
        layout.addStretch()
        layout.addWidget(add)


class PosWidget(QWidget):
    def __init__(self, session_factory, user: User):
        super().__init__()
        self.session_factory = session_factory
        self.user = user
        self.cart: dict[int, CartEntry] = {}
        self.held_carts: list[dict[int, CartEntry]] = []
        self.selected_product: Product | None = None
        self.shift_id: int | None = None
        self.terminal_id: int | None = None
        with self.session_factory() as session:
            self.permissions = permission_keys(session, user)
            self.role_name = session.scalar(select(Role.name).where(Role.id == user.role_id)) or "Unknown"
        self.setStyleSheet(MODERN_STYLE)
        self._build_ui()
        self.search_products()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)
        header = QHBoxLayout()
        title = QLabel("POS - Sales")
        title.setObjectName("titleLabel")
        header.addWidget(title)
        subtitle = QLabel("Create new invoice and process sales")
        subtitle.setObjectName("subtitleLabel")
        header.addWidget(subtitle)
        header.addStretch()
        self.shift_button = QPushButton("Open shift")
        self.shift_button.clicked.connect(self.close_current_shift)
        self.shift_button.setVisible("sales.create" in self.permissions)
        header.addWidget(self.shift_button)
            
        header.addStretch()
        header.addWidget(QLabel(f"{self.user.display_name} · {self.role_name}"))
        root.addLayout(header)

        body = QHBoxLayout()
        body.setSpacing(10)
        left_panel = QFrame()
        left_panel.setObjectName("posPanel")
        left = QVBoxLayout(left_panel)
        left.setContentsMargins(10, 10, 10, 10)
        search_row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Scan barcode or search product name…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.search_products)
        self.search.returnPressed.connect(self.add_first_result)
        search_row.addWidget(self.search, 1)
        self.category = QComboBox()
        with self.session_factory() as session:
            self.categories = session.scalars(select(Category).where(Category.active.is_(True)).order_by(Category.name)).all()
            for category in self.categories:
                session.expunge(category)
        self.category.addItem("All Categories", None)
        for category in self.categories:
            self.category.addItem(category.name, category.id)
        self.category.currentTextChanged.connect(self.search_products)
        search_row.addWidget(self.category)
        left.addLayout(search_row)
        category_chips = QHBoxLayout()
        for label in ["All Items", *[category.name for category in self.categories[:6]]]:
            chip = QPushButton(label)
            chip.clicked.connect(lambda _checked=False, value=label: self.select_category(value))
            category_chips.addWidget(chip)
        category_chips.addStretch()
        left.addLayout(category_chips)
        self.product_scroll = QScrollArea()
        self.product_scroll.setWidgetResizable(True)
        self.product_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.product_host = QWidget()
        self.product_grid = QGridLayout(self.product_host)
        self.product_grid.setContentsMargins(0, 4, 0, 4)
        self.product_grid.setSpacing(8)
        self.product_grid.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.product_scroll.setWidget(self.product_host)
        left.addWidget(self.product_scroll, 1)
        self.product_detail = QFrame()
        self.product_detail.setObjectName("posPanel")
        self.product_detail_layout = QHBoxLayout(self.product_detail)
        self.product_detail_layout.addWidget(QLabel("Select a product to view details"))
        left.addWidget(self.product_detail)

        right_panel = QFrame()
        right_panel.setObjectName("posPanel")
        right_panel.setMinimumWidth(430)
        right = QVBoxLayout(right_panel)
        right.setContentsMargins(12, 12, 12, 12)
        right.setSpacing(12)
        cart_title = QLabel("Current Sale")
        cart_title.setObjectName("titleLabel")
        right.addWidget(cart_title)
        customer_row = QHBoxLayout()
        self.customer = QComboBox()
        self.customer.setMinimumWidth(230)
        self.add_customer_button = QPushButton("+ Customer")
        self.add_customer_button.clicked.connect(self.add_customer)
        self.add_customer_button.setEnabled("customer.add" in self.permissions)
        customer_row.addWidget(QLabel("Customer"))
        customer_row.addWidget(self.customer, 1)
        customer_row.addWidget(self.add_customer_button)
        right.addLayout(customer_row)
        self.cart_table = QTableWidget(0, 6)
        self.cart_table.setHorizontalHeaderLabels(["#", "Item", "Qty", "Price", "Amount", ""])
        self.cart_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.cart_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.cart_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        right.addWidget(self.cart_table)
        controls = QHBoxLayout()
        minus = QPushButton("− Qty")
        plus = QPushButton("+ Qty")
        remove = QPushButton("Remove")
        hold = QPushButton("Hold")
        clear = QPushButton("Clear All")
        minus.clicked.connect(lambda: self.change_quantity(-1))
        plus.clicked.connect(lambda: self.change_quantity(1))
        remove.clicked.connect(self.remove_selected)
        hold.clicked.connect(self.hold_sale)
        clear.clicked.connect(self.clear_cart)
        for button in (minus, plus, remove, hold, clear):
            controls.addWidget(button)
        right.addLayout(controls)
        totals_form = QFormLayout()
        self.discount_amount = QDoubleSpinBox()
        self.discount_amount.setRange(0, 100000000)
        self.discount_amount.setDecimals(2)
        self.discount_amount.setPrefix("Rs. ")
        self.discount_amount.setEnabled("sales.edit" in self.permissions)
        self.discount_amount.valueChanged.connect(lambda _value: self.refresh_cart())
        self.tax_amount = QDoubleSpinBox()
        self.tax_amount.setRange(0, 100000000)
        self.tax_amount.setDecimals(2)
        self.tax_amount.setPrefix("Rs. ")
        self.tax_amount.setEnabled("sales.edit" in self.permissions)
        self.tax_amount.valueChanged.connect(lambda _value: self.refresh_cart())
        totals_form.addRow("Discount", self.discount_amount)
        totals_form.addRow("Tax", self.tax_amount)
        right.addLayout(totals_form)
        self.subtotal_summary = QLabel("Subtotal: Rs. 0.00")
        self.discount_summary = QLabel("Discount: Rs. 0.00")
        self.tax_summary = QLabel("Tax: Rs. 0.00")
        for summary in (self.subtotal_summary, self.discount_summary, self.tax_summary):
            summary.setAlignment(Qt.AlignmentFlag.AlignRight)
            right.addWidget(summary)
        self.total = QLabel("Total: Rs. 0.00")
        self.total.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.total.setObjectName("totalLabel")
        right.addWidget(self.total)
        payment_methods = QHBoxLayout()
        self.payment_method = "Cash"
        for method in ("Cash", "Card", "Credit", "Other"):
            button = QPushButton(method)
            button.setEnabled(method != "Other")
            button.clicked.connect(lambda _checked=False, selected=method: self.select_payment_method(selected))
            payment_methods.addWidget(button)
        right.addLayout(payment_methods)
        self.checkout_button = QPushButton("PAY / COMPLETE SALE")
        self.checkout_button.setObjectName("primaryButton")
        self.checkout_button.setMinimumHeight(52)
        self.checkout_button.setEnabled(False)
        self.checkout_button.clicked.connect(self.complete_sale)
        right.addWidget(self.checkout_button)
        status_row = QHBoxLayout()
        status_row.addWidget(QLabel("● Offline ready"))
        with self.session_factory() as session:
            settings = session.scalar(select(BillSetting).where(BillSetting.branch_id == self.user.branch_id))
            printer_status = "Printer connected" if settings and settings.printer_name else "Printer not configured"
        status_row.addWidget(QLabel(printer_status))
        status_row.addStretch()
        status_row.addWidget(QLabel(datetime.now().strftime("%d %b %Y | %H:%M")))
        right.addLayout(status_row)

        body.addWidget(left_panel, 3)
        body.addWidget(right_panel, 2)
        root.addLayout(body)
        self.search.setFocus()
        self.refresh_customers()

    def _open_admin(self):
        dialog = AdminDialog(self.session_factory, self.user, self)
        dialog.exec()

    def _open_users(self):
        dialog = UserManagementDialog(self.session_factory, self.user, self)
        dialog.exec()

    def select_payment_method(self, method: str):
        self.payment_method = method

    def select_category(self, label: str):
        category = "All Categories" if label == "All Items" else label
        self.category.setCurrentText(category)
        self.search_products()

    def ensure_shift(self) -> bool:
        if "sales.create" not in self.permissions:
            return True
        with self.session_factory() as session:
            self.terminal_id = session.scalar(select(Terminal.id).where(
                Terminal.branch_id == self.user.branch_id
            ).order_by(Terminal.id))
            if self.terminal_id is None:
                QMessageBox.critical(self, "No terminal", "No POS terminal is assigned to this branch.")
                return False
            shift = active_shift(session, self.terminal_id)
            if shift:
                if shift.user_id != self.user.id:
                    QMessageBox.critical(self, "Terminal in use",
                        "Another cashier has an open shift on this terminal.")
                    return False
                self.shift_id = shift.id
                self.shift_button.setText(f"Close shift #{shift.id}")
                return True
        amount, ok = QInputDialog.getDouble(self, "Open shift",
            "Count and enter the opening cash amount (Rs.):", 0, 0, 100000000, 2)
        if not ok:
            return False
        with self.session_factory() as session:
            try:
                shift = open_shift(session, user_id=self.user.id, terminal_id=self.terminal_id,
                                   opening_cash_cents=int(round(amount * 100)))
            except ShiftError as exc:
                QMessageBox.warning(self, "Cannot open shift", str(exc))
                return False
        self.shift_id = shift.id
        self.shift_button.setText(f"Close shift #{shift.id}")
        return True

    def close_current_shift(self):
        if self.shift_id is None:
            self.ensure_shift()
            return
        counted, ok = QInputDialog.getDouble(self, "Close shift",
            "Count and enter all cash currently in the drawer (Rs.):", 0, 0, 100000000, 2)
        if not ok:
            return
        with self.session_factory() as session:
            try:
                summary = close_shift(session, shift_id=self.shift_id, user_id=self.user.id,
                                      counted_cash_cents=int(round(counted * 100)))
            except ShiftError as exc:
                QMessageBox.warning(self, "Cannot close shift", str(exc))
                return
        QMessageBox.information(self, "Shift closed",
            f"Opening cash: {money(summary.opening_cash_cents)}\n"
            f"Cash sales: {money(summary.cash_sales_cents)}\n"
            f"Expected cash: {money(summary.expected_cash_cents)}\n"
            f"Counted cash: {money(summary.counted_cash_cents)}\n"
            f"Variance: {money(summary.variance_cents)}")
        self.shift_id = None
        self.shift_button.setText("Open shift")

    def search_products(self):
        term = self.search.text().strip()
        with self.session_factory() as session:
            query = select(Product).where(Product.active.is_(True))
            if term:
                query = query.where(or_(Product.name.ilike(f"%{term}%"), Product.barcode.ilike(f"%{term}%")))
            category_id = self.category.currentData() if hasattr(self, "category") else None
            if category_id is not None:
                query = query.where(Product.category_id == category_id)
            rows = session.execute(query.order_by(Product.name).limit(100)).scalars().all()
            for product in rows:
                session.expunge(product)
        self.product_results = rows
        while self.product_grid.count():
            item = self.product_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        columns = 4 if self.width() >= 1050 else 3
        for index, product in enumerate(rows):
            self.product_grid.addWidget(ProductCard(product, self.add_product), index // columns, index % columns)
        if "product.add" in self.permissions:
            add_button = QPushButton("＋\nAdd New Product")
            add_button.setMinimumSize(155, 190)
            add_button.setStyleSheet("color: #126ff5; font-weight: 700; border: 1px dashed #8bbcff;")
            add_button.clicked.connect(self.add_new_product)
            index = len(rows)
            self.product_grid.addWidget(add_button, index // columns, index % columns)
        if not rows and "product.add" not in self.permissions:
            empty = QLabel("No products found")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setObjectName("subtitleLabel")
            self.product_grid.addWidget(empty, 0, 0, 1, columns)

    def refresh_customers(self, selected_id: int | None = None):
        self.customer.clear()
        self.customer.addItem("Walk-in customer", None)
        with self.session_factory() as session:
            customers = session.scalars(select(Customer).order_by(Customer.name)).all()
            for customer in customers:
                label = customer.name
                if customer.phone:
                    label += f" · {customer.phone}"
                if customer.credit_balance_cents:
                    label += f" · Due {money(customer.credit_balance_cents)}"
                self.customer.addItem(label, customer.id)
        if selected_id is not None:
            index = self.customer.findData(selected_id)
            if index >= 0:
                self.customer.setCurrentIndex(index)

    def add_customer(self):
        name, ok = QInputDialog.getText(self, "New customer", "Customer name:")
        if not ok or not name.strip():
            return
        phone, ok = QInputDialog.getText(self, "New customer", "Phone number:")
        if not ok:
            return
        limit, ok = QInputDialog.getDouble(self, "New customer",
            "Credit limit (Rs.):", 0, 0, 100000000, 2)
        if not ok:
            return
        with self.session_factory() as session:
            try:
                customer = create_customer(session, user_id=self.user.id, name=name, phone=phone,
                                           credit_limit_cents=int(round(limit * 100)))
            except ValueError as exc:
                QMessageBox.warning(self, "Cannot add customer", str(exc))
                return
        self.refresh_customers(customer.id)

    def add_first_result(self):
        if self.product_results:
            self.add_product(self.product_results[0])

    def add_product(self, product: Product):
        self.show_product_detail(product)
        existing = self.cart.get(product.id)
        quantity = (existing.quantity if existing else 0) + 1
        if quantity > product.stock_quantity:
            QMessageBox.warning(self, "Stock unavailable", f"Only {product.stock_quantity} units are available.")
            return
        self.cart[product.id] = CartEntry(product, quantity)
        self.refresh_cart()
        self.search.clear()
        self.search.setFocus()

    def show_product_detail(self, product: Product):
        self.selected_product = product
        while self.product_detail_layout.count():
            item = self.product_detail_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        category_name = next((category.name for category in self.categories
                              if category.id == product.category_id), "Uncategorized")
        name = QLabel(f"{product.name}\nBarcode: {product.barcode}  |  Category: {category_name}")
        name.setObjectName("productName")
        stock = QLabel(f"In Stock\n{product.stock_quantity} available")
        stock.setObjectName("stockLabel")
        price = QLabel(money(product.selling_price_cents))
        price.setObjectName("productPrice")
        add = QPushButton("Add to Cart")
        add.setObjectName("primaryButton")
        add.clicked.connect(lambda _checked=False: self.add_product(product))
        self.product_detail_layout.addWidget(name, 1)
        self.product_detail_layout.addWidget(stock)
        self.product_detail_layout.addWidget(price)
        self.product_detail_layout.addWidget(add)

    def add_new_product(self):
        barcode, ok = QInputDialog.getText(self, "Add product", "Barcode:")
        if not ok or not barcode.strip(): return
        name, ok = QInputDialog.getText(self, "Add product", "Product name:")
        if not ok or not name.strip(): return
        with self.session_factory() as session:
            category_rows = session.execute(select(Category.id, Category.name).where(
                Category.active.is_(True)).order_by(Category.name)).all()
        category_name, ok = QInputDialog.getItem(
            self, "Add product", "Category:",
            [name for _, name in category_rows] + ["+ Create New Category"], 0, False
        )
        if not ok: return
        if category_name == "+ Create New Category":
            category_name, ok = QInputDialog.getText(self, "New category", "Category name:")
            if not ok or not category_name.strip(): return
            with self.session_factory() as session:
                category = Category(name=category_name.strip())
                session.add(category)
                try:
                    session.flush()
                    category_id = category.id
                    session.add(ActivityLog(user_id=self.user.id, action="created category",
                                            module="products", details=category.name))
                    session.commit()
                except Exception:
                    session.rollback()
                    QMessageBox.warning(self, "Cannot add category", "Category name must be unique.")
                    return
            self.reload_categories(category_id)
        else:
            category_id = next(category_id for category_id, existing_name in category_rows
                               if existing_name == category_name)
        purchase, ok = QInputDialog.getDouble(self, "Add product", "Purchase price (Rs.):", 0, 0, 100000000, 2)
        if not ok: return
        selling, ok = QInputDialog.getDouble(self, "Add product", "Selling price (Rs.):", 0, 0, 100000000, 2)
        if not ok: return
        stock, ok = QInputDialog.getInt(self, "Add product", "Opening stock:", 0, 0, 100000000)
        if not ok: return
        with self.session_factory() as session:
            product = Product(barcode=barcode.strip(), name=name.strip(), category_id=category_id,
                purchase_price_cents=int(round(purchase * 100)),
                selling_price_cents=int(round(selling * 100)), stock_quantity=stock)
            session.add(product)
            try:
                session.flush()
                session.add(ActivityLog(user_id=self.user.id, action="created product",
                                        module="products", details=product.name))
                session.commit()
            except Exception:
                session.rollback()
                QMessageBox.warning(self, "Cannot add product", "Barcode must be unique.")
                return
        self.search_products()

    def reload_categories(self, selected_id: int | None = None):
        with self.session_factory() as session:
            categories = session.scalars(select(Category).where(Category.active.is_(True)).order_by(Category.name)).all()
            for category in categories:
                session.expunge(category)
        self.categories = categories
        self.category.blockSignals(True)
        self.category.clear()
        self.category.addItem("All Categories", None)
        for category in categories:
            self.category.addItem(category.name, category.id)
        if selected_id is not None:
            index = self.category.findData(selected_id)
            if index >= 0: self.category.setCurrentIndex(index)
        self.category.blockSignals(False)

    def refresh_cart(self):
        entries = list(self.cart.values())
        self.cart_table.setRowCount(len(entries))
        total = 0
        for row, entry in enumerate(entries):
            amount = entry.product.selling_price_cents * entry.quantity
            total += amount
            values = (str(row + 1), entry.product.name)
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole, entry.product.id if column == 1 else None)
                self.cart_table.setItem(row, column, item)
            quantity = QWidget()
            quantity_layout = QHBoxLayout(quantity)
            quantity_layout.setContentsMargins(0, 0, 0, 0)
            minus = QPushButton("−"); minus.setFixedWidth(28)
            count = QLabel(str(entry.quantity)); count.setAlignment(Qt.AlignmentFlag.AlignCenter)
            plus = QPushButton("+"); plus.setFixedWidth(28)
            minus.clicked.connect(lambda _checked=False, pid=entry.product.id: self.change_product_quantity(pid, -1))
            plus.clicked.connect(lambda _checked=False, pid=entry.product.id: self.change_product_quantity(pid, 1))
            quantity_layout.addWidget(minus); quantity_layout.addWidget(count); quantity_layout.addWidget(plus)
            self.cart_table.setCellWidget(row, 2, quantity)
            self.cart_table.setItem(row, 3, QTableWidgetItem(money(entry.product.selling_price_cents)))
            self.cart_table.setItem(row, 4, QTableWidgetItem(money(amount)))
            delete = QPushButton("×")
            delete.setStyleSheet("color: #ef4444; font-weight: 900;")
            delete.clicked.connect(lambda _checked=False, pid=entry.product.id: self.remove_product(pid))
            self.cart_table.setCellWidget(row, 5, delete)
        discount = int(round(self.discount_amount.value() * 100)) if hasattr(self, "discount_amount") else 0
        tax = int(round(self.tax_amount.value() * 100)) if hasattr(self, "tax_amount") else 0
        grand_total = max(0, total - discount + tax)
        self.subtotal_summary.setText(f"Subtotal: {money(total)}")
        self.discount_summary.setText(f"Discount: {money(discount)}")
        self.tax_summary.setText(f"Tax: {money(tax)}")
        self.total.setText(f"Total: {money(grand_total)}")
        self.checkout_button.setText(f"Pay {money(grand_total)}  →")
        self.checkout_button.setEnabled(bool(entries) and "sales.create" in self.permissions)

    def _selected_cart_id(self) -> int | None:
        row = self.cart_table.currentRow()
        return None if row < 0 else self.cart_table.item(row, 1).data(Qt.ItemDataRole.UserRole)

    def change_product_quantity(self, product_id: int, delta: int):
        self.cart_table.selectRow(next((row for row in range(self.cart_table.rowCount())
            if self.cart_table.item(row, 1).data(Qt.ItemDataRole.UserRole) == product_id), -1))
        self.change_quantity(delta)

    def remove_product(self, product_id: int):
        self.cart.pop(product_id, None)
        self.refresh_cart()

    def hold_sale(self):
        if not self.cart:
            QMessageBox.information(self, "Hold sale", "The current sale is empty.")
            return
        self.held_carts.append(dict(self.cart))
        self.cart.clear()
        self.refresh_cart()
        QMessageBox.information(self, "Sale held", f"Sale held in memory ({len(self.held_carts)} held).")

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
        if self.shift_id is None:
            QMessageBox.warning(self, "Shift required", "Open a shift before creating a sale.")
            return
        subtotal = sum(x.product.selling_price_cents * x.quantity for x in self.cart.values())
        discount = int(round(self.discount_amount.value() * 100))
        tax = int(round(self.tax_amount.value() * 100))
        if discount > subtotal:
            QMessageBox.warning(self, "Invalid discount", "Discount cannot exceed the subtotal.")
            return
        total = subtotal - discount + tax
        dialog = PaymentDialog(total, self, self.payment_method)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        method, paid = dialog.result_data
        with self.session_factory() as session:
            terminal_id = session.scalar(select(Terminal.id).where(Terminal.branch_id == self.user.branch_id).order_by(Terminal.id))
            try:
                invoice = checkout(session, terminal_id=terminal_id, cashier_id=self.user.id,
                    shift_id=self.shift_id,
                    lines=[CartLine(p, e.quantity) for p, e in self.cart.items()],
                    payment_method=method, paid_cents=paid,
                    discount_cents=discount, tax_cents=tax,
                    customer_id=self.customer.currentData())
            except (CheckoutError, PermissionDenied) as exc:
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
        self.discount_amount.setValue(0)
        self.tax_amount.setValue(0)
        self.customer.setCurrentIndex(0)
        self.refresh_cart()
        self.search_products()
        main_window = self.window()
        if isinstance(main_window, QMainWindow):
            main_window.statusBar().showMessage(
                f"Completed {invoice.local_invoice_number}", 8000
            )
        receipt_dialog = ReceiptDialog(self.session_factory, invoice.id, self)
        with self.session_factory() as session:
            settings = session.scalar(select(BillSetting).where(BillSetting.branch_id == invoice.branch_id))
            auto_print = settings.auto_print and bool(settings.printer_name.strip())
        if auto_print:
            receipt_dialog.print_now()
        else:
            receipt_dialog.exec()
