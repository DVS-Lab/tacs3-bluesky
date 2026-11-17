"""Identity checks and retirement of unsafe automatic legacy exports."""
from pathlib import Path
import sys
import pandas as pd
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'code'))
from rhythm_validation_io import validate_identity, InputError
import calculate_theta_beta as legacy


def job():
    return dict(subject='G11033',session='3',task='bandit',phase='pre',run='1',
                eeg='20261113100137_G11033-3_Bandit_pre-stim.easy',
                events='sub-G11033-3_task-bandit_pre-stim_2026.csv')


def test_alphanumeric_identity_and_row_prefix():
    validate_identity(job(),pd.DataFrame({'subject_id':['sub-G11033'],'session_id':['ses-3']}))


@pytest.mark.parametrize('filename',['sub-G11033-2_task-bandit_pre-stim.csv',
                                     'sub-AG11033-3_task-bandit_pre-stim.csv',
                                     'sub-G110330-3_task-bandit_pre-stim.csv',
                                     'sub-G11033-3_task-bandit_post-stim.csv'])
def test_conflicting_session_identity_phase_rejected(filename):
    j=job();j['events']=filename
    with pytest.raises(InputError):validate_identity(j,pd.DataFrame())


def test_legacy_export_fails_before_reading_or_writing(tmp_path,monkeypatch):
    monkeypatch.setattr(legacy,'OUTPUT_DIR',tmp_path)
    with pytest.raises(RuntimeError,match='does not validate'):
        legacy.run_analysis('G11033','3')
    assert not list(tmp_path.iterdir())


def test_legacy_lookup_never_substitutes_post_or_other_subject(tmp_path,monkeypatch):
    monkeypatch.setattr(legacy,'STIM_DATA_DIR',tmp_path)
    monkeypatch.setattr(legacy,'BEHAVIOR_DATA_DIR',tmp_path)
    (tmp_path/'1_G11033-3_Bandit_pre-stim.easy').touch()
    (tmp_path/'sub-G11033-3_task-bandit_post-stim_2026.csv').touch()
    with pytest.raises(FileNotFoundError):legacy.find_input_files('G11033','3')
    (tmp_path/'sub-G11033-3_task-bandit_pre-stim_2026.csv').touch()
    assert legacy.find_input_files('G11033','3')[0].name.startswith('1_G11033')
    with pytest.raises(FileNotFoundError):legacy.find_input_files('G11450','3')
    (tmp_path/'2_G11033-3_Bandit_pre-stim.easy').touch()
    with pytest.raises(FileNotFoundError):legacy.find_input_files('G11033','3')


def test_zero_prefixed_alphanumeric_identity_is_not_collapsed():
    j=job();j['subject']='G12';j['eeg']='1_G12-3_Bandit_pre-stim.easy';j['events']='sub-G12-3_task-bandit_pre-stim.csv'
    with pytest.raises(InputError,match='behavior_subject_id_mismatch'):
        validate_identity(j,pd.DataFrame({'subject_id':['sub-0G12']}))
