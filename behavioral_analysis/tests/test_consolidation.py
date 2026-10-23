import pandas as pd

from behavioral_analysis.design import descriptive_comparisons
from behavioral_analysis.metadata import scan_metadata


def test_descriptive_pairs_keep_namespaces_and_phase_gates():
    rows = []
    def add(p, visit, task, phase, valid, value):
        rows.append(dict(participant=p, session=visit, task=task, phase=phase, cohort="experimental_candidate",
                         collection_date=f"2026-10-{visit:02d}", behavior_valid=valid, ssrt_valid=valid,
                         choice_accuracy=value, ssrt_ms=value))
    for visit in [1, 2]:
        add("G00123", visit, "bandit", "active", True, .5 + .1 * visit)
        add("G00123", visit, "sst", "active", True, 300 - 10 * visit)
    add("G00123", 1, "bandit", "pre-stim", True, .5)
    add("00123", 1, "bandit", "post-stim", True, .7)  # not an evidenced alias
    add("G00123", 1, "sst", "pre-stim", False, 280)
    add("G00123", 1, "sst", "post-stim", False, 260)
    coverage, pairs = descriptive_comparisons(pd.DataFrame(rows))
    assert coverage.query('task == "bandit" and comparison == "post_minus_pre"').n_available_visit_pairs.iloc[0] == 0
    sst = coverage.query('task == "sst" and comparison == "post_minus_pre"').iloc[0]
    assert sst.n_available_visit_pairs == 1 and sst.n_eligible_visit_pairs == 0
    assert pairs.query('task == "sst"').difference.iloc[0] == -10
    assert set(pairs.participant) == {"G00123"}
    # Two dates for a nominal active visit are ambiguous, not a choice of latest.
    rows.append(dict(rows[0], collection_date="2026-10-03"))
    coverage, _ = descriptive_comparisons(pd.DataFrame(rows))
    assert coverage.query('task == "bandit" and comparison == "visit2_minus_visit1_active"').n_available_visit_pairs.iloc[0] == 0


def test_zero_hz_does_not_collapse_distinct_protocol_configurations(tmp_path):
    folder = tmp_path / "stimulation/protocols/generated"
    folder.mkdir(parents=True)
    for visit, step, electrode, amp in [(1, 0, 2, 1500), (2, 7, 1, 0)]:
        (folder / f"G00123_visit{visit}_bandit_run1.neprot").write_text(
            f"<ProtocolTemplates><Template><Step><stepType>{step}</stepType><Channel><index>1</index><electrodeType>{electrode}</electrodeType>"
            f"<atacsValue>{amp}</atacsValue><atdcsValue>0</atdcsValue><ftacsValue>0</ftacsValue></Channel></Step></Template></ProtocolTemplates>")
    _, stim, _ = scan_metadata(tmp_path)
    assert stim.frequency_hz.eq(0).all()
    assert set(stim.protocol_step_types) == {"0", "7"}
    assert set(stim.all_programmed_amplitudes_zero) == {True, False}
    assert stim.delivery_status.eq("generation_only").all()
    assert stim.participant.eq("G00123").all()
