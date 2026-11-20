"""Time-domain carrier recovery and separation of spectral and effect failures."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import numpy as np
import pytest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'code'))
from rhythm_validation_carrier import carrier_spectra, locate, assess_carrier
from rhythm_validation_core import spectra
sp=importlib.util.spec_from_file_location('carrier_validation',ROOT/'validation/experiments/validate_carrier_estimator.py')
exp=importlib.util.module_from_spec(sp);sp.loader.exec_module(exp)


def config():return json.loads((ROOT/'code/rhythm_validation_config.json').read_text())


@pytest.mark.parametrize('key,freq',[('response_beta_erd',21),('stop_success_beta_enhancement',21),('feedback_theta_enhancement',6),('feedback_theta_enhancement',7)])
def test_high_snr_native_rate_carrier_recovery(key,freq):
    cfg=config();cfg['reliability']['bootstrap_iterations']=30;spec=cfg['estimands'][key]
    fs=500;t=np.arange(round(np.diff(spec['epoch_sec'])[0]*fs))/fs+spec['epoch_sec'][0]
    rng=np.random.default_rng(111);start,end=spec['analysis_sec']
    env=.5*(np.tanh((t-start+.12)/.04)-np.tanh((t-end-.12)/.04))
    amp=2.5+7.5*(1-env if spec['direction']<0 else env)
    wave=amp*np.sin(2*np.pi*freq*t+rng.uniform(-np.pi,np.pi,(60,1)))
    ep=rng.normal(size=(60,3,len(t)))+wave[:,None,:]*np.array([1,-1,.6])[None,:,None]
    original=ep.copy();r=exp.quantify(ep,t,fs,spec,cfg)
    np.testing.assert_array_equal(ep,original)
    assert abs(r['candidate_hz']-freq)<.15
    assert r['reliable'],r['failure_reasons']
    assert r['approved_stimulation_frequency_hz'] is None


@pytest.mark.parametrize('scenario',['stationary','broadband_stationary','switch','competing','chirp','boundary','noise'])
def test_unsuitable_time_domain_controls_not_accepted(scenario):
    cfg=config();cfg['reliability']['bootstrap_iterations']=30;spec=cfg['estimands']['response_beta_erd']
    case=dict(scenario=scenario,seed=221,n_trials=60,rep=1,frequency_hz=21,amplitude=5)
    ep,t,fs=exp.generate(spec,case,'development');r=exp.quantify(ep,t,fs,spec,cfg)
    assert not r['reliable'],r
    assert not r['data_adequacy_reasons']
    assert r['target_identifiability_reasons']
    if r['candidate_hz'] is None:
        for label, split in r['splits'].items():
            if split['difference_hz'] is None:
                assert label+'_carrier_frequency_unstable' not in r['failure_reasons']


def test_frequency_choice_does_not_follow_contrast_extremum():
    cfg=config();spec=cfg['estimands']['response_beta_erd'];cfg['reliability']['bootstrap_iterations']=10
    f=np.arange(8,40.5,.5);pf=np.arange(8,40,.25)
    psd=np.tile(.1+10*np.exp(-.5*((pf-21)/.35)**2),(60,1))
    base=np.tile(1+10*np.exp(-.5*((f-21)/2)**2),(60,1));active=base*.25
    # Arbitrary relative-change extremum at 17 Hz must not move the carrier.
    trials=np.tile(-3-2*np.exp(-.5*((f-17)/2)**2),(60,1))
    r=assess_carrier(f,trials,base,active,pf,psd,spec,cfg,60,3,temporal=[(pf,psd),(pf,psd)])
    assert abs(r['candidate_hz']-21)<.05
    assert r['reliable']


def test_empty_data_has_no_frequency():
    cfg=config();spec=cfg['estimands']['response_beta_erd'];t=np.arange(1900)/500-2.2
    ep=np.empty((0,3,len(t)));r=exp.quantify(ep,t,500,spec,cfg)
    assert r['candidate_hz'] is None and not r['reliable']
    assert 'insufficient_epochs' in r['data_adequacy_reasons']


def test_new_heldout_cases_are_disjoint_and_frozen(tmp_path):
    dev=list(exp.cases('development'));held=list(exp.cases('heldout'))
    assert len(dev)==54 and len(held)==135
    assert not {r['seed'] for r in dev}&{r['seed'] for r in held}
    assert not {r['frequency_hz'] for r in dev if r['scenario']=='known'}&{r['frequency_hz'] for r in held if r['scenario']=='known'}
    lock=tmp_path/'lock.json';lock.write_text('{"source_sha256":{}}')
    with pytest.raises(ValueError,match='unchanged development lock'): exp.run('heldout',tmp_path/'out',lock)
