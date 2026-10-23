"""Check CI really analyzed EEG, rather than merely emitting input-failure JSON."""
import argparse
import json
from pathlib import Path

import pandas as pd

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--output', default='ci-smoke', help='Run directory name within validation_outputs')
args = parser.parse_args()
out = root / 'validation_outputs' / args.output
completion = json.loads((out / 'completion.json').read_text(encoding='utf-8'))
assert completion['completed'] and completion['recordings'] == 4
summary = pd.read_csv(out / 'qc_summary.csv')
assert len(summary) == 10
beta = summary[summary.estimand == 'response_beta_erd']
assert sorted(beta.n_eligible.tolist()) == [47, 53, 119, 120], 'EEG/event loading or selection changed'
pre = beta[(beta.task == 'bandit') & (beta.phase == 'pre')].iloc[0]
assert pre.n_retained == 115, 'Expected retained Bandit epochs were not analyzed'
spectrum = pd.read_csv(out / pre.recording_id / 'response_beta_erd' / 'spectrum.csv')
assert abs(spectrum.loc[spectrum.frequency_hz == 23, 'change_db'].iloc[0] - (-0.06508836339709226)) < 1e-8, 'Mean-log-ratio regression'
result = json.loads((out / pre.recording_id / 'response_beta_erd' / 'result.json').read_text())
assert result['power_normalization'] == 'per_trial_meanlogratio'
assert result['analysis_version'] == 'offline-rhythm-validation-1.2'
assert result['candidate_hz'] is None and 'no_resolved_carrier_peak' in result['failure_reasons']
assert result['contrast_extremum_hz_descriptive'] == 23
assert result['estimator'] == 'full_epoch_hann_carrier_with_separate_task_modulation'
assert (out / pre.recording_id / 'response_beta_erd' / 'carrier_spectrum.csv').exists()
assert beta.individualized_frequency_hz.isna().all(), 'Pilot reliability conclusions changed'
print('Real-data smoke verified: 4 recordings, 10 analyses, expected selection/retention and no approved candidates.')
