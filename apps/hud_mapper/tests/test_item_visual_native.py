import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from PIL import Image

from hm.item_movement import ItemMovementTracker
from hm.item_visual_native import ItemVisualNative


ROOT = Path(__file__).resolve().parents[3]
LIBRARY = (ROOT / 'tools/hm-item-native/target/release' /
           ('agente_tft_hm_item_native.dll' if os.name == 'nt'
            else 'libagente_tft_hm_item_native.so'))


class ItemNativeTests(unittest.TestCase):
    @unittest.skipUnless(LIBRARY.is_file(), 'Build native item library first')
    def test_source_crop_ranks_patch_gallery_without_class_head(self):
        with tempfile.TemporaryDirectory() as directory:
            icons = Path(directory)
            a = Image.new('RGB', (16, 16))
            b = Image.new('RGB', (16, 16))
            for y in range(16):
                for x in range(16):
                    a.putpixel((x, y), (x * 13, y * 12, 40))
                    b.putpixel((x, y), (y * 12, 40, x * 13))
            a.save(icons / 'a.png')
            a.save(icons / 'a-alias.png')
            b.save(icons / 'b.png')
            gallery = ItemVisualNative(ROOT, [dict(id='a', icon='a.png', name='A'),
                dict(id='a-alias', icon='a-alias.png', name='Alias'),
                dict(id='b', icon='b.png', name='B')], icons, {'a', 'b'}, LIBRARY)
            screen = Image.new('RGB', (32, 32))
            screen.paste(a, (0, 0))
            source = SimpleNamespace(width=32, height=32, rgb=screen.tobytes())
            found = gallery.rank(source, dict(x=0, y=0, width=960, height=540))
            self.assertEqual(found['candidate_id'], 'a')
            self.assertFalse(found['identity_verified'])
            self.assertGreater(found['candidates'][0]['similarity'],
                               found['candidates'][1]['similarity'])
            self.assertEqual(found['source_rect'], [0, 0, 16, 16])
            self.assertEqual(found['candidates'][0]['visual_ids'], ['a', 'a-alias'])
            self.assertEqual(gallery.reference_artworks, 2)
            self.assertEqual(gallery.rank(source, dict(x=0, y=0, width=960, height=540))['candidate_id'], 'a')
            self.assertEqual(gallery.cache_hits, 1)
            self.assertEqual(ItemVisualNative._source_rect(
                dict(x=960, y=540, width=30, height=30), 1280, 720), (640, 360, 20, 20))
            screen.paste(b, (16, 0))
            source.rgb = screen.tobytes()
            inventory_rect = dict(x=0, y=0, width=960, height=540)
            equipped_rect = dict(x=960, y=0, width=960, height=540)
            snapshot = dict(inventory={'candidate_slots': [dict(slot=1,
                candidates=[dict(sample_rect=inventory_rect,
                                 ids_with_same_template=['a'])])]},
                observed_markers=[dict(marker_id=7, position_candidate={'zone': 'board'},
                    equipped_slots=[dict(slot=0, status='icon_candidate',
                        candidates=[dict(sample_rect=equipped_rect,
                                         ids_with_same_template=['b'])])])])
            observed = gallery.observe(source, snapshot)
            self.assertEqual(observed['inventory'][0]['candidate_id'], 'a')
            self.assertTrue(observed['inventory'][0]['rms_top_artwork_agrees'])
            self.assertEqual(observed['equipped'][0]['candidate_id'], 'b')
            self.assertEqual(observed['equipped'][0]['marker_id'], 7)

    def test_only_consecutive_visible_inventory_and_same_position_can_imply_transfer(self):
        tracker = ItemMovementTracker()
        position = dict(zone='board', row=1, cell_or_slot=3, status='candidate_only')

        def frame(ms, inventory, equipped, epoch=1, panel='located'):
            snapshot = dict(timestamp_ms=ms, position_status='candidate_only',
                            inventory={'inventory': {'panel_status': panel}},
                            observed_markers=[dict(position_candidate=position)])
            def item(slot, art):
                return dict(slot=slot, status='candidate_only', candidate_id='sword',
                            candidates=[dict(art_sha256=art)])
            visual = dict(active=True,
                inventory=[item(1, art) for art in inventory],
                equipped=[dict(item(slot, art), position_candidate=position)
                          for slot, art in equipped])
            return tracker.update(snapshot, visual, epoch)

        self.assertFalse(frame(1000, ['art-a'], [])['events'])
        event = frame(2000, [], [(0, 'art-a')])['events']
        self.assertEqual(len(event), 1)
        self.assertEqual(event[0]['kind'], 'equip_hypothesis')
        self.assertFalse(event[0]['training_label'])
        self.assertFalse(frame(100, ['art-a'], [], epoch=2)['events'])
        self.assertFalse(frame(200, [], [(0, 'art-a')], epoch=3)['events'])
        self.assertFalse(frame(300, [], [(0, 'art-a')], epoch=3, panel='unavailable')['events'])

    def test_components_can_form_only_a_recipe_bound_candidate_event(self):
        tracker = ItemMovementTracker({'combined': ('sword', 'vest')})
        position = dict(zone='board', row=1, cell_or_slot=3, status='candidate_only')

        def frame(ms, inventory, equipped):
            snapshot = dict(timestamp_ms=ms, position_status='candidate_only',
                            inventory={'inventory': {'panel_status': 'located'}},
                            observed_markers=[dict(position_candidate=position)])
            def row(item_id, art):
                return dict(status='candidate_only', candidate_id=item_id,
                            candidates=[dict(art_sha256=art)])
            visual = dict(active=True,
                inventory=[dict(slot=n, **row(item_id, art))
                           for n, (item_id, art) in enumerate(inventory)],
                equipped=[dict(marker_id=1, slot=n, position_candidate=position,
                               **row(item_id, art))
                          for n, (item_id, art) in enumerate(equipped)])
            return tracker.update(snapshot, visual, 1)

        self.assertEqual(frame(1000, [('sword', 'a'), ('vest', 'b')], [])['events'], [])
        events = frame(2000, [], [('combined', 'c')])['events']
        self.assertEqual([row['kind'] for row in events], ['combine_hypothesis'])
        self.assertEqual(events[0]['components'], ['sword', 'vest'])
        self.assertFalse(events[0]['training_label'])


if __name__ == '__main__':
    unittest.main()
