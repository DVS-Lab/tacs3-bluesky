# TACS-3 impedance diagnostics

Read-only analysis of every working-tree `*_ImpVal.txt` and `*_IMP.txt` export,
including pilots, tests, empty and malformed files. Exports missing from the
working tree are recovered **in memory** from ancestors of the analyzed Git HEAD,
using each missing path's last extant blob. No historical raw file is restored.
Current and history-only records have separate summary denominators. Historical
versions of paths still present are not repeated as independent measurements.

This package never controls NIC or changes protocols, acquisition code or data.
It uses the existing behavioral analysis's documented G/R identity resolver and
Python requirements. No participant result, configuration log or assignment key
belongs in Git. See [scientific status](../behavioral_analysis/SCIENTIFIC_STATUS.md)
for the combined handoff when available.

## Run

From the repository root, using Python 3.9+ and the existing environment:

```bash
python -m pip install -r behavioral_analysis/requirements.txt
python -m impedance_analysis
python -m pytest impedance_analysis/tests behavioral_analysis/tests -q
```

For read-only integration tests against the complete local clone:

```bash
TACS3_REAL_ROOT="$PWD" python -m pytest impedance_analysis/tests behavioral_analysis/tests -q -W error::RuntimeWarning
```

Windows PowerShell: set `$env:TACS3_REAL_ROOT=(Get-Location).Path` before pytest.
Full Git history is required to reproduce the history appendix; shallow clones
can only recover reachable commits. A non-Git dataset reports history unavailable.
`--root PATH` selects the source repository; `--output PATH` selects a dedicated
external output directory or `impedance_analysis/outputs/`. `--threshold 20000`
sets a descriptive raw-value threshold. Private configuration/alias inputs must
be outside the chosen output tree so a rebuild cannot overwrite them. `--no-plots` is for smoke tests.

Default output: `impedance_analysis/outputs/latest/` (ignored by Git):

- **`share/report.html`**: diagnostic observations, alternatives, plots and linked
  CSVs. Send the **whole share directory** (or zip), so plots and links work.
- `share/exports.csv`: every export, including empty/problematic files, opaque
  export ID, timestamp, availability, input hash and issue/status fields.
- `share/standalone_checks.csv`: all standalone exports in chronological wide
  format, eight recorded values per check. `priority_checks.csv` is the date subset.
- `share/readings.csv`: every row × eight physical channel slots; continuous
  Unix-ms and UTC timestamps are separate from unverified filename wall time.
- `share/channel_summary.csv`: mode × availability × channel × denominator scope.
- `share/suspicious_sequences.csv`: temporal transitions; no automatic hardware
  recovery claim. `priority_checks.csv` lists all Oct 19/20/22 standalone values.
- `share/pattern_hypotheses.csv`, `daily_summary.csv`, `parse_errors.csv`,
  `summary.json`: exploratory ~4 kΩ screens, coverage and errors.
- **`private/`**: identities, original source paths/hashes, candidate NIC/protocol
  links, full metadata inventory, parsing evidence, configuration-log template and
  software/input provenance. Keep this directory local.

The share directory omits recruitment IDs, free-text operator evidence, device
network IDs, source paths, protocol names and frequencies. It retains dates and
opaque export IDs for diagnostic use; it is identifier-minimized, not guaranteed
anonymous. No private condition key is read. Generated results stay out of Git.

## Private operator configuration log

Copy `private/configuration_log_template.csv` to an ignored location such as
`impedance_analysis/local/configuration_log.csv`. Delete rows for which there is
no documented configuration; fill only supported records. Pass it explicitly:

```bash
python -m impedance_analysis --configuration-log impedance_analysis/local/configuration_log.csv
```

Required columns:

| Column | Meaning |
|---|---|
| `source_file`, `sha256` | Exact repository-relative export and hash from inventory; stale/unknown/duplicate bindings fail |
| `setup` | `flat_cable_testboard`, `normal_electrode_cable`, `headcap`, `other`, or `unknown` |
| `connected_channels` | Physical channels `1;2;3;4`; `none` means explicitly none; blank/`unknown` means unrecorded |
| `active_channels` | Same syntax; channels actually active for that measurement; must be a subset of known connected channels |
| `evidence` | Contemporaneous log, operator confirmation and handling/change times; required, stays private |

Optional `info_file`/`info_sha256` and `protocol_file`/`protocol_sha256` establish
operator-documented linkage to an inventoried record. Optional `channel_locations`
is a JSON object such as `{"1":"F3"}` based on wiring/montage evidence. Enter one
row per export; do not interpolate configuration through undocumented intervals.
Use `other` plus evidence for an incompletely represented setup. A normal cable
and headcap can coexist: describe the full assembly in evidence. `--aliases PATH`
uses the [existing private legacy alias schema](../behavioral_analysis/IDENTITY_ALIASES.md).
Prefixes and leading zeros are preserved; equal numeric suffixes never imply a join.

A unique continuous-log/run `.info` association requires matching preserved ID,
visit, step name and filename time within two seconds. This is a recording
association, **not proof of wiring**. Standalone exports keep all same-ID/visit/day
`.info` candidates within one hour, with signed time differences; nearest is never
silently selected. Protocol files with a matching associated step name remain
candidates, not proof of import/execution. All `.info` and `.neprot` files are
inventoried with hashes and parsed configurations; neither their existence nor
channel roles establish physical connection. In particular, F3 is not assumed to
be physical channel 1 for all dates or templates.

## Interpretation and denominators

- **Exact 150000** is separate from all other high values. Its device-specific
  meaning is unconfirmed. Do not call it literal 150 kΩ, a ceiling or an open circuit.
- Ordinary positive values >20000 are flagged separately; if export units are Ω,
  that corresponds to >20 kΩ. Confirm units and AC/DC/continuous measurement modes
  with Neuroelectrics. This screen is not a replacement for the lab's approved SOP.
- Zero is `zero_uninterpreted`; negative/nonfinite/missing values are invalid.
  Wrong-width rows retain raw evidence and eight channel slots but contribute no
  eligible readings. Empty files remain in inventory. No interpolation/imputation.
- Denominators include structurally valid positive readings (including exact
  150000). Mode and working-tree/history-only availability are separate. All-recorded,
  documented-connected and documented-active scopes are distinct. Unknown physical
  connectivity is never inferred from a configured NIC role or numeric pattern.
- With no operator log, connected/active denominators are **zero**, rates undefined.
  High values on explicitly disconnected channels do not count in those scopes.
  All-recorded summaries describe exports, not hardware-fault or participant risks.
- Repeated exports remain separate; identical-content counts are reported, not
  silently deduplicated. Continuous samples are correlated, not independent checks.
- Sequences join adjacent standalone checks only within preserved ID/visit/day,
  ≤2 h apart, with complete eight-value rows. A transition to ≤threshold does not
  prove an unchanged setup or successful hardware recovery.
- At least two readings in 3500–4500 are labeled an exploratory **testboard-like
  hypothesis**. Actual configuration comes only from operator evidence. Ordinary
  electrode measurements may also match. No setup is auto-filled from values.

Source/input and acquisition-code hashes are checked before/after execution;
software hashes and dependency versions are recorded. The recursive scan excludes
only `.git`, outputs/local, virtual environments and caches, and does not follow
symlinks. Malformed encodings and timestamps are visible in inventory. CSV and
plots preserve standalone vs continuous measurement modes and clock bases.

## Manufacturer evidence and questions

Neuroelectrics describes prelaunch AC/DC checks and monitored impedance in
[How is Impedance Measured?](https://supportne.freshdesk.com/support/solutions/articles/35000308661-how-is-impedance-measured-).
It does not define the exact 150000 export value. Newer-device EEG-check guidance
on that page should not be assumed to apply to an older StarStim-8/NIC build.
The [Starstim-Home manual](https://www.neuroelectrics.com/api/downloads/NE_UM_P1_SH_1.3_EN.pdf)
describes testboard debugging for that model; it does not establish this device's
expected values or testboard calibration. Ask support to confirm:

1. ImpVal/IMP units, zero and exact-150000 semantics for the actual NIC/firmware/device.
2. Measurement mode/reference, channels included, stale/status behavior and known issues.
3. Expected testboard values/tolerance and the approved procedure/logs to distinguish
   device, flat cable, electrode cable, connector and contact problems.

Use the private inventory to supply actual serial/device details through the lab's
normal support channel. This package does not send a support request or authorize
changes to experimental parameters.
