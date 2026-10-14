"""
Car Tracking Phase I ETL.

Reads the 11 official Parquet datasets and loads them into
PostgreSQL + PostGIS using parameterized INSERT statements.

EWKB geometry values are explicitly converted using
ST_GeomFromEWKB(decode(%s, 'hex')).

The entire load runs in one transaction. If any insertion
fails, the transaction is rolled back.
"""

import logging
import os
import sys
import time
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import psycopg
from psycopg import sql

log = logging.getLogger("etl")

REPO_ROOT = Path(__file__).resolve().parent.parent

# Target tables in foreign-key load order (parents before children).
# Columns are listed in sql/schema.sql order with their PostgreSQL types.
# Geometry values arrive as EWKB hexadecimal strings.
# They are explicitly converted using ST_GeomFromEWKB().
TABLES = [
    ("vehicle_kind", [
        ("name", "text"),
        ("vehicle_kind_id", "bigint"),
    ]),
    ("fuel_type", [
        ("name", "text"),
        ("fuel_type_id", "bigint"),
    ]),
    ("vehicle_status", [
        ("name", "text"),
        ("vehicle_status_id", "bigint"),
    ]),
    ("vehicle_type", [
        ("vehicle_kind_id", "bigint"),
        ("fuel_type_id", "bigint"),
        ("emissions_rating", "double precision"),
        ("created_at", "timestamp"),
        ("vehicle_type_id", "bigint"),
    ]),
    ("parking_area", [
        ("name", "text"),
        ("capacity", "bigint"),
        ("geom", "geometry"),
        ("created_at", "timestamp"),
        ("parking_area_id", "bigint"),
    ]),
    ("driver", [
        ("first_name", "text"),
        ("last_name", "text"),
        ("license_number", "text"),
        ("hired_at", "timestamp"),
        ("driver_id", "bigint"),
    ]),
    ("road_segment", [
        ("name", "text"),
        ("speed_limit_kph", "bigint"),
        ("geom", "geometry"),
        ("created_at", "timestamp"),
        ("is_oneway", "boolean"),
        ("direction", "text"),
        ("road_id", "bigint"),
    ]),
    ("vehicle", [
        ("vehicle_type_id", "bigint"),
        ("vehicle_status_id", "bigint"),
        ("plate_number", "text"),
        ("make", "text"),
        ("model", "text"),
        ("year", "bigint"),
        ("created_at", "timestamp"),
        ("vehicle_id", "bigint"),
    ]),
    ("location_ping", [
        ("vehicle_id", "bigint"),
        ("ts", "timestamp"),
        ("geom", "geometry"),
        ("speed_kph", "double precision"),
        ("heading_deg", "double precision"),
        ("ping_id", "bigint"),
    ]),
    ("vehicle_assignment", [
        ("vehicle_id", "bigint"),
        ("driver_id", "bigint"),
        ("assigned_from", "timestamp"),
        ("assigned_to", "timestamp"),
        ("assignment_id", "bigint"),
    ]),
    ("trip", [
        ("vehicle_id", "bigint"),
        ("start_ts", "timestamp"),
        ("end_ts", "timestamp"),
        ("start_geom", "geometry"),
        ("end_geom", "geometry"),
        ("distance_km", "double precision"),
        ("trip_id", "bigint"),
    ]),
]

# Arrow types accepted for each PostgreSQL column type.
ARROW_TYPE_CHECKS = {
    "text": pa.types.is_string,
    "geometry": pa.types.is_string,
    "bigint": pa.types.is_integer,
    "double precision": pa.types.is_floating,
    "boolean": pa.types.is_boolean,
    # TIMESTAMP (without time zone) only accepts naive timestamps
    "timestamp": lambda t: pa.types.is_timestamp(t) and t.tz is None,
}


class EtlError(Exception):
    """Error /."""


def get_config():
    missing = [v for v in ("DB_USER", "DB_PASSWORD", "DB_NAME") if not os.getenv(v)]
    if missing:
        raise EtlError(
            f"Missing environment variable(s): {', '.join(missing)}. "
            "Copy .env.example to .env and fill in the database credentials."
        )

    conninfo = {
        "host": os.getenv("DB_HOST", "localhost"),
        "port": os.getenv("DB_PORT", "5432"),
        "user": os.environ["DB_USER"],
        "password": os.environ["DB_PASSWORD"],
        "dbname": os.environ["DB_NAME"],
    }
    if os.getenv("DB_SSLMODE"):
        conninfo["sslmode"] = os.environ["DB_SSLMODE"]

    data_dir = Path(os.getenv("DATA_DIR") or REPO_ROOT / "data")
    return conninfo, data_dir


def read_parquet(data_dir, table_name, columns):
    # Read one dataset and check it matches the target table's columns
    path = data_dir / f"{table_name}.parquet"
    if not path.is_file():
        raise EtlError(f"Parquet file not found: {path}")

    try:
        table = pq.read_table(path)
    except Exception as exc:
        raise EtlError(f"Could not read {path}: {exc}") from exc

    # Checks if each Parquet file's collums match the ones in the Schema.
    expected = {name for name, _ in columns}
    actual = set(table.column_names)
    if expected != actual:
        problems = []
        if expected - actual:
            problems.append(f"missing {sorted(expected - actual)}")
        if actual - expected:
            problems.append(f"unexpected {sorted(actual - expected)}")
        raise EtlError(f"{path.name}: column mismatch ({'; '.join(problems)})")

    # Checks if each data type read from the Parquet file by Pyarrow matches the one in Postgres schema. 
    for name, pg_type in columns:
        arrow_type = table.schema.field(name).type
        if not ARROW_TYPE_CHECKS[pg_type](arrow_type):
            raise EtlError(
                f"{path.name}: column '{name}' has Parquet type {arrow_type}, "
                f"which cannot be loaded into a {pg_type} column"
            )

    return table


def column_values(table, name):
    column = table.column(name)
    if pa.types.is_timestamp(column.type) and column.type.unit == "ns":
        # PostgreSQL stores microseconds. A safe cast raises instead of
        # silently truncating if any value has sub-microsecond precision.
        try:
            column = column.cast(pa.timestamp("us"), safe=True)
        except pa.ArrowInvalid as exc:
            raise EtlError(
                f"Column '{name}' has sub-microsecond timestamps that "
                f"PostgreSQL cannot store exactly: {exc}"
            ) from exc
    return column.to_pylist()


def check_tables_exist(cur):
    missing = []
    for table_name, _ in TABLES:
        cur.execute("SELECT to_regclass(%s)", (f"public.{table_name}",))
        if cur.fetchone()[0] is None:
            missing.append(table_name)
    if missing:
        raise EtlError(
            f"Table(s) not found: {', '.join(missing)}. "
            "Create the schema first by running sql/schema.sql (see README)."
        )



def load_table(cur, table_name, columns, table):
    names = [name for name, _ in columns]

    # Read the Parquet values in the schema's column order.
    values = [column_values(table, name) for name in names]

    # Build SQL placeholders based on each column's type.
    placeholders = []

    for name, pg_type in columns:
        if pg_type == "geometry":
            # Explicitly convert EWKB hex into PostGIS geometry.
            placeholders.append(
                sql.SQL("ST_GeomFromEWKB(decode(%s, 'hex'))")
            )
        else:
            # Regular PostgreSQL parameter.
            placeholders.append(sql.SQL("%s"))

    # Construct a parameterized INSERT statement.
    insert_stmt = sql.SQL(
        "INSERT INTO {} ({}) VALUES ({})"
    ).format(
        sql.Identifier(table_name),
        sql.SQL(", ").join(map(sql.Identifier, names)),
        sql.SQL(", ").join(placeholders),
    )

    # Insert each row using the correct parameter values.
    for row in zip(*values):
        cur.execute(insert_stmt, row)



def verify_counts(cur, expected_counts):
    for table_name, expected in expected_counts.items():
        cur.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table_name)))
        loaded = cur.fetchone()[0]
        if loaded != expected:
            raise EtlError(
                f"{table_name}: loaded {loaded} rows but the Parquet file has {expected}"
            )


def run():
    conninfo, data_dir = get_config()
    log.info("Reading Parquet files from %s", data_dir)

    # Read and validate every file before touching the database.
    datasets = {}
    for table_name, columns in TABLES:
        datasets[table_name] = read_parquet(data_dir, table_name, columns)
        log.info("Read %-20s %7d rows", table_name, datasets[table_name].num_rows)

    log.info(
        "Connecting to %s@%s:%s/%s",
        conninfo["user"], conninfo["host"], conninfo["port"], conninfo["dbname"],
    )
    try:
        conn = psycopg.connect(**conninfo, connect_timeout=15)
    except psycopg.OperationalError as exc:
        raise EtlError(f"Could not connect to the database: {exc}") from exc

    # Commits on success, rolls back on any exception, then closes.
    with conn:
        with conn.cursor() as cur:
            check_tables_exist(cur)

            table_list = sql.SQL(", ").join(sql.Identifier(t) for t, _ in TABLES)
            cur.execute(sql.SQL("TRUNCATE {}").format(table_list))
            log.info("Truncated %d tables", len(TABLES))

            for table_name, columns in TABLES:
                start = time.perf_counter()
                try:
                    load_table(cur, table_name, columns, datasets[table_name])
                except psycopg.Error as exc:
                    raise EtlError(f"Failed loading {table_name}: {exc}") from exc
                log.info(
                    "Loaded %-20s %7d rows in %.2fs",
                    table_name, datasets[table_name].num_rows, time.perf_counter() - start,
                )

            verify_counts(cur, {t: d.num_rows for t, d in datasets.items()})
            log.info("Row counts verified for all %d tables", len(TABLES))

    log.info("ETL finished successfully")


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    try:
        run()
    except EtlError as exc:
        log.error("%s", exc)
        log.error("ETL aborted; no changes were committed")
        return 1
    except Exception:
        log.exception("Unexpected error; no changes were committed")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
