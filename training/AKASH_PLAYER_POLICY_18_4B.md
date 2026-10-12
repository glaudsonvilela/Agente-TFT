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

Current state (2026-10-12): seven complete-match 1080p clips were
separated from three Setsuko Twitch VODs without downloading any whole archive.
Their source-video durations total 4 h 11 min 58 s. The first result is visibly
first place; the second match shows loading, stage 1-1 through 7-1, the end
animation and return to queue, but its placement is not labeled. The third
shows loading, stage 1-1, elimination, and return to queue. The fourth clip
is from an independent VOD and also shows loading, stage 1-1, and the end.
A 5 fps review pass produced 10,100 native-resolution frames and 10,099 visual
transition candidates. Eight actions are reviewed: six XP purchases and two
rerolls. One XP purchase at stage 3-1 changed 34→30 gold and level 5 at 18/20
XP → level 6 at 2/36 XP. The other visual transitions have not been labeled
as actions; many are cinematics or choice overlays. A separate five-second HUD
index of the first complete match contains 404 chronological observations:
stage in 359, gold in 269, and level in 330. Missing readings remain unknown.
The second match has 450 five-second observations: stage in 404, gold in 287,
and level in 351. These sparse HUD observations are not action labels.
`training.simulate_reviewed_economy_branches` verifies immediate economy
branches against these video decisions. For rerolls, the next shop is recorded
as an observed outcome and never exposed as a pre-action prediction. It
generates no match result or policy preference label. A portable source
package includes the whole 1920×1080 first clip, reviewed evidence frames, timeline
and local branch results; its `episode.json` explicitly reports that policy
training is not ready. The seven-video corpus and its explicit readiness flags
are under `experiments/player-policy-video-18.4b-pilot-20261011/complete-match-corpus-1080p`
outside the Git repository. The client patch and complete observable state per
action remain unverified. The full 18.4B simulator audit is blocked, so the
nine-hour player-policy job is not yet
launchable.

The separately authorized **10-hour experimental video-state test** is described
in `training/EXPERIMENTAL_VIDEO_STATE_18_4B.md`. It predicts visible future HUD
values from complete-match frames, reports held-out VOD metrics, and checks the
eight reviewed economy branches separately. It does not bypass the policy gate
or claim to learn full-match strategic play.
