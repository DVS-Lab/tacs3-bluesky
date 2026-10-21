"""End-to-end orchestration. All writes are confined to an explicit output directory."""
import importlib.metadata
import json
import os
import platform
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd

from . import __version__, bandit, sst
from .common import digest, dump_json, write_csv
from .design import paired_differences, readiness
from .discovery import adjudicate, discover, select_records
from .metadata import condition_key, scan_metadata, session_metadata
from .identity import IdentityResolver


GROUP = ["participant", "session", "task", "phase", "cohort", "collection_date"]
REPORT_METRICS = ["ssrt_valid", "ssrt_ms", "ssrt_exclusion_reasons", "behavior_valid", "p_stay_win", "p_shift_loss",
                  "choice_accuracy", "reward_rate", "rt_median_ms", "pre_reversal_accuracy", "post_reversal_accuracy",
                  "missed_response_rate", "go_accuracy", "go_omission_rate", "p_respond_stop", "go_rt_mean_ms",
                  "failed_stop_rt_mean_ms", "n_stop", "n_early_response_before_display", "n_ssd_state_mismatch", "n_ssd_timing_mismatch"]


def ensure_report_columns(frame):
    for name in REPORT_METRICS:
        if name not in frame:
            frame[name] = np.nan
    return frame


def git_revision(root, ref="HEAD"):
    try:
        return subprocess.check_output(["git", "-C", str(root), "rev-parse", ref], text=True, stderr=subprocess.DEVNULL).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unavailable"


def run(root, out, config_path=None, key_path=None, roster_path=None, make_figures=True, adjudications_path=None, aliases_path=None):
    root, out = Path(root).resolve(), Path(out).resolve()
    for protected in [root / "data", root / "pilot_data", root / "stimulation", root / "code"]:
        if out == protected or protected in out.parents or out in protected.parents:
            raise ValueError("output must not overlap acquisition code or source data")
    if out == root:
        raise ValueError("use a dedicated output directory")
    config_path = Path(config_path or Path(__file__).with_name("config.json"))
    config = json.loads(config_path.read_text())
    identities = IdentityResolver(aliases_path)
    records = discover(root, identities)
    if not records:
        raise ValueError("no behavioral event files found under the repository data locations")
    # An optional local roster provides independently documented cohort identity.
    if roster_path:
        from .discovery import read_table
        roster, _ = read_table(roster_path)
        if not {"participant", "cohort", "evidence"}.issubset(roster):
            raise ValueError("roster requires participant, cohort, evidence")
        roster.participant = roster.participant.map(identities.resolve)
        if roster.participant.duplicated().any() or roster.evidence.str.strip().eq("").any():
            raise ValueError("roster identities must be unique and documented")
        if not roster.cohort.isin(["experimental_candidate", "pilot", "test", "unverified_identity"]).all():
            raise ValueError("invalid roster cohort")
        mapping = roster.set_index("participant").cohort.to_dict()
        for rec in records:
            p = rec.meta.get("participant")
            if p in mapping:
                rec.meta["cohort"] = mapping[p]
                rec.meta["cohort_evidence"] = roster.loc[roster.participant.eq(p), "evidence"].iloc[0]
    select_records(records, config)
    adjudicate(records, adjudications_path)
    manifest = pd.DataFrame([r.meta for r in records])
    manifest["primary_sample_status"] = np.where(manifest.cohort.eq("experimental_candidate") & manifest.phase.eq("active") & manifest.selected,
                                                  "candidate_active_selected", "not_primary")
    # Session labels reused across dates must never be silently pooled.
    active = manifest[manifest.selected & manifest.phase.eq("active") & manifest.cohort.eq("experimental_candidate")]
    date_conflicts = set()
    for pair, group in active.groupby(["participant", "session"]):
        if group.collection_date.nunique() > 1:
            date_conflicts.add(pair)
    bframes, sframes, revframes, metrics = [], [], [], []
    trial_log = []
    for rec in records:
        m = rec.meta
        if not m["selected"]:
            continue
        common = {k: m[k] for k in GROUP}
        common.update(run=m["run"], source_file=m["source_file"], duration_s=m["duration_s"], schema_family=m["schema_family"])
        if m["task"] == "bandit":
            frame, rev = bandit.score_trials(rec.data, **config["reversal"])
            values = bandit.metrics(frame, rev)
            for k, v in common.items():
                frame[k] = v
                if len(rev):
                    rev[k] = v
            bframes.append(frame)
            if len(rev):
                revframes.append(rev)
            for i, row in frame.iterrows():
                reasons = []
                if not row.valid_choice:
                    reasons.append("missing_or_invalid_choice")
                if row.valid_choice and pd.isna(row.reward_valid):
                    reasons.append("missing_feedback")
                if row.valid_choice and pd.isna(row.rt_ms):
                    reasons.append("missing_or_invalid_rt")
                if row.mapping_conflict:
                    reasons.append("choice_or_screen_mapping_conflict")
                if row.feedback_conflict:
                    reasons.append("feedback_conflict")
                if reasons:
                    trial_log.append(dict(source_file=m["source_file"], trial=i + 1, task="bandit", reasons=";".join(reasons), treatment="affected_metrics_only;mapping_conflict_invalidates_run"))
        else:
            frame = sst.reconstruct_ssd(rec.data, m["schema_family"], config["sst"])
            values = sst.metrics(frame, config["sst"])
            for k, v in common.items():
                frame[k] = v
            sframes.append(frame)
            for i, row in frame.iterrows():
                reasons = [k for k in ["response_before_stop_display", "ssd_state_mismatch", "ssd_timing_mismatch", "missing_stop_signal", "invalid_event"] if row[k]]
                if reasons:
                    trial_log.append(dict(source_file=m["source_file"], trial=i + 1, task="sst", reasons=";".join(reasons),
                                          treatment="retained_intended_stop_failure" if reasons == ["response_before_stop_display"] else "QC_flag;see_run_SSRT_eligibility"))
        metrics.append({**common, **values})
    btrials = pd.concat(bframes, ignore_index=True) if bframes else pd.DataFrame()
    strials = pd.concat(sframes, ignore_index=True) if sframes else pd.DataFrame()
    reversals = pd.concat(revframes, ignore_index=True) if revframes else pd.DataFrame()
    run_metrics = ensure_report_columns(pd.DataFrame(metrics) if metrics else pd.DataFrame(columns=GROUP + ["run", "source_file", "duration_s", "schema_family"]))
    # Order is derived from event timestamps, never lexical run filenames.
    timing = manifest[["source_file", "start_unix_s", "end_unix_s", "qc_flags"]]
    run_metrics = run_metrics.merge(timing, on="source_file", validate="one_to_one")
    run_metrics["run_order"] = np.nan
    run_metrics["task_order"] = np.nan
    orders = []
    for key, group in run_metrics.groupby(["participant", "session", "collection_date", "phase"], dropna=False):
        ordered = group.sort_values("start_unix_s", na_position="last")
        order_known = group.start_unix_s.notna().all()
        sequence = list(dict.fromkeys(ordered.task.tolist())) if order_known else []
        for n, (i, row) in enumerate(ordered.iterrows(), 1):
            if order_known:
                run_metrics.loc[i, "run_order"] = n
                run_metrics.loc[i, "task_order"] = sequence.index(row.task) + 1
        overlap = False
        if order_known:
            ends = ordered.end_unix_s.shift()
            overlap = bool((ordered.start_unix_s < ends).any())
        orders.append(dict(participant=key[0], session=key[1], collection_date=key[2], phase=key[3],
                           chronological_task_sequence=" > ".join(ordered.task) if order_known else "unverified_missing_clock",
                           task_order=" > ".join(sequence), cross_run_overlap=overlap,
                           source_files=";".join(ordered.source_file)))
    order_frame = pd.DataFrame(orders, columns=["participant", "session", "collection_date", "phase",
                                               "chronological_task_sequence", "task_order", "cross_run_overlap", "source_files"])
    sessions = []
    for trials, task in [(btrials, "bandit"), (strials, "sst")]:
        if not len(trials):
            continue
        for groupkey, g in trials.groupby(GROUP, dropna=False):
            common = dict(zip(GROUP, groupkey))
            sources = set(g.source_file)
            common.update(n_runs=g.source_file.nunique(), source_files=";".join(sorted(sources)))
            if task == "bandit":
                rev = reversals[reversals.source_file.isin(sources)] if len(reversals) else reversals
                values = bandit.metrics(g, rev)
            else:
                values = sst.metrics(g, config["sst"], "session")
                # Session SSRT pools only runs passing substantive gates; low-count-only
                # runs can contribute, since the pooled stop-count gate is applied anew.
                local_runs = run_metrics[run_metrics.source_file.isin(sources)]
                keep = []
                for _, r in local_runs.iterrows():
                    flags = set(str(r.ssrt_exclusion_reasons).split(";")) - {"", "insufficient_stop_trials", "insufficient_go_trials"}
                    if not flags:
                        keep.append(r.source_file)
                pool = g[g.source_file.isin(keep)]
                pooled = sst.metrics(pool, config["sst"], "session") if len(pool) else dict(ssrt_ms=np.nan, ssrt_valid=False, ssrt_status="withheld", ssrt_exclusion_reasons="no_eligible_runs")
                for name in ["ssrt_ms", "ssrt_valid", "ssrt_status", "ssrt_exclusion_reasons"]:
                    values[name] = pooled[name]
                values.update(ssrt_pool_source_files=";".join(sorted(keep)),
                              ssrt_pool_excluded_source_files=";".join(sorted(sources - set(keep))),
                              ssrt_pool_n_go=pooled.get("n_go", 0), ssrt_pool_n_stop=pooled.get("n_stop", 0),
                              ssrt_pool_p_respond=pooled.get("p_respond_stop", np.nan),
                              ssrt_pool_ssd_mean_ms=pooled.get("ssd_mean_ms", np.nan))
            if (common["participant"], common["session"]) in date_conflicts:
                values.update(ssrt_ms=np.nan, ssrt_valid=False, ssrt_status="withheld", ssrt_exclusion_reasons="session_label_reused_across_dates", behavior_valid=False)
            order_rows = run_metrics[run_metrics.source_file.isin(sources)]
            common["task_order"] = order_rows.task_order.dropna().iloc[0] if order_rows.task_order.notna().any() else np.nan
            common["session_order"] = common["session"]
            sessions.append({**common, **values})
    sessions = ensure_report_columns(pd.DataFrame(sessions) if sessions else pd.DataFrame(columns=GROUP + ["source_files", "n_runs", "n_trials"]))
    frequencies, stimulation, aux = scan_metadata(root, identities)
    key = condition_key(key_path, identities)
    session_meta = session_metadata(manifest, frequencies, stimulation, key)
    sessions = sessions.merge(session_meta, on=["participant", "session"], how="left", validate="many_to_one")
    run_metrics = run_metrics.merge(session_meta, on=["participant", "session"], how="left", validate="many_to_one")
    for frame in [btrials, strials]:
        if len(frame):
            context = run_metrics[["source_file", "task_order", "run_order", "intended_condition", "delivery_verified"]]
            enriched = frame.merge(context, on="source_file", how="left", validate="many_to_one")
            enriched["session_order"] = enriched.session
            if frame is btrials:
                btrials = enriched
            else:
                strials = enriched
    pairs = paired_differences(sessions)
    analysis_readiness = readiness(sessions, pairs)
    out.mkdir(parents=True, exist_ok=True)
    # Remove only this pipeline's known plot outputs, so a later unblinded/no-plot
    # run cannot leave an obsolete paired figure claiming current provenance.
    for name in ["bandit_wsls.png", "bandit_accuracy_reward.png", "bandit_reversals.png", "rt_and_omissions.png",
                 "sst_qc.png", "session_trajectories.png", "paired_differences.png"]:
        previous = out / "plots" / name
        if previous.is_file():
            previous.unlink()
    outputs = {"manifest.csv": manifest, "run_metrics.csv": run_metrics, "session_metrics.csv": sessions,
               "identity_aliases.csv": identities.rows,
               "identity_resolution.csv": manifest.reindex(columns=["source_file", "raw_participant", "recorded_participant", "participant", "participant_namespace", "identity_status", "alias_evidence", "alias_scope", "body_identity_resolution", "selected", "exclusion_reason"]),
               "participant_session_qc.csv": sessions, "task_sequence.csv": order_frame,
               "exclusion_log.csv": manifest[~manifest.selected],
               "primary_sample_exclusions.csv": manifest[manifest.primary_sample_status.ne("candidate_active_selected")],
               "trial_qc_log.csv": pd.DataFrame(trial_log, columns=["source_file", "trial", "task", "reasons", "treatment"]),
               "bandit_trials.csv": btrials, "sst_trials.csv": strials, "reversals.csv": reversals,
               "frequency_estimates.csv": frequencies, "stimulation_records.csv": stimulation,
               "auxiliary_inventory.csv": aux, "session_stimulation_metadata.csv": session_meta,
               "paired_differences.csv": pairs}
    # The QC table also counts excluded exports/attempts, so missing files cannot vanish.
    if len(manifest):
        filecounts = manifest.groupby(GROUP, dropna=False).agg(
            n_source_files=("source_file", "size"), n_selected_files=("selected", "sum"),
            available_source_files=("source_file", lambda v: ";".join(v)),
            file_exclusion_reasons=("exclusion_reason", lambda v: ";".join(sorted(set(x for x in v if x)))))
        outputs["participant_session_qc.csv"] = sessions.merge(filecounts.reset_index(), on=GROUP, how="outer", validate="one_to_one")
    for name, frame in outputs.items():
        write_csv(frame, out / name)
    dump_json(out / "analysis_readiness.json", analysis_readiness)
    dump_json(out / "configuration.json", config)
    revision = git_revision(root)
    provenance = dict(pipeline_version=__version__, repository_revision=revision,
                      rhythm_validation_revision=git_revision(root, "origin/codex/rhythm-estimation-validation"),
                      python=platform.python_version(), packages={name: importlib.metadata.version(name) for name in ["pandas", "numpy", "matplotlib"]},
                      config_sha256=digest(config_path), condition_key_sha256=digest(key_path) if key_path else None,
                      roster_sha256=digest(roster_path) if roster_path else None,
                      aliases_sha256=digest(aliases_path) if aliases_path else None,
                      identity_policy="preserve_G_R_and_leading_zeros;explicit_evidenced_flat_aliases_only",
                      adjudications_sha256=digest(adjudications_path) if adjudications_path else None,
                      acquisition_source_hashes={str(p.relative_to(root)): digest(p) for p in
                                                 [root / "code/bandit_main.py", root / "code/sst_main.py", root / "code/sst_eeg.py", root / "code/protocol_generator.py", root / "code/config.json"] if p.exists()},
                      analysis_source_hashes={str(p.relative_to(Path(__file__).parent)): digest(p) for p in Path(__file__).parent.glob("*.py")},
                      output_interpretation="All outputs share manifest/configuration/provenance; source_file(s) identify metric inputs. Plots use selected experimental candidates unless labeled pilot.",
                      source_integrity_verified=False)
    # Hash check detects accidental writes by analysis or concurrent collection.
    changed = [rec.meta["source_file"] for rec in records if digest(root / rec.meta["source_file"]) != rec.meta["sha256"]]
    if changed:
        raise RuntimeError("source files changed during analysis: " + ";".join(changed))
    provenance["source_integrity_verified"] = True
    dump_json(out / "provenance.json", provenance)
    plots = []
    if make_figures:
        os.environ.setdefault("MPLCONFIGDIR", str(out / ".matplotlib"))
        from .plots import make_plots
        plots = make_plots(run_metrics, sessions, btrials, strials, reversals, pairs, out)
    from .report import build_reports
    summary = build_reports(out, manifest, run_metrics, sessions, frequencies, stimulation, order_frame, plots, analysis_readiness)
    dump_json(out / "summary.json", summary)
    # A run-level dependency index associates every derived artifact with exact inputs.
    dump_json(out / "output_index.json", {str(p.relative_to(out)): {"sha256": digest(p), "provenance": "provenance.json", "inputs": "manifest.csv;configuration.json;auxiliary_inventory.csv"}
                                           for p in sorted(out.rglob("*")) if p.is_file() and p.name != "output_index.json" and ".matplotlib" not in p.parts})
    return summary
