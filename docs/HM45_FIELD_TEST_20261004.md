# HM4.5 replay screen field test, 2026-10-04

Source: `hm4-20261004-005730-923603.zip`, SHA256
`6f0dc4002e64957518e4a6decfbb94cd77f1b54c6e8153185b709565ab233a3d`.
The ZIP and earlier RAR contain the same session summary and file sizes. Raw
images, account names, and telemetry remain outside Git.

## What the recording establishes

- The 23.3 minute session completed without a session-level exception.
- Rust received 72,608 capture frames. The Windows preview reader received
  30,679 frames, about 22 frames/s; 13,535 pending preview frames were replaced.
  The window displayed about 12.4 frames/s at the median of its rolling
  measurements. Its source age was 44 ms at the median and 88 ms at p95.
  The slowdown is in the local capture/preview/UI path; VM round trips are
  only used for analysis frames.
- The neural map ran in diagnostic mode for 2,707 frames. It did not train or
  update the game state. Its model covers bench/shop regions, not verified
  champion identities, items, or strategy.
- The native readers ran 2,702 times and bound 6,848 shop offers to the set
  catalog. The decision engine abstained 2,702 times, primarily because the
  owned champions were unverified. The 344 coach updates contained no
  actionable tips (269 observations and 75 missing-gold abstentions).
- Voice queued up to 91 utterances but played none. Telemetry records
  `winsound.SND_SYNC` missing and a Supertonic/Sherpa engine mismatch while
  changing voice. Both paths are corrected in this branch.
- The board and item HUB ran 272 times. Board cells and champion/item
  identities were not independently validated. Candidate icons are not
  accepted as ground truth or equipment instructions.

## Change and next Windows check

The preview now has its own nonblocking UI timer; expensive performance text
refreshes once per second, and inspection images are scaled before overlays.
Waiting for evidence is shown as a status, without reading on-screen numbers
aloud or adding them to the advice history. The BigBANANA terminal and web
panel separate the server's unpromoted training candidate from the diagnostic
neural mapping measured in the last imported Windows session.

The original button-only voice check is superseded by the recorded replay
pipeline described in `HM45_ENTREGA_20261004.md`. Play a replay on the chosen
monitor and exercise the complete image → decision → automatic voice path. Record `voice.played`,
`preview.fps`, `preview.native_received`, `preview.native_queue_replaced`,
`preview.render_p95_ms`, `replay_tips`, and `board_reference_status`. A real
Windows run is required to measure the FPS change and audio output; CI only
checks program behavior and packaged voice synthesis.

## New learning experiment

The separate BigBANANA CPU training container fine-tuned the bench/shop
localizer for 600 optimizer steps using 66 verified frames from three sessions.
The ONNX export passed parity (max absolute difference 2.98e-7); real inference
p95 was about 1.03 ms. On the same 46 latest-session frames, the installed
candidate proposed a shop region in 43; the new candidate proposed one in 5.
This regression blocks promotion. Neither candidate has independent champion,
item, board-cell, or decision accuracy labels. No strategic neural learning or
simulator has been activated by this localization experiment.

The pinned 18.3 knowledge release contains all 74 playable unit IDs with combat
stats, traits, and ability descriptions, joined exactly to the 74 visual IDs.
Only two abilities expose numeric variables and all descriptions contain
unresolved placeholders. The client snapshot may lag Riot's 18.3 B notes, so
strategy activation remains false.
The separate CPU JIT benchmark aggregated 500 synthetic paths of 12 steps in
0.0234 ms/call after warmup versus 2.8063 ms/call in plain Python on
BigBANANA (120x). First-call compilation took 578 ms. These paths are numeric
fixtures; they are not simulated TFT games.
