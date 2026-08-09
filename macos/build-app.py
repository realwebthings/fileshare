#!/usr/bin/env python3
"""
Build a macOS .app bundle for FileShare using PyInstaller.

Must be run ON macOS - PyInstaller does not cross-compile between platforms.
Requires: pip install pyinstaller cryptography

Usage:
    python3 macos/build-app.py
"""
import os
import sys
import shutil
import subprocess


def build_macos_app():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)
    dist_dir = os.path.join(script_dir, 'releases')
    build_dir = os.path.join(script_dir, 'build')
    templates_dir = os.path.join(project_root, 'templates')
    entry_point = os.path.join(project_root, 'control_panel.py')

    print("🍎 Building macOS .app bundle with PyInstaller...")

    args = [
        sys.executable, '-m', 'PyInstaller',
        '--name', 'fileShare',
        '--windowed',
        '--onedir',
        '--noconfirm',
        '--distpath', dist_dir,
        '--workpath', build_dir,
        '--specpath', script_dir,
        '--add-data', f'{templates_dir}:templates',
        '--hidden-import', 'cryptography',
        '--collect-all', 'cryptography',
        entry_point,
    ]

    subprocess.run(args, check=True, cwd=project_root)

    app_path = os.path.join(dist_dir, 'fileShare.app')
    if not os.path.isdir(app_path):
        print(f"❌ Build finished but {app_path} was not found")
        sys.exit(1)

    print(f"✅ Built: {app_path}")
    print("   Drag it into /Applications, or run it in place.")
    print("   First launch: right-click > Open (it's unsigned/unnotarized).")
    return app_path


if __name__ == '__main__':
    build_macos_app()
