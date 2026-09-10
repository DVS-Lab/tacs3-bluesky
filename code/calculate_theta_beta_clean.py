#!/usr/bin/env python3
"""Lab-style individualized theta / beta frequency estimation.

GUI version.

The script:
1. Asks for Subject ID.
2. Asks for Session number (1-3).
3. Automatically finds the matching EEG .easy file.
4. Automatically finds the matching behavioral .csv file.
5. Uses Unix timestamps in the two files to align EEG and behavior.
6. Estimates outcome theta peak frequency and decision beta ERD peak frequency.
7. Saves a single text report named SUBJECT-SESSION_pre-stim_theta-beta.txt.
"""

import warnings
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk

import numpy as np
import pandas as pd
from scipy import signal
from scipy.ndimage import gaussian_filter1d


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

THETA_SEARCH_BAND = (4.0, 12.0)
BETA_SEARCH_BAND = (13.0, 30.0)

FEEDBACK_EPOCH = (-1.5, 2.0)
FEEDBACK_BASELINE = (-0.8, -0.1)
FEEDBACK_ANALYSIS = (0.1, 1.0)

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
    """Load a Neuroelectrics .easy file and return usable EEG channels."""
    raw = np.loadtxt(path)

    if raw.ndim != 2 or raw.shape[1] < 6:
        raise ValueError(f"Unexpected .easy shape: {raw.shape}")

    # Layout: EEG channels + 3 accelerometer columns + trigger + Unix timestamp.
    n_eeg = raw.shape[1] - 5
    eeg_nv = raw[:, :n_eeg].astype(float)
    unix_ms = raw[:, -1].astype(float)

    dt_ms = np.median(np.diff(unix_ms))
    srate = 1000.0 / dt_ms

    # Neuroelectrics may write -1 for unavailable channels.
    unavailable = np.mean(eeg_nv == -1, axis=0) >= 0.50
    available = ~unavailable

    if not np.any(available):
        raise RuntimeError("No available EEG channels detected.")

    original_indices = np.flatnonzero(available)
    eeg_nv = eeg_nv[:, available]

    # Treat rare isolated -1 values as missing, then interpolate them.
    eeg_nv[eeg_nv == -1] = np.nan
    eeg_df = pd.DataFrame(eeg_nv).interpolate(axis=0, limit_direction="both")

    if eeg_df.isna().any().any():
        raise RuntimeError("Missing EEG samples remained after interpolation.")

    eeg_uv = eeg_df.to_numpy() * NV_TO_UV
    return eeg_uv, unix_ms, srate, original_indices


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
# TIME-FREQUENCY ANALYSIS
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


def theta_analysis(feedback_epochs, feedback_times, srate, frontal_idx):
    """Estimate the outcome-related theta peak frequency."""
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
# CHANNEL MAPPING / ARTIFACT REPORTING
# =====================================================================


def map_requested_roi(requested_original_idx, available_original_idx):
    """Map requested original channel indices to reduced available-channel indices."""
    available_lookup = {
        original_idx: reduced_idx
        for reduced_idx, original_idx in enumerate(available_original_idx)
    }

    usable = []
    missing = []

    for orig in requested_original_idx:
        if orig in available_lookup:
            usable.append(available_lookup[orig])
        else:
            missing.append(orig)

    return usable, missing


def get_artifact_counts(reject_info, available_original_idx):
    """Convert reduced channel artifact counts back to named original channels."""
    counts = {}

    for reduced_idx, count in reject_info.get("artifact_by_channel", {}).items():
        original_ch = int(available_original_idx[reduced_idx]) + 1
        channel_name = CHANNEL_LABELS.get(original_ch, f"Ch{original_ch}")
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


def append_peak_result(lines, label, peak_hz, peak_db, edge):
    """Append a standard peak-result block to the report."""
    if np.isfinite(peak_hz):
        lines.extend(
            [
                f"{label}: {peak_hz:.2f} Hz",
                f"Peak dB change: {peak_db:.3f} dB",
                f"Peak at band edge: {'YES' if edge else 'NO'}",
            ]
        )
    else:
        lines.append(f"{label}: unavailable")


def append_artifact_breakdown(lines, heading, artifact_counts):
    """Append channel-level artifact counts to the report."""
    lines.append(heading)

    if artifact_counts:
        for channel, count in sorted(artifact_counts.items()):
            lines.append(f"  {channel}: {count} rejected epochs")
    else:
        lines.append("  None")


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

    eeg_uv, unix_ms, srate, available_original_idx = load_easy(eeg_file)

    # Convert configured 1-based original channels to 0-based indices.
    requested_frontal = [ch - 1 for ch in FRONTAL_CHANNELS]

    ref_idx = [
        reduced_idx
        for reduced_idx, original_idx in enumerate(available_original_idx)
        if (original_idx + 1) in REF_CHANNELS
    ]

    eeg_clean = preprocess(eeg_uv, srate, ref_idx=ref_idx)
    reject_idx = ref_idx  # artifact rejection uses scalp channels only

    events = pd.read_csv(behavior_file)

    usable_frontal, missing_frontal = map_requested_roi(
        requested_frontal,
        available_original_idx,
    )

    if missing_frontal:
        warnings.warn(
            "These requested frontal channels are unavailable: "
            + ", ".join(str(i + 1) for i in missing_frontal)
        )

    if not usable_frontal:
        raise RuntimeError(
            "None of the requested frontal channels are recording EEG."
        )

    used_original = [available_original_idx[i] for i in usable_frontal]

    feedback_ms = get_event_times(events, FEEDBACK_EVENT_COL)
    ep_fb, t_fb, rej_fb = epoch_from_unix(
        eeg_clean,
        unix_ms,
        srate,
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
        srate,
        decision_ms,
        DECISION_EPOCH[0],
        DECISION_EPOCH[1],
        reject_uv=EPOCH_REJECT_UV,
        reject_ch_idx=reject_idx,
    )

    theta_peak_hz = np.nan
    theta_peak_db = np.nan
    theta_edge = False
    if len(ep_fb) > 0:
        theta_peak_hz, theta_peak_db, theta_edge = theta_analysis(
            ep_fb,
            t_fb,
            srate,
            usable_frontal,
        )

    beta_peak_hz = np.nan
    beta_peak_db = np.nan
    beta_edge = False
    if len(ep_dec) > 0:
        beta_peak_hz, beta_peak_db, beta_edge = beta_analysis(
            ep_dec,
            t_dec,
            srate,
            usable_frontal,
        )

    feedback_artifacts = get_artifact_counts(rej_fb, available_original_idx)
    decision_artifacts = get_artifact_counts(rej_dec, available_original_idx)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / f"{subject_id}-{session}_pre-stim_theta-beta.txt"

    requested_text = ", ".join(str(ch) for ch in FRONTAL_CHANNELS)
    montage_text = ", ".join(CHANNEL_LABELS.get(ch, f"Ch{ch}") for ch in FRONTAL_CHANNELS)
    used_text = ", ".join(
        f"{i + 1} ({CHANNEL_LABELS.get(i + 1, f'Ch{i + 1}')})"
        for i in used_original
    )

    lines = [
        "THETA / BETA FREQUENCY ESTIMATION",
        "=" * 60,
        "",
        f"Subject ID: {subject_id}",
        f"Session: {session}",
        "",
        "INPUT FILES",
        "-" * 60,
        f"EEG file: {eeg_file.name}",
        f"Behavior file: {behavior_file.name}",
        "",
        "EEG PREPROCESSING",
        "-" * 60,
        f"Sampling rate: {srate:.3f} Hz",
        f"Bandpass: {HIGHPASS:g}-{LOWPASS:g} Hz",
        f"Notch: {NOTCH:g} Hz, Q={NOTCH_Q:g}",
        "Reference: average scalp reference",
        f"Reference channels: {REF_CHANNELS[0]}-{REF_CHANNELS[-1]}",
        "EXT / cheek channel excluded",
        f"Artifact threshold: ±{EPOCH_REJECT_UV:.1f} uV",
        "",
        "FRONTAL ROI",
        "-" * 60,
        f"Requested: channels {requested_text}",
        f"Expected montage: {montage_text}",
        f"Actually used: {used_text}",
        "",
        "OUTCOME THETA",
        "-" * 60,
        f"Locking event: {FEEDBACK_EVENT_COL}",
        f"Epoch: {format_window(FEEDBACK_EPOCH)}",
        f"Baseline: {format_window(FEEDBACK_BASELINE)}",
        f"Analysis window: {format_window(FEEDBACK_ANALYSIS)}",
        f"Frequency search: {format_band(THETA_SEARCH_BAND)}",
        f"Morlet cycles: {N_CYCLES}",
        f"Feedback events with timestamps: {np.isfinite(feedback_ms).sum()}",
        f"Feedback epochs retained: {len(ep_fb)}",
        f"Feedback epochs rejected for artifact: {rej_fb['artifact']}",
        f"Feedback epochs rejected for bounds: {rej_fb['out_of_bounds']}",
        "",
    ]

    append_peak_result(
        lines,
        "THETA PEAK",
        theta_peak_hz,
        theta_peak_db,
        theta_edge,
    )
    lines.append("")
    append_artifact_breakdown(
        lines,
        "Feedback artifact breakdown:",
        feedback_artifacts,
    )

    lines.extend(
        [
            "",
            "DECISION BETA ERD",
            "-" * 60,
            f"Locking event: {DECISION_EVENT_COL}",
            f"Epoch: {format_window(DECISION_EPOCH)}",
            f"Baseline: {format_window(DECISION_BASELINE)}",
            f"Analysis window: {format_window(DECISION_ANALYSIS)}",
            f"Frequency search: {format_band(BETA_SEARCH_BAND)}",
            f"Morlet cycles: {N_CYCLES}",
            f"Decision events with timestamps: {np.isfinite(decision_ms).sum()}",
            f"Decision epochs retained: {len(ep_dec)}",
            f"Decision timestamps missing: {rej_dec['missing_timestamp']}",
            f"Decision epochs rejected for artifact: {rej_dec['artifact']}",
            f"Decision epochs rejected for bounds: {rej_dec['out_of_bounds']}",
            "",
        ]
    )

    append_peak_result(
        lines,
        "BETA ERD PEAK",
        beta_peak_hz,
        beta_peak_db,
        beta_edge,
    )
    lines.append("")
    append_artifact_breakdown(
        lines,
        "Decision artifact breakdown:",
        decision_artifacts,
    )

    lines.extend(["", "INDIVIDUALIZED FREQUENCIES", "=" * 60])
    lines.append(
        f"Theta stimulation frequency: {theta_peak_hz:.2f} Hz"
        if np.isfinite(theta_peak_hz)
        else "Theta stimulation frequency: UNAVAILABLE"
    )
    lines.append(
        f"Beta stimulation frequency: {beta_peak_hz:.2f} Hz"
        if np.isfinite(beta_peak_hz)
        else "Beta stimulation frequency: UNAVAILABLE"
    )
    lines.extend(["", "END OF REPORT"])

    output_path.write_text("\n".join(lines), encoding="utf-8")

    print()
    print("=" * 70)
    print("RESULTS")
    print("=" * 70)
    print(f"Subject: {subject_id}")
    print(f"Session: {session}")
    print(
        f"Outcome theta peak: {theta_peak_hz:.2f} Hz"
        if np.isfinite(theta_peak_hz)
        else "Outcome theta peak: unavailable"
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
