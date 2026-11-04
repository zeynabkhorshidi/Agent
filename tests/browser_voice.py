"""آزمون واقعی MediaRecorder/HTTP، با STT کنترل‌شده؛ دقت تشخیص گفتار را نمی‌سنجد.
سرور fixture روی 8134 و برنامه با STT_BASE_URL آن روی 8010 روشن باشند.
"""
import json,os,time,uuid
from pathlib import Path
import httpx
from playwright.sync_api import sync_playwright
BASE=os.getenv('BASE_URL','http://127.0.0.1:8010')
FIXTURE=os.getenv('STT_FIXTURE','http://127.0.0.1:8134')
out=Path('artifacts');out.mkdir(exist_ok=True)

def control(**kw):
    r=httpx.post(FIXTURE+'/_test/control',json=kw);r.raise_for_status()

with sync_playwright() as p:
    browser=p.chromium.launch(executable_path=os.getenv('CHROMIUM_PATH','/usr/bin/chromium'),args=['--no-sandbox','--use-fake-device-for-media-stream','--use-fake-ui-for-media-stream'],headless=True)
    context=browser.new_context(permissions=['microphone'],viewport={'width':1440,'height':1100})
    page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto(BASE);page.wait_for_selector('.product')
    page.wait_for_function("()=>document.querySelector('#voiceConnection').textContent.includes('ارتباط برقرار')")
    voice_ms=[]
    phrases=['09'+str(uuid.uuid4().int)[:9],'123456','مشتری تست صوت','تهران','نشانی آزمایشی پلاک دوازده','بله','پرتقال دو کارتن و انبه سه کارتن']
    for i,phrase in enumerate(phrases):
        control(text=phrase)
        before=page.locator('.bubble').count()
        page.click('#mic');page.wait_for_selector('#stopRecording:visible');page.wait_for_timeout(400)
        t=time.perf_counter();page.click('#stopRecording');page.wait_for_function('(s)=>document.querySelector("#input").value===s',arg=phrase)
        voice_ms.append(round((time.perf_counter()-t)*1000,2))
        # نتیجه تبدیل به تنهایی گفت‌وگو یا سبد را تغییر نمی‌دهد.
        if i==6:assert page.locator('.cart-row').count()==0
        page.click('.send');page.wait_for_function('()=>!document.querySelector("#input").disabled')
        if i>0:assert page.locator('.bubble').count()>before
    assert page.locator('.cart-row').count()==2
    # آفلاین بعد از خطای واقعی HTTP در fixture
    control(text='نه پرتقال رو سه کارتن کن و انبه رو حذف کن',online_status=502)
    page.set_input_files('#audioFile',{'name':'sample.wav','mimeType':'audio/wav','buffer':b'RIFF-controlled-test-audio'})
    page.wait_for_function("()=>document.querySelector('#input').value.includes('نه پرتقال')")
    assert 'مسیر جایگزین' in page.locator('#voiceConnection').inner_text()
    page.click('.send');page.wait_for_function('()=>!document.querySelector("#input").disabled');assert page.locator('.cart-row').count()==1
    # لغو در میانه ضبط و جلوگیری از ارسال
    page.click('#mic');page.wait_for_selector('#stopRecording:visible');page.click('#cancelVoice');assert page.locator('#stopRecording').is_hidden()
    # نتیجه دیررس پس از لغو، متن جدید را بازنویسی نمی‌کند.
    control(text='پاسخ قدیمی',delay=0.8)
    page.set_input_files('#audioFile',{'name':'sample.wav','mimeType':'audio/wav','buffer':b'RIFF-controlled-test-audio'})
    page.wait_for_selector('#cancelVoice:visible');page.wait_for_timeout(200);page.click('#cancelVoice');page.fill('#input','متن تازه مشتری')
    page.wait_for_timeout(1300);assert page.input_value('#input')=='متن تازه مشتری'
    # متن تایپ‌شده هم‌زمان با تبدیل به‌صورت خودکار بازنویسی نمی‌شود.
    control(text='متن گفتار تازه',delay=0.4)
    page.fill('#input','پیش‌نویس تایپی مشتری')
    page.set_input_files('#audioFile',{'name':'sample.wav','mimeType':'audio/wav','buffer':b'RIFF-controlled-test-audio'})
    page.wait_for_selector('#transcriptConflict:visible');assert page.input_value('#input')=='پیش‌نویس تایپی مشتری'
    assert page.locator('#recognizedText').inner_text()=='متن گفتار تازه';page.click('#dismissTranscript')
    page.fill('#input','');page.click('#review');page.check('#confirmCheck');page.click('#submitOrder');page.wait_for_selector('#successDialog[open]')
    with page.expect_download() as dl:page.click('#receiptLink')
    dl.value.save_as(out/'voice-order-receipt.pdf');assert (out/'voice-order-receipt.pdf').read_bytes().startswith(b'%PDF')
    page.click('#successClose');page.screenshot(path=str(out/'voice-desktop.png'),full_page=True)
    # مجوز میکروفون رد شده: مسیر متن و بارگذاری حفظ می‌شود.
    denied=browser.new_context(permissions=[]);denied.grant_permissions([])
    denied_page=denied.new_page();denied_page.goto(BASE);denied_page.wait_for_selector('.product')
    denied_page.add_init_script("Object.defineProperty(navigator.mediaDevices,'getUserMedia',{value:()=>Promise.reject(new DOMException('denied','NotAllowedError'))})")
    denied_page.reload();denied_page.wait_for_selector('.product');denied_page.click('#mic');denied_page.wait_for_selector('#voiceError:visible');assert 'اجازه میکروفون' in denied_page.locator('#voiceError').inner_text()
    denied_page.fill('#input','09121111111');denied_page.click('.send');denied_page.wait_for_function('()=>!document.querySelector("#input").disabled')
    mobile=context.new_page();mobile.set_viewport_size({'width':390,'height':844});mobile.goto(BASE);mobile.wait_for_selector('.product');assert mobile.evaluate('document.documentElement.scrollWidth<=innerWidth');mobile.screenshot(path=str(out/'voice-mobile.png'),full_page=True)
    assert not errors,errors
    report={'microphone_recording':'passed (synthetic browser device)','multipart_http':'passed (controlled STT fixture)', 'order_and_pdf':'passed','fallback':'passed (502 online / 200 offline)','late_response_cancel':'passed','typed_text_preserved':'passed','microphone_denied_text_fallback':'passed','javascript_errors':errors,'mobile_overflow':False,'stop_to_text_ms':voice_ms,'real_company_stt':'not tested; network 403'}
    (out/'voice-browser-result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps(report,ensure_ascii=False));browser.close()
