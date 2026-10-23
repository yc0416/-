"""Server-only PostgreSQL + private Supabase Storage integration."""
import json
import logging
import os
import ssl
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

DATABASE_URL = os.environ.get('DATABASE_URL', '').strip()
SUPABASE_URL = os.environ.get('SUPABASE_URL', '').strip().rstrip('/')
SERVICE_KEY = os.environ.get('SUPABASE_SERVICE_ROLE_KEY', '').strip()
BUCKET = 'gallery-images'
ENABLED = bool(DATABASE_URL)
if any((DATABASE_URL, SUPABASE_URL, SERVICE_KEY)) and not all((DATABASE_URL, SUPABASE_URL, SERVICE_KEY)):
    raise RuntimeError('Cloud setup requires DATABASE_URL, SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY together. Set values privately in Render Environment.')
if os.environ.get('GALLERY_REQUIRE_CLOUD') == '1' and not ENABLED:
    raise RuntimeError('This deployment requires Supabase. Local SQLite fallback is disabled.')
if ENABLED and (urlsplit(SUPABASE_URL).scheme != 'https' or not urlsplit(SUPABASE_URL).hostname):
    raise RuntimeError('SUPABASE_URL must be an HTTPS project URL.')

class StorageError(Exception):
    pass

def storage_request(method, path, content=None, content_type='image/jpeg'):
    headers = {'apikey': SERVICE_KEY, 'Authorization': f'Bearer {SERVICE_KEY}'}
    if content is not None:
        headers['Content-Type'] = content_type
    request = Request(f'{SUPABASE_URL}/storage/v1/{path}', data=content, method=method, headers=headers)
    try:
        with urlopen(request, timeout=20, context=ssl.create_default_context()) as response:
            return response.read()
    except HTTPError as error:
        # Never expose key, request headers, database URL, or upstream response body.
        if method == 'DELETE' and error.code == 404:
            return b''
        raise StorageError(f'Private photo storage request failed ({error.code}).') from None
    except (URLError, TimeoutError, OSError):
        raise StorageError('Private photo storage is temporarily unavailable.') from None

def verify_storage():
    try:
        bucket = json.loads(storage_request('GET', f'bucket/{BUCKET}'))
    except (ValueError, StorageError):
        raise RuntimeError('Create the private gallery-images bucket and verify the server-only Supabase service_role key.') from None
    if bucket.get('public') is not False:
        raise RuntimeError('gallery-images must be a PRIVATE bucket.')

def image_path(iid, authenticated=False):
    return f'object/{"authenticated/" if authenticated else ""}{BUCKET}/{iid}.jpg'

def delete_image(iid):
    storage_request('DELETE', f'object/{BUCKET}', json.dumps({'prefixes': [f'{iid}.jpg']}).encode(), 'application/json')

class Row(dict):
    def __getitem__(self, key):
        return tuple(self.values())[key] if isinstance(key, int) else super().__getitem__(key)

def row_factory(cursor):
    names = [column.name for column in cursor.description] if cursor.description else []
    return lambda values: Row(zip(names, values))

class Cursor:
    def __init__(self, raw, lastrowid=None):
        self.raw, self.lastrowid = raw, lastrowid
    def fetchone(self): return self.raw.fetchone()
    def fetchall(self): return self.raw.fetchall()
    def __iter__(self): return iter(self.raw)

class Connection:
    def __init__(self):
        import psycopg
        # verify-full checks both the CA and hostname. Never downgrade cloud TLS.
        self.raw = psycopg.connect(DATABASE_URL, sslmode='verify-full',
            sslrootcert=os.environ.get('GALLERY_DB_CA_FILE', 'system'),
            connect_timeout=10, prepare_threshold=None, row_factory=row_factory)
        self.raw.execute('SET search_path TO gallery, public')
        self.raw.execute("SET statement_timeout TO '15s'")
        self.uploaded = []

    def execute(self, sql, params=()):
        sql = sql.replace('?', '%s')
        returning = sql.startswith(('INSERT INTO users(', 'INSERT INTO posts('))
        cursor = self.raw.execute(sql + (' RETURNING id' if returning else ''), params)
        lastrowid = cursor.fetchone()['id'] if returning else None
        return Cursor(cursor, lastrowid)

    def upload(self, iid, content):
        storage_request('POST', image_path(iid), content)
        self.uploaded.append(iid)

    def queue_delete(self, iid):
        self.execute('INSERT INTO storage_cleanup(id) VALUES (?) ON CONFLICT DO NOTHING', (iid,))

    def commit(self):
        self.raw.commit()
        self.uploaded.clear()
        self.cleanup()

    def cleanup(self):
        # Deletions are transactional outbox entries. Failed remote deletes retry
        # on later writes; no object is removed before its DB change is committed.
        try:
            with self.raw.transaction():
                rows = self.execute('SELECT id FROM storage_cleanup LIMIT 12 FOR UPDATE SKIP LOCKED').fetchall()
                for row in rows:
                    try:
                        delete_image(row['id'])
                    except StorageError:
                        logging.warning('Photo cleanup pending; will retry on a later write.')
                        break
                    self.execute('DELETE FROM storage_cleanup WHERE id=?', (row['id'],))
        except Exception:
            # The primary mutation was already committed. Cleanup cannot turn
            # a successful post into an apparent failure and duplicate retries.
            logging.warning('Photo cleanup deferred.')

    def __enter__(self): return self
    def __exit__(self, kind, value, traceback):
        try:
            if kind is None:
                # GETs and explicit-commit writes have nothing left to publish.
                self.raw.commit()
            else:
                self.raw.rollback()
                for iid in self.uploaded:
                    try:
                        delete_image(iid)
                    except StorageError:
                        logging.warning('Interrupted photo upload needs orphan cleanup.')
        finally:
            self.raw.close()

SCHEMA = '''
CREATE SCHEMA IF NOT EXISTS gallery;
REVOKE ALL ON SCHEMA gallery FROM PUBLIC;
SET search_path TO gallery, public;
CREATE TABLE IF NOT EXISTS users(id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY, username TEXT UNIQUE NOT NULL, nickname TEXT NOT NULL, salt TEXT NOT NULL, password TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE, expires BIGINT NOT NULL);
CREATE TABLE IF NOT EXISTS posts(id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY, gallery_id TEXT NOT NULL, user_id BIGINT NOT NULL REFERENCES users(id), title TEXT NOT NULL, content TEXT NOT NULL, anonymous INTEGER NOT NULL DEFAULT 0, created_at BIGINT NOT NULL);
CREATE TABLE IF NOT EXISTS comments(id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY, post_id BIGINT NOT NULL REFERENCES posts(id) ON DELETE CASCADE, user_id BIGINT NOT NULL REFERENCES users(id), content TEXT NOT NULL, created_at BIGINT NOT NULL);
CREATE TABLE IF NOT EXISTS votes(post_id BIGINT REFERENCES posts(id) ON DELETE CASCADE, user_id BIGINT REFERENCES users(id), value INTEGER CHECK(value IN (-1,1)), PRIMARY KEY(post_id,user_id));
CREATE TABLE IF NOT EXISTS attempts(ip TEXT NOT NULL, created_at BIGINT NOT NULL);
CREATE TABLE IF NOT EXISTS images(id TEXT PRIMARY KEY, post_id BIGINT NOT NULL REFERENCES posts(id) ON DELETE CASCADE, content BYTEA NOT NULL);
CREATE TABLE IF NOT EXISTS storage_cleanup(id TEXT PRIMARY KEY);
CREATE INDEX IF NOT EXISTS comments_post_idx ON comments(post_id);
CREATE INDEX IF NOT EXISTS images_post_idx ON images(post_id);
CREATE INDEX IF NOT EXISTS attempts_time_idx ON attempts(created_at);
'''

def initialize():
    import psycopg
    with psycopg.connect(DATABASE_URL, sslmode='verify-full',
            sslrootcert=os.environ.get('GALLERY_DB_CA_FILE', 'system'), connect_timeout=10,
            prepare_threshold=None) as db:
        # Serialize schema initialization if multiple worker starts overlap.
        db.execute('SELECT pg_advisory_xact_lock(7041601)')
        db.execute(SCHEMA, prepare=False)
        for name in ('users','sessions','posts','comments','votes','attempts','images','storage_cleanup'):
            db.execute(f'ALTER TABLE gallery.{name} ENABLE ROW LEVEL SECURITY')
            db.execute(f'REVOKE ALL ON gallery.{name} FROM PUBLIC')
        # Supabase browser roles receive no access to passwords or private rows.
        for role in ('anon', 'authenticated'):
            if db.execute('SELECT 1 FROM pg_roles WHERE rolname=%s', (role,)).fetchone():
                db.execute(f'REVOKE ALL ON SCHEMA gallery FROM {role}')
                db.execute(f'REVOKE ALL ON ALL TABLES IN SCHEMA gallery FROM {role}')
                db.execute(f'REVOKE ALL ON ALL SEQUENCES IN SCHEMA gallery FROM {role}')
    verify_storage()
