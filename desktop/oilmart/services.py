from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import ActivityLog, Customer, InventoryMovement, Invoice, Payment, Product, SaleItem, SyncOutbox, Terminal
from .models import User
from .security import require_permission


class CheckoutError(ValueError):
    pass


@dataclass(frozen=True)
class CartLine:
    product_id: int
    quantity: int


def create_customer(session: Session, *, user_id: int, name: str, phone: str = "",
                    credit_limit_cents: int = 0) -> Customer:
    user = session.get(User, user_id)
    if user is None:
        raise ValueError("User does not exist")
    require_permission(session, user, "customer.add")
    name = name.strip()
    phone = phone.strip()
    if not name:
        raise ValueError("Customer name is required")
    if credit_limit_cents < 0:
        raise ValueError("Credit limit cannot be negative")
    customer = Customer(name=name, phone=phone, credit_limit_cents=credit_limit_cents)
    session.add(customer)
    session.flush()
    session.add(SyncOutbox(aggregate_type="customer", aggregate_uuid=customer.uuid,
        payload_json=json.dumps({"uuid": customer.uuid, "name": name, "phone": phone,
                                 "credit_limit_cents": credit_limit_cents,
                                 "credit_balance_cents": 0}, separators=(",", ":"))))
    session.add(ActivityLog(user_id=user_id, action="created customer", module="customers",
                            details=customer.uuid))
    session.commit()
    return customer


def _invoice_payload(invoice: Invoice) -> str:
    return json.dumps({
        "uuid": invoice.uuid,
        "local_invoice_number": invoice.local_invoice_number,
        "branch_id": invoice.branch_id,
        "terminal_id": invoice.terminal_id,
        "cashier_id": invoice.cashier_id,
        "customer_id": invoice.customer_id,
        "subtotal_cents": invoice.subtotal_cents,
        "discount_cents": invoice.discount_cents,
        "tax_cents": invoice.tax_cents,
        "total_cents": invoice.total_cents,
        "payment_method": invoice.payment_method,
        "status": invoice.status,
        "created_at": invoice.created_at.isoformat(),
        "items": [{"product_id": x.product_id, "name": x.product_name, "quantity": x.quantity,
                   "unit_price_cents": x.unit_price_cents, "cost_price_cents": x.cost_price_cents,
                   "line_total_cents": x.line_total_cents} for x in invoice.items],
    }, separators=(",", ":"))


def checkout(session: Session, *, terminal_id: int, cashier_id: int, lines: list[CartLine],
             payment_method: str, paid_cents: int, discount_cents: int = 0, tax_cents: int = 0,
             customer_id: int | None = None, shift_id: int | None = None,
             now: datetime | None = None) -> Invoice:
    if not lines or any(line.quantity <= 0 for line in lines):
        raise CheckoutError("Cart must contain positive quantities")
    if payment_method not in {"cash", "card", "credit"}:
        raise CheckoutError("Unsupported payment method")
    now = now or datetime.now(timezone.utc)
    try:
        cashier = session.get(User, cashier_id)
        if cashier is None:
            raise CheckoutError("Cashier does not exist")
        require_permission(session, cashier, "sales.create")
        if discount_cents or tax_cents:
            require_permission(session, cashier, "sales.edit")
        if payment_method == "credit":
            require_permission(session, cashier, "customer.credit")
        terminal = session.execute(select(Terminal).where(Terminal.id == terminal_id).with_for_update()).scalar_one()
        merged: dict[int, int] = {}
        for line in lines:
            merged[line.product_id] = merged.get(line.product_id, 0) + line.quantity
        products = {p.id: p for p in session.execute(select(Product).where(Product.id.in_(merged)).with_for_update()).scalars()}
        if len(products) != len(merged):
            raise CheckoutError("One or more products no longer exist")
        for product_id, quantity in merged.items():
            if not products[product_id].active or products[product_id].stock_quantity < quantity:
                raise CheckoutError(f"Insufficient stock for {products[product_id].name}")
        subtotal = sum(products[p].selling_price_cents * q for p, q in merged.items())
        total = subtotal - discount_cents + tax_cents
        if min(discount_cents, tax_cents, total) < 0 or discount_cents > subtotal:
            raise CheckoutError("Invalid totals")
        if payment_method != "credit" and paid_cents < total:
            raise CheckoutError("Payment is less than total")
        customer = session.get(Customer, customer_id) if customer_id is not None else None
        if payment_method == "credit":
            if customer is None:
                raise CheckoutError("Select a customer for a credit sale")
            new_balance = customer.credit_balance_cents + total
            if new_balance > customer.credit_limit_cents:
                available = max(0, customer.credit_limit_cents - customer.credit_balance_cents)
                raise CheckoutError(f"Customer credit limit exceeded; available credit is {available / 100:,.2f}")
            customer.credit_balance_cents = new_balance
        local_number = f"TEMP-{terminal.code}-{terminal.next_invoice_sequence:06d}"
        terminal.next_invoice_sequence += 1
        invoice = Invoice(local_invoice_number=local_number, branch_id=terminal.branch_id,
                          terminal_id=terminal.id, cashier_id=cashier_id, customer_id=customer_id,
                          shift_id=shift_id,
                          subtotal_cents=subtotal, discount_cents=discount_cents, tax_cents=tax_cents,
                          total_cents=total, payment_method=payment_method, created_at=now)
        invoice.status = "pending" if payment_method == "credit" else "paid"
        session.add(invoice)
        session.flush()
        for product_id, quantity in merged.items():
            product = products[product_id]
            product.stock_quantity -= quantity
            invoice.items.append(SaleItem(product_id=product.id, product_name=product.name, quantity=quantity,
                unit_price_cents=product.selling_price_cents, cost_price_cents=product.purchase_price_cents,
                line_total_cents=product.selling_price_cents * quantity))
            session.add(InventoryMovement(product_id=product.id, invoice_id=invoice.id,
                quantity_delta=-quantity, reason="sale"))
        invoice.payments.append(Payment(method=payment_method, amount_cents=total))
        session.flush()
        session.add(SyncOutbox(aggregate_type="invoice", aggregate_uuid=invoice.uuid,
                               payload_json=_invoice_payload(invoice)))
        session.add(ActivityLog(user_id=cashier_id, action="created invoice", module="sales",
                                details=local_number))
        session.commit()
        return invoice
    except Exception:
        session.rollback()
        raise


def reverse_invoice(session: Session, *, invoice_id: int, user_id: int,
                    action: str, reason: str = "") -> Invoice:
    """Atomically cancel or refund an invoice and restore inventory."""
    if action not in {"cancelled", "refunded"}:
        raise ValueError("Unsupported reversal action")
    user = session.get(User, user_id)
    if user is None:
        raise ValueError("User does not exist")
    require_permission(session, user, "sales.cancel" if action == "cancelled" else "sales.refund")
    try:
        invoice = session.get(Invoice, invoice_id)
        if invoice is None:
            raise CheckoutError("Invoice does not exist")
        if invoice.status in {"cancelled", "refunded"}:
            raise CheckoutError(f"Invoice is already {invoice.status}")
        for item in invoice.items:
            product = session.get(Product, item.product_id)
            if product:
                product.stock_quantity += item.quantity
                session.add(InventoryMovement(product_id=product.id, invoice_id=invoice.id,
                    quantity_delta=item.quantity, reason=action))
        if invoice.payment_method == "credit" and invoice.customer_id:
            customer = session.get(Customer, invoice.customer_id)
            if customer:
                customer.credit_balance_cents = max(0, customer.credit_balance_cents - invoice.total_cents)
        invoice.status = action
        payload = json.dumps({"uuid": invoice.uuid, "status": action, "reason": reason}, separators=(",", ":"))
        session.add(SyncOutbox(aggregate_type=f"invoice_{action}", aggregate_uuid=invoice.uuid,
                               payload_json=payload))
        session.add(ActivityLog(user_id=user_id, action=f"{action} invoice", module="sales",
                                details=f"{invoice.local_invoice_number}: {reason}"))
        session.commit()
        return invoice
    except Exception:
        session.rollback()
        raise
