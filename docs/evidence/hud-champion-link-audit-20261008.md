# Champion labels in the Ubuntu HUD replay

The board detector emits a health-bar marker, a tentative board cell and a
separate neural champion candidate. The marker number is assigned again on
each frame. A persistent candidate therefore belongs to its recorded cell,
not to the current marker number. The HUD now joins candidates to uniquely
occupied cells and leaves ambiguous cells unnamed. The fast overlay also
requires a mutual nearest match between its current bar and the slower board
observation before borrowing a champion name.

The board region previously put the marker number inside its position value.
It did reach the HUD. The new explicit `marker_id` field makes this contract
clear while the diagnostic reader still accepts recorded sessions with the
older shape. This was not the cause of the low recognition coverage.

Replay audit of three local Ubuntu sessions (counts are marker observations,
not independent champion identities):

| Session suffix | Detected bars | Neural proposals | Model candidates accepted | Names shown after corrected cell join | Old labels attached to a different cell |
| --- | ---: | ---: | ---: | ---: | ---: |
| `210913-610035` | 1,037 | 555 | 139 | 101 | 3 |
| `211224-836106` | 722 | 437 | 113 | 71 | 8 |
| `211515-258948` | 513 | 361 | 52 | 24 | 2 |

The classifier accepted 304 of 1,353 proposals across these sessions. Most
remaining crops have no accepted identity, so the name coverage is still low.
The independent model check retained 21/32 correct on its small validation
set; these replay counts do not measure accuracy. No predicted name was
promoted to a training label or to verified game state. More independently
confirmed champion crops and a separate match validation are needed before
the HUD can treat board names as dependable inputs for coaching.

For inspection, the classifier now exposes the leading name even when its
acceptance gate rejects it. The HUD marks that entry `hipótese rejeitada` and
keeps `candidate_name` empty, so it cannot enter temporal identity evidence or
the coaching state. A direct run of the packaged ONNX model on one saved
1920×1080 replay image completed nine bar proposals and three accepted
candidates; this checks the output contract, not label correctness.
