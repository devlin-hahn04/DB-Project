# Car Tracking Database Project

A PostgreSQL 17 database project using PostGIS for geospatial data storage and Python for ETL processing.

## Project Structure

```text
DB-Project/
├── data/                 # Parquet datasets (not tracked by Git)
├── ETL/
│   └── main.py           # Python ETL pipeline
├── sql/
│   └── schema.sql        # PostgreSQL relational database schema
├── .env.example          # Example environment variables
├── .gitignore
├── docker-compose.yml
├── requirements.txt
└── README.md
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

On Windows PowerShell:

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

```text
CREATE EXTENSION
NOTICE:  extension "postgis" already exists, skipping
CREATE TABLE
CREATE TABLE
CREATE TABLE
CREATE TABLE
CREATE TABLE
CREATE TABLE
CREATE TABLE
CREATE TABLE
CREATE TABLE
CREATE TABLE
CREATE TABLE
```

The output should contain **11 `CREATE TABLE` messages**.

The PostGIS notice is normal if the extension is already installed.

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

All spatial columns use **SRID 4326 (WGS 84)**.

The geometry types are:

- `POINT` — Represents a geographic location, such as a vehicle GPS position.
- `LINESTRING` — Represents a connected sequence of points, such as a road segment.
- `POLYGON` — Represents a geographic area, such as a parking area.

### 10. Exit PostgreSQL

To exit the PostgreSQL terminal:

```sql
\q
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
- The schema is compatible with PostgreSQL 17 and PostGIS.
- The `sql/schema.sql` file is version-controlled so each developer can initialize the same database structure locally.
- Database contents and Docker volumes are not shared through GitHub. Each developer maintains their own local database.
