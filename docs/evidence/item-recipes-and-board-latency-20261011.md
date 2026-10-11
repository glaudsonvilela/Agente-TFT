# Item recipes and board pass audit — 2026-10-11

## Scope

The active local knowledge release is TFT Set 18 patch 18.3. The visual art
reference is pinned separately at Data Dragon 16.19.1. This audit checks the
eight ordinary components and their 36 unordered two-component combinations.
Spatula, Frying Pan, emblems, radiant items, artifacts, and consumables are
outside the 36-pair core matrix.

## Findings

- The pinned item release contains one ordinary `TFT_Item_*` result for each
  of the 36 core pairs. The active visual catalog contains artwork on disk for
  all 36 results.
- `Giant's Belt + Giant's Belt` resolves to `TFT_Item_WarmogsArmor` (Armadura
  de Warmog). `B.F. Sword + Negatron Cloak` resolves to
  `TFT_Item_Bloodthirster` (Sedenta por Sangue).
- The strategic coaching catalog has only 18 recipes with evaluated item
  handlers. The remaining 18 were absent from that planner, despite being
  present in the source release and visual catalog. The new core recipe lookup
  exposes all 36 identities without inventing combat effects or silently
  promoting unsupported items to strategic recommendations.
- The heavy part of the complete board pass was icon template ranking. In the
  full 347.8 s replay, the board observer's p95 was 702.8 ms; inventory
  ranking p95 was 201.1 ms and equipped ranking p95 was 499.3 ms.
- On the same source frame at 223.5 s, replacing the NumPy reference BLAS dot
  product with OpenCV's native GEMM reduced snapshot time from 527.5 ms to
  45.4 ms in a repeat measurement. Inventory and equipped top candidates and
  statuses were identical on that frame. The NumPy fallback remains available
  when OpenCV is absent.
- The inventory now ranks every visible slot in one matrix batch, matching the
  already batched equipped-item reader. A regression test compares two slot
  outputs and exact source rectangles against independent per-slot searches.
  Across twelve replay frames spanning the recording, the optimized snapshot
  took 2.8–154.9 ms before inventory batching; targeted post-batch frames
  took 15.7–139.9 ms under varying desktop load. These are frame-processing
  measurements, not end-to-end display latency.
- The full-board cadence is now 500 ms (previously 1000 ms in the profile and
  1500 ms in the Ubuntu replay override); the fast item path remains separate.
  The complete 347.8 s replay produced 691 board observations from 2,782
  source frames, matching the intended two full-board reads per second.
  Processing time was p50 106.0 ms, p95 222.7 ms, maximum 495.5 ms;
  board-bar worker p95 115.2 ms and observer p95 130.0 ms. The preview encoded
  about 30 frames/s during the run, and 1,386 fast item reads completed.
- The first runtime repeat exposed a second bottleneck hidden by the isolated
  item benchmark: ORB arena registration repeatedly ran on the video's
  transition before a gameplay HUD was observed. The item/geometry work on
  those frames was under 50 ms, but synchronous calibration drove observer
  time to 222–577 ms. Arena registration now runs in one background task,
  starts only after level/gold or board markers are observed without a confirmed
  standard-layout stage, and retries
  unmatched arenas at most every five seconds. Its result is accepted only
  within the same source epoch and within three seconds of its source frame.
  The diagnostic now reports calibration and snapshot time separately.
  When stage text already confirms the fixed 1080p layout, the existing
  standard grid is used and feature registration is skipped.
- A final memory reduction reuses the immutable source RGB bytes for the board
  snapshot instead of copying another 1920×1080 RGB buffer. In an isolated
  frame, the snapshot preparation stage fell from 7.6 ms to 0.1 ms; total
  frame time varied with concurrent replay load. This last change passed the
  snapshot equivalence test. In the first 28.5 seconds of a fresh runtime
  replay, board processing p50 was 52.6 ms and p95 was 101.9 ms, with snapshot
  p95 4.7 ms; the video was still in its pre-game segment at that point.
- On the Linux desktop during the complete replay, observed RSS was about
  455 MB for the Python studio and about 299 MB across both FFmpeg decoders.
  These are process snapshots, not a measured peak, and Windows memory and
  latency have not been measured.

## Limits

Recipe coverage is identity and icon coverage. It does not establish that an
item detected in a replay is correctly named, that its carrier is known, or
that its combat effect is validated. The local release remains pinned to 18.3;
current patch changes need separate review before updating effects.
