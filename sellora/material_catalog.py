"""Sayesaman's supplied material and image-index contracts; no inferred endpoint."""
import asyncio, json, os, re, time
from . import db
from .domain import normalize

BASE='https://catalog.sayesaman.com'
MATERIALS=BASE+'/Mara?typename=material'
IMAGES=BASE+'/api/products/available-images'
IMAGE_TEMPLATE=BASE+'/img/Products/{material}.png'

def material_product(row):
    if not isinstance(row,dict):raise ValueError('ردیف کالا معتبر نیست.')
    sku=str(row.get('material','')).strip()
    name=str(row.get('materialDescription','')).strip()
    if not re.fullmatch(r'[0-9]{1,32}',sku) or not name or len(name)>300:
        raise ValueError('کد یا نام کالا معتبر نیست.')
    raw_count=str(row.get('qtycar','')).strip()
    count=int(raw_count) if raw_count.isdigit() and 0<int(raw_count)<=10000 else None
    brand=str(row.get('pH11','')).strip()[:100]
    category=str(row.get('pH21','')).strip()[:200]
    subgroup=str(row.get('pH31','')).strip()[:200]
    clean=normalize(name)
    # Attributes only when literally present in the supplied description.
    flavors=[f for f in ('پرتقال','سیب','انبه','هلو','آلبالو','آناناس','انگور','انار','لیمو','گواوا','موز','چندمیوه','استوایی') if f in clean]
    size_match=re.search(r'\d+(?:[.,]\d+)?\s*(?:CC|cc|ML|ml|سی سی|میلی لیتر|لیتر|گرم|کیلوگرم)',clean)
    packaging=next((p for p in ('قوطی','بطری','پاکتی','تتراپک','شیشه') if p in clean),'')
    return dict(sku=sku,external_sku=sku,name=name,brand=brand,category=category,
        subcategory=subgroup,flavor=' '.join(flavors),size=size_match.group() if size_match else '',
        packaging=packaging,per_carton=count,unit='کارتن',minimum=1,
        sales_policy='واحد کارتن و حداقل یک کارتن، قابل تنظیم توسط فروش',
        net_weight=str(row.get('netWeight','')),weight_unit=str(row.get('gewei','')),
        barcode=str(row.get('eaN11','')).strip('*'),hierarchy=str(row.get('prdha','')),
        aliases=[category,subgroup],source=MATERIALS,source_url=MATERIALS,
        catalog_verified=True,catalog_present=True,image_kind='catalog',image_url=None,
        last_catalog_sync=int(time.time()))

def parse_materials(payload):
    if not isinstance(payload,list) or not payload or len(payload)>50000:
        raise ValueError('پاسخ محصولات باید فهرست غیرخالی باشد.')
    result={}
    for row in payload:
        product=material_product(row)
        if product['sku'] in result:raise ValueError('کد کالای تکراری در پاسخ کاتالوگ است.')
        result[product['sku']]=product
    return result

def parse_image_index(payload):
    if not isinstance(payload,list) or len(payload)>50000 or any(not isinstance(x,str) for x in payload):
        raise ValueError('ساختار فهرست عکس‌ها معتبر نیست.')
    return {x for x in payload if re.fullmatch(r'[0-9]{1,32}',x)}

async def sync_materials(service):
    # Import shared bounded fetch and image sanitization without a module cycle.
    from .catalog import fetch,company_url,image_url,store_image
    import httpx
    service.state=dict(state='running',products=0,images=0,pages=0,complete=False,
                       source='material_api',images_pending=0,image_failures=0)
    try:
        async with asyncio.timeout(int(os.getenv('CATALOG_SYNC_TIMEOUT','900'))):
            async with httpx.AsyncClient(timeout=20,follow_redirects=False,transport=service.transport) as client:
                raw,_,_=await fetch(client,MATERIALS,16*1024*1024,company_url)
                products=parse_materials(json.loads(raw));service.state['pages']=1
                # A failing image index must not throw away successfully fetched products.
                try:
                    raw,_,_=await fetch(client,IMAGES,2*1024*1024,company_url)
                    image_ids=parse_image_index(json.loads(raw));index_ok=True;service.state['pages']=2
                except (httpx.HTTPError,ConnectionError,ValueError):image_ids=set();index_ok=False
                cached=set()
                with db.connect() as c:
                    c.execute('BEGIN IMMEDIATE')
                    for sku,p in products.items():
                        previous=c.execute('SELECT data FROM products WHERE sku=?',(sku,)).fetchone()
                        if previous:
                            old=json.loads(previous['data'])
                            for field in ('unit','minimum'):
                                if old.get('catalog_verified') and old.get(field):p[field]=old[field]
                            if old.get('image_url') and (not index_ok or sku in image_ids):
                                p['image_url']=old['image_url'];p['image_origin']=old.get('image_origin')
                            c.execute('UPDATE products SET data=? WHERE sku=?',(json.dumps(p,ensure_ascii=False),sku))
                        else:c.execute('INSERT INTO products VALUES(?,?,0)',(sku,json.dumps(p,ensure_ascii=False)))
                        c.execute('INSERT OR IGNORE INTO prices VALUES(?,0,1)',(sku,))
                        c.execute('INSERT OR IGNORE INTO inventory VALUES(?,0,1)',(sku,))
                        if index_ok:
                            url=IMAGE_TEMPLATE.format(material=sku)
                            status='pending' if sku in image_ids else 'not_listed'
                            previous_image=c.execute('SELECT * FROM catalog_images WHERE sku=?',(sku,)).fetchone()
                            if previous_image and previous_image['status']=='ready' and sku in image_ids and p.get('image_url') and int(time.time())-(previous_image['checked_at'] or 0)<86400:
                                from .catalog import MEDIA
                                if (MEDIA/p['image_url'].split('/')[-1]).is_file():status='ready';cached.add(sku)
                            c.execute('INSERT INTO catalog_images VALUES(?,?,?,?,?) ON CONFLICT(sku) DO UPDATE SET source_url=excluded.source_url,status=excluded.status',
                                      (sku,url,None,status,int(time.time())))
                    # This is a validated full material snapshot, so absent API products leave sale.
                    for row in c.execute('SELECT sku,data FROM products').fetchall():
                        old=json.loads(row['data'])
                        if old.get('source')==MATERIALS and row['sku'] not in products:
                            old['catalog_present']=False
                            c.execute('UPDATE products SET data=?,active=0 WHERE sku=?',(json.dumps(old,ensure_ascii=False),row['sku']))
                    c.commit()
                candidates=[p for p in products.values() if p['sku'] in image_ids and p['sku'] not in cached]
                service.state.update(products=len(products),images=len(cached),images_pending=len(candidates),image_index_ok=index_ok,available_image_codes=len(image_ids))
                # A fixed worker pool bounds both memory and concurrent requests for large catalogs.
                queue=asyncio.Queue()
                for p in candidates:queue.put_nowait(p)
                async def worker():
                    while not queue.empty():
                        p=queue.get_nowait();sku=p['sku'];url=IMAGE_TEMPLATE.format(material=sku)
                        try:
                            raw,_,actual=await fetch(client,url,8*1024*1024,image_url)
                            local=await asyncio.to_thread(store_image,raw)
                            with db.connect() as c:
                                c.execute('BEGIN IMMEDIATE')
                                row=c.execute('SELECT data FROM products WHERE sku=?',(sku,)).fetchone()
                                current=json.loads(row['data']);current.update(image_url=local,image_origin=actual)
                                c.execute('UPDATE products SET data=? WHERE sku=?',(json.dumps(current,ensure_ascii=False),sku))
                                c.execute("UPDATE catalog_images SET local_url=?,status='ready',checked_at=? WHERE sku=?",(local,int(time.time()),sku));c.commit()
                            service.state['images']+=1
                        except (httpx.HTTPError,ConnectionError,ValueError):
                            service.state['image_failures']+=1
                            with db.connect() as c:c.execute("UPDATE catalog_images SET status='failed',checked_at=? WHERE sku=?",(int(time.time()),sku))
                        finally:service.state['images_pending']-=1;queue.task_done()
                await asyncio.gather(*(worker() for _ in range(4)))
                service.state.update(state='ready',complete=index_ok and not service.state['image_failures'])
    except (httpx.HTTPError,ConnectionError,ValueError,TimeoutError):
        service.state.update(state='partial' if service.state['products'] else 'unavailable',complete=False)
    service.state['finished_at']=int(time.time())
    return service.state
