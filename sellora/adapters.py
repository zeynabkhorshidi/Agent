"""قراردادهای توسعه؛ Adapter اجرایی STT با مسیرهای مستند در stt.py و voice_api.py قرار دارد."""
from typing import Protocol, AsyncIterator
from dataclasses import dataclass
import asyncio, time

@dataclass
class AudioCapabilities:
    connected: bool = False
    streaming: bool = False
    duplex: bool = False
    voices: tuple = ()

class VoiceAdapter(Protocol):
    async def capabilities(self) -> AudioCapabilities: ...
    async def transcribe(self, audio: bytes, turn_id: str) -> str: ...
    async def synthesize(self, text: str, voice: str, turn_id: str) -> AsyncIterator[bytes]: ...
    async def cancel(self, turn_id: str) -> None: ...

class UnconfiguredVoice:
    async def capabilities(self): return AudioCapabilities()
    async def transcribe(self, audio, turn_id): raise ConnectionError('قرارداد سرویس صوت تنظیم نشده است')
    async def synthesize(self, text, voice, turn_id): raise ConnectionError('قرارداد سرویس صوت تنظیم نشده است')
    async def cancel(self, turn_id): pass

class MockVoice(UnconfiguredVoice):
    """فقط برای آزمون هماهنگ‌کننده؛ هرگز به عنوان تشخیص صوت واقعی عرضه نشود."""
    async def capabilities(self): return AudioCapabilities(connected=True)
    async def transcribe(self, audio, turn_id): return audio.decode('utf-8')

class Circuit:
    def __init__(self, adapter, timeout=3, cooldown=30):
        self.adapter, self.timeout, self.cooldown = adapter, timeout, cooldown
        self.failures, self.open_until = 0, 0
    async def call(self, method, *args):
        if time.monotonic() < self.open_until: raise ConnectionError('مدار موقتاً باز است')
        try:
            result = await asyncio.wait_for(getattr(self.adapter, method)(*args), self.timeout)
            self.failures = 0
            return result
        except (TimeoutError, ConnectionError):
            self.failures += 1
            if self.failures >= 2: self.open_until = time.monotonic() + self.cooldown
            raise

class VoiceRouter:
    def __init__(self, online, offline): self.online, self.offline = Circuit(online), Circuit(offline)
    async def transcribe(self, audio, turn_id, mode='auto'):
        if mode not in ('auto','online','offline'): raise ValueError('حالت نامعتبر')
        if mode == 'offline': return await self.offline.call('transcribe',audio,turn_id)
        try: return await self.online.call('transcribe',audio,turn_id)
        except (TimeoutError,ConnectionError):
            if mode == 'online': raise
            return await self.offline.call('transcribe',audio,turn_id)

class TelephonyAdapter(Protocol):
    """رویدادهای call.started/audio/final/barge_in/ended با call_id و turn_id؛
    Caller ID تنها سرنخ است. codec و DTMF تابع قرارداد استقرار شرکت هستند."""
    async def send_audio(self, call_id: str, frame: bytes, turn_id: str): ...
    async def cancel(self, call_id: str, turn_id: str): ...
    async def request_transfer(self, call_id: str, context_id: str) -> bool: ...

class CustomerSource(Protocol):
    def lookup_verified(self, customer_id: str): ...
class OTPProvider(Protocol):
    def send(self, mobile: str): ...
    def verify(self, mobile: str, code: str) -> bool: ...
class CatalogSource(Protocol):
    def products(self) -> list[dict]: ...
class CommercialSource(Protocol):
    def quote(self, items: dict) -> dict: ...
class OrderSource(Protocol):
    def submit(self, quote: dict, idempotency_key: str) -> dict: ...
class LanguageModel(Protocol):
    async def propose(self, text: str, context: dict) -> dict: ...
