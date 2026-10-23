# Follow-up: baseline normalization and the 10034 beta effect

The earlier [method comparison](10034_beta_method_comparison.md) identifies the choices that move the minimum from 13 to 23 Hz. It does not establish that the larger negative value is physiological suppression. A focused follow-up checks the baseline normalization itself.

## Finding

Using the same 115 retained trials, revised preprocessing, windows, wavelets, and per-channel power averaging:

- Current per-trial log-ratio: minimum **23 Hz, −0.753483 dB**, FAIL.
- Mean-log-ratio alternative: minimum **23 Hz, −0.065088 dB**, FAIL.

The alternative subtracts the mean of baseline log power from mean response-window log power. The current formula instead subtracts the log of mean baseline power. Because the logarithm is nonlinear, these are different quantities. The difference at 23 Hz is about **0.688 dB**. Thus the location of the diagnostic minimum persists, but most of the reported negative effect disappears when baseline and response are centered consistently in log power. This does not prove absence of neural suppression; it establishes substantial normalization sensitivity.

With the same provisional gates, the alternative additionally fails the effect-size/direction criteria and bootstrap frequency certainty. Neither value is an approved individualized frequency. Acceptance thresholds have not been recalibrated for the alternative metric.

## No-change control

For 1,000 independent synthetic trials of stationary Gaussian white noise, with three channels, the same padded epoch duration, sampling rate, seven-cycle transforms, and revised windows, there is no event-related signal change by construction:

- Current log-ratio: mean effect across 13–30 Hz **−0.583188 dB**.
- Mean-log-ratio: mean effect across 13–30 Hz **−0.001044 dB**.

These are band averages, not selected minima. The mean-log-ratio spectrum ranges from approximately −0.053 to +0.059 dB due to finite-sample variation. This is a controlled arithmetic/transform check, not a realistic EEG noise model, a full false-positive-rate study, or an empirical test of frequency reliability. It does not test known signal recovery, acquisition artifacts, or task specificity.

The finding agrees with [Kinley et al. (2026), *Spectral change or Jensen gap?*](https://pubmed.ncbi.nlm.nih.gov/42276213/), which identifies downward bias in log-ratio correction and describes mean-log-ratio as an alternative. Both original and revised pipelines use log-ratio correction with different averaging order; this follow-up changes only the revised normalization and does not claim the original method is unbiased.

## Interpretation and decision

Retain the revised framework's input checks, reproducibility, and explicit rejection of unreliable frequencies. Correct and validate the normalization before promoting the revised estimator for participant frequency selection. Mean-log-ratio is a justified candidate for event-related log-power analysis, but this focused check alone does not establish the most reliable frequency estimator across participants or tasks. Confirm known signal recovery, evaluate more realistic nulls, calibrate acceptance criteria, and assess within-task repeatability before deployment.

Task/event-specific estimates need not agree across tasks. Each must independently demonstrate a reproducible target signal; choosing a separate number per task does not resolve failed identification. Response-related beta suppression and stop-related beta enhancement remain distinct targets. No live settings or stimulation assignments were modified.

## Reproduction

From a checkout with the pinned validation environment, write to a new output file:

```powershell
.\.venv\Scripts\python.exe validation\experiments\check_10034_normalization.py --repo . --out validation_outputs\10034-normalization-check.json
```

The [experiment script](../validation/experiments/check_10034_normalization.py) recomputes native retained epochs and evaluates both normalization formulas, then runs the seeded stationary control. It checks the reproduced current effect and the no-change control's mean. [Saved results](../validation/10034_beta_comparison/normalization_check.json) include spectra, trial standard errors for the stationary control, revised QC results, configuration, input/source hashes, and the experiment hash. The primary estimation code and its saved reference outputs are unchanged.
