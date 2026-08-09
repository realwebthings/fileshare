# Flatpak/Flathub Distribution Guide

## 📦 Building Flatpak Package

```bash
python3 build-flatpak.py
cd build/flatpak
flatpak-builder build-dir com.fileshare.FileShare.json --force-clean
```

## 📋 Requirements

- `flatpak` and `flatpak-builder`
- Freedesktop SDK

```bash
# Install flatpak
sudo apt install flatpak flatpak-builder  # Debian/Ubuntu
sudo dnf install flatpak flatpak-builder  # Fedora

# Add Flathub repository
flatpak remote-add --if-not-exists flathub https://flathub.org/repo/flathub.flatpakrepo

# Install SDK
flatpak install flathub org.freedesktop.Platform//22.08 org.freedesktop.Sdk//22.08
```

## 🚀 Building Process

### 1. Generate Configuration
```bash
python3 build-flatpak.py
```

### 2. Build Flatpak
```bash
cd build/flatpak
flatpak-builder build-dir com.fileshare.FileShare.json --force-clean
```

### 3. Create Repository
```bash
flatpak build-export repo build-dir
```

### 4. Test Installation
```bash
flatpak --user remote-add --no-gpg-verify fileshare-repo repo
flatpak --user install fileshare-repo com.fileshare.FileShare
```

## 📤 Publishing to Flathub

### 1. Fork Flathub Repository
- Fork https://github.com/flathub/flathub
- Create new repository: `com.fileshare.FileShare`

### 2. Prepare Manifest
```json
{
  "app-id": "com.fileshare.FileShare",
  "runtime": "org.freedesktop.Platform",
  "runtime-version": "22.08",
  "sdk": "org.freedesktop.Sdk",
  "command": "fileshare-gui",
  "finish-args": [
    "--share=network",
    "--socket=x11",
    "--socket=wayland", 
    "--filesystem=home"
  ]
}
```

### 3. Submit Pull Request
- Add manifest to repository
- Include AppStream metadata
- Add desktop file and icon
- Submit PR to Flathub

### 4. Review Process
- Automated testing
- Manual review by Flathub team
- Address feedback
- Approval and publication

## 🎯 AppStream Metadata

Create `com.fileshare.FileShare.metainfo.xml`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<component type="desktop-application">
  <id>com.fileshare.FileShare</id>
  <name>FileShare</name>
  <summary>Share files over WiFi network</summary>
  <description>
    <p>A simple HTTP server to share files between devices on the same network.</p>
  </description>
  <categories>
    <category>Network</category>
    <category>FileTransfer</category>
  </categories>
  <url type="homepage">https://github.com/realwebthings/fileshare</url>
  <launchable type="desktop-id">com.fileshare.FileShare.desktop</launchable>
  <releases>
    <release version="1.0.0" date="2024-01-01"/>
  </releases>
</component>
```

## 🚀 User Installation

```bash
# Install from Flathub
flatpak install flathub com.fileshare.FileShare

# Run application
flatpak run com.fileshare.FileShare
```

## 🔒 Permissions (Finish Args)

- `--share=network` - Network access
- `--socket=x11` - X11 display
- `--socket=wayland` - Wayland display
- `--filesystem=home` - Home directory access
- `--device=dri` - Hardware acceleration

## 📊 Flathub Benefits

- ✅ **Universal** - Works on all Linux distributions
- ✅ **Sandboxed** - Secure runtime environment
- ✅ **Centralized** - Single store for all apps
- ✅ **Auto-updates** - Automatic application updates
- ✅ **Dependency-free** - Runtime included

## 🎯 Best Practices

### Security
- Minimal permissions
- Sandbox-friendly design
- No hardcoded paths

### Quality
- Include high-quality icons
- Comprehensive AppStream data
- Proper desktop integration

### Maintenance
- Regular updates
- Security patches
- User feedback response

## 📝 Submission Checklist

- [ ] Valid manifest file
- [ ] AppStream metadata
- [ ] Desktop file
- [ ] Application icon (multiple sizes)
- [ ] Screenshots for store
- [ ] License compatibility
- [ ] Security review passed