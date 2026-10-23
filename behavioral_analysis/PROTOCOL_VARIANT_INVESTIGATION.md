# G11450 / 11450 protocol investigation

## Current-main update — 2026-10-23

The investigation below is a **historical October 20 snapshot**. It is preserved
so the original findings remain auditable; its statements about the “current”
generator and file contents apply to that snapshot, not to today's main.

Main commit [`6b10b90`](https://github.com/DVS-Lab/tacs3-bluesky/commit/6b10b90bbaf67c15da2d95c7b6e3444cd8f98be0)
(October 22) introduced `PROTOCOL_SHAM_TEMPLATE.neprot` and selects it for the sham
branch. That template records `stepType=7`, `electrodeType=1` on all eight channels
and zero programmed current amplitudes. Its physical index mapping also places F3
at channel 6 and P4 at channel 1. These are XML observations and the source author's
stated all-EEG intent, not independently verified NIC semantics or wiring.
The four **unprefixed** visit-2 files originally containing 4.5 Hz were overwritten
with this new template. The prefixed G files retain their older active-style 0-Hz
configuration. No analysis change made here generated or modified these files.

Thus the original 4.5-vs-0 comparison must be reproduced from its recorded Git
revisions. Current files containing 0 Hz are not interchangeable. A later generated
file cannot establish what NIC imported or executed on October 19/20, and does not
retroactively resolve approved sham versus EEG-only control. Retain exact file
hash/version, original private assignment, operator confirmation, installed NIC
semantics and execution/current-envelope evidence. The G/R recruitment namespace
is appropriate throughout; no alias is inferred from a matching numeric suffix.

See [SCIENTIFIC_STATUS.md](SCIENTIFIC_STATUS.md) and the
[impedance diagnostic methods](../impedance_analysis/README.md) for the updated
handoff. No acquisition, generator, timing, protocol or raw data was changed by
this analysis branch.

## Historical October 20 investigation


Reviewed 2026-10-20. Scope: read-only Git/source/XML investigation and offline
reproduction in disposable workspace files. No experimental script, executable,
protocol, frequency report, condition key or device setting was changed. This note
contains parameters relevant to blinding; circulate to the PI and authorized
protocol staff under the study's existing rules.

**The G prefix alone does not explain the switch from 4.5 Hz to 0 Hz. The recorded
files exactly match different condition-selection branches of the generator.
The 0-Hz files also lack the explicit sham-step settings seen in an earlier
matched active/sham export pair. Their actual interpretation/output in NIC
2.1.4.4 remains unverified.**

The recruitment explanation supplied by Avi clarifies that G/R prefixes are an
intentional long-term identity policy. The prefix is not the defect under review.
Legacy records should be linked by a documented alias, not by stripping the source
namespace. The 0.2 analysis correction is described in [IDENTITY_ALIASES.md](IDENTITY_ALIASES.md).
The investigation below concerns differing generator selections during that
migration; it does not establish that the later G files were used for treatment.

## 1. Git establishes two distinct sets, first committed on different days

| Set | First-added commit (not proven generation time) | Recorded contents |
|---|---|---|
| `11450_visit2_{SST,bandit}_run{1,2}.neprot` | [`f175084`, October 19](https://github.com/DVS-Lab/tacs3-bluesky/commit/f17508491244a747e5c97281b528b9cf70bdf6ea) | Four 4.50-Hz protocols, with the unprefixed 4.50-Hz theta / unavailable-beta report |
| `G11450_visit2_{SST,bandit}_run{1,2}.neprot` | [`fccf758`, October 20](https://github.com/DVS-Lab/tacs3-bluesky/commit/fccf7588977c88183b1491b26eae36b4403fa99f) | Four 0-Hz protocols, with the prefixed 4-Hz theta / 30-Hz beta report |

The October 20 Python change replaces numeric-only ID validation/integer conversion
with an alphanumeric string. The counterbalance mapping and frequency-selection
logic are unchanged. The older GUI would reject a G-prefixed ID; the new GUI can
look up a report whose filename includes G. Neither GUI preselects a default
counterbalance group in the inspected source.

All eight protocols retain the same configuration structure. For a corresponding
run, the XML leaf differences are the template's ID-containing name and the eight
frequency fields; the sham-related fields do not change. Git does not retain the
GUI selections or generation timestamp, and an exact source reproduction does
not identify which executable was historically run.

## 2. Offline reproduction isolates the selection difference

Only three reviewed functions (`extract_frequency_values`,
`replace_protocol_info`, `create_protocol`) and their constants were extracted
with Python AST from the historical source revisions. The GUI/module top level
and executables were not run. The functions read repository reports/template and
wrote **only disposable workspace copies**. All six counterbalances were tried
for visit 2. Source/protocol/report hashes were checked before and after: **161
protected files remained unchanged**.

| Visit-2 counterbalance input | Generator branch label | Unprefixed report output | G-prefixed report output |
|---|---|---:|---:|
| A or F | beta | 20 Hz (parser fallback) | 30 Hz |
| B or C | theta | 4.5 Hz | 4 Hz |
| D or E | sham | 0 Hz | 0 Hz |

Using the October 19 source, **all four unprefixed files reproduce byte for byte
with B or C**. Using the October 20 source, **all four G-prefixed files reproduce
byte for byte with D or E**. The October 20 source still reproduces the unprefixed
files with B/C. No source calculation turns the G report's 4-Hz theta into 0 Hz
while holding the theta selection fixed.

This establishes source-compatible explanations, **not participants' true
assignments**. A changed counterbalance input is the most direct explanation under
the inspected generator; manual changes or a different executable/workflow are
not ruled out. The G files' first appearance after the session is also compatible
with a later demonstration/regeneration. Do not assume they were used on October
19. The four October 19 run-specific `.info` files list 4.5-Hz settings, supporting
the unprefixed set as consistent with the recorded settings, but do not establish
completed delivery or the intended condition.

**To close the provenance issue:** the assignment custodian should verify the
original visit-2 A–F key and the canonical ID mapping; the protocol administrator
should identify the inputs and purpose of each generation, the deployed executable,
and the exact file imported on October 19. Preserve both sets and document which
is historical versus later/test material. Do not select the latest file or assign
the participant's condition from this table.

## 3. The 0-Hz files do not reproduce the earlier explicit sham encoding

An earlier matched pair, `TACS3-Pilot_Run-1_750-Theta.neprot` and
`TACS3-Pilot_Run-1_750-Theta-Sham.neprot`, differs only in names and two fields:

| Field | Earlier active export | Earlier sham-named export | Generated G11450 visit-2 file |
|---|---:|---:|---:|
| `stepType` | 0 | 2 | 0 |
| `rampSham` | 0 | 30 | 0 |
| `stimulationSham` | Single | Single | Single |
| Configured stimulation-channel frequency | 6 Hz | 6 Hz | 0 Hz |

The generated files also retain `atacsValue` 1500/500/500/500 on the four configured
stimulation channels, with phases 0/180/180/180 degrees; all `atdcsValue` and
`atrnsValue` entries are zero. This comparison reports recorded parameters, not
recommended stimulation settings or an endorsement of the older pilot protocol.

Consequences of the comparison:

* The text `stimulationSham=Single` alone cannot identify sham: it appears in both
  members of the matched pair and the active template.
* The current generator implements its **branch labeled sham** by substituting
  frequency 0 into the active template. It does not change `stepType`, `rampSham`
  or amplitude values to the values in the earlier explicit sham export.
* Filenames cannot validate configuration: another pilot file named
  `Run-3_1500-Theta-Sham` has the same active-style step/ramp fields as its active
  counterpart. Treat these files as evidence for comparison, not validation gold
  standards.

Neuroelectrics' [sham configuration guidance](https://supportne.freshdesk.com/support/solutions/articles/35000291577-sham-protocol-blind)
describes explicitly enabling sham mode and configuring its envelope. Its
[zero-current OCS example](https://supportne.freshdesk.com/support/solutions/articles/35000319273-online-change-of-stimulation-ocs-for-tacs-using-matnic-pro)
sets amplitude as well as frequency to zero; it does not establish that zero
frequency with nonzero amplitude is zero current. These sources support the need
for an explicit sham/output check, but do not specify this XML edge case's runtime
behavior in the recorded NIC version.

**Conclusion:** the generated 0-Hz files are not demonstrated NIC sham protocols,
and their static sham-related fields differ from the earlier explicit sham export.
It is not established whether NIC rejects them, produces zero output, applies a
constant component, or behaves another way. In particular, neither DC delivery nor
no-current delivery can be inferred from these files. The archived `.info` records
for 10029 visit 2 say EEG-only; they do not test importing these 0-Hz files.

## 4. The remaining NIC verification is specific

No NIC import or device test was performed in this investigation. Ask the
authorized administrator, preserving the study's blinding, to:

1. Inspect a **copy** of the exact 0-Hz file in the study's installed NIC version
   (the archived device records name 2.1.4.4, firmware 4021). Retain import warnings,
   the actual interpreted step type/sham state, and a re-export without overwriting
   the original. A launch-screen picture alone may be intentionally blinded.
2. Compare it with a separately exported explicit-sham configuration representing
   the **approved study procedure**, including its full envelope. This comparison
   does not authorize substituting the older pilot's parameters.
3. Obtain manufacturer clarification of the exact XML combination. If physical
   output verification is needed, have qualified staff use the lab's approved
   nonparticipant test-load procedure. Do not test the edge case on a participant.

Suggested question for Neuroelectrics (draft only; not sent):

> In NIC 2.1.4.4 / firmware 4021, how is an imported protocol interpreted when
> stepType=0, rampSham=0, stimulationSham=Single, tACS frequency is 0 Hz,
> tACS amplitudes are nonzero, and tDCS/tRNS values are zero? Does it engage
> native sham mode, reject the configuration, or produce another output?
> Which export/status fields and approved test-load procedure can verify this?

Until this is resolved, do not certify the 0-Hz convention as the approved sham
implementation. Any operational correction needs the PI's existing study procedure;
this investigation makes no acquisition changes or retrospective treatment claim.

## 5. Which document to share

* [README.md](README.md): share with analysts for setup, scoring definitions and
  reproduction. It does not contain the generated participant results because
  those outputs are intentionally ignored in Git.
* [TEAM_PRESESSION_CHECKS.md](TEAM_PRESESSION_CHECKS.md): send directly to the PI,
  coordinator and authorized stimulation/protocol staff for the action checklist.
* This note: attach to that operational discussion for the new timeline,
  counterbalance reproduction and sham-encoding evidence. Do not circulate
  parameter/assignment-revealing details to staff who should remain blinded.
