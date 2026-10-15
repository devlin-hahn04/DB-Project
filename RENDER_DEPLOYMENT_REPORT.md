# Render PostgreSQL Deployment and Validation Report

**Project:** Car Tracking — Phase I (Database and ETL)  
**Course:** CIIC 4060 / ICOM 5016 — Introduction to Database Systems, Fall 2026  
**Team:** NaturalJoiners  
**Issue:** #8 — Deploy PostgreSQL database to Render  
**Deployment environment:** Render managed PostgreSQL; client commands run from Windows PowerShell with Docker Desktop 

## 1. Objective

Provision a cloud-hosted PostgreSQL 17 database on Render with PostGIS enabled; initialize the schema defined by the project; load the 11 official Parquet datasets via the existing Python ETL pipeline, and verify database structure, content counts, spatial integrity, and external access. The deployment is intended to meet the Phase I requirement that the database be available remotely for grading.

## 2. Provisioned service

| Setting | Observed configuration |
|---|---|
| Platform | Render PostgreSQL |
| Render service | 'car-tracking-db' |
| Region | Virginia (US East) |
| Plan | Free ($0/month) |
| Database name | 'cartracking_nchv' |
| PostgreSQL version | **17.11** |
| PostGIS extension available | **3.6.2** |
| PostGIS version enabled | **3.6** ('USE_GEOS=1', 'USE_PROJ=1', 'USE_STATS=1') |
| Port | '5432' |
| SSL connection | **TLS 1.3** ('sslmode=require') |
| External hostname | 'dpg-db87op4s728c738ghs30-a.virginia-postgres.render.com' |
| Credential used for deployment | 'cartrackingdb_2rg8_user' (password omitted) |

## 3. Setup and verification sequence

### 3.1 Provision the hosted database

1. Opened the Render dashboard and selected **New → Postgres**.
2. Configured the database in **Virginia (US East)** with **PostgreSQL 17**.
3. Selected the Free plan, with storage autoscaling and high availability disabled.
4. Created the database and waited until the service status was Available.
5. Used an external database credential for remote access so the local Docker database and Render database remain separate.

### 3.2 Test external connection and PostgreSQL version

The PostgreSQL 17 client was run in a temporary Docker container. The command prompts for the password interactively without displaying it or placing it into command history:

'powershell
docker run --rm -it postgres:17 psql '
  "host=dpg-db87op4s728c738ghs30-a.virginia-postgres.render.com port=5432 dbname=cartracking_nchv user=cartrackingdb_2rg8_user sslmode=require" '
  -W
'

**Observed:** Connection succeeded; 'psql' identified **PostgreSQL 17.11**, and the connection was encrypted with **TLS 1.3**. '\conninfo' confirmed the correct remote host, database, and authenticated username.

The two roles seen during deployment were expected given the Render role configuration:

'sql
SELECT session_user, current_user, current_database();
'

**Observed:** 'session_user = cartrackingdb_2rg8_user', 'current_user = naturaljoiners', 'current_database = cartracking_nchv'. The credential's role configuration included 'role=naturaljoiners'. All 11 application tables are owned by 'naturaljoiners'.

### 3.3 Verify and enable PostGIS

'sql
SELECT name, default_version
FROM pg_available_extensions
WHERE name = 'postgis';

CREATE EXTENSION IF NOT EXISTS postgis;
SELECT PostGIS_Version();
'

**Observed:** PostGIS was available at version **3.6.2**, the extension was created successfully, and 'PostGIS_Version()' reported **3.6** with GEOS and PROJ support.

### 3.4 Apply the official project schema

To give the temporary PostgreSQL client access to the committed SQL scripts, mounted the project's 'sql' folder read-only:

'powershell
docker run --rm -it '
  -v "${PWD}\sql:/sql:ro" '
  postgres:17 psql '
  "host=dpg-db87op4s728c738ghs30-a.virginia-postgres.render.com port=5432 dbname=cartracking_nchv user=cartrackingdb_2rg8_user sslmode=require" '
  -W -X -v ON_ERROR_STOP=1
'

Then, inside 'psql':

'sql
BEGIN;
\i /sql/schema.sql
COMMIT;
\dt public.*
'

**Observed:** The hosted schema contained **11 application tables** and the PostGIS-managed 'spatial_ref_sys' table (**12 total**). The schema includes the project foreign keys, geometry columns, and five spatial indexes. PostgreSQL reported 'naturaljoiners' as the application table owner.

### 3.5 Verify ETL permissions

Verified the deployment credential's 'INSERT' and 'TRUNCATE' privileges on all 11 application tables:

'sql
SELECT tablename,
       has_table_privilege('cartrackingdb_2rg8_user',
           format('%I.%I', schemaname, tablename), 'INSERT') AS can_insert,
       has_table_privilege('cartrackingdb_2rg8_user',
           format('%I.%I', schemaname, tablename), 'TRUNCATE') AS can_truncate
FROM pg_tables
WHERE schemaname = 'public'
  AND tablename <> 'spatial_ref_sys'
ORDER BY tablename;
'

**Observed:** **11 of 11 tables** returned 't' for both privileges. The pipeline uses a transactional full-refresh strategy, so both privileges are necessary.

## 4. ETL deployment

The Docker ETL image 'db-project-etl:latest', previously built from the project's Python 3.13 Dockerfile, was run with the official 11 Parquet files mounted from 'data/' as read-only. The ETL processes EWKB geometry values using PostGIS functions, including 'ST_GeomFromEWKB(decode(%s, 'hex'))', and stores geometries with SRID 4326.

The password was supplied through a local PowerShell environment variable rather than embedded in a shell command or Git file. After authenticating successfully using 'PGPASSWORD' and 'psql', the value was supplied to the ETL as 'DB_PASSWORD':

'powershell
# $env:PGPASSWORD is set locally from the current Render credential.
$env:DB_PASSWORD = $env:PGPASSWORD

docker run --rm '
  -v "${PWD}\data:/data:ro" '
  -e DB_HOST=dpg-db87op4s728c738ghs30-a.virginia-postgres.render.com '
  -e DB_PORT=5432 '
  -e DB_USER=cartrackingdb_2rg8_user '
  -e DB_PASSWORD '
  -e DB_NAME=cartracking_nchv '
  -e DB_SSLMODE=require '
  -e DATA_DIR=/data '
  db-project-etl:latest
'

For an interactive password entry that avoids saving it in terminal history, the PostgreSQL client can instead use '-W' (Section 3.2). Environment variables are temporary and should be cleared once no longer needed. Be aware that environment variables passed into containers can be inspected by someone with local Docker administrative access; this method avoids Git exposure but is not a substitute for access controls.

**Observed execution log (selected milestones, UTC timestamps from the container):**

| Dataset | Imported rows | Logged load time |
|---|---:|---:|
| 'vehicle_kind' | 5 | 0.25 s |
| 'fuel_type' | 2 | 0.10 s |
| 'vehicle_status' | 2 | 0.10 s |
| 'vehicle_type' | 8 | 0.46 s |
| 'parking_area' | 224 | 11.77 s |
| 'driver' | 12 | 0.66 s |
| 'road_segment' | 4,086 | 209.02 s |
| 'vehicle' | 30 | 1.58 s |
| 'location_ping' | 28,041 | 1,437.57 s |
| 'vehicle_assignment' | 42 | 2.22 s |
| 'trip' | 300 | 15.37 s |
| **Total** | **32,752** | **approximately 28 minutes elapsed** |

The ETL reported:

'text
Row counts verified for all 11 tables
ETL finished successfully
'

**Interpretation:** The full-refresh import completed and committed successfully, and the ETL's source-versus-destination row-count checks passed for all 11 tables. No additional production rerun was performed after the successful import; destructive rerun testing was performed earlier against the separate local development database.

## 5. Remote database validation

Connected again to Render with the SQL directory mounted, disabled the terminal pager, and ran the existing validation script:

'sql
\pset pager off
\i /sql/validation.sql
'

**Actual summary from the Render-hosted database:**

'text
 passed | failed | info | overall
--------+--------+------+---------
    167 |      0 |   17 | PASS
'

The **167 passing checks** covered:

- Schema column names and data types.
- Expected row counts for all 11 entities.
- Primary-key definitions and absence of duplicate or NULL identifiers.
- Foreign-key definitions and absence of orphan rows.
- Expected NULL counts.
- Geometry types ('Point', 'LineString', 'Polygon') and **SRID 4326**.
- PostGIS spatial checks for stored geometries.

The **17 informational results** included geometry extent and validity observations, as well as basic data sanity checks. They were not failures. The script additionally executed representative remote SQL queries, including vehicle joins and spatial operations using 'ST_Within', nearest-road KNN ('<->'), and 'ST_DWithin', these returned results.

## 6. Direct source-to-database value verification

To supplement the schema and row-count checks, we performed a **read-only value-level comparison** of the Render-hosted database against all **11 original Parquet datasets** using the created 'verify_parquet_render.py' which mimics "compare_parquet_csv.py", but with direct connection to PostgreSQL, allowing verification of the Render-hosted database against the original Parquet datasets without requiring CSV exports. The script matched records by primary key and compared all source and destination columns, including numeric fields, timestamps, NULL values, and EWKB/PostGIS geometry values. No records were inserted, updated, or deleted during verification.

The verification script was placed in the project root and executed from PowerShell with the official 'data/' folder mounted read-only. The connection password was supplied through a local environment variable, not embedded in the command:

'powershell
# DB_PASSWORD is set locally from the active Render credential.
docker run --rm '
  -v "${PWD}\data:/data:ro" '
  -v "${PWD}\verify_parquet_render.py:/verify.py:ro" '
  -e DB_HOST=dpg-db87op4s728c738ghs30-a.virginia-postgres.render.com '
  -e DB_PORT=5432 '
  -e DB_USER=cartrackingdb_2rg8_user '
  -e DB_PASSWORD '
  -e DB_NAME=cartracking_nchv '
  -e DB_SSLMODE=require '
  -e DATA_DIR=/data '
  db-project-etl:latest python /verify.py
'

**Actual results from the Render-hosted database:**

| Dataset | Source rows | Database rows | Discrepancies | Result |
|---|---:|---:|---:|---|
| 'vehicle_kind' | 5 | 5 | 0 | PASS |
| 'fuel_type' | 2 | 2 | 0 | PASS |
| 'vehicle_status' | 2 | 2 | 0 | PASS |
| 'vehicle_type' | 8 | 8 | 0 | PASS |
| 'parking_area' | 224 | 224 | 0 | PASS |
| 'driver' | 12 | 12 | 0 | PASS |
| 'road_segment' | 4,086 | 4,086 | 0 | PASS |
| 'vehicle' | 30 | 30 | 0 | PASS |
| 'location_ping' | 28,041 | 28,041 | 0 | PASS |
| 'vehicle_assignment' | 42 | 42 | 0 | PASS |
| 'trip' | 300 | 300 | 0 | PASS |
| **Total** | **32,752** | **32,752** | **0** | **PASS** |

The script reported:

'text
OVERALL: PASS — 11/11 tables have identical per-key values
'

**Interpretation:** All **32,752 records** matched their source counterparts across the values checked by the comparison script, with **zero discrepancies**. This provides direct source-to-destination verification beyond the earlier 167 schema, constraint, count, and spatial checks.

## 7. Security, grading access, and follow-up

**Confirmed from testing:**

- Authorized external connection succeeded with SSL/TLS encryption.
- PostgreSQL 17 and PostGIS were available and working.
- Application tables existed, the official record counts were loaded, and the remote validation suite passed.

## 8. Outcome

**Deployment and technical validation: PASS.** A PostgreSQL **17.11** database with PostGIS **3.6** is running on Render. The project schema is in place, all **32,752** records from eleven official Parquet inputs have been imported using the Python ETL, and remote validation returned **167 PASS, 0 FAIL, 17 INFO**. The additional read-only Parquet-to-Render comparison returned **11/11 tables PASS**, verifying **32,752 source records with 0 discrepancies**. Connectivity, TLS encryption, required permissions, and representative spatial queries were verified.