"""users_and_auth

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-10

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE users (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            email               CITEXT UNIQUE NOT NULL,
            password_hash       TEXT NOT NULL,
            email_verified_at   TIMESTAMPTZ,
            plan_tier_id        UUID NOT NULL REFERENCES plan_tiers(id) ON DELETE RESTRICT,
            quota_minutes_used  NUMERIC(10,2) NOT NULL DEFAULT 0 CHECK (quota_minutes_used >= 0),
            quota_period_start  DATE NOT NULL DEFAULT date_trunc('month', now() AT TIME ZONE 'UTC')::date,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )

    op.execute(
        """
        CREATE TABLE refresh_tokens (
            id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id              UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            family_id            UUID NOT NULL,
            token_hash           TEXT NOT NULL,
            expires_at           TIMESTAMPTZ NOT NULL,
            revoked_at           TIMESTAMPTZ,
            replaced_by_token_id UUID REFERENCES refresh_tokens(id) ON DELETE SET NULL,
            grace_ciphertext     BYTEA,
            grace_expires_at     TIMESTAMPTZ,
            created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX idx_refresh_tokens_user ON refresh_tokens(user_id)")
    op.execute("CREATE INDEX idx_refresh_tokens_hash ON refresh_tokens(token_hash)")
    op.execute("CREATE INDEX idx_refresh_tokens_family ON refresh_tokens(family_id)")

    op.execute(
        """
        CREATE TABLE email_verification_tokens (
            id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id      UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            token_hash   TEXT NOT NULL,
            expires_at   TIMESTAMPTZ NOT NULL,
            consumed_at  TIMESTAMPTZ,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX idx_email_verif_user ON email_verification_tokens(user_id)")

    op.execute(
        """
        CREATE TABLE password_reset_tokens (
            id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id      UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            token_hash   TEXT NOT NULL,
            expires_at   TIMESTAMPTZ NOT NULL,
            consumed_at  TIMESTAMPTZ,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX idx_pw_reset_user ON password_reset_tokens(user_id)")


def downgrade() -> None:
    op.execute("DROP TABLE password_reset_tokens")
    op.execute("DROP TABLE email_verification_tokens")
    op.execute("DROP TABLE refresh_tokens")
    op.execute("DROP TABLE users")
