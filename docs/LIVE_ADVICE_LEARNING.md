# Live advice from partial evidence

The live reader can show an actionable **experimental** suggestion when the full
board identity contract is unavailable. The current families are bounded rolls
at low observed HP, patch-quoted level purchases, two identical named shop
cards, and nearby interest thresholds. They require observed HUD/shop fields;
the advisor does not invent a champion on the board, an equipped item, or an
opponent's position. Exact board recommendations still use the verified-state
strategic coach when such a state is available.

Each experimental decision records its observed inputs, patch basis, action,
and `training_label=false` in the normal session streams. The user can mark a
visible suggestion **Ajudou** or **Não ajudou** during a live match or replay
shown on screen. This
updates a small local preference model immediately and saves its counts beside
the session directory for later matches. A rating affects the priority between
available suggestions; it does not make unreadable pixels readable. The same
suggestion is rated only once per session. Replay review samples frames at a
slower five-second interval and keeps terminal-HP detection from ending a
recorded video prematurely.

This is online preference learning, not online neural-weight training. The
existing low-rate frame capture and server upload after a completed match
remain the path for neural training. Observed player compliance, OCR guesses,
and advice text are not treated as ground-truth strategy or vision labels.
Windows capture, narration latency, and coaching quality still require a
full-session field check; the Linux unit tests cover policy wiring only.
