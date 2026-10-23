# Follow-up: what we resolved ourselves and what the lab needs to supply

**Decision: the normalization fix is retained; individualized stimulation is still not supported.** We completed a larger, frozen-policy comparison and recovered one previously excluded recording. Jacob and Avi do not need to debug normalization, run the pipeline, or choose acceptance thresholds. The remaining lab request is for specific identity/timing evidence and any existing independent repeat recordings, listed in [the short handoff](next_steps_for_jacob_avi.md).

## Work completed

The acceptance experiment now contains **540 new synthetic datasets**: 216 development datasets and 324 held-out datasets. The comparison was specified before running either set. A source/configuration hash lock was written after development and checked before held-out evaluation. Held-out seeds, frequencies, noise slopes, sample rate, amplitude transitions, and trial-gain structure differ from development. No thresholds were tuned using the pilot results or the held-out results.

We compared the current v1.1 rule with an experimental rule that measures peak prominence over the available frequency grid while still selecting the candidate within the target band. The experimental rule removes fixed contrast-width and linearly detrended-contrast vetoes; it retains absolute-power corroboration, effect thresholds, competing-peak checks, band-boundary rejection, split checks, and the 300-iteration block bootstrap. This tests whether those shape vetoes cause false rejection. It is not a claim that these are the only possible approaches or that either is optimal.

**The experiment improved recovery but did not establish an acceptable replacement.** On the held-out set:

- The current rule accepted **72/162** known-signal datasets; the experimental rule accepted **159/162**. For the strong-signal subset, this was **19/54 versus 54/54**.
- The current rule also accepted **18/162** deliberately unsuitable stress cases; the experimental rule accepted **34/162**. Accepted stress cases involved within-trial frequency sweeps, competing oscillations, or—in the experimental rule—an injected frequency at the search boundary whose estimated maximum shifted slightly inward.
- Neither rule accepted the held-out stationary-noise, stationary-oscillator, broadband-change, broadband-change-with-stationary-oscillator, between-half frequency-switch, or isolated voltage-transient controls (**0/108 each**).

These are counts under specified synthetic models, not population sensitivity/specificity estimates. A frequency sweep or a pair of oscillators can have a reproducible average spectral maximum without establishing one stationary, unambiguous oscillator. The stress cases challenge that stronger interpretation. If a different scientific target is intended, its validation criterion must be stated explicitly.

Neither policy met the development promotion criterion (zero accepted unsuitable controls, no excessive error among accepted known signals, and at least 80% strong-signal acceptance). The development lock therefore selected **no replacement**. The held-out evaluation tested both frozen alternatives for diagnosis; it did not rescue or retune either one. The production acceptance policy remains unchanged and provisional. Further algorithm development remains our responsibility, not a task delegated to Jacob or Avi.

The previous 162-dataset benchmark remains useful for normalization and initial signal recovery, but its 90 controls did not expose these new failure modes. Its zero accepted controls should not be presented as general validation of the acceptance policy.

## One real input problem fixed

The 10579 Bandit-post behavioral file already existed as `sub-010579-1_task-bandit_2026-09-03_20-12-30.csv`. Filename matching rejected the leading zero even though behavioral-row validation already normalized leading zeros. The loader now treats numeric leading-zero padding consistently, while still rejecting additional trailing digits, conflicting participant rows, and wrong sessions.

The exact file has 118/119 choice events and 119/120 feedback events inside the EEG recording. The manifest now records the pairing and hashes. The original metadata filename says `pre-stim`; its start time/sample count identify this EEG, and the pilot EEG filename supplies the post phase. That filename discrepancy is documented rather than silently renamed. All original files remain unchanged.

The recovered recording retains **117 response-beta trials and 116 feedback-theta trials**. Beta has a 27-Hz diagnostic minimum with a −0.210-dB effect. Theta has a 5.25-Hz diagnostic maximum with a +0.645-dB effect. Neither passes either policy. The theta candidate is worth further investigation: its numerical half estimates differ by 0.75 Hz chronologically and 0.5 Hz odd/even, but the qualifying effect/localized feature is not consistently present in the halves or bootstrap samples. Calling this simply an “unstable frequency” would overstate what failed. It is not an approved individualized target.

## Pilot rerun and verification

The updated full batch completed **38 recordings / 95 analyses**, with **0 accepted analyses** under either policy. There are now 29 manifest pairings and nine unresolved recordings. The 93 previously computed scientific result records are unchanged (excluding the intentionally skipped historical replay field), and all 68 existing trial logs are byte-identical. Only the two analyses of the recovered recording changed from missing-input results to computed results. For 10034 Bandit pre, the diagnostic minimum remains 23 Hz and −0.065 dB.

**67 tests pass; one documented obsolete GUI-interface test is skipped.** New tests cover the actual recovered file, identity-conflict rejection, development/held-out separation, source-lock enforcement, and isolation of the experimental rule from the default pipeline. No task timing, EEG/behavior source data, stimulation assignments, or live configuration changed. SST theta remains outside this validated batch.

## What cannot be supplied by another code change

We re-inventoried the available repository files. Five unresolved SST recordings have candidate event files with LSL timestamps but no matching Unix timestamps; they require recorded synchronization evidence, not a guessed clock offset. Four 12193 recordings have candidate behavioral rows labeled `1219300000` and unresolved session/run identities. Leading-zero normalization does not justify removing trailing digits. The 10037 timing inconsistencies also need original clock/acquisition evidence if they are to be resolved.

Independent, unstimulated repeats of the same task would allow a biological repeatability test. Existing pre/post recordings spanning stimulation cannot establish that. We should first find out whether suitable recordings already exist; this report does not request new participant sessions or change the protocol. Even reliable task frequencies would still need a separate scientific justification as tACS targets.

## Reproducible artifacts

- [Development results](../validation/acceptance_calibration_followup/development.json), [frozen lock](../validation/acceptance_calibration_followup/development_lock.json), and [held-out results](../validation/acceptance_calibration_followup/heldout.json).
- [Both policies on all pilot analyses](../validation/acceptance_calibration_followup/pilot_policy_comparison.json).
- [Current full pilot outputs](../validation/pilot_results_input_recovery/README.md) and [QC summary](../validation/pilot_results_input_recovery/qc_summary.csv).
- [Unresolved-input inventory with candidate paths, hashes, and identity/timing fields](../validation/acceptance_calibration_followup/unresolved_input_inventory.json).
- [Verification record](../validation/acceptance_calibration_followup/verification.json) and [test log](../validation/acceptance_calibration_followup/tests.txt).

From the repository root in the pinned Python environment, use new output names:

```powershell
python -m pytest tests -q
python validation/experiments/calibrate_acceptance.py development --out validation_outputs/new-development
python validation/experiments/calibrate_acceptance.py heldout --lock validation_outputs/new-development/lock.json --out validation_outputs/new-heldout
python validation/experiments/calibrate_acceptance.py pilot --lock validation_outputs/new-development/lock.json --out validation_outputs/new-policy-pilot
python validation/experiments/audit_unresolved_inputs.py --out validation_outputs/new-input-inventory.json
python code/validate_rhythms.py --skip-legacy --output-name new-full-pilot
```

The simulation script supplies epochs directly and does not validate acquisition, hardware latency, or artifact rejection. Held-out simulations use 250 Hz; actual pilot processing uses native 500 Hz. All simulations use the fixed mean-log-ratio normalization described in the [normalization report](meanlogratio_validation_decision.md), whose rationale is supported by [Kinley et al. (2026)](https://pubmed.ncbi.nlm.nih.gov/42276213/). That paper does not validate our acceptance policy.
