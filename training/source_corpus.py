"""Build a private, source-linked corpus without turning narration into action labels."""
from __future__ import annotations
import argparse
import html
import json
from pathlib import Path
import re
import sqlite3
from urllib.parse import parse_qs, urlparse

from .transcribe_sources import atomic, digest

TRANSCRIPTS = {'livelojnga.mp4':'livelojnga-sampled.jsonl',
               'videoplayback 02.mp4':'videoplayback-02.jsonl',
               'videoplayback.mp4':'videoplayback.jsonl',
               'videoplayback03.mp4':'videoplayback03-sampled.jsonl',
               'videoplayback04.mp4':'videoplayback04.jsonl'}


def clean(value):
    return re.sub(r'\s+', ' ', html.unescape(re.sub('<[^>]+>', ' ', value))).strip()


def build(registry, analysis, supplemental, output, online=None):
    output.mkdir(parents=True, exist_ok=True)
    sources = json.loads(registry.read_text())['sources']
    seals = {x['filename']: x for x in json.loads((analysis/'analysis-index.json').read_text())['transcripts']}
    db = sqlite3.connect(output/'corpus.sqlite3')
    db.execute('CREATE VIRTUAL TABLE IF NOT EXISTS passages USING fts5(source_sha, url, patch_claim, start UNINDEXED, end UNINDEXED, text)')
    report = dict(schema_version=1, kind='source_corpus', sources=[], segments=0,
                  action_outcome_labels=0, patch_binding_verified=False, runtime_promoted=False)
    with db:
        db.execute('DELETE FROM passages')
        for source in sources:
            name = source.get('source_file')
            if name in TRANSCRIPTS:
                path = analysis/TRANSCRIPTS[name]
                if digest(path) != seals[path.name]['sha256']: raise ValueError('transcript hash mismatch')
                rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
                previous_scope = seals[path.name]['scope']
            elif source.get('local_media') and source.get('source_sha256'):
                rows=[]; previous_scope='no_previous_transcript'
            else:
                if online is None: continue
                video_id = parse_qs(urlparse(source['url']).query).get('v', [''])[0]
                if not re.fullmatch(r'[A-Za-z0-9_-]{11}', video_id): continue
                track = next((online/(video_id+suffix) for suffix in ('.en-orig.json3','.en.json3')
                              if (online/(video_id+suffix)).is_file()), None)
                if track is None: continue
                subtitle_sha = digest(track); count = 0
                for event in json.loads(track.read_text()).get('events',[]):
                    text = ''.join(s.get('utf8','') for s in event.get('segs',[])).strip()
                    if not text: continue
                    start = event['tStartMs']/1000
                    end = start + event.get('dDurationMs',0)/1000
                    db.execute('INSERT INTO passages VALUES (?,?,?,?,?,?)',
                               (subtitle_sha,source['url'],source['patch_claim'],start,end,text))
                    count += 1
                report['sources'].append(dict(subtitle_sha256=subtitle_sha,url=source['url'],segments=count,
                                              supervision='unreviewed_platform_subtitles',action_outcome_labels=0))
                report['segments'] += count
                continue
            chunks = sorted((supplemental/source['source_sha256'][:16]).glob('*.json'))
            windows = []
            for chunk in chunks:
                item = json.loads(chunk.read_text())
                if item['source_sha256'] != source['source_sha256']: raise ValueError('chunk source mismatch')
                windows.append((item['start'],item['end']))
            # New complete audio windows replace overlapping old ASR, including silence.
            rows = [r for r in rows if not any(r['start'] < end and r['end'] > start for start,end in windows)]
            for chunk in chunks: rows.extend(json.loads(chunk.read_text())['segments'])
            rows.sort(key=lambda r:(r['start'],r['end']))
            for row in rows:
                if not 0 <= row['start'] <= row['end'] <= source['duration_seconds']+.1:
                    raise ValueError('transcript outside source time range')
                db.execute('INSERT INTO passages VALUES (?,?,?,?,?,?)',
                           (source['source_sha256'],source['url'],source['patch_claim'],
                            row['start'],row['end'],row['text']))
            report['sources'].append(dict(source_sha256=source['source_sha256'],url=source['url'],
                                          segments=len(rows), previous_scope=previous_scope,
                                          newly_transcribed_audio_seconds=sum(e-s for s,e in windows),
                                          supervision='automatic_unreviewed_transcript',
                                          action_outcome_labels=0))
            report['segments'] += len(rows)
    db.close()
    report['sources_with_text'] = sum(s['segments']>0 for s in report['sources'])
    report['database_sha256'] = digest(output/'corpus.sqlite3')
    atomic(output/'report.json',report)
    return report


def reference_audit(cards, output):
    if digest(cards) != 'c645113e0b1950bfdef766b1d4870c6495ce828732557a5097474c50e14c2593':
        raise ValueError('reference snapshot changed; conflict review must be repeated')
    raw = json.loads(cards.read_text()); units=[]
    for slug, unit in raw['units'].items():
        stats = unit.get('stats', {})
        text = clean(unit.get('ability',{}).get('desc',''))
        units.append(dict(slug=slug, id=unit.get('api'), name=unit.get('name'), cost=unit.get('cost'),
                          stats=stats, traits=unit.get('traits', []),
                          missing_stats=[k for k in ('hp','ad','as','armor','mr','range','mana') if k not in stats],
                          numeric_text_groups=re.findall(r'\d+(?:\.\d+)?(?:\s*/\s*\d+(?:\.\d+)?)*',text),
                          contains_unknown='?' in text, formula_binding=None, executable=False))
    report=dict(schema_version=1,kind='supplemental_reference_candidate',
                source_url='https://tftcodex.com/cards.json',source_sha256=digest(cards),
                retrieved_on='2026-10-04',exact_patch_verified=False,
                counts={k:len(raw[k]) for k in ('units','items','traits','augments')},
                units=units, current_patch_training_ready=False,
                conflicts=[dict(entity='DA_18_Cassiopeia',field='ability.poison_damage',
                                supplemental=[420,630,1020],official=[425,630,1020],
                                source_url='https://teamfighttactics.leagueoflegends.com/pt-br/news/game-updates/teamfight-tactics-patch-18-3/',
                                resolution='official fact retained; no executable formula inferred')])
    atomic(output,report)
    return {k:v for k,v in report.items() if k!='units'}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--registry',type=Path,required=True)
    p.add_argument('--analysis',type=Path,required=True)
    p.add_argument('--supplemental',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--cards',type=Path)
    p.add_argument('--online',type=Path)
    args=p.parse_args()
    result=build(args.registry,args.analysis,args.supplemental,args.output,args.online)
    if args.cards: result['reference']=reference_audit(args.cards,args.output/'reference-candidate.json')
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__ == '__main__': main()
