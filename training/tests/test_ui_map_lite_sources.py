"""Dataset/source contracts; fixture coordinates are not TFT labels."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


def fixture_dataset(root):
    from PIL import Image,ImageDraw
    from training.ui_map_lite.core import sha
    board=dict(id='match001-board-bench-v1',bench_centers=[409+117*i for i in range(9)],
               bench_crop_width=103,bench_crop_y=682,bench_crop_height=146)
    shop=dict(id='match001-desktop-1920x1080-ptbr-v1',slots=[
        dict(card=dict(x=553+i*202,y=929,width=192,height=141)) for i in range(5)])
    profiles=[]
    for name,obj in [('board.json',board),('shop.json',shop)]:
        path=root/name;path.write_text(json.dumps(obj));raw=path.read_bytes()
        profiles.append(dict(path=name,git_blob=hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()))
    imgs=root/'images';imgs.mkdir();seeds=[];frames=[]
    for i,split in enumerate(('train','validation','test')):
        im=Image.new('RGB',(1920,1080),(40+30*i,70,100));draw=ImageDraw.Draw(im)
        for j in range(9):draw.rectangle((370+117*j,705,430+117*j,800),fill=(50,80+25*i,140))
        for j in range(5):draw.rectangle((560+202*j,937,725+202*j,1060),fill=(140,50+20*i,40))
        p=imgs/(split+'.png');im.save(p)
        seeds.append(dict(image=p.name,sha256=sha(p),split=split))
        frames.append(dict(image=p.name,timestamp_ms=i*100000,suggestions={'irrelevant':'never training labels'}))
    spec=root/'spec.json';spec.write_text(json.dumps(dict(schema_version=1,id='uimap-lite-u1-match001',profiles=profiles,seeds=seeds)))
    manifest=root/'manifest.json';manifest.write_text(json.dumps(dict(frames=frames)))
    return spec,imgs,manifest


@unittest.skipUnless(importlib.util.find_spec('numpy') and importlib.util.find_spec('PIL'),'data tools')
class SourceTests(unittest.TestCase):
    def call(self,root,args):
        from training.ui_map_lite.data import prepare
        return prepare(root,*args)

    def test_profiles_derive_boxes_and_ignore_prelabels(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);a=fixture_dataset(root);p=self.call(root,a)
            self.assertEqual(p['boxes'][1],[553,929,1553,1070])
            self.assertNotIn('suggestions',p['frames'][0])

    def test_profile_mutation_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);a=fixture_dataset(root);(root/'board.json').write_text('{}')
            with self.assertRaises(ValueError):self.call(root,a)

    def test_seed_mutation_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);a=fixture_dataset(root);(a[1]/'train.png').write_bytes(b'changed')
            with self.assertRaises(ValueError):self.call(root,a)

    def test_cross_split_duplicate_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);a=fixture_dataset(root);s=json.loads(a[0].read_text())
            s['seeds'][1]=dict(s['seeds'][0],split='validation');a[0].write_text(json.dumps(s))
            with self.assertRaises(ValueError):self.call(root,a)

    def test_missing_partition_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);a=fixture_dataset(root);s=json.loads(a[0].read_text())
            s['seeds'][2]['split']='train';a[0].write_text(json.dumps(s))
            with self.assertRaises(ValueError):self.call(root,a)

    def test_duplicate_timestamp_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);a=fixture_dataset(root);m=json.loads(a[2].read_text())
            m['frames'][1]['timestamp_ms']=0;a[2].write_text(json.dumps(m))
            with self.assertRaises(ValueError):self.call(root,a)

    def test_empty_manifest_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);a=fixture_dataset(root);a[2].write_text('{"frames":[]}')
            with self.assertRaises(ValueError):self.call(root,a)

    def test_source_parent_escape_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);a=fixture_dataset(root);m=json.loads(a[2].read_text())
            m['frames'][0]['image']='../outside.png';a[2].write_text(json.dumps(m))
            with self.assertRaises(ValueError):self.call(root,a)


if __name__=='__main__':unittest.main()
