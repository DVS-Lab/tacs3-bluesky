"""Select individualized or fallback stimulation frequencies from QC JSON files."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Iterable


@dataclass
class RhythmSelectionDecision:
    subject_id: str
    session_id: str
    rhythm_key: str
    rhythm_label: str
    frequency_to_use_hz: float | None
    rhythm_source: str
    reliable: bool
    reason: str
    estimate_file: str | None
    intended_protocol_label: str
    manual_override_used: bool = False
    manual_override_reason: str | None = None

    @property
    def theta_source(self) -> str:
        return self.rhythm_source if "theta" in self.rhythm_key else "none"

    def to_log_dict(self) -> dict[str, Any]:
        log = {
            "rhythm_key": self.rhythm_key,
            "rhythm_label": self.rhythm_label,
            "rhythm_source": self.rhythm_source,
            "rhythm_reliable": self.reliable,
            "rhythm_reliability_reason": self.reason,
            "rhythm_estimate_file": self.estimate_file or "",
            "frequency_to_use_hz": self.frequency_to_use_hz,
            "protocol_label_to_show": self.intended_protocol_label,
            "manual_override_used": self.manual_override_used,
            "manual_override_reason": self.manual_override_reason or "",
        }
        if "theta" in self.rhythm_key:
            log.update(
                {
                    "theta_source": self.rhythm_source,
                    "theta_reliable": self.reliable,
                    "theta_reliability_reason": self.reason,
                    "theta_estimate_file": self.estimate_file or "",
                }
            )
        else:
            log.update(
                {
                    "theta_source": "none",
                    "theta_reliable": False,
                    "theta_reliability_reason": "",
                    "theta_estimate_file": "",
                    "beta_source": self.rhythm_source,
                    "beta_reliable": self.reliable,
                    "beta_reliability_reason": self.reason,
                    "beta_estimate_file": self.estimate_file or "",
                }
            )
        return log


def select_stimulation_frequency(
    subject_id: str,
    session_id: str,
    config: dict[str, Any],
    *,
    rhythm_key: str = "bandit_feedback_theta",
    estimate_file: Path | str | None = None,
    theta_estimate_file: Path | str | None = None,
    search_root: Path | str | None = None,
    manual_override_hz: float | None = None,
    manual_override_reason: str | None = None,
) -> RhythmSelectionDecision:
    if theta_estimate_file is not None and estimate_file is None:
        estimate_file = theta_estimate_file
    spec = config.get("rhythm_estimands", {}).get(rhythm_key)
    if spec is None:
        spec = _legacy_theta_spec(config)
    selection_config = config.get("stimulation_frequency_selection", {})
    valid_range = _valid_range(selection_config, spec)
    fallback_hz = _fallback_hz(selection_config, spec)
    rhythm_label = str(spec.get("label", rhythm_key))

    if manual_override_hz is not None:
        if not selection_config.get("manual_override_allowed", True):
            raise ValueError("Manual override is disabled in config.")
        if selection_config.get("manual_override_requires_reason", True) and not manual_override_reason:
            raise ValueError("Manual override requires a reason.")
        if not (valid_range[0] <= float(manual_override_hz) <= valid_range[1]):
            raise ValueError(
                f"Manual override {manual_override_hz:.2f} Hz is outside the valid range "
                f"{valid_range[0]:.1f}-{valid_range[1]:.1f} Hz for {rhythm_key}."
            )
        source = "manual_override"
        return RhythmSelectionDecision(
            subject_id=subject_id,
            session_id=session_id,
            rhythm_key=rhythm_key,
            rhythm_label=rhythm_label,
            frequency_to_use_hz=float(manual_override_hz),
            rhythm_source=source,
            reliable=False,
            reason=f"Manual override applied: {manual_override_reason}",
            estimate_file=str(estimate_file) if estimate_file else None,
            intended_protocol_label=_protocol_label(rhythm_key, float(manual_override_hz), source),
            manual_override_used=True,
            manual_override_reason=manual_override_reason,
        )

    if estimate_file is None:
        matches = find_estimate_files(subject_id, session_id, rhythm_key, search_root)
        estimate_file = matches[0] if matches else None

    if estimate_file is None:
        stop_key = "stop_if_no_theta_file" if "theta" in rhythm_key else "stop_if_no_rhythm_file"
        if selection_config.get(stop_key, False):
            raise FileNotFoundError(f"No {rhythm_key} estimate file found for sub-{subject_id}, ses-{session_id}.")
        source = spec.get("fallback_source", "fallback_fixed")
        return RhythmSelectionDecision(
            subject_id=subject_id,
            session_id=session_id,
            rhythm_key=rhythm_key,
            rhythm_label=rhythm_label,
            frequency_to_use_hz=fallback_hz,
            rhythm_source=source,
            reliable=False,
            reason=f"No {rhythm_key} estimate file found. Using fixed {fallback_hz:.1f} Hz fallback.",
            estimate_file=None,
            intended_protocol_label=_protocol_label(rhythm_key, fallback_hz, source),
        )

    estimate = _load_json(Path(estimate_file))
    reliable = bool(estimate.get("reliable", False))
    reason = (
        estimate.get("decision", {}).get("reason")
        or estimate.get("rhythm_reliability_reason")
        or estimate.get("theta_reliability_reason")
        or "Frequency selection loaded from estimate file."
    )
    candidate = _first_float(
        estimate.get("frequency_to_use_hz"),
        estimate.get("peak_hz_rounded"),
        estimate.get("itheta_hz_rounded"),
        estimate.get("ibeta_hz_rounded"),
        estimate.get("peak_hz_raw"),
    )

    if reliable and selection_config.get("use_individualized_if_reliable", True) and candidate is not None:
        if valid_range[0] <= candidate <= valid_range[1]:
            source = str(estimate.get("rhythm_source") or estimate.get("theta_source") or spec.get("reliable_source", "reliable_individualized"))
            return RhythmSelectionDecision(
                subject_id=subject_id,
                session_id=session_id,
                rhythm_key=rhythm_key,
                rhythm_label=str(estimate.get("rhythm_label") or rhythm_label),
                frequency_to_use_hz=float(candidate),
                rhythm_source=source,
                reliable=True,
                reason=reason,
                estimate_file=str(estimate_file),
                intended_protocol_label=_protocol_label(rhythm_key, float(candidate), source),
            )
        reliable = False
        reason = f"Estimate suggested {candidate:.2f} Hz, outside valid range {valid_range[0]:.1f}-{valid_range[1]:.1f} Hz."

    fallback_policy = selection_config.get("fallback_if_unreliable", "fixed")
    if fallback_policy in {"fixed", "fixed_6hz", "fixed_beta"}:
        source = spec.get("fallback_source", "fallback_fixed")
        return RhythmSelectionDecision(
            subject_id=subject_id,
            session_id=session_id,
            rhythm_key=rhythm_key,
            rhythm_label=rhythm_label,
            frequency_to_use_hz=fallback_hz,
            rhythm_source=source,
            reliable=False,
            reason=reason,
            estimate_file=str(estimate_file),
            intended_protocol_label=_protocol_label(rhythm_key, fallback_hz, source),
        )
    raise ValueError(f"{rhythm_key} estimate was unreliable and fixed-frequency fallback is disabled.")


def find_estimate_files(
    subject_id: str,
    session_id: str | None,
    rhythm_key: str,
    search_root: Path | str | None = None,
) -> list[Path]:
    if search_root is None:
        search_root = Path(__file__).resolve().parent.parent / "data"
    search_root = Path(search_root)
    subject = str(subject_id).replace("sub-", "")
    session = str(session_id).replace("ses-", "") if session_id else None
    subject_dir = search_root / f"sub-{subject}"
    patterns = []
    if session:
        patterns.append(f"**/*ses-{session}*{rhythm_key}*estimate*.json")
        if "theta" in rhythm_key:
            patterns.append(f"**/*ses-{session}*theta_estimate*.json")
    patterns.append(f"**/*{rhythm_key}*estimate*.json")
    if "theta" in rhythm_key:
        patterns.append("**/*theta_estimate*.json")
    matches: list[Path] = []
    for pattern in patterns:
        for path in subject_dir.glob(pattern):
            if path.is_file() and path not in matches:
                matches.append(path)
    matches.sort(key=lambda item: item.stat().st_mtime, reverse=True)
    return matches


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _valid_range(selection_config: dict[str, Any], spec: dict[str, Any]) -> tuple[float, float]:
    rhythm = str(spec.get("rhythm", "theta"))
    key = "valid_beta_range_hz" if rhythm == "beta" else "valid_theta_range_hz"
    return _as_float_range(selection_config.get(key, spec.get("primary_band_hz", [4.0, 8.0])))


def _fallback_hz(selection_config: dict[str, Any], spec: dict[str, Any]) -> float:
    rhythm = str(spec.get("rhythm", "theta"))
    if rhythm == "beta":
        return float(spec.get("fallback_frequency_hz", selection_config.get("default_fixed_beta_hz", 20.0)))
    return float(spec.get("fallback_frequency_hz", selection_config.get("default_fixed_theta_hz", 6.0)))


def _as_float_range(values: Iterable[float]) -> tuple[float, float]:
    first, second = list(values)[:2]
    return float(first), float(second)


def _first_float(*values: Any) -> float | None:
    for value in values:
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _protocol_label(rhythm_key: str, frequency_hz: float | None, source: str) -> str:
    if frequency_hz is None:
        return "NO_STIMULATION"
    if "beta" in rhythm_key:
        prefix = "IBETA_TACS" if source.startswith("reliable") else "FIXED_BETA_TACS"
    else:
        prefix = "ITHETA_TACS" if source.startswith("reliable") else "FIXED_THETA_TACS"
    if "fallback" in source:
        return f"{prefix}_{frequency_hz:.1f}Hz_FALLBACK"
    return f"{prefix}_{frequency_hz:.1f}Hz"


def _legacy_theta_spec(config: dict[str, Any]) -> dict[str, Any]:
    theta = config.get("theta_estimation", {})
    return {
        "label": theta.get("theta_label", "participant_specific_feedback_theta"),
        "rhythm": "theta",
        "primary_band_hz": theta.get("primary_theta_band_hz", [4.0, 8.0]),
        "fallback_frequency_hz": theta.get("default_fixed_theta_hz", 6.0),
        "fallback_source": "fallback_fixed_6hz",
        "reliable_source": "reliable_itheta",
    }
