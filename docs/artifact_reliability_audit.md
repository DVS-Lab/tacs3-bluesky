# Artifact and frequency reliability audit — November 17, 2026

## Recommendation

Use the offline validation workflow below to distinguish unresolved inputs, insufficient usable observations, and lack of a reproducible task-related rhythm. Do not use a band maximum/minimum, an alpha-minus-five proxy, or a fixed default as evidence of an individualized theta/beta frequency. A failed frequency estimate does not establish that the EEG is bad.

This branch starts from main `ef109bc` and brings forward the separately reviewed v1.2 validation modules from `7c772d0`. They were not present on main when the November presentation was prepared. Version 1.3 adds explicit local ocular screening and raw-versus-filtered drift diagnostics. It does not loosen the carrier or reliability acceptance criteria.

## What the slides and current source establish

Avi's source applies 0.5–45 Hz filtering, a 60 Hz notch, a reference including Fp1, rejection above ±200 µV, and epoch detrending. Thus it has some artifact handling, but no explicit localized ocular screen or repeatability requirement. The batch output discards the peak's effect size and boundary flag. A forced maximum/minimum can be returned even without the expected direction or a localized peak.

The committed 1.5-second batch CSV contains 55 theta TFR values; 35 are exactly 4 or 8 Hz, and only three specparam theta values are present. With the 1.3-second window, 38 of 55 theta TFR values are boundaries. Nine change, with a mean absolute difference of 0.08636 Hz and maximum 1.75 Hz. This is window sensitivity, not independent reliability validation. Neither a boundary value nor lack of a specparam peak alone diagnoses bad EEG.

Specparam uses half-second Welch segments (2 Hz native bin spacing) after averaging channel voltages; opposite phases can cancel before power is measured. The decision baseline also reaches the epoch boundary without sufficient real-data wavelet support. The GUI selects a finite candidate/fallback without demonstrating reliability and previously could pair different phases or substitute an unrelated EEG file. These are analysis defects independent of electrode impedance.

The code uses a real `10*log10(power/baseline_power)` calculation. The presentation's example of subtracting linear powers and labelling the difference dB is a slide error, not that particular implementation bug. Its description of a 20 Hz beta fallback is not present in the inspected GUI source. Source inspection cannot establish which executable Avi installed.

## What changed

- File selection now requires explicit matching identity, session, task and phase; exact SHA256 duplicates are counted once. Ambiguous and missing pairs remain explicit failures. Numeric zero padding is supported without treating distinct alphanumeric identifiers as equal.
- Bad channels are screened before reference. Fp1 and EXT are excluded from the scalp reference. Reference contributors are also checked within each epoch so transient artifacts cannot spread silently through the reference.
- Local Fp1 deflections are detected using a recording-wide robust threshold and checked for local spread into the frontal ROI. Fp1-only events generate warnings. Missing, flat, nonfinite and poor-quality ocular proxies are explicitly labelled. This rejects suspect epochs; it does not subtract an ICA component or certify blink removal.
- Raw amplitude and slope are recorded alongside filtered amplitude. A removable slow trend is not automatically called unusable EEG. These drift diagnostics do not independently reject trials.
- Power is calculated per channel before averaging. Per-trial mean-log-ratio normalization, real-data wavelet padding, full-epoch carrier estimation, task modulation, split-half, cross-fit and block-bootstrap checks are retained from v1.2. They are provisional within-recording checks, not established cross-day test–retest reliability.
- The Python GUI's automatic stimulation-frequency export is disabled, with a direct pointer to the offline workflow. Its historical calculation functions remain for review. The existing `.exe` was not rebuilt or changed. No participant protocol, acquisition script or raw data was modified.

The ocular settings are provisional: 50 µV minimum Fp1 peak, six robust standard deviations, 10 Hz low-pass for detection, ±250 ms local window, at least 10 µV ROI deflection and absolute local correlation of 0.6. Rejecting anywhere in the full padded epoch is conservative. Fp1 is a proxy, not dedicated EOG; shared frontal neural activity can also correlate. Manual labels are needed before claiming native-blink sensitivity or specificity.

## Rerun and validation results

All **105 tests pass**, including 13 artifact challenges. The existing carrier benchmark was rerun under a source/config lock: **54/54 known-frequency cases accepted at the correct frequency, 0/81 unsuitable controls accepted**. This is a regression recheck of previously used simulation cases, not a fresh independent validation dataset. An additional continuous-signal test rejects all 44 repeated ocular theta bursts without producing an individualized frequency.

The full current-data run covers **139 recordings and 349 task-specific estimates; none passes all provisional acceptance criteria**. The previous v1.2 screen on these identical recordings also produces **0/349**, so the absence of qualifying frequencies is not caused solely by the new ocular screen. Carrier/reliability rules were unchanged.

The final v1.3 classification is:

- 106 estimates blocked by unresolved input/timing.
- 100 have too few eligible trials before artifact screening.
- 85 are limited by channel availability or retained-trial yield.
- 58 have adequate yield but no qualifying reproducible task-related carrier.

These are analysis counts, not independent participants. A recording contributes several task-specific estimates. None of these categories alone proves defective EEG acquisition or resolves the separate impedance question.

Among the 15,371 eligible estimand-trial instances that reach paired artifact screening, retention changes from **9,736 to 7,695**. All 2,041 additional exclusions come from the localized ocular-spread screen, with exactly identical filtered/referenced arrays and channel membership. Of these flags, 864 use a proxy labelled poor quality and 1,177 use the ordinary proxy status. They are **suspected ocular contamination, not 2,041 confirmed blinks**. Twenty-three estimates move from adequate-yield/carrier failure into the yield-limited category. This stricter screen needs manually labelled native examples before claiming a validated false-positive rate; retain v1.2 as a sensitivity comparator.

The final run was repeated after the alphanumeric identity guard fix, with identical counts, candidate frequencies, acceptance decisions and failure reasons. All inventoried raw-input hashes remain unchanged. `docs/artifact_reliability_results.json` records aggregate results and exact analysis hashes; participant-level results stay local in `validation_outputs/artifact_audit_final_20261117/`.

## Data available on GitHub

At main `ef109bc`, 380 tracked `.easy` files represent 342 unique byte contents and 38 duplicate copies; 358 `.info` files are tracked. Every inventoried tracked input is locally available and matches the fetched Git source.

The manifest includes 139 distinct pre/post task recordings: 38 historical and 101 additional. Of these, 121 have all required paths; 18 have unresolved inputs (nine historical unmatched behavior, four ambiguous behavioral matches, two missing metadata and three missing explicitly matched behavioral files). Complete paths do not guarantee valid identity, timing or EEG.

Another 203 unique EEG contents are excluded from this pre/post analysis. Importantly, 106 are numbered Bandit/SST runs without verified pre/post phase; the others have stimulation, template, generic-run, test or incomplete names. These are filename categories, not proof of stimulation delivery. They are inventoried rather than silently reassigned or discarded. A master acquisition/session log is needed to establish whether every collected recording is on GitHub and what those runs represent.

## Run it

From the repository root, use Python 3.11 in a separate environment (no NIC/PsychoPy needed):

```sh
python -m venv .venv
# Activate .venv using your operating system's normal command.
python -m pip install -r requirements-validation.txt
python -m pytest tests -q
python code/build_rhythm_manifest.py --ref origin/main --output-name current_inventory
python code/validate_rhythms.py --manifest validation_outputs/current_inventory/manifest.json --output-name artifact_review --skip-legacy
```

Use a new output name for every run. Do not overwrite the original EEG/behavior or resolve a failure by selecting the newest file. Generated inventories, participant paths, per-trial decisions and plots remain in ignored `validation_outputs/`.

Start with `artifact_review/qc_summary.csv`. Inspect `analysis_limiting_stage`, `failure_reasons`, retained/eligible counts and the result's split/bootstrap diagnostics. Each recording has `channels.json`; each estimand has `events.csv`, `result.json`, `spectrum.csv`, `carrier_spectrum.csv` and `spectra_tfr.png` when computable. `events.csv` records exact exclusion reasons and raw/filtered/ocular diagnostics. No result in this workflow authorizes a stimulation frequency; the separate selector refuses these offline outputs.

## Script codebook

- `code/build_rhythm_manifest.py`: inventory Git-tracked recordings and build explicit, hash-bound input pairs. It does not infer missing phase or timing.
- `code/validate_rhythms.py`: entry point for QC, estimation, plots and `qc_summary.csv`.
- `code/rhythm_validation_io.py`: identities, units, channel metadata, clocks and event definitions.
- `code/rhythm_validation_core.py`: filtering/reference, artifact screening, epoching and normalized time-frequency power.
- `code/rhythm_validation_carrier.py`: spectral carrier identification and reliability/task-modulation checks.
- `code/rhythm_validation_report.py`: secondary descriptive estimates, plots and summary files.
- `code/rhythm_validation_config.json`: versioned, explicit preprocessing and acceptance settings.
- `analysis/Avi theta_beta_analysis/frequency_analysis.py`: historical exploratory batch calculation underlying the presentation; not the qualified-frequency workflow.
- `code/calculate_theta_beta.py` / `calculate_theta_beta.exe`: historical GUI source / existing executable; the new source blocks automatic export, but does not patch a previously built executable.

## Interpretation and next evidence

Keep task-specific estimands distinct. Theta from one task need not equal theta from another; the current validated event definitions include Bandit feedback theta, response beta and SST stop-related beta. A peak in one condition cannot fill a missing peak in another. Pre/post task changes also do not provide a pure independent repeatability test.

Synthetic tests can show that the estimator recovers known oscillations and rejects specified confounds. They cannot prove that a native recording contains the targeted biological generator or that an Fp1 event was a blink. The next external inputs should be existing records: the executable/build identity actually used, acquisition/channel/reference metadata, resolution of the manifest's specific missing/ambiguous links and a small manually labelled set of native artifact examples. Do not collect another unlabelled batch merely to obtain more numerical peaks.

Method references: MNE documents [peak-to-peak epoch rejection](https://mne.tools/stable/generated/mne.BaseEpochs.html) and the need to inspect artifacts when using [ICA correction](https://mne.tools/stable/auto_tutorials/preprocessing/40_artifact_correction_ica.html). Those references support separating filtering, rejection and correction; they do not validate this project's custom thresholds or justify automatic ICA on this sparse montage.
