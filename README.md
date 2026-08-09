# FileShare

A self-hosted file server for moving files between your computer and your
phone (or any other device) over the same WiFi network — no cloud, no
account, no third party involved. Browse folders, download files, stream
video/audio, and upload from your phone, all through a browser.

## Why this exists

You're on the same WiFi as your phone and just want to grab a file off
your laptop, or push a photo from your phone to your computer, without
emailing it to yourself or opening a cloud drive. Run this, open the URL
it prints on your phone's browser, done.

## Quick start

```bash
git clone <this-repo>
cd file-share
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt   # installs cryptography, enables HTTPS by default
python3 main.py
```

Every packaged install (`.deb`/`.rpm`/`.snap`/the macOS `.app`/the Windows
`.exe`) already bundles `cryptography`, so HTTPS is on by default there
too — `requirements.txt` above only matters if you're running from a
source checkout. If `cryptography` can't be installed for some reason,
`main.py` still runs fine over plain HTTP, just with a warning at startup.

The terminal prints an admin username/password and a URL. Open that URL
on your phone (same WiFi network as your computer) to browse, download,
or upload files.

Prefer clicking buttons instead of a terminal? Run `python3
control_panel.py` for a small Start/Stop/Quit window instead.

### Common options

```bash
python3 main.py --port 8080                # use a different port
python3 main.py --no-tls                   # plain HTTP instead of HTTPS
python3 main.py --cert cert.pem --key key.pem   # use your own TLS cert
python3 main.py --reset-admin-password     # forgot it? generate a new one
```

## How sharing works

- **Nothing is visible by default.** After you log in as admin, browse to
  a folder and click **"Share This Folder"** (or **"Share File"** next to
  a single file) to make it visible to other logged-in users.
- New accounts need admin approval before they can log in (Admin Panel →
  Pending Approval).
- The admin account can browse and share anything on the machine; everyone
  else only ever sees what's been explicitly shared with them.

## Platform support

| Platform | How to run it | Status |
|---|---|---|
| macOS | `python3 main.py` or a packaged `.app` | Packaged `.app` build verified working — see [macos/](macos/) |
| Linux | `python3 main.py`, or `.deb`/`.rpm`/`.snap`/`.flatpak`/`.run` packages | See [linux/](linux/) |
| Windows | `python3 main.py`, or a packaged `.exe` | Runs fine as a plain script. The packaged `.exe` build script is written but hasn't been test-run on a real Windows machine yet — see [windows/](windows/) |

The plain `python3 main.py` route works identically on all three; the
packaged apps just add a double-clickable icon and a GUI control panel.

## Can it handle large files?

Short answer: **yes, in both directions, with no practical size limit —
as long as you use the folder/bulk uploader for uploads.**

- **Downloads and video/audio streaming** are sent in small chunks
  (8 KB–1 MB at a time), so file size doesn't matter — a 50 GB file
  downloads exactly like a 5 MB one, just slower.
- **Uploads via the folder/bulk uploader** stream straight to disk in
  chunks and are resumable — an interrupted transfer (dropped connection,
  closed tab, even a server restart) picks up from the last confirmed
  byte instead of starting over. This is the path to use for large files
  or whole folders.
- **Uploads via the single-file quick-upload form** are read fully into
  memory before being written to disk, capped at 2 GB by default
  (`Config.MAX_UPLOAD_SIZE_MB` in `config.py`). Fine for a quick single
  file; for anything large, use the folder/bulk uploader instead.
- **Viewing** a huge non-media file inline (the "View" link, not
  "Download") also loads the whole thing into memory first — for very
  large files, use "Download" instead.

## Can you trust this with your files?

Be realistic about what this is: a small, self-hosted tool for **personal
use on a network you trust** (your home or office WiFi) — not a hardened,
professionally audited product.

What's true today:
- Passwords are salted and hashed (PBKDF2), never stored in plain text.
- Traffic is encrypted by default (HTTPS with an auto-generated
  certificate) rather than plain HTTP.
- Everything is locked down by default — a fresh install shares nothing
  until the admin explicitly shares it.
- Common web vulnerabilities (XSS, CSRF, session tokens leaking into
  URLs/logs) have been reviewed and fixed — see [PROGRESS.md](PROGRESS.md)
  for the specifics.

What's still true and worth knowing:
- The HTTPS certificate is self-signed — it stops passive network
  sniffing, but there's no certificate authority vouching for it, so your
  browser will (correctly) warn you on first visit.
- This has been reviewed by its maintainer and an AI coding assistant, not
  by an independent security firm. There's no bug bounty, no CVE history,
  no third-party audit to point to.
- The distributed `.app`/`.exe` builds are unsigned, so macOS/Windows will
  show a security warning the first time you open them.
- The admin account can read (and share) anything on the machine it runs
  on by design — appropriate for "this is my computer," not appropriate
  for a shared/public server.

If you need something you can point at a compliance checklist, this isn't
that. If you want a quick, private way to move files to your own phone on
your own WiFi, this does that well.

## Security notes

- Only run this on a network you trust.
- Stop the server (Ctrl+C, or "Quit" in the control panel) when you're
  done sharing.
- The admin password is saved to `admin_password.txt` next to the
  database (0600 permissions) the first time an admin account is created,
  in case you miss it in the terminal output.

## Troubleshooting

- **Can't connect from your phone**: confirm both devices are on the same
  WiFi network and no firewall is blocking the port.
- **Port already in use**: `python3 main.py --port 8080`
- **Forgot the admin password**: `python3 main.py --reset-admin-password`
- **Browser warns about the certificate**: expected with the self-signed
  cert — click through it, or run with `--no-tls` if you'd rather have
  plain HTTP on a fully trusted network.

## For contributors

- [PROGRESS.md](PROGRESS.md) — history of what's been fixed/added and why
- [linux/](linux/), [macos/](macos/), [windows/](windows/) — per-platform
  packaging scripts and notes
- `main.py` is the server; `control_panel.py` is the optional GUI wrapper;
  `config.py` holds the tunable settings (port, token expiry, rate limits,
  upload size cap)
