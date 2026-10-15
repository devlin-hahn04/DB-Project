# Database and ETL Reproducibility Test Report

**Project:** Car Tracking – Phase I  
**Course:** CIIC 4060 / ICOM 5016   
**Test environment:** Windows, Docker Desktop  

## 1. Objective

Verify that the Car Tracking database and ETL pipeline can be reproduced independently using the repository's documented schema, Docker configuration, and official Parquet datasets.

This testing also verifies repeatable ETL execution, duplicate prevention, missing configuration handling, and data preservation after unsuccessful ETL executions.

## 2. Test Environment

- Docker Engine: 29.8.2
- Docker Compose: 5.6.0
- PostgreSQL: 17 with PostGIS 3.5
- ETL Python environment: Python 3.13 (Docker)
- Operating System: Windows with WSL2
- Development database: 'cartracking_fresh_test'
- Source files: 11 official Parquet datasets

## 3. Initialization Procedure

The following workflow was executed in PowerShell from the project directory.

### Start PostgreSQL

'''powershell
docker compose up -d postgres
'''

### Create a fresh development database

'''powershell
docker exec car-tracking-db psql -U naturaljoiners -d postgres -c "CREATE DATABASE cartracking_fresh_test;"
'''

**Result:** Database created successfully.

### Initialize schema

'''powershell
Get-Content .\sql\schema.sql -Raw |
docker exec -i car-tracking-db psql -X -v ON_ERROR_STOP=1 -1 -U naturaljoiners -d cartracking_fresh_test
'''

**Result:** PostGIS extension, 11 application tables, and 5 indexes created successfully.

### Build and execute ETL

'''powershell
docker compose build etl
docker compose run --rm -e DB_NAME=cartracking_fresh_test etl
'''

**Result:** All 11 Parquet datasets imported successfully, totaling 32,752 records.

## 4. ETL Rerun and Duplicate Prevention

The ETL was executed a second time against the same database.

'''powershell
docker compose run --rm -e DB_NAME=cartracking_fresh_test etl
'''

**Result:** Execution completed successfully with all 32,752 records reloaded.

The ETL follows a transactional full-refresh approach, resetting existing table contents before inserting the official dataset. This ensures that rerunning the process does not accumulate duplicate records.

## 5. Error Handling Tests

### Missing Database Configuration

'''powershell
docker compose run --rm -e DB_NAME=cartracking_fresh_test -e DB_USER= etl
'''

**Result:** PASSED

The ETL identified the missing 'DB_USER' variable, displayed a descriptive error message, and aborted execution.

### Missing Parquet Input Files

'''powershell
docker compose run --rm -e DB_NAME=cartracking_fresh_test -e DATA_DIR=/missing-data etl
'''

**Result:** PASSED

The ETL identified the missing 'vehicle_kind.parquet' file and aborted execution with a descriptive error.

### Data Preservation

After the unsuccessful ETL tests, the database was queried to verify that previously imported records remained available.

**Result:** PASSED — 'location_ping' retained all 28,041 records.

## 6. Database Validation

Executed:

'''powershell
Get-Content .\sql\validation.sql -Raw |
docker exec -i car-tracking-db psql -X -v ON_ERROR_STOP=1 -U naturaljoiners -d cartracking_fresh_test
'''

### Results

| Metric | Result |
|---|---|
| Validation checks passed | 167 |
| Validation checks failed | 0 |
| Informational results | 17 |
| Overall validation | passed |

Validation covered schema structure, column data types, primary keys, foreign keys, duplicate identifiers, NULL values, expected row counts, PostGIS geometry types, SRID 4326, and spatial integrity.

## 7. Reproducibility Conclusion

The Car Tracking database schema and ETL pipeline were successfully reproduced and tested from a fresh development database by a secondary team member.

All 11 official Parquet datasets were imported successfully, ETL reruns produced consistent record counts, and missing configuration or input files generated clear errors.

The validation suite completed with 167 passing checks and zero failures.

**Final Result: PASSED**

The database and ETL workflow were successfully reproduced in the independent tester's local development environment.