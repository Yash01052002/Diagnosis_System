-- Executed once by the postgres image on first initialisation of the data
-- directory. Extensions must exist before Alembic runs.

-- Server-side UUID generation (the application generates UUIDs in Python, but
-- this keeps raw SQL inserts and future default expressions available).
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- Trigram indexes for the crash/device search added in Phase 2.
CREATE EXTENSION IF NOT EXISTS "pg_trgm";
