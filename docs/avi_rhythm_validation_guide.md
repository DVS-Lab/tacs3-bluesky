# Avi: offline rhythm validation

This is a **separate analysis checkout**. No StarStim, NIC-2, PsychoPy, or stimulation session is needed. Do not copy its candidate values into NIC-2. This work has not approved a new stimulation policy.

## One-time setup (Windows, PowerShell)

Install Python **3.11** from python.org with the Windows Python launcher, and Git for Windows if absent. Open PowerShell in the folder where you want a separate analysis copy. Run:

```powershell
git clone --branch codex/rhythm-estimation-validation https://github.com/DVS-Lab/tacs3-bluesky.git tacs3-rhythm-validation
cd tacs3-rhythm-validation
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-validation.txt
```

If already in this analysis checkout, start with the `py -3.11` line. No activation, config changes, hardware drivers, or parameter choices are needed.

## Run these three checks

Run from the `tacs3-rhythm-validation` folder:

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
.\.venv\Scripts\python.exe code\validate_rhythms.py --subject 10034
.\.venv\Scripts\python.exe code\validate_rhythms.py
```

The first command tests known synthetic increases **and suppression**, input alignment, artifacts, reproducibility, and the stimulation boundary. One legacy SST test is explicitly skipped: the current experimental script is a GUI and no longer implements that old test's command-line interface. Do not launch the experimental task to resolve this skip.

The second command is the smoke test. The third processes all 38 pilot EEG recordings in the reviewed manifest, including explicit missing-input failures. Allow several minutes; processing time depends on the computer. A QC **FAIL is a completed scientific result**, not a software crash. A completed run prints `Outputs: ...` and contains `completion.json`. A traceback or absent `completion.json` means the run did not complete; send the error to David.

Each run makes a **new timestamped folder** under `validation_outputs`. Originals and older outputs are never overwritten. The reviewed reference results are in `validation/pilot_results`.

## Inspect these outputs

1. Open `qc_summary.csv` and `original_revised_comparison.csv` in the new output folder. Compare trial counts, failure reasons, and frequencies with `validation/pilot_results`; do not expect reliable frequencies just because numbers are shown in the candidate column.
2. Open `10034_ses-1_bandit_pre_20260918104411/response_beta_erd/spectra_tfr.png`. Left: baseline-corrected beta spectrum. Right: response-locked power. Dashed lines mark 13–30 Hz; a red candidate line means it failed QC. A broad dip or an endpoint is not an individualized frequency.
3. Open `10034_ses-1_sst_pre_20260918103527/channel_qc.png` and its `response_beta_erd/spectra_tfr.png`. These show channel contamination and what survived. A plot can correctly say “No retained epochs.”

**PASS** means the candidate meets the current provisional QC rules; it still requires a separately approved deployment. **WARNING** appears in the `warnings` column for limitations such as sparse montage, uncertain software latency, or fewer than 80 trials. **FAIL** means no reliable individualized frequency is available. The `individualized_frequency_hz` cell stays empty; the 20-Hz beta and 6-Hz theta fallbacks are documented options, not assignments.

**Alignment problem:** `event_recording_overlap_below_threshold`, `event_unix_lsl_clock_inconsistency`, or a timestamp/hash/identity error in `result.json`. Read its `timestamp_diagnostics` and `events.csv`; do not shift timestamps or substitute files. Some pilot failures, particularly 10037, are expected.

**Channel problem:** red bars in `channel_qc.png`, too few usable F3/FCz/F4 channels, or many artifact/ocular exclusions in `events.csv`. Fp1 is monitored but excluded from the reference; artifacts still reject a trial when they spread into the analyzed channels. Do not raise thresholds to make a participant pass.

## Send back to David

Send the test summary, Python version (`.\.venv\Scripts\python.exe --version`), the path/name of the completed batch folder, its `qc_summary.csv`, `original_revised_comparison.csv`, `provenance.json`, and the three plots above. Include any traceback or differences from the checked-in reference. Keep participant files within the lab's approved sharing location. No methodological choices or code edits are expected from you.
