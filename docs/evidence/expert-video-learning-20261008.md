# Expert VOD learning checkpoint — 2026-10-08

## Current evidence

- Four hash-verified, user-provided YouTube/Twitch VODs with timestamped ASR were indexed (12.95 hours). Three shorter guide sources in the ASR manifest have no segment files in the current corpus and were excluded rather than reported as processed.
- The tactical speech index contains 591 candidate passages. A 32-dimensional latent text representation and diversity selection reduced these to 160 moments for review.
- A CPU temporal-context encoder trained on 417 near-versus-distant speech pairs from three VODs. On 40 pairs from the held-out fourth VOD, pair ranking improved from 28/40 to 31/40; the best checkpoint was at epoch 20. This is a small, source-limited context test, not game-strategy accuracy.
- All 160 selected moments have before/during/after visual frames (480 frames total) on the SSD. Frames and model weights are not in Git.
- The previously reviewed demonstration corpus contains three move transitions. The new speech and review frames yielded **zero new executed-action labels**. No expert imitation policy was trained or promoted.
- A second queue samples 2,000 distinct time points from three high-level-player sources: Dishsoap's tournament VOD, Wasianiverson's Challenger VOD, and BrosephTFT's ranked guide. Source hashes and the reason for qualification are recorded in `configs/training/high-level-vods-20261008.json`. The four-source collection above remains separate.
- The 2,000-point queue has 1,217 segments classified as general context. Theme detection is lexical and may have both misses and false positives. Those segments are retained for chronology and visual review, but are not presented as strategy learned. The remaining segments are only candidate TFT-related speech.
- The 2,000-passage CPU context model improved held-out speech-pair ranking from 0.5852 to 0.5919 at its best epoch, an inconclusive gain. It does not predict actions or wins. Portuguese translations are automatic, unreviewed, and can mistranslate TFT terms; the terminal displays the English original alongside them.
- One frame per time point was extracted from existing local copies, with source hash verification and no new video download. The extraction report records 2,000/2,000 frames. This is coverage for viewing, not proof that all frames depict playable TFT states.

## Data boundary

The indexed passages are speech observations. They can include hypothetical plays, other players, past rounds, and transcription errors. The visual triplets are review candidates. Only a visible and independently checked state-to-action transition may become a policy label. Patch identity and whole-match boundaries must be checked before a policy train/validation split.

## Next substantive step

Review the 160 visual windows for actual executed actions, reject combat/scouting-only windows, bind the patch and match for accepted transitions, and then train/evaluate a policy on whole-match holdouts. Keep this distinct from the synthetic match MVP; no additional simulation was run in this checkpoint.

## Local artifacts

- `/mnt/sherlock-ssd/AgenteTFT/diagnostics/expert-video-memory-20261008/`
- `/mnt/sherlock-ssd/AgenteTFT/diagnostics/expert-context-learning-20261008/`
- `/mnt/sherlock-ssd/AgenteTFT/diagnostics/expert-video-review-20261008/`
- `/mnt/sherlock-ssd/AgenteTFT/diagnostics/high-level-moments-2000-v2-20261008/`
- `/mnt/sherlock-ssd/AgenteTFT/diagnostics/high-level-context-2000-20261008/`
- `/mnt/sherlock-ssd/AgenteTFT/diagnostics/high-level-moments-pt-20261008/` (translation in progress)
- `/mnt/sherlock-ssd/AgenteTFT/diagnostics/high-level-frames-2000-20261008/`

## Pending at this commit

The visual sequence experiment is being built separately in `training/visual_context_1000.py` and `training/train_visual_context_1000.py`. It is not included as a validated model in this checkpoint. The first unfiltered sample contained menu frames; a visual scene filter is being applied before training. The partial first triplet directory is not training evidence.

No credentials, media, large model, or automatically inferred action label is committed.
