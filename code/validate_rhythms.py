#!/usr/bin/env python3
"""Reproducible offline pilot validation. Never generates stimulation protocols."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import subprocess
import sys

import numpy as np
import pandas as pd

from rhythm_validation_io import InputError, alignment_qc, load_pair, resolve, select_events, sha256, validate_identity
from rhythm_validation_core import estimate, preprocess, preview
from rhythm_validation_report import legacy_replay, plot_channels, plot_result, summarize, theta_secondary, write_json

ROOT = Path(__file__).resolve().parents[1]


def create_output(root, requested=None):
    # All runs confined to a dedicated derived directory, always exclusive creation.
    base = root / 'validation_outputs'
    name = requested or datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S_%fZ')
    if Path(name).name != name or name in {'.', '..'}:
        raise InputError('output_name_must_be_a_single_directory_name')
    out = base / name
    out.mkdir(parents=True, exist_ok=False)
    return out


def fixture_values(root):
    frame = pd.read_csv(root/'validation/historical_beta_fixture.csv',dtype={'subject':str})
    return {(r.subject,r.task,r.phase):None if pd.isna(r.frequency_hz) else float(r.frequency_hz) for r in frame.itertuples()}


def run(root, manifest_path, config_path, subject=None, output_name=None, replay=True):
    cfg=json.loads(config_path.read_text())
    manifest=json.loads(manifest_path.read_text())
    jobs=[j for j in manifest['jobs'] if subject is None or j['subject']==subject]
    if not jobs:raise InputError('no_recordings_for_subject')
    ids=[j['id'] for j in jobs]
    if len(ids)!=len(set(ids)):raise InputError('duplicate_manifest_recording_id')
    out=create_output(root,output_name)
    os.environ.setdefault('MPLCONFIGDIR',str(out/'mpl_cache'))
    write_json(out/'config.json',cfg)
    write_json(out/'manifest.json',dict(schema=manifest['schema'],jobs=jobs))
    cfg_hash=sha256(config_path)
    try:git_sha=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip()
    except (OSError,subprocess.CalledProcessError):git_sha=None
    code_hashes={p.name:sha256(p) for p in sorted((root/'code').glob('*validation*.py'))}
    code_hashes['validate_rhythms.py']=sha256(Path(__file__))
    provenance=dict(created_at=datetime.now(timezone.utc).isoformat(),python=platform.python_version(),
                    platform=platform.platform(),git_commit=git_sha,source_sha256=code_hashes,
                    config_sha256=cfg_hash,manifest_sha256=sha256(manifest_path),
                    packages={p:importlib.metadata.version(p) for p in ['numpy','scipy','pandas','matplotlib','specparam']})
    write_json(out/'provenance.json',provenance)
    results=[]
    for job in jobs:
        print(job['id'],flush=True)
        recording_out=out/job['id'];recording_out.mkdir()
        replay_result=[]
        # Historical replays are separate from corrected inputs and never authorize them.
        if replay and job.get('eeg') and job.get('events'):
            try:
                for key in ('eeg','events'):
                    if sha256(resolve(root,job[key]))!=job['sha256'][key]:raise InputError(f'{key}_hash_mismatch')
                behavior=pd.read_csv(root/job['events'],sep='\t' if job['events'].endswith('.tsv') else ',')
                validate_identity(job,behavior)
                replay_result=legacy_replay(root,job)
            except (InputError,ValueError,KeyError,OSError) as exc:
                replay_result=[dict(error=str(exc))]
            write_json(recording_out/'legacy_reproduction.json',replay_result)
        failure=None
        try:
            raw,t,fs,names,rows,clocks=load_pair(root,job,cfg['preprocessing'])
            clean,filtered,roi,refs,channel_qc=preprocess(raw,fs,names,cfg['preprocessing'])
            write_json(recording_out/'channels.json',channel_qc)
            plot_channels(recording_out,channel_qc)
        except InputError as exc:
            failure=str(exc)
        estimands=['response_beta_erd','feedback_theta_enhancement'] if job['task']=='bandit' else ['response_beta_erd','stop_success_beta_enhancement','stop_failure_beta_enhancement']
        for estimand in estimands:
            spec=cfg['estimands'][estimand]
            result={k:job[k] for k in ['subject','session','task','phase','run']}
            result.update(recording_id=job['id'],estimand=estimand,
                          analysis_version=cfg['analysis_version'],config_sha256=cfg_hash,
                          input_paths={k:job.get(k) for k in ['eeg','events','metadata']},input_sha256=job['sha256'],
                          intended_use='offline_validation_only',approved_stimulation_frequency_hz=None,
                          legacy_reproduction=replay_result if estimand=='response_beta_erd' else [])
            dest=recording_out/estimand;dest.mkdir()
            logs=[]
            try:
                if failure:raise InputError(failure)
                result['timestamp_diagnostics']=clocks
                logs=select_events(rows,job['task'],estimand,job['clock_domain'],job)
                result['timestamp_diagnostics']={**clocks,**alignment_qc(logs,rows,t,cfg['preprocessing'])}
                assessed,arrays,epochs,times=estimate(clean,filtered,t,fs,names,roi,refs,logs,spec,cfg)
                result.update(assessed)
                result['warnings']+=['software_timestamp_latency_unvalidated','sparse_frontal_montage_not_motor_cortex']
                if any(x.get('warning') for x in logs):result['warnings'].append('fp1_artifacts_inspect_channel_qc')
                plot_result(dest,result,arrays,spec)
                pd.DataFrame({'frequency_hz':arrays['freqs'],
                              'change_db':arrays['trials'].mean(0) if len(epochs) else np.nan,
                              'baseline_power_uv2':arrays['base'].mean(0) if len(epochs) else np.nan,
                              'analysis_power_uv2':arrays['active'].mean(0) if len(epochs) else np.nan}).to_csv(dest/'spectrum.csv',index=False)
                if estimand=='feedback_theta_enhancement':
                    result['secondary_theta']=theta_secondary(epochs,times,fs,clean,names,channel_qc,cfg['theta_secondary'])
            except InputError as exc:
                result['timestamp_diagnostics'] = {**result.get('timestamp_diagnostics', {}), **exc.diagnostics}
                result.update(reliable=False,qc='FAIL',status='unreliable_no_individualized_frequency',
                              candidate_hz=None,individualized_frequency_hz=None,effect_db=None,
                              fallback_option_hz=spec['fallback_option_hz'],n_eligible=sum(x['eligible'] for x in logs),
                              n_retained=0,retention_fraction=0,failure_reasons=[str(exc)],warnings=[])
                for log in logs:
                    if log['eligible']:log['reason']=str(exc)
            if logs:pd.DataFrame(logs).to_csv(dest/'events.csv',index=False)
            write_json(dest/'result.json',result)
            write_json(dest/'recommendation_preview.json',preview(result))
            print(f"  {estimand}: {result['qc']} {result['n_retained']}/{result['n_eligible']} {','.join(result['failure_reasons'])}",flush=True)
            results.append(result)
    summarize(out,results,fixture_values(root))
    write_json(out/'completion.json',dict(completed=True,recordings=len(jobs),estimates=len(results),
                                        passing_estimates=sum(r['reliable'] for r in results)))
    print(f'Outputs: {out}',flush=True)
    return out


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--subject',help='One participant, e.g. 10034; omit for all pilot recordings')
    parser.add_argument('--manifest',type=Path,default=ROOT/'validation/pilot_manifest.json')
    parser.add_argument('--config',type=Path,default=ROOT/'code/rhythm_validation_config.json')
    parser.add_argument('--output-name',help='Optional NEW directory name within validation_outputs')
    parser.add_argument('--skip-legacy',action='store_true',help='Skip historical replay; revised analysis unchanged')
    args=parser.parse_args()
    try:run(ROOT,args.manifest.resolve(),args.config.resolve(),args.subject,args.output_name,not args.skip_legacy)
    except (InputError,FileExistsError) as exc:parser.exit(2,f'Input error: {exc}\n')


if __name__=='__main__':main()
