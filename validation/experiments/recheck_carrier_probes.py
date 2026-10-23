#!/usr/bin/env python3
"""Rerun the exact prior 132 additive probes with the frozen v1.2 estimator.

Conditional on unchanged retained epochs: this is a regression on previously
seen data, not the independent held-out validation, and not raw-data QC.
"""
import argparse
import collections
import hashlib
import json
from pathlib import Path
import sys
import numpy as np
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'code'))
from rhythm_validation_core import epoch_data, preprocess
from rhythm_validation_io import load_pair, select_events, alignment_qc
from diagnose_data_vs_method import probe_epochs
from validate_carrier_estimator import quantify, hashes


def run(out,lock):
    if json.loads(lock.read_text())['source_sha256'] != hashes():raise ValueError('Estimator changed after lock')
    out.mkdir(parents=True,exist_ok=False)
    cfg=json.loads((ROOT/'code/rhythm_validation_config.json').read_text())
    prior=json.loads((ROOT/'validation/data_method_diagnosis/diagnostics.json').read_text())
    manifest=json.loads((ROOT/'validation/pilot_manifest.json').read_text());jobs={j['id']:j for j in manifest['jobs']}
    groups=collections.defaultdict(list)
    for p in prior['probes']:groups[(p['recording_id'],p['estimand'])].append(p)
    records=[]
    for (recording,key),pp in groups.items():
        job=jobs[recording];raw,t,fs,names,rows,_=load_pair(ROOT,job,cfg['preprocessing'])
        clean,filtered,roi,refs,_=preprocess(raw,fs,names,cfg['preprocessing'])
        logs=select_events(rows,job['task'],key,job['clock_domain'],job)
        alignment_qc(logs,rows,t,cfg['preprocessing']);spec=cfg['estimands'][key]
        ep,times,_=epoch_data(clean,filtered,t,fs,names,roi,refs,logs,spec,cfg['preprocessing'])
        for old in pp:
            assert len(ep)==old['n_trials'] and fs==old['sampling_hz']
            probe=probe_epochs(times,len(ep),len(roi),spec,old['true_frequency_hz'],old['high_peak_amplitude_uv'],old['seed'])
            values=ep+probe if old['background']=='retained_real_eeg' else np.random.default_rng(old['seed']+1).normal(0,1,ep.shape)+probe
            r=quantify(values,times,fs,spec,cfg)
            error=abs(r['candidate_hz']-old['true_frequency_hz']) if r['candidate_hz'] is not None else None
            recovered=error is not None and error<=old['tolerance_hz'] and r['effect_db']*spec['direction']>0
            records.append(dict(**{k:old[k] for k in ['recording_id','estimand','background','true_frequency_hz','high_peak_amplitude_uv','seed','n_trials','sampling_hz','tolerance_hz']},frequency_error_hz=error,recovered_frequency_and_direction=recovered,
                previous_recovered=old['recovered_frequency_and_direction'],previous_accepted=old['reliable'],**r))
        print(recording,key,len(pp),'probes complete',flush=True)
    summary=[]
    for b in ['clean_1uv_noise','retained_real_eeg']:
        rr=[r for r in records if r['background']==b]
        summary.append(dict(background=b,datasets=len(rr),recovered=sum(r['recovered_frequency_and_direction'] for r in rr),accepted=sum(r['reliable'] for r in rr),wrong_accepted=sum(r['reliable'] and not r['recovered_frequency_and_direction'] for r in rr),previous_recovered=sum(r['previous_recovered'] for r in rr),correct_recovery_rejected=sum(r['recovered_frequency_and_direction'] and not r['reliable'] for r in rr)))
    payload=dict(source_sha256={**hashes(),str(Path(__file__).relative_to(ROOT)):hashlib.sha256(Path(__file__).read_bytes()).hexdigest()},summary=summary,records=records,interpretation='Previously inspected post-preprocessing additive probes; recovery at injected amplitude cannot prove native peaks or validate acquisition. Acceptance here uses n_eligible=n_retained to isolate estimation; original pilot retention gates are applied separately.')
    (out/'probes.json').write_text(json.dumps(payload,indent=2,allow_nan=False)+'\n');print(json.dumps(summary,indent=2),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,required=True);p.add_argument('--lock',type=Path,required=True);a=p.parse_args();run(a.out,a.lock)
