"""بررسی اتصال STT روی همان سیستم کاربر؛ بدون ارسال صوت یا ثبت اطلاعات شخصی."""
import asyncio,json
from pathlib import Path
from dotenv import load_dotenv
from .stt import STTConfig,HTTPSTT
ROOT=Path(__file__).resolve().parents[1]
def main():
    load_dotenv(ROOT/'.env',override=False)
    report=asyncio.run(HTTPSTT(STTConfig.from_env()).diagnostics())
    target=ROOT/'data/stt-diagnostics.json';target.parent.mkdir(parents=True,exist_ok=True);target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(report['message']);print('گزارش بدون اطلاعات صوتی در data/stt-diagnostics.json ذخیره شد.')
if __name__=='__main__':main()
