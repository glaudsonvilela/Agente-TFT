"""Actual ONNX/native/PNG/trainer integration on generated fixtures; not TFT accuracy."""
import argparse,json,queue,subprocess,time
from pathlib import Path
import numpy as np
from PIL import Image,ImageDraw
from hm.core import dump,sha,ENVELOPES,xyxy,load_json
from hm.session import Session,Options
from hm.app import paths
from hm.train import train

def fixture_model(folder):
    import torch
    from uimap_lite_l2.model import UIMapSpatial,save_weights
    from uimap_lite_l2.export import export_checked
    folder.mkdir(parents=True,exist_ok=False)
    torch.set_num_threads(1);torch.manual_seed(11);model=UIMapSpatial()
    x=torch.rand(2,3,192,320);o=torch.optim.Adam(model.parameters(),lr=.001)
    out=model(x);loss=out.square().mean();loss.backward();o.step();model.eval()
    save_weights(model,folder/'weights.npz')
    result=export_checked(model,x[:1].numpy(),folder,True)
    dump(folder/'fixture.json',dict(synthetic_test_model=True,optimizer_executed=True,accuracy_not_tested=True,export=result))

def fixture_training(folder):
    folder.mkdir(parents=True,exist_ok=False);(folder/'samples').mkdir();rows=[];labels=[]
    for i in range(40):
        im=Image.new('RGB',(1920,1080),(i*5,30,55));d=ImageDraw.Draw(im)
        for name,rect in ENVELOPES.items():
            b=xyxy(rect);d.rectangle(b,fill=(40+i,120,60),outline=(200,220,230),width=3)
        d.rectangle((50+i*5,50,80+i*5,100),fill=(220,180,30))
        name=f'samples/{i:04d}.png';im.save(folder/name)
        rows.append(dict(sample_id=str(i),frame_id=i,image=name,image_sha256=sha(folder/name),width=1920,height=1080,
                         source_ms=i*5000.,targets=None))
        labels.append(dict(sample_id=str(i),image_sha256=rows[-1]['image_sha256'],
                    targets={n:dict(box=xyxy(b),visible=True,basis='synthetic_test_fixture') for n,b in ENVELOPES.items()},
                    supervision='profile_template_weak',neural_used_as_label=False,corners_independently_observed=False))
    dump(folder/'training-manifest.json',dict(policy='hm1_natural_mapping_dataset',samples=rows,source={'sha256':'synthetic-fixture-not-video'},
                                             synthetic_fixture=True,session_id='training-fixture'))
    dump(folder/'COMPLETE.json',{str(p.relative_to(folder)):sha(p) for p in folder.rglob('*') if p.is_file()})
    (folder/'supervision').mkdir()
    dump(folder/'supervision/weak-seeds.json',dict(policy='hm1_explicit_weak_seeds_v1',records=labels,
                                                 source_seal_sha256=sha(folder/'COMPLETE.json'),synthetic_fixture=True))

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);a=p.parse_args();out=Path(a.output)
    out.mkdir(parents=True,exist_ok=False);fixture_model(out/'model');fixture_training(out/'training-session')
    media=out/'input.mkv';cfg=paths()
    subprocess.run([cfg['ffmpeg'],'-v','error','-f','lavfi','-i','color=black:s=1920x1080:r=10:d=2','-c:v','ffv1',str(media)],check=True,timeout=30)
    s=Session(Options(**cfg,video=str(media),model=str(out/'model/deployment-candidate.json'),output=str(out/'mapping'),seconds=2)).start()
    timeout=time.monotonic()+60
    while not s.done.is_set():
        if time.monotonic()>timeout:s.stop();raise TimeoutError('integration session')
        for q in (s.map_results,s.native_results):
            try:q.get(.01)
            except queue.Empty:pass
    report=s.finish()
    assert report['execution_complete'],report.get('error')
    assert report['counts']['mapped_frames']>0 and report['counts']['read_frames']>0
    m=load_json(out/'mapping/training-manifest.json');assert m['samples'] and all(x['targets'] is None for x in m['samples'])
    assert any(r['region']=='player.hp' for r in report['coverage'])
    assert not report['profile_promoted'] and not report['full_hud_neural_mapping']
    trained=train([str(out/'training-session')],str(out/'model/deployment-candidate.json'),str(out/'trained'),8,True)
    assert trained['export']['validated'] and trained['optimization_steps_executed']==8
    dump(out/'INTEGRATION.json',dict(real_neural_inference=True,real_native_and_tesseract=True,
          real_optimizer_steps=8,real_onnx_export=True,pixels_collected=True,tft_accuracy_tested=False))
    print('HUD_MAPPER_INTEGRATION_OK')
if __name__=='__main__':main()
