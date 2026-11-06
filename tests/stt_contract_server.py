"""سرویس کنترل‌شده آزمون قرارداد؛ تشخیص گفتار نیست و در برنامه اصلی استفاده نمی‌شود.
اجرای محلی: uvicorn tests.stt_contract_server:app --host 127.0.0.1 --port 8134
"""
import asyncio
from fastapi import FastAPI, File, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel

app=FastAPI(title='STT contract fixture — NOT a recognition engine')
last_audio={}
config={'text':'پرتقال دو کارتن','online_status':200,'delay':0}
class Control(BaseModel):
    text:str='پرتقال دو کارتن'
    online_status:int=200
    delay:float=0
@app.post('/_test/control')
def control(body:Control):config.update(body.model_dump());return {'ok':True}
@app.get('/health')
def health():return {'status':'ok','offline_model_files_present':True,'offline_model_loaded':False}
@app.get('/_test/last-audio')
def last_audio_info():return last_audio
async def transcript(file,mode):
    name=file.filename
    data=await file.read();await file.close()
    last_audio.clear();last_audio.update(filename=name,size=len(data),wav=data[:4]==b'RIFF' and data[8:12]==b'WAVE')
    if last_audio['wav']:last_audio.update(channels=int.from_bytes(data[22:24],'little'),sample_rate=int.from_bytes(data[24:28],'little'),bits=int.from_bytes(data[34:36],'little'))
    if not data:return JSONResponse({'error':{'code':'empty_audio','message':'empty'}},400)
    await asyncio.sleep(config['delay'])
    if mode=='online' and config['online_status']!=200:return JSONResponse({'error':{'code':'online_unavailable','message':'controlled fixture'}},config['online_status'])
    return {'text':config['text'],'language':'fa','engine':'google_online' if mode=='online' else 'faster_whisper_offline','duration_seconds':1.0,'processing_seconds':config['delay'],'segments':[]}
@app.post('/api/v1/stt/online')
async def online(file:UploadFile=File(...)):return await transcript(file,'online')
@app.post('/api/v1/stt/offline')
async def offline(file:UploadFile=File(...)):return await transcript(file,'offline')
