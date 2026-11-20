from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'code'))
from build_rhythm_manifest import build,digest


def put(root,path,content):
    p=root/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(content);return path


def test_hash_dedup_and_exact_identity_no_subject_prefix_match(tmp_path):
    eeg='20261117120000_G12-1_Bandit_pre-stim'
    paths=[put(tmp_path,f'a/{eeg}.easy','eeg'),put(tmp_path,f'b/{eeg}.easy','eeg'),
           put(tmp_path,f'a/{eeg}.info','meta'),put(tmp_path,'a/sub-G123-1_task-bandit_pre-stim.csv','wrong')]
    m,i=build(tmp_path,paths,{'jobs':[]})
    assert len(m['jobs'])==1 and m['jobs'][0]['events'] is None
    assert i['summary']['duplicate_easy_copies']==1
    assert i['summary']['recordings_with_all_input_paths']==0


def test_ambiguous_distinct_behavior_fails_without_newest_guess(tmp_path):
    eeg='20261117120000_G12-1_Bandit_pre-stim'
    paths=[put(tmp_path,f'{eeg}.easy','eeg'),put(tmp_path,f'{eeg}.info','meta'),
           put(tmp_path,'sub-G12-1_task-bandit_pre-stim_a.csv','first'),
           put(tmp_path,'sub-G12-1_task-bandit_pre-stim_b.csv','second')]
    m,_=build(tmp_path,paths,{'jobs':[]})
    assert m['jobs'][0]['events'] is None
    assert m['jobs'][0]['missing_reason']=='ambiguous_behavior'


def test_behavior_duplicate_identical_bytes_can_be_used(tmp_path):
    eeg='20261117120000_G12-1_Bandit_pre-stim'
    paths=[put(tmp_path,f'{eeg}.easy','eeg'),put(tmp_path,f'{eeg}.info','meta'),
           put(tmp_path,'a/sub-G12-1_task-bandit_pre-stim.csv','same'),
           put(tmp_path,'b/sub-G12-1_task-bandit_pre-stim.csv','same')]
    m,i=build(tmp_path,paths,{'jobs':[]})
    assert m['jobs'][0]['events'].startswith('a/')
    assert i['summary']['recordings_with_all_input_paths']==1


def test_historical_relocations_require_exact_hash(tmp_path):
    paths=[put(tmp_path,'new/record.easy','eeg'),put(tmp_path,'new/events.csv','events'),put(tmp_path,'new/record.info','changed')]
    old={'id':'reviewed','eeg':'old/record.easy','events':'old/events.csv','metadata':'old/record.info',
         'sha256':{'eeg':digest(tmp_path/paths[0]),'events':digest(tmp_path/paths[1]),'metadata':'not-matching'}}
    m,i=build(tmp_path,paths,{'jobs':[old]})
    assert m['jobs'][0]['eeg']=='new/record.easy'
    assert m['jobs'][0]['metadata'] is None
    assert m['jobs'][0]['events'] is None
    assert 'metadata' in m['jobs'][0]['missing_reason']
    assert i['historical_relocations'][0]['missing']==['metadata']


def test_post_not_substituted_for_pre(tmp_path):
    eeg='20261117120000_G12-1_Bandit_pre-stim'
    paths=[put(tmp_path,f'{eeg}.easy','eeg'),put(tmp_path,f'{eeg}.info','meta'),
           put(tmp_path,'sub-G12-1_task-bandit_post-stim.csv','wrong')]
    m,_=build(tmp_path,paths,{'jobs':[]})
    assert m['jobs'][0]['events'] is None
