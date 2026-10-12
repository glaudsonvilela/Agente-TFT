from pathlib import Path
from types import SimpleNamespace
import json
import tempfile
import unittest

from hm.dataset import Store


class AugmentCapturePersistenceTests(unittest.TestCase):
    def test_card_crops_survive_when_periodic_sample_has_same_frame(self):
        width, height = 1920, 1080
        frame = SimpleNamespace(id=7, pts_ms=1000, epoch=0,
                                width=width, height=height,
                                rgb=bytes(width * height * 3), capture=None)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'session'
            store = Store(root, max_samples=10, max_bytes=16 * 1024**2,
                          reserve_bytes=0)
            store.emit('periodic', {'frame_id': 7}, frame, True)
            store.emit('augment-options-observations', {
                'frame_id': 7,
                'selection_visible': True,
                'selection_confirmed': False,
                'regions': [
                    {'id': f'augment.offer.{slot}', 'box': box,
                     'status': 'observed_card_pixels_not_label'}
                    for slot, box in enumerate((
                        [375, 245, 740, 810], [780, 245, 1145, 810],
                        [1190, 245, 1555, 810]))],
            }, frame, True)
            store.close({'session_id': 'capture-test', 'source': {},
                         'versions': {}, 'execution_complete': True})
            manifest = json.loads((root / 'training-manifest.json').read_text())
            self.assertEqual(len(manifest['samples']), 1)
            self.assertEqual(len(manifest['samples'][0]['crops']), 3)
            self.assertFalse(manifest['ground_truth_available'])


if __name__ == '__main__':
    unittest.main()
