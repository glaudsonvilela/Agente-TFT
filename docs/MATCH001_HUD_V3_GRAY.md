# Match001 — HUD v3: grayscale, line segmentation and neutral glyph projection

Base: `4bda4fb3d5d2cfe62a7307ea91874365744813fb`.
Branch: `work/match001-ocr-gray-v3-2026-10-01`.

## Status and scope

Opt-in calibration candidate, NOT a promoted visual baseline. Changes only HUD
preprocessing, OCR options and conservative read validation. No OpportunityWeights,
strategy changes, input automation, HP, board, shop or player-list changes.
The v1/v2 JSONs and the v2 runner remain unchanged. All four ROI rectangles in v3
are identical to v2, including the unresolved initial-stage displacement.

## User-reported baseline

The user's v2 run at `telemetry/data/match-001-hud-v2.pfj6GDxL/report.json` reported:

| Field | Labeled | Agreed | Unknown | Read but disagreed |
|---|---:|---:|---:|---:|
| gold | 35 | 14 | 21 | 0 |
| level | 35 | 29 | 4 | 2 |
| xp | 35 | 1 | 34 | 0 |
| stage | 38 | 33 | 5 | 0 |

Level disagreed at 1400000 and 1900000 ms: expected 8, read 3,
confidence 0.7473866. These are disagreements with unreviewed AI labels, not
independent human ground truth. No unknown or disagreement is removed.

## Measured prototype BEFORE the Rust run

A bounded local prototype used the recovered original JPEGs from
`TFT_MATCH_001_AI_BATCH.zip`, the existing prelabels, Pillow JPEG decode and
Tesseract **5.5.0**. Three fixed scales (3, 4, 5), inverted grayscale, 10 pixels of
artificial background after upscaling, and PSM 7. One multi-page TIFF OCR process
per field/profile; no exhaustive parameter search. Labels were used only in the
comparison after image processing/recognition.

| Prototype | Labeled | Agreed | Unknown | Read but disagreed |
|---|---:|---:|---:|---:|
| xp, grayscale | 35 | 35 | 0 | 0 |
| level, grayscale | 35 | 35 | 0 | 0 |
| gold, grayscale alone — rejected candidate | 35 | 22 | 12 | 1 |
| gold, neutral-color projection + grayscale | 35 | 35 | 0 | 0 |

These are calibration-set **prelabel agreement** measurements, not generalization,
human accuracy, a held-out test, or measurements of the Rust executable. The user's
Tesseract version, single-image invocation and FFmpeg JPEG decode may differ.
The Rust rerun below is required. In particular, do NOT report the prototype's
35/35 as already measured on the user's PC. Stage was not rerun in the prototype.

## Algorithm and safeguards

The original mean-threshold + nearest-neighbor path remains the default
`image_mode: legacy_binary`. New policy fields have serde defaults.

`gray_bilinear`: existing BT.601 integer luma and contrast stretch, integer
center-aligned bilinear enlargement with one final rounding, optional inversion,
then a constant 10-pixel border. No pre-OCR binarization removes the antialiasing.

`neutral_gray_bilinear` (gold only): before contrast stretch, project each pixel
as `max(0, luma - 2 * (max(R,G,B) - min(R,G,B)))`. The chromatic coin fragment
visible at the left edge of the measured ROI is suppressed; neutral light glyphs
are preserved. This is a pixel transformation, not deletion/invention of a
recognized digit. No pixel coordinate, expected gold, or timestamp selects it.
This mode is specific to light neutral glyphs; colored glyphs/other skins and
other replays remain unvalidated.

The v3 policies use `page_segmentation: 7` explicitly. The backend preserves the
original stage=7 and other-fields=8 defaults for older layouts. A backend that
does not support an explicit PSM returns an error rather than ignoring it.

`min_confidence=0.70`, `ambiguity_margin=0.03`, and three attempts are unchanged.
The new XP policy requires the `/` separator and then uses the existing fraction
parser; slash loss cannot silently turn `0/10` into 10. Legacy numeric XP remains
supported by the old policy. Domain validation remains mandatory.

Ambiguity now checks the highest-confidence *distinct value* across all attempts:
two repeated agreeing candidates cannot hide a third contradictory candidate
within the same 0.03 margin. This conservative correctness fix also applies to
the legacy reader; it can suppress a formerly accepted ambiguous value.

Policy validation bounds attempts, scale and PSM. New image paths validate ROI
buffer/stride/pixel format and bound scaled allocation. No new crate dependency.
The existing `read_roi_robust` is used by both the HUD pipeline and sparse probe.

Reference for trying grayscale/inversion, bounded borders and line segmentation:
https://tesseract-ocr.github.io/tessdoc/ImproveQuality.html
The neutral-color projection is this project's experimental transformation, not
a claim from the Tesseract documentation.

## Validation and continuation

Rust coverage adds interpolation/stride/color/bounds tests, old-policy defaults,
explicit PSM dispatch, slash loss, low confidence, impossible fractions, third-
candidate ambiguity, and a real Tesseract blank-line smoke test. CI installs
FFmpeg, FFprobe and Tesseract instead of silently skipping external media smoke.
It still does not contain Match001 or measure game HUD accuracy.

Four Python config tests enforce identical ROIs, unchanged stage, fixed thresholds,
three attempts, color projection only for gold and fraction validation only for XP.

After green CI and merge, on the user's Ubuntu:

```bash
cd "$HOME/Agente-TFT" && git switch main && git pull --ff-only && bash scripts/probe_match001_hud_v3.sh
```

Uses only existing JPEGs/prelabels; no full-video pass. A unique
`telemetry/data/match-001-hud-v3.XXXXXXXX` contains report.json, events.jsonl and
environment.txt (commit, tool versions and hashes of labels/layout). No labels or
prior evidence are overwritten. Return code 0 means diagnostic completion, not
Promotion Gate approval. Keep prelabel agreement distinct from exact accuracy.

Next: compare the Rust v3 output with v2 on the same labeled timestamps; inspect
remaining disagreements/unknowns. Then handle the measured initial-stage anchor
shift and the other stage failures, review human labels and validate on a separate
replay before progressing to dynamic HP and shop recognition.
