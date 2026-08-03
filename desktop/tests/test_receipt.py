from datetime import datetime, timezone
from types import SimpleNamespace

from oilmart.receipt import ReceiptData, escpos_document, render_receipt


def sample_data():
    return ReceiptData(
        invoice_number="TEMP-POS01-000001", local_number="TEMP-POS01-000001",
        cloud_number="Pending sync", created_at=datetime(2026, 8, 1, 12, 30, tzinfo=timezone.utc),
        cashier="Administrator", branch="OilMart Colombo", branch_address="Main Street, Colombo",
        branch_phone="011-2222222", items=(("Engine Oil 1L", 2, 220000, 440000),),
        subtotal_cents=440000, discount_cents=10000, tax_cents=20000,
        total_cents=450000, payment_method="cash",
    )


def test_58mm_receipt_respects_width_and_totals():
    settings = SimpleNamespace(paper_width_mm=58, header_text="OILMART", footer_text="Thank you",
                               show_discount=True, show_tax=True)
    text = render_receipt(sample_data(), settings)
    assert max(map(len, text.splitlines())) <= 32
    assert "Rs. 4,500.00" in text
    assert "Discount" in text and "Tax" in text


def test_hidden_totals_and_escpos_commands():
    settings = SimpleNamespace(paper_width_mm=80, header_text="OILMART", footer_text="Thanks",
                               show_discount=False, show_tax=False)
    text = render_receipt(sample_data(), settings)
    assert "Discount" not in text and "Tax" not in text
    payload = escpos_document(text)
    assert payload.startswith(b"\x1b@")
    assert payload.endswith(b"\x1dV\x00")

