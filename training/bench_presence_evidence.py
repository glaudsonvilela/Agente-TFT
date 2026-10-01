"""B2 hypotheses and historical B1 regression, never labels or state writes."""
from collections import Counter
import hashlib
import math
import struct
from training.board_spatial_evidence import require, rect_ok


def blob_sha(content):
    return hashlib.sha1(b'blob '+str(len(content)).encode()+b'\0'+content).hexdigest()


def validate_policy(p, base, parent_bytes=None):
    keys = {'schema_version','id','parent_profile_id','parent_blob_sha1','surface_anchors',
        'body_top','body_width','body_height','marker_top','marker_bottom','marker_center_tolerance','support_top',
        'max_color_offset','surface_min_correlation','surface_max_residual_mae','surface_max_changed_fraction',
        'empty_min_correlation','empty_max_residual_mae','empty_max_changed_fraction','residual_threshold',
        'min_component_pixels','min_component_width','min_component_height','max_component_fraction','max_components','note'}
    require(set(p) == keys and p['schema_version'] == 1 and p['parent_profile_id'] == base['id'], 'presence policy identity')
    require(isinstance(p['id'],str) and 0 < len(p['id']) <= 100, 'invalid presence id')
    require(isinstance(p['parent_blob_sha1'],str) and len(p['parent_blob_sha1']) == 40
            and all(c in '0123456789abcdef' for c in p['parent_blob_sha1']), 'invalid parent pin')
    if parent_bytes is not None:
        require(blob_sha(parent_bytes) == p['parent_blob_sha1'], 'presence parent bytes changed')
    ranges = {'body_width':(32,128),'body_height':(32,160),'body_top':(0,8191),
        'marker_top':(0,8191),'marker_bottom':(0,8191),'marker_center_tolerance':(1,64),'support_top':(0,8191),
        'max_color_offset':(0,40),'residual_threshold':(24,32),'min_component_pixels':(120,4096),
        'min_component_width':(10,64),'min_component_height':(24,96),'max_components':(1,512)}
    for key,(lo,hi) in ranges.items():
        require(type(p[key]) is int and lo <= p[key] <= hi, 'invalid integer policy: '+key)
    for key,lo,hi in [('surface_min_correlation',.90,1),('surface_max_residual_mae',0,6),
        ('surface_max_changed_fraction',0,.05),('empty_min_correlation',.98,1),
        ('empty_max_residual_mae',0,4),('empty_max_changed_fraction',0,.01),('max_component_fraction',.1,.70)]:
        require(number(p[key]) and lo <= p[key] <= hi, 'invalid policy threshold: '+key)
    require(p['marker_top'] < p['marker_bottom'] <= p['body_top']+24
            and p['body_top'] < p['support_top'] < p['body_top']+p['body_height']
            and p['marker_center_tolerance'] <= p['body_width']//2, 'inconsistent presence geometry')
    crops = [crop(p,base,i) for i in range(9)]
    w,h = base['reference_width'],base['reference_height']
    require(all(rect_ok(r,w,h) for r in crops)
            and all(not overlaps(a,b) for i,a in enumerate(crops) for b in crops[i+1:]), 'presence crops overlap')
    anchors=p['surface_anchors']
    require(len(anchors)==3 and all(rect_ok(a,w,h) and a['width']<=128 and a['height']<=64
        and a['y']>=p['body_top']+p['body_height'] for a in anchors), 'presence anchors invalid')
    require(all(not overlaps(a,b) for i,a in enumerate(anchors) for b in anchors[i+1:]), 'presence anchors overlap')
    require(isinstance(p['note'],str) and len(p['note'])<=1024, 'invalid presence note')
    return p


def number(v):
    return type(v) in (int,float) and math.isfinite(v)


def f32(v):
    return struct.unpack('!f',struct.pack('!f',v))[0]


def crop(p,b,i):
    return dict(x=b['bench_centers'][i]-p['body_width']//2,y=p['body_top'],width=p['body_width'],height=p['body_height'])


def overlaps(a,b):
    return (a['x']<b['x']+b['width'] and b['x']<a['x']+a['width']
            and a['y']<b['y']+b['height'] and b['y']<a['y']+a['height'])


def appearance_ok(s):
    require(isinstance(s,dict) and set(s)=={'offset','residual_mae','changed_fraction','correlation','reference_spread'}, 'bad appearance schema')
    require(len(s['offset'])==3 and all(type(v) is int and -255<=v<=255 for v in s['offset']), 'invalid RGB offset')
    for k,lo,hi in [('residual_mae',0,510),('changed_fraction',0,1),('correlation',-1,1),('reference_spread',0,255)]:
        require(number(s[k]) and lo<=s[k]<=hi, 'invalid appearance '+k)


def offset_ok(s,p):
    return all(abs(v)<=p['max_color_offset'] for v in s['offset'])


def shape_ok(s,p,kind):
    return (offset_ok(s,p) and s['reference_spread']>=4 and s['correlation']>=f32(p[kind+'_min_correlation'])
        and s['residual_mae']<=f32(p[kind+'_max_residual_mae'])
        and s['changed_fraction']<=f32(p[kind+'_max_changed_fraction']))


def validate(report,base,p):
    """Recompute decisions from all emitted evidence; reject unsupported claims."""
    counts,surfaces=Counter(),Counter()
    for record in report['records']:
        legacy=record['read'];r=record.get('bench_presence')
        require(isinstance(r,dict) and r.get('profile')==p['id'] and r.get('timestamp_ms')==legacy['timestamp_ms'], 'missing/misaligned B2')
        require(r.get('temporal_confirmation') is False and r.get('ownership_established') is False, 'unsupported temporal/owner claim')
        require(len(r['surface_scores'])==3, 'missing structural anchors')
        for s in r['surface_scores']: appearance_ok(s)
        surface=('reference_arena' if legacy['projection_status']=='reference_arena_match' else
                 'bench_structure_match' if all(shape_ok(s,p,'surface') for s in r['surface_scores']) else 'unresolved')
        require(r['surface_status']==surface, 'structural gate inconsistent')
        require([s['slot'] for s in r['slots']]==list(range(9)), 'missing/duplicate presence slot')
        surfaces[surface]+=1
        for i,s in enumerate(r['slots']):
            box=crop(p,base,i);require(s['crop']==box, 'presence crop changed')
            require(s.get('unit_id') is None and s.get('ground_point') is None, 'invented unit or footpoint')
            require(type(s['components_total']) is int and 0<=s['components_total']<=p['max_components'], 'bad component budget')
            if surface=='unresolved':
                require(s['appearance'] is None and not s['marker_candidates'] and not s['body_candidates'] and s['components_total']==0, 'unresolved surface reused')
                expected=('unavailable',None,'surface_unresolved')
            else:
                a=s['appearance'];appearance_ok(a)
                markers=legacy['markers'];center=base['bench_centers'][i]
                hints=[m['id'] for m in markers if p['marker_top']<=m['rect']['y']
                    and m['rect']['y']+m['rect']['height']<=p['marker_bottom']
                    and abs(m['rect']['x']+m['rect']['width']/2-center)<=p['marker_center_tolerance']]
                require(s['marker_candidates']==hints, 'presence marker routing changed')
                bodies=s['body_candidates'];require(len(bodies)<=s['components_total'], 'component count mismatch')
                for c in bodies:
                    q=c['rect'];require(rect_ok(q,base['reference_width'],base['reference_height']), 'invalid component box')
                    require(type(c['pixels']) is int and p['min_component_pixels']<=c['pixels']<=q['width']*q['height']
                        and f32(c['pixels']/(box['width']*box['height']))<=f32(p['max_component_fraction'])
                        and q['width']>=p['min_component_width'] and q['height']>=p['min_component_height']
                        and box['x']<q['x'] and q['x']+q['width']<box['x']+box['width']
                        and box['y']<q['y'] and q['y']+q['height']<box['y']+box['height']
                        and q['y']+q['height']>p['support_top'], 'ineligible body component')
                empty=shape_ok(a,p,'empty');paired=False
                if len(hints)==len(bodies)==1:
                    m=markers[hints[0]]['rect'];b=bodies[0]['rect']
                    paired=(b['y']>=m['y']+m['height'] and abs(m['x']+m['width']/2-b['x']-b['width']/2)<=p['marker_center_tolerance'])
                if not offset_ok(a,p): expected=('unknown',None,'appearance_offset_out_of_budget')
                elif len(hints)>1 or len(bodies)>1 or (empty and hints): expected=('ambiguous',None,'conflicting_or_multiple_support')
                elif paired and not empty: expected=('occupied_visual',True,'single_bar_and_connected_foreground_reaches_support_band')
                elif empty and not hints and not bodies and not any(overlaps(box,m['rect']) for m in markers):
                    expected=('empty_visual',False,'textured_empty_reference_match_without_marker_or_body')
                else: expected=('unknown',None,'insufficient_joint_support')
            require(s['status']==expected[0] and s['occupancy'] is expected[1] and s['reason']==expected[2], 'presence decision unsupported')
            counts[s['status']]+=1
        for key in ('bench_presence_scan_ms','decode_and_both_scans_ms'):
            require(number(record[key]) and record[key]>=0, 'invalid B2 duration')
    return dict(bench_statuses=dict(counts),surface_statuses=dict(surfaces))


def compare_legacy(before,after):
    a,b=before['records'],after['records']
    require(len(a)==len(b), 'legacy frame count changed')
    changed=[x['read']['timestamp_ms'] for x,y in zip(a,b) if x['read']!=y['read']]
    return dict(frames=len(a),b1_observations_unchanged=not changed,changed_frames=changed)
