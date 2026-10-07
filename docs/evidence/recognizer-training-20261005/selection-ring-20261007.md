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

Pending: rerun both VOD review sets, quantify false selection halos, and
require repeated name, halo and tracked crop agreement before promoting an
automatic label. Unrelated training files in the main worktree were not
modified. The current active coaching catalog still targets patch 18.3B.
