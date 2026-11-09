"""Run on the company's permitted network; print only product/image counts."""
import asyncio,json
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[1]/'.env',override=False)
from . import db
from .catalog import CatalogSync

async def main():
    db.init()
    report=await CatalogSync().run()
    output=Path(db.PATH).parent/'catalog-sync-report.json'
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
    print('Report:',output)
    return 0 if report['state']=='ready' else 1

if __name__=='__main__':raise SystemExit(asyncio.run(main()))
