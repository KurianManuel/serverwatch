# Migration SQL Files

This directory contains SQL migration files for future schema versions.

## Conventions

- Migration files are named: `{version:04d}_{description}.sql`
- Example: `0002_alert_rules.sql`, `0003_process_samples.sql`
- Each file must contain only DDL statements (CREATE TABLE, CREATE INDEX, etc.)
- Statements are executed in order within a single explicit transaction
- No BEGIN/COMMIT in the SQL file - the migration runner manages transactions
- Future migrations should follow the same pattern: create tables/indexes first, version record last

## Phase 4A Note

Migration 0001 (initial schema) is defined directly in `app/database/migrations.py` as `MIGRATION_0001_STATEMENTS`.
This avoids maintaining a separate SQL file for the initial schema while the project is in early development.

Future migrations (0002+) should use files in this directory.