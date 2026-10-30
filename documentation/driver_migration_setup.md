# PostgreSQL Driver ID Migration — Team Setup

## Objective

Update your local PostgreSQL database so the `driver` table automatically generates a unique `driver_id` whenever a new driver is inserted.

This is required for the Phase 2 Driver REST API (`POST /api/v1/drivers`).

The migration also ensures that:

- `driver_id` is automatically generated using PostgreSQL identity.
- `license_number` is unique.
- Required driver fields cannot be `NULL`.
- Existing driver records are preserved.
- The identity sequence continues after the highest existing driver ID.

## Step 1 — Pull the latest repository changes

Open PowerShell in the project directory:

```powershell
cd C:\Documents\DB-Project
git pull
```

Make sure the latest changes include:

```text
sql/migrations/001_driver_constraints.sql
```

This migration contains the database updates needed for the Driver REST API.

## Step 2 — Start PostgreSQL

Start the existing PostgreSQL Docker container:

```powershell
docker compose up -d postgres
```

Verify that it is running:

```powershell
docker compose ps
```

The PostgreSQL service should be running.

**Important:** Do not use `docker compose down -v`, because that removes Docker volumes and may delete your existing database data.

## Step 3 — Apply the database migration

From the project root, execute:

```powershell
Get-Content -Raw sql/migrations/001_driver_constraints.sql | docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U naturaljoiners -d cartracking
```

This executes the migration against the existing PostgreSQL database.

The migration updates the driver table without requiring the database to be recreated.

**Important:** Run this against the project's intended local database, and verify the migration has not already been applied. Database migrations should be applied once unless specifically written to be repeatable.

## Step 4 — Verify the driver table structure

Run:

```powershell
docker compose exec postgres psql -U naturaljoiners -d cartracking -c "\d public.driver"
```

Verify that:

- `driver_id` is a `BIGINT` primary key.
- `driver_id` has an identity definition.
- `license_number` has a unique constraint.
- `first_name`, `last_name`, `license_number`, and `hired_at` are `NOT NULL`.

## Step 5 — Verify the identity sequence

Run:

```powershell
docker compose exec postgres psql -U naturaljoiners -d cartracking -c "SELECT MAX(driver_id) AS highest_driver_id FROM driver;"
```

If the original Phase 1 data is loaded, the highest ID should normally be `12`.

The migration synchronizes the identity sequence so that newly inserted drivers receive an ID above the existing maximum.

For example, with the original 12 records, the next generated ID should be `13`.

## Step 6 — Test the Driver REST API

Start the backend if it isn't running:

```powershell
docker compose up -d --build
```

Open Swagger UI:

http://localhost:8000/docs

Execute **POST `/api/v1/drivers`** with:

```json
{
  "first_name": "Test",
  "last_name": "Driver",
  "license_number": "PR-TEST-9001",
  "hired_at": "2025-01-15T09:00:00Z"
}
```

Expected result:

**HTTP 201 — Created**

The response should contain a generated `driver_id`, without requiring the client to provide one.

Finally, delete the test driver through the DELETE endpoint using the returned ID.

## Expected final result

After completing these steps, your local PostgreSQL database should support automatic driver ID generation and the constraints required by the Phase 2 Driver REST API.

Your original Phase 1 records should remain intact.
