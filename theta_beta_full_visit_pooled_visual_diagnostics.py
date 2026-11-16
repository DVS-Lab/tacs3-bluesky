#!/usr/bin/env python3
"""Full-visit theta / beta / IAF estimation (batch version, no GUI).

For every subject and session (1-3) found in the behavior-CSV folder, the
script analyzes four recordings:

    Bandit pre-stim, Bandit post-stim, SST pre-stim, SST post-stim

and writes ONE wide CSV with:
    subject_id, session,
    one block of columns per recording (bandit_pre_, bandit_post_,
    sst_pre_, sst_post_),
    one block for the pooled visit (all_),
    notes.

What each recording produces
    Bandit: outcome theta (Specparam, TFR), IAF-5, decision beta ERD
    SST:    IAF / IAF-5 only (continuous posterior alpha)

Pooled ("all_") values
    Theta / beta: retained epochs from Bandit pre + post are concatenated and
                  the estimators are run once on the pooled epochs.
    IAF:          posterior PSDs from all available recordings are averaged,
                  weighted by recording length (signals are never glued).

Discovery
    Subjects and sessions are read from filenames matching
    sub-[ID]-[session]_task-[task]_[pre|post]-stim_[time].csv
    in BEHAVIOR_DATA_DIR. Only sessions 1-3 are processed.

Usage
    python theta_beta_full_visit.py
    python theta_beta_full_visit.py --subjects G11033 G11034
    python theta_beta_full_visit.py --subjects G11033 --sessions 3
"""

import argparse
import re
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
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

STIM_DATA_DIR = Path(
    r"C:\Users\Public\LAB PROJECTS\smith-lab\tacs3-bluesky"
    r"\stimulation\stimulation-data"
)
BEHAVIOR_DATA_DIR = Path(
    r"C:\Users\Public\LAB PROJECTS\smith-lab\tacs3-bluesky"
    r"\stimulation\pre-stimulation-participant-responses"
)
OUTPUT_DIR = Path(
    r"C:\Users\Public\LAB PROJECTS\smith-lab\tacs3-bluesky"
    r"\stimulation\calculated-theta-beta"
)

SESSIONS = (1, 2, 3)
PHASES = ("pre", "post")

HIGHPASS = 0.5
LOWPASS = 45.0
NOTCH = 60.0
NOTCH_Q = 30.0
EPOCH_REJECT_UV = 200.0
NV_TO_UV = 1e-3
SRATE = 500.0

# Minimum retained epochs before a theta / beta peak is reported.
MIN_EPOCHS = 20

SPECPARAM_THETA_BAND = (4.0, 8.0)
SPECPARAM_FIT_RANGE = (2.0, 40.0)
SPECPARAM_FEEDBACK_ANALYSIS = (0.1, 1.5)
SPECPARAM_WELCH_SECONDS = 1.4  # Diagnostic: use the full 0.1-1.5 s feedback analysis window

THETA_SEARCH_BAND = (4.0, 8.0)  # Target theta band; do not change for diagnostic search
THETA_DIAGNOSTIC_BAND = (2.0, 12.0)  # Wider TFR search to reveal peaks outside target band
ALPHA_SEARCH_BAND = (8.0, 13.0)
BETA_SEARCH_BAND = (13.0, 30.0)

FEEDBACK_EPOCH = (-1.5, 2.0)
FEEDBACK_BASELINE = (-0.8, -0.1)
FEEDBACK_ANALYSIS = (0.1, 1.5)

DECISION_EPOCH = (-1.5, 0.5)
DECISION_BASELINE = (-1.5, -1.0)
DECISION_ANALYSIS = (-1.0, -0.1)

THETA_FREQS = np.arange(THETA_SEARCH_BAND[0], THETA_SEARCH_BAND[1] + 0.25, 0.25)
THETA_DIAGNOSTIC_FREQS = np.arange(THETA_DIAGNOSTIC_BAND[0], THETA_DIAGNOSTIC_BAND[1] + 0.25, 0.25)
DECISION_FREQS = np.arange(BETA_SEARCH_BAND[0], BETA_SEARCH_BAND[1] + 0.5, 0.5)

N_CYCLES = 5
SMOOTH_SIGMA = 1.0

FEEDBACK_EVENT_COL = "feedback_onset_unix_time"
DECISION_EVENT_COL = "choice_onset_unix_time"

FRONTAL_CHANNELS = (1, 3, 5)         # F3, FCz, F4
POSTERIOR_ALPHA_CHANNELS = (6, 7)    # P4, P3
REF_CHANNELS = (1, 2, 3, 4, 5, 6, 7)

CHANNEL_LABELS = {1: "F3", 2: "Fp1", 3: "FCz", 4: "FT7",
                  5: "F4", 6: "P4", 7: "P3", 8: "EXT"}

FRONTAL_IDX = [c - 1 for c in FRONTAL_CHANNELS]
POSTERIOR_IDX = [c - 1 for c in POSTERIOR_ALPHA_CHANNELS]
REF_IDX = [c - 1 for c in REF_CHANNELS]

# sub-G11033-3_task-bandit_post-stim_2026-11-13_11-07-59.csv
BEHAVIOR_RE = re.compile(
    r"^sub-(?P<sub>[A-Za-z0-9]+)-(?P<ses>\d+)_task-(?P<task>[A-Za-z0-9]+)"
    r"_(?P<phase>pre|post)-stim_.+\.csv$",
    re.IGNORECASE,
)

# Recording blocks, in CSV column order: (task, phase, column prefix, file label)
RECORDINGS = [
    ("bandit", "pre", "bandit_pre_", "Bandit"),
    ("bandit", "post", "bandit_post_", "Bandit"),
    ("sst", "pre", "sst_pre_", "SST"),
    ("sst", "post", "sst_post_", "SST"),
]


# =====================================================================
# DISCOVERY
# =====================================================================


def natural_key(text):
    return [int(p) if p.isdigit() else p.lower()
            for p in re.split(r"(\d+)", text)]


def scan_behavior_folder(folder):
    """Index behavior CSVs by (subject, session, task, phase).

    Returns (index, subjects) where subjects maps subject -> sorted sessions.
    """
    index = {}
    subjects = {}

    for path in folder.glob("sub-*.csv"):
        m = BEHAVIOR_RE.match(path.name)
        if not m:
            continue
        ses = int(m["ses"])
        if ses not in SESSIONS:
            continue
        sub = m["sub"]
        key = (sub, ses, m["task"].lower(), m["phase"].lower())
        index.setdefault(key, []).append(path)
        subjects.setdefault(sub, set()).add(ses)

    subjects = {s: sorted(v) for s, v in subjects.items()}
    return index, subjects


def pick_latest(paths):
    """Latest file by name (filenames start with / end in a timestamp)."""
    return sorted(paths, key=lambda p: p.name)[-1]


def find_eeg_file(subject, session, task_label, phase, notes, tag):
    pattern = f"*_{subject}-{session}_{task_label}_{phase}-stim*.easy"
    matches = list(STIM_DATA_DIR.glob(pattern))
    if not matches:
        notes.append(f"{tag}: no EEG file ({pattern})")
        return None
    if len(matches) > 1:
        chosen = pick_latest(matches)
        notes.append(f"{tag}: {len(matches)} EEG files matched, used {chosen.name}")
        return chosen
    return matches[0]


# =====================================================================
# EEG LOADING / PREPROCESSING
# =====================================================================


def load_easy(path):
    """Load EEG (uV) and Unix timestamps (ms) from a Neuroelectrics .easy file."""
    try:
        raw = pd.read_csv(path, sep=r"\s+", header=None, dtype=float).to_numpy()
    except Exception:
        raw = np.loadtxt(path)

    if raw.ndim != 2 or raw.shape[1] < 6:
        raise ValueError(f"Unexpected .easy shape: {raw.shape}")

    n_eeg = raw.shape[1] - 5
    if n_eeg < max(REF_CHANNELS):
        raise ValueError(
            f"Expected at least {max(REF_CHANNELS)} EEG channels, found {n_eeg}."
        )

    eeg_uv = raw[:, :n_eeg].astype(float) * NV_TO_UV
    unix_ms = raw[:, -1].astype(float)
    return eeg_uv, unix_ms


def preprocess(eeg_uv, srate, ref_idx):
    out = eeg_uv.copy()
    nyq = srate / 2.0

    b, a = signal.butter(4, [HIGHPASS / nyq, LOWPASS / nyq], btype="band")
    out = signal.filtfilt(b, a, out, axis=0)

    if 0 < NOTCH < nyq:
        bn, an = signal.iirnotch(NOTCH / nyq, Q=NOTCH_Q)
        out = signal.filtfilt(bn, an, out, axis=0)

    out -= np.mean(out[:, ref_idx], axis=1, keepdims=True)
    return out


def timing_qc(unix_ms):
    """Estimated sampling rate and largest timestamp gap."""
    if len(unix_ms) < 2:
        return np.nan, np.nan
    d = np.diff(unix_ms)
    srate_est = 1000.0 / np.median(d)
    return float(srate_est), float(np.max(d) / 1000.0)


# =====================================================================
# EPOCHING
# =====================================================================


def nearest_sample_index(unix_ms, event_ms):
    idx = int(np.searchsorted(unix_ms, event_ms))
    if idx <= 0:
        return 0
    if idx >= len(unix_ms):
        return len(unix_ms) - 1
    before = idx - 1
    if abs(unix_ms[before] - event_ms) <= abs(unix_ms[idx] - event_ms):
        return before
    return idx


def epoch_from_unix(eeg, unix_ms, srate, event_times_ms, tmin, tmax,
                    reject_uv=EPOCH_REJECT_UV, reject_ch_idx=None):
    n_pre = int(round(abs(tmin) * srate))
    n_post = int(round(tmax * srate))
    n_epoch = n_pre + n_post
    times = np.arange(n_epoch) / srate + tmin

    epochs = []
    rejected_artifact = 0
    rejected_bounds = 0
    skipped_missing = 0
    artifact_by_channel = {}

    if reject_ch_idx is None:
        reject_ch_idx = list(range(eeg.shape[1]))

    for event_ms in event_times_ms:
        if not np.isfinite(event_ms):
            skipped_missing += 1
            continue

        center = nearest_sample_index(unix_ms, event_ms)
        s0 = center - n_pre
        s1 = center + n_post

        if s0 < 0 or s1 > len(eeg):
            rejected_bounds += 1
            continue

        ep = eeg[s0:s1].copy()
        if ep.shape[0] != n_epoch:
            rejected_bounds += 1
            continue

        if reject_uv is not None:
            channel_max = np.max(np.abs(ep[:, reject_ch_idx]), axis=0)
            bad_mask = channel_max > reject_uv
            if np.any(bad_mask):
                rejected_artifact += 1
                for pos in np.where(bad_mask)[0]:
                    ch = reject_ch_idx[pos]
                    artifact_by_channel[ch] = artifact_by_channel.get(ch, 0) + 1
                continue

        ep = signal.detrend(ep, axis=0, type="linear")
        epochs.append(ep)

    if epochs:
        epochs = np.stack(epochs)
    else:
        epochs = np.empty((0, n_epoch, eeg.shape[1]))

    info = {
        "missing_timestamp": skipped_missing,
        "out_of_bounds": rejected_bounds,
        "artifact": rejected_artifact,
        "artifact_by_channel": artifact_by_channel,
    }
    return epochs, times, info


def get_event_times(events, column):
    if column not in events.columns:
        raise KeyError(f"CSV is missing {column}")
    return pd.to_numeric(events[column], errors="coerce").to_numpy(float)


def artifact_channel_string(info):
    parts = []
    for idx, count in sorted(info["artifact_by_channel"].items()):
        name = CHANNEL_LABELS.get(int(idx) + 1, f"Ch{int(idx) + 1}")
        parts.append(f"{name}={count}")
    return ";".join(parts)


# =====================================================================
# SPECTRAL ESTIMATORS
# =====================================================================


def specparam_band_peak(freqs, psd, band=SPECPARAM_THETA_BAND,
                        freq_range=SPECPARAM_FIT_RANGE):
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
        for cf, pw, _bw in peaks:
            if band[0] <= cf <= band[1] and pw > best_power:
                best_cf = cf
                best_power = pw

    return float(best_cf) if np.isfinite(best_cf) else np.nan


def theta_specparam_diagnostics(epochs, times, srate, frontal_idx):
    """Return Specparam theta plus fit diagnostics for the feedback epochs."""
    result = {
        "theta_specparam_hz": np.nan,
        "theta_specparam_status": "not_run",
        "theta_specparam_n_peaks": 0,
        "theta_specparam_peaks": "",
        "theta_specparam_r_squared": np.nan,
        "theta_specparam_error": np.nan,
        "theta_specparam_resolution_hz": np.nan,
        "theta_specparam_segment_s": np.nan,
    }
    if not SPECPARAM_AVAILABLE:
        result["theta_specparam_status"] = "specparam_not_installed"
        return result

    win = ((times >= SPECPARAM_FEEDBACK_ANALYSIS[0])
           & (times <= SPECPARAM_FEEDBACK_ANALYSIS[1]))
    frontal_window = epochs[:, win][:, :, frontal_idx]
    if frontal_window.shape[1] < 2:
        result["theta_specparam_status"] = "insufficient_window_samples"
        return result

    frontal_mean = np.mean(frontal_window, axis=2)
    nperseg = min(int(round(srate * SPECPARAM_WELCH_SECONDS)),
                  frontal_mean.shape[1])
    if nperseg < 2:
        result["theta_specparam_status"] = "insufficient_welch_samples"
        return result

    result["theta_specparam_segment_s"] = nperseg / srate
    result["theta_specparam_resolution_hz"] = srate / nperseg
    freqs, trial_psds = signal.welch(
        frontal_mean, fs=srate, nperseg=nperseg, noverlap=nperseg // 2,
        window="hann", axis=1,
    )
    psd = np.mean(trial_psds, axis=0)
    try:
        model = SpectralModel(
            peak_width_limits=[1.0, 8.0], max_n_peaks=6,
            min_peak_height=0.05, aperiodic_mode="fixed",
        )
        model.fit(freqs, psd, freq_range=list(SPECPARAM_FIT_RANGE))
        peaks = model.results.params.periodic.params
        if peaks.size > 0 and peaks.ndim == 2:
            result["theta_specparam_n_peaks"] = int(len(peaks))
            result["theta_specparam_peaks"] = ";".join(
                f"{cf:.3f}Hz|power={pw:.3f}|bw={bw:.3f}"
                for cf, pw, bw in peaks
            )
            candidates = [(float(cf), float(pw)) for cf, pw, _bw in peaks
                          if THETA_SEARCH_BAND[0] <= cf <= THETA_SEARCH_BAND[1]]
            if candidates:
                result["theta_specparam_hz"] = max(candidates, key=lambda x: x[1])[0]
                result["theta_specparam_status"] = "theta_peak_found"
            else:
                result["theta_specparam_status"] = "fit_ok_no_peak_in_4_8hz"
        else:
            result["theta_specparam_status"] = "fit_ok_no_periodic_peaks"

        metrics = getattr(model.results, "metrics", None)
        if metrics is not None:
            result["theta_specparam_r_squared"] = getattr(metrics, "r_squared", np.nan)
            result["theta_specparam_error"] = getattr(metrics, "error", np.nan)
    except Exception as exc:
        result["theta_specparam_status"] = f"fit_error:{type(exc).__name__}:{exc}"
    return result


def morlet_tfr(epochs, srate, freqs, n_cycles=N_CYCLES, ch_idx=None):
    """Mean Morlet power across epochs and selected channels (vectorized)."""
    if len(epochs) == 0:
        raise ValueError("Cannot compute TFR with zero epochs.")

    n_ep, n_times, n_ch = epochs.shape
    if ch_idx is None:
        ch_idx = list(range(n_ch))
    if len(ch_idx) == 0:
        raise ValueError("No usable frontal channels were selected.")

    x = epochs[:, :, ch_idx]
    power = np.zeros((len(freqs), n_times), dtype=float)

    for fi, f in enumerate(freqs):
        sigma_t = n_cycles / (2 * np.pi * f)
        hw = int(np.ceil(3.5 * sigma_t * srate))
        t_wav = np.arange(-hw, hw + 1) / srate

        wav = np.exp(2j * np.pi * f * t_wav) * np.exp(-(t_wav**2) / (2 * sigma_t**2))
        wav /= np.sqrt(np.sum(np.abs(wav) ** 2))

        conv = signal.fftconvolve(x, wav[None, :, None], mode="same", axes=1)
        power[fi] = np.mean(np.abs(conv) ** 2, axis=(0, 2))

    return power


def baseline_correct_db(tfr, times, baseline_window):
    mask = (times >= baseline_window[0]) & (times <= baseline_window[1])
    base = np.maximum(np.mean(tfr[:, mask], axis=1, keepdims=True), 1e-30)
    return 10 * np.log10(np.maximum(tfr, 1e-30) / base)


def find_peak(freqs, spectrum, mode="max", smooth_sigma=SMOOTH_SIGMA):
    if len(freqs) == 0:
        return np.nan, np.nan, False

    smoothed = gaussian_filter1d(spectrum, sigma=smooth_sigma)
    idx = int(np.argmax(smoothed)) if mode == "max" else int(np.argmin(smoothed))
    edge = idx == 0 or idx == len(freqs) - 1
    return float(freqs[idx]), float(smoothed[idx]), bool(edge)


def theta_tfr_analysis(epochs, times, srate, frontal_idx):
    """Return target-band peak and wider diagnostic-band peak."""
    mask = (times >= FEEDBACK_ANALYSIS[0]) & (times <= FEEDBACK_ANALYSIS[1])
    tfr_target = morlet_tfr(epochs, srate, THETA_FREQS, ch_idx=frontal_idx)
    db_target = baseline_correct_db(tfr_target, times, FEEDBACK_BASELINE)
    target_spectrum = np.mean(db_target[:, mask], axis=1)
    target = find_peak(THETA_FREQS, target_spectrum, mode="max")

    tfr_wide = morlet_tfr(epochs, srate, THETA_DIAGNOSTIC_FREQS, ch_idx=frontal_idx)
    db_wide = baseline_correct_db(tfr_wide, times, FEEDBACK_BASELINE)
    wide_spectrum = np.mean(db_wide[:, mask], axis=1)
    wide = find_peak(THETA_DIAGNOSTIC_FREQS, wide_spectrum, mode="max")
    return target, wide


def beta_analysis(epochs, times, srate, frontal_idx):
    tfr = morlet_tfr(epochs, srate, DECISION_FREQS, ch_idx=frontal_idx)
    tfr_db = baseline_correct_db(tfr, times, DECISION_BASELINE)
    mask = (times >= DECISION_ANALYSIS[0]) & (times <= DECISION_ANALYSIS[1])
    spectrum = np.mean(tfr_db[:, mask], axis=1)
    return find_peak(DECISION_FREQS, spectrum, mode="min")


# =====================================================================
# IAF (posterior alpha) FROM A PSD
# =====================================================================


def posterior_psd(eeg_clean, srate, posterior_idx):
    """2-s Welch PSD averaged over posterior channels. Returns (freqs, psd)."""
    if len(eeg_clean) < 2:
        return None, None

    nperseg = min(int(round(2 * srate)), len(eeg_clean))
    noverlap = min(int(round(srate)), max(0, nperseg - 1))
    freqs, psd = signal.welch(
        eeg_clean[:, posterior_idx], fs=srate, nperseg=nperseg,
        noverlap=noverlap, axis=0,
    )
    return freqs, np.mean(psd, axis=1)


def iaf_from_psd(freqs, psd):
    """Return (theta_iaf_minus_5, iaf, source). NaN / 'unavailable' on failure."""
    if freqs is None or psd is None:
        return np.nan, np.nan, "unavailable"

    iaf_sp = specparam_band_peak(freqs, psd, band=ALPHA_SEARCH_BAND)

    mask = (freqs >= ALPHA_SEARCH_BAND[0]) & (freqs <= ALPHA_SEARCH_BAND[1])
    iaf_power = np.nan
    if mask.any():
        db = 10 * np.log10(np.maximum(psd[mask], 1e-30))
        iaf_power, _p, _e = find_peak(freqs[mask], db, mode="max")

    if valid_frequency(iaf_sp, ALPHA_SEARCH_BAND):
        iaf, source = iaf_sp, "Specparam"
    elif valid_frequency(iaf_power, ALPHA_SEARCH_BAND):
        iaf, source = iaf_power, "power"
    else:
        return np.nan, np.nan, "unavailable"

    theta = np.clip(iaf - 5.0, THETA_SEARCH_BAND[0], THETA_SEARCH_BAND[1])
    return float(theta), float(iaf), source


def valid_frequency(value, band):
    return bool(np.isfinite(value) and band[0] <= value <= band[1])


# =====================================================================
# EVENT-LOCKED ANALYSIS (shared by per-file and pooled)
# =====================================================================


def analyze_event_locked(ep_fb, t_fb, ep_dec, t_dec, label, notes):
    """Theta (Specparam, TFR) from feedback epochs; beta ERD from decision epochs."""
    out = {
        "theta_specparam_hz": np.nan,
        "theta_tfr_hz": np.nan,
        "theta_tfr_db": np.nan,
        "theta_tfr_edge": np.nan,
        "theta_tfr_wide_hz": np.nan,
        "theta_tfr_wide_db": np.nan,
        "theta_tfr_wide_edge": np.nan,
        "theta_specparam_status": "not_run",
        "theta_specparam_n_peaks": 0,
        "theta_specparam_peaks": "",
        "theta_specparam_r_squared": np.nan,
        "theta_specparam_error": np.nan,
        "theta_specparam_resolution_hz": np.nan,
        "theta_specparam_segment_s": np.nan,
        "beta_erd_hz": np.nan,
        "beta_erd_db": np.nan,
        "beta_edge": np.nan,
    }

    if len(ep_fb) >= MIN_EPOCHS:
        try:
            out.update(theta_specparam_diagnostics(
                ep_fb, t_fb, SRATE, FRONTAL_IDX))
        except Exception as exc:
            notes.append(f"{label}: Specparam theta failed ({exc})")
        try:
            target, wide = theta_tfr_analysis(ep_fb, t_fb, SRATE, FRONTAL_IDX)
            out["theta_tfr_hz"], out["theta_tfr_db"], out["theta_tfr_edge"] = target
            out["theta_tfr_wide_hz"], out["theta_tfr_wide_db"], out["theta_tfr_wide_edge"] = wide
        except Exception as exc:
            notes.append(f"{label}: TFR theta failed ({exc})")
    elif len(ep_fb) > 0:
        notes.append(f"{label}: only {len(ep_fb)} feedback epochs (< {MIN_EPOCHS}), theta blank")

    if len(ep_dec) >= MIN_EPOCHS:
        try:
            hz, db, edge = beta_analysis(ep_dec, t_dec, SRATE, FRONTAL_IDX)
            out["beta_erd_hz"], out["beta_erd_db"], out["beta_edge"] = hz, db, edge
        except Exception as exc:
            notes.append(f"{label}: beta ERD failed ({exc})")
    elif len(ep_dec) > 0:
        notes.append(f"{label}: only {len(ep_dec)} decision epochs (< {MIN_EPOCHS}), beta blank")

    return out


def select_theta(specparam_hz, tfr_hz, tfr_edge, iaf5_hz):
    """Specparam -> TFR -> IAF-5. Blank (no fixed fallback) if all fail."""
    if valid_frequency(specparam_hz, THETA_SEARCH_BAND):
        return specparam_hz, "Specparam"
    # Do not accept a TFR maximum at 4 or 8 Hz: it may be outside the
    # searched range, so the in-band peak is not yet trustworthy.
    if valid_frequency(tfr_hz, THETA_SEARCH_BAND) and not bool(tfr_edge):
        return tfr_hz, "TFR"
    if valid_frequency(iaf5_hz, THETA_SEARCH_BAND):
        return iaf5_hz, "IAF-5"
    return np.nan, ""


# =====================================================================
# ONE RECORDING
# =====================================================================


def process_recording(subject, session, task, phase, task_label, prefix,
                      behavior_index, notes):
    """Analyze one .easy file. Returns (row_dict, state_for_pooling)."""
    tag = f"{task}_{phase}"
    row = {}
    state = {"psd": None, "n_samples": 0, "ep_fb": None, "t_fb": None,
             "ep_dec": None, "t_dec": None}

    eeg_file = find_eeg_file(subject, session, task_label, phase, notes, tag)
    if eeg_file is None:
        return row, state

    row[prefix + "eeg_file"] = eeg_file.name

    eeg_uv, unix_ms = load_easy(eeg_file)
    srate_est, max_gap_s = timing_qc(unix_ms)
    row[prefix + "n_samples"] = len(eeg_uv)
    row[prefix + "duration_s"] = round(len(eeg_uv) / SRATE, 1)
    row[prefix + "srate_est_hz"] = round(srate_est, 2) if np.isfinite(srate_est) else np.nan
    row[prefix + "max_gap_s"] = round(max_gap_s, 3) if np.isfinite(max_gap_s) else np.nan

    if np.isfinite(srate_est) and abs(srate_est - SRATE) / SRATE > 0.02:
        notes.append(f"{tag}: estimated srate {srate_est:.1f} Hz differs from {SRATE:g}")
    if np.isfinite(max_gap_s) and max_gap_s > 0.1:
        notes.append(f"{tag}: timestamp gap of {max_gap_s:.2f} s")

    eeg_clean = preprocess(eeg_uv, SRATE, REF_IDX)

    # Continuous IAF / IAF-5 (all four recordings).
    freqs, psd = posterior_psd(eeg_clean, SRATE, POSTERIOR_IDX)
    state["psd"] = (freqs, psd)
    state["n_samples"] = len(eeg_clean)
    iaf5, iaf, iaf_src = iaf_from_psd(freqs, psd)
    row[prefix + "iaf_hz"] = iaf
    row[prefix + "iaf_source"] = iaf_src
    row[prefix + "theta_iaf5_hz"] = iaf5

    if task != "bandit":
        return row, state

    # ---- Bandit: event-locked measures ----
    csvs = behavior_index.get((subject, session, "bandit", phase), [])
    if not csvs:
        notes.append(f"{tag}: no behavior CSV found")
        return row, state

    if len(csvs) > 1:
        behavior_file = pick_latest(csvs)
        notes.append(f"{tag}: {len(csvs)} behavior CSVs matched, used {behavior_file.name}")
    else:
        behavior_file = csvs[0]
    row[prefix + "behavior_file"] = behavior_file.name

    events = pd.read_csv(behavior_file)
    fb_ms = get_event_times(events, FEEDBACK_EVENT_COL)
    dec_ms = get_event_times(events, DECISION_EVENT_COL)

    # Pairing check: events must fall inside this EEG file's time span.
    t0, t1 = unix_ms[0], unix_ms[-1]
    for name, ev in (("feedback", fb_ms), ("decision", dec_ms)):
        valid = np.isfinite(ev)
        in_span = int(np.sum(valid & (ev >= t0) & (ev <= t1)))
        if valid.sum() > 0 and in_span == 0:
            notes.append(
                f"{tag}: no {name} events fall inside the EEG time span; "
                f"event-locked values blank (check CSV/EEG pairing)"
            )
            return row, state

    ep_fb, t_fb, rej_fb = epoch_from_unix(
        eeg_clean, unix_ms, SRATE, fb_ms, *FEEDBACK_EPOCH, reject_ch_idx=REF_IDX)
    ep_dec, t_dec, rej_dec = epoch_from_unix(
        eeg_clean, unix_ms, SRATE, dec_ms, *DECISION_EPOCH, reject_ch_idx=REF_IDX)

    for short, ev, ep, rej in (("fb", fb_ms, ep_fb, rej_fb), ("dec", dec_ms, ep_dec, rej_dec)):
        row[prefix + f"{short}_valid_events"] = int(np.isfinite(ev).sum())
        row[prefix + f"{short}_retained"] = len(ep)
        row[prefix + f"{short}_rej_artifact"] = rej["artifact"]
        row[prefix + f"{short}_rej_bounds"] = rej["out_of_bounds"]
        row[prefix + f"{short}_rej_missing"] = rej["missing_timestamp"]
        row[prefix + f"{short}_artifact_channels"] = artifact_channel_string(rej)

    res = analyze_event_locked(ep_fb, t_fb, ep_dec, t_dec, tag, notes)
    for k, v in res.items():
        row[prefix + k] = v

    sel_hz, sel_src = select_theta(res["theta_specparam_hz"], res["theta_tfr_hz"], res["theta_tfr_edge"], iaf5)
    row[prefix + "theta_selected_hz"] = sel_hz
    row[prefix + "theta_selected_source"] = sel_src

    # Keep epochs for pooling (time axes are identical across files).
    state.update(ep_fb=ep_fb, t_fb=t_fb, ep_dec=ep_dec, t_dec=t_dec)
    return row, state


# =====================================================================
# POOLED VISIT
# =====================================================================


def pool_visit(states, notes):
    """Pool Bandit epochs and average posterior PSDs across recordings."""
    prefix = "all_"
    row = {}

    # Event-locked: concatenate retained epochs from Bandit pre + post.
    fb_list = [s["ep_fb"] for s in states.values()
               if s["ep_fb"] is not None and len(s["ep_fb"]) > 0]
    dec_list = [s["ep_dec"] for s in states.values()
                if s["ep_dec"] is not None and len(s["ep_dec"]) > 0]

    ep_fb = np.concatenate(fb_list) if fb_list else np.empty((0, 1, 1))
    ep_dec = np.concatenate(dec_list) if dec_list else np.empty((0, 1, 1))

    t_fb = next((s["t_fb"] for s in states.values() if s["t_fb"] is not None), None)
    t_dec = next((s["t_dec"] for s in states.values() if s["t_dec"] is not None), None)

    row[prefix + "fb_retained"] = len(ep_fb)
    row[prefix + "dec_retained"] = len(ep_dec)

    res = analyze_event_locked(ep_fb, t_fb, ep_dec, t_dec, "all", notes)
    for k, v in res.items():
        row[prefix + k] = v

    # IAF: duration-weighted mean of posterior PSDs.
    usable = [(s["psd"][0], s["psd"][1], s["n_samples"])
              for s in states.values()
              if s["psd"] is not None and s["psd"][0] is not None]
    iaf5, iaf, iaf_src = np.nan, np.nan, ""
    if usable:
        ref_freqs = usable[0][0]
        same = [(f, p, n) for f, p, n in usable if len(f) == len(ref_freqs)]
        if len(same) < len(usable):
            notes.append("all: some PSDs had different frequency grids and were skipped")
        weights = np.array([n for _f, _p, n in same], dtype=float)
        mean_psd = np.average(np.stack([p for _f, p, _n in same]), axis=0, weights=weights)
        iaf5, iaf, iaf_src = iaf_from_psd(ref_freqs, mean_psd)
        row[prefix + "iaf_n_files"] = len(same)
    row[prefix + "iaf_hz"] = iaf
    row[prefix + "iaf_source"] = iaf_src
    row[prefix + "theta_iaf5_hz"] = iaf5

    sel_hz, sel_src = select_theta(res["theta_specparam_hz"], res["theta_tfr_hz"], res["theta_tfr_edge"], iaf5)
    row[prefix + "theta_selected_hz"] = sel_hz
    row[prefix + "theta_selected_source"] = sel_src
    return row




# =====================================================================
# DIAGNOSTIC PLOTS / REPORT
# These functions inspect retained data. They do not feed values back into
# the production estimator or change the CSV theta/beta calculations.
# =====================================================================

def diagnostic_spectra(epochs, times, srate, frontal_idx):
    """Recreate the existing Specparam-input PSD and TFR curves for plotting."""
    result = {
        "n_epochs": int(len(epochs)),
        "specparam_status": "not_run",
        "specparam_peaks": [],
        "specparam_r_squared": np.nan,
        "specparam_error": np.nan,
        "specparam_theta_peak_hz": np.nan,
        "tfr_wide_peak_hz": np.nan,
        "tfr_wide_peak_db": np.nan,
        "tfr_wide_edge": False,
        "tfr_target_peak_hz": np.nan,
        "tfr_target_peak_edge": False,
    }
    if len(epochs) < MIN_EPOCHS:
        result["specparam_status"] = f"too_few_epochs:{len(epochs)}"
        return result

    # Match theta_specparam_diagnostics exactly: same window, channel average,
    # Welch segment length, overlap, Hann window, and mean across epochs.
    win = ((times >= SPECPARAM_FEEDBACK_ANALYSIS[0])
           & (times <= SPECPARAM_FEEDBACK_ANALYSIS[1]))
    frontal_window = epochs[:, win][:, :, frontal_idx]
    if frontal_window.shape[1] < 2:
        result["specparam_status"] = "insufficient_window_samples"
        return result

    frontal_mean = np.mean(frontal_window, axis=2)
    nperseg = min(int(round(srate * SPECPARAM_WELCH_SECONDS)),
                  frontal_mean.shape[1])
    freqs, trial_psds = signal.welch(
        frontal_mean, fs=srate, nperseg=nperseg, noverlap=nperseg // 2,
        window="hann", axis=1)
    psd = np.mean(trial_psds, axis=0)
    result["psd_freqs"] = freqs
    result["psd"] = psd
    result["welch_resolution_hz"] = float(srate / nperseg)
    result["welch_segment_s"] = float(nperseg / srate)

    if SPECPARAM_AVAILABLE:
        try:
            model = SpectralModel(
                peak_width_limits=[1.0, 8.0], max_n_peaks=6,
                min_peak_height=0.05, aperiodic_mode="fixed")
            model.fit(freqs, psd, freq_range=list(SPECPARAM_FIT_RANGE))
            peaks = model.results.params.periodic.params
            if peaks.size > 0 and peaks.ndim == 2:
                result["specparam_peaks"] = [
                    {"cf": float(cf), "power": float(pw), "bw": float(bw)}
                    for cf, pw, bw in peaks
                ]
                theta_peaks = [p for p in result["specparam_peaks"]
                               if THETA_SEARCH_BAND[0] <= p["cf"] <= THETA_SEARCH_BAND[1]]
                if theta_peaks:
                    result["specparam_theta_peak_hz"] = max(
                        theta_peaks, key=lambda p: p["power"])["cf"]
                result["specparam_status"] = (
                    "theta_peak_found" if theta_peaks else "fit_ok_no_peak_in_4_8hz")
            else:
                result["specparam_status"] = "fit_ok_no_periodic_peaks"
            metrics = getattr(model.results, "metrics", None)
            if metrics is not None:
                result["specparam_r_squared"] = getattr(metrics, "r_squared", np.nan)
                result["specparam_error"] = getattr(metrics, "error", np.nan)
        except Exception as exc:
            result["specparam_status"] = f"fit_error:{type(exc).__name__}:{exc}"
    else:
        result["specparam_status"] = "specparam_not_installed"

    # Match the existing TFR estimator's Morlet, baseline correction,
    # analysis window, and smoothing; this is a diagnostic copy of its curves.
    tfr = morlet_tfr(epochs, srate, THETA_DIAGNOSTIC_FREQS, ch_idx=frontal_idx)
    db = baseline_correct_db(tfr, times, FEEDBACK_BASELINE)
    analysis_mask = ((times >= FEEDBACK_ANALYSIS[0])
                     & (times <= FEEDBACK_ANALYSIS[1]))
    wide_curve = np.mean(db[:, analysis_mask], axis=1)
    result["tfr_freqs"] = THETA_DIAGNOSTIC_FREQS.copy()
    result["tfr_db"] = wide_curve
    wide_peak = find_peak(THETA_DIAGNOSTIC_FREQS, wide_curve, mode="max")
    result["tfr_wide_peak_hz"] = wide_peak[0]
    result["tfr_wide_peak_db"] = wide_peak[1]
    result["tfr_wide_edge"] = wide_peak[2]

    target_mask = ((THETA_DIAGNOSTIC_FREQS >= THETA_SEARCH_BAND[0])
                   & (THETA_DIAGNOSTIC_FREQS <= THETA_SEARCH_BAND[1]))
    target_peak = find_peak(THETA_DIAGNOSTIC_FREQS[target_mask],
                            wide_curve[target_mask], mode="max")
    result["tfr_target_peak_hz"] = target_peak[0]
    result["tfr_target_peak_edge"] = target_peak[2]
    return result


def _diagnostic_slug(value):
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value)).strip("_")


def save_theta_diagnostic(label, epochs, times, output_dir):
    """Save one two-panel PSD/TFR plot and return one report row."""
    spectra = diagnostic_spectra(epochs, times, SRATE, FRONTAL_IDX)
    row = {
        "group": label,
        "retained_feedback_epochs": spectra["n_epochs"],
        "specparam_status": spectra["specparam_status"],
        "specparam_theta_peak_hz": spectra["specparam_theta_peak_hz"],
        "specparam_peaks": "; ".join(
            f'{p["cf"]:.3f} Hz (height={p["power"]:.3f}, bw={p["bw"]:.3f})'
            for p in spectra["specparam_peaks"]),
        "specparam_r_squared": spectra["specparam_r_squared"],
        "specparam_error": spectra["specparam_error"],
        "welch_segment_s": spectra.get("welch_segment_s", np.nan),
        "welch_resolution_hz": spectra.get("welch_resolution_hz", np.nan),
        "tfr_wide_peak_hz": spectra["tfr_wide_peak_hz"],
        "tfr_wide_peak_db": spectra["tfr_wide_peak_db"],
        "tfr_wide_peak_at_2_12_edge": spectra["tfr_wide_edge"],
        "tfr_target_peak_hz": spectra["tfr_target_peak_hz"],
        "tfr_target_peak_at_4_8_edge": spectra["tfr_target_peak_edge"],
    }

    fig, axes = plt.subplots(2, 1, figsize=(11, 8), constrained_layout=True)
    fig.suptitle(
        f"{label} | feedback epochs: {spectra['n_epochs']}\n"
        "Diagnostic only — production theta/beta calculations are unchanged",
        fontsize=12)

    ax = axes[0]
    if "psd_freqs" in spectra:
        f = spectra["psd_freqs"]
        psd = spectra["psd"]
        view = (f >= 2.0) & (f <= 12.0)
        ax.plot(f[view], 10 * np.log10(np.maximum(psd[view], 1e-30)),
                linewidth=1.8, label="Mean Welch PSD (Specparam input)")
        ax.set_ylabel("Power (dB; relative scale)")
        ax.set_xlabel("Frequency (Hz)")
        ax.set_title(
            f"Frontal-average spectrum | Welch segment "
            f"{spectra['welch_segment_s']:.2f} s, "
            f"resolution {spectra['welch_resolution_hz']:.2f} Hz")
        ax.legend(loc="best")
        for peak in spectra["specparam_peaks"]:
            if 2 <= peak["cf"] <= 12:
                ax.axvline(peak["cf"], linestyle="--", alpha=0.65)
                ax.annotate(f'{peak["cf"]:.2f} Hz',
                            (peak["cf"], ax.get_ylim()[1]),
                            xytext=(3, -12), textcoords="offset points",
                            rotation=90, va="top", fontsize=8)
    else:
        ax.text(0.5, 0.5, spectra["specparam_status"],
                ha="center", va="center", transform=ax.transAxes)
        ax.set_title("Welch PSD unavailable")
    ax.axvspan(4, 8, alpha=0.15, label="Target theta: 4–8 Hz")
    ax.set_xlim(2, 12)
    ax.grid(True, alpha=0.25)

    ax = axes[1]
    if "tfr_freqs" in spectra:
        ax.plot(spectra["tfr_freqs"], spectra["tfr_db"],
                linewidth=1.8, label="Mean baseline-corrected TFR")
        ax.axvline(spectra["tfr_wide_peak_hz"], linestyle="--",
                   label=f'2–12 Hz maximum: {spectra["tfr_wide_peak_hz"]:.2f} Hz')
        ax.axvline(spectra["tfr_target_peak_hz"], linestyle=":",
                   label=f'4–8 Hz maximum: {spectra["tfr_target_peak_hz"]:.2f} Hz')
        ax.set_xlim(2, 12)
        ax.set_ylabel("Power change from baseline (dB)")
        ax.set_xlabel("Frequency (Hz)")
        ax.set_title("TFR frequency profile averaged over feedback analysis window")
        ax.legend(loc="best")
    else:
        ax.text(0.5, 0.5, "TFR unavailable", ha="center", va="center",
                transform=ax.transAxes)
    ax.axvspan(4, 8, alpha=0.15)
    ax.grid(True, alpha=0.25)

    fig.savefig(output_dir / f"{_diagnostic_slug(label)}.png", dpi=160)
    plt.close(fig)
    return row


def create_subject_diagnostics(subject, session_states, output_dir):
    """Create per-recording, per-session pooled, and across-session diagnostics."""
    output_dir.mkdir(parents=True, exist_ok=True)
    report_rows = []
    all_feedback = []

    for session in sorted({key[0] for key in session_states}):
        session_feedback = []
        for phase in ("pre", "post"):
            state = session_states.get((session, "bandit", phase))
            if state and state.get("ep_fb") is not None and len(state["ep_fb"]):
                label = f"{subject}_session-{session}_bandit-{phase}"
                report_rows.append(save_theta_diagnostic(
                    label, state["ep_fb"], state["t_fb"], output_dir))
                session_feedback.append((state["ep_fb"], state["t_fb"]))
                all_feedback.append((state["ep_fb"], state["t_fb"]))

        if session_feedback:
            ep = np.concatenate([item[0] for item in session_feedback], axis=0)
            t = session_feedback[0][1]
            label = f"{subject}_session-{session}_bandit-pre-plus-post"
            report_rows.append(save_theta_diagnostic(label, ep, t, output_dir))

    if all_feedback:
        ep = np.concatenate([item[0] for item in all_feedback], axis=0)
        t = all_feedback[0][1]
        label = f"{subject}_pooled-sessions-1-3_bandit-pre-plus-post"
        report_rows.append(save_theta_diagnostic(label, ep, t, output_dir))

    report = pd.DataFrame(report_rows)
    report_path = output_dir / f"{_diagnostic_slug(subject)}_theta_diagnostic_report.csv"
    report.to_csv(report_path, index=False)

    # A readable text summary accompanies the machine-readable report.
    txt_path = output_dir / f"{_diagnostic_slug(subject)}_theta_diagnostic_report.txt"
    with txt_path.open("w", encoding="utf-8") as f:
        f.write(f"Theta diagnostic report: {subject}\n")
        f.write("=" * 60 + "\n\n")
        f.write("These diagnostics do not alter or replace the main theta/beta CSV.\n")
        f.write("Both Bandit pre- and post-stimulation feedback epochs are included.\n")
        f.write("PSD plots show the spectrum supplied to Specparam; TFR plots show\n")
        f.write("the existing baseline-corrected TFR profile over 2–12 Hz.\n\n")
        f.write("Interpretation cautions:\n")
        f.write("- A Specparam peak is a periodic peak above the fitted aperiodic background.\n")
        f.write("- No Specparam peak in 4–8 Hz does not mean there is no theta-band power.\n")
        f.write("- A TFR maximum at a band edge is not evidence of a well-localized peak.\n")
        f.write("- These plots are descriptive; peak presence should be judged using\n")
        f.write("  prespecified quality criteria and the study protocol.\n\n")
        if report.empty:
            f.write("No usable Bandit feedback epochs were available for diagnostics.\n")
        else:
            f.write(report.to_string(index=False))
            f.write("\n")
    return report_path, txt_path, len(report_rows)


# =====================================================================
# CSV COLUMNS
# =====================================================================

_FILE_QC = ["eeg_file", "n_samples", "duration_s", "srate_est_hz", "max_gap_s"]
_IAF = ["iaf_hz", "iaf_source", "theta_iaf5_hz"]
_EPOCH_QC = [f"{s}_{k}" for s in ("fb", "dec")
             for k in ("valid_events", "retained", "rej_artifact", "rej_bounds",
                       "rej_missing", "artifact_channels")]
_EVENT_VALUES = ["theta_specparam_hz", "theta_specparam_status",
                 "theta_specparam_n_peaks", "theta_specparam_peaks",
                 "theta_specparam_r_squared", "theta_specparam_error",
                 "theta_specparam_resolution_hz", "theta_specparam_segment_s",
                 "theta_tfr_hz", "theta_tfr_db", "theta_tfr_edge",
                 "theta_tfr_wide_hz", "theta_tfr_wide_db", "theta_tfr_wide_edge",
                 "theta_selected_hz", "theta_selected_source",
                 "beta_erd_hz", "beta_erd_db", "beta_edge"]

BANDIT_COLS = _FILE_QC + ["behavior_file"] + _EPOCH_QC + _EVENT_VALUES + _IAF
SST_COLS = _FILE_QC + _IAF
ALL_COLS = ["fb_retained", "dec_retained", "iaf_n_files"] + _EVENT_VALUES + _IAF


def all_columns():
    cols = ["subject_id", "session"]
    for task, _phase, prefix, _label in RECORDINGS:
        block = BANDIT_COLS if task == "bandit" else SST_COLS
        cols += [prefix + c for c in block]
    cols += ["all_" + c for c in ALL_COLS]
    cols.append("notes")
    return cols


# =====================================================================
# SESSION DRIVER
# =====================================================================


def process_session(subject, session, behavior_index):
    """Process one session and return both its output row and pooling states."""
    notes = []
    row = {"subject_id": subject, "session": session}
    states = {}

    for task, phase, prefix, task_label in RECORDINGS:
        try:
            rec_row, state = process_recording(
                subject, session, task, phase, task_label, prefix,
                behavior_index, notes)
        except Exception as exc:
            notes.append(f"{task}_{phase}: ERROR {type(exc).__name__}: {exc}")
            rec_row, state = {}, None
        row.update(rec_row)
        if state is not None:
            states[(task, phase)] = state

    if states:
        try:
            row.update(pool_visit(states, notes))
        except Exception as exc:
            notes.append(f"all: pooling ERROR {type(exc).__name__}: {exc}")

    if not SPECPARAM_AVAILABLE:
        notes.append("specparam not installed: Specparam values blank")

    row["notes"] = " | ".join(notes)
    return row, states


def pool_subject_sessions(subject, session_states, available_sessions):
    """Create a fourth output row pooling retained data across sessions 1-3.

    Session-level rows remain unchanged. The pooled row combines the retained
    Bandit event epochs across sessions and duration-weights posterior PSDs
    from every available recording/session, using the same method as pool_visit.
    """
    row = {"subject_id": subject, "session": "pooled_1-3"}
    notes = []
    missing = sorted(set(SESSIONS) - set(available_sessions))

    if missing:
        notes.append(
            "Cross-session pooling not calculated: missing session(s) "
            + ", ".join(map(str, missing))
        )
    else:
        try:
            row.update(pool_visit(session_states, notes))
        except Exception as exc:
            notes.append(f"cross-session pooling ERROR {type(exc).__name__}: {exc}")

    if not SPECPARAM_AVAILABLE:
        notes.append("specparam not installed: Specparam values blank")
    row["notes"] = " | ".join(notes)
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--subjects", nargs="*", help="Limit to these subject IDs")
    parser.add_argument("--sessions", nargs="*", type=int, help="Limit to these sessions")
    parser.add_argument("--out", type=Path, help="Output CSV path")
    parser.add_argument("--diagnostic-dir", type=Path,
                        help="Folder for diagnostic PNGs and report (default: timestamped folder in OUTPUT_DIR)")
    args = parser.parse_args()

    print(f"Scanning: {BEHAVIOR_DATA_DIR}")
    behavior_index, subjects = scan_behavior_folder(BEHAVIOR_DATA_DIR)
    if not subjects:
        raise SystemExit("No behavior CSVs matching the expected pattern were found.")

    wanted = set(args.subjects) if args.subjects else None
    wanted_ses = set(args.sessions) if args.sessions else set(SESSIONS)

    jobs_by_subject = {}
    for sub in sorted(subjects, key=natural_key):
        if wanted and sub not in wanted:
            continue
        selected_sessions = [ses for ses in subjects[sub] if ses in wanted_ses]
        if selected_sessions:
            jobs_by_subject[sub] = selected_sessions
    job_count = sum(len(v) for v in jobs_by_subject.values())

    print(f"Found {len(subjects)} subject(s); {job_count} session(s) to process.")
    if not SPECPARAM_AVAILABLE:
        print("WARNING: specparam is not installed; Specparam columns will be blank.")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    run_stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_path = args.out or OUTPUT_DIR / f"full-visit_theta-beta_{run_stamp}.csv"
    diagnostic_dir = args.diagnostic_dir or OUTPUT_DIR / f"theta-diagnostics_{run_stamp}"

    cols = all_columns()
    rows = []
    t_start = time.time()
    completed = 0

    for sub, selected_sessions in jobs_by_subject.items():
        subject_states = {}
        processed_sessions = []
        for ses in selected_sessions:
            completed += 1
            t0 = time.time()
            print(f"[{completed}/{job_count}] {sub} session {ses} ...", end=" ", flush=True)
            row, states = process_session(sub, ses, behavior_index)
            rows.append(row)
            processed_sessions.append(ses)

            # Keep session identity in the keys so states from different
            # sessions are all retained when pooling across the participant.
            for (task, phase), state in states.items():
                subject_states[(ses, task, phase)] = state

            print(f"done in {time.time() - t0:.0f}s" + ("  (see notes)" if row["notes"] else ""))

            # Rewrite after every session so a crash never loses finished work.
            pd.DataFrame(rows).reindex(columns=cols).to_csv(out_path, index=False)

        # Add one extra participant-level row after the session rows.
        # A true 1-3 pooled result is only calculated when all three sessions
        # were selected and discovered; otherwise the extra row explains why
        # the cross-session value was not calculated.
        pooled_row = pool_subject_sessions(sub, subject_states, processed_sessions)
        rows.append(pooled_row)
        pd.DataFrame(rows).reindex(columns=cols).to_csv(out_path, index=False)

        # Diagnostic plotting is a separate read-only pass over retained
        # epochs. It does not modify the main CSV or estimator outputs.
        subject_diag_dir = diagnostic_dir / _diagnostic_slug(sub)
        report_csv, report_txt, plot_count = create_subject_diagnostics(
            sub, subject_states, subject_diag_dir)
        print(f"  Diagnostics: {plot_count} plot(s)")
        print(f"  Report CSV: {report_csv}")
        print(f"  Report TXT: {report_txt}")

    print(f"\nFinished {job_count} session(s) in {(time.time() - t_start) / 60:.1f} min")
    print(f"Saved: {out_path}")
    print(f"Diagnostic files: {diagnostic_dir}")


if __name__ == "__main__":
    main()
