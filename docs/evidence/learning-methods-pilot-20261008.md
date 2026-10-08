# Learning-method comparison and visual pilot — 2026-10-08

## Relevant designs

| Reference | Useful idea | Limit for this project |
| --- | --- | --- |
| [OpenAI Video PreTraining](https://openai.com/index/vpt/) | Train an inverse dynamics model on a smaller set with known actions, then label larger unlabeled video sets and learn a behavior prior. | A video alone does not identify exactly which action was taken; a verified action seed is required. |
| [AlphaStar paper](https://www.nature.com/articles/s41586-019-1724-z) | Learn from expert replays before reinforcement learning and evaluate by actual games. | StarCraft replay data exposes structured observations and actions; TFT broadcast pixels do not. |
| [Leela Chess Zero overview](https://lczero.org/dev/overview/) | Separate position evaluation, legal move policy, and search; measure play strength on games. | Chess starts from an exact board state. It cannot repair a missing or incorrect TFT visual state. |
| [TFT-OCR-BOT](https://github.com/jfd02/TFT-OCR-BOT) | Read round, gold, shop, items, bench, and board with OCR and fixed regions. | Its own README requires English and 1920×1080 borderless mode; fixed geometry is brittle across layouts and recordings. The code is GPL-3.0 and was not copied. |
| [TFT AI Coach](https://github.com/HamieXD/tft-ai-coach) | Capture a screen frame and request structured tactical output from a vision model. | It uses a remote or local general vision model and reports feature claims, not a demonstrated learned action policy or independent accuracy benchmark. Periodic screenshots alone lose short player actions. |

## Controlled OCR pilot on the same frame

The local high-level-player video `first6h-indexed-20261007.mp4` is 1920×1080. At timestamp 3600 seconds, the frame visibly shows stage **4-2**, **41 gold**, shop names **Lillia, Brambleback, Lillia, Mama Beak**, and an item tooltip headed **Lucky Item Chest**. This was manually checked against the image. Tesseract 5.3.4 read fixed crops after 3× enlargement. The same frame was then downsampled to 640×360 and enlarged back to 1920×1080 before the same OCR procedure.

The 1080p crop rectangles `(left, top, right, bottom)` were stage `(748, 0, 817, 38)`, gold `(980, 871, 1057, 919)`, shop `(547, 1007, 1555, 1080)`, and item tooltip `(69, 636, 483, 839)`. Numeric crops used Tesseract page segmentation mode 7 with a digit/hyphen whitelist; text crops used mode 6. The single-frame outputs below are direct tool observations, with no lexicon correction.

| Field | Native 1080p OCR | Simulated 360p OCR |
| --- | --- | --- |
| Stage | `4-2` | `4-2` |
| Gold | `41` | `4` |
| Shop names | All four readable, with noisy trait/cost text | Several names corrupted (`Lilba`, `Brambledack`, `Ul`) |
| Item tooltip | Heading and instructions readable | Heading readable, most instruction words corrupted |

This is one diagnostic frame, **not** an accuracy estimate. It isolates source resolution as one cause of the poor shop/item reading in the 640×360 VODs. Upscaling does not restore lost text. Eleven neighboring seconds in the same 1080p VOD also showed why a scene/phase gate and temporal memory are needed: camera scouting and an item-choice overlay temporarily hid or moved the shop and gold. Raw OCR fluctuated even when the match state was unchanged.

## Decision for the next experiment

Use a two-part local observation pipeline: a visual scene/phase gate, then high-resolution OCR for text and numbers plus image recognition/tracking for board units and item icons. Keep state across frames with explicit unknown values when an overlay hides a field. Capture denser visual transitions during planning, with before/action/after at roughly one-second or faster intervals. Verify a small seed of actual purchases, rolls, level-ups, item equips, positioning changes, and opponent scouting. Only then evaluate an inverse-dynamics model and any pseudo-labels, with whole matches held out. The Rust decision engine should receive the verified structured state and uncertainty; the voice layer explains its recommendation.

The current 1,000-triplet experiment measured visual continuity only (153/457 to 161/457 on a source holdout) and yielded zero confirmed actions. It cannot yet establish that the coach understands the game.

## Local evidence

- Native frame: `/mnt/sherlock-ssd/AgenteTFT/diagnostics/learning-methods-pilot-20261008/k3soju-3600.jpg`
- Neighboring frames: `/mnt/sherlock-ssd/AgenteTFT/diagnostics/learning-methods-pilot-20261008/second-01.jpg` through `second-11.jpg`
- Earlier visual training report: `/mnt/sherlock-ssd/AgenteTFT/diagnostics/visual-learning-1000-game-v4-20261008/report.json`

No external project code, video, or model weight is copied into Git.

## Dense 1080p action pilot

A second pass used a 15-second planning interval from the same native 1920×1080 VOD. Frames were sampled at 5 fps (75 images, 74 adjacent transitions). The local review queue ranks changes in the stage, gold, shop, bench, and board regions; **it does not assign an action label**. Manual before/after review established five rerolls, one Morgana purchase, and one unit sale. Each record in [the review manifest](dense-visual-actions-20261008.json) has source/frame hashes, gold, shop evidence where visible, and a rationale. The hashes were checked against the local images. This is a strong visual inference, not input-event ground truth.

The top-ranked transition was **not** a reroll: dragging a unit over the sell zone hid the shop, then revealed it. Another reviewed pair had the shop reappear after dragging while gold stayed at 68; it is recorded as a hard case rather than a negative label for all actions. These examples show why shop pixel difference or a single OCR reading cannot safely become a training target.

The queue and review can be reproduced locally with `training/mine_dense_action_candidates.py` and `training/validate_dense_action_review.py`. The source VOD and 75 JPEGs stay on the SSD under `/mnt/sherlock-ssd/AgenteTFT/diagnostics/dense-visual-vod-20261008/`. The review manifest is small enough for Git; no media, weights, or private media URL are committed.

This seed demonstrates that high-resolution short transitions expose real decisions lost by 5-second gaps. It is **one match and three action classes**, heavily dominated by rerolls. It cannot support a general TFT action policy or an out-of-match accuracy claim yet. Next, mine distinct matches and phases, collect deliberate counterexamples and input-event labels from our own replay/capture where possible, then evaluate a visual action model with entire matches held out. Preserve unknown labels when board/item/opponent state is obscured.
