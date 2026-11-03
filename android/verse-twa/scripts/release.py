#!/usr/bin/env python3
"""Build, sign and verify Verse. Passwords are read from private files, never argv."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
PRIVATE = REPO / ".private/android-signing"
CONFIG = json.loads((ROOT / "twa-manifest.json").read_text())
ASSETLINKS = REPO / "app/web/.well-known/assetlinks.json"
KEYSTORE = Path(os.environ.get("VERSE_KEYSTORE", str(ROOT / CONFIG["signingKey"]["path"]))).resolve()
STORE_PASSWORD = Path(os.environ.get("VERSE_KEYSTORE_PASSWORD_FILE", str(PRIVATE / "store-password.txt"))).resolve()
KEY_PASSWORD = Path(os.environ.get("VERSE_KEY_PASSWORD_FILE", str(STORE_PASSWORD))).resolve()
ALIAS = CONFIG["signingKey"]["alias"]
BUILD_TOOLS = "36.1.0"
# Android's apksigner launcher uses PATH even when Gradle honors JAVA_HOME.
if os.environ.get("JAVA_HOME"):
    os.environ["PATH"] = str(Path(os.environ["JAVA_HOME"]) / "bin") + os.pathsep + os.environ["PATH"]


def run(args, capture=False, **kwargs):
    return subprocess.run([str(a) for a in args], check=True, text=True,
                          stdout=subprocess.PIPE if capture else None, **kwargs)


def tool(name):
    if name == "keytool":
        java = os.environ.get("JAVA_HOME")
        candidate = Path(java) / "bin/keytool" if java else Path(shutil.which(name) or name)
    else:
        sdk = os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT")
        if not sdk:
            raise SystemExit("Set ANDROID_HOME to your Android SDK directory.")
        candidate = Path(sdk) / "build-tools" / BUILD_TOOLS / name
    if not candidate.is_file():
        raise SystemExit(f"Missing tool: {candidate}")
    return candidate


def require_key():
    for file in (KEYSTORE, STORE_PASSWORD, KEY_PASSWORD):
        if not file.is_file():
            raise SystemExit(f"Missing signing material: {file}. Restore your backup; builds never create a replacement key.")
        if file.stat().st_mode & 0o077:
            raise SystemExit(f"Signing file must be private (chmod 600): {file}")


def key_fingerprint():
    require_key()
    certificate = subprocess.run([
        str(tool("keytool")), "-exportcert", "-keystore", str(KEYSTORE), "-alias", ALIAS,
        "-storepass:file", str(STORE_PASSWORD),
    ], check=True, stdout=subprocess.PIPE).stdout
    return ":".join(re.findall("..", hashlib.sha256(certificate).hexdigest().upper()))


def association(fingerprint):
    return [{"relation": ["delegate_permission/common.handle_all_urls"], "target": {
        "namespace": "android_app", "package_name": CONFIG["packageId"],
        "sha256_cert_fingerprints": [fingerprint],
    }}]


def verify_association(fingerprint):
    actual = json.loads(ASSETLINKS.read_text())
    assert actual == association(fingerprint), "assetlinks.json does not match this release identity"
    assert any(f["value"] == fingerprint for f in CONFIG["fingerprints"]), "TWA fingerprint does not match release key"


def init_key():
    # Never replace an identity or mint a new key after an association is committed.
    if KEYSTORE.exists() or STORE_PASSWORD.exists() or ASSETLINKS.exists() or CONFIG["fingerprints"]:
        raise SystemExit("Signing identity already exists. Restore/reuse it; init-key will not replace it.")
    if KEYSTORE != (PRIVATE / "verse-release.keystore").resolve():
        raise SystemExit("init-key only creates the default private key; configure external keys separately.")
    PRIVATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    PRIVATE.chmod(0o700)
    with STORE_PASSWORD.open("x") as output:
        os.chmod(STORE_PASSWORD, 0o600)
        output.write(secrets.token_urlsafe(48) + "\n")
    run([tool("keytool"), "-genkeypair", "-noprompt", "-storetype", "PKCS12",
         "-keystore", KEYSTORE, "-alias", ALIAS, "-keyalg", "RSA", "-keysize", "4096",
         "-sigalg", "SHA256withRSA", "-validity", "10000", "-dname", "CN=Verse",
         "-storepass:file", STORE_PASSWORD, "-keypass:file", KEY_PASSWORD])
    KEYSTORE.chmod(0o600)
    print(f"Release key preserved at {KEYSTORE}. Back up this directory securely.")


def associate():
    fingerprint = key_fingerprint()
    if ASSETLINKS.exists() and json.loads(ASSETLINKS.read_text()) != association(fingerprint):
        raise SystemExit("Existing website association differs; refusing to replace a signing identity.")
    if CONFIG["fingerprints"] and not any(f["value"] == fingerprint for f in CONFIG["fingerprints"]):
        raise SystemExit("Existing Android fingerprint differs; refusing to replace it.")
    ASSETLINKS.parent.mkdir(parents=True, exist_ok=True)
    ASSETLINKS.write_text(json.dumps(association(fingerprint), indent=2) + "\n")
    CONFIG["fingerprints"] = [{"name": "Verse direct distribution release", "value": fingerprint}]
    (ROOT / "twa-manifest.json").write_text(json.dumps(CONFIG, indent=2) + "\n")
    print(f"Release certificate SHA-256: {fingerprint}")


def verify(apk):
    fingerprint = key_fingerprint()
    verify_association(fingerprint)
    result = run([tool("apksigner"), "verify", "--verbose", "--print-certs", apk], capture=True).stdout
    match = re.search(r"Signer #1 certificate SHA-256 digest: ([0-9a-f]+)", result)
    assert match, "APK signer not found"
    apk_fingerprint = ":".join(re.findall("..", match[1].upper()))
    assert apk_fingerprint == fingerprint, "APK signer differs from website and keystore"
    assert "Signer #2" not in result, "Unexpected additional APK signer"
    badging = run([tool("aapt"), "dump", "badging", apk], capture=True).stdout
    package = re.search(r"package: name='([^']+)' versionCode='([^']+)' versionName='([^']+)'", badging)
    assert package and package.groups() == (CONFIG["packageId"], str(CONFIG["appVersionCode"]), CONFIG["appVersion"]), "Unexpected APK identity/version"
    assert "application-debuggable" not in badging, "APK must be a release build"
    with zipfile.ZipFile(apk) as archive:
        forbidden = (".py", ".pyc", ".db", ".sqlite", ".keystore", ".jks", ".mp3", ".flac", ".m4a", ".ogg", ".wav")
        assert not any(name.lower().endswith(forbidden) for name in archive.namelist()), "APK contains backend, music, database or signing files"
    permissions = re.findall(r"uses-permission(?:-[^:]+)?: name='([^']+)'", badging)
    # Browser handles networking, audio and media notifications. No runtime permissions.
    allowed = {"android.permission.INTERNET", "android.permission.ACCESS_NETWORK_STATE"}
    unexpected = set(permissions) - allowed
    # AndroidX may add its own signature-only receiver permission; never grant it to other apps.
    unexpected.discard(CONFIG["packageId"] + ".DYNAMIC_RECEIVER_NOT_EXPORTED_PERMISSION")
    assert not unexpected, f"Unexpected permissions: {sorted(unexpected)}"
    run([tool("zipalign"), "-c", "-P", "16", "4", apk], capture=True)
    report = {"applicationId": CONFIG["packageId"], "versionName": CONFIG["appVersion"],
              "versionCode": CONFIG["appVersionCode"], "apk": apk.name,
              "apkSha256": hashlib.sha256(apk.read_bytes()).hexdigest(),
              "certificateSha256": fingerprint, "permissions": permissions,
              "signatureVerification": result.strip().splitlines(), "debuggable": False,
              "backendMusicAndSigningFilesAbsent": True}
    apk.with_suffix(".verification.json").write_text(json.dumps(report, indent=2) + "\n")
    apk.with_suffix(".apk.sha256").write_text(f"{report['apkSha256']}  {apk.name}\n")
    print(json.dumps(report, indent=2))


def build():
    verify_association(key_fingerprint())
    run(["node", ROOT / "scripts/generate.cjs"], cwd=ROOT)
    env = os.environ.copy()
    env.setdefault("GRADLE_USER_HOME", str(ROOT / ".gradle-user-home"))
    run([ROOT / "gradlew", "--no-daemon", "--max-workers=2", "assembleRelease"], cwd=ROOT, env=env)
    releases = ROOT / "releases"
    releases.mkdir(exist_ok=True)
    apk = releases / f"verse-{CONFIG['appVersion']}-release.apk"
    aligned = releases / "aligned-unsigned.apk"
    run([tool("zipalign"), "-f", "-P", "16", "4", ROOT / "app/build/outputs/apk/release/app-release-unsigned.apk", aligned])
    password_args = ["--ks-pass", f"file:{STORE_PASSWORD}"]
    # PKCS12 uses the same key/store password. apksigner reuses the store
    # password by default; giving the same file twice consumes a second line.
    if KEY_PASSWORD != STORE_PASSWORD:
        password_args += ["--key-pass", f"file:{KEY_PASSWORD}"]
    run([tool("apksigner"), "sign", "--ks", KEYSTORE, "--ks-key-alias", ALIAS,
         *password_args, "--out", apk, aligned])
    aligned.unlink()
    verify(apk)
    print(f"Share this signed release APK: {apk}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["init-key", "associate", "build", "verify"])
    parser.add_argument("apk", nargs="?", type=Path)
    args = parser.parse_args()
    if args.command == "verify":
        if not args.apk:
            parser.error("verify requires an APK path")
        verify(args.apk.resolve())
    else:
        {"init-key": init_key, "associate": associate, "build": build}[args.command]()
