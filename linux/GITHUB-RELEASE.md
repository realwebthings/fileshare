# 🚀 FileShare v1.0.0 - Initial Release

**Share files between devices over WiFi with secure authentication and a web-based control panel.**

## ✨ Highlights

- 🔒 **Secure by default** - HttpOnly/SameSite=Strict session cookie, automatic HTTPS (self-signed cert, on by default in the `.deb`/`.rpm` packages), salted password hashing, path-based access control (only admin-shared folders/files are reachable)
- 📤 **Resumable uploads** - Large files and whole folders upload in chunks and resume after a dropped connection, closed tab, or server restart
- 🎛️ **Web control panel** - Start/stop the server and manage users/shared folders from a browser
- 📦 **Multiple package formats** - `.deb`, `.rpm`, `.run` (universal installer), Snap, Flatpak
- 🐧 **Universal compatibility** - Works on any Linux distribution with Python 3.6+
- 🎬 **Media streaming** - Video/audio streaming with HTTP range-request seeking

## 📥 Quick Installation

### 🎯 Universal Installer (All Linux Distributions)
```bash
wget https://github.com/realwebthings/fileshare/releases/latest/download/fileshare-installer.run
chmod +x fileshare-installer.run
./fileshare-installer.run
```

### 📦 Distribution-Specific Packages

#### Debian/Ubuntu
```bash
wget https://github.com/realwebthings/fileshare/releases/latest/download/fileshare_1.0.0.deb
sudo dpkg -i fileshare_1.0.0.deb
```

#### Red Hat/Fedora/CentOS
```bash
wget https://github.com/realwebthings/fileshare/releases/latest/download/fileshare-1.0.0-1.noarch.rpm
sudo rpm -i fileshare-1.0.0-1.noarch.rpm
```

## 🚀 Usage

```bash
# GUI Control Panel (Recommended)
fileshare-gui

# Terminal Mode
fileshare
```

## 🎯 Features

- ✅ **Secure Authentication** - Cookie-based session login, admin approval for new users
- ✅ **Admin Panel** - User management and file sharing controls
- ✅ **Mobile Optimized** - Works well on phones/tablets
- ✅ **Video Streaming** - Stream videos directly to mobile devices
- ✅ **Rate Limiting** - Protection against brute force login attempts
- ✅ **Cross-Platform** - Works on any device with a web browser

## 📱 How to Use

1. **Start the server**: Run `fileshare-gui`
2. **Note the admin password** displayed in the GUI (also saved locally for recovery)
3. **Connect devices** to the same WiFi network
4. **Open browser** on your phone/tablet
5. **Visit the URL** shown in the control panel
6. **Login** with username `admin` and the displayed password
7. **Share files** by adding folders in the admin panel

## 🔧 System Requirements

- **Python**: 3.6 or higher
- **`cryptography` package**: required for automatic HTTPS - already included with the `.deb`/`.rpm` packages; if you're using the `.run` installer or running `main.py` directly from source, install it yourself (see Troubleshooting below)
- **Network**: WiFi connection
- **OS**: Any Linux distribution

## 📋 Package Details

| Package | Description |
|---------|-------------|
| `fileshare-installer.run` | Universal self-extracting installer |
| `fileshare_1.0.0.deb` | Debian/Ubuntu package |
| `fileshare-1.0.0-1.noarch.rpm` | Red Hat/Fedora package |

## 🛡️ Security Notes

- 🔒 **Local Network Only** - Designed for trusted WiFi networks, not adversarial public internet exposure
- 🔑 **Auto-Generated Admin Password** - Generated once on first run, persisted locally for recovery
- 🚫 **Rate Limited** - Automatic protection against failed login attempts
- 📁 **Selective Sharing** - Only admin-approved folders are accessible

## 🆘 Troubleshooting

**Running plain HTTP instead of HTTPS?** (only relevant for the `.run`
installer or running from source - the `.deb`/`.rpm` packages already
include `cryptography` and get HTTPS automatically)
```bash
# Install the cryptography package
sudo apt install python3-cryptography  # Debian/Ubuntu
sudo dnf install python3-cryptography  # Fedora
```

**Can't access from phone?**
- Ensure both devices are on the same WiFi
- Check firewall settings
- Try the IP address shown in the control panel

## 📚 Documentation

- [Linux Distribution Guide](https://github.com/realwebthings/fileshare/tree/main/linux)
- [Installation Troubleshooting](https://github.com/realwebthings/fileshare/blob/main/linux/README.md)
- [Security Best Practices](https://github.com/realwebthings/fileshare/blob/main/README.md)

---

**⭐ Star this repo if FileShare helped you!**
**🐛 Report issues on [GitHub Issues](https://github.com/realwebthings/fileshare/issues)**
