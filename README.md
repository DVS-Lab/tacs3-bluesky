# tacs3-bluesky

Working scaffold for two tACS3 tasks that estimate task-evoked individualized rhythms and then use those frequencies for StarStim/NIC-2 stimulation runs.

The current structure follows Jimmy's `tacs_bandit` layout: task entry points and EEG helpers live under `code/`, with synthetic workflow tests under `tests/`.

## What This Implements

- `code/bandit_main.py`: two-armed bandit reversal-learning task (PsychoPy). Trial mechanics are identical on every run regardless of stimulation condition; the only run-type distinction is the pre-stimulation `--localizer` baseline run.
- `code/sst_main.py`: Stop Signal Task (PsychoPy), adapted from `DVS-Lab/gambling-2025/stimuli/Scan-SST`. Mirrors `bandit_main.py`'s architecture exactly: no mode/frequency argument, `--localizer` for the pre-stimulation baseline run, LSL trigger sync, and the same duration-or-trial-count stop rule (both tasks share `experiment.run_duration_minutes`, so a run is the same length regardless of task).
- `code/rhythm_estimator.py`: shared power-based estimator for task-evoked theta and beta.
- `code/eeg_lsl_recorder.py`: live StarStim EEG recording over LSL during localizers.
- `code/select_stimulation_frequency.py`: reliable individualized rhythm selection with fixed-frequency fallback.
- `code/run_rhythm_estimation.py`: CLI for estimating bandit and SST theta/beta from localizer EEG.

## Scientific Targets

The primary bandit target is participant-specific feedback-locked theta: task-evoked theta power after reward/loss/miss feedback, not resting intrinsic theta and not PLV.

The beta target is participant-specific decision/response beta: task-evoked beta power aligned to choice/response timing. This is exploratory and reliability-gated in the same way as theta.

For SST, the default targets are stop-signal theta and response beta. These can be changed in `code/config.json` without changing estimator code.

## Standard Bandit Workflow

`bandit_main.py` has no concept of stimulation mode or frequency — trial
timing and structure are identical on every run. Frequency/condition
selection happens entirely outside the task (see below) and is applied by
the operator directly in NIC-2. The only run-type flag is `--localizer`,
for the pre-stimulation baseline run used to estimate individualized
rhythms; every other run is auto-numbered (`run-01`, `run-02`, ...) so
repeated active/sham runs never overwrite each other or reveal condition
in the filename.

```bash
cd code
python bandit_main.py --subject 001 --session 001 --localizer
python run_rhythm_estimation.py --task bandit --subject 001 --session 001 --auto-find --all-defaults
python bandit_main.py --subject 001 --session 001
python bandit_main.py --subject 001 --session 001
```

The task waits for either SPACE or an LSL marker `203` from NIC-2 (sent
when the experimenter starts a stimulation protocol) before beginning
trials, so it can be started in sync with stimulation onset from a
separate machine on the same network. `--localizer` runs skip that wait
and start on SPACE only, since there is no stimulation device running yet.

## Standard SST Workflow

`sst_main.py` has no concept of stimulation mode or frequency either —
same as bandit, and for the same reason. It waits for SPACE or the LSL
marker `203` from NIC-2 before beginning trials (skipped on `--localizer`
runs), and every non-localizer run is auto-numbered.

```bash
cd code
python sst_main.py --subject 001 --session 001 --localizer
python run_rhythm_estimation.py --task sst --subject 001 --session 001 --auto-find --all-defaults
python sst_main.py --subject 001 --session 001
python sst_main.py --subject 001 --session 001
```

Hardware-free smoke test:

```bash
python sst_main.py --subject 001 --session 001 --localizer --test-mode
```

## Frequency Decision Rules

- Reliable individualized theta or beta: use the rounded participant-specific frequency.
- Unreliable individualized theta: use fixed 6.0 Hz unless config says to stop.
- Unreliable individualized beta: use fixed 20.0 Hz unless config says to stop.
- No estimate file: warn and use the configured fallback unless `stop_if_no_*_file` is enabled.

The task does not silently substitute frequencies, but neither `bandit_main.py` nor `sst_main.py` has a mode/frequency argument at all, so neither task's own output can leak condition. Frequency selection for both tasks lives entirely in `select_stimulation_frequency.py`, run and logged separately from the task itself. `select_stimulation_frequency.py` is currently a library with no standalone CLI — the operator reads `run_rhythm_estimation.py`'s QC output and applies the reliability-gated decision rules below manually. A small CLI wrapper for `select_stimulation_frequency.py` is a known follow-up, not yet built.

## StarStim/NIC-2 Notes

Python determines the intended stimulation frequency (via `select_stimulation_frequency.py`) and that's as far as it goes — it does not claim to program NIC-2 directly, and neither task script prompts for or logs an operator-confirmed protocol/frequency anymore. The operator loads/edits the matching NIC-2 protocol and starts the run; `bandit_main.py`/`sst_main.py` sync trial onset to that via the LSL marker `203` trigger, without knowing or recording which protocol was loaded.

## EEG and Blink Notes

The estimator performs channel QC, frequency-domain filtering, average reference over good channels, event alignment, epoch rejection, ROI averaging, split-half checks, and bootstrap checks.

Blink rejection is explicit but depends on the montage. If no EOG/Fp blink channel is available, the estimator writes a QC warning and still uses amplitude/step rejection. With only frontal electrodes, adding a dedicated VEOG/Fp channel would improve blink-specific rejection; otherwise, blink handling is necessarily limited.

## Marker Summary

- Bandit trial start: `10`
- Bandit choice: `20`
- Bandit feedback win/loss/miss: `31`, `32`, `33`
- SST go stimulus: `110`
- SST stop signal: `111`
- SST response: `120`
- SST stop success/failure: `131`, `132`
- SST go correct/incorrect/miss: `133`, `134`, `135`
- Run start/end: `100`, `200`
- NIC-2 stimulation start expected from operator workflow: `203`

## Review Notes From Jimmy's Current Bandit Repo

Jimmy's `tacs_bandit` main branch includes useful localizer/stimulation task code in `code/bandit_main_theta.py`, but `code/bandit_main.py` is still the older task and the theta estimation CLI/tests import a missing `theta_estimator.py`. This repo makes `code/bandit_main.py` the localizer-aware entry point and restores the estimator behind a generalized rhythm API.

## Tests

```bash
python -m unittest discover -s tests
```

The tests generate synthetic EEG for reliable 6.5 Hz feedback theta, reliable decision beta, no peak, edge peak, split-half disagreement, too few epochs, frequency selection, and SST test-mode logging.
