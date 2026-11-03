"""Browser integration contracts and cookie-backed image responses (no live DB)."""
import io
from pathlib import Path
import subprocess

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


@pytest.mark.parametrize("script", ["test_media_session.js", "test_loop_playback.js"])
def test_media_session_browser_contracts(script):
    result = subprocess.run(["node", str(Path(__file__).with_name(script))],
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr


def test_now_playing_images_with_production_cookie_dependencies(tmp_path, monkeypatch):
    from app.api.server import app
    from app.auth.sessions import SessionService, SESSION_COOKIE
    from app.database import connection
    from app.database.models import Base, Song, User
    from app.api.images import default_artwork

    # Keep the actual route dependency and identity middleware, replacing only
    # the database factory, not authorization or image response functions.
    engine = create_engine(f"sqlite:///{tmp_path / 'media.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(connection, "SessionFactory", factory)
    assert not app.dependency_overrides
    originals = {}
    with factory() as db:
        user = db.get(User, 1)
        user.password_hash = "fixture-password-hash"
        for sid, fmt in enumerate(("JPEG", "PNG", "BMP"), start=1):
            output = io.BytesIO()
            Image.new("RGB", (73, 49), (60, 20, 90)).save(output, format=fmt)
            originals[sid] = output.getvalue()
            db.add(Song(id=sid, path=f"/{sid}.mp3", hash=str(sid), title=str(sid), cover_art=output.getvalue()))
        db.add(Song(id=4, path="/4.mp3", hash="4", title="No cover"))
        db.add(Song(id=5, path="/5.mp3", hash="5", title="Bad cover", cover_art=b"not an image"))
        db.commit()
        token = SessionService.create(user, db)

    try:
        with TestClient(app) as client:
            client.cookies.set(SESSION_COOKIE, token)
            assert client.get("/api/v1/auth/me").status_code == 200
            for sid, mime in ((1, "image/jpeg"), (2, "image/png"), (3, "image/png"), (4, "image/png"), (5, "image/png")):
                url = f"/api/v1/songs/{sid}/artwork?fallback=true"
                result = client.get(url)
                assert result.status_code == 200, result.text
                assert result.headers["content-type"] == mime
                assert result.headers["cache-control"] == "private, no-cache"
                with Image.open(io.BytesIO(result.content)) as image:
                    image.load()
                    assert Image.MIME[image.format] == mime
                    assert image.size == ((73, 49) if sid <= 3 else (512, 512))
                if sid <= 2:
                    assert result.content == originals[sid], "Do not transform supported covers"
                else:
                    assert result.content != originals.get(sid)
                cached = client.get(url, headers={"If-None-Match": result.headers["etag"]})
                assert cached.status_code == 304 and not cached.content
            fallback = client.get("/api/v1/artwork/default")
            assert fallback.status_code == 200
            assert fallback.headers["content-type"] == "image/png"
            assert fallback.content == default_artwork()
            # Normal UI artwork keeps the existing missing-cover 404 contract,
            # but PNG covers are no longer incorrectly labelled as JPEG.
            assert client.get("/api/v1/songs/4/artwork").status_code == 404
            assert client.get("/api/v1/songs/5/artwork").status_code == 404
            assert client.get("/api/v1/songs/2/artwork").headers["content-type"] == "image/png"
            with factory() as db:
                db.get(Song, 1).cover_art = originals[2]
                db.commit()
            replaced = client.get("/api/v1/songs/1/artwork?fallback=true")
            assert replaced.content == originals[2] and replaced.headers["content-type"] == "image/png"
            # Image fetches use the existing cookie, without a special bearer URL
            # or modifying/revoking that authenticated session.
            assert client.get("/api/v1/auth/me").status_code == 200
            assert client.cookies.get(SESSION_COOKIE) == token
        assert engine.pool.checkedout() == 0
    finally:
        engine.dispose()
