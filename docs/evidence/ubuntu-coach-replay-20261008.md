# Ubuntu replay coach check — 2026-10-08

The first live session stopped after the Python decision stage sent `rank_advice`
to an older resident Rust executable. Its `unknown operation` response ended the
worker and froze the preview. The Rust handshake now advertises `rank_advice`;
the Python side checks that capability before sending the request. A normal
Rust abstention is recorded as `NO_ACTIONABLE_NATIVE_CANDIDATE`, separately from
a missing or failed motor.

After rebuilding the Rust executable, a replay capture ran for roughly two
minutes with the preview advancing at about 11–12 FPS. It saved 2,533 source
frames, produced 18 actionable tip records, completed four voice playbacks,
and compiled a 35.7-second local spoken-moments video. The spoken moments were
an Ornn/Defender suggestion (twice), a combat-loss reaction, and a level-7
plan. The two Ornn playbacks show that repeated advice still needs better
session-level variety; four voice events do not demonstrate complete coaching.

Verification: six Python decision-priority tests and 61 Rust worker tests
passed. The replay and generated speech/video stay in the local SSD diagnostic
session and are not committed to the repository. This replay check is not a
Windows gameplay validation or evidence of a trained neural policy.
