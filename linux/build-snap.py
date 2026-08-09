#!/usr/bin/env python3
"""
Build Snap package for universal Linux distribution
"""
import os
import sys
import shutil
import json

def build_snap_package():
    """Build Snap package"""
    
    print("📦 Building Snap package...")
    
    build_dir = "releases/snap"
    
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
    
    # Create snapcraft.yaml
    snapcraft_config = {
        'name': 'fileshare',
        'version': '1.0.0',
        'summary': 'Share files over WiFi network',
        'description': '''
A simple HTTP server to share files between devices on the same network.
Supports both command-line and GUI modes for easy file sharing.
        '''.strip(),
        'grade': 'stable',
        'confinement': 'strict',
        'base': 'core22',
        
        'apps': {
            'fileshare': {
                'command': 'fileshare/fileshare-launcher',
                'plugs': ['network', 'network-bind', 'home']
            },
            'fileshare-gui': {
                'command': 'fileshare/fileshare-gui-launcher',
                'plugs': ['network', 'network-bind', 'home', 'desktop', 'x11']
            }
        },
        
        'parts': {
            'fileshare': {
                'plugin': 'dump',
                'source': '.',
                'stage-packages': ['python3', 'python3-cryptography'],
                'organize': {
                    'fileshare/*': 'fileshare/'
                }
            }
        }
    }
    
    # Write snapcraft.yaml (convert from JSON)
    yaml_content = '''name: fileshare
version: '1.0.0'
summary: Share files over WiFi network
description: |
  A simple HTTP server to share files between devices on the same network.
  Supports both command-line and GUI modes for easy file sharing.

grade: stable
confinement: strict
base: core22

apps:
  fileshare:
    command: fileshare/fileshare-launcher
    plugs: [network, network-bind, home]
  fileshare-gui:
    command: fileshare/fileshare-gui-launcher
    plugs: [network, network-bind, home, desktop, x11]

parts:
  fileshare:
    plugin: dump
    source: .
    stage-packages: [python3, python3-cryptography]
    organize:
      'fileshare/*': 'fileshare/'
'''
    
    with open(f"{build_dir}/snapcraft.yaml", 'w') as f:
        f.write(yaml_content)
    
    # Create launcher scripts (separate filenames from the copied main.py /
    # control_panel.py above - overwriting those would destroy the modules
    # the launchers themselves import)
    launcher_script = """#!/usr/bin/env python3
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ['FILESHARE_DB_PATH'] = os.path.expanduser('~/snap/fileshare/current/.fileshare/users.db')
import main
if __name__ == '__main__':
    main.main()
"""

    gui_launcher_script = """#!/usr/bin/env python3
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import control_panel
if __name__ == '__main__':
    control_panel.main()
"""

    with open(f"{app_dir}/fileshare-launcher", 'w') as f:
        f.write(launcher_script)

    with open(f"{app_dir}/fileshare-gui-launcher", 'w') as f:
        f.write(gui_launcher_script)

    os.chmod(f"{app_dir}/fileshare-launcher", 0o755)
    os.chmod(f"{app_dir}/fileshare-gui-launcher", 0o755)
    
    print(f"✅ Snap configuration created in: {build_dir}")
    print("📋 Build with: cd releases/snap && snapcraft")
    print("📋 Install with: sudo snap install fileshare_1.0.0_amd64.snap --dangerous")
    
    return build_dir

if __name__ == "__main__":
    build_snap_package()