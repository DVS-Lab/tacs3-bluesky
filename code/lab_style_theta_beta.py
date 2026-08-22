#!/usr/bin/env python3
"""
Lab-style individualized theta / beta frequency estimation.

This script follows the core analysis choices in
`individualized_freq_estimation_v3.ipynb`, but uses the task's exact Unix
timestamps instead of estimating an EEG/behavior alignment offset.

Primary outputs
---------------
1. Outcome theta peak frequency:
   - feedback/outcome locked
   - Morlet TFR, 5 cycles
   - theta = 4-8 Hz
   - baseline = -0.8 to -0.1 s relative to outcome onset
   - analysis window = 0.1 to 1.0 s by default
     (set --outcome-end 1.5 to reproduce the older notebook's 0.1-1.5 s window)
   - peak = maximum smoothed dB ERSP across theta frequencies

2. Decision beta ERD peak frequency:
   - response locked using `choice_onset_unix_time`
   - trials with no choice timestamp are skipped (no inferred decision time)
   - Morlet TFR, 5 cycles
   - beta = 13-30 Hz
   - baseline = -1.5 to -1.0 s before response
   - analysis window = -1.0 to -0.1 s before response
   - peak = frequency with the strongest ERD (minimum smoothed dB change)

Preprocessing follows the executable lab notebook:
   - 0.5-45 Hz, 4th-order Butterworth, zero-phase
   - 60 Hz IIR notch, Q=30
   - average reference across scalp EEG channels 1-7 (EXT/cheek excluded)
   - ±200 uV epoch rejection by default
   - linear detrending per epoch / channel

The .easy layout is inferred as:
   EEG channels + 3 accelerometer columns + trigger + Unix timestamp

Example
-------
python lab_style_theta_beta.py \
    --eeg "subject.easy" \
    --events "subject_task-bandit.csv" \
    --output-prefix "subject_run01" \
    --frontal-channels 1,3,5

IMPORTANT
---------
The lab notebook used channels 1=F3, 3=FCz, 5=F4 as the frontal ROI.
If your current montage is different, pass the correct 1-based channel numbers
with --frontal-channels.
"""

import argparse
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import signal
from scipy.ndimage import gaussian_filter1d


# ---------------------------------------------------------------------
# Lab defaults
# ---------------------------------------------------------------------
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


def parse_channels(text):
    """Convert comma-separated 1-based channel numbers to 0-based indices."""
    vals = []
    for item in text.split(","):
        item = item.strip()
        if not item:
            continue
        ch = int(item)
        if ch < 1:
            raise ValueError("Channel numbers must be 1-based positive integers.")
        vals.append(ch - 1)
    if not vals:
        raise ValueError("At least one frontal channel is required.")
    return vals


def load_easy(path):
    raw = np.loadtxt(path)
    if raw.ndim != 2 or raw.shape[1] < 6:
        raise ValueError(f"Unexpected .easy shape: {raw.shape}")

    n_eeg = raw.shape[1] - 5
    eeg_nv = raw[:, :n_eeg].astype(float)
    unix_ms = raw[:, -1].astype(float)

    dt_ms = np.median(np.diff(unix_ms))
    srate = 1000.0 / dt_ms

    # Neuroelectrics may write -1 for channels that are not recording EEG.
    unavailable = np.mean(eeg_nv == -1, axis=0) >= 0.50
    available = ~unavailable

    if not np.any(available):
        raise RuntimeError("No available EEG channels detected.")

    # Keep only available EEG channels for preprocessing / reference.
    original_indices = np.flatnonzero(available)
    eeg_nv = eeg_nv[:, available]

    # Rare isolated -1 values in an otherwise-recording channel are treated
    # as missing and interpolated.
    eeg_nv[eeg_nv == -1] = np.nan
    eeg_df = pd.DataFrame(eeg_nv).interpolate(
        axis=0, limit_direction="both"
    )
    if eeg_df.isna().any().any():
        raise RuntimeError("Missing EEG samples remained after interpolation.")

    eeg_uv = eeg_df.to_numpy() * NV_TO_UV

    return eeg_uv, unix_ms, srate, original_indices, unavailable


def preprocess(eeg_uv, srate, ref_idx=None):
    """Bandpass, notch, average re-reference."""
    out = eeg_uv.copy()
    nyq = srate / 2.0

    b, a = signal.butter(
        4, [HIGHPASS / nyq, LOWPASS / nyq], btype="band"
    )
    out = signal.filtfilt(b, a, out, axis=0)

    if 0 < NOTCH < nyq:
        bn, an = signal.iirnotch(NOTCH / nyq, Q=NOTCH_Q)
        out = signal.filtfilt(bn, an, out, axis=0)

    if ref_idx is None:
        ref_idx = list(range(out.shape[1]))

    # Average reference using scalp EEG channels only
    out -= np.mean(out[:, ref_idx], axis=1, keepdims=True)

    return out


def nearest_sample_index(unix_ms, event_ms):
    """Index of EEG sample nearest an event Unix timestamp."""
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
    reject_uv=200.0,
    reject_ch_idx=None,
):
    """
    Extract event-locked epochs directly from Unix timestamps.

    In addition to rejecting epochs that exceed the amplitude threshold,
    this records which EEG channel(s) caused each rejection.

    Returns
    -------
    epochs : ndarray
        n_epochs x n_times x n_channels
    times : ndarray
        Relative time vector in seconds.
    kept_event_indices : list
        Indices into event_times_ms for retained epochs.
    reject_reason : dict
        Counts plus artifact-by-channel and per-epoch artifact details.
    """
    n_pre = int(round(abs(tmin) * srate))
    n_post = int(round(tmax * srate))
    n_epoch = n_pre + n_post
    times = np.arange(n_epoch) / srate + tmin

    epochs = []
    kept = []

    rejected_artifact = 0
    rejected_bounds = 0
    skipped_missing = 0

    # Number of rejected epochs in which each reduced-data channel exceeded
    # the amplitude threshold.
    artifact_by_channel = {}

    # One row per channel per rejected epoch. This makes it easy to inspect
    # exactly which channel caused a rejection and by how much.
    artifact_details = []

    if reject_ch_idx is None:
        reject_ch_idx = list(range(eeg.shape[1]))

    for i, event_ms in enumerate(event_times_ms):
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

        # ---------------------------------------------------------
        # Artifact rejection + channel diagnostics
        # ---------------------------------------------------------
        if reject_uv is not None:
            channel_max = np.max(
                np.abs(ep[:, reject_ch_idx]),
                axis=0,
            )

            bad_mask = channel_max > reject_uv

            if np.any(bad_mask):
                rejected_artifact += 1

                bad_positions = np.where(bad_mask)[0]

                for pos in bad_positions:
                    reduced_idx = reject_ch_idx[pos]
                    max_uv = float(channel_max[pos])

                    artifact_by_channel[reduced_idx] = (
                        artifact_by_channel.get(reduced_idx, 0) + 1
                    )

                    artifact_details.append({
                        "event_index": int(i),
                        "event_unix_ms": float(event_ms),
                        "reduced_channel_index": int(reduced_idx),
                        "max_abs_uv": max_uv,
                    })

                continue

        # Linear detrend per channel after amplitude rejection,
        # matching the original pipeline ordering.
        for ci in range(ep.shape[1]):
            ep[:, ci] = signal.detrend(ep[:, ci], type="linear")

        epochs.append(ep)
        kept.append(i)

    if epochs:
        epochs = np.stack(epochs)
    else:
        epochs = np.empty((0, n_epoch, eeg.shape[1]))

    reject_reason = {
        "missing_timestamp": skipped_missing,
        "out_of_bounds": rejected_bounds,
        "artifact": rejected_artifact,
        "artifact_by_channel": artifact_by_channel,
        "artifact_details": artifact_details,
    }

    return epochs, times, kept, reject_reason


def morlet_tfr(epochs, srate, freqs, n_cycles=5, ch_idx=None):
    """
    Replicate the notebook's Morlet power calculation:
    average power over selected channels and epochs.
    """
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

        wav = (
            np.exp(2j * np.pi * f * t_wav)
            * np.exp(-(t_wav ** 2) / (2 * sigma_t ** 2))
        )
        wav /= np.sqrt(np.sum(np.abs(wav) ** 2))

        for ci in ch_idx:
            for ei in range(n_ep):
                conv = signal.fftconvolve(
                    epochs[ei, :, ci], wav, mode="same"
                )
                power[fi] += np.abs(conv) ** 2

        power[fi] /= (n_ep * len(ch_idx))

    return power


def find_peak(freqs, spectrum, band, mode="max", smooth_sigma=1.0):
    """Peak after Gaussian smoothing across frequency, matching notebook logic."""
    mask = (freqs >= band[0]) & (freqs <= band[1])
    bf = freqs[mask]
    bs = spectrum[mask]

    if len(bf) == 0:
        return np.nan, np.nan, False

    smoothed = gaussian_filter1d(bs, sigma=smooth_sigma)

    if mode == "max":
        idx = int(np.argmax(smoothed))
    elif mode == "min":
        idx = int(np.argmin(smoothed))
    else:
        raise ValueError("mode must be 'max' or 'min'")

    edge = idx in (0, len(bf) - 1)
    return float(bf[idx]), float(smoothed[idx]), bool(edge)


def map_requested_roi(requested_original_idx, available_original_idx):
    """
    Convert original .easy channel indices to positions in the reduced
    available-channel EEG matrix.
    """
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
        np.mean(tfr[:, baseline_mask], axis=1, keepdims=True),
        1e-30,
    )
    tfr_db = 10 * np.log10(np.maximum(tfr, 1e-30) / baseline_power)

    outcome_mask = (
        (feedback_times >= 0.1)
        & (feedback_times <= outcome_end)
    )
    theta_mask = (
        (THETA_FREQS >= THETA_SEARCH_BAND[0])
        & (THETA_FREQS <= THETA_SEARCH_BAND[1])
    )

    theta_freqs = THETA_FREQS[theta_mask]
    theta_spectrum = np.mean(
        tfr_db[theta_mask][:, outcome_mask], axis=1
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

    return peak_hz, peak_db, edge, spectrum_df


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
        np.mean(tfr[:, baseline_mask], axis=1, keepdims=True),
        1e-30,
    )
    tfr_db = 10 * np.log10(np.maximum(tfr, 1e-30) / baseline_power)

    decision_mask = (
        (decision_times >= DECISION_ANALYSIS[0])
        & (decision_times <= DECISION_ANALYSIS[1])
    )
    beta_mask = (
        (DECISION_FREQS >= BETA_BAND[0])
        & (DECISION_FREQS <= BETA_BAND[1])
    )

    beta_freqs = DECISION_FREQS[beta_mask]
    beta_spectrum = np.mean(
        tfr_db[beta_mask][:, decision_mask], axis=1
    )

    # Strongest ERD = most negative dB value.
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

    return peak_hz, peak_db, edge, spectrum_df



def artifact_breakdown_dataframe(
    phase,
    reject_info,
    available_original_idx,
):
    """
    Convert per-epoch artifact diagnostics into a readable DataFrame.

    One rejected epoch can appear on multiple rows if multiple channels
    exceeded the threshold.
    """
    rows = []

    for item in reject_info.get("artifact_details", []):
        reduced_idx = item["reduced_channel_index"]

        # Map position in the reduced EEG matrix back to the original
        # 1-based .easy channel number.
        original_ch = int(available_original_idx[reduced_idx]) + 1
        channel_name = CHANNEL_LABELS.get(
            original_ch,
            f"Ch{original_ch}",
        )

        rows.append({
            "phase": phase,
            "event_index": item["event_index"],
            "event_unix_ms": item["event_unix_ms"],
            "channel_number": original_ch,
            "channel_name": channel_name,
            "max_abs_uv": item["max_abs_uv"],
        })

    return pd.DataFrame(
        rows,
        columns=[
            "phase",
            "event_index",
            "event_unix_ms",
            "channel_number",
            "channel_name",
            "max_abs_uv",
        ],
    )


def print_artifact_breakdown(
    label,
    reject_info,
    available_original_idx,
):
    """
    Print how many rejected epochs implicated each scalp EEG channel.

    Counts can sum to more than the total number of rejected epochs because
    a single rejected epoch may exceed threshold on multiple channels.
    """
    print(f"\n{label} artifact breakdown:")

    counts = reject_info.get("artifact_by_channel", {})

    if not counts:
        print("  No artifact-rejected epochs.")
        print(f"  Total rejected epochs: {reject_info['artifact']}")
        return

    mapped = []

    for reduced_idx, count in counts.items():
        original_ch = int(available_original_idx[reduced_idx]) + 1
        channel_name = CHANNEL_LABELS.get(
            original_ch,
            f"Ch{original_ch}",
        )
        mapped.append(
            (count, original_ch, channel_name)
        )

    for count, original_ch, channel_name in sorted(
        mapped,
        reverse=True,
    ):
        print(
            f"  {channel_name} "
            f"(channel {original_ch}): "
            f"{count} rejected epochs"
        )

    print(
        f"  Total unique artifact-rejected epochs: "
        f"{reject_info['artifact']}"
    )


def main():
    parser = argparse.ArgumentParser(
        description="Lab-style outcome theta and decision beta peak-frequency estimation."
    )
    parser.add_argument("--eeg", type=Path, required=True)
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument(
        "--output-prefix",
        type=Path,
        required=True,
        help="Prefix for _summary.csv and _spectra.csv outputs",
    )
    parser.add_argument(
        "--frontal-channels",
        default="1,3,5",
        help=(
            "1-based .easy EEG channel numbers for frontal ROI. "
            "Default 1,3,5 matches the lab notebook's F3, FCz, F4."
        ),
    )
    parser.add_argument(
        "--outcome-end",
        type=float,
        default=1.0,
        help=(
            "End of outcome theta analysis window in seconds after feedback. "
            "Default 1.0 = strictly within the 1-s outcome. "
            "Use 1.5 to reproduce the older lab notebook."
        ),
    )
    parser.add_argument(
        "--reject-uv",
        type=float,
        default=EPOCH_REJECT_UV,
        help="Global epoch artifact threshold in microvolts; default 200.",
    )
    args = parser.parse_args()

    requested_frontal = parse_channels(args.frontal_channels)

    eeg_uv, unix_ms, srate, available_original_idx, unavailable = load_easy(args.eeg)


    # Average-reference using scalp EEG electrodes only:
    # 1=F3, 2=Fp1, 3=FCz, 4=FT7, 5=F4, 6=P4, 7=P3.
    # 8=EXT is on the cheek and is excluded from the reference.
    REF_CHANNELS = [1, 2, 3, 4, 5, 6, 7]

    ref_idx = [
        reduced_idx
        for reduced_idx, original_idx in enumerate(available_original_idx)
        if (original_idx + 1) in REF_CHANNELS
    ]

    eeg_clean = preprocess(eeg_uv, srate, ref_idx=ref_idx)
    # Same scalp channels are used for the ±200 uV artifact threshold.
    # Channel 8 = EXT/cheek is excluded.
    reject_idx = ref_idx
    
    events = pd.read_csv(args.events)

    usable_frontal, missing_frontal = map_requested_roi(
        requested_frontal, available_original_idx
    )

    print(f"Sampling rate: {srate:.3f} Hz")
    print(
        "Available EEG channels (1-based): "
        + ", ".join(str(i + 1) for i in available_original_idx)
    )
    print(
        "Requested frontal ROI (1-based): "
        + ", ".join(str(i + 1) for i in requested_frontal)
    )

    if missing_frontal:
        warnings.warn(
            "These requested frontal channels are unavailable in this recording: "
            + ", ".join(str(i + 1) for i in missing_frontal)
        )

    if not usable_frontal:
        raise RuntimeError(
            "None of the requested frontal channels are recording EEG. "
            "Specify the correct montage with --frontal-channels."
        )

    used_original = [available_original_idx[i] for i in usable_frontal]
    print(
        "Frontal channels actually used (1-based): "
        + ", ".join(str(i + 1) for i in used_original)
    )

    # -------------------------------------------------------------
    # Feedback / outcome epochs
    # -------------------------------------------------------------
    if "feedback_onset_unix_time" not in events.columns:
        raise KeyError("CSV is missing feedback_onset_unix_time")

    feedback_ms = pd.to_numeric(
        events["feedback_onset_unix_time"], errors="coerce"
    ).to_numpy(float)

    ep_fb, t_fb, kept_fb, rej_fb = epoch_from_unix(
        eeg_clean,
        unix_ms,
        srate,
        feedback_ms,
        FEEDBACK_EPOCH[0],
        FEEDBACK_EPOCH[1],
        reject_uv=args.reject_uv,
        reject_ch_idx=reject_idx,
    )

    # -------------------------------------------------------------
    # Decision epochs: ACTUAL DECISIONS ONLY
    # -------------------------------------------------------------
    if "choice_onset_unix_time" not in events.columns:
        raise KeyError("CSV is missing choice_onset_unix_time")

    decision_ms = pd.to_numeric(
        events["choice_onset_unix_time"], errors="coerce"
    ).to_numpy(float)

    ep_dec, t_dec, kept_dec, rej_dec = epoch_from_unix(
        eeg_clean,
        unix_ms,
        srate,
        decision_ms,
        DECISION_EPOCH[0],
        DECISION_EPOCH[1],
        reject_uv=args.reject_uv,
        reject_ch_idx=reject_idx,
    )

    # -------------------------------------------------------------
    # Artifact diagnostics
    # -------------------------------------------------------------
    print_artifact_breakdown(
        "Feedback",
        rej_fb,
        available_original_idx,
    )

    print_artifact_breakdown(
        "Decision",
        rej_dec,
        available_original_idx,
    )

    # -------------------------------------------------------------
    # Frequency estimates
    # -------------------------------------------------------------
    theta_peak_hz = np.nan
    theta_peak_db = np.nan
    theta_edge = np.nan
    theta_spec_df = pd.DataFrame(
        columns=["metric", "frequency_hz", "db_change"]
    )

    if len(ep_fb) > 0:
        theta_peak_hz, theta_peak_db, theta_edge, theta_spec_df = theta_analysis(
            ep_fb,
            t_fb,
            srate,
            usable_frontal,
            args.outcome_end,
        )

    beta_peak_hz = np.nan
    beta_peak_db = np.nan
    beta_edge = np.nan
    beta_spec_df = pd.DataFrame(
        columns=["metric", "frequency_hz", "db_change"]
    )

    if len(ep_dec) > 0:
        beta_peak_hz, beta_peak_db, beta_edge, beta_spec_df = beta_analysis(
            ep_dec,
            t_dec,
            srate,
            usable_frontal,
        )

    summary = pd.DataFrame([{
        "eeg_file": args.eeg.name,
        "events_file": args.events.name,
        "sampling_rate_hz": srate,
        "frontal_channels_requested_1based": args.frontal_channels,
        "frontal_channels_used_1based": ",".join(
            str(i + 1) for i in used_original
        ),
        "artifact_threshold_uv": args.reject_uv,
        "outcome_theta_window_s": f"0.1,{args.outcome_end}",
        "n_feedback_events_with_timestamp": int(np.isfinite(feedback_ms).sum()),
        "n_feedback_epochs_kept": len(ep_fb),
        "feedback_rejected_artifact": rej_fb["artifact"],
        "feedback_rejected_bounds": rej_fb["out_of_bounds"],
        "theta_peak_hz": theta_peak_hz,
        "theta_peak_db_change": theta_peak_db,
        "theta_peak_at_band_edge": theta_edge,
        "decision_beta_window_s": "-1.0,-0.1",
        "n_decision_events_with_timestamp": int(np.isfinite(decision_ms).sum()),
        "n_decision_epochs_kept": len(ep_dec),
        "decision_missing_timestamp": rej_dec["missing_timestamp"],
        "decision_rejected_artifact": rej_dec["artifact"],
        "decision_rejected_bounds": rej_dec["out_of_bounds"],
        "beta_erd_peak_hz": beta_peak_hz,
        "beta_erd_peak_db_change": beta_peak_db,
        "beta_peak_at_band_edge": beta_edge,

        # Artifact-rejection counts by scalp channel.
        # A single epoch may be counted for more than one channel.
        "feedback_artifact_F3": rej_fb["artifact_by_channel"].get(
            next(
                (i for i, orig in enumerate(available_original_idx)
                 if orig + 1 == 1),
                -1,
            ),
            0,
        ),
        "feedback_artifact_Fp1": rej_fb["artifact_by_channel"].get(
            next(
                (i for i, orig in enumerate(available_original_idx)
                 if orig + 1 == 2),
                -1,
            ),
            0,
        ),
        "feedback_artifact_FCz": rej_fb["artifact_by_channel"].get(
            next(
                (i for i, orig in enumerate(available_original_idx)
                 if orig + 1 == 3),
                -1,
            ),
            0,
        ),
        "feedback_artifact_FT7": rej_fb["artifact_by_channel"].get(
            next(
                (i for i, orig in enumerate(available_original_idx)
                 if orig + 1 == 4),
                -1,
            ),
            0,
        ),
        "feedback_artifact_F4": rej_fb["artifact_by_channel"].get(
            next(
                (i for i, orig in enumerate(available_original_idx)
                 if orig + 1 == 5),
                -1,
            ),
            0,
        ),
        "feedback_artifact_P4": rej_fb["artifact_by_channel"].get(
            next(
                (i for i, orig in enumerate(available_original_idx)
                 if orig + 1 == 6),
                -1,
            ),
            0,
        ),
        "feedback_artifact_P3": rej_fb["artifact_by_channel"].get(
            next(
                (i for i, orig in enumerate(available_original_idx)
                 if orig + 1 == 7),
                -1,
            ),
            0,
        ),
        "decision_artifact_F3": rej_dec["artifact_by_channel"].get(
            next(
                (i for i, orig in enumerate(available_original_idx)
                 if orig + 1 == 1),
                -1,
            ),
            0,
        ),
        "decision_artifact_Fp1": rej_dec["artifact_by_channel"].get(
            next(
                (i for i, orig in enumerate(available_original_idx)
                 if orig + 1 == 2),
                -1,
            ),
            0,
        ),
        "decision_artifact_FCz": rej_dec["artifact_by_channel"].get(
            next(
                (i for i, orig in enumerate(available_original_idx)
                 if orig + 1 == 3),
                -1,
            ),
            0,
        ),
        "decision_artifact_FT7": rej_dec["artifact_by_channel"].get(
            next(
                (i for i, orig in enumerate(available_original_idx)
                 if orig + 1 == 4),
                -1,
            ),
            0,
        ),
        "decision_artifact_F4": rej_dec["artifact_by_channel"].get(
            next(
                (i for i, orig in enumerate(available_original_idx)
                 if orig + 1 == 5),
                -1,
            ),
            0,
        ),
        "decision_artifact_P4": rej_dec["artifact_by_channel"].get(
            next(
                (i for i, orig in enumerate(available_original_idx)
                 if orig + 1 == 6),
                -1,
            ),
            0,
        ),
        "decision_artifact_P3": rej_dec["artifact_by_channel"].get(
            next(
                (i for i, orig in enumerate(available_original_idx)
                 if orig + 1 == 7),
                -1,
            ),
            0,
        ),
    }])

    spectra = pd.concat(
        [theta_spec_df, beta_spec_df],
        ignore_index=True,
    )

    feedback_artifacts_df = artifact_breakdown_dataframe(
        "feedback",
        rej_fb,
        available_original_idx,
    )
    decision_artifacts_df = artifact_breakdown_dataframe(
        "decision",
        rej_dec,
        available_original_idx,
    )

    artifact_df = pd.concat(
        [feedback_artifacts_df, decision_artifacts_df],
        ignore_index=True,
    )

    prefix = args.output_prefix
    prefix.parent.mkdir(parents=True, exist_ok=True)

    summary_path = Path(str(prefix) + "_summary.csv")
    spectra_path = Path(str(prefix) + "_spectra.csv")
    artifact_path = Path(str(prefix) + "_artifact_rejections.csv")

    summary.to_csv(summary_path, index=False)
    spectra.to_csv(spectra_path, index=False)
    artifact_df.to_csv(artifact_path, index=False)

    print("\n--- Results ---")
    print(f"Feedback epochs kept: {len(ep_fb)}")
    if np.isfinite(theta_peak_hz):
        edge_txt = " [EDGE PEAK]" if bool(theta_edge) else ""
        print(
            f"Outcome theta peak: {theta_peak_hz:.2f} Hz "
            f"({theta_peak_db:.3f} dB){edge_txt}"
        )
    else:
        print("Outcome theta peak: unavailable (no usable feedback epochs)")

    print(f"Actual decision timestamps: {np.isfinite(decision_ms).sum()}")
    print(f"Decision epochs kept: {len(ep_dec)}")
    if np.isfinite(beta_peak_hz):
        edge_txt = " [EDGE PEAK]" if bool(beta_edge) else ""
        print(
            f"Decision beta ERD peak: {beta_peak_hz:.2f} Hz "
            f"({beta_peak_db:.3f} dB){edge_txt}"
        )
    else:
        print(
            "Decision beta ERD peak: unavailable "
            "(no usable response-locked decision epochs)"
        )

    print(f"\nSaved: {summary_path}")
    print(f"Saved: {spectra_path}")
    print(f"Saved: {artifact_path}")


if __name__ == "__main__":
    main()
