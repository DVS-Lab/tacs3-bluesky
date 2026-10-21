import numpy as np
import pandas as pd
import pytest

from behavioral_analysis.bandit import score_trials, metrics
from .conftest import bandit_frame


def test_wsls_known_denominators():
    d, rev = score_trials(bandit_frame())
    m = metrics(d, rev)
    assert m["n_win_transitions"] == 2
    assert m["n_loss_transitions"] == 2
    assert m["p_stay_win"] == .5
    assert m["p_shift_loss"] == .5
    assert m["choice_accuracy"] == .6
    assert m["reward_rate"] == .6


def test_missing_choice_does_not_bridge():
    d, _ = score_trials(bandit_frame([1, np.nan, 2, 2], [True, True, False, True]))
    assert d.valid_wsls.tolist() == [False, False, False, True]


def test_missing_feedback_excludes_only_next_transition():
    d, _ = score_trials(bandit_frame([1, 1, 2], [True, None, False]))
    assert d.valid_wsls.tolist() == [False, True, False]


def test_run_boundary_is_not_transition():
    a, _ = score_trials(bandit_frame([1, 1], [True, True]))
    b, _ = score_trials(bandit_frame([2, 2], [False, False]))
    pooled = metrics(pd.concat([a, b]))
    assert pooled["n_win_transitions"] == 1
    assert pooled["n_loss_transitions"] == 1
    assert pooled["p_shift_loss"] == 0


def test_screen_randomization_does_not_change_flower_stay():
    f = bandit_frame([1, 1], [True, True])
    f["slot1_position"] = ["left", "right"]
    f["left_stimulus"] = [10, 20]
    f["right_stimulus"] = [20, 10]
    d, _ = score_trials(f)
    assert d.stay.iloc[1] == 1
    assert not d.mapping_conflict.any()


def test_detects_misrecorded_mapping():
    f = bandit_frame([1, 2], [True, False])
    f["correct"] = [False, True]
    d, _ = score_trials(f)
    assert d.mapping_conflict.all()
    assert not metrics(d)["behavior_valid"]


def test_inconsistent_feedback_cannot_become_wsls_outcome():
    f = bandit_frame([1, 1], [True, False])
    f["outcome"] = ["loss", "loss"]
    d, _ = score_trials(f)
    assert d.feedback_conflict.iloc[0]
    assert not d.valid_wsls.iloc[1]
    assert not metrics(d)["behavior_valid"]


def test_reversal_uses_good_flower_not_choices():
    f = bandit_frame([1, 1, 1, 1, 2], [True] * 5)
    f["current_good"] = [10, 10, 20, 20, 20]
    d, rev = score_trials(f)
    assert d.is_reversal.tolist() == [False, False, True, False, False]
    assert rev.reversal_trial.unique().tolist() == [3]
    assert rev.initial_perseverative_trials.unique().tolist() == [2]
    assert rev.loc[rev.offset.eq(0), "accuracy"].iloc[0] == 0


@pytest.mark.parametrize("value", [999, -1, 1300, "missing"])
def test_invalid_bandit_rt(value):
    f = bandit_frame([1], [True])
    f["rt"] = [value]
    d, _ = score_trials(f)
    if value == 999:  # 999 ms is a legitimate bandit RT, unlike the SST omission flag.
        assert d.rt_ms.iloc[0] == 999
    else:
        assert pd.isna(d.rt_ms.iloc[0])
