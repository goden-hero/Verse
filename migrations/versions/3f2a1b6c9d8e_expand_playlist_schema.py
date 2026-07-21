"""Expand playlist storage for metadata and playback sessions.

Revision ID: 3f2a1b6c9d8e
Revises: 82fcd3e04761
Create Date: 2026-07-21
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "3f2a1b6c9d8e"
down_revision: Union[str, Sequence[str], None] = "82fcd3e04761"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add the columns used by the playlist API to existing installations."""
    with op.batch_alter_table("playlists") as batch_op:
        batch_op.add_column(sa.Column("description", sa.String(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "updated_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            )
        )
        batch_op.add_column(sa.Column("seed_type", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("seed_song_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("generator_version", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("llm_model", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("created_from", sa.String(), nullable=True))
        batch_op.create_foreign_key(
            "fk_playlists_seed_song_id_songs",
            "songs",
            ["seed_song_id"],
            ["id"],
            ondelete="SET NULL",
        )

    op.create_table(
        "playback_sessions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("playlist_id", sa.Integer(), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("current_song_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("current_position", sa.Float(), nullable=False, server_default="0"),
        sa.Column("completed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.ForeignKeyConstraint(["playlist_id"], ["playlists.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_playback_sessions_playlist_id", "playback_sessions", ["playlist_id"])


def downgrade() -> None:
    op.drop_index("ix_playback_sessions_playlist_id", table_name="playback_sessions")
    op.drop_table("playback_sessions")

    with op.batch_alter_table("playlists") as batch_op:
        batch_op.drop_constraint("fk_playlists_seed_song_id_songs", type_="foreignkey")
        batch_op.drop_column("created_from")
        batch_op.drop_column("llm_model")
        batch_op.drop_column("generator_version")
        batch_op.drop_column("seed_song_id")
        batch_op.drop_column("seed_type")
        batch_op.drop_column("updated_at")
        batch_op.drop_column("description")
