# Decision after correcting normalization and rerunning validation

**Follow-up:** [Expanded acceptance testing and recovered input](acceptance_calibration_followup.md) adds 540 simulations, documents newly exposed acceptance failures, and recovers 10579 Bandit post. The latest batch still has 0/95 accepted analyses; nine recordings remain unresolved. [Only these specific lab inputs are requested](next_steps_for_jacob_avi.md).

**Recommendation: do not use this workflow's current individualized frequencies for participant stimulation.** The baseline correction is now implemented, but these pilot data do not establish usable individualized estimates, and the current acceptance rules are not sufficiently calibrated for deployment. This applies to the analyses tested here, not a claim that individualization is impossible.

The immediate decision is complete: retain this as an offline analysis/validation workflow. Do not choose between 13 and 23 Hz for participant 10034. Task-specific targets remain a reasonable future design choice, conditional on reliable measurement; separate task labels cannot rescue unreliable estimates. Fixed-frequency fallback options remain a separate PI/protocol decision and were not assigned by this update.

## What changed

Version **offline-rhythm-validation-1.1** uses per-trial **mean-log-ratio** normalization for all primary theta/beta spectra and time-frequency plots. After computing each channel's power and averaging across ROI channels, it subtracts each trial's mean baseline log power from its log power. This removes the downward offset caused by subtracting log(mean baseline power). Arithmetic power is still retained for the absolute-spectrum checks and descriptive secondary analyses.

Input matching, trial selection, filtering, reference, windows, wavelets, and reliability thresholds were held constant. Every saved trial log matches the v1.0 run byte-for-byte. The thresholds were not relaxed to produce passing participants. Each result and the QC CSV identify the normalization and analysis version.

## Software and numerical validation

- **54 tests passed; one documented obsolete SST GUI-interface test remains skipped.** This includes recovery of known 21-Hz beta suppression/enhancement and 6-Hz theta enhancement, artifact/alignment checks, and new tests ensuring a baseline compared with itself has zero contrast and stationary noise does not create mean suppression.
- All **38 pilot recordings / 95 requested analyses** completed, including explicit input/QC failures.
- A separate 10034 rerun reproduced all **10 scientific result records exactly**, excluding the deliberately skipped historical replay field. This establishes computation reproducibility, not biological test–retest reliability.
- The original EEG, behavior, historical reports, task scripts, counterbalancing, `.neprot` files, and live stimulation settings were not changed.
- Source hashes and configuration in the new output provenance identify the computation exactly. The run was generated before committing, so its recorded Git commit is the parent; the source hashes match corrected code commit `4ca1dc7`.

**Windows and Linux CI also passed** the complete test suite and actual-data 10034 smoke check, including the corrected effect and normalization-version assertions: [workflow run](https://github.com/DVS-Lab/tacs3-bluesky/actions/runs/39985644935).

## Broader synthetic validation: estimator works, acceptance policy needs calibration

The [seeded benchmark](../validation/normalization_validation_v1_1/synthetic_benchmark.json) evaluated **162 synthetic datasets**, each with 120 trials. It used white and 1/f backgrounds, variable trial amplitudes, opposite channel phases, and frozen analysis settings. It did not tune thresholds after observing outcomes.

For **72 datasets with injected signals**, the estimated frequency was always within **0.5 Hz** of the known frequency (theta within 0.25 Hz). The median frequency error was zero for each of the three analysis types. Known beta frequencies were 17, 21, and 26 Hz; known theta frequencies were 5, 6, and 7 Hz.

However, only **30/72** passed all provisional acceptance gates:

- Response beta suppression: **9/24** accepted.
- Stop-related beta enhancement: **9/24** accepted.
- Feedback theta enhancement: **12/24** accepted.

The rejected known signals frequently failed feature-width, slope-removal/localization, or feature-presence requirements in the halves/bootstrap samples. All numeric chronological/odd-even peak differences for these known signals were at most 0.5 Hz. Thus a failure labeled `split_unstable_or_missing` often reflects a missing *qualifying feature*, not a large shift in the estimated frequency. These results expose substantial false rejection in the current gates and limit what can be inferred from the absence of pilot passes.

For **90 nonqualifying controls**, none was accepted: 54 stationary-noise/stationary-oscillator datasets with no event-related change, 18 broadband power-change datasets with no localized target frequency, and 18 datasets whose oscillation frequency changes between trial halves. These results do not establish a population false-positive rate; the simulations are a limited collection of seeded models and bypass acquisition/preprocessing by supplying epochs directly. Broad-spectrum contrasts can be real changes without supplying an individualized oscillatory frequency.

## Pilot results with corrected normalization

**0/95 analyses pass the current criteria:**

- Response beta suppression: **0/38**.
- Bandit feedback theta enhancement: **0/19**.
- SST successful-stop beta enhancement: **0/19**.
- SST failed-stop beta enhancement: **0/19**.

There are no qualified task pairs or pre/post pairs. Ten recordings still lack verified behavioral matches; other failures include timing alignment, insufficient usable trials, weak/nonlocalized effects, or missing qualifying split/bootstrap features. Fourteen response-beta recordings and ten feedback-theta recordings retain at least one epoch; five and four respectively retain at least 40. No stop-beta subgroup retains 40 trials.

For **10034 Bandit pre**, 115/120 trials remain. The diagnostic minimum stays at **23 Hz**, while the corrected effect is **−0.065088 dB** (previously −0.753483 dB). It fails the effect-size/direction, localization, corroboration, and reliability criteria. The individualized-frequency field remains empty. Bandit post remains unqualified as well (26 Hz diagnostic minimum, −0.269994 dB).

**SST theta is not validated by this batch.** The primary theta analysis implemented here is Bandit feedback theta. An SST stopping-theta localizer would require its own defined events, analysis, and validation; the results above cannot authorize it. Descriptive Specparam/IAF-minus-5 outputs are also not validated replacements.

## What can and cannot be concluded

The normalization error is corrected and known frequencies can be recovered under the tested signal models. **We still cannot endorse individualized stimulation using this workflow now.** That judgment rests on both unqualified pilot estimates and an acceptance policy that rejects many known signals. It would be wrong to interpret 0/95 as proof that all recordings lack relevant rhythms, or to treat relaxing thresholds until participants pass as validation.

Before a deployment claim, calibrate feature/reliability gates on an independent simulation set spanning signal strengths, frequencies, realistic background/artifact conditions, and absent/broad/unstable signals; then lock the policy and test within-task repeatability on independent or repeated recordings. The current block/split/bootstrap checks are within-recording diagnostics; there are no new independent participant recordings in this work. Pre/post recordings span stimulation and do not constitute a clean unstimulated test–retest design. Even a reproducible task frequency would not by itself establish the optimal tACS frequency.

## Where to inspect and rerun

- [Corrected pilot outputs](../validation/pilot_results_meanlogratio_v1_1/README.md), [QC summary](../validation/pilot_results_meanlogratio_v1_1/qc_summary.csv), [completion record](../validation/pilot_results_meanlogratio_v1_1/completion.json).
- [Synthetic benchmark](../validation/normalization_validation_v1_1/synthetic_benchmark.json), [test log](../validation/normalization_validation_v1_1/tests.txt), [verification summary](../validation/normalization_validation_v1_1/verification.json).
- [10034 corrected spectrum/TFR](../validation/pilot_results_meanlogratio_v1_1/10034_ses-1_bandit_pre_20260918104411/response_beta_erd/spectra_tfr.png).
- The earlier `validation/pilot_results` and comparison artifacts remain unchanged as explicitly historical v1.0 results.

From the repository root in the pinned Python 3.11 environment:

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
.\.venv\Scripts\python.exe validation\experiments\validate_meanlogratio.py --out validation_outputs\new-meanlogratio-benchmark.json
.\.venv\Scripts\python.exe code\validate_rhythms.py
```

Use a new benchmark filename. The full pilot command creates a new run directory automatically. No hardware or task execution is required.

The normalization rationale is described in [Kinley et al. (2026)](https://pubmed.ncbi.nlm.nih.gov/42276213/). The empirical conclusions here come from the linked computations; the paper does not validate this lab's individual frequencies or acceptance thresholds.
