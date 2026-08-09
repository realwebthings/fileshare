#!/usr/bin/env python3
import webbrowser
import threading
import time
import os
import socket
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Optional

# Import main server module
main_server = None
try:
    import main as main_server
except ImportError:
    try:
        # Try importing from current directory if main.py exists
        import sys
        import os
        current_dir = os.path.dirname(os.path.abspath(__file__))
        if os.path.exists(os.path.join(current_dir, 'main.py')):
            sys.path.insert(0, current_dir)
            import main as main_server
        else:
            raise ImportError("main.py not found")
    except ImportError:
        print("❌ Main server module not found")
        main_server = None

class ControlPanelHandler(BaseHTTPRequestHandler):
    server_thread = None
    server_instance = None
    _admin_password_cache = None
    control_server: Optional['HTTPServer'] = None  # Reference to control panel server
    
    def do_GET(self):
        if self.path == '/':
            self.send_control_panel()
        elif self.path == '/start':
            self.start_file_server()
        elif self.path == '/stop':
            self.stop_file_server()
        elif self.path == '/quit':
            self.quit_application()
        elif self.path == '/status':
            self.send_status()
        else:
            self.send_error(404)
    
    def get_template_path(self, template_name):
        """Get template path for both development and packaged app"""
        if getattr(sys, 'frozen', False):
            base_path = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
        else:
            base_path = os.path.dirname(os.path.abspath(__file__))
        
        # Try multiple possible locations
        possible_paths = [
            os.path.join(base_path, 'templates', template_name),
            os.path.join(base_path, 'app', 'templates', template_name),
            os.path.join(os.path.dirname(base_path), 'templates', template_name)
        ]
        
        for path in possible_paths:
            if os.path.exists(path):
                return path
        
        # Fallback to first path if none found
        return possible_paths[0]
    
    def get_scheme(self):
        """Best-effort scheme for display: reflects the running server once
        started, otherwise guesses based on whether TLS support is installed."""
        if main_server is not None and getattr(main_server.AuthFileHandler, 'USE_SECURE_COOKIE', False):
            return 'https'
        try:
            import cryptography  # noqa: F401
            return 'https'
        except ImportError:
            return 'http'

    def send_control_panel(self):
        local_ip = self.get_local_ip()
        admin_password = self.get_admin_password()
        scheme = self.get_scheme()

        try:
            template_path = self.get_template_path('control_panel.html')
            with open(template_path, 'r', encoding='utf-8') as f:
                html = f.read()

            # Replace placeholders
            html = html.replace('{scheme}', scheme)
            html = html.replace('{local_ip}', local_ip)
            html = html.replace('{admin_password}', admin_password or 'Will be created when server starts')
            html = html.replace('{password_note}',
                              '<p><small>⚠️ Save this password - it will be cleared when server stops</small></p>' if admin_password else '')

        except FileNotFoundError as e:
            self.send_error(500, f"Template file not found: {e}")
            return
        
        self.send_response(200)
        self.send_header('Content-type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(html.encode('utf-8'))
    
    def start_file_server(self):
        if ControlPanelHandler.server_thread and ControlPanelHandler.server_thread.is_alive():
            message = "Server is already running!"
        else:
            if not main_server:
                message = "❌ Main server module not found. Please reinstall the application."
            else:
                try:
                    def run_server():
                        try:
                            if not main_server:
                                raise ImportError("Main server module not available")
                            
                            # Set database path for packaged apps
                            if getattr(sys, 'frozen', False):
                                db_path = os.path.expanduser('~/fileShare_users.db')
                                os.environ['FILESHARE_DB_PATH'] = db_path
                                main_server.AuthFileHandler.DB_FILE = db_path
                            
                            # Initialize database and create server
                            main_server.AuthFileHandler.init_db()
                            threading.Thread(
                                target=main_server.AuthFileHandler.sweep_stale_uploads, daemon=True
                            ).start()
                            local_ip = self.get_local_ip()
                            ssl_context = main_server.build_ssl_context(local_ip=local_ip)
                            main_server.AuthFileHandler.USE_SECURE_COOKIE = bool(ssl_context)
                            port = main_server.Config.DEFAULT_PORT
                            host = main_server.Config.HOST
                            ControlPanelHandler.server_instance = main_server.create_server(port, host, ssl_context)
                            ControlPanelHandler.server_instance.serve_forever()
                        except Exception as e:
                            print(f"❌ Server error: {e}")
                    
                    ControlPanelHandler.server_thread = threading.Thread(target=run_server, daemon=True)
                    ControlPanelHandler.server_thread.start()
                    time.sleep(1)  # Give more time for server to start
                    message = "Server started successfully!"
                except Exception as e:
                    print(f"❌ Start server error: {e}")
                    import traceback
                    traceback.print_exc()
                    message = f"Failed to start server: {str(e)}"
        
        template_path = self.get_template_path('message.html')
        with open(template_path, 'r', encoding='utf-8') as f:
            html = f.read()
        html = html.replace('{message}', message)
        
        self.send_response(200)
        self.send_header('Content-type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(html.encode('utf-8'))
    
    def stop_file_server(self):
        if ControlPanelHandler.server_instance:
            ControlPanelHandler.server_instance.shutdown()
            ControlPanelHandler.server_instance = None
            ControlPanelHandler.server_thread = None
            # Clean up admin password file
            if main_server is not None:
                try:
                    main_server.cleanup_admin_password()
                except AttributeError:
                    pass  # Function may not exist in all versions
            message = "Server stopped successfully!"
        else:
            message = "Server is not running!"
        
        template_path = self.get_template_path('message.html')
        with open(template_path, 'r', encoding='utf-8') as f:
            html = f.read()
        html = html.replace('{message}', message)
        
        self.send_response(200)
        self.send_header('Content-type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(html.encode('utf-8'))
    
    def send_status(self):
        running = ControlPanelHandler.server_thread is not None and ControlPanelHandler.server_thread.is_alive()
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        self.wfile.write(f'{{"running": {str(running).lower()}}}'.encode())
    
    def get_local_ip(self):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except:
            return "127.0.0.1"
    
    def get_admin_password(self):
        # Only show password if server is running
        if (ControlPanelHandler.server_thread and 
            ControlPanelHandler.server_thread.is_alive() and 
            main_server is not None):
            return main_server.AuthFileHandler.get_admin_password()
        return None
    
    def quit_application(self):
        # Stop file server if running
        if ControlPanelHandler.server_instance:
            ControlPanelHandler.server_instance.shutdown()
            if main_server is not None:
                try:
                    main_server.cleanup_admin_password()
                except AttributeError:
                    pass  # Function may not exist in all versions
        
        # Send response
        message = "Application shutting down..."
        template_path = self.get_template_path('message.html')
        with open(template_path, 'r', encoding='utf-8') as f:
            html = f.read()
        html = html.replace('{message}', message)
        
        self.send_response(200)
        self.send_header('Content-type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(html.encode('utf-8'))
        
        # Shutdown control panel server after response
        def shutdown_server():
            time.sleep(1)
            if ControlPanelHandler.control_server:
                ControlPanelHandler.control_server.shutdown()
        
        threading.Thread(target=shutdown_server, daemon=True).start()

def main():
    # Setup logging for packaged desktop apps (macOS/Windows) that have no
    # attached console to print to.
    if getattr(sys, 'frozen', False):
        desktop_dir = os.path.expanduser('~/Desktop')
        log_dir = desktop_dir if os.path.isdir(desktop_dir) else os.path.expanduser('~')
        log_file = os.path.join(log_dir, 'fileShare_debug.log')

        class Logger:
            def __init__(self, filename):
                # Packaged --windowed apps can have sys.stdout set to None
                # (no console attached) - guard against that instead of
                # crashing on the first print().
                self.terminal = sys.stdout
                self.log = open(filename, 'w', encoding='utf-8')
            def write(self, message):
                if self.terminal is not None:
                    try:
                        self.terminal.write(message)
                    except OSError:
                        pass
                self.log.write(message)
                self.log.flush()
            def flush(self):
                if self.terminal is not None:
                    try:
                        self.terminal.flush()
                    except OSError:
                        pass
        try:
            sys.stdout = Logger(log_file)
            sys.stderr = sys.stdout
            print(f"Debug log: {log_file}")
        except OSError as e:
            pass  # No writable location for a debug log - just run without one
    
    PORT = 9000
    server = HTTPServer(('127.0.0.1', PORT), ControlPanelHandler)
    ControlPanelHandler.control_server = server  # Store reference
    
    print(f"🎛️  FileShare Control Panel starting...")
    print(f"📱 Opening control panel in browser...")
    
    # Open browser after a short delay
    def open_browser():
        time.sleep(1)
        webbrowser.open(f'http://127.0.0.1:{PORT}')
    
    threading.Thread(target=open_browser, daemon=True).start()
    
    try:
        server.serve_forever()
    except (KeyboardInterrupt, OSError):
        print("\n🛑 Shutting down FileShare...")
        try:
            if ControlPanelHandler.server_instance:
                ControlPanelHandler.server_instance.shutdown()
                if main_server is not None:
                    try:
                        main_server.cleanup_admin_password()
                    except AttributeError:
                        pass
        except:
            pass
        try:
            server.shutdown()
            server.server_close()
        except:
            pass

if __name__ == "__main__":
    main()