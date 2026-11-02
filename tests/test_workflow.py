import os,tempfile,unittest,uuid,json,time,concurrent.futures,asyncio
from pathlib import Path
os.environ['SELLORA_DB']=str(Path(tempfile.mkdtemp())/'test.db')
os.environ['SELLORA_ADMIN_PASSWORD']='test-admin-only'
os.environ['SELLORA_OPERATOR_PASSWORD']='test-operator-only'
os.environ['SELLORA_SALES_PASSWORD']='test-sales-only'
from fastapi.testclient import TestClient
from sellora.app import app
from sellora import db
from sellora.adapters import VoiceRouter,MockVoice,UnconfiguredVoice
from sellora.domain import normalize,mobile

TIMINGS=[]
class Workflow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx=TestClient(app);cls.ctx.__enter__()
    @classmethod
    def tearDownClass(cls):cls.ctx.__exit__(None,None,None)
    def client(self):
        c=TestClient(app);self.assertEqual(c.get('/api/session').status_code,200);return c
    def turn(self,c,text,tid=None):
        t=time.perf_counter();r=c.post('/api/turn',json={'text':text,'turn_id':tid or uuid.uuid4().hex});TIMINGS.append(('turn_ms',(time.perf_counter()-t)*1000));self.assertEqual(r.status_code,200,r.text);return r.json()
    def customer(self,c,phone=None):
        phone=phone or '09'+str(uuid.uuid4().int)[:9]
        self.turn(c,phone);self.turn(c,'123456')
        s=c.get('/api/session').json()
        if not s['customer']['name']:
            for t in ['مشتری نمونه','تهران','خیابان نمونه پلاک دوازده','بله']:self.turn(c,t)
        else:self.turn(c,'بله')
        return phone
    def add(self,c,n=2):
        s=c.get('/api/session').json();r=c.post('/api/cart',json={'sku':'DEMO-OR-1','quantity':n,'revision':s['cart']['revision']});self.assertEqual(r.status_code,200,r.text)
    def quote(self,c):
        r=c.post('/api/quote',json={});self.assertEqual(r.status_code,200,r.text);return r.json()
    def submit(self,c,q,key=None,confirmed=True):
        t=time.perf_counter();r=c.post('/api/orders',json={'quote_id':q['id'],'request_key':key or uuid.uuid4().hex,'confirmed':confirmed});TIMINGS.append(('submit_ms',(time.perf_counter()-t)*1000));return r
    def test_new_customer_order_pdf(self):
        c=self.client();self.customer(c);self.add(c);q=self.quote(c);r=self.submit(c,q);self.assertEqual(r.status_code,200,r.text)
        pdf=c.get('/api/orders/'+r.json()['id']+'/receipt.pdf');self.assertEqual(pdf.status_code,200);self.assertTrue(pdf.content.startswith(b'%PDF'));self.assertGreater(len(pdf.content),10000)
        self.assertEqual(len(c.get('/api/orders').json()),1)
    def test_no_auth_no_private_data(self):
        c=self.client();self.assertEqual(c.get('/api/orders').status_code,401);self.assertIsNone(c.get('/api/session').json()['customer'])
        self.turn(c,'09121111111');self.assertIsNone(c.get('/api/session').json()['customer'])
    def test_returning_customer_cart_recovery(self):
        c=self.client();phone=self.customer(c);self.add(c,3);c.post('/api/logout',json={});new=self.client();self.turn(new,phone);self.assertIsNone(new.get('/api/session').json()['customer']);self.turn(new,'123456');s=new.get('/api/session').json();self.assertEqual(s['cart']['items'][0]['quantity'],3);self.assertEqual(s['customer']['city'],'تهران')
    def test_multi_item_and_edit(self):
        c=self.client();self.customer(c);r=self.turn(c,'پرتقال دو کارتن و انبه سه کارتن');self.assertEqual(len(r['state']['cart']['items']),2)
        r=self.turn(c,'نه پرتقال رو سه کارتن کن و انبه رو حذف کن');self.assertEqual(len(r['state']['cart']['items']),1);self.assertEqual(r['state']['cart']['items'][0]['quantity'],3)
    def test_ambiguous_unit_and_product(self):
        c=self.client();self.customer(c);r=self.turn(c,'نوشیدنی دو کارتن');self.assertEqual(r['state']['cart']['items'],[]);r=self.turn(c,'پرتقال دو تا');self.assertEqual(r['state']['cart']['items'],[])
    def test_duplicate_turn(self):
        c=self.client();self.customer(c);t=uuid.uuid4().hex;r=self.turn(c,'پرتقال دو کارتن',t);r2=self.turn(c,'پرتقال دو کارتن',t);self.assertEqual(r['state']['cart']['revision'],r2['state']['cart']['revision']);self.assertTrue(r2['duplicate'])
    def test_confirmation_required_and_revision(self):
        c=self.client();self.customer(c);self.add(c);q=self.quote(c);self.assertEqual(self.submit(c,q,confirmed=False).status_code,400);self.add(c,3);self.assertEqual(self.submit(c,q).status_code,409)
    def test_price_change_invalidates_confirmation(self):
        c=self.client();self.customer(c);self.add(c);q=self.quote(c)
        with db.connect() as conn:conn.execute("UPDATE prices SET amount=amount+1,version=version+1 WHERE sku='DEMO-OR-1'")
        self.assertEqual(self.submit(c,q).status_code,409);newq=self.quote(c);self.assertNotEqual(q['snapshot']['total'],newq['snapshot']['total']);self.assertEqual(self.submit(c,newq).status_code,200)
    def test_out_of_stock(self):
        c=self.client();self.customer(c);s=c.get('/api/session').json();r=c.post('/api/cart',json={'sku':'DEMO-OR-1','quantity':9999,'revision':s['cart']['revision']});self.assertEqual(r.status_code,400)
    def test_concurrent_retry_only_one_order(self):
        c=self.client();self.customer(c);self.add(c,1);q=self.quote(c);key=uuid.uuid4().hex
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            results=list(pool.map(lambda _:self.submit(c,q,key),range(2)))
        self.assertTrue(all(r.status_code==200 for r in results));self.assertEqual(results[0].json()['id'],results[1].json()['id']);self.assertEqual(len(c.get('/api/orders').json()),1)
    def test_cross_customer_receipt_denied(self):
        a=self.client();self.customer(a);self.add(a,1);o=self.submit(a,self.quote(a)).json()['id'];b=self.client();self.customer(b);self.assertEqual(b.get('/api/orders/'+o+'/receipt.pdf').status_code,404)
    def test_reject_suggestion_and_submit(self):
        c=self.client();self.customer(c);self.turn(c,'آب دو کارتن');self.turn(c,'پیشنهاد نمی‌خواهم');self.assertEqual(self.submit(c,self.quote(c)).status_code,200)
    def test_restart_requires_confirmation_and_pause(self):
        c=self.client();self.customer(c);self.add(c,1);self.turn(c,'از اول');self.assertEqual(len(c.get('/api/session').json()['cart']['items']),1);self.turn(c,'توقف');self.turn(c,'پرتقال سه کارتن');self.assertEqual(c.get('/api/session').json()['cart']['items'][0]['quantity'],1);self.turn(c,'ادامه بده');self.turn(c,'پاک کردن سبد');self.assertEqual(c.get('/api/session').json()['cart']['items'],[])
    def test_csrf_and_admin(self):
        c=self.client();self.assertEqual(c.get('/api/admin').status_code,403);self.assertEqual(c.post('/api/turn',headers={'Origin':'https://evil.example'},json={'text':'hi','turn_id':'12345678'}).status_code,403);self.assertEqual(c.post('/api/admin/login',json={'password':'test-admin-only'}).status_code,200);self.assertEqual(c.get('/api/admin').status_code,200)
    def test_role_permissions(self):
        c=self.client();self.assertEqual(c.post('/api/admin/login',json={'password':'test-operator-only','role':'operator'}).status_code,200)
        r=c.get('/api/admin');self.assertEqual(r.status_code,200);self.assertEqual(r.json()['role'],'operator')
        self.assertEqual(c.post('/api/admin/commercial',json={'sku':'DEMO-OR-1','price':1,'stock':1}).status_code,403)
        self.assertEqual(c.get('/api/admin/orders/none/receipt.pdf').status_code,403)
    def test_quote_expiry(self):
        c=self.client();self.customer(c);self.add(c,1);q=self.quote(c)
        with db.connect() as conn:conn.execute('UPDATE quotes SET expires=0 WHERE id=?',(q['id'],))
        self.assertEqual(self.submit(c,q).status_code,409)
    def test_incomplete_profile(self):
        c=self.client();self.turn(c,'09129999999');self.turn(c,'123456');self.add(c,1);self.assertEqual(c.post('/api/quote',json={}).status_code,400)
    def test_persistence_new_connection(self):
        c=self.client();self.customer(c);self.add(c,1);order=self.submit(c,self.quote(c)).json()['id']
        with db.connect() as conn:self.assertEqual(conn.execute('SELECT id FROM orders WHERE id=?',(order,)).fetchone()[0],order)
    def test_normalization(self):
        self.assertEqual(mobile('+۹۸۹۱۲۱۲۳۴۵۶۷'),'09121234567');self.assertEqual(normalize('كيك'),'کیک')
    def test_voice_fallback_contract_only(self):
        async def test():
            router=VoiceRouter(UnconfiguredVoice(),MockVoice());self.assertEqual(await router.transcribe('سلام'.encode(),'t'),'سلام')
            with self.assertRaises(ConnectionError):await router.transcribe(b'a','t','online')
            with self.assertRaises(ConnectionError):await VoiceRouter(UnconfiguredVoice(),UnconfiguredVoice()).transcribe(b'a','t')
        asyncio.run(test())

if __name__=='__main__':
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(Workflow);result=unittest.TextTestRunner(verbosity=2).run(suite)
    from statistics import median
    print('LOCAL HTTP TIMINGS (not speech latency):', {k: {'count':len(v:=[n for key,n in TIMINGS if key==k]),'median_ms':round(median(v),2),'max_ms':round(max(v),2)} for k in set(k for k,n in TIMINGS)})
    raise SystemExit(not result.wasSuccessful())
