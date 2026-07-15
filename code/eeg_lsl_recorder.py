"""
Utilities for recording StarStim EEG over Lab Streaming Layer during the localizer.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import csv
import json
from pathlib import Path
import threading
import time
from typing import Any, Dict, List, Optional

import numpy as np

try:
    import pylsl

    PYLsl_AVAILABLE = True
except ImportError:  # pragma: no cover - depends on operator environment
    pylsl = None
    PYLsl_AVAILABLE = False


class EEGRecordingError(RuntimeError):
    """Raised when EEG recording cannot proceed."""


@dataclass
class EEGRecordingSummary:
    status: str
    stream_name: Optional[str]
    stream_type: Optional[str]
    sampling_rate_hz: Optional[float]
    channel_names: List[str]
    n_samples: int
    start_lsl_time: Optional[float]
    end_lsl_time: Optional[float]
    output_npz: Optional[str] = None
    output_csv: Optional[str] = None
    output_metadata_json: Optional[str] = None
    message: Optional[str] = None


def _extract_channel_names(stream_info: Any) -> List[str]:
    names: List[str] = []
    try:
        desc = stream_info.desc()
        channels = desc.child("channels")
        child = channels.child("channel")
        while child and child.name():
            label = child.child_value("label") or child.child_value("name")
            names.append(label or f"ch{len(names) + 1}")
            child = child.next_sibling()
    except Exception:
        names = []

    if not names:
        names = [f"ch{i + 1}" for i in range(stream_info.channel_count())]
    return names


class LSLEEGRecorder:
    """
    Lightweight EEG recorder for preferred StarStim LSL streams.
    """

    def __init__(
        self,
        *,
        preferred_stream_type: str = "EEG",
        preferred_stream_name_contains: Optional[str] = "StarStim",
        resolve_timeout_sec: float = 5.0,
    ):
        self.preferred_stream_type = preferred_stream_type
        self.preferred_stream_name_contains = preferred_stream_name_contains
        self.resolve_timeout_sec = resolve_timeout_sec

        self.stream_info = None
        self.inlet = None
        self.channel_names: List[str] = []
        self.samples: List[List[float]] = []
        self.timestamps: List[float] = []
        self.recording = False
        self.recording_thread: Optional[threading.Thread] = None
        self.start_lsl_time: Optional[float] = None
        self.end_lsl_time: Optional[float] = None
        self.status_message: Optional[str] = None

    def resolve_stream(self) -> bool:
        if not PYLsl_AVAILABLE:
            self.status_message = "pylsl is not installed; cannot subscribe to live EEG."
            return False

        streams = pylsl.resolve_streams(wait_time=self.resolve_timeout_sec)
        if not streams:
            self.status_message = "No LSL streams were found."
            return False

        preferred = []
        secondary = []
        name_hint = (self.preferred_stream_name_contains or "").lower()
        for stream in streams:
            stream_type = (stream.type() or "").lower()
            stream_name = (stream.name() or "").lower()
            if self.preferred_stream_type and stream_type == self.preferred_stream_type.lower():
                if not name_hint or name_hint in stream_name:
                    preferred.append(stream)
                else:
                    secondary.append(stream)

        chosen = preferred[0] if preferred else (secondary[0] if secondary else None)
        if chosen is None:
            self.status_message = (
                f"No matching EEG stream was found for type={self.preferred_stream_type!r} "
                f"and name containing {self.preferred_stream_name_contains!r}."
            )
            return False

        self.stream_info = chosen
        self.channel_names = _extract_channel_names(chosen)
        self.inlet = pylsl.StreamInlet(chosen, max_buflen=360, max_chunklen=256)
        self.status_message = f"Connected to EEG stream '{chosen.name()}'."
        return True

    def start(self) -> bool:
        if not self.resolve_stream():
            return False
        self.recording = True
        self.start_lsl_time = float(pylsl.local_clock()) if PYLsl_AVAILABLE else time.time()
        self.recording_thread = threading.Thread(target=self._record_loop, daemon=True)
        self.recording_thread.start()
        return True

    def _record_loop(self) -> None:
        assert self.inlet is not None
        while self.recording:
            try:
                chunk, timestamps = self.inlet.pull_chunk(timeout=0.2, max_samples=256)
                if chunk:
                    self.samples.extend(chunk)
                    self.timestamps.extend(timestamps)
            except Exception as exc:  # pragma: no cover - depends on hardware transport
                self.status_message = f"EEG recording stopped after an LSL error: {exc}"
                self.recording = False

    def stop(self) -> EEGRecordingSummary:
        self.recording = False
        if self.recording_thread is not None:
            self.recording_thread.join(timeout=2.0)
        self.end_lsl_time = float(pylsl.local_clock()) if PYLsl_AVAILABLE else time.time()

        stream_name = None
        stream_type = None
        sampling_rate_hz = None
        if self.stream_info is not None:
            stream_name = self.stream_info.name()
            stream_type = self.stream_info.type()
            sampling_rate_hz = float(self.stream_info.nominal_srate())

        return EEGRecordingSummary(
            status="recorded" if self.samples else "no_samples",
            stream_name=stream_name,
            stream_type=stream_type,
            sampling_rate_hz=sampling_rate_hz,
            channel_names=self.channel_names,
            n_samples=len(self.samples),
            start_lsl_time=self.start_lsl_time,
            end_lsl_time=self.end_lsl_time,
            message=self.status_message,
        )

    def save(
        self,
        output_dir: Path | str,
        basename: str,
        *,
        write_raw_csv: bool = True,
        write_raw_npz: bool = True,
        extra_metadata: Optional[Dict[str, Any]] = None,
    ) -> EEGRecordingSummary:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        summary = self.stop()

        metadata: Dict[str, Any] = {
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "status": summary.status,
            "stream_name": summary.stream_name,
            "stream_type": summary.stream_type,
            "sampling_rate_hz": summary.sampling_rate_hz,
            "channel_names": summary.channel_names,
            "n_samples": summary.n_samples,
            "start_lsl_time": summary.start_lsl_time,
            "end_lsl_time": summary.end_lsl_time,
            "message": summary.message,
        }
        if extra_metadata:
            metadata.update(extra_metadata)

        samples = np.asarray(self.samples, dtype=float) if self.samples else np.empty((0, 0))
        timestamps = np.asarray(self.timestamps, dtype=float) if self.timestamps else np.empty((0,))

        if write_raw_npz:
            npz_path = output_dir / f"{basename}.npz"
            np.savez_compressed(
                npz_path,
                samples=samples,
                timestamps=timestamps,
                channel_names=np.asarray(summary.channel_names, dtype=object),
                sampling_rate_hz=np.asarray([summary.sampling_rate_hz or np.nan], dtype=float),
                metadata_json=json.dumps(metadata),
            )
            summary.output_npz = str(npz_path)

        if write_raw_csv:
            csv_path = output_dir / f"{basename}.csv"
            with csv_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(["lsl_timestamp", *summary.channel_names])
                for ts, row in zip(timestamps, samples):
                    writer.writerow([ts, *row.tolist()])
            summary.output_csv = str(csv_path)

        metadata_path = output_dir / f"{basename}_metadata.json"
        with metadata_path.open("w", encoding="utf-8") as handle:
            json.dump(metadata, handle, indent=2)
        summary.output_metadata_json = str(metadata_path)

        return summary

    def fail_summary(self) -> EEGRecordingSummary:
        return EEGRecordingSummary(
            status="unavailable",
            stream_name=None,
            stream_type=None,
            sampling_rate_hz=None,
            channel_names=[],
            n_samples=0,
            start_lsl_time=None,
            end_lsl_time=None,
            message=self.status_message,
        )


def save_recording_summary(summary: EEGRecordingSummary, output_path: Path | str) -> None:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(asdict(summary), handle, indent=2)
