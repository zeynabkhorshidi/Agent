"""پاک‌سازی داده موقت و پشتیبان بدون کپی ناسازگار WAL."""
import argparse,time,sqlite3
from . import db
p=argparse.ArgumentParser();p.add_argument('action',choices=['purge','backup']);p.add_argument('--destination');p.add_argument('--transcript-days',type=int,default=7)
def main():
    args=p.parse_args()
    with db.connect() as c:
        if args.action=='backup':
            if not args.destination:p.error('--destination لازم است')
            with sqlite3.connect(args.destination) as target:c.backup(target)
            print('پشتیبان سازگار ساخته شد. دسترسی فایل را محدود نگه دارید.')
        else:
            if args.transcript_days<1:p.error('حداقل یک روز لازم است')
            c.execute("DELETE FROM conversations WHERE created < datetime('now', ?)",(f'-{args.transcript_days} days',))
            c.execute('DELETE FROM quotes WHERE expires<?',(int(time.time()),))
            c.execute('DELETE FROM voice_requests WHERE created<?',(int(time.time())-600,))
            print('رونوشت‌های قدیمی و مرورهای منقضی پاک شدند؛ اطلاعات مشتری و سفارش محفوظ‌اند.')
if __name__=='__main__':main()
