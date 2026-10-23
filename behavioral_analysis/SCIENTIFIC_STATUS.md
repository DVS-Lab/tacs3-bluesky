# TACS-3 analysis status — 2026-10-23

**Ready:** impedance evidence for Neuroelectrics and descriptive behavioral QC.
**Unresolved:** setup/device interpretation, assignment/delivery records, approved
control implementation and reliable individualized rhythms. Stimulation-effect
inference is not currently supported.

Reviewed main `1c27842` and open [PR #1](https://github.com/DVS-Lab/tacs3-bluesky/pull/1),
head `e3b0df59c6d77f7668a02f4d6c0bbdce27c54a23`, before implementation. Work is on
`codex/impedance-diagnostics-consolidation`; PR #1 was neither merged nor deployed.
Only analysis, tests and documentation change. Participant results and private
configuration/assignment/alias records remain outside Git.

## Impedance: first handoff

The [diagnostic package](../impedance_analysis/README.md) inventories **92 current
standalone exports, 110 continuous logs and eight history-only standalone exports**
recovered in memory from Git. Six history-only checks were removed with a failed
visit cleanup; two older checks were also absent. History-only denominators are
separate. All 100 standalone exports contain eight parseable values. **47 continuous
logs are empty** and explicitly retained; the others contain 16,219 rows. All 311
available `.info`/protocol files are inventoried. Source hashes remain unchanged.

- **October 19:** two checks; all 16 values are positive and below 20,000 recorded
  units (range 1367–7179). Low impedance does not independently verify delivery.
- **October 20:** channel 1 is exactly 150000 at 15:21:11, 15:28:48 and 15:34:53,
  then 3251 at 15:41:23, falling to 1196 by 15:57:45.
- **October 22:** all eight values are 3966–4398 at 08:04:46. At 08:17:36,
  channels 1/4 read 4013/4048, with six exact-150000 values. These are testboard-like
  hypotheses, not confirmed setups. Channel 1 returns to exact 150000 at
  08:29:54/08:34:37, then 15232 at 08:37:05. Channels 5/8 remain exactly 150000
  through the final check; other channels also change.

Channel 1 has **18/92 exact-150000** readings and three other >20,000 values in the
current standalone exports. This is an export flag frequency, not a hardware-fault
probability. No operator setup log was supplied: **documented-connected and
active denominators are zero**. Unused inputs, contact, cables/connectors, device
behavior and measurement/status encoding remain competing explanations. F3's
physical mapping must come from the applicable configuration.

Send the local **`share/` bundle**—HTML, heatmap, October 20/22 plots and CSVs—through
the lab's normal support channel. Keep `private/` local. Complete its hash-bound
operator template where records exist. Ask Neuroelectrics to decode **150000 and
zero**, confirm ImpVal/IMP units/modes and specify approved diagnostic evidence.
[Manufacturer impedance guidance](https://supportne.freshdesk.com/support/solutions/articles/35000308661-how-is-impedance-measured-)
does not establish the special value's meaning for this device/build.

## Behavioral coverage and findings

The existing pipeline was rebuilt using all available sources, without a private
roster, aliases, assignment key or adjudications. **239 files** yield **118 selected**
files across cohorts/phases and **121 exclusions**: 54 duplicate exports, 28 ambiguous
complete attempts, 27 short Bandit files, nine identity conflicts (one also has a
session conflict), two incomplete SST files and one empty file. These are
all-source file counts, not lost experimental-run counts; 12 pilot IDs remain
separately inventoried.

The active experimental-candidate subset contains **two IDs, four visits, eight
Bandit runs and eight SST runs**. All eight Bandit runs, eight run-level SSRTs and
**four pooled active SSRTs** pass current gates. There are no primary active SSD
state/onset mismatches or responses before stop display. The October 20 SST run-2
restart retains the 91-trial complete attempt and excludes the 10-trial attempt.
Other IDs have only localizer/pre/post records. These remain candidate ID counts
until the roster confirms enrollment; G/R strings and leading zeros are preserved.

Participant-weighted Bandit means: **win-stay 0.964, lose-shift 0.384, accuracy
0.736, reward rate 0.614**. Pre-reversal accuracy spans 0.734–0.810 versus
0.484–0.586 in the first five post-reversal trials. This describes feedback and
contingency sensitivity, not fitted learning-rate asymmetry.

Pooled active **SSRT spans 228.8–314.3 ms**, go accuracy 0.983–1.000, omissions
0–0.0078 and stop-response probability 0.463–0.492. Structurally valid complete
runs pool before behavioral gates; run warnings and invalid event/SSD exclusions
remain visible. Pre/post phases are never pooled together to satisfy stop counts.

| Comparison among IDs with active study data | Available | Eligible outcome pairs |
|---|---|---|
| Active visit 2 − visit 1, Bandit | 2 ID pairs | 2 |
| Active visit 2 − visit 1, SST SSRT | 2 ID pairs | 2 |
| Bandit post − pre | 3 visit pairs / 2 IDs | 3 |
| SST post − pre | 4 visit pairs / 2 IDs | **0 SSRT pairs** under phase gates |
| Theta−sham, beta−sham or theta−beta | **0 documented-condition pairs** | 0 |

Mean visit-2 minus visit-1 SSRT is −46.5 ms across two IDs, confounded by time,
practice, order and unknown treatment. One Bandit pre phase lacks an eligible
exact-namespace match. Local `comparison_coverage.csv` and
`descriptive_longitudinal_pairs.csv` contain coverage and contrasts. No efficacy
model or frequency–behavior correlation was fit.

## Rhythm and delivery limitations

[PR #1's pilot report](https://github.com/DVS-Lab/tacs3-bluesky/blob/e3b0df59c6d77f7668a02f4d6c0bbdce27c54a23/docs/pilot_rhythm_validation_report.md)
reports 38 EEG recordings, 28 explicit behavioral matches and **0/95 primary
analyses passing provisional reliability gates**. Four response-beta recordings
meet trial/retention gates but fail localization/corroboration/stability; no reliable
cross-task/pre/post pairs remain. Historical Bandit values reproduce 11/11
numerically; two SST adaptations reproduce only 4/11 and 5/11. The original SST
method remains unresolved. Those are the unmerged branch's findings; its estimator
was reviewed, not rerun/deployed here. Historical active-study reports also retain
task mismatches, zero epochs, boundary estimates and wrong-sign beta warnings.

Main's [October 22 generator change](https://github.com/DVS-Lab/tacs3-bluesky/commit/6b10b90bbaf67c15da2d95c7b6e3444cd8f98be0)
adds a separate all-EEG/zero-amplitude template and overwrites four historical
protocols. Older active-style 0-Hz and newer all-EEG files differ; current XML
cannot establish a past import or delivered envelope. The dated
[protocol investigation](PROTOCOL_VARIANT_INVESTIGATION.md) preserves this distinction.

There are **zero documented intended-condition and zero verified-delivery
task-sessions** in the analysis. Seventeen relevant run-specific device `.info`
files include restart/missing-counterpart gaps: 13 list zero stimulation samples
and four EEG-only mode. These are recording observations, not proof of 17 failures.

## Highest-value next steps

1. **Operator/device team:** document each priority check's assembly, connected/active
   physical channels, references, handling, cable/testboard identity and NIC/firmware/
   check mode; obtain manufacturer interpretation under the approved device workflow.
2. **Coordinator:** supply private roster/evidenced aliases, original assignment,
   exact imported protocol hashes/versions and task-to-NIC execution/restart logs.
3. **PI/protocol administrator:** reconcile approved sham/control with historical
   0-Hz and newer EEG-only files, installed-NIC semantics and required execution/
   current-envelope evidence. Retain unresolved retrospective uncertainty.
4. **PI/rhythm team:** finish PR #1's source/pairing review, locate the original SST
   estimator and decide the approved policy for unreliable/unavailable rhythms.
5. **Analysis team:** rerun QC after visits, collect documented condition pairs and
   finalize estimands/model identifiability before efficacy or RL modeling.

Validation: **105 tests passed**, including complete-data read-only integrations;
source/acquisition hashes were unchanged. Plotting dependencies emit deprecation
warnings; no RuntimeWarnings occurred. Use [TEAM_HANDOFF.md](TEAM_HANDOFF.md) for the
short message and [TEAM_PRESESSION_CHECKS.md](TEAM_PRESESSION_CHECKS.md) for operational detail.
