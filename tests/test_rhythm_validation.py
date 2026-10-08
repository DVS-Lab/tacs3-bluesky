"""Scientific behavior and fail-closed input/protocol boundaries."""
import copy
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'code'))
from rhythm_validation_core import assess, epoch_data, feature, preprocess, preview, spectra
from rhythm_validation_io import InputError, alignment_qc, clock_qc, load_pair, seconds, select_events, sha256, validate_identity
from validate_rhythms import create_output


@pytest.fixture
def config():
    return json.loads((ROOT/'code/rhythm_validation_config.json').read_text())


def gaussian(f,center=21,width=1.8):return np.exp(-.5*((f-center)/width)**2)


def synthetic_epochs(spec, frequency, n=80):
    rng=np.random.default_rng(1729)
    fs=100
    times=np.arange(round((spec['epoch_sec'][1]-spec['epoch_sec'][0])*fs))/fs+spec['epoch_sec'][0]
    epochs=rng.normal(0,2,(n,3,len(times)))
    for i in range(n):
        freq=frequency if np.isscalar(frequency) else frequency[i]
        phase=rng.uniform(-np.pi,np.pi)
        start,end=spec['analysis_sec']
        active=(times>=start-.12)&(times<=end+.12)
        amp=np.where(active,1,8) if spec['direction']<0 else np.where(active,8,1)
        oscillation=amp*np.sin(2*np.pi*freq*times+phase)
        # Opposing channel phases would cancel if voltage were averaged first.
        epochs[i,0]+=oscillation;epochs[i,1]-=oscillation;epochs[i,2]+=oscillation*.6
    return epochs,times,fs


@pytest.mark.parametrize('key,freq',[('response_beta_erd',21),('stop_success_beta_enhancement',21),('feedback_theta_enhancement',6)])
def test_known_time_domain_signals(config,key,freq):
    spec=config['estimands'][key]
    ep,t,fs=synthetic_epochs(spec,freq)
    f,trials,base,active,_,_=spectra(ep,t,fs,spec)
    absolute=base if spec['direction']<0 else active
    result=assess(f,trials,absolute,spec,config,len(ep),3)
    assert result['reliable'],result['failure_reasons']
    assert abs(result['candidate_hz']-freq)<=.5
    assert result['effect_db']*spec['direction']>0
    assert result['approved_stimulation_frequency_hz'] is None


@pytest.mark.parametrize('kind',['flat','broadband','monotonic','boundary','wrong_sign','broad','ambiguous','nan'])
def test_unidentifiable_spectra(config,kind):
    spec=config['estimands']['response_beta_erd'];f=np.arange(8,40.5,.5)
    shapes={'flat':np.zeros(len(f)),'broadband':np.full(len(f),-3),
            'monotonic':-f/5,'boundary':-3*gaussian(f,13),
            'wrong_sign':3*gaussian(f),'broad':-3*gaussian(f,width=15),
            'ambiguous':-3*(gaussian(f,18,1)+gaussian(f,26,1)),
            'nan':np.full(len(f),np.nan)}
    result=feature(f,shapes[kind],spec,config['reliability'])
    assert result['reasons']


def test_absent_absolute_peak_fails(config):
    spec=config['estimands']['response_beta_erd'];f=np.arange(8,40.5,.5)
    result=feature(f,-3*gaussian(f),spec,config['reliability'],1/f**2)
    assert 'no_absolute_spectral_corroboration' in result['reasons']


def test_stability_and_reproducibility(config):
    spec=config['estimands']['response_beta_erd'];f=np.arange(8,40.5,.5)
    stable=np.tile(-3*gaussian(f),(80,1));absolute=np.tile(1+5*gaussian(f),(80,1))
    a=assess(f,stable,absolute,spec,config,80,3);b=assess(f,stable,absolute,spec,config,80,3)
    assert a==b and a['reliable']
    unstable=np.array([-3*gaussian(f,17 if i<40 else 26) for i in range(80)])
    result=assess(f,unstable,absolute,spec,config,80,3)
    assert not result['reliable']
    assert 'chronological_split_unstable_or_missing' in result['failure_reasons']


@pytest.mark.parametrize('n',[0,1,5,39])
def test_no_or_low_epochs(config,n):
    spec=config['estimands']['response_beta_erd'];f=np.arange(8,40.5,.5)
    result=assess(f,np.tile(-3*gaussian(f),(n,1)),np.tile(1+gaussian(f),(n,1)),spec,config,80,3)
    assert not result['reliable'] and result['individualized_frequency_hz'] is None
    assert 'insufficient_epochs' in result['failure_reasons']


def test_noisy_flat_and_fp1_channels(config):
    rng=np.random.default_rng(3);fs=100
    names=['F3','Fp1','FCz','FT7','F4','P4','P3','EXT']
    raw=rng.normal(0,2,(6000,8));raw[:,1]=rng.normal(0,800,6000);raw[:,6]=0;raw[:,7]=0
    clean,filtered,roi,refs,qc=preprocess(raw,fs,names,config['preprocessing'])
    assert qc['Fp1']['bad'] and qc['P3']['bad'] and qc['EXT']['bad']
    assert len(roi)==3 and 1 not in refs and 7 not in refs
    assert np.max(abs(clean[:,roi]))<20
    t=np.arange(len(raw))/fs
    logs=[dict(eligible=True,event_sec=10,reason='',retained=False)]
    ep,_,logs=epoch_data(clean,filtered,t,fs,names,roi,refs,logs,config['estimands']['response_beta_erd'],config['preprocessing'])
    assert len(ep)==1,logs
    assert logs[0]['warning']=='fp1_artifact_without_detected_roi_spread'


def test_ocular_spread_is_rejected(config):
    rng=np.random.default_rng(3);fs=100
    names=['F3','Fp1','FCz','FT7','F4','P4','P3','EXT'];t=np.arange(6000)/fs
    raw=rng.normal(0,1,(6000,8));blink=100*np.exp(-((t-10)/.08)**2)
    raw[:,1]+=blink*3;raw[:,0]+=blink;raw[:,2]+=blink
    clean,filtered,roi,refs,qc=preprocess(raw,fs,names,config['preprocessing'])
    logs=[dict(eligible=True,event_sec=10,reason='',retained=False)]
    ep,_,logs=epoch_data(clean,filtered,t,fs,names,roi,refs,logs,config['estimands']['response_beta_erd'],config['preprocessing'])
    assert len(ep)==0


def test_all_rejected_and_insufficient_roi(config):
    fs=100;t=np.arange(3000)/fs
    raw=np.zeros((3000,3));names=['F3','FCz','F4']
    clean,filtered,roi,refs,qc=preprocess(raw,fs,names,config['preprocessing'])
    ep,_,logs=epoch_data(clean,filtered,t,fs,names,roi,refs,[dict(eligible=True,event_sec=10,reason='')],config['estimands']['response_beta_erd'],config['preprocessing'])
    assert len(ep)==0 and logs[0]['reason']=='insufficient_roi_channels'


@pytest.mark.parametrize('fault',['reverse','gap','rate','nan'])
def test_sampling_failures(config,fault):
    t=np.arange(1000)/500
    if fault=='reverse':t[20]=t[19]
    if fault=='gap':t[500:]+=.1
    if fault=='rate':t*=2
    if fault=='nan':t[20]=np.nan
    with pytest.raises(InputError):clock_qc(t,500,config['preprocessing'])


def test_unix_units_and_overlap(config):
    unix=1_780_000_000+np.arange(100)/500
    np.testing.assert_allclose(seconds(unix*1000,'ms','unix'),seconds(unix,'s','unix'))
    with pytest.raises(InputError):seconds(unix*1000,'s','unix')
    with pytest.raises(InputError):seconds(np.arange(100),'s','unix')
    with pytest.raises(InputError):alignment_qc([dict(eligible=True,event_sec=123,event_column='response_onset_unix_time')],pd.DataFrame(),unix,config['preprocessing'])


def test_correct_go_and_stop_selection():
    rows=pd.DataFrame({'stop':[0,0,0,1,1],'go_correct':[1,0,0,0,0],'stop_success':[0,0,0,1,0],
                       'response':[True,True,False,False,True],
                       'response_onset_lsl_time':[10,20,None,None,50],'stop_onset_lsl_time':[None,None,None,40,49]})
    for key,expected in [('response_beta_erd',[1]),('stop_success_beta_enhancement',[4]),('stop_failure_beta_enhancement',[5])]:
        logs=select_events(rows,'sst',key,'lsl',{})
        assert [l['row'] for l in logs if l['eligible']]==expected


def test_missing_event_timestamp_counted():
    rows=pd.DataFrame({'choice':[1,1,2],'choice_onset_lsl_time':[2,None,4]})
    logs=select_events(rows,'bandit','response_beta_erd','lsl',{})
    assert len(logs)==3 and logs[1]['reason']=='missing_event_timestamp'


@pytest.mark.parametrize('field,value',[('subject','10085'),('task','sst'),('phase','post'),('session','2')])
def test_identity_mismatch(field,value):
    job=dict(subject='10034',session='1',task='bandit',phase='pre',run='01',
             eeg='20260918104411_10034-1_Bandit_pre-stim.easy',events='sub-10034-1_task-bandit_pre-stim.csv')
    rows=pd.DataFrame({'subject_id':['sub-10034'],'session_id':['ses-1']})
    job[field]=value
    with pytest.raises(InputError):validate_identity(job,rows)


def test_hash_failure_and_missing_metadata(config,tmp_path):
    job=copy.deepcopy(json.loads((ROOT/'validation/pilot_manifest.json').read_text())['jobs'][4])
    job['sha256']['events']='wrong'
    with pytest.raises(InputError,match='hash_mismatch'):load_pair(ROOT,job,config['preprocessing'])


def test_output_cannot_overwrite(tmp_path):
    out=create_output(tmp_path,'first')
    assert out.exists()
    with pytest.raises(FileExistsError):create_output(tmp_path,'first')
    with pytest.raises(InputError):create_output(tmp_path,'../stimulation')


def test_preview_cannot_approve():
    r=dict(subject='10034',session='1',task='bandit',phase='pre',run='01',estimand='response_beta_erd',
           individualized_frequency_hz=21,approved_stimulation_frequency_hz=21,analysis_version='test')
    p=preview(r)
    assert p['requires_pi_approval'] and p['approved_stimulation_frequency_hz'] is None
    assert 'frequency_to_use_hz' not in p


def test_wavelet_padding_is_enforced(config):
    spec=copy.deepcopy(config['estimands']['response_beta_erd']);spec['epoch_sec']=[-1.5,.5]
    with pytest.raises(InputError,match='wavelet_padding'):
        epoch_data(np.zeros((1000,3)),np.zeros((1000,3)),np.arange(1000)/100,100,['F3','FCz','F4'],[0,1,2],[0,1,2],[],spec,config['preprocessing'])


def test_live_selector_refuses_offline_result(config,tmp_path):
    from select_stimulation_frequency import select_stimulation_frequency
    live=json.loads((ROOT/'code/config.json').read_text())
    path=tmp_path/'candidate.json'
    path.write_text(json.dumps({'reliable':True,'intended_use':'offline_validation_only','frequency_to_use_hz':21}))
    with pytest.raises(ValueError,match='cannot select stimulation'):
        select_stimulation_frequency('10034','1',live,rhythm_key='bandit_decision_beta',estimate_file=path)
    path.write_text(json.dumps({'mode':'dry_run_only','reliable':True,'frequency_to_use_hz':21}))
    with pytest.raises(ValueError,match='cannot select stimulation'):
        select_stimulation_frequency('10034','1',live,rhythm_key='bandit_decision_beta',estimate_file=path)


def test_legacy_discovery_never_substitutes(monkeypatch,tmp_path):
    # Compile the pure finder from the GUI module without requiring Tk on CI.
    import ast
    tree=ast.parse((ROOT/'code/calculate_theta_beta.py').read_text())
    func=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='find_input_files')
    env={'STIM_DATA_DIR':tmp_path,'BEHAVIOR_DATA_DIR':tmp_path}
    exec(compile(ast.Module(body=[func],type_ignores=[]),'legacy_finder','exec'),env)
    (tmp_path/'20200101000000_10034-1_SST_pre-stim.easy').touch()
    (tmp_path/'sub-10034-1_task-bandit_pre-stim_test.csv').touch()
    with pytest.raises(FileNotFoundError):env['find_input_files']('10034','1')
    eeg=tmp_path/'20200101000000_10034-1_Bandit_pre-stim.easy';eeg.touch()
    assert env['find_input_files']('10034','1')[0]==eeg
    (tmp_path/'20200102000000_10034-1_Bandit_pre-stim.easy').touch()
    with pytest.raises(FileNotFoundError):env['find_input_files']('10034','1')


def test_legacy_localizer_ambiguity_fails(tmp_path):
    from run_rhythm_estimation import _find_latest
    (tmp_path/'a.csv').touch();(tmp_path/'b.csv').touch()
    with pytest.raises(ValueError,match='Ambiguous'):_find_latest(tmp_path,['*.csv'])


def test_clock_residual_diagnostic(config):
    t=1_780_000_000+np.arange(5000)/500
    rows=pd.DataFrame({'response_onset_unix_time':(1_780_000_000+np.array([2,4,6],dtype=np.float64))*1000,
                       'response_onset_lsl_time':[2,4,6.5]})
    logs=[dict(eligible=True,event_sec=v/1000,event_column='response_onset_unix_time') for v in rows.response_onset_unix_time]
    with pytest.raises(InputError,match='clock_inconsistency') as exc:alignment_qc(logs,rows,t,config['preprocessing'])
    assert exc.value.diagnostics['unix_lsl_max_offset_residual_sec']>.4


def test_lsl_csv_input_requires_units_and_actual_samples(config,tmp_path):
    n=1000;names=['F3','FCz','F4'];stem='sub-10034_ses-1_run-01_task-bandit'
    eeg=tmp_path/(stem+'_eeg.csv');meta=tmp_path/(stem+'_metadata.json');events=tmp_path/(stem+'_events.tsv')
    pd.DataFrame({'lsl_timestamp':np.arange(n)/500,**{name:np.ones(n) for name in names}}).to_csv(eeg,index=False)
    pd.DataFrame({'subject_id':['sub-10034'],'session_id':['ses-1'],'choice':[1],'choice_onset_lsl_time':[1]}).to_csv(events,sep='\t',index=False)
    metadata=dict(sampling_rate_hz=500,channel_names=names,status='recorded',units='uV');meta.write_text(json.dumps(metadata))
    job=dict(subject='10034',session='1',task='bandit',phase='pre',run='01',clock_domain='lsl',
             eeg=eeg.name,events=events.name,metadata=meta.name,sha256={k:sha256(p) for k,p in [('eeg',eeg),('events',events),('metadata',meta)]})
    data,t,fs,got,rows,qc=load_pair(tmp_path,job,config['preprocessing'])
    assert data.shape==(1000,3) and got==names and fs==500
    del metadata['units'];meta.write_text(json.dumps(metadata));job['sha256']['metadata']=sha256(meta)
    with pytest.raises(InputError,match='amplitude_unit'):load_pair(tmp_path,job,config['preprocessing'])
    metadata['status']='no_samples';meta.write_text(json.dumps(metadata));job['sha256']['metadata']=sha256(meta)
    with pytest.raises(InputError,match='no_samples'):load_pair(tmp_path,job,config['preprocessing'])


def test_continuous_erd_through_preprocessing_and_epoching(config):
    from rhythm_validation_core import estimate
    rng=np.random.default_rng(91);fs=100
    names=['F3','Fp1','FCz','FT7','F4','P4','P3','EXT']
    n=60;t=np.arange((n+2)*6*fs)/fs
    raw=rng.normal(0,2,(len(t),len(names)))
    events=np.arange(1,n+1)*6
    phase=2*np.pi*21*t
    amp=np.ones(len(t))*5
    for event in events:amp[(t>=event-.55)&(t<=event+.25)]=.5
    raw[:,0]+=amp*np.sin(phase);raw[:,2]-=amp*np.sin(phase);raw[:,4]+=amp*np.cos(phase)
    clean,filtered,roi,refs,qc=preprocess(raw,fs,names,config['preprocessing'])
    logs=[dict(eligible=True,event_sec=float(x),reason='',retained=False) for x in events]
    result,_,_,_=estimate(clean,filtered,t,fs,names,roi,refs,logs,config['estimands']['response_beta_erd'],config)
    assert result['reliable'],result['failure_reasons']
    assert abs(result['individualized_frequency_hz']-21)<=.5


def test_secondary_no_peak_is_valid_json(config,tmp_path):
    from rhythm_validation_report import theta_secondary,write_json
    # Flat PSD is not a theta peak; Specparam uses NaN to encode empty parameters.
    from unittest.mock import patch
    class NoPeak:
        def __init__(self,**kwargs):pass
        def fit(self,*args):pass
        def get_params(self,key):return np.array([np.nan]*3) if key=='peak_params' else .8
    spec=config['estimands']['feedback_theta_enhancement']
    epochs,t,fs=synthetic_epochs(spec,6,n=4)
    with patch('specparam.SpectralModel',NoPeak):
        result=theta_secondary(epochs,t,fs,np.zeros((1000,1)),['F3'],{'F3':{'bad':False}},config['theta_secondary'])
    write_json(tmp_path/'result.json',result)
    assert result['feedback_specparam']['candidate_hz'] is None
    assert result['feedback_specparam']['peak_parameters']==[]


def test_legacy_auto_find_does_not_confuse_eeg_csv_with_events(tmp_path,monkeypatch):
    import run_rhythm_estimation as cli
    monkeypatch.setattr(cli,'_repo_root',lambda:tmp_path)
    subject=tmp_path/'data/sub-001';(subject/'eeg').mkdir(parents=True)
    events=subject/'sub-001_ses-1_run-localizer_task-SST_2026-01-01_events.csv';events.touch()
    eeg=subject/'eeg/sub-001_ses-1_run-localizer_task-SST_eeg.csv';eeg.touch()
    assert cli._auto_find_inputs('001','1','sst')==(events,eeg)
    # A different session and task must not be used as a fallback.
    assert cli._auto_find_inputs('001','2','sst')==(None,None)
    assert cli._auto_find_inputs('001','1','bandit')==(None,None)
