#!/usr/bin/env python3
"""
Build Flatpak package for universal Linux distribution
"""
import os
import sys
import shutil
import json

def build_flatpak_package():
    """Build Flatpak package"""
    
    print("📦 Building Flatpak package...")
    
    build_dir = "releases/flatpak"
    app_id = "com.fileshare.FileShare"
    
    # Clean and create build directory
    if os.path.exists(build_dir):
        shutil.rmtree(build_dir)
    os.makedirs(build_dir, exist_ok=True)
    
    # Copy source files
    app_dir = f"{build_dir}/fileshare"
    os.makedirs(f"{app_dir}/templates", exist_ok=True)
    
    source_files = [
        ('../main.py', f'{app_dir}/main.py'),
        ('../control_panel.py', f'{app_dir}/control_panel.py'),
        ('../config.py', f'{app_dir}/config.py'),
        ('../remote_control.py', f'{app_dir}/remote_control.py'),
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
                    f"{app_dir}/templates/{template}"
                )
    
    # Create Flatpak manifest
    manifest = {
        "app-id": app_id,
        "runtime": "org.freedesktop.Platform",
        "runtime-version": "22.08",
        "sdk": "org.freedesktop.Sdk",
        "command": "fileshare-gui",
        "finish-args": [
            "--share=network",
            "--socket=x11",
            "--socket=wayland",
            "--filesystem=home",
            "--device=dri"
        ],
        "modules": [
            {
                "name": "fileshare",
                "buildsystem": "simple",
                "build-commands": [
                    "mkdir -p /app/share/fileshare",
                    "cp -r fileshare/* /app/share/fileshare/",
                    "mkdir -p /app/bin",
                    "install -Dm755 fileshare-launcher /app/bin/fileshare",
                    "install -Dm755 fileshare-gui-launcher /app/bin/fileshare-gui",
                    "mkdir -p /app/share/applications",
                    "install -Dm644 com.fileshare.FileShare.desktop /app/share/applications/"
                ],
                "sources": [
                    {
                        "type": "dir",
                        "path": "."
                    }
                ]
            }
        ]
    }
    
    # Write manifest
    with open(f"{build_dir}/{app_id}.json", 'w') as f:
        json.dump(manifest, f, indent=2)
    
    # Create launcher scripts
    launcher_script = """#!/bin/bash
cd /app/share/fileshare
export FILESHARE_DB_PATH="$HOME/.var/app/com.fileshare.FileShare/data/users.db"
mkdir -p "$(dirname "$FILESHARE_DB_PATH")"
python3 main.py "$@"
"""
    
    gui_launcher_script = """#!/bin/bash
cd /app/share/fileshare
python3 control_panel.py
"""
    
    with open(f"{build_dir}/fileshare-launcher", 'w') as f:
        f.write(launcher_script)
    
    with open(f"{build_dir}/fileshare-gui-launcher", 'w') as f:
        f.write(gui_launcher_script)
    
    os.chmod(f"{build_dir}/fileshare-launcher", 0o755)
    os.chmod(f"{build_dir}/fileshare-gui-launcher", 0o755)
    
    # Create desktop entry
    desktop_content = f"""[Desktop Entry]
Name=FileShare
Comment=Share files over WiFi
Exec=fileshare-gui
Icon={app_id}
Terminal=false
Type=Application
Categories=Network;FileTransfer;
"""
    
    with open(f"{build_dir}/{app_id}.desktop", 'w') as f:
        f.write(desktop_content)
    
    print(f"✅ Flatpak configuration created in: {build_dir}")
    print("📋 Build with:")
    print(f"   cd {build_dir}")
    print(f"   flatpak-builder build-dir {app_id}.json --force-clean")
    print(f"   flatpak build-export repo build-dir")
    print("📋 Install with:")
    print(f"   flatpak --user remote-add --no-gpg-verify fileshare-repo repo")
    print(f"   flatpak --user install fileshare-repo {app_id}")
    
    return build_dir

if __name__ == "__main__":
    build_flatpak_package()