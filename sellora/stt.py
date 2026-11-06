"""Adapter قرارداد HTTP فایل‌های ارائه‌شده سرویس Persian Speech-to-Text.
هیچ مدل صوتی در Sellora دانلود یا اجرا نمی‌شود؛ صوت فقط به سرویس شرکت می‌رود.
"""
import asyncio
import os
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, Field, ValidationError
from typing import Literal


class STTError(Exception):
    def __init__(self, code, message, status=502, retryable=False):
        self.code, self.message, self.status, self.retryable = code, message, status, retryable
        super().__init__(message)


class Transcript(BaseModel):
    text: str = Field(max_length=10000)
    language: Literal['fa'] = 'fa'
    engine: Literal['google_online', 'faster_whisper_offline']
    duration_seconds: float = Field(ge=0)
    processing_seconds: float = Field(ge=0)


@dataclass(frozen=True)
class STTConfig:
    base_url: str
    online_timeout: float = 45
    offline_timeout: float = 120
    max_bytes: int = 25 * 1024 * 1024
    cooldown: float = 30

    @classmethod
    def from_env(cls):
        return cls(os.getenv('STT_BASE_URL', '').strip().rstrip('/'),
                   float(os.getenv('STT_ONLINE_TIMEOUT', '45')),
                   float(os.getenv('STT_OFFLINE_TIMEOUT', '120')),
                   int(os.getenv('STT_MAX_UPLOAD_MB', '25')) * 1024 * 1024)

    def validate(self):
        if not self.base_url:
            raise STTError('not_configured', 'نشانی سرویس گفتار روی سرور تنظیم نشده است؛ متنی ادامه دهید.', 503)
        p = urlsplit(self.base_url)
        if p.scheme not in ('http', 'https') or not p.hostname or p.username or p.password or p.query or p.fragment:
            raise STTError('invalid_config', 'تنظیمات اتصال صوت نیازمند بررسی مدیر است.', 503)
        if self.online_timeout <= 0 or self.offline_timeout <= 0 or self.max_bytes <= 0:
            raise STTError('invalid_config', 'تنظیمات زمان یا حجم صوت معتبر نیست.', 503)


class HTTPSTT:
    """Circuit مستقل برای آنلاین و آفلاین؛ بدون retry روی گفتار نامفهوم.
    health وجود فایل مدل را گزارش می‌کند، نه موفقیت استنتاج یا سلامت Google.
    """
    def __init__(self, config: STTConfig, transport=None):
        self.config = config
        self.transport = transport
        self.failures = {'online': 0, 'offline': 0}
        self.open_until = {'online': 0.0, 'offline': 0.0}
        self.last_success = {'online': None, 'offline': None}
        self.last_error = {'online': None, 'offline': None}
        self.gates = {'online': asyncio.Semaphore(1), 'offline': asyncio.Semaphore(1)}

    def client(self, timeout):
        # پراکسی و TLS سیستم حفظ می‌شوند؛ redirect برای جلوگیری از ارسال صوت به مقصد دیگر ممنوع است.
        return httpx.AsyncClient(transport=self.transport, timeout=timeout, follow_redirects=False)

    async def health(self):
        if not self.config.base_url:
            return {'configured': False, 'reachable': False, 'message': 'نشانی سرویس گفتار تنظیم نشده است.'}
        try:self.config.validate()
        except STTError as e:return {'configured':True,'reachable':False,'message':e.message,'code':e.code}
        try:
            async with self.client(3) as client:
                r = await client.get(self.config.base_url + '/health')
            if r.status_code != 200:
                raise ValueError()
            b = r.json()
            if not isinstance(b, dict) or b.get('status') != 'ok':
                raise ValueError()
            return {'configured': True, 'reachable': True,
                    'offline_model_files_present': b.get('offline_model_files_present') is True,
                    'offline_model_loaded': b.get('offline_model_loaded') is True,
                    'message': 'ارتباط برقرار است؛ سلامت موتور آنلاین و صحت مدل فقط با تبدیل واقعی مشخص می‌شود.'}
        except (httpx.HTTPError, ValueError):
            return {'configured': True, 'reachable': False,
                    'message': 'از سرور فروش به سرویس گفتار دسترسی نداریم؛ شبکه شرکت و نشانی سرویس بررسی شود.'}

    async def diagnostics(self):
        report={'configured':bool(self.config.base_url),'checks':{},'message':'تنظیمات صدا بررسی شد.'}
        try:self.config.validate()
        except STTError as e:return dict(report,code=e.code,message=e.message)
        for name,path in [('health','/health'),('contract','/openapi.json')]:
            try:
                async with self.client(5) as client:r=await client.get(self.config.base_url+path)
                result={'http_status':r.status_code,'content_type':r.headers.get('content-type','')[:80]}
                if r.status_code==200:
                    try:body=r.json()
                    except ValueError:body=None
                    if name=='health':
                        result['valid']=isinstance(body,dict) and body.get('status')=='ok'
                        if isinstance(body,dict):
                            for key in ('offline_model_files_present','offline_model_loaded'):result[key]=body.get(key) is True
                    else:
                        paths=body.get('paths',{}) if isinstance(body,dict) else {}
                        result['online_route']='/api/v1/stt/online' in paths
                        result['offline_route']='/api/v1/stt/offline' in paths
                        result['valid']=result['online_route'] and result['offline_route']
                report['checks'][name]=result
            except httpx.TimeoutException:report['checks'][name]={'error':'timeout'}
            except httpx.ConnectError as e:report['checks'][name]={'error':'tls_verification' if 'CERTIFICATE_VERIFY_FAILED' in str(e) else 'connection'}
            except httpx.HTTPError:report['checks'][name]={'error':'network'}
        checks=report['checks']
        if any(c.get('http_status') in (401,403) for c in checks.values()):report.update(code='access_denied',message='دسترسی به سرویس گفتار رد شده؛ شبکه یا مجوز سرویس باید بررسی شود.')
        elif any(c.get('error')=='tls_verification' for c in checks.values()):report.update(code='tls_verification',message='گواهی اتصال به سرویس گفتار در این سیستم مورد اعتماد نیست.')
        elif any(c.get('error') for c in checks.values()):report.update(code='network',message='ارتباط با سرویس گفتار برقرار نیست؛ مسیر شبکه یا نشانی سرویس بررسی شود.')
        elif not checks.get('contract',{}).get('valid'):report.update(code='contract_mismatch',message='نشانی پاسخ می‌دهد اما قرارداد سرویس گفتار مورد انتظار در آن دیده نشد.')
        else:report.update(code='reachable',message='ارتباط و مسیرهای سرویس درست‌اند؛ تشخیص واقعی باید با یک فایل صوتی بررسی شود.')
        return report

    def status(self):
        return {'configured': bool(self.config.base_url), 'streaming': False, 'full_duplex': False,
                'tts': False, 'voices': [], 'upload_field': 'file',
                'online': {'circuit_open': self.open_until['online'] > time.monotonic(),
                           'last_success_utc': self.last_success['online'], 'last_error': self.last_error['online']},
                'offline': {'circuit_open': self.open_until['offline'] > time.monotonic(),
                            'last_success_utc': self.last_success['offline'], 'last_error': self.last_error['offline']}}

    async def transcribe(self, audio, filename, content_type, mode):
        self.config.validate()
        deadline=(self.config.online_timeout+self.config.offline_timeout if mode=='auto' else self.config.offline_timeout if mode=='offline' else self.config.online_timeout)+5
        try:return await asyncio.wait_for(self._dispatch(audio,filename,content_type,mode),deadline)
        except TimeoutError:raise STTError('timeout','دریافت متن طول کشید؛ دوباره ضبط کنید یا بنویسید.',504,True) from None

    async def _dispatch(self, audio, filename, content_type, mode):
        self.config.validate()
        if mode not in ('auto', 'online', 'offline'):
            raise STTError('invalid_mode', 'حالت صوت معتبر نیست.', 400)
        if len(audio) > self.config.max_bytes:
            raise STTError('too_large', 'حجم فایل صوتی بیش از حد مجاز است.', 413)
        if mode == 'offline':
            return await self._run('offline', audio, filename, content_type), False
        try:
            return await self._run('online', audio, filename, content_type), False
        except STTError as online:
            if mode == 'online' or not online.retryable:
                raise
            # تنها خرابی وابستگی/پروتکل باعث fallback می‌شود؛ سکوت یا فایل نامعتبر نه.
            try:
                return await self._run('offline', audio, filename, content_type), True
            except STTError as offline:
                if not offline.retryable:
                    raise
                raise STTError('all_unavailable', 'هیچ‌یک از مسیرهای گفتار پاسخ ندادند. سبد محفوظ است؛ متنی ادامه دهید.', 503) from None

    async def _run(self, mode, audio, filename, content_type):
        # بعد از cooldown فقط یک درخواست آزمایشی وارد مدار می‌شود.
        async with self.gates[mode]:
            if self.open_until[mode] > time.monotonic():
                raise STTError('circuit_open', 'سرویس گفتار موقتاً پاسخ نمی‌دهد. کمی بعد دوباره تلاش کنید.', 503, True)
            timeout = self.config.online_timeout if mode == 'online' else self.config.offline_timeout
            try:
                async with self.client(timeout) as client:
                    r = await client.post(self.config.base_url + '/api/v1/stt/' + mode,
                                          files={'file': (filename, audio, content_type)})
                if r.status_code != 200:
                    client_error = r.status_code in (400, 413, 422)
                    try:
                        code = r.json().get('error', {}).get('code', '')
                    except (ValueError, AttributeError):
                        code = ''
                    messages = {400: 'فایل صوتی خالی یا قالب آن نامعتبر است.',
                                413: 'حجم یا مدت صوت بیش از حد مجاز است؛ کوتاه‌تر ضبط کنید.',
                                422: 'گفتار قابل تشخیص نبود؛ دوباره ضبط کنید یا متنی بنویسید.',
                                401: 'مجوز دسترسی به سرویس گفتار نیازمند بررسی مدیر است.',
                                403: 'دسترسی سرور به سرویس گفتار مجاز نیست؛ مدیر شبکه بررسی کند.'}
                    safe_code = code if code in ('no_speech', 'unsupported_file', 'invalid_request') else 'upstream_error'
                    raise STTError(safe_code, messages.get(r.status_code, 'سرویس گفتار پاسخ معتبر نداد؛ متنی ادامه دهید.'),
                                   r.status_code if client_error else 502, not client_error and r.status_code not in (401, 403))
                try:
                    result = Transcript.model_validate(r.json())
                    expected = 'google_online' if mode == 'online' else 'faster_whisper_offline'
                    if result.engine != expected:
                        raise ValueError()
                except (ValueError, ValidationError):
                    raise STTError('invalid_response', 'پاسخ سرویس گفتار با قرارداد سازگار نیست.', 502, True) from None
                if not result.text.strip():
                    raise STTError('no_speech', 'گفتاری تشخیص داده نشد. دوباره ضبط کنید یا متنی ادامه دهید.', 422)
                if len(result.text.strip()) > 1500:
                    raise STTError('too_long', 'متن تشخیص‌داده‌شده طولانی است؛ گفتار را در چند نوبت کوتاه بفرستید.', 422)
                self.failures[mode] = 0
                self.open_until[mode] = 0
                self.last_error[mode] = None
                self.last_success[mode] = int(time.time())
                return result.model_copy(update={'text': result.text.strip()})
            except httpx.TimeoutException:
                error = STTError('timeout', 'پاسخ گفتار دیر رسید. می‌توانید دوباره ضبط کنید یا متنی ادامه دهید.', 504, True)
            except httpx.HTTPError:
                error = STTError('connection', 'ارتباط سرور با سرویس گفتار برقرار نیست. متنی ادامه دهید.', 503, True)
            except STTError as exc:
                error = exc
            self.last_error[mode] = error.code
            if error.retryable:
                self.failures[mode] += 1
                if self.failures[mode] >= 2:
                    self.open_until[mode] = time.monotonic() + self.config.cooldown
            raise error
