# Changelog

## Version 1.0.0 - Initial Release

### 🔒 Security
- Session cookie is `HttpOnly` + `SameSite=Strict`, no longer passed in the URL
- Optional automatic HTTPS (self-signed certificate generated on first run if the `cryptography` package is installed, or bring your own via `--cert`/`--key`)
- CSRF defense-in-depth on state-changing admin routes (same-origin check on top of `SameSite=Strict`)
- Passwords hashed with salted PBKDF2 - no plaintext password storage
- Path-based access control: only explicitly admin-shared folders/files are reachable, everything else blocked by default
- Rate limiting on login attempts (configurable window/attempt count)
- Admin password generated once on first run and persisted to a local recovery file, not regenerated on every restart

### 📦 File Transfer
- Resumable, chunked uploads for large files and whole folders: interrupted transfers (dropped connection, closed tab, server restart) resume from the last confirmed byte instead of starting over
- Upfront disk-space check across an entire folder upload before any byte moves
- Live transfer list so users can see what's currently uploading
- Video/audio streaming with HTTP range requests (seek support, `206 Partial Content`)
- Fast chunked downloads

### 🖥️ Cross-Platform
- macOS: packaged `.app` via PyInstaller (`macos/`)
- Linux: `.deb`, `.rpm`, `.run` (universal installer), Snap, and Flatpak packaging (`linux/`)
- Windows: packaged `.exe` via PyInstaller (`windows/`) - built successfully but not yet run on a real Windows machine, treat as best-effort until confirmed
- Windows drive enumeration (`C:\`, `D:\`, ...) in place of POSIX-only `/` root browsing

### 🎛️ Control Panel
- Web-based GUI to start/stop the file server and see its status
- Admin panel for managing users (approve/reject/reset) and shared paths

Current security model targets trusted local-network use (home/office WiFi), not adversarial public internet exposure.
