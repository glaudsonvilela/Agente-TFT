# Trait panel constraint, 2026-10-07

The independent Rust board reader extracted four trait words from Windows session
`hm4-20261004-190825-730054`, frame `000010682`: Defendente,
Enfeiti¢ador, Florescer, Solar. The seasonal catalog binds these to
Defendente, Enfeitiçador, Florescer, Solar. With the two observed green health
bars, an exact cover of those four traits yields two **conditional hypotheses**:
Ahri + Leona, or Karma + Leona. This does not identify either image crop or
verify that the trait panel, the visible bars, or the player perspective is
complete. The DINO head rejected both crop identities on this frame.

The new binder records raw OCR, catalog matches and conditional rosters in
the diagnostic snapshot. It never supplies champion IDs to the strategic
coach or creates training labels. It discards OCR cached for over two seconds
and refuses to enumerate rosters when a detected text row lacks a full trait
name. A full catalog name read with low OCR confidence can still match; this
recovers `Enfeiticador` at 0.36 confidence on frame `000010486`.

On 12 selected screenshots from the same Windows session, frames `000010486`,
`000010682` and `000011104` yielded the same two conditional rosters. Frame
`000009240` showed two trait rows, but OCR read only one full name and a short
fragment (`FI`); the binder now returns `partial_panel` and no roster there.
The other selected frames did not supply catalog matched traits. This is a
same-session sanity check, not an independent accuracy measurement.

Next evidence required: repeated frames across distinct matches, a verified
perspective and bar count, and independent champion labels. The seasonal
knowledge bundle remains on patch 18.3B and must be updated before current
patch recommendations are released.
