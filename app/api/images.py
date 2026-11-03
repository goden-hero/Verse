"""Conditional image responses without changing the stored artwork."""

import hashlib
import io
from functools import lru_cache

from fastapi import HTTPException, Request, Response
from PIL import Image


@lru_cache(maxsize=1)
def default_artwork() -> bytes:
    """Reuse Verse's existing cover design; no stored songs or artwork are changed."""
    from app.services.playlist_artwork import PlaylistArtworkService

    image = PlaylistArtworkService._create_placeholder_image((512, 512))
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


@lru_cache(maxsize=32)
def now_playing_artwork(data: bytes | None) -> tuple[bytes, str]:
    """Return decodable Safari artwork, including a real image for absent/bad covers.

    A small bounded cache avoids decoding on every OS artwork fetch. Keys are the
    content bytes, so a replaced cover cannot keep returning its old image.
    """
    if data:
        try:
            with Image.open(io.BytesIO(data)) as image:
                image.load()
                if image.format in ("JPEG", "PNG"):
                    return data, Image.MIME[image.format]
                # Embedded covers may be formats that Safari cannot display.
                output = io.BytesIO()
                image.convert("RGB").save(output, format="PNG")
                return output.getvalue(), "image/png"
        except (OSError, ValueError, SyntaxError, Image.DecompressionBombError):
            pass
    return default_artwork(), "image/png"


def image_response(data: bytes, request: Request, media_type: str | None = None) -> Response:
    if media_type is None:
        try:
            with Image.open(io.BytesIO(data)) as image:
                media_type = Image.MIME.get(image.format)
        except (OSError, ValueError, SyntaxError, Image.DecompressionBombError):
            raise HTTPException(status_code=404, detail="Invalid artwork")
        if not media_type:
            raise HTTPException(status_code=404, detail="Unsupported artwork")
    etag = '"' + hashlib.sha256(data).hexdigest() + '"'
    headers = {"ETag": etag, "Cache-Control": "private, no-cache"}
    candidates = request.headers.get("if-none-match", "").split(",")
    if any(value.strip().removeprefix("W/") in (etag, "*") for value in candidates):
        return Response(status_code=304, headers=headers)
    return Response(data, media_type=media_type, headers=headers)
