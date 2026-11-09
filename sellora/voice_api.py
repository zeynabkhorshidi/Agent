"""کانال صوت فقط متن پیشنهادی می‌دهد؛ هرگز سبد یا سفارش را تغییر نمی‌دهد."""
import hashlib
import json
import re
import time
import uuid
from pathlib import Path
from fastapi import Request, UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse
from . import db
from .stt import STTError

EXTENSIONS = {'.wav', '.mp3', '.m4a', '.mp4', '.ogg', '.opus', '.flac', '.webm'}


def register_voice(app, sid, load):
    @app.get('/api/voice/status')
    async def voice_status(request: Request):
        with db.connect() as c:
            load(c, sid(request))
            settings = json.loads(c.execute('SELECT data FROM settings WHERE id=1').fetchone()[0])
        service = request.app.state.stt
        health = await service.health()
        return dict(**service.status(), health=health, mode=settings['mode'],
                    max_upload_bytes=service.config.max_bytes, recording_limit_seconds=50,request_timeout_seconds=service.config.online_timeout+service.config.offline_timeout+15,
                    note='تبدیل گفتار پس از پایان ضبط انجام می‌شود.')

    @app.post('/api/voice/transcribe')
    async def transcribe(request: Request, file: UploadFile = File(...), turn_id: str = Form(...), quote_id: str = Form('')):
        value = sid(request)
        # نشست پیش از خواندن و ارسال فایل کنترل می‌شود.
        with db.connect() as c:
            load(c, value)
            settings = json.loads(c.execute('SELECT data FROM settings WHERE id=1').fetchone()[0])
            if quote_id and not c.execute('SELECT 1 FROM quotes WHERE id=? AND session_id=? AND expires>?',(quote_id,value,int(time.time()))).fetchone():
                await file.close()
                raise HTTPException(409,'مرور سفارش تغییر کرده یا منقضی شده است.')
        if not re.fullmatch(r'[A-Za-z0-9_-]{8,100}', turn_id):
            await file.close()
            raise HTTPException(400, 'شناسه نوبت صوت معتبر نیست.')
        suffix = Path(file.filename or '').suffix.lower()
        if suffix not in EXTENSIONS:
            await file.close()
            raise HTTPException(400, 'فایل WAV، MP3، M4A، MP4، OGG، OPUS، FLAC یا WEBM انتخاب کنید.')
        service = request.app.state.stt
        audio = bytearray()
        try:
            while chunk := await file.read(65536):
                audio.extend(chunk)
                if len(audio) > service.config.max_bytes:
                    raise HTTPException(413, 'فایل صوتی بیش از حد مجاز است.')
        finally:
            await file.close()
        if not audio:
            raise HTTPException(400, 'فایل صوتی خالی است.')
        # نام اصلی فایل و متن گفتار وارد لاگ یا fingerprint نمی‌شوند.
        fingerprint = hashlib.sha256(bytes(audio) + settings['mode'].encode() + quote_id.encode()).hexdigest()
        now = int(time.time())
        with db.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            c.execute('DELETE FROM voice_requests WHERE created<?', (now - 600,))
            load(c, value)
            old = c.execute('SELECT * FROM voice_requests WHERE session_id=? AND turn_id=?', (value, turn_id)).fetchone()
            if old:
                if old['status'] == 'cancelled':
                    raise HTTPException(409, 'این نوبت لغو شده است. دوباره ضبط کنید.')
                if old['fingerprint'] != fingerprint:
                    raise HTTPException(409, 'این نوبت قبلاً برای صوت دیگری استفاده شده است.')
                if old['status'] == 'done':
                    return dict(json.loads(old['result']), duplicate=True)
                if old['status'] == 'cancelled':
                    raise HTTPException(409, 'این نوبت لغو شده است. دوباره ضبط کنید.')
                raise HTTPException(409, 'این نوبت قبلاً پردازش شده یا در حال پردازش است؛ برای تلاش تازه دوباره ضبط کنید.')
            running = c.execute("SELECT count(*) FROM voice_requests WHERE status='processing' AND created>?", (now - 180,)).fetchone()[0]
            recent = c.execute('SELECT count(*) FROM voice_requests WHERE session_id=? AND created>?', (value, now - 60)).fetchone()[0]
            if running >= 4 or recent >= 10:
                raise HTTPException(429, 'درخواست‌های صوت زیاد است. کمی صبر کنید یا متنی ادامه دهید.')
            c.execute('INSERT INTO voice_requests VALUES(?,?,?,?,?,?)', (value, turn_id, fingerprint, 'processing', None, now))
            c.commit()
        started = time.perf_counter()
        try:
            result, fallback = await service.transcribe(bytes(audio), 'voice' + suffix,
                                                         file.content_type or 'application/octet-stream', settings['mode'])
            payload = dict(turn_id=turn_id, quote_id=quote_id or None, text=result.text, engine=result.engine,
                           language=result.language, duration_seconds=result.duration_seconds,
                           processing_seconds=result.processing_seconds, fallback=fallback,
                           elapsed_ms=round((time.perf_counter() - started) * 1000, 2))
            with db.connect() as c:
                c.execute('BEGIN IMMEDIATE')
                load(c, value)  # خروج مشتری در حین پردازش، افشای نتیجه را متوقف می‌کند.
                changed = c.execute("UPDATE voice_requests SET status='done',result=? WHERE session_id=? AND turn_id=? AND status='processing'",
                                    (json.dumps(payload), value, turn_id)).rowcount
                if not changed:
                    raise HTTPException(409, 'این نوبت لغو شده است؛ پاسخ قدیمی کنار گذاشته شد.')
                db.audit(c, value, 'voice.completed', {k: payload[k] for k in ('turn_id','engine','fallback','elapsed_ms')})
                c.commit()
            return payload
        except STTError as exc:
            incident_id=uuid.uuid4().hex[:16]
            with db.connect() as c:
                c.execute("UPDATE voice_requests SET status='failed',result=NULL WHERE session_id=? AND turn_id=? AND status='processing'", (value, turn_id))
                db.audit(c, value, 'voice.failed', {'turn_id': turn_id, 'code': exc.code,'incident_id':incident_id,'causes':exc.details})
            return JSONResponse({'detail':exc.message,'code':exc.code,'incident_id':incident_id},status_code=exc.status)
        finally:
            audio.clear()

    @app.post('/api/voice/cancel/{turn_id}')
    async def cancel_voice(turn_id: str, request: Request):
        value = sid(request)
        if not re.fullmatch(r'[A-Za-z0-9_-]{8,100}', turn_id):
            raise HTTPException(400, 'شناسه نوبت معتبر نیست.')
        with db.connect() as c:
            load(c, value)
            # قرارداد بالادستی cancel ندارد؛ فقط نتیجه محلی باطل می‌شود.
            c.execute("INSERT INTO voice_requests VALUES(?,?,?,'cancelled',NULL,?) ON CONFLICT(session_id,turn_id) DO UPDATE SET status='cancelled',result=NULL", (value, turn_id, '', int(time.time())))
        return {'cancelled': True, 'upstream_cancel_supported': False}
