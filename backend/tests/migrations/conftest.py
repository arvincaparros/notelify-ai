import os
import subprocess
from pathlib import Path

import psycopg
import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
TEST_DB_NAME = "notelify_migrations_test"


def _base_url_without_db() -> str:
    """The configured DATABASE_URL (postgresql+asyncpg://user:pass@host:port)
    with the trailing /<dbname> stripped, so a different database name can be
    substituted for migration testing."""
    base = os.environ["DATABASE_URL"]
    prefix, _, _ = base.rpartition("/")
    return prefix


def _test_db_url() -> str:
    """postgresql+asyncpg:// URL for the dedicated migration-test database --
    same scheme app settings expect, so Settings.sync_database_url's
    asyncpg->psycopg swap works unchanged for Alembic."""
    return f"{_base_url_without_db()}/{TEST_DB_NAME}"


def _admin_psycopg_url() -> str:
    """Sync psycopg URL for the server's default maintenance database, used
    only to CREATE/DROP the dedicated test database itself."""
    prefix = _base_url_without_db().replace("postgresql+asyncpg://", "postgresql://")
    return f"{prefix}/postgres"


def run_alembic(args: list[str], db_url: str) -> subprocess.CompletedProcess:
    """Runs the real `alembic` CLI as a subprocess with DATABASE_URL pointed
    at the given database -- a fresh process means no lru_cache'd Settings
    from this test session leaks in, and it exercises Alembic exactly as a
    developer running `alembic upgrade head` from backend/ would."""
    env = {**os.environ, "DATABASE_URL": db_url}
    return subprocess.run(
        ["python", "-m", "alembic", *args],
        cwd=str(BACKEND_DIR),
        env=env,
        capture_output=True,
        text=True,
    )


@pytest.fixture(scope="session")
def migration_db_url():
    """A dedicated Postgres database for migration tests only -- never the
    dev database. Created once per test session and dropped at the end
    (docs/09-TESTING-STRATEGY.md's ephemeral-Postgres approach), with Alembic
    migrated to head exactly once here rather than per test."""
    admin_url = _admin_psycopg_url()
    with psycopg.connect(admin_url, autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}"')
        conn.execute(f'CREATE DATABASE "{TEST_DB_NAME}"')

    db_url = _test_db_url()
    try:
        result = run_alembic(["upgrade", "head"], db_url)
        assert result.returncode == 0, (
            f"alembic upgrade head failed:\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
        yield db_url
    finally:
        # Guarantees cleanup even if the assert above raises (migration setup
        # failed before yield) -- the dedicated test database is always
        # dropped, and only ever this one, never the dev database.
        with psycopg.connect(admin_url, autocommit=True) as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}"')


@pytest.fixture()
def migration_conn(migration_db_url):
    """Sync psycopg connection to the migrated test database, for schema
    introspection assertions."""
    sync_url = migration_db_url.replace("postgresql+asyncpg://", "postgresql://")
    with psycopg.connect(sync_url) as conn:
        yield conn
