# Rhythm validation codebook

**Run [`validate_rhythms.py`](validate_rhythms.py) to generate `qc_summary.csv`.** This guide describes the offline validation scripts in this folder.

From the repository root, with the validation environment installed:

```powershell
.\.venv\Scripts\python.exe code\validate_rhythms.py --subject 10034
```

Remove `--subject 10034` to analyze all pilot recordings. The command prints the output folder, `validation_outputs/<timestamp>/`, which contains the new `qc_summary.csv`. The current saved reference is `validation/pilot_results_input_recovery`; `validation/pilot_results_meanlogratio_v1_1` and `validation/pilot_results` preserve earlier runs. None is overwritten by a new run. See the [setup instructions](../docs/avi_rhythm_validation_guide.md#6-optional-reproduce-the-analysis-on-the-lab-windows-computer) if the environment is not installed.

## What each script does

- **[`validate_rhythms.py`](validate_rhythms.py):** The entry point. `run()` reads the input manifest and configuration, calls the functions below for each recording and analysis, saves detailed results, and calls `summarize()` to produce the combined CSV. It also records input failures as failed results.
- **[`rhythm_validation_io.py`](rhythm_validation_io.py):** Loads and verifies EEG, metadata, and behavioral files. `load_pair()` checks the input pair; `select_events()` selects the relevant trials; `alignment_qc()` checks event timing against the EEG recording.
- **[`rhythm_validation_core.py`](rhythm_validation_core.py):** Calculates the estimates and scientific QC. `preprocess()` filters, screens channels, and rereferences EEG. `estimate()` calls `epoch_data()` to extract and screen epochs, `spectra()` to calculate power changes, and `assess()` to evaluate candidate features and reliability. `feature()` identifies spectral features; `assess()` applies trial-count, retention, split-half, and bootstrap criteria. `preview()` creates an offline recommendation record with no approved stimulation frequency.
- **[`rhythm_validation_report.py`](rhythm_validation_report.py):** Writes plots and summary tables. **`summarize()` is the function that writes `qc_summary.csv`** from the result dictionaries; it does not calculate the primary estimates. `legacy_replay()` runs the separate historical comparison, and `theta_secondary()` calculates separate descriptive theta measures.

To follow a CSV row through the code, start at `validate_rhythms.run()`, then follow `estimate()` → `assess()` in the core module, and finally `summarize()` in the report module. For a row that failed before estimation, inspect the `InputError` handling in `run()` and the corresponding checks in the IO module.

## Inputs and settings

- [`validation/pilot_manifest.json`](../validation/pilot_manifest.json) lists the exact EEG, metadata, and behavioral file pairings, hashes, and matching evidence.
- [`rhythm_validation_config.json`](rhythm_validation_config.json) contains the preprocessing settings, analysis windows, frequency ranges, artifact thresholds, and reliability thresholds used by this pipeline.
- [`requirements-validation.txt`](../requirements-validation.txt) pins the analysis dependencies.

## Reading the outputs

Each `qc_summary.csv` row represents one recording and one analysis (`estimand`). The corresponding `<recording_id>/<estimand>/result.json` contains more detail, including input paths, timing diagnostics, and reliability results. When available, `events.csv` records trial selection and exclusion reasons, `spectrum.csv` contains the calculated spectrum, and `spectra_tfr.png` visualizes it. Input failures can prevent these additional files from being produced.

The main CSV fields are:

- `candidate_hz`: the diagnostic frequency found, even if it fails QC.
- `individualized_frequency_hz`: populated only when the estimate passes the provisional reliability criteria; it is not deployment approval.
- `effect_db`: the power change at the diagnostic frequency relative to baseline.
- `n_eligible`, `n_retained`, `retention_fraction`: selected trial count, retained trial count, and their ratio.
- `qc`, `status`, `failure_reasons`, `warnings`: the outcome and its explanations.
- `bootstrap_detection_fraction`, `bootstrap_ci_hz`: how often resampling finds a qualifying feature and the frequency interval conditional on finding one.
- `roi_channels`: the channels used for the region of interest.

`chronological_split_unstable_or_missing` and `odd_even_split_unstable_or_missing` combine two different failures. Read `splits.<name>.difference_hz` for the numerical frequency change, and `splits.<name>.halves[].reasons` for feature/effect failures. A small frequency difference can still fail because a qualifying feature is missing; the label alone does not demonstrate a shifting frequency. Bootstrap frequency intervals are conditional on qualifying-feature detection, so a narrow interval with low detection is insufficient.

`completion.json` records whether the batch completed. `provenance.json` records code/input provenance and the software environment; copied `config.json` and `manifest.json` identify the run settings and inputs.

## Relationship to the older scripts

`calculate_theta_beta.py`, `run_rhythm_estimation.py`, and `rhythm_estimator.py` are historical estimation interfaces, not the entry point for this QC summary. The report module uses historical code separately for comparison; those historical frequencies do not determine the revised CSV estimates. Experimental task, acquisition, and protocol-generation scripts are outside this offline workflow.

For the scientific rationale and limitations, see the [audit](../docs/rhythm_estimation_audit.md). For expected pilot results, see the [pilot report](../docs/pilot_rhythm_validation_report.md).

For the controlled 10034 pre comparison showing which choices move the beta minimum from 13 to 23 Hz, see the [method comparison and reproduction commands](../docs/10034_beta_method_comparison.md).

The correction is now applied in v1.1. Read the [current validation and individualization decision](../docs/meanlogratio_validation_decision.md), including the pilot rerun and limitations of the acceptance criteria.

## Follow-up experiments and input audit

- [`calibrate_acceptance.py`](../validation/experiments/calibrate_acceptance.py): compares the default and experimental acceptance policies on separate development/held-out simulations, then on pilot data. `development` writes a source/configuration lock; `heldout` and `pilot` require it. It does not change the default policy or write `qc_summary.csv`.
- [`audit_unresolved_inputs.py`](../validation/experiments/audit_unresolved_inputs.py): inventories candidate paths, hashes, identity fields, and available clock columns for unresolved recordings. It does not alter the manifest or infer clock offsets.

See [the results and exact commands](../docs/acceptance_calibration_followup.md) and [the specific evidence requested from the lab](../docs/next_steps_for_jacob_avi.md). No experimental acceptance rule was promoted.

## Data versus method diagnostics

[`diagnose_data_vs_method.py`](../validation/experiments/diagnose_data_vs_method.py) separates trial-yield limitations from candidate-estimation and acceptance failures using known signals added to retained epochs and matched clean controls. Its peak-first alternative is diagnostic only. [`audit_eeg_spatial_quality.py`](../validation/experiments/audit_eeg_spatial_quality.py) measures all EEG recordings independently of behavioral availability, including spatial similarity and residual amplitude after reference. [`plot_data_method_diagnostics.py`](../validation/experiments/plot_data_method_diagnostics.py) illustrates the clean-signal counterexamples.

Read [the diagnosis and commands](../docs/data_vs_method_diagnosis.md), and use [diagnostic_summary.csv](../validation/data_method_diagnosis/diagnostic_summary.csv) alongside the ordinary QC summary. A failed peak does not establish poor EEG quality.
