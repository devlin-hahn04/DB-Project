from contextlib import asynccontextmanager

from fastapi import FastAPI
from pydantic import BaseModel

from backend.config.dbconfig import (
    initialize_connection_pool,
    close_connection_pool
)

from backend.handler.health import HealthHandler


# Pydantic response models


class HealthResponse(BaseModel):
    status: str
    service: str


class DatabaseHealthResponse(BaseModel):
    status: str
    database: str
    postgis_version: str

# Application lifecycle


@asynccontextmanager
async def lifespan(app: FastAPI):

    # Initialize PostgreSQL connection pool
    initialize_connection_pool()

    yield

    # Close connections when shutting down
    close_connection_pool()


# FastAPI application


app = FastAPI(
    title="Car Tracking REST API",
    description=(
        "Phase 2 REST API for the Car Tracking "
        "Database Project using Handler/DAO architecture."
    ),
    version="1.0.0",
    lifespan=lifespan
)



# Root endpoint


@app.get("/")
def root():
    return {
        "application": "Car Tracking REST API",
        "version": "1.0.0",
        "status": "running"
    }



# Application health


@app.get(
    "/api/v1/health",
    response_model=HealthResponse
)
def health():
    return {
        "status": "ok",
        "service": "backend"
    }



# Database health


@app.get(
    "/api/v1/health/database",
    response_model=DatabaseHealthResponse
)
def database_health():

    handler = HealthHandler()

    return handler.get_database_status()