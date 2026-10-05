"""Seeded resource/planning tests; never full matches or policy training.

Uses the actual compiled catalog and writes bounded, resumable-by-seed evidence.
Combat results are test inputs. No neural weights or runtime settings are changed.
"""

import argparse
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import random
import resource
import time

from trainer.simulation.economy import accounted_copies, new_planning_probe
from trainer.simulation.state import (
    Action,
    IllegalAction,
    Player,
    Unit,
    UnsupportedRule,
    apply,
    validate_world,
)
from trainer.simulation.seasonal_events import (
    begin_observed_round,
    buy_wisp,
    end_planning,
    observe_offer,
    settle_observed_pvp,
    settle_observed_non_pvp,
)
from trainer.simulation.seasonal_offers import round_key


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def conserved(world, content):
    validate_world(world, content)
    require(accounted_copies(world, content) == world.pool_totals, "pool drift")
    for p in world.players:
        require(p.gold >= 0 and p.hp >= 0 and p.xp >= 0, "negative resources")


def snapshot(content, rng, seed):
    candidates = sorted(
        key
        for key, spec in content["champions"].items()
        if not spec.get("purchase_blocker")
        and spec.get("pool_identity", key) == key
        and spec.get("team_slots", 1) == 1
    )
    require(len(candidates) >= 2, "requires two canonical shop champions")
    a, b = rng.sample(candidates, 2)
    units = [
        Unit("board", a, zone="board", position=(0, 0)),
        Unit("bench", b, position=(0,)),
    ]
    player = Player(
        rng.randint(20, 100),
        rng.randint(2, 9),
        0,
        hp=rng.randint(10, 28),
        stage=2,
        units=units,
        free_rerolls=rng.randrange(3),
        round_free_rerolls=rng.randrange(3),
    )
    # Opponent reservations must remain unavailable to the tested player.
    other = Player(30, 2, 0, units=[Unit("opponent", a, position=(0,))])
    return new_planning_probe([player, other], content, seed=seed)


def offer_case(index, seed, content, events, calendar, economy):
    rng = random.Random(seed)
    names = sorted(events["wisps"])
    name = names[index % len(names)]
    tier = (0, 3, 7, 9)[(index // len(names)) % 4]
    spec = events["wisps"][name]
    eligibility = spec["eligibility"]
    rounds = [
        key
        for key, row in calendar["rounds"].items()
        if row["kind"] == "pvp"
        and not row.get("augment")
        and round_key(key) >= round_key(eligibility["first_round"])
        and (
            eligibility["last_round"] is None
            or round_key(key) <= round_key(eligibility["last_round"])
        )
    ]
    key = rng.choice(rounds)
    world = snapshot(content, rng, seed)
    low = max(-2, eligibility.get("streak_min", -2))
    high = min(2, eligibility.get("streak_max", 2))
    world.players[0].streak = rng.randint(low, high)
    world = begin_observed_round(
        world,
        0,
        key,
        content,
        events,
        calendar,
        initial_blossom_tier=tier,
        initial_offer_history={},
    )
    before = deepcopy(world)
    offered = observe_offer(world, 0, name, content, events, refresh=bool(index % 2))
    require(world == before, "offer mutated its input")
    before = deepcopy(offered)
    purchased, receipt = buy_wisp(offered, 0, content, events)
    require(offered == before, "purchase mutated its input")
    repeated, second_receipt = buy_wisp(offered, 0, content, events)
    require(purchased == repeated and receipt == second_receipt, "seed replay differs")
    require(purchased.players[1] == world.players[1], "opponent changed")
    conserved(purchased, content)
    require(purchased.players[0].seasonal["purchased"] == 1, "purchase counted twice")
    require(purchased.players[0].seasonal["offer"] is None, "purchased offer retained")

    # Sufficient funds at offer time must not allow later overdrafts.
    rejected = 0
    if receipt["cost"]:
        poor = deepcopy(offered)
        poor.players[0].gold = receipt["cost"] - 1
        unchanged = deepcopy(poor)
        try:
            buy_wisp(poor, 0, content, events)
        except IllegalAction:
            require(poor == unchanged, "failed purchase mutated state or RNG")
            rejected += 1
        else:
            raise AssertionError("unaffordable purchase succeeded")

    combat = end_planning(purchased, 0, content, events)
    outcome = rng.choice(("win", "loss"))
    settled, result = settle_observed_pvp(
        combat,
        0,
        content,
        events,
        calendar,
        economy,
        outcome=outcome,
        enemy_champion_kills=rng.randrange(9),
        surviving_enemy_champions=0 if outcome == "win" else rng.randint(1, 8),
        allied_survivors=1 if outcome == "win" else 0,
        one_star_deaths=0 if outcome == "win" else 1,
    )
    conserved(settled, content)
    require(not result["full_match"], "resource test mislabeled as a match")
    if settled.players[0].hp:
        try:
            settle_observed_pvp(
                settled,
                0,
                content,
                events,
                calendar,
                economy,
                outcome=outcome,
                enemy_champion_kills=0,
                surviving_enemy_champions=0,
                allied_survivors=0,
            )
        except IllegalAction:
            rejected += 1
        else:
            raise AssertionError("round settlement paid twice")
    return dict(
        family="wisp_resource",
        wisp=name,
        blossom_tier=tier,
        round=key,
        outcome_input=outcome,
        cost=receipt["cost"],
        rejected_invalid_actions=rejected,
        state_sha256=digest(asdict(settled)),
        effects_sha256=digest(receipt["effects"]),
        steps=4,
    )


def planning_case(index, seed, content, events, calendar, economy):
    rng = random.Random(seed)
    world = snapshot(content, rng, seed)
    # Avoid merges in this case: sale and component handling are checked on the
    # owned unit. Merge ordering with equipped items has its own readiness gap.
    world = apply(world, 0, Action("reroll"), content)
    conserved(world, content)
    before = deepcopy(world)
    p = world.players[0]
    unit = p.units[0]
    price = content["champions"][unit.champion]["sale_prices"]["1"]
    components = sorted(k for k, v in content["items"].items() if v.get("component"))
    require(bool(components), "no bound component catalog")
    item = rng.choice(components)
    world.players[0].inventory.append(item)
    equipped = apply(world, 0, Action("equip", (0, unit.uid)), content)
    require(equipped.players[0].units[0].items == [item], "item equip failed")
    sold = apply(equipped, 0, Action("sell", (unit.uid,)), content)
    require(sold.players[0].gold == before.players[0].gold + price, "sale price drift")
    require(sold.players[0].inventory == [item], "sale lost or duplicated item")
    require(sold.players[1] == before.players[1], "sale changed opponent")
    conserved(sold, content)
    return dict(
        family="shop_item_sale",
        champion=unit.champion,
        item=item,
        rejected_invalid_actions=0,
        state_sha256=digest(asdict(sold)),
        steps=3,
    )


def calendar_case(index, seed, content, events, calendar, economy):
    rng = random.Random(seed)
    world = snapshot(content, rng, seed)
    world.players[0].hp = rng.randint(50, 100)
    tier = rng.choice((0, 3))
    outcomes = [rng.choice(("win", "loss")) for _ in range(3)]
    win_count = outcomes.count("win")
    result = None
    for key in ("2-2", "2-3", "2-4", "2-5"):
        world = begin_observed_round(
            world,
            0,
            key,
            content,
            events,
            calendar,
            initial_blossom_tier=tier if key == "2-2" else 0,
        )
        if key == "2-2":
            world = observe_offer(world, 0, "golden_road", content, events)
            world, _ = buy_wisp(world, 0, content, events)
        world = end_planning(world, 0, content, events)
        if key == "2-4":
            player = world.players[0]
            pending = deepcopy(player.seasonal["pending"])
            resources = {
                k: getattr(player, k)
                for k in (
                    "gold",
                    "xp",
                    "level",
                    "hp",
                    "streak",
                    "free_rerolls",
                    "round_free_rerolls",
                )
            }
            world, _ = settle_observed_non_pvp(
                world, 0, content, events, calendar, resources=resources
            )
            require(
                world.players[0].seasonal["pending"] == pending,
                "carousel consumed a PvP reward counter",
            )
        else:
            outcome = outcomes.pop(0)
            world, result = settle_observed_pvp(
                world,
                0,
                content,
                events,
                calendar,
                economy,
                outcome=outcome,
                enemy_champion_kills=rng.randrange(7),
                surviving_enemy_champions=0 if outcome == "win" else rng.randint(1, 6),
                allied_survivors=1 if outcome == "win" else 0,
            )
        conserved(world, content)
    expected = win_count * 2 + int(tier == 3)
    require(result["resource_events"][0]["amount"] == expected, "delayed reward lost")
    require(world.players[0].seasonal["pending"] == [], "matured reward retained")
    return dict(
        family="delayed_reward_carousel",
        rejected_invalid_actions=0,
        declared_wins=win_count,
        payout=expected,
        blossom_tier=tier,
        state_sha256=digest(asdict(world)),
        steps=4,
    )


def atomic_json(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


def run_batch(
    content, events, calendar, economy, output, *, cases=10000, seed=20261004
):
    if type(cases) is not int or cases < 1 or type(seed) is not int:
        raise ValueError("positive cases and integer seed required")
    if content.get("patch") != events.get("patch"):
        raise UnsupportedRule("content/events patch mismatch")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    # Exclusive creation prevents a repeated command from erasing evidence.
    results = (output / "cases.jsonl").open("x")
    start, cpu_start = time.monotonic(), time.process_time()
    report = dict(
        kind="seasonal_resource_stress",
        status="running",
        requested_cases=cases,
        completed_cases=0,
        failed_cases=0,
        seed=seed,
        family_counts={},
        wisp_variant_counts={},
        steps=0,
        rejected_invalid_actions=0,
        complete_matches=0,
        combats_simulated=0,
        training_labels=0,
        training_started=False,
        runtime_promoted=False,
        outcome_source="explicit synthetic test inputs, not combat predictions",
        data_sha256={
            key: digest(value)
            for key, value in dict(
                content=content, events=events, calendar=calendar, economy=economy
            ).items()
        },
        engine_sha256={
            str(path.relative_to(Path(__file__).resolve().parents[1])): hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
            for path in sorted(
                (Path(__file__).resolve().parents[1] / "trainer/simulation").glob(
                    "*.py"
                )
            )
            + [Path(__file__).resolve()]
        },
        limitations=[
            "Tests implementation consistency of bound resource candidates only.",
            "Does not validate game accuracy, full matches, neural skill or HUD latency.",
            "Abilities, augments, Coven cashouts and generated loot remain outside this batch.",
        ],
    )

    def checkpoint():
        report.update(
            wall_seconds=time.monotonic() - start,
            cpu_seconds=time.process_time() - cpu_start,
            peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        )
        atomic_json(output / "progress.json", report)

    checkpoint()
    # 80% Wisp cases cycle every identity and variant; 10% shop/items, 10% calendar.
    wisp_index = 0
    with results:
        for index in range(cases):
            case_seed = seed + index
            family = (
                planning_case
                if index % 10 == 8
                else calendar_case if index % 10 == 9 else offer_case
            )
            try:
                row = family(
                    wisp_index if family is offer_case else index,
                    case_seed,
                    content,
                    events,
                    calendar,
                    economy,
                )
                if family is offer_case:
                    wisp_index += 1
                    key = row["wisp"] + ":" + str(row["blossom_tier"])
                    report["wisp_variant_counts"][key] = (
                        report["wisp_variant_counts"].get(key, 0) + 1
                    )
                report["completed_cases"] += 1
                name = row["family"]
                report["family_counts"][name] = report["family_counts"].get(name, 0) + 1
                report["steps"] += row["steps"]
                report["rejected_invalid_actions"] += row["rejected_invalid_actions"]
                results.write(
                    json.dumps(
                        dict(index=index, seed=case_seed, status="passed", **row)
                    )
                    + "\n"
                )
            except Exception as error:
                report["status"] = "failed"
                report["failed_cases"] = 1
                report["failure"] = dict(
                    index=index,
                    seed=case_seed,
                    exception=type(error).__name__,
                    message=str(error),
                )
                results.write(
                    json.dumps(dict(status="failed", **report["failure"])) + "\n"
                )
                results.flush()
                checkpoint()
                return report
            if (index + 1) % 100 == 0:
                results.flush()
                checkpoint()
    report["status"] = "completed"
    report["cases_sha256"] = hashlib.sha256(
        (output / "cases.jsonl").read_bytes()
    ).hexdigest()
    checkpoint()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--content", type=Path, required=True)
    parser.add_argument(
        "--events",
        type=Path,
        default=Path("configs/simulation/seasons/TFTSet18/events/18.3B-economy.json"),
    )
    parser.add_argument(
        "--calendar",
        type=Path,
        default=Path("configs/simulation/core/standard-calendar-v1.json"),
    )
    parser.add_argument(
        "--economy",
        type=Path,
        default=Path("configs/simulation/core/standard-economy-v2.json"),
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cases", type=int, default=10000)
    parser.add_argument("--seed", type=int, default=20261004)
    args = parser.parse_args()
    report = run_batch(
        **{
            key: json.loads(getattr(args, key).read_text())
            for key in ("content", "events", "calendar", "economy")
        },
        output=args.output,
        cases=args.cases,
        seed=args.seed
    )
    print(
        json.dumps(
            {
                key: report[key]
                for key in (
                    "status",
                    "completed_cases",
                    "failed_cases",
                    "complete_matches",
                    "wall_seconds",
                    "cpu_seconds",
                    "peak_rss_kib",
                )
            }
        )
    )
    raise SystemExit(0 if report["status"] == "completed" else 1)


if __name__ == "__main__":
    main()
