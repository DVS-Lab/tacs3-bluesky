#!/usr/bin/env python3
"""
Lab-style individualized theta / beta frequency estimation.

GUI version.

The script:
1. Asks for Subject ID.
2. Asks for Session number (1-3).
3. Automatically finds the matching EEG .easy file.
4. Automatically finds the matching behavioral .csv file.
5. Uses the exact Unix timestamps in the two files to align EEG and behavior.
6. Estimates:
   - Outcome theta peak frequency
   - Decision beta ERD peak frequency
7. Saves a single text report:

       SUBJECT-SESSION_theta-beta.txt

Example:
       1234-2_theta-beta.txt
"""

import argparse
import warnings
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox

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


# =====================================================================
# LAB DEFAULTS
# =====================================================================

HIGHPASS = 0.5
LOWPASS = 45.0
NOTCH = 60.0
NOTCH_Q = 30.0

EPOCH_REJECT_UV = 200.0

THETA_SEARCH_BAND = (4.0, 12.0)
BETA_BAND = (13.0, 30.0)

FEEDBACK_EPOCH = (-1.5, 2.0)
FEEDBACK_BASELINE = (-0.8, -0.1)

DECISION_EPOCH = (-1.5, 0.5)
DECISION_BASELINE = (-1.5, -1.0)
DECISION_ANALYSIS = (-1.0, -0.1)

THETA_FREQS = np.arange(2.0, 15.25, 0.25)
DECISION_FREQS = np.arange(8.0, 35.25, 0.5)

N_CYCLES = 5
SMOOTH_SIGMA = 1.0

NV_TO_UV = 1e-3


# =====================================================================
# CHANNEL LABELS
# =====================================================================

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
    """
    Open GUI asking for subject ID and session number.
    """

    result = {
        "subject_id": None,
        "session": None,
    }

    root = tk.Tk()
    root.title("Theta / Beta Frequency Estimation")
    root.geometry("420x230")
    root.resizable(False, False)

    frame = ttk.Frame(root, padding=20)
    frame.pack(fill="both", expand=True)

    ttk.Label(
        frame,
        text="Subject ID:",
        font=("Arial", 11),
    ).grid(
        row=0,
        column=0,
        sticky="w",
        pady=(0, 10),
    )

    subject_entry = ttk.Entry(
        frame,
        width=30,
    )
    subject_entry.grid(
        row=0,
        column=1,
        pady=(0, 10),
    )

    ttk.Label(
        frame,
        text="Session:",
        font=("Arial", 11),
    ).grid(
        row=1,
        column=0,
        sticky="w",
        pady=(0, 10),
    )

    session_var = tk.StringVar(value="1")

    session_dropdown = ttk.Combobox(
        frame,
        textvariable=session_var,
        values=["1", "2", "3"],
        state="readonly",
        width=27,
    )

    session_dropdown.grid(
        row=1,
        column=1,
        pady=(0, 10),
    )

    def submit():
        subject = subject_entry.get().strip()
        session = session_var.get()

        if not subject:
            messagebox.showerror(
                "Missing Subject ID",
                "Please enter a subject ID.",
            )
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

    button = ttk.Button(
        frame,
        text="Run Analysis",
        command=submit,
    )

    button.grid(
        row=2,
        column=0,
        columnspan=2,
        pady=(20, 0),
    )

    subject_entry.focus()

    root.bind(
        "<Return>",
        lambda event: submit(),
    )

    root.mainloop()

    return result["subject_id"], result["session"]


# =====================================================================
# FILE FINDING
# =====================================================================

def find_input_files(subject_id, session):
    """
    Find the EEG and behavioral files.

    EEG:
        *_1234-2*.easy

    Behavioral:
        sub-1234-2_task-bandit_*.csv
    """

    eeg_pattern = f"*_{subject_id}-{session}*.easy"

    behavior_pattern = (
        f"sub-{subject_id}-{session}_task-bandit_*.csv"
    )

    eeg_matches = sorted(
        STIM_DATA_DIR.glob(eeg_pattern)
    )

    behavior_matches = sorted(
        BEHAVIOR_DATA_DIR.glob(behavior_pattern)
    )

    if not eeg_matches:
        raise FileNotFoundError(
            "No EEG .easy file was found.\n\n"
            f"Directory:\n{STIM_DATA_DIR}\n\n"
            f"Pattern:\n{eeg_pattern}"
        )

    if not behavior_matches:
        raise FileNotFoundError(
            "No behavioral CSV file was found.\n\n"
            f"Directory:\n{BEHAVIOR_DATA_DIR}\n\n"
            f"Pattern:\n{behavior_pattern}"
        )

    # If multiple files exist, use the most recently modified one.
    eeg_file = max(
        eeg_matches,
        key=lambda p: p.stat().st_mtime,
    )

    behavior_file = max(
        behavior_matches,
        key=lambda p: p.stat().st_mtime,
    )

    return eeg_file, behavior_file


# =====================================================================
# CHANNEL PARSING
# =====================================================================

def parse_channels(text):
    """
    Convert comma-separated 1-based channel numbers
    to 0-based indices.
    """

    vals = []

    for item in text.split(","):
        item = item.strip()

        if not item:
            continue

        ch = int(item)

        if ch < 1:
            raise ValueError(
                "Channel numbers must be 1-based positive integers."
            )

        vals.append(ch - 1)

    if not vals:
        raise ValueError(
            "At least one frontal channel is required."
        )

    return vals


# =====================================================================
# LOAD EEG
# =====================================================================

def load_easy(path):

    raw = np.loadtxt(path)

    if raw.ndim != 2 or raw.shape[1] < 6:
        raise ValueError(
            f"Unexpected .easy shape: {raw.shape}"
        )

    # .easy layout:
    #
    # EEG channels
    # + 3 accelerometer columns
    # + trigger
    # + Unix timestamp
    #
    # Therefore last 5 columns are not EEG.

    n_eeg = raw.shape[1] - 5

    eeg_nv = raw[:, :n_eeg].astype(float)

    unix_ms = raw[:, -1].astype(float)

    dt_ms = np.median(np.diff(unix_ms))

    srate = 1000.0 / dt_ms

    # Neuroelectrics may write -1 for unavailable channels.

    unavailable = (
        np.mean(eeg_nv == -1, axis=0) >= 0.50
    )

    available = ~unavailable

    if not np.any(available):
        raise RuntimeError(
            "No available EEG channels detected."
        )

    original_indices = np.flatnonzero(
        available
    )

    eeg_nv = eeg_nv[:, available]

    # Rare isolated -1 values are treated as missing.

    eeg_nv[eeg_nv == -1] = np.nan

    eeg_df = pd.DataFrame(
        eeg_nv
    ).interpolate(
        axis=0,
        limit_direction="both",
    )

    if eeg_df.isna().any().any():
        raise RuntimeError(
            "Missing EEG samples remained after interpolation."
        )

    # Neuroelectrics values are in nV.
    # Convert to uV.

    eeg_uv = (
        eeg_df.to_numpy() * NV_TO_UV
    )

    return (
        eeg_uv,
        unix_ms,
        srate,
        original_indices,
        unavailable,
    )


# =====================================================================
# PREPROCESSING
# =====================================================================

def preprocess(
    eeg_uv,
    srate,
    ref_idx=None,
):
    """
    Bandpass, notch, average reference.
    """

    out = eeg_uv.copy()

    nyq = srate / 2.0

    # -------------------------------------------------------------
    # 0.5-45 Hz Butterworth bandpass
    # -------------------------------------------------------------

    b, a = signal.butter(
        4,
        [
            HIGHPASS / nyq,
            LOWPASS / nyq,
        ],
        btype="band",
    )

    out = signal.filtfilt(
        b,
        a,
        out,
        axis=0,
    )

    # -------------------------------------------------------------
    # 60 Hz notch
    # -------------------------------------------------------------

    if 0 < NOTCH < nyq:

        bn, an = signal.iirnotch(
            NOTCH / nyq,
            Q=NOTCH_Q,
        )

        out = signal.filtfilt(
            bn,
            an,
            out,
            axis=0,
        )

    # -------------------------------------------------------------
    # Average reference
    # -------------------------------------------------------------

    if ref_idx is None:
        ref_idx = list(
            range(out.shape[1])
        )

    out -= np.mean(
        out[:, ref_idx],
        axis=1,
        keepdims=True,
    )

    return out


# =====================================================================
# UNIX TIMESTAMP -> EEG SAMPLE
# =====================================================================

def nearest_sample_index(
    unix_ms,
    event_ms,
):
    """
    Find EEG sample nearest to an event Unix timestamp.
    """

    idx = int(
        np.searchsorted(
            unix_ms,
            event_ms,
        )
    )

    if idx <= 0:
        return 0

    if idx >= len(unix_ms):
        return len(unix_ms) - 1

    before = idx - 1

    if (
        abs(unix_ms[before] - event_ms)
        <= abs(unix_ms[idx] - event_ms)
    ):
        return before

    return idx


# =====================================================================
# EPOCHING
# =====================================================================

def epoch_from_unix(
    eeg,
    unix_ms,
    srate,
    event_times_ms,
    tmin,
    tmax,
    reject_uv=200.0,
    reject_ch_idx=None,
):

    n_pre = int(
        round(abs(tmin) * srate)
    )

    n_post = int(
        round(tmax * srate)
    )

    n_epoch = n_pre + n_post

    times = (
        np.arange(n_epoch) / srate
        + tmin
    )

    epochs = []
    kept = []

    rejected_artifact = 0
    rejected_bounds = 0
    skipped_missing = 0

    artifact_by_channel = {}

    artifact_details = []

    if reject_ch_idx is None:
        reject_ch_idx = list(
            range(eeg.shape[1])
        )

    for i, event_ms in enumerate(
        event_times_ms
    ):

        if not np.isfinite(event_ms):

            skipped_missing += 1
            continue

        center = nearest_sample_index(
            unix_ms,
            event_ms,
        )

        s0 = center - n_pre
        s1 = center + n_post

        if s0 < 0 or s1 > len(eeg):

            rejected_bounds += 1
            continue

        ep = eeg[
            s0:s1
        ].copy()

        if ep.shape[0] != n_epoch:

            rejected_bounds += 1
            continue

        # ---------------------------------------------------------
        # Artifact rejection
        # ---------------------------------------------------------

        if reject_uv is not None:

            channel_max = np.max(
                np.abs(
                    ep[:, reject_ch_idx]
                ),
                axis=0,
            )

            bad_mask = (
                channel_max > reject_uv
            )

            if np.any(bad_mask):

                rejected_artifact += 1

                bad_positions = np.where(
                    bad_mask
                )[0]

                for pos in bad_positions:

                    reduced_idx = (
                        reject_ch_idx[pos]
                    )

                    max_uv = float(
                        channel_max[pos]
                    )

                    artifact_by_channel[
                        reduced_idx
                    ] = (
                        artifact_by_channel.get(
                            reduced_idx,
                            0,
                        )
                        + 1
                    )

                    artifact_details.append({
                        "event_index": int(i),
                        "event_unix_ms": float(
                            event_ms
                        ),
                        "reduced_channel_index": int(
                            reduced_idx
                        ),
                        "max_abs_uv": max_uv,
                    })

                continue

        # ---------------------------------------------------------
        # Linear detrending
        # ---------------------------------------------------------

        for ci in range(
            ep.shape[1]
        ):

            ep[:, ci] = signal.detrend(
                ep[:, ci],
                type="linear",
            )

        epochs.append(ep)
        kept.append(i)

    if epochs:

        epochs = np.stack(
            epochs
        )

    else:

        epochs = np.empty(
            (
                0,
                n_epoch,
                eeg.shape[1],
            )
        )

    reject_reason = {
        "missing_timestamp": skipped_missing,
        "out_of_bounds": rejected_bounds,
        "artifact": rejected_artifact,
        "artifact_by_channel": artifact_by_channel,
        "artifact_details": artifact_details,
    }

    return (
        epochs,
        times,
        kept,
        reject_reason,
    )


# =====================================================================
# MORLET TFR
# =====================================================================

def morlet_tfr(
    epochs,
    srate,
    freqs,
    n_cycles=5,
    ch_idx=None,
):

    if len(epochs) == 0:
        raise ValueError(
            "Cannot compute TFR with zero epochs."
        )

    n_ep, n_times, n_ch = epochs.shape

    if ch_idx is None:
        ch_idx = list(
            range(n_ch)
        )

    if len(ch_idx) == 0:
        raise ValueError(
            "No usable frontal channels were selected."
        )

    power = np.zeros(
        (
            len(freqs),
            n_times,
        ),
        dtype=float,
    )

    for fi, f in enumerate(freqs):

        sigma_t = (
            n_cycles
            / (2 * np.pi * f)
        )

        hw = int(
            np.ceil(
                3.5
                * sigma_t
                * srate
            )
        )

        t_wav = (
            np.arange(
                -hw,
                hw + 1,
            )
            / srate
        )

        wav = (
            np.exp(
                2j
                * np.pi
                * f
                * t_wav
            )
            * np.exp(
                -(t_wav ** 2)
                / (
                    2
                    * sigma_t ** 2
                )
            )
        )

        wav /= np.sqrt(
            np.sum(
                np.abs(wav) ** 2
            )
        )

        for ci in ch_idx:

            for ei in range(n_ep):

                conv = signal.fftconvolve(
                    epochs[
                        ei,
                        :,
                        ci
                    ],
                    wav,
                    mode="same",
                )

                power[fi] += (
                    np.abs(conv) ** 2
                )

        power[fi] /= (
            n_ep
            * len(ch_idx)
        )

    return power


# =====================================================================
# PEAK FINDING
# =====================================================================

def find_peak(
    freqs,
    spectrum,
    band,
    mode="max",
    smooth_sigma=1.0,
):

    mask = (
        (freqs >= band[0])
        & (freqs <= band[1])
    )

    bf = freqs[mask]
    bs = spectrum[mask]

    if len(bf) == 0:
        return (
            np.nan,
            np.nan,
            False,
        )

    smoothed = gaussian_filter1d(
        bs,
        sigma=smooth_sigma,
    )

    if mode == "max":

        idx = int(
            np.argmax(smoothed)
        )

    elif mode == "min":

        idx = int(
            np.argmin(smoothed)
        )

    else:

        raise ValueError(
            "mode must be 'max' or 'min'"
        )

    edge = (
        idx == 0
        or idx == len(bf) - 1
    )

    return (
        float(bf[idx]),
        float(smoothed[idx]),
        bool(edge),
    )


# =====================================================================
# ROI MAPPING
# =====================================================================

def map_requested_roi(
    requested_original_idx,
    available_original_idx,
):

    available_lookup = {
        original_idx: reduced_idx
        for reduced_idx, original_idx
        in enumerate(
            available_original_idx
        )
    }

    usable = []
    missing = []

    for orig in requested_original_idx:

        if orig in available_lookup:

            usable.append(
                available_lookup[orig]
            )

        else:

            missing.append(orig)

    return usable, missing


# =====================================================================
# THETA ANALYSIS
# =====================================================================

def theta_analysis(
    feedback_epochs,
    feedback_times,
    srate,
    frontal_idx,
    outcome_end,
):

    tfr = morlet_tfr(
        feedback_epochs,
        srate,
        THETA_FREQS,
        n_cycles=N_CYCLES,
        ch_idx=frontal_idx,
    )

    baseline_mask = (
        (feedback_times >= FEEDBACK_BASELINE[0])
        & (feedback_times <= FEEDBACK_BASELINE[1])
    )

    baseline_power = np.maximum(
        np.mean(
            tfr[:, baseline_mask],
            axis=1,
            keepdims=True,
        ),
        1e-30,
    )

    tfr_db = (
        10
        * np.log10(
            np.maximum(
                tfr,
                1e-30,
            )
            / baseline_power
        )
    )

    outcome_mask = (
        (feedback_times >= 0.1)
        & (feedback_times <= outcome_end)
    )

    theta_mask = (
        (THETA_FREQS >= THETA_SEARCH_BAND[0])
        & (THETA_FREQS <= THETA_SEARCH_BAND[1])
    )

    theta_freqs = THETA_FREQS[
        theta_mask
    ]

    theta_spectrum = np.mean(
        tfr_db[
            theta_mask
        ][:, outcome_mask],
        axis=1,
    )

    peak_hz, peak_db, edge = find_peak(
        theta_freqs,
        theta_spectrum,
        THETA_SEARCH_BAND,
        mode="max",
        smooth_sigma=SMOOTH_SIGMA,
    )

    spectrum_df = pd.DataFrame({
        "metric": "outcome_theta",
        "frequency_hz": theta_freqs,
        "db_change": theta_spectrum,
    })

    return (
        peak_hz,
        peak_db,
        edge,
        spectrum_df,
    )


# =====================================================================
# BETA ANALYSIS
# =====================================================================

def beta_analysis(
    decision_epochs,
    decision_times,
    srate,
    frontal_idx,
):

    tfr = morlet_tfr(
        decision_epochs,
        srate,
        DECISION_FREQS,
        n_cycles=N_CYCLES,
        ch_idx=frontal_idx,
    )

    baseline_mask = (
        (decision_times >= DECISION_BASELINE[0])
        & (decision_times <= DECISION_BASELINE[1])
    )

    baseline_power = np.maximum(
        np.mean(
            tfr[:, baseline_mask],
            axis=1,
            keepdims=True,
        ),
        1e-30,
    )

    tfr_db = (
        10
        * np.log10(
            np.maximum(
                tfr,
                1e-30,
            )
            / baseline_power
        )
    )

    decision_mask = (
        (decision_times >= DECISION_ANALYSIS[0])
        & (decision_times <= DECISION_ANALYSIS[1])
    )

    beta_mask = (
        (DECISION_FREQS >= BETA_BAND[0])
        & (DECISION_FREQS <= BETA_BAND[1])
    )

    beta_freqs = DECISION_FREQS[
        beta_mask
    ]

    beta_spectrum = np.mean(
        tfr_db[
            beta_mask
        ][:, decision_mask],
        axis=1,
    )

    # Strongest ERD = most negative dB.

    peak_hz, peak_db, edge = find_peak(
        beta_freqs,
        beta_spectrum,
        BETA_BAND,
        mode="min",
        smooth_sigma=SMOOTH_SIGMA,
    )

    spectrum_df = pd.DataFrame({
        "metric": "decision_beta_erd",
        "frequency_hz": beta_freqs,
        "db_change": beta_spectrum,
    })

    return (
        peak_hz,
        peak_db,
        edge,
        spectrum_df,
    )


# =====================================================================
# ARTIFACT REPORTING
# =====================================================================

def get_artifact_counts(
    reject_info,
    available_original_idx,
):

    counts = {}

    for reduced_idx, count in (
        reject_info
        .get(
            "artifact_by_channel",
            {},
        )
        .items()
    ):

        original_ch = (
            int(
                available_original_idx[
                    reduced_idx
                ]
            )
            + 1
        )

        channel_name = CHANNEL_LABELS.get(
            original_ch,
            f"Ch{original_ch}",
        )

        counts[
            channel_name
        ] = count

    return counts


# =====================================================================
# MAIN ANALYSIS
# =====================================================================

def run_analysis(
    subject_id,
    session,
):

    # -------------------------------------------------------------
    # Find files
    # -------------------------------------------------------------

    eeg_file, behavior_file = (
        find_input_files(
            subject_id,
            session,
        )
    )

    print()
    print("=" * 70)
    print("THETA / BETA FREQUENCY ESTIMATION")
    print("=" * 70)

    print(
        f"Subject: {subject_id}"
    )

    print(
        f"Session: {session}"
    )

    print(
        f"\nEEG file:\n{eeg_file}"
    )

    print(
        f"\nBehavior file:\n{behavior_file}"
    )

    # -------------------------------------------------------------
    # Load EEG
    # -------------------------------------------------------------

    (
        eeg_uv,
        unix_ms,
        srate,
        available_original_idx,
        unavailable,
    ) = load_easy(
        eeg_file
    )

    # -------------------------------------------------------------
    # Frontal channels
    #
    # Default:
    # 1 = F3
    # 3 = FCz
    # 5 = F4
    # -------------------------------------------------------------

    requested_frontal = parse_channels(
        "1,3,5"
    )

    # -------------------------------------------------------------
    # Average reference
    #
    # 1=F3
    # 2=Fp1
    # 3=FCz
    # 4=FT7
    # 5=F4
    # 6=P4
    # 7=P3
    #
    # 8=EXT is excluded.
    # -------------------------------------------------------------

    REF_CHANNELS = [
        1,
        2,
        3,
        4,
        5,
        6,
        7,
    ]

    ref_idx = [
        reduced_idx
        for reduced_idx, original_idx
        in enumerate(
            available_original_idx
        )
        if (
            original_idx + 1
        ) in REF_CHANNELS
    ]

    eeg_clean = preprocess(
        eeg_uv,
        srate,
        ref_idx=ref_idx,
    )

    # Artifact rejection also uses
    # scalp channels only.

    reject_idx = ref_idx

    # -------------------------------------------------------------
    # Load behavioral data
    # -------------------------------------------------------------

    events = pd.read_csv(
        behavior_file
    )

    # -------------------------------------------------------------
    # Determine usable frontal channels
    # -------------------------------------------------------------

    usable_frontal, missing_frontal = (
        map_requested_roi(
            requested_frontal,
            available_original_idx,
        )
    )

    if missing_frontal:

        warnings.warn(
            "These requested frontal channels "
            "are unavailable: "
            + ", ".join(
                str(i + 1)
                for i in missing_frontal
            )
        )

    if not usable_frontal:

        raise RuntimeError(
            "None of the requested frontal "
            "channels are recording EEG."
        )

    used_original = [
        available_original_idx[i]
        for i in usable_frontal
    ]

    # -------------------------------------------------------------
    # Feedback / outcome timestamps
    # -------------------------------------------------------------

    if (
        "feedback_onset_unix_time"
        not in events.columns
    ):

        raise KeyError(
            "CSV is missing "
            "feedback_onset_unix_time"
        )

    feedback_ms = pd.to_numeric(
        events[
            "feedback_onset_unix_time"
        ],
        errors="coerce",
    ).to_numpy(float)

    # -------------------------------------------------------------
    # Feedback epochs
    # -------------------------------------------------------------

    ep_fb, t_fb, kept_fb, rej_fb = (
        epoch_from_unix(
            eeg_clean,
            unix_ms,
            srate,
            feedback_ms,
            FEEDBACK_EPOCH[0],
            FEEDBACK_EPOCH[1],
            reject_uv=EPOCH_REJECT_UV,
            reject_ch_idx=reject_idx,
        )
    )

    # -------------------------------------------------------------
    # Decision timestamps
    # -------------------------------------------------------------

    if (
        "choice_onset_unix_time"
        not in events.columns
    ):

        raise KeyError(
            "CSV is missing "
            "choice_onset_unix_time"
        )

    decision_ms = pd.to_numeric(
        events[
            "choice_onset_unix_time"
        ],
        errors="coerce",
    ).to_numpy(float)

    # -------------------------------------------------------------
    # Decision epochs
    # -------------------------------------------------------------

    ep_dec, t_dec, kept_dec, rej_dec = (
        epoch_from_unix(
            eeg_clean,
            unix_ms,
            srate,
            decision_ms,
            DECISION_EPOCH[0],
            DECISION_EPOCH[1],
            reject_uv=EPOCH_REJECT_UV,
            reject_ch_idx=reject_idx,
        )
    )

    # -------------------------------------------------------------
    # Theta
    # -------------------------------------------------------------

    theta_peak_hz = np.nan
    theta_peak_db = np.nan
    theta_edge = False

    if len(ep_fb) > 0:

        (
            theta_peak_hz,
            theta_peak_db,
            theta_edge,
            theta_spec_df,
        ) = theta_analysis(
            ep_fb,
            t_fb,
            srate,
            usable_frontal,
            1.0,
        )

    # -------------------------------------------------------------
    # Beta
    # -------------------------------------------------------------

    beta_peak_hz = np.nan
    beta_peak_db = np.nan
    beta_edge = False

    if len(ep_dec) > 0:

        (
            beta_peak_hz,
            beta_peak_db,
            beta_edge,
            beta_spec_df,
        ) = beta_analysis(
            ep_dec,
            t_dec,
            srate,
            usable_frontal,
        )

    # -------------------------------------------------------------
    # Artifact information
    # -------------------------------------------------------------

    feedback_artifacts = (
        get_artifact_counts(
            rej_fb,
            available_original_idx,
        )
    )

    decision_artifacts = (
        get_artifact_counts(
            rej_dec,
            available_original_idx,
        )
    )

    # -------------------------------------------------------------
    # Output filename
    # -------------------------------------------------------------

    output_filename = (
        f"{subject_id}-{session}_pre-stim_theta-beta.txt"
    )

    output_path = (
        OUTPUT_DIR
        / output_filename
    )

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    # -------------------------------------------------------------
    # Create text report
    # -------------------------------------------------------------

    lines = []

    lines.append(
        "THETA / BETA FREQUENCY ESTIMATION"
    )

    lines.append(
        "=" * 60
    )

    lines.append("")

    lines.append(
        f"Subject ID: {subject_id}"
    )

    lines.append(
        f"Session: {session}"
    )

    lines.append("")

    lines.append(
        "INPUT FILES"
    )

    lines.append(
        "-" * 60
    )

    lines.append(
        f"EEG file: {eeg_file.name}"
    )

    lines.append(
        f"Behavior file: {behavior_file.name}"
    )

    lines.append("")

    lines.append(
        "EEG PREPROCESSING"
    )

    lines.append(
        "-" * 60
    )

    lines.append(
        f"Sampling rate: {srate:.3f} Hz"
    )

    lines.append(
        f"Bandpass: {HIGHPASS}-{LOWPASS} Hz"
    )

    lines.append(
        f"Notch: {NOTCH} Hz, Q={NOTCH_Q}"
    )

    lines.append(
        "Reference: average scalp reference"
    )

    lines.append(
        "Reference channels: 1-7"
    )

    lines.append(
        "EXT / cheek channel excluded"
    )

    lines.append(
        f"Artifact threshold: ±{EPOCH_REJECT_UV:.1f} uV"
    )

    lines.append("")

    lines.append(
        "FRONTAL ROI"
    )

    lines.append(
        "-" * 60
    )

    lines.append(
        "Requested: channels 1, 3, 5"
    )

    lines.append(
        "Expected montage: F3, FCz, F4"
    )

    lines.append(
        "Actually used: "
        + ", ".join(
            f"{i + 1} ({CHANNEL_LABELS.get(i + 1, f'Ch{i + 1}')})"
            for i in used_original
        )
    )

    lines.append("")

    # -------------------------------------------------------------
    # Theta results
    # -------------------------------------------------------------

    lines.append(
        "OUTCOME THETA"
    )

    lines.append(
        "-" * 60
    )

    lines.append(
        "Locking event: feedback_onset_unix_time"
    )

    lines.append(
        "Epoch: -1.5 to +2.0 s"
    )

    lines.append(
        "Baseline: -0.8 to -0.1 s"
    )

    lines.append(
        "Analysis window: +0.1 to +1.0 s"
    )

    lines.append(
        "Frequency search: 4-12 Hz"
    )

    lines.append(
        "Morlet cycles: 5"
    )

    lines.append(
        f"Feedback events with timestamps: "
        f"{np.isfinite(feedback_ms).sum()}"
    )

    lines.append(
        f"Feedback epochs retained: "
        f"{len(ep_fb)}"
    )

    lines.append(
        f"Feedback epochs rejected for artifact: "
        f"{rej_fb['artifact']}"
    )

    lines.append(
        f"Feedback epochs rejected for bounds: "
        f"{rej_fb['out_of_bounds']}"
    )

    lines.append("")

    if np.isfinite(theta_peak_hz):

        lines.append(
            f"THETA PEAK: {theta_peak_hz:.2f} Hz"
        )

        lines.append(
            f"Peak dB change: {theta_peak_db:.3f} dB"
        )

        lines.append(
            "Peak at band edge: "
            + (
                "YES"
                if theta_edge
                else "NO"
            )
        )

    else:

        lines.append(
            "THETA PEAK: unavailable"
        )

    lines.append("")

    lines.append(
        "Feedback artifact breakdown:"
    )

    if feedback_artifacts:

        for channel, count in sorted(
            feedback_artifacts.items()
        ):

            lines.append(
                f"  {channel}: "
                f"{count} rejected epochs"
            )

    else:

        lines.append(
            "  None"
        )

    lines.append("")

    # -------------------------------------------------------------
    # Beta results
    # -------------------------------------------------------------

    lines.append(
        "DECISION BETA ERD"
    )

    lines.append(
        "-" * 60
    )

    lines.append(
        "Locking event: choice_onset_unix_time"
    )

    lines.append(
        "Epoch: -1.5 to +0.5 s"
    )

    lines.append(
        "Baseline: -1.5 to -1.0 s"
    )

    lines.append(
        "Analysis window: -1.0 to -0.1 s"
    )

    lines.append(
        "Frequency search: 13-30 Hz"
    )

    lines.append(
        "Morlet cycles: 5"
    )

    lines.append(
        f"Decision events with timestamps: "
        f"{np.isfinite(decision_ms).sum()}"
    )

    lines.append(
        f"Decision epochs retained: "
        f"{len(ep_dec)}"
    )

    lines.append(
        f"Decision timestamps missing: "
        f"{rej_dec['missing_timestamp']}"
    )

    lines.append(
        f"Decision epochs rejected for artifact: "
        f"{rej_dec['artifact']}"
    )

    lines.append(
        f"Decision epochs rejected for bounds: "
        f"{rej_dec['out_of_bounds']}"
    )

    lines.append("")

    if np.isfinite(beta_peak_hz):

        lines.append(
            f"BETA ERD PEAK: "
            f"{beta_peak_hz:.2f} Hz"
        )

        lines.append(
            f"Peak dB change: "
            f"{beta_peak_db:.3f} dB"
        )

        lines.append(
            "Peak at band edge: "
            + (
                "YES"
                if beta_edge
                else "NO"
            )
        )

    else:

        lines.append(
            "BETA ERD PEAK: unavailable"
        )

    lines.append("")

    lines.append(
        "Decision artifact breakdown:"
    )

    if decision_artifacts:

        for channel, count in sorted(
            decision_artifacts.items()
        ):

            lines.append(
                f"  {channel}: "
                f"{count} rejected epochs"
            )

    else:

        lines.append(
            "  None"
        )

    lines.append("")

    # -------------------------------------------------------------
    # Final recommended frequencies
    # -------------------------------------------------------------

    lines.append(
        "INDIVIDUALIZED FREQUENCIES"
    )

    lines.append(
        "=" * 60
    )

    if np.isfinite(theta_peak_hz):

        lines.append(
            f"Theta stimulation frequency: "
            f"{theta_peak_hz:.2f} Hz"
        )

    else:

        lines.append(
            "Theta stimulation frequency: "
            "UNAVAILABLE"
        )

    if np.isfinite(beta_peak_hz):

        lines.append(
            f"Beta stimulation frequency: "
            f"{beta_peak_hz:.2f} Hz"
        )

    else:

        lines.append(
            "Beta stimulation frequency: "
            "UNAVAILABLE"
        )

    lines.append("")

    lines.append(
        "END OF REPORT"
    )

    # -------------------------------------------------------------
    # Write file
    # -------------------------------------------------------------

    with open(
        output_path,
        "w",
        encoding="utf-8",
    ) as f:

        f.write(
            "\n".join(lines)
        )

    # -------------------------------------------------------------
    # Console output
    # -------------------------------------------------------------

    print()
    print("=" * 70)
    print("RESULTS")
    print("=" * 70)

    print(
        f"Subject: {subject_id}"
    )

    print(
        f"Session: {session}"
    )

    if np.isfinite(theta_peak_hz):

        print(
            f"Outcome theta peak: "
            f"{theta_peak_hz:.2f} Hz"
        )

    else:

        print(
            "Outcome theta peak: unavailable"
        )

    if np.isfinite(beta_peak_hz):

        print(
            f"Decision beta ERD peak: "
            f"{beta_peak_hz:.2f} Hz"
        )

    else:

        print(
            "Decision beta ERD peak: unavailable"
        )

    print()
    print(
        f"Saved: {output_path}"
    )

    return output_path


# =====================================================================
# GUI ERROR/SUCCESS WRAPPER
# =====================================================================

def main():

    # -------------------------------------------------------------
    # Ask for subject/session
    # -------------------------------------------------------------

    subject_id, session = (
        get_subject_and_session()
    )

    if subject_id is None:
        print(
            "Analysis cancelled."
        )
        return

    try:

        output_path = run_analysis(
            subject_id,
            session,
        )

    except Exception as e:

        # Show the error in a GUI dialog.

        root = tk.Tk()
        root.withdraw()

        messagebox.showerror(
            "Analysis Error",
            str(e),
        )

        root.destroy()

        raise

    # -------------------------------------------------------------
    # Success dialog
    # -------------------------------------------------------------

    root = tk.Tk()
    root.withdraw()

    messagebox.showinfo(
        "Analysis Complete",
        "Theta/beta analysis completed.\n\n"
        f"Output:\n{output_path}",
    )

    root.destroy()


# =====================================================================
# RUN
# =====================================================================

if __name__ == "__main__":
    main()