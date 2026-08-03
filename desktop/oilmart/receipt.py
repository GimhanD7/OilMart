from __future__ import annotations

import ctypes
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from .models import BillSetting, Branch, Invoice, User


class PrinterError(RuntimeError):
    pass


@dataclass(frozen=True)
class ReceiptData:
    invoice_number: str
    local_number: str
    cloud_number: str
    created_at: datetime
    cashier: str
    branch: str
    branch_address: str
    branch_phone: str
    items: tuple[tuple[str, int, int, int], ...]
    subtotal_cents: int
    discount_cents: int
    tax_cents: int
    total_cents: int
    payment_method: str


def receipt_data(invoice: Invoice, branch: Branch, cashier: User) -> ReceiptData:
    display_number = invoice.cloud_invoice_number or invoice.local_invoice_number
    return ReceiptData(
        invoice_number=display_number,
        local_number=invoice.local_invoice_number,
        cloud_number=invoice.cloud_invoice_number or "Pending sync",
        created_at=invoice.created_at,
        cashier=cashier.display_name,
        branch=branch.name,
        branch_address=branch.address,
        branch_phone=branch.phone,
        items=tuple((item.product_name, item.quantity, item.unit_price_cents, item.line_total_cents)
                    for item in invoice.items),
        subtotal_cents=invoice.subtotal_cents,
        discount_cents=invoice.discount_cents,
        tax_cents=invoice.tax_cents,
        total_cents=invoice.total_cents,
        payment_method=invoice.payment_method,
    )


def _money(cents: int) -> str:
    return f"{Decimal(cents) / Decimal(100):,.2f}"


def _center(text: str, width: int) -> str:
    return text[:width].center(width)


def _pair(left: str, right: str, width: int) -> str:
    available = max(1, width - len(right) - 1)
    return f"{left[:available]:<{available}} {right}"


def _wrap(text: str, width: int) -> list[str]:
    words, lines, current = text.split(), [], ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) <= width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word[:width]
    if current:
        lines.append(current)
    return lines or [""]


def render_receipt(data: ReceiptData, settings: BillSetting) -> str:
    width = 32 if settings.paper_width_mm == 58 else 48
    rule = "-" * width
    lines = [
        _center(settings.header_text or data.branch, width),
        _center(data.branch, width),
    ]
    if data.branch_address:
        lines.extend(_center(line, width) for line in _wrap(data.branch_address, width))
    if data.branch_phone:
        lines.append(_center(data.branch_phone, width))
    lines.extend([
        rule,
        _pair("Invoice", data.invoice_number, width),
        _pair("Local", data.local_number, width),
        _pair("Cloud", data.cloud_number, width),
        _pair("Date", data.created_at.strftime("%Y-%m-%d %H:%M"), width),
        _pair("Cashier", data.cashier, width),
        rule,
    ])
    for name, quantity, unit_price, line_total in data.items:
        lines.extend(_wrap(name, width))
        lines.append(_pair(f"  {quantity} x {_money(unit_price)}", _money(line_total), width))
    lines.extend([rule, _pair("Subtotal", _money(data.subtotal_cents), width)])
    if settings.show_discount and data.discount_cents:
        lines.append(_pair("Discount", f"-{_money(data.discount_cents)}", width))
    if settings.show_tax and data.tax_cents:
        lines.append(_pair("Tax", _money(data.tax_cents), width))
    lines.extend([
        _pair("TOTAL", f"Rs. {_money(data.total_cents)}", width),
        _pair("Payment", data.payment_method.upper(), width),
        rule,
        _center(settings.footer_text or "Thank you", width),
        "",
        "",
    ])
    return "\n".join(lines)


def escpos_document(text: str) -> bytes:
    # Initialize, print text, feed, then full cut. Unsupported printers safely
    # ignore the cut sequence while still printing the receipt.
    normalized = text.replace("\n", "\r\n")
    return b"\x1b@" + normalized.encode("cp437", errors="replace") + b"\r\n\x1bd\x04\x1dV\x00"


class _DocInfo1(ctypes.Structure):
    _fields_ = [("pDocName", ctypes.c_wchar_p), ("pOutputFile", ctypes.c_wchar_p),
                ("pDatatype", ctypes.c_wchar_p)]


def send_raw_windows(printer_name: str, payload: bytes, document_name: str = "OilMart receipt") -> None:
    if not printer_name.strip():
        raise PrinterError("Select a Windows printer before printing")
    try:
        spooler = ctypes.WinDLL("winspool.drv", use_last_error=True)
    except (AttributeError, OSError) as exc:
        raise PrinterError("Raw ESC/POS printing is available on Windows only") from exc
    handle = ctypes.c_void_p()
    if not spooler.OpenPrinterW(printer_name, ctypes.byref(handle), None):
        raise PrinterError(f"Cannot open printer: {printer_name}")
    started_doc = started_page = False
    try:
        info = _DocInfo1(document_name, None, "RAW")
        if not spooler.StartDocPrinterW(handle, 1, ctypes.byref(info)):
            raise PrinterError("Windows print spooler rejected the document")
        started_doc = True
        if not spooler.StartPagePrinter(handle):
            raise PrinterError("Windows print spooler could not start the page")
        started_page = True
        written = ctypes.c_uint32()
        buffer = ctypes.create_string_buffer(payload)
        if not spooler.WritePrinter(handle, buffer, len(payload), ctypes.byref(written)):
            raise PrinterError("Windows could not write to the printer")
        if written.value != len(payload):
            raise PrinterError("Printer accepted only part of the receipt")
    finally:
        if started_page:
            spooler.EndPagePrinter(handle)
        if started_doc:
            spooler.EndDocPrinter(handle)
        spooler.ClosePrinter(handle)


def print_receipt(printer_name: str, text: str, copies: int = 1) -> None:
    if not 1 <= copies <= 5:
        raise PrinterError("Receipt copies must be between 1 and 5")
    payload = escpos_document(text)
    for _ in range(copies):
        send_raw_windows(printer_name, payload)

