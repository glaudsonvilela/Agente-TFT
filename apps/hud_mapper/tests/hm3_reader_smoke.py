"""Native OCR on 1920x1080 pixels; optionally use only the compact package's tools."""
import argparse,json,os
from pathlib import Path
from e1.protocol import NativeWorker
from hm.runtime_app import runtime_paths


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True);parser.add_argument('--runtime-root')
    args=parser.parse_args();out=Path(args.output);out.mkdir(parents=True,exist_ok=False)
    paths=runtime_paths()
    old_path=os.environ.get('PATH','');old_tess=os.environ.get('TESSDATA_PREFIX')
    worker=None
    try:
        if args.runtime_root:
            root=Path(args.runtime_root).resolve(strict=True)
            paths=dict(worker=str(root/'bin/agente-tft-e1-worker.exe'),configs=str(root/'configs'),
                       tesseract=str(root/'tesseract/tesseract.exe'))
            os.environ['PATH']=str(Path(os.environ['SystemRoot'])/'System32')
            os.environ['TESSDATA_PREFIX']=str(root/'tesseract/tessdata')
        worker=NativeWorker(paths['worker'],paths['configs'],paths['tesseract'],log=out/'reader-stderr.log')
        assert worker.ready['ocr_available']
        raw=bytes(1920*1080*3)
        result=worker.request(dict(op='frame',id=7,source_ms=0,width=1920,height=1080,bytes=len(raw)),raw,timeout=20)
        assert result['id']==7 and result['origin']=='observed_pixels'
        assert len(result['hud'])==4 and all(row['value'] is None for row in result['hud'])
        assert any(row['stage']=='shop_cards' for row in result['spans'])
        (out/'reader-smoke.json').write_text(json.dumps(dict(execution_complete=True,ocr_available=True,
            private_package_only=bool(args.runtime_root),PATH_restricted=bool(args.runtime_root),
            hud_statuses=[row['status'] for row in result['hud']],spans=result['spans'],tft_accuracy_tested=False),indent=2),encoding='utf-8')
        print('HM3_READER_SMOKE_OK')
    finally:
        if worker:worker.close()
        os.environ['PATH']=old_path
        if old_tess is None:os.environ.pop('TESSDATA_PREFIX',None)
        else:os.environ['TESSDATA_PREFIX']=old_tess


if __name__=='__main__':main()
