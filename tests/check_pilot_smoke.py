"""Check CI really analyzed EEG, rather than merely emitting input-failure JSON."""
import json
from pathlib import Path

import pandas as pd

root = Path(__file__).resolve().parents[1]
out = root / 'validation_outputs' / 'ci-smoke'
completion = json.loads((out / 'completion.json').read_text(encoding='utf-8'))
assert completion['completed'] and completion['recordings'] == 4
summary = pd.read_csv(out / 'qc_summary.csv')
assert len(summary) == 10
beta = summary[summary.estimand == 'response_beta_erd']
assert sorted(beta.n_eligible.tolist()) == [47, 53, 119, 120], 'EEG/event loading or selection changed'
pre = beta[(beta.task == 'bandit') & (beta.phase == 'pre')].iloc[0]
assert pre.n_retained == 115, 'Known clean Bandit epochs were not analyzed'
assert beta.individualized_frequency_hz.isna().all(), 'Pilot reliability conclusions changed'
print('Real-data smoke verified: 4 recordings, 10 analyses, expected selection/retention and no approved candidates.')
