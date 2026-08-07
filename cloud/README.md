# OilMart Cloud (Laravel 13 target)

Runtime prerequisite: PHP 8.3+, Laravel 13, MySQL 8, and Sanctum.

## API contract

- `POST /api/login`
- `POST /api/sync/sales` — idempotent on invoice UUID, validates local number payload equality, returns the canonical cloud number.
- `POST /api/sync/products`, `/api/sync/inventory`, `/api/sync/customers`
- `POST /api/sync/purchases`
- `GET /api/sync/changes?cursor=...` — incremental product, customer, supplier,
  and settings download. Returns `{products, customers, suppliers, settings,
  next_cursor}`; UUID is the stable entity key and responses must be idempotent.
- `GET /api/reports/sales`, `/api/reports/inventory`

The database blueprint in `database-schema.sql` deliberately uses integer cents and unique constraints on both UUID and invoice numbers. Cloud numbering must be allocated inside a MySQL transaction using a locked per-branch daily sequence row.
