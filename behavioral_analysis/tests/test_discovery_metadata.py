from pathlib import Path

import pandas as pd
import pytest

from behavioral_analysis.discovery import discover, select_records, participant_id, load_recording
from behavioral_analysis.metadata import condition_key
from .conftest import main_sst, bandit_frame


def event_path(tmp_path, timestamp="16-00-00", extension="csv", participant="10029"):
    folder = tmp_path / "data" / ("sub-" + participant)
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"sub-{participant}_ses-2_run-2_task-SST_2026-10-20_{timestamp}_events.{extension}"


def test_csv_tsv_exact_duplicate_and_incomplete_restart(tmp_path, config):
    full = main_sst()
    full.to_csv(event_path(tmp_path), index=False)
    full.to_csv(event_path(tmp_path, extension="tsv"), index=False, sep="\t")
    full.iloc[:10].to_csv(event_path(tmp_path, "15-59-00"), index=False)
    records = select_records(discover(tmp_path), config)
    assert sum(r.meta["selected"] for r in records) == 1
    reasons = [r.meta["exclusion_reason"] for r in records]
    assert any(x.startswith("duplicate_export_of:") for x in reasons)
    assert "incomplete_or_unexpected_trial_count" in reasons


def test_two_complete_attempts_quarantined(tmp_path, config):
    raw = main_sst()
    raw.to_csv(event_path(tmp_path), index=False)
    raw["stim_onset"] = pd.to_numeric(raw.stim_onset) + 1000
    raw.to_csv(event_path(tmp_path, "16-20-00"), index=False)
    records = select_records(discover(tmp_path), config)
    assert not any(r.meta["selected"] for r in records)
    assert all(r.meta["exclusion_reason"] == "ambiguous_repeated_complete_run" for r in records)


def test_content_delimiter_overrides_extension(tmp_path):
    p = event_path(tmp_path)
    main_sst().to_csv(p, sep="\t", index=False)
    rec = load_recording(p, tmp_path)
    assert rec.meta["delimiter"] == "tab"
    assert rec.meta["trial_count"] == 91


@pytest.mark.parametrize("raw,expected", [("sub-G010029", "10029"), ("010579", "10579"), ("1056100000", "1056100000"), ("avi-pilot", "avi-pilot")])
def test_identity_formatting_only(raw, expected):
    assert participant_id(raw) == expected


def test_filename_body_conflict_excluded(tmp_path, config):
    raw = main_sst()
    raw["subject_id"] = "sub-11450"
    raw.to_csv(event_path(tmp_path), index=False)
    rec = select_records(discover(tmp_path), config)[0]
    assert not rec.meta["selected"]
    assert "identity_conflict" in rec.meta["exclusion_reason"]


def test_missing_trial_not_bridged_or_sorted_away(tmp_path, config):
    raw = main_sst().drop(index=10)
    raw.to_csv(event_path(tmp_path), index=False)
    rec = select_records(discover(tmp_path), config)[0]
    assert "trial_sequence_incomplete" in rec.meta["exclusion_reason"]


def test_condition_key_requires_evidence_and_rejects_conflicts(tmp_path):
    path = tmp_path / "key.csv"
    pd.DataFrame([dict(participant="G10029", session=2, counterbalance="A", intended_condition="theta", condition_evidence="coordinator")]).to_csv(path, index=False)
    with pytest.raises(ValueError, match="conflicts"):
        condition_key(path)
    pd.DataFrame([dict(participant="G10029", session=2, counterbalance="A", condition_evidence="coordinator")]).to_csv(path, index=False)
    key = condition_key(path)
    assert key.intended_condition.iloc[0] == "beta"
    assert key.participant.iloc[0] == "10029"


def test_no_key_does_not_infer_condition():
    assert condition_key(None).empty
