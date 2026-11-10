"""enable_extensions

Revision ID: 0001
Revises:
Create Date: 2026-11-10

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")


def downgrade() -> None:
    # No-op by design: CREATE EXTENSION IF NOT EXISTS doesn't record whether
    # this migration created the extension or it already existed, so there's
    # no reliable way to know it's safe to drop -- leave both installed.
    pass
