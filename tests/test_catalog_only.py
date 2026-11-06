import os
os.environ['CATALOG_AUTO_SYNC']='false'
import io,json,tempfile,unittest,uuid
from pathlib import Path
from unittest.mock import patch
import httpx
from PIL import Image
from fastapi.testclient import TestClient
from sellora.app import app
from sellora import db
from sellora.catalog import CatalogSync

class CatalogOnly(unittest.IsolatedAsyncioTestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.change=patch.object(db,'PATH',str(Path(self.temp.name)/'test.db'));self.change.start();db.init()
 def tearDown(self):self.change.stop();self.temp.cleanup()
 async def test_default_database_contains_no_demo_products(self):
  with db.connect() as c:self.assertEqual(c.execute('SELECT count(*) FROM products').fetchone()[0],0)
  with TestClient(app) as client:
   body=client.get('/api/session').json();self.assertEqual(body['products'],[]);self.assertIsNone(body['hero_image'])
 async def test_old_demo_hidden_without_removing_order_snapshot(self):
  with db.connect() as c:
   c.execute('INSERT INTO products VALUES(?,?,1)',('DEMO-GR-1',json.dumps({'sku':'DEMO-GR-1','name':'مخلوط حبوبات','source':'داده آزمایشی'})))
   c.execute('INSERT INTO prices VALUES(?,1,1)',('DEMO-GR-1',));c.execute('INSERT INTO inventory VALUES(?,1,1)',('DEMO-GR-1',))
   c.execute('INSERT INTO orders VALUES(?,?,?,?,?,?,?)',('OLD','customer','old-request','old-quote',json.dumps({'items':[{'name':'سفارش قبلی'}]}),'2026-11-01','old'))
  db.init()
  with db.connect() as c:self.assertEqual(c.execute("SELECT active FROM products WHERE sku='DEMO-GR-1'").fetchone()[0],0);self.assertIsNotNone(c.execute("SELECT snapshot FROM orders WHERE id='OLD'").fetchone())
  with TestClient(app) as client:self.assertEqual(client.get('/api/session').json()['products'],[])
 async def test_catalog_pages_and_exact_images_are_imported(self):
  out=io.BytesIO();Image.new('RGB',(64,64),'red').save(out,format='PNG');png=out.getvalue();calls=[]
  def transport(r):
   calls.append(r.url.path)
   if r.url.path=='/':return httpx.Response(200,text='<a href="/p/a">A</a><a href="/p/b">B</a>',headers={'Content-Type':'text/html'})
   if r.url.path.startswith('/image/'):return httpx.Response(200,content=png,headers={'Content-Type':'image/png'})
   name='آبمیوه سن‌ایچ' if r.url.path.endswith('a') else 'کالای دوم کاتالوگ'
   image='/image/a.png' if r.url.path.endswith('a') else '/image/b.png'
   html='<script type="application/ld+json">'+json.dumps({'@type':'Product','name':name,'sku':'P'+r.url.path[-1],'brand':'سن‌ایچ','image':image})+'</script>'
   return httpx.Response(200,text=html,headers={'Content-Type':'text/html'})
  service=CatalogSync(httpx.MockTransport(transport));result=await service.run();self.assertEqual(result['products'],2);self.assertEqual(result['images'],2);self.assertTrue(result['complete']);self.assertEqual(result['pages'],3)
  self.assertEqual(set(calls),{'/','/p/a','/p/b','/image/a.png','/image/b.png'})
  with TestClient(app) as client:
   state=client.get('/api/session').json();self.assertEqual({p['name'] for p in state['products']},{'آبمیوه سن‌ایچ','کالای دوم کاتالوگ'});self.assertTrue(state['hero_image'].startswith('/media/'))
   for p in state['products']:
    self.assertFalse(p['active']);self.assertIsNone(p['per_carton']);self.assertEqual(p['price'],0);self.assertTrue(p['image_origin'].startswith('https://catalog.sayesaman.com/image/'))
 async def test_missing_trade_information_does_not_crash_or_guess(self):
  with db.connect() as c:
   p={'sku':'REAL','name':'محصول سن‌ایچ','brand':'سن‌ایچ','source':'https://catalog.sayesaman.com/','catalog_verified':True}
   c.execute('INSERT INTO products VALUES(?,?,0)',('REAL',json.dumps(p)))
   c.execute('INSERT INTO prices VALUES(?,0,1)',('REAL',));c.execute('INSERT INTO inventory VALUES(?,0,1)',('REAL',))
  with TestClient(app) as client:
   client.get('/api/session')
   for text in ['09121119999','123456','مشتری تست','تهران','نشانی تست دوازده','بله','محصول سن‌ایچ دو کارتن']:
    r=client.post('/api/turn',json={'text':text,'turn_id':uuid.uuid4().hex});self.assertEqual(r.status_code,200,r.text)
   self.assertIn('استعلام',r.json()['reply']);self.assertEqual(r.json()['state']['cart']['items'],[])
 async def test_access_denied_does_not_generate_catalog(self):
  report=await CatalogSync(httpx.MockTransport(lambda r:httpx.Response(403))).run();self.assertEqual(report['state'],'unavailable');self.assertFalse(report['complete'])
  with db.connect() as c:self.assertEqual(c.execute('SELECT count(*) FROM products').fetchone()[0],0)
 async def test_external_image_not_fetched_or_replaced(self):
  calls=[]
  def handler(r):
   calls.append(str(r.url));return httpx.Response(200,text='<script type="application/ld+json">'+json.dumps({'@type':'Product','name':'محصول واقعی','sku':'R','image':'http://127.0.0.1/private.png'})+'</script>',headers={'Content-Type':'text/html'})
  await CatalogSync(httpx.MockTransport(handler)).run();self.assertEqual(len(calls),1)
  with db.connect() as c:p=json.loads(c.execute('SELECT data FROM products').fetchone()[0]);self.assertIsNone(p['image_url'])
