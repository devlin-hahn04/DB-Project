
-- =========================================================
-- Phase III - Issue #2
-- Authentication user table migration
-- =========================================================

BEGIN;

CREATE TABLE public.app_user (
    user_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    email TEXT NOT NULL,

    password_hash TEXT NOT NULL,

    created_at TIMESTAMPTZ NOT NULL
        DEFAULT CURRENT_TIMESTAMP,

    is_active BOOLEAN NOT NULL
        DEFAULT TRUE,

    CONSTRAINT app_user_email_canonical
        CHECK (
            email = lower(btrim(email))
            AND length(email) BETWEEN 3 AND 254
        ),

    CONSTRAINT app_user_password_hash_nonempty
        CHECK (length(password_hash) > 0),

    CONSTRAINT app_user_email_unique
        UNIQUE (email)
);

COMMIT;
