"""Schema tests for migrations 0001-0003 against docs/04-DATABASE-DESIGN.md.

Verifies: clean apply, the Free plan seed, exact column/constraint/index
shape for plan_tiers/users/refresh_tokens/email_verification_tokens/
password_reset_tokens, and that downgrade leaves no unexpected objects.
"""
from .conftest import run_alembic


def _columns(conn, table_name):
    rows = conn.execute(
        """
        SELECT column_name, data_type, udt_name, is_nullable, column_default
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = %s
        ORDER BY ordinal_position
        """,
        (table_name,),
    ).fetchall()
    return {r[0]: {"data_type": r[1], "udt_name": r[2], "nullable": r[3] == "YES", "default": r[4]} for r in rows}


def _constraints(conn, table_name):
    rows = conn.execute(
        """
        SELECT conname, contype, pg_get_constraintdef(oid)
        FROM pg_constraint
        WHERE conrelid = %s::regclass
        """,
        (table_name,),
    ).fetchall()
    return {r[0]: {"type": r[1], "def": r[2]} for r in rows}


def _indexes(conn, table_name):
    rows = conn.execute(
        "SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = 'public' AND tablename = %s",
        (table_name,),
    ).fetchall()
    return {r[0]: r[1] for r in rows}


def _table_exists(conn, table_name) -> bool:
    row = conn.execute(
        "SELECT to_regclass(%s)",
        (f"public.{table_name}",),
    ).fetchone()
    return row[0] is not None


def test_extensions_enabled(migration_conn):
    rows = migration_conn.execute("SELECT extname FROM pg_extension").fetchall()
    names = {r[0] for r in rows}
    assert "pgcrypto" in names
    assert "citext" in names


def test_free_plan_seeded_exactly_once_with_300_minutes(migration_conn):
    rows = migration_conn.execute(
        "SELECT name, quota_minutes_per_period, is_active FROM plan_tiers WHERE name = 'free'"
    ).fetchall()
    assert len(rows) == 1, f"expected exactly one 'free' plan_tiers row, got {rows}"
    name, quota, is_active = rows[0]
    assert quota == 300
    assert is_active is True

    total = migration_conn.execute("SELECT count(*) FROM plan_tiers").fetchone()[0]
    assert total == 1, "plan_tiers should contain only the seeded free tier after a clean migration"


def test_reseeding_free_plan_does_not_create_a_duplicate(migration_conn):
    """Running the migration's seed statement again (e.g. a re-applied
    migration) must not create a second 'free' row -- the ON CONFLICT (name)
    DO NOTHING + UNIQUE(name) pairing is what the task required."""
    migration_conn.execute(
        """
        INSERT INTO plan_tiers (name, quota_minutes_per_period)
        VALUES ('free', 300)
        ON CONFLICT (name) DO NOTHING
        """
    )
    total = migration_conn.execute(
        "SELECT count(*) FROM plan_tiers WHERE name = 'free'"
    ).fetchone()[0]
    assert total == 1


def test_reseeding_does_not_overwrite_an_existing_free_plan_with_a_different_quota(migration_conn):
    """Documents the intentional DO NOTHING behavior: a pre-existing 'free'
    row with a different quota is left untouched by a repeated seed insert
    -- this is not a bug, by the approved correction. Mutates and rolls back
    within this test's own transaction so the shared migrated test database
    is unaffected for any other test."""
    migration_conn.execute(
        "UPDATE plan_tiers SET quota_minutes_per_period = 999 WHERE name = 'free'"
    )
    migration_conn.execute(
        """
        INSERT INTO plan_tiers (name, quota_minutes_per_period)
        VALUES ('free', 300)
        ON CONFLICT (name) DO NOTHING
        """
    )
    quota = migration_conn.execute(
        "SELECT quota_minutes_per_period FROM plan_tiers WHERE name = 'free'"
    ).fetchone()[0]
    assert quota == 999, "DO NOTHING must leave a pre-existing differing quota unchanged, by design"

    migration_conn.rollback()


def test_plan_tiers_schema(migration_conn):
    cols = _columns(migration_conn, "plan_tiers")
    assert cols["name"]["udt_name"] == "varchar"
    assert cols["name"]["nullable"] is False
    assert cols["quota_minutes_per_period"]["udt_name"] == "int4"
    assert cols["quota_minutes_per_period"]["nullable"] is False
    assert cols["is_active"]["udt_name"] == "bool"
    assert cols["is_active"]["default"] == "true"

    constraints = _constraints(migration_conn, "plan_tiers")
    check_defs = [c["def"] for c in constraints.values() if c["type"] == "c"]
    assert any("quota_minutes_per_period > 0" in d for d in check_defs)
    unique_defs = [c["def"] for c in constraints.values() if c["type"] == "u"]
    assert any("(name)" in d for d in unique_defs)


def test_users_schema(migration_conn):
    cols = _columns(migration_conn, "users")
    assert cols["email"]["udt_name"] == "citext"
    assert cols["email"]["nullable"] is False
    assert cols["password_hash"]["nullable"] is False
    assert cols["plan_tier_id"]["nullable"] is False
    assert cols["quota_minutes_used"]["default"] == "0"
    assert "date_trunc" in (cols["quota_period_start"]["default"] or "")

    constraints = _constraints(migration_conn, "users")
    unique_defs = [c["def"] for c in constraints.values() if c["type"] == "u"]
    assert any("(email)" in d for d in unique_defs)

    fk_defs = [c["def"] for c in constraints.values() if c["type"] == "f"]
    assert any("plan_tiers" in d and "ON DELETE RESTRICT" in d for d in fk_defs)

    check_defs = [c["def"] for c in constraints.values() if c["type"] == "c"]
    assert any("quota_minutes_used >=" in d for d in check_defs)


def test_refresh_tokens_schema(migration_conn):
    cols = _columns(migration_conn, "refresh_tokens")

    # family_id: NOT NULL, and critically -- no column default. The approved
    # design assigns it only in application code (fresh at login, copied
    # forward at rotation); a column default here would be an unapproved
    # deviation from docs/04-DATABASE-DESIGN.md.
    assert cols["family_id"]["nullable"] is False
    assert cols["family_id"]["default"] is None

    assert cols["grace_ciphertext"]["udt_name"] == "bytea"
    assert cols["grace_ciphertext"]["nullable"] is True
    assert cols["grace_expires_at"]["nullable"] is True
    assert cols["replaced_by_token_id"]["nullable"] is True

    constraints = _constraints(migration_conn, "refresh_tokens")
    fk_defs = [c["def"] for c in constraints.values() if c["type"] == "f"]
    assert any("users" in d and "ON DELETE CASCADE" in d for d in fk_defs)
    assert any(
        "refresh_tokens" in d and "ON DELETE SET NULL" in d and "replaced_by_token_id" in d
        for d in fk_defs
    )

    indexes = _indexes(migration_conn, "refresh_tokens")
    assert any("user_id" in d for d in indexes.values())
    assert any("token_hash" in d for d in indexes.values())
    assert any("family_id" in d for d in indexes.values())


def test_email_verification_tokens_schema(migration_conn):
    cols = _columns(migration_conn, "email_verification_tokens")
    assert cols["user_id"]["nullable"] is False
    assert cols["consumed_at"]["nullable"] is True

    constraints = _constraints(migration_conn, "email_verification_tokens")
    fk_defs = [c["def"] for c in constraints.values() if c["type"] == "f"]
    assert any("users" in d and "ON DELETE CASCADE" in d for d in fk_defs)

    indexes = _indexes(migration_conn, "email_verification_tokens")
    assert any("user_id" in d for d in indexes.values())


def test_password_reset_tokens_schema(migration_conn):
    cols = _columns(migration_conn, "password_reset_tokens")
    assert cols["user_id"]["nullable"] is False
    assert cols["consumed_at"]["nullable"] is True

    constraints = _constraints(migration_conn, "password_reset_tokens")
    fk_defs = [c["def"] for c in constraints.values() if c["type"] == "f"]
    assert any("users" in d and "ON DELETE CASCADE" in d for d in fk_defs)

    indexes = _indexes(migration_conn, "password_reset_tokens")
    assert any("user_id" in d for d in indexes.values())


def test_downgrade_removes_everything_then_restores_head(migration_db_url, migration_conn):
    down = run_alembic(["downgrade", "base"], migration_db_url)
    assert down.returncode == 0, f"downgrade failed:\n{down.stdout}\n{down.stderr}"

    for table in (
        "password_reset_tokens",
        "email_verification_tokens",
        "refresh_tokens",
        "users",
        "plan_tiers",
    ):
        assert not _table_exists(migration_conn, table), f"{table} still exists after downgrade base"

    # 0001's downgrade is a deliberate no-op (ownership of a shared resource
    # like an extension can't be determined reliably) -- both remain
    # installed even after a full downgrade to base.
    extensions = {r[0] for r in migration_conn.execute("SELECT extname FROM pg_extension").fetchall()}
    assert "pgcrypto" in extensions
    assert "citext" in extensions

    up = run_alembic(["upgrade", "head"], migration_db_url)
    assert up.returncode == 0, f"restoring upgrade head failed:\n{up.stdout}\n{up.stderr}"
