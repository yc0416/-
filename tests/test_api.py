import base64
import io
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
        command = [sys.executable, '-m', 'gunicorn', '--bind', f'127.0.0.1:{port}', '--workers', '1', '--threads', '4', 'server.wsgi:application'] if os.environ.get('GALLERY_TEST_WSGI') else [sys.executable, 'server/app.py']
        cls.server_env = {**os.environ, 'PORT': str(port), 'GALLERY_DATA_DIR': cls.temp.name, 'GALLERY_INVITE_CODE': 'test-invite'}
        cls.server_env['GALLERY_ADMIN_USERNAMES'] = ''
        if os.environ.get('GALLERY_TEST_CLOUD') != '1':
            for name in ('DATABASE_URL', 'DATABASE_PASSWORD', 'SUPABASE_URL', 'SUPABASE_SERVICE_ROLE_KEY', 'GALLERY_REQUIRE_CLOUD'):
                cls.server_env.pop(name, None)

        cls.process = subprocess.Popen(command, cwd=Path(__file__).resolve().parents[1], env=cls.server_env, stdout=subprocess.DEVNULL)
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

    def test_admin_deletes_others_posts_but_cannot_edit_them(self):
        from PIL import Image
        admin, author, other, guest = self.client(), self.client(), self.client(), self.client()
        for client, name, nickname in ((admin,'galleryadmin','운영자'),(author,'modauthor','작성자'),(other,'modother','galleryadmin')):
            status,result=self.req(client,'/signup',{'username':name,'nickname':nickname,'password':'password123','inviteCode':'test-invite','is_admin':True})
            self.assertEqual(status,200)
            self.assertFalse(result['user']['is_admin'])
        output=io.BytesIO();Image.new('RGB',(5,5),'blue').save(output,'PNG')
        data={'title':'관리 테스트','content':'테스트 글','galleryId':'free','images':[{'data':base64.b64encode(output.getvalue()).decode()}]}
        pid=self.req(author,'/posts',data)[1]['id']
        self.assertEqual(self.req(other,f'/posts/{pid}',{},'DELETE')[0],403)
        self.assertEqual(self.req(admin,f'/posts/{pid}',{},'DELETE')[0],403)
        self.assertFalse(self.req(other,f'/posts/{pid}')[1]['post']['can_delete'])
        self.assertTrue(self.req(author,f'/posts/{pid}')[1]['post']['can_delete'])
        # Admin is enabled by server configuration only, after account creation.
        cls=type(self);command=cls.process.args
        cls.process.terminate();cls.process.wait(timeout=5)
        cls.server_env['GALLERY_ADMIN_USERNAMES']=' GALLERYADMIN '
        cls.process=subprocess.Popen(command,cwd=Path(__file__).resolve().parents[1],env=cls.server_env,stdout=subprocess.DEVNULL)
        for _ in range(100):
            try:
                urllib.request.urlopen(self.base+'/api/health',timeout=1).close();break
            except OSError:time.sleep(.05)
        self.assertTrue(self.req(admin,'/me')[1]['user']['is_admin'])
        self.assertFalse(self.req(other,'/me')[1]['user']['is_admin'])
        post=self.req(admin,f'/posts/{pid}')[1]['post']
        self.assertFalse(post['mine'])
        self.assertTrue(post['can_delete'])
        self.assertEqual(self.req(admin,f'/posts/{pid}',{**data,'title':'변조'},'PUT')[0],403)
        self.assertEqual(self.req(guest,f'/posts/{pid}',{},'DELETE')[0],401)
        self.assertEqual(self.req(admin,f'/posts/{pid}',{},'DELETE')[0],200)
        self.assertEqual(self.req(author,f'/posts/{pid}')[0],404)
        self.assertEqual(self.req(author,post['images'][0]['url'].removeprefix('/api'))[0],404)
        self.assertEqual(self.req(guest,'/signup',{'username':'galleryadmin','nickname':'운영자','password':'password123','inviteCode':'test-invite'})[0],403)

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

    def test_images_edit_and_comment_permissions(self):
        from PIL import Image
        a, b, guest = self.client(), self.client(), self.client()
        for client, name in ((a, 'photoauthor'), (b, 'photofriend')):
            self.assertEqual(self.req(client, '/signup', {'username':name,'nickname':name,'password':'password123','inviteCode':'test-invite'})[0],200)
        output = io.BytesIO()
        Image.new('RGB',(20,20),'green').save(output,'PNG')
        image = {'data':base64.b64encode(output.getvalue()).decode()}
        data = {'title':'사진 글','content':'내용','galleryId':'free','images':[image]}
        status, result = self.req(a,'/posts',data)
        self.assertEqual(status,201)
        pid=result['id']
        post=self.req(a,f'/posts/{pid}')[1]['post']
        url=post['images'][0]['url']
        self.assertEqual(self.req(guest,url.removeprefix('/api'))[0],401)
        with b.open(self.base+url) as r:
            self.assertEqual(r.headers['Content-Type'],'image/jpeg')
            self.assertEqual(Image.open(io.BytesIO(r.read())).size,(20,20))
        self.assertEqual(self.req(b,f'/posts/{pid}',data,'PUT')[0],403)
        data.update(title='수정된 제목',images=[{'id':post['images'][0]['id']}])
        self.assertEqual(self.req(a,f'/posts/{pid}',data,'PUT')[0],200)
        post=self.req(a,f'/posts/{pid}')[1]['post']
        self.assertEqual(post['title'],'수정된 제목')
        self.assertEqual(post['images'][0]['url'],url)
        # Invalid uploads must not erase attachments or change content.
        self.assertEqual(self.req(a,f'/posts/{pid}',{**data,'title':'bad','images':[{'data':'bad'}]},'PUT')[0],400)
        self.assertEqual(self.req(a,f'/posts/{pid}')[1]['post']['title'],'수정된 제목')
        self.assertEqual(self.req(a,'/posts',{**data,'images':[image]*4})[0],400)
        self.assertEqual(self.req(a,'/posts',{**data,'images':[{'data':base64.b64encode(b'<svg/>').decode()}]})[0],400)
        self.assertEqual(self.req(b,f'/posts/{pid}/comments',{'content':'내 댓글'})[0],201)
        comment=self.req(b,f'/posts/{pid}')[1]['post']['comments'][0]
        self.assertTrue(comment['mine'])
        cid=comment['id']
        self.assertEqual(self.req(a,f'/comments/{cid}',{},'DELETE')[0],403)
        self.assertEqual(self.req(b,f'/comments/{cid}',{},'DELETE')[0],200)
        self.assertEqual(self.req(a,f'/posts/{pid}')[1]['post']['comments'],[])
        # Restart against the same on-disk database: images and sessions survive.
        cls = type(self)
        command = cls.process.args
        cls.process.terminate()
        cls.process.wait(timeout=5)
        cls.process = subprocess.Popen(command, cwd=Path(__file__).resolve().parents[1], env=cls.server_env, stdout=subprocess.DEVNULL)
        for _ in range(100):
            try:
                urllib.request.urlopen(self.base+'/api/health', timeout=1).close()
                break
            except OSError:
                time.sleep(.05)
        self.assertEqual(self.req(a,f'/posts/{pid}')[1]['post']['title'],'수정된 제목')
        with b.open(self.base+url) as response:
            self.assertEqual(response.status,200)
        self.assertEqual(self.req(a,f'/posts/{pid}',{**data,'images':[]},'PUT')[0],200)
        self.assertEqual(self.req(b,url.removeprefix('/api'))[0],404)
        self.assertEqual(self.req(a,f'/posts/{pid}',{},'DELETE')[0],200)

if __name__ == '__main__':
    unittest.main()
