"""Watch a recorded synthetic player match and inspect every decision branch."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time


def load_journal(path: Path):
    rows=[]
    for line_number,line in enumerate(path.read_text().splitlines(),1):
        if not line.strip(): continue
        row=json.loads(line)
        if row.get('kind') not in ('decision','action_executed','combat_start','round_result','match_end'):
            raise ValueError(f'unknown journal row at line {line_number}')
        rows.append(row)
    if not rows: raise ValueError('journal is empty')
    return rows


def follow_journal(path: Path):
    while not path.exists(): time.sleep(0.2)
    with path.open() as stream:
        while True:
            position=stream.tell()
            line=stream.readline()
            if not line or not line.endswith('\n'):
                stream.seek(position)
                time.sleep(0.2)
                continue
            row=json.loads(line)
            yield row
            if row.get('kind')=='match_end': break


def board_grid(units):
    cells=[[' · ' for _ in range(7)] for _ in range(4)]
    for unit in units:
        pos=unit.get('position')
        if isinstance(pos,(list,tuple)) and len(pos)==2:
            r,c=pos
            if isinstance(r,int) and isinstance(c,int) and 0<=r<4 and 0<=c<7:
                cells[r][c]=unit['champion'].split('_')[-1][:3].upper().center(3)
    return '\n'.join(f"  {r+1}  "+' '.join(cells[r]) for r in range(4))


def action_name(action):
    kind=action.get('kind','?'); args=action.get('args',[])
    names={'hold':'Esperar','xp':'Comprar XP','reroll':'Rolar loja',
           'buy':'Comprar','sell':'Vender','lock':'Travar loja',
           'equip':'Equipar','combine':'Combinar','move':'Mover'}
    detail=', '.join(str(value) for value in args)
    return names.get(kind,kind)+(f' ({detail})' if detail else '')


def format_row(row, *, branches=False):
    if row['kind']=='match_end':
        return (f"PARTIDA ENCERRADA | Colocação {row['placement']} | "
                f"Rodadas {row['rounds']} | Concluída: {row['completed']}")
    if row['kind']=='combat_start':
        opponent=', '.join(f"{u['champion']} {u['stars']}★" for u in row['opponent_board']) or 'vazio'
        # Winner is an absolute seat, not a local combat side index.
        result='vitória' if row['winner']==row['agent_seat'] else (
            'empate' if row['winner'] is None else 'derrota')
        return (f"RODADA {row['round']} · COMBATE contra jogador {row['opponent_seat']}\n"
                f"Adversário: {opponent}\n"
                f"Duração simulada: {row['duration_seconds']:.1f}s | Resultado: {result}")
    if row['kind']=='action_executed':
        board=', '.join(f"{u['champion']} {u['stars']}★ @{u['position']}" for u in row['board']) or 'vazio'
        bench=', '.join(f"{u['champion']} {u['stars']}★" for u in row['bench']) or 'vazio'
        source='Plano escolhido' if row['source']=='rust_plan' else 'Continuação do plano'
        return (f"RODADA {row['round']} · {source}: {action_name(row['action'])}\n"
                f"Ouro {row['gold']} | Nível {row['level']}\n"
                f"Tabuleiro: {board}\n{board_grid(row['board'])}\nBanco: {bench}")
    if row['kind']=='round_result':
        eliminated=', '.join(str(x) for x in row['eliminated']) or 'ninguém'
        return (f"FIM DA RODADA {row['round']} | Vida {row['agent_hp']} | "
                f"Ouro {row['agent_gold']} | Nível {row['agent_level']} | "
                f"Eliminados: {eliminated}")
    observed=row['observed']; decision=row['decision']; selected=decision['selected']
    board=', '.join(f"{u['champion']} {u['stars']}★" for u in observed['board']) or 'vazio'
    bench=', '.join(f"{u['champion']} {u['stars']}★" for u in observed['bench']) or 'vazio'
    shop=', '.join(f"{i}:{offer['entity']}({offer['cost']}g)" for i,offer in enumerate(observed['shop']) if offer) or 'vazia'
    alive=sum(p['hp']>0 for p in observed['opponents'])+1
    lines=[f"RODADA {row['round']} · ESCOLHA DO PLANO",
           f"Vida {observed['hp']} | Ouro {observed['gold']} | Nível {observed['level']} | Jogadores vivos {alive}",
           f"Tabuleiro: {board}",board_grid(observed['board']),
           f"Banco: {bench}",f"Loja: {shop}",
           f"Escolha: {action_name(decision['action'])} | colocação média simulada {selected['mean_placement']:.2f} "
           f"em {selected['samples']} futuro(s)"]
    if branches:
        lines.append('Árvore de alternativas:')
        for index,candidate in enumerate(decision['candidates']):
            mark='→' if index==decision['selected_index'] else ' '
            lines.append(f" {mark} {action_name(candidate['action']):28} "
                         f"colocação {candidate['mean_placement']:.2f} | "
                         f"top 4 {candidate['top4_rate']:.0%} | "
                         f"1º {candidate['first_rate']:.0%}")
    return '\n'.join(lines)


def watch_realtime(rows):
    round_start=None; last_action=None; combat_until=None
    for index,row in enumerate(rows,1):
        now=time.monotonic()
        if row['kind']=='decision':
            round_start=now
        elif row['kind']=='action_executed':
            if last_action is not None:
                time.sleep(max(0.0,last_action+2.0-now))
            last_action=time.monotonic()
        elif row['kind']=='combat_start':
            if round_start is not None:
                time.sleep(max(0.0,round_start+30.0-now))
            combat_until=time.monotonic()+float(row['duration_seconds'])
        elif row['kind']=='round_result':
            target=combat_until if combat_until is not None else (
                round_start+30.0 if round_start is not None else now)
            time.sleep(max(0.0,target-now))
            combat_until=None;last_action=None
        if sys.stdout.isatty(): print('\033[2J\033[H',end='')
        print(f'AGENTE TFT · partida no terminal · evento {index}\n')
        print(format_row(row,branches=True),flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('journal',type=Path)
    parser.add_argument('--auto',type=float,metavar='SECONDS',
                        help='play automatically, waiting this many seconds between events')
    parser.add_argument('--all',action='store_true',help='print the complete decision tree without prompts')
    parser.add_argument('--realtime',action='store_true',
                        help='show 30 seconds of planning and the recorded fight duration per round')
    parser.add_argument('--follow',action='store_true',help='watch while a match writes its journal')
    args=parser.parse_args()
    if args.auto is not None and args.auto < 0:
        parser.error('--auto must be nonnegative')
    if args.follow or args.realtime:
        watch_realtime(follow_journal(args.journal) if args.follow else load_journal(args.journal))
        return
    rows=load_journal(args.journal)
    if args.all or not sys.stdin.isatty():
        for row in rows:
            print(format_row(row,branches=True))
            print()
        return
    index=0; branches=True
    while 0 <= index < len(rows):
        print('\033[2J\033[H',end='')
        print(f'AGENTE TFT · replay de decisões · {index+1}/{len(rows)}\n')
        print(format_row(rows[index],branches=branches))
        if args.auto is not None:
            time.sleep(args.auto); index+=1; continue
        answer=input('\nEnter: próxima | p: anterior | a: alternativas | q: sair > ').strip().lower()
        if answer=='q': break
        if answer=='p': index=max(0,index-1)
        elif answer=='a': branches=not branches
        else: index+=1


if __name__=='__main__': main()
