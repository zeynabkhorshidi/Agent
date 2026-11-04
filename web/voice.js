/* دریافت گفتار فقط از STT شرکت؛ هیچ Web Speech API یا TTS جایگزین به کار نمی‌رود. */
export class VoiceController {
  constructor({onDraft,onStatus,onError,canStart}) {
    Object.assign(this,{onDraft,onStatus,onError,canStart});
    this.generation=0;this.recorder=null;this.stream=null;this.controller=null;this.turnId=null;
    this.state='idle';this.chunks=[];this.timer=null;this.limitTimer=null;this.limit=50;this.maxBytes=25*1024*1024;
  }
  setState(state,label){this.state=state;this.onStatus(state,label);}
  async status(){
    const r=await fetch('/api/voice/status');
    const b=await r.json();if(!r.ok)throw Error(b.detail||'وضعیت صوت دریافت نشد.');
    this.maxBytes=b.max_upload_bytes;this.limit=b.recording_limit_seconds;
    return b;
  }
  stopTracks(){this.stream?.getTracks().forEach(t=>t.stop());this.stream=null;clearInterval(this.timer);clearTimeout(this.limitTimer);}
  async start(deviceId=''){
    if(!this.canStart()){this.onError('منتظر پایان نوبت فعلی بمانید.');return;}
    this.cancel();const generation=++this.generation;
    this.setState('requesting','در انتظار اجازه میکروفون');
    try{
      if(!window.isSecureContext||!navigator.mediaDevices?.getUserMedia)throw Error('برای میکروفون، صفحه را روی localhost یا HTTPS باز کنید. بارگذاری فایل و متن در دسترس است.');
      if(!window.MediaRecorder)throw Error('این مرورگر ضبط صوت را پشتیبانی نمی‌کند؛ فایل صوتی بارگذاری کنید.');
      const settings=await this.status();if(generation!==this.generation)return;
      if(!settings.configured)throw Error('نشانی سرویس گفتار روی سرور تنظیم نشده است؛ راهنمای اتصال را بررسی کنید.');
      // بررسی قابلیت شبکه جدا از مجوز کاربر است؛ فایل صوت تا اقدام او تولید نمی‌شود.
      const stream=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true,autoGainControl:true,...(deviceId?{deviceId:{exact:deviceId}}:{})}});
      if(generation!==this.generation){stream.getTracks().forEach(t=>t.stop());return;}
      this.stream=stream;
      const mime=['audio/webm;codecs=opus','audio/ogg;codecs=opus','audio/mp4'].find(t=>MediaRecorder.isTypeSupported(t));
      const recorder=new MediaRecorder(stream,mime?{mimeType:mime}:{});this.recorder=recorder;this.chunks=[];
      let size=0;
      recorder.ondataavailable=e=>{if(generation===this.generation&&e.data.size){size+=e.data.size;if(size>this.maxBytes){this.cancel();this.onError('حجم ضبط بیش از حد مجاز شد؛ کوتاه‌تر صحبت کنید.');return;}this.chunks.push(e.data);}};
      recorder.onerror=()=>{if(generation===this.generation){this.cancel();this.onError('ضبط صدا قطع شد؛ دوباره تلاش کنید یا متنی ادامه دهید.');}};
      recorder.onstop=()=>{
        if(generation!==this.generation)return;this.stopTracks();
        const blob=new Blob(this.chunks,{type:recorder.mimeType||'audio/webm'});this.chunks=[];this.recorder=null;
        if(!blob.size){this.setState('idle','آماده');this.onError('صدایی ضبط نشد.');return;}
        const ext=blob.type.includes('mp4')?'m4a':blob.type.includes('ogg')?'ogg':'webm';
        this.upload(blob,'voice.'+ext,generation);
      };
      recorder.start(250);this.started=Date.now();this.setState('recording','در حال ضبط · ۰ ثانیه');
      this.timer=setInterval(()=>{if(generation===this.generation)this.setState('recording','در حال ضبط · '+new Intl.NumberFormat('fa-IR').format(Math.floor((Date.now()-this.started)/1000))+' ثانیه');},1000);
      this.limitTimer=setTimeout(()=>this.stop(),this.limit*1000);
      return true;
    }catch(e){if(generation!==this.generation)return;this.stopTracks();this.setState('idle','ورود متنی آماده');
      const errors={NotAllowedError:'اجازه میکروفون داده نشد؛ از تنظیمات مرورگر مجاز کنید یا فایل و متن بفرستید.',NotFoundError:'میکروفونی پیدا نشد؛ فایل صوتی یا متن بفرستید.',NotReadableError:'میکروفون در اختیار برنامه دیگری است یا قابل دسترسی نیست.'};this.onError(errors[e.name]||e.message||'شروع ضبط ممکن نشد.');}
  }
  stop(){if(this.recorder?.state==='recording'){this.setState('processing','پایان ضبط؛ در حال ارسال');this.recorder.stop();}}
  async fromFile(file){
    if(!file||!this.canStart())return;
    this.cancel();const generation=++this.generation;
    try{const settings=await this.status();if(generation!==this.generation)return;if(!settings.configured)throw Error('نشانی سرویس گفتار تنظیم نشده است.');if(file.size>this.maxBytes)throw Error('حجم فایل بیش از حد مجاز است.');await this.upload(file,file.name,generation);}catch(e){if(generation===this.generation){this.setState('idle','ورود متنی آماده');this.onError(e.message);}}
  }
  async upload(blob,filename,generation){
    if(generation!==this.generation)return;
    this.setState('processing','در حال تبدیل گفتار به متن');
    this.turnId=crypto.randomUUID();const turnId=this.turnId;
    this.controller=new AbortController();const form=new FormData();form.append('file',blob,filename);form.append('turn_id',turnId);
    try{
      const r=await fetch('/api/voice/transcribe',{method:'POST',body:form,signal:this.controller.signal});const b=await r.json();
      if(generation!==this.generation)return;
      if(!r.ok)throw Error(typeof b.detail==='string'?b.detail:'تبدیل گفتار انجام نشد. فایل دیگری امتحان کنید یا متنی ادامه دهید.');
      if(b.turn_id!==turnId)return;
      this.onDraft(b);this.setState('draft','متن آماده بررسی شماست');
    }catch(e){if(generation!==this.generation||e.name==='AbortError')return;this.setState('idle','ورود متنی آماده');this.onError(e instanceof TypeError?'ارتباط با سرور قطع شد؛ سبد محفوظ است. دوباره تلاش کنید یا متنی ادامه دهید.':e.message);}
    finally{if(generation===this.generation){this.controller=null;this.turnId=null;}}
  }
  cancel(){
    ++this.generation;this.controller?.abort();this.controller=null;
    if(this.turnId){fetch('/api/voice/cancel/'+encodeURIComponent(this.turnId),{method:'POST'}).catch(()=>{});this.turnId=null;}
    if(this.recorder){this.recorder.onstop=null;this.recorder.ondataavailable=null;this.recorder.onerror=null;if(this.recorder.state!=='inactive')this.recorder.stop();}
    this.recorder=null;this.chunks=[];this.stopTracks();this.setState('idle','ورود متنی آماده');
  }
}
