#!/usr/bin/env python3
"""Rasterize Verse's existing SVG branding; no new artwork or network inputs."""
import os
from pathlib import Path
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--no-sandbox --disable-gpu --disable-dev-shm-usage")
from PySide6.QtCore import QTimer, QUrl
from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineWidgets import QWebEngineView
from PIL import Image

web = Path(__file__).resolve().parents[3] / "app/web"
icons = web / "icons"
icons.mkdir(exist_ok=True)
app = QApplication(sys.argv)
view = QWebEngineView()
view.resize(1024, 1024)
svg = (web / "favicon.svg").read_text()
view.setHtml('<html><body style="margin:0;background:#080610;overflow:hidden">' + svg + '</body></html>', QUrl.fromLocalFile(str(web) + '/'))

def save():
    image_path = icons / "verse-1024.png"
    view.grab().save(str(image_path))
    with Image.open(image_path) as original:
        image = original.convert("RGB")
        for size in (192, 512):
            image.resize((size, size), Image.Resampling.LANCZOS).save(icons / f"verse-{size}.png")
        # Keep the original V inside the central mask-safe circle (80% diameter).
        maskable = Image.new("RGB", (512, 512), "#080610")
        maskable.paste(image.resize((410, 410), Image.Resampling.LANCZOS), (51, 51))
        maskable.save(icons / "verse-maskable-512.png")
    image_path.unlink()
    app.quit()

view.loadFinished.connect(lambda ok: QTimer.singleShot(600, save) if ok else app.exit(1))
view.show()
QTimer.singleShot(15000, lambda: app.exit(1))
sys.exit(app.exec())
