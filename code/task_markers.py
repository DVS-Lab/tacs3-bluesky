"""Shared LSL marker logging utilities for the tACS3 bluesky tasks."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import queue
import threading
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


class LSLStimulationTrigger:
    """Listens for NIC-2 stimulation start/stop markers over LSL.

    Marker 203 is used by NIC-2 to mean "stimulation is starting" for both
    active and sham protocols, so listening for it lets a task auto-start
    in sync with the experimenter clicking Go on the stimulation machine,
    without the task knowing which condition is running.
    """

    RAMP_UP_START = 201
    RAMP_DOWN_START = 202
    STIMULATION_START = 203
    STIMULATION_STOP = 204
    TASK_START_MARKER = 203

    def __init__(self):
        self.inlet = None
        self.listening = False
        self.marker_queue: queue.Queue = queue.Queue()
        self.listener_thread: threading.Thread | None = None

    def connect(self) -> bool:
        if not LSL_AVAILABLE:
            print("LSL: pylsl not available; the task will only start on SPACE.")
            return False
        try:
            streams = pylsl.resolve_streams(wait_time=5.0)
            marker_streams = [s for s in streams if s.type() == "Markers"]
            chosen = marker_streams[0] if marker_streams else (streams[0] if streams else None)
            if chosen is None:
                print("LSL: no marker streams found; the task will only start on SPACE.")
                return False
            self.inlet = pylsl.StreamInlet(chosen)
            print(f"LSL: connected to marker stream '{chosen.name()}'.")
            return True
        except Exception as exc:
            print(f"LSL: failed to connect to marker stream: {exc}")
            return False

    def start_listening(self) -> None:
        if self.listening or self.inlet is None:
            return
        self.listening = True
        self.listener_thread = threading.Thread(target=self._listen_loop, daemon=True)
        self.listener_thread.start()

    def stop_listening(self) -> None:
        self.listening = False
        if self.listener_thread:
            self.listener_thread.join(timeout=1.0)

    def _listen_loop(self) -> None:
        while self.listening:
            try:
                marker, timestamp = self.inlet.pull_sample(timeout=0.1)
                if marker:
                    self.marker_queue.put((int(marker[0]), timestamp))
            except Exception:
                time.sleep(0.1)

    def check_for_stimulation_stop(self) -> bool:
        try:
            while True:
                marker_code, _ = self.marker_queue.get_nowait()
                if marker_code == self.STIMULATION_STOP:
                    return True
        except queue.Empty:
            pass
        return False
