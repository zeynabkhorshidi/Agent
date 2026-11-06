import io,json,pathlib
from datetime import datetime
from zoneinfo import ZoneInfo
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from bidi.algorithm import get_display
import arabic_reshaper

def pdf(order):
    font=pathlib.Path(__file__).resolve().parents[1]/'web/fonts/iransansx-fanum.ttf'
    pdfmetrics.registerFont(TTFont('Persian',str(font)))
    out=io.BytesIO();c=canvas.Canvas(out,pagesize=(595,842));c.setTitle('Sellora - '+order['id']);y=800
    def line(s,big=False):
        nonlocal y
        if y<60:c.showPage();y=800
        c.setFont('Persian',16 if big else 11)
        # شکستن سطر با اندازه واقعی فونت؛ متن و خروجی فقط سمت سرور
        words=str(s).replace('—','-').replace('–','-').split();chunk=''
        for w in words:
            test=(chunk+' '+w).strip()
            if pdfmetrics.stringWidth(get_display(arabic_reshaper.reshape(test)),'Persian',11)>490:
                c.drawRightString(550,y,get_display(arabic_reshaper.reshape(chunk)));y-=23;chunk=w
            else:chunk=test
        c.drawRightString(550,y,get_display(arabic_reshaper.reshape(chunk)));y-=28
    snap=json.loads(order['snapshot']);customer=snap['customer']
    line('Sellora | '+('پیش‌فاکتور' if snap['expert_required'] else 'رسید سفارش'),True)
    line('داده و سفارش آزمایشی — فاکتور رسمی یا پرداخت موفق نیست')
    line('شماره سفارش: '+order['id'])
    dt=datetime.fromisoformat(order['created']).astimezone(ZoneInfo('Asia/Tehran'))
    # تبدیل شمسی با کتابخانه مستقل، زمان مرجع UTC است.
    import jdatetime
    line('تاریخ: '+jdatetime.datetime.fromgregorian(datetime=dt).strftime('%Y/%m/%d %H:%M')+' — تهران')
    line('وضعیت: '+order['status'])
    for title,key in [('مشتری','name'),('کد مشتری','id'),('موبایل','mobile'),('فروشگاه','business'),('شهر','city'),('نشانی','address')]:line(title+': '+(customer[key] or 'اعلام نشده'))
    line('اقلام سفارش',True)
    for p in snap['items']:
        line(p['name']+' | '+p['size']+' | '+p['sku'])
        line(f"{p['quantity']} کارتن × {p['per_carton']} عدد؛ هر کارتن {p['price']:,} تومان؛ جمع {p['total']:,} تومان")
    line(f"تخفیف: {snap['discount']:,} تومان | جمع اقلام: {snap['total']:,} تومان",True)
    line(snap['commercial_note']);line('نگه‌داری این رسید به معنی پرداخت یا تعهد تحویل نیست.')
    c.save();return out.getvalue()
