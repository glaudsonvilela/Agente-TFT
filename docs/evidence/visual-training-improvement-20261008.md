# Visual learning: event evidence and review queue

The server's eight previously sealed sessions produced one supported champion
anchor and no promoted model. The challenger scored 20/32 on the independent
check, versus 21/32 for the retained baseline. These counts do not justify
claiming that the neural model improved.

The Windows capture now selects a bounded RGB frame on visible changes in the
shop, board, or bench/item area, with a sparse periodic fallback. Event names
describe where pixels changed; they do not identify a champion, item, purchase,
or game action. The recorder still runs JPEG encoding on its writer thread and
retains the 3,600-frame and 2 GiB ceilings. Replay seeks use a monotonic upload
timeline while preserving the original source timestamp in the local manifest.

The upload API preserves the event name in server evidence. After the normal
dense crop collection, the worker prepares a bounded review queue of visually
diverse unit crops and frames with bench/item changes. The queue has no labels.
Prediction margins contribute to its priority only when candidate scores are
actually present; absent scores are not invented. A human or an independent
observable event must confirm a label before it enters training. Champion and
item contexts remain separate, and the existing independent promotion gate
continues to decide whether a new model replaces the baseline.

To measure improvement, compare per-match accuracy and macro recall against
the retained model on independent matches after new confirmed examples arrive.
The queue alone does not train or promote a model.
