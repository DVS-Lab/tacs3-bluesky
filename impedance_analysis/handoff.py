"""Generic troubleshooting interpretation shared by the existing HTML report."""
from html import escape
import pandas as pd

DECISIONS = [
    ('Changing only programmed amplitude/phase leaves the error at the same label',
     'Does not localize hardware: the precheck uses a separate diagnostic current; label, index and physical path may all be unchanged.',
     'Record exact channel index, display label, connected lead and scalp/testboard endpoint; identify AC/DC precheck versus continuous log.'),
    ('Repeatable failure on the supported testboard with a verified complete connection',
     'Scalp contact is not required to reproduce the failure; device, connector, cable, testboard, configuration or NIC behavior remain possible.',
     'Use the manufacturer-approved diagnostic check only; compare a known-good compatible testboard cable/load while keeping other factors fixed.'),
    ('Failure remains at one device index after independently verified cable and load substitutions',
     'Supports a device-port or channel-specific software/configuration explanation; does not distinguish those by itself.',
     'Send the raw check exports, index mapping and NIC/firmware versions to Neuroelectrics for device-versus-software isolation.'),
    ('Failure follows one identifiable lead when only that lead/path is exchanged',
     'Supports that lead/connector path over a fixed device index. Moving an electrode/contact with it would confound this conclusion.',
     'Document which endpoint changed and which stayed fixed; repeat with a verified replacement path under the approved bench procedure.'),
    ('Testboard passes; failure appears only with the normal electrode assembly',
     'Does not prove hardware perfect. Normal cable, electrode contact, CMS/DRL or setup-specific effects remain.',
     'Check existing normal-cable/contact and CMS/DRL records; use only the manufacturer-approved follow-up, with each changed component logged.'),
    ('Several channels change together after a CMS/DRL or connector intervention',
     'A shared connection/reference path is plausible; simultaneous handling prevents channel-specific attribution.',
     'Record shared-path changes separately; do not infer that one scalp electrode or the programmed waveform caused the original result.'),
    ('Only disconnected or zero-amplitude, stimulation-configured slots show the special value',
     'Could reflect channel inclusion/status behavior rather than a failed connected electrode. Zero amplitude alone proves neither disconnection nor exclusion.',
     'Supply actual connected-channel list; ask Neuroelectrics how electrodeType, zero amplitudes and return-channel pairing select diagnostic channels.'),
]


def section(audit, table):
    body=['<h2>Protocol audit and next discriminating test</h2>',
        '<p>The programmed file is not the NIC measurement procedure. Its existence does not establish import or delivery. Generic-template settings below are configuration evidence; participant protocol settings and raw paths remain private.</p>']
    for p in audit.get('current_generic_protocols',[]):
        body.append('<h3>'+escape(p['category'])+'</h3>')
        body.append(table(pd.DataFrame(p['steps'])))
        body.append(table(pd.DataFrame(p['channels'])))
    body += ['<h3>Archived records bearing the impedance-check step label</h3>',table(pd.DataFrame(audit.get('impedance_named_info_groups',[]))),
        '<p>A configured stimulation-channel count can include zero-amplitude channels. Zero recorded stimulation samples and a zero first-STIM timestamp provide no evidence of a delivered programmed step; they do not exclude the separate diagnostic current. The different archived settings cannot be replaced by the current XML retrospectively.</p>',
        '<h3>Programmed F3 location versus device index</h3>',table(pd.DataFrame(audit.get('f3_programmed_index_counts',[]))),
        '<p>These are configuration occurrences, not independent subjects, checks or physical wiring observations. A channel index in an export is retained separately from the programmed label, configured role, operator-documented physical site and lead. Unlinked standalone checks are not assigned the nearest montage.</p>',
        '<h3>Most informative next physical test</h3><p>Request a manufacturer-approved StarStim-8 testboard impedance check with known connections, before any participant-based troubleshooting. Record all eight indices and CMS/DRL, then change only a verified compatible cable/lead or load path at a time as the approved procedure permits. Do not use the programmed 300-second step as a diagnostic test, run stimulation, or create a replacement participant protocol. This audit does not perform or certify a physical test.</p>',
        '<p>Interpretation of controlled observations:</p>',table(pd.DataFrame(DECISIONS,columns=['Observation','What it supports / does not establish','Next evidence'])),
        '<h3>Smallest operator record</h3><p>For each before/after check: timestamp and raw export; NIC/firmware/device identification privately; whether the AC or DC Check Impedance button was used or a protocol was started; exact loaded/exported protocol; device index → NIC label → identifiable physical lead → scalp site/testboard endpoint; connected/unused channels and CMS/DRL; and exactly one change made. A screenshot of the full channel display plus this map resolves what “stayed on F3” means. Free-text notes and lead identities stay in the private configuration log.</p>',
        '<p><a href="https://supportne.freshdesk.com/support/solutions/articles/35000308661-how-is-impedance-measured-">Neuroelectrics</a> describes a separate precheck current: AC 300 µA at 30 Hz or DC 300 µA. Therefore changing programmed tACS amplitude/phase need not change a precheck. Its <a href="https://supportne.freshdesk.com/support/solutions/articles/35000288498-6-cms-drl-impedance-information-eeg-and-stimulation-">CMS/DRL guidance</a> also identifies that shared contact as part of stimulation-channel impedance checking. Applicability and channel inclusion for this installed NIC/firmware remain manufacturer questions.</p>',
        '<p>The official <a href="https://www.neuroelectrics.com/product-page-1/testboard">testboard description</a> gives an approximate 4 kΩ model, not a calibrated tolerance for this individual board. Ask support to confirm the exact board/cable procedure, permitted swaps and expected range. Do not transfer Enobio or StarStim-20/32 firmware/artifact instructions to StarStim-8.</p>']
    return '\n'.join(body)
