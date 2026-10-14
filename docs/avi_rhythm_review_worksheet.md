# Avi: pilot rhythm review worksheet

Copy this worksheet into your own document and return it to David through the approved lab sharing location. Follow the [step-by-step guide](avi_rhythm_validation_guide.md). No installation is required. Fill every item with confirmed, contradicted, unknown, found, or not found, plus the supporting detail. Do not put participant files or sensitive paths in public GitHub comments.

Reviewer: ___  Review date: ___

Materials reviewed: PR #1 / handoff ZIP / other: ___

## A. Three diagnostic images

- 10034 Bandit pre: Does the summary show 115/120 retained and FAIL? ___
- 10034 SST pre channel QC: Which channels are flagged? What do the session notes say, or are notes unavailable? ___
- 10034 SST pre spectrum/trial log: Does the summary show 3/53 retained? Which exclusion reasons appear, and do any conflict with session records? ___
- Other observations/questions for David: ___

## B. Confirm the four 10037 file pairings

For each entry, compare the source paths below with the lab session log and original exports. These are repository-relative paths from the manifest, not assumed paths on your computer.

### 10037_ses-1_sst_pre_20260916105202

- EEG: `pilot_data/Pilot-G10037/20260916105202_10037-1_SST_pre-stim.easy`
- Events: `pilot_data/Pilot-G10037/sub-10037-1_task-SST_pre-stim_2026-09-16_10-51-42.csv`
- Metadata: `stimulation/stimulation-data/20260916105202_10037-1_Run 1.info`
- [Read the analysis diagnostics](../validation/pilot_results/10037_ses-1_sst_pre_20260916105202/response_beta_erd/result.json).
- Pairing: confirmed / contradicted / unknown: ___
- Evidence (session log, run identity, original export, timing log): ___
- Known restart, early stop, clock change, aborted run, or other relevant event; otherwise unknown: ___
- If a different source is proposed: exact location and evidence linking it to this recording: ___

### 10037_ses-1_bandit_pre_20260916105944

- EEG: `pilot_data/Pilot-G10037/20260916105944_10037-1_Bandit_pre-stim.easy`
- Events: `pilot_data/Pilot-G10037/sub-10037-1_task-bandit_pre-stim_2026-09-16_10-58-33.csv`
- Metadata: `stimulation/stimulation-data/20260916105944_10037-1_Run 1.info`
- [Read the analysis diagnostics](../validation/pilot_results/10037_ses-1_bandit_pre_20260916105944/response_beta_erd/result.json).
- Pairing: confirmed / contradicted / unknown: ___
- Evidence (session log, run identity, original export, timing log): ___
- Known restart, early stop, clock change, aborted run, or other relevant event; otherwise unknown: ___
- If a different source is proposed: exact location and evidence linking it to this recording: ___

### 10037_ses-1_sst_post_20260916113150

- EEG: `pilot_data/Pilot-G10037/20260916113150_10037-1_SST_post-stim.easy`
- Events: `data/sub-10037/sub-10037_ses-1_run-02_task-SST_2026-09-16_11-31-36_events.csv`
- Metadata: `stimulation/stimulation-data/20260916113150_10037-1_SST_post-stim.info`
- [Read the analysis diagnostics](../validation/pilot_results/10037_ses-1_sst_post_20260916113150/response_beta_erd/result.json).
- Pairing: confirmed / contradicted / unknown: ___
- Evidence (session log, run identity, original export, timing log): ___
- Known restart, early stop, clock change, aborted run, or other relevant event; otherwise unknown: ___
- If a different source is proposed: exact location and evidence linking it to this recording: ___

### 10037_ses-1_bandit_post_20260916113955

- EEG: `pilot_data/Pilot-G10037/20260916113955_10037-1_Bandit_post-stim.easy`
- Events: `behavioral-data/sub-10037/sub-10037_ses-1_run-02_task-bandit_2026-09-16_11-39-45_events.tsv`
- Metadata: `stimulation/stimulation-data/20260916113955_10037-1_Bandit_post-stim.info`
- [Read the analysis diagnostics](../validation/pilot_results/10037_ses-1_bandit_post_20260916113955/response_beta_erd/result.json).
- Pairing: confirmed / contradicted / unknown: ___
- Evidence (session log, run identity, original export, timing log): ___
- Known restart, early stop, clock change, aborted run, or other relevant event; otherwise unknown: ___
- If a different source is proposed: exact location and evidence linking it to this recording: ___

## C. Ten recordings with no verified behavioral match

For each, list the folders/archives searched and either a candidate source with evidence or “unresolved.” File timestamps below are recording filename timestamps, not independent proof of event alignment. Session “unverified” must not be guessed.

### 10010_ses-1_sst_pre_20260904111037

- EEG: `pilot_data/Pilot-G10010/20260904111037_10010-1_SST_pre-stim.easy`
- Locations searched: ___
- Outcome: candidate found / unresolved: ___
- Candidate event file location (if found): ___
- Evidence for participant, session, task, pre/post phase, and run: ___
- Relevant notes or timing/acquisition logs: ___

### 10010_ses-1_sst_post_20260904114750

- EEG: `pilot_data/Pilot-G10010/20260904114750_10010-1_SST_post-stim.easy`
- Locations searched: ___
- Outcome: candidate found / unresolved: ___
- Candidate event file location (if found): ___
- Evidence for participant, session, task, pre/post phase, and run: ___
- Relevant notes or timing/acquisition logs: ___

### 10579_ses-1_sst_pre_20260903195950

- EEG: `pilot_data/Pilot-G10579/20260903195950_10579-1_SST_pre-stim.easy`
- Locations searched: ___
- Outcome: candidate found / unresolved: ___
- Candidate event file location (if found): ___
- Evidence for participant, session, task, pre/post phase, and run: ___
- Relevant notes or timing/acquisition logs: ___

### 10579_ses-1_bandit_post_20260903201256

- EEG: `pilot_data/Pilot-G10579/20260903201256_10579-1_Bandit_post-stim.easy`
- Locations searched: ___
- Outcome: candidate found / unresolved: ___
- Candidate event file location (if found): ___
- Evidence for participant, session, task, pre/post phase, and run: ___
- Relevant notes or timing/acquisition logs: ___

### 10890_ses-unverified_sst_pre_20260828130310

- EEG: `pilot_data/Pilot-G10890/20260828130310_10890_SST_pre-stim.easy`
- Locations searched: ___
- Outcome: candidate found / unresolved: ___
- Candidate event file location (if found): ___
- Evidence for participant, session, task, pre/post phase, and run: ___
- Relevant notes or timing/acquisition logs: ___

### 10890_ses-1_sst_pre_20260828134105

- EEG: `pilot_data/Pilot-G10890/20260828134105_10890-1_SST_pre-stim.easy`
- Locations searched: ___
- Outcome: candidate found / unresolved: ___
- Candidate event file location (if found): ___
- Evidence for participant, session, task, pre/post phase, and run: ___
- Relevant notes or timing/acquisition logs: ___

### 12193_ses-unverified_sst_pre_20260914112951

- EEG: `pilot_data/Pilot-G12193/20260914112951_12193_SST_pre-stim.easy`
- Locations searched: ___
- Outcome: candidate found / unresolved: ___
- Candidate event file location (if found): ___
- Evidence for participant, session, task, pre/post phase, and run: ___
- Relevant notes or timing/acquisition logs: ___

### 12193_ses-unverified_bandit_pre_20260914113817

- EEG: `pilot_data/Pilot-G12193/20260914113817_12193_Bandit_pre-stim.easy`
- Locations searched: ___
- Outcome: candidate found / unresolved: ___
- Candidate event file location (if found): ___
- Evidence for participant, session, task, pre/post phase, and run: ___
- Relevant notes or timing/acquisition logs: ___

### 12193_ses-unverified_sst_post_20260914121139

- EEG: `pilot_data/Pilot-G12193/20260914121139_12193_SST_post-stim.easy`
- Locations searched: ___
- Outcome: candidate found / unresolved: ___
- Candidate event file location (if found): ___
- Evidence for participant, session, task, pre/post phase, and run: ___
- Relevant notes or timing/acquisition logs: ___

### 12193_ses-unverified_bandit_post_20260914121834

- EEG: `pilot_data/Pilot-G12193/20260914121834_12193_Bandit_post-stim.easy`
- Locations searched: ___
- Outcome: candidate found / unresolved: ___
- Candidate event file location (if found): ___
- Evidence for participant, session, task, pre/post phase, and run: ___
- Relevant notes or timing/acquisition logs: ___

## D. Historical SST analysis provenance

- Exact script/notebook located? yes / no / uncertain: ___
- Locations searched: ___
- Script/notebook filename and approved storage location: ___
- Version/commit and command/notebook execution details, if available: ___
- Input and output files linked to the historical frequencies: ___
- Evidence this actually generated the historical values (not just similar results): ___

## E. Optional Windows rerun

- Performed? yes / no (not required): ___
- Git commit and Python version: ___
- Test summary (expected 50 passed, 1 skipped): ___
- 10034 completion (expected 4 recordings / 10 analyses) and four beta trial counts match the guide? ___
- Full batch, if run (expected 38 recordings / 95 analyses / 0 passing): ___
- Output folder location and differences/errors, if any: ___

## F. Return to David

- Main findings and unresolved items: ___
- Links/locations of candidate source files and session logs: ___
- Questions requiring scientific decisions: ___

Done means all sections A–D and F have answers, including unknown/not found where needed. Section E is optional. No passing frequency, code change, PR merge, or stimulation change is required.
