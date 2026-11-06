"""واردسازی محافظه‌کارانه از داده ساختاریافته وب؛ بدون حدس قیمت/موجودی فروش."""
import hashlib,io,json,os
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin,urlsplit
import httpx
from PIL import Image,ImageOps,UnidentifiedImageError

MEDIA=Path(os.getenv('SELLORA_MEDIA_DIR',str(Path(__file__).resolve().parents[1]/'data/media')))
CATALOG=os.getenv('CATALOG_URL','https://catalog.sayesaman.com/')

class PageData(HTMLParser):
    def __init__(self):super().__init__();self.ld=False;self.text='';self.scripts=[];self.images=[]
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=='script' and a.get('type','').lower()=='application/ld+json':self.ld=True;self.text=''
        if tag=='img' and a.get('src'):self.images.append({'url':a['src'],'label':a.get('alt','')[:200]})
    def handle_data(self,data):
        if self.ld:self.text+=data
    def handle_endtag(self,tag):
        if tag=='script' and self.ld:self.ld=False;self.scripts.append(self.text)

def store_image(data):
    if len(data)>8*1024*1024:raise ValueError('حجم عکس باید کمتر از هشت مگابایت باشد.')
    try:
        with Image.open(io.BytesIO(data)) as im:
            if im.width*im.height>16000000 or min(im.size)<32:raise ValueError('ابعاد عکس مناسب نیست.')
            im=ImageOps.exif_transpose(im).convert('RGB');im.thumbnail((1400,1400))
            out=io.BytesIO();im.save(out,format='WEBP',quality=88)
    except (UnidentifiedImageError,OSError,Image.DecompressionBombError):raise ValueError('فایل عکس معتبر نیست.') from None
    encoded=out.getvalue();name=hashlib.sha256(encoded).hexdigest()+'.webp'
    MEDIA.mkdir(parents=True,exist_ok=True);(MEDIA/name).write_bytes(encoded)
    return '/media/'+name

async def preview(transport=None):
    # مقصد فقط تنظیم سمت سرور است؛ لینک‌های دلخواه کاربر واکشی نمی‌شوند.
    origin=urlsplit(CATALOG)
    if origin.scheme!='https' or origin.hostname!='catalog.sayesaman.com':raise ValueError('نشانی کاتالوگ شرکت معتبر نیست.')
    async with httpx.AsyncClient(timeout=12,follow_redirects=False,transport=transport) as c:
        r=await c.get(CATALOG)
        if r.status_code!=200:raise ConnectionError('کاتالوگ از سرور در دسترس نیست.')
        if len(r.content)>4*1024*1024:raise ValueError('صفحه کاتالوگ بیش از حد بزرگ است.')
    parser=PageData();parser.feed(r.text);products=[]
    def visit(x):
        if isinstance(x,list):
            for a in x:visit(a)
        elif isinstance(x,dict):
            types=x.get('@type',[]);types=[types] if isinstance(types,str) else types
            if 'Product' in types and isinstance(x.get('name'),str):
                img=x.get('image','');img=img[0] if isinstance(img,list) and img else img
                if isinstance(img,dict):img=img.get('url','')
                products.append({'name':x['name'][:200],'sku':str(x.get('sku',''))[:64],
                                 'image':urljoin(CATALOG,img) if isinstance(img,str) and img else None,
                                 'brand':str(x.get('brand',{}).get('name','') if isinstance(x.get('brand'),dict) else x.get('brand',''))[:100],
                                 'category':str(x.get('category',''))[:100]})
            for v in x.values():
                if isinstance(v,(list,dict)):visit(v)
    for raw in parser.scripts:
        try:visit(json.loads(raw))
        except (ValueError,TypeError):continue
    return {'source':CATALOG,'products':products[:100],
            'image_candidates':[dict(url=urljoin(CATALOG,i['url']),label=i['label']) for i in parser.images[:100]],
            'note':'قیمت و موجودی فروش از این صفحه تأیید نمی‌شود؛ اطلاعات بدون SKU/بسته‌بندی نیازمند تکمیل مدیر است.'}
