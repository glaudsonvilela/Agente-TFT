# Selected unit evidence, 2026-10-07

The tooltip miner now checks for a cyan selection halo below a detected unit
and records its shape independently of the OCR name. This replaces raw cyan
pixel ranking, which ranked a coloured unit above the visibly selected Camille
in one review frame. The halo requires pixels on both sides of the unit and a
vertical spread; a narrow combat effect or one-sided glow is rejected.

On the saved review frame at source second 120, the tooltip reads Camille and
the selection halo belongs to marker 2. A local one-frame-per-second extraction
around this event reads the same tooltip in three consecutive frames and finds
the same halo in the last two. These observations are from one event in one
VOD, so they are **not** an independent accuracy benchmark. No automatic
training label or live champion ID is emitted by the miner yet.

The first attempt to replay 360 saved frames recovered only two names because
the coin/cost icon was OCRed as `a3`, `ain`, or `a`, appended to the champion's
name. The tooltip-specific matcher now strips one short trailing OCR glyph
group when it begins with `a`; the strict shop-name matcher remains unchanged.

The completed 360-frame review recovered five exact tooltip names. Four had
one selected halo candidate; the combat frame had none. A separate 229-frame
VOD recovered two exact tooltip names and no cyan halo candidates, because
that arena uses a different selection effect. These are sparse event counts,
not precision or recall. The 12-frame dense window around the Camille event
produced two consecutive automatic anchors after the second halo was selected
by strong dominance over a partially overlapping bar. The original
cyan-count adjudicator could have attached a tooltip to the wrong unit. It
now requires the halo shape and two distinct consecutive frames; its singleton
exception and 20-second tracking window have been removed. The two sparse
review sets correctly produce zero training anchors under this rule.

No model was updated and no live champion ID was released. Unrelated training
files in the main worktree were not modified. The current active coaching
catalog still targets patch 18.3B.

The second VOD's arena renders a pale blue halo. A second shape channel now
finds the selected Camille on its bench without accepting the narrow combat
effect in the first VOD. A 60-frame dense window from that distinct VOD
produced three additional direct Camille anchors; together the two sources
provide five distinct crop pixels. The frozen head supported one, gave mixed
evidence for two and disagreed with two. Across both arenas, the minimum DINO
similarity among the five same-unit anchors was 0.516. This is evidence of a
domain shift in the current crop/encoder representation, not an accuracy
estimate. The model and live coach remain unchanged while that representation
is corrected and independently measured.

A third, warm halo channel found the selected Ornn in the second VOD's saved
review frame. It did not add an automatic label: the OCR confidence for that
frame was about 91.8, below the 94 threshold, and a dense one-minute window
provided only one additional shape candidate. This illustrates the
fail-closed rule for sparse or weak names. The corresponding Rust test checks
that a warm ellipse passes while a one-sided warm flash fails.

Pending: compare more arena styles, improve cross-arena foreground features,
and evaluate a new model on matches kept out of training.

The full six-hour evaluation VOD was collected in annotation-only mode at
one saved frame per ten seconds: 2,160 review frames and 9,554 unit crops.
The tooltip miner is scanning these frames. Its proposals are observations,
not labels or an accuracy estimate. The separate training VOD supplies the
only eligible source for automatic training anchors.

Partition provenance is now carried from the verified collection report into
tooltip and shop proposals, then into consensus labels. Evaluation labels are
kept for held-out measurement with `training_eligible=false`; missing or
inconsistent partitions are rejected. The Rust adjudicator, temporal
propagator and weighted trainer reject non-training gold. Legacy tooltip and
shop labels without a partition must be regenerated before training. The
previous two Camille anchors from the evaluation VOD must never be used for
training, regardless of the earlier output's `training_eligible` flag.

The first regenerated dense training window produced two direct Camille
anchors at nominal seconds 11529 and 11530. Eight tooltip proposals were
inspected; three had OCR below 94, three lacked a strong selected-unit
association, and two met the temporal rule. These two are training eligible
because the source is in `training_pool_unlabeled`. This is label evidence,
not proof that the current classifier recognizes Camille in live play.

The independently regenerated dense evaluation window produced three
Camille anchors at nominal seconds 122–124. All three are explicitly marked
`evaluation_unlabeled` and `training_eligible=false`. They can measure a
challenger trained only on the separate training source, but cannot support
the training corpus.

The complete sparse evaluation scan inspected all 2,160 saved frames and
found 52 tooltip proposals. A new reproducible dense-window orchestrator
selects only exact catalog names with a plausible selected-unit halo, checks
the source and partition against the collection report, and reruns the Rust
collector and miner at one frame per second. It planned 16 evaluation windows;
the first window yielded four held-out Camille anchors. The remaining windows
are still being processed. A matching full-video annotation-only collection
from the separate training VOD is in progress. Neither collection updates
model weights or grants runtime approval.

The first dense pass exposed a collection error: it inherited the sparse
`keyframes` decoder mode. In the Varus window, nominal seconds 430 and 431
had the same frame and crop hashes, so they were correctly rejected as one
observation rather than two confirmations. Dense windows now use the full
decoder with one sampled frame per second. The earlier keyframe windows remain
diagnostic only; new output directories preserve the evidence of the issue.
The separate training VOD's full sparse annotation collection has completed:
1,374 saved review frames and 6,466 unit crops, with zero inferred labels.
