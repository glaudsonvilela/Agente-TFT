"""Bounded UCT planning search over atomic actions and a caller-supplied evaluator.

Search paths are NOT full matches. Values are simulator estimates, not observed
human outcomes. Evaluators must score from the same player's point of view.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import math
import random
import time

from .state import Action, apply, legal_actions


@dataclass
class Node:
    world: object
    action: Action | None = None
    parent: object = None
    depth: int = 0
    visits: int = 0
    total: float = 0
    children: list = field(default_factory=list)
    pending: list | None = None


def search(world, seat, content, evaluate, *, simulations=500, seconds=10., depth=3,
           seed=0, positions=True, exploration=math.sqrt(2)):
    if simulations < 1 or depth < 1 or seconds <= 0: raise ValueError('positive search budget required')
    rng = random.Random(seed); root = Node(world); started = time.monotonic(); calls = 0
    for _ in range(simulations):
        if time.monotonic()-started >= seconds: break
        node = root
        while node.depth < depth and (node.action is None or node.action.kind != 'hold'):
            if node.pending is None:
                node.pending = legal_actions(node.world, seat, content, positions=positions)
                rng.shuffle(node.pending)
            if node.pending:
                action = node.pending.pop()
                child = Node(apply(node.world, seat, action, content), action, node, node.depth+1)
                node.children.append(child); node = child
                break
            if not node.children: break
            node = max(node.children, key=lambda c: c.total/c.visits +
                       exploration*math.sqrt(math.log(max(1, node.visits))/c.visits))
        value = float(evaluate(node.world, rng.randrange(2**31))); calls += 1
        if not math.isfinite(value) or not -1 <= value <= 1:
            raise ValueError('evaluator must return finite utility in [-1, 1]')
        while node is not None:
            node.visits += 1; node.total += value; node = node.parent
    ranked = sorted(root.children, key=lambda c: (c.visits, c.total/c.visits), reverse=True)
    return dict(scope='experimental_hex_lab', runtime_promoted=False,
                simulation_paths=calls, complete_matches=0, elapsed_seconds=time.monotonic()-started,
                action=ranked[0].action if ranked else Action('hold'),
                candidates=[dict(action=c.action, visits=c.visits, value=c.total/c.visits) for c in ranked],
                unexpanded_root_actions=len(root.pending or []))
