# Reused methods and inspected sources

Only small scoring methods were adapted. Neither source repository is imported,
modified, or required to run this pipeline. Study-specific registries, colors,
clinical variables, condition maps and plotting frameworks were not ported.

## Bandit source

`DVS-Lab/tacs_bandit`, inspected local revision
`460ecbb1ad4e2a3a3899d0324145d00b0f5934b9`:

* `code/data_loading.py::preprocess_trials`: preceding choice/reward and valid
  within-run transitions. Adapted to source-file boundaries (so same run labels in
  different sessions never join), explicit adjacency, strict Boolean outcomes,
  and chosen flower identity. Its `get_latest_run_files` was deliberately **not**
  reused: completeness and explicit ambiguity take precedence over recency.
* `code/wsls.py::compute_wsls`: mean stay after win and mean shift after loss,
  including denominators. Session estimates sum run counts without joining runs.
* `code/reversal_analysis.py::identify_reversals` and
  `compute_reversal_accuracy`: recorded `current_good` changes and aligned accuracy.
  The export keeps a separate row for each reversal/offset and exact source run.
* `code/derived_behaviour.py::_subject_condition_features`: RT summaries,
  missed-response rate, five-trial pre/post-reversal characterization. The earlier
  task's 200–1990-ms RT filter and clinical/age analyses were not inherited.

`code/rl_models/models.py`, `models_within.py`, `test_recovery_within.py` and the
module layout were inspected. They provide RW, dual-outcome RW, Pearce–Hall and
hierarchical within-participant methods. No fit is required or run here. The
within-participant implementation is the relevant future starting point, with
three visit conditions, source-run resets, parameter/condition-effect recovery,
and predictive checks adapted before use.

## SST source

`DVS-Lab/gambling-2025` was available locally. Both requested commits were
inspected with `git show`:

* `2849b4d95916248118718b5f10be74d023deb819`, `code/sst_analysis.Rmd`.
* `4dc7c81c947fb6693a3e1b18307d170387fe5c81`, `code/sst_analysis.py`.

Those particular diffs primarily add imaging ROI extraction/reporting. The Python
script at the requested commit already contains `compute_run_exclusion_metrics`,
an integration rank calculation, stop response probability, go accuracy, failed
stop versus go RT, SSRT exclusions, and minimum pooled stop counts. Those small
methodological components were adapted into `sst.py`; ROI/clinical group joins and
the script's top-level analysis framework were not copied.

Changes necessary for TACS-3: reconstruct the post-update active SSD; retain early
intended stop failures; separate EEG/pre/post schemas; handle omission sentinels;
use all responding go RTs plus maximum-RT omission replacement; use an explicit
ceil empirical rank; apply a stricter provisional go-accuracy gate; keep count
gates explicit at run versus visit level; recalculate rather than average pooled
SSRT; and never emit a failed estimate as valid. The source's correct-go-only,
low-count SSRT calculation was not inherited unchanged.

## Current experiment and independent reference

The acquisition source of truth was `tacs3-bluesky` main at
`016305126565835ee76d345d3f9edae40b30874a`: `code/bandit_main.py`,
`code/sst_main.py`, `code/sst_eeg.py`, `code/config.json`, and
`code/protocol_generator.py`. Acquisition source hashes are retained on each run.
No acquisition module is imported: importing task programs could launch their GUI.

The original analysis methods were checked against
[Verbruggen et al. (2019), eLife 8:e46323](https://elifesciences.org/articles/46323).
Its integration/omission guidance and P(respond) bounds informed the SST scoring;
the remaining project thresholds are provisional and transparently configurable.

The rhythm PR documents were read from the existing remote branch at
`b3fa31557b5b4251912b96313a5f5d0ead851232`. The branch was not checked out, merged,
or modified; its failed physiological reliability results remain separate from
behavioral validity. Review date: 2026-10-20.

Identity handling was corrected in version 0.2 following Avi's recruitment-namespace
explanation: preserve G/R prefixes and leading zeros, and use an explicit evidenced
alias map for legacy records. This policy is local to the analysis and changes no
acquisition code or historical filenames; see [IDENTITY_ALIASES.md](IDENTITY_ALIASES.md).
