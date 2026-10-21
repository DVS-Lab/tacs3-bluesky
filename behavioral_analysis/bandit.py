"""Slot/flower scoring adapted from tacs_bandit WSLS and reversal methods."""
import numpy as np
import pandas as pd

from .common import column, flags, numeric, ratio, median


def score_trials(frame, pre=5, post=15):
    d = frame.copy().reset_index(drop=True)
    choice = numeric(d, "choice")
    f1, f2, good = (numeric(d, key) for key in ["flower1", "flower2", "current_good"])
    d["chosen_flower"] = np.where(choice.eq(1), f1, np.where(choice.eq(2), f2, np.nan))
    d["valid_choice"] = choice.isin([1, 2]) & d.chosen_flower.notna() & f1.ne(f2)
    good_valid = good.eq(f1) | good.eq(f2)
    d["choice_accuracy"] = d.chosen_flower.eq(good).astype(float).where(d.valid_choice & good_valid)
    d["reward_valid"] = flags(column(d, "reward")).map({True: 1.0, False: 0.0}).where(d.valid_choice)
    d["feedback_conflict"] = False
    if "outcome" in d:
        expected_reward = d.outcome.astype(str).str.lower().map({"win": 1.0, "loss": 0.0})
        d["feedback_conflict"] |= d.valid_choice & expected_reward.notna() & d.reward_valid.notna() & expected_reward.ne(d.reward_valid)
    if "feedback_marker" in d:
        expected_reward = numeric(d, "feedback_marker").map({31: 1.0, 32: 0.0})
        d["feedback_conflict"] |= d.valid_choice & expected_reward.notna() & d.reward_valid.notna() & expected_reward.ne(d.reward_valid)
    d.loc[d.feedback_conflict, "reward_valid"] = np.nan
    d["rt_ms"] = numeric(d, "rt").where(d.valid_choice)
    d["rt_ms"] = d.rt_ms.where(d.rt_ms.gt(0) & d.rt_ms.le(1250))
    adjacent = numeric(d, "trial_num").diff().eq(1)
    prev_valid = d.valid_choice.shift(fill_value=False)
    d["valid_wsls"] = adjacent & d.valid_choice & prev_valid & d.reward_valid.shift().notna()
    d["prev_reward"] = d.reward_valid.shift().where(d.valid_wsls)
    d["stay"] = d.chosen_flower.eq(d.chosen_flower.shift()).astype(float).where(d.valid_wsls)
    d["shift"] = 1 - d.stay
    d["is_reversal"] = good.notna() & good.shift().notna() & good.ne(good.shift()) & adjacent
    d["mapping_conflict"] = (choice.notna() & ~choice.isin([1, 2])) | f1.eq(f2) | ~good_valid
    if "correct" in d:
        correct = flags(d.correct).map({True: 1.0, False: 0.0})
        d["mapping_conflict"] |= correct.notna() & d.choice_accuracy.notna() & correct.ne(d.choice_accuracy)
    if {"slot1_position", "left_stimulus", "right_stimulus"}.issubset(d):
        expected_left = pd.Series(np.where(d.slot1_position.eq("left"), f1, f2))
        expected_right = pd.Series(np.where(d.slot1_position.eq("left"), f2, f1))
        d["mapping_conflict"] |= numeric(d, "left_stimulus").ne(expected_left) | numeric(d, "right_stimulus").ne(expected_right)
    if "contingency_id" in d:
        c = numeric(d, "contingency_id")
        d["contingency_conflict"] = adjacent & (c.diff().ne(0) != d.is_reversal)
    else:
        d["contingency_conflict"] = False
    reversal_rows = []
    for i in np.flatnonzero(d.is_reversal):
        old_good = good.iloc[i - 1]
        initial_errors = 0
        censored = True
        end = min(len(d), i + post + 1)
        for j in range(i, end):
            if good.iloc[j] != good.iloc[i] or not d.valid_choice.iloc[j]:
                break
            if d.chosen_flower.iloc[j] != old_good:
                censored = False
                break
            initial_errors += 1
        for offset in range(-pre, post + 1):
            j = i + offset
            if 0 <= j < len(d):
                reversal_rows.append(dict(reversal_trial=int(numeric(d, "trial_num").iloc[i]), offset=offset,
                                          accuracy=d.choice_accuracy.iloc[j],
                                          old_option_choice=float(d.chosen_flower.iloc[j] == old_good) if d.valid_choice.iloc[j] else np.nan,
                                          initial_perseverative_trials=initial_errors,
                                          perseveration_censored=censored,
                                          source_file=d.source_file.iloc[j] if "source_file" in d else ""))
    return d, pd.DataFrame(reversal_rows)


def metrics(d, reversals=None):
    wins = d.prev_reward.eq(1)
    losses = d.prev_reward.eq(0)
    nwin, nloss = int(wins.sum()), int(losses.sum())
    out = dict(n_trials=len(d), n_valid_choice=int(d.valid_choice.sum()),
               n_reward_valid=int(d.reward_valid.notna().sum()),
               n_missing_feedback=int((d.valid_choice & d.reward_valid.isna()).sum()),
               missed_response_rate=1 - d.valid_choice.mean(),
               p_stay_win=ratio(d.loc[wins, "stay"].sum(), nwin),
               p_shift_loss=ratio(d.loc[losses, "shift"].sum(), nloss),
               n_win_transitions=nwin, n_loss_transitions=nloss,
               n_stay_win=int(d.loc[wins, "stay"].sum()), n_shift_loss=int(d.loc[losses, "shift"].sum()),
               choice_accuracy=d.choice_accuracy.mean(), reward_rate=d.reward_valid.mean(),
               rt_mean_ms=d.rt_ms.mean(), rt_median_ms=median(d.rt_ms), n_valid_rt=int(d.rt_ms.notna().sum()),
               n_reversals=int(d.is_reversal.sum()), n_mapping_conflicts=int(d.mapping_conflict.sum()),
               n_feedback_conflicts=int(d.feedback_conflict.sum()),
               n_contingency_conflicts=int(d.contingency_conflict.sum()))
    if reversals is not None and len(reversals):
        out.update(pre_reversal_accuracy=reversals.loc[reversals.offset.between(-5, -1), "accuracy"].mean(),
                   post_reversal_accuracy=reversals.loc[reversals.offset.between(0, 4), "accuracy"].mean(),
                   perseverative_choice_rate=reversals.loc[reversals.offset.between(0, 4), "old_option_choice"].mean())
    out["behavior_valid"] = not (out["n_mapping_conflicts"] or out["n_contingency_conflicts"] or out["n_feedback_conflicts"])
    return out
