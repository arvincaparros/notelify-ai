"""plan_tiers

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-10

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE plan_tiers (
            id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name                     VARCHAR(32) UNIQUE NOT NULL,
            quota_minutes_per_period INTEGER NOT NULL CHECK (quota_minutes_per_period > 0),
            is_active                BOOLEAN NOT NULL DEFAULT true,
            created_at               TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    # ON CONFLICT DO NOTHING: safe against unintended duplicate insertion if
    # this migration is ever re-applied against a database that already has
    # the 'free' row (the UNIQUE(name) constraint is what makes this correct).
    op.execute(
        """
        INSERT INTO plan_tiers (name, quota_minutes_per_period)
        VALUES ('free', 300)
        ON CONFLICT (name) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE plan_tiers")
