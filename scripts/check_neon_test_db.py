"""Read-only connectivity/schema check for the Neon test database.

Run with TEST_DATABASE_URL set:
    python scripts/check_neon_test_db.py

This script never creates, alters, inserts, updates, or deletes data.
"""
import os
import sys

import psycopg


def main() -> int:
    dsn = os.environ.get("TEST_DATABASE_URL")
    if not dsn:
        print("FAIL: TEST_DATABASE_URL is not set.")
        return 2

    try:
        with psycopg.connect(dsn, connect_timeout=10) as conn:
            with conn.cursor() as cur:
                cur.execute("SET TRANSACTION READ ONLY")
                cur.execute(
                    """
                    SELECT current_database(), current_user,
                           current_schema(), version()
                    """
                )
                database, user, schema, version = cur.fetchone()

                cur.execute(
                    """
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema = 'public'
                      AND table_type = 'BASE TABLE'
                    ORDER BY table_name
                    """
                )
                tables = [row[0] for row in cur.fetchall()]

        print("PASS: Neon test database connection succeeded.")
        print(f"Database: {database}")
        print(f"User: {user}")
        print(f"Schema: {schema}")
        print(f"Public tables ({len(tables)}): {', '.join(tables) if tables else '(none yet)'}")
        print("Transaction mode: READ ONLY")
        print(f"PostgreSQL: {version.splitlines()[0]}")
        return 0
    except Exception as exc:
        # Do not print the DSN or credentials.
        print(f"FAIL: Neon test database check failed: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
