import csv
import json
import os
import subprocess
from pathlib import Path

import pandas as pd
import pytest

from impedance_analysis.core import (classify, digest, filename_fields, parse_export,
                                     metadata_record, load_config, link_export)
from impedance_analysis.pipeline import run


def export(root, name="20261020120000_G00123-2_ImpVal.txt", text="150000 21000 20000 0 -1 bad 4000 4100"):
    folder = root / "stimulation/stimulation-data"
    folder.mkdir(parents=True, exist_ok=True)
    p = folder / name
    p.write_text(text)
    return p


@pytest.mark.parametrize("value,expected", [(150000, "exact_150000"), (150001, "above_threshold_other"),
    (20001, "above_threshold_other"), (20000, "positive_at_or_below_threshold"), (0, "zero_uninterpreted"),
    (-1, "negative_invalid"), (None, "invalid_or_missing"), (float("nan"), "invalid_or_missing")])
def test_special_value_is_separate(value, expected):
    assert classify(value) == expected


def test_namespace_timestamp_and_pilot_identifiers():
    meta = filename_fields("20261020120000_G00123-2_Bandit-1_IMP.txt")
    assert meta["participant"] == "G00123"
    assert meta["visit"] == "2"
    assert meta["step"] == "Bandit-1"
    assert filename_fields("20261020120000_R00123-2_ImpVal.txt")["participant"] == "R00123"
    assert filename_fields("20261020120000_avi-eeg-test-03_ImpVal.txt")["visit"] == ""
    assert filename_fields("20269920120000_x_ImpVal.txt")["filename_issue"]


def test_invalid_token_does_not_silently_remove_file_or_channel(tmp_path):
    p = export(tmp_path)
    meta, rows, errors = parse_export(p, tmp_path)
    assert len(rows) == 8 and meta["n_malformed_rows"] == 1
    assert len(errors) == 1 and rows[5]["raw_token"] == "bad"
    assert not any(x["structurally_valid"] for x in rows)
    assert rows[0]["category"] == "exact_150000"


@pytest.mark.parametrize("text,expected", [("", 0), ("1 2 3", 8), ("1 2 3 4 5 6 7 8 9", 8),
    ("1 2 3 4 5 6 7 8\n1 2 3 4 5 6 7 8", 16), ("nan inf 3 4 5 6 7 8", 8)])
def test_malformed_exports_remain_in_inventory(tmp_path, text, expected):
    p = export(tmp_path, text=text)
    output = tmp_path.parent / (tmp_path.name + "-out")
    result = run(tmp_path, output, figures=False)
    assert result["n_exports"] == 1
    assert result["n_files_with_issues"] == 1
    assert result["n_channel_readings"] == expected
    assert (output / "share/report.html").exists()
    assert digest(p) == json.loads((output / "private/provenance.json").read_text())["protected_source_hashes"][p.relative_to(tmp_path).as_posix()]


def test_continuous_epoch_and_zero_preserved(tmp_path):
    p = export(tmp_path, name="20261020120000_G00123-2_Bandit-1_IMP.txt", text="1000 0 3000 4000 0 0 0 0 1792512000000\n1000 2 3 4 5 6 7 8 nope")
    _, rows, errors = parse_export(p, tmp_path)
    assert len(rows) == 16 and len(errors) == 1
    assert rows[0]["sample_utc"].endswith("+00:00")
    assert rows[1]["category"] == "zero_uninterpreted"
    assert rows[8]["sample_utc"] == ""
    assert not rows[8]["structurally_valid"]


def write_log(path, row):
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(row))
        writer.writeheader()
        writer.writerow(row)


def test_configuration_controls_connected_denominators_and_private_evidence(tmp_path):
    root, out = tmp_path / "repo", tmp_path / "out"
    p = export(root, text="150000 150000 21000 4000 0 0 0 0")
    log = tmp_path / "log.csv"
    row = dict(source_file=p.relative_to(root).as_posix(), sha256=digest(p), setup="flat_cable_testboard",
               connected_channels="1;4", active_channels="1", evidence="PRIVATE G00123 operator note", channel_locations='{"1":"F3"}')
    write_log(log, row)
    run(root, out, configuration_log=log, figures=False)
    summary = pd.read_csv(out / "share/channel_summary.csv")
    ch2 = summary[summary.physical_channel.eq(2)]
    assert ch2.loc[ch2.denominator_scope.eq("documented_connected"), "n_eligible_positive_readings"].iloc[0] == 0
    assert ch2.loc[ch2.denominator_scope.str.startswith("all_"), "n_exact_150000"].iloc[0] == 1
    text = "\n".join(p.read_text() for p in (out / "share").iterdir() if p.suffix != ".png")
    assert "PRIVATE" not in text and "G00123" not in text and "F3" in text  # only generic explanatory text
    readings = pd.read_csv(out / "private/readings.csv")
    assert readings.loc[readings.physical_channel.eq(1), "location"].iloc[0] == "F3"
    row["sha256"] = "stale"
    write_log(log, row)
    with pytest.raises(ValueError, match="hash"):
        run(root, tmp_path / "stale", configuration_log=log, figures=False)


@pytest.mark.parametrize("changes", [dict(connected_channels="1;1"), dict(active_channels="2"),
    dict(setup="guessed_testboard"), dict(evidence=""), dict(info_file="fake", info_sha256="x")])
def test_configuration_rejects_unsupported_or_ambiguous_records(tmp_path, changes):
    p = export(tmp_path, text="1 2 3 4 5 6 7 8")
    meta, _, _ = parse_export(p, tmp_path)
    row = dict(source_file=meta["source_file"], sha256=meta["sha256"], setup="headcap", connected_channels="1", active_channels="1", evidence="operator record")
    row.update(changes)
    log = tmp_path / "config.csv"
    write_log(log, row)
    with pytest.raises(ValueError):
        load_config(log, [meta], [])


def test_linkage_does_not_assign_nearest_info_to_standalone_or_infer_connected(tmp_path):
    p = export(tmp_path, text="4000 4000 4000 4000 4000 4000 4000 4000")
    info = p.with_name("20261020120001_G00123-2_Bandit-1.info")
    info.write_text("Step name: Bandit-1\nSoftware's version: NIC test\nStimulation parameters:\n\tChannel 1: \n\t\tPosition: F3\n\t\tType: Stimulation\n")
    meta, _, _ = parse_export(p, tmp_path)
    record = metadata_record(info, tmp_path)
    links, linked = link_export(meta, [record], {})
    assert linked is None and "delta_seconds" in links["info_candidates"]
    continuous = export(tmp_path, name="20261020120000_G00123-2_Bandit-1_IMP.txt", text="1 2 3 4 5 6 7 8 1792512000000")
    meta, _, _ = parse_export(continuous, tmp_path)
    links, linked = link_export(meta, [record], {})
    assert linked and "not_wiring_proof" in links["info_link_status"]
    # Duplicate qualifying info is ambiguous, never select latest.
    assert link_export(meta, [record, dict(record)], {})[1] is None


def test_transitions_do_not_cross_identity_day_or_large_gap(tmp_path):
    root, out = tmp_path / "repo", tmp_path / "out"
    for name, value in [("20261020120000_G00123-2", 150000), ("20261020121000_G00123-2", 3000),
                        ("20261020121500_R00123-2", 150000), ("20261020121600_00123-2", 150000),
                        ("20261020160000_G00123-2", 150000), ("20261021120000_G00123-2", 3000)]:
        export(root, name=name + "_ImpVal.txt", text=f"{value} 4000 4000 4000 4000 4000 4000 4000")
    run(root, out, figures=False)
    changes = pd.read_csv(out / "share/suspicious_sequences.csv")
    assert len(changes) == 1
    assert changes.iloc[0].elapsed_seconds == 600
    assert changes.iloc[0].setup_comparability == "unknown_or_not_comparable"
    assert pd.read_csv(out / "share/readings.csv").connected.eq("unknown").all()


def test_absent_git_exports_are_recovered_separately_without_restoring_raw(tmp_path):
    root, out = tmp_path / "repo", tmp_path / "out"
    p = export(root, text="150000 4000 4000 4000 4000 4000 4000 4000")
    def git(*args):
        return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)
    git("init")
    git("add", ".")
    git("-c", "user.name=Test", "-c", "user.email=test@example.org", "commit", "-m", "synthetic export")
    git("rm", p.relative_to(root).as_posix())
    git("-c", "user.name=Test", "-c", "user.email=test@example.org", "commit", "-m", "synthetic deletion")
    result = run(root, out, figures=False)
    assert result["n_history_only_exports"] == 1 and result["n_working_tree_standalone_exports"] == 0
    assert not p.exists()
    assert pd.read_csv(out / "share/channel_summary.csv").source_availability.eq("git_history_only").all()


def test_protected_output_overlap_rejected(tmp_path):
    export(tmp_path)
    for out in [tmp_path, tmp_path.parent, tmp_path / "stimulation/derived", tmp_path / "code", tmp_path / "data"]:
        with pytest.raises(ValueError, match="overlap"):
            run(tmp_path, out)


@pytest.mark.skipif(not os.getenv("TACS3_REAL_ROOT"), reason="set TACS3_REAL_ROOT for read-only integration")
def test_full_real_inventory_and_source_integrity(tmp_path):
    root = Path(os.environ["TACS3_REAL_ROOT"])
    source = root / "stimulation/stimulation-data"
    before = {p.name: digest(p) for p in source.iterdir() if p.suffix in {".txt", ".info"}}
    result = run(root, tmp_path / "out", figures=True)
    actual = list(source.glob("*_ImpVal.txt"))
    assert result["n_working_tree_standalone_exports"] == len(actual)
    assert result["n_working_tree_standalone_exports"] >= 92
    assert result["n_history_only_exports"] >= 6
    assert before == {p.name: digest(p) for p in source.iterdir() if p.suffix in {".txt", ".info"}}
    assert result["source_integrity_verified"]
    summary = pd.read_csv(tmp_path / "out/share/channel_summary.csv")
    assert summary.loc[summary.denominator_scope.eq("documented_connected"), "n_eligible_positive_readings"].eq(0).all()
    assert (tmp_path / "out/share/timeseries_2026-10-22.png").exists()


@pytest.mark.parametrize("threshold", [float("nan"), float("inf"), 0, 150000])
def test_invalid_threshold_is_rejected(tmp_path, threshold):
    export(tmp_path)
    with pytest.raises(ValueError, match="threshold"):
        run(tmp_path, tmp_path.parent / (tmp_path.name + "-out"), threshold=threshold)


def test_private_operator_log_cannot_be_overwritten_by_output(tmp_path):
    root, out = tmp_path / "repo", tmp_path / "out"
    export(root)
    out.mkdir()
    log = out / "configuration_log.csv"
    log.write_text("PRIVATE source input")
    before = digest(log)
    with pytest.raises(ValueError, match="outside the output"):
        run(root, out, configuration_log=log)
    assert digest(log) == before
