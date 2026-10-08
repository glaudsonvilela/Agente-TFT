"""Run a planning player in the experimental eight-seat TFT laboratory.

Every planning round, complete-match counterfactuals are generated from the
same observed world. Rust picks the first action; the same deterministic
continuation is used both in prediction and execution. The simulator is
synthetic, so these frequencies are not live TFT odds.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
import json
import os
from pathlib import Path
import subprocess

from trainer.simulation.match import begin_round, new_match, play, resolve_round, scripted_action
from trainer.simulation.state import Action, apply, legal_actions


def _placement_trial(request):
    world,content,seat,action,seed=request
    result=play(content,seed,start_world=world,focus_seat=seat,first_action=action)
    if not result['completed'] or str(seat) not in result['placements']:
        raise ValueError('counterfactual match did not produce a placement')
    return result['placements'][str(seat)]


def choose_action(world, content, binary: Path, *, seat: int, rollout_seeds: list[int], executor=None):
    if world.round_phase != 'planning' or world.players[seat].hp <= 0:
        raise ValueError('agent needs an active planning seat')
    if not rollout_seeds or len(set(rollout_seeds)) != len(rollout_seeds):
        raise ValueError('distinct rollout seeds required')
    actions=legal_actions(world,seat,content,positions=False)
    requests=[(world,content,seat,action,seed)
              for action in actions for seed in rollout_seeds]
    placements=list(executor.map(_placement_trial,requests)) if executor else list(map(_placement_trial,requests))
    candidates=[dict(action=asdict(action),
                     placements=placements[i*len(rollout_seeds):(i+1)*len(rollout_seeds)])
                for i,action in enumerate(actions)]
    request=dict(scope='experimental_hex_lab',candidates=candidates)
    process=subprocess.run([str(binary)],input=json.dumps(request),text=True,
                           capture_output=True,check=True)
    decision=json.loads(process.stdout)
    chosen=Action(decision['action']['kind'],tuple(decision['action']['args']))
    if chosen not in actions:
        raise ValueError('Rust returned an action outside the legal set')
    return chosen,decision


def _record(stream, row):
    if stream is not None:
        stream.write(json.dumps(row,ensure_ascii=False,allow_nan=False)+'\n')
        stream.flush()
        os.fsync(stream.fileno())


def play_agent(content, binary: Path, *, seed=0, rollouts=2, seat=0,
               workers=4, journal=None):
    if rollouts < 1: raise ValueError('positive rollout count required')
    if not 1 <= workers <= 4: raise ValueError('worker count outside 1..4')
    world=new_match(content,seed); decisions=[]; actions=[]; rounds=[]; placements={}
    def execute(current, action, source):
        nonlocal world
        world=apply(world,current,action,content)
        if current==seat:
            player=world.players[seat]
            row=dict(kind='action_executed',round=world.round_number,source=source,
                action=asdict(action),gold=player.gold,level=player.level,
                board=[asdict(u) for u in player.units if u.zone=='board'],
                bench=[asdict(u) for u in player.units if u.zone=='bench'])
            actions.append(row)
            _record(journal,row)
    with ProcessPoolExecutor(max_workers=workers) as executor:
        while world.round_number < content['match_rules']['max_rounds']:
            world=begin_round(world,content)
            active=[i for i,p in enumerate(world.players) if p.hp>0]
            choice=None
            if seat in active:
                seeds=[seed*1_000_000+world.round_number*10_000+i for i in range(rollouts)]
                choice,decision=choose_action(world,content,binary,seat=seat,
                    rollout_seeds=seeds,executor=executor)
                row=dict(round=world.round_number,
                    observed=dict(gold=world.players[seat].gold,hp=world.players[seat].hp,
                        level=world.players[seat].level,
                        shop=[asdict(x) if x else None for x in world.players[seat].shop],
                        board=[asdict(u) for u in world.players[seat].units if u.zone=='board'],
                        bench=[asdict(u) for u in world.players[seat].units if u.zone=='bench'],
                        inventory=list(world.players[seat].inventory),
                        opponents=[dict(hp=p.hp,gold=p.gold,level=p.level,
                            board=[dict(champion=u.champion,stars=u.stars,items=u.items,
                                        position=u.position)
                                   for u in p.units if u.zone=='board'])
                                   for i,p in enumerate(world.players) if i!=seat]),
                    plan=dict(first_action=asdict(choice),continuation='scripted_action_v1'),
                    decision=decision)
                decisions.append(row)
                _record(journal,dict(kind='decision',**row))
                print(json.dumps(dict(round=world.round_number,plan=asdict(choice),
                    decisions=len(decisions))),flush=True)
            for current in active:
                remaining=content['match_rules']['planning_actions']
                if current==seat and choice is not None:
                    if choice.kind=='hold': continue
                    execute(current,choice,'rust_plan')
                    remaining-=1
                for _ in range(remaining):
                    scripted=scripted_action(world,current,content)
                    if scripted.kind=='hold': break
                    execute(current,scripted,'plan_continuation')
            opponent_boards={i:[dict(champion=u.champion,stars=u.stars,items=u.items,
                                     position=u.position)
                                for u in p.units if u.zone=='board']
                             for i,p in enumerate(world.players) if i!=seat}
            world,record=resolve_round(world,content,seed*1000+world.round_number-1)
            agent_fight=next((fight for fight in record['fights']
                              if seat in fight['seats']),None)
            if agent_fight:
                enemy=next(i for i in agent_fight['seats'] if i!=seat)
                combat_row=dict(kind='combat_start',round=world.round_number,
                    agent_seat=seat,opponent_seat=enemy,opponent_board=opponent_boards[enemy],
                    duration_seconds=agent_fight['duration_seconds'],
                    winner=agent_fight['winner'])
                _record(journal,combat_row)
            place=len(active)-(len(record['eliminated'])-1)/2
            for eliminated in record['eliminated']: placements[str(eliminated)]=place
            round_row=dict(round=world.round_number,agent_hp=world.players[seat].hp,
                           agent_gold=world.players[seat].gold,
                           agent_level=world.players[seat].level,
                           eliminated=record['eliminated'])
            rounds.append(round_row)
            _record(journal,dict(kind='round_result',**round_row))
            survivors=[i for i,p in enumerate(world.players) if p.hp>0]
            if len(survivors)<=1:
                if survivors: placements[str(survivors[0])]=1.0
                break
    completed=len([p for p in world.players if p.hp>0])<=1
    _record(journal,dict(kind='match_end',completed=completed,
                         placement=placements.get(str(seat)),rounds=len(rounds)))
    return dict(scope='experimental_hex_lab',policy='empirical_placement_v1',
                seed=seed,rollouts_per_action=rollouts,cpu_workers=workers,completed=completed,
                agent_placement=placements.get(str(seat)),decisions=decisions,
                executed_actions=actions,rounds=rounds,
                spoken_phrases=[],neural_weights_trained=False,
                real_tft_probability=None,runtime_promoted=False)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--content',type=Path,default=Path('configs/simulation/hex-lab-v1.json'))
    parser.add_argument('--rust-player',type=Path,default=Path('rust/target/release/agente-tft-hex-player'))
    parser.add_argument('--seed',type=int,default=0)
    parser.add_argument('--rollouts',type=int,default=2)
    parser.add_argument('--workers',type=int,default=4)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    content=json.loads(args.content.read_text())
    args.output.parent.mkdir(parents=True,exist_ok=True)
    journal_path=args.output.with_suffix('.decisions.jsonl')
    if args.output.exists() or journal_path.exists():
        raise ValueError('Use a new output path for each test')
    with journal_path.open('x') as journal:
        report=play_agent(content,args.rust_player,seed=args.seed,
                          rollouts=args.rollouts,workers=args.workers,journal=journal)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ('decisions','executed_actions','rounds')},ensure_ascii=False))


if __name__=='__main__': main()
