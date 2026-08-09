# Red Hat/Fedora Distribution Guide

## 📦 Building .rpm Package

```bash
python3 build-rpm.py
```

## 📋 Requirements

- `rpm-build` package for building
- Python 3.6+ - the built package Requires/Depends on `python3-cryptography` (enables HTTPS by default)

```bash
# Fedora/CentOS 8+
sudo dnf install rpm-build python3 python3-cryptography

# CentOS 7/RHEL 7
sudo yum install rpm-build python3 python3-cryptography
```

## 🚀 Installation

### For Users
```bash
# Download and install
wget https://github.com/realwebthings/fileshare/releases/latest/download/fileshare-1.0.0-1.noarch.rpm
sudo rpm -i fileshare-1.0.0-1.noarch.rpm

# Or with dnf/yum
sudo dnf install fileshare-1.0.0-1.noarch.rpm
```

### Usage
```bash
fileshare          # Terminal mode
fileshare-gui      # GUI control panel
```

## 📤 Publishing to Repository

### 1. Fedora Official Repository
```bash
# Create Fedora account
# Submit package review request
# Follow Fedora packaging guidelines
# Create SPEC file according to standards
```

### 2. EPEL (Enterprise Linux)
```bash
# For CentOS/RHEL compatibility
# Submit to EPEL repository
# Ensure compatibility with older Python versions
```

### 3. COPR (Community Repository)
```bash
# Create COPR project
copr-cli create fileshare --chroot fedora-38-x86_64 --chroot fedora-39-x86_64

# Build package
copr-cli build fileshare --srpm fileshare-1.0.0-1.src.rpm
```

### 4. Custom Repository
```bash
# Create repository structure
mkdir -p repo/x86_64
cp fileshare-1.0.0-1.noarch.rpm repo/x86_64/

# Create repository metadata
createrepo repo/

# Sign packages (optional)
rpm --addsign repo/x86_64/*.rpm
```

## 🎯 Supported Distributions

- ✅ Fedora 36+
- ✅ CentOS 8+
- ✅ RHEL 8+
- ✅ Rocky Linux 8+
- ✅ AlmaLinux 8+
- ✅ openSUSE Leap 15+

## 🔧 Package Details

- **Package name:** `fileshare`
- **Version:** `1.0.0-1`
- **Architecture:** `noarch`
- **Dependencies:** `python3 >= 3.6, python3-cryptography`
- **Install location:** `/usr/share/fileshare`
- **Executables:** `/usr/bin/fileshare`, `/usr/bin/fileshare-gui`
- **Desktop entry:** `/usr/share/applications/fileshare.desktop`

## 📝 SPEC File Highlights

```spec
Name:           fileshare
Version:        1.0.0
Release:        1%{?dist}
Summary:        Share files over WiFi network
License:        MIT
BuildArch:      noarch
Requires:       python3 >= 3.6, python3-cryptography
```