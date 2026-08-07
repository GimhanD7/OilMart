# OilMart POS

Oil Mart point-of-sale monorepo with SQLite offline mode and PostgreSQL deployment support.

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

The first launch creates the required roles, permissions, product categories, and
an administrator (`admin` / `ChangeMe123!`). It does not insert demo products or
sales. The administrator must change the temporary password at first sign-in.

Run tests:

```powershell
$env:PYTHONPATH = "$PWD\desktop"
python -m pytest desktop/tests -q
```

## Build the Windows desktop app

Install the development requirements, then run the packaging script:

```powershell
.\.venv\Scripts\python.exe -m pip install -r .\desktop\requirements-dev.txt
.\desktop\build_windows.ps1
```

This produces `desktop\dist\OilMart POS.exe` and creates an **OilMart POS**
shortcut on the current user's desktop. The app keeps its offline SQLite data
under the user's application data directory; rebuilding the executable does not
overwrite business data.

Migrations run automatically when OilMart starts. To check/apply them manually:

```powershell
$env:PYTHONPATH = "$PWD\desktop"
python -m oilmart.migrations
```

Do not execute `desktop/oilmart/migrations.py` by file path; it is part of the
`oilmart` package and must be loaded as a module.

## Deployment notes

The desktop data file defaults to `~/.oilmart/oilmart.db`; override it with `OILMART_DB_URL`. Configure `OILMART_API_URL` and `OILMART_API_TOKEN` for cloud sync. Laravel 13 requires PHP 8.3+; the local machine currently has PHP 8.2, so the cloud application must be installed on a compatible runtime before its migrations/controllers can be executed.

## Run with PostgreSQL

Install the updated desktop requirements, which include the Psycopg PostgreSQL driver:

```powershell
.\.venv\Scripts\python.exe -m pip install -r .\desktop\requirements.txt
```

Start PostgreSQL using `compose.postgres.yml` (Docker Desktop is required):

```powershell
$env:OILMART_POSTGRES_PASSWORD = "use-a-long-random-password"
docker compose -f .\compose.postgres.yml up -d
```

Point OilMart at PostgreSQL and start it. On first launch, all tables and migration
history are created automatically:

```powershell
$env:OILMART_DB_URL = "postgresql+psycopg://oilmart:use-a-long-random-password@localhost:5432/oilmart"
$env:PYTHONPATH = "$PWD\desktop"
.\.venv\Scripts\python.exe -m oilmart
```

For a remote production database, require TLS in the connection string:

```powershell
$env:OILMART_DB_URL = "postgresql+psycopg://USER:PASSWORD@HOST:5432/oilmart?sslmode=require"
```

To copy the existing local SQLite data into a new, empty PostgreSQL database:

```powershell
$env:OILMART_SOURCE_DB_URL = "sqlite:///C:/Users/gimha/.oilmart/oilmart.db"
$env:OILMART_TARGET_DB_URL = "postgresql+psycopg://oilmart:PASSWORD@localhost:5432/oilmart"
$env:PYTHONPATH = "$PWD\desktop"
.\.venv\Scripts\python.exe -m oilmart.database_transfer
```

The transfer refuses to overwrite a PostgreSQL database containing branch data.
After a successful transfer, keep `OILMART_DB_URL` set to the PostgreSQL URL whenever
the desktop application starts.

## Offline sync and automatic backups

For offline-first operation, leave `OILMART_DB_URL` unset so every sale is committed
to the local SQLite database immediately. Configure the HTTPS cloud API separately:

```powershell
$env:OILMART_API_URL = "https://your-server.example.com/api"
$env:OILMART_API_TOKEN = "your-terminal-api-token"
$env:OILMART_SYNC_INTERVAL = "30"
$env:OILMART_BACKUP_INTERVAL = "21600"
$env:OILMART_BACKUP_RETENTION = "14"
$env:OILMART_BACKUP_DIR = "C:\OilMart-Backups"
```

The desktop footer always shows online/offline state, pending/failed/synced jobs,
and the most recent backup. Sales continue locally while offline. Failed jobs use
exponential retry and can also be retried with **Sync now**. SQLite backups use its
consistent online-backup API and old backups are removed according to retention.
Remote API URLs must use HTTPS; plain HTTP is accepted only for localhost development.
