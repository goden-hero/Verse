"""Persistent discovery cache, rate budget, source identities and request queue."""
from alembic import op
import sqlalchemy as sa

revision = "6a7b8c9d0e1f"
down_revision = "5f2b3c4d6e7f"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("song_sources",
        sa.Column("identity_key", sa.String(180), primary_key=True),
        sa.Column("song_id", sa.Integer(), sa.ForeignKey("songs.id", ondelete="CASCADE"), nullable=False))
    op.create_index("ix_song_sources_song_id", "song_sources", ["song_id"])
    op.create_table("song_requests",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("identity_key", sa.String(180), unique=True, nullable=False),
        sa.Column("metadata_json", sa.String(), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("error", sa.String()),
        sa.Column("resolved_json", sa.String()),
        sa.Column("downloaded_path", sa.String()),
        sa.Column("song_id", sa.Integer(), sa.ForeignKey("songs.id", ondelete="SET NULL")))
    op.create_index("ix_song_requests_state", "song_requests", ["state"])
    op.create_table("discovery_cache", sa.Column("key", sa.String(240), primary_key=True),
        sa.Column("payload", sa.String(), nullable=False), sa.Column("expires_at", sa.Float(), nullable=False))
    op.create_index("ix_discovery_cache_expires_at", "discovery_cache", ["expires_at"])
    op.create_table("catalogue_budgets", sa.Column("provider", sa.String(30), primary_key=True),
        sa.Column("next_allowed_at", sa.Float(), nullable=False))


def downgrade():
    for table in ("catalogue_budgets", "discovery_cache", "song_requests", "song_sources"):
        op.drop_table(table)
