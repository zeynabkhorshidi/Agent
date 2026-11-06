import unittest,tempfile,uuid,json,io,threading,asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
import httpx
from fastapi.testclient import TestClient
from PIL import Image
from sellora.app import app
from sellora import db
from sellora.stt import HTTPSTT,STTConfig
from sellora.intelligence import SalesModel,Plan,SpeechOutput
from sellora.catalog import preview,store_image

class SpokenCheckout(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.patch=patch.object(db,'PATH',str(Path(self.temp.name)/'db.sqlite'));self.patch.start()
  self.c=TestClient(app);self.c.__enter__();self.c.get('/api/session')
  self.c.app.state.sales_model.base='';self.words='سفارش را تأیید می کنم'
  self.c.app.state.stt=HTTPSTT(STTConfig('http://stt.test'),httpx.MockTransport(lambda r:httpx.Response(200,json={'text':self.words,'engine':'google_online','language':'fa','duration_seconds':2,'processing_seconds':.1})))
  for t in ['09121110000','123456','مشتری تست','تهران','نشانی دوازده','بله','پرتقال دو کارتن']:self.turn(t)
 def tearDown(self):self.c.__exit__(None,None,None);self.patch.stop();self.temp.cleanup()
 def turn(self,text,**extra):return self.c.post('/api/turn',json={'text':text,'turn_id':uuid.uuid4().hex,**extra})
 def proof(self,qid=None):
  tid=uuid.uuid4().hex;form={'turn_id':tid}
  if qid:form['quote_id']=qid
  r=self.c.post('/api/voice/transcribe',data=form,files={'file':('v.wav',b'RIFF-test','audio/wav')});self.assertEqual(r.status_code,200,r.text);return r.json()
 def test_end_to_end_voice_confirmation(self):
  reviewed=self.turn('همین کافیه');self.assertEqual(reviewed.status_code,200);q=reviewed.json()['actions']['quote'];self.assertIn('تومان',q['speech_summary'])
  p=self.proof(q['id']);tid=uuid.uuid4().hex
  body={'text':p['text'],'turn_id':tid,'source':'voice','voice_turn_id':p['turn_id'],'quote_id':q['id']}
  r=self.c.post('/api/turn',json=body);self.assertEqual(r.status_code,200,r.text);o=r.json()['actions']['order']['id']
  duplicate=self.c.post('/api/turn',json=body);self.assertEqual(duplicate.json()['actions']['order']['id'],o)
  self.assertEqual(len(self.c.get('/api/orders').json()),1);self.assertTrue(self.c.get('/api/orders/'+o+'/receipt.pdf').content.startswith(b'%PDF'))
 def test_pause_during_model_latency_does_not_change_cart(self):
  entered=threading.Event()
  async def handler(r):
   entered.set();await asyncio.sleep(.2)
   return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps({'intent':'cart','items':[{'sku':'DEMO-OR-1','action':'set','quantity':3,'unit':'کارتن'}]})}}]})
  with patch.dict('os.environ',{'LLM_BASE_URL':'http://model.test/v1','LLM_MODEL':'test'}):model=SalesModel(httpx.MockTransport(handler))
  self.c.app.state.sales_model=model
  with ThreadPoolExecutor(1) as pool:
   result=pool.submit(self.turn,'پرتقال سه کارتن')
   self.assertTrue(entered.wait(2));self.assertEqual(self.turn('توقف').status_code,200);self.assertEqual(result.result().status_code,409)
  self.assertEqual(self.c.get('/api/session').json()['cart']['items'][0]['quantity'],2)
 def test_early_details_are_not_asked_again(self):
  c=TestClient(app);c.get('/api/session')
  def send(t):return c.post('/api/turn',json={'text':t,'turn_id':uuid.uuid4().hex})
  send('نام من زینب خورشیدی، شهرم شیراز، آدرسم خیابان تست، شماره 09123330000')
  r=send('123456');self.assertEqual(r.status_code,200,r.text)
  v=r.json()['state'];self.assertEqual(v['customer']['name'],'زینب خورشیدی');self.assertEqual(v['customer']['city'],'شیراز');self.assertEqual(v['stage'],'address_confirm')
 def test_cart_change_during_review_produces_fresh_quote(self):
  q=self.c.post('/api/quote',json={}).json();self.words='پرتقال سه کارتن';p=self.proof(q['id']);r=self.turn(p['text'],source='voice',voice_turn_id=p['turn_id'],quote_id=q['id'])
  self.assertEqual(r.status_code,200,r.text);self.assertNotEqual(r.json()['actions']['quote']['id'],q['id']);self.assertEqual(r.json()['state']['cart']['items'][0]['quantity'],3)
 def test_forged_proof_rejected(self):
  q=self.c.post('/api/quote',json={}).json();r=self.turn(self.words,source='voice',voice_turn_id='fake-proof',quote_id=q['id']);self.assertEqual(r.status_code,409);self.assertEqual(self.c.get('/api/orders').json(),[])
 def test_old_unbound_speech_rejected(self):
  p=self.proof();q=self.c.post('/api/quote',json={}).json();self.assertEqual(self.turn(p['text'],source='voice',voice_turn_id=p['turn_id'],quote_id=q['id']).status_code,409)
 def test_price_change_requires_fresh_confirmation(self):
  q=self.c.post('/api/quote',json={}).json();p=self.proof(q['id'])
  with db.connect() as c:c.execute("UPDATE prices SET version=version+1,amount=amount+100 WHERE sku='DEMO-OR-1'")
  self.assertEqual(self.turn(p['text'],source='voice',voice_turn_id=p['turn_id'],quote_id=q['id']).status_code,409);self.assertEqual(self.c.get('/api/orders').json(),[])
 def test_vague_yes_does_not_register(self):
  q=self.c.post('/api/quote',json={}).json();self.words='بله';p=self.proof(q['id']);r=self.turn(p['text'],source='voice',voice_turn_id=p['turn_id'],quote_id=q['id']);self.assertEqual(r.status_code,200);self.assertEqual(self.c.get('/api/orders').json(),[])
 def test_text_does_not_impersonate_voice(self):
  self.c.post('/api/quote',json={});self.turn(self.words);self.assertEqual(self.c.get('/api/orders').json(),[])
 def test_photo_upload_is_protected_and_reencoded(self):
  b=io.BytesIO();Image.new('RGB',(80,80),'blue').save(b,format='PNG');data=b.getvalue()
  r=self.c.post('/api/admin/products/DEMO-OR-1/image',files={'file':('a.png',data,'image/png')});self.assertEqual(r.status_code,403)
  with patch.dict('os.environ',{'SELLORA_ADMIN_PASSWORD':'test-admin-only'}):
   self.assertEqual(self.c.post('/api/admin/login',json={'password':'test-admin-only'}).status_code,200)
  r=self.c.post('/api/admin/products/DEMO-OR-1/image',files={'file':('a.png',data,'image/png')});self.assertEqual(r.status_code,200,r.text);self.assertTrue(r.json()['image_url'].endswith('.webp'))
  self.assertEqual(self.c.get(r.json()['image_url']).status_code,200)
 def test_cancelled_proof_rejected(self):
  q=self.c.post('/api/quote',json={}).json();p=self.proof(q['id']);self.c.post('/api/voice/cancel/'+p['turn_id']);self.assertEqual(self.turn(p['text'],source='voice',voice_turn_id=p['turn_id'],quote_id=q['id']).status_code,409)

class ModelAndCatalog(unittest.IsolatedAsyncioTestCase):
 async def test_planner_validates_unknown_sku(self):
  with patch.dict('os.environ',{'LLM_BASE_URL':'http://model.test/v1','LLM_MODEL':'test'}):m=SalesModel(httpx.MockTransport(lambda r:httpx.Response(200,json={'choices':[{'message':{'content':json.dumps({'intent':'cart','items':[{'sku':'invented','action':'set','quantity':1,'unit':'کارتن'}]})}}]})))
  self.assertIsNone(await m.plan('یک کارتن',[],{}))
 async def test_planner_structured_only(self):
  with patch.dict('os.environ',{'LLM_BASE_URL':'http://model.test/v1','LLM_MODEL':'test'}):m=SalesModel(httpx.MockTransport(lambda r:httpx.Response(200,json={'choices':[{'message':{'content':json.dumps({'intent':'cart','items':[{'sku':'sku1','action':'set','quantity':2,'unit':'کارتن'}]})}}]})))
  p={'sku':'sku1','active':True,'name':'پرتقال','flavor':'پرتقال','size':'یک لیتر','unit':'کارتن'};r=await m.plan('دو کارتن پرتقال',[p],{});self.assertEqual(r.items[0].quantity,2)
 async def test_catalog_jsonld_separate_from_price(self):
  html='<script type="application/ld+json">'+json.dumps({'@type':'Product','name':'کالای واقعی','sku':'P1','image':'/photo.jpg','offers':{'price':'100'}})+'</script>'
  r=await preview(httpx.MockTransport(lambda req:httpx.Response(200,text=html)));self.assertEqual(r['products'][0]['name'],'کالای واقعی');self.assertNotIn('price',r['products'][0]);self.assertEqual(r['products'][0]['image'],'https://catalog.sayesaman.com/photo.jpg')
 async def test_catalog_denial_not_demo_success(self):
  with self.assertRaises(ConnectionError):await preview(httpx.MockTransport(lambda req:httpx.Response(403)))

 async def test_tts_uses_configured_contract_only(self):
  def handler(r):
   self.assertEqual(str(r.url),'http://speech.test/v1/audio/speech')
   body=json.loads(r.content);self.assertEqual(body['voice'],'configured-voice');self.assertEqual(body['input'],'سلام')
   return httpx.Response(200,content=b'ID3-test-audio',headers={'Content-Type':'audio/mpeg'})
  with patch.dict('os.environ',{'TTS_ENDPOINT':'http://speech.test/v1/audio/speech','TTS_MODEL':'configured-model','TTS_VOICE':'configured-voice'}):speaker=SpeechOutput(httpx.MockTransport(handler))
  self.assertEqual(await speaker.synthesize('سلام'),b'ID3-test-audio')
 async def test_tts_failure_is_not_silently_successful(self):
  with patch.dict('os.environ',{'TTS_ENDPOINT':'http://speech.test/v1/audio/speech','TTS_MODEL':'configured-model','TTS_VOICE':'configured-voice'}):speaker=SpeechOutput(httpx.MockTransport(lambda r:httpx.Response(503)))
  with self.assertRaises(ConnectionError):await speaker.synthesize('سلام')
