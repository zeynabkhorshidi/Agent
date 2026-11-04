"""پس از اجرای سرور: python -m tests.browser_smoke؛ نیازمند Playwright و Chromium."""
from playwright.sync_api import sync_playwright
from pathlib import Path
import time,json,os,uuid
out=Path('artifacts');out.mkdir(exist_ok=True)
with sync_playwright() as p:
    browser=p.chromium.launch(executable_path=os.getenv('CHROMIUM_PATH','/usr/bin/chromium'),headless=True,args=['--no-sandbox'])
    page=browser.new_page(viewport={'width':1440,'height':1100},device_scale_factor=1)
    errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto(os.getenv('BASE_URL','http://127.0.0.1:8000'));page.wait_for_selector('.product');page.screenshot(path=str(out/'desktop.png'),full_page=True)
    page.click('#textStart')
    measurements=[]
    for text in ['09'+str(uuid.uuid4().int)[:9],'123456','فروشگاه آزمایشی','تهران','خیابان آزمایشی، پلاک ۱۲','بله','پرتقال دو کارتن و انبه سه کارتن','پیشنهاد نمی‌خواهم']:
        before=page.locator('.bubble').count();start=time.perf_counter();page.fill('#input',text);page.click('.send');page.wait_for_function('(n)=>document.querySelectorAll(".bubble").length>n',arg=before if before>1 else 0);page.wait_for_function('()=>!document.querySelector("#input").disabled');measurements.append(round((time.perf_counter()-start)*1000,2))
    assert page.locator('.cart-row').count()==2
    page.click('#review');page.wait_for_selector('#reviewDialog[open]');page.check('#confirmCheck');t=time.perf_counter();page.click('#submitOrder');page.wait_for_selector('#successDialog[open]');submit_ms=round((time.perf_counter()-t)*1000,2)
    with page.expect_download() as dl:page.click('#receiptLink')
    dl.value.save_as(out/'receipt.pdf');assert (out/'receipt.pdf').read_bytes().startswith(b'%PDF')
    page.screenshot(path=str(out/'success.png'),full_page=True)
    page.click('#successClose');page.click('#ordersTab');page.wait_for_selector('.order-card');assert page.locator('.order-card').count()>=1
    mobile=browser.new_page(viewport={'width':390,'height':844},is_mobile=True,has_touch=True)
    mobile.goto(os.getenv('BASE_URL','http://127.0.0.1:8000'));mobile.wait_for_selector('.product');assert mobile.evaluate('document.documentElement.scrollWidth<=innerWidth');mobile.screenshot(path=str(out/'mobile.png'),full_page=True)
    assert not errors,errors
    print(json.dumps({'browser_errors':errors,'desktop':'passed','mobile_overflow':'none','text_turn_roundtrip_ms':measurements,'submit_to_success_ms':submit_ms,'audio':'tested separately in browser_voice.py'},ensure_ascii=False))
    browser.close()
