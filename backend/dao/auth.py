
"""PostgreSQL access for application users."""

from psycopg2.extras import RealDictCursor

from backend.config.dbconfig import get_db_connection


class AuthDAO:
    """Database operations for authentication users."""

    PUBLIC_COLUMNS = (
        "user_id, email, created_at, is_active"
    )

    def create_user(
        self,
        email: str,
        password_hash: str
    ) -> dict:
        """Create a user and return public account fields."""

        with get_db_connection() as conn:
            with conn.cursor(
                cursor_factory=RealDictCursor
            ) as cursor:

                cursor.execute(
                    f"""
                    INSERT INTO public.app_user (
                        email,
                        password_hash
                    )
                    VALUES (%s, %s)
                    RETURNING {self.PUBLIC_COLUMNS}
                    """,
                    (email, password_hash)
                )

                return dict(cursor.fetchone())

    def get_by_email(
        self,
        email: str
    ) -> dict | None:
        """Retrieve a user including their password hash."""

        with get_db_connection() as conn:
            with conn.cursor(
                cursor_factory=RealDictCursor
            ) as cursor:

                cursor.execute(
                    """
                    SELECT
                        user_id,
                        email,
                        password_hash,
                        created_at,
                        is_active
                    FROM public.app_user
                    WHERE email = %s
                    """,
                    (email,)
                )

                row = cursor.fetchone()

                return dict(row) if row else None

    def get_by_id(
        self,
        user_id: int
    ) -> dict | None:
        """Retrieve public account information by user ID."""

        with get_db_connection() as conn:
            with conn.cursor(
                cursor_factory=RealDictCursor
            ) as cursor:

                cursor.execute(
                    f"""
                    SELECT {self.PUBLIC_COLUMNS}
                    FROM public.app_user
                    WHERE user_id = %s
                    """,
                    (user_id,)
                )

                row = cursor.fetchone()

                return dict(row) if row else None
