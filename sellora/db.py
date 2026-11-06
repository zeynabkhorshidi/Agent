import os, sqlite3, json, pathlib
ROOT=pathlib.Path(__file__).resolve().parents[1]
PATH=os.getenv('SELLORA_DB',str(ROOT/'data/sellora.db'))

class Connection(sqlite3.Connection):
    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()

def connect():
    c=sqlite3.connect(PATH,timeout=15,isolation_level=None,factory=Connection)
    c.row_factory=sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON')
    c.execute('PRAGMA journal_mode=WAL')
    return c

def init():
    pathlib.Path(PATH).parent.mkdir(parents=True,exist_ok=True)
    with connect() as c:
        for migration in sorted((ROOT/'migrations').glob('*.sql')):
            c.executescript(migration.read_text())
        # داده نمونه در اجرای عادی ساخته نمی‌شود. رکوردهای قدیمی برای حفظ رسیدها
        # باقی می‌مانند ولی کالاهای نمونه قبلی از فروش خارج می‌شوند.
        for row in c.execute('SELECT sku,data FROM products').fetchall():
            p=json.loads(row['data'])
            if row['sku'] in ('DEMO-OR-1','DEMO-MA-1','DEMO-AP-1','DEMO-WA-05','DEMO-GR-1') and p.get('source')=='داده آزمایشی':
                c.execute('UPDATE products SET active=0 WHERE sku=?',(row['sku'],))
        c.execute("INSERT OR IGNORE INTO settings VALUES(1,?)",(json.dumps(dict(mode='auto',style='گرم و محترمانه',suggestion_limit=0,expert_required=True)),))


def products(c):
    rows=c.execute('SELECT p.data,p.active,r.amount,r.version AS price_version,i.quantity,i.version AS stock_version FROM products p JOIN prices r USING(sku) JOIN inventory i USING(sku)').fetchall()
    result=[]
    for r in rows:
        p=dict(brand='',category='',flavor='',size='',packaging='',per_carton=None,unit=None,minimum=None,aliases=[],catalog_verified=False)
        p.update(json.loads(r['data']))
        p.update(active=bool(r['active']),price=r['amount'],stock=r['quantity'],price_version=r['price_version'],stock_version=r['stock_version'])
        p['commercial_ready']=bool(p['unit'] and p['per_carton'] and p['minimum'] and p['price']>0)
        result.append(p)
    return result

def audit(c,sid,kind,data):
    c.execute('INSERT INTO audit_events(session_id,kind,data) VALUES(?,?,?)',(sid,kind,json.dumps(data,ensure_ascii=False)))
