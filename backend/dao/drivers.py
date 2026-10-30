from psycopg2 import sql
from psycopg2.extras import RealDictCursor

from backend.config.dbconfig import get_db_connection


class DriverDAO:
    """
    Data Access Object for driver records.

    Responsible for SQL operations only.
    """

    DRIVER_COLUMNS = """
        driver_id,
        first_name,
        last_name,
        license_number,
        hired_at
    """

    def create_driver(self, data):
        """
        Insert a driver and return the created record.
        """

        query = f"""
            INSERT INTO driver (
                first_name,
                last_name,
                license_number,
                hired_at
            )
            VALUES (
                %(first_name)s,
                %(last_name)s,
                %(license_number)s,
                %(hired_at)s
            )
            RETURNING {self.DRIVER_COLUMNS}
        """

        with get_db_connection() as conn:
            with conn.cursor(
                cursor_factory=RealDictCursor
            ) as cursor:

                cursor.execute(query, data)

                return dict(cursor.fetchone())

    def get_driver_by_id(self, driver_id):
        """
        Retrieve one driver by primary key.
        """

        query = f"""
            SELECT {self.DRIVER_COLUMNS}
            FROM driver
            WHERE driver_id = %s
        """

        with get_db_connection() as conn:
            with conn.cursor(
                cursor_factory=RealDictCursor
            ) as cursor:

                cursor.execute(query, (driver_id,))

                result = cursor.fetchone()

                return dict(result) if result else None

    def get_drivers(
        self,
        limit,
        offset,
        name=None,
        license_number=None,
    ):
        """
        Retrieve drivers with optional filters and pagination.
        """

        conditions = []
        parameters = []

        if name:
            conditions.append(
                "(first_name ILIKE %s OR last_name ILIKE %s)"
            )

            pattern = f"%{name}%"
            parameters.extend([pattern, pattern])

        if license_number:
            conditions.append(
                "license_number ILIKE %s"
            )

            parameters.append(f"%{license_number}%")

        where_clause = ""

        if conditions:
            where_clause = (
                " WHERE " + " AND ".join(conditions)
            )

        query = f"""
            SELECT {self.DRIVER_COLUMNS}
            FROM driver
            {where_clause}
            ORDER BY driver_id
            LIMIT %s OFFSET %s
        """

        count_query = f"""
            SELECT COUNT(*) AS total
            FROM driver
            {where_clause}
        """

        with get_db_connection() as conn:
            with conn.cursor(
                cursor_factory=RealDictCursor
            ) as cursor:

                cursor.execute(
                    query,
                    parameters + [limit, offset]
                )

                drivers = [
                    dict(row)
                    for row in cursor.fetchall()
                ]

                cursor.execute(
                    count_query,
                    parameters
                )

                total = cursor.fetchone()["total"]

        return drivers, total

    def update_driver(self, driver_id, data):
        """
        Update only the supplied fields.

        Column names are safely constructed using psycopg2.sql.
        """

        assignments = [
            sql.SQL("{} = %s").format(
                sql.Identifier(column)
            )
            for column in data
        ]

        query = sql.SQL("""
            UPDATE driver
            SET {}
            WHERE driver_id = %s
            RETURNING
                driver_id,
                first_name,
                last_name,
                license_number,
                hired_at
        """).format(
            sql.SQL(", ").join(assignments)
        )

        values = list(data.values()) + [driver_id]

        with get_db_connection() as conn:
            with conn.cursor(
                cursor_factory=RealDictCursor
            ) as cursor:

                cursor.execute(query, values)

                result = cursor.fetchone()

                return dict(result) if result else None

    def delete_driver(self, driver_id):
        """
        Delete a driver by ID.

        PostgreSQL prevents deletion when vehicle assignments
        reference the driver.
        """

        query = """
            DELETE FROM driver
            WHERE driver_id = %s
            RETURNING driver_id
        """

        with get_db_connection() as conn:
            with conn.cursor() as cursor:

                cursor.execute(query, (driver_id,))

                return cursor.fetchone() is not None