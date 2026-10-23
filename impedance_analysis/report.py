"""Identifier-minimized diagnostic report and scientific plots."""
from html import escape

import numpy as np
import pandas as pd


def table(frame):
    return frame.to_html(index=False, border=0, na_rep="—", float_format=lambda x: f"{x:.3f}", escape=True)


def plots(out, inventory, readings, threshold):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import LogNorm
    files = []
    standalone = readings[readings.export_type.eq("standalone") & readings.structurally_valid & readings.row_number.eq(1)]
    ordered = inventory[inventory.export_type.eq("standalone")].sort_values(["timestamp", "export_id"])
    if len(standalone):
        matrix = standalone.pivot(index="export_id", columns="physical_channel", values="value").reindex(index=ordered.export_id, columns=range(1, 9))
        array = matrix.to_numpy(dtype=float)
        numeric = np.ma.masked_where((array <= 0) | (array == 150000) | ~np.isfinite(array), array)
        fig, ax = plt.subplots(figsize=(11, max(7, len(matrix) * .21)))
        im = ax.imshow(numeric, aspect="auto", norm=LogNorm(vmin=500, vmax=50000), cmap="viridis", interpolation="none")
        y, x = np.where(array == 150000)
        ax.scatter(x, y, color="#db334f", marker="s", s=28, label="exact 150000 (meaning unconfirmed)")
        y, x = np.where(array == 0)
        ax.scatter(x, y, color="gray", marker="x", s=24, label="zero (uninterpreted)")
        ax.set_xticks(range(8), range(1, 9))
        labels = [f"{str(row.timestamp).replace('T',' ')}{' †' if row.source_availability == 'git_history_only' else ''}" for row in ordered.itertuples()]
        ax.set_yticks(range(len(matrix)), labels, fontsize=7)
        ax.set_xlabel("Physical channel (location is configuration-dependent)")
        ax.set_title("Standalone impedance exports in chronological order\nExact 150000 is categorical; gray/blank is not evidence of a normal reading")
        fig.colorbar(im, ax=ax, label="Recorded numeric value, log scale (Ω interpretation to confirm)", extend="both", fraction=.025)
        ax.legend(loc="upper center", bbox_to_anchor=(.5, -.025), fontsize=8)
        fig.tight_layout()
        fig.savefig(out / "heatmap.png", dpi=150)
        plt.close(fig)
        files.append("heatmap.png")
    for date in ["2026-10-20", "2026-10-22"]:
        day = standalone[standalone.timestamp.str.startswith(date)]
        if day.empty:
            continue
        fig, axes = plt.subplots(4, 2, figsize=(13, 11), sharex=True, sharey=True)
        import matplotlib.dates as mdates
        for ch, ax in enumerate(axes.flat, 1):
            group = day[day.physical_channel.eq(ch)].sort_values("timestamp")
            times = pd.to_datetime(group.timestamp)
            # A categorical strip above the numeric axes prevents 150000 being read as a measured resistance.
            ordinary = group.value.where(group.value.gt(0) & group.value.ne(150000))
            ax.plot(times, ordinary, "o-", color="#207a9c", markersize=4)
            special = group.value.eq(150000)
            ax.scatter(times[special], [1.04] * int(special.sum()), transform=ax.get_xaxis_transform(), color="#db334f", marker="s", clip_on=False, zorder=5)
            ax.axhline(threshold, color="#ac6b1d", linestyle="--", linewidth=.8)
            ax.set_yscale("log")
            ax.set_ylim(500, 200000)
            ax.set_yticks([1000, 4000, 10000, 20000, 100000], ["1k", "4k", "10k", "20k", "100k"])
            ax.text(.02, .95, f"Channel {ch}", transform=ax.transAxes, va="top", fontsize=10, bbox=dict(facecolor="white", alpha=.8, edgecolor="none"))
            ax.grid(alpha=.18)
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
            ax.tick_params(axis="x", rotation=25)
        fig.suptitle(f"{date}: standalone checks\nRed squares above axes = exact 150000, not numeric resistance; dashed line = descriptive threshold", fontsize=12)
        fig.supylabel("Recorded numeric value (log scale; units/mode to confirm)")
        fig.supxlabel("Filename wall time; timezone unverified. Setup is unknown without operator evidence.")
        fig.tight_layout(rect=(0, .02, 1, .93))
        filename = f"timeseries_{date}.png"
        fig.savefig(out / filename, dpi=160)
        plt.close(fig)
        files.append(filename)
    return files


def build_report(out, inv, values, summary, changes, patterns, result, threshold, figures):
    selected = inv[inv.export_type.eq("standalone")].sort_values("timestamp")
    priorities = selected[["export_id", "timestamp", "source_availability", "setup", "info_link_status"]].copy()
    for ch in range(1, 9):
        lookup = values[values.physical_channel.eq(ch) & values.row_number.eq(1)].set_index("export_id").value
        priorities[f"ch{ch}"] = priorities.export_id.map(lookup)
    priorities.to_csv(out / "standalone_checks.csv", index=False)
    priorities = priorities[priorities.timestamp.str.startswith(("2026-10-19", "2026-10-20", "2026-10-22"))]
    priorities.to_csv(out / "priority_checks.csv", index=False)
    observations = []
    for date in ["2026-10-19", "2026-10-20", "2026-10-22"]:
        d = values[values.export_type.eq("standalone") & values.timestamp.str.startswith(date) & values.structurally_valid]
        if d.empty:
            continue
        n = d.export_id.nunique()
        exact = d.category.eq("exact_150000")
        ch1 = d[d.physical_channel.eq(1)].sort_values("timestamp")
        observations.append(f"{date}: {n} standalone exports; {int(exact.sum())}/{len(d)} channel slots are exactly 150000. "
                            f"Channel 1 values in time order: {', '.join(f'{x:g}' for x in ch1.value)}.")
    daily = values.assign(date=values.timestamp.str[:10]).groupby(["export_type", "source_availability", "date"]).agg(
        n_exports=("export_id", "nunique"), n_channel_slots=("physical_channel", "size"),
        n_exact_150000=("category", lambda x: int(x.eq("exact_150000").sum())),
        n_zero=("category", lambda x: int(x.eq("zero_uninterpreted").sum()))).reset_index()
    daily.to_csv(out / "daily_summary.csv", index=False)
    files = plots(out, inv, values, threshold) if figures else []
    transition_note = "Recorded changes are tabulated below; unknown intervening handling, preparation or wiring prevents verified hardware-recovery claims."
    relevant = changes[changes.timestamp.str.startswith(("2026-10-20", "2026-10-22"))] if len(changes) else changes
    recovery = relevant[relevant.transition.eq("exact_150000_to_positive_at_or_below_threshold")] if len(relevant) else relevant
    if len(recovery):
        transition_note = f"{len(recovery)} exact-150000 → positive-at/below-threshold channel transitions occur on the priority dates. " + transition_note
    pattern_note = "The exploratory ~4 kΩ screen is a hypothesis, not evidence of actual testboard connection."
    if len(patterns):
        pattern_note = f"{len(patterns)} exports match the exploratory ~4 kΩ screen. " + pattern_note
    body = ["<!doctype html><html lang='en'><meta charset='utf-8'><title>TACS-3 impedance diagnostics</title>",
            "<style>body{font:16px/1.5 system-ui;max-width:1200px;margin:36px auto;padding:0 24px;color:#172536}table{border-collapse:collapse;font-size:12px;display:block;overflow:auto}td,th{padding:6px;border-bottom:1px solid #ddd;text-align:left}img{max-width:100%;height:auto}.note{background:#eef4fa;padding:16px}h1,h2{line-height:1.2}a{color:#176288}</style>",
            "<h1>TACS-3 historical impedance diagnostics</h1>",
            "<p class='note'>Verified export observations, with configuration uncertainty preserved. Exact <b>150000</b> is a distinct recorded value with unconfirmed meaning. It is not labeled an open circuit, ceiling, or literal 150 kΩ. No hardware fault or successful treatment is established by these exports.</p>",
            "<h2>Coverage</h2><p>" + escape(f"{result['n_exports']} exports: {result['n_standalone_exports']} standalone and {result['n_continuous_exports']} continuous. "
            f"{result['n_working_tree_standalone_exports']} standalone exports are currently present; {result['n_history_only_exports']} additional exports were recovered read-only from Git history. "
            f"{result['n_channel_readings']} channel slots retained; {result['n_files_with_issues']} files have parse/filename issues. "
            f"{result['n_documented_configuration_exports']} exports have an operator configuration record. "
            f"{result['n_metadata_records']} metadata/protocol files inventoried; {result['n_metadata_parse_issues']} have parse/configuration warnings. "
            "Source hashes were unchanged before/after analysis. No participant identifiers, assignment key, protocol frequency, source paths or device network identifier are included in this share directory.") + "</p>",
            "<h2>Strongest observations</h2><ul>" + "".join("<li>" + escape(x) + "</li>" for x in observations) + "</ul>",
            "<p>" + escape(transition_note + " " + pattern_note) + "</p>",
            "<h2>Competing explanations and decisive evidence</h2>",
            "<table><tr><th>Explanation</th><th>Why plausible / limitation</th><th>Evidence needed</th></tr>",
            "<tr><td>Intermittent channel/cable/connector path</td><td>Channel-specific exact values followed by low readings; setup may have changed</td><td>Documented channel-by-channel bench results with cable/connector identity and handling times</td></tr>",
            "<tr><td>Contact/preparation or setup/reference changes</td><td>Several channels decrease together; not uniquely a hardware effect</td><td>Operator log: headcap/electrodes, CMS/DRL, preparation, substitutions and timestamps</td></tr>",
            "<tr><td>Unused/disconnected inputs</td><td>High values outside a connected subset need not be faults; subset cannot be inferred from values</td><td>Connected and active physical channels for each check</td></tr>",
            "<tr><td>NIC/device status encoding or measurement mode</td><td>Repeated exact 150000 and zeros; standalone and continuous logs differ</td><td>Manufacturer definition of ImpVal/IMP units, zero, 150000, AC/DC mode, NIC/firmware behavior</td></tr></table>",
            "<h2>Priority checks</h2>" + table(priorities.drop(columns="export_id")),
            "<h2>Channel summaries and denominators</h2><p>Standalone checks and continuous samples are separate. Git-history-only records are separate from the working tree. The denominator is structurally valid, finite, positive channel readings, including exact 150000; zero, negative, missing and malformed rows are separately counted. Continuous samples are temporally dependent and are not independent checks. Repeated exports are retained; these are export/sample frequencies, not participant failure risks.</p>",
            "<p>Documented-connected and documented-active denominators use only explicit operator evidence. A configured NIC role is not proof of a physical connection. With no configuration log, those denominators are zero and rates are undefined. Counts across all recorded channels must not be interpreted as hardware-fault rates.</p>",
            table(summary[summary.denominator_scope.eq("all_recorded_connection_unknown_or_known")] if len(summary) else summary),
            "<p>All connection-specific denominators are in <a href='channel_summary.csv'>channel_summary.csv</a>. The descriptive numeric threshold is " + escape(f"{threshold:g}") + "; if ordinary exports are in Ω, this is 20 kΩ at the default setting. It is not an operational acceptance rule. Exact 150000 is excluded from the separate 'above threshold other' category.</p>",
            "<h2>Chronological plots</h2><p>Standalone heatmap rows are successive exports, not equally spaced time. † denotes a Git-history-only export. Red markers represent a category, not measured 150 kΩ. Channel numbers are physical indices; F3 must be established from the applicable configuration.</p>"]
    body += [f"<figure><img src='{escape(f)}' alt='{escape(f)}'></figure>" for f in files]
    body += ["<h2>Suspicious sequences</h2><p>Adjacent standalone exports within the same preserved identity, visit and filename day, with gaps ≤2 hours. No cross-identity, overnight or continuous-sample joins. Unknown setup prevents a verified recovery claim.</p>",
             table(changes[changes.timestamp.str.startswith(("2026-10-20", "2026-10-22"))] if len(changes) else changes),
             "<details><summary>Testboard-like pattern table</summary><p>At least two structurally valid channel readings in 3500–4500 recorded units. This exploratory window is a pattern screen, not a testboard classifier; ordinary electrode readings can match it.</p>" + table(patterns) + "</details>",
             "<details><summary>Daily coverage, including continuous logs</summary><p>Each IMP row has eight values plus a Unix-millisecond time. Filename wall time and UTC sample time remain separate; their clock relation is unverified. Zero does not establish a usable impedance or a disconnected channel. Associated NIC versions/firmware are carried in exports/readings only where a run-name/time or operator link exists; no version is propagated to unlinked checks.</p>" + table(daily) + "</details>",
             "<h2>Files for Neuroelectrics</h2><ul>"]
    for f in ["exports.csv", "standalone_checks.csv", "readings.csv", "channel_summary.csv", "suspicious_sequences.csv", "pattern_hypotheses.csv", "priority_checks.csv", "daily_summary.csv", "parse_errors.csv", "summary.json"]:
        body.append(f"<li><a href='{f}'>{f}</a></li>")
    body += ["</ul><p>This directory minimizes identifiers but retains diagnostic dates. The sibling private directory contains source paths/hashes, recruitment identities, candidate links and the blank configuration-log template. Keep it local. Supply actual setup records via --configuration-log and rebuild; the share report never includes free-text operator evidence.</p>",
             "<h2>Manufacturer questions</h2><p>What do exact 150000 and zero encode for this StarStim-8/NIC/firmware combination? Are ImpVal and IMP values in Ω, with the same measurement method and reference? Which channels are measured in each mode? Can status/stale values persist across rechecks? What approved testboard values/tolerances and diagnostic records distinguish the device, flat cable, electrode cable and contact paths?</p>",
             "<p>Neuroelectrics describes prelaunch AC/DC checks and monitored impedance, but this does not decode the special export value: <a href='https://supportne.freshdesk.com/support/solutions/articles/35000308661-how-is-impedance-measured-'>How is Impedance Measured?</a>. Testboard debugging is described in its <a href='https://www.neuroelectrics.com/api/downloads/NE_UM_P1_SH_1.3_EN.pdf'>Starstim-Home manual</a>; that model's guidance does not calibrate this StarStim-8 setup. This report does not authorize a stimulation or bench-test procedure.</p></html>"]
    (out / "report.html").write_text("\n".join(body))
