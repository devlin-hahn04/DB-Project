"""Read-only, value-by-value comparison of the 11 original Parquet files with PostgreSQL.

Run inside the project's existing ETL Docker image (pyarrow + psycopg already installed).
Uses PRIMARY KEY to match records, checks all columns, and compares PostGIS EWKB.
Does not change the database. Environment: DB_HOST, DB_PORT (optional),
DB_USER, DB_PASSWORD, DB_NAME, DB_SSLMODE (defaults to require), DATA_DIR.
"""

import math
import os
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

import pyarrow.parquet as pq
import psycopg
from psycopg import sql

TABLE_KEYS = {
    "vehicle_kind": "vehicle_kind_id",
    "fuel_type": "fuel_type_id",
    "vehicle_status": "vehicle_status_id",
    "vehicle_type": "vehicle_type_id",
    "parking_area": "parking_area_id",
    "driver": "driver_id",
    "road_segment": "road_id",
    "vehicle": "vehicle_id",
    "location_ping": "ping_id",
    "vehicle_assignment": "assignment_id",
    "trip": "trip_id",
}
GEOMETRY_COLUMNS = {"geom", "start_geom", "end_geom"}
MAX_EXAMPLES = 5


def as_ewkb_bytes(value):
    if value is None:
        return None
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value)
    raw = str(value).strip()
    if raw.startswith("\\x") or raw.startswith("0x"):
        raw = raw[2:]
    return bytes.fromhex(raw)


def value_matches(source, database, column):
    if column in GEOMETRY_COLUMNS:
        # Exact EWKB serialization (not just matching spatial bounding boxes).
        return as_ewkb_bytes(source) == as_ewkb_bytes(database)
    if source is None or database is None:
        return source is None and database is None
    if isinstance(source, float):
        if isinstance(database, float) and math.isnan(source) and math.isnan(database):
            return True
        return type(database) in (float, int) and source == database
    # Python datetime, int, str, bool compare natively with psycopg values.
    return type(source) is type(database) and source == database


def display(value, column):
    if column in GEOMETRY_COLUMNS and value is not None:
        b = as_ewkb_bytes(value)
        return f"EWKB({len(b)} bytes, prefix={b[:12].hex()})"
    return repr(value)[:110]


def verify_table(conn, root, table, key):
    path = root / f"{table}.parquet"
    if not path.is_file():
        raise ValueError(f"Missing official Parquet input: {path}")
    parquet = pq.read_table(path)
    columns = parquet.column_names
    if key not in columns:
        raise ValueError(f"{table}: primary key {key} is absent from Parquet")

    select_cols = [
        (sql.SQL("ST_AsEWKB({})").format(sql.Identifier(col))
         if col in GEOMETRY_COLUMNS else sql.Identifier(col))
        for col in columns
    ]
    query = sql.SQL("SELECT {} FROM {}.{} ORDER BY {}").format(
        sql.SQL(", ").join(select_cols),
        sql.Identifier("public"),
        sql.Identifier(table),
        sql.Identifier(key),
    )
    src_rows = parquet.to_pylist()
    source_by_key = {}
    repeated_source = 0
    for row in src_rows:
        pk = row[key]
        if pk in source_by_key:
            repeated_source += 1
        source_by_key[pk] = row

    # Compare column names against PostgreSQL so missing/extra columns are flagged.
    with conn.cursor() as cur:
        cur.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = %s
        """, (table,))
        database_cols = {r[0] for r in cur.fetchall()}
    missing_cols = set(columns) - database_cols
    extra_cols = database_cols - set(columns)
    if missing_cols or extra_cols:
        print(f"{table:20} FAIL: column mismatch; missing={sorted(missing_cols)}, extra={sorted(extra_cols)}")
        return False

    database_count = 0
    mismatch_counts = Counter()
    missing_keys = set(source_by_key)
    repeated_db = 0
    extra_keys = 0
    examples = []
    seen_db = set()
    # Server-side cursor streams rather than retrieving 28k+ rows all at once.
    with conn.cursor(name=f"verify_{table}") as cursor:
        cursor.execute(query)
        while True:
            batch = cursor.fetchmany(1000)
            if not batch:
                break
            for record in batch:
                database_count += 1
                dst = dict(zip(columns, record))
                pk = dst[key]
                if pk in seen_db:
                    repeated_db += 1
                seen_db.add(pk)
                if pk not in source_by_key:
                    extra_keys += 1
                    if len(examples) < MAX_EXAMPLES:
                        examples.append(f"Unexpected database PK={pk}")
                    continue
                missing_keys.discard(pk)
                src = source_by_key[pk]
                for col in columns:
                    if not value_matches(src[col], dst[col], col):
                        mismatch_counts[col] += 1
                        if len(examples) < MAX_EXAMPLES:
                            examples.append(
                                f"PK={pk}, column={col}: source={display(src[col], col)}, "
                                f"database={display(dst[col], col)}"
                            )

    errors = (sum(mismatch_counts.values()) + len(missing_keys) + extra_keys
              + repeated_source + repeated_db)
    passed = errors == 0 and len(src_rows) == database_count
    print(f"{table:20} {'PASS' if passed else 'FAIL'} "
          f"source={len(src_rows):6} database={database_count:6} discrepancies={errors}")
    if not passed:
        if missing_keys:
            print(f"    Missing database PKs (first 5): {list(sorted(missing_keys))[:5]}")
        if mismatch_counts:
            print(f"    Value mismatches by column: {dict(mismatch_counts)}")
        if repeated_source or repeated_db:
            print(f"    Duplicate source PKs: {repeated_source}; database PKs: {repeated_db}")
        for example in examples:
            print("    " + example)
    return passed


def main():
    required = ("DB_HOST", "DB_USER", "DB_PASSWORD", "DB_NAME")
    missing = [key for key in required if not os.getenv(key)]
    if missing:
        print(f"ERROR: Missing environment variables: {', '.join(missing)}", file=sys.stderr)
        return 2
    root = Path(os.environ.get("DATA_DIR", "/data"))
    if not root.is_dir():
        print(f"ERROR: Parquet directory not found: {root}", file=sys.stderr)
        return 2
    conninfo = {
        "host": os.environ["DB_HOST"],
        "port": os.environ.get("DB_PORT", "5432"),
        "user": os.environ["DB_USER"],
        "password": os.environ["DB_PASSWORD"],
        "dbname": os.environ["DB_NAME"],
        "sslmode": os.environ.get("DB_SSLMODE", "require"),
        "connect_timeout": 15,
    }
    try:
        with psycopg.connect(**conninfo) as conn:
            # Safety: default transaction is READ ONLY; no data modifications.
            with conn.cursor() as cursor:
                cursor.execute("SET TRANSACTION READ ONLY")
            print("Read-only source-to-database comparison (all 11 tables, all columns)")
            passed = 0
            for table, key in TABLE_KEYS.items():
                if verify_table(conn, root, table, key):
                    passed += 1
            print(f"\nOVERALL: {'PASS' if passed == len(TABLE_KEYS) else 'FAIL'} "
                  f"— {passed}/{len(TABLE_KEYS)} tables have identical per-key values")
            return 0 if passed == len(TABLE_KEYS) else 1
    except (psycopg.Error, ValueError, OSError) as exc:
        print(f"ERROR: Verification could not complete: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
