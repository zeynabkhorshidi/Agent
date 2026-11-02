import os, sqlite3, json, pathlib
ROOT=pathlib.Path(__file__).resolve().parents[1]
PATH=os.getenv('SELLORA_DB',str(ROOT/'data/sellora.db'))

def connect():
    c=sqlite3.connect(PATH,timeout=15,isolation_level=None)
    c.row_factory=sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON')
    c.execute('PRAGMA journal_mode=WAL')
    return c

def init():
    pathlib.Path(PATH).parent.mkdir(parents=True,exist_ok=True)
    with connect() as c:
        c.executescript((ROOT/'migrations/001_initial.sql').read_text())
        if not c.execute('SELECT 1 FROM products LIMIT 1').fetchone():
            products=[('DEMO-OR-1','نوشیدنی پرتقال','پرتقال','۱ لیتر','#f8a83a',180000,24),('DEMO-MA-1','نوشیدنی انبه','انبه','۱ لیتر','#ffc24d',210000,18),('DEMO-AP-1','نوشیدنی سیب','سیب','۱ لیتر','#87ad72',175000,30),('DEMO-WA-05','آب آشامیدنی','ساده','۵۰۰ میلی‌لیتر','#6dbde1',96000,40)]
            c.execute('BEGIN IMMEDIATE')
            for sku,name,flavor,size,color,price,stock in products:
                p=dict(sku=sku,name=name,flavor=flavor,size=size,brand='برند نمونه',category='نوشیدنی آزمایشی',packaging='بطری',per_carton=12,unit='کارتن',minimum=1,color=color,aliases=[flavor],source='داده آزمایشی')
                c.execute('INSERT INTO products VALUES(?,?,1)',(sku,json.dumps(p,ensure_ascii=False)))
                c.execute('INSERT INTO prices VALUES(?,?,1)',(sku,price))
                c.execute('INSERT INTO inventory VALUES(?,?,1)',(sku,stock))
            c.execute("INSERT OR IGNORE INTO settings VALUES(1,?)",(json.dumps(dict(mode='auto',style='گرم و محترمانه',suggestion_limit=1,expert_required=False)),))
            c.commit()

def products(c):
    rows=c.execute('SELECT p.data,p.active,r.amount,r.version AS price_version,i.quantity,i.version AS stock_version FROM products p JOIN prices r USING(sku) JOIN inventory i USING(sku)').fetchall()
    return [dict(json.loads(r['data']),active=bool(r['active']),price=r['amount'],stock=r['quantity'],price_version=r['price_version'],stock_version=r['stock_version']) for r in rows]

def audit(c,sid,kind,data):
    c.execute('INSERT INTO audit_events(session_id,kind,data) VALUES(?,?,?)',(sid,kind,json.dumps(data,ensure_ascii=False)))
