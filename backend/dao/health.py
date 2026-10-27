from backend.config.dbconfig import get_db_connection


class HealthDAO:
    
    # Data Access Object for database health checks.

    # Responsible only for executing SQL queries.
    

    def get_database_status(self):

        with get_db_connection() as conn:

            with conn.cursor() as cursor:

                cursor.execute("""
                    SELECT
                        current_database(),
                        PostGIS_Version()
                """)

                result = cursor.fetchone()

        return {
            "database": result[0],
            "postgis_version": result[1]
        }