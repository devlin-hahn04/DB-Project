# Car Tracking Database Project

## Project Overview

The Car Tracking Database Project develops a database-driven system for organizing and analyzing vehicle tracking information. It brings together vehicles, drivers, assignments, trips, GPS location records, road segments, and parking areas in a relational database, enabling both conventional SQL queries and geographic analysis of vehicle activity.

The project uses PostgreSQL and PostGIS to store structured and spatial data. Its development is organized into three phases, progressing from database preparation and reliable data ingestion to subsequent project requirements.

## Project Phases

| Phase | Scope | Status |
|---|---|---|
| **Phase 1** | Design and initialize a PostgreSQL/PostGIS database; load the 11 supplied Parquet datasets using a reproducible Python ETL pipeline; validate relational and spatial data; and deploy a populated database to Render for remote access and grading. | Completed |
| **Phase 2** | To be documented when Phase 2 requirements are provided. | Pending |
| **Phase 3** | To be documented when Phase 3 requirements are provided. | Pending |

## Phase Documentation

| Phase | Documentation |
|---|---|
| **Phase 1** | [Phase 1 — Setup, ETL, Validation, and Render Deployment](phase1/README.md) |
| **Phase 2** | Documentation pending |
| **Phase 3** | Documentation pending |

## Render Database Credentials

The deployed database is hosted on Render and contains the project tables and imported data. These are **remote database credentials**, separate from the local Docker `.env` settings.

| Connection setting | Value |
|---|---|
| **Database user** | `cartrackingdb_2rg8_user` |
| **Database host** | `dpg-db87op4s728c738ghs30-a.virginia-postgres.render.com` |
| **Database name** | `cartracking_nchv` |
| **Database port** | `5432` |
| **Database password** | `dvAXpDOZkDMOwD7o1K4NRY54C43jNWrP` |

