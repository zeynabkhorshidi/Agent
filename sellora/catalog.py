"""فقط مشخصات و عکس‌هایی که واقعاً از کاتالوگ شرکت دریافت شده‌اند."""
import asyncio,hashlib,io,json,os,re,time
from collections import deque
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin,urlsplit,urlunsplit
import httpx
from PIL import Image,ImageOps,UnidentifiedImageError
from . import db

MEDIA=Path(os.getenv('SELLORA_MEDIA_DIR',str(Path(__file__).resolve().parents[1]/'data/media')))
CATALOG=os.getenv('CATALOG_URL','https://catalog.sayesaman.com/').strip()
HOST='catalog.sayesaman.com'

def company_url(url):
    u=urlsplit(url)
    return u.scheme=='https' and u.hostname==HOST and not u.username and not u.password and u.port in (None,443)

def image_url(url):
    u=urlsplit(url);hosts={HOST}|{h.strip().lower() for h in os.getenv('CATALOG_IMAGE_HOSTS','').split(',') if h.strip()}
    return u.scheme=='https' and u.hostname in hosts and not u.username and not u.password and u.port in (None,443)

class PageData(HTMLParser):
    def __init__(self):super().__init__();self.ld=False;self.text='';self.scripts=[];self.images=[];self.links=[];self.image_meta=None
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=='script' and a.get('type','').lower()=='application/ld+json':self.ld=True;self.text=''
        if tag=='img' and a.get('src'):self.images.append({'url':a['src'],'label':a.get('alt','')[:200]})
        if tag=='a' and a.get('href'):self.links.append(a['href'])
        if tag=='meta' and a.get('property')=='og:image':self.image_meta=a.get('content')
    def handle_data(self,data):
        if self.ld:self.text+=data
    def handle_endtag(self,tag):
        if tag=='script' and self.ld:self.ld=False;self.scripts.append(self.text)

def store_image(data):
    if len(data)>8*1024*1024:raise ValueError('حجم عکس باید کمتر از هشت مگابایت باشد.')
    try:
        with Image.open(io.BytesIO(data)) as im:
            if im.width*im.height>16000000 or min(im.size)<32:raise ValueError('ابعاد عکس مناسب نیست.')
            im=ImageOps.exif_transpose(im).convert('RGB');im.thumbnail((1600,1600))
            out=io.BytesIO();im.save(out,format='WEBP',quality=92)
    except (UnidentifiedImageError,OSError,Image.DecompressionBombError):raise ValueError('فایل عکس معتبر نیست.') from None
    data=out.getvalue();name=hashlib.sha256(data).hexdigest()+'.webp';MEDIA.mkdir(parents=True,exist_ok=True);(MEDIA/name).write_bytes(data)
    return '/media/'+name

async def fetch(client,url,limit,validator):
    for _ in range(4):
        if not validator(url):raise ValueError('نشانی خارج از منبع مجاز کاتالوگ است.')
        async with client.stream('GET',url) as r:
            if r.status_code in (301,302,303,307,308):url=urljoin(url,r.headers.get('location',''));continue
            if r.status_code!=200:raise ConnectionError('کاتالوگ در دسترس نیست.')
            data=bytearray()
            async for part in r.aiter_bytes():
                data.extend(part)
                if len(data)>limit:raise ValueError('حجم پاسخ کاتالوگ بیش از حد مجاز است.')
            return bytes(data),r.headers.get('content-type',''),url
    raise ConnectionError('انتقال کاتالوگ کامل نشد.')

def parse_page(html,url):
    parser=PageData();parser.feed(html);products=[]
    def visit(x):
        if isinstance(x,list):
            for a in x:visit(a)
        elif isinstance(x,dict):
            types=x.get('@type',[]);types=[types] if isinstance(types,str) else types
            if isinstance(types,list) and 'Product' in types and isinstance(x.get('name'),str) and x['name'].strip():
                img=x.get('image','');img=img[0] if isinstance(img,list) and img else img
                if isinstance(img,dict):img=img.get('url','')
                brand=x.get('brand','');brand=brand.get('name','') if isinstance(brand,dict) else brand
                products.append({'name':x['name'].strip()[:200],'sku':str(x.get('sku',''))[:64],
                  'image':urljoin(url,img) if isinstance(img,str) and img else None,'brand':str(brand)[:100],
                  'category':str(x.get('category',''))[:100],'source_url':url,'description':str(x.get('description',''))[:2000]})
            for v in x.values():
                if isinstance(v,(dict,list)):visit(v)
    for raw in parser.scripts:
        try:visit(json.loads(raw))
        except (ValueError,TypeError):continue
    return products,parser

async def preview(transport=None):
    if not company_url(CATALOG):raise ValueError('نشانی کاتالوگ معتبر نیست.')
    async with httpx.AsyncClient(timeout=12,follow_redirects=False,transport=transport) as c:
        data,_,url=await fetch(c,CATALOG,4*1024*1024,company_url)
    products,parser=parse_page(data.decode('utf-8',errors='replace'),url)
    return {'source':CATALOG,'products':products,'image_candidates':[dict(url=urljoin(url,i['url']),label=i['label']) for i in parser.images[:100]],'note':'فقط داده واقعی صفحه؛ قیمت و موجودی فروش جداگانه تأیید می‌شوند.'}

class CatalogSync:
    def __init__(self,transport=None):self.transport=transport;self.task=None;self.state={'state':'not_started','products':0,'images':0,'pages':0,'complete':False}
    def start(self):
        if not self.task or self.task.done():self.task=asyncio.create_task(self.run())
        return self.state
    async def run(self):
        self.state={'state':'running','products':0,'images':0,'pages':0,'complete':False}
        queue=deque([CATALOG]);seen=set();found={};limit=int(os.getenv('CATALOG_MAX_PAGES','200'));failures=0
        try:
            if not company_url(CATALOG):raise ValueError()
            async with asyncio.timeout(120):
                async with httpx.AsyncClient(timeout=12,follow_redirects=False,transport=self.transport) as client:
                    while queue and len(seen)<limit:
                        url=queue.popleft()
                        if url in seen:continue
                        seen.add(url)
                        try:data,ctype,actual=await fetch(client,url,4*1024*1024,company_url)
                        except (httpx.HTTPError,ConnectionError,ValueError):
                            failures+=1
                            if len(seen)==1:raise ConnectionError()
                            continue
                        self.state['pages']+=1
                        if 'html' not in ctype and not data.lstrip().startswith(b'<'):continue
                        records,parser=parse_page(data.decode('utf-8',errors='replace'),actual)
                        for p in records:
                            ident=p['sku'] or p['source_url']+'|'+p['name'];found[ident]=p
                        for href in parser.links:
                            target=urljoin(actual,href);u=urlsplit(target);target=urlunsplit((u.scheme,u.netloc,u.path,u.query,''))
                            if not company_url(target) or target in seen or len(queue)>2000:continue
                            if re.search(r'logout|signout|add-to-cart|wp-admin|wp-login|delete|remove|checkout',target,re.I):continue
                            if re.search(r'\.(?:jpg|jpeg|png|webp|gif|svg|pdf|zip|css|js)$',u.path,re.I):continue
                            queue.append(target)
                    # عکس فقط از لینک همان محصول دریافت می‌شود؛ هیچ تصویر عمومی به SKU نسبت داده نمی‌شود.
                    images=0
                    for p in found.values():
                        p['image_url']=None
                        if p['image'] and image_url(p['image']):
                            try:
                                raw,_,origin=await fetch(client,p['image'],8*1024*1024,image_url);p['image_url']=await asyncio.to_thread(store_image,raw);p['image_origin']=origin;images+=1
                            except (ValueError,ConnectionError,httpx.HTTPError):failures+=1
                        rawsku=p['sku'];p['external_sku']=rawsku
                        if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',rawsku):p['sku']='CAT-'+hashlib.sha256((p['source_url']+'|'+p['name']).encode()).hexdigest()[:18]
                        p.update(source=CATALOG,catalog_verified=True,image_kind='catalog',flavor='',size='',packaging='',per_carton=None,unit=None,minimum=None,aliases=[],last_catalog_sync=int(time.time()))
                        with db.connect() as c:
                            c.execute('BEGIN IMMEDIATE')
                            row=c.execute('SELECT data FROM products WHERE sku=?',(p['sku'],)).fetchone()
                            if row:
                                old=json.loads(row['data'])
                                for k in ('per_carton','unit','minimum','size','packaging'):
                                    if old.get('catalog_verified') and old.get(k):p[k]=old[k]
                                if not p['image_url'] and old.get('catalog_verified'):
                                    p['image_url']=old.get('image_url');p['image_origin']=old.get('image_origin')
                                c.execute('UPDATE products SET data=? WHERE sku=?',(json.dumps(p,ensure_ascii=False),p['sku']))
                            else:c.execute('INSERT INTO products VALUES(?,?,0)',(p['sku'],json.dumps(p,ensure_ascii=False)))
                            c.execute('INSERT OR IGNORE INTO prices VALUES(?,0,1)',(p['sku'],));c.execute('INSERT OR IGNORE INTO inventory VALUES(?,0,1)',(p['sku'],));c.commit()
                        self.state.update(products=len(found),images=images)
            self.state.update(state='ready' if found else 'unsupported',complete=bool(found) and not queue and not failures,finished_at=int(time.time()))
        except (httpx.HTTPError,ConnectionError,ValueError,TimeoutError):self.state.update(state='unavailable',complete=False,finished_at=int(time.time()))
        return self.state
