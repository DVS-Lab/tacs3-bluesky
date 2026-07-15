# tacs3-bluesky

Working scaffold for two tACS3 tasks that estimate task-evoked individualized rhythms and then use those frequencies for StarStim/NIC-2 stimulation runs.

The current structure follows Jimmy's `tacs_bandit` layout: task entry points and EEG helpers live under `code/`, with synthetic workflow tests under `tests/`.

## What This Implements

- `code/bandit_main.py`: localizer-aware two-armed bandit task based on Jimmy's individualized theta branch.
- `code/sst_main.py`: Stop Signal Task workflow adapted from `DVS-Lab/gambling-2025/stimuli/Scan-SST`.
- `code/rhythm_estimator.py`: shared power-based estimator for task-evoked theta and beta.
- `code/eeg_lsl_recorder.py`: live StarStim EEG recording over LSL during localizers.
- `code/select_stimulation_frequency.py`: reliable individualized rhythm selection with fixed-frequency fallback.
- `code/run_rhythm_estimation.py`: CLI for estimating bandit and SST theta/beta from localizer EEG.

## Scientific Targets

The primary bandit target is participant-specific feedback-locked theta: task-evoked theta power after reward/loss/miss feedback, not resting intrinsic theta and not PLV.

The beta target is participant-specific decision/response beta: task-evoked beta power aligned to choice/response timing. This is exploratory and reliability-gated in the same way as theta.

For SST, the default targets are stop-signal theta and response beta. These can be changed in `code/config.json` without changing estimator code.

## Standard Bandit Workflow

```bash
cd code
python bandit_main.py --mode LOCALIZER_FAST_THETA --subject 001 --session 001
python run_rhythm_estimation.py --task bandit --subject 001 --session 001 --auto-find --all-defaults
python bandit_main.py --mode ITHETA_TACS --subject 001 --session 001 --run 1
python bandit_main.py --mode IBETA_TACS --subject 001 --session 001 --run 1
```

Fixed-frequency controls/fallbacks remain available:

```bash
python bandit_main.py --mode FIXED_THETA_TACS --subject 001 --session 001 --run 1 --frequency 6.0
python bandit_main.py --mode FIXED_BETA_TACS --subject 001 --session 001 --run 1 --frequency 20.0
```

## Standard SST Workflow

```bash
cd code
python sst_main.py --mode LOCALIZER_SST --subject 001 --session 001
python run_rhythm_estimation.py --task sst --subject 001 --session 001 --auto-find --all-defaults
python sst_main.py --mode ITHETA_TACS --subject 001 --session 001 --run 1
python sst_main.py --mode IBETA_TACS --subject 001 --session 001 --run 1
```

Hardware-free smoke test:

```bash
python sst_main.py --mode LOCALIZER_SST --subject 001 --session 001 --test-mode
```

## Frequency Decision Rules

- Reliable individualized theta or beta: use the rounded participant-specific frequency.
- Unreliable individualized theta: use fixed 6.0 Hz unless config says to stop.
- Unreliable individualized beta: use fixed 20.0 Hz unless config says to stop.
- No estimate file: warn and use the configured fallback unless `stop_if_no_*_file` is enabled.

The task does not silently substitute frequencies. Operator-facing output and CSVs log intended frequency, confirmed frequency, rhythm source, estimate path, reliability flag, and reason.

## StarStim/NIC-2 Notes

Python determines the intended stimulation frequency and displays operator instructions. It does not claim to program NIC-2 directly. The operator should load/edit the matching NIC-2 protocol, confirm the actual protocol/frequency, and then start the run. The task logs the operator-confirmed frequency.

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
