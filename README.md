
# Car Tracking Database Project

A PostgreSQL 17 database project using PostGIS for geospatial data storage and Python for ETL processing.

## Project Structure

```text
DB-Project/
├── data/                 # Parquet datasets (not tracked by Git)
├── ETL/
│   └── main.py           # Python ETL pipeline
├── sql/
│   └── schema.sql        # Database schema
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

### 1. Clone the repository

```bash
git clone https://github.com/devlin-hahn04/DB-Project.git
cd DB-Project
```

### 2. Configure environment variables

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

### 4. Connect to the database

```powershell
docker exec -it car-tracking-db psql -U your_username -d cartracking
```

Replace `your_username` with the value of `DB_USER` in your `.env` file.

### 5. Verify PostgreSQL and PostGIS

Inside the PostgreSQL terminal:

```sql
SELECT current_database(), current_user;
SELECT PostGIS_Version();
```

To exit:

```sql
\q
```

## Useful Docker Commands

| Command | Description |
|---|---|
| `docker compose up -d` | Start the database |
| `docker compose down` | Stop and remove the container while retaining database data |
| `docker compose ps` | Check container status |
| `docker compose logs postgres` | View PostgreSQL logs |

**Important:** Do not use `docker compose down -v` unless you intentionally want to delete the database volume and its stored data.

