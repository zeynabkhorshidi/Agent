"""Actual browser checks, using explicit demo data and a controlled STT HTTP fixture."""
import json,os
from pathlib import Path
from playwright.sync_api import sync_playwright
BASE=os.getenv('BASE_URL','http://127.0.0.1:8012')
OUT=Path('artifacts');OUT.mkdir(exist_ok=True)
with sync_playwright() as p:
 browser=p.chromium.launch(executable_path='/usr/bin/chromium',args=['--no-sandbox'])
 context=browser.new_context(viewport={'width':1440,'height':1000})
 page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
 page.goto(BASE);page.wait_for_selector('.product');page.evaluate('document.fonts.ready')
 assert page.locator('.product').count()==2
 assert page.locator('#demoNotice').is_visible()
 assert page.locator('.company-brand img').evaluate('(i)=>i.complete && i.naturalWidth>0')
 assert page.evaluate('document.fonts.check("14px IRANSansX")')
 page.screenshot(path=str(OUT/'agent-demo-desktop.png'),full_page=True)
 page.click('#textStart')
 def say(text):
  page.fill('#input',text)
  with page.expect_response(lambda r:'/api/turn' in r.url and r.request.method=='POST') as response:page.click('.send')
  assert response.value.status==200,response.value.text()
  page.wait_for_function('!document.querySelector("#input").disabled')
  return response.value.json()
 say('09120000001');assert page.request.get(BASE+'/api/session').json()['customer'] is None
 r=say('123456');assert r['state']['stage']=='address_confirm';assert r['state']['customer']['name']=='نیما راد'
 say('بله');r=say('سفارش قبلی');assert not r['state']['cart']['items']
 page.locator('#conversationChoices button',has_text='بله، اقلام قبلی').click()
 page.wait_for_selector('.cart-row');assert page.locator('.cart-row').count()==1
 say('همین کافیه');page.wait_for_selector('#reviewDialog[open]');page.check('#confirmCheck');page.click('#submitOrder');page.wait_for_selector('#successDialog[open]')
 with page.expect_download() as download:page.click('#receiptLink')
 download.value.save_as(OUT/'agent-demo-receipt.pdf');assert (OUT/'agent-demo-receipt.pdf').read_bytes().startswith(b'%PDF')
 order_id=page.locator('#orderNumber').inner_text().split(' · ')[0]
 page.click('#successClose');page.click('#ordersTab');page.wait_for_function('(id)=>document.querySelector("#orderList").textContent.includes(id)',arg=order_id)
 admin=browser.new_page(viewport={'width':1440,'height':1000});admin.on('pageerror',lambda e:errors.append(str(e)));admin.goto(BASE+'/admin')
 admin.fill('#password',os.getenv('TEST_ADMIN_PASSWORD','demo-preview-only'));admin.click('#login button.primary');admin.wait_for_selector('#dashboard:visible')
 admin.click('[data-section="customers"]');admin.wait_for_selector('.customer-card');assert admin.locator('.customer-card').count()==6
 admin.fill('#customerSearch','نیما');admin.locator('[data-customer="DEMO-C01"]').click();admin.wait_for_selector('#customerFile:visible');assert order_id in admin.locator('#customerFile').inner_text();assert 'سفارش قبلی' in admin.locator('.customer-dialogue').inner_text()
 admin.screenshot(path=str(OUT/'agent-customer-file.png'),full_page=True)
 mobile=context.new_page();mobile.set_viewport_size({'width':390,'height':844});mobile.goto(BASE);mobile.wait_for_selector('.product');assert mobile.evaluate('document.documentElement.scrollWidth<=innerWidth')
 mobile.screenshot(path=str(OUT/'agent-demo-mobile.png'),full_page=True)
 assert not errors,errors
 result=dict(returning_customer_no_profile_reentry=True,private_data_hidden_before_verification=True,reorder_requires_consent=True,order_and_pdf=True,customer_file_and_transcript=True,iran_sans_and_branding=True,mobile_no_overflow=True,javascript_errors=errors,live_company_connections='not verified; controlled fixtures only')
 (OUT/'agent-browser-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps(result,ensure_ascii=False));browser.close()
