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

Pending: compare more arena styles, improve cross-arena foreground features,
and evaluate a new model on matches kept out of training.
