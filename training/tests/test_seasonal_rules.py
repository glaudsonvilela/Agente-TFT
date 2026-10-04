from copy import deepcopy
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from ingestion.simulation_bindings import load_bindings,substitute
from trainer.simulation.event_combat import Battle
from trainer.simulation.state import UnsupportedRule,Unit
from training.compile_effects import compile_item,compile_trait
from training.tests.test_event_combat import content,players

PACK=Path(__file__).resolve().parents[2]/'configs/simulation/seasons/TFTSet18/18.3/manifest.json'


class SeasonalIsolation(unittest.TestCase):
    def setUp(self):self.pack=load_bindings(PACK)

    def test_changed_file_is_rejected_before_compilation(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d)/'pack';shutil.copytree(PACK.parent,folder)
            path=folder/'items.json';path.write_text(path.read_text()+' ')
            with self.assertRaisesRegex(UnsupportedRule,'component changed'):load_bindings(folder/'manifest.json')

    def test_file_cannot_escape_pack(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d)/'pack';shutil.copytree(PACK.parent,folder)
            path=folder/'manifest.json';m=json.loads(path.read_text());m['components']['items']['path']='../outside.json';path.write_text(json.dumps(m))
            with self.assertRaisesRegex(UnsupportedRule,'unsafe'):load_bindings(path)

    def test_new_item_id_and_new_balance_need_only_data_changes(self):
        rules=deepcopy(self.pack['items']);original=deepcopy(rules)
        rules['entities']['arbitrary_new_set_blade']=deepcopy(rules['entities']['TFT_Item_Deathblade'])
        row=dict(api_name='arbitrary_new_set_blade',name='fixture',unique=False,effects={'AD':.75,'BonusDamage':.2,'{1543aa48}':.2})
        result=compile_item(row,rules)
        c=content();p=players();p[0].units[0].items=['new'];c['items']['new']=result
        b=Battle(p,c)
        self.assertEqual(b.get(b.units[0],'ad'),35)
        self.assertEqual(b.get(b.units[0],'damage_amp'),.2)
        self.assertEqual(self.pack['items'],original)

    def test_role_and_star_metrics_live_outside_compiler(self):
        root=PACK.parents[5]
        code=(root/'training/compile_effects.py').read_text()
        for forbidden in ('TFT_Item_','DA_18_','mana_per_attack=7','1.8,3.24'):
            self.assertNotIn(forbidden,code)
        self.assertEqual(self.pack['profile']['roles']['caster']['mana_per_attack'],7)

    def test_numeric_substitution_rejects_expression_strings(self):
        with self.assertRaises(UnsupportedRule):substitute({'$field':'x'}, {'x':'__import__("os")'})
        with self.assertRaises(UnsupportedRule):substitute({'$field':'x','integer':True}, {'x':2.4})


class NewItemMechanics(unittest.TestCase):
    def setUp(self):self.rules=load_bindings(PACK)['items']

    def battle_with(self,name,values,copies=1):
        c=content();p=players()
        c['items'][name]=compile_item(dict(api_name='TFT_Item_'+name,name=name,unique=False,effects=values),self.rules)
        p[0].units[0].items=[name]*copies
        return Battle(p,c)

    def test_titan_attack_and_damage_share_cap_and_duplicates_are_independent(self):
        b=self.battle_with('TitansResolve',{'AS':10,'Armor':20,'StackCap':25,'StackedAmp':.1,'StackingAD':.02,'StackingSP':2},copies=2)
        a,z=b.units
        for i in range(40):b.hook('attack' if i%2 else 'damage_taken',a,z)
        self.assertEqual(b.get(a,'ap'),200)
        self.assertAlmostEqual(b.get(a,'ad'),40)
        self.assertAlmostEqual(b.get(a,'damage_amp'),.2)
        self.assertEqual(b.get(a,'cc_immune'),2)
        self.assertEqual(a.counters['item:0:stacks'],25)
        self.assertEqual(a.counters['item:1:stacks'],25)

    def test_last_whisper_refreshes_and_does_not_stack(self):
        b=self.battle_with('LastWhisper',{'AD':.15,'AS':20,'CritChance':20,'ArmorReductionPercent':30,'ArmorBreakDuration':3})
        a,z=b.units;z.values.base['armor']=100
        for _ in range(4):b.hook('damage_dealt',a,z,{'tag':'spell'})
        self.assertAlmostEqual(b.get(z,'sunder'),.3)
        b.now=2;b.hook('damage_dealt',a,z,{'tag':'attack'});b.now=3.1
        self.assertAlmostEqual(b.get(z,'sunder'),.3)
        b.now=5.1;self.assertEqual(b.get(z,'sunder'),0)

    def test_quicksilver_immunity_expires_and_attack_speed_uses_time(self):
        b=self.battle_with('Quicksilver',{'AS':15,'CritChance':20,'MagicResist':20,'ProcAttackSpeed':.03,'SpellShieldDuration':18})
        a,z=b.units;b.start_actor(a,0)
        self.assertEqual(b.get(a,'cc_immune'),1)
        b.hook('attack',a,z);self.assertAlmostEqual(b.get(a,'attack_speed'),1.15)
        b.hook('periodic',a,a);self.assertAlmostEqual(b.get(a,'attack_speed'),1.18)
        b.now=18;self.assertEqual(b.get(a,'cc_immune'),0)

    def test_protectors_vow_threshold_reward_only_once(self):
        b=self.battle_with('FrozenHeart',{'Armor':25,'MagicResist':25,'ManaRegen':1,'CombatStartMana':20,
                'HealthThreshold':40,'TriggerMana':15,'ShieldHealthPercent':20,'ShieldDuration':60})
        a,z=b.units;b.start_actor(a,0);self.assertEqual(a.mana,20)
        a.hp=30;b.hook('health_below',a,z);b.hook('health_below',a,z)
        self.assertEqual(a.mana,35);self.assertEqual(len(a.shields),1)


class ConditionalTraits(unittest.TestCase):
    def test_vanguard_durability_follows_any_live_shield_and_is_not_permanent(self):
        rules=load_bindings(PACK)['traits']
        row=dict(api_name='DA_18_Vanguard',name='vanguard',effects=[dict(min_units=6,max_units=99,
                 variables={'MaxHealthShield':.4,'HealthThreshold':.5,'ShieldDuration':10,'{b58e0b6e}':.05})])
        c=content();c['traits']['vanguard']=compile_trait(row,rules);p=players();p[0].units=[];p[0].level=6
        for i in range(6):
            ident=f'fixture{i}';c['champions'][ident]=deepcopy(c['champions']['fixture']);c['champions'][ident]['traits']=['vanguard']
            p[0].units.append(Unit(str(i),ident,zone='board',position=(0,i)))
        b=Battle(p,c);a=b.units[0];z=b.units[-1]
        self.assertEqual(b.get(a,'durability'),0)
        b.start_actor(a,0);self.assertEqual(b.get(a,'durability'),.05)
        b.hit(z,a,40,'true','attack');self.assertEqual(b.get(a,'durability'),0)
        a.hp=40;b.hook('health_below',a,z);self.assertEqual(b.get(a,'durability'),.05)
        b.now=10;self.assertEqual(b.get(a,'durability'),0)


if __name__=='__main__':unittest.main()
