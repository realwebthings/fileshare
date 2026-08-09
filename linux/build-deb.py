#!/usr/bin/env python3
"""
Build .deb package for Debian/Ubuntu systems
"""
import os
import sys
import shutil
import subprocess

def build_deb_package():
    """Build Debian package"""
    
    print("📦 Building .deb package...")
    
    package_name = "fileshare"
    version = "1.0.0"
    build_dir = f"releases/deb/{package_name}_{version}"
    
    # Clean and create build directory
    if os.path.exists(build_dir):
        shutil.rmtree(build_dir)
    
    # Create Debian package structure
    dirs = [
        f"{build_dir}/DEBIAN",
        f"{build_dir}/usr/share/fileshare",
        f"{build_dir}/usr/share/fileshare/templates", 
        f"{build_dir}/usr/bin",
        f"{build_dir}/usr/share/applications",
        f"{build_dir}/usr/share/doc/fileshare"
    ]
    
    for dir_path in dirs:
        os.makedirs(dir_path, exist_ok=True)
    
    # Copy source files
    source_files = [
        ('../main.py', f'{build_dir}/usr/share/fileshare/main.py'),
        ('../control_panel.py', f'{build_dir}/usr/share/fileshare/control_panel.py'),
        ('../config.py', f'{build_dir}/usr/share/fileshare/config.py'),
        ('../remote_control.py', f'{build_dir}/usr/share/fileshare/remote_control.py'),
    ]
    
    for src, dst in source_files:
        if os.path.exists(src):
            shutil.copy2(src, dst)
    
    # Copy templates
    template_dir = "../templates"
    if os.path.exists(template_dir):
        for template in os.listdir(template_dir):
            if template.endswith('.html'):
                shutil.copy2(
                    os.path.join(template_dir, template),
                    f"{build_dir}/usr/share/fileshare/templates/{template}"
                )
    
    # Create control file
    control_content = f"""Package: {package_name}
Version: {version}
Section: net
Priority: optional
Architecture: all
Depends: python3 (>= 3.6), python3-cryptography
Maintainer: FileShare Team <contact@fileshare.app>
Description: Share files over WiFi network
 A simple HTTP server to share files between devices on the same network.
 Supports both command-line and GUI modes.
"""
    
    with open(f"{build_dir}/DEBIAN/control", 'w') as f:
        f.write(control_content)
    
    # Create launcher scripts
    launcher_content = """#!/bin/bash
cd /usr/share/fileshare
export FILESHARE_DB_PATH="$HOME/.fileshare/users.db"
mkdir -p "$HOME/.fileshare"
python3 main.py "$@"
"""
    
    gui_launcher_content = """#!/bin/bash
cd /usr/share/fileshare
python3 control_panel.py
"""
    
    with open(f"{build_dir}/usr/bin/fileshare", 'w') as f:
        f.write(launcher_content)
    
    with open(f"{build_dir}/usr/bin/fileshare-gui", 'w') as f:
        f.write(gui_launcher_content)
    
    os.chmod(f"{build_dir}/usr/bin/fileshare", 0o755)
    os.chmod(f"{build_dir}/usr/bin/fileshare-gui", 0o755)
    
    # Create desktop entry
    desktop_content = """[Desktop Entry]
Name=FileShare
Comment=Share files over WiFi
Exec=fileshare-gui
Icon=folder-remote
Terminal=false
Type=Application
Categories=Network;FileTransfer;
"""

    with open(f"{build_dir}/usr/share/applications/fileshare.desktop", 'w') as f:
        f.write(desktop_content)
    
    # Create copyright file
    copyright_content = """Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
Upstream-Name: fileshare
Source: https://github.com/realwebthings/fileshare

Files: *
Copyright: 2024 FileShare Team
License: MIT
"""
    
    with open(f"{build_dir}/usr/share/doc/fileshare/copyright", 'w') as f:
        f.write(copyright_content)
    
    # Build package
    try:
        subprocess.run(['dpkg-deb', '--build', build_dir], check=True)
        deb_file = f"{build_dir}.deb"
        size = os.path.getsize(deb_file)
        print(f"✅ Created: {deb_file} ({size:,} bytes)")
        print(f"📋 Install with: sudo dpkg -i {deb_file}")
        return deb_file
    except subprocess.CalledProcessError as e:
        print(f"❌ dpkg-deb build failed: {e}")
        return None
    except FileNotFoundError:
        print("❌ dpkg-deb not found. Install with: sudo apt install dpkg-dev")
        return None

if __name__ == "__main__":
    build_deb_package()