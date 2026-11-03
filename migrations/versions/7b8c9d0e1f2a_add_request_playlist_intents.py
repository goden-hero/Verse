"""Retain download-then-append destinations independently of acquisition state."""
from alembic import op
import sqlalchemy as sa

revision = '7b8c9d0e1f2a'
down_revision = '6a7b8c9d0e1f'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('song_request_playlists',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('request_id', sa.String(36), sa.ForeignKey('song_requests.id', ondelete='CASCADE'), nullable=False),
        sa.Column('playlist_id', sa.Integer(), nullable=False),
        sa.Column('playlist_name', sa.String(), nullable=False),
        sa.Column('playlist_created_at', sa.DateTime(), nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('state', sa.String(20), nullable=False), sa.Column('error', sa.String()),
        sa.Column('added_count', sa.Integer(), nullable=False), sa.Column('skipped_count', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False), sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('request_id', 'playlist_id'))
    op.create_index('ix_song_request_playlists_request_id', 'song_request_playlists', ['request_id'])
    op.create_index('ix_song_request_playlists_state', 'song_request_playlists', ['state'])


def downgrade():
    op.drop_table('song_request_playlists')
