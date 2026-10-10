-- Phase 1 DB Schema 

-- Enable PostGIS

CREATE EXTENSION IF NOT EXISTS postgis;

--Vehicle kind

CREATE TABLE vehicle_kind (
  name TEXT,
  vehicle_kind_id BIGINT PRIMARY KEY 
);

-- Fuel Type 
CREATE TABLE fuel_type (
  name TEXT,
  fuel_type_id BIGINT PRIMARY KEY
);

-- Vehicle status
CREATE TABLE vehicle_status (
  name TEXT,
  vehicle_status_id BIGINT PRIMARY KEY
);

-- Vehicle type
CREATE TABLE vehicle_type (
  vehicle_kind_id BIGINT,
  fuel_type_id BIGINT,
  emissions_rating DOUBLE PRECISION,
  created_at TIMESTAMP,
  vehicle_type_id BIGINT PRIMARY KEY,

  FOREIGN KEY (vehicle_kind_id)
    REFERENCES vehicle_kind(vehicle_kind_id),

  FOREIGN KEY (fuel_type_id) 
    REFERENCES fuel_type(fuel_type_id)
);

-- Parking area
CREATE TABLE parking_area (
  name TEXT,
  capacity BIGINT,
  geom GEOMETRY(POLYGON, 4326),
  created_at TIMESTAMP,
  parking_area_id BIGINT PRIMARY KEY
);

-- Driver
CREATE TABLE driver (
  first_name TEXT,
  last_name TEXT,
  license_number TEXT,
  hired_at TIMESTAMP,
  driver_id BIGINT PRIMARY KEY
);

-- Road segment
CREATE TABLE road_segment (
  name TEXT,
  speed_limit_kph BIGINT,
  geom GEOMETRY(LINESTRING, 4326),
  created_at TIMESTAMP,
  is_oneway BOOLEAN,
  direction TEXT,
  road_id BIGINT PRIMARY KEY
);

-- Vehicle 
CREATE TABLE vehicle (
  vehicle_type_id BIGINT,
  vehicle_status_id BIGINT,
  plate_number TEXT,
  make TEXT,
  model TEXT,
  year BIGINT,
  created_at TIMESTAMP,
  vehicle_id BIGINT PRIMARY KEY,

  FOREIGN KEY (vehicle_type_id) 
    REFERENCES vehicle_type(vehicle_type_id),

  FOREIGN KEY (vehicle_status_id) 
    REFERENCES vehicle_status(vehicle_status_id)
);

-- Location ping
CREATE TABLE location_ping (
  vehicle_id BIGINT,
  ts TIMESTAMP,
  geom GEOMETRY(POINT, 4326),
  speed_kph DOUBLE PRECISION,
  heading_deg DOUBLE PRECISION,
  ping_id BIGINT PRIMARY KEY,

  FOREIGN KEY (vehicle_id) 
    REFERENCES vehicle(vehicle_id)
);

-- Vehicle assignment 
CREATE TABLE vehicle_assignment (
  vehicle_id BIGINT,
  driver_id BIGINT,
  assigned_from TIMESTAMP,
  assigned_to TIMESTAMP,
  assignment_id BIGINT PRIMARY KEY,

  FOREIGN KEY (vehicle_id)
    REFERENCES vehicle(vehicle_id),

  FOREIGN KEY (driver_id)
    REFERENCES driver(driver_id)
);

-- Trip
CREATE TABLE trip (
  vehicle_id BIGINT,
  start_ts TIMESTAMP,
  end_ts TIMESTAMP,
  start_geom GEOMETRY(POINT, 4326),
  end_geom GEOMETRY(POINT, 4326),
  distance_km DOUBLE PRECISION,
  trip_id BIGINT PRIMARY KEY,

  FOREIGN KEY (vehicle_id)
    REFERENCES vehicle(vehicle_id)
);