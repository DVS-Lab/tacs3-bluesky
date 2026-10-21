# Behavioral analysis variable dictionary

Every table shares `provenance.json`, `configuration.json` and the SHA-256 input
manifest. Raw columns retained in trial derivatives have their original names;
the normalized analysis columns below should be used for scoring. Units are
explicit because Bandit RT is recorded in milliseconds and SST RT in seconds.

| Variables | Meaning / denominator |
|---|---|
| `participant`, `raw_participant` | Formatting-normalized and original ID; no long-ID truncation |
| `session`, `session_order` | Recorded visit number, not condition |
| `run` | Recorded run label within task; does not establish task sequence |
| `run_order`, `task_order` | Chronological rank across selected runs/tasks in the same visit/date/phase; missing if clock is unverified |
| `phase` | `pre-stim`, `active`, `post-stim`, or `unlabeled_localizer` |
| `cohort` | `experimental_candidate`, `pilot`, `test`, or `unverified_identity`; default heuristic documented in README |
| `source_file`, `source_files` | Repository-relative immutable source path(s); aggregation inputs |
| `sha256`, `semantic_sha256` | Raw byte hash, normalized table-content hash for deduplication |
| `schema_family`, `schema_hash`, `acquisition_version` | Scoring interpretation, exact header hash, and explicit absence of recorded software version |
| `collection_date`, `filename_timestamp` | Filename's acquisition label; ordering uses actual event time |
| `start_unix_s`, `end_unix_s`, `time_source` | Available event endpoints in Unix seconds, and chosen onset column; not assumed file modification time |
| `duration_s` | Recorded task-time span when available, else Unix end minus run start/first event; no filename-time substitution |
| `trial_count`, `expected_trial_count` | Actual and schema/date-supported expected count; unknown expectations remain missing |
| `selected`, `exclusion_reason`, `qc_status`, `qc_flags` | Discovery inclusion, explicit reason, and warnings; not equivalent to SSRT validity |
| `primary_sample_status` | Selected active experimental-candidate file versus nonprimary file |
| `n_source_files`, `n_selected_files`, `file_exclusion_reasons` | All available exports/attempts and selected-file counts/reasons per QC group |

## Bandit

| Variables | Definition |
|---|---|
| `chosen_flower`, `valid_choice` | `flower1` for slot 1 or `flower2` for slot 2; not screen side |
| `choice_accuracy` | Chosen flower equals `current_good`, over valid choices/contingency IDs |
| `reward_valid`, `reward_rate`, `n_reward_valid` | Boolean reward among valid chosen trials with feedback; misses/missing feedback excluded |
| `valid_wsls`, `prev_reward`, `stay`, `shift` | Adjacent within-source-run transition; both choices and previous feedback valid |
| `p_stay_win`, `n_stay_win`, `n_win_transitions` | Number of stays after a reward / valid transitions after reward |
| `p_shift_loss`, `n_shift_loss`, `n_loss_transitions` | Number of switches after no reward / valid transitions after no reward |
| `n_trials`, `n_valid_choice`, `n_missing_feedback` | Total trial rows, valid chosen trials, chosen trials lacking usable feedback |
| `rt_ms`, `rt_mean_ms`, `rt_median_ms`, `n_valid_rt` | Choice RT, mean/median/count within current task deadline |
| `missed_response_rate` | Fraction of trials without valid choices |
| `is_reversal`, `n_reversals`, `reversal_trial`, `offset` | Change in recorded good flower, count, first new-contingency trial number, and position relative to it |
| `pre_reversal_accuracy`, `post_reversal_accuracy` | Mean accuracy at offsets −5…−1 and 0…4 |
| `perseverative_choice_rate`, `old_option_choice` | Choice of formerly good flower over valid choices in offsets 0…4; individual window value in reversal table |
| `initial_perseverative_trials`, `perseveration_censored` | Leading consecutive old-option choices and whether corrective choice was unobserved |
| `mapping_conflict`, `contingency_conflict`, `behavior_valid` | Identity/correctness/screen or reversal-state contradictions; valid only when none |

## SST

| Variables | Definition |
|---|---|
| `is_stop`, `responded` | Strictly parsed intended stop and response flags; unknown/sentinel is not True |
| `rt_s` | Valid responding-trial RT in seconds; `0 < RT <= 1.5` |
| `ssd_saved_s`, `planned_ssd_s` | Original recorded SSD and current-trial pre-update state |
| `observed_ssd_s`, `ssd_timing_kind` | Recorded onset difference and whether timing came from main onsets/reconstruction or current-SSD EEG schema |
| `ssd_used_s` | Main observed delay if displayed, otherwise planned; EEG saved current SSD; stop rows only |
| `response_before_stop_display` | Intended stop response before display, with missing stop onset and RT no later than planned SSD+tolerance |
| `early_response_by_planned_ssd` | Intended stop response earlier than the planned delay (separate from observed display evidence) |
| `ssd_state_mismatch`, `ssd_timing_mismatch` | Saved-state contradiction or observed delay differing from planned by >50 ms/nonpositive |
| `missing_stop_signal`, `invalid_event` | Missing display not explained by an early response, or invalid/contradictory outcome/response fields |
| `n_go`, `n_stop`, `n_go_responses`, `n_failed_stop` | Intended-trial and response counts; includes early stop failures |
| `p_respond_stop`, `stop_success_rate` | Stop responses / intended stops; no response / intended stops |
| `go_accuracy`, `go_accuracy_value` | Correct go responses / all go trials; omission counts as incorrect |
| `go_omission_rate`, `n_go_omissions` | No-response go trials / all go trials; sentinel 999 is an omission flag |
| `go_rt_mean_ms`, `go_rt_median_ms` | Responding-go RTs, including errors; do not mix with correct-go-only measure |
| `correct_go_rt_mean_ms`, `failed_stop_rt_mean_ms` | Correct-go-only mean and stop-response mean (ms) |
| `ssd_mean_ms`, `ssd_median_ms` | Mean/median current-trial SSD across intended stops |
| `ssrt_ms`, `ssrt_valid`, `ssrt_status` | Gated integration estimate; missing if withheld; run-level values explicitly provisional |
| `ssrt_exclusion_reasons` | Count, accuracy, omission, probability, race-model, timing/event or plausibility failure(s) |
| `ssrt_pool_source_files`, `ssrt_pool_excluded_source_files` | Included/excluded run sources for pooled visit estimate |
| `ssrt_pool_n_go`, `ssrt_pool_n_stop`, `ssrt_pool_p_respond`, `ssrt_pool_ssd_mean_ms` | Exact pooled SSRT denominators/stop delay; session descriptions can use more runs |
| `n_early_response_before_display`, `n_response_before_planned_stop` | Counts of distinct early flags; neither removes intended stops |
| `n_missing_stop_signal`, `n_ssd_state_mismatch`, `n_ssd_timing_mismatch`, `n_invalid_events` | Run/pool QC contradiction counts |
| `n_observed_ssd`, `n_anticipated_responses` | Stop onset-difference availability and RT<100-ms counts for review |

## Frequencies, assignment and design

| Variables | Meaning |
|---|---|
| `rhythm`, `historical_frequency_hz`, `historical_theta_hz`, `historical_beta_hz` | Original numerical estimates; a wide value is missing when conflicting values exist |
| `method`, `task_source`, `eeg_source`, `behavior_source` | Historical method string and original task/input pairing |
| `eligible_epochs`, `retained_epochs`, `qc_flags`, `reliability_status` | Available historical QC counts/warnings; not upgraded to physiological reliability |
| `fallback_status` | Explicitly documented fallback or `not_documented`; numeric equality with a fallback is insufficient |
| `theta_frequency_status`, `beta_frequency_status` | Missing, conflicting reports, or unvalidated historical value(s) |
| `historical_theta_values`, `historical_beta_values` | All distinct recorded historical values, retained without arbitrary choice |
| `record_kind`, `frequency_hz`, `frequency_values` | Generated protocol versus device `.info` parameter record, and observed parameter value(s) |
| `stim_record_count`, `first_stim_timestamp`, `delivery_status` | Device stimulation evidence fields and explicit verification limitation |
| `generated_frequency_values_hz`, `device_documented_frequency_values_hz` | Session coverage of generated versus recorded device settings |
| `intended_condition`, `intended_frequency_hz`, `condition_status`, `condition_evidence` | Private documented assignment; unknown by default |
| `documented_delivered_frequency_hz`, `delivery_verified`, `verified_delivery_status` | Separate documented-delivery assertion; never inferred from generation |
| `contrast`, `difference` | Within-person intended-condition outcome difference; no cross-person substitution |
| `treatment_session`, `reference_session`, `assignment_basis` | Visit provenance for paired comparison; intended assignment is not proof of delivery |

Missing estimates are blank/NaN, never zero. Zero Hz in a protocol/device record is
a recorded parameter, not a missing-value code or independently assigned condition.
