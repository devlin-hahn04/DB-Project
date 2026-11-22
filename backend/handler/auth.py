
"""Authentication business logic and HTTP error handling."""

import logging

from fastapi import HTTPException

from psycopg2 import (
    Error as PostgreSQLError,
    IntegrityError,
    OperationalError,
)
from psycopg2.errorcodes import UNIQUE_VIOLATION

from backend.dao.auth import AuthDAO

from backend.security.tokens import (
    hash_password,
    verify_password,
    create_access_token,
    decode_access_token,
)


logger = logging.getLogger(__name__)

# Fixed dummy hash for nonexistent account login attempts.
# Reduces timing differences between known and unknown emails.
DUMMY_HASH = hash_password(
    "dummy-password-for-timing-equalization"
)


class AuthHandler:
    """Registration, login, and current-user business logic."""

    def __init__(self, dao=None):
        self.dao = dao if dao is not None else AuthDAO()

    def register(
        self,
        email: str,
        password: str,
    ) -> dict:
        """Register a user with an Argon2id password hash."""

        # Hashing is separate from database error handling.
        try:
            password_hash = hash_password(password)

        except Exception as error:
            logger.exception(
                "Password hashing failed during registration"
            )

            raise HTTPException(
                status_code=500,
                detail="Internal server error",
            ) from error

        # Only PostgreSQL operations are handled here.
        try:
            return self.dao.create_user(
                email,
                password_hash,
            )

        except IntegrityError as error:
            if error.pgcode == UNIQUE_VIOLATION:
                raise HTTPException(
                    status_code=409,
                    detail="Email is already registered.",
                ) from error

            logger.exception(
                "Registration database constraint failure"
            )

            raise HTTPException(
                status_code=500,
                detail="Internal server error",
            ) from error

        except OperationalError as error:
            logger.exception(
                "Authentication database unavailable"
            )

            raise HTTPException(
                status_code=503,
                detail="Authentication service unavailable.",
            ) from error

        except PostgreSQLError as error:
            logger.exception(
                "Registration database operation failed"
            )

            raise HTTPException(
                status_code=500,
                detail="Internal server error",
            ) from error

    def login(
        self,
        email: str,
        password: str,
    ) -> dict:
        """Verify credentials and issue an access token."""

        try:
            user = self.dao.get_by_email(email)

        except OperationalError as error:
            logger.exception(
                "Authentication database unavailable"
            )

            raise HTTPException(
                status_code=503,
                detail="Authentication service unavailable.",
            ) from error

        except PostgreSQLError as error:
            logger.exception(
                "Authentication user lookup failed"
            )

            raise HTTPException(
                status_code=500,
                detail="Internal server error",
            ) from error

        candidate_hash = (
            user["password_hash"]
            if user
            else DUMMY_HASH
        )

        try:
            is_valid = verify_password(
                password,
                candidate_hash,
            )

        except Exception as error:
            logger.exception(
                "Password verification failed"
            )

            raise HTTPException(
                status_code=500,
                detail="Internal server error",
            ) from error

        if (
            not user
            or not is_valid
            or not user["is_active"]
        ):
            raise HTTPException(
                status_code=401,
                detail="Invalid email or password.",
                headers={
                    "WWW-Authenticate": "Bearer",
                },
            )

        # JWT configuration and generation are intentionally
        # separate from database error handling.
        try:
            token, expires_in = create_access_token(
                user["user_id"]
            )

        except Exception as error:
            logger.exception(
                "Access token generation failed"
            )

            raise HTTPException(
                status_code=500,
                detail="Authentication token generation failed.",
            ) from error

        return {
            "access_token": token,
            "token_type": "bearer",
            "expires_in": expires_in,
        }

    def current_user(
        self,
        token: str,
    ) -> dict:
        """Validate JWT and retrieve the authenticated user."""

        try:
            user_id = decode_access_token(token)

        except ValueError as error:
            raise HTTPException(
                status_code=401,
                detail=(
                    "Invalid or expired authentication token."
                ),
                headers={
                    "WWW-Authenticate": "Bearer",
                },
            ) from error

        # Configuration failures should not be reported
        # to clients as invalid credentials.
        except RuntimeError as error:
            logger.exception(
                "Authentication configuration failed"
            )

            raise HTTPException(
                status_code=500,
                detail="Authentication service configuration error.",
            ) from error

        try:
            user = self.dao.get_by_id(user_id)

        except OperationalError as error:
            logger.exception(
                "Authentication database unavailable"
            )

            raise HTTPException(
                status_code=503,
                detail="Authentication service unavailable.",
            ) from error

        except PostgreSQLError as error:
            logger.exception(
                "Authentication user lookup failed"
            )

            raise HTTPException(
                status_code=500,
                detail="Internal server error",
            ) from error

        if not user or not user["is_active"]:
            raise HTTPException(
                status_code=401,
                detail=(
                    "Invalid or expired authentication token."
                ),
                headers={
                    "WWW-Authenticate": "Bearer",
                },
            )

        return user
