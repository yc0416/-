"""Optional integration runner: Docker, OpenSSL and installed requirements required.
Starts disposable TLS PostgreSQL and an authenticated HTTPS Storage test double.
Does not connect to the user's Supabase project or print credentials.
Run: node scripts/python.mjs tests/cloud_integration.py
"""
import io
import json
import os
from pathlib import Path
import secrets
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import quote
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = Path(__file__).resolve().parents[1]
objects = {}
KEY = secrets.token_urlsafe(24)

def port():
    with socket.socket() as s:
        s.bind(('127.0.0.1',0))
        return s.getsockname()[1]

class Storage(BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def answer(self, status, data):
        self.send_response(status)
        self.send_header('Content-Length',str(len(data)))
        self.end_headers()
        self.wfile.write(data)
    def handle_request(self):
        if self.headers.get('apikey') != KEY or self.headers.get('Authorization') != f'Bearer {KEY}':
            return self.answer(401,b'{}')
        if self.path == '/storage/v1/bucket/gallery-images' and self.command == 'GET':
            return self.answer(200,b'{"public":false,"id":"gallery-images"}')
        if self.path == '/storage/v1/object/gallery-images' and self.command == 'DELETE':
            body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            for name in body['prefixes']: objects.pop(name,None)
            return self.answer(200,b'[]')
        prefix='/storage/v1/object/' + ('authenticated/' if self.command == 'GET' else '') + 'gallery-images/'
        if not self.path.startswith(prefix): return self.answer(404,b'{}')
        name=self.path[len(prefix):]
        if self.command=='POST':
            if name in objects: return self.answer(409,b'{}')
            objects[name]=self.rfile.read(int(self.headers['Content-Length']))
            return self.answer(200,b'{}')
        if name not in objects: return self.answer(404,b'{}')
        return self.answer(200,objects[name])
    do_GET=handle_request
    do_POST=handle_request
    do_DELETE=handle_request

with tempfile.TemporaryDirectory(prefix='gallery-cloud-') as folder:
    tls=Path(folder)
    tls.chmod(0o755)
    subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-keyout',str(tls/'server.key'),'-out',str(tls/'server.crt'),'-days','1','-subj','/CN=localhost','-addext','subjectAltName=DNS:localhost,IP:127.0.0.1','-addext','basicConstraints=critical,CA:TRUE'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    (tls/'server.crt').chmod(0o644)
    # A private temporary key is copied into this disposable PostgreSQL container.
    db_port, storage_port=port(),port()
    password=secrets.token_urlsafe(24)+'@:#%/?[]'
    container='gallery-pg-'+secrets.token_hex(4)
    context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(str(tls/'server.crt'),str(tls/'server.key'))
    storage=ThreadingHTTPServer(('127.0.0.1',storage_port),Storage)
    storage.socket=context.wrap_socket(storage.socket,server_side=True)
    thread=threading.Thread(target=storage.serve_forever,daemon=True);thread.start()
    db_url=f'postgresql://postgres:{quote(password,safe="")}@localhost:{db_port}/postgres'
    env={**os.environ,'DATABASE_URL':db_url.replace(quote(password,safe=''),'[YOUR-PASSWORD]'),'DATABASE_PASSWORD':password,'SUPABASE_URL':f'https://localhost:{storage_port}',
        'SUPABASE_SERVICE_ROLE_KEY':KEY,'SSL_CERT_FILE':str(tls/'server.crt'),
        'GALLERY_DB_CA_FILE':str(tls/'server.crt'),'GALLERY_REQUIRE_CLOUD':'1','GALLERY_TEST_WSGI':'1','GALLERY_TEST_CLOUD':'1'}
    try:
        subprocess.run(['docker','run','-d','--name',container,'-p',f'127.0.0.1:{db_port}:5432','-e','POSTGRES_PASSWORD','-v',f'{tls}:/tls','postgres:17','sh','-c','chown postgres:postgres /tls/server.key && chmod 600 /tls/server.key && exec docker-entrypoint.sh postgres -c ssl=on -c ssl_cert_file=/tls/server.crt -c ssl_key_file=/tls/server.key'],env={**os.environ,'POSTGRES_PASSWORD':password},check=True,stdout=subprocess.DEVNULL)
        import psycopg
        def connect():
            return psycopg.connect(db_url,sslmode='verify-full',sslrootcert=str(tls/'server.crt'),connect_timeout=1)
        for _ in range(100):
            try:
                with connect() as db:
                    db.execute('SELECT 1')
                break
            except psycopg.OperationalError:time.sleep(.15)
        else: raise RuntimeError('Disposable PostgreSQL failed to start')
        with connect() as db:
            db.execute('CREATE ROLE anon')
            db.execute('CREATE ROLE authenticated')
        result=subprocess.run([sys.executable,'-m','unittest','discover','-s','tests','-v'],cwd=ROOT,env=env)
        if result.returncode: raise RuntimeError('Cloud API integration failed')
        with connect() as db:
            for role in ('anon','authenticated'):
                assert not db.execute("SELECT has_schema_privilege(%s,'gallery','USAGE')",(role,)).fetchone()[0]
                assert not db.execute("SELECT has_table_privilege(%s,'gallery.users','SELECT')",(role,)).fetchone()[0]
            assert db.execute("SELECT count(*) FROM pg_tables WHERE schemaname='gallery' AND rowsecurity").fetchone()[0]==8
            assert db.execute('SELECT count(*) FROM gallery.storage_cleanup').fetchone()[0]==0
        assert not objects, 'Deleted photos must be removed from private Storage'
        print('PASS: real TLS PostgreSQL + HTTPS Storage API double; full workflow, restart persistence, RLS/role isolation and remote object deletion.')
    finally:
        subprocess.run(['docker','rm','-f','-v',container],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        storage.shutdown()
        storage.server_close()
