# Migrations

SQL files applied manually via the Supabase SQL editor (Dashboard → SQL Editor → New query → paste → Run) or `psql "$SUPABASE_DB_URL" -f 001_initial.sql`.

Run them in numeric order. Each file is idempotent for table/index creation; RLS policies use `drop policy if exists` so re-running is safe.

## Adding a new migration

Name the file `NNN_short_description.sql` (zero-padded number). Document any non-additive changes in the file header comment.
