#!/usr/bin/env python3
"""
Build a Windows .exe for FileShare using PyInstaller.

Must be run ON Windows - PyInstaller does not cross-compile between
platforms, so this cannot be produced from macOS/Linux.

Usage (from a Windows cmd/PowerShell prompt):
    py -3 -m venv venv
    venv\\Scripts\\activate
    pip install pyinstaller cryptography
    python windows\\build-exe.py
"""
import os
import sys
import subprocess

if sys.platform == 'win32':
    # Windows consoles default to a legacy codepage (e.g. cp1252) that
    # can't encode the emoji used in these print statements - force UTF-8
    # so this doesn't crash with UnicodeEncodeError on a plain `python
    # build-exe.py` run outside a UTF-8-configured terminal.
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')


def build_windows_exe():
    if sys.platform != 'win32':
        print("⚠️  This must be run on Windows - PyInstaller does not cross-compile.")
        print("    Run it from a Windows machine (or VM) instead.")
        sys.exit(1)

    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)
    dist_dir = os.path.join(script_dir, 'releases')
    build_dir = os.path.join(script_dir, 'build')
    templates_dir = os.path.join(project_root, 'templates')
    entry_point = os.path.join(project_root, 'control_panel.py')

    print("🪟 Building Windows .exe with PyInstaller...")

    args = [
        sys.executable, '-m', 'PyInstaller',
        '--name', 'fileShare',
        '--windowed',
        '--onedir',
        '--noconfirm',
        '--distpath', dist_dir,
        '--workpath', build_dir,
        '--specpath', script_dir,
        '--add-data', f'{templates_dir}{os.pathsep}templates',
        '--hidden-import', 'cryptography',
        '--collect-all', 'cryptography',
        entry_point,
    ]

    subprocess.run(args, check=True, cwd=project_root)

    exe_path = os.path.join(dist_dir, 'fileShare', 'fileShare.exe')
    if not os.path.exists(exe_path):
        print(f"❌ Build finished but {exe_path} was not found")
        sys.exit(1)

    print(f"✅ Built: {exe_path}")
    print("   Zip up the 'fileShare' folder to distribute it, or wrap it")
    print("   with an installer (Inno Setup / NSIS) for a proper setup.exe.")
    return exe_path


if __name__ == '__main__':
    build_windows_exe()
