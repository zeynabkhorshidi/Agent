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
    m=re.search(r'\b(\d+)\b',normalize(s))
    if m: return int(m.group())
    for w,n in NUMBERS.items():
        if re.search(r'\b'+w+r'\b',s): return n
    return None

def find_products(text, products):
    text=normalize(text)
    tokens=set(re.findall(r'\w+',text))
    ranked=[]
    for p in products:
        words=set(normalize(' '.join([p['name'],p['flavor'],p['brand'],p['sku']]+p.get('aliases',[]))).split())
        score=len(tokens & words)
        if score: ranked.append((score,p))
    if not ranked:return []
    best=max(x[0] for x in ranked)
    return [p for n,p in ranked if n==best]
