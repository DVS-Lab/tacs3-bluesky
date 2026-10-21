import json
import os
from pathlib import Path

import pandas as pd
import pytest

from behavioral_analysis.common import digest, write_csv
from behavioral_analysis.discovery import adjudicate, discover, select_records
from behavioral_analysis.design import paired_differences
from behavioral_analysis.pipeline import run
from .conftest import bandit_frame, main_sst


def synthetic_repository(root):
    folder = root / "data/sub-10029"
    folder.mkdir(parents=True)
    for run_number in [1, 2]:
        raw = main_sst()
        # Distinct actual onsets: do not use copied content as a second run.
        for col in ["stim_onset", "stop_onset", "iti_offset", "run_start_unix"]:
            values = pd.to_numeric(raw[col], errors="coerce")
            raw[col] = (values + run_number * 1000).where(values.notna(), "")
        raw.to_csv(folder / f"sub-10029_ses-1_run-{run_number}_task-SST_2026-10-20_16-{run_number}0-00_events.csv", index=False)
        b = bandit_frame([1] * 100 + [2] * 100, [True, False] * 100)
        b["run_start_task_time"] = 0
        b["run_end_task_time"] = 601
        b["trial_start_unix_time"] = [1790000000000 + 3000 * i + 1000000 * run_number for i in range(200)]
        b.to_csv(folder / f"sub-10029_ses-1_run-{run_number}_task-bandit_2026-10-20_15-{run_number}0-00_events.csv", index=False)


def test_full_pipeline_source_integrity_and_outputs(tmp_path):
    root = tmp_path / "repo"
    synthetic_repository(root)
    before = {str(p): digest(p) for p in root.rglob("*.csv")}
    output = tmp_path / "derived"
    summary = run(root, output, make_figures=False)
    assert summary["n_experimental_candidate_participants"] == 1
    assert summary["n_selected_active_sst_runs"] == 2
    assert summary["n_eligible_session_ssrt"] == 1
    assert before == {str(p): digest(p) for p in root.rglob("*.csv")}
    for name in ["report.html", "manifest.csv", "collection_warnings.txt", "sst_qc.html", "participant_session_qc.csv", "provenance.json"]:
        assert (output / name).is_file()
    assert json.loads((output / "provenance.json").read_text())["source_integrity_verified"]
    assert pd.read_csv(output / "paired_differences.csv").empty


def test_source_output_overlap_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="overlap"):
        run(tmp_path, tmp_path / "data/derived")


@pytest.mark.parametrize("available", ["bandit", "sst", "only_aborted"])
def test_partial_and_entirely_excluded_task_coverage(tmp_path, available):
    root = tmp_path / "repo"
    synthetic_repository(root)
    for path in (root / "data").rglob("*.csv"):
        if available == "bandit" and "task-SST" in path.name:
            path.unlink()
        elif available == "sst" and "task-bandit" in path.name:
            path.unlink()
        elif available == "only_aborted":
            if "task-bandit" in path.name:
                path.unlink()
            else:
                pd.read_csv(path).iloc[:5].to_csv(path, index=False)
    output = tmp_path / "derived"
    summary = run(root, output, make_figures=False)
    if available == "only_aborted":
        assert summary["n_selected_files"] == 0
        assert not pd.read_csv(output / "participant_session_qc.csv").empty
    else:
        assert summary["n_selected_files"] == 2
    assert (output / "report.html").is_file()


def test_csv_preserves_submillisecond_unix_timing(tmp_path):
    value = 1792528175.428123
    write_csv(pd.DataFrame({"start_unix_s": [value]}), tmp_path / "timestamps.csv")
    result = pd.read_csv(tmp_path / "timestamps.csv").start_unix_s.iloc[0]
    assert abs(result - value) < .000001


def test_adjudication_is_hash_bound_and_unambiguous(tmp_path, config):
    synthetic_repository(tmp_path)
    records = select_records(discover(tmp_path), config)
    selected = next(x for x in records if x.meta["task"] == "sst")
    path = tmp_path / "adjudications.csv"
    row = dict(source_file=selected.meta["source_file"], sha256="wrong", decision="exclude", reason="test review")
    pd.DataFrame([row]).to_csv(path, index=False)
    with pytest.raises(ValueError, match="hash"):
        adjudicate(records, path)
    row["sha256"] = selected.meta["sha256"]
    pd.DataFrame([row]).to_csv(path, index=False)
    adjudicate(records, path)
    assert not selected.meta["selected"]


def test_paired_differences_preserve_within_participant_estimand():
    rows = []
    for p in ["10029", "11450"]:
        for session, condition, value in [(1, "sham", .5), (2, "theta", .7)]:
            rows.append(dict(participant=p, session=session, task="bandit", phase="active", cohort="experimental_candidate",
                             intended_condition=condition, behavior_valid=True, p_stay_win=value,
                             source_files=f"{p}-{session}.csv"))
    pairs = paired_differences(pd.DataFrame(rows))
    assert pairs.participant.nunique() == 2
    assert (pairs.difference - .2).abs().max() < 1e-9


@pytest.mark.skipif(not os.getenv("TACS3_REAL_ROOT"), reason="set TACS3_REAL_ROOT to run integration against local raw data")
def test_real_experimental_and_pilot_integration(tmp_path):
    root = Path(os.environ["TACS3_REAL_ROOT"]).resolve()
    protected = [root / "code/bandit_main.py", root / "code/sst_main.py", root / "code/sst_eeg.py", root / "code/protocol_generator.py", root / "code/config.json"]
    before = {str(p): digest(p) for p in protected}
    result = run(root, tmp_path / "real", make_figures=True)
    assert result["n_experimental_candidate_participants"] >= 2
    assert result["n_pilot_ids"] > 0
    manifest = pd.read_csv(tmp_path / "real/manifest.csv", dtype={"participant": str})
    restart = manifest[manifest.source_file.str.contains("10029_ses-2_run-2_task-SST_2026-10-20")]
    assert sorted(restart.loc[restart.selected, "trial_count"]) == [91]
    assert restart.loc[restart.trial_count.eq(10), "selected"].eq(False).all()
    assert manifest.cohort.eq("pilot").any()
    assert result["n_eligible_session_ssrt"] >= 1
    assert before == {str(p): digest(p) for p in protected}
