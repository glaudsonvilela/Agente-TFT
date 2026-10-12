# Experimental Setsuko video-state test (patch 18.4B)

## Result and scope correction

The run on DSEQ 29027458 ended after 49 epochs (608 seconds). On its untouched
test match it lost to last-value persistence for stage, gold, and level. The
downloaded report and sealed checkpoint are under the local experiment's
`akash-experimental-state-10h-20261012-ready/results/` directory. Do not
promote or repeat this model as an imitation learner.

The seven complete 1920×1080, 60 fps match videos remain on local disk (about
11.7 GB). **The Akash package did not contain those videos.** It contained
1,009 still frames, one every 15 seconds (227 MB archive). It also contained
no executed-action labels for the trainer. Therefore this run never watched
continuous gameplay and never learned the player's decisions. The packaging
command now rejects another sparse upload unless
`--allow-sparse-state-experiment` is explicitly supplied. A future imitation
experiment requires continuous match coverage, verified state/action timing,
and held-out action evaluation before a paid deployment.

This is a **separate, capped 10-hour experiment**, requested after the
full-match player-policy preflight found that action labels and a validated
18.4B combat simulator are missing. It does **not** train a TFT player or
estimate win rate. It asks a narrower question: can a small visual model
predict visible stage, gold, and level 30 seconds later more accurately than
copying the current value?

The local corpus contains seven complete Setsuko Challenger clips from three
Twitch VODs, 15,118.370 seconds (4 h 11 min 58 s) of native 1920×1080 video.
Its portable metadata and video hashes are saved in
`configs/training/setsuko-18.4b-complete-match-corpus-20261012.json`.
Only match-sized intervals were downloaded. The original source VODs were not
downloaded in full, and no further videos will be fetched for this test.
The client patch number remains unverified in the captured frames; the VOD
dates follow the 18.4B release. The corpus manifest records clip hashes,
source intervals, known results, and unknown results explicitly.

`training.prepare_experimental_state_index` samples one native-resolution frame
every 15 seconds and runs sparse OCR. An OCR reading may be wrong or absent and
must never become an action or reward label. The model sees a 320×180 resized
copy of each 1080p frame plus available current HUD readings. The source images
remain 1080p; resize is an internal network input, not a 720p video source.
The target is the visible HUD reading two samples later. All examples from
Twitch VOD `2894958056` are withheld from optimization. Its first match is
used for validation and early stopping; its second match is read once at the
end as an untouched test. The report includes per-field observation counts, model MAE, and
last-value persistence MAE (stage in stage steps, gold in coins, level in levels).
A model that fails to beat this baseline has not
demonstrated useful future-state prediction.

The eight reviewed XP/reroll scenes are carried as a **separate** economy
branch artifact. Those scenes verify only immediate local changes and unknown
reroll outcomes. They create zero strategic preference labels. The full-match
simulator and `training.akash_policy_supervisor` gate remain untouched.

`training.package_experimental_video_state_akash` emits a signed input archive,
20 MB upload parts, a secret-bearing SDL, a private curl configuration, and a
resume-safe upload helper. It does not create a lease. The SDL requests one
RTX 3090 and 20 GiB of provider persistent storage at `/workspace`; inspect
the actual provider bid before accepting. After upload, the receiver assembles
and verifies the archive on the remote volume, then starts the supervisor.
`training.experimental_video_state_supervisor` persists the 10-hour wall-clock
deadline, hash-sealed checkpoints and job status. A container restart in the
same lease resumes from the checkpoint without the local PC. A closed lease or
lost provider volume is outside that guarantee. The trainer may stop early
after 15 validation epochs without improvement to avoid burning paid time.
No model is promoted automatically.

Before launch, run a local one-epoch smoke test, verify the native frame count,
inspect the package summary, and confirm the lease's real hourly bid and
persistent-storage offer. After launch, `/status` reports progress and the
authenticated `/download/` endpoints expose the report, log, and weights.
Run the generated `fetch-results.sh` and verify its checkpoint hash **before**
closing the lease; Akash deletes provider-local persistent data when a lease
ends.
