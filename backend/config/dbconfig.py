# creates a shared pool of postgresql connections
# dao classes borrow connectiond using get_db_connection()
# queries are executed using those connections 
# connections are returned to the pool automatically
# close_connection_pool() closes all connections when FastAPI shuts down 

import os
from contextlib import contextmanager

from psycopg2.pool import ThreadedConnectionPool

# SimpleConnectionPool creates, manages and reuses database connections in a single threaded env. 
# -> not thread safe, meaning it is not designed to be accessed simultaneously by multiple threads 

# ThreadedConnectionPool creates, manages and reuses database connections in a multithreaded env.
# -> it is thread safe, meaning multiple threads can safely acquire and return connnections concurrently 
# (concurrently means to handle multiple HTTP requests at the same time, instead of waiting for one request
# -> to finish before processing another)


# PostgreSQL connection pool configuration
POOL_CONFIG = {
    "minconn": int(os.getenv("DB_POOL_MIN", "1")),
    "maxconn": int(os.getenv("DB_POOL_MAX", "10")),
}


# PostgreSQL database configuration
PG_DB_CONFIG = {
    "host": os.getenv("DB_HOST", "postgres"),
    "port": int(os.getenv("DB_PORT", "5432")),
    "dbname": os.getenv("DB_NAME"),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
    "sslmode": os.getenv("DB_SSLMODE", "disable"),
}


# Shared connection pool
connection_pool = None


def initialize_connection_pool():
    """
    Initialize the PostgreSQL connection pool.

    Called once when the FastAPI application starts.
    """

    global connection_pool

    if connection_pool is None:
        connection_pool = ThreadedConnectionPool(
            **POOL_CONFIG,
            **PG_DB_CONFIG
        )

    return connection_pool


@contextmanager
def get_db_connection():
    """
    Acquire a connection from the pool.

    Automatically commits successful operations,
    rolls back failed operations, and returns
    the connection to the pool.
    """

    if connection_pool is None:
        raise RuntimeError(
            "Database connection pool is not initialized."
        )

    conn = connection_pool.getconn()

    try:
        yield conn
        conn.commit()

    except Exception:
        conn.rollback()
        raise

    finally:
        connection_pool.putconn(conn)


def close_connection_pool():
    """
    Close all PostgreSQL connections when
    the application shuts down.
    """

    global connection_pool

    if connection_pool is not None:
        connection_pool.closeall()
        connection_pool = None