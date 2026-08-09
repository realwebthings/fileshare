# Windows build

Builds `fileShare.exe` - a double-clickable control panel with Start/Stop
buttons, matching the Linux/macOS GUI experience.

**This has to be built on an actual Windows machine (or VM).** PyInstaller
does not cross-compile, so it can't be produced from macOS/Linux - this
script was written and reasoned through carefully but has not been run on
real Windows. Please validate it there before relying on it.

## Build

From a Windows `cmd` or PowerShell prompt:

```bat
py -3 -m venv venv
venv\Scripts\activate
pip install pyinstaller cryptography
python windows\build-exe.py
```

Output: `windows\releases\fileShare\fileShare.exe`

## Notes

- **First launch is slow (5-15s)** before the control panel opens in your
  browser - the bundled `cryptography`/OpenSSL libraries take a moment to
  initialize on cold start.
- The binary is unsigned. Windows SmartScreen will warn on first run;
  choose "More info" > "Run anyway". Proper distribution would need a code
  signing certificate, which isn't set up here.
- Debug output goes to `%USERPROFILE%\Desktop\fileShare_debug.log` if that
  folder exists, otherwise `%USERPROFILE%\fileShare_debug.log`.
- The admin password is written to `admin_password.txt` next to the
  database (`%USERPROFILE%\fileShare_users.db` for packaged builds).
- Zip the `fileShare` output folder to hand it to someone else, or wrap it
  with an installer (Inno Setup / NSIS) for a proper `setup.exe` - not
  included here.
