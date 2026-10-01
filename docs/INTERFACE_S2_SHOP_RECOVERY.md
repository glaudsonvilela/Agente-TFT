# S2 — panel evidence independent of button text; field-local OCR conflicts

Base: S1 `be06c9eff84970b97555306046d0d88ff15c1bbc`. Local replay work only.

## Received S1 measurement

40 frames, 29 panels located, 11 unresolved; 200 slots: 84 full text/price,
20 partial, 4 empty markers, 37 unknown, 55 unavailable. 58 OCR calls.
Runtime reported p50 449.557092 ms and p95 505.492433 ms per frame; these include
decoding, localization, preparation and OCR. They are not training time or
per-field latency. No ground truth, catalog binding, GameState update or promotion.

The source log does not include native per-word traces or code-review findings.
The 22 structural findings remain pending; zero structural errors is not a full
semantic review. No claim that every accepted name or price is correct.

## Findings from code and available images

S1 requires both button-label templates. Disabled/hovered controls can therefore
hide a shop that is otherwise visible. In the supplied original frames, the
shop is visible at 250000 and 1250000 ms while buttons are darkened. Screen
appearance, not a label/expected price, motivated the recovery landmarks.

S1 also turns any TSV word without exactly one containing tile into a global
conflict for all fields of that scale. This can erase otherwise usable unrelated
fields. Without the user's complete native report we cannot attribute every
unknown slot to that issue. S2 exports explicit routing traces to measure it.

## Changes

- Optional companion `configs/ui/match001-shop-recovery-v2.json`, bound to the
  existing parent UI ID. Original slot rectangles/empty template remain unchanged.
- Two structural border anchors outside all card rectangles; both must pass
  similarity >=0.95. Only tried when the two original anchors fail.
- Recovery does NOT assert buttons enabled, a valid transaction or that every
  card is visible. Per-field text and empty-marker checks still run afterwards.
- S2 atlas words are assigned only by bounding boxes. Cross-boundary words taint
  just the fields they intersect. Gutter-only words remain in trace and are not
  assigned to any field. Ambiguous words never get guessed by nearest neighbor.
- Names/prices still require two eligible scales (3x/4x), minimum word confidence
  >=0.70 and strict agreement. No new OCR calls, price dictionary or season list.
- S1 remains selectable by omitting the companion profile. Both modes share
  preparation, parsing and decoding; no cloned season-specific reader.

Diagnostics include fallback scores, affected slot/field, word boxes and orphan
counts. Fallback geometry was seeded from 150000 ms, already used in S1. This is
same-recording calibration, not an independent evaluation.

## Deliberately unchanged / not finished

The empty-marker classifier is unchanged. An unread slot is NOT called empty.
Neither this patch nor a better comparison proves purchases, catalog identity,
lock/button states, temporal consensus or the board/bench detector.
The unresolved season/patch remains unknown; names are observed strings, not
canonical champion IDs. No fuzzy spelling correction or latest catalog substitution.
HP quarantine and A14/A15/A16 databases are unchanged. No service or training.

## Comparison runner

```
bash scripts/probe_match001_shop_v2.sh telemetry/data/match-001-shop-s1.sjWxJi2V
```

Before compilation/OCR, checks the S1 report/manifest completion hashes and the
same current image hashes/timestamps/UI. S2 compiles only the shop executable in
`rust/target/shop-s2`, leaving S1 shop and frozen HP3 binaries untouched. Reuses
40 JPEGs; does not extract the MP4. A fresh evidence directory contains environment,
whole-tree structural audit, raw TSV routing evidence, full report and comparison.

The comparison uses the HISTORICAL S1 report, not a simultaneous baseline run.
It checks frame identities, context, aggregate counts and completion hashes;
hashes are integrity checks, not signatures or truth labels. New name/price reads,
losses and disagreements remain distinct. Different text does not silently become
a spelling fix. Historical timing differences are not controlled benchmarks.
No evaluation activates a reader or turns its outputs into training labels.

## Tests

Rust: isolated contained/crossing/gutter words, overlapping tiles, low-confidence
crossing geometry, half-open boundaries and preserved acceptance threshold.
Native media: both old labels absent, two structural anchors present; empty,
unknown and hidden remain distinct; invalid parent/weak thresholds/card-overlapping
landmarks are rejected. S1 tests remain mandatory.
Python: sealed evidence, mismatched pixels/context, contradictory names, lost
readability, source preflight and unchanged side-effect constraints.

Local inspection used Python/Pillow for geometry on the mounted JPEGs. Cargo is
not installed in the editing container and clone failed DNS, so native compilation
and tests are delegated to CI, not claimed locally. Actual S2 Match001 measurement
is pending the user's Ubuntu run. Final CI numbers are recorded in the PR.

Next: evaluate S2 output, then complete controls and explicit catalog context,
continuing toward bank/board. Avoid another remote infrastructure detour.
