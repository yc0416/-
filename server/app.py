import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(os.environ.get('GALLERY_DATA_DIR', ROOT / '.local'))
DATA.mkdir(parents=True, exist_ok=True)
DB = DATA / 'gallery.sqlite3'
INVITE = os.environ.get('GALLERY_INVITE_CODE')
if not INVITE:
    invite_file = DATA / 'invite-code'
    if not invite_file.exists():
        invite_file.write_text(secrets.token_urlsafe(12))
        invite_file.chmod(0o600)
    INVITE = invite_file.read_text().strip()
SECURE = os.environ.get('GALLERY_SECURE_COOKIE') == '1'
GALLERIES = [{'id': 'free', 'name': '자유 갤러리', 'description': '소소한 일상부터 주말 약속까지'}, {'id': 'game', 'name': '게임 갤러리', 'description': '오늘의 파티원을 구해 보세요'}, {'id': 'meme', 'name': '유머 갤러리', 'description': '혼자 보기 아까운 웃긴 이야기'}]

def connect():
    db = sqlite3.connect(DB, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys = ON')
    return db

with connect() as db:
    db.executescript('''
    PRAGMA journal_mode=WAL;
    CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, nickname TEXT NOT NULL, salt TEXT NOT NULL, password TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, expires INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS posts(id INTEGER PRIMARY KEY, gallery_id TEXT NOT NULL, user_id INTEGER NOT NULL REFERENCES users(id), title TEXT NOT NULL, content TEXT NOT NULL, anonymous INTEGER NOT NULL DEFAULT 0, created_at INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS comments(id INTEGER PRIMARY KEY, post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE, user_id INTEGER NOT NULL REFERENCES users(id), content TEXT NOT NULL, created_at INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS votes(post_id INTEGER REFERENCES posts(id) ON DELETE CASCADE, user_id INTEGER REFERENCES users(id), value INTEGER CHECK(value IN (-1,1)), PRIMARY KEY(post_id,user_id));
    CREATE TABLE IF NOT EXISTS attempts(ip TEXT NOT NULL, created_at INTEGER NOT NULL);
    ''')

def password_hash(password, salt):
    return hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def reply(self, status, data, cookie=None):
        raw = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        if cookie:
            self.send_header('Set-Cookie', cookie)
        self.end_headers()
        self.wfile.write(raw)

    def user(self, db):
        c = cookies.SimpleCookie()
        try:
            c.load(self.headers.get('Cookie', ''))
            token = c['gallery_session'].value if 'gallery_session' in c else ''
        except cookies.CookieError:
            token = ''
        return db.execute('SELECT u.id,u.username,u.nickname FROM users u JOIN sessions s ON s.user_id=u.id WHERE s.token=? AND s.expires>?', (hashlib.sha256(token.encode()).hexdigest(), int(time.time()))).fetchone()

    def session_cookie(self, token, age=604800):
        return f'gallery_session={token}; HttpOnly; SameSite=Lax; Path=/; Max-Age={age}' + ('; Secure' if SECURE else '')

    def do_GET(self):
        path = urlparse(self.path).path
        if path.startswith('/api/'):
            return self.api('GET', path)
        # Build output is served here in production. Never serve source or local data.
        base = ROOT / 'dist'
        target = (base / path.lstrip('/')).resolve()
        if not target.is_relative_to(base.resolve()):
            return self.reply(404, {'error': '페이지를 찾을 수 없습니다.'})
        if not target.is_file():
            target = base / 'index.html'
        if not target.is_file():
            return self.reply(404, {'error': '먼저 npm run build를 실행하세요.'})
        import mimetypes
        raw = target.read_bytes()
        self.send_response(200)
        self.send_header('Content-Type', mimetypes.guess_type(str(target))[0] or 'application/octet-stream')
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self):
        self.api('POST', urlparse(self.path).path)

    def do_DELETE(self):
        self.api('DELETE', urlparse(self.path).path)

    def api(self, method, path):
        try:
            self.handle_api(method, path)
        except ValueError as e:
            self.reply(400, {'error': str(e)})
        except sqlite3.IntegrityError:
            self.reply(409, {'error': '이미 사용 중인 아이디입니다.'})
        except Exception:
            self.reply(500, {'error': '서버 오류가 발생했습니다. 잠시 후 다시 시도하세요.'})

    def handle_api(self, method, path):
        body = {}
        if method != 'GET':
            # JSON-only mutations prevent cross-site HTML form requests.
            if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                return self.reply(415, {'error': 'JSON 요청만 허용됩니다.'})
            origin = self.headers.get('Origin')
            if origin and urlparse(origin).netloc != self.headers.get('Host'):
                return self.reply(403, {'error': '허용되지 않은 요청입니다.'})
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if size < 0 or size > 65536:
                    return self.reply(413, {'error': '요청이 너무 큽니다.'})
                body = json.loads(self.rfile.read(size) or b'{}')
                if not isinstance(body, dict):
                    raise ValueError()
            except (ValueError, UnicodeError):
                return self.reply(400, {'error': '올바른 JSON 요청이 아닙니다.'})
        def field(name, minimum, maximum):
            value = body.get(name, '')
            if not isinstance(value, str) or not minimum <= len(value.strip()) <= maximum:
                raise ValueError(f'{name}: {minimum}~{maximum}자로 입력해 주세요.')
            return value.strip()
        with connect() as db:
            user = self.user(db)
            if path == '/api/health' and method == 'GET':
                db.execute('SELECT 1').fetchone()
                return self.reply(200, {'ok': True})
            if path == '/api/me' and method == 'GET':
                return self.reply(200, {'user': dict(user) if user else None})
            if path in ('/api/signup', '/api/login') and method == 'POST':
                now = int(time.time())
                ip = self.client_address[0]
                db.execute('DELETE FROM attempts WHERE created_at<?', (now-900,))
                if db.execute('SELECT count(*) FROM attempts WHERE ip=?', (ip,)).fetchone()[0] >= 30:
                    return self.reply(429, {'error': '시도가 너무 많습니다. 15분 후 다시 시도하세요.'})
                db.execute('INSERT INTO attempts VALUES (?,?)', (ip, now))
                db.commit()
                username = field('username', 3, 30).lower()
                import re
                if not re.fullmatch(r'[a-z0-9_]+', username):
                    raise ValueError('아이디는 영문 소문자, 숫자, 밑줄을 사용하세요.')
                password = body.get('password')
                if not isinstance(password, str) or not 8 <= len(password) <= 128:
                    raise ValueError('비밀번호는 8~128자로 입력하세요.')
                if path == '/api/signup':
                    if not hmac.compare_digest(str(body.get('inviteCode', '')).encode(), INVITE.encode()):
                        return self.reply(403, {'error': '초대 코드가 올바르지 않습니다.'})
                    nickname = field('nickname', 1, 20)
                    salt = secrets.token_hex(16)
                    cursor = db.execute('INSERT INTO users(username,nickname,salt,password) VALUES (?,?,?,?)', (username, nickname, salt, password_hash(password, salt)))
                    uid = cursor.lastrowid
                else:
                    row = db.execute('SELECT * FROM users WHERE username=?', (username,)).fetchone()
                    salt = row['salt'] if row else '00'*16
                    valid = hmac.compare_digest(password_hash(password, salt), row['password'] if row else '0'*128)
                    if not row or not valid:
                        return self.reply(401, {'error': '아이디 또는 비밀번호를 확인해 주세요.'})
                    uid = row['id']
                token = secrets.token_urlsafe(32)
                db.execute('DELETE FROM sessions WHERE expires<?', (now,))
                db.execute('INSERT INTO sessions VALUES (?,?,?)', (hashlib.sha256(token.encode()).hexdigest(), uid, now+604800))
                result = dict(db.execute('SELECT id,username,nickname FROM users WHERE id=?', (uid,)).fetchone())
                return self.reply(200, {'user': result}, self.session_cookie(token))
            if not user:
                return self.reply(401, {'error': '로그인이 필요합니다.'})
            uid = user['id']
            if path == '/api/logout' and method == 'POST':
                c = cookies.SimpleCookie(self.headers.get('Cookie', ''))
                token = c['gallery_session'].value if 'gallery_session' in c else ''
                db.execute('DELETE FROM sessions WHERE token=?', (hashlib.sha256(token.encode()).hexdigest(),))
                return self.reply(200, {'ok': True}, self.session_cookie('', 0))
            if path == '/api/galleries' and method == 'GET':
                return self.reply(200, {'galleries': GALLERIES})
            def serialize(row):
                p = dict(row)
                p['author'] = '익명' if p['anonymous'] else p['nickname']
                p['mine'] = p['user_id'] == uid
                p['likes'] = db.execute('SELECT count(*) FROM votes WHERE post_id=? AND value=1', (p['id'],)).fetchone()[0]
                p['dislikes'] = db.execute('SELECT count(*) FROM votes WHERE post_id=? AND value=-1', (p['id'],)).fetchone()[0]
                vote = db.execute('SELECT value FROM votes WHERE post_id=? AND user_id=?', (p['id'], uid)).fetchone()
                p['vote'] = vote[0] if vote else 0
                p['comment_count'] = db.execute('SELECT count(*) FROM comments WHERE post_id=?', (p['id'],)).fetchone()[0]
                del p['nickname'], p['user_id']
                return p
            if path == '/api/posts' and method == 'GET':
                rows = db.execute('SELECT p.*,u.nickname FROM posts p JOIN users u ON u.id=p.user_id ORDER BY p.id DESC LIMIT 200').fetchall()
                return self.reply(200, {'posts': [serialize(r) for r in rows]})
            if path == '/api/posts' and method == 'POST':
                title, content = field('title', 1, 100), field('content', 1, 10000)
                gid = body.get('galleryId')
                if gid not in [g['id'] for g in GALLERIES]:
                    raise ValueError('갤러리를 선택하세요.')
                if type(body.get('anonymous', False)) is not bool:
                    raise ValueError('익명 설정이 올바르지 않습니다.')
                cursor = db.execute('INSERT INTO posts(gallery_id,user_id,title,content,anonymous,created_at) VALUES (?,?,?,?,?,?)', (gid,uid,title,content,int(body.get('anonymous', False)),int(time.time())))
                return self.reply(201, {'id': cursor.lastrowid})
            parts = path.strip('/').split('/')
            if len(parts) in (3,4) and parts[:2] == ['api','posts'] and parts[2].isdigit():
                pid = int(parts[2])
                row = db.execute('SELECT p.*,u.nickname FROM posts p JOIN users u ON u.id=p.user_id WHERE p.id=?', (pid,)).fetchone()
                if not row:
                    return self.reply(404, {'error': '게시글을 찾을 수 없습니다.'})
                if len(parts) == 3 and method == 'GET':
                    p = serialize(row)
                    p['comments'] = [dict(c) for c in db.execute('SELECT c.id,c.content,c.created_at,u.nickname AS author FROM comments c JOIN users u ON u.id=c.user_id WHERE c.post_id=? ORDER BY c.id', (pid,))]
                    return self.reply(200, {'post': p})
                if len(parts) == 3 and method == 'DELETE':
                    if row['user_id'] != uid:
                        return self.reply(403, {'error': '작성자만 삭제할 수 있습니다.'})
                    db.execute('DELETE FROM posts WHERE id=?', (pid,))
                    return self.reply(200, {'ok': True})
                if len(parts) == 4 and parts[3] == 'vote' and method == 'POST':
                    value = body.get('value')
                    if type(value) is not int or value not in (-1,0,1):
                        raise ValueError('올바른 반응을 선택하세요.')
                    db.execute('DELETE FROM votes WHERE post_id=? AND user_id=?', (pid,uid))
                    if value:
                        db.execute('INSERT INTO votes VALUES (?,?,?)', (pid,uid,value))
                    return self.reply(200, {'ok': True})
                if len(parts) == 4 and parts[3] == 'comments' and method == 'POST':
                    content = field('content', 1, 2000)
                    db.execute('INSERT INTO comments(post_id,user_id,content,created_at) VALUES (?,?,?,?)', (pid,uid,content,int(time.time())))
                    return self.reply(201, {'ok': True})
            self.reply(404, {'error': '요청을 찾을 수 없습니다.'})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', '8000'))
    print(f'Gallery server listening on port {port}', flush=True)
    ThreadingHTTPServer((os.environ.get('HOST', '127.0.0.1'), port), Handler).serve_forever()
