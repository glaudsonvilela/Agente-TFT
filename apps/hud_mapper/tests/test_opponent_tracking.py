import unittest

from hm.opponent_tracking import OpponentTracker, parse_panel


def word(text, x, y, confidence=.95):
    return dict(text=text, confidence=confidence, box=[x, y-7, x+len(text)*7, y+7])


def panel(frame, rows, battle=''):
    words=[]
    for index, name, hp in rows:
        y=289+80*index
        words.append(word(name, 1730, y))
        words.append(word(str(hp), 1835, y))
    return dict(status='raw_ocr', frame_id=frame, words=words,
                battle_name_words=[word(battle,1080,135)] if battle else [])


class OpponentTrackingTest(unittest.TestCase):
    def test_scoreboard_tracks_name_across_reordered_rows(self):
        tracker=OpponentTracker()
        first=panel(1,[(0,'Black Sheep',80),(1,'FL Upsetmax',95)],'Black Sheep')
        second=panel(2,[(1,'Black Sheep',74),(0,'FL Upsetmax',95)],'Black Sheep')
        tracker.update(first,epoch=1,source_ms=0)
        state=tracker.update(second,epoch=1,source_ms=5000)
        self.assertEqual({p['name']:p['hp'] for p in state['players']},
                         {'Black Sheep':None,'FL Upsetmax':95})
        self.assertIsNone(state['current_opponent'])
        state=tracker.update(panel(3,[(1,'Black Sheep',74)],'Black Sheep'),
                             epoch=1,source_ms=10000)
        self.assertEqual(state['current_opponent'],'Black Sheep')
        self.assertEqual(next(p for p in state['players'] if p['name']=='Black Sheep')['hp'],74)
        event=dict(event='combat_loss_observed',stage='3-1')
        linked=tracker.register_loss(event,epoch=1,source_ms=10500)
        self.assertEqual(linked['opponent_name'],'Black Sheep')
        self.assertEqual(next(p for p in tracker.snapshot(10500)['players']
                              if p['name']=='Black Sheep')['losses_observed'],1)

    def test_cached_ocr_is_not_new_evidence_and_epoch_resets(self):
        tracker=OpponentTracker()
        raw=panel(1,[(0,'Black Sheep',80)],'Black Sheep')
        tracker.update(raw,epoch=1,source_ms=0)
        cached=dict(raw,status='cadence_cached')
        self.assertEqual(tracker.update(cached,epoch=1,source_ms=1000)['players'][0]['reads'],1)
        self.assertEqual(tracker.update(panel(2,[],''),epoch=2,source_ms=2000)['players'],[])

    def test_panel_discards_low_confidence_name(self):
        sample=panel(1,[(0,'Black Sheep',80)])
        sample['words'][0]['confidence']=.2
        self.assertEqual(parse_panel(sample),[])

    def test_damage_statistics_panel_is_not_a_player_list(self):
        sample=panel(1,[(0,'Damage',55),(1,'Viego',70)])
        sample['words'].append(word('Dealt',1790,289))
        self.assertEqual(parse_panel(sample),[])

    def test_single_bad_hp_ocr_does_not_replace_confirmed_value(self):
        tracker=OpponentTracker()
        for frame,hp in [(1,95),(2,95),(3,9)]:
            state=tracker.update(panel(frame,[(0,'FL Upsetmax',hp)]),
                                 epoch=1,source_ms=frame*5000)
        self.assertEqual(state['players'][0]['hp'],95)

    def test_vod_roster_survives_damage_panel_without_stale_hp(self):
        tracker=OpponentTracker()
        roster=[(0,'Xbmots',100),(1,'Filup',92),(2,'david1',90)]
        first=panel(1,roster)
        first['words'][0]=word('Xbmots',1730,199)
        first['words'][1]=word('100',1835,199)
        tracker.update(first,epoch=1,source_ms=0,stage='3-2')
        second=panel(2,roster)
        second['words'][0]=word('Xbmots',1730,199)
        second['words'][1]=word('100',1835,199)
        second['enemy_name_words']=[word('Xbmots',1215,88)]
        tracker.update(second,epoch=1,source_ms=5000,stage='3-2')
        third=dict(second,frame_id=4)
        state=tracker.update(third,epoch=1,source_ms=10000,stage='3-2')
        self.assertEqual(state['current_opponent'],'Xbmots')
        damage=panel(3,[(0,'Damage',55),(1,'Viego',70)])
        damage['words'].append(word('Dealt',1790,289))
        state=tracker.update(damage,epoch=1,source_ms=180000,stage='4-3')
        self.assertEqual({row['name'] for row in state['players']},
                         {'Xbmots','Filup','david1'})
        self.assertTrue(all(row['hp'] is None and row['status']=='stale_roster'
                            for row in state['players']))
        self.assertIsNone(state['current_opponent'])

    def test_streamer_self_name_does_not_become_opponent(self):
        tracker=OpponentTracker()
        for frame in (1,2,3):
            sample=panel(frame,[(0,'VIT k3soju',86),(1,'Xbmots',100)])
            sample['self_name_words']=[word('VIT K3SOJU#000',80,20)]
            sample['enemy_name_words']=[word('VIT k3soju',1215,88)]
            state=tracker.update(sample,epoch=1,source_ms=frame*5000)
        self.assertEqual([row['name'] for row in state['players']],['Xbmots'])
        self.assertIsNone(state['current_opponent'])

    def test_new_match_stage_resets_roster_after_two_reads(self):
        tracker=OpponentTracker()
        tracker.update(panel(1,[(0,'Xbmots',80)]),epoch=1,source_ms=0,stage='4-3')
        self.assertEqual(len(tracker.update(panel(2,[],''),epoch=1,
                            source_ms=5000,stage='1-2')['players']),1)
        self.assertEqual(tracker.update(panel(3,[],''),epoch=1,
                         source_ms=10000,stage='1-2')['players'],[])

    def test_ocr_final_i_and_one_keep_same_player_history(self):
        tracker=OpponentTracker()
        tracker.update(panel(1,[(0,'davidi',90)]),epoch=1,source_ms=0)
        state=tracker.update(panel(2,[(0,'david1',90)]),epoch=1,source_ms=5000)
        self.assertEqual(len(state['players']),1)
        self.assertEqual(state['players'][0]['hp'],90)

    def test_two_name_regions_agree_on_one_opponent(self):
        tracker=OpponentTracker()
        for frame in (1,2,3):
            sample=panel(frame,[(0,'Xbmots',100)],'Xbmots')
            sample['enemy_name_words']=[word('Xbmots',1215,88)]
            state=tracker.update(sample,epoch=1,source_ms=frame*5000)
        self.assertEqual(state['current_opponent'],'Xbmots')


if __name__ == '__main__':
    unittest.main()
