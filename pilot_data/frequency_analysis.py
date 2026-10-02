#!/usr/bin/env python3
"""Batch individualized theta / beta frequency estimation.

Place this script in the base folder that contains the participant folders
(e.g. ...\\10001, ...\\10002, ...). Every folder whose name contains a subject
ID is processed. Inside each folder the script expects, for each session n:

    *<ID>-<n>_Bandit_pre-stim.easy
    *<ID>-<n>_Bandit_post-stim.easy
    sub-<ID>-<n>_task-bandit_pre-stim*.csv
    sub-<ID>-<n>_task-bandit_post-stim*.csv

Sessions are discovered automatically from the filenames, so any number of
sessions is supported. Pre and post are analyzed independently with exactly the
same methods as the single-subject script:

    theta: Specparam, Morlet TFR, IAF-5  (feedback epochs / posterior alpha)
    beta : Morlet TFR ERD                (choice epochs)

Output: batch_theta_beta_results.csv in the base folder, one row per
subject-session (e.g. 10001-ses1) and one column per measurement
(e.g. bandit_pre_theta_specparam).

Behavior on problems:
  * Missing file(s) or failed analysis -> values left blank, script continues.
  * Duplicate matching files           -> script stops with an error
                                          (checked for all participants before
                                          any analysis starts).
"""

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

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_CSV = BASE_DIR / "batch_theta_beta_results.csv"

CONDITIONS = ("pre", "post")

HIGHPASS = 0.5
LOWPASS = 45.0
NOTCH = 60.0
NOTCH_Q = 30.0
EPOCH_REJECT_UV = 200.0
NV_TO_UV = 1e-3
SRATE = 500.0

SPECPARAM_THETA_BAND = (4.0, 8.0)
SPECPARAM_FIT_RANGE = (2.0, 40.0)
SPECPARAM_FEEDBACK_ANALYSIS = (0.1, 1.5)
SPECPARAM_WELCH_SECONDS = 0.5

THETA_SEARCH_BAND = (4.0, 8.0)
ALPHA_SEARCH_BAND = (8.0, 13.0)
BETA_SEARCH_BAND = (13.0, 30.0)

FEEDBACK_EPOCH = (-1.5, 2.0)
FEEDBACK_BASELINE = (-0.8, -0.1)
FEEDBACK_ANALYSIS = (0.1, 1.5)

DECISION_EPOCH = (-1.5, 0.5)
DECISION_BASELINE = (-1.5, -1.0)
DECISION_ANALYSIS = (-1.0, -0.1)

THETA_FREQS = np.arange(THETA_SEARCH_BAND[0], THETA_SEARCH_BAND[1] + 0.25, 0.25)
DECISION_FREQS = np.arange(BETA_SEARCH_BAND[0], BETA_SEARCH_BAND[1] + 0.5, 0.5)

N_CYCLES = 5
SMOOTH_SIGMA = 1.0

FEEDBACK_EVENT_COL = "feedback_onset_unix_time"
DECISION_EVENT_COL = "choice_onset_unix_time"

# Original 1-based channel numbers.
FRONTAL_CHANNELS = (1, 3, 5)         # F3, FCz, F4
POSTERIOR_ALPHA_CHANNELS = (6, 7)    # P4, P3
REF_CHANNELS = (1, 2, 3, 4, 5, 6, 7)  # all scalp channels; excludes EXT

MEASURES = ("theta_specparam", "theta_tfr", "theta_iaf5", "beta_tfr")


class DuplicateFileError(Exception):
    """Raised when more than one file matches an expected pattern."""


# =====================================================================
# FILE DISCOVERY
# =====================================================================


def subject_id_from_folder(name):
    """Return the subject ID in a folder name (longest run of digits), or None."""
    runs = re.findall(r"\d+", name)
    if not runs:
        return None
    return max(runs, key=len)


def eeg_regex(subject_id, session, cond):
    return re.compile(
        rf"(?<!\d){subject_id}-{session}_Bandit_{cond}-stim\.easy$", re.IGNORECASE
    )


def csv_regex(subject_id, session, cond):
    return re.compile(
        rf"^sub-{subject_id}-{session}_task-bandit_{cond}-stim.*\.csv$", re.IGNORECASE
    )


def discover_sessions(folder, subject_id):
    """Find all session numbers present in a participant folder."""
    eeg_pat = re.compile(
        rf"(?<!\d){subject_id}-(\d+)_Bandit_(?:pre|post)-stim\.easy$", re.IGNORECASE
    )
    csv_pat = re.compile(
        rf"^sub-{subject_id}-(\d+)_task-bandit_(?:pre|post)-stim.*\.csv$",
        re.IGNORECASE,
    )
    sessions = set()
    for f in folder.iterdir():
        if not f.is_file():
            continue
        for pat in (eeg_pat, csv_pat):
            m = pat.search(f.name)
            if m:
                sessions.add(int(m.group(1)))
    return sorted(sessions)


def find_unique(folder, regex, description):
    """Return the single matching file, None if none, raise if duplicates."""
    matches = sorted(
        f for f in folder.iterdir() if f.is_file() and regex.search(f.name)
    )
    if len(matches) > 1:
        names = "\n  ".join(m.name for m in matches)
        raise DuplicateFileError(
            f"Multiple files match {description} in {folder}:\n  {names}"
        )
    return matches[0] if matches else None


def build_job_list():
    """Scan every participant folder. Raises on duplicates before any analysis."""
    jobs = []  # (subject_id, session, cond, eeg_file|None, csv_file|None)

    folders = sorted(
        (p for p in BASE_DIR.iterdir() if p.is_dir()),
        key=lambda p: p.name,
    )
    for folder in folders:
        subject_id = subject_id_from_folder(folder.name)
        if subject_id is None:
            continue

        for session in discover_sessions(folder, subject_id):
            for cond in CONDITIONS:
                eeg_file = find_unique(
                    folder,
                    eeg_regex(subject_id, session, cond),
                    f"EEG {subject_id}-{session} {cond}-stim",
                )
                csv_file = find_unique(
                    folder,
                    csv_regex(subject_id, session, cond),
                    f"behavior CSV {subject_id}-{session} {cond}-stim",
                )
                jobs.append((subject_id, session, cond, eeg_file, csv_file))

    return jobs


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
# BETA: TFR ERD
# =====================================================================


def beta_analysis(decision_epochs, decision_times, srate, frontal_idx):
    """Estimate the decision-related beta ERD peak frequency."""
    tfr = morlet_tfr(
        decision_epochs, srate, DECISION_FREQS, n_cycles=N_CYCLES, ch_idx=frontal_idx
    )
    tfr_db = baseline_correct_db(tfr, decision_times, DECISION_BASELINE)

    decision_mask = (
        (decision_times >= DECISION_ANALYSIS[0])
        & (decision_times <= DECISION_ANALYSIS[1])
    )
    beta_spectrum = np.mean(tfr_db[:, decision_mask], axis=1)

    # Strongest ERD = most negative dB.
    return find_peak(DECISION_FREQS, beta_spectrum, mode="min")


# =====================================================================
# PER-RECORDING ANALYSIS
# =====================================================================


def analyze_recording(eeg_file, behavior_file):
    """Run all four measurements for one EEG/behavior pair."""
    results = {m: np.nan for m in MEASURES}

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

    # Each measurement is isolated so one failure doesn't blank the others.
    def attempt(label, func):
        try:
            return func()
        except Exception as exc:  # noqa: BLE001
            print(f"    WARNING: {label} failed: {exc}")
            return np.nan

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


# =====================================================================
# MAIN
# =====================================================================


def main():
    print(f"Base folder: {BASE_DIR}")
    if not SPECPARAM_AVAILABLE:
        print("WARNING: specparam is not installed; Specparam theta will be blank "
              "and IAF-5 will use the power-spectrum fallback.")

    # Pre-flight scan: raises DuplicateFileError before any analysis starts.
    try:
        jobs = build_job_list()
    except DuplicateFileError as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    if not jobs:
        print("No participant sessions were found.")
        sys.exit(0)

    rows = {}  # (int subject, int session) -> {column: value}

    for subject_id, session, cond, eeg_file, csv_file in jobs:
        key = (int(subject_id), session)
        row = rows.setdefault(key, {})
        for m in MEASURES:
            row.setdefault(f"bandit_{cond}_{m}", np.nan)

        label = f"{subject_id}-ses{session} [{cond}-stim]"
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
            results = analyze_recording(eeg_file, csv_file)
        except Exception as exc:  # noqa: BLE001
            print(f"    ERROR: analysis failed: {exc}")
            traceback.print_exc()
            continue

        for m, value in results.items():
            row[f"bandit_{cond}_{m}"] = value

    # Columns ordered by measure, pre then post (matches requested layout).
    columns = [f"bandit_{cond}_{m}" for m in MEASURES for cond in CONDITIONS]

    index = []
    data = []
    for (subject, session) in sorted(rows):
        index.append(f"{subject}-ses{session}")
        data.append([rows[(subject, session)].get(c, np.nan) for c in columns])

    df = pd.DataFrame(data, index=index, columns=columns)
    df.index.name = "participant_session"
    df.round(2).to_csv(OUTPUT_CSV)

    print(f"\nSaved: {OUTPUT_CSV}")


if __name__ == "__main__":
    main()