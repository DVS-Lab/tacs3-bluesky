#!/usr/bin/env python3
"""Estimate participant-specific task-evoked rhythms from a localizer run."""

from __future__ import annotations

import argparse
from pathlib import Path

from rhythm_estimator import estimate_rhythm_from_files, load_config


DEFAULT_RHYTHMS_BY_TASK = {
    "bandit": ["bandit_feedback_theta", "bandit_decision_beta"],
    "sst": ["sst_stop_theta", "sst_response_beta"],
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _find_latest(base_dir: Path, patterns: list[str]) -> Path | None:
    matches: list[Path] = []
    for pattern in patterns:
        matches.extend(path for path in base_dir.glob(pattern) if path.is_file())
    matches.sort(key=lambda item: item.stat().st_mtime, reverse=True)
    return matches[0] if matches else None


def _auto_find_inputs(subject_id: str, session_id: str, task: str) -> tuple[Path | None, Path | None]:
    subject = subject_id.replace("sub-", "")
    session = session_id.replace("ses-", "")
    subject_dir = _repo_root() / "data" / f"sub-{subject}"
    if task == "sst":
        events = _find_latest(subject_dir, [f"**/*ses-{session}*task-SST*.csv", f"**/*ses-{session}*task-sst*.csv"])
        eeg = _find_latest(subject_dir, [f"**/*ses-{session}*sst*eeg.npz", f"**/*ses-{session}*sst*eeg.csv", f"**/*ses-{session}*localizer*eeg.npz"])
    else:
        events = _find_latest(subject_dir, [f"**/*ses-{session}*run-localizer*task-bandit*.csv", f"**/*ses-{session}*localizer*.csv"])
        eeg = _find_latest(subject_dir, [f"**/*ses-{session}*localizer*eeg.npz", f"**/*ses-{session}*localizer*eeg.csv"])
    return events, eeg


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Estimate task-evoked theta/beta rhythms from localizer EEG.")
    parser.add_argument("--subject", required=True, help="Subject ID with or without sub- prefix.")
    parser.add_argument("--session", required=True, help="Session ID with or without ses- prefix.")
    parser.add_argument("--task", choices=sorted(DEFAULT_RHYTHMS_BY_TASK), default="bandit")
    parser.add_argument("--rhythm", action="append", help="Rhythm key to estimate. Can be repeated.")
    parser.add_argument("--all-defaults", action="store_true", help="Estimate the default rhythm set for the selected task.")
    parser.add_argument("--events", help="Path to localizer behavioral/event CSV or TSV.")
    parser.add_argument("--eeg", help="Path to EEG recording file.")
    parser.add_argument("--config", default=str(Path(__file__).resolve().parent / "config.json"))
    parser.add_argument("--out", help="Output QC directory.")
    parser.add_argument("--auto-find", action="store_true", help="Auto-find latest events and EEG files.")
    parser.add_argument("--run-label", default="run-localizer")
    return parser


def main() -> int:
    args = build_arg_parser().parse_args()
    config = load_config(args.config)
    events_path = Path(args.events) if args.events else None
    eeg_path = Path(args.eeg) if args.eeg else None
    if args.auto_find:
        auto_events, auto_eeg = _auto_find_inputs(args.subject, args.session, args.task)
        events_path = events_path or auto_events
        eeg_path = eeg_path or auto_eeg
    if events_path is None or not events_path.exists():
        raise FileNotFoundError("Could not locate the localizer events CSV/TSV.")
    if eeg_path is None or not eeg_path.exists():
        raise FileNotFoundError("Could not locate the localizer EEG file.")
    rhythms = args.rhythm or []
    if args.all_defaults or not rhythms:
        rhythms = DEFAULT_RHYTHMS_BY_TASK[args.task]
    output_dir = Path(args.out) if args.out else _repo_root() / "data" / f"sub-{args.subject.replace('sub-', '')}" / "qc"
    for rhythm_key in rhythms:
        result, artifacts = estimate_rhythm_from_files(
            subject_id=args.subject,
            session_id=args.session,
            events_path=events_path,
            eeg_path=eeg_path,
            config=config,
            rhythm_key=rhythm_key,
            output_dir=output_dir,
            run_label=args.run_label,
        )
        print(result["operator_summary"])
        if artifacts.json_path:
            print(f"Estimate JSON: {artifacts.json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
