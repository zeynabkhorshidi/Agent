"""ورود JSON مجاز از مالک کاتالوگ؛ python -m sellora.catalog_import path.json
این ابزار تنها مشخصات کالا را وارد می‌کند. قیمت و موجودی واقعی از منبع تجاری مستقل لازم است.
"""
import json,sys,re
from pydantic import BaseModel,Field,field_validator
from . import db
class Product(BaseModel):
    sku:str=Field(pattern=r'^[A-Za-z0-9_-]{1,64}$')
    name:str=Field(min_length=2,max_length=200)
    brand:str=Field(min_length=1,max_length=100)
    category:str=Field(min_length=1,max_length=100)
    flavor:str=Field(max_length=100)
    size:str=Field(max_length=100)
    packaging:str=Field(max_length=100)
    per_carton:int=Field(ge=1,le=1000)
    unit:str=Field(pattern='^کارتن$')
    minimum:int=Field(ge=1,le=10000)
    aliases:list[str]=Field(default_factory=list,max_length=50)
    source:str=Field(min_length=3,max_length=500)
    image_url:str|None=Field(default=None,pattern=r'^/(?:media|static/images)/[A-Za-z0-9_./-]+$')
    color:str=Field(default='#7388af',pattern=r'^#[0-9a-fA-F]{6}$')
    @field_validator('image_url')
    @classmethod
    def safe_image(cls,value):
        if value and '..' in value:raise ValueError('مسیر عکس معتبر نیست')
        return value

def main(path):
    data=json.load(open(path));items=[Product.model_validate(x).model_dump() for x in data]
    if len({x['sku'] for x in items})!=len(items):raise ValueError('شناسه تکراری در فایل')
    db.init()
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        for p in items:
            c.execute('INSERT INTO products(sku,data,active) VALUES(?,?,0) ON CONFLICT(sku) DO UPDATE SET data=excluded.data,active=0',(p['sku'],json.dumps(p,ensure_ascii=False)))
            c.execute('INSERT OR IGNORE INTO prices VALUES(?,0,1)',(p['sku'],))
            c.execute('INSERT OR IGNORE INTO inventory VALUES(?,0,1)',(p['sku'],))
        db.audit(c,'import','catalog.imported',{'count':len(items)});c.commit()
    print(f'{len(items)} قلم غیرفعال وارد شد؛ قیمت، موجودی و فعال‌سازی باید از منبع معتبر تأمین شود.')
if __name__=='__main__':main(sys.argv[1])
