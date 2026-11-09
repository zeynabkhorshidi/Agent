"""Browser playback regression with an explicit WAV fixture, not a real TTS provider."""
import io,json,os,wave
from pathlib import Path
from playwright.sync_api import sync_playwright
out=io.BytesIO()
with wave.open(out,'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);w.writeframes(b'\0\0'*24000)
audio=out.getvalue();base=os.getenv('BASE_URL','http://127.0.0.1:8013')
with sync_playwright() as p:
 b=p.chromium.launch(executable_path='/usr/bin/chromium',args=['--no-sandbox']);page=b.new_page()
 page.add_init_script("""window.__played=false;window.__ended=false;window.__csp=[];const play=HTMLMediaElement.prototype.play;HTMLMediaElement.prototype.play=function(...args){this.addEventListener('playing',()=>window.__played=true);this.addEventListener('ended',()=>window.__ended=true);return play.apply(this,args)};document.addEventListener('securitypolicyviolation',e=>window.__csp.push(e.effectiveDirective));""")
 page.route('**/api/assistant/status',lambda r:r.fulfill(json={'server_tts':True,'browser_voice_optional':True}))
 page.route('**/api/assistant/speak',lambda r:r.fulfill(status=200,content_type='audio/wav',body=audio))
 page.goto(base);page.wait_for_function("()=>document.querySelector('#ttsStatus').textContent.includes('آماده')")
 page.click('#readLast');page.wait_for_function('()=>window.__ended===true',timeout=10000)
 assert page.evaluate('()=>window.__played');assert not page.evaluate('()=>window.__csp')
 report=dict(controlled_audio_received=True,blob_playback_started=True,playback_completed=True,csp_violations=[],real_tts_provider_tested=False)
 Path('artifacts').mkdir(exist_ok=True);Path('artifacts/voice-playback-result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps(report));b.close()
