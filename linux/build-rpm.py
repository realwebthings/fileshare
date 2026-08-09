#!/usr/bin/env python3
"""
Build .rpm package for Red Hat/Fedora/CentOS systems
"""
import os
import sys
import shutil
import subprocess

def build_rpm_package():
    """Build RPM package"""
    
    print("📦 Building .rpm package...")
    
    package_name = "fileshare"
    version = "1.0.0"
    release = "1"
    build_dir = f"releases/rpm"
    
    # Clean and create RPM build structure
    if os.path.exists(build_dir):
        shutil.rmtree(build_dir)
    
    rpm_dirs = [
        f"{build_dir}/BUILD",
        f"{build_dir}/RPMS",
        f"{build_dir}/SOURCES", 
        f"{build_dir}/SPECS",
        f"{build_dir}/SRPMS",
        f"{build_dir}/BUILDROOT"
    ]
    
    for dir_path in rpm_dirs:
        os.makedirs(dir_path, exist_ok=True)
    
    # Create source tarball
    source_dir = f"{build_dir}/SOURCES/{package_name}-{version}"
    os.makedirs(f"{source_dir}/templates", exist_ok=True)
    
    # Copy source files
    source_files = [
        ('../main.py', f'{source_dir}/main.py'),
        ('../control_panel.py', f'{source_dir}/control_panel.py'),
        ('../config.py', f'{source_dir}/config.py'),
        ('../remote_control.py', f'{source_dir}/remote_control.py'),
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
                    f"{source_dir}/templates/{template}"
                )
    
    # Create tarball
    subprocess.run([
        'tar', 'czf', f'{build_dir}/SOURCES/{package_name}-{version}.tar.gz',
        '-C', f'{build_dir}/SOURCES', f'{package_name}-{version}'
    ], check=True)
    
    # Create RPM spec file
    spec_content = f"""Name:           {package_name}
Version:        {version}
Release:        {release}%{{?dist}}
Summary:        Share files over WiFi network

License:        MIT
URL:            https://github.com/realwebthings/fileshare
Source0:        %{{name}}-%{{version}}.tar.gz

BuildArch:      noarch
Requires:       python3 >= 3.6
Requires:       python3-cryptography

%description
A simple HTTP server to share files between devices on the same network.
Supports both command-line and GUI modes for easy file sharing.

%prep
%setup -q

%build
# Nothing to build

%install
rm -rf $RPM_BUILD_ROOT

# Create directories
mkdir -p $RPM_BUILD_ROOT/usr/share/fileshare/templates
mkdir -p $RPM_BUILD_ROOT/usr/bin
mkdir -p $RPM_BUILD_ROOT/usr/share/applications

# Install files
cp *.py $RPM_BUILD_ROOT/usr/share/fileshare/
cp templates/*.html $RPM_BUILD_ROOT/usr/share/fileshare/templates/

# Create launcher scripts
cat > $RPM_BUILD_ROOT/usr/bin/fileshare << 'EOF'
#!/bin/bash
cd /usr/share/fileshare
export FILESHARE_DB_PATH="$HOME/.fileshare/users.db"
mkdir -p "$HOME/.fileshare"
python3 main.py "$@"
EOF

cat > $RPM_BUILD_ROOT/usr/bin/fileshare-gui << 'EOF'
#!/bin/bash
cd /usr/share/fileshare
python3 control_panel.py
EOF

chmod +x $RPM_BUILD_ROOT/usr/bin/fileshare
chmod +x $RPM_BUILD_ROOT/usr/bin/fileshare-gui

# Create desktop entry
cat > $RPM_BUILD_ROOT/usr/share/applications/fileshare.desktop << 'EOF'
[Desktop Entry]
Name=FileShare
Comment=Share files over WiFi
Exec=fileshare-gui
Icon=folder-remote
Terminal=false
Type=Application
Categories=Network;FileTransfer;
EOF

%files
%defattr(-,root,root,-)
/usr/share/fileshare/
/usr/bin/fileshare
/usr/bin/fileshare-gui
/usr/share/applications/fileshare.desktop

%changelog
* Wed Jan 01 2024 FileShare Team <contact@fileshare.app> - {version}-{release}
- Initial RPM package
"""
    
    with open(f"{build_dir}/SPECS/{package_name}.spec", 'w') as f:
        f.write(spec_content)
    
    # Build RPM
    try:
        subprocess.run([
            'rpmbuild', '--define', f'_topdir {os.path.abspath(build_dir)}',
            '-ba', f'{build_dir}/SPECS/{package_name}.spec'
        ], check=True)
        
        # Find generated RPM
        rpm_file = None
        for root, dirs, files in os.walk(f"{build_dir}/RPMS"):
            for file in files:
                if file.endswith('.rpm'):
                    rpm_file = os.path.join(root, file)
                    break
        
        if rpm_file:
            size = os.path.getsize(rpm_file)
            print(f"✅ Created: {rpm_file} ({size:,} bytes)")
            print(f"📋 Install with: sudo rpm -i {os.path.basename(rpm_file)}")
            return rpm_file
        else:
            print("❌ RPM file not found")
            return None
            
    except subprocess.CalledProcessError:
        print("❌ rpmbuild failed. Install with: sudo dnf install rpm-build")
        return None
    except FileNotFoundError:
        print("❌ rpmbuild not found. Install with: sudo dnf install rpm-build")
        return None

if __name__ == "__main__":
    build_rpm_package()