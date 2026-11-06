import os
os.environ['CATALOG_AUTO_SYNC']='false'
"""داده مصنوعی فقط برای آزمون؛ برنامه و بسته عادی هرگز آن را بارگذاری نمی‌کنند."""
import json
from sellora import db

def seed_test_products():
    rows=[('DEMO-OR-1','نوشیدنی پرتقال','پرتقال',180000,24),('DEMO-MA-1','نوشیدنی انبه','انبه',210000,18),('DEMO-AP-1','نوشیدنی سیب','سیب',175000,30),('DEMO-WA-05','آب آشامیدنی','ساده',96000,40)]
    with db.connect() as c:
        for sku,name,flavor,price,stock in rows:
            p=dict(sku=sku,name=name,flavor=flavor,size='۱ لیتر',brand='برند تست',category='نوشیدنی',packaging='بطری',per_carton=12,unit='کارتن',minimum=1,color='#1a37b8',aliases=[flavor],source='test-fixture',catalog_verified=True)
            c.execute('INSERT OR IGNORE INTO products VALUES(?,?,1)',(sku,json.dumps(p,ensure_ascii=False)))
            c.execute('INSERT OR IGNORE INTO prices VALUES(?,?,1)',(sku,price))
            c.execute('INSERT OR IGNORE INTO inventory VALUES(?,?,1)',(sku,stock))
