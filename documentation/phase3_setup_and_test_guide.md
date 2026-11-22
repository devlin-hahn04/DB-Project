# Issue #2 — User Registration & Authentication
## Setup and Testing Guide

### Overview
Implemented user registration and authentication using **FastAPI, PostgreSQL, Argon2id password hashing, and JWT tokens**, following the existing Handler/DAO architecture.

**New endpoints:**
- `POST /api/v1/auth/register` — Register a user.
- `POST /api/v1/auth/login` — Authenticate and receive a JWT.
- `GET /api/v1/auth/me` — Retrieve the authenticated user's information.

### 1. Environment Configuration

Add the following variables to your local `.env`:

```dotenv
JWT_SECRET_KEY=<your-secure-random-secret>
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=30
```

Generate a secret with:

```powershell
python -c "import secrets; print(secrets.token_hex(32))"
```

Ensure the existing PostgreSQL environment variables are configured. The `.env` file must remain excluded from Git.

### 2. Start PostgreSQL

From the project root:

```powershell
docker compose config --quiet
docker compose up -d postgres
docker compose ps
```

### 3. Apply Database Migration

Migration: `sql/migrations/008_create_app_users.sql`

Apply to the local development database:

```powershell
Get-Content -Raw .\sql\migrations\008_create_app_users.sql |
    docker compose exec -T postgres psql -X -v ON_ERROR_STOP=1 -U naturaljoiners -d cartracking
```

Apply to the isolated testing database:

```powershell
Get-Content -Raw .\sql\migrations\008_create_app_users.sql |
    docker compose exec -T postgres psql -X -v ON_ERROR_STOP=1 -U naturaljoiners -d cartracking_test
```

Run each migration only once per database. Replace the username if your local PostgreSQL role differs.

### 4. Rebuild and Start the Backend

```powershell
docker compose --profile test up -d --build --force-recreate backend backend-test
```

Verify container status:

```powershell
docker compose --profile test ps
docker compose --profile test logs --tail=50 backend-test
```

**Local services:**
- Development API: `http://127.0.0.1:8000`
- Testing API: `http://127.0.0.1:8001`
- Testing Swagger UI: `http://127.0.0.1:8001/docs`

### 5. Verify API Connectivity

```powershell
Invoke-RestMethod http://127.0.0.1:8001/api/v1/health

Invoke-RestMethod http://127.0.0.1:8001/api/v1/health/database
```

The database health response must identify `cartracking_test`.

### 6. Run Integration Tests

Test file: `backend/tests/test_full_api_integration.py`

```powershell
$env:CARTRACKING_E2E_ALLOW_WRITES = "cartracking_test"

python -m unittest discover -s backend/tests -p test_full_api_integration.py -v
```

The integration suite verifies registration, database persistence, duplicate email rejection, Argon2id hashing, JWT login, token expiration, authorization, invalid credentials, and the existing Phase 2 endpoints.

**Important:** Execute only against the isolated `cartracking_test` database. Tests perform database writes and cleanup.

### 7. Verify Cleanup

```powershell
docker compose exec postgres psql -U naturaljoiners -d cartracking_test -c "SELECT COUNT(*) FROM public.app_user;"
```

Expected result after the test suite: `0`, assuming no pre-existing users.

### Verified Results

- **78/78 integration tests passed**
- **69** original Phase 2 tests passed
- **6** authentication tests passed
- **3** final database preservation tests passed
- No remaining test authentication accounts
- Original database records preserved
- Local database migrations successful

**Status:** Issue #2 implementation and local integration testing completed successfully. Production deployment to Render remains deferred.