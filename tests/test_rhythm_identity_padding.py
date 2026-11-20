"""Recover numeric zero-padding without admitting different participant IDs."""
import copy
import json
from pathlib import Path
import sys

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'code'))
from rhythm_validation_io import InputError, load_pair, validate_identity


def job():
    return next(j for j in json.loads((ROOT/'validation/pilot_manifest.json').read_text())['jobs']
                if j['id'] == '10579_ses-1_bandit_post_20260903201256')


def test_zero_padded_identity_validates_actual_matching_inputs():
    cfg = json.loads((ROOT/'code/rhythm_validation_config.json').read_text())
    raw, times, fs, names, rows, _ = load_pair(ROOT, job(), cfg['preprocessing'])
    assert len(raw) == len(times) == 150000
    assert fs == 500 and len(names) == 8 and len(rows) == 120
    choice = rows['choice_onset_unix_time'].dropna()/1000
    assert ((choice >= times[0]) & (choice <= times[-1])).sum() == 118


@pytest.mark.parametrize('wrong',['105790','0105790','1219300000'])
def test_extra_digits_do_not_become_the_same_participant(wrong):
    j = job()
    j['events'] = f'sub-{wrong}-1_task-bandit.csv'
    with pytest.raises(InputError, match='events_participant_mismatch'):
        validate_identity(j, pd.DataFrame({'subject_id':['sub-010579'], 'session_id':['ses-1']}))


def test_zero_padded_eeg_does_not_bypass_session_check():
    j = copy.deepcopy(job())
    j['eeg'] = '010579-2_Bandit_post-stim.easy'
    with pytest.raises(InputError, match='eeg_session_mismatch'):
        validate_identity(j, pd.DataFrame())


def test_matching_filename_does_not_override_conflicting_rows():
    with pytest.raises(InputError, match='behavior_subject_id_mismatch'):
        validate_identity(job(), pd.DataFrame({'subject_id':['sub-105790'], 'session_id':['ses-1']}))
