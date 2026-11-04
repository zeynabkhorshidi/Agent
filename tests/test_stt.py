"""آزمون قرارداد HTTP با پاسخ کنترل‌شده؛ آزمون دقت Google/Whisper نیست."""
import asyncio
import io
import os
import tempfile
import time
import unittest
import uuid
import wave
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient
from sellora.app import app
from sellora import db
from sellora.stt import HTTPSTT, STTConfig, STTError


def wav():
    out=io.BytesIO()
    with wave.open(out,'wb') as w:
        w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);w.writeframes(b'\0\0'*1600)
    return out.getvalue()


def result(mode='online',text='پرتقال دو کارتن'):
    return {'text':text,'language':'fa','engine':'google_online' if mode=='online' else 'faster_whisper_offline',
            'duration_seconds':0.1,'processing_seconds':0.02,'segments':[]}


class AdapterTests(unittest.IsolatedAsyncioTestCase):
    def service(self, handler, **kw):
        return HTTPSTT(STTConfig('http://stt.test', **kw),httpx.MockTransport(handler))

    async def test_exact_multipart_contract(self):
        requests=[]
        def handler(request):
            requests.append(request)
            self.assertEqual(request.url.path,'/api/v1/stt/online')
            self.assertIn('multipart/form-data',request.headers['content-type'])
            self.assertIn(b'name="file"; filename="voice.wav"',request.content)
            self.assertIn(b'RIFF',request.content)
            return httpx.Response(200,json=result())
        transcript,fallback=await self.service(handler).transcribe(wav(),'voice.wav','audio/wav','auto')
        self.assertEqual(transcript.text,'پرتقال دو کارتن');self.assertFalse(fallback);self.assertEqual(len(requests),1)

    async def test_auto_fallback(self):
        paths=[]
        def handler(r):
            paths.append(r.url.path)
            return httpx.Response(502,json={'error':{'code':'online_unavailable'}}) if r.url.path.endswith('online') else httpx.Response(200,json=result('offline'))
        transcript,fallback=await self.service(handler).transcribe(wav(),'v.wav','audio/wav','auto')
        self.assertTrue(fallback);self.assertEqual(transcript.engine,'faster_whisper_offline');self.assertEqual(paths,['/api/v1/stt/online','/api/v1/stt/offline'])

    async def test_online_no_fallback(self):
        paths=[]
        def handler(r):paths.append(r.url.path);return httpx.Response(502)
        with self.assertRaises(STTError):await self.service(handler).transcribe(wav(),'v.wav','audio/wav','online')
        self.assertEqual(len(paths),1)

    async def test_offline_only(self):
        def handler(r):self.assertTrue(r.url.path.endswith('/offline'));return httpx.Response(200,json=result('offline'))
        _,fallback=await self.service(handler).transcribe(wav(),'v.wav','audio/wav','offline');self.assertFalse(fallback)

    async def test_no_retry_for_invalid_audio(self):
        for status in (400,413,422,401,403):
            requests=[]
            def handler(r):requests.append(r);return httpx.Response(status,json={'error':{'code':'no_speech','message':'raw server text'}})
            with self.assertRaises(STTError) as error:await self.service(handler).transcribe(wav(),'v.wav','audio/wav','auto')
            self.assertEqual(len(requests),1);self.assertNotIn('raw server text',error.exception.message)

    async def test_empty_text_not_fallback(self):
        requests=[]
        def handler(r):requests.append(r);return httpx.Response(200,json=result(text='  '))
        with self.assertRaises(STTError) as error:await self.service(handler).transcribe(wav(),'v.wav','audio/wav','auto')
        self.assertEqual(error.exception.status,422);self.assertEqual(len(requests),1)

    async def test_timeout_falls_back(self):
        def handler(r):
            if r.url.path.endswith('/online'):raise httpx.ReadTimeout('test')
            return httpx.Response(200,json=result('offline'))
        _,fallback=await self.service(handler).transcribe(wav(),'v.wav','audio/wav','auto');self.assertTrue(fallback)

    async def test_both_fail(self):
        with self.assertRaises(STTError) as e:await self.service(lambda r:httpx.Response(503)).transcribe(wav(),'v.wav','audio/wav','auto')
        self.assertEqual(e.exception.code,'all_unavailable')

    async def test_invalid_response_and_redirect(self):
        for response in (httpx.Response(200,json={'unexpected':True}),httpx.Response(200,json=result('offline')),httpx.Response(302,headers={'Location':'http://elsewhere.test'})):
            with self.assertRaises(STTError):await self.service(lambda r:response).transcribe(wav(),'v.wav','audio/wav','online')

    async def test_circuit_recovers(self):
        calls=[];healthy=False
        def handler(r):calls.append(r);return httpx.Response(200,json=result()) if healthy else httpx.Response(502)
        service=self.service(handler)
        for i in range(2):
            with self.assertRaises(STTError):await service.transcribe(wav(),'v.wav','audio/wav','online')
        with self.assertRaises(STTError) as e:await service.transcribe(wav(),'v.wav','audio/wav','online')
        self.assertEqual(e.exception.code,'circuit_open');self.assertEqual(len(calls),2)
        healthy=True;service.open_until['online']=0
        t,_=await service.transcribe(wav(),'v.wav','audio/wav','online');self.assertTrue(t.text);self.assertEqual(service.failures['online'],0)

    async def test_health_not_inference_claim(self):
        s=await self.service(lambda r:httpx.Response(200,json={'status':'ok','offline_model_files_present':True,'offline_model_loaded':False})).health()
        self.assertTrue(s['reachable']);self.assertFalse(s['offline_model_loaded']);self.assertIn('فقط با تبدیل واقعی',s['message'])

    async def test_unconfigured(self):
        service=HTTPSTT(STTConfig(''))
        self.assertFalse((await service.health())['configured'])
        with self.assertRaises(STTError) as e:await service.transcribe(wav(),'v.wav','audio/wav','auto')
        self.assertEqual(e.exception.code,'not_configured')


class VoiceAPITests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=patch.object(db,'PATH',str(Path(self.temp.name)/'voice.db'));self.path.start()
        self.ctx=TestClient(app);self.ctx.__enter__();self.ctx.get('/api/session');self.calls=[]
        def handler(r):self.calls.append(r);return httpx.Response(200,json=result())
        self.ctx.app.state.stt=HTTPSTT(STTConfig('http://stt.test'),httpx.MockTransport(handler))
    def tearDown(self):self.ctx.__exit__(None,None,None);self.path.stop();self.temp.cleanup()
    def upload(self,tid=None,audio=None,name='speech.wav'):
        return self.ctx.post('/api/voice/transcribe',data={'turn_id':tid or uuid.uuid4().hex},files={'file':(name,wav() if audio is None else audio,'audio/wav')})
    def test_audio_is_draft_and_duplicate_safe(self):
        before=self.ctx.get('/api/session').json();tid=uuid.uuid4().hex
        r=self.upload(tid);self.assertEqual(r.status_code,200,r.text);self.assertEqual(r.json()['text'],'پرتقال دو کارتن')
        again=self.upload(tid);self.assertTrue(again.json()['duplicate']);self.assertEqual(len(self.calls),1)
        after=self.ctx.get('/api/session').json();self.assertEqual(before['cart'],after['cart']);self.assertEqual(before['messages'],after['messages'])
        with db.connect() as c:
            a=c.execute("SELECT data FROM audit_events WHERE kind='voice.completed'").fetchone()[0];self.assertNotIn('پرتقال',a)
    def test_duplicate_payload_conflict(self):
        tid=uuid.uuid4().hex;self.assertEqual(self.upload(tid).status_code,200);self.assertEqual(self.upload(tid,wav()+b'x').status_code,409)
    def test_reject_empty_invalid_oversized(self):
        self.assertEqual(self.upload(audio=b'').status_code,400)
        self.assertEqual(self.upload(name='bad.exe').status_code,400)
        self.ctx.app.state.stt.config=STTConfig('http://stt.test',max_bytes=10)
        self.assertEqual(self.upload().status_code,413);self.assertEqual(len(self.calls),0)
    def test_session_and_origin(self):
        c=TestClient(app);r=c.post('/api/voice/transcribe',data={'turn_id':uuid.uuid4().hex},files={'file':('a.wav',wav())});self.assertEqual(r.status_code,401)
        r=self.ctx.post('/api/voice/transcribe',headers={'Origin':'https://evil.test'},data={'turn_id':uuid.uuid4().hex},files={'file':('a.wav',wav())});self.assertEqual(r.status_code,403)
    def test_early_cancel_and_late_replay(self):
        tid=uuid.uuid4().hex;self.ctx.post('/api/voice/cancel/'+tid)
        self.assertEqual(self.upload(tid).status_code,409);self.assertEqual(len(self.calls),0)
        tid=uuid.uuid4().hex;self.upload(tid);self.ctx.post('/api/voice/cancel/'+tid);self.assertEqual(self.upload(tid).status_code,409)
    def test_cancel_while_processing(self):
        entered=threading.Event()
        async def handler(request):
            entered.set();await asyncio.sleep(0.25);return httpx.Response(200,json=result())
        self.ctx.app.state.stt=HTTPSTT(STTConfig('http://stt.test'),httpx.MockTransport(handler))
        tid=uuid.uuid4().hex
        with ThreadPoolExecutor(1) as pool:
            future=pool.submit(self.upload,tid)
            self.assertTrue(entered.wait(2))
            self.assertEqual(self.ctx.post('/api/voice/cancel/'+tid).status_code,200)
            self.assertEqual(future.result().status_code,409)
        with db.connect() as c:
            row=c.execute('SELECT status,result FROM voice_requests WHERE turn_id=?',(tid,)).fetchone()
            self.assertEqual(row['status'],'cancelled');self.assertIsNone(row['result'])
    def test_admin_mode_controls_route(self):
        with db.connect() as c:c.execute("UPDATE settings SET data=json_set(data,'$.mode','offline') WHERE id=1")
        self.ctx.app.state.stt=HTTPSTT(STTConfig('http://stt.test'),httpx.MockTransport(lambda r:httpx.Response(200,json=result('offline'))))
        r=self.upload();self.assertEqual(r.json()['engine'],'faster_whisper_offline');self.assertEqual(self.ctx.get('/api/voice/status').json()['mode'],'offline')
    def test_failed_voice_preserves_cart_and_text(self):
        before=self.ctx.get('/api/session').json()
        self.ctx.app.state.stt=HTTPSTT(STTConfig('http://stt.test'),httpx.MockTransport(lambda r:httpx.Response(503)))
        self.assertEqual(self.upload().status_code,503)
        self.assertEqual(self.ctx.get('/api/session').json()['cart'],before['cart'])
        r=self.ctx.post('/api/turn',json={'turn_id':uuid.uuid4().hex,'text':'09121111111'});self.assertEqual(r.status_code,200)
    def test_request_rate_limit(self):
        for i in range(10):self.assertEqual(self.upload().status_code,200)
        self.assertEqual(self.upload().status_code,429)
