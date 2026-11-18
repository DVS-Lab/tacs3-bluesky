"""Within-participant contrasts and model-readiness gates; no automatic inference."""
import pandas as pd


def paired_differences(sessions):
    rows = []
    for task, outcomes in [("bandit", ["p_stay_win", "p_shift_loss", "post_reversal_accuracy"]),
                           ("sst", ["ssrt_ms", "go_rt_mean_ms"])]:
        if not len(sessions):
            continue
        d = sessions[(sessions.task == task) & (sessions.phase == "active") &
                     (sessions.cohort == "experimental_candidate") & sessions.intended_condition.isin(["theta", "beta", "sham"])]
        for p, group in d.groupby("participant"):
            # Repeated same-condition visits require adjudication, not averaging by accident.
            if group.intended_condition.duplicated().any():
                continue
            for outcome in outcomes:
                if outcome not in group:
                    continue
                valid = group[group.ssrt_valid.eq(True)] if outcome == "ssrt_ms" else group[group.behavior_valid.eq(True)] if task == "bandit" else group
                values = valid.set_index("intended_condition")
                for treatment, reference in [("theta", "sham"), ("beta", "sham"), ("theta", "beta")]:
                    if treatment in values.index and reference in values.index:
                        a, b = values.loc[treatment], values.loc[reference]
                        if pd.notna(a[outcome]) and pd.notna(b[outcome]):
                            rows.append(dict(participant=p, task=task, outcome=outcome,
                                             contrast=treatment + "-" + reference, difference=a[outcome] - b[outcome],
                                             treatment_session=a.session, reference_session=b.session,
                                             treatment_source_files=a.source_files, reference_source_files=b.source_files,
                                             assignment_basis="documented_intended_assignment;delivery_not_assumed"))
    return pd.DataFrame(rows, columns=["participant", "task", "outcome", "contrast", "difference", "treatment_session",
                                       "reference_session", "treatment_source_files", "reference_source_files", "assignment_basis"])


def readiness(sessions, pairs):
    active = sessions[(sessions.phase == "active") & (sessions.cohort == "experimental_candidate")] if len(sessions) else sessions
    known = int(active.intended_condition.isin(["theta", "beta", "sham"]).sum()) if len(active) else 0
    return dict(inference_run=False, reason="Descriptive pipeline; model fitting requires an explicit analysis decision and adequate paired coverage.",
                n_task_sessions=len(active), n_with_intended_assignment=known,
                n_participants_with_any_pair=int(pairs.participant.nunique()) if len(pairs) else 0,
                bandit_formula="stay ~ intended_condition * prev_reward + session_order + run_order + task_order + (1 + prev_reward | participant)",
                bandit_estimand="trial-level binary stay, valid within-run transitions; theta versus sham feedback interaction",
                sst_formula="ssrt_ms ~ intended_condition + session_order + task_order + go_rt_mean_ms + (1 | participant)",
                sst_estimand="one gated pooled active SST SSRT per participant/visit; beta versus sham",
                cautions=["Check identifiability, paired coverage, missingness and convergence before fitting.",
                          "Intended assignment alone does not verify delivery; retain separate sensitivity analyses.",
                          "Run order is available in trial and run tables; pooled SSRT has no trial-level replicate.",
                          "Frequency associations require validated rhythm estimates; they are exploratory and cannot show efficacy."])
