"""Content-aware discovery, identity checks, chronological ordering and exclusions."""
import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from .common import column, digest, flag, numeric


def participant_id(raw):
    """Only documented formatting: sub-, G + digits, and numeric leading zeros.

    Never truncate long numeric IDs (e.g. 1056100000) or do fuzzy matching.
    """
    value = re.sub(r"^sub-", "", str(raw).strip(), flags=re.I)
    value = re.sub(r"^[Gg](?=\d+$)", "", value)
    return str(int(value)) if value.isdigit() else value.lower()


def read_table(path):
    with Path(path).open(encoding="utf-8-sig") as stream:
        header = stream.readline()
    delimiter = "\t" if header.count("\t") > header.count(",") else ","
    return pd.read_csv(path, sep=delimiter, dtype=str, keep_default_na=False), delimiter


def epoch_seconds(value):
    try:
        v = float(value)
        if v > 1e12:
            v /= 1000
        return v if 1e9 < v < 3e9 else np.nan
    except (ValueError, TypeError):
        return np.nan


@dataclass
class Recording:
    meta: dict
    data: pd.DataFrame
    issues: list = field(default_factory=list)


def load_recording(path, root):
    relative = str(path.relative_to(root))
    frame, delimiter = read_table(path)
    match = re.search(r"sub-(.*?)_(?:ses-|task-)", path.name, re.I)
    if not match:
        raise ValueError("cannot parse participant identity")
    raw_id = match[1]
    ses = re.search(r"_ses-(\d+)", path.name)
    suffix = re.fullmatch(r"(.+)-(\d+)", raw_id)
    if not ses and suffix:
        raw_id, session = suffix[1], int(suffix[2])
    else:
        session = int(ses[1]) if ses else None
    identity = participant_id(raw_id)
    issues = []
    body_ids = {participant_id(x) for x in column(frame, "subject_id") if x}
    if body_ids and body_ids != {identity}:
        issues.append("identity_conflict")
    body_ses = {int(re.sub(r"^ses-", "", x)) for x in column(frame, "session_id")
                if re.fullmatch(r"(?:ses-)?\d+", str(x))}
    if session is None and len(body_ses) == 1:
        session = next(iter(body_ses))
    if body_ses and body_ses != {session}:
        issues.append("session_conflict")
    run_match = re.search(r"_run-(\d+)", path.name)
    run = int(run_match[1]) if run_match else 1
    if run_match and "run" in frame:
        body_runs = {int(re.sub(r"^run-", "", x)) for x in frame.run
                     if re.fullmatch(r"(?:run-)?\d+", str(x))}
        if body_runs and body_runs != {run}:
            issues.append("run_conflict")
    task = "bandit" if "task-bandit" in path.name.lower() else "sst"
    phase_match = re.search(r"_(pre-stim|post-stim)_", path.name)
    phase = phase_match[1] if phase_match else (
        "active" if "_events" in path.name else "unlabeled_localizer")
    # Folder provenance takes precedence over the identity heuristic.
    if relative.startswith("pilot_data/"):
        cohort = "pilot"
    elif re.fullmatch(r"1\d{4}", identity):
        cohort = "experimental_candidate"
    elif not identity.isdigit() or len(identity) <= 4:
        cohort = "test"
    else:
        cohort = "unverified_identity"
    trial_col = "trial_num" if task == "bandit" else "trialNumber"
    schema_family = "bandit_slots" if task == "bandit" else (
        "sst_eeg_current_ssd" if "marker_code" in frame else "sst_main_updated_ssd")
    required = ({"trial_num", "choice", "flower1", "flower2", "current_good", "reward", "rt"}
                if task == "bandit" else {"trialNumber", "stop", "response", "rt", "ssd", "go_correct"})
    if not required.issubset(frame.columns):
        issues.append("unsupported_schema:" + ",".join(sorted(required - set(frame.columns))))
    nums = numeric(frame, trial_col)
    if not len(frame):
        issues.append("empty")
    elif nums.isna().any() or not np.array_equal(nums.to_numpy(), np.arange(1, len(frame) + 1)):
        issues.append("trial_sequence_incomplete")
    if column(frame, "localizer").map(flag).eq(True).any():
        issues.append("localizer_flag")
    times = []
    time_source = ""
    for key in (["trial_start_unix_time", "choice_onset_unix_time", "feedback_onset_unix_time"]
                if task == "bandit" else ["stim_onset_unix_time", "stim_onset"]):
        values = column(frame, key).map(epoch_seconds).dropna()
        if len(values):
            times = values.tolist()
            time_source = key
            if (np.diff(times) <= 0).any():
                issues.append("nonmonotonic_onsets")
            break
    filename_time = re.search(r"(\d{4}-\d\d-\d\d_\d\d-\d\d-\d\d)", path.name)
    file_date = filename_time[1][:10] if filename_time else ""
    start = min(times) if times else np.nan
    end = np.nan
    for key in ["run_end_unix_time", "iti_offset", "feedback_onset_unix_time"]:
        vals = column(frame, key).map(epoch_seconds).dropna()
        if len(vals):
            end = max(vals)
            break
    duration = np.nan
    if {"run_end_task_time", "run_start_task_time"}.issubset(frame.columns):
        duration = numeric(frame, "run_end_task_time").max() - numeric(frame, "run_start_task_time").min()
    if not np.isfinite(duration) and np.isfinite(end) and times:
        starts = column(frame, "run_start_unix_time").map(epoch_seconds).dropna()
        starts2 = column(frame, "run_start_unix").map(epoch_seconds).dropna()
        duration = end - (min(starts) if len(starts) else min(starts2) if len(starts2) else start)
    if not times:
        issues.append("no_unix_clock_for_cross_task_order")
    expected = 91 if schema_family == "sst_main_updated_ssd" and file_date >= "2026-10-01" and phase == "active" else np.nan
    if np.isfinite(expected) and len(frame) != expected:
        issues.append("unexpected_trial_count")
    # Content equality, irrespective of delimiter/extension or file location.
    canonical = json.dumps({"columns": sorted(frame.columns),
                            "rows": frame.reindex(columns=sorted(frame.columns)).values.tolist()}, sort_keys=True)
    semantic_hash = hashlib.sha256(canonical.encode()).hexdigest()
    meta = dict(participant=identity, raw_participant=raw_id, session=session, task=task,
                phase=phase, run=run, source_file=relative, cohort=cohort,
                sha256=digest(path), semantic_sha256=semantic_hash,
                schema_family=schema_family, schema_hash=hashlib.sha256("|".join(frame.columns).encode()).hexdigest()[:12],
                acquisition_version="not_recorded;schema_family_only",
                delimiter="tab" if delimiter == "\t" else "comma", trial_count=len(frame),
                collection_date=file_date, filename_timestamp=filename_time[1] if filename_time else "",
                start_unix_s=start, end_unix_s=end, duration_s=duration, time_source=time_source,
                expected_trial_count=expected, selected=False, exclusion_reason="")
    return Recording(meta, frame, issues)


def discover(root):
    records = []
    for folder in ["data", "pilot_data", "stimulation/pre-stimulation-participant-responses"]:
        for path in sorted((root / folder).rglob("*")):
            if path.suffix.lower() not in {".csv", ".tsv"} or not re.search(r"_task-(bandit|sst)_", path.name, re.I):
                continue
            try:
                records.append(load_recording(path, root))
            except (ValueError, OSError, pd.errors.ParserError) as error:
                records.append(Recording(dict(source_file=str(path.relative_to(root)), sha256=digest(path),
                                              selected=False, exclusion_reason="read_error:" + str(error),
                                              task="unknown", cohort="unknown", trial_count=0), pd.DataFrame(), ["read_error"]))
    return records


def adjudicate(records, path):
    """Optional explicit local decisions, bound to source bytes; never edit raw data."""
    if path is None:
        return
    decisions, _ = read_table(path)
    required = {"source_file", "sha256", "decision", "reason"}
    if not required.issubset(decisions) or decisions.source_file.duplicated().any():
        raise ValueError("adjudications require unique source_file, sha256, decision, reason")
    by_source = {rec.meta["source_file"]: rec for rec in records}
    for _, decision in decisions.iterrows():
        if decision.source_file not in by_source or not decision.reason.strip():
            raise ValueError("unknown source or missing reason in adjudications")
        rec = by_source[decision.source_file]
        if decision.sha256 != rec.meta["sha256"] or decision.decision not in {"include", "exclude"}:
            raise ValueError("adjudication hash mismatch or invalid decision")
        if decision.decision == "include":
            if rec.meta["exclusion_reason"] not in {"", "ambiguous_repeated_complete_run"}:
                raise ValueError("cannot override structural or incomplete-recording exclusions")
            rec.meta.update(selected=True, exclusion_reason="", qc_status="warning")
        else:
            rec.meta.update(selected=False, exclusion_reason="local_adjudication:" + decision.reason, qc_status="excluded")
        rec.meta["adjudication_reason"] = decision.reason
    chosen = [rec for rec in records if rec.meta["selected"]]
    keys = [tuple(rec.meta.get(k) for k in ["participant", "session", "task", "phase", "run", "collection_date"]) for rec in chosen]
    if len(keys) != len(set(keys)):
        raise ValueError("adjudications selected multiple attempts for the same run")


def select_records(records, config):
    """Deduplicate exact exports, then accept one complete attempt, else quarantine.

    Multiple complete attempts remain ambiguous. No timestamp/mtime tie breaking.
    """
    hashes = {}
    for rec in sorted(records, key=lambda r: (not r.meta["source_file"].startswith("data/"),
                                             not r.meta["source_file"].startswith("pilot_data/"), r.meta["source_file"])):
        m = rec.meta
        h = m.get("semantic_sha256")
        if h and h in hashes:
            m["exclusion_reason"] = "duplicate_export_of:" + hashes[h]
        elif h:
            hashes[h] = m["source_file"]
    grouped = {}
    for rec in records:
        m = rec.meta
        if m.get("exclusion_reason"):
            continue
        fatal = [x for x in rec.issues if x in {"empty", "trial_sequence_incomplete", "identity_conflict", "session_conflict", "run_conflict", "nonmonotonic_onsets"}
                 or x.startswith("unsupported_schema")]
        if fatal:
            m["exclusion_reason"] = ";".join(fatal)
            continue
        if "unexpected_trial_count" in rec.issues:
            m["exclusion_reason"] = "incomplete_or_unexpected_trial_count"
            continue
        if m["task"] == "bandit":
            if m["trial_count"] < config["bandit"]["min_trials"]:
                m["exclusion_reason"] = "too_few_bandit_trials"
                continue
            if m["phase"] == "active" and m["cohort"] == "experimental_candidate":
                dur = m["duration_s"]
                if not np.isfinite(dur) or abs(dur - config["bandit"]["active_duration_s"]) > config["bandit"]["duration_tolerance_s"]:
                    m["exclusion_reason"] = "active_duration_incomplete_or_unverified"
                    continue
        # Split dates to avoid merging unrelated days reusing the same session label.
        key = tuple(m.get(k) for k in ["participant", "session", "task", "phase", "run", "collection_date"])
        grouped.setdefault(key, []).append(rec)
    for group in grouped.values():
        if len(group) > 1:
            for rec in group:
                rec.meta["exclusion_reason"] = "ambiguous_repeated_complete_run"
        else:
            group[0].meta["selected"] = True
    for rec in records:
        rec.meta["qc_status"] = "excluded" if not rec.meta["selected"] else "warning" if rec.issues else "pass"
        rec.meta["qc_flags"] = ";".join(rec.issues)
        rec.data["source_file"] = rec.meta["source_file"]
    return records
