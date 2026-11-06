"""نسخه عادی بدون نمونه؛ آزمون صوت در سرور جدا با fixture صریح اجرا می‌شود."""
import json,os,httpx
from pathlib import Path
from playwright.sync_api import sync_playwright
out=Path('artifacts');out.mkdir(exist_ok=True)
with sync_playwright() as p:
 browser=p.chromium.launch(executable_path='/usr/bin/chromium',args=['--no-sandbox','--use-fake-device-for-media-stream','--use-fake-ui-for-media-stream'])
 normal=browser.new_page(viewport={'width':1440,'height':1000});errors=[];normal.on('pageerror',lambda e:errors.append(str(e)))
 normal.goto('http://127.0.0.1:8011');normal.wait_for_selector('#catalog .empty');normal.evaluate('()=>document.fonts.ready')
 text=normal.locator('body').inner_text()
 assert 'حبوبات' not in text and 'عکس مرجع' not in text and 'داده آزمایشی' not in text and 'نسخه توسعه' not in text
 assert normal.locator('.product').count()==0;assert normal.locator('#heroImage').is_hidden();assert normal.locator('#heroFallback').inner_text()=='سن‌ایچ'
 normal.screenshot(path=str(out/'catalog-only-desktop.png'),full_page=True)
 mobile=browser.new_page(viewport={'width':390,'height':844});mobile.goto('http://127.0.0.1:8011');mobile.wait_for_selector('#catalog .empty');assert mobile.evaluate('document.documentElement.scrollWidth<=innerWidth');mobile.screenshot(path=str(out/'catalog-only-mobile.png'),full_page=True)
 # داده آزمون فقط در سرویس 8010 تزریق شده و در اجرای عادی وجود ندارد.
 ctx=browser.new_context(permissions=['microphone']);page=ctx.new_page();page.on('pageerror',lambda e:errors.append(str(e)));requests=[]
 def request(req):
  if req.url.endswith('/api/voice/transcribe'):
   raw=req.post_data_buffer or b'';idx=raw.find(b'RIFF')
   if idx>=0:requests.append({'wav':True,'channels':int.from_bytes(raw[idx+22:idx+24],'little'),'sample_rate':int.from_bytes(raw[idx+24:idx+28],'little'),'bits':int.from_bytes(raw[idx+34:idx+36],'little')})
 page.on('request',request);page.goto('http://127.0.0.1:8010');page.wait_for_selector('.product');page.click('#mic');page.wait_for_selector('#stopRecording:visible');page.wait_for_timeout(700);page.click('#stopRecording');page.wait_for_function('()=>document.querySelector("#input").value.length>0',timeout=15000)
 received=httpx.get('http://127.0.0.1:8134/_test/last-audio').json();print('Received audio metadata',received);assert received['wav'] and received['channels']==1 and received['sample_rate']==16000 and received['bits']==16,received
 # حالت کم‌صدا نباید ضبط را بعد از ده ثانیه دور بریزد.
 quiet=ctx.new_page();quiet.clock.install()
 quiet.add_init_script("""window.AudioContext=class {constructor(){this.state='running'} createMediaStreamSource(){return {connect(){}}} createAnalyser(){return {fftSize:1024,getByteTimeDomainData(a){a.fill(128)}}} close(){this.state='closed';return Promise.resolve()} resume(){return Promise.resolve()}}""")
 quiet.goto('http://127.0.0.1:8010');quiet.wait_for_selector('.product');quiet.click('#mic');quiet.wait_for_selector('#stopRecording:visible');quiet.clock.fast_forward(11000);assert quiet.locator('#stopRecording').is_visible();quiet.click('#cancelVoice');assert quiet.locator('#stopRecording').is_hidden()
 assert not errors,errors
 report={'normal_store_has_no_demo_products':True,'unrelated_photos_removed':True,'sunich_real_photo_not_fabricated':True,'no_developer_footer':True,'microphone_sent_pcm_wav_16khz_mono':True,'quiet_recording_not_discarded':True,'mobile_overflow':False,'javascript_errors':errors,'real_catalog_and_stt':'blocked from build environment; not validated'}
 (out/'catalog-voice-browser-result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps(report,ensure_ascii=False));browser.close()
