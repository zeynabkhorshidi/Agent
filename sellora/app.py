import os, json, secrets, time, uuid, hashlib, hmac, io, html, re
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Response, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from . import db
from .domain import normalize, mobile, quantity, find_products

PRODUCTION=os.getenv('SELLORA_ENV','development')=='production'
COOKIE='sellora_session'
ADMIN=os.getenv('SELLORA_ADMIN_PASSWORD','')
ADMIN_SESSIONS={}
D=json.dumps

def fail(message,code=400): raise HTTPException(code,message)
def uid():return uuid.uuid4().hex

def load(c,sid):
    r=c.execute('SELECT * FROM sessions WHERE id=? AND expires>?',(sid,int(time.time()))).fetchone()
    if not r: fail('نشست پایان یافته است. صفحه را تازه کنید.',401)
    return r,json.loads(r['state'])

def persist(c,sid,state,cid=None):
    if cid: c.execute('UPDATE sessions SET state=?,customer_id=? WHERE id=?',(D(state),cid,sid))
    else: c.execute('UPDATE sessions SET state=? WHERE id=?',(D(state),sid))

def auth(c,sid):
    r,s=load(c,sid)
    if not r['customer_id']:fail('ابتدا شماره موبایل را تأیید کنید.',401)
    return dict(c.execute('SELECT * FROM customers WHERE id=?',(r['customer_id'],)).fetchone())

def cart(c,sid):
    r=c.execute('SELECT * FROM carts WHERE session_id=?',(sid,)).fetchone()
    return r['revision'],json.loads(r['items'])

def save_cart(c,sid,items):
    c.execute('UPDATE carts SET revision=revision+1,items=? WHERE session_id=?',(D(items),sid))
    c.execute('DELETE FROM quotes WHERE session_id=?',(sid,))
    db.audit(c,sid,'cart.changed',{'items':items})

def view(c,sid):
    r,s=load(c,sid); rev,items=cart(c,sid)
    customer=dict(c.execute('SELECT * FROM customers WHERE id=?',(r['customer_id'],)).fetchone()) if r['customer_id'] else None
    ps=db.products(c); by={p['sku']:p for p in ps}
    lines=[dict(by[k],quantity=n,total=by[k]['price']*n) for k,n in items.items() if k in by]
    history=[dict(x) for x in c.execute('SELECT role,text FROM conversations WHERE session_id=? ORDER BY id DESC LIMIT 60',(sid,)).fetchall()][::-1]
    return dict(customer=customer,stage=s.get('stage','mobile'),paused=s.get('paused',False),cart=dict(revision=rev,items=lines,total=sum(x['total'] for x in lines)),products=ps,messages=history,demo=True)

def next_question(customer,s):
    if not customer:return 'شماره موبایلتان را وارد کنید. احراز این نسخه آزمایشی است.'
    for key,label in [('name','نام و نام خانوادگی'),('city','شهر تحویل'),('address','آدرس کامل تحویل')]:
        if not customer[key]:s['stage']=key;return f'لطفاً {label} را بفرمایید.'
    if not s.get('address_confirmed'):s['stage']='address_confirm';return f"مقصد را تأیید می‌کنید؟ {customer['city']}، {customer['address']} (بله / تغییر آدرس)"
    s['stage']='shopping';return 'چه محصولی و چند کارتن نیاز دارید؟ واحد فروش نمونه‌ها کارتن دوازده‌تایی است.'

@asynccontextmanager
async def lifespan(app):
    if PRODUCTION: raise RuntimeError('این توزیع آزمایشی است؛ استقرار عملیاتی نیازمند احراز و منابع تجاری واقعی است. راهنمای استقرار را بخوانید.')
    db.init();yield

app=FastAPI(title='Sellora',docs_url='/api/docs',lifespan=lifespan)
@app.middleware('http')
async def security(request,call_next):
    if request.method not in ('GET','HEAD','OPTIONS'):
        origin=request.headers.get('origin')
        from urllib.parse import urlsplit
        if origin and urlsplit(origin).netloc!=request.headers.get('host'):return Response('درخواست مجاز نیست',status_code=403)
    res=await call_next(request)
    res.headers['X-Content-Type-Options']='nosniff'
    res.headers['Referrer-Policy']='same-origin'
    res.headers['X-Frame-Options']='DENY'
    res.headers['Content-Security-Policy']="default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; font-src 'self'; script-src 'self'; frame-ancestors 'none'"
    res.headers['Cache-Control']='no-store'
    return res

@app.exception_handler(Exception)
async def unexpected(request,exc):
    from fastapi.responses import JSONResponse
    return JSONResponse({'detail':'عملیات انجام نشد. دوباره تلاش کنید؛ موفقیت سفارش را در سفارش‌های من بررسی کنید.'},status_code=500)

def sid(request):
    value=request.cookies.get(COOKIE)
    if not value:fail('نشست معتبر نیست.',401)
    return value

@app.get('/api/session')
def session(request:Request,response:Response):
    value=request.cookies.get(COOKIE)
    with db.connect() as c:
        exists=c.execute('SELECT 1 FROM sessions WHERE id=? AND expires>?',(value,int(time.time()))).fetchone() if value else None
        if not exists:
            value=secrets.token_urlsafe(32)
            c.execute('INSERT INTO sessions VALUES(?,?,?,?)',(value,None,D({'stage':'mobile'}),int(time.time())+86400))
            c.execute('INSERT INTO carts(session_id) VALUES(?)',(value,))
            response.set_cookie(COOKIE,value,httponly=True,samesite='strict',secure=os.getenv('COOKIE_SECURE')=='true',max_age=86400)
        return view(c,value)

class Turn(BaseModel):
    text:str=Field(min_length=1,max_length=1500)
    turn_id:str=Field(min_length=8,max_length=100)

@app.post('/api/turn')
def turn(body:Turn,request:Request):
    start=time.perf_counter(); value=sid(request)
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        _,s=load(c,value)
        prior=c.execute("SELECT text FROM conversations WHERE session_id=? AND turn_id=? AND role='assistant'",(value,body.turn_id)).fetchone()
        if prior:return dict(reply=prior['text'],state=view(c,value),duplicate=True)
        text=normalize(body.text)
        reply=handle(c,value,s,text)
        # OTP و تلفن در رونوشت ذخیره نمی‌شوند.
        safe=re.sub(r'\d{4,}', '••••',text)
        c.execute('INSERT INTO conversations(session_id,turn_id,role,text) VALUES(?,?,?,?)',(value,body.turn_id,'user',safe))
        c.execute('INSERT INTO conversations(session_id,turn_id,role,text) VALUES(?,?,?,?)',(value,body.turn_id,'assistant',reply))
        persist(c,value,s)
        db.audit(c,value,'turn.completed',{'turn_id':body.turn_id,'ms':round((time.perf_counter()-start)*1000,2)})
        c.commit()
        return dict(reply=reply,state=view(c,value))

def handle(c,value,s,text):
    if text in ('توقف','مکث'):s['paused']=True;return 'گفت‌وگو متوقف شد؛ سبد محفوظ است. برای ادامه بگویید «ادامه بده».'
    if text=='ادامه بده':s['paused']=False;return 'از همین‌جا ادامه می‌دهیم.'
    if s.get('paused'):return 'گفت‌وگو متوقف است. برای ادامه بگویید «ادامه بده».'
    if text=='از اول':s['reset_pending']=True;return 'شروع دوباره سبد را پاک می‌کند. برای تأیید بنویسید «پاک کردن سبد».'
    if text=='پاک کردن سبد' and s.pop('reset_pending',False):save_cart(c,value,{});s['stage']='shopping';return 'سبد پاک شد. مشخصات تأییدشده حفظ شده است.'
    if 'کارشناس' in text:
        customer=auth(c,value)
        c.execute('INSERT INTO callbacks(id,customer_id) VALUES(?,?)',(uid(),customer['id']))
        return 'درخواست تماس در فهرست آزمایشی ثبت شد. اتصال تلفنی یا ارسال به کارشناس واقعی برقرار نیست.'
    row,_=load(c,value)
    if not row['customer_id']:
        if s.get('stage')=='otp':
            if time.time()>s.get('otp_expires',0):s['stage']='mobile';return 'مهلت کد تمام شد. شماره را دوباره وارد کنید.'
            s['attempts']=s.get('attempts',0)+1
            if s['attempts']>5:s['stage']='mobile';s['locked_until']=time.time()+60;return 'تعداد تلاش‌ها زیاد است؛ یک دقیقه بعد شماره را وارد کنید.'
            if text!='123456':return 'کد آزمایشی نادرست است. در این نسخه فقط از ۱۲۳۴۵۶ استفاده کنید.'
            phone=s.pop('mobile')
            customer=c.execute('SELECT * FROM customers WHERE mobile=?',(phone,)).fetchone()
            if not customer:
                cid=uid();c.execute('INSERT INTO customers(id,mobile) VALUES(?,?)',(cid,phone))
            else:cid=customer['id']
            persist(c,value,s,cid)
            # بازیابی تنها بعد از احراز آزمایشی؛ آخرین سبد مشتری از نشست قبلی
            prev=c.execute('SELECT c.items FROM carts c JOIN sessions t ON c.session_id=t.id WHERE t.customer_id=? AND t.id<>? ORDER BY t.expires DESC LIMIT 1',(cid,value)).fetchone()
            if prev:save_cart(c,value,json.loads(prev['items']))
            s['stage']='name';customer=auth(c,value)
            return 'هویت صرفاً در محیط آزمایشی تأیید شد. '+next_question(customer,s)
        if time.time()<s.get('locked_until',0):return 'لطفاً یک دقیقه برای تلاش بعدی صبر کنید.'
        match=re.search(r'(?:\+98|0098|0)?9[\d\s-]{9,15}',text)
        try:phone=mobile(match.group() if match else text)
        except ValueError:
            if find_products(text,db.products(c)):s['pending_product']=text
            return 'درخواستتان را نگه می‌دارم. ابتدا شماره موبایل یازده رقمی را بفرمایید.'
        s.update(stage='otp',mobile=phone,attempts=0,otp_expires=time.time()+180)
        return 'شماره «'+ ' '.join(phone)+'» را بررسی کنید. هیچ پیامکی ارسال نشده؛ برای تأیید آزمایشی کد ۱۲۳۴۵۶ را وارد کنید. اگر شماره اشتباه است، صفحه خروج را بزنید.'
    customer=auth(c,value)
    stage=s.get('stage')
    if stage in ('name','city','address'):
        if len(text)<3:return 'لطفاً این مورد را کامل‌تر وارد کنید.'
        c.execute(f'UPDATE customers SET {stage}=? WHERE id=?',(text,customer['id']))
        customer=auth(c,value);return next_question(customer,s)
    if text=='تغییر آدرس':s.update(stage='city',address_confirmed=False);return 'شهر مقصد جدید کجاست؟'
    if stage=='address_confirm':
        if text not in ('بله','تایید','تأیید'):return 'مقصد را با «بله» تأیید کنید یا «تغییر آدرس» را بنویسید.'
        s['address_confirmed']=True;s['stage']='shopping'
        pending=s.pop('pending_product',None)
        if pending:return shopping(c,value,s,pending)
        return next_question(customer,s)
    if text=='سفارش قبلی':
        order=c.execute('SELECT id,snapshot FROM orders WHERE customer_id=? ORDER BY created DESC LIMIT 1',(customer['id'],)).fetchone()
        if not order:return 'هنوز سفارش آزمایشی قبلی ندارید.'
        snap=json.loads(order['snapshot']);return 'آخرین سفارش: '+ '، '.join(f"{i['name']}، {i['quantity']} کارتن" for i in snap['items'])+'؛ برای افزودن، نام و تعداد موردنظر را بفرمایید.'
    if text in ('همین کافیه','مرور سفارش','تأیید سفارش','تایید سفارش'):
        return 'برای دیدن جمع معتبر و تأیید صریح، دکمه «مرور سفارش» در سبد را بزنید. پیام متنی به‌تنهایی سفارش ثبت نمی‌کند.'
    return shopping(c,value,s,text)

def shopping(c,value,s,text):
    rev,items=cart(c,value);ps=db.products(c)
    if text in ('نه','نمی‌خوام','پیشنهاد نمی‌خواهم'):s['rejected']=True;return 'پیشنهاد دیگری مطرح نمی‌کنم. می‌توانید سفارش را مرور کنید.'
    if text in ('حذفش کن','اولی رو حذف کن'):
        sku=s.get('last_sku') if text=='حذفش کن' else next(iter(items),None)
        if not sku or sku not in items:return 'کدام محصول را حذف کنم؟ نام آن را بفرمایید.'
        del items[sku];save_cart(c,value,items);return 'قلم از سبد حذف شد.'
    parts=re.split(r'\s+و\s+|،',text);changes=[];questions=[]
    for part in parts:
        found=find_products(part,ps)
        if not found:continue
        if len(found)>1:questions.append('کدام مورد؟ '+ ' یا '.join(p['name']+' '+p['size'] for p in found));continue
        p=found[0];sku=p['sku'];s['last_sku']=sku
        if 'حذف' in part:items.pop(sku,None);changes.append(p['name']+' حذف شد');continue
        n=quantity(part)
        if n is None:questions.append('چند کارتن '+p['name']+' نیاز دارید؟ لطفاً نام و تعداد را با هم بگویید.');continue
        if 'کارتن' not in part and sku not in items:questions.append('منظورتان '+str(n)+' کارتن '+p['name']+' است؟ برای تأیید نام، تعداد و «کارتن» را بگویید.');continue
        if n<p['minimum'] or n>p['stock'] or not p['active']:questions.append(p['name']+' با این تعداد موجود نیست؛ موجودی آزمایشی '+str(p['stock'])+' کارتن است.');continue
        items[sku]=n;changes.append(p['name']+'، '+str(n)+' کارتن')
    if changes:save_cart(c,value,items)
    reply='؛ '.join(changes+questions)
    if not reply:reply='نام یا تعداد روشن نیست. نام محصول و تعداد کارتن را بگویید یا از کارت محصول انتخاب کنید.'
    if changes and not questions and not s.get('suggested') and not s.get('rejected'):
        s['suggested']=True
        settings=json.loads(c.execute('SELECT data FROM settings WHERE id=1').fetchone()[0])
        if settings['suggestion_limit']>0:reply+='؛ اگر برای سبد نوشیدنی، آب هم نیاز دارید می‌توانید از کاتالوگ انتخاب کنید. این پیشنهاد قاعده‌ای آزمایشی است.'
    return reply

class CartChange(BaseModel):
    sku:str
    quantity:int=Field(ge=0,le=10000)
    revision:int
@app.post('/api/cart')
def change(body:CartChange,request:Request):
    value=sid(request)
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE');auth(c,value)
        rev,items=cart(c,value)
        if rev!=body.revision:fail('سبد در جای دیگری تغییر کرده است. صفحه را تازه کنید.',409)
        p=next((p for p in db.products(c) if p['sku']==body.sku),None)
        if not p:fail('محصول پیدا نشد.',404)
        if body.quantity and (not p['active'] or body.quantity<p['minimum'] or body.quantity>p['stock']):fail('تعداد در محدوده موجودی و حداقل فروش نیست.')
        if body.quantity:items[body.sku]=body.quantity
        else:items.pop(body.sku,None)
        save_cart(c,value,items);c.commit();return view(c,value)

@app.post('/api/quote')
def quote(request:Request):
    value=sid(request)
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE');customer=auth(c,value);_,s=load(c,value)
        if not all(customer[k] for k in ('name','city','address')) or not s.get('address_confirmed'):fail('مشخصات و مقصد را در گفت‌وگو تکمیل و تأیید کنید.')
        v=view(c,value)
        if not v['cart']['items']:fail('سبد خالی است.')
        for p in v['cart']['items']:
            if p['quantity']>p['stock'] or not p['active']:fail('موجودی تغییر کرده است. سبد را اصلاح کنید.',409)
        settings=json.loads(c.execute('SELECT data FROM settings WHERE id=1').fetchone()[0])
        snapshot=dict(customer=customer,items=v['cart']['items'],total=v['cart']['total'],currency='تومان',discount=0,tax=0,shipping=0,commercial_note='داده و قیمت آزمایشی؛ مالیات و ارسال محاسبه نشده، پرداخت و زمان تحویل تعیین نشده است.',expert_required=settings['expert_required'])
        qid=uid();c.execute('INSERT INTO quotes VALUES(?,?,?,?,?)',(qid,value,v['cart']['revision'],D(snapshot),int(time.time())+300));c.commit()
        return dict(id=qid,revision=v['cart']['revision'],snapshot=snapshot,expires_in=300)

class Submit(BaseModel):
    quote_id:str
    request_key:str=Field(min_length=16,max_length=100)
    confirmed:bool
@app.post('/api/orders')
def submit(body:Submit,request:Request):
    value=sid(request)
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE');customer=auth(c,value)
        old=c.execute('SELECT * FROM orders WHERE request_key=? OR quote_id=?',(body.request_key,body.quote_id)).fetchone()
        if old:
            if old['customer_id']!=customer['id']:fail('دسترسی مجاز نیست.',403)
            return dict(id=old['id'],status=old['status'])
        if not body.confirmed:fail('تأیید صریح لازم است.')
        q=c.execute('SELECT * FROM quotes WHERE id=? AND session_id=?',(body.quote_id,value)).fetchone()
        if not q or q['expires']<time.time():fail('مرور سفارش منقضی یا تغییر کرده است. دوباره مرور کنید.',409)
        rev,_=cart(c,value)
        if rev!=q['revision']:fail('سبد تغییر کرده است. دوباره تأیید کنید.',409)
        snap=json.loads(q['snapshot']);ps={p['sku']:p for p in db.products(c)}
        for i in snap['items']:
            p=ps[i['sku']]
            if not p['active'] or p['price_version']!=i['price_version'] or p['stock_version']!=i['stock_version'] or p['stock']<i['quantity']:fail('قیمت یا موجودی تغییر کرده؛ مرور و تأیید دوباره لازم است.',409)
        current=auth(c,value)
        if current!=snap['customer']:fail('مشخصات تغییر کرده؛ دوباره مرور کنید.',409)
        oid='SL-'+secrets.token_hex(6).upper();now=datetime.now(timezone.utc).isoformat()
        status='در انتظار تأیید کارشناس' if snap['expert_required'] else 'ثبت آزمایشی'
        c.execute('INSERT INTO orders VALUES(?,?,?,?,?,?,?)',(oid,customer['id'],body.request_key,body.quote_id,D(snap),now,status))
        for i in snap['items']:c.execute('UPDATE inventory SET quantity=quantity-?,version=version+1 WHERE sku=?',(i['quantity'],i['sku']))
        save_cart(c,value,{})
        db.audit(c,value,'order.created',{'order_id':oid,'revision':rev,'quote_id':q['id']})
        c.commit();return dict(id=oid,status=status)

@app.get('/api/orders')
def orders(request:Request):
    with db.connect() as c:
        customer=auth(c,sid(request))
        return [dict(id=r['id'],created=r['created'],status=r['status'],snapshot=json.loads(r['snapshot'])) for r in c.execute('SELECT * FROM orders WHERE customer_id=? ORDER BY created DESC',(customer['id'],))]

def owned_order(c,request,oid):
    customer=auth(c,sid(request));r=c.execute('SELECT * FROM orders WHERE id=? AND customer_id=?',(oid,customer['id'])).fetchone()
    if not r:fail('سفارش در دسترس نیست.',404)
    return r

@app.get('/api/orders/{oid}/receipt.pdf')
def receipt(oid:str,request:Request):
    from .receipt import pdf
    with db.connect() as c:r=owned_order(c,request,oid);data=pdf(dict(r))
    return Response(data,media_type='application/pdf',headers={'Content-Disposition':f'attachment; filename="{oid}.pdf"'})

@app.post('/api/logout')
def logout(request:Request,response:Response):
    with db.connect() as c:c.execute('UPDATE sessions SET expires=0 WHERE id=?',(sid(request),))
    response.delete_cookie(COOKIE);return {'ok':True}

@app.get('/api/health')
def health():
    try:
        with db.connect() as c:c.execute('SELECT 1').fetchone()
        database='سالم'
    except Exception:database='قطع'
    return dict(database=database,orders='محلی آزمایشی' if database=='سالم' else 'قطع',stt='نیازمند قرارداد',tts='نیازمند قرارداد',llm='متصل نیست؛ قواعد محلی',catalog='نمونه؛ منبع واقعی در دسترس نبود',authentication='احراز آزمایشی',voice_capabilities=dict(voices=[],streaming=False,full_duplex=False))

class Login(BaseModel):
    password:str=Field(max_length=200)
    role:str='admin'
@app.post('/api/admin/login')
def admin_login(body:Login,response:Response):
    password={'admin':ADMIN,'sales':os.getenv('SELLORA_SALES_PASSWORD',''),'operator':os.getenv('SELLORA_OPERATOR_PASSWORD','')}.get(body.role,'')
    if not password:fail('رمز این نقش روی سرور تنظیم نشده است.',503)
    if not hmac.compare_digest(body.password,password):fail('ورود مجاز نیست.',403)
    token=secrets.token_urlsafe(32);ADMIN_SESSIONS[token]=(time.time()+3600,body.role)
    response.set_cookie('sellora_admin',token,httponly=True,samesite='strict',secure=os.getenv('COOKIE_SECURE')=='true',max_age=3600)
    return {'ok':True}
def admin(request,roles=('admin',)):
    expiry,role=ADMIN_SESSIONS.get(request.cookies.get('sellora_admin',''),(0,''))
    if expiry<time.time() or role not in roles:fail('دسترسی این نقش مجاز نیست.',403)
    return role
@app.get('/api/admin')
def dashboard(request:Request):
    role=admin(request,('admin','sales','operator'))
    with db.connect() as c:
        rows=[dict(r) for r in c.execute('SELECT id,customer_id,created,status,snapshot FROM orders ORDER BY created DESC LIMIT 500')]
        for r in rows:
            r['snapshot']=json.loads(r['snapshot'])
            if role=='operator':
                r['snapshot']['customer']={'name':'اطلاعات محدودشده','city':'—'}
                r['customer_id']='محدود'
        audits=[dict(r) for r in c.execute('SELECT kind,data,created FROM audit_events ORDER BY id DESC LIMIT 100')]
        return dict(role=role,orders=rows,settings=json.loads(c.execute('SELECT data FROM settings WHERE id=1').fetchone()[0]),products=db.products(c),audit=audits if role=='admin' else [],callbacks=[dict(r) for r in c.execute('SELECT * FROM callbacks')] if role in ('admin','sales') else [],metrics=dict(order_count=len(rows),average_order=(sum(r['snapshot']['total'] for r in rows)//len(rows) if rows else None),completion_rate=None,satisfaction=None))
class Settings(BaseModel):
    mode:str
    style:str=Field(max_length=80)
    suggestion_limit:int=Field(ge=0,le=2)
    expert_required:bool
@app.post('/api/admin/settings')
def settings(body:Settings,request:Request):
    admin(request)
    if body.mode not in ('auto','online','offline'):fail('حالت نامعتبر است.')
    with db.connect() as c:
        c.execute('UPDATE settings SET data=? WHERE id=1',(body.model_dump_json(),));db.audit(c,'admin','settings.changed',body.model_dump())
    return {'ok':True}
class Commercial(BaseModel):
    sku:str
    price:int=Field(ge=0,le=1000000000)
    stock:int=Field(ge=0,le=1000000)
@app.post('/api/admin/commercial')
def commercial(body:Commercial,request:Request):
    admin(request)
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        if not c.execute('SELECT 1 FROM products WHERE sku=?',(body.sku,)).fetchone():fail('کالا وجود ندارد.',404)
        c.execute('UPDATE prices SET amount=?,version=version+1 WHERE sku=?',(body.price,body.sku))
        c.execute('UPDATE inventory SET quantity=?,version=version+1 WHERE sku=?',(body.stock,body.sku))
        db.audit(c,'admin','commercial.changed',body.model_dump());c.commit()
    return {'ok':True}


@app.get('/api/admin/orders/{oid}/receipt.pdf')
def admin_receipt(oid:str,request:Request):
    admin(request,('admin','sales'))
    from .receipt import pdf
    with db.connect() as c:
        r=c.execute('SELECT * FROM orders WHERE id=?',(oid,)).fetchone()
        if not r:fail('سفارش وجود ندارد.',404)
        db.audit(c,'admin','receipt.downloaded',{'order_id':oid})
        return Response(pdf(dict(r)),media_type='application/pdf',headers={'Content-Disposition':f'attachment; filename="{oid}.pdf"'})

@app.get('/')
def index():return FileResponse(db.ROOT/'web/index.html')
@app.get('/admin')
def admin_page():return FileResponse(db.ROOT/'web/admin.html')
app.mount('/static',StaticFiles(directory=db.ROOT/'web'),name='static')
