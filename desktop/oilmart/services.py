from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import ActivityLog, InventoryMovement, Invoice, Payment, Product, SaleItem, SyncOutbox, Terminal


class CheckoutError(ValueError):
    pass


@dataclass(frozen=True)
class CartLine:
    product_id: int
    quantity: int


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
        "created_at": invoice.created_at.isoformat(),
        "items": [{"product_id": x.product_id, "name": x.product_name, "quantity": x.quantity,
                   "unit_price_cents": x.unit_price_cents, "cost_price_cents": x.cost_price_cents,
                   "line_total_cents": x.line_total_cents} for x in invoice.items],
    }, separators=(",", ":"))


def checkout(session: Session, *, terminal_id: int, cashier_id: int, lines: list[CartLine],
             payment_method: str, paid_cents: int, discount_cents: int = 0, tax_cents: int = 0,
             customer_id: int | None = None, now: datetime | None = None) -> Invoice:
    if not lines or any(line.quantity <= 0 for line in lines):
        raise CheckoutError("Cart must contain positive quantities")
    if payment_method not in {"cash", "card", "credit"}:
        raise CheckoutError("Unsupported payment method")
    now = now or datetime.now(timezone.utc)
    try:
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
        local_number = f"TEMP-{terminal.code}-{terminal.next_invoice_sequence:06d}"
        terminal.next_invoice_sequence += 1
        invoice = Invoice(local_invoice_number=local_number, branch_id=terminal.branch_id,
                          terminal_id=terminal.id, cashier_id=cashier_id, customer_id=customer_id,
                          subtotal_cents=subtotal, discount_cents=discount_cents, tax_cents=tax_cents,
                          total_cents=total, payment_method=payment_method, created_at=now)
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

