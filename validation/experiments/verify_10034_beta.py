"""Independent checks of the two main forward interventions via legacy functions."""
import importlib.util,json,sys
from pathlib import Path
import numpy as np
root=Path(sys.argv[1]).resolve(); dest=Path(sys.argv[2]).resolve()
s=importlib.util.spec_from_file_location('old',root/'pilot_data/frequency_analysis.py'); old=importlib.util.module_from_spec(s);s.loader.exec_module(old)
sys.path.insert(0,str(root/'code'));import rhythm_validation_io as vio
job=next(j for j in json.loads((root/'validation/pilot_manifest.json').read_text())['jobs'] if j['id']=='10034_ses-1_bandit_pre_20260918104411')
data,t=old.load_easy(root/job['eeg']);clean=old.preprocess(data,old.SRATE,list(range(7)))
rows=old.pd.read_csv(root/job['events']);events=old.get_event_times(rows,old.DECISION_EVENT_COL)
epochs,times=old.epoch_from_unix(clean,t,500,events,*old.DECISION_EPOCH,reject_ch_idx=list(range(7)))
ref=json.loads((dest/'comparison.json').read_text());results={r['label']:r for r in ref['results']}
old.DECISION_ANALYSIS=(-.4,.1)
freq,effect,edge=old.beta_analysis(epochs,times,500,[0,2,4])
assert freq==results['Historical + analysis_window']['frequency_hz']
assert abs(effect-results['Historical + analysis_window']['effect_db'])<1e-10
print('Independent original-code analysis-window check:',freq,effect,flush=True)
old.DECISION_ANALYSIS=(-1.,-.1)
active=(times>=-1)&(times<=-.1)
trial_spectra=[]; ratios=[]; baseline=[]
# Using the original functions on each individual trial moves baseline correction
# before the trial average without using the comparison harness's convolution.
for epoch in epochs:
 power=old.morlet_tfr(epoch[None,:,:],500,old.DECISION_FREQS,ch_idx=[0,2,4])
 db=old.baseline_correct_db(power,times,old.DECISION_BASELINE)
 trial_spectra.append(db[:,active].mean(1))
 bm=(times>=-1.5)&(times<=-1)
 bp=power[:,bm].mean(1)
 baseline.append(bp)
 ratios.append(power[:,active]/np.maximum(bp[:,None],1e-30))
freq2,effect2,edge2=old.find_peak(old.DECISION_FREQS,np.mean(trial_spectra,axis=0),mode='min')
assert freq2==results['Historical + trialwise_db']['frequency_hz']
assert abs(effect2-results['Historical + trialwise_db']['effect_db'])<1e-10
print('Independent original-code trialwise-dB check:',freq2,effect2,flush=True)
# Optional decomposition: normalize trials first, then average linear ratios
# before taking dB, separating normalization order from log averaging.
intermediate=(10*np.log10(np.maximum(np.mean(ratios,axis=0),1e-30))).mean(1)
freq3,effect3,edge3=old.find_peak(old.DECISION_FREQS,intermediate,mode='min')
print('Intermediate equal-trial linear ratios then dB:',freq3,effect3,flush=True)
verification=dict(analysis_window_only=dict(frequency_hz=freq,effect_db=effect),trialwise_db_only=dict(frequency_hz=freq2,effect_db=effect2),equal_trial_ratios_then_db=dict(frequency_hz=freq3,effect_db=effect3),method='Original morlet_tfr, baseline_correct_db, beta_analysis and find_peak functions; no comparison-harness transforms used.',tolerance_db=1e-10)
(dest/'independent_verification.json').write_text(json.dumps(verification,indent=2)+'\n')
