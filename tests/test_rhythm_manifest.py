import json
from pathlib import Path
import subprocess
import sys

import pytest
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


def test_github_desktop_git_follows_installed_versions(tmp_path):
    from build_rhythm_manifest import desktop_git

    for version in ['3.9.11', '3.10.0', 'invalid']:
        binary = tmp_path / f'app-{version}/resources/app/git/cmd/git.exe'
        binary.parent.mkdir(parents=True)
        binary.touch()
    assert desktop_git(tmp_path) == str(tmp_path / 'app-3.10.0/resources/app/git/cmd/git.exe')


def test_checkout_inventory_and_retries(tmp_path):
    from build_rhythm_manifest import build_inventory, find_git

    def git(*args):
        subprocess.run([find_git(), '-C', str(tmp_path), *args], check=True, capture_output=True)

    # Standalone clone with no main or origin refs.
    git('init', '-b', 'review')
    seed = put(tmp_path, 'validation/pilot_manifest.json', '{"jobs":[]}')
    raw = put(tmp_path, 'sample with space.csv', 'source')
    git('add', '.')
    git('-c', 'user.name=Test', '-c', 'user.email=test@example.org', 'commit', '-m', 'fixture')
    first = build_inventory(tmp_path)
    second = build_inventory(tmp_path)
    assert first.parent != second.parent
    report = json.loads((first.parent / 'inventory.json').read_text())
    assert report['git_source_ref'] == 'HEAD'
    assert report['input_sha256'][raw] == digest(tmp_path / raw)
    assert report['historical_manifest_sha256'] == digest(tmp_path / seed)
    with pytest.raises(FileExistsError, match='already exists'):
        build_inventory(tmp_path, output_name=first.parent.name)
    assert first.read_bytes() == second.read_bytes()
    with pytest.raises(ValueError, match='Git could not read'):
        build_inventory(tmp_path, ref='origin/main', output_name='retry')
    assert not (tmp_path / 'validation_outputs/retry').exists()
    (tmp_path / raw).write_text('edited')
    with pytest.raises(ValueError, match='inputs differ'):
        build_inventory(tmp_path, output_name='retry')
    assert not (tmp_path / 'validation_outputs/retry').exists()


def test_missing_git_does_not_claim_output(tmp_path, monkeypatch):
    import build_rhythm_manifest as inventory

    monkeypatch.setattr(inventory.shutil, 'which', lambda command: None)
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    with pytest.raises(FileNotFoundError, match='GitHub Desktop'):
        inventory.build_inventory(tmp_path, output_name='review')
    assert not (tmp_path / 'validation_outputs').exists()
