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

Deployment check on BigBANANA: the eight previously processed sessions now have
review queues with 175 unit crops in total and zero new labels. Those older
sessions contain no item-change events. On a two-minute full-HUD source video,
the selector chose 58 frames: 35 shop changes, three bench/item-area changes,
one board change, and 19 periodic frames. A separate board-only clip produced
no shop events, as expected. This checks acquisition behavior; it is not a
recognition-accuracy measurement. New Windows sessions are still needed to
measure the gain in confirmed labels and independent-match accuracy.

On October 8, two compact packages of already adjudicated game-derived gold
were imported into the BigBANANA corpus: two crops from one full-HUD match and
six strictly supported crops from another VOD. The corpus now holds nine gold
crops from three source groups. Two mixed-teacher rows were excluded. A new
weighted challenger trained on the enlarged corpus but scored 20/32 correct
and 0.643939 macro recall on the frozen validation set. The retained baseline
scored 21/32 and 0.689394; no new model was promoted. This is a failed
improvement attempt, not a success metric for the acquisition pipeline.

A separate native 1080p gameplay source produced 331 sampled frames and 842
unit crops. Strict shop acquisition checks found four possible transitions but
zero confirmed labels; tooltip supervision also found zero. Its unlabeled
review queue contains 64 selected crops from 841 unique candidates. This
source therefore did not change the training corpus. A second distinct 1080p
match produced 335 sampled frames and 1,255 crops. It yielded one shop purchase
and bench persistence anchor for Elise; the independent adjudicator supported
that anchor. The central corpus now holds 10 gold crops from four source groups.
Its remaining 1,253 unique unlabeled crops contributed 64 review candidates,
not training labels. Tooltip supervision added no further gold. The challenger
trained with all 10 corpus gold examples again scored 20/32 correct and
0.643939 macro recall on the frozen validation set, so the 21/32 baseline
remained selected. A third distinct 1080p match is being analyzed. The 360p
archive videos were not used for this OCR
path: the collector requires native 1920x1080 pixels and upscaling would not
restore the missing text detail.
