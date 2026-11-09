import re

def normalize(s):
    return str(s).translate(str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩يك','01234567890123456789یک')).replace('\u200c',' ').strip()

def mobile(s):
    s = re.sub(r'[\s\-()]','',normalize(s))
    if s.startswith('+98'): s='0'+s[3:]
    if s.startswith('0098'): s='0'+s[4:]
    if not re.fullmatch(r'09\d{9}',s): raise ValueError('شماره موبایل یازده رقمی با ۰۹ وارد کنید.')
    return s

NUMBERS={'یک':1,'یه':1,'دو':2,'سه':3,'چهار':4,'پنج':5,'شش':6,'هفت':7,'هشت':8,'نه':9,'ده':10}
def quantity(s):
    s=normalize(s)
    m=re.search(r'\b(\d+)\s*(?:کارتن|عدد|تا)\b',s)
    if m:return int(m.group(1))
    if re.fullmatch(r'\d+',s):return int(s)
    for w,n in NUMBERS.items():
        if re.search(r'\b'+w+r'\b',s): return n
    return None

def search_text(text):
    text=normalize(text).lower().replace('آ','ا').replace('أ','ا').replace('ۀ','ه')
    text=re.sub(r'اب\s*میوه(?:\s*های)?','ابمیوه',text)
    text=re.sub(r'سن\s*ایچ','سنایچ',text)
    return re.sub(r'\s+',' ',text)

def find_products(text, products):
    text=search_text(text)
    exact=[p for p in products if re.search(r'(?<!\w)'+re.escape(p['sku'].lower())+r'(?!\w)',text)]
    if exact:return exact
    tokens=set(re.findall(r'\w+',text)) - {'میخوام','می','خوام','میخواهم','میخواهیم','از','رو','را','کن','کنید','بده','لطفا','برای','عدد','تا','کارتن','نه','حذف','اون','همون','محصول','محصولات'}
    tokens={t for t in tokens if not t.isdigit() and t not in NUMBERS}
    ranked=[]
    for p in products:
        words=set(search_text(' '.join([p['name'],p.get('flavor',''),p.get('brand',''),p.get('category',''),p.get('subcategory','')]+p.get('aliases',[]))).split())
        score=len(tokens & words)
        if score: ranked.append((score,p))
    if not ranked:return []
    best=max(x[0] for x in ranked)
    return [p for n,p in ranked if n==best]
