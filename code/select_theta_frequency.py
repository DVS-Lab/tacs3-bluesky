"""Backward-compatible helper for selecting feedback-locked theta frequency."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from select_stimulation_frequency import (
    RhythmSelectionDecision as ThetaSelectionDecision,
    find_estimate_files,
    select_stimulation_frequency as _select_stimulation_frequency,
)


def find_theta_estimate_files(
    subject_id: str,
    session_id: str | None = None,
    search_root: Path | str | None = None,
) -> list[Path]:
    return find_estimate_files(subject_id, session_id, "bandit_feedback_theta", search_root)


def select_stimulation_frequency(
    subject_id: str,
    session_id: str,
    config: dict[str, Any],
    *,
    theta_estimate_file: Path | str | None = None,
    search_root: Path | str | None = None,
    manual_override_hz: float | None = None,
    manual_override_reason: str | None = None,
) -> ThetaSelectionDecision:
    return _select_stimulation_frequency(
        subject_id,
        session_id,
        config,
        rhythm_key="bandit_feedback_theta",
        estimate_file=theta_estimate_file,
        search_root=search_root,
        manual_override_hz=manual_override_hz,
        manual_override_reason=manual_override_reason,
    )
