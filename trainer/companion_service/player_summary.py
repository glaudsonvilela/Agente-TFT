"""Exact ranked statistics from an adapter's normalized, attributable records.

No neural model is invoked here: numerical evidence must precede interpretation.
External adapters must resolve the full player identity before calling summarize.
"""
import math


def summarize(records, *, source, fetched_at, current_patch, current_set):
    if not source or not isinstance(fetched_at,(int,float)) or not math.isfinite(fetched_at):
        raise ValueError('History provenance required')
    if not current_patch or not current_set:raise ValueError('Current patch and set required')
    accepted=[];seen=set();rejected=0;excluded_patch=0
    for row in records:
        if row.get('queue')!='ranked':continue
        if row.get('patch')!=current_patch or row.get('set')!=current_set:
            excluded_patch+=1;continue
        identity=row.get('match_id');place=row.get('placement');timestamp=row.get('played_at')
        if (not isinstance(identity,str) or not identity or type(place)!=int or not 1<=place<=8
                or not isinstance(timestamp,(int,float)) or not math.isfinite(timestamp)
                or timestamp<=0 or timestamp>fetched_at):
            rejected+=1;continue
        if identity in seen:continue
        seen.add(identity);accepted.append(row)
    accepted.sort(key=lambda row:(row['played_at'],row['match_id']),reverse=True)
    accepted=accepted[:20]
    def stats(rows):
        n=len(rows)
        return dict(matches=n,average_placement=round(sum(r['placement'] for r in rows)/n,2) if n else None,
                    wins=sum(r['placement']==1 for r in rows),top4=sum(r['placement']<=4 for r in rows),
                    top4_rate=sum(r['placement']<=4 for r in rows)/n if n else None)
    overall=stats(accepted)
    groups={}
    for row in accepted:
        key=(row.get('set') or 'unknown',row.get('patch') or 'unknown')
        groups.setdefault(key,[]).append(row)
    patches=[dict(set=key[0],patch=key[1],**stats(rows)) for key,rows in groups.items()]
    # Chronology alone cannot attribute a change to a decision or to learning.
    trend=None
    if len(accepted)>=10:
        window=accepted[:10]
        if all((r.get('set'),r.get('patch'))==(window[0].get('set'),window[0].get('patch')) for r in window) and window[0].get('set') and window[0].get('patch'):
            recent=stats(window[:5]);previous=stats(window[5:])
            trend=dict(recent_five=recent,previous_five=previous,
                       average_placement_delta=round(recent['average_placement']-previous['average_placement'],2),
                       causality_established=False)
    n=overall['matches']
    text=('Nenhuma partida ranked válida disponível.' if not n else
          f"No patch {current_patch}, nas {n} partidas ranked disponíveis: colocação média {overall['average_placement']:.2f}, "
          f"{overall['wins']} vitórias e {overall['top4']} Top 4. ")
    if 0<n<10:text+='A amostra ainda é pequena para avaliar uma tendência.'
    return dict(status='available' if n else 'empty',source=source,fetched_at=fetched_at,
                window='up_to_20_latest_available_ranked_matches_current_patch',
                current_patch=current_patch,current_set=current_set,excluded_patch_records=excluded_patch,
                rejected_records=rejected,
                statistics=overall,by_patch=patches,trend=trend,summary=text,
                interpretation='deterministic_evidence_summary',neural_analysis_applied=False,
                strategic_errors_inferred=False)
