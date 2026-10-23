#!/usr/bin/env python3
"""Development then locked new held-out validation of carrier-first v1.2.

Simulation recovery is conditional evidence, not clinical/tACS validation. The
held-out set has new seeds, off-grid frequencies, native 500-Hz sampling, AR
trial gains and mixed colored noise; it is not the previously inspected set.
"""
from __future__ import annotations
import argparse
import collections
import hashlib
import json
from pathlib import Path
import sys
import numpy as np
from scipy import signal
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'code'))
from rhythm_validation_core import spectra
from rhythm_validation_carrier import carrier_spectra, assess_carrier, temporal_carrier_spectra
KEYS=['response_beta_erd','stop_success_beta_enhancement','feedback_theta_enhancement']
CONTROLS=['noise','stationary','broadband','broadband_stationary','switch','boundary','transient','chirp','competing']


def cases(phase):
    offset=8100000 if phase=='development' else 9700000
    reps=1 if phase=='development' else 3
    serial=0
    for key in KEYS:
        theta=key.startswith('feedback')
        frequencies=([5,6,7] if theta else [17,21,26]) if phase=='development' else ([5.35,6.65] if theta else [18.35,24.65])
        for strength,amplitude in [('weak',1.3),('moderate',2),('strong',5)]:
            for f in frequencies:
                for rep in range(reps):
                    serial+=1
                    yield dict(estimand=key,scenario='known',strength=strength,amplitude=amplitude,frequency_hz=f,seed=offset+serial,n_trials=[40,80,120][rep],rep=rep)
        for scenario in CONTROLS:
            for rep in range(reps):
                serial+=1
                yield dict(estimand=key,scenario=scenario,strength=None,amplitude=5,frequency_hz=6 if theta else 21,seed=offset+serial,n_trials=[40,80,120][rep],rep=rep)


def generate(spec,c,phase):
    rng=np.random.default_rng(c['seed']); fs=250 if phase=='development' else 500
    n=c['n_trials'];t=np.arange(round(np.diff(spec['epoch_sec'])[0]*fs))/fs+spec['epoch_sec'][0]
    noise=rng.normal(size=(n,3,len(t)));f=np.fft.rfftfreq(len(t),1/fs)
    exponent=[0,.8,1.6][c['rep']]
    weights=np.maximum(f,.5)**(-exponent/2); weights[0]=0
    noise=np.fft.irfft(np.fft.rfft(noise,axis=-1)*weights,n=len(t),axis=-1)
    noise*=2/np.std(noise,axis=-1,keepdims=True)
    if phase=='heldout': noise+=rng.normal(0,.25,noise.shape)
    lo,hi=spec['analysis_sec'];smooth=.04 if phase=='development' else .065
    env=.5*(np.tanh((t-lo+.12)/smooth)-np.tanh((t-hi-.12)/smooth))
    scenario=c['scenario'];theta=spec['band_hz'][1]==8
    if scenario in ('broadband','broadband_stationary'):
        noise*=1+((.35 if spec['direction']<0 else 3)-1)*env
    if scenario not in ('noise','broadband','transient'):
        freq=np.full(n,c['frequency_hz'])
        if scenario=='switch':freq[:n//2]=5 if theta else 17;freq[n//2:]=7 if theta else 26
        if scenario=='boundary':freq[:]=spec['band_hz'][0]
        if phase=='heldout' and scenario=='known':freq+=rng.normal(0,.06 if theta else .12,n)
        phase0=rng.uniform(-np.pi,np.pi,(n,1));angle=2*np.pi*freq[:,None]*t+phase0
        if scenario=='chirp':angle+=np.pi*(2 if theta else 9)*(t-lo)**2
        wave=np.sin(angle)
        if scenario=='competing':wave=np.sin(2*np.pi*(5 if theta else 17)*t+phase0)+np.sin(2*np.pi*(7 if theta else 26)*t-phase0)
        high=c['amplitude'];amp=1+(high-1)*(1-env if spec['direction']<0 else env)
        if scenario in ('stationary','broadband_stationary'):amp=np.full(len(t),5.)
        noise+=wave[:,None,:]*amp[None,None,:]*np.array([1,-1,.6])[None,:,None]
    if scenario=='transient':
        pulse=12*np.exp(-.5*((t-np.mean(spec['analysis_sec']))/rng.uniform(.025,.075,(n,1)))**2)
        noise+=pulse[:,None,:]*np.array([1,-.6,.8])[None,:,None]
    gain=rng.normal(0,.4,n)
    if phase=='heldout':gain=signal.lfilter([1],[1,-.55],gain)
    return noise*np.exp(gain)[:,None,None],t,fs


def hashes():
    paths=[Path(__file__),ROOT/'code/rhythm_validation_core.py',ROOT/'code/rhythm_validation_carrier.py',ROOT/'code/rhythm_validation_config.json']
    return {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def quantify(ep,t,fs,spec,cfg):
    f,trials,b,a,_,_=spectra(ep,t,fs,spec)
    pf,psd=carrier_spectra(ep,fs,spec)
    return assess_carrier(f,trials,b,a,pf,psd,spec,cfg,len(ep),ep.shape[1],temporal=temporal_carrier_spectra(ep,fs,spec))


def run(phase,out,lock):
    if phase=='heldout' and (not lock or json.loads(lock.read_text())['source_sha256']!=hashes()):
        raise ValueError('Held-out validation requires an unchanged development lock')
    source_hashes=hashes()
    out.mkdir(parents=True,exist_ok=False)
    cfg=json.loads((ROOT/'code/rhythm_validation_config.json').read_text());records=[]
    for i,c in enumerate(cases(phase)):
        spec=cfg['estimands'][c['estimand']];ep,t,fs=generate(spec,c,phase);r=quantify(ep,t,fs,spec,cfg)
        error=abs(r['candidate_hz']-c['frequency_hz']) if c['scenario']=='known' and r['candidate_hz'] is not None else None
        records.append(dict(**c,fs=fs,candidate_hz=r['candidate_hz'],frequency_error_hz=error,reliable=r['reliable'],failure_reasons=r['failure_reasons'],effect_db=r['effect_db'],selective_modulation_fraction=r['selective_modulation_fraction'],width_hz=r['width_hz']))
        print(i+1,c['estimand'],c['scenario'],c['strength'],r['candidate_hz'],r['reliable'],r['failure_reasons'],flush=True)
    groups=collections.defaultdict(list)
    for r in records:groups[(r['scenario'],r['strength'])].append(r)
    summary=[dict(scenario=k[0],strength=k[1],datasets=len(rr),accepted=sum(r['reliable'] for r in rr),correct_location=sum(r['frequency_error_hz'] is not None and r['frequency_error_hz']<=(.5 if r['estimand'].startswith('feedback') else 1) for r in rr)) for k,rr in groups.items()]
    known=[r for r in records if r['scenario']=='known'];controls=[r for r in records if r['scenario']!='known'];ms=[r for r in known if r['strength']!='weak']
    wrong=[r for r in known if r['reliable'] and (r['frequency_error_hz'] is None or r['frequency_error_hz']>(.5 if r['estimand'].startswith('feedback') else 1))]
    decision=dict(criteria='>=85% moderate/strong accepted; no wrong accepted known frequencies; <=5% unsuitable controls accepted',moderate_strong_acceptance=sum(r['reliable'] for r in ms)/len(ms),wrong_accepted_known=len(wrong),control_acceptance=sum(r['reliable'] for r in controls)/len(controls))
    decision['passed']=decision['moderate_strong_acceptance']>=.85 and not wrong and decision['control_acceptance']<=.05
    if source_hashes != hashes(): raise ValueError('Source changed during validation; discard run')
    payload=dict(phase=phase,source_sha256=source_hashes,summary=summary,decision=decision,records=records)
    (out/'results.json').write_text(json.dumps(payload,indent=2,allow_nan=False)+'\n')
    if phase=='development':(out/'lock.json').write_text(json.dumps(dict(source_sha256=hashes(),heldout_cases=list(cases('heldout')),criteria=decision['criteria']),indent=2)+'\n')
    print(json.dumps(dict(summary=summary,decision=decision),indent=2),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('phase',choices=['development','heldout']);p.add_argument('--out',type=Path,required=True);p.add_argument('--lock',type=Path);a=p.parse_args();run(a.phase,a.out,a.lock)
