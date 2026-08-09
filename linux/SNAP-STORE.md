# Snap Store Distribution Guide

## 📦 Building Snap Package

```bash
python3 build-snap.py
cd build/snap
snapcraft
```

## 📋 Requirements

- `snapcraft` for building
- `multipass` or `lxd` for isolated builds

```bash
# Install snapcraft
sudo snap install snapcraft --classic

# Install multipass (recommended)
sudo snap install multipass
```

## 🚀 Building Process

### 1. Generate Configuration
```bash
python3 build-snap.py
```

### 2. Build Snap
```bash
cd build/snap
snapcraft
```

### 3. Test Locally
```bash
sudo snap install fileshare_1.0.0_amd64.snap --dangerous
```

## 📤 Publishing to Snap Store

### 1. Create Developer Account
- Register at https://snapcraft.io/account
- Verify email and enable 2FA
- Accept developer agreement

### 2. Register Snap Name
```bash
snapcraft register fileshare
```

### 3. Upload and Release
```bash
# Upload to store
snapcraft upload fileshare_1.0.0_amd64.snap

# Release to stable channel
snapcraft release fileshare 1 stable
```

### 4. Store Listing
- Add description and screenshots
- Set category: "Productivity" or "Utilities"
- Add contact information
- Submit for review

## 🎯 Snap Channels

| Channel | Purpose | Auto-updates |
|---------|---------|--------------|
| `stable` | Production releases | ✅ |
| `candidate` | Release candidates | ✅ |
| `beta` | Beta testing | ✅ |
| `edge` | Development builds | ✅ |

## 🔧 Snap Configuration

```yaml
name: fileshare
version: '1.0.0'
summary: Share files over WiFi network
description: |
  A simple HTTP server to share files between devices on the same network.
  Supports both command-line and GUI modes.

grade: stable
confinement: strict
base: core22

apps:
  fileshare:
    command: fileshare/main.py
    plugs: [network, network-bind, home]
  
  fileshare-gui:
    command: fileshare/control_panel.py
    plugs: [network, network-bind, home, desktop, x11]
```

## 🚀 User Installation

```bash
# Install from Snap Store
sudo snap install fileshare

# Run applications
fileshare          # Terminal mode
fileshare.gui      # GUI mode (note the dot)
```

## 🔒 Permissions (Plugs)

- `network` - Internet access for updates
- `network-bind` - Bind to network ports
- `home` - Access user files
- `desktop` - Desktop integration
- `x11` - GUI display

## 📊 Store Analytics

- View install statistics
- Monitor user ratings
- Track geographic distribution
- Analyze channel usage

## 🎯 Benefits

- ✅ **Universal** - Works on all Linux distributions
- ✅ **Auto-updates** - Automatic security updates
- ✅ **Sandboxed** - Secure isolated environment
- ✅ **Easy discovery** - Snap Store visibility
- ✅ **No dependencies** - Self-contained package