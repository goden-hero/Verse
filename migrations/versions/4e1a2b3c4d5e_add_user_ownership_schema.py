"""Add user infrastructure and ownership refactor.

Revision ID: 4e1a2b3c4d5e
Revises: 3f2a1b6c9d8e
Create Date: 2026-08-02
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "4e1a2b3c4d5e"
down_revision: Union[str, Sequence[str], None] = "3f2a1b6c9d8e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create users table, migrate playlists ownership, create user-owned tables."""
    # 1. Create users table
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("username", sa.String(), nullable=False),
        sa.Column("password_hash", sa.String(), nullable=True),
        sa.Column("display_name", sa.String(), nullable=True),
        sa.Column("avatar_path", sa.String(), nullable=True),
        sa.Column(
            "created_at",
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
        sa.Column("last_login_at", sa.DateTime(), nullable=True),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_username", "users", ["username"], unique=True)

    # 2. Insert default system user for existing playlists migration
    bind = op.get_bind()
    users_table = sa.table(
        "users",
        sa.column("id", sa.Integer),
        sa.column("username", sa.String),
        sa.column("password_hash", sa.String),
        sa.column("display_name", sa.String),
        sa.column("is_active", sa.Boolean),
    )
    bind.execute(
        users_table.insert().values(
            username="Verse Owner",
            password_hash=None,
            display_name="Verse Owner",
            is_active=True,
        )
    )

    # 3. Add user_id column to playlists and assign existing playlists to default user (id=1)
    op.add_column(
        "playlists",
        sa.Column(
            "user_id",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )
    op.create_index("ix_playlists_user_id", "playlists", ["user_id"])

    # 4. Create liked_songs table
    op.create_table(
        "liked_songs",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("song_id", sa.Integer(), nullable=False),
        sa.Column(
            "liked_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["song_id"], ["songs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "song_id"),
    )
    op.create_index("ix_liked_songs_user_id", "liked_songs", ["user_id"])

    # 5. Create playback_history table
    op.create_table(
        "playback_history",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("song_id", sa.Integer(), nullable=False),
        sa.Column(
            "played_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("duration_played", sa.Float(), nullable=False, server_default="0.0"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["song_id"], ["songs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_playback_history_user_id", "playback_history", ["user_id"])
    op.create_index("ix_playback_history_song_id", "playback_history", ["song_id"])
    op.create_index("ix_playback_history_played_at", "playback_history", ["played_at"])

    # 6. Create queue_items table
    op.create_table(
        "queue_items",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("song_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column(
            "added_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["song_id"], ["songs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "position", name="uq_queue_items_user_position"),
    )
    op.create_index("ix_queue_items_user_id", "queue_items", ["user_id"])

    # 7. Create user_preferences table
    op.create_table(
        "user_preferences",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("theme", sa.String(), nullable=True, server_default="dark"),
        sa.Column("accent_color", sa.String(), nullable=True),
        sa.Column("volume", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("crossfade", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("equalizer", sa.String(), nullable=True),
        sa.Column(
            "created_at",
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
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )


def downgrade() -> None:
    """Revert user infrastructure and ownership refactor tables and columns."""
    op.drop_table("user_preferences")

    op.drop_index("ix_queue_items_user_id", table_name="queue_items")
    op.drop_table("queue_items")

    op.drop_index("ix_playback_history_played_at", table_name="playback_history")
    op.drop_index("ix_playback_history_song_id", table_name="playback_history")
    op.drop_index("ix_playback_history_user_id", table_name="playback_history")
    op.drop_table("playback_history")

    op.drop_index("ix_liked_songs_user_id", table_name="liked_songs")
    op.drop_table("liked_songs")

    with op.batch_alter_table("playlists") as batch_op:
        batch_op.drop_index("ix_playlists_user_id")
        batch_op.drop_column("user_id")

    op.drop_index("ix_users_username", table_name="users")
    op.drop_table("users")
