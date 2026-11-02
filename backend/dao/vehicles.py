
from psycopg2 import sql
from psycopg2.extras import RealDictCursor

from backend.config.dbconfig import get_db_connection


class VehicleDAO:
    """
    Data Access Object for vehicle records.
    Responsible for SQL operations only.
    """

    VEHICLE_COLUMNS = """
        vehicle_id,
        vehicle_type_id,
        vehicle_status_id,
        plate_number,
        make,
        model,
        year,
        created_at
    """

    def create_vehicle(self, data):
        query = f"""
            INSERT INTO vehicle (
                vehicle_type_id,
                vehicle_status_id,
                plate_number,
                make,
                model,
                year
            )
            VALUES (
                %(vehicle_type_id)s,
                %(vehicle_status_id)s,
                %(plate_number)s,
                %(make)s,
                %(model)s,
                %(year)s
            )
            RETURNING {self.VEHICLE_COLUMNS}
        """

        with get_db_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(query, data)
                return dict(cursor.fetchone())

    def get_vehicle_by_id(self, vehicle_id):
        query = f"""
            SELECT {self.VEHICLE_COLUMNS}
            FROM vehicle
            WHERE vehicle_id = %s
        """

        with get_db_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(query, (vehicle_id,))
                result = cursor.fetchone()
                return dict(result) if result else None

    def get_vehicles(self, limit, offset, plate_number=None, status=None):
        conditions = []
        parameters = []

        if plate_number:
            conditions.append("v.plate_number ILIKE %s")
            parameters.append(f"%{plate_number}%")

        if status:
            conditions.append(
                "(vs.name ILIKE %s OR "
                "CAST(v.vehicle_status_id AS TEXT) = %s)"
            )
            parameters.extend([status, status])

        where_clause = (
            " WHERE " + " AND ".join(conditions)
            if conditions else ""
        )

        columns = ", ".join(
            f"v.{column.strip()}"
            for column in self.VEHICLE_COLUMNS.split(",")
        )

        query = f"""
            SELECT {columns}
            FROM vehicle v
            JOIN vehicle_status vs
                ON v.vehicle_status_id = vs.vehicle_status_id
            {where_clause}
            ORDER BY v.vehicle_id
            LIMIT %s OFFSET %s
        """

        count_query = f"""
            SELECT COUNT(*) AS total
            FROM vehicle v
            JOIN vehicle_status vs
                ON v.vehicle_status_id = vs.vehicle_status_id
            {where_clause}
        """

        with get_db_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(query, parameters + [limit, offset])
                vehicles = [dict(row) for row in cursor.fetchall()]

                cursor.execute(count_query, parameters)
                total = cursor.fetchone()["total"]

        return vehicles, total

    def update_vehicle(self, vehicle_id, data):
        assignments = [
            sql.SQL("{} = %s").format(sql.Identifier(column))
            for column in data
        ]

        query = sql.SQL("""
            UPDATE vehicle
            SET {}
            WHERE vehicle_id = %s
            RETURNING
                vehicle_id,
                vehicle_type_id,
                vehicle_status_id,
                plate_number,
                make,
                model,
                year,
                created_at
        """).format(sql.SQL(", ").join(assignments))

        values = list(data.values()) + [vehicle_id]

        with get_db_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(query, values)
                result = cursor.fetchone()
                return dict(result) if result else None

    def delete_vehicle(self, vehicle_id):
        query = """
            DELETE FROM vehicle
            WHERE vehicle_id = %s
            RETURNING vehicle_id
        """

        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(query, (vehicle_id,))
                return cursor.fetchone() is not None

    def get_current_location(self, vehicle_id):
        """
        Retrieve the latest location ping and related vehicle details.
        """
        query = """
            SELECT
                v.vehicle_id,
                v.plate_number,
                vs.name AS status,
                vk.name AS vehicle_kind,
                ft.name AS fuel_type,
                vt.emissions_rating,
                lp.ts AS last_ts,
                ST_AsGeoJSON(lp.geom)::json AS last_geom,
                lp.speed_kph,
                lp.heading_deg
            FROM vehicle v
            LEFT JOIN vehicle_status vs
                ON v.vehicle_status_id = vs.vehicle_status_id
            LEFT JOIN vehicle_type vt
                ON v.vehicle_type_id = vt.vehicle_type_id
            LEFT JOIN vehicle_kind vk
                ON vt.vehicle_kind_id = vk.vehicle_kind_id
            LEFT JOIN fuel_type ft
                ON vt.fuel_type_id = ft.fuel_type_id
            JOIN LATERAL (
                SELECT ts, geom, speed_kph, heading_deg
                FROM location_ping
                WHERE vehicle_id = v.vehicle_id
                ORDER BY ts DESC NULLS LAST, ping_id DESC
                LIMIT 1
            ) lp ON TRUE
            WHERE v.vehicle_id = %s
        """

        with get_db_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(query, (vehicle_id,))
                result = cursor.fetchone()
                return dict(result) if result else None
