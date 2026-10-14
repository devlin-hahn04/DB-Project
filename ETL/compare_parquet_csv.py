"""Compare official Parquet source files against PostgreSQL CSV exports.
Run in the project's ETL Docker image (pyarrow required)."""
import csv
import math
from collections import Counter
from datetime import date, datetime
from pathlib import Path
import pyarrow.parquet as pq

SOURCE = Path('/data')
EXPORTS = Path('/exports')
TABLES = {
    'driver': 'driver_id', 'fuel_type': 'fuel_type_id',
    'location_ping': 'ping_id', 'parking_area': 'parking_area_id',
    'road_segment': 'road_id', 'trip': 'trip_id',
    'vehicle': 'vehicle_id', 'vehicle_assignment': 'assignment_id',
    'vehicle_kind': 'vehicle_kind_id', 'vehicle_status': 'vehicle_status_id',
    'vehicle_type': 'vehicle_type_id',
}
GEOM_COLS = {'geom', 'start_geom', 'end_geom'}

def equal_value(src, dst, col):
    if src is None:
        return dst == ''
    if col in GEOM_COLS:
        if isinstance(src, bytes):
            src = src.hex()
        a = str(src).removeprefix('\\x').upper()
        b = dst.removeprefix('\\x').upper()
        return a == b
    if isinstance(src, bool):
        return dst.lower() in (('t', 'true', '1') if src else ('f', 'false', '0'))
    if isinstance(src, int):
        try:
            return int(dst) == src
        except ValueError:
            return False
    if isinstance(src, float):
        try:
            val = float(dst)
            return (math.isnan(src) and math.isnan(val)) or src == val
        except ValueError:
            return False
    if isinstance(src, (datetime, date)):
        try:
            return src == datetime.fromisoformat(dst) if isinstance(src, datetime) else src == date.fromisoformat(dst)
        except ValueError:
            return False
    return str(src) == dst

def main():
    grand_errors = 0
    for table, key in TABLES.items():
        src_path = SOURCE / f'{table}.parquet'
        csv_path = EXPORTS / f'{table}.csv'
        if not src_path.exists() or not csv_path.exists():
            print(f'{table:20} MISSING FILE: {src_path if not src_path.exists() else csv_path}')
            grand_errors += 1
            continue
        parquet = pq.read_table(src_path)
        columns = parquet.column_names
        source_rows = parquet.to_pylist()
        source_by_id = {str(row[key]): row for row in source_rows}
        with csv_path.open('r', encoding='utf-8-sig', newline='') as f:
            reader = csv.DictReader(f)
            export_columns = reader.fieldnames or []
            csv_rows = list(reader)
        if set(columns) != set(export_columns):
            print(f'{table:20} COLUMN MISMATCH: parquet={columns} csv={export_columns}')
            grand_errors += 1
            continue
        csv_by_id = {row[key]: row for row in csv_rows}
        missing = set(source_by_id) - set(csv_by_id)
        extra = set(csv_by_id) - set(source_by_id)
        errors = len(missing) + len(extra)
        mismatches = Counter()
        examples = []
        for pk in set(source_by_id) & set(csv_by_id):
            s, d = source_by_id[pk], csv_by_id[pk]
            for col in columns:
                if not equal_value(s[col], d[col], col):
                    errors += 1
                    mismatches[col] += 1
                    if len(examples) < 4:
                        examples.append((pk, col, repr(s[col])[:100], repr(d[col])[:100]))
        source_nulls = {col: sum(row[col] is None for row in source_rows) for col in columns}
        status = 'PASS' if errors == 0 and len(source_rows) == len(csv_rows) else 'FAIL'
        print(f'{table:20} {status:4} parquet={len(source_rows):6} csv={len(csv_rows):6} differences={errors}')
        if table in ('location_ping', 'vehicle_assignment'):
            for col in ('heading_deg', 'assigned_to'):
                if col in columns:
                    print(f'    {col}: source NULL={source_nulls[col]}, CSV blank={sum(r[col] == "" for r in csv_rows)}')
        if missing or extra:
            print(f'    Missing IDs: {list(sorted(missing))[:5]}; extra IDs: {list(sorted(extra))[:5]}')
        if mismatches:
            print(f'    Mismatched columns: {dict(mismatches)}')
            for example in examples:
                print(f'    Example ID={example[0]} column={example[1]} parquet={example[2]} csv={example[3]}')
        grand_errors += errors
    print(f'\nOVERALL: {"PASS" if grand_errors == 0 else "FAIL"} — {grand_errors} differences')

if __name__ == '__main__':
    main()
