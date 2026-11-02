# Hat targets follow-up: hypothesis H10 rejected on the engine (#293)

Follows `2026-11-02_hat-targets-and-listening-plan.md` (hypothesis H10). Source: review of PR #290 (hat voice).

- **H10** (early/late brightness above 1.5 at `body_mix` 0.4) was **rejected** on the engine. Measured `early_late` (reviewer experiment, engine as in PR #290): 1.10-1.16 at `body_mix` 0.4 / `decay_hi_ratio` 0.5; 1.64-1.72 at `body_mix` 0.8.
- The engine implements `body_mix` as a frequency split at `SPLIT_RATIO` x `hp_hz` (the part below keeps the slow envelope). Reviewer experiment on the split ratio at `body_mix` 0.4: 1.5 gives 1.32-1.38, 2.0 gives 1.16-1.19, 3.0 and above give about 1.0.
- Cause: not established beyond "limit of the high-passed body model" as stated in the issue; the ratio experiment shows the effect depends on how much of the passband lies below the split.
- Consequence: the contract wording now describes the split (`contracts/hat-params.schema.json`, `docs/INTERFACES.md`, #293). No value or range changed. Whether a wider `body_mix` default or another model is wanted is a decision for a later issue, not made here.
- Not a listening claim: these are measured features only.
