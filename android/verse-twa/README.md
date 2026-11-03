# Verse Android APK

This is a Bubblewrap 1.27.0 Trusted Web Activity for the existing
**https://verse786.dpdns.org/** deployment. The APK contains the Android launcher,
splash/launcher artwork and browser helper. FastAPI, SQLite, authentication, song
requests, music files and playback remain on the existing web/server stack.

## Release delivered

| Property | Value |
| --- | --- |
| APK | `releases/verse-1.0.0-release.apk` |
| Absolute path on this machine | `/home/pyro/apps/Verse-test/android/verse-twa/releases/verse-1.0.0-release.apk` |
| Application ID | `org.dpdns.verse786.twa` |
| Launcher name | Verse |
| Version name / code | `1.0.0` / `1` |
| Minimum Android | Android 7 / API 24, required by browser helper 2.7.4 |
| Compile / target API | 36 / 36 |
| Launch URL | `https://verse786.dpdns.org/` |
| Display | `standalone`: no browser toolbar after TWA verification; Android system bars remain |
| APK SHA-256 | `9a72cc5d3c6e7d67fa7860eed433fdf6f9eeac398a428e5f5baea57b9139c35d` |
| Certificate SHA-256 | `C9:B2:52:D1:F8:69:0E:C0:29:B1:C3:8F:86:74:6F:4D:4B:3D:D7:89:3B:AF:40:15:D1:DA:98:D8:11:96:A5:99` |

The release APK passed Android `apksigner verify` (v2 and v3), 16 KB zip alignment,
package/version and non-debuggable checks. Its certificate matches the persisted
keystore, `twa-manifest.json`, and the deployed Digital Asset Links statement.
Verification also checks that backend code, databases, music and signing files
are absent from the APK. No Android runtime permissions are requested. The merged
manifest includes AndroidX's app-specific signature receiver permission.

Only share the signed `.apk`; friends do not need an AAB, `.idsig`, build tools,
keystore or password. See [installation instructions](INSTALL.md).

## Website changes and deployment

The live HTML and JavaScript matched this checkout before implementation,
confirming the expected deployment. Added website files are:

- `app/web/manifest.webmanifest`: stable `/` ID, name/short name Verse, `/` start
  URL and scope, standalone display, existing `#080610` theme/background.
- `app/web/icons/verse-{192,512}.png` and `verse-maskable-512.png`: raster exports
  of the existing `favicon.svg`, with opaque backgrounds and mask-safe padding.
- `app/web/mobile-shell.css`: safe-area spacing for the header, navigation,
  player and overlays; scrollable login/register forms at keyboard height.
- `app/web/.well-known/assetlinks.json`: actual release application ID and
  certificate fingerprint.
- `app/web/index.html`: manifest/icon links, theme metadata, `viewport-fit=cover`,
  Chrome's `interactive-widget=resizes-content`, and the mobile stylesheet.

No service worker was added. There is no new offline/precache layer for private
APIs, login responses, streams, artwork or the music library. Existing persistent
HttpOnly session cookies, backend authorization and web Media Session code are
unchanged. TWA uses its selected browser's cookie/storage profile; a login from a
different browser is not necessarily shared.

The existing FastAPI root `StaticFiles` mount serves these files, including the
dot directory, without an authentication gate. **They are already live on this
host; no additional website deployment or service restart is needed for this
release's association.** Anonymous HTTPS checks confirm 200 responses, correct
content types, matching content and no redirects or session-changing cookies.
Cloudflare sometimes adds its analytics beacon to HTML; the verifier permits
only that known addition when comparing the application markup.

For another deployment, publish these files under the same origin. The required
association URL is exactly:

`https://verse786.dpdns.org/.well-known/assetlinks.json`

It must return the JSON directly with status 200 and `application/json`, without
login, a redirect, or reverse-proxy rules blocking dot directories. Keep it
published for future verification. Run from the repository root:

```bash
python3 android/verse-twa/scripts/verify-website.py
```

The report is `releases/website-verification.json`. This proves the public
prerequisites; browser fullscreen verification still needs a real Android launch.
Chrome may retain previous verification results temporarily. A toolbar indicates
unverified association or browser fallback; do not use verification-bypass flags
to treat it as passing. The fallback is Custom Tabs, preserving browser login.

## Rebuild

Prerequisites: Node 22, npm, Python 3.10+, JDK 17, Android command-line tools, the
Android SDK packages below, and network access for the initial dependency fetch.
Exact versions, official Linux download URLs and archive SHA-256 values used here
are recorded in [toolchain.json](toolchain.json). Verify those hashes before
extracting downloaded archives. Gradle's wrapper also verifies its distribution
checksum. Other operating systems can use the equivalent official JDK/SDK.

Install the SDK packages and accept the SDK's license prompt:

```bash
export JAVA_HOME=/path/to/jdk-17
export ANDROID_HOME=/path/to/android-sdk
export PATH="$JAVA_HOME/bin:$ANDROID_HOME/platform-tools:$PATH"
"$ANDROID_HOME/cmdline-tools/19.0/bin/sdkmanager" \
  --sdk_root="$ANDROID_HOME" \
  'platforms;android-36' 'build-tools;36.1.0' 'platform-tools'
```

Restore the existing signing directory described below before building a fresh
checkout. Then:

```bash
cd android/verse-twa
npm ci
npm run release
```

`npm run release` uses the pinned Bubblewrap core generator to regenerate the
checked-in Android project, runs Gradle `assembleRelease`, aligns the unsigned
output, signs with the existing key and verifies the resulting APK. It reads
icons and the web manifest directly from the checked-in website files, so an
unpublished new manifest does not block compilation. The generated Android
resources still reference the real HTTPS deployment.

The generator preserves Bubblewrap's current browser helper version explicitly,
uses Maven Central instead of retired JCenter, and pins Gradle's distribution
checksum. Generated files should be changed through `twa-manifest.json` or
`scripts/generate.cjs`, since regeneration overwrites generated files.

The PNG icons are committed build inputs. To re-export them after editing Verse's
SVG branding, use the project's existing PySide6/Pillow environment from the
repository root, then rebuild:

```bash
.venv/bin/python android/verse-twa/scripts/render-icons.py
```

On this machine the installed temporary toolchain can be used immediately:

```bash
export JAVA_HOME=/tmp/verse-android-toolchain/jdk-17.0.21+9
export ANDROID_HOME=/tmp/verse-android-toolchain/sdk
export GRADLE_USER_HOME=/tmp/verse-gradle-cache
python3 android/verse-twa/scripts/release.py build
```

`/tmp` tools/caches can disappear after reboot; reinstall them when needed. The
release key is persisted under the checkout's `.private/`, outside `/tmp`.
These are repeatable source/build instructions, not a claim that independent
builds will have byte-identical APK hashes (ZIP/build/signing metadata can differ).

To verify an existing APK without rebuilding:

```bash
python3 android/verse-twa/scripts/release.py verify \
  android/verse-twa/releases/verse-1.0.0-release.apk
```

This produces an adjacent `.verification.json` and `.apk.sha256` report. Keep
release artifacts and their reports together when archiving a distribution.

## Signing key and backup

No prior Android project, keystore or deployed association was found before
creating this identity. The existing identity must now be reused for updates.

The persistent signing material on this machine is:

```text
/home/pyro/apps/Verse-test/.private/android-signing/
  verse-release.keystore  # PKCS12, RSA 4096, alias verse-release
  store-password.txt     # shared keystore/key password
```

The directory and its parent have mode `0700`, files `0600`. Git ignores the
private directory, keystores, passwords within that directory, SDK config,
node modules, build outputs and release binaries. Password values are never
placed in tracked files or command arguments. The APK and certificate fingerprint
are public; the private key and password are not.

**Back up both private files before removing this checkout, running an ignored-file
cleanup such as `git clean -x`, or moving machines.** Git is not their backup.
Copy the private directory to an encrypted offline drive or an encrypted archive
and keep a second secure copy. Store the password in your password manager as
well. Protect backups with an independent strong password; never send signing
material along with the APK. A backup has not been copied to an external device
by this task.

Restore to the same relative directory with the same permissions, or set:

```bash
export VERSE_KEYSTORE=/secure/path/verse-release.keystore
export VERSE_KEYSTORE_PASSWORD_FILE=/secure/path/store-password.txt
# Only if the private-key password is in a different file:
export VERSE_KEY_PASSWORD_FILE=/secure/path/key-password.txt
```

Verify a previously distributed APK with `release.py verify` after restoring.
The build refuses a different certificate or mismatching association. The initial
`init-key` command refuses an existing key, password, fingerprint or association;
ordinary rebuilds never create keys. Do not run it for updates. Losing the key
means an installed copy cannot be updated under this identity using these
instructions.

## Version updates

Edit `twa-manifest.json`: increment `appVersionCode` for **every distributed APK**
and set a human-readable `appVersion`, for example code `2`, version `1.0.1`.
Run `npm run release` again. Output becomes `releases/verse-1.0.1-release.apk`.
Keep `packageId`, signing alias and release certificate unchanged. Website-only
changes normally require no APK release; clients receive the hosted application.

## Validation completed and remaining

Validated on 2026-11-03 UTC:

| Check | Result |
| --- | --- |
| Correct existing deployment | Live HTML and JS initially matched repository SHA-256 values |
| Signed release APK, package/version, alignment | Passed; non-debuggable, one signer, v2/v3 signatures |
| Release certificate association | APK, keystore, TWA config and public assetlinks match |
| Public PWA/association assets | HTTPS 200, anonymous, no redirects; live content verified |
| Login/session, playlist/request and Media Session regressions | 50 pytest tests passed using isolated databases/fixtures |
| Search, requests, playlist actions and playback continuity | Existing offscreen Chromium browser probes passed at 1440 and 390 px; APIs/audio simulated |
| Mobile layout | Chromium 140 passed 390×844, 390×420, 844×390 and 320×568; login/register reachability and overflow; mobile safe-area spacing/search checks below 768 px |
| Physical keyboard/IME | Not tested; short viewport resizing checks are a proxy, not Android keyboard tests |
| Android install/launch and browser fullscreen | Pending device test |
| Real Android login persistence, search, requests and playlists | Pending device test |
| Real audio, screen-off playback and automatic transitions | Pending device test |
| Metadata/artwork, notification/lock-screen media controls | Web contracts passed; Android presentation/actions pending |
| Android Back and temporary connectivity loss | Pending device test; fixture network-error/retry behavior passed |

`adb devices -l` found no connected devices. No Android emulator was available;
the host exposes `/dev/kvm` but this account cannot access it. No emulator
installation, Android launch, on-device fullscreen or background playback pass
is claimed. Existing web Media Session integration has been preserved.

Repeat the completed application/browser checks from the repository root:

```bash
.venv/bin/python -m pytest tests/test_auth_sessions.py tests/test_auth_api_routes.py \
  tests/test_media_session.py tests/test_catalogue_workflow.py \
  tests/test_manual_playlists.py tests/test_playlist_api_routes.py -q
.venv/bin/python tests/browser_manual_playlist_probe.py --discovery
.venv/bin/python tests/browser_manual_playlist_probe.py
.venv/bin/python android/verse-twa/scripts/check-mobile.py
```

The browser probes use offscreen Qt Chromium with network access blocked and
synthetic APIs/audio. Their successful results do not establish Android hardware,
OS media-control or background-playback behavior.

Before wider distribution, run this sequence on at least one Android phone:

1. Record model, Android version, browser/version and default browser. Install
   the release with `adb install -r releases/verse-1.0.0-release.apk`, or follow
   [the friend guide](INSTALL.md). Confirm launcher name/icon and launch appearance.
2. Launch without any verification bypass. Confirm no browser toolbar; system
   status/navigation bars are expected with standalone display. Use `adb logcat`
   to inspect `TWAProviderPicker`, `OriginVerifier` and `cr_OriginVerifier` if needed.
3. Log in, close/reopen Verse and relaunch after process removal. Check the login
   remains valid; log out and confirm it is revoked. Test registration/login
   with the keyboard open in portrait and landscape.
4. Search local music and the catalogue, request a song, check progress/retry,
   create a playlist and add/play tracks. Use your test account and remove test
   playlists afterwards. Requests require the existing server worker/providers.
5. Tap Play, confirm audible playback, then press Home and turn the screen off.
   Let at least two complete tracks transition. Repeat across Wi-Fi/mobile data
   and over an extended screen-off period; record battery saver behavior.
6. Confirm title, artist, album and cover artwork in the notification and lock
   screen. Test play/pause, next/previous and seek where the browser exposes them.
   Android/browser layouts may omit supported actions; not every Media Session
   handler becomes a visible button.
7. Test Android Back with search, song actions, playlist dialogs and full player
   open, then at the root. The existing SPA does not push history for every
   internal screen/overlay; Back can leave the TWA, and Close/Minimize controls
   are available. No native Back interception was added.
8. Briefly disable connectivity during playback and search, then restore it.
   Check buffered audio behavior, visible retry/errors, subsequent playback and
   session retention. Retry interrupted actions without duplicate submissions.

TWA is browser-rendered web content, not a native playback service. Android can
stop a browser process; autoplay policies can reject a transition, and battery
management, lost connectivity and browser behavior can interrupt playback.
Packaging alone does not guarantee background playback. There is no offline
library in this APK. References: [Chrome TWA overview](https://developer.chrome.com/docs/android/trusted-web-activity),
[Bubblewrap documentation](https://github.com/GoogleChromeLabs/bubblewrap/blob/main/packages/cli/README.md),
[Digital Asset Links](https://developers.google.com/digital-asset-links/v1/getting-started).
