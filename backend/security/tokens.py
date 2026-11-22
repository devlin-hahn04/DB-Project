
"""Argon2id password hashing and HS256 JWT utilities."""

import os

from datetime import datetime, timedelta, timezone

import jwt

from jwt.exceptions import InvalidTokenError

from pwdlib import PasswordHash


HASHER = PasswordHash.recommended()

ALGORITHM = "HS256"

ISSUER = "car-tracking-api"


# Add near ISSUER
AUDIENCE = "car-tracking-api-users"



def get_secret() -> str:
    """Read and validate the JWT signing secret."""

    secret = os.getenv("JWT_SECRET_KEY", "")

    if len(secret) < 32:
        raise RuntimeError(
            "JWT_SECRET_KEY must contain at least 32 characters."
        )

    return secret


def token_lifetime_minutes() -> int:
    """Retrieve the configured access-token lifetime."""

    raw = os.getenv(
        "JWT_ACCESS_TOKEN_EXPIRE_MINUTES",
        "30"
    )

    try:
        minutes = int(raw)

    except ValueError as error:
        raise RuntimeError(
            "Invalid JWT_ACCESS_TOKEN_EXPIRE_MINUTES."
        ) from error

    if not 1 <= minutes <= 1440:
        raise RuntimeError(
            "JWT token lifetime must be between "
            "1 and 1440 minutes."
        )

    return minutes


def validate_settings() -> None:
    """Validate authentication configuration on startup."""

    get_secret()
    token_lifetime_minutes()


def hash_password(password: str) -> str:
    """Generate an Argon2id password hash."""

    return HASHER.hash(password)


def verify_password(
    password: str,
    hashed: str
) -> bool:
    """Verify a plaintext password against its hash."""

    return HASHER.verify(password, hashed)


def create_access_token(
    user_id: int
) -> tuple[str, int]:
    """Create an expiring signed JWT."""

    now = datetime.now(timezone.utc)

    expires_in = token_lifetime_minutes() * 60

    payload = {
        "sub": str(user_id),
        "iss": ISSUER,
        "iat": now,
        "exp": now + timedelta(seconds=expires_in),
        "type": "access",
        "aud": AUDIENCE
    }

    token = jwt.encode(
        payload,
        get_secret(),
        algorithm=ALGORITHM
    )

    return token, expires_in


def decode_access_token(token: str) -> int:
    """Verify a JWT and return its user ID."""

    try:
        payload = jwt.decode(
            token,
            get_secret(),
            algorithms=[ALGORITHM],
            issuer=ISSUER,
            audience=AUDIENCE,
            options={
                "require": [
                    "sub",
                    "iss",
                    "iat",
                    "exp",
                    "type",
                    "aud"
                ]
            }
        )

        if payload.get("type") != "access":
            raise ValueError(
                "Unexpected token type."
            )

        subject = payload["sub"]

        if (
            not isinstance(subject, str)
            or not subject.isascii()
            or not subject.isdecimal()
            or not 1 <= len(subject) <= 19
        ):
            raise ValueError(
                "Invalid token subject."
            )

        user_id = int(subject)

        if user_id < 1:
            raise ValueError(
                "Invalid token subject."
            )

        return user_id

    except (
        InvalidTokenError,
        ValueError,
        TypeError,
        KeyError
    ) as error:
        raise ValueError(
            "Invalid or expired authentication token."
        ) from error
