# One complete 1080p match at 10 fps — 2026-10-08

## Capture and integrity

The authorized high-level-player VOD contains a continuous match from source
seconds **2375 to 3900**. The interval begins as matchmaking is accepted,
includes loading and every game round, and extends past the result screen.
We extracted **15,250 numbered JPEG frames** at native **1920 × 1080** and
**10 fps**, with no missing frame numbers. There is no deliberate cut within
the interval. The source video, 4.85 GB of frames, and the full visual review
queue remain on the SSD under
`/mnt/sherlock-ssd/AgenteTFT/diagnostics/full-match-10fps-20261008/`.
The local `manifest.json` records the source hash, exact interval, extraction
settings, sample frame hashes, and the resumed extraction boundary. An
independent re-decode of seven frames spanning that boundary matched all seven
stored frames pixel for pixel. This verifies that resuming introduced neither
a dropped nor a repeated image there; it is not input-event ground truth.

## What this match actually shows

The manually checked [milestones](full-match-10fps-milestones-20261008.json)
tie visible state to hashed frames:

| Stage | Player HP | Gold | Level | Visible phase |
| --- | ---: | ---: | ---: | --- |
| 2-5 | 90 | 20 | 4 | combat |
| 3-1 | 80 | 50 | 5 | planning |
| 3-2 | 57 | 57 | 6 | combat |
| 3-7 | 40 | 66 | 7 | planning |
| 4-2 | 25 | 41 | 8 | combat |
| 4-5 | 13 | 0 | 9 | planning |
| 4-6 | 0 | unknown | unknown | 7th-place result |

This gives a complete economy, health, level, composition, and result
trajectory for studying the tradeoff between saving gold and stabilizing the
board. It does **not** prove that any one earlier choice caused the 7th-place
finish. The VOD also shows opponent boards, shop choices, item icons, tooltips,
combat, carousel, and overlays. Some overlays hide the shop or gold while the
stage remains visible; a player model must preserve an explicit unknown state.

The sparse HUD index contains **153 observations** at ten-second intervals,
with raw OCR and parsed *candidates*: stage in 118, gold in 105, level in 115.
These counts are coverage, **not accuracy**. One obvious stage OCR error read
`5-2` from a `3-2` frame. The index intentionally carries no action or
outcome labels. The full 10-fps frames are retained for short actions that a
ten-second index would miss.

The full visual queue contains **15,249 adjacent-frame transitions** and zero
automatic action labels. Manual review of high-scoring changes found camera
cuts, reward-panel animation, tooltip closing, automatic loot effects, and
combat transition effects. In one sequence, the game showed `Sell for 1g`,
but the dragged unit returned and gold stayed at 51. Labelling the prompt as
a completed sale would corrupt player training. These examples and frame
hashes are in [the hard-case review](full-match-transition-hard-cases-20261008.json).
The seven previously reviewed stage-4-2 actions (five rerolls, one Morgana
purchase, one sale) occur within this full match and remain visual inferences,
not recorded input events.

## Relation to a player IA

The target is a model that estimates game state, selects a legal action, and
learns from later rounds. This match contributes a long, ordered experience:
observations before and after choices plus the final outcome. The visual
change queue is only a **review queue**. Shop refreshes, purchases, level-ups,
unit sales, item equips, repositioning, scouting, animations, and natural round
transitions can look alike in pixels. Only checked action transitions should
become imitation targets; an unobserved action stays unknown. A 7th-place VOD
is useful for learning perception and consequences, but copying its decisions
as optimal play would be wrong.

Next, review action candidates across different rounds and classes, attach
the visible before/action/after evidence, and associate later combat/HP and
placement outcomes. Use whole matches from different games for holdout
evaluation. The Rust player can then compare legal choices using the current
structured state and uncertainty; the coach voice should explain that choice.
No trained player policy or claim of improved play comes from this extraction
alone.
