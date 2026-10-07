# Shop names as the primary identity signal (2026-10-07)

The fixed shop text strip is a cheaper source of champion identity than the animated body. The patch catalog remains a separate replaceable input; a generic name with multiple seasonal forms remains ambiguous.

## Observed evidence

- An indexed VOD window produced readable repeated names for all five visible cards: Kha'Zix, Kayle, Alistar, Sett and Draven. This is a window observation, not an overall accuracy estimate.
- In a separate 12-second, 4 Hz purchase window, the millisecond transition miner found two shop card disappearances with one new bench box each. Elder Dragon had four strong exact-name confirmations across 1,250 ms (lowest strong OCR score 94.83%). Ashe had one 96.87% read. The purchase consensus accepted two shop-to-bench training anchors; no body-recognition prediction was used as a label.
- A tooltip briefly obscured the shop and existing bench markers. The miner now retains the last strong name for up to 750 ms and compares against the most complete recent bench observation. These are bounded memories, not proof from an unreadable frame.

## Limits and next integration

- This establishes two purchase anchors in one VOD segment. It does not establish universal shop coverage, board identity after arbitrary moves, runtime latency, or Windows accuracy.
- The current HM4 app submits OCR frames at a default 2 Hz but requests shop OCR only every 2 seconds. The live scheduler must react to changes in the shop text region and retain the normal slow fallback for an unchanged shop.
- Offline anchors remain training material until a held-out purchase set and the Windows runtime pass their checks. Rejected or ambiguous transitions remain unknown.

Pending outside this checkpoint: live shop scheduling, held-out precision/recall, board event tracking, and runtime benchmark. No videos, model weights or private media locations are stored in this document.
