# Visual expert VOD checkpoint — 2026-10-08

## What was actually observed

- Two hash-verified, high-level TFT VOD copies supplied the visual sample. The embedded-webpage guide source was excluded from this visual run.
- 1,000 time-spaced moments have before, during, and after frames, 5 seconds apart. Selection did not use transcript content, but the initial 2,000 timestamp pool came from speech segments. It is **not** yet independent full-video visual sampling.
- The older TFT scene gate proposed 1,060 candidates. A stage-HUD brightness check retained 1,010, from which 1,000 were selected. The gate had limited evaluation on one earlier match. Manual spot checks found browser/menu false positives before the brightness check; spot checks of the retained sample do not establish a full scene accuracy rate.
- A frozen int8 DINO image encoder embedded board, shop, and opponent regions. A small temporal head trained only on these images to match views from the same moment. Speech was not fed to this model.
- On the separate source video, same-moment pair retrieval was 153/457 before training and 161/457 after the fixed final epoch. The 8 additional matches are a small, possibly noisy gain in visual continuity. This is **not** decision, game-state, or win prediction accuracy.
- A review heuristic ranked 29/1,000 windows with a fairly stable stage HUD, visible shop before/after, and a changed shop embedding. Manual inspection of moments 101, 126, and 252 found round transitions in the first two and ambiguous shop changes in the third. No executed action is confirmed. Candidate deltas must never become action labels automatically.

## Why this does not yet teach play

The model does not identify the player's exact action, intent, outcome, or counterfactual alternative. Five-second gaps can contain a roll, purchase, round transition, UI overlay, camera shift, or several of these. The current 1,000 sequences help test whether the system follows visual context, but cannot train an expert imitation policy. The terminal viewer therefore presents original speech, automatic Portuguese translation, visual change, and an explicit unknown-action status.

## Next visual learning gate

Sample directly from video time during planning and shop interaction, at a denser rate. For each accepted transition, verify the pre-action board, shop, gold, level and stage; the visible action; and the post-action state. Bind patch and match identity. Split evaluation by whole match/source before training any policy. Keep uncertain transitions as unknown rather than guessed actions.

## Reproducible local artifacts

- Triplets: `/mnt/sherlock-ssd/AgenteTFT/diagnostics/visual-context-1000-game-v4-20261008/visual_triplets.jsonl`
- Visual learning report: `/mnt/sherlock-ssd/AgenteTFT/diagnostics/visual-learning-1000-game-v4-20261008/report.json`
- Action review queue: `/mnt/sherlock-ssd/AgenteTFT/diagnostics/visual-action-review-v4-20261008/action_review_queue.jsonl`
- Image encoder SHA-256: `5da185e587feee83a48d120cd57aa9f9f0c66d7adf3f6780764f6077a6cf8d35`

Frames, VODs, and model weights remain on the SSD, outside Git. No inferred labels or private media links are committed.
