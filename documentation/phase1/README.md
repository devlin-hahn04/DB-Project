
# Phase 1 — Database Setup, ETL, and Deployment

[← Back to Project Overview](../README.md)

## Overview

Phase 1 focused on establishing a PostgreSQL/PostGIS database, importing the 11 provided Parquet datasets through a reproducible Python ETL pipeline, verifying the database structure and imported records, and deploying the database to Render for remote access and grading.

The implementation includes:

- 11 relational tables
- 8 foreign-key relationships
- 5 PostGIS geometry columns using SRID 4326 (WGS84)
- 5 GiST spatial indexes
- 32,752 imported records

**Technologies:** PostgreSQL 17, PostGIS, Python, Docker, Docker Compose, Render, and JetBrains DataGrip.

## Project Structure

```
DB-Project/
├── documentation/
│   └── phase1/
│       └── README.md           # Phase 1 documentation
├── ETL/
│   ├── Dockerfile
│   └── main.py                  # Python ETL pipeline
├── sql/
│   └── schema.sql               # PostgreSQL/PostGIS database schema
├── docker-compose.yml           # Docker services configuration
├── .env.example                 # Example environment variables
├── requirements.txt             # Python dependencies
└── README.md                    # Main project overview
```

## 1. Local Database Setup with Docker

### Step 1 — Clone the Repository

```powershell
git clone https://github.com/devlin-hahn04/DB-Project.git
cd DB-Project
```

### Step 2 — Configure Environment Variables

Create a `.env` file from the provided example:

```powershell
Copy-Item .env.example .env
```

Configure your local PostgreSQL credentials:

```dotenv
DB_USER=naturaljoiners
DB_PASSWORD=your_local_password
DB_NAME=cartracking
```

Place the 11 official `.parquet` files inside the `data/` directory.

### Step 3 — Start PostgreSQL

Make sure Docker Desktop is running, then execute:

```powershell
docker compose up -d postgres
```

Verify that the container is running:

```powershell
docker compose ps
```

This starts a PostgreSQL 17 database with PostGIS support.

### Step 4 — Initialize the Database Schema

The database schema is defined in `sql/schema.sql`, which creates the relational tables, primary and foreign keys, PostGIS geometry columns, and spatial indexes.

Execute the following command from the project root:

```powershell
Get-Content .\sql\schema.sql -Raw |
  docker exec -i car-tracking-db psql `
    -X -v ON_ERROR_STOP=1 -1 `
    -U naturaljoiners -d cartracking
```

This command should only be executed when initializing a fresh database.

## 2. ETL Pipeline

The ETL pipeline, implemented in `ETL/main.py`, imports the 11 Parquet datasets into PostgreSQL.

The pipeline uses:

- `pyarrow` to read Parquet files.
- `psycopg` to communicate with PostgreSQL.
- Parameterized SQL `INSERT` statements to load records.
- PostGIS functions to convert and preserve spatial geometries.

The ETL verifies dataset structure, inserts records in foreign-key order, and checks that imported row counts match the original files.

All operations are performed within a database transaction to prevent incomplete imports.

### Run the ETL

Build the ETL Docker image:

```powershell
docker compose build etl
```

Run the pipeline:

```powershell
docker compose run --rm etl
```

Expected output:

```text
Row counts verified for all 11 tables
ETL finished successfully
```

The ETL successfully imported **32,752 records across all 11 tables**, without filtering or modifying the original data.

**Note:** Running the ETL again truncates and reloads the 11 application tables.

## 3. Database Inspection and Validation Using DataGrip

JetBrains DataGrip was used to connect to both the local Docker PostgreSQL database and the Render-hosted database. Its graphical interface allowed us to inspect database schemas, examine table relationships, browse imported records, and execute SQL queries to verify database structure and data accessibility..

### Local Docker Database

DataGrip was connected to the PostgreSQL container using the following configuration:

| Setting | Value |
|---|---|
| Host | `localhost` |
| Port | `5432` |
| Database | `cartracking` |
| Username | `naturaljoiners` |
| Password | Local `.env` password |

Through DataGrip, the database tables and their contents were inspected to verify the database structure and successful ETL import.

### Render Database

A second DataGrip connection was configured for the remotely hosted PostgreSQL database.

| Setting | Value |
|---|---|
| Host | `dpg-db87op4s728c738ghs30-a.virginia-postgres.render.com` |
| Port | `5432` |
| Database | `cartracking_nchv` |
| Username | `cartrackingdb_2rg8_user` |
| Password | `dvAXpDOZkDMOwD7o1K4NRY54C43jNWrP` |

The Render connection was successfully established, allowing the hosted database to be inspected through the same interface.

### Validation Summary

Both database environments were accessible through DataGrip, enabling inspection of:

- The 11 application tables and their columns.
- Primary-key and foreign-key relationships.
- Imported records and table contents.
- PostGIS spatial columns and geometry types.
- SQL query results and database connectivity.

The local and hosted databases contain the imported project datasets, with **32,752 records across 11 tables**.

## 4. Render Deployment

The project database was deployed to Render to provide a remotely accessible PostgreSQL/PostGIS instance for grading.

The Render deployment uses PostgreSQL 17 with PostGIS enabled and contains the same database schema and imported datasets as the local environment.

### Deployment Overview

| Configuration | Value |
|---|---|
| Hosting provider | Render |
| Service | Managed PostgreSQL |
| Region | Virginia (US East) |
| PostgreSQL version | 17 |
| PostGIS | Enabled |
| Application tables | 11 |
| Imported records | 32,752 |
| Spatial reference | SRID 4326 (WGS84) |

The database schema was initialized on Render using `sql/schema.sql`, and the Python ETL pipeline was configured to connect to the hosted PostgreSQL instance and load the original Parquet datasets.

The deployed database was successfully accessed through DataGrip, confirming that it is available for remote inspection and SQL queries.

## 5. Useful Docker Commands

| Command | Description |
|---|---|
| `docker compose up -d postgres` | Start the PostgreSQL container |
| `docker compose ps` | Check container status |
| `docker compose build etl` | Build the ETL Docker image |
| `docker compose run --rm etl` | Execute the ETL pipeline |
| `docker compose logs postgres` | View PostgreSQL logs |
| `docker compose down` | Stop containers while preserving database data |

**Important:** Avoid using `docker compose down -v` unless you intentionally want to delete the database volume and its stored records.

