#!/usr/bin/env python3
"""
Optional update checker.

This checks the project's GitHub releases feed in the background and prints
a notice if a newer version is available. It never blocks the running server
and never shuts it down on its own - the previous version of this file could
forcibly sys.exit() the whole app based on remote data, which is a
phone-home/kill-switch pattern users weren't told about. That behavior has
been removed; this is now a passive, informational check only.

Set FILESHARE_DISABLE_UPDATE_CHECK=1 to turn it off entirely.
"""
try:
    import requests
except ImportError:
    requests = None
import os
import time
import threading

class RemoteControl:
    def __init__(self, control_url="https://api.github.com/repos/realwebthings/fileshare/releases/latest"):
        self.control_url = control_url
        self.current_version = "1.0.0"
        self.check_interval = 3600  # 1 hour
        self.running = True
        self.enabled = os.environ.get('FILESHARE_DISABLE_UPDATE_CHECK', '') not in ('1', 'true', 'yes')

    def check_remote_commands(self):
        """Check for a newer release and print an informational notice only."""
        if not requests or not self.enabled:
            return
        try:
            response = requests.get(self.control_url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                latest_version = data.get('tag_name', '').lstrip('v')
                if self.is_newer_version(latest_version):
                    self.notify_update_available(data)
        except Exception:
            # Silently fail - this is a best-effort convenience check
            pass

    def is_newer_version(self, remote_version):
        """Compare versions"""
        try:
            current = [int(x) for x in self.current_version.split('.')]
            remote = [int(x) for x in remote_version.split('.')]
            return remote > current
        except (ValueError, AttributeError):
            return False

    def notify_update_available(self, release_data):
        """Print a one-time, non-blocking notice. Does not stop the server."""
        print("\n" + "="*50)
        print("ℹ️  UPDATE AVAILABLE")
        print("="*50)
        print(f"New version available: {release_data.get('tag_name', 'Unknown')}")
        print(f"Download: {release_data.get('html_url', 'Check GitHub')}")
        print("The server will keep running on the current version.")
        print("="*50 + "\n")

    def start_background_check(self):
        """Start background thread for periodic update checks"""
        if not self.enabled:
            return
        def check_loop():
            while self.running:
                self.check_remote_commands()
                time.sleep(self.check_interval)

        thread = threading.Thread(target=check_loop, daemon=True)
        thread.start()

    def stop(self):
        """Stop the background update check"""
        self.running = False
