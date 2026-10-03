# HM4.2 field test — 2026-10-02

Aggregate-only comparison of the prior HM4 natural capture and the new HM4.2 natural 1920×1080 capture. No user images, crops, raw telemetry, account identifiers or trained weights are committed.

## Session integrity

New field session:
- policy: `hud_mapper_hm4_auto`
- elapsed: 2179.74 s (~36m20s)
- source frames: 13,858
- reader records: 1,094
- error: null
- neural mode: disabled
- marker: PARTIAL only because the UI `ENCERRAR` path set the generic cancellation flag; evidence files and hashes were produced.

The HM4.3 branch changes explicit user stop to a graceful sealed completion while preserving error/time-out partial semantics.

## Latency / throughput

| Metric | Prior field session | HM4.2 field session | Change |
|---|---:|---:|---:|
| reader source→result p50 | 6240.90 ms | 2103.99 ms | -66.3% |
| reader source→result p95 | 9107.65 ms | 4929.57 ms | -45.9% |
| reader queue p50 | 471.10 ms | 234.19 ms | -50.3% |
| reader queue p95 | 1004.27 ms | 564.49 ms | -43.8% |
| latest-frame replacement | 81.0% | 69.7% | -11.3 pp |
| completed reads / submitted | 18.9% | 30.3% | +11.5 pp |
| completed reader records / second | 0.179 | 0.502 | 2.80× |

HM4.2 executed 1,083 native reader runs plus 11 exact full-source cache deliveries. The full-source cache itself is rare (~1.0%), but the Rust worker's exact per-ROI cache was heavily used:
- stage: 91.3%
- gold: 75.4%
- level: 85.7%
- XP: 83.3%

Shop cadence reuse was recorded 392 times. Fresh shop-card work still has p50 ~1741.5 ms. The synchronous HP path remained the dominant always-on cost: HP p50 ~1073.7 ms and p95 ~2436.2 ms.

## Observation usability (not accuracy)

There is no independent ground truth in either session. These are only rates of usable reader observations when the field was eligible.

| Field | Prior | HM4.2 | Delta |
|---|---:|---:|---:|
| stage | 81.9% | 79.7% | -2.2 pp |
| gold | 69.6% | 71.8% | +2.3 pp |
| level | 69.9% | 73.6% | +3.7 pp |
| XP | 69.9% | 73.6% | +3.7 pp |
| HP | 87.5% | 80.9% | -6.6 pp |
| buy-XP control | 98.5% | 99.6% | +1.1 pp |
| lock control | 99.5% | 97.1% | -2.4 pp |
| refresh control | 97.0% | 96.9% | -0.1 pp |

Shop card usable (fully + partially readable) rates:
- slot 0: 81.4% → 88.2%
- slot 1: 72.4% → 76.4%
- slot 2: 67.8% → 79.4%
- slot 3: 87.4% → 91.0%
- slot 4: 74.9% → 67.6%

Do not interpret these percentages as semantic TFT correctness. Unknown, partial and accepted are reader states, not labels.

## HM4.3 response

The next branch deliberately does **not** change OCR thresholds or promote any model.

1. HP gets an independent 1 Hz latest-only queue instead of blocking every HUD publication.
2. HUD reader results use only causal HP evidence from the same geometry segment.
3. HP evidence older than 2 s is marked `async_stale` and is not surfaced as a current numeric HP value.
4. HP latency/queue statistics are reported separately.
5. Explicit UI `ENCERRAR` becomes a graceful completion; errors remain partial.
6. L2 remains shadow diagnostic only; no GameState write, training-label permission or silent profile promotion.

Next field proof: package HM4.3 in Windows CI, run a natural 1920×1080 match, then compare HUD p50/p95 and independent HP freshness against this HM4.2 field baseline.
