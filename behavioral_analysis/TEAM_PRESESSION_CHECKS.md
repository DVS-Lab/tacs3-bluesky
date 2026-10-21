# TACS-3: frequency provenance and delivery checks before the next session

Reviewed 2026-10-20 against analysis commit `144e48a` and the available repository
records. This is a coordination note for the PI and authorized stimulation staff.
It contains parameter information that could reveal assignment; use the study's
existing access/blinding rules when sharing it. It does not assign conditions,
change the approved protocol, or establish that stimulation failed.

**Resolve three things before the next stimulation session: the participant/visit
assignment, the exact authorized protocol loaded in NIC, and how its execution
will be documented.** Historical frequency provenance also needs PI review before
it is used for another individualized-frequency decision. Old delivery gaps can
remain explicitly unresolved while staff establish a verifiable prospective
workflow; do not invent retrospective certainty or silently repeat a session.

Follow-up: [PROTOCOL_VARIANT_INVESTIGATION.md](PROTOCOL_VARIANT_INVESTIGATION.md)
shows that the G/unprefixed protocol variants exactly reproduce different
visit-2 condition-selection branches; changing the ID prefix alone does not
explain 4.5 Hz versus 0 Hz. The generated 0-Hz files also retain the active-style
step/ramp fields, rather than those in an earlier matched explicit-sham export.
Their physical interpretation in NIC remains unverified. Consult that note before
certifying a 0-Hz file as the approved sham implementation.

## What the frequency conflicts actually are

| Case | Observed evidence | What must be checked |
|---|---|---|
| **11450, visit 2, October 19** | `11450-2_pre-stim_theta-beta.txt` pairs **SST EEG with Bandit events**, retains **0/116 feedback and 0/116 decision epochs**, reports theta **4.50 Hz via IAF−5**, and beta unavailable. `G11450-2_pre-stim_theta-beta.txt` names Bandit EEG and Bandit events, retains **113/116 and 114/116** epochs, and reports theta **4.00 Hz** and beta **30.00 Hz**. Its theta value is a band-edge negative contrast (−3.310 dB); its beta contrast is positive (+3.220 dB), not suppression. | Confirm `G11450` and `11450` are the same enrolled participant using the private roster. Identify the intended EEG/event pair, exact estimator report, and report used when protocols were generated. A better file pairing does not make the prefixed estimates physiologically reliable. |
| **11450, visit 2: protocol conflict** | The four unprefixed `11450_visit2_*` protocols contain **4.50 Hz**. The four `G11450_visit2_*` protocols contain **0 Hz**. The four run-specific device `.info` records list **4.50 Hz settings**. | Reconcile the original private counterbalance/visit record, generator inputs, deployed executable/version, exact imported protocol and operator log. Frequency disagreement alone cannot tell us whether the wrong report, a stale protocol, a different generator input, or a different intended assignment explains the files. Do not choose a protocol by recency or prefix. |
| **10029, visit 1, October 13** | `10029-1_pre-stim_theta-beta.txt` also pairs **SST EEG with Bandit events**. It retains **0/114 feedback and 0/113 decision epochs**, reports theta **4.29 Hz via IAF−5**, and beta unavailable. Generated protocols and run-specific device settings contain **20 Hz**. | Verify the source pairing and whether 20 Hz was explicitly authorized as a fallback. The current generator substitutes 20 Hz when no numeric beta is parsed; that is a plausible explanation, not proof of the historical executable's action or of intended assignment. |
| **Boundary estimates** | For 10029 visit 2, theta **8 Hz** and beta **13 Hz** are search-band endpoints despite 106/116 and 109/116 retained epochs. For 11450 visit 1, beta **30 Hz** is the upper endpoint with 116/118 retained decision epochs. | Do not equate adequate epoch counts or a numerical extremum with a reliable individualized rhythm. Ask the PI to document how the existing study policy handles failed/uncertain estimates before the next frequency decision. |

The zero-retention reports attribute the excluded epochs to **bounds**, not large
artifact counts. This supports investigating EEG/event mismatch or nonoverlapping
recordings first; it does not establish the full root cause without checking their
timestamps and original acquisition records. The IAF−5 number is a different
estimator and does not rescue missing event-related theta/beta evidence.

The current Python generator reads the exact report filename corresponding to the
entered subject string and visit. It accepts the numeric stimulation-frequency
lines without consulting their QC, and defaults to theta 6 Hz/beta 20 Hz when the
corresponding numeric match is absent. It chooses a frequency using the entered
A–F counterbalance and visit. These observations explain possible failure paths;
they are **not** a recommendation to use a fallback, nor proof of what a compiled
executable did during a past session.

The separate, unmerged [rhythm-validation PR #1](https://github.com/DVS-Lab/tacs3-bluesky/pull/1)
reports no primary estimates passing its provisional reliability framework. That
pilot finding is an additional limitation, not a new validation test performed on
these experimental visits. Correcting a file pairing will require a separately
authorized reanalysis; preserve all historical reports and protocols.

## What the delivery records do and do not establish

The available records form separate layers:

1. **Intended assignment:** the original private counterbalance/visit key. It has
   not been supplied to this behavioral analysis.
2. **Generated/recorded settings:** a `.neprot` file and the parameters listed in
   a matching device `.info` file. These show files/settings, not completed dose.
3. **Execution evidence:** time-stamped device/session records, logged output or
   completion/termination information, and the operator's contemporaneous record.
   These need reconciliation before marking delivery verified.

Across the two experimental-candidate IDs there are **17 matched run-specific
`.info` files for 16 selected behavioral runs**: 13 list zero stimulation samples
and `firstSTIMtimestamp=0`; four say **EEG only mode**. These are file counts, not
17 distinct treatments or 17 demonstrated delivery failures.

* **10029 visit 2:** four generated protocols contain 0 Hz. The four available
  run-specific device records say EEG only: two SST run-2 attempts and Bandit runs
  1 and 2. No matching SST run-1 `.info` file was found in the checked folder.
  Confirm the intended condition, whether EEG-only operation was deliberate, and
  whether the missing run-1 record exists on the acquisition computer. A 0-Hz
  file plus EEG-only records does not establish an approved sham implementation.
* **11450 visits 1/2 and 10029 visit 1:** device settings list 30 Hz, 4.5 Hz and
  20 Hz, respectively, but stimulation sample counts and first-stimulation
  timestamps are zero. Determine whether this reflects recording/export settings,
  a missing execution log, or an execution problem. The current repository cannot
  distinguish these explanations.
* **Restarts need a device-side explanation too.** October 20 SST run 2 has a
  10-trial behavioral attempt and a later 91-trial attempt, plus two EEG-only device
  files. October 13 SST run 2 has two device recordings: 128,854 and 53,631 EEG
  samples at 500 Hz (about 258 and 107 seconds of nominal EEG coverage). These are
  EEG coverage estimates, **not stimulation-dose estimates**. Record what stopped
  and restarted on the task and device separately, and which device intervals map
  to the retained behavior.

No `.stim` files were found in `stimulation/stimulation-data/`. This does not mean
a `.stim` file must exist or that no stimulation occurred. Confirm the installed
NIC version's recording/export configuration and where execution evidence is
stored. Neuroelectrics describes `.easy` as a native raw recording format; an EEG
recording or stimulation artifact alone is not a calibrated verification of dose.
See the manufacturer's [NIC data-format guidance](https://supportne.freshdesk.com/support/solutions/articles/35000294937-nic-data-formats).

### An additional sham-implementation question

In the inspected 0-Hz protocols, `atacsValue` remains 1500/500/500/500 on the four
configured stimulation channels, `rampSham` is 0, and `stimulationSham` is `Single`.
The current generator changes frequency and names; it does not separately toggle
those sham/amplitude fields. This does **not** establish the physical output at
0 Hz, DC delivery, or whether NIC rejects/ignores/converts that configuration.

Before using that file, the authorized protocol administrator should verify the
exact imported settings in the installed NIC version against the approved study
sham procedure. If the interpretation remains unclear, obtain manufacturer
clarification and, where covered by the lab's SOP, use a qualified nonparticipant
bench verification. Do not improvise parameter changes or use a participant to
resolve this uncertainty. The manufacturer's [sham guidance](https://supportne.freshdesk.com/support/solutions/articles/35000320308-sham-and-double-blind-experiments)
describes sham as an explicitly configured current-envelope procedure; it does not
validate this repository's 0-Hz convention. A blinded launch-window display alone
may not reveal the true sham envelope.

## Exact checklist for the next session

| Owner | Check | Evidence to retain / completion criterion |
|---|---|---|
| **Coordinator / assignment custodian** | Verify canonical participant ID, visit number, original A–F assignment and authorized protocol code. Resolve G/unprefixed variants privately. | Dated, attributable private key entry and explicit mapping to that visit. Keep condition labels from personnel meant to remain blinded. |
| **PI / frequency analyst** | Verify the designated EEG and behavioral files belong to the same participant, visit, task and overlapping recording interval. Review retained epochs, estimator method, boundary/sign warnings and reliability status. | Exact source paths/hashes and dated decision under the existing approved frequency-selection/fallback policy. Unavailable or failed estimates remain labeled that way. Do not pick 4 versus 4.5 Hz from these reports automatically. |
| **Protocol administrator** | Establish one authorized file for each planned task/run. Compare the report used, generator inputs/version, generated bytes and the file imported in NIC. Review frequency, montage, per-channel amplitude/phase, ramps, duration and sham configuration against the approved protocol. | Exact protocol path/hash, version, and recorded review. For a 0-Hz/sham file, documented interpretation in the installed NIC version and confirmation it implements the study's approved sham procedure. |
| **Stimulation operator / administrator** | Confirm where NIC records execution, how start/end/completion or interruption is captured, and what zero STIM counters mean in this installation. Follow the existing impedance/device SOP. | A named execution record/export location and a demonstrated way, under the lab's SOP, to retain the required evidence. Existing `.info` zeros must not be relabeled as successful delivery. Preserve the required blinding. |
| **Operator, each run** | Match the loaded blinded protocol code and task/run; record device and task starts/ends, completion versus stop/error, and any restart separately. Do not assume restarting behavior restarts or extends stimulation appropriately. | Contemporaneous operator record linked to the selected protocol and device files; interrupted exposure gets an explicit PI/SOP decision before resumption or repetition. |
| **Analyst / coordinator, after the visit** | Rerun behavioral QC; reconcile planned runs with behavioral and device files, especially short attempts or missing exports. | Reviewed manifest/exclusion log and a private resolution log. Keep `delivery_verified=False` unless the relevant evidence has actually been reviewed. |

**If staff cannot establish the next visit's assignment, authorized source/protocol,
or intended active/sham execution, refer the unresolved item to the PI before
starting that stimulation session.** This is a request to resolve observed
discrepancies, not a new stimulation protocol or a decision to exclude/repeat all
earlier sessions. The PI determines any operational change under the study's
approved procedures; old analysis can continue with explicit uncertainty labels.

## Record resolutions once, with evidence

Use a private local log containing participant/visit/task/run, issue, intended
assignment, exact report and protocol path/hash, generator/NIC versions, documented
settings, device execution evidence, start/end/termination, resolved/unresolved
status, reviewer/date, and the basis for any fallback or restart decision. Distinguish
documented settings from independently reviewed execution evidence.

The existing local condition-key template supports intended assignment/frequency
and documented delivered frequency separately. `delivery_verified=True` imports
the team's assertion; the pipeline cannot certify hardware from that Boolean.
Keep keys and logs in `behavioral_analysis/local/` or the approved private study
location. Do not overwrite historical reports or publish the key in Git.

## Source pointers

* Frequency cases: `stimulation/calculated-theta-beta/10029-1_pre-stim_theta-beta.txt`,
  `10029-2_pre-stim_theta-beta.txt`, `11450-1_pre-stim_theta-beta.txt`,
  `11450-2_pre-stim_theta-beta.txt`, `G11450-2_pre-stim_theta-beta.txt`.
* Protocol variants: `stimulation/protocols/generated/{11450,G11450}_visit2_*`
  and `10029_visit2_*`; template `stimulation/protocols/PROTOCOL_TEMPLATE.neprot`.
* Generator: `code/protocol_generator.py`, especially `extract_frequency_values`,
  `replace_protocol_info` and `create_protocol`. Read only; never import its GUI
  merely to inspect these functions.
* Device examples: `20261019180837_11450-2_SST-1.info`,
  `20261020162935_10029-2_SST-2.info`, and both October 13 SST run-2 records,
  under `stimulation/stimulation-data/`.
* Full machine-readable evidence: ignored `outputs/latest/frequency_estimates.csv`,
  `stimulation_records.csv`, `session_stimulation_metadata.csv`, and `manifest.csv`
  under this analysis directory; these include original source paths/hashes.

This note documents observations and checks. It does not modify acquisition code,
protocol files, historical frequency estimates, assignment records or the rhythm PR.
