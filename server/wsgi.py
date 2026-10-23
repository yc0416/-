"""Run the existing HTTP application behind a production WSGI server."""
import io
from email.message import Message
from http import HTTPStatus
from server.app import Handler

class WSGIHandler(Handler):
    def send_response(self, code, message=None):
        self.status = f'{code} {message or HTTPStatus(code).phrase}'
        self.response_headers = []

    def send_header(self, name, value):
        self.response_headers.append((name, value))

    def end_headers(self):
        pass

def application(environ, start_response):
    handler = WSGIHandler.__new__(WSGIHandler)
    handler.path = environ.get('PATH_INFO', '/')
    handler.client_address = (environ.get('REMOTE_ADDR', 'unknown'), 0)
    handler.headers = Message()
    for key, value in environ.items():
        if key.startswith('HTTP_'):
            handler.headers[key[5:].replace('_', '-')] = value
    handler.headers['Content-Type'] = environ.get('CONTENT_TYPE', '')
    handler.headers['Content-Length'] = environ.get('CONTENT_LENGTH', '') or '0'
    handler.rfile = environ['wsgi.input']
    handler.wfile = io.BytesIO()
    method = environ['REQUEST_METHOD']
    if method == 'GET':
        handler.do_GET()
    elif method in ('POST', 'PUT', 'DELETE'):
        handler.api(method, handler.path)
    else:
        handler.reply(405, {'error': '지원하지 않는 요청입니다.'})
    start_response(handler.status, handler.response_headers)
    return [handler.wfile.getvalue()]
