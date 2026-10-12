# Akash player-policy job, patch 18.4B

The job is capped at nine hours of **wall-clock time**, including restarts. Only
reviewed Challenger match clips encoded at 1920×1080 may enter the dataset.
Original multi-hour Twitch archives are source containers, not training episodes.

`python -m training.akash_policy_supervisor` runs three independent gates before
starting a child trainer: reviewed match selection, reviewed action features,
and full-match simulator audit. Synthetic Dyna branches cannot become 18.4B
policy labels until the simulator matches the patch and passes replay validation.
The currently bundled synthetic laboratory is not an alternative 18.4B engine.

For an Akash deployment, mount provider **persistent** storage at `/workspace`.
Place the repository, source clips, reviewed dataset, trainer and the supervisor
work directory there before launching. The container command should re-run the
same supervisor invocation after a restart. It writes `job.json`,
`training.log`, `checkpoint.json` and the checkpoint artifact in that volume.
The child trainer must accept `--resume`, save a checkpoint and its SHA-256 seal
atomically after bounded batches, and create `complete.flag` only after a final
checkpoint. The supervisor refuses changed commands, missing or corrupt
checkpoints, and starts after the original deadline. A crashed batch can be
repeated, but saved batches are preserved.

The user's PC is not part of the running job once all files have reached the
remote persistent volume. Persistence covers a container restart in the same
lease; a closed lease or lost provider volume still requires an external backup
and a new deployment. No Akash job should be opened while the preflight is
blocked. No weights are promoted automatically.

Current state (2026-10-12): one complete-match 1080p candidate clip was
separated from a Setsuko Twitch VOD. Its result is visibly first place. A
5 fps review pass produced 10,100 native-resolution frames and 10,099 visual
transition candidates. One actual buy-XP action at stage 3-1 is now reviewed:
34→30 gold and level 5 at 18/20 XP → level 6 at 2/36 XP. The other visual
transitions have not been labeled as actions; many are cinematics or choice
overlays. `training.simulate_reviewed_economy_branches` is enabled for this
reviewed decision and verifies immediate gold, level, and XP branches against
the video. It generates no match result or policy preference label. The
client patch, enough independent reviewed decisions, and two additional
complete matches remain unverified. The full 18.4B simulator audit is blocked,
so the nine-hour player-policy job is not yet launchable.
