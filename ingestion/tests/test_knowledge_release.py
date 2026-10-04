import copy
import json
from pathlib import Path
import tempfile
import unittest
from ingestion import knowledge_release as k


def source():
    return {'sets':{'18':{'name':'Fixture only','champions':[
        {'apiName':'TFT18_A','name':'Alpha','cost':1,'traits':['Fixture'],'icon':'ASSETS/a.png'},
        {'apiName':'TFT18_B','name':'Beta','cost':2,'traits':['Fixture'],'icon':'ASSETS/b.png'}],
        'traits':[{'apiName':'TFT18_Fixture','name':'Fixture','icon':'ASSETS/trait.png','effects':[]}]}},
        'items':[{'apiName':'TFT_Item_Fixture','name':'Fixture item','icon':'ASSETS/item.png'}]}


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.input=self.root/'source.json'
        self.input.write_text(json.dumps(source()))
        self.kw=dict(selector='18',tft_patch='18.3',source_build='16.19',locale='pt_br',output_root=self.root/'releases')
    def build(self,**kw):return k.build(self.input,**(self.kw|kw))
    def test_pins_all_asset_urls_and_separates_version_namespaces(self):
        path,m,_=self.build();_,c=k.read_release(path)
        self.assertIn('/16.19/game/',c['units']['champions'][0]['icon_url'])
        self.assertNotIn('/latest/',json.dumps(c))
        self.assertEqual(m['tft_patch'],'18.3');self.assertEqual(m['provider_build'],'16.19')
        self.assertFalse(m['geometry_included'])
        self.assertEqual(m['champion_attribute_coverage']['total'], 2)
        self.assertEqual(m['champion_attribute_coverage']['stats'], 0)
    def test_champion_combat_attributes_survive_release(self):
        raw=source()
        raw['sets']['18']['champions'][0]['stats']={
            'hp': 650, 'damage': 52, 'attackSpeed': 0.7, 'armor': 35,
            'magicResist': 30, 'range': 2, 'mana': 80, 'initialMana': 20,
            'critChance': 0.25, 'critMultiplier': 1.4,
        }
        raw['sets']['18']['champions'][0]['ability']={
            'name': 'Golpe', 'desc': 'Causa dano',
            'variables': [{'name': 'Damage', 'value': [100, 200, 300]}],
        }
        self.input.write_text(json.dumps(raw))
        path,manifest,_=self.build();_,catalogs=k.read_release(path)
        champion=catalogs['units']['champions'][0]
        self.assertEqual(champion['stats']['hp'],650)
        self.assertEqual(champion['stats']['range'],2)
        self.assertEqual(champion['ability']['variables'][0]['values'],[100,200,300])
        self.assertEqual(manifest['champion_attribute_coverage']['stats'],1)
        self.assertEqual(manifest['champion_attribute_coverage']['abilities'],1)
        self.assertEqual(manifest['champion_attribute_coverage']['abilities_with_numeric_variables'],1)
    def test_repeated_snapshot_is_idempotent(self):
        p,m,a=self.build();p2,m2,b=self.build()
        self.assertTrue(a);self.assertFalse(b);self.assertEqual((p,m),(p2,m2))
    def test_latest_pbe_and_unpinned_builds_are_rejected(self):
        for build in ['latest','pbe','../16.19','16.19?x=1','']:
            with self.subTest(build=build),self.assertRaises(ValueError):self.build(source_build=build)
    def test_same_patch_new_content_has_new_identity_preserves_old(self):
        p1,_,_=self.build();raw=source();raw['sets']['18']['champions'][0]['cost']=2
        self.input.write_text(json.dumps(raw));p2,_,_=self.build()
        self.assertNotEqual(p1,p2);self.assertTrue(p1.is_dir())
        _,old=k.read_release(p1);_,new=k.read_release(p2)
        d=k.changes(old,new)
        self.assertEqual(d['components']['units']['changed'],['TFT18_A'])
        self.assertFalse(d['geometry_changed']);self.assertFalse(d['model_weights_changed'])
    def test_catalog_corruption_fails_closed(self):
        p,_,_=self.build();(p/'units.json').write_text('{}')
        with self.assertRaises(ValueError):k.read_release(p)
    def test_missing_patch_and_bad_locale_rejected(self):
        for kwargs in [dict(tft_patch=''),dict(tft_patch='../a'),dict(locale='')]:
            with self.assertRaises(ValueError):self.build(**kwargs)
    def test_duplicate_keys_and_nonfinite_rejected(self):
        for text in ['{"a":1,"a":2}','{"a":NaN}']:
            self.input.write_text(text)
            with self.assertRaises(ValueError):self.build()
    def test_unknown_set_not_substituted_with_latest(self):
        with self.assertRaises(ValueError):self.build(selector='99')
    def test_matching_name_does_not_replace_observed_price(self):
        p,_,_=self.build()
        r={'summary':{'layout_id':'fixture','locale':'pt_br','capabilities':{}},
           'records':[{'read':{'slots':[{'observed_name':'Alpha','observed_cost':0,'unit_id':None}]}}]}
        ctx=dict(schema_version=1,set_key='18',tft_patch='18.3',locale='pt_br',layout_id='fixture')
        result=k.bind_names(r,ctx,p);s=result['records'][0]['read']['slots'][0]
        self.assertEqual(s['unit_id'],'TFT18_A');self.assertEqual(s['observed_cost'],0);self.assertEqual(s['catalog_base_cost'],1)
    def test_patch_locale_or_layout_mismatch_blocks_binding(self):
        p,_,_=self.build();r={'summary':{'layout_id':'fixture','locale':'pt_br','capabilities':{}},'records':[]}
        base=dict(schema_version=1,set_key='18',tft_patch='18.3',locale='pt_br',layout_id='fixture')
        for field,value in [('tft_patch',None),('set_key','17'),('locale','en_us'),('layout_id','other')]:
            with self.assertRaises(ValueError):k.bind_names(copy.deepcopy(r),base|{field:value},p)
    def test_same_name_different_units_is_not_resolved_by_cost(self):
        raw=source();raw['sets']['18']['champions'][1]['name']='Alpha';self.input.write_text(json.dumps(raw))
        p,_,_=self.build();r={'summary':{'layout_id':'f','locale':'pt_br','capabilities':{}},
            'records':[{'read':{'slots':[{'observed_name':'Alpha','observed_cost':1,'unit_id':None}]}}]}
        r=k.bind_names(r,dict(schema_version=1,set_key='18',tft_patch='18.3',locale='pt_br',layout_id='f'),p)
        self.assertIsNone(r['records'][0]['read']['slots'][0]['unit_id'])
        self.assertEqual(r['records'][0]['read']['slots'][0]['catalog_status'],'ambiguous_name')
    def test_special_offer_not_forced_to_a_champion(self):
        p,_,_=self.build();r={'summary':{'layout_id':'f','locale':'pt_br','capabilities':{}},
            'records':[{'read':{'slots':[{'observed_name':'Ritual fixture','unit_id':None}]}}]}
        r=k.bind_names(r,dict(schema_version=1,set_key='18',tft_patch='18.3',locale='pt_br',layout_id='f'),p)
        self.assertEqual(r['records'][0]['read']['slots'][0]['catalog_status'],'offer_not_in_unit_catalog')
