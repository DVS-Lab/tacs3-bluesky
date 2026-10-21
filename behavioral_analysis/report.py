"""Concise local reports with source evidence and explicit interpretation limits."""
from html import escape

import numpy as np
import pandas as pd

from .common import write_csv


def table(frame, columns=None):
    if columns:
        frame = frame[[c for c in columns if c in frame]]
    return frame.to_html(index=False, border=0, na_rep="—", float_format=lambda x: f"{x:.3f}", escape=True)


def build_reports(out, manifest, runs, sessions, frequencies, stimulation, orders, plots, readiness):
    primary = runs[runs.cohort.eq("experimental_candidate") & runs.phase.eq("active")]
    ps = sessions[sessions.cohort.eq("experimental_candidate") & sessions.phase.eq("active")]
    bandit = ps[ps.task.eq("bandit") & ps.behavior_valid.eq(True)]
    sst = ps[ps.task.eq("sst")]
    summary = dict(n_behavioral_files=len(manifest), n_selected_files=int(manifest.selected.sum()),
                   n_excluded_or_duplicate_files=int((~manifest.selected).sum()),
                   n_experimental_candidate_participants=int(primary.participant.nunique()),
                   n_experimental_candidate_visits=len(primary[["participant", "session", "collection_date"]].drop_duplicates()),
                   n_selected_active_bandit_runs=int(primary.task.eq("bandit").sum()),
                   n_usable_active_bandit_runs=int((primary.task.eq("bandit") & primary.behavior_valid.eq(True)).sum()),
                   n_selected_active_sst_runs=int(primary.task.eq("sst").sum()),
                   n_eligible_run_ssrt=int(primary.ssrt_valid.eq(True).sum()),
                   n_eligible_session_ssrt=int(sst.ssrt_valid.eq(True).sum()),
                   n_pilot_ids=int(manifest.loc[manifest.cohort.eq("pilot"), "participant"].nunique()),
                   n_known_intended_task_sessions=int(ps.intended_condition.isin(["theta", "beta", "sham"]).sum()),
                   n_verified_delivered_task_sessions=int(ps.delivery_verified.eq(True).sum()),
                   n_primary_early_stop_responses=int(primary.n_early_response_before_display.fillna(0).sum()),
                   n_primary_ssd_timing_mismatches=int(primary.n_ssd_timing_mismatch.fillna(0).sum()),
                   n_primary_ssd_state_mismatches=int(primary.n_ssd_state_mismatch.fillna(0).sum()))
    for name in ["p_stay_win", "p_shift_loss", "choice_accuracy", "reward_rate"]:
        # Participant first, then group, avoids weighting participants by visits/trials.
        value = bandit.groupby("participant")[name].mean().mean() if len(bandit) else np.nan
        summary["bandit_participant_mean_" + name] = float(value) if np.isfinite(value) else None
    issues = []

    def issue(priority, title, evidence, consequence, recommendation):
        issues.append(dict(priority=priority, issue=title, evidence=evidence, likely_consequence=consequence, recommended_action=recommendation))

    experimental_metadata = stimulation[stimulation.participant.isin(primary.participant.unique())] if len(stimulation) else stimulation
    device = experimental_metadata[experimental_metadata.record_kind.eq("device_info")] if len(experimental_metadata) else experimental_metadata
    if len(device):
        eeg_only = device[device.delivery_status.eq("eeg_only_documented")]
        zero = device[device.stim_record_count.eq(0)]
        issue("1_before_more_sessions", "Verify assignment and delivery documentation",
              f"{len(eeg_only)} experimental device .info files document EEG-only mode; {len(zero)} document zero stimulation samples. "
              "These records alone cannot establish successful delivery or whether EEG-only was intended sham. Sources: " + ";".join(device.source_file),
              "Intended assignment, protocol generation and actual stimulation cannot be equated.",
              "Study coordinator should reconcile the private counterbalance key, selected NIC protocol and device/delivery logs for every run; record intended sham explicitly. Preserve blinding for scorers.")
    if len(frequencies):
        flagged = frequencies[frequencies.qc_flags.str.contains("eeg_behavior_task_mismatch|zero_retained_epochs|band_edge|no_beta_suppression", regex=True)]
        if len(flagged):
            issue("1_before_more_sessions", "Resolve frequency provenance and reliability with the rhythm-validation team",
                  f"{len(flagged)} rhythm rows carry task-mismatch, zero-epoch, boundary or wrong-sign flags. PR #1 reports no primary beta/theta estimate passing provisional gates. Sources: " + ";".join(flagged.source_file.unique()),
                  "Historical numeric estimates are not established physiological rhythms; conflicting ID/report variants may select different values.",
                  "Review the existing rhythm-validation audit and original EEG/event pairing with the PI before further frequency decisions. This pipeline does not change selection or overwrite historical reports.")
    incomplete = manifest[manifest.exclusion_reason.fillna("").str.contains("incomplete|unexpected|empty") & manifest.participant.isin(primary.participant.unique())]
    if len(incomplete):
        issue("2_analytically_correctable", "Interrupted recordings and duplicate exports",
              ";".join(incomplete.source_file),
              "Counting aborted attempts or CSV/TSV copies inflates trial/run counts.",
              "Use manifest/exclusion_log; accept the uniquely complete chronological attempt. Keep both attempts and document restart circumstances; never select by modification time.")
    issue("2_analytically_correctable", "Active SST saved SSD is the next staircase state",
          f"code/sst_main.py updates ssd before appending the trial; reconstruction flags {summary['n_primary_ssd_state_mismatches']} primary state mismatches and {summary['n_primary_ssd_timing_mismatches']} onset mismatches.",
          "Using saved SSD directly biases SSRT. Early stop responses lack an observed signal delay.",
          "Use reconstructed pre-update state and observed stop_onset-stim_onset when present. Retain intended stops responding before display as failures with reconstructed SSD; consult sst_trials.csv.")
    issue("2_analytically_correctable", "Pre/post SST timing has different semantics",
          "code/sst_eeg.py records current SSD before updating it and synthesizes task-time stop_onset as stim_onset+ssd. Unix stop timestamps can also be filled by the recorder.",
          "A matching task-time SSD is arithmetic agreement, not independent display/hardware validation.",
          "Use schema-specific scoring and retain timestamp source. Review event/hardware timing independently for acquisition validation.")
    bad_sst = primary[primary.task.eq("sst") & ~primary.ssrt_valid.eq(True)]
    if len(bad_sst):
        issue("3_more_data_or_review", "Some SST runs cannot support an interpretable SSRT",
              "; ".join(r.source_file + ":" + str(r.ssrt_exclusion_reasons) for _, r in bad_sst.iterrows()),
              "Low stop counts, poor go behavior or failed race-model diagnostics can invalidate individual estimates.",
              "Inspect run-level QC before additional visits; follow existing speed/accuracy instructions. Pool only substantively eligible runs within the same visit/phase, with >=50 stop trials; do not pool across conditions.")
    issue("3_more_data_or_review", "Small incomplete within-participant sample and unknown condition key",
          f"{summary['n_experimental_candidate_participants']} candidate experimental IDs, {summary['n_experimental_candidate_visits']} visits; {summary['n_known_intended_task_sessions']} task-sessions have documented intended assignment.",
          "Efficacy inference and validated frequency-behavior correlations are premature.",
          "Confirm roster and private condition key locally, accumulate complete visits, then examine paired contrasts and model identifiability. Do not treat WSLS differences as learning-rate estimates.")
    warnings = pd.DataFrame(issues)
    write_csv(warnings, out / "collection_warnings.csv")
    pseq = orders[orders.participant.isin(primary.participant.unique()) & orders.phase.eq("active")]
    cohorts = manifest.groupby("cohort").agg(n_files=("source_file", "size"), n_ids=("participant", "nunique"), n_selected=("selected", "sum")).reset_index()
    session_columns = ["participant", "session", "collection_date", "task", "n_runs", "n_trials", "p_stay_win", "p_shift_loss", "n_win_transitions", "n_loss_transitions", "choice_accuracy", "reward_rate", "rt_median_ms", "go_accuracy", "go_omission_rate", "p_respond_stop", "ssrt_ms", "ssrt_exclusion_reasons", "condition_status"]
    narrative = (
        f"The experimental directory contains {summary['n_experimental_candidate_participants']} candidate study IDs across "
        f"{summary['n_experimental_candidate_visits']} visits, with {summary['n_selected_active_bandit_runs']} selected active Bandit runs "
        f"and {summary['n_selected_active_sst_runs']} selected active SST runs. A recruitment roster was not supplied: five-digit numeric IDs "
        "are candidates, not independently verified enrollment. Older pilot-folder recordings and test-like IDs remain separately labeled. "
        f"Across all sources, {len(manifest)} behavioral files were inventoried; {summary['n_excluded_or_duplicate_files']} were excluded as "
        "duplicates, incomplete/invalid or ambiguous attempts. All exclusions remain available in the manifest."
    )
    values = summary
    if len(bandit):
        behavior_text = (f"Participant-weighted active Bandit means are win-stay {values['bandit_participant_mean_p_stay_win']:.3f}, "
                         f"lose-shift {values['bandit_participant_mean_p_shift_loss']:.3f}, choice accuracy {values['bandit_participant_mean_choice_accuracy']:.3f}, "
                         f"and reward rate {values['bandit_participant_mean_reward_rate']:.3f}. These describe feedback-driven choice repetition and "
                         "selection of the higher-probability flower. They are not estimates of learning-rate asymmetry or stimulation effects.")
    else:
        behavior_text = "No selected active experimental-candidate Bandit data are available."
    sst_text = (f"{summary['n_eligible_run_ssrt']} active SST runs pass all run gates (provisional, >=20 stops); "
                f"{summary['n_eligible_session_ssrt']} pooled visit estimates pass all session gates (>=50 stops). "
                f"{summary['n_primary_early_stop_responses']} stop trials had a response before display; these remain intended stop failures. "
                "Failed-stop RT is compared with all responding-go RT, including errors. Go omissions are replaced by the maximum observed go RT "
                "in the integration distribution; the ceil(N_go × p_respond) ranked RT minus mean current-trial SSD gives SSRT. "
                "No SSRT value is emitted after a failed validity gate. Count/accuracy/omission/50–500-ms bounds are provisional project QC choices, "
                "not universal clinical thresholds. See configuration.json and README for exact gates.")
    frequency_text = (
        "Historical estimates, generated protocols and device settings are retained separately, with hashes and task/method/QC fields. "
        "No condition is inferred from a numeric frequency or from a generated file. No historical estimate is promoted to reliable by this analysis. "
        "The unmerged rhythm-validation PR reports no reliable primary estimates; no frequency-behavior correlation is calculated. "
        "Fields describing programmed device settings do not establish actual delivered current. A private local condition key may document intended "
        "assignment and independently verified delivery. The generated 0-Hz value alone is not proof of an intended or delivered sham session."
    )
    roadmap = ["Reconcile private roster, visit labels, protocol selection and delivery evidence; investigate urgent frequency/report pairing flags.",
               "Review SST exclusion reasons and observed/reconstructed SSD residuals after every new visit; retain source hashes and restart logs.",
               "Accumulate complete within-participant visits, then inspect intended-condition paired differences with session/task/run order retained.",
               "Choose and preregister a defensible mixed-effects analysis once paired coverage supports it; SSRT remains a visit-level estimand.",
               "Add RL models only after synthetic parameter/condition-effect recovery and predictive checks. Add validated clinical covariates later."]
    html = ["<!doctype html><html lang='en'><meta charset='utf-8'><title>TACS-3 behavioral report</title>",
            "<style>body{font:16px/1.55 system-ui;max-width:1250px;margin:36px auto;padding:0 24px;color:#172536}h1,h2{line-height:1.2}table{border-collapse:collapse;font-size:12px;display:block;overflow:auto}td,th{padding:7px;border-bottom:1px solid #ddd;text-align:left}img{max-width:100%;height:auto}a{color:#1b6395}.note{background:#eef5fa;padding:18px}</style>",
            "<h1>TACS-3 behavioral QC and initial results</h1><p class='note'>Developmental descriptive analysis. Source data are read-only. Candidate study IDs, pilots and tests are separated. No efficacy claim is supported.</p>",
            "<h2>Current sample</h2><p>" + escape(narrative) + "</p>" + table(cohorts),
            "<h2>Active behavioral findings</h2><p>" + escape(behavior_text) + "</p><p>" + escape(sst_text) + "</p>" + table(ps, session_columns),
            "<h2>Timestamp-derived task sequence</h2>" + table(pseq, ["participant", "session", "task_order", "chronological_task_sequence", "cross_run_overlap"]),
            "<h2>Data-collection warnings</h2>" + table(warnings),
            "<h2>Frequency and condition coverage</h2><p>" + escape(frequency_text) + "</p>",
            table(ps.drop_duplicates(["participant", "session"]), ["participant", "session", "theta_frequency_status", "beta_frequency_status", "n_generated_protocols", "n_device_records", "n_eeg_only_device_records", "condition_status", "verified_delivery_status"]),
            "<h2>Descriptive plots</h2>"]
    for path in plots:
        html.append(f"<figure><img src='{escape(path)}' alt='{escape(path)}'></figure>")
    html += ["<h2>Next steps</h2><ol>" + "".join("<li>" + escape(x) + "</li>" for x in roadmap) + "</ol>",
             "<h2>Reproduction and detailed outputs</h2><p>From the repository root: <code>python -m behavioral_analysis</code>. "
             "Methods and variable definitions are in behavioral_analysis/README.md and VARIABLE_DICTIONARY.md.</p><ul>"]
    for filename in ["manifest.csv", "participant_session_qc.csv", "run_metrics.csv", "session_metrics.csv", "exclusion_log.csv", "trial_qc_log.csv", "sst_trials.csv", "frequency_estimates.csv", "stimulation_records.csv", "collection_warnings.csv", "analysis_readiness.json", "provenance.json"]:
        html.append(f"<li><a href='{filename}'>{filename}</a></li>")
    html += ["</ul><p>SSRT reference: <a href='https://elifesciences.org/articles/46323'>Verbruggen et al., 2019 consensus guide</a>. "
             "Frequency validation: <a href='https://github.com/DVS-Lab/tacs3-bluesky/pull/1'>PR #1 (unmerged, read-only review)</a>.</p></html>"]
    (out / "report.html").write_text("\n".join(html))
    text = "TACS-3 INITIAL BEHAVIORAL REPORT\n\n" + narrative + "\n\n" + behavior_text + "\n\n" + sst_text + "\n\n" + frequency_text + "\n\n"
    text += ps.reindex(columns=session_columns).to_string(index=False) + "\n\nNEXT STEPS\n" + "\n".join(f"{i}. {x}" for i, x in enumerate(roadmap, 1)) + "\n"
    (out / "initial_results.txt").write_text(text)
    warning_text = "TACS-3 DATA-COLLECTION WARNINGS\n\n"
    for row in issues:
        warning_text += f"{row['priority']} — {row['issue']}\nEvidence: {row['evidence']}\nConsequence: {row['likely_consequence']}\nAction: {row['recommended_action']}\n\n"
    (out / "collection_warnings.txt").write_text(warning_text)
    (out / "sst_qc.html").write_text("<!doctype html><meta charset='utf-8'><h1>SST QC</h1><p>" + escape(sst_text) + "</p>" +
                                   table(runs[runs.task.eq("sst")], ["participant", "session", "cohort", "phase", "run", "n_go", "n_stop", "p_respond_stop", "go_accuracy", "go_omission_rate", "go_rt_mean_ms", "failed_stop_rt_mean_ms", "ssrt_ms", "ssrt_exclusion_reasons", "source_file"]) +
                                   ("<img style='max-width:100%' src='plots/sst_qc.png' alt='SST QC distributions'>" if plots else "<p>Figures disabled for this run.</p>"))
    return summary
