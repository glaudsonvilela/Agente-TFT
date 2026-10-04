"""Read-only readiness and capacity report for a requested full-match batch.

This command never substitutes combats or observed event probes for matches,
never launches training, and returns exit code 2 when prerequisites are missing.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil

from trainer.simulation.match import match_rules
from trainer.simulation.state import UnsupportedRule


def capacity(path):
    memory = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        key, value = line.split(":", 1)
        if key in ("MemTotal", "MemAvailable"):
            memory[key] = int(value.split()[0]) * 1024
    cpu = (
        len(os.sched_getaffinity(0))
        if hasattr(os, "sched_getaffinity")
        else os.cpu_count()
    )
    limits = {"cpu_quota": None, "memory_bytes": None, "memory_current_bytes": None}
    cgroup = Path("/sys/fs/cgroup")
    if (cgroup / "cpu.max").exists():
        quota, period = (cgroup / "cpu.max").read_text().split()
        if quota != "max":
            limits["cpu_quota"] = int(quota) / int(period)
    for key, name in [
        ("memory_bytes", "memory.max"),
        ("memory_current_bytes", "memory.current"),
    ]:
        if (cgroup / name).exists():
            value = (cgroup / name).read_text().strip()
            if value != "max":
                limits[key] = int(value)
    return dict(
        cpu_affinity=cpu,
        host_memory_bytes=memory,
        disk_free_bytes=shutil.disk_usage(path).free,
        cgroup=limits,
    )


def review(content, events, *, matches=10000, workers=1, output_directory=Path(".")):
    if (
        type(matches) is not int
        or matches <= 0
        or type(workers) is not int
        or workers <= 0
    ):
        raise ValueError("positive match and worker counts required")
    blockers = []
    coverage = content.get("coverage", {})
    for key in (
        "full_match_ready",
        "augments_ready",
        "seasonal_events_ready",
        "current_patch_training_ready",
    ):
        if coverage.get(key) is not True:
            blockers.append(key)
    if content.get("planning_requirements"):
        blockers.extend("planning:" + str(x) for x in content["planning_requirements"])
    unsupported = [
        k for k, v in content.get("champions", {}).items() if v.get("unsupported")
    ]
    if unsupported:
        blockers.append("unimplemented_champion_combat")
    if not content.get("champions"):
        blockers.append("empty_champion_catalog")
    if events.get("patch") != content.get("patch"):
        blockers.append("seasonal_patch_mismatch")
    if any(
        not v.get("stage_distribution_verified")
        for v in events.get("wisps", {}).values()
    ) or not events.get("wisps"):
        blockers.append("wisp_stage_distribution")
    if not events.get("coven", {}).get("cashout_tables"):
        blockers.append("coven_cashout_tables")
    try:
        match_rules(content, initializing=True)
    except UnsupportedRule as error:
        blockers.append("match_entry:" + str(error))
    # The present entry point only runs synthetic matches, regardless of mutable
    # report booleans. A real seasonal executor must be wired before this changes.
    blockers.append("seasonal_full_match_executor_not_integrated")
    resources = capacity(output_directory)
    if resources["disk_free_bytes"] < 2 * 1024**3:
        blockers.append("less_than_2_gib_free_disk")
    return dict(
        schema_version=1,
        kind="full_match_batch_preflight",
        status="blocked" if blockers else "ready",
        requested_matches=matches,
        requested_workers=workers,
        launched=False,
        completed_matches=0,
        blockers=sorted(set(blockers)),
        unsupported_champions=unsupported,
        resource_wisp_candidates=len(events.get("wisps", {})),
        wisp_bindings=dict(
            variant_programs=sum(
                int(bool(spec.get("normal"))) + int(bool(spec.get("blossom")))
                for spec in events.get("wisps", {}).values()
            ),
            catalog_id_pairs=sum(
                spec.get("catalog_id_verified") is True
                for spec in events.get("wisps", {}).values()
            ),
            eligibility_candidates=sum(
                bool(spec.get("eligibility"))
                for spec in events.get("wisps", {}).values()
            ),
            distribution_ready=False,
        ),
        resources=resources,
        estimated_seconds=None,
        estimated_peak_memory_bytes=None,
        estimate_reason="No calibrated complete-match pilot exists for this engine.",
        training_started=False,
        runtime_promoted=False,
    )


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--content", type=Path, required=True)
    p.add_argument("--events", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--matches", type=int, default=10000)
    p.add_argument("--workers", type=int, default=1)
    args = p.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    report = review(
        json.loads(args.content.read_text()),
        json.loads(args.events.read_text()),
        matches=args.matches,
        workers=args.workers,
        output_directory=args.output.parent,
    )
    report["content_sha256"] = hashlib.sha256(args.content.read_bytes()).hexdigest()
    report["events_sha256"] = hashlib.sha256(args.events.read_bytes()).hexdigest()
    report["engine_files_sha256"] = {
        str(path.relative_to(Path.cwd())): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted((Path.cwd() / "trainer/simulation").glob("*.py"))
    }
    tmp = args.output.with_suffix(".tmp")
    tmp.write_text(json.dumps(report, indent=2) + "\n")
    tmp.replace(args.output)
    print(
        json.dumps(
            {
                k: report[k]
                for k in (
                    "status",
                    "requested_matches",
                    "completed_matches",
                    "blockers",
                    "resources",
                )
            },
            indent=2,
        )
    )
    raise SystemExit(0 if report["status"] == "ready" else 2)


if __name__ == "__main__":
    main()
