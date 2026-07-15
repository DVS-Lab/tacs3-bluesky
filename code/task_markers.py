"""Shared LSL marker logging utilities for the tACS3 bluesky tasks."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import time
from typing import Any

try:
    import pylsl

    LSL_AVAILABLE = True
except ImportError:  # pragma: no cover - depends on operator environment
    pylsl = None
    LSL_AVAILABLE = False


def lsl_clock() -> float:
    """Return the LSL clock when available, otherwise fall back to wall time."""
    if LSL_AVAILABLE:
        try:
            return float(pylsl.local_clock())
        except Exception:
            return time.time()
    return time.time()


class TaskMarkerLogger:
    """Send task markers over LSL when possible and always keep a JSONL log."""

    def __init__(self, stream_name: str = "LSLOutletStreamName-Markers"):
        self.stream_name = stream_name
        self.outlet = None
        self.events: list[dict[str, Any]] = []
        if LSL_AVAILABLE:
            try:
                info = pylsl.StreamInfo(
                    stream_name,
                    "Markers",
                    1,
                    0,
                    pylsl.cf_int32,
                    f"{stream_name}-source",
                )
                self.outlet = pylsl.StreamOutlet(info)
            except Exception:
                self.outlet = None

    def send(self, marker_code: int, label: str, payload: dict[str, Any] | None = None) -> float:
        marker_time = lsl_clock()
        if self.outlet is not None:
            try:
                self.outlet.push_sample([int(marker_code)], marker_time)
            except Exception:
                pass
        event = {
            "marker_code": int(marker_code),
            "label": label,
            "lsl_time": marker_time,
            "created_at": datetime.utcnow().isoformat(timespec="milliseconds") + "Z",
        }
        if payload:
            event.update(payload)
        self.events.append(event)
        return marker_time

    def save(self, output_path: Path | str) -> None:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8") as handle:
            for event in self.events:
                handle.write(json.dumps(event) + "\n")
