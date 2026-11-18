"""SST scoring with version-specific SSD reconstruction and gated integration SSRT."""
import math

import numpy as np
import pandas as pd

from .common import column, flags, numeric, ratio, median


def reconstruct_ssd(frame, schema, cfg):
    """State before current trial; saved sst_main SSD is the state AFTER outcome.

    Observed main-task stop onsets are used when present and compared with state.
    sst_eeg task-time stop_onset is synthesized by its recorder: not independent
    timing evidence. Unix deltas are retained as corroboration, not hardware proof.
    """
    d = frame.copy().reset_index(drop=True)
    d["is_stop"] = flags(column(d, "stop"))
    d["responded"] = flags(column(d, "response"))
    saved = numeric(d, "ssd")
    state = cfg["initial_ssd_s"]
    planned, next_expected = [], []
    for i, row in d.iterrows():
        planned.append(state if schema == "sst_main_updated_ssd" else saved.iloc[i])
        if row.is_stop is True and row.responded is not None:
            state = float(np.clip(state + (-1 if row.responded else 1) * cfg["ssd_step_s"],
                                  cfg["min_ssd_s"], cfg["max_ssd_s"]))
        next_expected.append(state)
    d["planned_ssd_s"] = planned
    d["ssd_saved_s"] = saved
    d["ssd_state_mismatch"] = False
    if schema == "sst_main_updated_ssd":
        d["ssd_state_mismatch"] = (saved - next_expected).abs().gt(0.0011) | saved.isna()
        observed = numeric(d, "stop_onset") - numeric(d, "stim_onset")
        d["observed_ssd_s"] = observed.where(d.is_stop.eq(True))
        d["ssd_timing_kind"] = np.where(d.observed_ssd_s.notna(), "recorded_onset_difference", "staircase_reconstruction")
    else:
        # Store a separate independent-clock difference where available, not task-time arithmetic.
        observed = (numeric(d, "stop_onset_unix_time") - numeric(d, "stim_onset_unix_time")) / 1000
        d["observed_ssd_s"] = observed.where(d.is_stop.eq(True))
        d["ssd_timing_kind"] = "saved_current_ssd_eeg_schema"
        # Validate the recorded current state against the same staircase rules.
        prior = cfg["initial_ssd_s"]
        for i, row in d.iterrows():
            d.loc[i, "ssd_state_mismatch"] = not np.isfinite(saved.iloc[i]) or abs(saved.iloc[i] - prior) > 0.0011
            if np.isfinite(saved.iloc[i]):
                prior = saved.iloc[i]
            if row.is_stop is True and row.responded is not None:
                prior = float(np.clip(prior + (-1 if row.responded else 1) * cfg["ssd_step_s"],
                                      cfg["min_ssd_s"], cfg["max_ssd_s"]))
    stop = d.is_stop.eq(True)
    d["ssd_timing_mismatch"] = stop & d.observed_ssd_s.notna() & (
        (d.observed_ssd_s - d.planned_ssd_s).abs().gt(cfg["timing_tolerance_s"]) | d.observed_ssd_s.le(0))
    d["ssd_used_s"] = d.planned_ssd_s.where(stop)
    if schema == "sst_main_updated_ssd":
        d.loc[stop & d.observed_ssd_s.notna(), "ssd_used_s"] = d.observed_ssd_s
    rt = numeric(d, "rt")
    d["rt_s"] = rt.where(d.responded.eq(True) & rt.gt(0) & rt.le(cfg["response_deadline_s"]))
    # Primary active schema provides actual display indication; eeg stop_onset may be synthetic.
    display = numeric(d, "stop_onset").notna()
    d["response_before_stop_display"] = stop & d.responded.eq(True) & ~display & d.rt_s.le(d.planned_ssd_s + cfg["timing_tolerance_s"])
    d["early_response_by_planned_ssd"] = stop & d.responded.eq(True) & d.rt_s.lt(d.planned_ssd_s)
    d["missing_stop_signal"] = stop & ~display & ~d.response_before_stop_display
    d["invalid_event"] = d.is_stop.isna() | d.responded.isna() | (d.responded.eq(True) & d.rt_s.isna())
    d["invalid_event"] |= d.responded.eq(False) & rt.gt(0) & rt.le(cfg["response_deadline_s"])
    if "stop_success" in d:
        success = flags(d.stop_success)
        d["invalid_event"] |= stop & (success.isna() | success.eq(True).ne(d.responded.eq(False)))
    d["go_accuracy_value"] = flags(column(d, "go_correct")).map({True: 1., False: 0.}).where(d.is_stop.eq(False))
    d["invalid_event"] |= d.is_stop.eq(False) & d.go_accuracy_value.isna()
    d["invalid_event"] |= d.is_stop.eq(False) & d.go_accuracy_value.eq(1) & ~d.responded.eq(True)
    # Explicit sentinel handling: go_miss=999 indicates omission, not correct behavior.
    sentinel_omission = numeric(d, "go_miss").eq(999)
    d["invalid_event"] |= d.is_stop.eq(False) & sentinel_omission & d.responded.eq(True)
    return d


def integration_ssrt(go_rts, p_respond, ssds, omissions=0):
    """Empirical rank ceil(N_go*p), with omissions replaced by maximum observed go RT.

    All valid go responses, including directional errors, enter the distribution.
    Stop responses before the planned signal remain failures in p_respond. Their
    reconstructed planned SSD remains in the mean (avoids conditioning on display).
    Returns no value for incomplete/nonfinite inputs.
    """
    rt = np.asarray(go_rts, dtype=float)
    ssd = np.asarray(ssds, dtype=float)
    if not len(rt) or not len(ssd) or not np.isfinite(rt).all() or not np.isfinite(ssd).all() or not 0 < p_respond < 1:
        return np.nan
    ordered = np.sort(np.r_[rt, np.repeat(rt.max(), omissions)])
    rank = max(1, min(len(ordered), math.ceil(len(ordered) * p_respond)))
    return float(ordered[rank - 1] - ssd.mean())


def metrics(d, cfg, level="run"):
    go = d[d.is_stop.eq(False)]
    stop = d[d.is_stop.eq(True)]
    go_response = go[go.responded.eq(True)]
    failed = stop[stop.responded.eq(True)]
    n_omit = int(go.responded.eq(False).sum())
    p = ratio(len(failed), len(stop))
    out = dict(n_trials=len(d), n_go=len(go), n_stop=len(stop), n_go_omissions=n_omit,
               n_go_responses=len(go_response), n_failed_stop=len(failed),
               p_respond_stop=p, stop_success_rate=ratio(stop.responded.eq(False).sum(), len(stop)),
               ssd_mean_ms=stop.ssd_used_s.mean() * 1000, ssd_median_ms=median(stop.ssd_used_s) * 1000,
               go_accuracy=go.go_accuracy_value.mean(), go_omission_rate=ratio(n_omit, len(go)),
               go_rt_mean_ms=go_response.rt_s.mean() * 1000, go_rt_median_ms=median(go_response.rt_s) * 1000,
               correct_go_rt_mean_ms=go.loc[go.go_accuracy_value.eq(1), "rt_s"].mean() * 1000,
               failed_stop_rt_mean_ms=failed.rt_s.mean() * 1000,
               n_early_response_before_display=int(d.response_before_stop_display.sum()),
               n_response_before_planned_stop=int(d.early_response_by_planned_ssd.sum()),
               n_missing_stop_signal=int(d.missing_stop_signal.sum()),
               n_ssd_state_mismatch=int(d.ssd_state_mismatch.sum()),
               n_ssd_timing_mismatch=int(d.ssd_timing_mismatch.sum()),
               n_invalid_events=int(d.invalid_event.sum()),
               n_observed_ssd=int(stop.observed_ssd_s.notna().sum()),
               n_anticipated_responses=int(d.rt_s.lt(0.1).sum()))
    reasons = []
    if len(go) < cfg["min_go_trials"]:
        reasons.append("insufficient_go_trials")
    minimum = cfg["min_stop_trials_session"] if level == "session" else cfg["min_stop_trials_run"]
    if len(stop) < minimum:
        reasons.append("insufficient_stop_trials")
    if not np.isfinite(p) or not cfg["min_p_respond"] <= p <= cfg["max_p_respond"]:
        reasons.append("stop_response_probability_outside_0.25_0.75")
    if not np.isfinite(out["go_accuracy"]) or out["go_accuracy"] < cfg["min_go_accuracy"]:
        reasons.append("low_go_accuracy")
    if not np.isfinite(out["go_omission_rate"]) or out["go_omission_rate"] > cfg["max_go_omission_rate"]:
        reasons.append("high_go_omissions")
    if not np.isfinite(out["failed_stop_rt_mean_ms"]) or out["failed_stop_rt_mean_ms"] >= out["go_rt_mean_ms"]:
        reasons.append("failed_stop_not_faster_than_go")
    if any(out[k] for k in ["n_missing_stop_signal", "n_ssd_state_mismatch", "n_ssd_timing_mismatch", "n_invalid_events"]):
        reasons.append("event_or_ssd_inconsistency")
    if stop.ssd_used_s.isna().any() or not stop.ssd_used_s.between(cfg["min_ssd_s"] - .001, cfg["max_ssd_s"] + cfg["timing_tolerance_s"]).all():
        reasons.append("invalid_ssd")
    estimate = np.nan
    # Do not compute/report candidate SSRTs for invalid inputs or poor behavior.
    if not reasons:
        estimate = integration_ssrt(go_response.rt_s.to_numpy(), p, stop.ssd_used_s.to_numpy(), n_omit)
        if not np.isfinite(estimate) or not cfg["min_ssrt_s"] <= estimate <= cfg["max_ssrt_s"]:
            reasons.append("implausible_ssrt")
            estimate = np.nan
    out.update(ssrt_ms=estimate * 1000, ssrt_valid=not reasons,
               ssrt_status="provisional_run" if not reasons and level == "run" else "eligible_session" if not reasons else "withheld",
               ssrt_exclusion_reasons=";".join(reasons))
    return out
