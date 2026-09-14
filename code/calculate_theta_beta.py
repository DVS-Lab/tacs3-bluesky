#!/usr/bin/env python3
"""Lab-style individualized theta / beta frequency estimation.

GUI version.

The script:
1. Asks for Subject ID.
2. Asks for Session number (1-3).
3. Automatically finds the matching EEG .easy file.
4. Automatically finds the matching behavioral .csv file.
5. Uses Unix timestamps in the two files to align EEG and behavior.
6. Estimates outcome theta frequency using two methods:
   - Specparam (periodic peak above the aperiodic background)
   - Morlet TFR power peak
7. Estimates decision beta ERD peak frequency using Morlet TFR.
8. Saves a single text report named SUBJECT-SESSION_pre-stim_theta-beta.txt.
"""

from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk

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

HIGHPASS = 0.5
LOWPASS = 45.0
NOTCH = 60.0
NOTCH_Q = 30.0
EPOCH_REJECT_UV = 200.0
NV_TO_UV = 1e-3
SRATE = 500.0

# Specparam theta settings copied from the lab pipeline.
SPECPARAM_THETA_BAND = (4.0, 8.0)
SPECPARAM_FIT_RANGE = (2.0, 40.0)
SPECPARAM_FEEDBACK_ANALYSIS = (0.1, 1.5)
SPECPARAM_WELCH_SECONDS = 0.5

# Individualized-frequency settings.
THETA_SEARCH_BAND = (4.0, 8.0)
ALPHA_SEARCH_BAND = (8.0, 13.0)
BETA_SEARCH_BAND = (13.0, 30.0)
DEFAULT_THETA_HZ = 6.0

FEEDBACK_EPOCH = (-1.5, 2.0)
FEEDBACK_BASELINE = (-0.8, -0.1)
FEEDBACK_ANALYSIS = (0.1, 1.5)

DECISION_EPOCH = (-1.5, 0.5)
DECISION_BASELINE = (-1.5, -1.0)
DECISION_ANALYSIS = (-1.0, -0.1)

THETA_FREQS = np.arange(
    THETA_SEARCH_BAND[0],
    THETA_SEARCH_BAND[1] + 0.25,
    0.25,
)
DECISION_FREQS = np.arange(
    BETA_SEARCH_BAND[0],
    BETA_SEARCH_BAND[1] + 0.5,
    0.5,
)

N_CYCLES = 5
SMOOTH_SIGMA = 1.0

FEEDBACK_EVENT_COL = "feedback_onset_unix_time"
DECISION_EVENT_COL = "choice_onset_unix_time"

# Original 1-based channel numbers.
FRONTAL_CHANNELS = (1, 3, 5)  # F3, FCz, F4
POSTERIOR_ALPHA_CHANNELS = (6, 7)  # P4, P3
REF_CHANNELS = (1, 2, 3, 4, 5, 6, 7)  # all scalp channels; excludes EXT

CHANNEL_LABELS = {
    1: "F3",
    2: "Fp1",
    3: "FCz",
    4: "FT7",
    5: "F4",
    6: "P4",
    7: "P3",
    8: "EXT",
}


# =====================================================================
# GUI
# =====================================================================


def get_subject_and_session():
    """Open a GUI asking for subject ID and session number."""
    result = {"subject_id": None, "session": None}

    root = tk.Tk()
    root.title("Theta / Beta Frequency Estimation")
    root.geometry("420x230")
    root.resizable(False, False)

    frame = ttk.Frame(root, padding=20)
    frame.pack(fill="both", expand=True)

    ttk.Label(frame, text="Subject ID:", font=("Arial", 11)).grid(
        row=0, column=0, sticky="w", pady=(0, 10)
    )
    subject_entry = ttk.Entry(frame, width=30)
    subject_entry.grid(row=0, column=1, pady=(0, 10))

    ttk.Label(frame, text="Session:", font=("Arial", 11)).grid(
        row=1, column=0, sticky="w", pady=(0, 10)
    )
    session_var = tk.StringVar(value="1")
    session_dropdown = ttk.Combobox(
        frame,
        textvariable=session_var,
        values=["1", "2", "3"],
        state="readonly",
        width=27,
    )
    session_dropdown.grid(row=1, column=1, pady=(0, 10))

    def submit():
        subject = subject_entry.get().strip()
        session = session_var.get()

        if not subject:
            messagebox.showerror("Missing Subject ID", "Please enter a subject ID.")
            return

        if not subject.isdigit():
            messagebox.showerror(
                "Invalid Subject ID",
                "Subject ID should contain numbers only.",
            )
            return

        result["subject_id"] = subject
        result["session"] = session
        root.destroy()

    ttk.Button(frame, text="Run Analysis", command=submit).grid(
        row=2, column=0, columnspan=2, pady=(20, 0)
    )

    subject_entry.focus()
    root.bind("<Return>", lambda _event: submit())
    root.mainloop()

    return result["subject_id"], result["session"]


# =====================================================================
# FILE FINDING
# =====================================================================


def newest_file(matches):
    """Return the most recently modified path from an iterable of paths."""
    return max(matches, key=lambda p: p.stat().st_mtime)


def find_input_files(subject_id, session):
    """Find the EEG and behavioral files for a subject/session."""
    eeg_pattern = f"*_{subject_id}-{session}*.easy"
    behavior_pattern = f"sub-{subject_id}-{session}_task-bandit_*.csv"

    eeg_matches = list(STIM_DATA_DIR.glob(eeg_pattern))
    behavior_matches = list(BEHAVIOR_DATA_DIR.glob(behavior_pattern))

    if not behavior_matches:
        raise FileNotFoundError(
            "No behavioral CSV file was found.\n\n"
            f"Directory:\n{BEHAVIOR_DATA_DIR}\n\n"
            f"Pattern:\n{behavior_pattern}"
        )

    behavior_file = newest_file(behavior_matches)

    if eeg_matches:
        return newest_file(eeg_matches), behavior_file

    all_easy_files = list(STIM_DATA_DIR.glob("*.easy"))
    if not all_easy_files:
        raise FileNotFoundError(
            "No EEG .easy file could be found.\n\n"
            f"Directory:\n{STIM_DATA_DIR}\n\n"
            f"Expected pattern:\n{eeg_pattern}\n\n"
            "There are also no .easy files in the stimulation-data directory."
        )

    most_recent_easy = newest_file(all_easy_files)

    root = tk.Tk()
    root.withdraw()
    use_fallback = messagebox.askyesno(
        "EEG File Not Found",
        (
            f"Couldn't locate:\n\n{eeg_pattern}\n\n"
            f"The most recent .easy file is:\n\n{most_recent_easy.name}\n\n"
            f"Would you like to use this file to calculate "
            f"{subject_id}'s session {session} theta and beta?"
        ),
    )
    root.destroy()

    if not use_fallback:
        raise FileNotFoundError(
            "No matching EEG file was found and the fallback file was declined."
        )

    return most_recent_easy, behavior_file


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

    b, a = signal.butter(
        4,
        [HIGHPASS / nyq, LOWPASS / nyq],
        btype="band",
    )
    out = signal.filtfilt(b, a, out, axis=0)

    # Retained from the original pipeline for methodological consistency.
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
    """Create event-locked epochs and reject epochs exceeding the UV threshold."""
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
                    reduced_idx = reject_ch_idx[pos]
                    artifact_by_channel[reduced_idx] = (
                        artifact_by_channel.get(reduced_idx, 0) + 1
                    )
                continue

        ep = signal.detrend(ep, axis=0, type="linear")
        epochs.append(ep)

    if epochs:
        epochs = np.stack(epochs)
    else:
        epochs = np.empty((0, n_epoch, eeg.shape[1]))

    reject_reason = {
        "missing_timestamp": skipped_missing,
        "out_of_bounds": rejected_bounds,
        "artifact": rejected_artifact,
        "artifact_by_channel": artifact_by_channel,
    }

    return epochs, times, reject_reason


def get_event_times(events, column):
    """Validate an event column and convert it to a float NumPy array."""
    if column not in events.columns:
        raise KeyError(f"CSV is missing {column}")

    return pd.to_numeric(events[column], errors="coerce").to_numpy(float)


# =====================================================================
# THETA METHOD 1: SPECPARAM
# =====================================================================


def specparam_band_peak(
    freqs,
    psd,
    band=SPECPARAM_THETA_BAND,
    freq_range=SPECPARAM_FIT_RANGE,
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
            if (
                band[0] <= center_frequency <= band[1]
                and peak_power > best_power
            ):
                best_cf = center_frequency
                best_power = peak_power

    return float(best_cf) if np.isfinite(best_cf) else np.nan


def theta_specparam_analysis(
    feedback_epochs,
    feedback_times,
    srate,
    frontal_idx,
):
    """Estimate theta from a Specparam fit to the feedback-window PSD.

    This is the minimum calculation used in the lab notebook:
    1. Keep the feedback analysis window.
    2. Average F3/FCz/F4 within each epoch.
    3. Compute a Welch PSD for each epoch and average the PSDs.
    4. Fit Specparam from 2-40 Hz.
    5. Return the strongest modeled periodic peak from 4-8 Hz.
    """
    if not SPECPARAM_AVAILABLE:
        return np.nan

    win_mask = (
        (feedback_times >= SPECPARAM_FEEDBACK_ANALYSIS[0])
        & (feedback_times <= SPECPARAM_FEEDBACK_ANALYSIS[1])
    )
    frontal_window = feedback_epochs[:, win_mask][:, :, frontal_idx]

    if frontal_window.shape[1] == 0:
        return np.nan

    # Average the frontal ROI first, matching the lab code.
    frontal_mean = np.mean(frontal_window, axis=2)

    nperseg = min(
        int(round(srate * SPECPARAM_WELCH_SECONDS)),
        frontal_mean.shape[1],
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
# THETA METHOD 2: TFR
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

        wav = np.exp(2j * np.pi * f * t_wav) * np.exp(
            -(t_wav**2) / (2 * sigma_t**2)
        )
        wav /= np.sqrt(np.sum(np.abs(wav) ** 2))

        for ci in ch_idx:
            for ei in range(n_ep):
                conv = signal.fftconvolve(epochs[ei, :, ci], wav, mode="same")
                power[fi] += np.abs(conv) ** 2

        power[fi] /= n_ep * len(ch_idx)

    return power


def baseline_correct_db(tfr, times, baseline_window):
    """Convert TFR power to dB relative to a baseline window."""
    baseline_mask = (
        (times >= baseline_window[0]) & (times <= baseline_window[1])
    )
    baseline_power = np.maximum(
        np.mean(tfr[:, baseline_mask], axis=1, keepdims=True),
        1e-30,
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
        feedback_epochs,
        srate,
        THETA_FREQS,
        n_cycles=N_CYCLES,
        ch_idx=frontal_idx,
    )
    tfr_db = baseline_correct_db(tfr, feedback_times, FEEDBACK_BASELINE)

    outcome_mask = (
        (feedback_times >= FEEDBACK_ANALYSIS[0])
        & (feedback_times <= FEEDBACK_ANALYSIS[1])
    )
    theta_spectrum = np.mean(tfr_db[:, outcome_mask], axis=1)

    return find_peak(
        THETA_FREQS,
        theta_spectrum,
        mode="max",
        smooth_sigma=SMOOTH_SIGMA,
    )


# =====================================================================
# THETA METHOD 3: IAF - 5
# =====================================================================


def iaf_minus_5_analysis(eeg_clean, srate, posterior_idx):
    """Estimate theta as IAF - 5 Hz using the lab's posterior-alpha method.

    IAF is estimated from continuous cleaned EEG at P3/P4 using a 2-second
    Welch PSD. The alpha peak is taken from 8-13 Hz using Specparam when
    available, with the power-spectrum peak as a fallback. IAF - 5 is then
    constrained to the 4-8 Hz theta range, matching the lab notebook.
    """
    if len(eeg_clean) < 2:
        return np.nan, np.nan, "unavailable"

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

    iaf_specparam = specparam_band_peak(
        freqs,
        posterior_psd,
        band=ALPHA_SEARCH_BAND,
    )

    alpha_mask = (
        (freqs >= ALPHA_SEARCH_BAND[0])
        & (freqs <= ALPHA_SEARCH_BAND[1])
    )
    alpha_freqs = freqs[alpha_mask]
    alpha_db = 10 * np.log10(np.maximum(posterior_psd[alpha_mask], 1e-30))

    iaf_power = np.nan
    if len(alpha_freqs) > 0:
        iaf_power, _power, _edge = find_peak(
            alpha_freqs,
            alpha_db,
            mode="max",
            smooth_sigma=SMOOTH_SIGMA,
        )

    if (
        np.isfinite(iaf_specparam)
        and ALPHA_SEARCH_BAND[0] <= iaf_specparam <= ALPHA_SEARCH_BAND[1]
    ):
        iaf = iaf_specparam
        iaf_source = "Specparam"
    elif (
        np.isfinite(iaf_power)
        and ALPHA_SEARCH_BAND[0] <= iaf_power <= ALPHA_SEARCH_BAND[1]
    ):
        iaf = iaf_power
        iaf_source = "power"
    else:
        return np.nan, np.nan, "unavailable"

    theta_iaf_minus_5 = np.clip(
        iaf - 5.0,
        THETA_SEARCH_BAND[0],
        THETA_SEARCH_BAND[1],
    )
    return float(theta_iaf_minus_5), float(iaf), iaf_source


def valid_frequency(value, band):
    """Return True when a frequency is finite and inside a requested band."""
    return bool(np.isfinite(value) and band[0] <= value <= band[1])


def beta_analysis(decision_epochs, decision_times, srate, frontal_idx):
    """Estimate the decision-related beta ERD peak frequency."""
    tfr = morlet_tfr(
        decision_epochs,
        srate,
        DECISION_FREQS,
        n_cycles=N_CYCLES,
        ch_idx=frontal_idx,
    )
    tfr_db = baseline_correct_db(tfr, decision_times, DECISION_BASELINE)

    decision_mask = (
        (decision_times >= DECISION_ANALYSIS[0])
        & (decision_times <= DECISION_ANALYSIS[1])
    )
    beta_spectrum = np.mean(tfr_db[:, decision_mask], axis=1)

    # Strongest ERD = most negative dB.
    return find_peak(
        DECISION_FREQS,
        beta_spectrum,
        mode="min",
        smooth_sigma=SMOOTH_SIGMA,
    )


# =====================================================================
# ARTIFACT REPORTING
# =====================================================================


def get_artifact_counts(reject_info):
    """Convert 0-based channel artifact counts to channel names."""
    counts = {}

    for channel_idx, count in reject_info.get("artifact_by_channel", {}).items():
        channel_number = int(channel_idx) + 1
        channel_name = CHANNEL_LABELS.get(channel_number, f"Ch{channel_number}")
        counts[channel_name] = count

    return counts


# =====================================================================
# REPORT HELPERS
# =====================================================================


def format_window(window):
    """Format a time window with explicit signs, e.g. -1.5 to +2.0 s."""
    return f"{window[0]:+.1f} to {window[1]:+.1f} s"


def format_band(band):
    """Format a frequency band compactly."""
    return f"{band[0]:g}-{band[1]:g} Hz"




# =====================================================================
# MAIN ANALYSIS
# =====================================================================


def run_analysis(subject_id, session):
    eeg_file, behavior_file = find_input_files(subject_id, session)

    print()
    print("=" * 70)
    print("THETA / BETA FREQUENCY ESTIMATION")
    print("=" * 70)
    print(f"Subject: {subject_id}")
    print(f"Session: {session}")
    print(f"\nEEG file:\n{eeg_file}")
    print(f"\nBehavior file:\n{behavior_file}")

    eeg_uv, unix_ms = load_easy(eeg_file)

    # Fixed montage: frontal ROI = F3/FCz/F4; posterior alpha ROI = P4/P3.
    # Reference/artifact checks use scalp channels 1-7.
    frontal_idx = [ch - 1 for ch in FRONTAL_CHANNELS]
    posterior_alpha_idx = [ch - 1 for ch in POSTERIOR_ALPHA_CHANNELS]
    ref_idx = [ch - 1 for ch in REF_CHANNELS]

    eeg_clean = preprocess(eeg_uv, SRATE, ref_idx=ref_idx)
    reject_idx = ref_idx

    events = pd.read_csv(behavior_file)

    feedback_ms = get_event_times(events, FEEDBACK_EVENT_COL)
    ep_fb, t_fb, rej_fb = epoch_from_unix(
        eeg_clean,
        unix_ms,
        SRATE,
        feedback_ms,
        FEEDBACK_EPOCH[0],
        FEEDBACK_EPOCH[1],
        reject_uv=EPOCH_REJECT_UV,
        reject_ch_idx=reject_idx,
    )

    decision_ms = get_event_times(events, DECISION_EVENT_COL)
    ep_dec, t_dec, rej_dec = epoch_from_unix(
        eeg_clean,
        unix_ms,
        SRATE,
        decision_ms,
        DECISION_EPOCH[0],
        DECISION_EPOCH[1],
        reject_uv=EPOCH_REJECT_UV,
        reject_ch_idx=reject_idx,
    )

    # Theta method 1: Specparam.
    theta_specparam_hz = np.nan
    if len(ep_fb) > 0:
        theta_specparam_hz = theta_specparam_analysis(
            ep_fb,
            t_fb,
            SRATE,
            frontal_idx,
        )

    # Theta method 2: existing Morlet TFR peak.
    theta_tfr_hz = np.nan
    theta_tfr_db = np.nan
    theta_tfr_edge = False
    if len(ep_fb) > 0:
        theta_tfr_hz, theta_tfr_db, theta_tfr_edge = theta_tfr_analysis(
            ep_fb,
            t_fb,
            SRATE,
            frontal_idx,
        )

    # Theta method 3: posterior individual alpha frequency minus 5 Hz.
    theta_iaf_minus_5_hz, iaf_hz, iaf_source = iaf_minus_5_analysis(
        eeg_clean,
        SRATE,
        posterior_alpha_idx,
    )

    # Final theta selection hierarchy:
    # Specparam -> TFR -> IAF-5 -> fixed 6 Hz fallback.
    if valid_frequency(theta_specparam_hz, THETA_SEARCH_BAND):
        theta_stimulation_hz = theta_specparam_hz
        theta_selection_source = "Specparam"
    elif valid_frequency(theta_tfr_hz, THETA_SEARCH_BAND):
        theta_stimulation_hz = theta_tfr_hz
        theta_selection_source = "TFR"
    elif valid_frequency(theta_iaf_minus_5_hz, THETA_SEARCH_BAND):
        theta_stimulation_hz = theta_iaf_minus_5_hz
        theta_selection_source = "IAF-5"
    else:
        theta_stimulation_hz = DEFAULT_THETA_HZ
        theta_selection_source = "fixed 6 Hz fallback"

    beta_peak_hz = np.nan
    beta_peak_db = np.nan
    beta_edge = False
    if len(ep_dec) > 0:
        beta_peak_hz, beta_peak_db, beta_edge = beta_analysis(
            ep_dec,
            t_dec,
            SRATE,
            frontal_idx,
        )

    feedback_artifacts = get_artifact_counts(rej_fb)
    decision_artifacts = get_artifact_counts(rej_dec)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / f"{subject_id}-{session}_pre-stim_theta-beta.txt"

    roi_text = ", ".join(CHANNEL_LABELS[ch] for ch in FRONTAL_CHANNELS)

    lines = [
        "THETA / BETA RESULTS",
        "=" * 50,
        f"Subject: {subject_id} | Session: {session}",
        f"EEG: {eeg_file.name}",
        f"Behavior: {behavior_file.name}",
        "",
        "QC / TROUBLESHOOTING",
        "-" * 50,
        f"Sampling rate: {SRATE:g} Hz (hard-coded)",
        f"Frontal ROI: {roi_text}",
        f"Artifact threshold: ±{EPOCH_REJECT_UV:g} uV",
        (
            "Feedback: "
            f"{np.isfinite(feedback_ms).sum()} valid events | "
            f"{len(ep_fb)} retained | "
            f"{rej_fb['artifact']} artifact | "
            f"{rej_fb['out_of_bounds']} bounds | "
            f"{rej_fb['missing_timestamp']} missing timestamp"
        ),
        (
            "Decision: "
            f"{np.isfinite(decision_ms).sum()} valid events | "
            f"{len(ep_dec)} retained | "
            f"{rej_dec['artifact']} artifact | "
            f"{rej_dec['out_of_bounds']} bounds | "
            f"{rej_dec['missing_timestamp']} missing timestamp"
        ),
    ]

    if feedback_artifacts:
        fb_breakdown = ", ".join(
            f"{channel}={count}" for channel, count in sorted(feedback_artifacts.items())
        )
        lines.append(f"Feedback artifact channels: {fb_breakdown}")

    if decision_artifacts:
        dec_breakdown = ", ".join(
            f"{channel}={count}" for channel, count in sorted(decision_artifacts.items())
        )
        lines.append(f"Decision artifact channels: {dec_breakdown}")

    lines.extend(
        [
            "",
            "THETA",
            "=" * 50,
            f"Band: {format_band(THETA_SEARCH_BAND)} | Feedback window: {format_window(FEEDBACK_ANALYSIS)}",
        ]
    )

    if not SPECPARAM_AVAILABLE:
        lines.append("Specparam: UNAVAILABLE (specparam not installed)")
    elif np.isfinite(theta_specparam_hz):
        lines.append(f"Specparam theta: {theta_specparam_hz:.2f} Hz")
    else:
        lines.append("Specparam theta: NO MODELED PEAK")

    if np.isfinite(theta_tfr_hz):
        edge_text = " | BAND EDGE" if theta_tfr_edge else ""
        lines.append(
            f"TFR theta: {theta_tfr_hz:.2f} Hz | {theta_tfr_db:.3f} dB{edge_text}"
        )
    else:
        lines.append("TFR theta: UNAVAILABLE")

    if np.isfinite(theta_iaf_minus_5_hz):
        lines.append(
            f"IAF-5 theta: {theta_iaf_minus_5_hz:.2f} Hz "
            f"(IAF: {iaf_hz:.2f} Hz via {iaf_source})"
        )
    else:
        lines.append("IAF-5 theta: UNAVAILABLE")

    lines.append(
        f"Selected theta: {theta_stimulation_hz:.2f} Hz via {theta_selection_source}"
    )

    lines.extend(
        [
            "",
            "BETA",
            "=" * 50,
            f"Band: {format_band(BETA_SEARCH_BAND)} | Decision window: {format_window(DECISION_ANALYSIS)}",
        ]
    )

    if np.isfinite(beta_peak_hz):
        edge_text = " | BAND EDGE" if beta_edge else ""
        lines.append(
            f"TFR beta ERD: {beta_peak_hz:.2f} Hz | {beta_peak_db:.3f} dB{edge_text}"
        )
    else:
        lines.append("TFR beta ERD: UNAVAILABLE")

    # Machine-readable lines for the downstream stimulation script.
    lines.extend(
        [
            "",
            "STIMULATION FREQUENCIES",
            "=" * 50,
            f"Theta stimulation frequency: {theta_stimulation_hz:.2f} Hz",
            (
                f"Beta stimulation frequency: {beta_peak_hz:.2f} Hz"
                if np.isfinite(beta_peak_hz)
                else "Beta stimulation frequency: UNAVAILABLE"
            ),
        ]
    )

    output_path.write_text("\n".join(lines), encoding="utf-8")

    print()
    print("=" * 70)
    print("RESULTS")
    print("=" * 70)
    print(f"Subject: {subject_id}")
    print(f"Session: {session}")
    print(
        f"Outcome theta peak (Specparam): {theta_specparam_hz:.2f} Hz"
        if np.isfinite(theta_specparam_hz)
        else "Outcome theta peak (Specparam): unavailable"
    )
    print(
        f"Outcome theta peak (TFR): {theta_tfr_hz:.2f} Hz"
        if np.isfinite(theta_tfr_hz)
        else "Outcome theta peak (TFR): unavailable"
    )
    print(
        f"Theta IAF-5: {theta_iaf_minus_5_hz:.2f} Hz "
        f"(IAF {iaf_hz:.2f} Hz via {iaf_source})"
        if np.isfinite(theta_iaf_minus_5_hz)
        else "Theta IAF-5: unavailable"
    )
    print(
        f"Selected theta stimulation frequency: {theta_stimulation_hz:.2f} Hz "
        f"({theta_selection_source})"
    )
    print(
        f"Decision beta ERD peak: {beta_peak_hz:.2f} Hz"
        if np.isfinite(beta_peak_hz)
        else "Decision beta ERD peak: unavailable"
    )
    print()
    print(f"Saved: {output_path}")

    return output_path


# =====================================================================
# GUI ERROR / SUCCESS WRAPPER
# =====================================================================


def main():
    subject_id, session = get_subject_and_session()

    if subject_id is None:
        print("Analysis cancelled.")
        return

    try:
        output_path = run_analysis(subject_id, session)
    except Exception as exc:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("Analysis Error", str(exc))
        root.destroy()
        raise

    root = tk.Tk()
    root.withdraw()
    messagebox.showinfo(
        "Analysis Complete",
        f"Theta/beta analysis completed.\n\nOutput:\n{output_path}",
    )
    root.destroy()


if __name__ == "__main__":
    main()
