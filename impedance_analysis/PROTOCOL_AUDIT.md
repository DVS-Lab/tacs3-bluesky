# StarStim-8 protocol audit and troubleshooting handoff

**The frequency-estimation repair does not resolve the impedance issue. The stored configuration could contribute to the pattern, but the available files do not identify the cause of a repeated F3-labelled `150000`.** This audit extends the existing impedance package; no experimental protocol, acquisition script, stimulation setting, or raw data was changed.

## Confirmed configuration observations

`stimulation/protocols/TACS3_Impedance-Check.neprot` assigns indices 1–8 to F3, Fp1, FCz, FT7, F4, P4, P3, EOG1. All eight have `electrodeType=2`. The first four have nonzero tACS settings (750, 250, 250, 250 µA; 6 Hz; phases 0°, 180°, 180°, 180°); indices 5–8 have zero programmed amplitudes. The step has `stepType=0`, a 300-second configured duration and 30-second up/down ramps. Its label does not make it an impedance-only operation. Reachable Git history has one extant version of this file, introduced in `5acde38` on July 22, 2026; the later operator-reported edits are not recoverable from that path's Git history.

The current `PROTOCOL_TEMPLATE.neprot` differs: only indices 1–4 have type 2; indices 5–8 have type 1, with EXT at index 8. Its duration is 480 seconds with 60-second ramps. The EEG recording template provides another role configuration. The audit preserves all reachable versions of these three generic templates privately; the experimental template has seven extant versions and the EEG example four. These are Git versions, not proof of what NIC imported.

Nine archived NIC `.info` records bear the impedance-check step label. Four describe eight stimulation channels and 300 seconds; five describe seven stimulation channels and 180 seconds, with channel 8 unused. Zero-amplitude channels can still be recorded as **Stimulation**. Those files corroborate the role interpretation of type 2 in this configuration, but do not document how NIC selects diagnostic pairs. All nine record zero stimulation samples and a zero first-STIM timestamp. They therefore provide no evidence that the programmed stimulation step was delivered; they also do not exclude a diagnostic current during an impedance check.

The manufacturer's [impedance description](https://supportne.freshdesk.com/support/solutions/articles/35000308661-how-is-impedance-measured-) specifies a separate precheck current: AC 300 µA at 30 Hz, or DC 300 µA. Thus changing the programmed tACS amplitude/phase need not alter that precheck. Confirm actual mode and installed-version applicability with support. The document does not decode `150000`.

## Historical evidence and its limits

The rerun preserves the existing 210-export inventory: 92 currently present standalone checks, eight history-only standalone checks, and 110 continuous exports; 130,552 channel slots. All original export values/categories and channel-summary denominators are unchanged. There is no documented operator configuration log, so connected/active denominators remain zero rather than being inferred.

Among the 92 current standalone checks, exact-150000 counts by slot 1–8 are **18, 5, 5, 1, 16, 13, 13, 16**. The positive-reading denominators are 92 for slots 1–7 and 90 for slot 8, which also has two zeros. In the eight history-only checks, slot 1 has six exact values and the others none; do not pool those silently. Continuous exports contain no exact 150000, but many zeros, especially outside slots 1–4. That different mode/pattern is not evidence that a standalone-check problem was repaired.

Across inventoried protocol configurations, F3 appears at index 1, 2 or 6; in the available `.info` configurations with F3, it appears at index 1. Configuration occurrences are not physical wiring observations or independent participant counts. Unlinked standalone checks retain unknown location/role. The new report distinguishes export column/device index, programmed location, configured role and zero amplitude, documented physical site/lead, and standalone versus continuous context. A continuous export bearing an impedance-check step label remains a continuous export; it is not relabelled as a standalone ImpVal check.

This rules out the descriptive claims that every special value is confined to slot 1 or that slot 1 always records 150000. It **does not rule out** intermittent hardware, cable/connector, electrode-contact, CMS/DRL, configuration, or NIC/status-encoding explanations. Nor does it demonstrate that this issue caused the unusual EEG channel similarity in the separate frequency audit. Unused but stimulation-configured inputs could contribute if NIC measures them; this does not by itself explain a truly connected F3 path. The [CMS/DRL guidance](https://supportne.freshdesk.com/support/solutions/articles/35000288498-6-cms-drl-impedance-information-eeg-and-stimulation-) identifies that shared contact as part of stimulation-channel impedance checking.

## Most informative next physical test

Use the **manufacturer-approved StarStim-8 testboard impedance procedure**, with all required connections and CMS/DRL documented, before participant-based troubleshooting. Record the full eight-channel result and index/lead/endpoint map. Then, only as the approved procedure permits, substitute one verified compatible cable/lead or load path at a time, keeping the configuration and other connections fixed. Do not launch the stored 300-second stimulation step as a diagnostic test. This analysis has not run a physical test or generated a replacement protocol.

A failure on the testboard makes scalp contact unnecessary to reproduce it. A failure that follows an independently identified lead supports the lead/connector path; one that stays at a device index after verified cable/load substitutions supports the device port or channel-specific software/configuration. A passing board test followed by failure with the normal electrode assembly leaves cable, contact and shared-reference explanations open. Moving a lead and electrode/contact together confounds that distinction. The HTML report contains the full controlled-observation decision table.

The official [testboard page](https://www.neuroelectrics.com/product-page-1/testboard) describes approximately 4 kΩ simulated impedance and an 8-channel model. Support must confirm this board's applicable tolerance and permitted connections/swaps; approximate values alone do not identify historical testboard use.

## Exact information still needed

**From the operator:** For the relevant before/after checks, supply the timestamp/raw ImpVal or IMP file, a full NIC display screenshot, and a map of **device index → NIC label → identifiable cable lead → physical scalp site/testboard endpoint**. State whether only amplitude/phase entries changed or any location assignment, lead, connector, electrode, contact or CMS/DRL connection changed. Identify the actual AC/DC Check Impedance action versus starting a protocol, the exact protocol exported from NIC, and the current NIC/firmware versions. Device/serial details and free-text notes stay private. These observations establish what “stayed on F3” means; amplitude edits alone do not answer it.

**From Neuroelectrics:** Confirm exact-150000 and zero semantics/units in ImpVal versus IMP for this installed build; channel/pair and return/reference selection with type-2 zero-amplitude channels; whether unloaded/unused channels are included; possible stale/status values and relevant software issues; why exported/archived configurations differ; and the supported testboard procedure, expected range and permitted component substitutions. Do not transfer Enobio firmware rules or StarStim-20/32 artifact instructions to StarStim-8.

The minimum useful new evidence is one documented before/after bench comparison, not more unlabelled impedance exports. No physical cause has yet been ruled out decisively, and the software audit cannot certify the equipment as repaired.

## Reproduce and inspect

Run `python -m impedance_analysis` in the existing environment. The updated `share/report.html` contains this audit, generic-template comparison, historical patterns and the decision table. `share/protocol_audit.json` and `share/configuration_channel_summary.csv` provide identifier-minimized evidence. The detailed XML/history/NIC inventory and original paths remain in ignored `private/` outputs. Keep the entire share directory together for its links and figures; do not send the private directory with it.

Tests: `TACS3_REAL_ROOT="$PWD" python -m pytest impedance_analysis/tests behavioral_analysis/tests -q -W error::RuntimeWarning`. Coverage includes zero amplitude versus configured role, recorded-zero versus diagnostic-current uncertainty, versioned read-only history, location/lead separation, privacy filtering, and the full local source-integrity check. Generated participant-level reports and private notes are not committed.

Validation completed on the local corpus: **111 tests passed**, with third-party Matplotlib/Pyparsing deprecation warnings only. The rerun verified unchanged source hashes, all 210 export identities/hashes, all 130,552 original reading values/categories, and all original channel-summary values/denominators. HTML generation and local asset/link checks passed; browser rendering was unavailable under the local-file URL policy.
