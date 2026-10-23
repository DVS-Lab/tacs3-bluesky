#!/usr/bin/env python3
"""Seeded transform/estimator checks; not empirical individualization validation.

python validation/experiments/validate_meanlogratio.py --out NEW.json
Uses the repository's frozen config without tuning thresholds to outcomes.
"""
import argparse,hashlib,json,sys,platform
from pathlib import Path
import numpy as np
import scipy
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'code'))
from rhythm_validation_core import spectra,assess,POWER_NORMALIZATION
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--out',type=Path,required=True)
args=parser.parse_args()
if args.out.exists():raise FileExistsError(args.out)
cfg=json.loads((ROOT/'code/rhythm_validation_config.json').read_text())
fs=100;n=120

def generate(spec,scenario,seed,noise_kind='pink',frequency=None):
 rng=np.random.default_rng(seed)
 t=np.arange(round(np.diff(spec['epoch_sec'])[0]*fs))/fs+spec['epoch_sec'][0]
 noise=rng.normal(size=(n,3,len(t)))
 if noise_kind=='pink':
  bins=np.fft.rfftfreq(len(t),1/fs)
  weights=1/np.sqrt(np.maximum(bins,.5));weights[0]=0
  noise=np.fft.irfft(np.fft.rfft(noise,axis=-1)*weights,n=len(t),axis=-1)
 noise=noise/np.std(noise,axis=-1,keepdims=True)*2
 gains=rng.lognormal(0,.7,(n,1,1))
 active=(t>=spec['analysis_sec'][0]-.12)&(t<=spec['analysis_sec'][1]+.12)
 center=6 if spec['band_hz'][1]==8 else 21
 if scenario=='broadband_change':
  noise*=np.where(active,.3 if spec['direction']<0 else 3,1)
 if scenario in ['known','stationary_peak','unstable_peak']:
  f=np.full(n,frequency or center,dtype=float)
  if scenario=='unstable_peak':
   f[:n//2]=5 if center==6 else 17
   f[n//2:]=7 if center==6 else 26
  phase=rng.uniform(-np.pi,np.pi,(n,1))
  wave=np.sin(2*np.pi*f[:,None]*t[None,:]+phase)
  amp=np.full(len(t),5.) if scenario=='stationary_peak' else (np.where(active,1,8) if spec['direction']<0 else np.where(active,8,1))
  noise+=wave[:,None,:]*amp[None,None,:]*np.array([1,-1,.6])[None,:,None]
 return noise*gains,t

results=[]
keys=['response_beta_erd','stop_success_beta_enhancement','feedback_theta_enhancement']
for key in keys:
 spec=cfg['estimands'][key]
 frequencies=[5,6,7] if key.startswith('feedback') else [17,21,26]
 cases=[]
 for freq in frequencies:
  for noise in ['white','pink']:
   for seed in range(4):cases.append(('known',noise,freq,10000+seed))
 for scenario in ['stationary_noise','stationary_peak','broadband_change','unstable_peak']:
  noises=['white','pink'] if scenario=='stationary_noise' else ['pink']
  for noise in noises:
   for seed in range(6):cases.append((scenario,noise,None,20000+seed))
 for scenario,noise,freq,seed in cases:
  ep,t=generate(spec,scenario,seed,noise,freq)
  f,trials,base,active,_,_=spectra(ep,t,fs,spec)
  assessed=assess(f,trials,base if spec['direction']<0 else active,spec,cfg,n,3)
  band=(f>=spec['band_hz'][0])&(f<=spec['band_hz'][1])
  record=dict(estimand=key,scenario=scenario,noise=noise,seed=seed,true_frequency_hz=freq,
              band_mean_effect_db=float(trials[:,band].mean()),**assessed)
  if freq is not None:record['absolute_frequency_error_hz']=abs(assessed['candidate_hz']-freq) if assessed['candidate_hz'] is not None else None
  results.append(record)
 print(key,'completed',len(cases),'datasets;',sum(r['reliable'] for r in results if r['estimand']==key),'accepted',flush=True)
summary=[]
for key in keys:
 for scenario in ['known','stationary_noise','stationary_peak','broadband_change','unstable_peak']:
  rr=[r for r in results if r['estimand']==key and r['scenario']==scenario]
  summary.append(dict(estimand=key,scenario=scenario,datasets=len(rr),accepted=sum(r['reliable'] for r in rr),
                      max_frequency_error_hz=max((r.get('absolute_frequency_error_hz') or 0 for r in rr)) if scenario=='known' else None,
                      mean_band_effect_db=float(np.mean([r['band_mean_effect_db'] for r in rr]))))
payload=dict(analysis_version=cfg['analysis_version'],power_normalization=POWER_NORMALIZATION,
             n_trials_per_dataset=n,sampling_hz=fs,limitations='Epoched synthetic inputs; does not test acquisition or calibrate empirical sensitivity/specificity. White/pink backgrounds, opposite channel phases, lognormal trial gains, strong injected sinusoids, fixed seeds. 100 Hz is the synthetic sampling rate; pilot runs use native 500 Hz.',
             summary=summary,results=results,config=cfg,python=platform.python_version(),numpy=np.__version__,scipy=scipy.__version__,
             source_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [ROOT/'code/rhythm_validation_core.py',ROOT/'code/rhythm_validation_config.json',Path(__file__)]})
args.out.parent.mkdir(parents=True,exist_ok=True)
with args.out.open('x') as fh:json.dump(payload,fh,indent=2);fh.write('\n')
print(json.dumps(summary,indent=2),flush=True)
