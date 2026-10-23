"""Focused normalization sensitivity check. No production modifications."""
import sys,json,importlib.util,hashlib,argparse
from pathlib import Path
import numpy as np
from scipy import signal
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--repo',type=Path,required=True);parser.add_argument('--out',type=Path,required=True)
args=parser.parse_args();root=args.repo.resolve();dest=args.out.resolve()
if dest.exists():raise FileExistsError(dest)
dest.parent.mkdir(parents=True,exist_ok=True)
sys.path.insert(0,str(root/'code'))
import rhythm_validation_io as io
import rhythm_validation_core as core
cfg=json.loads((root/'code/rhythm_validation_config.json').read_text());sp=cfg['estimands']['response_beta_erd']
job=next(j for j in json.loads((root/'validation/pilot_manifest.json').read_text())['jobs'] if j['id']=='10034_ses-1_bandit_pre_20260918104411')
raw,t,fs,names,rows,clock=io.load_pair(root,job,cfg['preprocessing'])
clean,filtered,roi,refs,cq=core.preprocess(raw,fs,names,cfg['preprocessing'])
logs=io.select_events(rows,'bandit','response_beta_erd','unix',job);io.alignment_qc(logs,rows,t,cfg['preprocessing'])
epochs,times,logs=core.epoch_data(clean,filtered,t,fs,names,roi,refs,logs,sp,cfg['preprocessing'])
freqs=np.arange(8,40.25,.5);bm=core.mask(times,sp['baseline_sec']);am=core.mask(times,sp['analysis_sec'])

def calculate(ep):
 old=[];new=[];base=[];gap=[];baseline_old=[]
 for f in freqs:
  sig=sp['cycles']/(2*np.pi*f);h=int(np.ceil(5*sig*fs));wt=np.arange(-h,h+1)/fs
  wav=(np.exp(2j*np.pi*f*wt)-np.exp(-sp['cycles']**2/2))*np.exp(-wt**2/(2*sig**2));wav/=np.sqrt(np.sum(np.abs(wav)**2))
  power=(np.abs(signal.fftconvolve(ep,wav[None,None,:],mode='same',axes=-1))**2).mean(1)
  b=power[:,bm].mean(1);lp=10*np.log10(np.maximum(power,1e-30));logb=10*np.log10(np.maximum(b,1e-30));meanlogb=lp[:,bm].mean(1)
  old.append(lp[:,am].mean(1)-logb);new.append(lp[:,am].mean(1)-meanlogb);base.append(b);gap.append(logb-meanlogb);baseline_old.append(meanlogb-logb)
 return {k:np.stack(v,axis=1) for k,v in [('logratio',old),('meanlogratio',new),('baseline',base),('jensen_gap',gap),('logratio_baseline_mean',baseline_old)]}
actual=calculate(epochs);band=(freqs>=13)&(freqs<=30)
res={}
for method in ['logratio','meanlogratio']:
 assessed=core.assess(freqs,actual[method],actual['baseline'],sp,cfg,len(rows),len(roi))
 res[method]=assessed
 print(method,assessed['candidate_hz'],assessed['effect_db'],assessed['qc'],assessed['failure_reasons'],flush=True)
# Independent synthetic stationary white EEG; no response-locked change at any frequency.
# Frequency and amplitude here are arbitrary units: this tests baseline arithmetic,
# not the physiological realism of white noise or the full acquisition pipeline.
rng=np.random.default_rng(112358)
stationary=rng.normal(size=(1000,3,len(times)))
null=calculate(stationary)
summary={}
for method in ['logratio','meanlogratio']:
 avg=null[method].mean(0);s=avg[band]
 summary[method]=dict(band_mean_db=float(s.mean()),minimum_db=float(s.min()),maximum_db=float(s.max()),mean_spectrum_db=avg.tolist(),trial_sem_db=(null[method].std(0,ddof=1)/np.sqrt(len(stationary))).tolist())
 print('Stationary control',method,summary[method]['band_mean_db'],summary[method]['minimum_db'],summary[method]['maximum_db'],flush=True)
payload=dict(recording_id=job['id'],n_retained=len(epochs),settings=sp,actual_results=res,frequencies_hz=freqs.tolist(),actual_spectra={k:v.mean(0).tolist() for k,v in actual.items()},stationary_control=dict(seed=112358,n_trials=1000,n_channels=3,model='Independent stationary Gaussian white noise, no event-related change; arithmetic/transform check, not calibrated EEG false-positive rate.',results=summary),input_sha256=job['sha256'],source_sha256={name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in ['code/rhythm_validation_core.py','code/rhythm_validation_io.py','code/rhythm_validation_config.json']})
payload['experiment_sha256']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
assert res['logratio']['candidate_hz']==23 and abs(res['logratio']['effect_db']+0.7534834295025061)<1e-10
assert abs(summary['meanlogratio']['band_mean_db'])<0.02
assert summary['logratio']['band_mean_db'] < -0.4
with dest.open('x') as fh:fh.write(json.dumps(payload,indent=2)+'\n')
