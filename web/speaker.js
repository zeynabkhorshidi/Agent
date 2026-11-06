/* صدای سرورِ پیکربندی‌شده، یا صدای فارسی واقعی دستگاه با انتخاب کاربر. */
export class AssistantSpeaker{
 constructor(onStatus){this.onStatus=onStatus;this.generation=0;this.audio=null;this.abort=null;this.url=null;this.server=false;this.browserName='';this.finish=null;}
 voices(){return window.speechSynthesis?window.speechSynthesis.getVoices().filter(v=>/^fa(?:-|_|$)/i.test(v.lang)):[];}
 cancel(){++this.generation;this.abort?.abort();this.abort=null;this.audio?.pause();this.audio=null;if(this.url)URL.revokeObjectURL(this.url);this.url=null;if(window.speechSynthesis)speechSynthesis.cancel();if(this.finish){this.finish(false);this.finish=null;}this.onStatus('');}
 async speak(text){
  this.cancel();const gen=++this.generation;
  if(!text)return false;
  if(this.server){
   try{
    this.abort=new AbortController();this.onStatus('در حال آماده‌سازی صدای پاسخ…');
    const r=await fetch('/api/assistant/speak',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text}),signal:this.abort.signal});
    if(!r.ok)throw Error('سرویس صدا پاسخ نداد. متن پاسخ در گفت‌وگو محفوظ است.');
    const blob=await r.blob();if(gen!==this.generation)return false;
    this.url=URL.createObjectURL(blob);this.audio=new Audio(this.url);const audio=this.audio;
    return await new Promise(resolve=>{this.finish=resolve;audio.onended=()=>{if(gen===this.generation){this.finish=null;this.onStatus('');resolve(true);}};audio.onerror=()=>{this.finish=null;this.onStatus('پخش صدا ممکن نشد؛ متن را بخوانید.');resolve(false);};audio.play().then(()=>this.onStatus('دستیار در حال صحبت است…')).catch(()=>{this.finish=null;this.onStatus('مرورگر پخش را متوقف کرد؛ دکمه پخش پاسخ را بزنید.');resolve(false);});});
   }catch(e){if(gen===this.generation&&e.name!=='AbortError')this.onStatus(e.message);return false;}
  }
  const voice=this.voices().find(v=>v.name===this.browserName);
  if(!voice){this.onStatus('سرویس صدای پاسخ تنظیم نشده؛ پاسخ متنی در دسترس است.');return false;}
  return await new Promise(resolve=>{this.finish=resolve;const u=new SpeechSynthesisUtterance(text);u.lang=voice.lang;u.voice=voice;u.rate=1;u.onstart=()=>this.onStatus('پخش با صدای فارسی دستگاه…');u.onend=()=>{if(gen===this.generation){this.finish=null;this.onStatus('');resolve(true);}};u.onerror=()=>{this.finish=null;this.onStatus('پخش صدای دستگاه متوقف شد.');resolve(false);};speechSynthesis.speak(u);});
 }
}
