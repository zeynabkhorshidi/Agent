"""آزمون UI با STT کنترل‌شده؛ هیچ مدل واقعی، صدای واقعی یا کاتالوگ شرکت را تأیید نمی‌کند."""
import json,os,time,uuid
from pathlib import Path
import httpx
from playwright.sync_api import sync_playwright
BASE=os.getenv('BASE_URL','http://127.0.0.1:8010');FIXTURE='http://127.0.0.1:8134';out=Path('artifacts');out.mkdir(exist_ok=True)
def control(text):httpx.post(FIXTURE+'/_test/control',json={'text':text}).raise_for_status()
with sync_playwright() as p:
 browser=p.chromium.launch(executable_path='/usr/bin/chromium',args=['--no-sandbox','--use-fake-device-for-media-stream','--use-fake-ui-for-media-stream'])
 context=browser.new_context(permissions=['microphone'],viewport={'width':1440,'height':1080})
 page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
 def response(r):
  if '/api/voice/transcribe' in r.url or '/api/turn' in r.url:
   try:
    b=r.json();print(r.url.rsplit('/',1)[-1],r.status, b.get('detail') or b.get('quote_id') or list(b.get('actions',{})))
   except:pass
 page.on('response',response)
 page.goto(BASE);page.wait_for_selector('.product');page.evaluate('()=>document.fonts.ready');assert page.evaluate('()=>document.fonts.check("14px IRANSansX")')
 page.screenshot(path=str(out/'storefront-desktop.png'),full_page=True)
 page.locator('[data-details]').first.click();page.wait_for_selector('#productDialog[open]');page.click('#closeProduct')
 page.fill('#search','پرتقال');assert page.locator('.product').count()==1;page.fill('#search','');page.select_option('#sort','price-desc')
 page.click('#textStart');phone='09'+str(uuid.uuid4().int)[:9]
 for text in [phone,'123456','نام من زینب تست','شهر من تهران','آدرسم خیابان تست پلاک دوازده','بله','پرتقال دو کارتن و انبه سه کارتن']:
  page.fill('#input',text);page.click('.send');page.wait_for_function('()=>!document.querySelector("#input").disabled')
 assert page.locator('.cart-row').count()==2
 # درخواست مرور هم از همان منطق گفت‌وگو می‌آید.
 page.fill('#input','همین کافیه');page.click('.send');page.wait_for_selector('#reviewDialog[open]')
 # تأیید نهایی با میکروفون و transcript معتبرِ متصل به quote
 control('سفارش را تأیید می کنم');page.click('#confirmByVoice');page.wait_for_function('()=>document.querySelector("#confirmByVoice").textContent.includes("پایان ضبط")');page.wait_for_timeout(400);page.click('#confirmByVoice');
 try:page.wait_for_selector('#successDialog[open]',timeout=15000)
 except Exception:
  print('DEBUG',page.locator('#quoteVoiceStatus').inner_text(),page.locator('#toast').inner_text(),errors);page.screenshot(path=str(out/'storefront-failure.png'),full_page=True);raise
 with page.expect_download() as dl:page.click('#receiptLink')
 dl.value.save_as(out/'storefront-receipt.pdf');assert (out/'storefront-receipt.pdf').read_bytes().startswith(b'%PDF')
 page.click('#successClose');page.screenshot(path=str(out/'storefront-order.png'),full_page=True)
 mobile=context.new_page();mobile.set_viewport_size({'width':390,'height':844});mobile.goto(BASE);mobile.wait_for_selector('.product');assert mobile.evaluate('document.documentElement.scrollWidth<=innerWidth');mobile.click('#cartToggle');mobile.wait_for_selector('.basket.open');mobile.click('#cartClose');mobile.screenshot(path=str(out/'storefront-mobile.png'),full_page=True)
 admin=browser.new_page(viewport={'width':1440,'height':1000});admin.goto(BASE+'/admin');admin.fill('#password','test-admin-only');admin.click('#login button.primary');admin.wait_for_selector('#dashboard:visible');admin.screenshot(path=str(out/'storefront-admin.png'),full_page=True)
 # کل مسیر با دریافت صوت و ارسال خودکار؛ بدون دکمه ارسال متن
 voicepage=context.new_page();voicepage.goto(BASE);voicepage.wait_for_selector('.product');phone2='09'+str(uuid.uuid4().int)[:9]
 phrases=[phone2,'123456','مشتری مسیر صوتی','تهران','نشانی تست چهارده','بله','پرتقال دو کارتن','همین کافیه']
 for index,text in enumerate(phrases):
  control(text)
  before=voicepage.locator('.bubble').count()
  if index==0:voicepage.click('#heroStart')
  voicepage.wait_for_selector('#stopRecording:visible');voicepage.wait_for_timeout(350);voicepage.click('#stopRecording')
  voicepage.wait_for_function('(n)=>document.querySelectorAll(".bubble").length>n',arg=before)
  voicepage.wait_for_function('()=>!document.querySelector("#input").disabled')
 voicepage.wait_for_selector('#reviewDialog[open]');control('سفارش را تأیید می کنم');voicepage.click('#confirmByVoice')
 voicepage.wait_for_function('()=>document.querySelector("#confirmByVoice").textContent.includes("پایان ضبط")');voicepage.wait_for_timeout(350);voicepage.click('#confirmByVoice');voicepage.wait_for_selector('#successDialog[open]',timeout=15000)
 assert not errors,errors
 report={'iran_sans_loaded':True,'catalog_search_details_sort':True,'text_profile_and_cart':True,'voice_only_final_confirmation_with_quote_binding':True,'pdf_download':True,'all_voice_profile_to_order_without_send_button':True,'mobile_no_overflow_and_cart_drawer':True,'admin_direct_login':True,'javascript_errors':errors,'company_stt':'unverified; controlled HTTP fixture used','live_catalog':'unavailable'}
 (out/'storefront-browser-result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps(report,ensure_ascii=False));browser.close()
