#!/usr/bin/env python3
"""
Feedback-locked Gain vs Loss ERP plot from a behavioral CSV and ANT-style .easy file.

Expected inputs:
  CSV:  sub-<subject>-<session>_task-<task>_<pre-stim|post-stim>_<timestamp>.csv
  EASY: <timestamp>_<subject>-<session>_<Task>_<pre-stim|post-stim>.easy

The .easy file supplied for the example has 12 tab-separated columns:
  columns 0-7: signal channels (assumed EEG channels; verify your montage)
  columns 8-10: auxiliary channels
  column 11: all zeros
  column 12: Unix timestamp in milliseconds

This script deliberately labels amplitude in recording units unless you provide
the acquisition-system conversion factor using --uv-per-unit. It does not guess
the electrode names or ADC-to-microvolt scaling.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


# Timing, in milliseconds relative to feedback onset.
FEEDBACK_START_MS = 0.0
FEEDBACK_END_MS = 700.0
BASELINE_START_MS = 700.0
BASELINE_END_MS = 1300.0

# Display-only plot settings. These do not alter trial data or statistics.
DISPLAY_SMOOTHING_MS = 15.0
MEAN_LINEWIDTH = 1.6
SEM_BAND_ALPHA = 0.055

# These are the signal columns in the example .easy file. Confirm this against
# your acquisition montage before interpreting the channel as a named electrode.
DEFAULT_CHANNEL = 0
TIMESTAMP_COLUMN = -1


def find_matching_files(csv_dir: Path, easy_dir: Path, subject: str,
                        session: str, task: str, phase: str) -> tuple[Path, Path]:
    """Find matching CSV and .easy files in their separate directories."""
    if not csv_dir.is_dir():
        raise FileNotFoundError(f"CSV directory does not exist: {csv_dir}")
    if not easy_dir.is_dir():
        raise FileNotFoundError(f"EASY directory does not exist: {easy_dir}")

    csv_candidates = []
    easy_candidates = []

    csv_re = re.compile(
        rf"^sub-{re.escape(subject)}-{re.escape(session)}_task-"
        rf"{re.escape(task)}_{re.escape(phase)}_.*\.csv$",
        re.IGNORECASE,
    )
    easy_re = re.compile(
        rf"^\d+_{re.escape(subject)}-{re.escape(session)}_"
        rf"{re.escape(task)}_{re.escape(phase)}\.easy$",
        re.IGNORECASE,
    )

    for path in csv_dir.iterdir():
        if path.is_file() and csv_re.match(path.name):
            csv_candidates.append(path)

    for path in easy_dir.iterdir():
        if path.is_file() and easy_re.match(path.name):
            easy_candidates.append(path)

    if len(csv_candidates) != 1 or len(easy_candidates) != 1:
        raise FileNotFoundError(
            "Could not identify exactly one matching pair.\n"
            f"CSV matches: {[p.name for p in csv_candidates]}\n"
            f"EASY matches: {[p.name for p in easy_candidates]}\n"
            "Use --csv and --easy to specify the files explicitly."
        )
    return csv_candidates[0], easy_candidates[0]


def load_easy(path: Path) -> tuple[np.ndarray, np.ndarray, float]:
    """Load tab-separated signal values and final-column Unix-ms timestamps."""
    data = np.loadtxt(path, delimiter="\t", dtype=np.float64)
    if data.ndim != 2 or data.shape[1] < 3:
        raise ValueError(f"Unexpected .easy structure: {data.shape}")

    timestamps_ms = data[:, TIMESTAMP_COLUMN]
    signals = data[:, :-1]

    if not np.all(np.diff(timestamps_ms) > 0):
        raise ValueError("The .easy timestamps are not strictly increasing.")

    sample_intervals_ms = np.diff(timestamps_ms)
    median_interval_ms = float(np.median(sample_intervals_ms))
    sampling_rate_hz = 1000.0 / median_interval_ms

    # Warn rather than silently accepting a badly irregular time base.
    if not np.allclose(sample_intervals_ms, median_interval_ms, atol=0.05):
        print("WARNING: .easy timestamps are not uniformly spaced; "
              "epochs will be interpolated onto a uniform time grid.")

    return signals, timestamps_ms, sampling_rate_hz


def epoch_trials(signals: np.ndarray, timestamps_ms: np.ndarray,
                 event_times_ms: np.ndarray, channel: int,
                 sampling_rate_hz: float) -> tuple[np.ndarray, np.ndarray]:
    """
    Interpolate each event onto a common 0..1300 ms time axis.
    Baseline-correct each trial using the post-feedback 700..1300 ms interval.
    Return baseline-corrected 0..700 ms trials and the feedback time axis.
    """
    if channel < 0 or channel >= signals.shape[1]:
        raise ValueError(
            f"Channel {channel} is out of range. The file has "
            f"{signals.shape[1]} signal columns (0 through {signals.shape[1]-1})."
        )

    step_ms = 1000.0 / sampling_rate_hz
    full_time_ms = np.arange(
        FEEDBACK_START_MS, BASELINE_END_MS + step_ms / 2, step_ms
    )
    feedback_mask = full_time_ms <= FEEDBACK_END_MS + 1e-9
    baseline_mask = (
        (full_time_ms >= BASELINE_START_MS)
        & (full_time_ms <= BASELINE_END_MS)
    )

    epochs = []
    rejected = 0
    channel_data = signals[:, channel]

    for event_ms in event_times_ms:
        relative_sample_times = timestamps_ms - event_ms
        if (relative_sample_times[0] > full_time_ms[0]
                or relative_sample_times[-1] < full_time_ms[-1]):
            rejected += 1
            continue

        epoch = np.interp(
            full_time_ms, relative_sample_times, channel_data
        )
        baseline_value = np.mean(epoch[baseline_mask])
        epoch = epoch - baseline_value
        epochs.append(epoch[feedback_mask])

    if rejected:
        print(f"WARNING: excluded {rejected} event(s) because the recording "
              "did not contain the complete 0..1300 ms epoch.")

    if not epochs:
        raise RuntimeError("No complete feedback epochs could be extracted.")

    return np.asarray(epochs), full_time_ms[feedback_mask]


def mean_and_sem(trials: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    mean = np.mean(trials, axis=0)
    if trials.shape[0] < 2:
        sem = np.full_like(mean, np.nan, dtype=float)
    else:
        sem = np.std(trials, axis=0, ddof=1) / np.sqrt(trials.shape[0])
    return mean, sem



def smooth_for_display(values: np.ndarray, window_ms: float,
                       sample_interval_ms: float) -> np.ndarray:
    """
    Smooth a plotted trace only; the input trial data and statistical
    calculations remain unchanged. Uses a centered moving-average window.
    """
    window_samples = max(1, int(round(window_ms / sample_interval_ms)))
    if window_samples <= 1:
        return values.copy()

    # Use an odd window so the moving average is centered on each sample.
    if window_samples % 2 == 0:
        window_samples += 1

    kernel = np.ones(window_samples, dtype=float) / window_samples
    pad = window_samples // 2
    padded = np.pad(values, (pad, pad), mode="edge")
    return np.convolve(padded, kernel, mode="valid")


def discover_bandit_file_pairs(csv_dir: Path, easy_dir: Path, task: str,
                               phase: str) -> list[tuple[str, str, Path, Path]]:
    """Find matching CSV/.easy files for every subject and session."""
    if not csv_dir.is_dir():
        raise FileNotFoundError(f"CSV directory does not exist: {csv_dir}")
    if not easy_dir.is_dir():
        raise FileNotFoundError(f"EASY directory does not exist: {easy_dir}")

    csv_re = re.compile(
        r"^sub-(?P<subject>.+?)-(?P<session>[^_]+)_task-"
        r"(?P<task>[^_]+)_(?P<phase>pre-stim|post-stim)_(?P<timestamp>.+)\.csv$",
        re.IGNORECASE,
    )
    easy_re = re.compile(
        r"^(?P<timestamp>\d+)_(?P<subject>.+?)-(?P<session>[^_]+)_"
        r"(?P<task>[^_]+)_(?P<phase>pre-stim|post-stim)\.easy$",
        re.IGNORECASE,
    )

    csv_by_key: dict[tuple[str, str, str, str], list[tuple[str, Path]]] = {}
    easy_by_key: dict[tuple[str, str, str, str], list[tuple[str, Path]]] = {}

    for path in csv_dir.iterdir():
        if not path.is_file():
            continue
        match = csv_re.match(path.name)
        if not match:
            continue
        fields = match.groupdict()
        if fields["task"].lower() != task.lower() or fields["phase"].lower() != phase.lower():
            continue
        key = (fields["subject"].lower(), fields["session"].lower(),
               fields["task"].lower(), fields["phase"].lower())
        csv_by_key.setdefault(key, []).append((fields["timestamp"], path))

    for path in easy_dir.iterdir():
        if not path.is_file():
            continue
        match = easy_re.match(path.name)
        if not match:
            continue
        fields = match.groupdict()
        if fields["task"].lower() != task.lower() or fields["phase"].lower() != phase.lower():
            continue
        key = (fields["subject"].lower(), fields["session"].lower(),
               fields["task"].lower(), fields["phase"].lower())
        easy_by_key.setdefault(key, []).append((fields["timestamp"], path))

    pairs = []
    all_keys = sorted(set(csv_by_key) | set(easy_by_key))
    for key in all_keys:
        csv_files = csv_by_key.get(key, [])
        easy_files = easy_by_key.get(key, [])
        subject, session, _, _ = key

        if len(csv_files) == 1 and len(easy_files) == 1:
            pairs.append((subject, session, csv_files[0][1], easy_files[0][1]))
            continue

        # If there are multiple recordings for a subject/session, pair files
        # whose timestamp strings match exactly (or contain one another).
        matched = []
        for csv_stamp, csv_path in csv_files:
            candidates = [
                (easy_stamp, easy_path) for easy_stamp, easy_path in easy_files
                if csv_stamp == easy_stamp or csv_stamp in easy_stamp or easy_stamp in csv_stamp
            ]
            if len(candidates) == 1:
                matched.append((subject, session, csv_path, candidates[0][1]))

        if matched:
            pairs.extend(matched)
        else:
            print(
                f"WARNING: skipping subject {subject}, session {session}: "
                f"found {len(csv_files)} CSV file(s) and {len(easy_files)} EASY file(s), "
                "but could not identify an unambiguous pair."
            )

    if not pairs:
        raise FileNotFoundError(
            f"No matching task-{task} {phase} CSV/.easy pairs were found in the supplied folders."
        )

    # Avoid accidentally processing the same file pair more than once.
    unique = {}
    for subject, session, csv_path, easy_path in pairs:
        unique[(str(csv_path.resolve()), str(easy_path.resolve()))] = (
            subject, session, csv_path, easy_path
        )
    return list(unique.values())


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Plot group-average feedback-locked Gain and Loss waveforms across all participants and sessions."
    )
    parser.add_argument("--csv", type=Path, help="Optional single behavioral CSV (must also provide --easy).")
    parser.add_argument("--easy", type=Path, help="Optional single neural .easy file (must also provide --csv).")
    parser.add_argument(
        "--csv-dir", type=Path,
        default=Path(r"C:\Users\Public\LAB PROJECTS\Smith-Lab\tacs3-bluesky\stimulation\pre-stimulation-participant-responses"),
        help="Folder containing behavioral CSV files.",
    )
    parser.add_argument(
        "--easy-dir", type=Path,
        default=Path(r"C:\Users\Public\LAB PROJECTS\Smith-Lab\tacs3-bluesky\stimulation\stimulation-data"),
        help="Folder containing neural .easy files.",
    )
    parser.add_argument("--task", default="bandit", help="Task name to include (default: bandit).")
    parser.add_argument("--phase", choices=["pre-stim", "post-stim"], default="pre-stim",
                        help="Include this stimulation phase (default: pre-stim).")
    parser.add_argument("--channel", type=int, default=DEFAULT_CHANNEL,
                        help="Zero-based .easy signal column to analyze (default: 0).")
    parser.add_argument("--uv-per-unit", type=float, default=None,
                        help="Known conversion factor from .easy units to µV.")
    parser.add_argument("--output", type=Path, default=None,
                        help="Output image path. Default: group_<task>_<phase>_channel-<channel>_gain-loss.png")
    parser.add_argument("--normal-y-axis", action="store_true",
                        help="Use conventional increasing-up y-axis. By default, negative is plotted upward.")
    args = parser.parse_args()

    if (args.csv is None) != (args.easy is None):
        parser.error("Provide both --csv and --easy for a single-file analysis, or neither for the group analysis.")

    if args.csv is not None:
        file_pairs = [(args.csv.stem, "manual", args.csv, args.easy)]
    else:
        file_pairs = discover_bandit_file_pairs(
            args.csv_dir, args.easy_dir, args.task, args.phase
        )

    print(f"Found {len(file_pairs)} participant/session recording pair(s) for task '{args.task}' ({args.phase}).")
    print("Signal columns are zero-indexed. Check the acquisition montage before assigning electrode names.")

    # Use the first recording's sampling rate as the common group-average time grid.
    first_signals, first_timestamps, reference_fs = load_easy(file_pairs[0][3])
    reference_step_ms = 1000.0 / reference_fs
    group_time_ms = np.arange(
        FEEDBACK_START_MS, FEEDBACK_END_MS + reference_step_ms / 2, reference_step_ms
    )

    all_epochs = {"loss": [], "win": []}
    included_pairs = 0
    total_events = 0

    for subject, session, csv_path, easy_path in file_pairs:
        try:
            behavior = pd.read_csv(csv_path)
            required = {"outcome", "feedback_onset_unix_time"}
            missing = required.difference(behavior.columns)
            if missing:
                raise ValueError(f"CSV is missing required column(s): {sorted(missing)}")

            behavior = behavior.copy()
            behavior["outcome"] = behavior["outcome"].astype(str).str.lower().str.strip()
            behavior = behavior[behavior["outcome"].isin(["win", "loss"])].copy()
            behavior["feedback_onset_unix_time"] = pd.to_numeric(
                behavior["feedback_onset_unix_time"], errors="coerce"
            )
            behavior = behavior.dropna(subset=["feedback_onset_unix_time"])

            signals, timestamps_ms, fs = load_easy(easy_path)
            total_events += len(behavior)
            print(
                f"Processing subject {subject}, session {session}: "
                f"{len(behavior)} feedback event(s), {fs:.2f} Hz"
            )

            for condition in ("loss", "win"):
                subset = behavior[behavior["outcome"] == condition]
                if subset.empty:
                    continue
                epochs, epoch_time_ms = epoch_trials(
                    signals, timestamps_ms,
                    subset["feedback_onset_unix_time"].to_numpy(dtype=float),
                    args.channel, fs,
                )

                # Resample this recording's epochs onto the shared group time axis.
                # This allows recordings with slightly different sampling rates to be combined.
                resampled = np.vstack([
                    np.interp(group_time_ms, epoch_time_ms, epoch)
                    for epoch in epochs
                ])
                all_epochs[condition].append(resampled)

            included_pairs += 1
        except Exception as exc:
            print(f"WARNING: skipping {csv_path.name} / {easy_path.name}: {exc}")

    combined = {}
    curves = {}
    counts = {}
    for condition in ("loss", "win"):
        if not all_epochs[condition]:
            raise RuntimeError(f"No usable {condition} trials were found across the selected recordings.")
        combined[condition] = np.vstack(all_epochs[condition])
        curves[condition] = mean_and_sem(combined[condition])
        counts[condition] = combined[condition].shape[0]

    scale = args.uv_per_unit if args.uv_per_unit is not None else 1.0
    y_label = "Amplitude (µV)" if args.uv_per_unit is not None else "Amplitude (recording units)"

    fig, ax = plt.subplots(figsize=(8.2, 5.8))
    styles = {
        "loss": {"color": "red", "linestyle": "-", "label": f"Loss (n={counts['loss']})"},
        "win": {"color": "limegreen", "linestyle": "--", "label": f"Gain (n={counts['win']})"},
    }

    for condition in ("loss", "win"):
        mean, sem = curves[condition]
        mean = mean * scale
        sem = sem * scale
        style = styles[condition]
        mean_display = smooth_for_display(mean, DISPLAY_SMOOTHING_MS, reference_step_ms)

        ax.plot(group_time_ms, mean_display, color=style["color"],
                linestyle=style["linestyle"], linewidth=MEAN_LINEWIDTH,
                label=style["label"])

        if counts[condition] >= 2:
            lower_display = smooth_for_display(
                mean - 2 * sem, DISPLAY_SMOOTHING_MS, reference_step_ms
            )
            upper_display = smooth_for_display(
                mean + 2 * sem, DISPLAY_SMOOTHING_MS, reference_step_ms
            )
            ax.fill_between(
                group_time_ms, lower_display, upper_display,
                color=style["color"], alpha=SEM_BAND_ALPHA, linewidth=0, zorder=1
            )

    ax.axvline(0, color="black", linewidth=0.7, alpha=0.35)
    ax.axhline(0, color="black", linewidth=0.6, alpha=0.25)
    ax.set_xlim(FEEDBACK_START_MS, FEEDBACK_END_MS)
    ax.set_xlabel("Time from feedback onset (ms)")
    ax.set_ylabel(y_label)
    ax.set_title(f"Group-Average Feedback-locked Gain vs Loss | Channel {args.channel}")
    ax.legend(frameon=False)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(False)

    if not args.normal_y_axis:
        ax.invert_yaxis()

    fig.tight_layout()
    output_path = args.output or Path(
        f"group_{args.task}_{args.phase}_channel-{args.channel}_gain-loss.png"
    )
    fig.savefig(output_path, dpi=300, bbox_inches="tight")
    print(f"\nSaved graph: {output_path.resolve()}")
    print(f"Participant/session pairs included: {included_pairs} / {len(file_pairs)}")
    print(f"Behavioral feedback events read: {total_events}")
    print(f"Total trials included: Gain={counts['win']}, Loss={counts['loss']}")
    print("Shaded bands show mean ± 2 SEM across all included trials.")
    print(f"Display-only smoothing: {DISPLAY_SMOOTHING_MS:g} ms (centered moving average).")
    print("Baseline correction: subtract each trial's mean from 700 to 1300 ms after feedback onset.")
    print("Group average is trial-weighted: every valid trial contributes equally, regardless of participant/session.")


if __name__ == "__main__":
    main()
