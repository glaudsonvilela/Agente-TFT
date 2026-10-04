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

The next Windows test should press **Testar voz** once, then play a replay on
the chosen monitor for several minutes. Record `voice.played`,
`preview.fps`, `preview.native_received`, `preview.native_queue_replaced`,
`preview.render_p95_ms`, `replay_tips`, and `board_reference_status`. A real
Windows run is required to measure the FPS change and audio output; CI only
checks program behavior and packaged voice synthesis.
