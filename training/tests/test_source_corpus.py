import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from training.source_corpus import build, reference_audit


class SourceCorpus(unittest.TestCase):
    def test_incremental_asr_replaces_overlapping_old_text_and_rebuild_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);analysis=root/'analysis';analysis.mkdir()
            path=analysis/'videoplayback.jsonl'
            path.write_text(json.dumps(dict(start=1,end=5,text='old'))+'\n'+
                            json.dumps(dict(start=70,end=75,text='keep'))+'\n')
            sha='a'*64
            (analysis/'analysis-index.json').write_text(json.dumps(dict(transcripts=[dict(filename=path.name,
                sha256=hashlib.sha256(path.read_bytes()).hexdigest(),scope='sampled')])))
            registry=root/'registry.json'
            registry.write_text(json.dumps(dict(sources=[dict(source_file='videoplayback.mp4',source_sha256=sha,
                url='https://example.org/video',patch_claim='unknown',duration_seconds=100)])))
            chunks=root/'chunks'/sha[:16];chunks.mkdir(parents=True)
            (chunks/'000000.json').write_text(json.dumps(dict(source_sha256=sha,start=0,end=60,
                segments=[dict(start=1,end=5,text='new')])) )
            first=build(registry,analysis,root/'chunks',root/'output')
            second=build(registry,analysis,root/'chunks',root/'output')
            self.assertEqual(first['segments'],2);self.assertEqual(second['segments'],2)
            with sqlite3.connect(root/'output/corpus.sqlite3') as db:
                self.assertEqual([r[0] for r in db.execute('SELECT text FROM passages ORDER BY start')],['new','keep'])
            self.assertEqual(first['action_outcome_labels'],0)
            path.write_text('tampered')
            with self.assertRaises(ValueError): build(registry,analysis,root/'chunks',root/'output')
            with sqlite3.connect(root/'output/corpus.sqlite3') as db:
                self.assertEqual(db.execute('SELECT count(*) FROM passages').fetchone()[0],2)

    def test_changed_reference_cannot_reuse_manual_conflict_audit(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'changed.json';path.write_text('{}')
            with self.assertRaises(ValueError): reference_audit(path,Path(temporary)/'report.json')


if __name__=='__main__': unittest.main()
