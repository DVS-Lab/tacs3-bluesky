# TACS-3 offline behavioral analysis

This directory is independent of the acquisition programs. It never imports or
changes task presentation, REDCap, EEG collection, protocol generation or frequency
selection. All new code, tests, documentation, ignore rules and local outputs live
here. Run it from the repository root after each visit:

```sh
python -m behavioral_analysis
```

That command scans new and existing files, scores Bandit and SST, and rebuilds
`behavioral_analysis/outputs/latest/report.html`. Open that report in a browser.
The output directory and `behavioral_analysis/local/` are ignored. Do not commit
derived participant data, a condition key, a recruitment roster or clinical records.

For the current frequency-report discrepancies, delivery evidence gaps and the
next-session checklist, see [TEAM_PRESESSION_CHECKS.md](TEAM_PRESESSION_CHECKS.md).
That note is intended for the PI and authorized stimulation staff; its parameter
details should be shared under the study's blinding rules.

## Setup and testing

Python 3.9 or later; NumPy, pandas and Matplotlib, with pytest for tests. No Bayesian,
R, EEG or experimental-presentation dependencies are required.

```sh
python3 -m venv behavioral_analysis/local/venv
source behavioral_analysis/local/venv/bin/activate
python -m pip install -r behavioral_analysis/requirements.txt
python -m pytest behavioral_analysis/tests -q
TACS3_REAL_ROOT="$PWD" python -m pytest behavioral_analysis/tests -q
python -m behavioral_analysis
```

The last test command enables the read-only real-data integration test, including
experimental and pilot recordings. It checks the known interrupted/restarted SST
attempt, output production, SSRT eligibility, and acquisition-source hashes. The
ordinary tests use known synthetic sequences. The tested dependency versions are
recorded in each output's `provenance.json`; the initial verified environment is
captured in `requirements-tested.txt`.

For another checkout or a separate destination:

```sh
python -m behavioral_analysis --root /path/to/tacs3-bluesky --output /path/to/private/derived
```

`--config` selects a separate analysis-only configuration. Never use it to modify
the experimental `code/config.json`. Outputs overlapping source-data/acquisition
directories are rejected. `--no-plots` is available for smoke testing only.

## Discovery, identity and inclusion

The manifest inventories every task CSV/TSV in `data/`, `pilot_data/`, and
`stimulation/pre-stimulation-participant-responses/`, including empty, malformed,
aborted and duplicate exports. A separate auxiliary manifest inventories pilot
auxiliary files, historical estimates, generated protocols and device/EEG files;
raw EEG is not analyzed here. Behavioral files and parsed metadata have SHA-256
hashes; raw EEG has file-size/path coverage only.

* Delimiters are detected from the contents; some `.csv` files contain tabs.
* Only `sub-`, a numeric `G` prefix, and numeric leading zeros are normalized.
  Long IDs are **not** truncated or fuzzily matched. Raw IDs are retained. A
  numeric G-prefix is treated as a formatting variant, not proof of enrollment.
* Pilot-directory provenance labels recordings as pilot. Elsewhere five-digit
  IDs starting with 1 are `experimental_candidate`; short/nonnumeric IDs are test,
  and other numeric formats remain unverified. This heuristic is transparent and
  cannot certify recruitment. Supply a documented local roster to override it.
* Filename/body participant, visit and explicit run labels are checked. Conflicts
  and broken trial sequences are excluded rather than silently repaired.
* Pre/post labels remain separate phases. Unlabeled localizers do not become
  active study runs. Multiple dates sharing a primary visit label are flagged and
  cannot produce an eligible pooled SSRT or valid Bandit session outcome.
* Task schema family and header hash are recorded. Acquisition software versions
  are generally **not recorded** in the original data; schema is not an exact
  historical software-version identifier.
* Semantically identical tables are deduplicated across delimiters and locations.
  Data-directory copies take precedence, then pilot copies, then localizer copies.
* Active current SST runs require 91 trials. Active experimental-candidate Bandit
  runs require a recorded duration within 15 seconds of 600 seconds, not a fixed
  trial count. The current active Bandit code overrides the config trial target
  with a ten-minute duration. Pilot/localizer duration/count differences remain
  visible; they are not assumed to share the active protocol.
* Repeated **complete** attempts for one participant/visit/task/phase/run/date are
  quarantined. A uniquely complete recording can be retained after an incomplete
  restart is excluded. Modification time and filename recency never select a run.
* Exclusions are metric specific: a discovery exclusion prevents all scoring;
  a missing choice/RT/feedback affects its relevant measure; SST validity flags
  withhold SSRT while preserving behavioral descriptions.

Optional private inputs (header-only templates are supplied in `templates/`):

```sh
python -m behavioral_analysis \
  --roster behavioral_analysis/local/roster.csv \
  --adjudications behavioral_analysis/local/adjudications.csv \
  --condition-key behavioral_analysis/local/condition_key.csv
```

The roster requires `participant,cohort,evidence`. Allowed cohorts match those
above. Adjudications require `source_file,sha256,decision,reason`, where decision is
`include` or `exclude`. An inclusion can resolve a complete-attempt ambiguity but
cannot override structural/incomplete-data exclusions. Exactly one chosen attempt
per logical run is enforced. Keys are hashed in provenance and never copied into
the repository's tracked code. Their derived values appear only in ignored outputs.

## Bandit scoring

`choice` is option **slot** 1 or 2; the chosen identity is `flower1` or `flower2`,
respectively. The screen position is randomized independently. `current_good`
identifies the flower with the higher reward probability; it does not mean the
last rewarded response. Accuracy is recomputed from the chosen flower, with
recorded correctness, screen mappings and contingency changes checked for conflicts.
Outcome labels/feedback markers are checked against reward; a contradictory outcome
is not used to define the next WSLS transition.

P(stay | win) and P(shift | loss) use adjacent trials **within each source run**.
Both choices and the preceding outcome must be valid; a missing trial/choice does
not create a bridge to the next observed choice. Current feedback is not needed
for the current transition, but missing feedback prevents the following one.
Numerators and win/loss transition denominators are exported. Session WSLS sums
within-run numerators and denominators; it does not create cross-run transitions.

Choice accuracy uses valid choices with a valid good-flower identity. Reward rate
uses valid choices with recorded Boolean reward. A miss is not a loss. RT is
milliseconds, valid only for a recorded choice and `0 < RT <= 1250` (the current
task deadline); no earlier-study 200–1990-ms filter is inherited. Means, medians,
valid counts, omissions and missing-feedback counts are exported. Mapping/feedback
conflicts invalidate the run/session's `behavior_valid` flag and group summaries.

Reversals use adjacent changes in `current_good`, corroborated by `contingency_id`.
Trial offset 0 is the first trial in the new contingency. Export windows −5 to +15,
pre-reversal accuracy (−5…−1), post-reversal accuracy (0…4), and the rate of choosing
the formerly good flower (0…4). Initial consecutive old-option choices are exported
with a censoring indicator (a miss, window end or lack of an observed corrective
choice censors the count). These are descriptive perseverative responses, not a
unique latent perseveration parameter. Group reversal curves average within
participant first. WSLS asymmetry is not evidence of asymmetric learning rates.

## SST SSD reconstruction and SSRT

Two schema families are scored separately:

1. **`sst_main_updated_ssd`:** `ssd` is recorded after success/failure updates it.
   Reconstruct the state before each trial from 250 ms, ±50-ms steps, and 50–900-ms
   bounds, resetting at each source run. Validate every saved post-update state.
   For displayed stops use recorded `stop_onset - stim_onset` in seconds, checking
   it against the reconstructed planned SSD within 50 ms. Onsets are software
   timestamps, not independently measured screen/hardware timing.
2. **`sst_eeg_current_ssd`:** the recorder receives the current SSD before the
   update. Use it directly and validate the staircase. The task-time stop onset is
   synthesized as stimulus onset plus SSD and cannot independently validate timing.
   Unix onset differences, when present, are retained as corroboration; the recorder
   can also fill these arithmetically, so they do not prove physical presentation.

The active task stops its response loop immediately when a response occurs. An
intended stop trial can therefore finish before the red arrow is drawn. Such a
response remains a **stop failure**, not a go trial. Keep its planned SSD in the
mean stop delay and count it in P(respond | stop); conditioning on displayed
signals would remove the fastest failures. Missing stop display after the planned
delay is a timing error. Store separate display-based and planned-SSD early flags.

SSRT follows the [integration method with go-omission replacement](https://elifesciences.org/articles/46323):

* Include all valid responding-go RTs, including directional errors.
* Replace each go omission with the maximum observed valid go RT in that run/pool.
  Sentinel `go_miss=999` indicates an omission, not a valid response/accuracy score.
  Invalid RT sentinels are not used as RTs. A response with invalid/missing RT is an
  event inconsistency, not silently recoded as an omission.
* P(respond | stop) counts **all intended stop trials**, including early failures.
* Sort the omission-replaced go distribution. Use empirical rank
  `ceil(N_go * P(respond | stop))` (one based), and subtract mean trial-specific SSD
  across intended stop trials. Do not average run SSRTs to obtain a visit estimate.

Exact project gates, set in `config.json` and intended for prospective review:

| Check | Run | Pooled visit/phase |
|---|---:|---:|
| Go trials | ≥30 | ≥30 |
| Intended stop trials | ≥20 | ≥50 |
| P(respond on stop) | 0.25–0.75 inclusive | same |
| Go accuracy over all go trials | ≥0.80 | same |
| Go omission fraction | ≤0.10 | same |
| Mean failed-stop versus responding-go RT | strictly faster | same |
| Event, missing-signal, saved-state or timing contradictions | none | none |
| SSRT plausibility | 50–500 ms | same |

The probability limits and race-model diagnostic follow the consensus guide.
The other numerical gates are **provisional project choices**, not established
clinical cutoffs or an independent validation of this task. Run estimates with
20–49 stop trials are explicitly provisional. Anticipatory RT counts (<100 ms)
are reported for review. Failed gates emit `ssrt_ms` as missing with reasons.

Visit estimates are recalculated by pooling substantively eligible runs of the
same participant/visit/date/phase. Low-count-only runs can enter a pool that reaches
the pooled count gate. Runs failing other gates are omitted from that SSRT pool;
both included and excluded source lists, pool go/stop counts, P(respond), and mean
SSD are exported. The other session descriptors use all selected runs. Their
denominators may consequently differ from the explicitly named `ssrt_pool_*` fields.
Pre, active and post are never combined. No SSRT is treated as a trial-level datum.

## Stimulation metadata and future analyses

Historical theta/beta estimates retain source method, task/EEG/event pairing,
eligible/retained epochs, fallback documentation and warning indicators. Conflicting
reports are not collapsed to an arbitrary value. Historical numbers remain
unvalidated. Numeric 6/20-Hz values alone do not establish fallback use. Legacy
summaries lacking a documented participant/visit join are auxiliary inventory only.

Generated protocol frequencies, device `.info` settings, first-stimulation timestamp
and stimulation sample count are distinct. A generated 0-Hz protocol is not used
to assign sham; device settings do not prove delivery. EEG-only mode and zero
stimulation samples require coordinator review against the intended procedure.

The optional condition key requires `participant,session,condition_evidence`, and
either `intended_condition` (`sham`, `theta`, `beta`) or a documented A–F
`counterbalance`. Its mapping is checked against the current generator's mapping;
conflicting explicit values are rejected. Optional `intended_frequency_hz`,
`documented_delivered_frequency_hz` and `delivery_verified` remain separate.
Claiming verified delivery requires a finite documented frequency and evidence.
This imports the local investigator's assertion; it does not independently certify
the hardware. Do not create such evidence from a filename or numeric rhythm alone.

The [open rhythm-validation PR #1](https://github.com/DVS-Lab/tacs3-bluesky/pull/1)
was reviewed at `b3fa31557b5b4251912b96313a5f5d0ead851232`, specifically
`docs/pilot_rhythm_validation_report.md` and `docs/rhythm_estimation_audit.md`.
It reports no primary theta/beta estimate passing provisional QC. Its sources,
historical estimates and experimental frequency-selection procedure remain unchanged.
No frequency correlation is currently estimated; frequency–behavior associations
would be exploratory and could not establish stimulation efficacy.

When documented assignments exist, the pipeline automatically emits within-person
theta−sham, beta−sham and theta−beta differences for eligible outcomes. Repeated
same-condition visits require adjudication rather than accidental averaging.
No inferential model is automatically fitted. `analysis_readiness.json` records
coverage, modeling cautions, and proposed trial-level Bandit and visit-level SST
formulas. Trial/run exports retain visit, chronological run order, timestamp-derived
task order, condition status and source files. A future fit must check paired sample
size, identifiability, accuracy/speed tradeoffs and convergence first. Clinical
variables are not used. PANAS/betting columns may remain in local trial derivatives
but are not primary outcomes in this pass.

## Outputs and provenance

`report.html`, `initial_results.txt`, `sst_qc.html`, and ranked
`collection_warnings.{txt,csv}` are the review entry points. `manifest.csv` and
`participant_session_qc.csv` cover all files/groups, including groups with no
selected run. `exclusion_log.csv` covers discovery decisions, while
`primary_sample_exclusions.csv` also documents cohort/phase separation and
`trial_qc_log.csv` explains affected trials. Trial, reversal, run and session tables
retain source-file links. `task_sequence.csv` orders actual event timestamps, flags
overlap, and leaves order unverified when Unix clocks are unavailable.

`provenance.json` records the data-repository revision, analysis-source hashes,
configuration/key hashes, reviewed rhythm branch, package versions, and end-of-run
source integrity checks. `output_index.json` hashes artifacts including plots and
links them to the manifest/configuration. Outputs are deterministic for the same
inputs/software/config, apart from external library metadata. A concurrent source
change aborts analysis rather than claiming an immutable input snapshot.

See [VARIABLE_DICTIONARY.md](VARIABLE_DICTIONARY.md), [REUSE.md](REUSE.md), and
[NEXT_STEPS.md](NEXT_STEPS.md). Source acquisition anomalies are reported, never
fixed by changing the experiment in this work.
