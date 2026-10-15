# Car Tracking Database Project

A PostgreSQL 17 database project using PostGIS for geospatial data storage and Python for ETL processing.

## Project Structure

```text
DB-Project/
├── data/                         # Official Parquet datasets (not tracked by Git)
│   ├── driver.parquet
│   ├── fuel_type.parquet
│   ├── location_ping.parquet
│   ├── parking_area.parquet
│   ├── road_segment.parquet
│   ├── trip.parquet
│   ├── vehicle_assignment.parquet
│   ├── vehicle_kind.parquet
│   ├── vehicle_status.parquet
│   ├── vehicle_type.parquet
│   └── vehicle.parquet
├── ETL/
│   ├── compare_parquet_csv.py    # Compare Parquet data against PostgreSQL CSV exports
│   ├── Dockerfile                # Docker image for the ETL pipeline
│   └── main.py                   # Python ETL pipeline
├── sql/
│   ├── schema.sql                # PostgreSQL relational database schema
│   └── validation.sql            # Database integrity and spatial validation tests
├── .dockerignore                 # Files excluded from Docker builds
├── .env                          # Local credentials (not tracked by Git)
├── .env.example                  # Example environment variables
├── .gitignore                    # Files excluded from Git
├── docker-compose.yml            # PostgreSQL and ETL service configuration
├── README.md                     # Project setup and usage documentation
├── RENDER_DEPLOYMENT_REPORT.md   # Render deployment and verification report
├── REPRODUCIBILITY_TEST.md       # Independent ETL reproducibility test report
├── requirements.txt              # Python dependencies
└── verify_parquet_render.py      # Direct Parquet vs. Render data verification
```

## Prerequisites

- Git
- Docker Desktop with Docker Compose
- Python 3 (for the ETL pipeline)

## Local Database Setup

### 1. Clone the Repository

```bash
git clone https://github.com/devlin-hahn04/DB-Project.git
cd DB-Project
```

### 2. Configure Environment Variables

Copy `.env.example` into a new `.env` file.

Edit `.env` and provide your local database credentials:

```dotenv
DB_USER=your_username
DB_PASSWORD=your_password
DB_NAME=cartracking
```

The `.env` file is excluded from Git to prevent credentials from being committed.

### 3. Start PostgreSQL

Make sure Docker Desktop is running, then execute:

```bash
docker compose up -d
```

This starts PostgreSQL 17 with PostGIS in a Docker container.

Verify that the container is running:

```bash
docker compose ps
```

The database container should appear with a status of `Up` or `running`.

### 4. Create the Database Schema

The database schema is defined in `sql/schema.sql`.

It contains:

- 11 relational tables
- 11 primary keys
- 8 foreign-key relationships
- 5 PostGIS geometry columns using SRID 4326
- 5 GiST spatial indexes

After starting PostgreSQL, execute the schema from the VS Code PowerShell terminal:

```powershell
Get-Content .\sql\schema.sql -Raw | docker exec -i car-tracking-db psql -X -v ON_ERROR_STOP=1 -1 -U your_username -d cartracking
```

Replace `your_username` with the value of `DB_USER` in your `.env` file. If you configured a different `DB_NAME`, replace `cartracking` as well.

#### How the Command Works

- `Get-Content .\sql\schema.sql -Raw` reads the SQL file.
- `docker exec -i` sends the SQL into the running Docker container.
- `psql` executes the SQL statements against PostgreSQL.
- `-X` prevents local `psql` startup settings from affecting execution.
- `ON_ERROR_STOP=1` stops execution if an SQL error occurs.
- `-1` executes the script in a single transaction, rolling back changes if an error occurs.

#### Expected Output

The initialization should produce:

- 11 `CREATE TABLE` messages
- 5 `CREATE INDEX` messages
- A successful PostGIS extension initialization

A notice indicating that the PostGIS extension already exists is normal.

**Important:** Execute the schema only when initializing a new database. Running the same script again after the tables exist will result in `relation already exists` errors.

### 5. Connect to PostgreSQL

From your terminal:

```powershell
docker exec -it car-tracking-db psql -U your_username -d cartracking
```

Replace `your_username` with your configured database username.

After connecting, you should see a PostgreSQL prompt similar to:

```text
psql (17.5)
Type "help" for help.

cartracking=#
```

You can now execute SQL queries directly inside PostgreSQL.

### 6. Verify PostgreSQL and PostGIS

Inside the PostgreSQL terminal, execute:

```sql
SELECT current_database(), current_user;

SELECT PostGIS_Version();
```

The first query should return your configured database name and username.

The second should return the installed PostGIS version.

### 7. Verify the Database Tables

List all tables in the `public` schema:

```sql
\dt public.*
```

#### Expected Result

```text
                   List of relations
 Schema |        Name        | Type  |     Owner
--------+--------------------+-------+----------------
 public | driver             | table | your_username
 public | fuel_type          | table | your_username
 public | location_ping      | table | your_username
 public | parking_area       | table | your_username
 public | road_segment       | table | your_username
 public | spatial_ref_sys    | table | your_username
 public | trip               | table | your_username
 public | vehicle            | table | your_username
 public | vehicle_assignment | table | your_username
 public | vehicle_kind       | table | your_username
 public | vehicle_status     | table | your_username
 public | vehicle_type       | table | your_username
(12 rows)
```

The database contains **11 project tables** and one PostGIS system table (`spatial_ref_sys`).

The table owner may vary depending on the database configuration.

#### Project Tables

| Table | Description |
|---|---|
| `vehicle_kind` | Vehicle categories |
| `fuel_type` | Supported fuel types |
| `vehicle_status` | Vehicle status information |
| `vehicle_type` | Vehicle classification and emissions information |
| `vehicle` | Registered vehicle information |
| `driver` | Driver information |
| `parking_area` | Parking locations and capacities |
| `road_segment` | Road network segments |
| `location_ping` | Vehicle GPS location records |
| `vehicle_assignment` | Driver-to-vehicle assignments |
| `trip` | Vehicle trip information |

### 8. Verify Foreign-Key Relationships

Execute the following SQL query to inspect all foreign-key relationships:

```sql
SELECT
    conrelid::regclass AS table_name,
    conname AS constraint_name,
    confrelid::regclass AS references_table
FROM pg_constraint
WHERE contype = 'f'
  AND connamespace = 'public'::regnamespace
ORDER BY table_name, constraint_name;
```

#### Expected Result

```text
     table_name     |          constraint_name           | references_table
--------------------+------------------------------------+------------------
 location_ping      | location_ping_vehicle_id_fkey      | vehicle
 trip               | trip_vehicle_id_fkey               | vehicle
 vehicle            | vehicle_vehicle_status_id_fkey     | vehicle_status
 vehicle            | vehicle_vehicle_type_id_fkey       | vehicle_type
 vehicle_assignment | vehicle_assignment_driver_id_fkey  | driver
 vehicle_assignment | vehicle_assignment_vehicle_id_fkey | vehicle
 vehicle_type       | vehicle_type_fuel_type_id_fkey     | fuel_type
 vehicle_type       | vehicle_type_vehicle_kind_id_fkey  | vehicle_kind
(8 rows)
```

The query should return **8 foreign-key relationships**, matching the database schema.

### 9. Verify PostGIS Geometry Columns

Execute the following query to verify the geometry types and spatial reference system:

```sql
SELECT
    f_table_name,
    f_geometry_column,
    type,
    srid
FROM geometry_columns
WHERE f_table_schema = 'public'
ORDER BY f_table_name, f_geometry_column;
```

#### Expected Result

```text
 f_table_name  | f_geometry_column |    type    | srid
---------------+-------------------+------------+------
 location_ping | geom              | POINT      | 4326
 parking_area  | geom              | POLYGON    | 4326
 road_segment  | geom              | LINESTRING | 4326
 trip          | end_geom          | POINT      | 4326
 trip          | start_geom        | POINT      | 4326
(5 rows)
```

All spatial columns use **SRID 4326 (WGS84)**.

The geometry types are:

- `POINT` — Represents a geographic location, such as a vehicle GPS position.
- `LINESTRING` — Represents a connected sequence of points, such as a road segment.
- `POLYGON` — Represents a geographic area, such as a parking area.

### 10. Exit PostgreSQL

To exit the PostgreSQL terminal:

```sql
\q
```

## ETL Pipeline

`ETL/main.py` loads the 11 official Parquet datasets into the schema exactly as provided, with no ORM. It uses `pyarrow` to read the files and `psycopg` to execute parameterized PostgreSQL `INSERT` statements. Geometry values are explicitly converted into PostGIS geometries using `ST_GeomFromEWKB(decode(%s, 'hex'))`.

What a run does:

1. Reads every Parquet file. It checks that each file's columns match the target table's columns and types before touching the database.
2. Connects and checks that all 11 tables exist. If they don't, run `sql/schema.sql` first (step 4 above).
3. Truncates the 11 tables and loads them in foreign-key order: `vehicle_kind`, `fuel_type`, `vehicle_status`, `vehicle_type`, `parking_area`, `driver`, `road_segment`, `vehicle`, `location_ping`, `vehicle_assignment`, `trip`.
4. Checks that each table's row count matches its Parquet file.

Everything runs in a single transaction. If any step fails, nothing is committed. Rerunning the ETL always leaves the tables matching the Parquet files exactly.

Geometry columns are provided as hexadecimal EWKB strings containing SRID 4326. During insertion, these values are explicitly converted into PostGIS geometry objects using `ST_GeomFromEWKB(decode(%s, 'hex'))`, following the professor's recommended SQL approach. The original spatial data and coordinate reference system are preserved.

### 1. Add the Data

Copy the 11 `.parquet` files from Moodle (Project/Project data) into the `data/` folder. Git does not track that folder.

```text
data/
├── driver.parquet
├── fuel_type.parquet
├── location_ping.parquet
├── parking_area.parquet
├── road_segment.parquet
├── trip.parquet
├── vehicle.parquet
├── vehicle_assignment.parquet
├── vehicle_kind.parquet
├── vehicle_status.parquet
└── vehicle_type.parquet
```

To read the files from another folder, set `DATA_DIR` in `.env`.

### 2. Run the ETL (Docker)

With the database running and the schema created:

```powershell
docker compose run --rm etl
```

This builds a small Python container on the first run and starts PostgreSQL if needed. It then runs the ETL against the local `car-tracking-db` database.

After code or dependency changes, rebuild with `docker compose build etl`.

### 2b. Run the ETL (Native Python, Optional)

Some Windows machines with Smart App Control block `pyarrow`, so use Docker on those. Elsewhere:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python ETL/main.py
```

The script reads its settings from environment variables, not from `.env`. Set `DB_USER`, `DB_PASSWORD` and `DB_NAME` in the shell first, for example `$env:DB_USER="..."`. `DB_HOST` defaults to `localhost` and `DB_PORT` to `5432`.

### Expected Output

```text
... INFO    Read vehicle_kind               5 rows
...
... INFO    Loaded trip                     300 rows in 0.05s
... INFO    Row counts verified for all 11 tables
... INFO    ETL finished successfully
```

| Table | Rows |
|---|---|
| `vehicle_kind` | 5 |
| `fuel_type` | 2 |
| `vehicle_status` | 2 |
| `vehicle_type` | 8 |
| `parking_area` | 224 |
| `driver` | 12 |
| `road_segment` | 4086 |
| `vehicle` | 30 |
| `location_ping` | 28041 |
| `vehicle_assignment` | 42 |
| `trip` | 300 |

On failure, the ETL logs the reason and exits with a non-zero code without changing the database. Examples: a missing file, a column mismatch, a missing table, or a connection error.

## Data Validation

Validation runs at two levels, and neither one modifies the data:

1. **`sql/validation.sql`** checks the database itself: the schema, row counts, keys, NULLs, PostGIS geometries and a set of representative queries. Run it against the local container or against Render.
2. **`ETL/compare_parquet_csv.py`** compares every exported row against the original Parquet files, value by value.

### Filtered or Rejected Records

None. The ETL loads all 32,752 records exactly as provided, with no cleaning, filtering, deduplication or value changes, as the project specification requires. If any row fails to insert, the whole load rolls back and the ETL exits with an error, so the database never holds a partial load. Checks marked `INFO` below only report on the data; nothing they flag is ever corrected.

### 1. Database Validation (SQL)

With the ETL loaded, run from the project root:

```powershell
Get-Content .\sql\validation.sql -Raw | docker exec -i car-tracking-db psql -X -v ON_ERROR_STOP=1 -U naturaljoiners -d cartracking
```

To validate the Render database, pass its external connection URL instead of `-U`/`-d`:

```powershell
Get-Content .\sql\validation.sql -Raw | docker exec -i car-tracking-db psql -X -v ON_ERROR_STOP=1 "postgresql://USER:PASSWORD@HOST/DBNAME?sslmode=require"
```

The script is read-only. It creates only session-scoped `TEMP` tables, which are dropped when it finishes.

| Section | What it checks | Status |
|---|---|---|
| 1. Schema | All 11 tables and 54 columns exist with the names and data types from the table diagram, including geometry type and SRID. Unexpected columns are also flagged. | PASS/FAIL |
| 2. Row counts | Each table matches its Parquet file's row count. | PASS/FAIL |
| 3. Primary keys | Each table has its primary key on the expected column, with no duplicate or NULL ids. | PASS/FAIL |
| 4. Foreign keys | All 8 foreign-key constraints exist and no row references a missing parent. | PASS/FAIL |
| 5. NULLs | Per-column NULL counts match the source. The only NULLs are `location_ping.heading_deg` (300) and `vehicle_assignment.assigned_to` (30, open-ended assignments). | PASS/FAIL |
| 6. PostGIS | `geometry_columns` registration, plus every stored value's SRID (4326) and geometry type. | PASS/FAIL |
| 6. PostGIS | Coordinates fall inside a Puerto Rico bounding box (catches swapped longitude/latitude), and geometries are valid and non-empty. | INFO |
| 7. Sanity | Trips ending before they start, negative distances or speeds, headings outside 0–360, assignments ending before they start. | INFO |
| 8. Representative queries | Relational joins (vehicle details, driver assignment history, trips per vehicle) and spatial queries (`ST_Within`, nearest road with `<->`, `ST_DWithin`). Shown for review. | — |

#### Expected Result

```text
========================= SUMMARY ==========================
 passed | failed | info | overall
--------+--------+------+---------
    167 |      0 |   17 | PASS
```

Every `INFO` check reports 0 problems: all coordinates are inside Puerto Rico in longitude/latitude order, and all geometries are valid. The only non-zero `INFO` rows are the expected NULLs (300 pings without a heading and 30 open-ended assignments).

Any `FAIL` row names the table and column and shows the actual and expected values.

### 2. Parquet vs. PostgreSQL Comparison

To verify data integrity, the imported PostgreSQL records can be cross-referenced against the original Parquet datasets using `ETL/compare_parquet_csv.py`.

The script compares all 11 datasets, including record counts, column values, timestamps, NULL values, and EWKB geometry representations.

**Step 1 — Run the ETL**

Ensure the database is running, the schema exists, and all 11 Parquet files are inside `data/`.

```powershell
docker compose build etl
docker compose run --rm etl
```

**Step 2 — Export PostgreSQL tables to CSV**

Run the following commands from the project root in PowerShell:

```powershell
$tables = @(
    "driver",
    "fuel_type",
    "location_ping",
    "parking_area",
    "road_segment",
    "trip",
    "vehicle",
    "vehicle_assignment",
    "vehicle_kind",
    "vehicle_status",
    "vehicle_type"
)

New-Item -ItemType Directory -Force -Path .\db_exports | Out-Null

foreach ($table in $tables) {
    docker exec car-tracking-db psql `
        -U naturaljoiners `
        -d cartracking `
        -c "\copy (SELECT * FROM public.$table) TO '/tmp/$table.csv' WITH (FORMAT csv, HEADER true)"

    docker cp "car-tracking-db:/tmp/$table.csv" ".\db_exports\$table.csv"
}
```

The CSV files will be saved in `db_exports/`. Exporting inside Docker avoids Windows PowerShell character-encoding issues.

**Step 3 — Run the comparison script**

```powershell
docker compose run --rm `
  -v "${PWD}/db_exports:/exports:ro" `
  etl python ETL/compare_parquet_csv.py
```

The script reads the original Parquet files from `/data` and the exported PostgreSQL CSV files from `/exports`.

**Expected Results**

```text
driver               PASS parquet=    12 csv=    12 differences=0
fuel_type            PASS parquet=     2 csv=     2 differences=0
location_ping        PASS parquet= 28041 csv= 28041 differences=0
parking_area         PASS parquet=   224 csv=   224 differences=0
road_segment         PASS parquet=  4086 csv=  4086 differences=0
trip                 PASS parquet=   300 csv=   300 differences=0
vehicle              PASS parquet=    30 csv=    30 differences=0
vehicle_assignment   PASS parquet=    42 csv=    42 differences=0
vehicle_kind         PASS parquet=     5 csv=     5 differences=0
vehicle_status       PASS parquet=     2 csv=     2 differences=0
vehicle_type         PASS parquet=     8 csv=     8 differences=0

OVERALL: PASS — 0 differences
```

**Validation Summary:** All 32,752 records across 11 tables were successfully verified, with zero differences between the original Parquet files and PostgreSQL exports. Original geometry values and NULL values were preserved.

The `db_exports/` directory contains generated test artifacts and is ignored by Git.

## PostGIS Spatial Configuration

The Car Tracking database uses PostgreSQL 17 with the PostGIS extension to support geographic data.

### Spatial Data

All geometry columns use **SRID 4326 (WGS84)**, with coordinates stored in longitude-latitude order.

The database contains five spatial columns:

| Table | Column | Geometry Type |
|---|---|---|
| `parking_area` | `geom` | POLYGON |
| `road_segment` | `geom` | LINESTRING |
| `location_ping` | `geom` | POINT |
| `trip` | `start_geom` | POINT |
| `trip` | `end_geom` | POINT |

### Spatial Indexes

Five GiST spatial indexes are defined in `sql/schema.sql` to support efficient spatial queries.

- `idx_parking_area_geom`
- `idx_road_segment_geom`
- `idx_location_ping_geom`
- `idx_trip_start_geom`
- `idx_trip_end_geom`

These indexes are created automatically when initializing a fresh database using `schema.sql`.

For an existing database, execute only the new `CREATE INDEX` statements rather than rerunning the entire schema.

#### Verify Spatial Indexes

Execute the following query inside PostgreSQL:

```sql
SELECT
    tablename,
    indexname
FROM pg_indexes
WHERE schemaname = 'public'
  AND indexdef ILIKE '%USING gist%'
ORDER BY tablename, indexname;
```

#### Expected Result

```text
   tablename   |       indexname
---------------+------------------------
 location_ping | idx_location_ping_geom
 parking_area  | idx_parking_area_geom
 road_segment  | idx_road_segment_geom
 trip          | idx_trip_end_geom
 trip          | idx_trip_start_geom
(5 rows)
```

## Useful Docker Commands

Run these commands from your system terminal, such as VS Code PowerShell.

| Command | Description |
|---|---|
| `docker compose up -d` | Start the database |
| `docker compose down` | Stop and remove the container while retaining database data |
| `docker compose ps` | Check container status |
| `docker ps` | List running Docker containers |
| `docker compose logs postgres` | View PostgreSQL logs |
| `docker exec -it car-tracking-db psql -U your_username -d cartracking` | Connect to PostgreSQL |
| `docker compose restart` | Restart the database service |

**Important:** Do not use `docker compose down -v` unless you intentionally want to delete the database volume and its stored data.

## Useful PostgreSQL Commands

These commands are executed inside the PostgreSQL terminal (`psql`).

| Command | Purpose |
|---|---|
| `\dt public.*` | List all tables in the public schema |
| `\d table_name` | Inspect a table's structure and constraints |
| `\d public.vehicle` | Inspect the vehicle table |
| `SELECT * FROM table_name LIMIT 10;` | Preview records |
| `SELECT COUNT(*) FROM table_name;` | Count records |
| `SELECT current_database(), current_user;` | Verify database connection |
| `SELECT PostGIS_Version();` | Verify PostGIS installation |
| `\pset pager off` | Disable paginated output |
| `\q` | Exit PostgreSQL |

## Database Schema Notes

- The schema is implemented using native PostgreSQL SQL without an ORM.
- All 11 project tables use `BIGINT` primary keys.
- The database includes 8 foreign-key relationships.
- Spatial columns use PostGIS `GEOMETRY` types with SRID 4326.
- Five GiST indexes support spatial queries.
- The `sql/schema.sql` file is version-controlled so each developer can initialize the same database structure locally.
- Database contents and Docker volumes are not shared through GitHub. Each developer maintains their own local database.
## Reproducible ETL and Clean Database Initialization

This issue was independently tested by a second team member to confirm that the database can be initialized from scratch and populated from the official Parquet datasets without relying on an existing, preloaded database. The testing results are recorded in `REPRODUCIBILITY_TEST.md`.

### 1. Create a Separate Clean Test Database

With the local Docker PostgreSQL container running, create a new database instead of using the existing `cartracking` database:

```powershell
docker compose up -d postgres

docker exec car-tracking-db psql -U naturaljoiners -d postgres -c "CREATE DATABASE cartracking_fresh_test;"
```

The fresh database starts without the application tables or imported project records. If your local database username is different, replace `naturaljoiners` in these commands with your configured `DB_USER`.

### 2. Initialize the Schema from Scratch

From the project root in VS Code PowerShell:

```powershell
Get-Content .\sql\schema.sql -Raw | docker exec -i car-tracking-db psql -X -v ON_ERROR_STOP=1 -1 -U naturaljoiners -d cartracking_fresh_test
```

This creates the 11 application tables, primary-key and foreign-key constraints, PostGIS geometry columns, and five GiST spatial indexes. It also enables the PostGIS extension. Using `-1` makes schema initialization transactional.

### 3. Load All Parquet Datasets Using the ETL

Place all 11 official `.parquet` files in `data/`, then execute:

```powershell
docker compose run --rm -e DB_NAME=cartracking_fresh_test etl
```

The Docker ETL container reads the official Parquet files, connects to the new database, inserts records in the proper foreign-key order, and checks the final counts. The clean initialization test successfully loaded **32,752 records across 11 application tables**, with no source records filtered or rejected.

### 4. Test Repeatability

Run the same ETL command a second time:

```powershell
docker compose run --rm -e DB_NAME=cartracking_fresh_test etl
```

**Observed result:** The second run completed successfully with the same row counts and no duplicated records. The ETL truncates and reloads the application tables in one transaction, so repeat runs recreate the expected contents rather than adding duplicate records.

### 5. Test Failures Without Altering Existing Records

The secondary testing also included deliberately invalid configurations:

**Missing required database username:**

```powershell
docker compose run --rm -e DB_NAME=cartracking_fresh_test -e DB_USER= etl
```

**Missing Parquet data directory:**

```powershell
docker compose run --rm -e DB_NAME=cartracking_fresh_test -e DATA_DIR=/missing-data etl
```

**Observed result:** Both tests returned clear errors. The ETL aborted without committing changes, and the previously loaded `location_ping` table retained all **28,041 rows**. These tests confirmed that failures are handled without leaving a partially reloaded database.

### 6. Validate the Fresh Database

Run the read-only validation suite against the fresh database:

```powershell
Get-Content .\sql\validation.sql -Raw | docker exec -i car-tracking-db psql -X -v ON_ERROR_STOP=1 -U naturaljoiners -d cartracking_fresh_test
```

**Actual test summary:**

```text
========================= SUMMARY ==========================
 passed | failed | info | overall
--------+--------+------+---------
    167 |      0 |   17 | PASS
```

Validation covered table structures, expected record counts, primary keys, foreign keys, NULL values, PostGIS geometry types and SRIDs, and representative relational and spatial queries. No validation failures were reported.

### 7. Reproducibility Result

The independent tester confirmed that the schema and ETL could be used to build a complete database from a clean starting point, repeat the import without duplicating records, and safely stop on invalid configuration or missing input files. The detailed procedure and evidence are documented in `REPRODUCIBILITY_TEST.md`.

## Deploy PostgreSQL Database to Render

The project database was deployed to Render so that a PostgreSQL 17/PostGIS instance would be available remotely for grading. The setup, issues encountered, test results, and verification evidence are documented in `RENDER_DEPLOYMENT_REPORT.md`.

### 1. Render Database Specifications

| Setting | Render configuration |
|---|---|
| Provider | Render managed PostgreSQL |
| Service name | `car-tracking-db` |
| Region | Virginia (US East) |
| Plan | Free |
| PostgreSQL version | `17.11` |
| PostGIS available version | `3.6.2` |
| Enabled PostGIS version | `3.6` |
| Database name | `cartracking_nchv` |
| External hostname | `dpg-db87op4s728c738ghs30-a.virginia-postgres.render.com` |
| Port | `5432` |
| External database username | `cartrackingdb_2rg8_user` |
| Password | `dvAXpDOZkDMOwD7o1K4NRY54C43jNWrP` |
| SSL mode | `require` |
| Verified encrypted connection | TLS 1.3 |
| Project application tables | 11 |
| PostGIS system table | `spatial_ref_sys` |
| Geometry SRID | `4326` (WGS84) |
| Loaded project records | 32,752 |

**Render DB username:** cartrackingdb_2rg8_user
**Render DB Password:** dvAXpDOZkDMOwD7o1K4NRY54C43jNWrP

Render is a separate hosted database; its username, database name, hostname, and password are not the same as the local Docker settings. The Render database has a PostgreSQL role configuration under which the authenticated `session_user` is `cartrackingdb_2rg8_user` and `current_user` is `naturaljoiners`.

### 2. Connect to Render from PowerShell

From the project root, use a temporary PostgreSQL client container. It asks for the password without displaying it:

```powershell
docker run --rm -it `
  -v "${PWD}\sql:/sql:ro" `
  postgres:17 psql `
  "host=dpg-db87op4s728c738ghs30-a.virginia-postgres.render.com port=5432 dbname=cartracking_nchv user=cartrackingdb_2rg8_user sslmode=require" `
  -W -X -v ON_ERROR_STOP=1
```

The `sql/` folder is mounted read-only inside the client at `/sql`. Inside `psql`, verify the connection and database configuration:

```sql
\pset pager off
\conninfo
SELECT session_user, current_user, current_database();
SELECT version();
SELECT PostGIS_Version();
\dt public.*
```

**Observed result:** Remote login succeeded using SSL/TLS, PostgreSQL 17.11 was available, the PostGIS extension was working, and the database contained 11 project tables plus the PostGIS `spatial_ref_sys` table.

### 3. Create the Hosted Database Schema

When initializing a brand-new Render database, connect using the command above and run:

```sql
BEGIN;
\i /sql/schema.sql
COMMIT;
```

**Important:** This schema step was already completed on the deployed Render database. Do not rerun `schema.sql` against the existing populated database because its tables already exist.

The deployed schema includes all 11 project tables, eight foreign-key relationships, five SRID 4326 geometry columns, and five GiST spatial indexes.

### 4. Import the Official Parquet Files to Render

First build the ETL Docker image if it is not already available:

```powershell
docker compose build etl
```

Set the current authorized Render password for this PowerShell session without printing it:

```powershell
$securePassword = Read-Host "Render database password" -AsSecureString
$env:DB_PASSWORD = [System.Net.NetworkCredential]::new("", $securePassword).Password
```

Then run the ETL with the Render connection variables explicitly specified:

```powershell
docker run --rm `
  -v "${PWD}\data:/data:ro" `
  -e DB_HOST=dpg-db87op4s728c738ghs30-a.virginia-postgres.render.com `
  -e DB_PORT=5432 `
  -e DB_USER=cartrackingdb_2rg8_user `
  -e DB_PASSWORD `
  -e DB_NAME=cartracking_nchv `
  -e DB_SSLMODE=require `
  -e DATA_DIR=/data `
  db-project-etl:latest
```

**Observed result:** The ETL successfully loaded **32,752 records across all 11 tables** and verified the expected row counts. The one-time remote import took approximately **28 minutes**, much longer than local Docker loading because records were inserted over an external network connection. Do not rerun the hosted ETL unless a refresh is actually required; it truncates and reloads the hosted tables.

Remove the PowerShell password variable after use:

```powershell
Remove-Item Env:DB_PASSWORD -ErrorAction SilentlyContinue
```

### 5. Validate the Hosted Database

Reconnect to Render using the interactive `psql` command in Step 2 and execute:

```sql
\i /sql/validation.sql
```

**Actual Render validation summary:**

```text
========================= SUMMARY ==========================
 passed | failed | info | overall
--------+--------+------+---------
    167 |      0 |   17 | PASS
```

All schema, constraint, row-count, and geometry checks passed. The remote tests also confirmed that PostGIS spatial queries such as `ST_Within`, `ST_DWithin`, and nearest-road ordering with `<->` executed successfully.

### 6. Compare the Hosted Data Directly with Parquet Sources

The independent script `verify_parquet_render.py` performs a read-only, source-to-database comparison. It connects to Render, reads each of the 11 original Parquet datasets, and compares the stored records by primary key and values, including the relevant geographic information.

With the authorized Render password temporarily set as `DB_PASSWORD`, run from the project root:

```powershell
docker run --rm `
  -v "${PWD}\data:/data:ro" `
  -v "${PWD}\verify_parquet_render.py:/verify.py:ro" `
  -e DB_HOST=dpg-db87op4s728c738ghs30-a.virginia-postgres.render.com `
  -e DB_PORT=5432 `
  -e DB_USER=cartrackingdb_2rg8_user `
  -e DB_PASSWORD `
  -e DB_NAME=cartracking_nchv `
  -e DB_SSLMODE=require `
  -e DATA_DIR=/data `
  db-project-etl:latest python /verify.py
```

**Actual verification result:**

```text
OVERALL: PASS — 11/11 tables have identical per-key values
```

| Verification | Result |
|---|---|
| Source Parquet datasets | 11 |
| Render application tables | 11 |
| Source records compared | 32,752 |
| Data discrepancies | 0 |
| SQL validation | 167 PASS / 0 FAIL / 17 INFO |
| PostGIS spatial queries | PASS |

This establishes that the Render-hosted records matched the official Parquet data in the values checked, not just in their total row counts.

After verification, clear the password variable:

```powershell
Remove-Item Env:DB_PASSWORD -ErrorAction SilentlyContinue
```

### 7. Render Deployment Problems and Resolutions

| Issue encountered | Resolution |
|---|---|
| Incorrect placeholder hostname during connection testing | Used Render's actual external database hostname. |
| Difficulty passing a password when piping SQL into a remote client | Used an interactive Docker `psql` client with `-W` and mounted `sql/` read-only. |
| Authentication error while configuring the remote ETL | Corrected the password passed through PowerShell and retested the connection. |
| `psql` output appeared to pause | Disabled the output pager with `\pset pager off`. |
| ETL inserts were significantly slower on Render than locally | Allowed the complete remote import to finish and verified all expected records afterward. |

### 8. Deployment Result and Report

The cloud-hosted Deployment delivered a remotely accessible PostgreSQL 17/PostGIS database on Render containing **all 32,752 official project records**. The remote schema, relationships, geometry data, spatial queries, and Parquet-to-database record values were independently verified. See `RENDER_DEPLOYMENT_REPORT.md` for the deployment steps, evidence, and full results. Local Docker databases remain separate and can be used for testing without affecting the Render instance.