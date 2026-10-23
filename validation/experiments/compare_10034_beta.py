#!/usr/bin/env python3
"""Controlled offline comparison of 10034 Bandit pre beta minima.

Run with the repository's pinned validation environment:
python compare_10034.py --repo /path/to/tacs3-bluesky --out /new/output/folder
No source data, production configuration, or stimulation files are modified.
"""
import argparse, copy, hashlib, importlib.util, itertools, json, platform, sys, time
from pathlib import Path
import numpy as np
from scipy import signal
from scipy.ndimage import gaussian_filter1d

p=argparse.ArgumentParser()
p.add_argument('--repo',type=Path,required=True)
p.add_argument('--out',type=Path,required=True)
a=p.parse_args(); root=a.repo.resolve(); out=a.out.resolve(); out.mkdir(parents=True,exist_ok=False)
sys.path.insert(0,str(root/'code'))
import rhythm_validation_io as vio
import rhythm_validation_core as core
loader=importlib.util.spec_from_file_location('historical',root/'pilot_data/frequency_analysis.py')
old=importlib.util.module_from_spec(loader);loader.loader.exec_module(old)
cfg=json.loads((root/'code/rhythm_validation_config.json').read_text())
job=next(j for j in json.loads((root/'validation/pilot_manifest.json').read_text())['jobs'] if j['id']=='10034_ses-1_bandit_pre_20260918104411')
spec=cfg['estimands']['response_beta_erd']
raw,t,fs,names,rows,clock=vio.load_pair(root,job,cfg['preprocessing'])
old_raw,t_ms=old.load_easy(root/job['eeg'])
np.testing.assert_array_equal(raw,old_raw)
old_clean=old.preprocess(raw,fs,list(range(7)))
ms=old.get_event_times(rows,old.DECISION_EVENT_COL)
old_epochs,old_times=old.epoch_from_unix(old_clean,t_ms,fs,ms,*old.DECISION_EPOCH,reject_ch_idx=list(range(7)))
old_ids=[]; old_centers=[]
for i,event in enumerate(ms):
 ep,_=old.epoch_from_unix(old_clean,t_ms,fs,[event],*old.DECISION_EPOCH,reject_ch_idx=list(range(7)))
 if len(ep): old_ids.append(i+1);old_centers.append(old.nearest_sample_index(t_ms,event))
old_result=old.beta_analysis(old_epochs,old_times,fs,[0,2,4])
clean,filtered,roi,refs,channels=core.preprocess(raw,fs,names,cfg['preprocessing'])
logs=vio.select_events(rows,'bandit','response_beta_erd','unix',job)
alignment=vio.alignment_qc(logs,rows,t,cfg['preprocessing'])
new_result,arrays,new_epochs,new_times=core.estimate(clean,filtered,t,fs,names,roi,refs,logs,spec,cfg)
new_ids=[x['row'] for x in logs if x['retained']]
new_centers=[]
for x in logs:
 if not x['retained']: continue
 k=min(int(np.searchsorted(t,x['event_sec'])),len(t)-1)
 if k and abs(t[k-1]-x['event_sec'])<abs(t[k]-x['event_sec']):k-=1
 new_centers.append(k)
assert old_ids==new_ids,'Trial identities differ: use intersection and report full/native results separately.'
assert old_centers==new_centers,'Sample alignment differs; add it as a factor.'
assert [names[i] for i in roi]==['F3','FCz','F4']
assert old_result[0]==13 and new_result['candidate_hz']==23
saved=json.loads((root/'validation/pilot_results'/job['id']/'response_beta_erd/result.json').read_text())
for field in ['candidate_hz','effect_db','failure_reasons','bootstrap_detection_fraction','n_retained']:
 assert new_result[field]==saved[field],field
print('Native endpoints:',old_result,'new',new_result['candidate_hz'],new_result['effect_db'],flush=True)
print('Matched trial identities and samples:',len(old_ids),'excluded',[i for i in range(1,len(rows)+1) if i not in old_ids],flush=True)

# Each factor is 0 for the historical choice and 1 for the revised choice.
# Artifacts/event eligibility do not alter this recording's retained set; it is
# frozen below to isolate numerical effects, not retuned for each hybrid.
factors=['baseline_window','analysis_window','epoch_padding','trialwise_db','reference','cycles','wavelet_support','detrend','highpass','notch','filter_form','zero_mean','smoothing','window_endpoints']
legacy={f:0 for f in factors}; revised={f:1 for f in factors}
base_windows=[(-1.5,-1.0),(-1.2,-0.7)]
active_windows=[(-1.0,-0.1),(-0.4,0.1)]
freqs=np.arange(13,30.25,.5)
# Frequencies outside 13-30 Hz do not affect its independently convolved bins.
# Full revised endpoint (8-40 Hz plus reliability gates) is checked above.
cache={}; filtered_cache={}; records=[]; start_time=time.monotonic()
spectral_keys=[f for f in factors if f not in ['baseline_window','analysis_window','trialwise_db','smoothing','window_endpoints']]

def spectra_for(c):
 key=tuple(c[k] for k in spectral_keys)
 if key in cache:return cache[key]
 filter_key=tuple(c[k] for k in ['highpass','notch','filter_form'])
 if filter_key not in filtered_cache:
  hp=1 if c['highpass'] else .5
  if c['filter_form']:
   sos=signal.butter(4,[hp,45],btype='bandpass',fs=fs,output='sos'); data=signal.sosfiltfilt(sos,raw,axis=0)
  else:
   b,aa=signal.butter(4,[hp/(fs/2),45/(fs/2)],btype='band'); data=signal.filtfilt(b,aa,raw,axis=0)
  if not c['notch']:
   b,aa=signal.iirnotch(60/(fs/2),Q=30);data=signal.filtfilt(b,aa,data,axis=0)
  filtered_cache[filter_key]=data
 data=filtered_cache[filter_key]
 reference=refs if c['reference'] else list(range(7))
 data=data-data[:,reference].mean(1,keepdims=True)
 limits=(-2.2,1.6) if c['epoch_padding'] else (-1.5,.5)
 n=round((limits[1]-limits[0])*fs); times=np.arange(n)/fs+limits[0]
 epochs=np.stack([data[k+round(limits[0]*fs):k+round(limits[0]*fs)+n,roi].T for k in old_centers])
 if not c['detrend']:epochs=signal.detrend(epochs,axis=-1,type='linear')
 ncycles=7 if c['cycles'] else 5; support=5 if c['wavelet_support'] else 3.5
 combos=list(itertools.product([0,1],repeat=4)) # baseline,active,trialwise_db,endpoints
 result={k:np.empty(len(freqs)) for k in combos}
 for j,f in enumerate(freqs):
  sigma=ncycles/(2*np.pi*f);h=int(np.ceil(support*sigma*fs));wt=np.arange(-h,h+1)/fs
  wav=(np.exp(2j*np.pi*f*wt)-(np.exp(-ncycles*ncycles/2) if c['zero_mean'] else 0))*np.exp(-wt*wt/(2*sigma*sigma))
  wav/=np.sqrt(np.sum(np.abs(wav)**2))
  power=np.abs(signal.fftconvolve(epochs,wav[None,None,:],mode='same',axes=-1))**2
  power=power.mean(axis=1)
  for baseline,active,trialwise,endpoints in combos:
   mask=core.mask if endpoints else lambda t,w:(t>=w[0])&(t<=w[1])
   bm=mask(times,base_windows[baseline]);am=mask(times,active_windows[active])
   if trialwise:
    bp=power[:,bm].mean(1)
    result[(baseline,active,trialwise,endpoints)][j]=(10*np.log10(np.maximum(power[:,am],1e-30)/np.maximum(bp[:,None],1e-30))).mean()
   else:
    grand=power.mean(0);bp=grand[bm].mean()
    result[(baseline,active,trialwise,endpoints)][j]=(10*np.log10(np.maximum(grand[am],1e-30)/max(bp,1e-30))).mean()
 cache[key]=result
 print('Calculated transform',len(cache),'elapsed',round(time.monotonic()-start_time,1),'s',flush=True)
 return result

def evaluate(label,c,group,factor=None):
 raw_spectrum=spectra_for(c)[tuple(c[k] for k in ['baseline_window','analysis_window','trialwise_db','window_endpoints'])]
 spectrum=raw_spectrum if c['smoothing'] else gaussian_filter1d(raw_spectrum,1)
 idx=int(np.argmin(spectrum))
 record=dict(label=label,group=group,factor=factor,settings=c.copy(),frequency_hz=float(freqs[idx]),effect_db=float(spectrum[idx]),spectrum_db=spectrum.tolist(),unsmoothed_spectrum_db=raw_spectrum.tolist())
 records.append(record)
 print(label,record['frequency_hz'],round(record['effect_db'],6),flush=True)
 return record

base=evaluate('Historical endpoint',legacy,'endpoint')
full=evaluate('Revised endpoint',revised,'endpoint')
assert abs(base['effect_db']-old_result[1])<1e-10
assert base['frequency_hz']==old_result[0]
band=(arrays['freqs']>=13)&(arrays['freqs']<=30)
np.testing.assert_allclose(full['spectrum_db'],arrays['trials'].mean(0)[band],atol=1e-10,rtol=0)
for f in factors:
 c=legacy.copy();c[f]=1;evaluate('Historical + '+f,c,'forward_one_change',f)
 c=revised.copy();c[f]=0;evaluate('Revised - '+f,c,'reverse_one_change',f)
# Two orders make path dependence explicit; an arbitrary sequence cannot allocate
# independent shares of the total shift to nonlinear frequency minima.
for order_name,order in [('timing_first',factors),('signal_first',['highpass','notch','filter_form','reference','detrend','cycles','wavelet_support','zero_mean','epoch_padding','baseline_window','analysis_window','trialwise_db','smoothing','window_endpoints'])]:
 c=legacy.copy()
 for f in order:
  c[f]=1;evaluate(order_name+' through '+f,c,'cumulative_'+order_name,f)
# Focused timing/normalization interaction grid with other factors at each endpoint.
for endpoint,c0 in [('historical',legacy),('revised',revised)]:
 for bits in itertools.product([0,1],repeat=4):
  c=c0.copy();c.update(zip(['baseline_window','analysis_window','epoch_padding','trialwise_db'],bits))
  evaluate(endpoint+' timing/normalization '+''.join(map(str,bits)),c,'factorial_'+endpoint)

payload=dict(recording_id=job['id'],repo=str(root),analysis='controlled_diagnostic_minima_not_individualized_frequencies',
 factors=factors,frequencies_hz=freqs.tolist(),native_historical=dict(frequency_hz=float(old_result[0]),effect_db=float(old_result[1]),n_retained=len(old_ids)),
 native_revised=new_result,retained_behavioral_rows=old_ids,retained_eeg_sample_indices=old_centers,
 excluded_behavioral_rows=[i for i in range(1,len(rows)+1) if i not in old_ids],
 event_logs=logs,channels=channels,results=records,
 provenance=dict(python=platform.python_version(),numpy=np.__version__,input_paths={k:job[k] for k in ['eeg','events','metadata']},input_sha256=job['sha256'],
 source_sha256={str(f):hashlib.sha256((root/f).read_bytes()).hexdigest() for f in ['pilot_data/frequency_analysis.py','code/rhythm_validation_core.py','code/rhythm_validation_io.py','code/rhythm_validation_config.json']},
 experiment_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()))
(out/'comparison.json').write_text(json.dumps(payload,indent=2)+'\n')
# A small plain-text log is convenient without spreadsheet software.
with (out/'comparison.txt').open('w') as fh:
 for r in records:fh.write(f"{r['label']}: {r['frequency_hz']:g} Hz, {r['effect_db']:+.6f} dB\n")
print('Outputs:',out,flush=True)
