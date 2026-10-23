# Avi: step-by-step review of the pilot rhythm validation

**The immediate handoff has been narrowed. Use [Jacob and Avi: the specific information we need](next_steps_for_jacob_avi.md).** The longer review below is optional background, not a new assignment. The [latest report](acceptance_calibration_followup.md) records 67 passing tests, one recovered input, and nine remaining unresolved recordings. Older expected counts and source lists below describe the earlier snapshot.

**Current result:** [Corrected normalization validation and recommendation](meanlogratio_validation_decision.md). The current v1.1 workflow is for offline analysis; individualized stimulation is not supported by this validation.

**Which script produces `qc_summary.csv`?** Run `code/validate_rhythms.py`. The [codebook in the code folder](../code/README.md) explains the supporting scripts, functions, settings, and output fields.

**Start with the browser review below. You do not need to install software or rerun the analysis to do this review.** The pilot analysis has already been completed, and automated tests plus a real-data smoke test passed on Windows and Linux. A local rerun is optional and described at the end.

Your immediate job is to check the recording history and source files against what happened in the lab, document any discrepancies, and send David your findings. You are not being asked to choose scientific thresholds or approve individualized stimulation. No individualized estimate passed all the provisional QC rules; this does not establish that participants lack theta or beta rhythms.

## 1. Open the reviewed materials (no installation)

1. Sign into GitHub with an account that can access DVS-Lab and open [PR #1](https://github.com/DVS-Lab/tacs3-bluesky/pull/1). If you cannot access it, tell David that repository access is needed; the review can also be done from the handoff ZIP he supplies.
2. Read the [pilot report](pilot_rhythm_validation_report.md), especially “Coverage and result” and the six-participant table. You do not need to review the code diff first.
3. Open the [review worksheet](avi_rhythm_review_worksheet.md). Copy it into a text document in the lab's approved working location and fill in the answers as you follow steps 2–5. “Unknown” and “not found in the locations checked” are useful answers.
4. Open the [QC summary](../validation/pilot_results_meanlogratio_v1_1/qc_summary.csv). In GitHub, use its table view, or download a copy and open it in Excel. If using the ZIP, extract it first and open `validation/pilot_results_meanlogratio_v1_1/qc_summary.csv`. Inspect copies without saving changes to source files.

These links point to the review branch. The checked-in reference outputs are under `validation/pilot_results_meanlogratio_v1_1`; `validation_outputs` exists only after a local rerun. No StarStim, NIC-2, PsychoPy, or connected hardware is needed.

## 2. Check what the summary is saying

In the QC summary, find subject `10034` and the rows whose `estimand` is `response_beta_erd` (response-related beta suppression). If using Excel, select the header row and choose **Data → Filter**; filter those two columns.

| Task and phase | Eligible trials (`n_eligible`) | Retained trials (`n_retained`) | Expected QC |
|---|---:|---:|---|
| Bandit pre | 120 | 115 | FAIL |
| Bandit post | 119 | 114 | FAIL |
| SST pre | 53 | 3 | FAIL |
| SST post | 47 | 30 | FAIL |

“Eligible” means trials of the type this analysis uses; “retained” means the trials remaining after timing and artifact checks. SST response beta uses correct go trials, not all SST trials. Read `failure_reasons` for why an estimate failed. A number in `candidate_hz` is only a diagnostic value; the `individualized_frequency_hz` column is empty for all reference results.

Open these three images, using the links or the same paths within the extracted ZIP:

1. [10034 Bandit pre spectrum and time-frequency plot](../validation/pilot_results_meanlogratio_v1_1/10034_ses-1_bandit_pre_20260918104411/response_beta_erd/spectra_tfr.png). The left panel shows power change by frequency; the right shows power change around responses. Record that 115/120 trials remain but the result still fails. A dip in the curve alone does not establish a reliable individual frequency.
2. [10034 SST pre channel QC](../validation/pilot_results_meanlogratio_v1_1/10034_ses-1_sst_pre_20260918103527/channel_qc.png). Note which channels are flagged, and whether the session notes mention poor contact, movement, blinking, or other acquisition problems. If no notes exist, write “no session notes available.”
3. [10034 SST pre spectrum and time-frequency plot](../validation/pilot_results_meanlogratio_v1_1/10034_ses-1_sst_pre_20260918103527/response_beta_erd/spectra_tfr.png). Only 3/53 eligible trials remain. Open its [trial exclusion log](../validation/pilot_results_meanlogratio_v1_1/10034_ses-1_sst_pre_20260918103527/response_beta_erd/events.csv) and read the `reason` column. `ocular_artifact_spreads_to_roi` means the screen detected eye-related activity spreading into the analyzed frontal channels. `not_correct_go` means that trial is outside this particular analysis, not necessarily a bad trial.

Write observations in the worksheet. You do not need to judge whether the provisional thresholds are scientifically optimal. If a plot or exclusion seems inconsistent with your knowledge of the session, identify the recording and the specific discrepancy.

## 3. Verify the flagged recording/event matches

The [input manifest](../validation/pilot_manifest.json) is the list of exactly which files were paired. Open it and use **Ctrl+F** to find a recording ID from the worksheet. Within that entry:

- `eeg` is the EEG recording path.
- `events` is the behavioral trial file path; `null` means no verified match was established.
- `metadata` is the associated recording-information file.
- `match_evidence` explains an existing match; `missing_reason` explains an unresolved one.

Use those paths to locate the files in GitHub or a local repository copy. Compare participant, session, task, pre/post phase, date, and run against the lab session log and original acquisition/export folders. A similarly named file or a nearby start time alone does not establish a match. The task and EEG may have been started at different times.

Start with these four 10037 recordings, all dated **September 16, 2026**. Exact IDs and source paths are in the worksheet:

| Recording | Current finding | What to check in lab records |
|---|---|---|
| Bandit pre, EEG filename time 10:59:44 | Unix and LSL timing is inconsistent | Was there a restart, clock adjustment, or another export? Locate any original timing/acquisition logs. A documented absence of such logs is also useful. |
| SST pre, 10:52:02 | Too few selected response times fall within the EEG recording | Do the paired files describe the same run? Was EEG started late or stopped early? |
| SST post, 11:31:50 | No eligible correct-go responses in the paired file | Check the original behavioral file's `stop`, `go_correct`, and response fields. Was this the intended completed run, an aborted run, or a different export? |
| Bandit post, 11:39:55 | Too few selected response times fall within the EEG recording | Confirm the post-run identity and whether the task continued beyond EEG recording. |

For details, open the recording's `response_beta_erd/result.json` under `validation/pilot_results_meanlogratio_v1_1` and search for `failure_reasons` and `timestamp_diagnostics`. These are readable text fields; no Python is required. If present, `events.csv` gives the trial-level reason. Some input failures occur before a trial log or plot can be produced, so a missing plot is not itself a new error.

The two 10037 post event files are already included: SST under `data/sub-10037`, Bandit under `behavioral-data/sub-10037`. Please verify these matches; do not assume the files are missing because they are outside `pilot_data`.

If you find a possible correction, record the existing path, proposed source path, and evidence in the worksheet. Keep the original bytes. Do not rename files, edit the manifest, shift timestamps, or replace inputs during this review. The correction needs to be incorporated into a documented analysis rerun.

## 4. Look for missing sources and the historical SST script

The worksheet lists all **10 recordings with no verified behavioral match**, grouped by participant and date. For each:

1. Check the lab's original session folder and behavioral export/archive location. Search for the participant ID and recording date, including `.csv` and `.tsv` files and any session/timing logs.
2. Record where you searched. If you find a candidate, record its exact filename/location and the evidence linking it to the task, session, and run. Keep it in the lab's approved storage; do not upload participant data to a public issue or comment.
3. For 10890, there are two recordings labeled SST pre on the same day: do not choose one just from that label. Look for run/session notes. For 12193, session identity is unverified: look for the original session record before assigning a session number.
4. If nothing can be verified, write “unresolved” and list the searched locations. No invented replacement or clock offset is needed.

Also look for the **exact script/notebook and inputs that produced the historical SST frequencies** for 10034, 10037, 10052, 10085, 10383, and 10696. Check the analysis computer's scripts/notebooks and saved analysis folders. Record the filename, version/commit if available, command or notebook used, and associated output file. Historical Bandit values were reproduced (11/11); the original expanded SST implementation has not been located. A script that merely produces similar values is not evidence it was the original. “Not located” is an acceptable finding.

## 5. Send David a completed review

Return the filled-in worksheet through the lab's approved sharing location. Include:

- Whether the 10037 pairings are confirmed, contradicted, or still unknown, with the evidence for each.
- Candidate source files for the 10 unresolved recordings, or the locations searched without finding a verified match.
- Whether the historical SST script was located and where.
- Brief observations about the three diagnostic plots and any relevant session notes.
- Any questions requiring David's scientific judgment, such as whether to revisit the provisional artifact or stability criteria.

You are finished with this review when each worksheet item has an answer, including “unknown” where appropriate. You do not have to fix every data problem or obtain a passing frequency. Leave PR #1 unmerged; these results do not authorize changes to stimulation assignments, protocols, task timing, or experimental configuration. David decides the next scientific step after reviewing the evidence.

## 6. Optional: reproduce the analysis on the lab Windows computer

This checks that the lab computer can reproduce the analysis. It is **not a prerequisite for steps 1–5**. Previously completed checks: [Windows/Linux CI run](https://github.com/DVS-Lab/tacs3-bluesky/actions/runs/39985644935) and [current validation report](meanlogratio_validation_decision.md).

### A. Set up a separate analysis copy

Open **PowerShell** from the Windows Start menu. Check prerequisites:

```powershell
git --version
py -3.11 --version
```

The Python command should report Python 3.11.x. If either command is unavailable, ask the lab's computer support to provide Git and Python 3.11 with the Windows Python launcher; you can still complete the browser review. Do not modify the acquisition computer's existing experiment environment.

In File Explorer, navigate to the approved folder where you want a separate analysis copy. Click the address bar, type `powershell`, and press Enter. Run each line below, waiting for it to finish before running the next:

```powershell
git clone --branch codex/rhythm-estimation-validation https://github.com/DVS-Lab/tacs3-bluesky.git tacs3-rhythm-validation
cd tacs3-rhythm-validation
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-validation.txt
git rev-parse HEAD
.\.venv\Scripts\python.exe --version
```

Save the commit and Python version in the worksheet. No environment activation or parameter edits are needed. If `tacs3-rhythm-validation` already exists, preserve it: use a different new folder name in both the clone and `cd` commands. If GitHub requests sign-in, use your authorized GitHub account. If a command fails, stop this optional rerun and send David the command and complete error text; do not continue with a partially installed environment.

### B. Run tests, then one participant

From the new `tacs3-rhythm-validation` folder:

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
.\.venv\Scripts\python.exe code\validate_rhythms.py --subject 10034
```

Expected test result for this version: **54 passed, 1 skipped**. The skip is an obsolete SST GUI command-line test; do not launch the experimental task to resolve it. Third-party Matplotlib/Pyparsing deprecation warnings were observed in the reference environment and do not mean a test failed. Report actual failed tests or new errors.

The participant command prints `Outputs: ...`. Open that exact folder in File Explorer under `validation_outputs`. Open `completion.json` with Notepad: expect `completed: true`, `recordings: 4`, and `estimates: 10`. Open its `qc_summary.csv`, filter to `response_beta_erd`, and compare all four rows to the trial-count table in step 2. All ten analyses are expected to fail scientific QC; the individual frequency cells should remain empty. If counts or conclusions differ, record the difference and send the run folder to David before continuing to the full batch.

### C. Optionally run the full pilot batch

If the participant check matches, run:

```powershell
.\.venv\Scripts\python.exe code\validate_rhythms.py
```

Allow several minutes or longer depending on the computer. Open the new folder printed after `Outputs:`. Its `completion.json` should report `completed: true`, **38 recordings, 95 estimates, 0 passing estimates**. A QC `FAIL` is a completed analysis outcome, not a software crash. A traceback or absent `completion.json` means the run did not complete. Completion alone does not establish that the expected data were analyzed: also compare trial counts and failure reasons with the reference summary.

Each run creates a new timestamped folder; older outputs remain intact. If rerun, send David the test summary, commit/Python version, and the completed output folder (or its `completion.json`, `qc_summary.csv`, `original_revised_comparison.csv`, `provenance.json`, and the three plots from step 2). Record any differences from `validation/pilot_results_meanlogratio_v1_1`; run timestamps and computer paths will naturally differ.

**Interpretation:** `PASS` would mean meeting provisional QC, still requiring separately approved deployment. `warnings` records limitations. `FAIL` means no qualified individual frequency. The documented 20-Hz beta and 6-Hz theta fallback options are not participant assignments. Do not raise thresholds to obtain a pass or copy diagnostic values into NIC-2.
