# Shop names as the primary identity signal (2026-10-07)

The fixed shop text strip is a cheaper source of champion identity than the animated body. The patch catalog remains a separate replaceable input; a generic name with multiple seasonal forms remains ambiguous.

## Observed evidence

- An indexed VOD window produced readable repeated names for all five visible cards: Kha'Zix, Kayle, Alistar, Sett and Draven. This is a window observation, not an overall accuracy estimate.
- In a separate 12-second, 4 Hz purchase window, the millisecond transition miner found two shop card disappearances with one new bench box each. Elder Dragon had four strong exact-name confirmations across 1,250 ms (lowest strong OCR score 94.83%). Ashe had one 96.87% read. The purchase consensus accepted two shop-to-bench training anchors; no body-recognition prediction was used as a label.
- A tooltip briefly obscured the shop and existing bench markers. The miner now retains the last strong name for up to 750 ms and compares against the most complete recent bench observation. These are bounded memories, not proof from an unreadable frame.

## Limits and next integration

- The live reader initially returned zero names on the Elder Dragon purchase frame because fixed panel anchors rejected that visible shop. A bounded fallback now requires at least three occupied card portraits and three readable names. It combines its original card OCR with one direct binarized name-strip read: agreement preserves the lower OCR score, disagreement abstains, and a single strip read needs at least 0.94 to be surfaced. On the same local frames with resident OCR, this changed the Elder Dragon shop from 0/5 to 4/5 names and the Ornn shop from 4/5 to 5/5. The remaining Alune strip score was 0.882, so it stays unresolved. Measured worker calls on four frames took 268–460 ms; these are local calls, not end-to-end Windows latency.
- These OCR scores are not calibrated probabilities. Both readers use Tesseract and share source pixels, so multiplying their scores would overstate certainty. A measured reliability guarantee needs separately annotated matches, calibration by evidence type, and held-out precision/coverage with confidence bounds.
- This establishes two purchase anchors in one VOD segment. It does not establish universal shop coverage, board identity after arbitrary moves, runtime latency, or Windows accuracy.
- HM4 submits OCR frames at a default 2 Hz. The new scheduler samples about 3,060 binary pixels in the five name regions (about 2 ms median in this local 48-frame window), requests shop OCR when at least 15 sampled pixels change in any card after a 500 ms minimum gap, and retains a 2-second refresh for unchanged text. On that window, this requested 15 reads in 12 seconds, compared with six fixed-cadence reads; both purchase transitions were included. This is a replay of scheduler decisions, not a Windows latency measurement.
- Offline anchors remain training material until a held-out purchase set and the Windows runtime pass their checks. Rejected or ambiguous transitions remain unknown.

Pending outside this checkpoint: live shop scheduling, held-out precision/recall, board event tracking, and runtime benchmark. No videos, model weights or private media locations are stored in this document.
