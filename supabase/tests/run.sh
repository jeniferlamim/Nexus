#!/usr/bin/env bash
# Applies all migrations to a throwaway PostgreSQL database and runs the RLS/governance tests.
# Usage: PGHOST=... PGPORT=... PGUSER=postgres ./supabase/tests/run.sh
set -euo pipefail
cd "$(dirname "$0")/.."
DB=${NEXUS_TEST_DB:-nexus_migration_test}
psql -v ON_ERROR_STOP=1 -q -d postgres -c "drop database if exists $DB" -c "create database $DB"
psql -v ON_ERROR_STOP=1 -q -d "$DB" -f tests/00_supabase_auth_stub.sql
for f in migrations/*.sql; do echo "→ $f"; psql -v ON_ERROR_STOP=1 -q -d "$DB" -f "$f"; done
out=$(psql -v ON_ERROR_STOP=1 -q -d "$DB" -f tests/10_rls_isolation_test.sql 2>&1) || { echo "$out"; echo "FAILED"; exit 1; }
echo "$out" | grep -o "PASS.*"
echo "ALL OK ($(echo "$out" | grep -c PASS) checks)"
