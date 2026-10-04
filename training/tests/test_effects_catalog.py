from copy import deepcopy
import json
from pathlib import Path
import unittest

from training.compile_effects import compile_catalog,compile_item,compile_trait
from trainer.simulation.event_combat import Battle
from trainer.simulation.state import UnsupportedRule
from training.tests.test_event_combat import content,players


class CatalogBindings(unittest.TestCase):
    def item(self,name,values):
        return dict(api_name='TFT_Item_'+name,name=name,effects=values,unique=False)

    def test_numeric_units_and_aliases_are_not_double_counted(self):
        r=compile_item(self.item('Deathblade',{'AD':.55,'BonusDamage':.1,'{1543aa48}':.1}))
        self.assertEqual(r['modifiers'],[dict(stat='ad',value=.55,mode='base_pct'),dict(stat='damage_amp',value=.1,mode='flat')])
        with self.assertRaises(UnsupportedRule):
            compile_item(self.item('Deathblade',{'AD':.55,'BonusDamage':.1,'{1543aa48}':.15}))

    def test_guinsoo_uses_per_second_clock_and_shojin_per_attack(self):
        g=compile_item(self.item('GuinsoosRageblade',{'AP':10,'AS':10,'AttackSpeedPerStack':7}))
        self.assertEqual((g['hooks'][0]['event'],g['hooks'][0]['interval']),('periodic',1))
        s=compile_item(self.item('SpearOfShojin',{'AP':15,'AD':.15,'ManaRegen':1,'FlatManaRestore':5}))
        self.assertIn(dict(stat='mana_per_attack',value=5,mode='flat'),s['modifiers'])

    def test_unknown_numeric_fields_cannot_disappear_silently(self):
        with self.assertRaises(UnsupportedRule):compile_item(self.item('WarmogsArmor',{'Health':500,'NewSeasonEffect':1}))
        self.assertTrue(compile_item(self.item('Spatula',{'unknown':5}))['unsupported'])

    def test_trait_member_replacement_is_explicit(self):
        row=dict(api_name='DA_Juggernaut18',name='juggernaut',effects=[dict(min_units=2,max_units=3,
                  variables={'{f8c73243}':.04,'{6eab9c5e}':.2})])
        trait=compile_trait(row)
        self.assertTrue(trait['tiers'][0]['members_replace_team'])
        self.assertEqual(trait['tiers'][0]['members']['modifiers'][0]['value'],.2)

    def test_release_mismatch_is_rejected(self):
        with self.assertRaises(UnsupportedRule):
            compile_catalog(dict(release_sha256='a',tft_patch='18.3',set={'key':'TFTSet18'}),{},
                            dict(release_sha256='b',patch='18.3',set_key='TFTSet18'))

    def test_crownguard_only_its_own_shield_end_grants_ap(self):
        c=content();p=players();p[0].units[0].items=['crown']
        c['items']['crown']=compile_item(self.item('Crownguard',{'AP':20,'Armor':20,'Health':100,
                                        'ShieldSize':25,'ShieldDuration':8,'ShieldBonusAP':25}))
        b=Battle(p,c);a,z=b.units;b.start_actor(a,0)
        b.hook('shield_end',a,z,{'key':'unrelated'})
        self.assertEqual(b.get(a,'ap'),120)
        b.hit(z,a,51,'true','attack')
        self.assertEqual(b.get(a,'ap'),145)

    def test_actual_pinned_catalog_compiles_when_present(self):
        from ingestion.knowledge_release import read_release
        root=Path(__file__).resolve().parents[2]
        bindings=json.loads((root/'configs/simulation/set18-effects-bindings-v1.json').read_text())
        release=root/'knowledge/releases/TFTSet18/18.3'/bindings['release_sha256']
        if not release.exists():self.skipTest('private sealed catalog not present on CI')
        manifest,catalogs=read_release(release);result=compile_catalog(manifest,catalogs,bindings)
        self.assertEqual(result['coverage']['champions']['candidate_effects'],4)
        self.assertEqual(result['coverage']['items']['candidate_effects'],17)
        self.assertEqual(result['coverage']['champions']['replay_validated'],0)
        self.assertFalse(result['coverage']['current_patch_training_ready'])


if __name__=='__main__':unittest.main()
