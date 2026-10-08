"""Diagnostics and historical replay; no writes to experimental directories."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import signal

from rhythm_validation_core import mask
from rhythm_validation_io import number


def write_json(path, obj):
    Path(path).write_text(json.dumps(obj, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def plot_result(out, result, arrays, spec):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    f, trials = arrays['freqs'], arrays['trials']
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.1), layout='constrained')
    if len(trials):
        mean = trials.mean(0)
        se = trials.std(0, ddof=1) / np.sqrt(len(trials)) if len(trials)>1 else np.zeros(len(f))
        axes[0].plot(f, mean, color='#245b80')
        axes[0].fill_between(f, mean-se, mean+se, alpha=.18, color='#245b80', label='±1 trial SE (descriptive)')
        im = axes[1].pcolormesh(arrays['times'], f, arrays['tfr'], shading='auto', cmap='RdBu_r', vmin=-3, vmax=3)
        fig.colorbar(im, ax=axes[1], label='Power change (dB)')
    else:
        for ax in axes:
            ax.text(.5,.5,'No retained epochs',transform=ax.transAxes,ha='center')
    axes[0].axhline(0, color='gray', lw=.7)
    for edge in spec['band_hz']:
        axes[0].axvline(edge, color='gray', ls='--', lw=.8)
        axes[1].axhline(edge, color='gray', ls='--', lw=.8)
    candidate = result.get('candidate_hz')
    if candidate is not None:
        color = '#00845a' if result['reliable'] else '#b64232'
        axes[0].axvline(candidate, color=color, label=f"Candidate {candidate:g} Hz ({result['qc']})")
        axes[1].axhline(candidate, color=color)
    axes[1].axvline(0, color='black', lw=.8)
    for window,color in [(spec['baseline_sec'],'gray'), (spec['analysis_sec'],'gold')]:
        axes[1].axvspan(*window, color=color, alpha=.14)
    axes[0].set(xlabel='Frequency (Hz)', ylabel='Power change (dB)', title='Baseline-corrected spectrum')
    if len(trials):axes[0].legend(fontsize=7)
    axes[1].set(xlabel='Time from event (s)', ylabel='Frequency (Hz)', title='Time-frequency power')
    fig.suptitle(f"{result['subject']} · {result['task']} {result['phase']} · {result['estimand']}\n{result['n_retained']}/{result['n_eligible']} retained · {result['qc']}",fontsize=10)
    fig.savefig(out / 'spectra_tfr.png', dpi=130)
    plt.close(fig)


def plot_channels(out, qc):
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(7,3.5),layout='constrained')
    names=list(qc)
    ax.bar(names,[qc[n]['bad_window_fraction'] for n in names],color=['#b64232' if qc[n]['bad'] else '#245b80' for n in names])
    ax.set(ylabel='Fraction of flagged 2-second windows',ylim=(0,1),title='Channel QC before reference; Fp1 ocular only, EXT excluded')
    fig.savefig(out/'channel_qc.png',dpi=130);plt.close(fig)


def legacy_replay(root, job):
    """Replay committed Bandit algorithm; SST variants are explicitly hypothetical."""
    source=root/'pilot_data/frequency_analysis.py'
    module_spec=importlib.util.spec_from_file_location('legacy_pilot',source)
    legacy=importlib.util.module_from_spec(module_spec);module_spec.loader.exec_module(legacy)
    data,t=legacy.load_easy(root/job['eeg'])
    cleaned=legacy.preprocess(data,legacy.SRATE,ref_idx=list(range(7)))
    rows=pd.read_csv(root/job['events'],sep='\t' if job['events'].endswith('.tsv') else ',')
    modes=['bandit_original'] if job['task']=='bandit' else ['sst_all_responses_hypothesis','sst_correct_go_hypothesis']
    results=[]
    for mode in modes:
        col='choice_onset_unix_time' if job['task']=='bandit' else 'response_onset_unix_time'
        if col not in rows:
            results.append(dict(mode=mode,error='missing_unix_event_column'));continue
        subset=rows
        if mode=='sst_correct_go_hypothesis':
            subset=rows[(rows['stop']==0)&(rows['go_correct']==1)]
        events=pd.to_numeric(subset[col],errors='coerce').to_numpy()
        epochs,times=legacy.epoch_from_unix(cleaned,t,500,events,*legacy.DECISION_EPOCH,reject_ch_idx=list(range(7)))
        if len(epochs):
            freq,effect,edge=legacy.beta_analysis(epochs,times,500,[0,2,4])
        else:freq=effect=edge=None
        results.append(dict(mode=mode,n_events=int(np.isfinite(events).sum()),n_retained=len(epochs),
                            frequency_hz=freq,effect_db=effect,boundary=edge,
                            provenance='committed_bandit_algorithm' if job['task']=='bandit' else 'SST_algorithm_not_found_variant_is_not_provenance'))
    return results


def theta_secondary(epochs, times, fs, clean, names, channel_qc, cfg):
    """Keep modeled feedback theta and IAF-minus-5 as separate descriptive methods."""
    from specparam import SpectralModel
    result={'status':'descriptive_only_not_validated_for_stimulation'}
    def fitted_peak(freqs,psd,band):
        model=SpectralModel(peak_width_limits=cfg['peak_width_hz'],max_n_peaks=cfg['max_n_peaks'],
                            min_peak_height=cfg['min_peak_height_log10'],aperiodic_mode='fixed',verbose=False)
        model.fit(freqs,psd,cfg['fit_range_hz'])
        peaks=model.get_params('peak_params')
        selected=[p for p in np.atleast_2d(peaks) if band[0]<p[0]<band[1] and np.isfinite(p).all()]
        peak=max(selected,key=lambda p:p[1]) if selected else None
        return {'candidate_hz':float(peak[0]) if peak is not None else None,
                'reason':None if peak is not None else 'no_interior_modeled_peak',
                'r_squared':number(model.get_params('r_squared')),
                'peak_parameters':[p.tolist() for p in np.asarray(peaks).reshape(-1,3) if np.isfinite(p).all()]}
    if len(epochs):
        window=epochs[:,:,mask(times,cfg['feedback_window_sec'])]
        freqs,psd=signal.welch(window,fs=fs,nperseg=min(window.shape[-1],round(cfg['welch_seconds']*fs)),axis=-1)
        result['feedback_specparam']=fitted_peak(freqs,psd.mean(axis=(0,1)),[4,8])
        result['feedback_native_bin_spacing_hz']=float(freqs[1]-freqs[0])
    else:result['feedback_specparam']={'candidate_hz':None,'reason':'no_retained_feedback_epochs'}
    roi=[i for i,name in enumerate(names) if name in cfg['posterior_channels'] and not channel_qc[name]['bad']]
    if len(roi)<2:
        result['iaf_minus_5']={'candidate_hz':None,'reason':'insufficient_posterior_channels'}
    else:
        n=round(cfg['iaf_welch_seconds']*fs)
        windows=[clean[j:j+n,roi].T for j in range(0,len(clean)-n+1,n)]
        # Use only windows meeting the same amplitude/step limits.
        windows=[w for w in windows if np.ptp(w,axis=1).max()<=cfg['epoch_ptp_uv'] and abs(np.diff(w,axis=1)).max()<=cfg['step_uv']]
        if not windows:result['iaf_minus_5']={'candidate_hz':None,'reason':'no_clean_posterior_windows'}
        else:
            f,power=signal.welch(np.stack(windows),fs=fs,nperseg=n,axis=-1)
            peak=fitted_peak(f,power.mean(axis=(0,1)),cfg['alpha_band_hz'])
            theta=peak['candidate_hz']-cfg['iaf_offset_hz'] if peak['candidate_hz'] else None
            result['iaf_minus_5']={'alpha':peak,'unclipped_theta_hz':theta,
                                    'candidate_hz':theta if theta is not None and 4<theta<8 else None,
                                    'reason':'heuristic_not_feedback_theta_no_clipping_or_power_argmax_fallback',
                                    'n_clean_windows':len(windows)}
    return result


def summarize(out, results, fixture):
    columns=['recording_id','subject','session','task','phase','run','estimand','qc','status','candidate_hz',
             'individualized_frequency_hz','effect_db','n_eligible','n_retained','retention_fraction',
             'bootstrap_detection_fraction','bootstrap_ci_hz','roi_channels','failure_reasons','warnings']
    rows=[{key:json.dumps(r.get(key)) if isinstance(r.get(key),(dict,list)) else r.get(key) for key in columns} for r in results]
    pd.DataFrame(rows,columns=columns).to_csv(out/'qc_summary.csv',index=False)
    beta=[r for r in results if r['estimand']=='response_beta_erd']
    comparison=[]
    for r in beta:
        historical=fixture.get((r['subject'],r['task'],r['phase']))
        replay=r.get('legacy_reproduction',[])
        primary=replay[0] if replay else {}
        comparison.append({**{k:r.get(k) for k in ['subject','session','task','phase','run','candidate_hz','individualized_frequency_hz','effect_db','n_eligible','n_retained','qc']},
                           'historical_hz':historical,'legacy_replay_hz':primary.get('frequency_hz'),
                           'legacy_replay_n_retained':primary.get('n_retained'),
                           'legacy_replay_provenance':primary.get('provenance'),
                           'sst_correct_go_hypothesis_hz':next((x.get('frequency_hz') for x in replay if x.get('mode')=='sst_correct_go_hypothesis'),None),
                           'reasons':';'.join(r['failure_reasons'])})
    pd.DataFrame(comparison).to_csv(out/'original_revised_comparison.csv',index=False)
    paired=[]
    # Never merge multiple runs into one participant value.
    for dimension,levels,group in [('task',['bandit','sst'],['subject','session','phase']),('phase',['pre','post'],['subject','session','task'])]:
        keys=sorted({tuple(r[k] for k in group) for r in beta})
        for key in keys:
            rr=[r for r in beta if tuple(r[k] for k in group)==key]
            left=[r for r in rr if r[dimension]==levels[0]];right=[r for r in rr if r[dimension]==levels[1]]
            reliable_pair=len(left)==len(right)==1 and left[0]['reliable'] and right[0]['reliable']
            paired.append({**dict(zip(group,key)),'comparison':dimension,'reliable_pair':reliable_pair,
                           'difference_hz':right[0]['individualized_frequency_hz']-left[0]['individualized_frequency_hz'] if reliable_pair else None,
                           'reason':None if reliable_pair else 'missing_unreliable_or_multiple_runs'})
    pd.DataFrame(paired).to_csv(out/'paired_descriptives.csv',index=False)
    lines=['# Pilot validation run','',f"Recordings: {len(beta)}. Response beta passing provisional QC: {sum(r['reliable'] for r in beta)}.",
           f"Reliable cross-task pairs: {sum(r['comparison']=='task' and r['reliable_pair'] for r in paired)}. Reliable pre/post pairs: {sum(r['comparison']=='phase' and r['reliable_pair'] for r in paired)}.",'',
           'A passing candidate is not an approved stimulation frequency. See the methodological audit for limitations.', '',
           '| Subject | Task | Phase | Retained/eligible | Candidate Hz | QC | Reasons |',
           '|---|---|---|---:|---:|---|---|']
    for r in beta:
        lines.append(f"| {r['subject']} | {r['task']} | {r['phase']} | {r.get('n_retained',0)}/{r.get('n_eligible',0)} | {r.get('candidate_hz') or '—'} | {r['qc']} | {'; '.join(r['failure_reasons'])} |")
    (out/'README.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
