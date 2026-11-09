"""Opt-in demonstration customers. Never creates products or claims real purchases."""
import json
from . import db

CUSTOMERS = [
 ('DEMO-C01','09120000001','نیما راد','فروشگاه سپیدار','تهران','خیابان نمونه، کوچه یکم، پلاک ۱۰','DEMO-S01'),
 ('DEMO-C02','09120000002','سارا مهر','فروشگاه سپیدار','تهران','خیابان نمونه، کوچه یکم، پلاک ۱۰','DEMO-S01'),
 ('DEMO-C03','09120000003','آرمان نیک','سوپرمارکت آبان','کرج','بلوار نمونه، کوچه دوم، پلاک ۲۰','DEMO-S02'),
 ('DEMO-C04','09120000004','نگار سپهر','فروشگاه نارون','رشت','میدان نمونه، خیابان سوم، پلاک ۳۰','DEMO-S03'),
 ('DEMO-C05','09120000005','سامان داد','کافه آبی','اصفهان','خیابان نمونه، کوچه چهارم، پلاک ۴۰','DEMO-S04'),
 ('DEMO-C06','09120000006','رها آذر','کافه آبی','اصفهان','خیابان نمونه، کوچه چهارم، پلاک ۴۰','DEMO-S04'),
]

def seed_customers():
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        for cid,phone,name,business,city,address,store in CUSTOMERS:
            c.execute('INSERT OR IGNORE INTO stores VALUES(?,?,?,?,?)',(store,business,city,address,'demo'))
            c.execute('INSERT OR IGNORE INTO customers VALUES(?,?,?,?,?,?)',(cid,phone,name,business,city,address))
            # Never relabel a pre-existing, non-demo account with the same phone.
            row=c.execute('SELECT id FROM customers WHERE mobile=?',(phone,)).fetchone()
            if row and row['id']==cid:
                c.execute('INSERT OR IGNORE INTO demo_customers VALUES(?)',(cid,))
                c.execute('INSERT OR IGNORE INTO store_buyers VALUES(?,?)',(store,cid))
        c.commit()
    return {'stores':4,'buyers':6,'source':'demo','orders_created':0}

def accounts(c):
    return [dict(r) for r in c.execute('SELECT c.* FROM customers c JOIN demo_customers d ON d.customer_id=c.id ORDER BY c.id')]

def prepare_demo():
    """Separate demo database, two literal user-supplied catalog rows, sample trade data."""
    from .material_catalog import parse_materials
    seed_customers()
    products=parse_materials(json.loads((db.ROOT/'examples/catalog-material-excerpt.json').read_text(encoding='utf-8')))
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        settings=json.loads(c.execute('SELECT data FROM settings WHERE id=1').fetchone()[0])
        settings['demo_database']=True
        c.execute('UPDATE settings SET data=? WHERE id=1',(json.dumps(settings,ensure_ascii=False),))
        for sku,p in products.items():
            p.update(verification='user_supplied_excerpt',commercial_source='demo')
            c.execute('INSERT OR IGNORE INTO products VALUES(?,?,1)',(sku,json.dumps(p,ensure_ascii=False)))
            c.execute('INSERT OR IGNORE INTO prices VALUES(?,?,1)',(sku,360000 if sku=='100406' else 450000))
            c.execute('INSERT OR IGNORE INTO inventory VALUES(?,100,1)',(sku,))
        ps={p['sku']:p for p in db.products(c)}
        for cid,sku,n in [('DEMO-C01','100406',2),('DEMO-C03','100249',1)]:
            oid='DEMO-HISTORY-'+cid
            customer=dict(c.execute('SELECT * FROM customers WHERE id=?',(cid,)).fetchone())
            item=dict(ps[sku],quantity=n,total=ps[sku]['price']*n)
            snapshot=dict(customer=customer,items=[item],total=item['total'],currency='تومان',discount=0,tax=0,shipping=0,
                          expert_required=True,demo=True,commercial_note='سابقه نمایشی؛ مبلغ و خرید واقعی نیستند.')
            c.execute('INSERT OR IGNORE INTO orders VALUES(?,?,?,?,?,?,?)',(oid,cid,oid+'-request',oid+'-quote',json.dumps(snapshot,ensure_ascii=False),'2026-10-01T08:00:00+00:00','سابقه نمایشی'))
        c.commit()
