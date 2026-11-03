#!/usr/bin/env python3
"""Check deployed TWA assets anonymously, over HTTPS, rejecting redirects."""
import hashlib
import json
from pathlib import Path
import re
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT.parents[1] / "app/web"
config = json.loads((ROOT / "twa-manifest.json").read_text())
origin = "https://" + config["host"]


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise HTTPError(req.full_url, code, "Redirect is not allowed for TWA verification", headers, fp)


opener = build_opener(NoRedirect)
results = []
for name, mime in [(".well-known/assetlinks.json", "application/json"),
                   ("manifest.webmanifest", "application/manifest+json"),
                   ("icons/verse-192.png", "image/png"),
                   ("icons/verse-512.png", "image/png"),
                   ("icons/verse-maskable-512.png", "image/png"),
                   ("mobile-shell.css", "text/css"), ("index.html", "text/html")]:
    with opener.open(Request(origin + "/" + name, headers={"User-Agent": "Verse-release-verification/1"}), timeout=30) as response:
        content = response.read()
        assert response.status == 200
        assert response.headers.get_content_type() == mime, (name, response.headers)
        # Cloudflare may append its analytics beacon to HTML depending on the
        # requesting client. All application markup and every other file must match.
        normalized = re.sub(rb'<script\b[^>]*\bsrc="https://static\.cloudflareinsights\.com/beacon\.min\.js/[^"]+"[^>]*></script>\n?', b'', content) if name == "index.html" else content
        assert normalized == (WEB / name).read_bytes(), f"Deploy current {name} before distribution"
        assert "set-cookie" not in response.headers, "Public verification assets must not alter login sessions"
        results.append({"url": response.url, "status": 200, "contentType": mime,
                        "sha256": hashlib.sha256(content).hexdigest(), "anonymous": True, "redirects": False,
                        "edgeAnalyticsNormalized": normalized != content})

association = json.loads((WEB / ".well-known/assetlinks.json").read_text())
assert association[0]["target"]["package_name"] == config["packageId"]
assert association[0]["target"]["sha256_cert_fingerprints"] == [config["fingerprints"][0]["value"]]
output = ROOT / "releases/website-verification.json"
output.parent.mkdir(exist_ok=True)
output.write_text(json.dumps({"origin": origin, "checks": results}, indent=2) + "\n")
print(f"PASS: {len(results)} deployed files match this checkout; HTTPS 200, no authentication or redirects.")
print(f"Report: {output}")
