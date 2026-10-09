# Same complete match at 20 fps versus 10 fps — 2026-10-08

## Controlled extraction

Both sets come from the same SHA-256-identified 1920 × 1080 source video and
the same continuous source interval, **2375–3900 s** (1525 s). The 20-fps set
contains **30,500 consecutively numbered frames**, twice the 15,250 in the
10-fps set. JPEG quality was set to `-q:v 3` for both. The 20-fps images occupy
**9,714,408,186 bytes**, versus **4,846,150,534 bytes** at 10 fps (2.005×).
They remain on the SSD in
`/mnt/sherlock-ssd/AgenteTFT/diagnostics/full-match-20fps-20261008/frames/`.
The local manifest records extraction settings and sample hashes. Independent
source re-decodes across both 20-fps chunk boundaries matched all 12 checked
frames exactly, six per boundary; the complete numbering has no gaps. The
source starts at matchmaking acceptance and extends past the match result.

## Did 20 fps improve the evidence?

**Yes, modestly for the timing and order of fast actions.** Sampling interval
fell from 100 ms to 50 ms. In the manually reviewed stage-4-2 sequence, the
20-fps set shows gold **48 → 52** after a unit sale, followed almost immediately
by **52 → 48**, the disappearance of the 4-gold Malphite offer from shop slot 2,
and a unit appearing on the bench. This supports a separate **Malphite
purchase** after the sale. It was absent from the previous seven-action review
(five rerolls, one Morgana purchase, one sale). The 10-fps frames also contain
one intermediate 52-gold image, so a careful review at 10 fps could have found
this action; 20 fps makes that intermediate state visible in two usable frames
and halves the time bracket. Do not count the extra purchase as a proven
increase in action recall caused by 20 fps.

| Evidence | 10-fps frames | 20-fps frames | Interpretation |
| --- | --- | --- | --- |
| Reroll at ~3571.1 s | 11961: 64g; 11962: 62g | 23922: 64g; 23923: 62g | Same reroll, onset bracket narrows from 100 to 50 ms. |
| Morgana purchase | 11995: 54g; 11996: 50g | 23989: 54g; 23990: 50g | Same purchase with shop slot 2 emptied and bench unit added. |
| Sale then Malphite purchase | 12005: 48g; 12006: 52g; 12007: 48g | 24009: 48g; 24010 and 24012: 52g; 24013: 48g | Two distinct actions. Malphite disappears from shop slot 2 on the second drop. |
| Drag over `Sell for 1g` at stage 3-5 | 9500 shows prompt; 9520 still 51g | 18999–19000 show prompt; 19001 shows the unit returned; gold stays 51g | Remains a canceled drag, not a sale. More frames do not replace the before/after state check. |

The five previously reviewed rerolls and Morgana purchase are visible at both
rates. No new champion name or item identity was established simply by raising
the frame rate; spatial resolution is unchanged. The candidate list still
requires manual review because animation, scouting, and round transitions can
change many pixels without a player action.

## Meaning for the player model

The improvement is **temporal evidence**, not a measured improvement in
strategic decisions or a trained player policy. The sale and immediate purchase
show why action order and intermediate state matter: a 48g-to-48g comparison
over the whole burst would erase both actions. The 20-fps data should be used
to resolve short ambiguous windows and preserve before/action/after records.
Long stretches of static planning or combat need not be processed at 20 fps
just to double the images. A separate, held-out evaluation of labeled actions
and player decisions is needed before claiming that the IA learned to play
better.

## Sampling decision

After reviewing the comparison, the project will continue with **10 fps** for
full-match visual evidence. The 20-fps extraction remains an archived
comparison on the SSD; it is not the default input for subsequent indexing or
training. The indexing tool already defaults to 10 fps.
