"""Task-evoked rhythm estimation for bandit and SST localizers.

The primary goal is to estimate participant-specific task-evoked rhythms for
stimulation planning. For the bandit task, the main target is feedback-locked
theta. For both bandit and SST, the same reliability-gated machinery can also
estimate decision/response beta when configured.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import csv
import json
import math
from pathlib import Path
from typing import Any, Iterable

import numpy as np


@dataclass
class EEGData:
    samples: np.ndarray
    timestamps: np.ndarray
    channel_names: list[str]
    sampling_rate_hz: float
    metadata: dict[str, Any]


@dataclass
class RhythmEstimateArtifacts:
    json_path: Path | None = None
    csv_path: Path | None = None
    plot_paths: list[Path] | None = None


def load_config(config_path: Path | str | None = None) -> dict[str, Any]:
    if config_path is None:
        config_path = Path(__file__).resolve().parent / "config.json"
    with Path(config_path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_eeg(eeg_path: Path | str) -> EEGData:
    path = Path(eeg_path)
    suffix = path.suffix.lower()
    if suffix == ".npz":
        return _load_npz(path)
    if suffix == ".csv":
        return _load_csv(path)
    if suffix in {".edf", ".bdf", ".set"}:
        return _load_mne(path)
    if suffix == ".xdf":
        return _load_xdf(path)
    raise ValueError(f"Unsupported EEG format: {path.suffix}")


def _load_npz(path: Path) -> EEGData:
    data = np.load(path, allow_pickle=True)
    samples = np.asarray(data["samples"], dtype=float)
    timestamps = np.asarray(data["timestamps"], dtype=float)
    channel_names = [str(item) for item in data["channel_names"].tolist()]
    srate_raw = data.get("sampling_rate_hz", np.asarray([np.nan]))
    sampling_rate_hz = float(np.asarray(srate_raw).ravel()[0])
    if not np.isfinite(sampling_rate_hz) or sampling_rate_hz <= 0:
        sampling_rate_hz = _infer_sampling_rate(timestamps)
    metadata: dict[str, Any] = {}
    if "metadata_json" in data:
        try:
            metadata = json.loads(str(np.asarray(data["metadata_json"]).item()))
        except Exception:
            metadata = {}
    return EEGData(samples=samples, timestamps=timestamps, channel_names=channel_names, sampling_rate_hz=sampling_rate_hz, metadata=metadata)


def _load_csv(path: Path) -> EEGData:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
    if not rows:
        raise ValueError(f"EEG CSV is empty: {path}")
    timestamp_column = "lsl_timestamp" if "lsl_timestamp" in rows[0] else "timestamp"
    channel_names = [name for name in rows[0] if name != timestamp_column]
    timestamps = np.asarray([_safe_float(row.get(timestamp_column)) for row in rows], dtype=float)
    samples = np.asarray([[float(row.get(ch, "nan")) for ch in channel_names] for row in rows], dtype=float)
    return EEGData(samples=samples, timestamps=timestamps, channel_names=channel_names, sampling_rate_hz=_infer_sampling_rate(timestamps), metadata={"source_csv": str(path)})


def _load_mne(path: Path) -> EEGData:
    try:
        import mne
    except ImportError as exc:  # pragma: no cover - optional lab dependency
        raise ImportError("MNE is required to load EDF/BDF/SET files. Install mne or convert to NPZ/CSV.") from exc
    suffix = path.suffix.lower()
    if suffix in {".edf", ".bdf"}:
        raw = mne.io.read_raw_edf(path, preload=True, verbose="ERROR")
    else:
        raw = mne.io.read_raw_eeglab(path, preload=True, verbose="ERROR")
    samples = raw.get_data().T * 1e6
    timestamps = np.arange(samples.shape[0], dtype=float) / float(raw.info["sfreq"])
    return EEGData(samples=samples, timestamps=timestamps, channel_names=list(raw.ch_names), sampling_rate_hz=float(raw.info["sfreq"]), metadata={"source_file": str(path)})


def _load_xdf(path: Path) -> EEGData:
    try:
        import pyxdf
    except ImportError as exc:  # pragma: no cover - optional lab dependency
        raise ImportError("pyxdf is required to load XDF files. Install pyxdf or convert to NPZ/CSV.") from exc
    streams, _ = pyxdf.load_xdf(str(path))
    eeg_streams = [stream for stream in streams if stream.get("info", {}).get("type", [""])[0].lower() == "eeg"]
    if not eeg_streams:
        raise ValueError(f"No EEG stream found in {path}")
    stream = eeg_streams[0]
    samples = np.asarray(stream["time_series"], dtype=float)
    timestamps = np.asarray(stream["time_stamps"], dtype=float)
    labels = []
    try:
        channels = stream["info"]["desc"][0]["channels"][0]["channel"]
        labels = [ch.get("label", [f"ch{i + 1}"])[0] for i, ch in enumerate(channels)]
    except Exception:
        labels = [f"ch{i + 1}" for i in range(samples.shape[1])]
    return EEGData(samples=samples, timestamps=timestamps, channel_names=labels, sampling_rate_hz=_infer_sampling_rate(timestamps), metadata={"source_xdf": str(path)})


def load_events(events_path: Path | str) -> list[dict[str, Any]]:
    path = Path(events_path)
    delimiter = "\t" if path.suffix.lower() == ".tsv" else ","
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter=delimiter))


def estimate_feedback_theta_from_files(
    *,
    subject_id: str,
    session_id: str,
    localizer_csv: Path | str,
    eeg_path: Path | str,
    config_path: Path | str | None = None,
    output_dir: Path | str | None = None,
    localizer_run: str = "run-localizer",
) -> tuple[dict[str, Any], RhythmEstimateArtifacts]:
    config = load_config(config_path)
    return estimate_rhythm_from_files(
        subject_id=subject_id,
        session_id=session_id,
        events_path=localizer_csv,
        eeg_path=eeg_path,
        config=config,
        rhythm_key="bandit_feedback_theta",
        output_dir=output_dir,
        run_label=localizer_run,
    )


def estimate_rhythm_from_files(
    *,
    subject_id: str,
    session_id: str,
    events_path: Path | str,
    eeg_path: Path | str,
    config: dict[str, Any] | None = None,
    config_path: Path | str | None = None,
    rhythm_key: str = "bandit_feedback_theta",
    output_dir: Path | str | None = None,
    run_label: str = "run-localizer",
) -> tuple[dict[str, Any], RhythmEstimateArtifacts]:
    if config is None:
        config = load_config(config_path)
    eeg_data = load_eeg(eeg_path)
    events = load_events(events_path)
    return estimate_rhythm(
        eeg_data,
        events,
        config,
        subject_id=subject_id,
        session_id=session_id,
        rhythm_key=rhythm_key,
        output_dir=output_dir,
        run_label=run_label,
    )


def estimate_feedback_theta(
    eeg_data: EEGData,
    behavior: Any,
    config: dict[str, Any],
    *,
    subject_id: str,
    session_id: str,
    output_dir: Path | str | None = None,
    localizer_run: str = "run-localizer",
) -> tuple[dict[str, Any], RhythmEstimateArtifacts]:
    return estimate_rhythm(
        eeg_data,
        behavior,
        config,
        subject_id=subject_id,
        session_id=session_id,
        rhythm_key="bandit_feedback_theta",
        output_dir=output_dir,
        run_label=localizer_run,
    )


def estimate_rhythm(
    eeg_data: EEGData,
    events: Any,
    config: dict[str, Any],
    *,
    subject_id: str,
    session_id: str,
    rhythm_key: str,
    output_dir: Path | str | None = None,
    run_label: str = "run-localizer",
) -> tuple[dict[str, Any], RhythmEstimateArtifacts]:
    estimands = config.get("rhythm_estimands", {})
    if rhythm_key not in estimands:
        raise KeyError(f"Unknown rhythm_key {rhythm_key!r}. Available: {sorted(estimands)}")
    spec = estimands[rhythm_key]
    preprocessing_config = config.get("eeg_preprocessing", {})

    preprocessed = _preprocess_eeg(eeg_data, preprocessing_config)
    event_times, event_labels, event_warnings = _extract_event_times(events, spec, preprocessed.timestamps)
    epochs, retained_event_labels, epoch_qc = _epoch_data(preprocessed, event_times, event_labels, spec, preprocessing_config)
    result = _estimate_from_epochs(
        epochs,
        retained_event_labels,
        preprocessed,
        spec,
        preprocessing_config,
        subject_id=subject_id,
        session_id=session_id,
        rhythm_key=rhythm_key,
        run_label=run_label,
        event_warnings=event_warnings,
        epoch_qc=epoch_qc,
    )
    artifacts = _write_outputs(result, output_dir, subject_id, session_id, rhythm_key, config)
    return result, artifacts


def _preprocess_eeg(eeg_data: EEGData, config: dict[str, Any]) -> EEGData:
    samples = np.asarray(eeg_data.samples, dtype=float)
    timestamps = np.asarray(eeg_data.timestamps, dtype=float)
    if samples.ndim != 2:
        raise ValueError("EEG samples must be a 2D array shaped samples x channels.")
    if samples.shape[0] != timestamps.shape[0]:
        raise ValueError("EEG sample count and timestamp count do not match.")
    warnings: list[str] = []
    timestamp_qc = _timestamp_qc(timestamps, eeg_data.sampling_rate_hz)
    warnings.extend(timestamp_qc["warnings"])

    target_srate = float(config.get("resample_hz") or eeg_data.sampling_rate_hz)
    if target_srate > 0 and abs(target_srate - eeg_data.sampling_rate_hz) > 1:
        samples, timestamps = _resample(samples, timestamps, target_srate)
        sampling_rate_hz = target_srate
    else:
        sampling_rate_hz = float(eeg_data.sampling_rate_hz)

    samples = _fft_filter(
        samples,
        sampling_rate_hz,
        highpass_hz=_optional_float(config.get("highpass_hz")),
        lowpass_hz=_optional_float(config.get("lowpass_hz")),
        notch_hz=_optional_float(config.get("notch_hz")),
    )

    channel_qc = _channel_quality(samples, eeg_data.channel_names, sampling_rate_hz, config)
    good_indices = [idx for idx, name in enumerate(eeg_data.channel_names) if name not in channel_qc["bad_channels"]]
    if config.get("reference", "average_available") == "average_available" and good_indices:
        samples = samples - np.nanmean(samples[:, good_indices], axis=1, keepdims=True)

    blink_mask, blink_warnings = _blink_sample_mask(samples, eeg_data.channel_names, sampling_rate_hz, config)
    warnings.extend(blink_warnings)

    metadata = dict(eeg_data.metadata or {})
    metadata.update(
        {
            "preprocessing_warnings": warnings,
            "timestamp_qc": timestamp_qc,
            "channel_qc": channel_qc,
            "blink_sample_mask": blink_mask,
            "highpass_hz": config.get("highpass_hz"),
            "lowpass_hz": config.get("lowpass_hz"),
            "notch_hz": config.get("notch_hz"),
            "resample_hz": sampling_rate_hz,
            "reference": config.get("reference", "average_available"),
        }
    )
    return EEGData(samples=samples, timestamps=timestamps, channel_names=list(eeg_data.channel_names), sampling_rate_hz=sampling_rate_hz, metadata=metadata)


def _timestamp_qc(timestamps: np.ndarray, nominal_srate: float) -> dict[str, Any]:
    diffs = np.diff(timestamps)
    warnings: list[str] = []
    if len(diffs) == 0:
        warnings.append("EEG recording has fewer than two timestamps.")
        return {"warnings": warnings, "n_gaps": 0, "n_duplicates": 0, "irregular_fraction": 0.0}
    median_dt = float(np.nanmedian(diffs))
    expected_dt = 1.0 / nominal_srate if nominal_srate and nominal_srate > 0 else median_dt
    n_duplicates = int(np.sum(diffs <= 0))
    n_gaps = int(np.sum(diffs > expected_dt * 3))
    irregular_fraction = float(np.mean(np.abs(diffs - median_dt) > max(0.002, median_dt * 0.25)))
    if n_duplicates:
        warnings.append(f"EEG timestamps include {n_duplicates} duplicate or reversed samples.")
    if n_gaps:
        warnings.append(f"EEG timestamps include {n_gaps} probable gaps.")
    if irregular_fraction > 0.01:
        warnings.append(f"EEG sampling appears irregular in {irregular_fraction:.1%} of intervals.")
    return {"warnings": warnings, "n_gaps": n_gaps, "n_duplicates": n_duplicates, "irregular_fraction": irregular_fraction}


def _resample(samples: np.ndarray, timestamps: np.ndarray, target_srate: float) -> tuple[np.ndarray, np.ndarray]:
    start = float(timestamps[0])
    stop = float(timestamps[-1])
    n_samples = int(math.floor((stop - start) * target_srate)) + 1
    new_timestamps = start + np.arange(n_samples, dtype=float) / target_srate
    new_samples = np.empty((n_samples, samples.shape[1]), dtype=float)
    for ch in range(samples.shape[1]):
        new_samples[:, ch] = np.interp(new_timestamps, timestamps, samples[:, ch])
    return new_samples, new_timestamps


def _fft_filter(samples: np.ndarray, srate: float, *, highpass_hz: float | None, lowpass_hz: float | None, notch_hz: float | None) -> np.ndarray:
    if samples.shape[0] < 4 or srate <= 0:
        return samples
    freqs = np.fft.rfftfreq(samples.shape[0], d=1.0 / srate)
    spectrum = np.fft.rfft(samples, axis=0)
    keep = np.ones_like(freqs, dtype=bool)
    if highpass_hz is not None and highpass_hz > 0:
        keep &= freqs >= highpass_hz
    if lowpass_hz is not None and lowpass_hz > 0:
        keep &= freqs <= lowpass_hz
    if notch_hz is not None and notch_hz > 0:
        keep &= np.abs(freqs - notch_hz) > 1.0
    spectrum[~keep, :] = 0
    return np.fft.irfft(spectrum, n=samples.shape[0], axis=0)


def _channel_quality(samples: np.ndarray, channel_names: list[str], srate: float, config: dict[str, Any]) -> dict[str, Any]:
    bad_channels: list[str] = []
    reasons: dict[str, str] = {}
    stds = np.nanstd(samples, axis=0)
    median_std = float(np.nanmedian(stds[np.isfinite(stds)])) if np.any(np.isfinite(stds)) else 0.0
    for idx, name in enumerate(channel_names):
        channel = samples[:, idx]
        channel_std = float(stds[idx])
        if not np.isfinite(channel_std) or channel_std < 1e-9:
            bad_channels.append(name)
            reasons[name] = "flat_or_nan"
            continue
        if median_std > 0 and channel_std > median_std * 25:
            bad_channels.append(name)
            reasons[name] = "extreme_variance"
            continue
        if median_std > 0 and channel_std < median_std / 25:
            bad_channels.append(name)
            reasons[name] = "very_low_variance"
            continue
        diffs = np.abs(np.diff(channel))
        if len(diffs) and np.sum(diffs < 1e-12) / len(diffs) > 0.98:
            bad_channels.append(name)
            reasons[name] = "flatline"
            continue
        rounded = np.round(channel, decimals=6)
        _, counts = np.unique(rounded, return_counts=True)
        if len(counts) and counts.max() / len(channel) > 0.05:
            bad_channels.append(name)
            reasons[name] = "possible_clipping_or_saturation"
    return {"bad_channels": bad_channels, "bad_channel_reasons": reasons, "channel_std_uv": {name: float(stds[idx]) for idx, name in enumerate(channel_names)}}


def _blink_sample_mask(samples: np.ndarray, channel_names: list[str], srate: float, config: dict[str, Any]) -> tuple[np.ndarray, list[str]]:
    mask = np.zeros(samples.shape[0], dtype=bool)
    warnings: list[str] = []
    if not config.get("blink_rejection", True):
        return mask, warnings
    candidates = [name.lower() for name in config.get("blink_channel_candidates", ["EOG", "Fp1", "Fp2"])]
    blink_indices = [
        idx
        for idx, name in enumerate(channel_names)
        if any(candidate == name.lower() or candidate in name.lower() for candidate in candidates)
    ]
    if not blink_indices:
        warnings.append("Blink rejection requested but no EOG/Fp blink channel was available; blink-specific rejection was skipped.")
        return mask, warnings
    z_threshold = float(config.get("blink_z_threshold", 5.0))
    blink_signal = np.nanmax(np.abs(_robust_z(samples[:, blink_indices])), axis=1)
    mask = blink_signal > z_threshold
    padding = int(round(float(config.get("blink_padding_sec", 0.1)) * srate))
    if padding > 0 and np.any(mask):
        padded = mask.copy()
        blink_samples = np.flatnonzero(mask)
        for sample in blink_samples:
            padded[max(0, sample - padding): min(len(mask), sample + padding + 1)] = True
        mask = padded
    return mask, warnings


def _extract_event_times(events: Any, spec: dict[str, Any], eeg_timestamps: np.ndarray) -> tuple[np.ndarray, list[str], list[str]]:
    rows = _records(events)
    event_times: list[float] = []
    event_labels: list[str] = []
    warnings: list[str] = []
    marker_column = spec.get("marker_column")
    marker_set = {int(marker) for marker in spec.get("markers", [])}
    for row in rows:
        if marker_column and marker_column in row and row.get(marker_column) not in ("", None):
            marker = _safe_float(row.get(marker_column))
            if marker_set and (marker is None or int(marker) not in marker_set):
                continue
        event_time = _row_event_time(row, spec.get("event_time_columns", []), eeg_timestamps)
        if event_time is None:
            continue
        event_times.append(float(event_time))
        event_labels.append(str(row.get("outcome") or row.get("trial_type") or row.get("stop_success") or spec.get("event_name", "event")))
    if not event_times:
        warnings.append(f"No usable event times found for {spec.get('label', spec.get('event_name'))}.")
    return np.asarray(event_times, dtype=float), event_labels, warnings


def _row_event_time(row: dict[str, Any], columns: Iterable[str], eeg_timestamps: np.ndarray) -> float | None:
    start = float(np.nanmin(eeg_timestamps)) if len(eeg_timestamps) else 0.0
    stop = float(np.nanmax(eeg_timestamps)) if len(eeg_timestamps) else 0.0
    run_start_lsl = _safe_float(row.get("run_start_lsl_time"))
    for column in columns:
        value = _safe_float(row.get(column))
        if value is None:
            continue
        if start - 5 <= value <= stop + 5:
            return value
        if run_start_lsl is not None and start - 5 <= run_start_lsl + value <= stop + 5:
            return run_start_lsl + value
    return None


def _epoch_data(
    eeg_data: EEGData,
    event_times: np.ndarray,
    event_labels: list[str],
    spec: dict[str, Any],
    preprocessing_config: dict[str, Any],
) -> tuple[np.ndarray, list[str], dict[str, Any]]:
    srate = float(eeg_data.sampling_rate_hz)
    tmin = float(spec["epoch_tmin_sec"])
    tmax = float(spec["epoch_tmax_sec"])
    n_times = int(round((tmax - tmin) * srate))
    epoch_times = np.arange(n_times, dtype=float) / srate + tmin
    retained: list[np.ndarray] = []
    retained_labels: list[str] = []
    rejection_reasons: list[str] = []
    blink_mask = np.asarray(eeg_data.metadata.get("blink_sample_mask", np.zeros(eeg_data.samples.shape[0], dtype=bool)), dtype=bool)
    reject_uv = float(preprocessing_config.get("epoch_reject_uv", 150))
    step_reject_uv = float(preprocessing_config.get("step_reject_uv", 75))
    for event_time, label in zip(event_times, event_labels):
        center = int(round((float(event_time) - float(eeg_data.timestamps[0])) * srate))
        start = center + int(round(tmin * srate))
        stop = start + n_times
        if start < 0 or stop > eeg_data.samples.shape[0]:
            rejection_reasons.append("outside_eeg_bounds")
            continue
        epoch = eeg_data.samples[start:stop, :].T
        if np.nanmax(np.abs(epoch)) > reject_uv:
            rejection_reasons.append("amplitude")
            continue
        if epoch.shape[1] > 1 and np.nanmax(np.abs(np.diff(epoch, axis=1))) > step_reject_uv:
            rejection_reasons.append("step")
            continue
        if len(blink_mask) == eeg_data.samples.shape[0] and np.any(blink_mask[start:stop]):
            rejection_reasons.append("blink")
            continue
        retained.append(epoch)
        retained_labels.append(label)
    if retained:
        epochs = np.stack(retained, axis=0)
    else:
        epochs = np.empty((0, eeg_data.samples.shape[1], n_times), dtype=float)
    return epochs, retained_labels, {
        "n_events_total": int(len(event_times)),
        "n_epochs_retained": int(len(retained)),
        "rejection_reasons": rejection_reasons,
        "epoch_times": epoch_times,
    }


def _estimate_from_epochs(
    epochs: np.ndarray,
    event_labels: list[str],
    eeg_data: EEGData,
    spec: dict[str, Any],
    preprocessing_config: dict[str, Any],
    *,
    subject_id: str,
    session_id: str,
    rhythm_key: str,
    run_label: str,
    event_warnings: list[str],
    epoch_qc: dict[str, Any],
) -> dict[str, Any]:
    channel_qc = eeg_data.metadata.get("channel_qc", {})
    bad_channels = set(channel_qc.get("bad_channels", []))
    requested_roi = list(spec.get("roi", []))
    roi_indices = [idx for idx, name in enumerate(eeg_data.channel_names) if name in requested_roi and name not in bad_channels]
    if not roi_indices:
        roi_indices = [idx for idx, name in enumerate(eeg_data.channel_names) if name not in bad_channels]
    roi_channels_used = [eeg_data.channel_names[idx] for idx in roi_indices]
    min_roi_channels = int(spec.get("min_roi_channels", 2))

    freqs = _frequency_grid(spec)
    epoch_times = np.asarray(epoch_qc["epoch_times"], dtype=float)
    spectrum_by_epoch = _window_power_spectrum(epochs, roi_indices, epoch_times, freqs, spec) if len(roi_indices) else np.empty((epochs.shape[0], len(freqs)))
    mean_spectrum = np.nanmean(spectrum_by_epoch, axis=0) if spectrum_by_epoch.size else np.full(len(freqs), np.nan)
    smoothed_spectrum = _smooth_spectrum(mean_spectrum, freqs, float(spec.get("smooth_spectrum_hz", 0)))
    peak = _find_peak(freqs, smoothed_spectrum, spec)

    n_total = int(epoch_qc["n_events_total"])
    n_retained = int(epoch_qc["n_epochs_retained"])
    usable_fraction = float(n_retained / n_total) if n_total else 0.0
    split = _split_half(freqs, spectrum_by_epoch, spec)
    bootstrap = _bootstrap(freqs, spectrum_by_epoch, spec)

    reasons: list[str] = []
    hard_min = int(spec.get("hard_min_usable_epochs", 0))
    if n_retained < hard_min:
        reasons.append(f"only {n_retained} usable epochs retained; hard minimum is {hard_min}")
    if usable_fraction < float(spec.get("min_usable_epoch_fraction", 0.0)):
        reasons.append(f"usable epoch fraction {usable_fraction:.2f} is below criterion")
    if len(roi_channels_used) < min_roi_channels:
        reasons.append(f"only {len(roi_channels_used)} usable ROI channels; minimum is {min_roi_channels}")
    if peak["peak_hz"] is None:
        reasons.append("no candidate spectral peak was found")
    if peak["edge_peak"] and spec.get("reject_edge_peaks", True):
        reasons.append("candidate peak was at the edge of the search band")
    if peak["peak_prominence_z"] < float(spec.get("min_peak_prominence_z", 0.0)):
        reasons.append(f"peak prominence z={peak['peak_prominence_z']:.2f} is below criterion")
    if split["split_half_diff_hz"] is None or split["split_half_diff_hz"] > float(spec.get("split_half_max_peak_diff_hz", np.inf)):
        reasons.append("split-half peaks were unstable")
    if bootstrap["bootstrap_ci_width_hz"] is None or bootstrap["bootstrap_ci_width_hz"] > float(spec.get("max_bootstrap_ci_width_hz", np.inf)):
        reasons.append("bootstrap peak CI was too wide")

    reliable = not reasons
    raw_peak = peak["peak_hz"] if reliable else None
    rounded_peak = _round_frequency(raw_peak, float(spec.get("round_to_nearest_hz", 0.5))) if raw_peak is not None else None
    fallback_hz = float(spec.get("fallback_frequency_hz", 6.0 if spec.get("rhythm") == "theta" else 20.0))
    frequency_to_use = float(rounded_peak) if reliable and rounded_peak is not None else fallback_hz
    source = spec.get("reliable_source", "reliable_individualized") if reliable else spec.get("fallback_source", "fallback_fixed")
    rhythm = str(spec.get("rhythm", "rhythm"))
    prefix = "itheta" if rhythm == "theta" else "ibeta" if rhythm == "beta" else "irhythm"
    decision_reason = (
        f"Reliable task-evoked {rhythm} estimate. Rounded to nearest {spec.get('round_to_nearest_hz', 0.5)} Hz."
        if reliable
        else "Unreliable estimate: " + "; ".join(reasons) + f". Use fixed {frequency_to_use:.1f} Hz fallback."
    )

    result: dict[str, Any] = {
        "subject_id": f"sub-{_strip_prefix(subject_id, 'sub-')}",
        "session_id": f"ses-{_strip_prefix(session_id, 'ses-')}",
        "localizer_run": run_label,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "analysis_version": "tacs3_bluesky_rhythm_estimator_v1",
        "rhythm_key": rhythm_key,
        "rhythm_label": spec.get("label", rhythm_key),
        "rhythm": rhythm,
        "task": spec.get("task", ""),
        "event_name": spec.get("event_name", ""),
        "reliable": bool(reliable),
        "peak_hz_raw": raw_peak,
        "peak_hz_rounded": rounded_peak,
        "frequency_to_use_hz": frequency_to_use,
        "fallback_frequency_hz": fallback_hz,
        "rhythm_source": source,
        "theta_source": source if rhythm == "theta" else "none",
        "beta_source": source if rhythm == "beta" else "none",
        f"{prefix}_hz_raw": raw_peak,
        f"{prefix}_hz_rounded": rounded_peak,
        "reliability": {
            "n_events_total": n_total,
            "n_feedback_epochs_total": n_total if spec.get("event_name") == "feedback" else None,
            "n_epochs_retained": n_retained,
            "usable_epoch_fraction": round(usable_fraction, 3),
            "split_half_peak_1_hz": split["split_half_peak_1_hz"],
            "split_half_peak_2_hz": split["split_half_peak_2_hz"],
            "split_half_diff_hz": split["split_half_diff_hz"],
            "bootstrap_ci_low_hz": bootstrap["bootstrap_ci_low_hz"],
            "bootstrap_ci_high_hz": bootstrap["bootstrap_ci_high_hz"],
            "bootstrap_ci_width_hz": bootstrap["bootstrap_ci_width_hz"],
            "peak_prominence_z": peak["peak_prominence_z"],
            "candidate_peak_hz": peak["peak_hz"],
            "edge_peak": peak["edge_peak"],
            "rejection_reasons": _count_items(epoch_qc["rejection_reasons"]),
            "warnings": event_warnings + eeg_data.metadata.get("preprocessing_warnings", []),
        },
        "preprocessing": {
            "highpass_hz": preprocessing_config.get("highpass_hz"),
            "lowpass_hz": preprocessing_config.get("lowpass_hz"),
            "notch_hz": preprocessing_config.get("notch_hz"),
            "resample_hz": eeg_data.sampling_rate_hz,
            "reference": preprocessing_config.get("reference", "average_available"),
            "bad_channels": sorted(bad_channels),
            "roi_channels_requested": requested_roi,
            "roi_channels_used": roi_channels_used,
            "blink_rejection": preprocessing_config.get("blink_rejection", True),
        },
        "windows": {
            "epoch_tmin_sec": spec.get("epoch_tmin_sec"),
            "epoch_tmax_sec": spec.get("epoch_tmax_sec"),
            "baseline_window_sec": spec.get("baseline_window_sec"),
            "analysis_window_sec": spec.get("analysis_window_sec"),
            "primary_band_hz": spec.get("primary_band_hz"),
        },
        "spectra": {
            "frequencies_hz": [float(freq) for freq in freqs],
            "mean_db": [float(x) if np.isfinite(x) else None for x in mean_spectrum],
            "smoothed_db": [float(x) if np.isfinite(x) else None for x in smoothed_spectrum],
        },
        "decision": {
            "use_for_stimulation": bool(reliable),
            "reason": decision_reason,
        },
    }
    if rhythm == "theta":
        result["itheta_hz_raw"] = raw_peak
        result["itheta_hz_rounded"] = rounded_peak
        result["theta_label"] = spec.get("label", rhythm_key)
        result["theta_source"] = source
        result["fallback_theta_hz"] = fallback_hz
    if rhythm == "beta":
        result["ibeta_hz_raw"] = raw_peak
        result["ibeta_hz_rounded"] = rounded_peak
        result["beta_label"] = spec.get("label", rhythm_key)
        result["fallback_beta_hz"] = fallback_hz
    result["operator_summary"] = _operator_summary(result)
    return result


def _window_power_spectrum(epochs: np.ndarray, roi_indices: list[int], times: np.ndarray, freqs: np.ndarray, spec: dict[str, Any]) -> np.ndarray:
    if epochs.shape[0] == 0 or not roi_indices:
        return np.empty((0, len(freqs)), dtype=float)
    roi_signal = np.nanmean(epochs[:, roi_indices, :], axis=1)
    baseline_mask = _time_mask(times, spec["baseline_window_sec"])
    analysis_mask = _time_mask(times, spec["analysis_window_sec"])
    baseline_power = _projection_power(roi_signal[:, baseline_mask], times[baseline_mask], freqs)
    analysis_power = _projection_power(roi_signal[:, analysis_mask], times[analysis_mask], freqs)
    eps = np.finfo(float).eps
    return 10.0 * np.log10((analysis_power + eps) / (baseline_power + eps))


def _projection_power(data: np.ndarray, times: np.ndarray, freqs: np.ndarray) -> np.ndarray:
    if data.shape[1] == 0:
        return np.full((data.shape[0], len(freqs)), np.nan)
    centered = data - np.nanmean(data, axis=1, keepdims=True)
    if data.shape[1] >= 4:
        window = np.hanning(data.shape[1])
    else:
        window = np.ones(data.shape[1])
    norm = np.sum(window ** 2) or 1.0
    power = np.empty((data.shape[0], len(freqs)), dtype=float)
    for idx, freq in enumerate(freqs):
        basis = np.exp(-2j * np.pi * float(freq) * times)
        amp = np.nansum(centered * window * basis, axis=1) / math.sqrt(norm)
        power[:, idx] = np.abs(amp) ** 2
    return power


def _find_peak(freqs: np.ndarray, spectrum: np.ndarray, spec: dict[str, Any]) -> dict[str, Any]:
    band = spec.get("primary_band_hz", [float(freqs[0]), float(freqs[-1])])
    mask = (freqs >= float(band[0])) & (freqs <= float(band[1])) & np.isfinite(spectrum)
    if not np.any(mask):
        return {"peak_hz": None, "peak_prominence_z": 0.0, "edge_peak": False}
    search_freqs = freqs[mask]
    search_spectrum = spectrum[mask]
    local_idx = int(np.nanargmax(search_spectrum))
    peak_hz = float(search_freqs[local_idx])
    edge_peak = local_idx == 0 or local_idx == len(search_freqs) - 1
    prominence_z = float((search_spectrum[local_idx] - np.nanmedian(search_spectrum)) / (_mad(search_spectrum) or np.nanstd(search_spectrum) or 1.0))
    return {"peak_hz": peak_hz, "peak_prominence_z": prominence_z, "edge_peak": bool(edge_peak)}


def _split_half(freqs: np.ndarray, spectrum_by_epoch: np.ndarray, spec: dict[str, Any]) -> dict[str, float | None]:
    n_epochs = spectrum_by_epoch.shape[0]
    if n_epochs < 4:
        return {"split_half_peak_1_hz": None, "split_half_peak_2_hz": None, "split_half_diff_hz": None}
    midpoint = n_epochs // 2
    peak_1 = _find_peak(freqs, _smooth_spectrum(np.nanmean(spectrum_by_epoch[:midpoint], axis=0), freqs, float(spec.get("smooth_spectrum_hz", 0))), spec)["peak_hz"]
    peak_2 = _find_peak(freqs, _smooth_spectrum(np.nanmean(spectrum_by_epoch[midpoint:], axis=0), freqs, float(spec.get("smooth_spectrum_hz", 0))), spec)["peak_hz"]
    diff = abs(float(peak_1) - float(peak_2)) if peak_1 is not None and peak_2 is not None else None
    return {"split_half_peak_1_hz": peak_1, "split_half_peak_2_hz": peak_2, "split_half_diff_hz": diff}


def _bootstrap(freqs: np.ndarray, spectrum_by_epoch: np.ndarray, spec: dict[str, Any]) -> dict[str, float | None]:
    n_epochs = spectrum_by_epoch.shape[0]
    iterations = int(spec.get("bootstrap_iterations", 0))
    if n_epochs < 4 or iterations <= 0:
        return {"bootstrap_ci_low_hz": None, "bootstrap_ci_high_hz": None, "bootstrap_ci_width_hz": None}
    rng = np.random.default_rng(112358)
    peaks: list[float] = []
    for _ in range(iterations):
        indices = rng.integers(0, n_epochs, size=n_epochs)
        spectrum = np.nanmean(spectrum_by_epoch[indices], axis=0)
        peak = _find_peak(freqs, _smooth_spectrum(spectrum, freqs, float(spec.get("smooth_spectrum_hz", 0))), spec)["peak_hz"]
        if peak is not None:
            peaks.append(float(peak))
    if not peaks:
        return {"bootstrap_ci_low_hz": None, "bootstrap_ci_high_hz": None, "bootstrap_ci_width_hz": None}
    low, high = np.percentile(peaks, [2.5, 97.5])
    return {"bootstrap_ci_low_hz": float(low), "bootstrap_ci_high_hz": float(high), "bootstrap_ci_width_hz": float(high - low)}


def _write_outputs(
    result: dict[str, Any],
    output_dir: Path | str | None,
    subject_id: str,
    session_id: str,
    rhythm_key: str,
    config: dict[str, Any],
) -> RhythmEstimateArtifacts:
    if output_dir is None:
        return RhythmEstimateArtifacts(plot_paths=[])
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    subject = _strip_prefix(subject_id, "sub-")
    session = _strip_prefix(session_id, "ses-")
    basename = f"sub-{subject}_ses-{session}_{rhythm_key}_estimate"
    json_path = output_path / f"{basename}.json"
    csv_path = output_path / f"{basename}.csv"
    with json_path.open("w", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2)
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        fields = [
            "subject_id",
            "session_id",
            "rhythm_key",
            "rhythm_label",
            "reliable",
            "peak_hz_raw",
            "peak_hz_rounded",
            "frequency_to_use_hz",
            "rhythm_source",
            "reason",
            "n_epochs_retained",
            "usable_epoch_fraction",
        ]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerow(
            {
                "subject_id": result["subject_id"],
                "session_id": result["session_id"],
                "rhythm_key": result["rhythm_key"],
                "rhythm_label": result["rhythm_label"],
                "reliable": result["reliable"],
                "peak_hz_raw": result["peak_hz_raw"],
                "peak_hz_rounded": result["peak_hz_rounded"],
                "frequency_to_use_hz": result["frequency_to_use_hz"],
                "rhythm_source": result["rhythm_source"],
                "reason": result["decision"]["reason"],
                "n_epochs_retained": result["reliability"]["n_epochs_retained"],
                "usable_epoch_fraction": result["reliability"]["usable_epoch_fraction"],
            }
        )
    plot_paths = _write_optional_plots(result, output_path, basename, config)
    return RhythmEstimateArtifacts(json_path=json_path, csv_path=csv_path, plot_paths=plot_paths)


def _write_optional_plots(result: dict[str, Any], output_dir: Path, basename: str, config: dict[str, Any]) -> list[Path]:
    if not config.get("qc_outputs", {}).get("write_plots", True):
        return []
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        return []
    paths: list[Path] = []
    freqs = np.asarray(result["spectra"]["frequencies_hz"], dtype=float)
    smoothed = np.asarray([np.nan if value is None else value for value in result["spectra"]["smoothed_db"]], dtype=float)
    raw = np.asarray([np.nan if value is None else value for value in result["spectra"]["mean_db"]], dtype=float)
    spectrum_path = output_dir / f"{basename}_spectrum.png"
    plt.figure(figsize=(7, 4))
    plt.plot(freqs, raw, color="0.65", label="Mean dB")
    plt.plot(freqs, smoothed, color="#0b4f6c", linewidth=2, label="Smoothed")
    if result["reliability"]["candidate_peak_hz"] is not None:
        plt.axvline(result["reliability"]["candidate_peak_hz"], color="#c44536", linestyle="--", label="Candidate peak")
    plt.xlabel("Frequency (Hz)")
    plt.ylabel("Task-evoked power change (dB)")
    plt.title(result["rhythm_label"])
    plt.legend()
    plt.tight_layout()
    plt.savefig(spectrum_path, dpi=160)
    plt.close()
    paths.append(spectrum_path)
    return paths


def _frequency_grid(spec: dict[str, Any]) -> np.ndarray:
    band = spec.get("exploratory_band_hz") or spec.get("primary_band_hz")
    step = float(spec.get("frequency_step_hz", 0.25))
    return np.round(np.arange(float(band[0]), float(band[1]) + step / 2, step), 6)


def _smooth_spectrum(spectrum: np.ndarray, freqs: np.ndarray, width_hz: float) -> np.ndarray:
    if width_hz <= 0 or len(freqs) < 3:
        return spectrum
    step = float(np.nanmedian(np.diff(freqs))) if len(freqs) > 1 else width_hz
    bins = max(1, int(round(width_hz / step)))
    if bins > 1 and bins % 2 == 0:
        bins += 1
    if bins <= 1:
        return spectrum
    kernel = np.ones(bins, dtype=float) / bins
    finite = np.where(np.isfinite(spectrum), spectrum, np.nanmedian(spectrum))
    return np.convolve(finite, kernel, mode="same")


def _time_mask(times: np.ndarray, window: Iterable[float]) -> np.ndarray:
    start, stop = list(window)
    return (times >= float(start)) & (times <= float(stop))


def _records(events: Any) -> list[dict[str, Any]]:
    if isinstance(events, list):
        return [dict(row) for row in events]
    if hasattr(events, "to_dict"):
        return list(events.to_dict(orient="records"))
    raise TypeError("Events must be a list of dicts or a pandas DataFrame.")


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if np.isfinite(numeric) else None


def _optional_float(value: Any) -> float | None:
    numeric = _safe_float(value)
    return numeric


def _infer_sampling_rate(timestamps: np.ndarray) -> float:
    diffs = np.diff(np.asarray(timestamps, dtype=float))
    diffs = diffs[np.isfinite(diffs) & (diffs > 0)]
    if len(diffs) == 0:
        return float("nan")
    return float(1.0 / np.median(diffs))


def _robust_z(values: np.ndarray) -> np.ndarray:
    median = np.nanmedian(values, axis=0, keepdims=True)
    mad = np.nanmedian(np.abs(values - median), axis=0, keepdims=True)
    scale = np.where(mad > 0, mad * 1.4826, np.nanstd(values, axis=0, keepdims=True))
    scale = np.where(scale > 0, scale, 1.0)
    return (values - median) / scale


def _mad(values: np.ndarray) -> float:
    median = np.nanmedian(values)
    return float(np.nanmedian(np.abs(values - median)) * 1.4826)


def _round_frequency(value: float | None, step: float) -> float | None:
    if value is None:
        return None
    if step <= 0:
        return float(value)
    return float(round(float(value) / step) * step)


def _count_items(items: Iterable[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        counts[item] = counts.get(item, 0) + 1
    return counts


def _strip_prefix(value: str, prefix: str) -> str:
    value = str(value)
    return value[len(prefix):] if value.startswith(prefix) else value


def _operator_summary(result: dict[str, Any]) -> str:
    rhythm_name = result["rhythm_label"].replace("_", " ")
    if result["reliable"]:
        return (
            f"{rhythm_name}: {result['frequency_to_use_hz']:.1f} Hz. "
            f"Reliability criteria passed. Use {result['frequency_to_use_hz']:.1f} Hz for tACS."
        )
    return (
        f"{rhythm_name} was unreliable. Reason: {result['decision']['reason']} "
        f"Selected fallback frequency: {result['frequency_to_use_hz']:.1f} Hz."
    )
