# Prioritized next analyses

Updated 2026-10-23; see [SCIENTIFIC_STATUS.md](SCIENTIFIC_STATUS.md) for the
current evidence and [TEAM_HANDOFF.md](TEAM_HANDOFF.md) for a shareable note.

**Immediate device handoff:** send the locally generated impedance `share/` bundle
to Neuroelectrics through the lab's normal support process. Have the operator
complete the private, hash-bound configuration log for the October 19/20/22 checks,
including connected/active channels, assembly/cable identity, handling and check
mode. Exact 150000 has unconfirmed meaning. Do not diagnose faults on unused
channels or infer a testboard setup from ~4 kΩ values. Review the approved device
workflow with the PI/authorized operator; this analysis changes no parameters.

**Versioned protocol reconciliation:** main's `6b10b90` now uses a separate all-EEG,
zero-amplitude template for the generator's sham branch and overwrites four old
generated files. Retrieve the exact imported historical version/hash and NIC
execution records rather than treating the current working-tree file as the past
session's protocol. Neither the old 0-Hz convention nor the newer file establishes
an approved sham envelope or retrospective delivery.


1. **Before more visits:** coordinator/PI reconciliation of intended assignment,
   selected protocol and documented delivery; review historical frequency reports
   with zero epochs, mismatched EEG/task pairing, unreconciled report/protocol versions, boundary
   extrema or wrong-sign beta. See the generated warning report and existing rhythm
   PR. This analysis does not decide a replacement stimulation procedure.
2. **After every visit:** run the one-command pipeline. Review newly excluded files,
   restarts, task sequence/duration, reconstructed SSD residuals, go accuracy/speed,
   omissions, stop tracking and SSRT eligibility. Confirm the private recruitment
   roster and evidenced legacy-alias map while preserving G/R namespaces; resolve repeated complete attempts with hash-bound adjudications.
3. **As complete visit pairs accumulate:** use documented intended assignments for
   paired theta–sham Bandit and beta–sham SST summaries. Retain participant, visit,
   task order, run order and delivery verification. Inspect practice/fatigue and
   speed–accuracy tradeoffs before interpreting differences.
4. **When paired coverage is sufficient:** finalize exclusions and estimands before
   efficacy analysis. Fit binomial mixed-effects Bandit transitions with feedback
   and condition interaction, accounting for visit/task/run order. Analyze SSRT at
   participant/visit level and assess general go response speed as a covariate or
   sensitivity outcome. Check identifiability and convergence; do not manufacture
   trial-level SSRT replicates.
5. **Later exploratory work:** reliable rhythm estimates can support explicitly
   exploratory frequency–behavior relationships; cross-sectional correlations do
   not establish stimulation efficacy. Add validated clinical variables, PANAS or
   betting outcomes through metadata joins. Evaluate RW/dual-outcome/perseveration
   models only after parameter recovery, condition-effect recovery and predictive
   checks. Keep these estimates conceptually distinct from WSLS probabilities.
