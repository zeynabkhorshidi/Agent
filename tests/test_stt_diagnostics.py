import unittest,json
import httpx
from sellora.stt import HTTPSTT,STTConfig
class Diagnostics(unittest.IsolatedAsyncioTestCase):
 async def test_proxy_or_service_denial_is_reported(self):
  s=HTTPSTT(STTConfig('http://stt.test'),httpx.MockTransport(lambda r:httpx.Response(403,text='forbidden')))
  report=await s.diagnostics();self.assertEqual(report['code'],'access_denied');self.assertEqual(report['checks']['contract']['http_status'],403)
 async def test_wrong_service_does_not_claim_readiness(self):
  s=HTTPSTT(STTConfig('http://stt.test'),httpx.MockTransport(lambda r:httpx.Response(200,text='<html>other service</html>')))
  self.assertEqual((await s.diagnostics())['code'],'contract_mismatch')
 async def test_valid_routes_still_do_not_claim_inference(self):
  def handler(r):return httpx.Response(200,json={'status':'ok','offline_model_files_present':False} if r.url.path=='/health' else {'paths':{'/api/v1/stt/online':{},'/api/v1/stt/offline':{}}})
  report=await HTTPSTT(STTConfig('http://stt.test'),httpx.MockTransport(handler)).diagnostics();self.assertEqual(report['code'],'reachable');self.assertFalse(report['checks']['health']['offline_model_files_present']);self.assertIn('فایل صوتی',report['message'])
 async def test_bad_configuration_returns_clear_report(self):
  s=HTTPSTT(STTConfig('172.20.3.81:30089'));self.assertEqual((await s.diagnostics())['code'],'invalid_config');self.assertFalse((await s.health())['reachable'])
