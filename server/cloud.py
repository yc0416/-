"""Server-only PostgreSQL + private Supabase Storage integration."""
import json
from contextlib import contextmanager
import tempfile
import logging
import os
import ssl
import socket
import struct
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

class SetupError(Exception):
    """Contains only predefined messages safe for public deployment logs."""

class StorageError(Exception):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status

def sqlstate(error):
    if getattr(error, 'sqlstate', None):
        return error.sqlstate
    if error.args and isinstance(error.args[0], dict):
        return error.args[0].get('C')
    return None

def database_error_message(error):
    # Inspect driver details locally but never return them: URI/passwords can
    # appear in parsing errors. Only emit one of these fixed diagnostic strings.
    detail = str(error).lower()
    state = sqlstate(error)
    if state in ('28P01', '28000') or any(x in detail for x in ('password authentication failed', 'wrong password', 'tenant or user not found')):
        return '[DB_AUTH] Check the database password and Session pooler username (postgres.PROJECT_REF).'
    if any(x in detail for x in ('does not match host', 'hostname mismatch', 'host name mismatch')):
        return '[DB_TLS_HOSTNAME] Certificate does not match the database hostname. Recopy the Session pooler URI from the same Supabase project.'
    if 'certificate has expired' in detail or 'certificate expired' in detail:
        return '[DB_TLS_EXPIRED] The database certificate has expired. Check Supabase status and the downloaded CA certificate.'
    if any(x in detail for x in ('unable to get local issuer', 'unable to verify the first certificate', 'self-signed certificate', 'self signed certificate')):
        return '[DB_TLS_ISSUER] Database certificate issuer is not trusted. Confirm the CA was downloaded from this Supabase project.'
    if any(x in detail for x in ('certificate', 'sslrootcert', 'tls', 'ssl error')):
        return '[DB_TLS] Database certificate verification failed. Configure the trusted Supabase CA file with GALLERY_DB_CA_FILE; keep TLS verification enabled.'
    if any(x in detail for x in ('resolve', 'name resolution', 'network is unreachable', 'timeout', 'timed out', 'connection refused')):
        return '[DB_NETWORK] Database could not be reached. Copy the Session pooler URI (IPv4, port 5432) from Supabase Connect and check project status.'
    if state == '42501':
        return '[DB_PERMISSIONS] Use the postgres Session pooler account so the app can create its private gallery schema.'
    if any(x in detail for x in ('invalid', 'parse', 'missing', 'uri', 'percent')):
        return '[DB_URI] DATABASE_URL is not a valid PostgreSQL URI. Check password URL encoding and remove surrounding quotes.'
    return '[DB_CONNECT] Database connection failed. Check Session pooler URI, password and Supabase project status.'

@contextmanager
def database_trust():
    path = os.environ.get('GALLERY_DB_CA_FILE', 'system')
    if path == 'system':
        yield path
        return
    # A Supabase CA supplements system trust instead of replacing it. Session
    # pooler and direct connections can have different certificate issuers.
    context = ssl.create_default_context()
    try:
        context.load_verify_locations(cafile=path)
    except FileNotFoundError:
        raise SetupError('[DB_CA_MISSING] CA file was not found. Check Render Secret Files and GALLERY_DB_CA_FILE.') from None
    except PermissionError:
        raise SetupError('[DB_CA_UNREADABLE] App user cannot read the CA file in Render Secret Files.') from None
    except (ssl.SSLError, OSError):
        raise SetupError('[DB_CA_FORMAT] CA file is not a readable PEM certificate. Paste all BEGIN CERTIFICATE through END CERTIFICATE lines.') from None
    with tempfile.TemporaryDirectory(prefix='gallery-ca-') as folder:
        bundle_path = os.path.join(folder, 'trusted.pem')
        with open(bundle_path, 'w', encoding='ascii') as bundle:
            for certificate in context.get_ca_certs(binary_form=True):
                bundle.write(ssl.DER_cert_to_PEM_cert(certificate))
        yield bundle_path

def probe_database_tls(url, ca_file):
    """Unauthenticated PostgreSQL SSLRequest; emit fixed codes, never credentials."""
    from psycopg.conninfo import conninfo_to_dict
    try:
        settings = conninfo_to_dict(url)
        host = settings.get('host', '').split(',')[0]
        port = int(settings.get('port', '5432').split(',')[0])
        if not host or host.startswith('/'):
            return '[DB_TLS] Database TLS connection failed; verify the configured endpoint.'
        context = ssl.create_default_context(cafile=None if ca_file == 'system' else ca_file)
        with socket.create_connection((host, port), timeout=6) as connection:
            # SSL negotiation contains no username, password or database name.
            connection.sendall(struct.pack('!II', 8, 80877103))
            if connection.recv(1) != b'S':
                return '[DB_TLS_ENDPOINT] Endpoint did not accept PostgreSQL TLS. Check Session pooler host and port 5432.'
            with context.wrap_socket(connection, server_hostname=host):
                return '[DB_TLS_DRIVER] Certificate checks pass in the TLS probe, but the PostgreSQL driver failed. Check connection URI SSL options.'
    except ssl.SSLCertVerificationError as error:
        codes = {
            9: '[DB_TLS_NOT_YET_VALID] Database certificate is not yet valid. Check Supabase certificate status.',
            10: '[DB_TLS_EXPIRED] Database certificate has expired. Check Supabase certificate status.',
            18: '[DB_TLS_ISSUER] Database certificate issuer is not trusted. Download the CA from the same Supabase project.',
            19: '[DB_TLS_ISSUER] Database certificate issuer is not trusted. Download the CA from the same Supabase project.',
            20: '[DB_TLS_ISSUER] Certificate chain is incomplete or its issuer is not trusted. Download the CA from the same Supabase project.',
            21: '[DB_TLS_ISSUER] Certificate chain is incomplete or its issuer is not trusted. Download the CA from the same Supabase project.',
            62: '[DB_TLS_HOSTNAME] Certificate does not match the database hostname. Recopy the Session pooler URI.',
            64: '[DB_TLS_HOSTNAME] Certificate does not match the database IP address. Use the Session pooler hostname, not an IP address.'
        }
        return codes.get(error.verify_code, '[DB_TLS_VERIFY] Database certificate validation failed with a different certificate constraint.')
    except ssl.SSLError:
        return '[DB_TLS_HANDSHAKE] TLS negotiation failed before authentication. Check the PostgreSQL Session pooler endpoint.'
    except (OSError, ValueError):
        return '[DB_TLS_PROBE_NETWORK] TLS probe could not reach the database. Check Supabase status and the Session pooler endpoint.'

def connect_database(**extra):
    import pg8000.dbapi
    from psycopg.conninfo import conninfo_to_dict
    url = DATABASE_URL
    password = os.environ.get('DATABASE_PASSWORD')
    if len(url) >= 2 and url[0] == url[-1] and url[0] in ('"', "'"):
        url = url[1:-1]
    if not url.startswith(('postgresql://', 'postgres://')):
        raise SetupError('[DB_URI] Copy only the PostgreSQL URI from Supabase Session pooler, not a psql command or a DATABASE_URL= assignment.')
    markers = ('[YOUR-PASSWORD]', '[YOUR_PASSWORD]')
    if password:
        # Keep the copied template untouched in Render. Pass the raw password
        # as a driver parameter, avoiding URL encoding of @, #, %, / etc.
        for marker in markers:
            url = url.replace(marker, '')
        extra['password'] = password
    elif any(marker in url.upper() for marker in markers):
        raise SetupError('[DB_PASSWORD_UNSET] Set DATABASE_PASSWORD to the raw database password. Keep the copied Session pooler URI in DATABASE_URL.')
    try:
        with database_trust() as ca_file:
            try:
                settings = conninfo_to_dict(url)
                context = ssl.create_default_context(cafile=None if ca_file == 'system' else ca_file)
                # pg8000 uses Python's verified SSLContext, the same TLS stack
                # used by the successful PostgreSQL certificate probe.
                return DatabaseClient(pg8000.dbapi.connect(
                    user=settings.get('user'), password=extra.get('password', settings.get('password')),
                    host=settings.get('host', 'localhost'), port=int(settings.get('port', '5432')),
                    database=settings.get('dbname', 'postgres'), ssl_context=context, timeout=10))
            except Exception as error:
                message = database_error_message(error)
                if message.startswith('[DB_TLS]'):
                    message = probe_database_tls(url, ca_file)
                raise SetupError(message) from None
    except SetupError:
        raise
    except Exception as error:
        raise SetupError(database_error_message(error)) from None

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
        raise StorageError(f'Private photo storage request failed ({error.code}).', status=error.code) from None
    except (URLError, TimeoutError, OSError):
        raise StorageError('Private photo storage is temporarily unavailable.') from None

def verify_storage():
    try:
        bucket = json.loads(storage_request('GET', f'bucket/{BUCKET}'))
    except StorageError as error:
        if error.status in (401, 403):
            raise SetupError('[STORAGE_KEY] Storage rejected the key. Use the legacy service_role key from the SAME Supabase project, not anon/Publishable key.') from None
        if error.status == 404:
            raise SetupError('[STORAGE_BUCKET] Create a PRIVATE bucket named gallery-images in this Supabase project.') from None
        raise SetupError('[STORAGE_NETWORK] Storage is unavailable. Check SUPABASE_URL and Supabase project status.') from None
    except ValueError:
        raise SetupError('[STORAGE_RESPONSE] SUPABASE_URL did not return a valid Storage response. Copy the project HTTPS URL.') from None
    if not isinstance(bucket, dict) or bucket.get('public') is not False:
        raise SetupError('[STORAGE_PUBLIC] gallery-images must be a PRIVATE bucket. Turn Public bucket OFF.')

def image_path(iid, authenticated=False):
    return f'object/{"authenticated/" if authenticated else ""}{BUCKET}/{iid}.jpg'

def delete_image(iid):
    storage_request('DELETE', f'object/{BUCKET}', json.dumps({'prefixes': [f'{iid}.jpg']}).encode(), 'application/json')

class Row(dict):
    def __getitem__(self, key):
        return tuple(self.values())[key] if isinstance(key, int) else super().__getitem__(key)

class DatabaseResult:
    def __init__(self, cursor):
        self.cursor = cursor
        self.names = [column[0] for column in cursor.description] if cursor.description else []
    def fetchone(self):
        values = self.cursor.fetchone()
        return Row(zip(self.names, values)) if values is not None else None
    def fetchall(self):
        return [Row(zip(self.names, values)) for values in self.cursor.fetchall()]
    def __iter__(self):
        while (row := self.fetchone()) is not None:
            yield row

class DatabaseClient:
    def __init__(self, connection): self.connection = connection
    def execute(self, sql, params=()):
        cursor = self.connection.cursor()
        cursor.execute(sql, params)
        return DatabaseResult(cursor)
    def commit(self): self.connection.commit()
    def rollback(self): self.connection.rollback()
    def close(self): self.connection.close()
    @contextmanager
    def transaction(self):
        try:
            yield
            self.commit()
        except Exception:
            self.rollback()
            raise
    def __enter__(self): return self
    def __exit__(self, kind, value, traceback):
        try:
            self.commit() if kind is None else self.rollback()
        finally:
            self.close()

class Cursor:
    def __init__(self, raw, lastrowid=None):
        self.raw, self.lastrowid = raw, lastrowid
    def fetchone(self): return self.raw.fetchone()
    def fetchall(self): return self.raw.fetchall()
    def __iter__(self): return iter(self.raw)

class Connection:
    def __init__(self):
        self.raw = connect_database()
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
    with connect_database() as db:
        # Serialize schema initialization if multiple worker starts overlap.
        db.execute('SELECT pg_advisory_xact_lock(7041601)')
        for statement in SCHEMA.split(';'):
            if statement.strip():
                db.execute(statement)
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
