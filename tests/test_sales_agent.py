"""Controlled contracts, not a claim of access to the company's live services."""
import os
os.environ['CATALOG_AUTO_SYNC']='false'
import io,json,tempfile,unittest,uuid
from pathlib import Path
from unittest.mock import patch
import httpx
from PIL import Image
from fastapi.testclient import TestClient
from sellora import db
from sellora.app import app
from sellora.catalog import CatalogSync
from sellora.material_catalog import MATERIALS,IMAGES,parse_materials,parse_image_index
from sellora.demo import seed_customers,prepare_demo

ROWS=[
 dict(pH11='عالیفرد',pH21='آبميوه های سن ایچ',pH31='آبميوه 250 سي سي قوطی سن ایچ',material='100406',qtycar='24',netWeight='240',gewei='G',materialDescription='نوشيدني هلو فروتي قوطي24*250CC',eaN11='*6260100601376*'),
 dict(pH11='شیوا',pH21='پودر ژله',pH31='پودر ژله',material='100249',qtycar='1',netWeight='2500',gewei='G',materialDescription='کرم کارامل شیبابا 2500 گرم')]

class MaterialContract(unittest.IsolatedAsyncioTestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.patch=patch.object(db,'PATH',str(Path(self.tmp.name)/'db.sqlite'));self.patch.start();db.init()
 def tearDown(self):self.patch.stop();self.tmp.cleanup()
 async def test_exact_material_mapping_and_image_join(self):
  out=io.BytesIO();Image.new('RGB',(64,64),'blue').save(out,format='PNG');calls=[]
  def route(r):
   calls.append(str(r.url))
   if str(r.url)==MATERIALS:return httpx.Response(200,json=ROWS)
   if str(r.url)==IMAGES:return httpx.Response(200,json=['100406','nopic','sibmoz','999999'])
   if r.url.path=='/img/Products/100406.png':return httpx.Response(200,content=out.getvalue())
   return httpx.Response(404)
  report=await CatalogSync(httpx.MockTransport(route)).run()
  self.assertEqual(report['products'],2);self.assertEqual(report['images'],1);self.assertTrue(report['complete'])
  self.assertEqual(set(calls),{MATERIALS,IMAGES,'https://catalog.sayesaman.com/img/Products/100406.png'})
  with db.connect() as c:
   ps={p['sku']:p for p in db.products(c)};p=ps['100406'];self.assertEqual(p['per_carton'],24);self.assertEqual(p['flavor'],'هلو');self.assertEqual(p['price'],0);self.assertFalse(p['active']);self.assertEqual(p['net_weight'],'240');self.assertEqual(p['size'],'250CC');self.assertTrue(p['image_url'].startswith('/media/'))
   self.assertIsNone(ps['100249']['image_url']);self.assertEqual(c.execute("SELECT status FROM catalog_images WHERE sku='100249'").fetchone()[0],'not_listed')
 async def test_image_api_failure_preserves_products_without_fake_images(self):
  route=lambda r:httpx.Response(200,json=ROWS) if str(r.url)==MATERIALS else httpx.Response(403)
  report=await CatalogSync(httpx.MockTransport(route)).run();self.assertEqual(report['products'],2);self.assertFalse(report['complete']);self.assertFalse(report['image_index_ok'])
  with db.connect() as c:self.assertEqual(len(db.products(c)),2);self.assertTrue(all(p['image_url'] is None for p in db.products(c)))
 async def test_large_material_list_is_not_truncated_to_first_hundred(self):
  rows=[dict(ROWS[0],material=str(200000+i)) for i in range(1236)]
  def route(r):return httpx.Response(200,json=rows if str(r.url)==MATERIALS else [])
  report=await CatalogSync(httpx.MockTransport(route)).run();self.assertEqual(report['products'],1236);self.assertTrue(report['complete'])
  with db.connect() as c:self.assertEqual(c.execute('SELECT count(*) FROM products').fetchone()[0],1236)
 async def test_invalid_snapshot_never_partially_imported(self):
  route=lambda r:httpx.Response(200,json=ROWS+[{'material':'../private','materialDescription':'Bad'}])
  report=await CatalogSync(httpx.MockTransport(route)).run();self.assertEqual(report['state'],'unavailable')
  with db.connect() as c:self.assertEqual(len(db.products(c)),0)
 def test_index_ignores_placeholder_and_cannot_inject_path(self):
  self.assertEqual(parse_image_index(['100406','nopic','sibmoz','../123','https://evil.test']),{'100406'})
 def test_materials_do_not_invent_pack_count(self):
  p=parse_materials([dict(ROWS[0],qtycar='unknown')])['100406'];self.assertIsNone(p['per_carton'])

class AgentDialogue(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.patch=patch.object(db,'PATH',str(Path(self.tmp.name)/'db.sqlite'));self.patch.start()
  self.env=patch.dict(os.environ,{'SELLORA_SEED_CUSTOMERS':'false','SELLORA_ADMIN_PASSWORD':'test-admin'});self.env.start()
  self.client=TestClient(app);self.client.__enter__();seed_customers()
  with db.connect() as c:
   for sku,flavor in [('T1','هلو'),('T2','انبه'),('T3','پرتقال')]:
    p=dict(sku=sku,name='نوشیدنی '+flavor,flavor=flavor,category='آبمیوه',brand='تست',size='250CC',per_carton=24,unit='کارتن',minimum=1,catalog_verified=True,source='test-fixture')
    c.execute('INSERT INTO products VALUES(?,?,1)',(sku,json.dumps(p)));c.execute('INSERT INTO prices VALUES(?,200000,1)',(sku,));c.execute('INSERT INTO inventory VALUES(?,100,1)',(sku,))
  self.client.get('/api/session')
 def tearDown(self):self.client.__exit__(None,None,None);self.env.stop();self.patch.stop();self.tmp.cleanup()
 def say(self,text,tid=None):
  r=self.client.post('/api/turn',json={'text':text,'turn_id':tid or uuid.uuid4().hex});self.assertEqual(r.status_code,200,r.text);return r.json()
 def returning(self):
  self.say('09120000001');self.assertIsNone(self.client.get('/api/session').json()['customer']);r=self.say('123456');self.assertEqual(r['state']['stage'],'address_confirm');self.assertNotIn('نام و نام خانوادگی',r['reply']);self.say('بله')
 def test_demo_seed_idempotent_and_never_creates_orders(self):
  seed_customers();seed_customers()
  with db.connect() as c:
   self.assertEqual(c.execute('SELECT count(*) FROM customers').fetchone()[0],6);self.assertEqual(c.execute('SELECT count(*) FROM stores').fetchone()[0],4);self.assertEqual(c.execute('SELECT count(*) FROM orders').fetchone()[0],0)
 def test_flavor_then_quantity_without_repeating_product(self):
  self.returning();r=self.say('آب میوه میخوام');self.assertEqual(len(r['state']['choices']),3);self.assertEqual(r['state']['cart']['items'],[])
  r=self.say('انبه');self.assertIn('چند کارتن',r['reply']);r=self.say('سه');self.assertEqual(r['state']['cart']['items'][0]['sku'],'T2');self.assertEqual(r['state']['cart']['items'][0]['quantity'],3)
 def test_ordinal_selection_and_ambiguous_count(self):
  self.returning();self.say('آبمیوه میخوام');self.say('اولی');r=self.say('دو تا');self.assertEqual(r['state']['cart']['items'],[]);self.assertIn('منظورتان',r['reply']);r=self.say('بله کارتن');self.assertEqual(r['state']['cart']['items'][0]['quantity'],2)
 def test_new_customer_and_conversation_saved_with_exact_sku(self):
  for text in ['09129998888','123456','مشتری جدید','تهران','خیابان جدید پلاک ده','بله','T1 دو کارتن']:r=self.say(text)
  self.assertEqual(r['state']['cart']['items'][0]['sku'],'T1')
  with db.connect() as c:
   self.assertEqual(c.execute('SELECT count(*) FROM customers').fetchone()[0],7)
   self.assertEqual(c.execute("SELECT count(*) FROM conversations WHERE role='user'").fetchone()[0],7)
   self.assertEqual(c.execute("SELECT count(*) FROM conversations WHERE text='123456'").fetchone()[0],0)
 def test_saved_purchase_and_privileged_customer_file(self):
  self.returning();self.say('هلو');self.say('دو کارتن');q=self.client.post('/api/quote',json={}).json()
  body=dict(quote_id=q['id'],request_key=uuid.uuid4().hex,confirmed=True)
  order=self.client.post('/api/orders',json=body);self.assertEqual(order.status_code,200,order.text)
  self.assertEqual(self.client.post('/api/orders',json=body).json()['id'],order.json()['id'])
  self.assertEqual(self.client.get('/api/admin/customers/DEMO-C01').status_code,403)
  self.client.post('/api/admin/login',json={'password':'test-admin'})
  f=self.client.get('/api/admin/customers/DEMO-C01').json();self.assertEqual(len(f['orders']),1);self.assertGreater(len(f['conversations']),4)
  self.assertEqual(self.client.get('/api/orders/'+order.json()['id']+'/receipt.pdf').status_code,200)
 def test_phone_not_enough_to_access_customer_file(self):
  self.say('09120000001');self.assertIsNone(self.client.get('/api/session').json()['customer']);self.assertEqual(self.client.get('/api/orders').status_code,401)
 def test_pack_change_invalidates_confirmation(self):
  self.returning();self.say('هلو دو کارتن');q=self.client.post('/api/quote',json={}).json()
  with db.connect() as c:
   p=json.loads(c.execute("SELECT data FROM products WHERE sku='T1'").fetchone()[0]);p['per_carton']=12;c.execute("UPDATE products SET data=? WHERE sku='T1'",(json.dumps(p),))
  r=self.client.post('/api/orders',json=dict(quote_id=q['id'],request_key=uuid.uuid4().hex,confirmed=True));self.assertEqual(r.status_code,409)
 def test_removed_catalog_item_remains_visible_for_cart_correction(self):
  self.returning();self.say('هلو دو کارتن')
  with db.connect() as c:
   p=json.loads(c.execute("SELECT data FROM products WHERE sku='T1'").fetchone()[0]);p['catalog_present']=False;c.execute("UPDATE products SET data=?,active=0 WHERE sku='T1'",(json.dumps(p),))
  state=self.client.get('/api/session').json();self.assertNotIn('T1',[p['sku'] for p in state['products']]);self.assertEqual(state['cart']['items'][0]['sku'],'T1');self.assertEqual(self.client.post('/api/quote',json={}).status_code,409)
 def test_phone_and_early_product_in_same_sentence_are_preserved(self):
  self.say('09120000001 هلو دو کارتن');self.say('123456');r=self.say('بله');self.assertEqual(r['state']['cart']['items'][0]['quantity'],2)
 def test_demo_excerpt_is_exact_and_history_requires_reorder_consent(self):
  prepare_demo();prepare_demo()
  with db.connect() as c:
   self.assertEqual(c.execute("SELECT count(*) FROM orders WHERE id LIKE 'DEMO-HISTORY-%'").fetchone()[0],2)
   p=json.loads(c.execute("SELECT data FROM products WHERE sku='100406'").fetchone()[0]);self.assertEqual(p['verification'],'user_supplied_excerpt');self.assertIsNone(p['image_url']);self.assertEqual(p['per_carton'],24)
  self.returning();r=self.say('سفارش قبلی');self.assertIn('هلو',r['reply']);self.assertEqual(r['state']['cart']['items'],[])
  r=self.say('بله اقلام قبلی');self.assertEqual(r['state']['cart']['items'][0]['sku'],'100406');self.assertEqual(r['state']['cart']['items'][0]['quantity'],2)
