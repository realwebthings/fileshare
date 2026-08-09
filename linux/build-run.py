#!/usr/bin/env python3
"""
Build .run installer for universal Linux distribution
"""
import os
import sys
import shutil
import base64
import gzip

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def build_run_installer():
    """Build self-extracting .run installer"""
    
    print("🔨 Building .run installer...")
    
    # Source files to include
    source_files = {
        '../main.py': 'main.py',
        '../control_panel.py': 'control_panel.py',
        '../config.py': 'config.py', 
        '../remote_control.py': 'remote_control.py',
        '../templates/admin.html': 'templates/admin.html',
        '../templates/control_panel.html': 'templates/control_panel.html',
        '../templates/directory.html': 'templates/directory.html',
        '../templates/login.html': 'templates/login.html',
        '../templates/message.html': 'templates/message.html',
        '../templates/register.html': 'templates/register.html',
        '../templates/welcome.html': 'templates/welcome.html'
    }
    
    # Embed files as base64
    embedded_files = {}
    for src, dest in source_files.items():
        if os.path.exists(src):
            with open(src, 'rb') as f:
                content = gzip.compress(f.read())
                embedded_files[dest] = base64.b64encode(content).decode()
    
    # Create installer script
    installer_script = f'''#!/bin/bash
# FileShare Universal Linux Installer
set -e

APP_NAME="FileShare"
INSTALL_DIR="$HOME/.local/share/fileShare"
BIN_DIR="$HOME/.local/bin"
DESKTOP_DIR="$HOME/.local/share/applications"

echo "🐧 Installing $APP_NAME..."

# Create directories
mkdir -p "$INSTALL_DIR/templates" "$BIN_DIR" "$DESKTOP_DIR"

# Extract embedded files
{generate_extract_commands(embedded_files)}

# Create launchers
cat > "$BIN_DIR/fileshare" << 'EOF'
#!/bin/bash
cd "$HOME/.local/share/fileShare"
export FILESHARE_DB_PATH="$HOME/.fileshare/users.db"
mkdir -p "$HOME/.fileshare"
python3 main.py "$@"
EOF

cat > "$BIN_DIR/fileshare-gui" << 'EOF'
#!/bin/bash
cd "$HOME/.local/share/fileShare"
python3 control_panel.py
EOF

chmod +x "$BIN_DIR/fileshare" "$BIN_DIR/fileshare-gui"

# Desktop entry
cat > "$DESKTOP_DIR/fileshare.desktop" << 'EOF'
[Desktop Entry]
Name=FileShare
Comment=Share files over WiFi
Exec=fileshare-gui
Icon=folder-remote
Terminal=false
Type=Application
Categories=Network;
EOF

echo "✅ Installation complete!"
echo "🚀 Run: fileshare (terminal) or fileshare-gui (GUI)"
'''
    
    # Write to releases directory
    output_path = "releases/run/fileshare-installer.run"
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w') as f:
        f.write(installer_script)
    
    os.chmod(output_path, 0o755)
    
    size = os.path.getsize(output_path)
    print(f"✅ Created: {output_path} ({size:,} bytes)")
    return output_path

def generate_extract_commands(embedded_files):
    """Generate bash commands to extract files"""
    commands = []
    for file_path, encoded_data in embedded_files.items():
        commands.append(f'echo "{encoded_data}" | base64 -d | gunzip > "$INSTALL_DIR/{file_path}"')
    return '\n'.join(commands)

if __name__ == "__main__":
    build_run_installer()