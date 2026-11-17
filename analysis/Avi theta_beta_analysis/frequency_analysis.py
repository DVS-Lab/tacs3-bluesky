#!/usr/bin/env python3
"""Batch individualized theta / beta frequency estimation.

Set the three folder paths in the "EDIT THESE PATHS" block near the top of this
file, then run the script:

  STIM_DIR     - folder containing the stimulation (EEG .easy) data
  BEHAVIOR_DIR - folder containing the behavioral (.csv) data
                 (may be the same folder as STIM_DIR)
  OUTPUT_DIR   - folder where the results CSV is saved

Only the files sitting directly in each folder are used (sub-folders are NOT
searched). Subject ID (letters/digits, e.g. G11033) and session are read from
the file names. For each session n and each task (Bandit, SST) it looks for:

    *<ID>-<n>_Bandit_pre-stim.easy      *<ID>-<n>_SST_pre-stim.easy
    *<ID>-<n>_Bandit_post-stim.easy     *<ID>-<n>_SST_post-stim.easy
    sub-<ID>-<n>_task-bandit_pre-stim*.csv   sub-<ID>-<n>_task-SST_pre-stim*.csv
    sub-<ID>-<n>_task-bandit_post-stim*.csv  sub-<ID>-<n>_task-SST_post-stim*.csv

Sessions are discovered automatically from the filenames, so any number of
sessions is supported. Pre and post are analyzed independently.

Bandit:
    theta: Specparam, Morlet TFR, IAF-5  (feedback epochs / posterior alpha)
    beta : Morlet TFR ERD                (choice epochs)
SST:
    beta : Morlet TFR ERD                (epochs around stim_onset_unix_time,
                                          0 to 1.5 s after onset, all trials)

Output: batch_theta_beta_results.csv in OUTPUT_DIR, one row per subject-session
(e.g. 10001-ses1) and one column per measurement
(e.g. bandit_pre_theta_specparam, sst_pre_beta_tfr).

Behavior on problems:
  * Missing file(s) or failed analysis -> values left blank, script continues.
  * Duplicate matching files           -> the first and last Unix time of every
                                          candidate .easy and behavior CSV are
                                          compared, and the EEG/CSV pair that
                                          overlaps the most in time is used.
                                          If no pair can be chosen (no overlap,
                                          unreadable times, a tie, or nothing to
                                          pair with), that subject is not
                                          analyzed; every cell in its output
                                          rows says DUPLICATE_MESSAGE and the
                                          script moves on to the next subject.
"""

import os
import re
import sys
import traceback
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import signal
from scipy.ndimage import gaussian_filter1d

try:
    from specparam import SpectralModel
    SPECPARAM_AVAILABLE = True
except ImportError:
    SpectralModel = None
    SPECPARAM_AVAILABLE = False


# =====================================================================
# CONFIGURATION
# =====================================================================

# ---------------------------------------------------------------------
# EDIT THESE PATHS
# ---------------------------------------------------------------------
# Use a raw string (r"...") for Windows paths, e.g.
#   STIM_DIR     = Path(r"C:\Study\EEG_stimulation_data")
#   BEHAVIOR_DIR = Path(r"C:\Study\Behavioral_data")
#   OUTPUT_DIR   = Path(r"C:\Study\Results")
# Only files sitting directly in each folder are used; sub-folders are NOT
# searched. The two folders may be the same.
STIM_DIR = Path(r"/Users/avidachs/Documents/GitHub/tacs3-bluesky/stimulation/stimulation-data")
BEHAVIOR_DIR = Path(r"/Users/avidachs/Documents/GitHub/tacs3-bluesky/stimulation/pre-stimulation-participant-responses")
OUTPUT_DIR = Path(r"/Users/avidachs/Documents/GitHub/tacs3-bluesky")   # created if it does not exist

OUTPUT_NAME = "batch_theta_beta_results_1p3.csv"

# Bandit feedback analysis window, in seconds relative to feedback onset.
# Used by BOTH theta measures (Specparam and TFR). In the bandit task the next
# trial's fixation cross appears 1.0 s after feedback onset and its flowers at
# 1.3 s, so the window should not extend past 1.3 s.
FEEDBACK_WINDOW = (0.1, 1.3)
# ---------------------------------------------------------------------

CONDITIONS = ("pre", "post")

# Task name -> token used in filenames (matching is case-insensitive).
TASK_TOKEN = {"bandit": "Bandit", "sst": "SST"}

HIGHPASS = 0.5
LOWPASS = 45.0
NOTCH = 60.0
NOTCH_Q = 30.0
EPOCH_REJECT_UV = 200.0
NV_TO_UV = 1e-3
SRATE = 500.0

SPECPARAM_THETA_BAND = (4.0, 8.0)
SPECPARAM_FIT_RANGE = (2.0, 40.0)
SPECPARAM_FEEDBACK_ANALYSIS = FEEDBACK_WINDOW
SPECPARAM_WELCH_SECONDS = 0.5

THETA_SEARCH_BAND = (4.0, 8.0)
ALPHA_SEARCH_BAND = (8.0, 13.0)
BETA_SEARCH_BAND = (13.0, 30.0)

FEEDBACK_EPOCH = (-1.5, 2.0)
FEEDBACK_BASELINE = (-0.8, -0.1)
FEEDBACK_ANALYSIS = FEEDBACK_WINDOW

DECISION_EPOCH = (-1.5, 0.5)
DECISION_BASELINE = (-1.5, -1.0)
DECISION_ANALYSIS = (-1.0, -0.1)

# SST: beta ERD in the 1.5 s after stimulus onset, vs. a pre-onset baseline.
SST_EPOCH = (-1.5, 2.0)
SST_BASELINE = (-1.0, -0.5)
SST_ANALYSIS = (0.0, 1.5)

THETA_FREQS = np.arange(THETA_SEARCH_BAND[0], THETA_SEARCH_BAND[1] + 0.25, 0.25)
DECISION_FREQS = np.arange(BETA_SEARCH_BAND[0], BETA_SEARCH_BAND[1] + 0.5, 0.5)

N_CYCLES = 5
SMOOTH_SIGMA = 1.0

FEEDBACK_EVENT_COL = "feedback_onset_unix_time"
DECISION_EVENT_COL = "choice_onset_unix_time"
SST_EVENT_COL = "stim_onset_unix_time"

# Original 1-based channel numbers.
FRONTAL_CHANNELS = (1, 3, 5)         # F3, FCz, F4
POSTERIOR_ALPHA_CHANNELS = (6, 7)    # P4, P3
REF_CHANNELS = (1, 2, 3, 4, 5, 6, 7)  # all scalp channels; excludes EXT

BANDIT_MEASURES = ("theta_specparam", "theta_tfr", "theta_iaf5", "beta_tfr")
SST_MEASURES = ("beta_tfr",)
TASK_MEASURES = {"bandit": BANDIT_MEASURES, "sst": SST_MEASURES}


DUPLICATE_MESSAGE = "DUPLICATE FILES FOUND - not analyzed"


def column_name(task, cond, measure):
    return f"{task}_{cond}_{measure}"


# =====================================================================
# FILE DISCOVERY
# =====================================================================

_TOKENS = "|".join(re.escape(t) for t in TASK_TOKEN.values())
_TOKEN_TO_TASK = {v.lower(): k for k, v in TASK_TOKEN.items()}

# Subject IDs may contain letters and digits (e.g. G11033, 10085).
# e.g. 20261113100137_G11033-3_Bandit_pre-stim.easy -> (G11033, 3, Bandit, pre)
EEG_PATTERN = re.compile(
    rf"(?<![A-Za-z0-9])([A-Za-z0-9]+)-(\d+)_({_TOKENS})_(pre|post)-stim\.easy$",
    re.IGNORECASE,
)
# e.g. sub-G11033-1_task-bandit_pre-stim_2026-10-30_10-04-13.csv
CSV_PATTERN = re.compile(
    rf"^sub-([A-Za-z0-9]+)-(\d+)_task-({_TOKENS})_(pre|post)-stim.*\.csv$",
    re.IGNORECASE,
)


def natural_key(text):
    """Sort key so that 'G2' < 'G10' and numeric IDs sort numerically."""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", text)]


def scan_files(folder, pattern):
    """Index matching files directly inside `folder` (no sub-folders).

    The subject ID comes from the file name. Returns
    {(subject_id, session, task, cond): [paths]}; a list with more than one
    path means duplicate files for that key.
    """
    found = {}
    for f in sorted(folder.iterdir()):
        if not f.is_file() or f.name.startswith("."):
            continue
        m = pattern.search(f.name)
        if not m:
            continue
        subject_id, session, token, cond = m.groups()
        key = (subject_id.upper(), int(session), _TOKEN_TO_TASK[token.lower()],
               cond.lower())
        found.setdefault(key, []).append(f)
    return found


def easy_time_range(path):
    """First and last Unix timestamp (last column) of a .easy file, in ms.

    Only the first and last lines are read, so this is fast on large files.
    """
    with open(path, "rb") as fh:
        first = fh.readline()
        fh.seek(0, os.SEEK_END)
        size = fh.tell()
        fh.seek(max(0, size - 65536))
        tail = [ln for ln in fh.read().splitlines() if ln.strip()]
    if not first.strip() or not tail:
        raise ValueError("empty file")
    t0 = float(first.split()[-1])
    t1 = float(tail[-1].split()[-1])
    return min(t0, t1), max(t0, t1)


def csv_time_range(path):
    """Earliest and latest value across every *unix_time* column of a CSV."""
    df = pd.read_csv(path)
    cols = [c for c in df.columns if "unix_time" in str(c).lower()]
    if not cols:
        raise KeyError("no *unix_time* columns")
    vals = df[cols].apply(pd.to_numeric, errors="coerce").to_numpy(float).ravel()
    vals = vals[np.isfinite(vals)]
    if vals.size == 0:
        raise ValueError("no valid unix times")
    return float(vals.min()), float(vals.max())


def _label(key):
    subject_id, session, task, cond = key
    return f"{task} {subject_id}-{session} {cond}-stim"


def pick_best_pair(key, eegs, csvs):
    """Choose the EEG/CSV pair whose Unix time ranges overlap the most.

    Returns (eeg_path, csv_path) or None when no pair can be chosen.
    """
    label = _label(key)
    print(f"WARNING: duplicate files for {label}; comparing Unix time ranges")

    def ranges(paths, reader):
        out = {}
        for path in paths:
            try:
                out[path] = reader(path)
                lo, hi = out[path]
                print(f"      {path.name}: {lo:.0f} to {hi:.0f} "
                      f"({(hi - lo) / 1000:.0f} s)")
            except Exception as exc:  # noqa: BLE001
                print(f"      {path.name}: could not read times ({exc})")
        return out

    eeg_ranges = ranges(eegs, easy_time_range)
    csv_ranges = ranges(csvs, csv_time_range)

    if not eeg_ranges or not csv_ranges:
        print(f"      -> cannot choose: need at least one readable EEG file and "
              f"one readable behavior CSV for {label}")
        return None

    pairs = []
    for e, (e0, e1) in eeg_ranges.items():
        for c, (c0, c1) in csv_ranges.items():
            overlap = max(0.0, min(e1, c1) - max(e0, c0))
            pairs.append((overlap, e, c))
    pairs.sort(key=lambda x: -x[0])

    best = pairs[0]
    if best[0] <= 0:
        print(f"      -> cannot choose: no EEG/CSV pair overlaps in time for {label}")
        return None
    if len(pairs) > 1 and abs(pairs[1][0] - best[0]) < 1e-6:
        print(f"      -> cannot choose: two pairs overlap equally for {label}")
        return None

    print(f"      -> using EEG {best[1].name} + CSV {best[2].name} "
          f"(overlap {best[0] / 1000:.0f} s)")
    return best[1], best[2]


def build_job_list():
    """Scan both folders; return (jobs, subjects_with_unresolved_duplicates)."""
    eeg_all = scan_files(Path(STIM_DIR), EEG_PATTERN)
    csv_all = scan_files(Path(BEHAVIOR_DIR), CSV_PATTERN)

    all_keys = set(eeg_all) | set(csv_all)
    chosen = {}                # key -> (eeg|None, csv|None)
    duplicate_subjects = set()  # subjects with a duplicate we could not resolve

    for key in sorted(all_keys, key=lambda k: (natural_key(k[0]), k[1], k[2], k[3])):
        eegs = eeg_all.get(key, [])
        csvs = csv_all.get(key, [])
        if len(eegs) <= 1 and len(csvs) <= 1:
            chosen[key] = (eegs[0] if eegs else None, csvs[0] if csvs else None)
            continue

        pair = pick_best_pair(key, eegs, csvs)
        if pair is None:
            duplicate_subjects.add(key[0])
        else:
            chosen[key] = pair

    subject_sessions = sorted(
        {(k[0], k[1]) for k in all_keys},
        key=lambda x: (natural_key(x[0]), x[1]),
    )

    jobs = []  # (subject_id, session, task, cond, eeg_file|None, csv_file|None)
    for subject_id, session in subject_sessions:
        for task in TASK_TOKEN:
            for cond in CONDITIONS:
                eeg_file, csv_file = chosen.get(
                    (subject_id, session, task, cond), (None, None)
                )
                jobs.append((subject_id, session, task, cond, eeg_file, csv_file))
    return jobs, duplicate_subjects


# =====================================================================
# EEG LOADING / PREPROCESSING
# =====================================================================


def load_easy(path):
    """Load EEG channels and Unix timestamps from a Neuroelectrics .easy file."""
    raw = np.loadtxt(path)

    if raw.ndim != 2 or raw.shape[1] < 6:
        raise ValueError(f"Unexpected .easy shape: {raw.shape}")

    # Layout: EEG channels + 3 accelerometer columns + trigger + Unix timestamp.
    n_eeg = raw.shape[1] - 5
    eeg_uv = raw[:, :n_eeg].astype(float) * NV_TO_UV
    unix_ms = raw[:, -1].astype(float)

    if n_eeg < max(REF_CHANNELS):
        raise ValueError(
            f"Expected at least {max(REF_CHANNELS)} EEG channels, found {n_eeg}."
        )

    return eeg_uv, unix_ms


def preprocess(eeg_uv, srate, ref_idx=None):
    """Bandpass, notch, and average-reference EEG data."""
    out = eeg_uv.copy()
    nyq = srate / 2.0

    b, a = signal.butter(4, [HIGHPASS / nyq, LOWPASS / nyq], btype="band")
    out = signal.filtfilt(b, a, out, axis=0)

    if 0 < NOTCH < nyq:
        bn, an = signal.iirnotch(NOTCH / nyq, Q=NOTCH_Q)
        out = signal.filtfilt(bn, an, out, axis=0)

    if ref_idx is None:
        ref_idx = list(range(out.shape[1]))

    out -= np.mean(out[:, ref_idx], axis=1, keepdims=True)
    return out


# =====================================================================
# EVENT ALIGNMENT / EPOCHING
# =====================================================================


def nearest_sample_index(unix_ms, event_ms):
    """Find the EEG sample nearest to an event Unix timestamp."""
    idx = int(np.searchsorted(unix_ms, event_ms))

    if idx <= 0:
        return 0
    if idx >= len(unix_ms):
        return len(unix_ms) - 1

    before = idx - 1
    if abs(unix_ms[before] - event_ms) <= abs(unix_ms[idx] - event_ms):
        return before
    return idx


def epoch_from_unix(
    eeg,
    unix_ms,
    srate,
    event_times_ms,
    tmin,
    tmax,
    reject_uv=EPOCH_REJECT_UV,
    reject_ch_idx=None,
):
    """Create event-locked epochs and reject epochs exceeding the uV threshold."""
    n_pre = int(round(abs(tmin) * srate))
    n_post = int(round(tmax * srate))
    n_epoch = n_pre + n_post
    times = np.arange(n_epoch) / srate + tmin

    epochs = []

    if reject_ch_idx is None:
        reject_ch_idx = list(range(eeg.shape[1]))

    for event_ms in event_times_ms:
        if not np.isfinite(event_ms):
            continue

        center = nearest_sample_index(unix_ms, event_ms)
        s0 = center - n_pre
        s1 = center + n_post

        if s0 < 0 or s1 > len(eeg):
            continue

        ep = eeg[s0:s1].copy()
        if ep.shape[0] != n_epoch:
            continue

        if reject_uv is not None:
            channel_max = np.max(np.abs(ep[:, reject_ch_idx]), axis=0)
            if np.any(channel_max > reject_uv):
                continue

        ep = signal.detrend(ep, axis=0, type="linear")
        epochs.append(ep)

    if epochs:
        epochs = np.stack(epochs)
    else:
        epochs = np.empty((0, n_epoch, eeg.shape[1]))

    return epochs, times


def get_event_times(events, column):
    """Validate an event column and convert it to a float NumPy array."""
    if column not in events.columns:
        raise KeyError(f"CSV is missing {column}")

    return pd.to_numeric(events[column], errors="coerce").to_numpy(float)


# =====================================================================
# THETA METHOD 1: SPECPARAM
# =====================================================================


def specparam_band_peak(
    freqs, psd, band=SPECPARAM_THETA_BAND, freq_range=SPECPARAM_FIT_RANGE
):
    """Return the strongest Specparam periodic peak inside the requested band."""
    if not SPECPARAM_AVAILABLE:
        return np.nan

    model = SpectralModel(
        peak_width_limits=[1.0, 8.0],
        max_n_peaks=6,
        min_peak_height=0.05,
        aperiodic_mode="fixed",
    )
    model.fit(freqs, psd, freq_range=list(freq_range))

    peaks = model.results.params.periodic.params
    best_cf = np.nan
    best_power = -np.inf

    if peaks.size > 0 and peaks.ndim == 2:
        for center_frequency, peak_power, _bandwidth in peaks:
            if band[0] <= center_frequency <= band[1] and peak_power > best_power:
                best_cf = center_frequency
                best_power = peak_power

    return float(best_cf) if np.isfinite(best_cf) else np.nan


def theta_specparam_analysis(feedback_epochs, feedback_times, srate, frontal_idx):
    """Estimate theta from a Specparam fit to the feedback-window PSD."""
    if not SPECPARAM_AVAILABLE:
        return np.nan

    win_mask = (
        (feedback_times >= SPECPARAM_FEEDBACK_ANALYSIS[0])
        & (feedback_times <= SPECPARAM_FEEDBACK_ANALYSIS[1])
    )
    frontal_window = feedback_epochs[:, win_mask][:, :, frontal_idx]

    if frontal_window.shape[1] == 0:
        return np.nan

    frontal_mean = np.mean(frontal_window, axis=2)

    nperseg = min(
        int(round(srate * SPECPARAM_WELCH_SECONDS)), frontal_mean.shape[1]
    )
    if nperseg < 2:
        return np.nan

    freqs, trial_psds = signal.welch(
        frontal_mean,
        fs=srate,
        nperseg=nperseg,
        noverlap=nperseg // 2,
        window="hann",
        axis=1,
    )
    avg_psd = np.mean(trial_psds, axis=0)

    return specparam_band_peak(freqs, avg_psd)


# =====================================================================
# THETA METHOD 2: TFR (also used for beta)
# =====================================================================


def morlet_tfr(epochs, srate, freqs, n_cycles=N_CYCLES, ch_idx=None):
    """Compute mean Morlet-wavelet power across epochs and selected channels."""
    if len(epochs) == 0:
        raise ValueError("Cannot compute TFR with zero epochs.")

    n_ep, n_times, n_ch = epochs.shape

    if ch_idx is None:
        ch_idx = list(range(n_ch))
    if len(ch_idx) == 0:
        raise ValueError("No usable frontal channels were selected.")

    power = np.zeros((len(freqs), n_times), dtype=float)

    for fi, f in enumerate(freqs):
        sigma_t = n_cycles / (2 * np.pi * f)
        hw = int(np.ceil(3.5 * sigma_t * srate))
        t_wav = np.arange(-hw, hw + 1) / srate

        wav = np.exp(2j * np.pi * f * t_wav) * np.exp(-(t_wav**2) / (2 * sigma_t**2))
        wav /= np.sqrt(np.sum(np.abs(wav) ** 2))

        for ci in ch_idx:
            for ei in range(n_ep):
                conv = signal.fftconvolve(epochs[ei, :, ci], wav, mode="same")
                power[fi] += np.abs(conv) ** 2

        power[fi] /= n_ep * len(ch_idx)

    return power


def baseline_correct_db(tfr, times, baseline_window):
    """Convert TFR power to dB relative to a baseline window."""
    baseline_mask = (times >= baseline_window[0]) & (times <= baseline_window[1])
    baseline_power = np.maximum(
        np.mean(tfr[:, baseline_mask], axis=1, keepdims=True), 1e-30
    )
    return 10 * np.log10(np.maximum(tfr, 1e-30) / baseline_power)


def find_peak(freqs, spectrum, mode="max", smooth_sigma=SMOOTH_SIGMA):
    """Find a smoothed spectral maximum or minimum and flag band-edge peaks."""
    if len(freqs) == 0:
        return np.nan, np.nan, False

    smoothed = gaussian_filter1d(spectrum, sigma=smooth_sigma)

    if mode == "max":
        idx = int(np.argmax(smoothed))
    elif mode == "min":
        idx = int(np.argmin(smoothed))
    else:
        raise ValueError("mode must be 'max' or 'min'")

    edge = idx == 0 or idx == len(freqs) - 1
    return float(freqs[idx]), float(smoothed[idx]), bool(edge)


def theta_tfr_analysis(feedback_epochs, feedback_times, srate, frontal_idx):
    """Estimate outcome-related theta as the maximum TFR power peak."""
    tfr = morlet_tfr(
        feedback_epochs, srate, THETA_FREQS, n_cycles=N_CYCLES, ch_idx=frontal_idx
    )
    tfr_db = baseline_correct_db(tfr, feedback_times, FEEDBACK_BASELINE)

    outcome_mask = (
        (feedback_times >= FEEDBACK_ANALYSIS[0])
        & (feedback_times <= FEEDBACK_ANALYSIS[1])
    )
    theta_spectrum = np.mean(tfr_db[:, outcome_mask], axis=1)

    return find_peak(THETA_FREQS, theta_spectrum, mode="max")


# =====================================================================
# THETA METHOD 3: IAF - 5
# =====================================================================


def iaf_minus_5_analysis(eeg_clean, srate, posterior_idx):
    """Estimate theta as IAF - 5 Hz (posterior alpha), clipped to 4-8 Hz."""
    if len(eeg_clean) < 2:
        return np.nan

    nperseg = min(int(round(2 * srate)), len(eeg_clean))
    noverlap = min(int(round(srate)), max(0, nperseg - 1))

    freqs, psd = signal.welch(
        eeg_clean[:, posterior_idx],
        fs=srate,
        nperseg=nperseg,
        noverlap=noverlap,
        axis=0,
    )
    posterior_psd = np.mean(psd, axis=1)

    iaf_specparam = specparam_band_peak(freqs, posterior_psd, band=ALPHA_SEARCH_BAND)

    alpha_mask = (freqs >= ALPHA_SEARCH_BAND[0]) & (freqs <= ALPHA_SEARCH_BAND[1])
    alpha_freqs = freqs[alpha_mask]
    alpha_db = 10 * np.log10(np.maximum(posterior_psd[alpha_mask], 1e-30))

    iaf_power = np.nan
    if len(alpha_freqs) > 0:
        iaf_power, _power, _edge = find_peak(alpha_freqs, alpha_db, mode="max")

    if (
        np.isfinite(iaf_specparam)
        and ALPHA_SEARCH_BAND[0] <= iaf_specparam <= ALPHA_SEARCH_BAND[1]
    ):
        iaf = iaf_specparam
    elif (
        np.isfinite(iaf_power)
        and ALPHA_SEARCH_BAND[0] <= iaf_power <= ALPHA_SEARCH_BAND[1]
    ):
        iaf = iaf_power
    else:
        return np.nan

    return float(np.clip(iaf - 5.0, THETA_SEARCH_BAND[0], THETA_SEARCH_BAND[1]))


# =====================================================================
# BETA: TFR ERD (shared by Bandit and SST)
# =====================================================================


def beta_analysis(
    epochs,
    times,
    srate,
    frontal_idx,
    baseline=DECISION_BASELINE,
    analysis=DECISION_ANALYSIS,
):
    """Estimate the beta ERD peak frequency (most negative dB in 13-30 Hz).

    Defaults reproduce the Bandit decision-epoch analysis; the SST passes its
    own baseline and analysis windows.
    """
    tfr = morlet_tfr(
        epochs, srate, DECISION_FREQS, n_cycles=N_CYCLES, ch_idx=frontal_idx
    )
    tfr_db = baseline_correct_db(tfr, times, baseline)

    analysis_mask = (times >= analysis[0]) & (times <= analysis[1])
    beta_spectrum = np.mean(tfr_db[:, analysis_mask], axis=1)

    # Strongest ERD = most negative dB.
    return find_peak(DECISION_FREQS, beta_spectrum, mode="min")


# =====================================================================
# PER-RECORDING ANALYSIS
# =====================================================================


def attempt(label, func):
    """Run one measurement; on failure warn and return NaN."""
    try:
        return func()
    except Exception as exc:  # noqa: BLE001
        print(f"    WARNING: {label} failed: {exc}")
        return np.nan


def analyze_bandit_recording(eeg_file, behavior_file):
    """Run all four Bandit measurements for one EEG/behavior pair."""
    results = {m: np.nan for m in BANDIT_MEASURES}

    frontal_idx = [ch - 1 for ch in FRONTAL_CHANNELS]
    posterior_idx = [ch - 1 for ch in POSTERIOR_ALPHA_CHANNELS]
    ref_idx = [ch - 1 for ch in REF_CHANNELS]

    eeg_uv, unix_ms = load_easy(eeg_file)
    eeg_clean = preprocess(eeg_uv, SRATE, ref_idx=ref_idx)
    events = pd.read_csv(behavior_file)

    feedback_ms = get_event_times(events, FEEDBACK_EVENT_COL)
    ep_fb, t_fb = epoch_from_unix(
        eeg_clean, unix_ms, SRATE, feedback_ms,
        FEEDBACK_EPOCH[0], FEEDBACK_EPOCH[1], reject_ch_idx=ref_idx,
    )

    decision_ms = get_event_times(events, DECISION_EVENT_COL)
    ep_dec, t_dec = epoch_from_unix(
        eeg_clean, unix_ms, SRATE, decision_ms,
        DECISION_EPOCH[0], DECISION_EPOCH[1], reject_ch_idx=ref_idx,
    )

    print(f"    feedback epochs retained: {len(ep_fb)} | "
          f"decision epochs retained: {len(ep_dec)}")

    if len(ep_fb) > 0:
        results["theta_specparam"] = attempt(
            "theta Specparam",
            lambda: theta_specparam_analysis(ep_fb, t_fb, SRATE, frontal_idx),
        )
        results["theta_tfr"] = attempt(
            "theta TFR",
            lambda: theta_tfr_analysis(ep_fb, t_fb, SRATE, frontal_idx)[0],
        )

    results["theta_iaf5"] = attempt(
        "theta IAF-5",
        lambda: iaf_minus_5_analysis(eeg_clean, SRATE, posterior_idx),
    )

    if len(ep_dec) > 0:
        results["beta_tfr"] = attempt(
            "beta TFR",
            lambda: beta_analysis(ep_dec, t_dec, SRATE, frontal_idx)[0],
        )

    return results


def analyze_sst_recording(eeg_file, behavior_file):
    """Run the SST beta measurement for one EEG/behavior pair."""
    results = {m: np.nan for m in SST_MEASURES}

    frontal_idx = [ch - 1 for ch in FRONTAL_CHANNELS]
    ref_idx = [ch - 1 for ch in REF_CHANNELS]

    eeg_uv, unix_ms = load_easy(eeg_file)
    eeg_clean = preprocess(eeg_uv, SRATE, ref_idx=ref_idx)
    events = pd.read_csv(behavior_file)

    # All trials with a valid stim_onset_unix_time are used.
    stim_ms = get_event_times(events, SST_EVENT_COL)
    ep_sst, t_sst = epoch_from_unix(
        eeg_clean, unix_ms, SRATE, stim_ms,
        SST_EPOCH[0], SST_EPOCH[1], reject_ch_idx=ref_idx,
    )

    print(f"    stim-onset epochs retained: {len(ep_sst)}")

    if len(ep_sst) > 0:
        results["beta_tfr"] = attempt(
            "SST beta TFR",
            lambda: beta_analysis(
                ep_sst, t_sst, SRATE, frontal_idx,
                baseline=SST_BASELINE, analysis=SST_ANALYSIS,
            )[0],
        )

    return results


ANALYZERS = {"bandit": analyze_bandit_recording, "sst": analyze_sst_recording}


# =====================================================================
# MAIN
# =====================================================================


def main():
    for label, folder in (("STIM_DIR", STIM_DIR), ("BEHAVIOR_DIR", BEHAVIOR_DIR)):
        if not Path(folder).is_dir():
            print(f"ERROR: {label} not found: {folder}\n"
                  f"Edit the paths at the top of this file.", file=sys.stderr)
            sys.exit(1)

    output_csv = Path(OUTPUT_DIR) / OUTPUT_NAME

    print(f"Stimulation (EEG) folder: {STIM_DIR}")
    print(f"Behavioral folder:        {BEHAVIOR_DIR}")
    print(f"Output folder:            {OUTPUT_DIR}")
    if not SPECPARAM_AVAILABLE:
        print("WARNING: specparam is not installed; Specparam theta will be blank "
              "and IAF-5 will use the power-spectrum fallback.")

    # Scan both folders. Duplicates are resolved by Unix time overlap where
    # possible; subjects that cannot be resolved are flagged, not fatal.
    jobs, duplicate_subjects = build_job_list()
    if duplicate_subjects:
        print("\nSubjects with unresolved duplicate files (marked in the output): "
              + ", ".join(sorted(duplicate_subjects, key=natural_key)))

    if not jobs:
        print("No participant sessions were found.")
        sys.exit(0)

    rows = {}  # (int subject, int session) -> {column: value}

    for subject_id, session, task, cond, eeg_file, csv_file in jobs:
        key = (subject_id, session)
        row = rows.setdefault(key, {})
        for m in TASK_MEASURES[task]:
            row.setdefault(column_name(task, cond, m), np.nan)

        if subject_id in duplicate_subjects:
            continue  # cells are filled with DUPLICATE_MESSAGE below

        label = f"{subject_id}-ses{session} [{task} {cond}-stim]"

        # A task with no files at all for this session simply wasn't run.
        if eeg_file is None and csv_file is None:
            continue

        print(f"\n{label}")

        if eeg_file is None or csv_file is None:
            missing = []
            if eeg_file is None:
                missing.append("EEG .easy")
            if csv_file is None:
                missing.append("behavior CSV")
            print(f"    SKIPPED: missing {' and '.join(missing)}")
            continue

        try:
            results = ANALYZERS[task](eeg_file, csv_file)
        except Exception as exc:  # noqa: BLE001
            print(f"    ERROR: analysis failed: {exc}")
            traceback.print_exc()
            continue

        for m, value in results.items():
            row[column_name(task, cond, m)] = value

    # Bandit columns first (by measure, pre then post), then SST columns.
    columns = [
        column_name(task, cond, m)
        for task in ("bandit", "sst")
        for m in TASK_MEASURES[task]
        for cond in CONDITIONS
    ]

    def cell(subject, session, column):
        if subject in duplicate_subjects:
            return DUPLICATE_MESSAGE
        value = rows[(subject, session)].get(column, np.nan)
        if isinstance(value, (float, np.floating)):
            value = round(float(value), 2)
        return value

    index = []
    data = []
    for (subject, session) in sorted(rows, key=lambda k: (natural_key(k[0]), k[1])):
        index.append(f"{subject}-ses{session}")
        data.append([cell(subject, session, c) for c in columns])

    df = pd.DataFrame(data, index=index, columns=columns)
    df.index.name = "participant_session"

    Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)
    df.to_csv(output_csv)

    print(f"\nSaved: {output_csv}")


if __name__ == "__main__":
    main()
