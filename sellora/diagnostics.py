"""بررسی اتصال STT روی همان سیستم کاربر؛ بدون ارسال صوت یا ثبت اطلاعات شخصی."""
import argparse,asyncio,json
from pathlib import Path
from dotenv import load_dotenv
from .stt import STTConfig,HTTPSTT,STTError
ROOT=Path(__file__).resolve().parents[1]
async def diagnose(config,audio_path=None):
    service=HTTPSTT(config)
    report=await service.diagnostics()
    if audio_path:
        path=Path(audio_path)
        allowed={'.wav','.mp3','.m4a','.mp4','.ogg','.opus','.flac','.webm'}
        if path.suffix.lower() not in allowed:raise ValueError('قالب فایل آزمون صوت پشتیبانی نمی‌شود.')
        if not path.is_file() or path.stat().st_size>config.max_bytes:raise ValueError('فایل آزمون موجود نیست یا حجمش بیش از حد مجاز است.')
        audio=path.read_bytes()
        if not audio:raise ValueError('فایل آزمون صوت خالی است.')
        report['inference_checks']={}
        # Explicit --audio is consent to process the selected test file, never to retain it.
        for mode in ('online','offline'):
            try:
                result,_=await service.transcribe(audio,'voice'+path.suffix.lower(),'application/octet-stream',mode)
                report['inference_checks'][mode]={'success':True,'engine':result.engine,'text_characters':len(result.text),'duration_seconds':result.duration_seconds,'processing_seconds':result.processing_seconds}
            except STTError as exc:report['inference_checks'][mode]={'success':False,'code':exc.code,'details':exc.details}
        report['inference_verified']=any(r['success'] for r in report['inference_checks'].values())
        del audio
    return report

def main():
    parser=argparse.ArgumentParser(description='بررسی اتصال واقعی Sellora به سرویس STT، بدون ذخیره صوت یا متن تشخیص')
    parser.add_argument('--audio',help='فایل صوت آزمایشی انتخابی شما؛ به هر دو مسیر مستند سرویس ارسال می‌شود')
    args=parser.parse_args()
    load_dotenv(ROOT/'.env',override=False)
    try:report=asyncio.run(diagnose(STTConfig.from_env(),args.audio))
    except (ValueError,OSError):print('فایل یا تنظیمات آزمون معتبر نیست؛ نشانی سرویس و مسیر فایل را بررسی کنید.');return 1
    target=ROOT/'data/stt-diagnostics.json';target.parent.mkdir(parents=True,exist_ok=True);target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2));print('گزارش بدون فایل صوت و متن تشخیص در data/stt-diagnostics.json ذخیره شد.')
    return 0 if report.get('code')=='reachable' and (not args.audio or report['inference_verified']) else 1
if __name__=='__main__':raise SystemExit(main())
