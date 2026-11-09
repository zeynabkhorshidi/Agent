"""Regression: preserve each cause; do not confuse open TCP with a working STT API."""
import asyncio,errno,json,tempfile,unittest,uuid
from pathlib import Path
from unittest.mock import patch
import httpx
from fastapi.testclient import TestClient
from sellora import db
from sellora.app import app
from sellora.stt import HTTPSTT,STTConfig,STTError,connection_reason
from sellora.diagnostics import diagnose
from tests.test_stt import wav,result

class FailureCauses(unittest.IsolatedAsyncioTestCase):
 async def test_reset_is_preserved_for_both_routes(self):
  def handler(r):
   try:raise ConnectionResetError(errno.ECONNRESET,'private proxy token must not be logged')
   except OSError as exc:raise httpx.ReadError('private request details',request=r) from exc
  service=HTTPSTT(STTConfig('http://stt.test'),httpx.MockTransport(handler))
  with self.assertRaises(STTError) as error:await service.transcribe(wav(),'v.wav','audio/wav','auto')
  exc=error.exception;self.assertEqual(exc.code,'all_unavailable');self.assertIn('پیش از پاسخ',exc.message)
  self.assertEqual(set(exc.details['attempts']),{'online','offline'})
  self.assertTrue(all(d['code']=='connection_reset' for d in exc.details['attempts'].values()))
  self.assertNotIn('private',json.dumps(exc.details))
 async def test_http_status_and_untrusted_message_not_lost_or_exposed(self):
  s=HTTPSTT(STTConfig('http://stt.test'),httpx.MockTransport(lambda r:httpx.Response(404,json={'error':{'code':'customer_secret_token','message':'raw stacktrace password'}})))
  with self.assertRaises(STTError) as error:await s.transcribe(wav(),'v.wav','audio/wav','auto')
  self.assertTrue(all(d['http_status']==404 for d in error.exception.details['attempts'].values()))
  self.assertIn('نشانی فعلی',error.exception.message);self.assertNotIn('secret',json.dumps(error.exception.details));self.assertNotIn('stacktrace',error.exception.message)
 async def test_circuit_retains_original_cause(self):
  def handler(r):raise httpx.ConnectError('offline')
  s=HTTPSTT(STTConfig('http://stt.test'),httpx.MockTransport(handler))
  for _ in range(3):
   with self.assertRaises(STTError) as err:await s.transcribe(wav(),'v.wav','audio/wav','auto')
  causes=err.exception.details['attempts'];self.assertTrue(causes['online']['circuit_open']);self.assertEqual(causes['offline']['code'],'connection')
 async def test_model_and_ffmpeg_failures_are_distinct(self):
  for upstream,canonical in [('offline_model_missing','offline_model_unavailable'),('ffmpeg_not_found','audio_processor_unavailable')]:
   def handler(r):return httpx.Response(503,json={'error':{'code':upstream,'message':'private server detail'}})
   service=HTTPSTT(STTConfig('http://stt.test'),httpx.MockTransport(handler))
   with self.assertRaises(STTError) as err:await service.transcribe(wav(),'v.wav','audio/wav','auto')
   self.assertEqual(err.exception.details['attempts']['offline']['code'],canonical);self.assertNotIn('private server',err.exception.message)
 async def test_invalid_health_does_not_report_ready(self):
  def handler(r):return httpx.Response(200,json={'status':'not-ready'} if r.url.path=='/health' else {'paths':{'/api/v1/stt/online':{},'/api/v1/stt/offline':{}}})
  report=await HTTPSTT(STTConfig('http://stt.test'),httpx.MockTransport(handler)).diagnostics()
  self.assertEqual(report['code'],'health_invalid');self.assertFalse(report['inference_verified'])
 async def test_reset_diagnostics_are_sanitized(self):
  def handler(r):
   try:raise OSError(10054,'sensitive')
   except OSError as exc:raise httpx.ReadError('credentials') from exc
  report=await HTTPSTT(STTConfig('http://stt.test'),httpx.MockTransport(handler)).diagnostics()
  self.assertEqual(report['code'],'connection_reset');self.assertNotIn('credentials',json.dumps(report));self.assertFalse(report['inference_verified'])
 async def test_model_missing_is_a_separate_health_fact(self):
  def handler(r):return httpx.Response(200,json={'status':'ok','offline_model_files_present':False} if r.url.path=='/health' else {'paths':{'/api/v1/stt/online':{},'/api/v1/stt/offline':{}}})
  report=await HTTPSTT(STTConfig('http://stt.test'),httpx.MockTransport(handler)).diagnostics()
  self.assertIn('offline_note',report);self.assertFalse(report['inference_verified'])
 async def test_optional_inference_sends_only_explicit_file_and_omits_text(self):
  calls=[]
  def handler(r):
   calls.append(r)
   if r.method=='POST':return httpx.Response(200,json=result('offline' if r.url.path.endswith('offline') else 'online',text='متن خصوصی آزمون'))
   return httpx.Response(200,json={'status':'ok'} if r.url.path=='/health' else {'paths':{'/api/v1/stt/online':{},'/api/v1/stt/offline':{}}})
  service=HTTPSTT(STTConfig('http://stt.test'),httpx.MockTransport(handler))
  with tempfile.TemporaryDirectory() as tmp,patch('sellora.diagnostics.HTTPSTT',return_value=service):
   file=Path(tmp)/'test.wav';file.write_bytes(wav());report=await diagnose(service.config,str(file))
  self.assertTrue(report['inference_verified']);self.assertEqual(len([r for r in calls if r.method=='POST']),2);self.assertNotIn('متن خصوصی',json.dumps(report,ensure_ascii=False))
 def test_bad_port_is_validation_error(self):
  with self.assertRaises(STTError):STTConfig('http://stt.test:wrong').validate()

class PersistentFailure(unittest.TestCase):
 def test_greeting_voice_uses_server_authorized_text(self):
  class Speech:
   async def synthesize(self,text):return b'controlled-authorization-fixture'
  with tempfile.TemporaryDirectory() as tmp,patch.object(db,'PATH',str(Path(tmp)/'voice.db')),patch.dict('os.environ',{'CATALOG_AUTO_SYNC':'false'}):
   with TestClient(app) as client:
    response=client.get('/api/session');greeting=response.json()['greeting'];client.app.state.speech_output=Speech()
    self.assertIn("media-src 'self' blob:",response.headers['content-security-policy'])
    self.assertEqual(client.post('/api/assistant/speak',json={'text':greeting}).status_code,200)
    self.assertEqual(client.post('/api/assistant/speak',json={'text':'متن دلخواه غیرمجاز'}).status_code,403)
 def test_customer_safe_incident_and_admin_causes(self):
  with tempfile.TemporaryDirectory() as tmp,patch.object(db,'PATH',str(Path(tmp)/'voice.db')),patch.dict('os.environ',{'CATALOG_AUTO_SYNC':'false','SELLORA_ADMIN_PASSWORD':'failure-test-only'}):
   with TestClient(app) as client:
    def handler(r):raise httpx.ConnectError('do not expose this raw error')
    client.app.state.stt=HTTPSTT(STTConfig('http://stt.test'),httpx.MockTransport(handler));client.get('/api/session')
    response=client.post('/api/voice/transcribe',data={'turn_id':uuid.uuid4().hex},files={'file':('v.wav',wav(),'audio/wav')})
    self.assertEqual(response.status_code,503);body=response.json();self.assertEqual(len(body['incident_id']),16);self.assertNotIn('causes',body);self.assertNotIn('raw error',json.dumps(body))
    self.assertEqual(client.get('/api/admin/voice/diagnostics').status_code,403)
    client.post('/api/admin/login',json={'password':'failure-test-only'});report=client.get('/api/admin/voice/diagnostics').json()
    failure=report['recent_failures'][0];self.assertEqual(failure['incident_id'],body['incident_id']);self.assertEqual(failure['causes']['attempts']['online']['code'],'connection')
