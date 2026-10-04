"""Eight-row odd-r hex topology; independent of pixels, arena and patch."""
from collections import deque


def global_hex(team, local):
    row, col = local
    if team not in (0, 1) or not (0 <= row < 4 and 0 <= col < 7):
        raise ValueError('invalid team/local hex')
    return (3-row, col) if team == 0 else (4+row, 6-col)


def cube(pos):
    row, col = pos
    x = col - (row - (row & 1)) // 2
    z = row
    return x, -x-z, z


def distance(a, b):
    return max(abs(x-y) for x, y in zip(cube(a), cube(b)))


def neighbors(pos):
    r, c = pos
    shift = 1 if r & 1 else -1
    candidates = [(r, c-1), (r, c+1), (r-1, c), (r+1, c), (r-1, c+shift), (r+1, c+shift)]
    return [p for p in candidates if 0 <= p[0] < 8 and 0 <= p[1] < 7]


def next_step(start, target, attack_range, occupied):
    """Shortest free route to any firing hex; never walk through another unit."""
    if distance(start, target) <= attack_range: return start
    queue = deque([(start, None)]); seen = {start}
    while queue:
        pos, first = queue.popleft()
        for nxt in sorted(neighbors(pos), key=lambda p: (distance(p, target), p)):
            if nxt in seen or nxt in occupied: continue
            seen.add(nxt)
            initial = nxt if first is None else first
            if distance(nxt, target) <= attack_range: return initial
            queue.append((nxt, initial))
    return start
