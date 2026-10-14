-- Phase 1 Data Validation
--
-- Read-only checks that the database matches the table diagram and the
-- official Parquet datasets. Nothing in the project tables is modified;
-- results are collected in a session-only TEMP table.
--
-- Status values:
--   PASS / FAIL  graded requirement (schema, row counts, keys, nulls, SRID)
--   INFO         reported only; the data is never fixed or filtered

\set QUIET on
\pset pager off
\pset footer off

CREATE TEMP TABLE validation_result (
  id SERIAL,
  section TEXT,
  check_name TEXT,
  status TEXT,
  detail TEXT
);

-- Expected schema (from the table diagram)
CREATE TEMP TABLE expected_column (table_name TEXT, column_name TEXT, data_type TEXT);
INSERT INTO expected_column VALUES
  ('vehicle_kind', 'name', 'text'),
  ('vehicle_kind', 'vehicle_kind_id', 'bigint'),
  ('fuel_type', 'name', 'text'),
  ('fuel_type', 'fuel_type_id', 'bigint'),
  ('vehicle_status', 'name', 'text'),
  ('vehicle_status', 'vehicle_status_id', 'bigint'),
  ('vehicle_type', 'vehicle_kind_id', 'bigint'),
  ('vehicle_type', 'fuel_type_id', 'bigint'),
  ('vehicle_type', 'emissions_rating', 'double precision'),
  ('vehicle_type', 'created_at', 'timestamp without time zone'),
  ('vehicle_type', 'vehicle_type_id', 'bigint'),
  ('parking_area', 'name', 'text'),
  ('parking_area', 'capacity', 'bigint'),
  ('parking_area', 'geom', 'geometry(Polygon,4326)'),
  ('parking_area', 'created_at', 'timestamp without time zone'),
  ('parking_area', 'parking_area_id', 'bigint'),
  ('driver', 'first_name', 'text'),
  ('driver', 'last_name', 'text'),
  ('driver', 'license_number', 'text'),
  ('driver', 'hired_at', 'timestamp without time zone'),
  ('driver', 'driver_id', 'bigint'),
  ('road_segment', 'name', 'text'),
  ('road_segment', 'speed_limit_kph', 'bigint'),
  ('road_segment', 'geom', 'geometry(LineString,4326)'),
  ('road_segment', 'created_at', 'timestamp without time zone'),
  ('road_segment', 'is_oneway', 'boolean'),
  ('road_segment', 'direction', 'text'),
  ('road_segment', 'road_id', 'bigint'),
  ('vehicle', 'vehicle_type_id', 'bigint'),
  ('vehicle', 'vehicle_status_id', 'bigint'),
  ('vehicle', 'plate_number', 'text'),
  ('vehicle', 'make', 'text'),
  ('vehicle', 'model', 'text'),
  ('vehicle', 'year', 'bigint'),
  ('vehicle', 'created_at', 'timestamp without time zone'),
  ('vehicle', 'vehicle_id', 'bigint'),
  ('location_ping', 'vehicle_id', 'bigint'),
  ('location_ping', 'ts', 'timestamp without time zone'),
  ('location_ping', 'geom', 'geometry(Point,4326)'),
  ('location_ping', 'speed_kph', 'double precision'),
  ('location_ping', 'heading_deg', 'double precision'),
  ('location_ping', 'ping_id', 'bigint'),
  ('vehicle_assignment', 'vehicle_id', 'bigint'),
  ('vehicle_assignment', 'driver_id', 'bigint'),
  ('vehicle_assignment', 'assigned_from', 'timestamp without time zone'),
  ('vehicle_assignment', 'assigned_to', 'timestamp without time zone'),
  ('vehicle_assignment', 'assignment_id', 'bigint'),
  ('trip', 'vehicle_id', 'bigint'),
  ('trip', 'start_ts', 'timestamp without time zone'),
  ('trip', 'end_ts', 'timestamp without time zone'),
  ('trip', 'start_geom', 'geometry(Point,4326)'),
  ('trip', 'end_geom', 'geometry(Point,4326)'),
  ('trip', 'distance_km', 'double precision'),
  ('trip', 'trip_id', 'bigint');

-- Row counts in the official Parquet files
CREATE TEMP TABLE expected_count (table_name TEXT, row_count BIGINT);
INSERT INTO expected_count VALUES
  ('vehicle_kind', 5),
  ('fuel_type', 2),
  ('vehicle_status', 2),
  ('vehicle_type', 8),
  ('parking_area', 224),
  ('driver', 12),
  ('road_segment', 4086),
  ('vehicle', 30),
  ('location_ping', 28041),
  ('vehicle_assignment', 42),
  ('trip', 300);

-- Nullable values present in the Parquet files; every other column has none
CREATE TEMP TABLE expected_null (table_name TEXT, column_name TEXT, null_count BIGINT);
INSERT INTO expected_null VALUES
  ('location_ping', 'heading_deg', 300),
  ('vehicle_assignment', 'assigned_to', 30);

-- 1. Schema: table names, column names and data types
WITH actual AS (
  SELECT c.relname AS table_name, a.attname AS column_name,
         format_type(a.atttypid, a.atttypmod) AS data_type
  FROM pg_attribute a
  JOIN pg_class c ON c.oid = a.attrelid
  WHERE c.relnamespace = 'public'::regnamespace
    AND c.relkind = 'r'
    AND c.relname IN (SELECT DISTINCT table_name FROM expected_column)
    AND a.attnum > 0
    AND NOT a.attisdropped
)
INSERT INTO validation_result (section, check_name, status, detail)
SELECT '1. Schema',
       coalesce(e.table_name, a.table_name) || '.' || coalesce(e.column_name, a.column_name),
       CASE WHEN e.data_type = a.data_type THEN 'PASS' ELSE 'FAIL' END,
       CASE
         WHEN a.column_name IS NULL THEN 'missing column (expected ' || e.data_type || ')'
         WHEN e.column_name IS NULL THEN 'unexpected column (' || a.data_type || ')'
         ELSE a.data_type ||
              CASE WHEN e.data_type <> a.data_type THEN ', expected ' || e.data_type ELSE '' END
       END
FROM expected_column e
FULL JOIN actual a
  ON a.table_name = e.table_name AND a.column_name = e.column_name;

-- 2. Row counts
INSERT INTO validation_result (section, check_name, status, detail)
SELECT '2. Row counts', e.table_name,
       CASE WHEN a.n = e.row_count THEN 'PASS' ELSE 'FAIL' END,
       a.n || ' rows (expected ' || e.row_count || ')'
FROM expected_count e
JOIN (
  SELECT 'vehicle_kind' AS table_name, count(*) AS n FROM vehicle_kind
  UNION ALL SELECT 'fuel_type', count(*) FROM fuel_type
  UNION ALL SELECT 'vehicle_status', count(*) FROM vehicle_status
  UNION ALL SELECT 'vehicle_type', count(*) FROM vehicle_type
  UNION ALL SELECT 'parking_area', count(*) FROM parking_area
  UNION ALL SELECT 'driver', count(*) FROM driver
  UNION ALL SELECT 'road_segment', count(*) FROM road_segment
  UNION ALL SELECT 'vehicle', count(*) FROM vehicle
  UNION ALL SELECT 'location_ping', count(*) FROM location_ping
  UNION ALL SELECT 'vehicle_assignment', count(*) FROM vehicle_assignment
  UNION ALL SELECT 'trip', count(*) FROM trip
) a USING (table_name);

-- 3. Primary keys: one PK per table, on the expected column, no duplicates or NULLs
WITH expected_pk (table_name, column_name) AS (
  VALUES ('vehicle_kind', 'vehicle_kind_id'), ('fuel_type', 'fuel_type_id'),
         ('vehicle_status', 'vehicle_status_id'), ('vehicle_type', 'vehicle_type_id'),
         ('parking_area', 'parking_area_id'), ('driver', 'driver_id'),
         ('road_segment', 'road_id'), ('vehicle', 'vehicle_id'),
         ('location_ping', 'ping_id'), ('vehicle_assignment', 'assignment_id'),
         ('trip', 'trip_id')
),
actual_pk AS (
  SELECT con.conrelid::regclass::text AS table_name,
         string_agg(a.attname, ', ') AS column_name
  FROM pg_constraint con
  JOIN pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = ANY (con.conkey)
  WHERE con.contype = 'p' AND con.connamespace = 'public'::regnamespace
  GROUP BY con.conrelid
)
INSERT INTO validation_result (section, check_name, status, detail)
SELECT '3. Primary keys', e.table_name || ' PK',
       CASE WHEN a.column_name = e.column_name THEN 'PASS' ELSE 'FAIL' END,
       coalesce('PRIMARY KEY (' || a.column_name || ')', 'no primary key') ||
       CASE WHEN a.column_name IS DISTINCT FROM e.column_name
            THEN ', expected (' || e.column_name || ')' ELSE '' END
FROM expected_pk e
LEFT JOIN actual_pk a USING (table_name);

INSERT INTO validation_result (section, check_name, status, detail)
SELECT '3. Primary keys', table_name || ' duplicate/NULL ids',
       CASE WHEN dupes = 0 AND nulls = 0 THEN 'PASS' ELSE 'FAIL' END,
       dupes || ' duplicate, ' || nulls || ' NULL'
FROM (
  SELECT 'vehicle_kind' AS table_name, count(*) - count(DISTINCT vehicle_kind_id) - count(*) FILTER (WHERE vehicle_kind_id IS NULL) AS dupes, count(*) FILTER (WHERE vehicle_kind_id IS NULL) AS nulls FROM vehicle_kind
  UNION ALL SELECT 'fuel_type', count(*) - count(DISTINCT fuel_type_id) - count(*) FILTER (WHERE fuel_type_id IS NULL), count(*) FILTER (WHERE fuel_type_id IS NULL) FROM fuel_type
  UNION ALL SELECT 'vehicle_status', count(*) - count(DISTINCT vehicle_status_id) - count(*) FILTER (WHERE vehicle_status_id IS NULL), count(*) FILTER (WHERE vehicle_status_id IS NULL) FROM vehicle_status
  UNION ALL SELECT 'vehicle_type', count(*) - count(DISTINCT vehicle_type_id) - count(*) FILTER (WHERE vehicle_type_id IS NULL), count(*) FILTER (WHERE vehicle_type_id IS NULL) FROM vehicle_type
  UNION ALL SELECT 'parking_area', count(*) - count(DISTINCT parking_area_id) - count(*) FILTER (WHERE parking_area_id IS NULL), count(*) FILTER (WHERE parking_area_id IS NULL) FROM parking_area
  UNION ALL SELECT 'driver', count(*) - count(DISTINCT driver_id) - count(*) FILTER (WHERE driver_id IS NULL), count(*) FILTER (WHERE driver_id IS NULL) FROM driver
  UNION ALL SELECT 'road_segment', count(*) - count(DISTINCT road_id) - count(*) FILTER (WHERE road_id IS NULL), count(*) FILTER (WHERE road_id IS NULL) FROM road_segment
  UNION ALL SELECT 'vehicle', count(*) - count(DISTINCT vehicle_id) - count(*) FILTER (WHERE vehicle_id IS NULL), count(*) FILTER (WHERE vehicle_id IS NULL) FROM vehicle
  UNION ALL SELECT 'location_ping', count(*) - count(DISTINCT ping_id) - count(*) FILTER (WHERE ping_id IS NULL), count(*) FILTER (WHERE ping_id IS NULL) FROM location_ping
  UNION ALL SELECT 'vehicle_assignment', count(*) - count(DISTINCT assignment_id) - count(*) FILTER (WHERE assignment_id IS NULL), count(*) FILTER (WHERE assignment_id IS NULL) FROM vehicle_assignment
  UNION ALL SELECT 'trip', count(*) - count(DISTINCT trip_id) - count(*) FILTER (WHERE trip_id IS NULL), count(*) FILTER (WHERE trip_id IS NULL) FROM trip
) t;

-- 4. Foreign keys: the 8 constraints exist and no child row points to a missing parent
WITH expected_fk (table_name, column_name, ref_table, ref_column) AS (
  VALUES ('vehicle_type', 'vehicle_kind_id', 'vehicle_kind', 'vehicle_kind_id'),
         ('vehicle_type', 'fuel_type_id', 'fuel_type', 'fuel_type_id'),
         ('vehicle', 'vehicle_type_id', 'vehicle_type', 'vehicle_type_id'),
         ('vehicle', 'vehicle_status_id', 'vehicle_status', 'vehicle_status_id'),
         ('location_ping', 'vehicle_id', 'vehicle', 'vehicle_id'),
         ('vehicle_assignment', 'vehicle_id', 'vehicle', 'vehicle_id'),
         ('vehicle_assignment', 'driver_id', 'driver', 'driver_id'),
         ('trip', 'vehicle_id', 'vehicle', 'vehicle_id')
),
actual_fk AS (
  SELECT con.conrelid::regclass::text AS table_name, a.attname AS column_name,
         con.confrelid::regclass::text AS ref_table, ra.attname AS ref_column
  FROM pg_constraint con
  JOIN pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = con.conkey[1]
  JOIN pg_attribute ra ON ra.attrelid = con.confrelid AND ra.attnum = con.confkey[1]
  WHERE con.contype = 'f' AND con.connamespace = 'public'::regnamespace
)
INSERT INTO validation_result (section, check_name, status, detail)
SELECT '4. Foreign keys',
       e.table_name || '.' || e.column_name || ' -> ' || e.ref_table,
       CASE WHEN a.table_name IS NOT NULL THEN 'PASS' ELSE 'FAIL' END,
       CASE WHEN a.table_name IS NOT NULL THEN 'constraint exists' ELSE 'constraint missing' END
FROM expected_fk e
LEFT JOIN actual_fk a USING (table_name, column_name, ref_table, ref_column);

INSERT INTO validation_result (section, check_name, status, detail)
SELECT '4. Foreign keys', check_name || ' orphans',
       CASE WHEN n = 0 THEN 'PASS' ELSE 'FAIL' END,
       n || ' orphan rows'
FROM (
  SELECT 'vehicle_type.vehicle_kind_id' AS check_name, count(*) AS n FROM vehicle_type c LEFT JOIN vehicle_kind p USING (vehicle_kind_id) WHERE c.vehicle_kind_id IS NOT NULL AND p.vehicle_kind_id IS NULL
  UNION ALL SELECT 'vehicle_type.fuel_type_id', count(*) FROM vehicle_type c LEFT JOIN fuel_type p USING (fuel_type_id) WHERE c.fuel_type_id IS NOT NULL AND p.fuel_type_id IS NULL
  UNION ALL SELECT 'vehicle.vehicle_type_id', count(*) FROM vehicle c LEFT JOIN vehicle_type p USING (vehicle_type_id) WHERE c.vehicle_type_id IS NOT NULL AND p.vehicle_type_id IS NULL
  UNION ALL SELECT 'vehicle.vehicle_status_id', count(*) FROM vehicle c LEFT JOIN vehicle_status p USING (vehicle_status_id) WHERE c.vehicle_status_id IS NOT NULL AND p.vehicle_status_id IS NULL
  UNION ALL SELECT 'location_ping.vehicle_id', count(*) FROM location_ping c LEFT JOIN vehicle p USING (vehicle_id) WHERE c.vehicle_id IS NOT NULL AND p.vehicle_id IS NULL
  UNION ALL SELECT 'vehicle_assignment.vehicle_id', count(*) FROM vehicle_assignment c LEFT JOIN vehicle p USING (vehicle_id) WHERE c.vehicle_id IS NOT NULL AND p.vehicle_id IS NULL
  UNION ALL SELECT 'vehicle_assignment.driver_id', count(*) FROM vehicle_assignment c LEFT JOIN driver p USING (driver_id) WHERE c.driver_id IS NOT NULL AND p.driver_id IS NULL
  UNION ALL SELECT 'trip.vehicle_id', count(*) FROM trip c LEFT JOIN vehicle p USING (vehicle_id) WHERE c.vehicle_id IS NOT NULL AND p.vehicle_id IS NULL
) t;

-- 5. NULL handling: per-column NULL counts match the source data
WITH actual AS (
  SELECT 'vehicle_kind' AS table_name, j.key AS column_name, count(*) FILTER (WHERE j.value = 'null') AS n FROM vehicle_kind t, jsonb_each(to_jsonb(t)) j GROUP BY j.key
  UNION ALL SELECT 'fuel_type', j.key, count(*) FILTER (WHERE j.value = 'null') FROM fuel_type t, jsonb_each(to_jsonb(t)) j GROUP BY j.key
  UNION ALL SELECT 'vehicle_status', j.key, count(*) FILTER (WHERE j.value = 'null') FROM vehicle_status t, jsonb_each(to_jsonb(t)) j GROUP BY j.key
  UNION ALL SELECT 'vehicle_type', j.key, count(*) FILTER (WHERE j.value = 'null') FROM vehicle_type t, jsonb_each(to_jsonb(t)) j GROUP BY j.key
  UNION ALL SELECT 'parking_area', j.key, count(*) FILTER (WHERE j.value = 'null') FROM parking_area t, jsonb_each(to_jsonb(t)) j GROUP BY j.key
  UNION ALL SELECT 'driver', j.key, count(*) FILTER (WHERE j.value = 'null') FROM driver t, jsonb_each(to_jsonb(t)) j GROUP BY j.key
  UNION ALL SELECT 'road_segment', j.key, count(*) FILTER (WHERE j.value = 'null') FROM road_segment t, jsonb_each(to_jsonb(t)) j GROUP BY j.key
  UNION ALL SELECT 'vehicle', j.key, count(*) FILTER (WHERE j.value = 'null') FROM vehicle t, jsonb_each(to_jsonb(t)) j GROUP BY j.key
  UNION ALL SELECT 'location_ping', j.key, count(*) FILTER (WHERE j.value = 'null') FROM location_ping t, jsonb_each(to_jsonb(t)) j GROUP BY j.key
  UNION ALL SELECT 'vehicle_assignment', j.key, count(*) FILTER (WHERE j.value = 'null') FROM vehicle_assignment t, jsonb_each(to_jsonb(t)) j GROUP BY j.key
  UNION ALL SELECT 'trip', j.key, count(*) FILTER (WHERE j.value = 'null') FROM trip t, jsonb_each(to_jsonb(t)) j GROUP BY j.key
)
INSERT INTO validation_result (section, check_name, status, detail)
SELECT '5. NULLs', a.table_name || '.' || a.column_name,
       CASE WHEN a.n = coalesce(e.null_count, 0) THEN 'PASS' ELSE 'FAIL' END,
       a.n || ' NULL (expected ' || coalesce(e.null_count, 0) || ')'
FROM actual a
LEFT JOIN expected_null e USING (table_name, column_name);

-- 6. PostGIS: geometry_columns registration, SRID and geometry type of every value
WITH expected_geom (table_name, column_name, geom_type) AS (
  VALUES ('parking_area', 'geom', 'POLYGON'),
         ('road_segment', 'geom', 'LINESTRING'),
         ('location_ping', 'geom', 'POINT'),
         ('trip', 'start_geom', 'POINT'),
         ('trip', 'end_geom', 'POINT')
)
INSERT INTO validation_result (section, check_name, status, detail)
SELECT '6. PostGIS', e.table_name || '.' || e.column_name || ' geometry_columns',
       CASE WHEN g.type = e.geom_type AND g.srid = 4326 THEN 'PASS' ELSE 'FAIL' END,
       coalesce(g.type || ', SRID ' || g.srid, 'not registered')
FROM expected_geom e
LEFT JOIN geometry_columns g
  ON g.f_table_schema = 'public' AND g.f_table_name = e.table_name AND g.f_geometry_column = e.column_name;

INSERT INTO validation_result (section, check_name, status, detail)
SELECT '6. PostGIS', check_name || ' SRID/type',
       CASE WHEN bad = 0 THEN 'PASS' ELSE 'FAIL' END,
       bad || ' of ' || total || ' values not ' || expected || ' with SRID 4326'
FROM (
  SELECT 'parking_area.geom' AS check_name, 'POLYGON' AS expected, count(*) AS total, count(*) FILTER (WHERE geom IS NOT NULL AND (ST_SRID(geom) <> 4326 OR GeometryType(geom) <> 'POLYGON')) AS bad FROM parking_area
  UNION ALL SELECT 'road_segment.geom', 'LINESTRING', count(*), count(*) FILTER (WHERE geom IS NOT NULL AND (ST_SRID(geom) <> 4326 OR GeometryType(geom) <> 'LINESTRING')) FROM road_segment
  UNION ALL SELECT 'location_ping.geom', 'POINT', count(*), count(*) FILTER (WHERE geom IS NOT NULL AND (ST_SRID(geom) <> 4326 OR GeometryType(geom) <> 'POINT')) FROM location_ping
  UNION ALL SELECT 'trip.start_geom', 'POINT', count(*), count(*) FILTER (WHERE start_geom IS NOT NULL AND (ST_SRID(start_geom) <> 4326 OR GeometryType(start_geom) <> 'POINT')) FROM trip
  UNION ALL SELECT 'trip.end_geom', 'POINT', count(*), count(*) FILTER (WHERE end_geom IS NOT NULL AND (ST_SRID(end_geom) <> 4326 OR GeometryType(end_geom) <> 'POINT')) FROM trip
) t;

-- 6b. PostGIS (INFO): coordinates in longitude/latitude order inside Puerto Rico,
-- geometry validity and emptiness. Reported only; values are never changed.
CREATE TEMP TABLE geom_value AS
SELECT 'parking_area.geom' AS check_name, geom FROM parking_area
UNION ALL SELECT 'road_segment.geom', geom FROM road_segment
UNION ALL SELECT 'location_ping.geom', geom FROM location_ping
UNION ALL SELECT 'trip.start_geom', start_geom FROM trip
UNION ALL SELECT 'trip.end_geom', end_geom FROM trip;

INSERT INTO validation_result (section, check_name, status, detail)
SELECT '6. PostGIS', check_name || ' extent',
       'INFO',
       count(*) FILTER (WHERE NOT ST_Within(geom, ST_MakeEnvelope(-68.0, 17.5, -65.0, 19.0, 4326)))
         || ' outside Puerto Rico bbox; extent lon ' || round(min(ST_XMin(geom))::numeric, 4) || '..' || round(max(ST_XMax(geom))::numeric, 4)
         || ', lat ' || round(min(ST_YMin(geom))::numeric, 4) || '..' || round(max(ST_YMax(geom))::numeric, 4)
FROM geom_value
WHERE geom IS NOT NULL
GROUP BY check_name;

INSERT INTO validation_result (section, check_name, status, detail)
SELECT '6. PostGIS', check_name || ' validity',
       'INFO',
       count(*) FILTER (WHERE NOT ST_IsValid(geom)) || ' invalid, '
         || count(*) FILTER (WHERE ST_IsEmpty(geom)) || ' empty'
FROM geom_value
WHERE geom IS NOT NULL
GROUP BY check_name;

-- 7. Data sanity (INFO): reported only, never filtered
INSERT INTO validation_result (section, check_name, status, detail)
SELECT '7. Sanity', check_name, 'INFO', n || ' rows'
FROM (
  SELECT 'trip end_ts before start_ts' AS check_name, count(*) AS n FROM trip WHERE end_ts < start_ts
  UNION ALL SELECT 'trip negative distance_km', count(*) FROM trip WHERE distance_km < 0
  UNION ALL SELECT 'assignment assigned_to before assigned_from', count(*) FROM vehicle_assignment WHERE assigned_to < assigned_from
  UNION ALL SELECT 'assignment open-ended (assigned_to NULL)', count(*) FROM vehicle_assignment WHERE assigned_to IS NULL
  UNION ALL SELECT 'ping negative speed_kph', count(*) FROM location_ping WHERE speed_kph < 0
  UNION ALL SELECT 'ping heading_deg outside 0..360', count(*) FROM location_ping WHERE heading_deg < 0 OR heading_deg > 360
  UNION ALL SELECT 'ping heading_deg NULL', count(*) FROM location_ping WHERE heading_deg IS NULL
) t;

-- Results
\echo
\echo '==================== VALIDATION RESULTS ===================='
SELECT section, check_name, status, detail
FROM validation_result
ORDER BY section, CASE status WHEN 'FAIL' THEN 0 WHEN 'INFO' THEN 2 ELSE 1 END, id;

\echo '========================= SUMMARY =========================='
SELECT count(*) FILTER (WHERE status = 'PASS') AS passed,
       count(*) FILTER (WHERE status = 'FAIL') AS failed,
       count(*) FILTER (WHERE status = 'INFO') AS info,
       CASE WHEN count(*) FILTER (WHERE status = 'FAIL') = 0 THEN 'PASS' ELSE 'FAIL' END AS overall
FROM validation_result;

-- 8. Representative queries (results shown for review, not pass/fail)
\echo
\echo '=========== REPRESENTATIVE QUERIES (for review) ============'

\echo '-- 8.1 Vehicles with their type, kind, fuel and status (first 10)'
SELECT v.vehicle_id, v.plate_number, v.make, v.model, v.year,
       k.name AS kind, f.name AS fuel, vt.emissions_rating, s.name AS status
FROM vehicle v
JOIN vehicle_type vt ON vt.vehicle_type_id = v.vehicle_type_id
JOIN vehicle_kind k ON k.vehicle_kind_id = vt.vehicle_kind_id
JOIN fuel_type f ON f.fuel_type_id = vt.fuel_type_id
JOIN vehicle_status s ON s.vehicle_status_id = v.vehicle_status_id
ORDER BY v.vehicle_id
LIMIT 10;

\echo '-- 8.2 Assignment history of driver 1'
SELECT d.driver_id, d.first_name || ' ' || d.last_name AS driver, v.plate_number,
       va.assigned_from, va.assigned_to
FROM vehicle_assignment va
JOIN driver d ON d.driver_id = va.driver_id
JOIN vehicle v ON v.vehicle_id = va.vehicle_id
WHERE d.driver_id = 1
ORDER BY va.assigned_from;

\echo '-- 8.3 Trips and distance per vehicle (top 10 by distance)'
SELECT v.vehicle_id, v.plate_number, count(t.trip_id) AS trips,
       round(sum(t.distance_km)::numeric, 3) AS total_km
FROM vehicle v
LEFT JOIN trip t ON t.vehicle_id = v.vehicle_id
GROUP BY v.vehicle_id, v.plate_number
ORDER BY total_km DESC NULLS LAST
LIMIT 10;

\echo '-- 8.4 Parking areas with the most GPS pings inside them (ST_Within)'
SELECT p.parking_area_id, p.name, p.capacity, count(*) AS pings_inside
FROM parking_area p
JOIN location_ping lp ON ST_Within(lp.geom, p.geom)
GROUP BY p.parking_area_id, p.name, p.capacity
ORDER BY pings_inside DESC
LIMIT 10;

\echo '-- 8.5 Nearest road segment to the first 5 pings (KNN <->)'
SELECT lp.ping_id, ST_AsText(lp.geom) AS ping, r.road_id, r.name AS road,
       round(ST_Distance(lp.geom::geography, r.geom::geography)::numeric, 1) AS meters
FROM (SELECT * FROM location_ping ORDER BY ping_id LIMIT 5) lp
CROSS JOIN LATERAL (
  SELECT road_id, name, geom FROM road_segment
  ORDER BY road_segment.geom <-> lp.geom
  LIMIT 1
) r
ORDER BY lp.ping_id;

\echo '-- 8.6 Trips that start within 500 m of the first trip start point (ST_DWithin)'
SELECT t.trip_id, t.vehicle_id, t.start_ts, ST_AsText(t.start_geom) AS start_point
FROM trip t, (SELECT start_geom FROM trip ORDER BY trip_id LIMIT 1) ref
WHERE ST_DWithin(t.start_geom::geography, ref.start_geom::geography, 500)
ORDER BY t.trip_id
LIMIT 10;
