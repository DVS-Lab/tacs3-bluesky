# Suggested team note

We now have a reproducible impedance diagnostic bundle for Neuroelectrics, including
all 92 current standalone checks, 110 continuous logs and eight checks recovered
read-only from Git history. Channel 1 changes from exact 150000 to low readings on
October 20, with another transition on October 22. The October 22 ~4 kΩ patterns
are compatible with testboard checks, but we need the operator's setup/channel log
to confirm that. We have not established what 150000 means or diagnosed a hardware
fault; high values on unused channels should not be counted as failures.

Please use the local **impedance `share/` bundle** for the support handoff; it
contains the HTML report, plots and CSVs, with recruitment IDs and assignment
information omitted. Keep the `private/` directory local. The
[diagnostic README](https://github.com/DVS-Lab/tacs3-bluesky/blob/codex/impedance-diagnostics-consolidation/impedance_analysis/README.md)
explains the configuration log and the exact questions for Neuroelectrics.

Behavioral QC is ready for descriptive use: two candidate active-study IDs, four
visits, eight runs per task and four eligible pooled SSRT estimates. Condition
comparisons remain unavailable without the private assignment/delivery records.
The [scientific status](https://github.com/DVS-Lab/tacs3-bluesky/blob/codex/impedance-diagnostics-consolidation/behavioral_analysis/SCIENTIFIC_STATUS.md)
gives the sample sizes, QC findings and next decisions;
[pre-session checks](https://github.com/DVS-Lab/tacs3-bluesky/blob/codex/impedance-diagnostics-consolidation/behavioral_analysis/TEAM_PRESESSION_CHECKS.md)
list the records to retain. The G/R prefixes are the intended recruitment
namespaces; we preserve them and use documented aliases for legacy records.

One update matters for the protocol review: main now contains a newer all-EEG,
zero-amplitude template, so today's generated files cannot establish what was
imported during an earlier session. Authorized protocol staff should use the dated
[protocol investigation](https://github.com/DVS-Lab/tacs3-bluesky/blob/codex/impedance-diagnostics-consolidation/behavioral_analysis/PROTOCOL_VARIANT_INVESTIGATION.md)
and reconcile exact versions with the approved control procedure and execution
logs. The unmerged [rhythm-validation PR #1](https://github.com/DVS-Lab/tacs3-bluesky/pull/1)
reports no primary rhythm estimates passing its provisional gates. This analysis
branch changes no acquisition code, protocols, parameters or participant data.
