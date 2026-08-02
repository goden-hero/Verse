"""PlaylistArtworkService to dynamically generate composite playlist covers using Pillow."""

import io
import logging
from functools import lru_cache
from PIL import Image, ImageDraw, ImageFont
from sqlalchemy.orm import Session
from app.database.models import Playlist

logger = logging.getLogger("music_rec.services.playlist_artwork")

# Cache images in-memory (max 100 dynamic covers)
_COVER_CACHE = {}


class PlaylistArtworkService:
    """Generates composite playlist cover images dynamically without persisting to disk."""

    @staticmethod
    def _create_placeholder_image(size: tuple[int, int], text: str = "Verse", bg_color: tuple[int, int, int] = (20, 10, 35)) -> Image.Image:
        """Helper to create a stylized fallback placeholder image with Verse logo aesthetic."""
        img = Image.new("RGB", size, color=bg_color)
        draw = ImageDraw.Draw(img)
        w, h = size

        # Draw dark purple gradient overlay
        for y in range(h):
            factor = y / float(h)
            r = int(25 + (120 - 25) * factor)
            g = int(10 + (30 - 10) * factor)
            b = int(45 + (190 - 45) * factor)
            draw.line([(0, y), (w, y)], fill=(r, g, b))

        center_x, center_y = w // 2, int(h * 0.45)
        scale = min(w, h) / 500.0

        # Draw Equalizer Bars in center top crotch of V
        bar_x_positions = [-60, -40, -20, 0, 20, 40, 60]
        bar_heights = [30, 60, 90, 120, 90, 60, 30]
        for bx, bh in zip(bar_x_positions, bar_heights):
            x = int(center_x + bx * scale)
            y_top = int(center_y - (bh / 2.0) * scale)
            y_bot = int(center_y + (bh / 2.0) * scale)
            draw.line([(x, y_top), (x, y_bot)], fill=(216, 180, 254), width=max(2, int(6 * scale)))

        # Draw 3D V Shape Lines
        v_width = max(4, int(18 * scale))
        # Left arm
        draw.line(
            [(int(center_x - 120 * scale), int(center_y - 120 * scale)), (center_x, int(center_y + 120 * scale))],
            fill=(192, 132, 252),
            width=v_width,
        )
        # Right arm
        draw.line(
            [(center_x, int(center_y + 120 * scale)), (int(center_x + 120 * scale), int(center_y - 120 * scale))],
            fill=(147, 51, 234),
            width=v_width,
        )

        # Draw Music Note Accent on bottom right crook
        note_cx = int(center_x + 25 * scale)
        note_cy = int(center_y + 80 * scale)
        note_r = max(4, int(16 * scale))
        draw.ellipse(
            [(note_cx - note_r, note_cy - int(note_r * 0.7)), (note_cx + note_r, note_cy + int(note_r * 0.7))],
            fill=(244, 114, 182),
        )

        return img

    @staticmethod
    def _load_song_art(song) -> Image.Image | None:
        """Helper to load PIL Image from song's binary cover_art blob."""
        if song and song.cover_art:
            try:
                return Image.open(io.BytesIO(song.cover_art)).convert("RGB")
            except Exception as e:
                logger.warning("Failed to parse cover_art binary for song ID %s: %s", song.id, e)
        return None

    @staticmethod
    def generate_cover(playlist_id: int, session: Session, target_size: tuple[int, int] = (500, 500)) -> bytes:
        """Generates dynamic playlist cover image binary (JPEG) according to track count rules."""
        playlist = session.get(Playlist, playlist_id)
        if not playlist:
            img = PlaylistArtworkService._create_placeholder_image(target_size, text="Verse")
            output = io.BytesIO()
            img.save(output, format="JPEG", quality=90)
            return output.getvalue()

        # Collect ordered songs
        songs = [ps.song for ps in playlist.songs if ps.song]
        song_ids = tuple(s.id for s in songs)
        cache_key = (playlist_id, len(song_ids), song_ids[:4], target_size)

        if cache_key in _COVER_CACHE:
            return _COVER_CACHE[cache_key]

        W, H = target_size
        canvas = Image.new("RGB", (W, H), color=(20, 20, 25))

        # Extract available images for the first 4 songs
        song_images = []
        for s in songs[:4]:
            art = PlaylistArtworkService._load_song_art(s)
            if not art:
                art = PlaylistArtworkService._create_placeholder_image((W, H), text=s.title or "Verse")
            song_images.append(art)

        num_images = len(song_images)

        if num_images == 0:
            # 0 Songs: Placeholder cover
            canvas = PlaylistArtworkService._create_placeholder_image((W, H), text=playlist.name)

        elif num_images == 1:
            # 1 Song: Full 500x500 artwork
            canvas = song_images[0].resize((W, H), Image.Resampling.LANCZOS)

        elif num_images == 2:
            # 2 Songs: 1x2 split (Song 1 left half, Song 2 right half)
            half_w = W // 2
            img1 = song_images[0].resize((half_w, H), Image.Resampling.LANCZOS)
            img2 = song_images[1].resize((W - half_w, H), Image.Resampling.LANCZOS)

            canvas.paste(img1, (0, 0))
            canvas.paste(img2, (half_w, 0))

            # Draw subtle vertical divider line
            draw = ImageDraw.Draw(canvas)
            draw.line([(half_w, 0), (half_w, H)], fill=(0, 0, 0, 100), width=2)

        elif num_images == 3:
            # 3 Songs: 2x2 grid (1: Top-L, 2: Top-R, 3: Bottom-L, Logo: Bottom-R)
            half_w, half_h = W // 2, H // 2

            img1 = song_images[0].resize((half_w, half_h), Image.Resampling.LANCZOS)
            img2 = song_images[1].resize((W - half_w, half_h), Image.Resampling.LANCZOS)
            img3 = song_images[2].resize((half_w, H - half_h), Image.Resampling.LANCZOS)
            logo_img = PlaylistArtworkService._create_placeholder_image(
                (W - half_w, H - half_h), text="Verse", bg_color=(15, 12, 28)
            )

            canvas.paste(img1, (0, 0))
            canvas.paste(img2, (half_w, 0))
            canvas.paste(img3, (0, half_h))
            canvas.paste(logo_img, (half_w, half_h))

            # Draw divider lines
            draw = ImageDraw.Draw(canvas)
            draw.line([(half_w, 0), (half_w, H)], fill=(0, 0, 0, 100), width=2)
            draw.line([(0, half_h), (W, half_h)], fill=(0, 0, 0, 100), width=2)

        else:
            # 4+ Songs: 2x2 grid of first 4 songs
            half_w, half_h = W // 2, H // 2

            img1 = song_images[0].resize((half_w, half_h), Image.Resampling.LANCZOS)
            img2 = song_images[1].resize((W - half_w, half_h), Image.Resampling.LANCZOS)
            img3 = song_images[2].resize((half_w, H - half_h), Image.Resampling.LANCZOS)
            img4 = song_images[3].resize((W - half_w, H - half_h), Image.Resampling.LANCZOS)

            canvas.paste(img1, (0, 0))
            canvas.paste(img2, (half_w, 0))
            canvas.paste(img3, (0, half_h))
            canvas.paste(img4, (half_w, half_h))

            # Draw divider lines
            draw = ImageDraw.Draw(canvas)
            draw.line([(half_w, 0), (half_w, H)], fill=(0, 0, 0, 100), width=2)
            draw.line([(0, half_h), (W, half_h)], fill=(0, 0, 0, 100), width=2)

        output = io.BytesIO()
        canvas.save(output, format="JPEG", quality=92)
        binary_data = output.getvalue()

        # Cache result
        _COVER_CACHE[cache_key] = binary_data
        return binary_data

    @staticmethod
    def invalidate_cover(playlist_id: int):
        """Invalidates in-memory cover cache for a playlist."""
        keys_to_remove = [k for k in _COVER_CACHE.keys() if k[0] == playlist_id]
        for k in keys_to_remove:
            _COVER_CACHE.pop(k, None)
