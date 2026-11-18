import json
from pathlib import Path

import pandas as pd
import pytest

from behavioral_analysis.discovery import discover, load_recording, select_records
from behavioral_analysis.identity import IdentityResolver, participant_id
from behavioral_analysis.metadata import condition_key, scan_metadata
from behavioral_analysis.pipeline import run
from .conftest import main_sst
from .test_discovery_metadata import event_path
from .test_pipeline import synthetic_repository


def alias_file(tmp_path, rows):
    p = tmp_path / "aliases.csv"
    pd.DataFrame(rows).to_csv(p, index=False)
    return p


def alias(alias="10029", participant="G10029", **extra):
    return {"alias": alias, "participant": participant, "evidence": "Synthetic roster confirmation", **extra}


def test_namespaces_and_zeros_never_collapse():
    resolver = IdentityResolver()
    ids = ["10029", "G10029", "R10029", "G010029", "010029"]
    assert [resolver.resolve(x) for x in ids] == ids
    assert resolver.resolve("sub-g10029") == "G10029"


def test_legacy_resolution_requires_explicit_evidence(tmp_path):
    resolver = IdentityResolver(alias_file(tmp_path, [alias()]))
    assert resolver.resolve("sub-10029") == "G10029"
    assert resolver.resolve("R10029") == "R10029"
    assert resolver.fields("10029")["alias_evidence"] == "Synthetic roster confirmation"
    assert resolver.fields("10029")["identity_status"] == "explicit_alias"


@pytest.mark.parametrize("rows", [
    [alias(), alias(participant="R10029")],
    [alias(evidence="")],
    [alias(alias="G10029", participant="R10029")],
    [alias(alias="G10029", participant="10029")],
    [alias(), alias(alias="G10029", participant="G12345")],
    [alias(alias="10029", participant="10029")],
    [alias(source_file="../outside.csv")],
    [alias(), alias(participant="R10029", source_file="data/one.csv")],
])
def test_ambiguous_chained_or_unsafe_aliases_rejected(tmp_path, rows):
    with pytest.raises(ValueError):
        IdentityResolver(alias_file(tmp_path, rows))


def test_file_scope_can_disambiguate_shared_legacy_number(tmp_path):
    resolver = IdentityResolver(alias_file(tmp_path, [alias(source_file="data/g.csv"), alias(participant="R10029", source_file="data/r.csv")]))
    assert resolver.resolve("10029", "data/g.csv") == "G10029"
    assert resolver.resolve("10029", "data/r.csv") == "R10029"
    assert resolver.resolve("10029", "data/unknown.csv") == "10029"


def test_body_filename_alias_resolved_before_conflict_check(tmp_path, config):
    raw = main_sst()
    raw["subject_id"] = "sub-10029"
    p = event_path(tmp_path, participant="G10029")
    raw.to_csv(p, index=False)
    unaliased = load_recording(p, tmp_path)
    assert "identity_conflict" in unaliased.issues
    resolver = IdentityResolver(alias_file(tmp_path, [alias()]))
    rec = load_recording(p, tmp_path, resolver)
    assert "identity_conflict" not in rec.issues
    assert rec.meta["participant"] == "G10029"
    assert rec.meta["cohort"] == "experimental_candidate"
    assert "Synthetic roster confirmation" in rec.meta["body_identity_resolution"]


def test_equal_trial_bytes_in_different_namespaces_not_deduplicated(tmp_path, config):
    raw = main_sst()
    for identity in ["G10029", "R10029", "10029"]:
        raw.to_csv(event_path(tmp_path, participant=identity), index=False)
    records = select_records(discover(tmp_path), config)
    assert len([r for r in records if r.meta["selected"]]) == 3


def test_canonical_condition_key_keeps_G_R_distinct(tmp_path):
    path = tmp_path / "key.csv"
    pd.DataFrame([dict(participant=p, session=1, intended_condition=c, condition_evidence="synthetic")
                  for p, c in [("G10029", "theta"), ("R10029", "beta")]]).to_csv(path, index=False)
    key = condition_key(path)
    assert set(key.participant) == {"G10029", "R10029"}


def test_duplicate_key_after_alias_resolution_rejected(tmp_path):
    resolver = IdentityResolver(alias_file(tmp_path, [alias()]))
    path = tmp_path / "key.csv"
    pd.DataFrame([dict(participant=p, session=1, intended_condition="theta", condition_evidence="synthetic")
                  for p in ["10029", "G10029"]]).to_csv(path, index=False)
    with pytest.raises(ValueError, match="duplicate"):
        condition_key(path, resolver)


def test_end_to_end_alias_applies_to_all_input_layers(tmp_path):
    root = tmp_path / "repo"
    synthetic_repository(root)
    aliases = alias_file(tmp_path, [alias()])
    roster = tmp_path / "roster.csv"
    pd.DataFrame([dict(participant="G10029", cohort="experimental_candidate", evidence="synthetic")]).to_csv(roster, index=False)
    key = tmp_path / "key.csv"
    pd.DataFrame([dict(participant="10029", session=1, intended_condition="theta", condition_evidence="synthetic")]).to_csv(key, index=False)
    freq_dir = root / "stimulation/calculated-theta-beta"
    freq_dir.mkdir(parents=True)
    (freq_dir / "10029-1_pre-stim_theta-beta.txt").write_text("Theta stimulation frequency: 6.00 Hz\nBeta stimulation frequency: 20.00 Hz\n")
    protocols = root / "stimulation/protocols/generated"
    protocols.mkdir(parents=True)
    (protocols / "10029_visit1_SST_run1.neprot").write_text("<ProtocolTemplates><ftacsValue>6.0</ftacsValue></ProtocolTemplates>")
    device = root / "stimulation/stimulation-data"
    device.mkdir(parents=True)
    (device / "20261020160000_10029-1_SST-1.info").write_text("Ftacs (Hz): 6.0\nNumber of records of Stimulation: 0\n")
    output = tmp_path / "derived"
    run(root, output, key_path=key, roster_path=roster, make_figures=False, aliases_path=aliases)
    for name in ["manifest.csv", "run_metrics.csv", "session_metrics.csv", "frequency_estimates.csv", "stimulation_records.csv"]:
        frame = pd.read_csv(output / name, dtype=str)
        assert set(frame.participant) == {"G10029"}, name
    sessions = pd.read_csv(output / "session_metrics.csv", dtype=str)
    assert sessions.intended_condition.eq("theta").all()
    audit = pd.read_csv(output / "identity_resolution.csv", dtype=str)
    assert audit.recorded_participant.eq("10029").all()
    assert audit.alias_evidence.eq("Synthetic roster confirmation").all()
    provenance = json.loads((output / "provenance.json").read_text())
    assert provenance["aliases_sha256"]


def test_roster_duplicates_after_alias_rejected(tmp_path):
    root = tmp_path / "repo"
    synthetic_repository(root)
    aliases = alias_file(tmp_path, [alias()])
    roster = tmp_path / "roster.csv"
    pd.DataFrame([dict(participant=p, cohort="experimental_candidate", evidence="synthetic") for p in ["G10029", "10029"]]).to_csv(roster, index=False)
    with pytest.raises(ValueError, match="unique"):
        run(root, tmp_path / "out", roster_path=roster, make_figures=False, aliases_path=aliases)
