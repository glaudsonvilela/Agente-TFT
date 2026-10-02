# HM3 finishing checkpoint

The initial Windows package compiled but failed BEFORE the mapper entry point:
`pyi_rth_pkgres` imported `pkg_resources`, which failed to resolve `jaraco`.
The artifact was not published as a working release. The fix explicitly includes
the small namespace dependencies and their data; it does not restore PyTorch,
FFmpeg, the replay UI, or training to the runtime. The executable itself and the
installed copy must pass actual Windows capture/UI tests before publication.

The install check now waits for the installer process and verifies every installed
file against BUILD_MANIFEST. A GUI process return from the shell is not proof of
completed installation. Startup diagnostics are retained when no console exists.

Review also found that the proposed ROI hash used approximate input footprints
for readers which include visual eligibility and search logic. Reuse now requires
complete immutable RGB equality, unchanged geometry and a nonnegative age of at
most 750 ms. It retains one RGB object rather than hashing guessed strips. Original
reader frame IDs stay intact within cached evidence. B1 reuse remains disabled.
This is not per-field change scheduling, calibrated confidence or a claim of more
accurate recognition. At the default 1 Hz reader schedule the 750 ms lease will
usually expire; no default OCR acceleration is promised from this cache.

Package compilation, portable launch, installed launch, synthetic neural execution
and actual Tesseract execution are distinct checks. A small synthetic captured
window exercises resolution rejection, not TFT OCR accuracy. The neural model used
by CI is a test fixture, not a TFT model to distribute as trained. Personal L2/L3
weights remain explicit inputs, separate from the runtime.
