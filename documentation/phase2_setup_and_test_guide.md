
# Phase 2 — Database Migrations & REST API Testing Guide

## Objective

This guide explains how to update your local PostgreSQL database for the Phase 2 Driver and Vehicle REST APIs and how to run the automated integration tests using an isolated test database.

After completing these steps, you will have:

- Updated `driver` and `vehicle` tables with the required database constraints.
- Automatic ID generation for newly created drivers and vehicles.
- A working FastAPI backend connected to the original local database.
- A separate test database named `cartracking_test`.
- An isolated FastAPI test backend for safely testing CRUD operations.
- A single automated test script covering GET, POST, PUT, and DELETE.

**Important:** The latest `docker-compose.yml` already contains the required configuration for both backends. You do not need to modify the Compose file.

---

## Step 1 — Pull the Latest Repository Changes

Open PowerShell in the project directory:

```powershell
cd C:\Documents\DB-Project
git pull
```

Verify that the latest changes include:

```text
sql/
  migrations/
    001_driver_constraints.sql
    002_vehicle_constraints.sql

backend/
  main.py
  models/
    drivers.py
    vehicles.py
  dao/
    drivers.py
    vehicles.py
  handler/
    drivers.py
    vehicles.py

docker-compose.yml
test_car_tracking_api.py
```

The two SQL migration files update the existing database tables without requiring the original database to be recreated.

---

## Step 2 — Start PostgreSQL

Start the existing PostgreSQL container:

```powershell
docker compose up -d postgres
```

Verify that the container is running:

```powershell
docker compose ps
```

The `car-tracking-db` container should report a healthy status.

**Important:** Do not run `docker compose down -v`. The `-v` flag removes Docker volumes and may delete your existing PostgreSQL data.

### Database configuration

The commands in this guide assume the project's default configuration:

| Setting | Value |
|---|---|
| PostgreSQL service | `postgres` |
| PostgreSQL username | `naturaljoiners` |
| Original database | `cartracking` |
| Test database | `cartracking_test` |
| PostgreSQL port | `5432` |

If your `.env` file uses a different PostgreSQL username or original database name, adjust the commands accordingly.

---

## Step 3 — Apply the Driver Table Migration

The Driver REST API requires the `driver` table to support automatically generated IDs and enforce the required field constraints.

The migration file is:

```text
sql/migrations/001_driver_constraints.sql
```

### What this migration does

- Configures `driver_id` to be automatically generated using PostgreSQL identity.
- Enforces uniqueness for `license_number`.
- Requires `first_name`, `last_name`, `license_number`, and `hired_at` to be non-NULL.
- Preserves existing Phase 1 driver records.
- Synchronizes the identity sequence with the highest existing driver ID.

### Execute the migration

From the project root, run:

```powershell
Get-Content -Raw sql/migrations/001_driver_constraints.sql | docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U naturaljoiners -d cartracking
```

This applies the migration to your existing local `cartracking` database.

**Important:** Apply the migration only if it has not already been applied. The migration may fail if its constraints or identity definition already exist.

### Verify the Driver table

Run:

```powershell
docker compose exec postgres psql -U naturaljoiners -d cartracking -c "\d public.driver"
```

Verify that:

- `driver_id` is a `BIGINT` primary key.
- `driver_id` has an identity definition.
- `license_number` has a unique constraint.
- Required fields are marked `NOT NULL`.

Check the highest existing driver ID:

```powershell
docker compose exec postgres psql -U naturaljoiners -d cartracking -c "SELECT MAX(driver_id) AS highest_driver_id FROM public.driver;"
```

If the original 12 Phase 1 driver records are present and no additional drivers have been inserted, the highest ID should be `12`.

The next generated ID should then be `13`.

---

## Step 4 — Apply the Vehicle Table Migration

The Vehicle REST API requires additional constraints and automatic ID generation.

The migration file is:

```text
sql/migrations/002_vehicle_constraints.sql
```

### What this migration does

- Requires `vehicle_type_id`, `vehicle_status_id`, and `plate_number` to be non-NULL.
- Prevents duplicate vehicle plate numbers.
- Configures `vehicle_id` as a PostgreSQL identity column.
- Synchronizes the identity sequence with the highest existing vehicle ID.
- Sets a default UTC timestamp for `created_at`.
- Preserves existing Phase 1 vehicle records.

### Execute the migration

Run:

```powershell
Get-Content -Raw sql/migrations/002_vehicle_constraints.sql | docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U naturaljoiners -d cartracking
```

This applies the migration to the existing `vehicle` table.

**Important:** Apply this migration only once unless it has been modified to be safely repeatable.

The migration can fail if existing records contain NULL values in required columns, duplicate plate numbers, or an identity definition already exists. Resolve any such issues before retrying.

### Verify the Vehicle table

Run:

```powershell
docker compose exec postgres psql -U naturaljoiners -d cartracking -c "\d public.vehicle"
```

Verify that:

- `vehicle_id` is a primary key with an identity definition.
- `vehicle_type_id` is `NOT NULL`.
- `vehicle_status_id` is `NOT NULL`.
- `plate_number` is `NOT NULL` and has a unique constraint.
- `created_at` has a default timestamp expression.

Check the highest existing vehicle ID:

```powershell
docker compose exec postgres psql -U naturaljoiners -d cartracking -c "SELECT MAX(vehicle_id) AS highest_vehicle_id FROM public.vehicle;"
```

If the original 30 Phase 1 vehicles are present and no additional vehicles have been inserted, the highest ID should be `30`.

The next generated ID should then be `31`.

---

## Step 5 — Start the Original FastAPI Backend

After applying both migrations, build and start the original API:

```powershell
docker compose up -d --build backend
```

Verify the running containers:

```powershell
docker compose ps
```

Open the Swagger UI:

http://localhost:8000/docs

The original backend connects to:

```text
Database: cartracking
API:      http://localhost:8000
```

You can use Swagger UI to inspect the available Driver and Vehicle endpoints.

### Available API endpoints

| Method | Endpoint | Description |
|---|---|---|
| POST | `/api/v1/drivers` | Create driver |
| GET | `/api/v1/drivers` | List drivers |
| GET | `/api/v1/drivers/{driver_id}` | Get driver by ID |
| PUT | `/api/v1/drivers/{driver_id}` | Update driver |
| DELETE | `/api/v1/drivers/{driver_id}` | Delete driver |
| POST | `/api/v1/vehicles` | Create vehicle |
| GET | `/api/v1/vehicles` | List vehicles |
| GET | `/api/v1/vehicles/{vehicle_id}` | Get vehicle by ID |
| PUT | `/api/v1/vehicles/{vehicle_id}` | Update vehicle |
| DELETE | `/api/v1/vehicles/{vehicle_id}` | Delete vehicle |
| GET | `/api/v1/vehicles/{vehicle_id}/current-location` | Get latest vehicle location |

**Do not run automated CRUD tests against port 8000.** This API uses the original local database.

---

## Step 6 — Create the Isolated Test Database

The automated test script performs database write operations, including creating, updating, and deleting records.

To prevent those operations from affecting the original database, the tests use a separate PostgreSQL database named:

```text
cartracking_test
```

Both databases run inside the existing PostgreSQL container.

You do not need to create another PostgreSQL container.

### 6.1 — Create the test database

Run:

```powershell
docker compose exec postgres psql -U naturaljoiners -d postgres -c "CREATE DATABASE cartracking_test OWNER naturaljoiners;"
```

Expected output:

```text
CREATE DATABASE
```

**Note:** This command only needs to be executed once. If `cartracking_test` already exists, skip this step.

### 6.2 — Copy the original database into the test database

After applying both migrations to `cartracking`, create a PostgreSQL backup:

```powershell
docker compose exec -T postgres pg_dump -U naturaljoiners -d cartracking -Fc -f /tmp/cartracking_test_seed.dump
```

Restore that backup into `cartracking_test`:

```powershell
docker compose exec postgres pg_restore -U naturaljoiners -d cartracking_test --no-owner --no-acl /tmp/cartracking_test_seed.dump
```

**Important:** Restore into a newly created, empty `cartracking_test` database. Do not run this restore repeatedly against an already populated test database, since existing tables and constraints can cause conflicts.

The test database will now contain a copy of the original database's tables, constraints, and data.

The backup in `/tmp` is temporary and is stored inside the PostgreSQL container.

### 6.3 — Verify the test database

Check the number of drivers:

```powershell
docker compose exec postgres psql -U naturaljoiners -d cartracking_test -c "SELECT COUNT(*) FROM public.driver;"
```

Check the number of vehicles:

```powershell
docker compose exec postgres psql -U naturaljoiners -d cartracking_test -c "SELECT COUNT(*) FROM public.vehicle;"
```

For the original Phase 1 dataset, the expected counts are:

```text
Drivers:  12
Vehicles: 30
```

If your original database contains additional records, the counts may be different. The important thing is that both databases initially contain matching data.

---

## Step 7 — Start the Isolated Test Backend

The updated `docker-compose.yml` already includes a `backend-test` service.

Start it using:

```powershell
docker compose --profile test up -d --build backend-test
```

Verify the containers:

```powershell
docker compose ps -a
```

You should see:

```text
car-tracking-db         Healthy
car-tracking-api        Running
car-tracking-api-test   Running
```

### Backend comparison

| Backend | Database | API Port |
|---|---|---|
| `backend` | `cartracking` | 8000 |
| `backend-test` | `cartracking_test` | 8001 |

Open the test API Swagger UI:

http://localhost:8001/docs

Both APIs expose the same endpoints, but they use different databases.

### Verify the database connections

Check the original backend:

```powershell
docker compose exec backend printenv DB_NAME
```

Expected:

```text
cartracking
```

Check the test backend:

```powershell
docker compose exec backend-test printenv DB_NAME
```

Expected:

```text
cartracking_test
```

### Verify the actual test database connection

Run:

```powershell
docker compose exec backend-test python -c "from backend.config.dbconfig import initialize_connection_pool, get_db_connection, close_connection_pool; initialize_connection_pool(); c = get_db_connection(); conn = c.__enter__(); cur = conn.cursor(); cur.execute('SELECT current_database(), COUNT(*) FROM public.vehicle'); print('Connected database and vehicle count:', cur.fetchone()); cur.close(); c.__exit__(None, None, None); close_connection_pool()"
```

Example expected output:

```text
Connected database and vehicle count: ('cartracking_test', 30)
```

This confirms that the test backend can actually connect to the isolated database.

---

## Step 8 — Run the Complete API Integration Test Suite

The repository includes one Python test script:

```text
test_car_tracking_api.py
```

This script tests both the Driver and Vehicle REST APIs.

### What is tested?

**GET requests**

- Driver and Vehicle listing.
- Pagination using `limit` and `offset`.
- Invalid pagination parameters.
- Existing and nonexistent IDs.
- Driver name and license filtering.
- Vehicle plate and status filtering.
- Vehicle current-location retrieval.
- GeoJSON response structure.

**POST requests**

- Successful Driver and Vehicle creation.
- Required-field validation.
- Duplicate driver licenses and vehicle plates.
- Invalid timestamps.
- Invalid vehicle foreign keys.
- Invalid field values.

**PUT requests**

- Successful partial updates.
- Persistence of updated values.
- Empty update requests.
- Invalid or NULL fields.
- Invalid vehicle foreign keys.
- Updates to nonexistent records.

**DELETE requests**

- Successful deletion of test-created records.
- Retrieval after deletion.
- Repeated deletion of nonexistent records.
- Invalid record IDs.

### Execute the tests

From the project root, run:

```powershell
python test_car_tracking_api.py --confirm-isolated-test-db
```

The script automatically:

1. Verifies that the original backend uses `cartracking`.
2. Verifies that the test backend uses `cartracking_test`.
3. Confirms the test backend's actual database connection.
4. Creates a backup of `cartracking_test`.
5. Executes the GET, POST, PUT, and DELETE tests.
6. Stops the test backend and restores the test database from its backup.
7. Restarts the test backend and verifies its connection.
8. Displays the final test results.

**Important:** The test script is designed to run against `http://localhost:8001`, not the original backend on port 8000.

Do not run other database operations against `cartracking_test` while the automated test suite is running.

### Expected test results

The integration suite has previously completed with:

```text
============================================================
FINAL TEST RESULTS
============================================================
Passed:  70
Failed:  0
Skipped: 0
Total:   70
============================================================
RESULT: ALL EXECUTED TESTS PASSED
```

Your results should match if the same backend implementation, migrations, and test script are used.

If any tests fail, review the failure messages and the test backend logs.

### Check test backend logs

```powershell
docker compose --profile test logs --tail=100 backend-test
```

---

## Step 9 — Confirm the Test Database Was Restored

After the integration tests finish, the script should display:

```text
[PASS] Test database restored successfully
```

You can independently verify the record counts:

```powershell
docker compose exec postgres psql -U naturaljoiners -d cartracking_test -c "SELECT COUNT(*) FROM public.driver;"
```

```powershell
docker compose exec postgres psql -U naturaljoiners -d cartracking_test -c "SELECT COUNT(*) FROM public.vehicle;"
```

For an unchanged copy of the original Phase 1 dataset, the expected counts are:

```text
Drivers:  12
Vehicles: 30
```

The test script restores the test database from the backup taken immediately before testing. It does not reset the test database to the original Phase 1 dataset if additional records already existed before the run.

If restoration fails, the script reports a fatal error. Do not assume the test database was restored successfully until the issue is resolved.



