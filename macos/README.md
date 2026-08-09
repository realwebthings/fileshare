# macOS build

Builds `fileShare.app` - a double-clickable control panel with Start/Stop
buttons, matching the Linux GUI experience.

## Build

```bash
cd file-share
python3 -m venv venv && source venv/bin/activate
pip install pyinstaller cryptography
python3 macos/build-app.py
```

Output: `macos/releases/fileShare.app`

## Notes

- **First launch is slow (5-15s)** before the control panel opens in your
  browser - the bundled `cryptography`/OpenSSL libraries take a moment to
  initialize on cold start. This is normal, not a hang.
- The app is unsigned and unnotarized. On first launch, macOS Gatekeeper
  will block it; right-click the app > **Open** to bypass that once.
  Proper distribution would need an Apple Developer ID and notarization,
  which isn't set up here.
- Debug output when running as a packaged app goes to
  `~/Desktop/fileShare_debug.log` (see `control_panel.py`'s frozen-mode
  logging setup).
- The admin password is written to `~/admin_password.txt` (0600
  permissions) the first time the server creates its `admin` account. See
  the security notes in the root `PROGRESS.md`.
