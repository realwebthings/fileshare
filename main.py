#!/usr/bin/env python3
"""
Secure File Share Server - Main authentication and file serving module
"""
import os
import sys
import socket
import secrets
import hashlib
import time
import sqlite3
import ssl
import re
import shutil
import threading
import uuid
import html as html_lib
import json
from http.server import HTTPServer, SimpleHTTPRequestHandler
from socketserver import ThreadingMixIn
import urllib.parse


def esc(value):
    """HTML-escape a value for safe interpolation into markup/attributes."""
    return html_lib.escape(str(value), quote=True)


def esc_js(value):
    """Escape a value for safe embedding as a single-quoted JS string literal
    inside a double-quoted HTML attribute, e.g. onclick="fn('...')"."""
    inner = json.dumps(str(value))[1:-1]
    inner = inner.replace("'", "\\'")
    return html_lib.escape(inner, quote=True)


IS_WINDOWS = sys.platform.startswith('win')


def list_windows_drives():
    """Available drive letters, e.g. ['C:\\\\', 'D:\\\\']. Windows has no
    single filesystem root, so the app's virtual '/' root lists drives
    here instead of calling os.listdir('/') (which would silently just
    show the current drive's root and hide everything else)."""
    import string
    return [f'{letter}:\\' for letter in string.ascii_uppercase if os.path.exists(f'{letter}:\\')]


def is_drive_root(path):
    """True for a Windows drive root like 'C:\\' or 'C:'."""
    return IS_WINDOWS and re.match(r'^[A-Za-z]:\\?$', path) is not None

# Import configuration. Tried in order: flat layout (how this app is
# actually packaged - see linux/build-*.py), namespaced "app" layout, then
# an inline fallback so the server still runs if config.py is missing.
try:
    from config import Config
except ImportError:
    try:
        from app.config import Config
    except ImportError:
        class Config:
            DEFAULT_PORT = 8000
            TOKEN_EXPIRY_HOURS = 1
            RATE_LIMIT_ATTEMPTS = 5
            RATE_LIMIT_WINDOW_MINUTES = 2
            SHARED_PATHS_CACHE_SECONDS = 30
            HOST = '0.0.0.0'
            MAX_UPLOAD_SIZE_MB = 2048
            UPLOAD_CHUNK_SIZE_MB = 8
            STALE_UPLOAD_HOURS = 48

            @classmethod
            def get_db_path(cls):
                if getattr(sys, 'frozen', False):
                    return os.path.expanduser('~/fileShare_users.db')
                return os.environ.get('FILESHARE_DB_PATH', 'users.db')

# Import remote control (optional)
try:
    from app.remote_control import RemoteControl
except ImportError:
    try:
        from remote_control import RemoteControl
    except ImportError:
        RemoteControl = None

class AuthFileHandler(SimpleHTTPRequestHandler):
    VALID_TOKENS = {}  # token -> {user, expires}
    FAILED_ATTEMPTS = {}
    DB_FILE = Config.get_db_path()
    ADMIN_PASSWORD = None  # Store admin password in memory
    ADMIN_NOTIFICATIONS = []  # Store admin notifications
    ACTIVE_USERS = {}  # token -> {user, last_activity, ip, user_agent}
    SHARED_PATHS_CACHE = None  # Cache shared paths to avoid repeated DB queries
    CACHE_TIMESTAMP = 0  # Track when cache was last updated
    USE_SECURE_COOKIE = False  # Set True at startup when serving over TLS

    # Chunked/resumable upload tracking. Unlike the older class-level dicts
    # above (VALID_TOKENS/ACTIVE_USERS), these are mutated many times per
    # second per active transfer, so they get real locks rather than
    # relying on GIL-level informal safety.
    TRANSFERS = {}          # upload_id -> {batch_id, user, relative_path, dest_dir,
                             #   total_bytes, bytes_done, status, started_at, updated_at}
    TRANSFERS_LOCK = threading.Lock()
    UPLOAD_LOCKS = {}       # upload_id -> threading.Lock(), created on demand
    UPLOAD_LOCKS_GUARD = threading.Lock()
    RESERVED_BYTES = {}     # mount_key -> bytes reserved by in-flight uploads
    RESERVED_LOCK = threading.Lock()
    UPLOAD_STAGING_DIRNAME = '.fileshare_uploads'

    def add_security_headers(self):
        """Add security headers to response"""
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('X-XSS-Protection', '1; mode=block')
        self.send_header('Referrer-Policy', 'strict-origin-when-cross-origin')
        self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
    
    def get_template_path(self, template_name):
        """Get template path for both development and packaged app"""
        if hasattr(sys, '_MEIPASS'):
            # Running as packaged app
            return os.path.join(sys._MEIPASS, 'templates', template_name)  # type: ignore
        else:
            # Running as script
            return os.path.join('templates', template_name)
    
    @classmethod
    def get_admin_password(cls):
        """Get current admin password from memory"""
        return cls.ADMIN_PASSWORD
    
    @classmethod
    def get_admin_password_file(cls):
        """Path to the local recovery file holding the admin password in
        plaintext (0600 permissions). This is the only place the password is
        recoverable from after the process exits, since the DB only stores
        a salted hash."""
        base_dir = os.path.dirname(os.path.abspath(cls.DB_FILE)) or '.'
        return os.path.join(base_dir, 'admin_password.txt')

    @classmethod
    def _write_admin_password_file(cls, password):
        password_file = cls.get_admin_password_file()
        try:
            with open(password_file, 'w', encoding='utf-8') as pf:
                pf.write(password + '\n')
            os.chmod(password_file, 0o600)
        except OSError as e:
            print(f"⚠️  Could not write admin password recovery file: {e}")
        return password_file

    @classmethod
    def reset_admin_password(cls):
        """Force-generate a brand new admin password, e.g. via --reset-admin-password."""
        admin_password = str(uuid.uuid4())
        admin_salt = secrets.token_hex(16)
        admin_hash = hashlib.pbkdf2_hmac('sha256', admin_password.encode(), admin_salt.encode(), 100000)

        conn = sqlite3.connect(cls.DB_FILE)
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM users WHERE username = ?', ('admin',))
        if cursor.fetchone()[0] == 0:
            cursor.execute('INSERT INTO users (username, password_hash, salt, is_approved) VALUES (?, ?, ?, 1)',
                         ('admin', admin_hash.hex(), admin_salt))
        else:
            cursor.execute('UPDATE users SET password_hash = ?, salt = ? WHERE username = ?',
                         (admin_hash.hex(), admin_salt, 'admin'))
        conn.commit()
        conn.close()

        cls.ADMIN_PASSWORD = admin_password
        password_file = cls._write_admin_password_file(admin_password)
        print(f"\n*** NEW ADMIN PASSWORD: {admin_password} ***")
        print(f"*** Saved to: {password_file} ***\n")
        return admin_password

    @classmethod
    def init_db(cls):
        conn = sqlite3.connect(cls.DB_FILE)
        # Ensure database file has proper permissions on Linux
        try:
            os.chmod(cls.DB_FILE, 0o644)
        except (OSError, AttributeError):
            pass  # Ignore permission errors
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                is_approved BOOLEAN DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Create shared_paths table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS shared_paths (
                id INTEGER PRIMARY KEY,
                path TEXT UNIQUE NOT NULL,
                shared_by TEXT NOT NULL,
                is_file BOOLEAN DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Add is_file column if it doesn't exist (migration)
        try:
            cursor.execute('ALTER TABLE shared_paths ADD COLUMN is_file BOOLEAN DEFAULT 0')
        except sqlite3.OperationalError:
            pass  # Column already exists

        # Chunked/resumable upload bookkeeping - lets an interrupted large
        # transfer resume after a server restart, not just a browser reload.
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS uploads (
                upload_id TEXT PRIMARY KEY,
                batch_id TEXT,
                username TEXT NOT NULL,
                dest_dir TEXT NOT NULL,
                relative_path TEXT NOT NULL,
                final_path TEXT NOT NULL,
                temp_path TEXT NOT NULL,
                total_size INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Remove password_plain column if it exists (security fix)
        try:
            cursor.execute('SELECT password_plain FROM users LIMIT 1')
            # Column exists, remove it
            cursor.execute('CREATE TABLE users_new AS SELECT id, username, password_hash, salt, is_approved, created_at FROM users')
            cursor.execute('DROP TABLE users')
            cursor.execute('ALTER TABLE users_new RENAME TO users')
            print("🔒 Removed plain text password storage for security")
        except sqlite3.OperationalError:
            pass  # Column doesn't exist
        
        # Only create the admin account (and its password) once. Regenerating
        # it on every restart meant any headless/service deployment had no
        # way to ever learn or reuse the current password.
        cursor.execute('SELECT COUNT(*) FROM users WHERE username = ?', ('admin',))
        admin_exists = cursor.fetchone()[0] > 0

        if not admin_exists:
            admin_password = str(uuid.uuid4())
            admin_salt = secrets.token_hex(16)
            admin_hash = hashlib.pbkdf2_hmac('sha256', admin_password.encode(), admin_salt.encode(), 100000)
            cursor.execute('INSERT INTO users (username, password_hash, salt, is_approved) VALUES (?, ?, ?, 1)',
                         ('admin', admin_hash.hex(), admin_salt))
            cls.ADMIN_PASSWORD = admin_password
            password_file = cls._write_admin_password_file(admin_password)
            print(f"\n*** ADMIN PASSWORD: {admin_password} ***")
            print(f"*** Saved to: {password_file} (also shown here once - save it now) ***\n")
        else:
            # Recover the plaintext from the local recovery file written on
            # first run, if it's still there, so the console/control panel
            # can keep displaying it. The DB itself only ever stores a hash.
            try:
                with open(cls.get_admin_password_file(), 'r', encoding='utf-8') as pf:
                    cls.ADMIN_PASSWORD = pf.read().strip() or None
            except OSError:
                cls.ADMIN_PASSWORD = None
            print("\n*** Admin account already exists - password unchanged ***")
            if cls.ADMIN_PASSWORD:
                print(f"*** Password recovery file: {cls.get_admin_password_file()} ***")
            else:
                print("*** Recovery file not found. Run with --reset-admin-password to set a new one ***")

        conn.commit()
        conn.close()
        cls.rebuild_transfers_from_db()

    @classmethod
    def rebuild_transfers_from_db(cls):
        """Restore in-progress upload tracking after a server restart. The
        DB row plus the .part file's real on-disk size is the source of
        truth - not any in-memory counter - so resuming after a crash/
        restart works the same way as resuming after a browser reload."""
        try:
            conn = sqlite3.connect(cls.DB_FILE, timeout=5.0)
            cursor = conn.cursor()
            cursor.execute('''SELECT upload_id, batch_id, username, dest_dir, relative_path,
                                      final_path, temp_path, total_size
                               FROM uploads WHERE status = 'active' ''')
            rows = cursor.fetchall()
        except sqlite3.Error as e:
            print(f"Database error rebuilding transfers: {e}")
            return
        finally:
            conn.close()

        restored = 0
        for upload_id, batch_id, username, dest_dir, relative_path, final_path, temp_path, total_size in rows:
            if not os.path.exists(temp_path):
                cls._mark_upload_status(upload_id, 'aborted')
                continue
            bytes_done = os.path.getsize(temp_path)
            with cls.TRANSFERS_LOCK:
                cls.TRANSFERS[upload_id] = {
                    'upload_id': upload_id, 'batch_id': batch_id, 'user': username,
                    'dest_dir': dest_dir, 'relative_path': relative_path,
                    'final_path': final_path, 'temp_path': temp_path,
                    'total_bytes': total_size, 'bytes_done': bytes_done,
                    'status': 'active', 'started_at': time.time(), 'updated_at': time.time(),
                }
            cls._reserve_bytes(dest_dir, max(total_size - bytes_done, 0))
            restored += 1
        if restored:
            print(f"🔁 Restored {restored} in-progress upload(s) - clients can resume via HEAD /api/upload/<id>")

    @classmethod
    def _mark_upload_status(cls, upload_id, status):
        try:
            conn = sqlite3.connect(cls.DB_FILE, timeout=5.0)
            cursor = conn.cursor()
            cursor.execute('UPDATE uploads SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE upload_id = ?',
                         (status, upload_id))
            conn.commit()
        except sqlite3.Error as e:
            print(f"Database error updating upload status: {e}")
        finally:
            try:
                conn.close()
            except Exception:
                pass

    @classmethod
    def get_shared_paths(cls):
        """Get shared paths from database with caching"""
        current_time = time.time()
        # Cache for configured seconds to improve performance
        if cls.SHARED_PATHS_CACHE is None or (current_time - cls.CACHE_TIMESTAMP) > Config.SHARED_PATHS_CACHE_SECONDS:
            try:
                conn = sqlite3.connect(cls.DB_FILE, timeout=5.0)
                cursor = conn.cursor()
                cursor.execute('SELECT path, is_file FROM shared_paths')
                cls.SHARED_PATHS_CACHE = {row[0]: bool(row[1]) for row in cursor.fetchall()}
                cls.CACHE_TIMESTAMP = current_time
            except sqlite3.Error as e:
                print(f"Database error in get_shared_paths: {e}")
                cls.SHARED_PATHS_CACHE = {}
            finally:
                try:
                    conn.close()
                except:
                    pass
        return cls.SHARED_PATHS_CACHE
    
    @classmethod
    def invalidate_shared_paths_cache(cls):
        """Invalidate cache when paths are modified"""
        cls.SHARED_PATHS_CACHE = None
        cls.CACHE_TIMESTAMP = 0
    
    @classmethod
    def create_user(cls, username, password):
        salt = secrets.token_hex(16)
        password_hash = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100000)
        
        try:
            conn = sqlite3.connect(cls.DB_FILE, timeout=5.0)
            cursor = conn.cursor()
            # Explicitly set is_approved=0 to ensure user needs admin approval
            cursor.execute('INSERT INTO users (username, password_hash, salt, is_approved) VALUES (?, ?, ?, 0)',
                         (username, password_hash.hex(), salt))
            conn.commit()
            print(f"Created user '{username}' - waiting for admin approval")
            return True
        except sqlite3.IntegrityError:
            return False
        except sqlite3.Error as e:
            print(f"Database error creating user: {e}")
            return False
        finally:
            try:
                conn.close()
            except:
                pass
    
    @classmethod
    def verify_user(cls, username, password):
        try:
            conn = sqlite3.connect(cls.DB_FILE, timeout=5.0)  # Add timeout
            cursor = conn.cursor()
            cursor.execute('SELECT password_hash, salt, is_approved FROM users WHERE username = ?', (username,))
            result = cursor.fetchone()
            conn.close()
            
            if not result:
                return False, 'User not found'
            
            stored_hash, salt, is_approved = result
            
            # Quick approval check first
            if not is_approved:
                return False, 'Account pending approval'
            
            # Then verify password
            password_hash = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100000)
            
            if password_hash.hex() != stored_hash:
                return False, 'Invalid password'
            
            return True, 'Success'
        except sqlite3.Error as e:
            print(f"Database error during login: {e}")
            return False, 'Database error - please try again'
    
    def generate_token(self, username):
        token = secrets.token_urlsafe(32)
        expires = time.time() + (Config.TOKEN_EXPIRY_HOURS * 3600)
        self.VALID_TOKENS[token] = {'user': username, 'expires': expires}
        return token
    
    def check_rate_limit(self, client_ip, bypass_admin=False):
        """Simple rate limit check - only used for admin operations now"""
        if bypass_admin:
            return True
            
        if client_ip in self.FAILED_ATTEMPTS:
            attempts, last_attempt = self.FAILED_ATTEMPTS[client_ip]
            # Clear expired attempts
            if time.time() - last_attempt > 120:
                del self.FAILED_ATTEMPTS[client_ip]
                return True
            # Block if max attempts reached
            return attempts < Config.RATE_LIMIT_ATTEMPTS
        return True
    
    def record_failed_attempt(self, client_ip):
        now = time.time()
        if client_ip in self.FAILED_ATTEMPTS:
            attempts, _ = self.FAILED_ATTEMPTS[client_ip]
            new_attempts = attempts + 1
            self.FAILED_ATTEMPTS[client_ip] = (new_attempts, now)
            print(f"DEBUG: Recorded failed attempt for {client_ip}: {new_attempts} total attempts")
        else:
            self.FAILED_ATTEMPTS[client_ip] = (1, now)
            print(f"DEBUG: First failed attempt recorded for {client_ip}")
    
    @classmethod
    def clear_rate_limit(cls, client_ip=None):
        """Clear rate limiting for specific IP or all IPs"""
        print(f"DEBUG: clear_rate_limit called with client_ip={client_ip}")
        print(f"DEBUG: Current FAILED_ATTEMPTS: {cls.FAILED_ATTEMPTS}")
        
        if client_ip:
            if client_ip in cls.FAILED_ATTEMPTS:
                del cls.FAILED_ATTEMPTS[client_ip]
                print(f"✅ Rate limit cleared for {client_ip}")
                print(f"DEBUG: After clearing, FAILED_ATTEMPTS: {cls.FAILED_ATTEMPTS}")
                cls.ADMIN_NOTIFICATIONS.append(f"Rate limit cleared for {client_ip}")
            else:
                print(f"⚠️  No rate limit found for {client_ip}")
                cls.ADMIN_NOTIFICATIONS.append(f"No rate limit found for {client_ip}")
        else:
            count = len(cls.FAILED_ATTEMPTS)
            cls.FAILED_ATTEMPTS.clear()
            print(f"✅ All rate limits cleared ({count} IPs)")
            print(f"DEBUG: After clearing all, FAILED_ATTEMPTS: {cls.FAILED_ATTEMPTS}")
            cls.ADMIN_NOTIFICATIONS.append(f"All rate limits cleared ({count} IPs)")
    
    COOKIE_NAME = 'session_token'

    def get_cookie_token(self):
        """Read the session token from the Cookie header, if present."""
        cookie_header = self.headers.get('Cookie', '')
        for part in cookie_header.split(';'):
            part = part.strip()
            if part.startswith(f'{self.COOKIE_NAME}='):
                return part[len(self.COOKIE_NAME) + 1:]
        return None

    def set_session_cookie(self, token):
        """Set the HttpOnly session cookie on the current response."""
        max_age = int(Config.TOKEN_EXPIRY_HOURS * 3600)
        secure = '; Secure' if self.USE_SECURE_COOKIE else ''
        self.send_header(
            'Set-Cookie',
            f'{self.COOKIE_NAME}={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={max_age}{secure}'
        )

    def clear_session_cookie(self):
        """Expire the session cookie on the current response."""
        secure = '; Secure' if self.USE_SECURE_COOKIE else ''
        self.send_header(
            'Set-Cookie',
            f'{self.COOKIE_NAME}=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0{secure}'
        )

    def _resolve_token(self, token):
        if not token or token not in self.VALID_TOKENS:
            return None
        token_data = self.VALID_TOKENS[token]
        if time.time() >= token_data['expires']:
            # Clean up expired token
            del self.VALID_TOKENS[token]
            if token in self.ACTIVE_USERS:
                del self.ACTIVE_USERS[token]
            return None
        # Update active user tracking
        self.ACTIVE_USERS[token] = {
            'user': token_data['user'],
            'last_activity': time.time(),
            'ip': self.client_address[0],
            'user_agent': self.headers.get('User-Agent', 'Unknown')[:50]
        }
        return token_data['user']

    def is_same_origin_request(self):
        """Defense-in-depth CSRF check for state-changing routes: if the
        browser sent an Origin/Referer header, it must match this host.
        Requests with no such header (direct navigation, curl, etc.) are
        allowed through - the primary defense is the SameSite=Strict cookie,
        which browsers refuse to attach to cross-site requests regardless."""
        host = self.headers.get('Host', '')
        origin = self.headers.get('Origin')
        referer = self.headers.get('Referer')
        source = origin or referer
        if not source:
            return True
        try:
            parsed = urllib.parse.urlparse(source)
        except ValueError:
            return False
        return parsed.netloc == host

    def check_token_auth(self):
        # Preferred: HttpOnly cookie set at login
        cookie_token = self.get_cookie_token()
        if cookie_token:
            user = self._resolve_token(cookie_token)
            if user:
                return user

        # Legacy fallback: token in the URL query string (old bookmarked links)
        if '?token=' in self.path:
            path_parts = self.path.split('?token=')
            if len(path_parts) == 2:
                self.path = path_parts[0]
                token = path_parts[1].split('&')[0]
                return self._resolve_token(token)
        return None

    def cleanup_expired_tokens(self):
        """Clean up expired tokens and active users"""
        now = time.time()
        expired_tokens = [token for token, data in self.VALID_TOKENS.items() if now >= data['expires']]
        for token in expired_tokens:
            del self.VALID_TOKENS[token]
            if token in self.ACTIVE_USERS:
                del self.ACTIVE_USERS[token]
        
        # Also clean up inactive users (5 minutes)
        inactive_tokens = [token for token, data in self.ACTIVE_USERS.items() 
                          if now - data['last_activity'] > 300]
        for token in inactive_tokens:
            if token in self.ACTIVE_USERS:
                del self.ACTIVE_USERS[token]
    
    def format_size(self, size):
        """Format file size in human readable format"""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"
    
    def send_auth_page(self, error_msg=''):
        client_ip = self.client_address[0]
        
        # Only show rate limit message if user is actually rate limited AND this is after a failed attempt
        if error_msg and '❌' in error_msg:
            # Don't call check_rate_limit here - just check if IP is in FAILED_ATTEMPTS with >= 5 attempts
            if client_ip in self.FAILED_ATTEMPTS:
                attempts, last_attempt = self.FAILED_ATTEMPTS[client_ip]
                if attempts >= 5 and (time.time() - last_attempt) <= 120:
                    time_remaining = int(120 - (time.time() - last_attempt))
                    if time_remaining > 0:
                        error_msg = f'🚫 Too many failed login attempts ({attempts}). Please wait {time_remaining} seconds before trying again.'
                    else:
                        error_msg = '🚫 Too many failed login attempts. Please contact admin to clear rate limits.'
        
        try:
            template_path = self.get_template_path('login.html')
            with open(template_path, 'r', encoding='utf-8') as f:
                html = f.read()

            error_html = ''
            if error_msg:
                if '🚫' in error_msg:  # Rate limit message
                    error_html = f'<div style="background: #f8d7da; color: #721c24; padding: 15px; border-radius: 8px; margin: 15px 0; border: 1px solid #f5c6cb;"><strong>Rate Limited</strong><br>{esc(error_msg)}</div>'
                else:
                    error_html = f'<p style="color: red;">{esc(error_msg)}</p>'
            html = html.replace('{error_message}', error_html)

            self.send_response(200)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self.add_security_headers()
            self.end_headers()
            self.wfile.write(html.encode('utf-8'))
        except FileNotFoundError:
            self.send_error(500, "Template file not found")
    
    def send_welcome_page(self):
        try:
            # Handle both development and packaged app paths
            template_path = self.get_template_path('welcome.html')
            with open(template_path, 'r', encoding='utf-8') as f:
                html = f.read()
            
            self.send_response(200)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(html.encode('utf-8'))
        except FileNotFoundError:
            self.send_error(500, "Template file not found")
    
    def send_register_page(self, error_msg=''):
        try:
            template_path = self.get_template_path('register.html')
            with open(template_path, 'r', encoding='utf-8') as f:
                html = f.read()
            
            if error_msg:
                html = html.replace('<div class="requirements">',
                                  f'<div style="color: red; margin: 10px 0;">{error_msg}</div><div class="requirements">')
            
            self.send_response(200)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(html.encode('utf-8'))
        except FileNotFoundError:
            self.send_error(500, "Template file not found")
    
    def send_registration_success_page(self, username):
        """Send success page with popup-style message after registration"""
        html = f'''<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Registration Successful</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body {{ font-family: Arial, sans-serif; background: #f5f5f5; margin: 0; padding: 20px; }}
        .popup {{ background: white; max-width: 500px; margin: 50px auto; padding: 30px; border-radius: 10px; box-shadow: 0 4px 20px rgba(0,0,0,0.1); text-align: center; }}
        .success-icon {{ font-size: 60px; color: #28a745; margin-bottom: 20px; }}
        .title {{ color: #28a745; font-size: 24px; font-weight: bold; margin-bottom: 15px; }}
        .message {{ color: #666; font-size: 16px; line-height: 1.5; margin-bottom: 25px; }}
        .login-btn {{ background: #007bff; color: white; padding: 12px 30px; text-decoration: none; border-radius: 5px; font-size: 16px; display: inline-block; }}
        .login-btn:hover {{ background: #0056b3; }}
    </style>
</head>
<body>
    <div class="popup">
        <div class="success-icon">✅</div>
        <div class="title">Account Created Successfully!</div>
        <div class="message">
            Welcome <strong>{esc(username)}</strong>!<br><br>
            Your account has been created and is now <strong>pending admin approval</strong>.<br><br>
            You will be able to login once an administrator approves your account.<br>
            Please check back later or contact the administrator.
        </div>
        <a href="/login" class="login-btn">Go to Login Page</a>
    </div>
</body>
</html>'''
        
        self.send_response(200)
        self.send_header('Content-type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(html.encode('utf-8'))
    
    def do_POST(self):
        # Handled separately: these bodies are binary/JSON, not a urlencoded
        # text form, so they must not be blanket-decoded as UTF-8 like the
        # routes below do.
        if self.path == '/upload':
            self.handle_upload()
            return
        if self.path == '/api/upload/create':
            self.handle_upload_create()
            return
        if self.path == '/api/upload/batch/create':
            self.handle_upload_batch_create()
            return

        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length).decode()
        client_ip = self.client_address[0]

        if self.path == '/login':
            print(f"DEBUG: Login attempt from {client_ip}")
            
            # Parse form data first
            params = urllib.parse.parse_qs(post_data)
            username = params.get('username', [''])[0]
            password = params.get('password', [''])[0]
            
            # Always check and clear expired rate limits first
            now = time.time()
            if client_ip in self.FAILED_ATTEMPTS:
                attempts, last_attempt = self.FAILED_ATTEMPTS[client_ip]
                # Clear old attempts if window expired
                window_seconds = Config.RATE_LIMIT_WINDOW_MINUTES * 60
                if now - last_attempt > window_seconds:
                    print(f"DEBUG: Clearing expired attempts for {client_ip} (timeout reached)")
                    del self.FAILED_ATTEMPTS[client_ip]
                elif attempts >= Config.RATE_LIMIT_ATTEMPTS:
                    time_remaining = int(120 - (now - last_attempt))
                    print(f"DEBUG: Rate limit active for {client_ip} - {attempts} attempts, {time_remaining}s remaining")
                    self.send_auth_page(f'🚫 Too many failed attempts. Please wait {time_remaining} seconds before trying again.')
                    return
            
            print(f"DEBUG: Attempting login for username='{username}' from {client_ip}")
            success, message = self.verify_user(username, password)
            print(f"DEBUG: Login result: success={success}, message='{message}'")
            
            if success:
                # Clear any failed attempts on successful login
                if client_ip in self.FAILED_ATTEMPTS:
                    print(f"DEBUG: Clearing failed attempts for {client_ip} after successful login")
                    del self.FAILED_ATTEMPTS[client_ip]
                token = self.generate_token(username)
                print(f"DEBUG: Generated token for {username}, redirecting to main page")
                self.send_response(302)
                self.send_header('Location', '/')
                self.set_session_cookie(token)
                self.end_headers()
            else:
                print(f"DEBUG: Login failed for {username}: {message}")
                self.record_failed_attempt(client_ip)
                self.send_auth_page(f'❌ {message}')
        
        elif self.path == '/register':
            params = urllib.parse.parse_qs(post_data)
            username = params.get('username', [''])[0]
            password = params.get('password', [''])[0]
            
            print(f"DEBUG: Registration attempt for username='{username}' from {client_ip}")
            
            if len(username) < 3 or len(password) < 6:
                self.send_register_page('Username must be at least 3 characters and password at least 6 characters')
                return
            
            if self.create_user(username, password):
                print(f"DEBUG: User '{username}' created successfully - showing success popup")
                # Show dedicated success page with popup-style message
                self.send_registration_success_page(username)
            else:
                print(f"DEBUG: Failed to create user '{username}' - username already exists")
                self.send_register_page('❌ Username already exists. Please choose another.')
        else:
            self.send_error(404)
    
    def do_HEAD(self):
        """Handle HEAD requests: video streaming, and upload resume queries."""
        if self.path.startswith('/api/upload/'):
            upload_id = self.path[len('/api/upload/'):].split('?')[0]
            self.handle_upload_status(upload_id)
            return
        self.do_GET()

    def do_PATCH(self):
        """PATCH /api/upload/<id> - one chunk of a resumable upload."""
        if self.path.startswith('/api/upload/'):
            upload_id = self.path[len('/api/upload/'):].split('?')[0]
            self.handle_upload_chunk(upload_id)
        else:
            self.send_error(404)

    def do_DELETE(self):
        """DELETE /api/upload/<id> - cancel a resumable upload."""
        if self.path.startswith('/api/upload/'):
            upload_id = self.path[len('/api/upload/'):].split('?')[0]
            self.handle_upload_abort(upload_id)
        else:
            self.send_error(404)

    def do_GET(self):
        # Clean up expired tokens first
        self.cleanup_expired_tokens()
        
        # Handle rate limit clearing BEFORE token auth to avoid triggering rate limits
        if self.path.startswith('/admin/clear-rate-limit'):
            # Check token authentication for admin routes
            user = self.check_token_auth()
            if user == 'admin' and not self.is_same_origin_request():
                self.send_error(403, "Cross-origin request blocked")
                return
            if user == 'admin':
                if self.path == '/admin/clear-rate-limit':
                    print("Admin clearing ALL rate limits")
                    self.clear_rate_limit()
                    self.send_response(302)
                    self.send_header('Location', f'/admin/rate-limits')
                    self.end_headers()
                    return
                elif self.path.startswith('/admin/clear-rate-limit/'):
                    path_part = self.path[25:]  # Remove '/admin/clear-rate-limit/'
                    if '?' in path_part:
                        ip_to_clear = urllib.parse.unquote(path_part.split('?')[0])
                    else:
                        ip_to_clear = urllib.parse.unquote(path_part)
                    
                    print(f"Admin clearing rate limit for IP: {ip_to_clear}")
                    self.clear_rate_limit(ip_to_clear)
                    
                    
                    self.send_response(302)
                    self.send_header('Location', f'/admin/rate-limits')
                    self.end_headers()
                    return
            else:
                self.send_error(401, "Access denied")
                return
        
        # Check token authentication for other routes
        user = self.check_token_auth()

        MUTATING_ADMIN_PREFIXES = (
            '/admin/approve/', '/admin/reject/', '/admin/delete/',
            '/admin/reset-password/', '/admin/share-path/', '/admin/unshare-path/'
        )
        if (user == 'admin' and self.path.startswith(MUTATING_ADMIN_PREFIXES)
                and not self.is_same_origin_request()):
            self.send_error(403, "Cross-origin request blocked")
            return

        if self.path == '/api/transfers':
            self.send_transfers_json()
            return

        if self.path.startswith('/api/upload/'):
            upload_id = self.path[len('/api/upload/'):].split('?')[0]
            self.handle_upload_status(upload_id)
            return

        if self.path == '/register':
            self.send_register_page()
            return

        if self.path == '/admin' and user == 'admin':
            self.send_admin_page()
            return
        
        if self.path.startswith('/admin/approve/') and user == 'admin':
            user_id = self.path.split('/')[-1]
            self.approve_user(user_id)
            return
        
        if self.path.startswith('/admin/reject/') and user == 'admin':
            user_id = self.path.split('/')[-1]
            self.reject_user(user_id)
            return
        
        if self.path.startswith('/admin/delete/') and user == 'admin':
            user_id = self.path.split('/')[-1]
            self.delete_user(user_id)
            return
        
        if self.path.startswith('/admin/reset-password/') and user == 'admin':
            user_id = self.path.split('/')[-1]
            self.reset_user_password(user_id)
            return
        
        if self.path == '/admin/active-users' and user == 'admin':
            self.send_active_users_page()
            return
        
        if self.path == '/admin/shared-paths' and user == 'admin':
            self.send_shared_paths_page()
            return
        
        if self.path.startswith('/admin/share-path/') and user == 'admin':
            # Extract path from URL, handling both /admin/share-path/PATH and /admin/share-path/?token=...
            path_part = self.path[18:]  # Remove '/admin/share-path/'
            force_type = None
            
            if '?' in path_part:
                path_to_share = urllib.parse.unquote(path_part.split('?')[0])
                # Check for type parameter
                query_string = path_part.split('?')[1]
                query_params = urllib.parse.parse_qs(query_string)
                force_type = query_params.get('type', [None])[0]
            else:
                path_to_share = urllib.parse.unquote(path_part)
            
            if path_to_share:  # Only proceed if path is not empty
                self.add_shared_path(path_to_share, force_type)
            else:
                # Redirect back to shared paths page if no path provided
                self.send_response(302)
                self.send_header('Location', f'/admin/shared-paths')
                self.end_headers()
            return
        
        if self.path.startswith('/admin/unshare-path/') and user == 'admin':
            path_to_unshare = urllib.parse.unquote(self.path[20:])
            self.remove_shared_path(path_to_unshare)
            return
        
        if self.path == '/admin/rate-limits' and user == 'admin':
            self.send_rate_limits_page()
            return
        

        
        # Handle favicon requests without authentication
        if self.path == '/favicon.ico':
            self.send_error(404, "Not found")
            return

        if self.path == '/logout':
            cookie_token = self.get_cookie_token()
            if cookie_token and cookie_token in self.VALID_TOKENS:
                del self.VALID_TOKENS[cookie_token]
                if cookie_token in self.ACTIVE_USERS:
                    del self.ACTIVE_USERS[cookie_token]
            self.send_response(302)
            self.send_header('Location', '/login')
            self.clear_session_cookie()
            self.end_headers()
            return

        if not user:
            if self.path == '/':
                self.send_welcome_page()
            elif self.path == '/login':
                self.send_auth_page()
            elif self.path == '/register':
                self.send_register_page()
            else:
                self.send_error(401, "Access denied")
            return
        
        # File serving logic (same as before). On POSIX, decoded paths are
        # already rooted at '/' so stripping the route prefix removes that
        # leading slash and must restore it; on Windows a decoded path is
        # already absolute via its drive letter (e.g. 'C:\\Users\\...') and
        # must NOT get a '/' prepended, or it becomes an invalid path.
        if self.path.startswith('/download/'):
            file_path = self.path[10:] if IS_WINDOWS else '/' + self.path[10:]
            self.serve_download(file_path)
        elif self.path.startswith('/raw/'):
            file_path = self.path[5:] if IS_WINDOWS else '/' + self.path[5:]
            self.serve_raw(file_path)
        elif self.path == '/' or self.path == '':
            self.show_directory('/', user)
        else:
            path = urllib.parse.unquote(self.path)
            try:
                if os.path.isdir(path):
                    self.show_directory(path, user)
                elif os.path.isfile(path):
                    self.serve_file(path)
                else:
                    self.send_error(404, "File or directory not found")
            except (OSError, PermissionError):
                self.send_error(403, "Permission denied")
    
    def serve_file(self, file_path):
        # Check access for non-admin users
        user = self.check_token_auth()

        if user != 'admin' and not self.is_path_accessible(os.path.dirname(file_path), user):
            self.send_error(403, "Access denied - This file is not in a shared folder")
            return
            
        try:
            if os.path.getsize(file_path) == 0:
                self.send_error(400, "Cannot view empty file (0 bytes)")
                return
                
            ext = file_path.lower().split('.')[-1]
            content_types = {
                'html': 'text/html; charset=utf-8',
                'css': 'text/css; charset=utf-8',
                'json': 'application/json; charset=utf-8',
                'xml': 'application/xml; charset=utf-8',
                'jpg': 'image/jpeg',
                'jpeg': 'image/jpeg',
                'png': 'image/png',
                'gif': 'image/gif',
                'svg': 'image/svg+xml',
                'ico': 'image/x-icon',
                'avif': 'image/avif',
                'webp': 'image/webp',
                'pdf': 'application/pdf',
                'mp4': 'video/mp4',
                'webm': 'video/webm',
                'avi': 'video/x-msvideo',
                'mov': 'video/quicktime',
                'wmv': 'video/x-ms-wmv',
                'flv': 'video/x-flv',
                'mkv': 'video/x-matroska',
                'mp3': 'audio/mpeg',
                'wav': 'audio/wav',
                'ogg': 'audio/ogg',
                'flac': 'audio/flac'
            }
            
            content_type = content_types.get(ext, 'text/plain; charset=utf-8')
            
            # Handle range requests for video streaming
            if ext in ['mp4', 'webm', 'ogg', 'avi', 'mov', 'wmv', 'flv', 'mkv', 'mp3', 'wav', 'flac']:
                self.serve_video_stream(file_path, content_type)
            else:
                with open(file_path, 'rb') as f:
                    self.send_response(200)
                    self.send_header("Content-type", content_type)
                    self.end_headers()
                    self.wfile.write(f.read())
        except IOError:
            self.send_error(404, "File not found")
    
    def serve_video_stream(self, file_path, content_type):
        """Handle optimized video streaming with range requests"""
        try:
            file_size = os.path.getsize(file_path)
            range_header = self.headers.get('Range')
            
            # Optimal chunk size for streaming (1MB)
            CHUNK_SIZE = 1024 * 1024
            
            if range_header:
                # Parse range header
                range_match = range_header.replace('bytes=', '').split('-')
                start = int(range_match[0]) if range_match[0] else 0
                end = int(range_match[1]) if range_match[1] else min(start + CHUNK_SIZE - 1, file_size - 1)
                
                if start >= file_size:
                    self.send_error(416, "Range not satisfiable")
                    return
                
                end = min(end, file_size - 1)
                content_length = end - start + 1
                
                self.send_response(206)  # Partial Content
                self.send_header('Content-Type', content_type)
                self.send_header('Content-Length', str(content_length))
                self.send_header('Content-Range', f'bytes {start}-{end}/{file_size}')
                self.send_header('Accept-Ranges', 'bytes')
                self.send_header('Cache-Control', 'public, max-age=3600')
                self.send_header('Connection', 'keep-alive')
                self.send_header('Keep-Alive', 'timeout=5, max=100')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.send_header('Access-Control-Allow-Methods', 'GET, HEAD, OPTIONS')
                self.send_header('Access-Control-Allow-Headers', 'Range')
                self.end_headers()
                
                # Stream in smaller chunks for better performance
                with open(file_path, 'rb') as f:
                    f.seek(start)
                    remaining = content_length
                    while remaining > 0:
                        chunk_size = min(8192, remaining)  # 8KB chunks
                        chunk = f.read(chunk_size)
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        remaining -= len(chunk)
            else:
                # No range request, send with chunked encoding for better streaming
                self.send_response(200)
                self.send_header('Content-Type', content_type)
                self.send_header('Content-Length', str(file_size))
                self.send_header('Accept-Ranges', 'bytes')
                self.send_header('Cache-Control', 'public, max-age=3600')
                self.send_header('Connection', 'keep-alive')
                self.send_header('Keep-Alive', 'timeout=5, max=100')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                
                # Stream entire file in chunks
                with open(file_path, 'rb') as f:
                    while True:
                        chunk = f.read(8192)  # 8KB chunks
                        if not chunk:
                            break
                        self.wfile.write(chunk)
        except (IOError, BrokenPipeError):
            # Client disconnected, stop streaming
            pass
    
    def serve_raw(self, file_path):
        file_path = urllib.parse.unquote(file_path)

        user = self.check_token_auth()
        if user != 'admin' and not self.is_path_accessible(os.path.dirname(file_path), user):
            self.send_error(403, "Access denied - This file is not in a shared folder")
            return

        try:
            if os.path.getsize(file_path) == 0:
                self.send_error(400, "Cannot view empty file (0 bytes)")
                return
                
            with open(file_path, 'rb') as f:
                self.send_response(200)
                self.send_header("Content-type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(f.read())
        except IOError:
            self.send_error(404, "File not found")
    
    def serve_download(self, file_path):
        file_path = urllib.parse.unquote(file_path)

        # Check access for non-admin users
        user = self.check_token_auth()

        if user != 'admin' and not self.is_path_accessible(os.path.dirname(file_path), user):
            self.send_error(403, "Access denied - This file is not in a shared folder")
            return
            
        try:
            file_size = os.path.getsize(file_path)
            
            self.send_response(200)
            self.send_header("Content-type", "application/octet-stream")
            self.send_header("Content-Disposition", f'attachment; filename="{os.path.basename(file_path)}"')
            self.send_header("Content-Length", str(file_size))
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Cache-Control", "public, max-age=0")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            
            # Stream download in large chunks for speed
            with open(file_path, 'rb') as f:
                while True:
                    chunk = f.read(65536)  # 64KB chunks for fast downloads
                    if not chunk:
                        break
                    self.wfile.write(chunk)
        except (IOError, BrokenPipeError):
            pass  # Client disconnected

    @staticmethod
    def _parse_multipart(body, boundary_bytes):
        """Parse a multipart/form-data body already read fully into memory.
        Returns (text_fields dict, file_field dict-or-None). Good enough for
        this app's single small form (one text field + one file field)."""
        fields = {}
        file_field = None
        delimiter = b'--' + boundary_bytes

        for part in body.split(delimiter):
            part = part.strip(b'\r\n')
            if not part or part == b'--':
                continue
            if b'\r\n\r\n' not in part:
                continue
            header_blob, content = part.split(b'\r\n\r\n', 1)
            if content.endswith(b'\r\n'):
                content = content[:-2]

            headers = header_blob.decode('utf-8', errors='replace')
            disposition_line = None
            content_type_line = None
            for line in headers.split('\r\n'):
                lowered = line.lower()
                if lowered.startswith('content-disposition:'):
                    disposition_line = line
                elif lowered.startswith('content-type:'):
                    content_type_line = line
            if not disposition_line:
                continue

            name_match = re.search(r'name="([^"]*)"', disposition_line)
            filename_match = re.search(r'filename="([^"]*)"', disposition_line)
            field_name = name_match.group(1) if name_match else None

            if filename_match:
                file_field = {
                    'field_name': field_name,
                    'filename': filename_match.group(1),
                    'content': content,
                    'content_type': content_type_line.split(':', 1)[1].strip() if content_type_line else 'application/octet-stream'
                }
            elif field_name:
                fields[field_name] = content.decode('utf-8', errors='replace')

        return fields, file_field

    @staticmethod
    def _unique_destination(path):
        """Avoid clobbering an existing file: foo.txt -> foo (1).txt, foo (2).txt, ..."""
        if not os.path.exists(path):
            return path
        base, ext = os.path.splitext(path)
        i = 1
        while True:
            candidate = f"{base} ({i}){ext}"
            if not os.path.exists(candidate):
                return candidate
            i += 1

    def handle_upload(self):
        """Handle a multipart/form-data file upload into a folder the
        current user is allowed to write to."""
        user = self.check_token_auth()
        if not user:
            self.send_error(401, "Access denied")
            return

        content_type = self.headers.get('Content-Type', '')
        if not content_type.startswith('multipart/form-data'):
            self.send_error(400, "Expected multipart/form-data")
            return

        boundary = None
        for piece in content_type.split(';'):
            piece = piece.strip()
            if piece.startswith('boundary='):
                boundary = piece[len('boundary='):].strip('"')
                break
        if not boundary:
            self.send_error(400, "Missing multipart boundary")
            return

        content_length = int(self.headers.get('Content-Length', 0))
        max_bytes = Config.MAX_UPLOAD_SIZE_MB * 1024 * 1024 if Config.MAX_UPLOAD_SIZE_MB else None
        if content_length <= 0:
            self.send_error(400, "Empty upload")
            return
        if max_bytes and content_length > max_bytes:
            # Drain the body so the connection can be reused/closed cleanly
            self.rfile.read(content_length)
            self.send_error(413, f"Upload too large (max {Config.MAX_UPLOAD_SIZE_MB} MB - use the folder/bulk uploader for bigger transfers)")
            return

        body = self.rfile.read(content_length)
        fields, file_field = self._parse_multipart(body, boundary.encode())
        upload_path = fields.get('upload_path', '/')

        if not file_field or not file_field.get('filename'):
            self.send_response(302)
            self.send_header('Location', urllib.parse.quote(upload_path))
            self.end_headers()
            return

        if not os.path.isdir(upload_path):
            self.send_error(404, "Destination folder not found")
            return
        if user != 'admin' and not self.is_path_accessible(upload_path, user):
            self.send_error(403, "Access denied - you cannot upload here")
            return
        if not self.check_space_available(upload_path, content_length):
            self.send_error(507, "Not enough free space on the destination to fit this file")
            return

        raw_filename = file_field['filename'].replace('\\', '/')
        safe_name = os.path.basename(raw_filename)
        if not safe_name or safe_name in ('.', '..'):
            self.send_error(400, "Invalid filename")
            return

        dest_path = self._unique_destination(os.path.join(upload_path, safe_name))

        try:
            with open(dest_path, 'wb') as f:
                f.write(file_field['content'])
        except OSError as e:
            self.send_error(500, f"Could not save file: {e}")
            return

        print(f"{user} uploaded '{os.path.basename(dest_path)}' to {upload_path}")
        self.ADMIN_NOTIFICATIONS.append(f"{user} uploaded: {os.path.basename(dest_path)}")

        self.send_response(302)
        self.send_header('Location', urllib.parse.quote(upload_path))
        self.end_headers()

    # ---- Chunked / resumable upload API (for large files and whole-folder
    # transfers - the single-shot handle_upload() above stays for small,
    # simple uploads and is unaffected by any of this) ----

    def _read_json_body(self):
        content_length = int(self.headers.get('Content-Length', 0))
        if content_length <= 0:
            return {}
        raw = self.rfile.read(content_length)
        try:
            return json.loads(raw.decode('utf-8'))
        except (ValueError, UnicodeDecodeError):
            return None

    def _send_json(self, status, payload):
        body = json.dumps(payload).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (IOError, BrokenPipeError):
            pass

    @staticmethod
    def _validate_relative_path(relative_path):
        """Reject path traversal / absolute paths in a client-supplied
        relative path. Never trust the client's folder structure claims."""
        if not relative_path or not isinstance(relative_path, str):
            return None
        normalized = relative_path.replace('\\', '/')
        parts = [p for p in normalized.split('/') if p not in ('', '.')]
        if not parts or any(p == '..' for p in parts):
            return None
        return '/'.join(parts)

    def create_upload(self, user, upload_path, relative_path, total_size, batch_id=None):
        """Validate, reserve disk space, and create a staging temp file + DB
        row + TRANSFERS entry for one file. Returns (upload_id, offset,
        error) where error is None on success or (status_code, json_body)."""
        safe_rel = self._validate_relative_path(relative_path)
        if not safe_rel:
            return None, 0, (400, {'error': 'invalid_relative_path'})
        if not isinstance(total_size, int) or total_size < 0:
            return None, 0, (400, {'error': 'invalid_size'})
        if not os.path.isdir(upload_path):
            return None, 0, (404, {'error': 'destination_not_found'})
        if user != 'admin' and not self.is_path_accessible(upload_path, user):
            return None, 0, (403, {'error': 'access_denied'})
        if not self.check_space_available(upload_path, total_size):
            return None, 0, (507, {
                'error': 'insufficient_space',
                'required_bytes': total_size,
                'available_bytes': self.get_free_space(upload_path),
            })

        final_path = os.path.join(upload_path, *safe_rel.split('/'))
        final_dir = os.path.dirname(final_path)
        try:
            os.makedirs(final_dir, exist_ok=True)
        except OSError as e:
            return None, 0, (500, {'error': 'mkdir_failed', 'detail': str(e)})
        final_path = self._unique_destination(final_path)

        staging_dir = os.path.join(upload_path, self.UPLOAD_STAGING_DIRNAME)
        try:
            os.makedirs(staging_dir, exist_ok=True)
        except OSError as e:
            return None, 0, (500, {'error': 'mkdir_failed', 'detail': str(e)})

        upload_id = uuid.uuid4().hex
        temp_path = os.path.join(staging_dir, upload_id + '.part')
        try:
            open(temp_path, 'ab').close()
        except OSError as e:
            return None, 0, (500, {'error': 'create_failed', 'detail': str(e)})

        self._reserve_bytes(upload_path, total_size)

        conn = None
        try:
            conn = sqlite3.connect(self.DB_FILE, timeout=5.0)
            cursor = conn.cursor()
            cursor.execute('''INSERT INTO uploads
                               (upload_id, batch_id, username, dest_dir, relative_path,
                                final_path, temp_path, total_size, status)
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active')''',
                         (upload_id, batch_id, user, upload_path, safe_rel,
                          final_path, temp_path, total_size))
            conn.commit()
        except sqlite3.Error as e:
            self._release_bytes(upload_path, total_size)
            return None, 0, (500, {'error': 'db_error', 'detail': str(e)})
        finally:
            if conn:
                conn.close()

        now = time.time()
        with self.TRANSFERS_LOCK:
            self.TRANSFERS[upload_id] = {
                'upload_id': upload_id, 'batch_id': batch_id, 'user': user,
                'dest_dir': upload_path, 'relative_path': safe_rel,
                'final_path': final_path, 'temp_path': temp_path,
                'total_bytes': total_size, 'bytes_done': 0,
                'status': 'active', 'started_at': now, 'updated_at': now,
            }
        return upload_id, 0, None

    def handle_upload_create(self):
        """POST /api/upload/create - one file."""
        user = self.check_token_auth()
        if not user:
            self._send_json(401, {'error': 'access_denied'})
            return
        data = self._read_json_body()
        if data is None:
            self._send_json(400, {'error': 'invalid_json'})
            return

        upload_id, offset, error = self.create_upload(
            user, data.get('upload_path', ''), data.get('relative_path', ''), data.get('size'))
        if error:
            status, payload = error
            self._send_json(status, payload)
            return
        self._send_json(200, {'upload_id': upload_id, 'offset': offset})

    def handle_upload_batch_create(self):
        """POST /api/upload/batch/create - a whole folder's manifest at once,
        so the disk-space check happens against the WHOLE transfer before any
        byte of any file moves, not file-by-file after it's too late."""
        user = self.check_token_auth()
        if not user:
            self._send_json(401, {'error': 'access_denied'})
            return
        data = self._read_json_body()
        if data is None:
            self._send_json(400, {'error': 'invalid_json'})
            return

        upload_path = data.get('upload_path', '')
        files = data.get('files')
        if not isinstance(files, list) or not files:
            self._send_json(400, {'error': 'empty_manifest'})
            return

        total_size = 0
        for f in files:
            size = f.get('size') if isinstance(f, dict) else None
            if not isinstance(size, int) or size < 0:
                self._send_json(400, {'error': 'invalid_size'})
                return
            total_size += size

        if not os.path.isdir(upload_path):
            self._send_json(404, {'error': 'destination_not_found'})
            return
        if user != 'admin' and not self.is_path_accessible(upload_path, user):
            self._send_json(403, {'error': 'access_denied'})
            return
        if not self.check_space_available(upload_path, total_size):
            self._send_json(507, {
                'error': 'insufficient_space',
                'required_bytes': total_size,
                'available_bytes': self.get_free_space(upload_path),
            })
            return

        batch_id = uuid.uuid4().hex
        results = []
        for f in files:
            upload_id, offset, error = self.create_upload(
                user, upload_path, f.get('relative_path', ''), f.get('size', 0), batch_id=batch_id)
            if error:
                _, payload = error
                results.append({'relative_path': f.get('relative_path'), 'error': payload})
            else:
                results.append({'relative_path': f.get('relative_path'), 'upload_id': upload_id, 'offset': offset})

        self._send_json(200, {'batch_id': batch_id, 'files': results})

    def handle_upload_chunk(self, upload_id):
        """PATCH /api/upload/<id> - Upload-Offset header + raw chunk bytes."""
        user = self.check_token_auth()
        content_length = int(self.headers.get('Content-Length', 0))
        if not user:
            self.rfile.read(content_length)
            self._send_json(401, {'error': 'access_denied'})
            return

        try:
            claimed_offset = int(self.headers.get('Upload-Offset', -1))
        except ValueError:
            claimed_offset = -1

        with self.UPLOAD_LOCKS_GUARD:
            lock = self.UPLOAD_LOCKS.setdefault(upload_id, threading.Lock())

        with lock:
            with self.TRANSFERS_LOCK:
                transfer = self.TRANSFERS.get(upload_id)
            if not transfer:
                self.rfile.read(content_length)
                self._send_json(404, {'error': 'unknown_upload'})
                return
            if transfer['user'] != user and user != 'admin':
                self.rfile.read(content_length)
                self._send_json(403, {'error': 'access_denied'})
                return

            temp_path = transfer['temp_path']
            try:
                current_offset = os.path.getsize(temp_path)
            except OSError:
                self.rfile.read(content_length)
                self._send_json(410, {'error': 'upload_gone'})
                return

            if claimed_offset != current_offset:
                self.rfile.read(content_length)
                self._send_json(409, {'error': 'offset_mismatch', 'offset': current_offset})
                return
            if current_offset + content_length > transfer['total_bytes']:
                self.rfile.read(content_length)
                self._send_json(400, {'error': 'chunk_exceeds_declared_size'})
                return

            try:
                with open(temp_path, 'ab') as f:
                    remaining = content_length
                    while remaining > 0:
                        chunk = self.rfile.read(min(65536, remaining))
                        if not chunk:
                            break
                        f.write(chunk)
                        remaining -= len(chunk)
            except OSError as e:
                self._send_json(500, {'error': 'write_failed', 'detail': str(e)})
                return

            new_offset = os.path.getsize(temp_path)
            now = time.time()
            with self.TRANSFERS_LOCK:
                transfer['bytes_done'] = new_offset
                transfer['updated_at'] = now
            done = new_offset >= transfer['total_bytes']

        if done:
            self.finalize_upload(upload_id)
        self._send_json(200, {'offset': new_offset, 'done': done})

    def finalize_upload(self, upload_id):
        with self.TRANSFERS_LOCK:
            transfer = self.TRANSFERS.pop(upload_id, None)
        if not transfer:
            return
        try:
            os.replace(transfer['temp_path'], transfer['final_path'])
        except OSError as e:
            print(f"⚠️  Could not finalize upload {upload_id}: {e}")
            # Put it back so a retry/HEAD can still find it rather than losing it silently
            with self.TRANSFERS_LOCK:
                self.TRANSFERS[upload_id] = transfer
            return

        self._release_bytes(transfer['dest_dir'], transfer['total_bytes'])
        self._mark_upload_status(upload_id, 'completed')

        name = os.path.basename(transfer['final_path'])
        print(f"{transfer['user']} uploaded '{name}' to {transfer['dest_dir']} (chunked)")
        self.ADMIN_NOTIFICATIONS.append(f"{transfer['user']} uploaded: {name}")

    def handle_upload_status(self, upload_id):
        """HEAD or GET /api/upload/<id> - query current offset to resume."""
        user = self.check_token_auth()
        if not user:
            self._send_json(401, {'error': 'access_denied'})
            return
        with self.TRANSFERS_LOCK:
            transfer = self.TRANSFERS.get(upload_id)
        if not transfer or (transfer['user'] != user and user != 'admin'):
            self._send_json(404, {'error': 'unknown_upload'})
            return
        self._send_json(200, {
            'offset': transfer['bytes_done'],
            'total_bytes': transfer['total_bytes'],
            'status': transfer['status'],
        })

    def handle_upload_abort(self, upload_id):
        """DELETE /api/upload/<id> - explicit cancel."""
        user = self.check_token_auth()
        if not user:
            self._send_json(401, {'error': 'access_denied'})
            return
        with self.TRANSFERS_LOCK:
            transfer = self.TRANSFERS.pop(upload_id, None)
        if not transfer or (transfer['user'] != user and user != 'admin'):
            self._send_json(404, {'error': 'unknown_upload'})
            return
        try:
            os.remove(transfer['temp_path'])
        except OSError:
            pass
        self._release_bytes(transfer['dest_dir'], transfer['total_bytes'] - transfer['bytes_done'])
        self._mark_upload_status(upload_id, 'aborted')
        self._send_json(200, {'status': 'aborted'})

    def send_transfers_json(self):
        """GET /api/transfers - polled by every logged-in user's page so
        everyone can see what's actively being transferred and by whom.
        Admin sees everything; a regular user sees only their own."""
        user = self.check_token_auth()
        if not user:
            self._send_json(401, {'error': 'access_denied'})
            return
        with self.TRANSFERS_LOCK:
            entries = list(self.TRANSFERS.values())
        if user != 'admin':
            entries = [e for e in entries if e['user'] == user]

        payload = []
        for e in entries:
            total = e['total_bytes'] or 1
            payload.append({
                'upload_id': e['upload_id'],
                'user': e['user'],
                'relative_path': e['relative_path'],
                'dest_dir': e['dest_dir'],
                'bytes_done': e['bytes_done'],
                'total_bytes': e['total_bytes'],
                'percent': round(min(e['bytes_done'] / total, 1.0) * 100, 1),
                'status': e['status'],
            })
        self._send_json(200, {'transfers': payload})

    @classmethod
    def sweep_stale_uploads(cls):
        """Background loop (run in a daemon thread) reclaiming abandoned
        upload temp files/reservations - dropped connection, closed tab,
        crashed browser - after Config.STALE_UPLOAD_HOURS of inactivity."""
        while True:
            time.sleep(3600)
            try:
                cutoff = time.time() - (Config.STALE_UPLOAD_HOURS * 3600)
                with cls.TRANSFERS_LOCK:
                    stale_ids = [uid for uid, t in cls.TRANSFERS.items() if t['updated_at'] < cutoff]
                for upload_id in stale_ids:
                    with cls.TRANSFERS_LOCK:
                        transfer = cls.TRANSFERS.pop(upload_id, None)
                    if not transfer:
                        continue
                    try:
                        os.remove(transfer['temp_path'])
                    except OSError:
                        pass
                    cls._release_bytes(transfer['dest_dir'], transfer['total_bytes'] - transfer['bytes_done'])
                    cls._mark_upload_status(upload_id, 'expired')
                    print(f"🧹 Reclaimed stale upload: {transfer['relative_path']} "
                          f"(inactive > {Config.STALE_UPLOAD_HOURS}h)")
            except Exception as e:
                print(f"⚠️  Stale-upload sweep error: {e}")

    def show_directory(self, path, user):
        # Check if non-admin user has access to this path
        if user != 'admin' and not self.is_path_accessible(path, user):
            self.send_error(403, "Access denied - This folder is not shared with you")
            return
            
        windows_root_listing = IS_WINDOWS and path == '/'
        try:
            if windows_root_listing:
                files = list_windows_drives()
            else:
                files = [f for f in os.listdir(path) if f != self.UPLOAD_STAGING_DIRNAME]
                files.sort()
        except PermissionError:
            self.send_error(403, "Permission denied - cannot access this directory")
            return
        except OSError as e:
            self.send_error(404, f"Cannot access directory: {str(e)}")
            return

        try:
            template_path = self.get_template_path('directory.html')
            with open(template_path, 'r', encoding='utf-8') as f:
                template = f.read()

            # Build parent link
            parent_link = ''
            if path != '/':
                if is_drive_root(path):
                    parent = '/'
                else:
                    parent = os.path.dirname(path.rstrip('\\')) if IS_WINDOWS else os.path.dirname(path)
                    if not parent or parent == path:
                        parent = '/'
                encoded_parent = urllib.parse.quote(parent)
                parent_link = f'<div class="file dir"><a href="{encoded_parent}">📁 ..</a></div>'

            # Build file list - filter for non-admin users
            file_list = ''
            shared_paths = self.get_shared_paths()  # Get for both admin and non-admin

            for raw_name in files:
                if windows_root_listing:
                    # raw_name is already an absolute drive path like 'C:\\'
                    full_path = raw_name
                    name = raw_name.rstrip('\\')
                else:
                    full_path = os.path.join(path, raw_name)
                    name = raw_name

                # For non-admin users, only show items that are accessible
                if user != 'admin':
                    if not self.is_path_accessible(full_path, user):
                        continue  # Skip this item for non-admin users
                
                try:
                    if os.path.isdir(full_path):
                        # Check if directory is accessible
                        try:
                            os.listdir(full_path)
                            # Directory is accessible - show as clickable
                            encoded_path = urllib.parse.quote(full_path)
                            copy_button = ''
                            if user == 'admin':
                                copy_button = f' | <button onclick="copyToClipboard(\'{esc_js(full_path)}\')" style="background: #6c757d; color: white; border: none; padding: 2px 6px; border-radius: 3px; cursor: pointer; font-size: 11px;">📋 Copy Path</button>'
                            file_list += f'<div class="file dir"><a href="{encoded_path}">📁 {esc(name)}/</a>{copy_button}</div>'
                        except (OSError, PermissionError):
                            # Directory not accessible - show as disabled
                            file_list += f'<div class="file dir" style="opacity: 0.5; color: #999;"><span style="cursor: not-allowed;">🔒 {esc(name)}/ (No access)</span></div>'
                    else:
                        size = os.path.getsize(full_path)
                        encoded_path = urllib.parse.quote(full_path)
                        ext = name.lower().split('.')[-1]

                        copy_button = ''
                        share_button = ''
                        if user == 'admin':
                            # Check if file is already shared
                            is_file_shared = full_path in shared_paths
                            if not is_file_shared:
                                encoded_file = urllib.parse.quote(full_path)
                                share_button = f' | <button onclick="if(confirm(\'Share this file: {esc_js(name)}?\')){{window.location.href=\'/admin/share-path/{encoded_file}\'}}" style="background: #28a745; color: white; border: none; padding: 2px 6px; border-radius: 3px; cursor: pointer; font-size: 11px;">📤 Share File</button>'
                            else:
                                encoded_file = urllib.parse.quote(full_path)
                                share_button = f' | <button onclick="if(confirm(\'Stop sharing this file: {esc_js(name)}?\')){{window.location.href=\'/admin/unshare-path/{encoded_file}\'}}" style="background: #fd7e14; color: white; border: none; padding: 2px 6px; border-radius: 3px; cursor: pointer; font-size: 11px;">🔒 Unshare File</button>'
                            copy_button = f' | <button onclick="copyToClipboard(\'{esc_js(full_path)}\')" style="background: #6c757d; color: white; border: none; padding: 2px 6px; border-radius: 3px; cursor: pointer; font-size: 11px;">📋 Copy Path</button>'

                        if size == 0:
                            # 0-byte files - only allow download
                            file_list += f'<div class="file" style="opacity: 0.7; color: #666;">📄 {esc(name)} (0 bytes) - <span style="color: #999;">Empty file</span> | <a href="/download/{encoded_path}">Download</a>{copy_button}{share_button}</div>'
                        else:
                            parseable_files = ['html', 'htm', 'css', 'svg', 'xml']
                            video_files = ['mp4', 'webm', 'avi', 'mov', 'wmv', 'flv', 'mkv']
                            audio_files = ['mp3', 'wav', 'ogg', 'flac']

                            if ext in video_files:
                                file_list += f'<div class="file">🎬 {esc(name)} ({self.format_size(size)}) - <a href="{encoded_path}">Stream</a> | <a href="/download/{encoded_path}">Download</a>{copy_button}{share_button}</div>'
                            elif ext in audio_files:
                                file_list += f'<div class="file">🎵 {esc(name)} ({self.format_size(size)}) - <a href="{encoded_path}">Play</a> | <a href="/download/{encoded_path}">Download</a>{copy_button}{share_button}</div>'
                            elif ext in parseable_files:
                                file_list += f'<div class="file">📄 {esc(name)} ({self.format_size(size)}) - <a href="{encoded_path}">View</a> | <a href="/raw/{encoded_path}">Raw</a> | <a href="/download/{encoded_path}">Download</a>{copy_button}{share_button}</div>'
                            else:
                                file_list += f'<div class="file">📄 {esc(name)} ({self.format_size(size)}) - <a href="{encoded_path}">View</a> | <a href="/download/{encoded_path}">Download</a>{copy_button}{share_button}</div>'
                except (OSError, PermissionError):
                    file_list += f'<div class="file" style="opacity: 0.5; color: #999;">❌ {esc(name)} (Permission denied)</div>'
            
            # For non-admin users in root directory, show shared folders as virtual links
            if user != 'admin' and path == '/' and not file_list:
                # Show shared folders as accessible links
                for shared_path, is_file in shared_paths.items():
                    if not is_file:  # Only show folders in root
                        folder_name = os.path.basename(shared_path)
                        encoded_path = urllib.parse.quote(shared_path)
                        file_list += f'<div class="file dir"><a href="{encoded_path}">📁 {esc(folder_name)}/ (Shared)</a></div>'
                    else:  # Show individual shared files
                        file_name = os.path.basename(shared_path)
                        encoded_path = urllib.parse.quote(shared_path)
                        file_size = os.path.getsize(shared_path) if os.path.exists(shared_path) else 0
                        ext = file_name.lower().split('.')[-1] if '.' in file_name else ''

                        if ext in ['mp4', 'webm', 'avi', 'mov', 'wmv', 'flv', 'mkv']:
                            file_list += f'<div class="file">🎬 {esc(file_name)} ({self.format_size(file_size)}) - <a href="{encoded_path}">Stream</a> | <a href="/download/{encoded_path}">Download</a></div>'
                        elif ext in ['mp3', 'wav', 'ogg', 'flac']:
                            file_list += f'<div class="file">🎵 {esc(file_name)} ({self.format_size(file_size)}) - <a href="{encoded_path}">Play</a> | <a href="/download/{encoded_path}">Download</a></div>'
                        else:
                            file_list += f'<div class="file">📄 {esc(file_name)} ({self.format_size(file_size)}) - <a href="{encoded_path}">View</a> | <a href="/download/{encoded_path}">Download</a></div>'
                
                if not file_list:
                    file_list = '<div style="text-align: center; padding: 40px; color: #666;">🔒 No shared content available<br><small>Contact admin to share folders or files with you</small></div>'
            elif not file_list and user != 'admin':
                file_list = '<div style="text-align: center; padding: 40px; color: #666;">🔒 No shared content available<br><small>Contact admin to share folders or files with you</small></div>'
            
            # Add admin panel and logout link
            header_content = ''
            if user == 'admin':
                # Check if current path is shared as a folder (not a file)
                is_shared = path in shared_paths and not shared_paths.get(path, False)
                share_button = ''
                if not is_shared and path != '/':
                    encoded_current_path = urllib.parse.quote(path)
                    share_button = f'<a href="/admin/share-path/{encoded_current_path}" style="background: #28a745; color: white; padding: 5px 10px; text-decoration: none; border-radius: 3px; font-size: 12px; margin-left: 5px;" onclick="return confirm(\'Share folder {esc_js(path)} with all users?\')">📤 Share This Folder</a>'
                elif is_shared and path != '/':
                    encoded_current_path = urllib.parse.quote(path)
                    share_button = f'<a href="/admin/unshare-path/{encoded_current_path}" style="background: #fd7e14; color: white; padding: 5px 10px; text-decoration: none; border-radius: 3px; font-size: 12px; margin-left: 5px;" onclick="return confirm(\'Stop sharing folder {esc_js(path)}?\')">🔒 Unshare This Folder</a>'

                header_content = f'<div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px;"><div><a href="/admin" style="background: #dc3545; color: white; padding: 5px 10px; text-decoration: none; border-radius: 3px; font-size: 12px;">Admin Panel</a>{share_button}</div><a href="/logout" style="color: #666;">Logout ({esc(user)})</a></div>'
            else:
                header_content = f'<div style="text-align: right; margin-bottom: 10px;"><a href="/logout" style="color: #666;">Logout ({esc(user)})</a></div>'

            # Add current path copy button for admin
            path_header = f"{header_content}<strong>Files in: {esc(path)}</strong>"
            if user == 'admin':
                path_header += f' <button onclick="copyToClipboard(\'{esc_js(path)}\')" style="background: #17a2b8; color: white; border: none; padding: 5px 10px; border-radius: 3px; cursor: pointer; font-size: 12px; margin-left: 10px;">📋 Copy Current Path</button>'
            
            # Upload form - only for real, writable directories the user can access
            upload_form = ''
            bulk_upload_widget = ''
            can_upload = path != '/' and (user == 'admin' or self.is_path_accessible(path, user))
            if can_upload:
                encoded_upload_path = esc(path)
                upload_form = (
                    '<form method="post" action="/upload" enctype="multipart/form-data" '
                    'style="background: #f8f9fa; padding: 12px; border-radius: 6px; margin-bottom: 15px;">'
                    f'<input type="hidden" name="upload_path" value="{encoded_upload_path}">'
                    '<input type="file" name="upload_file" required> '
                    '<button type="submit" style="background: #007bff; color: white; border: none; '
                    'padding: 6px 14px; border-radius: 4px; cursor: pointer;">⬆️ Upload here</button>'
                    '</form>'
                )
                bulk_upload_widget = (
                    f'<div id="bulk-dropzone" data-upload-path="{encoded_upload_path}" class="bulk-dropzone">'
                    '<input type="file" id="bulk-folder-input" webkitdirectory multiple style="display:none;">'
                    '<div>📁 Drag a folder here, or</div>'
                    '<button type="button" id="bulk-choose-btn">Choose a folder to upload</button>'
                    '<div class="bulk-note" id="bulk-note">Large/whole-folder uploads resume automatically if interrupted.</div>'
                    '<div class="bulk-queue" id="bulk-queue-panel"></div>'
                    '</div>'
                )

            # Replace placeholders
            html = template.replace('{path}', path_header)
            html = html.replace('{upload_form}', upload_form)
            html = html.replace('{bulk_upload_widget}', bulk_upload_widget)
            html = html.replace('{parent_link}', parent_link)
            html = html.replace('{file_list}', file_list)
            
            self.send_response(200)
            self.send_header("Content-type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(html.encode('utf-8'))
        except FileNotFoundError:
            self.send_error(500, "Template file not found")
    
    def send_admin_page(self):
        try:
            template_path = self.get_template_path('admin.html')
            with open(template_path, 'r', encoding='utf-8') as f:
                template = f.read()
            
            conn = sqlite3.connect(self.DB_FILE)
            cursor = conn.cursor()
            cursor.execute('SELECT id, username, is_approved, created_at FROM users ORDER BY is_approved DESC, created_at DESC')
            users = cursor.fetchall()
            conn.close()
            
            # Separate approved and pending users
            approved_users = []
            pending_users = []
            
            for user_id, username, is_approved, created_at in users:
                if username == 'admin':
                    continue
                if is_approved:
                    approved_users.append((user_id, username, created_at))
                else:
                    pending_users.append((user_id, username, created_at))
            
            user_list = ''
            
            # Approved Users Section
            if approved_users:
                user_list += '<h3 style="color: #28a745; margin-top: 20px;">✅ Approved Users</h3>'
                for user_id, username, created_at in approved_users:
                    user_list += f'''
                    <div class="user approved">
                        <div>
                            <strong>{esc(username)}</strong><br>
                            <small>Joined: {esc(created_at)}</small><br>
                            <span style="color: #28a745;">✅ Active User</span>
                        </div>
                        <div>
                            <a href="/admin/reset-password/{user_id}" class="btn" style="background: #ffc107; color: #000; margin: 2px;">Reset Password</a>
                            <a href="/admin/reject/{user_id}" class="btn" style="background: #fd7e14; margin: 2px;">Suspend</a>
                            <a href="/admin/delete/{user_id}" class="btn btn-danger" onclick="return confirm('Delete user {esc_js(username)}? This cannot be undone!')">Delete</a>
                        </div>
                    </div>
                    '''
            
            # Pending Users Section
            if pending_users:
                user_list += '<h3 style="color: #dc3545; margin-top: 30px;">⏳ Pending Approval</h3>'
                for user_id, username, created_at in pending_users:
                    user_list += f'''
                    <div class="user pending">
                        <div>
                            <strong>{esc(username)}</strong><br>
                            <small>Requested: {esc(created_at)}</small><br>
                            <span style="color: #dc3545;">⏳ Waiting for approval</span>
                        </div>
                        <div>
                            <a href="/admin/approve/{user_id}" class="btn btn-success">Approve</a>
                            <a href="/admin/delete/{user_id}" class="btn btn-danger" onclick="return confirm('Delete user {esc_js(username)}? This cannot be undone!')">Delete</a>
                        </div>
                    </div>
                    '''
            
            if not approved_users and not pending_users:
                user_list = '<div style="text-align: center; padding: 40px; color: #666;">No users registered yet</div>'
            
            # Add notifications
            notifications = ''
            if AuthFileHandler.ADMIN_NOTIFICATIONS:
                notifications = '<div style="background: #fff3cd; border: 1px solid #ffeaa7; padding: 15px; border-radius: 8px; margin-bottom: 20px;">'
                notifications += '<h3 style="color: #856404;">🔔 Recent Actions</h3>'
                for notification in AuthFileHandler.ADMIN_NOTIFICATIONS[-5:]:  # Show last 5
                    notifications += f'<p style="margin: 5px 0; color: #856404;">• {esc(notification)}</p>'
                notifications += '<button onclick="this.parentElement.style.display=\'none\'" style="background: #ffc107; border: none; padding: 5px 10px; border-radius: 3px; cursor: pointer;">Clear</button>'
                notifications += '</div>'
            
            # Add summary stats
            stats = f'''
            <div style="background: #e9ecef; padding: 15px; border-radius: 8px; margin-bottom: 20px;">
                <h3>User Statistics</h3>
                <p><strong>Total Users:</strong> {len(approved_users) + len(pending_users)}</p>
                <p><strong>Approved:</strong> <span style="color: #28a745;">{len(approved_users)}</span></p>
                <p><strong>Pending:</strong> <span style="color: #dc3545;">{len(pending_users)}</span></p>
            </div>
            '''
            user_list = notifications + stats + user_list
            
            # Add admin navigation
            admin_nav = f'''
            <div style="background: #e9ecef; padding: 15px; border-radius: 8px; margin-bottom: 20px; text-align: center;">
                <h3>Admin Tools</h3>
                <a href="/" style="display: inline-block; padding: 10px 20px; margin: 5px; background: #6f42c1; color: white; text-decoration: none; border-radius: 5px;">📂 Browse Files</a>
                <a href="/admin/active-users" style="display: inline-block; padding: 10px 20px; margin: 5px; background: #17a2b8; color: white; text-decoration: none; border-radius: 5px;">👥 View Active Users</a>
                <a href="/admin/shared-paths" style="display: inline-block; padding: 10px 20px; margin: 5px; background: #28a745; color: white; text-decoration: none; border-radius: 5px;">📁 Manage Shared Folders</a>
                <a href="/admin/rate-limits" style="display: inline-block; padding: 10px 20px; margin: 5px; background: #dc3545; color: white; text-decoration: none; border-radius: 5px;">🚫 Manage Rate Limits</a>
            </div>
            '''
            
            html = template.replace('{user_list}', admin_nav + user_list)
            
            self.send_response(200)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(html.encode('utf-8'))
        except FileNotFoundError:
            self.send_error(500, "Template file not found")
    
    def approve_user(self, user_id):
        conn = sqlite3.connect(self.DB_FILE)
        cursor = conn.cursor()
        cursor.execute('UPDATE users SET is_approved = 1 WHERE id = ?', (user_id,))
        conn.commit()
        conn.close()
        
        self.send_response(302)
        self.send_header('Location', f'/admin')
        self.end_headers()
    
    def reject_user(self, user_id):
        conn = sqlite3.connect(self.DB_FILE)
        cursor = conn.cursor()
        cursor.execute('UPDATE users SET is_approved = 0 WHERE id = ?', (user_id,))
        conn.commit()
        conn.close()
        
        self.send_response(302)
        self.send_header('Location', f'/admin')
        self.end_headers()
    
    def delete_user(self, user_id):
        conn = sqlite3.connect(self.DB_FILE)
        cursor = conn.cursor()
        # Get username before deleting for logging
        cursor.execute('SELECT username FROM users WHERE id = ?', (user_id,))
        result = cursor.fetchone()
        if result:
            username = result[0]
            cursor.execute('DELETE FROM users WHERE id = ? AND username != "admin"', (user_id,))
            conn.commit()
            print(f"Admin deleted user: {username}")
            
            # Invalidate all tokens and active sessions for the deleted user
            tokens_to_remove = []
            for token, data in self.VALID_TOKENS.items():
                if data['user'] == username:
                    tokens_to_remove.append(token)
            
            for token in tokens_to_remove:
                del self.VALID_TOKENS[token]
                if token in self.ACTIVE_USERS:
                    del self.ACTIVE_USERS[token]
                print(f"Invalidated token for deleted user: {username}")
        conn.close()
        
        self.send_response(302)
        self.send_header('Location', f'/admin')
        self.end_headers()
    
    def reset_user_password(self, user_id):
        new_password = str(uuid.uuid4())[:8]  # 8 character password
        salt = secrets.token_hex(16)
        password_hash = hashlib.pbkdf2_hmac('sha256', new_password.encode(), salt.encode(), 100000)
        
        conn = sqlite3.connect(self.DB_FILE)
        cursor = conn.cursor()
        try:
            # Get username and update password
            cursor.execute('SELECT username FROM users WHERE id = ?', (user_id,))
            result = cursor.fetchone()
            if result:
                username = result[0]
                if username == 'admin':
                    print("Cannot reset admin password")
                    conn.close()
                    return
                
                # Update password (no plain text storage)
                cursor.execute('UPDATE users SET password_hash = ?, salt = ? WHERE id = ?',
                             (password_hash.hex(), salt, user_id))
                print(f"✅ Admin reset password for user: {username} -> {new_password}")
                # Store notification for admin
                AuthFileHandler.ADMIN_NOTIFICATIONS.append(f"Password reset for {username}: {new_password}")
                
                # Invalidate user sessions on password reset
                tokens_to_remove = []
                for token, data in AuthFileHandler.VALID_TOKENS.items():
                    if data['user'] == username:
                        tokens_to_remove.append(token)
                
                for token in tokens_to_remove:
                    del AuthFileHandler.VALID_TOKENS[token]
                    if token in AuthFileHandler.ACTIVE_USERS:
                        del AuthFileHandler.ACTIVE_USERS[token]
                print(f"🔒 Invalidated {len(tokens_to_remove)} sessions for {username}")
                
                conn.commit()
            else:
                print(f"❌ User with ID {user_id} not found")
        except Exception as e:
            print(f"❌ Password reset failed: {e}")
        finally:
            conn.close()
        
        self.send_response(302)
        self.send_header('Location', f'/admin')
        self.end_headers()
    
    @staticmethod
    def _mount_key(path):
        """Bucket a path to 'the filesystem it lives on', for grouping disk-space
        reservations. Drive letter on Windows, st_dev on POSIX. This is a
        simplification (not full multi-mount-point detection) but is enough to
        stop two concurrent large batches on the same volume from both passing
        a space check that only holds if only one of them actually runs."""
        if IS_WINDOWS:
            drive, _ = os.path.splitdrive(os.path.abspath(path))
            return drive.upper() or 'C:'
        try:
            return os.stat(path).st_dev
        except OSError:
            return os.path.abspath(path)

    @classmethod
    def _reserve_bytes(cls, dest_dir, amount):
        if amount <= 0:
            return
        key = cls._mount_key(dest_dir)
        with cls.RESERVED_LOCK:
            cls.RESERVED_BYTES[key] = cls.RESERVED_BYTES.get(key, 0) + amount

    @classmethod
    def _release_bytes(cls, dest_dir, amount):
        if amount <= 0:
            return
        key = cls._mount_key(dest_dir)
        with cls.RESERVED_LOCK:
            cls.RESERVED_BYTES[key] = max(cls.RESERVED_BYTES.get(key, 0) - amount, 0)

    @classmethod
    def get_free_space(cls, dest_dir):
        """Free bytes on dest_dir's filesystem, minus what's already reserved
        by other in-flight uploads targeting the same filesystem."""
        free = shutil.disk_usage(dest_dir).free
        key = cls._mount_key(dest_dir)
        with cls.RESERVED_LOCK:
            reserved = cls.RESERVED_BYTES.get(key, 0)
        return max(free - reserved, 0)

    @classmethod
    def check_space_available(cls, dest_dir, needed_bytes, margin_bytes=64 * 1024 * 1024):
        """~64MB safety margin so we don't cut it down to the literal last byte."""
        try:
            return cls.get_free_space(dest_dir) >= (needed_bytes + margin_bytes)
        except OSError:
            return False

    def is_path_accessible(self, path, user):
        """Check if user has access to the given path - BLOCKED BY DEFAULT"""
        if user == 'admin':
            return True
        
        # Always allow access to root directory (but filter contents)
        if path == '/':
            return True
        
        # Get shared paths from database (now returns dict with is_file info)
        shared_paths = self.get_shared_paths()
        
        # BLOCK EVERYTHING BY DEFAULT - only allow explicitly shared paths
        if not shared_paths:
            return False  # No access to anything if nothing is shared
        
        # Check if exact path is shared (for files)
        if path in shared_paths:
            return True
        
        # Check if path is within a shared folder (segment-aware: sharing
        # /data/project must not also grant /data/project-secret)
        norm_path = path.rstrip('/\\')
        for shared_path, is_file in shared_paths.items():
            if is_file:
                continue
            norm_shared = shared_path.rstrip('/\\')
            if norm_path == norm_shared or norm_path.startswith(norm_shared + os.sep) or norm_path.startswith(norm_shared + '/'):
                return True
        return False
    
    def add_shared_path(self, path, force_type=None):
        """Add a path to shared paths in database"""
        if os.path.exists(path):
            conn = sqlite3.connect(self.DB_FILE)
            cursor = conn.cursor()
            try:
                # Determine if it's a file based on force_type or actual filesystem
                if force_type == 'file':
                    is_file = True
                elif force_type == 'folder':
                    is_file = False
                else:
                    is_file = os.path.isfile(path)
                
                cursor.execute('INSERT INTO shared_paths (path, shared_by, is_file) VALUES (?, ?, ?)', (path, 'admin', is_file))
                conn.commit()
                self.invalidate_shared_paths_cache()  # Clear cache
                item_type = "file" if is_file else "folder"
                print(f"Admin shared {item_type}: {path}")
                self.ADMIN_NOTIFICATIONS.append(f"Shared {item_type}: {os.path.basename(path)}")
            except sqlite3.IntegrityError:
                item_type = "file" if (force_type == 'file' or (force_type != 'folder' and os.path.isfile(path))) else "folder"
                print(f"Path already shared: {path}")
                self.ADMIN_NOTIFICATIONS.append(f"{item_type.title()} already shared: {os.path.basename(path)}")
            finally:
                conn.close()
        else:
            print(f"Path does not exist: {path}")
            self.ADMIN_NOTIFICATIONS.append(f"Path not found: {path}")
        
        # Redirect back to shared paths management page
        self.send_response(302)
        self.send_header('Location', f'/admin/shared-paths')
        self.end_headers()
    
    def remove_shared_path(self, path):
        """Remove a path from shared paths in database"""
        conn = sqlite3.connect(self.DB_FILE)
        cursor = conn.cursor()
        cursor.execute('DELETE FROM shared_paths WHERE path = ?', (path,))
        if cursor.rowcount > 0:
            self.invalidate_shared_paths_cache()  # Clear cache
            print(f"Admin unshared path: {path}")
            self.ADMIN_NOTIFICATIONS.append(f"Unshared: {path}")
        conn.commit()
        conn.close()
        
        # Always redirect back to shared paths management page
        self.send_response(302)
        self.send_header('Location', f'/admin/shared-paths')
        self.end_headers()
    
    def send_active_users_page(self):
        """Send page showing currently active users"""
        try:
            current_time = time.time()
            inactive_tokens = []
            for token, data in self.ACTIVE_USERS.items():
                if current_time - data['last_activity'] > 300:
                    inactive_tokens.append(token)
            
            for token in inactive_tokens:
                del self.ACTIVE_USERS[token]
            
            
            active_users_html = ''
            active_count = 0
            for token, data in self.ACTIVE_USERS.items():
                if data['user'] != 'admin':
                    active_count += 1
                    last_seen = int(current_time - data['last_activity'])
                    active_users_html += f'<div style="background: #f8f9fa; padding: 15px; border-radius: 8px; margin: 10px 0; border-left: 4px solid #28a745;"><h4 style="margin: 0 0 10px 0; color: #28a745;">🟢 {esc(data["user"])}</h4><p><strong>IP:</strong> {esc(data["ip"])}</p><p><strong>Device:</strong> {esc(data["user_agent"])}</p><p><strong>Last Activity:</strong> {last_seen} seconds ago</p></div>'
            
            if not active_users_html:
                active_users_html = '<div style="text-align: center; padding: 40px; color: #666;">No users currently active</div>'
            
            html = f'<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Active Users</title><meta name="viewport" content="width=device-width, initial-scale=1"><meta http-equiv="refresh" content="10"><style>body{{font-family: Arial, sans-serif; max-width: 800px; margin: 20px auto; padding: 20px;}}.nav a{{display: inline-block; padding: 8px 16px; margin: 5px; background: #007bff; color: white; text-decoration: none; border-radius: 4px;}}</style></head><body><h1>👥 Active Users ({active_count})</h1><div class="nav"><a href="/admin">← Back</a><a href="/admin/shared-paths">📁 Shared Folders</a></div>{active_users_html}</body></html>'
            
            self.send_response(200)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(html.encode('utf-8'))
        except Exception as e:
            self.send_error(500, f"Error: {str(e)}")
    
    def send_shared_paths_page(self):
        """Send page for managing shared paths"""
        try:
            
            shared_paths = self.get_shared_paths()
            shared_paths_html = ''
            if shared_paths:
                for path in sorted(shared_paths):
                    encoded_path = urllib.parse.quote(path)
                    shared_paths_html += f'<div style="background: #d4edda; padding: 15px; border-radius: 8px; margin: 10px 0; display: flex; justify-content: space-between; align-items: center;"><div><strong>📁 {esc(path)}</strong></div><div><a href="/admin/unshare-path/{encoded_path}" style="background: #dc3545; color: white; padding: 5px 10px; text-decoration: none; border-radius: 3px;" onclick="return confirm(\'Stop sharing {esc_js(path)}?\')">Remove</a></div></div>'
            else:
                shared_paths_html = '<div style="text-align: center; padding: 40px; color: #666;">No folders shared<br><small>🔒 All files are BLOCKED by default</small><br><small>Users cannot access anything until you share folders</small></div>'
            
            html = f'<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Shared Folders</title><meta name="viewport" content="width=device-width, initial-scale=1"><style>body{{font-family: Arial, sans-serif; max-width: 800px; margin: 20px auto; padding: 20px;}}.nav a{{display: inline-block; padding: 8px 16px; margin: 5px; background: #007bff; color: white; text-decoration: none; border-radius: 4px;}}.add-form{{background: #f8f9fa; padding: 20px; border-radius: 8px; margin-bottom: 20px;}}.add-form input{{width: 70%; padding: 8px; margin-right: 10px;}}.add-form button{{padding: 8px 16px; background: #28a745; color: white; border: none; border-radius: 4px; cursor: pointer;}}</style><script>function shareFolder(){{const pathInput = document.getElementById(\'pathInput\'); const path = pathInput.value.trim(); if(path){{window.location.href = \'/admin/share-path/\' + encodeURIComponent(path) + \'\';}} else {{alert(\'Please enter a folder path\');}} return false;}}</script></head><body><h1>📁 Shared Folders ({len(shared_paths)})</h1><div style="background: #fff3cd; padding: 10px; border-radius: 5px; margin-bottom: 20px; text-align: center;"><strong>🔒 SECURE MODE:</strong> All files blocked by default. Only shared folders are accessible.</div><div class="nav"><a href="/admin">← Back</a><a href="/admin/active-users">👥 Active Users</a></div><div class="add-form"><h3>Add Shared Folder</h3><form onsubmit="return shareFolder()"><input type="text" id="pathInput" placeholder="Enter folder path (e.g., /Users/username/Documents)" required><button type="submit">Share Folder</button></form><small>💡 Tip: Use the 📋 Copy Path buttons when browsing files</small></div>{shared_paths_html}</body></html>'
            
            self.send_response(200)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(html.encode('utf-8'))
        except Exception as e:
            self.send_error(500, f"Error: {str(e)}")

    def send_rate_limits_page(self):
        """Send page for managing rate limits"""
        
        # Clean up expired rate limits first
        now = time.time()
        expired_ips = []
        for ip, (attempts, last_attempt) in self.FAILED_ATTEMPTS.items():
            if now - last_attempt > 120:
                expired_ips.append(ip)
        
        for ip in expired_ips:
            del self.FAILED_ATTEMPTS[ip]
            print(f"DEBUG: Cleared expired rate limit for {ip}")
        
        rate_limits_html = ''
        blocked_ips = 0
        warning_ips = 0
        
        if self.FAILED_ATTEMPTS:
            for ip, (attempts, last_attempt) in self.FAILED_ATTEMPTS.items():
                time_ago = int(now - last_attempt)
                encoded_ip = urllib.parse.quote(ip)
                
                # Only show as blocked if >= 5 attempts and within 2 minutes
                if attempts >= 5 and (now - last_attempt) <= 120:
                    blocked_ips += 1
                    time_remaining = int(120 - (now - last_attempt))
                    rate_limits_html += f'<div style="background: #f8d7da; padding: 15px; border-radius: 8px; margin: 10px 0; display: flex; justify-content: space-between; align-items: center;"><div><strong>🚫 {esc(ip)} (BLOCKED)</strong><br><small>{attempts} failed attempts</small><br><small>Blocked for {time_remaining} more seconds</small></div><div><a href="/admin/clear-rate-limit/{encoded_ip}" style="background: #28a745; color: white; padding: 5px 10px; text-decoration: none; border-radius: 3px;" onclick="return confirm(\'Clear rate limit for {esc_js(ip)}?\')">Clear Block</a></div></div>'
                else:
                    # Show as warning (has attempts but not blocked)
                    warning_ips += 1
                    rate_limits_html += f'<div style="background: #fff3cd; padding: 15px; border-radius: 8px; margin: 10px 0; display: flex; justify-content: space-between; align-items: center;"><div><strong>⚠️ {esc(ip)} (WARNING)</strong><br><small>{attempts} failed attempts (not blocked yet)</small><br><small>Last attempt: {time_ago} seconds ago</small></div><div><a href="/admin/clear-rate-limit/{encoded_ip}" style="background: #6c757d; color: white; padding: 5px 10px; text-decoration: none; border-radius: 3px;" onclick="return confirm(\'Clear attempts for {esc_js(ip)}?\')">Clear</a></div></div>'
        
        if not rate_limits_html:
            rate_limits_html = '<div style="text-align: center; padding: 40px; color: #666;">No failed attempts recorded<br><small>All IPs are currently allowed to login</small></div>'
        
        html = f'<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Rate Limits</title><meta name="viewport" content="width=device-width, initial-scale=1"><style>body{{font-family: Arial, sans-serif; max-width: 800px; margin: 20px auto; padding: 20px;}}.nav a{{display: inline-block; padding: 8px 16px; margin: 5px; background: #007bff; color: white; text-decoration: none; border-radius: 4px;}}.clear-all{{background: #dc3545; padding: 10px 20px; margin: 10px 0; display: inline-block; color: white; text-decoration: none; border-radius: 5px;}}</style></head><body><h1>🚫 Rate Limits</h1><div style="background: #d1ecf1; padding: 10px; border-radius: 5px; margin-bottom: 20px; text-align: center;"><strong>Rate Limiting:</strong> 5 failed attempts per 2 minutes, then blocked for 2 minutes<br><strong>Currently:</strong> {blocked_ips} blocked IPs, {warning_ips} IPs with failed attempts</div><div class="nav"><a href="/admin">← Back to Admin Panel</a><a href="/admin/active-users">👥 Active Users</a></div><div style="text-align: center; margin-bottom: 20px;"><a href="/admin/clear-rate-limit" class="clear-all" onclick="return confirm(\'Clear ALL rate limits for all IPs?\')">Clear All</a></div><div><h3>IP Status</h3>{rate_limits_html}</div></body></html>'
        
        self.send_response(200)
        self.send_header('Content-type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(html.encode('utf-8'))

def cleanup_admin_password():
    """Clear admin password from memory for security"""
    AuthFileHandler.ADMIN_PASSWORD = None
    print("🗑️  Admin password cleared from memory for security")

class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    """Handle requests in separate threads"""
    daemon_threads = True
    allow_reuse_address = True
    
    def handle_error(self, request, client_address):
        """Handle errors - suppress common video streaming connection errors"""
        import sys
        
        # Get the exception info
        exc_type, _, _ = sys.exc_info()
        
        # Suppress common connection errors during video streaming
        if exc_type in (ConnectionResetError, BrokenPipeError, ConnectionAbortedError):
            # These are normal when clients disconnect during video streaming
            return
        
        # For other errors, use default handling
        super().handle_error(request, client_address)

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "127.0.0.1"

def get_tls_dir():
    """Directory alongside the database where auto-generated TLS materials live."""
    base_dir = os.path.dirname(os.path.abspath(Config.get_db_path())) or '.'
    return base_dir

def generate_self_signed_cert(cert_path, key_path, local_ip):
    """Generate a self-signed TLS cert/key pair using the optional
    'cryptography' package. Returns True on success, False if the package
    isn't installed or generation fails for any reason."""
    try:
        import datetime
        import ipaddress
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
    except ImportError:
        return False

    try:
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'FileShare')])

        san_entries = [x509.DNSName('localhost'), x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]
        try:
            san_entries.append(x509.IPAddress(ipaddress.ip_address(local_ip)))
        except ValueError:
            pass

        now = datetime.datetime.now(datetime.timezone.utc)
        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=825))
            .add_extension(x509.SubjectAlternativeName(san_entries), critical=False)
            .sign(key, hashes.SHA256())
        )

        with open(key_path, 'wb') as f:
            f.write(key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption(),
            ))
        try:
            os.chmod(key_path, 0o600)
        except (OSError, AttributeError):
            pass

        with open(cert_path, 'wb') as f:
            f.write(cert.public_bytes(serialization.Encoding.PEM))
        return True
    except Exception as e:
        print(f"⚠️  Could not generate self-signed certificate: {e}")
        return False

def build_ssl_context(cert_file=None, key_file=None, local_ip='127.0.0.1'):
    """Return an SSLContext for the server socket, or None if TLS isn't
    available. Uses --cert/--key if given, otherwise auto-generates (and
    reuses) a self-signed cert in the app's data directory."""
    if not cert_file or not key_file:
        tls_dir = get_tls_dir()
        cert_file = os.path.join(tls_dir, 'server_cert.pem')
        key_file = os.path.join(tls_dir, 'server_key.pem')
        if not (os.path.exists(cert_file) and os.path.exists(key_file)):
            if not generate_self_signed_cert(cert_file, key_file, local_ip):
                return None

    try:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(certfile=cert_file, keyfile=key_file)
        return context
    except (ssl.SSLError, OSError) as e:
        print(f"⚠️  Could not load TLS certificate ({e}) - falling back to plain HTTP")
        return None

def create_server(port=None, host=None, ssl_context=None):
    """Create and return threaded HTTP server instance without starting it"""
    port = port or Config.DEFAULT_PORT
    host = host or Config.HOST
    server = ThreadedHTTPServer((host, port), AuthFileHandler)
    if ssl_context:
        server.socket = ssl_context.wrap_socket(server.socket, server_side=True)
    return server

def parse_args():
    import argparse
    parser = argparse.ArgumentParser(description="FileShare server")
    parser.add_argument('--port', type=int, default=Config.DEFAULT_PORT, help='Port to listen on')
    parser.add_argument('--host', type=str, default=Config.HOST, help='Host/interface to bind to')
    parser.add_argument('--reset-admin-password', action='store_true',
                       help='Generate a new admin password and exit')
    parser.add_argument('--no-tls', action='store_true',
                       help='Serve plain HTTP instead of auto-generated/self-signed HTTPS')
    parser.add_argument('--cert', type=str, default=None, help='Path to a TLS certificate (PEM)')
    parser.add_argument('--key', type=str, default=None, help='Path to the matching TLS private key (PEM)')
    return parser.parse_args()

def main():
    # Line-buffer stdout so startup info (admin password, URLs) shows up
    # immediately even when output is redirected to a file/log (headless
    # runs, systemd, packaged launchers) instead of sitting in a buffer.
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except AttributeError:
        pass

    args = parse_args()

    if args.reset_admin_password:
        AuthFileHandler.reset_admin_password()
        return

    # Initialize database
    AuthFileHandler.init_db()

    # Reclaim abandoned in-progress uploads (dropped connections, closed
    # tabs) after Config.STALE_UPLOAD_HOURS of inactivity.
    threading.Thread(target=AuthFileHandler.sweep_stale_uploads, daemon=True).start()

    # Initialize remote control if available
    if RemoteControl:
        remote_control = RemoteControl()
        remote_control.start_background_check()

    local_ip = get_local_ip()
    PORT = args.port

    ssl_context = None
    if not args.no_tls:
        ssl_context = build_ssl_context(args.cert, args.key, local_ip)
        if not ssl_context:
            print("⚠️  TLS unavailable (install the 'cryptography' package for HTTPS, or pass --cert/--key).")
            print("⚠️  Falling back to plain HTTP - only use this on a network you trust.")
    scheme = 'https' if ssl_context else 'http'
    AuthFileHandler.USE_SECURE_COOKIE = bool(ssl_context)

    server = create_server(args.port, args.host, ssl_context)

    print("\n" + "="*60)
    print("🔐 FileShare - RUNNING")
    print("="*60)
    print(f"📱 MOBILE ACCESS: {scheme}://{local_ip}:{PORT}")
    print(f"💻 COMPUTER ACCESS: {scheme}://localhost:{PORT}")
    if ssl_context:
        print("   (self-signed certificate - your browser will show a security warning; that's expected)")
    print("\n🔑 ADMIN LOGIN:")
    print("   Username: admin")
    if AuthFileHandler.ADMIN_PASSWORD:
        print(f"   Password: {AuthFileHandler.ADMIN_PASSWORD}")
    else:
        print(f"   Password: unknown - run 'python3 main.py --reset-admin-password'")
    print(f"   (also saved to {AuthFileHandler.get_admin_password_file()})")
    print("\n📱 ON YOUR PHONE:")
    print("   1. Connect to same WiFi")
    print(f"   2. Open browser, go to: {local_ip}:{PORT}")
    print("   3. Register account or login as admin")
    print("   4. Browse and download files!")
    print("\n⚠️  SECURITY: Only use on trusted networks")
    print("\n🛑 TO STOP SERVER:")
    print("   • Press Ctrl+C")
    print("   • Or close this window")
    print("="*60)
    
    try:
        print("\n⚠️  To stop server: Press Ctrl+C or close this window")
        print("🔒 Server will stop automatically when this window closes\n")
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n🛑 Shutting down server...")
        if RemoteControl:
            try:
                remote_control.stop()
            except:
                pass
        server.shutdown()
        cleanup_admin_password()
        print("✅ Server stopped successfully")

if __name__ == "__main__":
    main()