import numpy as np
import pandas as pd
import pytest

from behavioral_analysis.sst import integration_ssrt, reconstruct_ssd, metrics
from .conftest import main_sst


def test_integration_rank_and_omission_replacement():
    assert integration_ssrt([.2, .3, .4, .5], .5, [.1, .1]) == pytest.approx(.2)
    # Five go trials, ceil(5*.75)=4, omission replaced by max(.2,.3,.4,.5).
    assert integration_ssrt([.2, .3, .4, .5], .75, [.1], omissions=1) == pytest.approx(.4)


@pytest.mark.parametrize("p", [0, 1, np.nan])
def test_invalid_probability_never_produces_ssrt(p):
    assert np.isnan(integration_ssrt([.2, .3], p, [.1]))


def test_ssd_main_reconstructs_pre_update_and_validates(config):
    raw = main_sst()
    d = reconstruct_ssd(raw, "sst_main_updated_ssd", config["sst"])
    assert d.planned_ssd_s.iloc[0] == .25
    assert d.planned_ssd_s.iloc[3] == pytest.approx(.30)
    assert not d.ssd_state_mismatch.any()
    assert not d.ssd_timing_mismatch.any()
    assert d.response_before_stop_display.sum() == 15
    m = metrics(d, config["sst"])
    assert m["ssrt_valid"]
    assert 50 <= m["ssrt_ms"] <= 500
    assert not metrics(d, config["sst"], "session")["ssrt_valid"]


def test_current_ssd_eeg_is_not_shifted(config):
    raw = main_sst()
    planned = reconstruct_ssd(raw, "sst_main_updated_ssd", config["sst"]).planned_ssd_s
    raw["ssd"] = planned
    raw["marker_code"] = "1"
    d = reconstruct_ssd(raw, "sst_eeg_current_ssd", config["sst"])
    assert d.planned_ssd_s.iloc[0] == .25
    assert not d.ssd_state_mismatch.any()
    assert d.ssd_timing_kind.eq("saved_current_ssd_eeg_schema").all()


def test_staircase_bounds(config):
    raw = main_sst(1)
    # An initial state at floor is a documented override for this synthetic test.
    cfg = {**config["sst"], "initial_ssd_s": .05}
    raw.loc[0, ["response", "rt", "ssd", "stop_onset", "stop_success"]] = ["True", ".02", ".05", "", "0"]
    d = reconstruct_ssd(raw, "sst_main_updated_ssd", cfg)
    assert d.planned_ssd_s.iloc[0] == .05
    assert not d.ssd_state_mismatch.any()


def test_event_timing_mismatch_withholds_ssrt(config):
    raw = main_sst()
    raw.loc[0, "stop_onset"] = str(float(raw.loc[0, "stim_onset"]) + .7)
    d = reconstruct_ssd(raw, "sst_main_updated_ssd", config["sst"])
    m = metrics(d, config["sst"])
    assert m["n_ssd_timing_mismatch"] == 1
    assert not m["ssrt_valid"]
    assert np.isnan(m["ssrt_ms"])


def test_missing_signal_after_planned_time_is_invalid(config):
    raw = main_sst()
    raw.loc[3, "rt"] = ".7"
    d = reconstruct_ssd(raw, "sst_main_updated_ssd", config["sst"])
    assert d.missing_stop_signal.iloc[3]
    assert not metrics(d, config["sst"])["ssrt_valid"]


def test_omission_sentinel_not_accuracy_or_rt(config):
    raw = main_sst()
    raw.loc[1, ["go_miss", "response", "rt", "go_correct"]] = ["999", "False", "999", "0"]
    d = reconstruct_ssd(raw, "sst_main_updated_ssd", config["sst"])
    assert pd.isna(d.rt_s.iloc[1])
    m = metrics(d, config["sst"])
    assert m["n_go_omissions"] == 1
    assert m["go_accuracy"] < 1


def test_session_pool_reestimates_not_mean_of_ssrts(config):
    d = reconstruct_ssd(main_sst(), "sst_main_updated_ssd", config["sst"])
    pooled = metrics(pd.concat([d, d]), config["sst"], "session")
    assert pooled["ssrt_valid"]
    assert pooled["n_stop"] == 62


def test_race_model_gate(config):
    raw = main_sst()
    raw.loc[raw.stop.eq("0"), "rt"] = ".1"
    d = reconstruct_ssd(raw, "sst_main_updated_ssd", config["sst"])
    m = metrics(d, config["sst"])
    assert "failed_stop_not_faster" in m["ssrt_exclusion_reasons"]
    assert pd.isna(m["ssrt_ms"])


@pytest.mark.parametrize("go_rt", [.22, .30, 1.20])
def test_negative_short_and_long_ssrt_withheld(config, go_rt):
    raw = main_sst()
    raw.loc[raw.stop.eq("0"), "rt"] = str(go_rt)
    d = reconstruct_ssd(raw, "sst_main_updated_ssd", config["sst"])
    m = metrics(d, config["sst"])
    assert "implausible_ssrt" in m["ssrt_exclusion_reasons"]
    assert pd.isna(m["ssrt_ms"])


def test_correct_go_without_response_is_contradiction(config):
    raw = main_sst()
    raw.loc[1, ["response", "rt"]] = ["False", ""]
    d = reconstruct_ssd(raw, "sst_main_updated_ssd", config["sst"])
    assert d.invalid_event.iloc[1]
