import http.cookiejar
import json
import os
import socket
import sys
import subprocess
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

class GalleryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        with socket.socket() as s:
            s.bind(('127.0.0.1', 0))
            port = s.getsockname()[1]
        cls.base = f'http://127.0.0.1:{port}'
        cls.process = subprocess.Popen([sys.executable, 'server/app.py'], cwd=Path(__file__).resolve().parents[1], env={**os.environ, 'PORT': str(port), 'GALLERY_DATA_DIR': cls.temp.name, 'GALLERY_INVITE_CODE': 'test-invite'}, stdout=subprocess.DEVNULL)
        for _ in range(100):
            try:
                urllib.request.urlopen(cls.base+'/api/health', timeout=1).close()
                break
            except OSError:
                time.sleep(.05)
        else:
            raise RuntimeError('Server did not start')

    @classmethod
    def tearDownClass(cls):
        cls.process.terminate()
        cls.process.wait(timeout=5)
        cls.temp.cleanup()

    def client(self):
        return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def req(self, client, path, data=None, method=None, headers=None):
        req = urllib.request.Request(self.base+'/api'+path, data=json.dumps(data).encode() if data is not None else None, method=method, headers={'Content-Type':'application/json', **(headers or {})})
        try:
            with client.open(req, timeout=5) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as e:
            return e.code, json.load(e)

    def test_complete_friend_workflow(self):
        a,b = self.client(), self.client()
        self.assertEqual(self.req(a,'/posts')[0],401)
        self.assertEqual(self.req(a,'/signup',{'username':'alice','nickname':'초코','password':'password123','inviteCode':'wrong'})[0],403)
        self.assertEqual(self.req(a,'/signup',{'username':'alice','nickname':'초코','password':'password123','inviteCode':'test-invite'})[0],200)
        self.assertEqual(self.req(b,'/signup',{'username':'friend','nickname':'친구','password':'password123','inviteCode':'test-invite'})[0],200)
        self.assertEqual(self.req(a,'/posts',{'title':' ','content':'test','galleryId':'free'})[0],400)
        status,p = self.req(a,'/posts',{'title':'주말에 모일까?','content':'토요일 어때?','galleryId':'free','anonymous':True})
        self.assertEqual(status,201)
        pid=p['id']
        status,p = self.req(b,f'/posts/{pid}')
        self.assertEqual(p['post']['author'],'익명')
        self.assertNotIn('user_id',p['post'])
        self.assertNotIn('nickname',p['post'])
        self.assertFalse(p['post']['mine'])
        for value in (1,1,-1,0):
            self.assertEqual(self.req(b,f'/posts/{pid}/vote',{'value':value})[0],200)
            post=self.req(a,f'/posts/{pid}')[1]['post']
            self.assertEqual((post['likes'],post['dislikes']), (int(value==1),int(value==-1)))
        self.assertEqual(self.req(b,f'/posts/{pid}/comments',{'content':'나도 갈게!'})[0],201)
        self.assertEqual(self.req(a,f'/posts/{pid}')[1]['post']['comments'][0]['content'],'나도 갈게!')
        self.assertEqual(self.req(b,f'/posts/{pid}',{},'DELETE')[0],403)
        self.assertEqual(self.req(a,'/posts',{'title':'bad','content':'bad','galleryId':'free'},headers={'Origin':'https://evil.example'})[0],403)
        self.assertEqual(self.req(a,'/logout',{})[0],200)
        self.assertEqual(self.req(a,'/posts')[0],401)
        self.assertEqual(self.req(a,'/login',{'username':'alice','password':'incorrect'})[0],401)
        self.assertEqual(self.req(a,'/login',{'username':'alice','password':'password123'})[0],200)
        self.assertEqual(self.req(a,f'/posts/{pid}')[0],200)
        self.assertEqual(self.req(a,f'/posts/{pid}',{},'DELETE')[0],200)
        self.assertEqual(self.req(b,f'/posts/{pid}')[0],404)

if __name__ == '__main__':
    unittest.main()
