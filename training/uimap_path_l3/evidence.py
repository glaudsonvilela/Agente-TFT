"""Verified input bundles and immutable output receipts. No user cache or model is deleted."""
from pathlib import Path
from . import legacy
from uimap_lite_l2.common import load,sha,require,contained,save


def baseline(path):
    p=Path(path).resolve(strict=True)
    if (p/'run/report.json').is_file():p=p/'run'
    seal=load(p/'COMPLETE.json')
    for name,digest in seal.items():
        require(sha(contained(p,name))==digest,'L2 sealed file changed: '+name)
    for name in ('weights.npz','report.json','plan.json','manifest.json'):
        require(name in seal,'L2 required sealed artifact absent: '+name)
    report=load(p/'report.json')['summary']
    require(report['policy']=='uimap-lite-l2-spatial-v1' and report['execution_complete'] and report['parameters']==27726,
            'requires L2, not U1/L1 or partial run')
    return p,dict(weights_sha256=sha(p/'weights.npz'),seal_sha256=sha(p/'COMPLETE.json'),
                  historical_model_trained=report['model_trained'],source='sealed_L2_bundle')


def locate(home):
    paths=sorted(Path(home).glob('match-001-ui-map-l2.*/run'),key=lambda p:p.parent.stat().st_mtime_ns,reverse=True)
    require(bool(paths),'no L2 run; specify --baseline')
    return baseline(paths[0])[0]


def validate_plan(plan,base):
    require(plan['schema_version']==3 and plan['id']=='uimap-path-l3-v2','L3 plan id')
    require(plan.get('initialization')=='frozen_L2_weights' and plan.get('test_seed')==80330000,'initialization/evaluation identity')
    require(plan['model_schema']=='l3_edge_nodes_bilinear_targets_v1','L3 model schema')
    require(plan['base_plan_sha256']==sha(base),'L2 seed plan changed')
    require(plan['training_steps']==1400 and plan['batch_size']==12 and plan['training_samples']==768,
            'unregistered training budget')
    require(plan['validation_samples']==96 and plan['test_samples']==192 and plan['training_threads']==2,'evaluation budget')
    require(plan['automatic_refinement'] is False and plan['activation_allowed'] is False,'no activation in L3')
    b=load(base)
    all_names=[set(b[s+'_images'])|{plan['negative_sources'][s]['image']} for s in ('train','validation','test')]
    require(all(not all_names[i]&all_names[j] for i in range(3) for j in range(i)),'negative/positive split leakage')
    return b


def seal_output(path):
    p=Path(path)
    save(p/'COMPLETE.json',{str(f.relative_to(p)):sha(f) for f in p.rglob('*') if f.is_file() and f.name!='COMPLETE.json'})
