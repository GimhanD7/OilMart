# OilMart POS

Offline-first Oil Mart point-of-sale monorepo foundation.

## What is implemented

- SQLAlchemy/SQLite domain model with branches, terminals, users, roles, permissions, products, customers, shifts, invoices, payments, inventory movements, sync outbox, bill settings, and activity logs.
- Atomic sale checkout: stock deduction, payment validation, terminal-local numbering, and sync enqueue happen in one transaction.
- UUID and invoice-number uniqueness constraints for cloud idempotency.
- Non-blocking background sync worker with retry/backoff and three-state sync status.
- Automatic versioned database migrations on every startup, with transactional migration history.
- PyQt6 cashier shell with login, product search/barcode entry, cart, cash/card/credit checkout, and sync indicator.
- Framework-neutral Laravel 13 API contract and MySQL schema blueprint in `cloud/`.
- Automated tests for checkout, rollback, numbering, and outbox behavior.

## Run locally

Your machine currently has Python 3.14. From PowerShell in the project root:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r .\desktop\requirements.txt
$env:PYTHONPATH = "$PWD\desktop"
.\.venv\Scripts\python.exe -m oilmart
```

If you already installed the requirements globally, the shorter command is:

```powershell
$env:PYTHONPATH = "$PWD\desktop"
python -m oilmart
```

The first launch seeds an administrator (`admin` / `ChangeMe123!`) and sample products. Change the password before real use.

Run tests:

```powershell
$env:PYTHONPATH = "$PWD\desktop"
python -m pytest desktop/tests -q
```

Migrations run automatically when OilMart starts. To check/apply them manually:

```powershell
$env:PYTHONPATH = "$PWD\desktop"
python -m oilmart.migrations
```

Do not execute `desktop/oilmart/migrations.py` by file path; it is part of the
`oilmart` package and must be loaded as a module.

## Deployment notes

The desktop data file defaults to `~/.oilmart/oilmart.db`; override it with `OILMART_DB_URL`. Configure `OILMART_API_URL` and `OILMART_API_TOKEN` for cloud sync. Laravel 13 requires PHP 8.3+; the local machine currently has PHP 8.2, so the cloud application must be installed on a compatible runtime before its migrations/controllers can be executed.
