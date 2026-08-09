# FileShare — Fix & Rebuild Progress

Tracking doc for the full audit fix-up. Updated as work lands. Legend: ⬜ not started · 🔄 in progress · ✅ done · ⏭️ skipped (with reason)

_Last updated: 2026-07-15_

## 1. Security fixes

- ✅ Escape all HTML interpolation (usernames, filenames, paths) to close XSS holes — `main.py` directory/admin/active-users/shared-paths/rate-limits pages
- ✅ Move session token out of the URL into an `HttpOnly`, `SameSite=Strict` cookie (stop leaking tokens via history/Referer/logs); added real `/logout` route
- ✅ Add CSRF protection on state-changing admin actions — SameSite=Strict cookie + same-origin Referer/Origin check on all mutating admin routes
- ✅ Add optional TLS (self-signed cert auto-generated via the `cryptography` package if installed, or `--cert`/`--key` to bring your own); `Secure` cookie flag turns on automatically when TLS is active
- ✅ Fix admin password lifecycle: only generated once now, persisted to a 0600 `admin_password.txt` recovery file next to the DB, recovered from that file on restart instead of silently rotating; added `--reset-admin-password` CLI flag; removed the dangling reference to a `FileShare_Admin_Password.txt` that was never written
- ✅ Remove/neutralize the remote kill-switch in `remote_control.py` (undisclosed phone-home + forced `sys.exit()` based on GitHub release data) — replaced with a passive, non-fatal update notice; opt-out via `FILESHARE_DISABLE_UPDATE_CHECK=1`
- ✅ Fix duplicate `content_types['ogg']` / duplicate ext-list bug causing Ogg video to be served as `audio/ogg`
- ✅ Reviewed in-memory rate limiting - behavior is as documented (5 attempts / 2 min window, in-memory only); no change made
- ✅ (bonus) Fixed stdout buffering so startup banner/admin password isn't lost when output is redirected (headless/service runs)
- ✅ (bonus) Added `--port`/`--host` CLI flags (README already documented `--port` but it never existed)
- ✅ (bonus) Fixed a real bug found while smoke-testing: login error messages ("wrong password", "pending approval", rate-limit notices) were computed correctly but never actually rendered - `send_auth_page` replaced a placeholder string that didn't exist in `login.html`. Added a real `{error_message}` placeholder and verified all three message types now render.

## 2. Functional gaps

- ✅ Implement real file upload (multipart/form-data) from mobile/browser into a shared, writable folder — verified end-to-end (login → share folder → upload → no-clobber rename → path-traversal-safe filename)
- ✅ Wire upload UI into `directory.html` for folders the user has access to
- ✅ (bonus) `config.py` at repo root was dead code — `main.py` imported a nonexistent `app.config` and silently used an inline fallback; fixed the import order so real config values (and the new `MAX_UPLOAD_SIZE_MB`) actually take effect

## 3. Cross-platform fixes

- ✅ Replace POSIX-only `/`-rooted filesystem browsing with a platform-aware root: enumerate drives on Windows (`C:\`, `D:\`, …) instead of `os.listdir('/')`; parent-link (`..`) logic now returns to the virtual root from a drive root instead of looping. Reasoned through carefully but **not executed on real Windows** - please validate there.
- ✅ Audited URL-decoded-path vs OS-separator handling: routes split on literal `/` (correct - HTTP paths always use `/` regardless of OS), and OS calls (`os.path.*`) receive whatever separator style the client sent back verbatim, which Windows accepts for both `/` and `\`. No changes needed beyond the root/drive fix above.
- ✅ `get_local_ip`/socket binding use stdlib `socket`/`http.server` with no OS-specific calls - should behave the same everywhere. File streaming (range requests, chunked reads) is pure byte I/O, no platform dependency. Not independently re-verified on Windows/Linux VMs - flagging as reasoned-through rather than executed there.

## 4. Packaging / distribution

- ✅ Windows: `windows/build-exe.py` (PyInstaller) + `windows/README.md` - **written but not run on real Windows** (PyInstaller can't cross-compile from macOS) - please validate before relying on it
- ✅ macOS: `macos/build-app.py` (PyInstaller) + `macos/README.md` - built and functionally verified on this machine: control panel serves HTTP 200, Start Sharing brings up the file server, admin password banner prints correctly. Note: cold start takes 5-15s (bundled `cryptography`/OpenSSL init) - not a hang.
- ✅ Updated root `README.md`: correct entry point (`main.py`, not the nonexistent `file_server.py`), real CLI flags, TLS behavior, upload feature, packaging status table per platform

## 5. Verification

- ✅ Manual smoke test: start server (HTTPS), login as admin, share a folder, upload a file (path-traversal-safe filename, no-clobber rename), browse and see it listed
- ✅ Manual smoke test: register a user → blocked pending approval (error message now actually renders - see bug fix above) → admin approves → user logs in → sees "no shared content" until admin shares something → confirmed non-admin can't reach `/admin/*` mutating routes
- ✅ Manual smoke test: macOS packaged `.app` boots, control panel responds, starts the underlying file server
- ✅ `python3 -m py_compile` clean on every touched `.py` file (`main.py`, `control_panel.py`, `config.py`, `remote_control.py`, `macos/build-app.py`, `windows/build-exe.py`)
- ✅ Manual smoke test: video range-request streaming (`206 Partial Content`, correct `Content-Range`/`Content-Length`) and confirmed `.ogg` now serves as `audio/ogg` per the dict-key bugfix

## 6. Repo cleanup (2026-07-15)

- ✅ Removed junk/clutter: `.DS_Store`, `__pycache__/` dirs, empty unused `nodejs/` and `test_folder/` dirs, stale duplicate root-level `releases/` folder, `linux/releases/` (regenerable build output), duplicate root `GITHUB-RELEASE.md` (kept the copy under `linux/`)
- ✅ Removed `users.db` (real local admin/user data) and `venv/` (this session's test environment) — both confirmed with the project owner first since they weren't "extra project files," they were real state
- ✅ Rewrote `README.md` end to end for clarity, including direct answers on large-file transfer capability and how much to trust this project

## 7. Chunked/resumable upload subsystem + security fix-up (2026-07-17)

Large uncommitted diff had landed on top of section 1-6 (a full chunked/resumable upload feature: `/api/upload/create`, `/api/upload/<id>` PATCH/HEAD/DELETE, `/api/upload/batch/create`, `/api/transfers`, disk-space reservation, crash-resume via the `uploads` DB table) that this doc hadn't caught up to. Audited it plus the surrounding auth/access-control code end to end:

- ✅ Fixed real path-traversal bug in `is_path_accessible` (`main.py`): used `path.startswith(shared_path)` (string prefix), so sharing `/data/project` also silently granted access to `/data/project-secret`. Now segment-aware.
- ✅ Fixed real authz-bypass in `serve_file`/`serve_download` (`main.py`): both resolved "who is making this request" by scanning `VALID_TOKENS`/`ACTIVE_USERS` for the first matching entry instead of resolving the actual caller's cookie — under concurrent sessions this could evaluate access as the wrong user. Now use `check_token_auth()` like every other route.
- ✅ Fixed `serve_raw` (`main.py`) having **no access check at all** — any logged-in user could read the raw bytes of any file on the filesystem the process could reach, entirely bypassing shared-path restrictions. Added the same check `serve_file`/`serve_download` use.
- ✅ Fixed `/download/` and `/raw/` routes dropping the leading `/` when stripping their prefix (`self.path[10:]` / `self.path[5:]`), so the resulting path never matched a stored shared path and access checks silently failed even for legitimately shared files. Restored the leading slash.
- ✅ Fixed `control_panel.py` hardcoding port `8000` instead of `Config.DEFAULT_PORT`/`Config.HOST`, diverging from `main.py`'s own CLI.
- ✅ Verified the chunked upload subsystem itself (offset checks, per-upload locking, byte reservation/release, crash-resume, stale-upload sweep) is sound — no changes needed there.
- ✅ Smoke-tested end-to-end: shared-folder access, sibling-folder-name traversal attempt (blocked), unauthenticated access (blocked), and a full multi-chunk upload landing correctly on disk.
- ⏭️ Left the old single-shot memory-buffered upload form in place alongside the new chunked/bulk uploader — reasonable UX split (quick single small file vs. large/folder transfers), bounded by `MAX_UPLOAD_SIZE_MB`, not a bug.
- ⏭️ Minor, non-correctness-affecting: `rebuild_transfers_from_db` resets an in-progress upload's staleness clock on every restart, so a frequently-restarted server delays (never incorrectly skips) stale-upload cleanup. Not fixed — low severity, no data risk.

## 8. Release-readiness audit: macOS + Linux (2026-07-17)

Checked whether the app is actually ready for a GitHub release on macOS and Linux (Windows already documented as untested/best-effort). Verified for real, not just by reading code — built and ran the macOS `.app` end-to-end, and used Docker containers (Ubuntu 24.04, Fedora) to actually build and install the Linux packages, since none of these had ever been executed before this pass.

- ✅ **macOS**: rebuilt `macos/build-app.py`'s `.app` fresh, launched it, drove the control panel's "Start Sharing" button, confirmed the real file server comes up over auto-TLS (self-signed cert) and serves the welcome page. Genuinely release-ready.
- ✅ Fixed **`linux/build-deb.py` — completely broken, never worked**: `dpkg-deb --build` was called with a `cwd=` override on top of an already-relative build path, so it looked for the source dir one directory too deep and failed every time (silently mislabeled as "dpkg-deb not found" even when installed). Verified in a clean Ubuntu 24.04 container: script now produces a real `.deb`, `dpkg -i` installs it cleanly, and the installed `fileshare` command actually serves HTTP 200.
- ✅ Fixed **bogus `python3-tk`/`python3-tkinter` dependency** declared in all four packaged formats (`.deb`, `.rpm`, `.snap`, `.flatpak`) — the app has no Tkinter code anywhere (it's a stdlib `http.server` app); this was dead/wrong copy-pasted metadata that could needlessly block installs on minimal systems lacking X11/tkinter. Replaced with `python3-cryptography` (the actual optional dependency that enables auto-TLS), and verified in Docker that this dependency resolves and installs correctly.
- ✅ Fixed **version mismatch**: every Linux packaging script hardcoded `1.0.0` while `CHANGELOG.md` documents `2.0.0`. Bumped all five formats (`deb`, `rpm`, `snap`, `flatpak` manifest, plus doc references in `DEBIAN-UBUNTU.md`/`REDHAT-FEDORA.md`) to `2.0.0`.
- ✅ Fixed **placeholder GitHub URL** (`github.com/yourusername/file-share`) across `build-deb.py`, `build-rpm.py`, and the Linux doc files — replaced with the real remote (`github.com/realwebthings/fileshare`).
- ✅ Fixed **`linux/build-snap.py` clobbering its own copied source**: it copied real `main.py`/`control_panel.py` into the staging dir, then immediately overwrote both filenames with 4-line launcher stubs that `import main` / `import control_panel` — destroying the very modules the stubs needed before packaging. Renamed the launcher stubs to `fileshare-launcher`/`fileshare-gui-launcher` so the real source and the launchers coexist; verified with a dry run that both are now present intact.
- ✅ Fixed **`linux/build-flatpak.py`'s fake dependency module**: a `python3-tkinter` build module tried `pip3 install ... tkinter` (tkinter isn't a real PyPI package — it's bound to the system Python build) wrapped in `|| true`, so it silently did nothing either way. Removed the dead module entirely; the freedesktop SDK/runtime already includes Python 3.
- ✅ Verified `.rpm` build succeeds in a Fedora container (`rpmbuild` produces `fileshare-2.0.0-1.fc44.noarch.rpm`); confirmed via `rpm -qpR`/`rpm -qpi` that the dependency and URL fixes landed correctly in the built artifact.
- ✅ Verified `linux/build-run.py` (the universal `.run` installer) end-to-end in a clean Ubuntu container — extracts correctly, `fileshare --help`/`--port`/`--host`/`--no-tls` all work, and a started server responds with a real 200.
- ⏭️ `.snap`/`.flatpak` were NOT run through a full `snapcraft`/`flatpak-builder` build (multi-minute sandboxed builds, heavy tooling) — only their generator scripts were dry-run to confirm correct manifest/file output. Logic-level bugs found and fixed as above; a full package build is still unverified.
- ⏭️ Template-path resolution (`get_template_path` in `main.py`) only branches on PyInstaller's `sys._MEIPASS`; for a plain `python3 main.py` run it resolves `templates/` relative to CWD, not `__file__`. This currently works only because every Linux launcher script does `cd` into the install dir first — verified consistent across all launchers, but flagged as a latent footgun if a future launcher (e.g. a systemd unit) omits that `cd`. Not fixed — no currently-broken path found.

---

### Notes / decisions log

- Chose SameSite=Strict (not Lax) for the session cookie: this app has no legitimate cross-site referral flow (users always navigate directly), so Strict's extra CSRF protection has no real UX cost here.
- Upload handling: the **old** single-shot multipart form still buffers the full request body in memory (bounded by `Config.MAX_UPLOAD_SIZE_MB`, default 2048 MB) — kept for simplicity on small/quick uploads. The **new** chunked uploader (section 7) streams each chunk straight to disk and is what large-file/folder transfers should use; it's the actual "best in file transfer" path.
- Remote kill-switch was neutralized rather than deleted outright, since a passive "update available" notice is still a reasonable, disclosed feature; the forced `sys.exit()` behavior is what got removed.
- Did not build a signed/notarized installer for macOS or Windows (needs paid developer certificates neither of us has here) - both platforms currently ship as unsigned binaries with documented Gatekeeper/SmartScreen bypass steps.

## 9. Post-push deletion audit + Windows-specific bug (2026-07-18)

Double-checked, after pushing the section 7/8 commits, that nothing was accidentally lost, and specifically hunted for Windows bugs since that platform still has no real machine to test on.

- ✅ Diff-audited all three new commits end to end (`870f6a6..49c5922`): no accidental deletions. The only file removed was the redundant root-level `GITHUB-RELEASE.md` (the real copy lives under `linux/`, from an earlier session). Every other removed line traces to a real, intentional replacement (URL-token auth → cookie auth, hardcoded port → `Config.DEFAULT_PORT`, etc.) — worth flagging that `remote_control.py`'s kill-switch removal, while justified, wasn't called out in that commit's message.
- ✅ Fixed a genuine Windows-breaking regression introduced by this session's own `/download/`+`/raw/` leading-slash fix (section 7): unconditionally prepending `/` is correct on POSIX but produces an invalid path like `/C:\Users\Bob\file.txt` on Windows, since a Windows drive path is already absolute without one. Now branches on `IS_WINDOWS` so the prefix is only added on POSIX.
- ✅ Hand-traced the Windows drive-root/parent-link logic (`list_windows_drives`, `is_drive_root`) and the new chunked-upload subsystem's path handling (`_validate_relative_path`, `create_upload`, `finalize_upload`'s `os.replace`) for Windows correctness — both hold up, no bugs found.
- ⏭️ Still genuinely unverified: actually running PyInstaller on a real Windows machine (DLL bundling, `cryptography`'s native dependencies, SmartScreen behavior) and actually launching the built `.exe`. No Windows machine or working Wine setup was available to close this gap.

## 10. Publishing as the first-ever release (2026-07-18)

Decided to publish this as `v1.0.0`, deleting the pre-existing `v1.0.0-linux` GitHub release rather than layering a `v2.0.0` on top of a version that was never actually released end-to-end. Reverted the version bump described in section 8/9 (`1.0.0` → `2.0.0` across the Linux packaging scripts) back down to `1.0.0` everywhere, and rewrote `CHANGELOG.md` and `linux/GITHUB-RELEASE.md` as a first-release changelog/announcement instead of an "upgrade from 1.0.0" narrative. `CHANGELOG.md` in particular had a stale "Why No HTTPS" section arguing against a feature the app now has (auto-TLS) - replaced with an accurate feature list.
