"""Validate the EXECUTED executable's outputs, not only successful process exit."""
from pathlib import Path
import json,sys
mapping,ui,training=map(Path,sys.argv[1:])
for root in (mapping,ui):
    d=json.loads((root/'summary.json').read_text(encoding='utf-8'))
    assert d['execution_complete'] and d['counts']['mapped_frames']>0 and d['counts']['read_frames']>0,d
    assert d['torch_loaded_in_mapper'] is False,'trainer leaked into observation process'
    assert d['collection']['samples_saved']>0 and not d['profile_promoted']
    assert (root/'COMPLETE.json').is_file()
    assert any(r['region']=='player.hp' for r in d['coverage'])
u=json.loads((ui/'summary.json').read_text(encoding='utf-8'))
assert u['counts'].get('ui_map',0)>0,'mapping canvas was not exercised'
t=json.loads((training/'report.json').read_text(encoding='utf-8'))
assert t['optimization_steps_executed']==4 and t['export']['validated'] and not t['profile_promoted']
print('HUD_MAPPER_PACKAGED_MAPPING_AND_TRAIN_OK')
