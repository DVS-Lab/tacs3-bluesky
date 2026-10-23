#!/usr/bin/env python3
"""Separate input/yield failures from estimation and acceptance-policy failures.

Known probes are added to copies of already retained epochs, never source EEG.
They test quantification conditional on preprocessing, not acquisition quality.
A separate threshold sensitivity run measures how much rejection depends on
provisional artifact settings; it does not approve rescued trials or frequencies.
"""
from __future__ import annotations

import argparse
import collections
import copy
import hashlib
import json
from pathlib import Path
import platform
import sys

import numpy as np
from scipy import signal

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'code'))
from rhythm_validation_core import assess, epoch_data, preprocess, spectra
from rhythm_validation_io import InputError, alignment_qc, load_pair, select_events


def probe_epochs(times, n_trials, n_channels, spec, frequency, high_uv, seed):
    """Known sinusoidal peak amplitudes in microvolts; no voltage averaging."""
    rng = np.random.default_rng(seed)
    start, end = spec['analysis_sec']
    envelope = .5 * (np.tanh((times-start+.12)/.04)-np.tanh((times-end-.12)/.04))
    low_uv = high_uv/4
    modulation = 1-envelope if spec['direction'] < 0 else envelope
    amp = low_uv + (high_uv-low_uv)*modulation
    phases = rng.uniform(-np.pi, np.pi, (n_trials, 1))
    wave = amp * np.sin(2*np.pi*frequency*times + phases)
    spatial = np.resize(np.array([1., -1., .6]), n_channels)
    return wave[:, None, :]*spatial[None, :, None]


def absolute_anchor(freqs, contrast, absolute, spec, thresholds):
    """Diagnostic alternative: locate an absolute spectral peak first.

    Select the in-band, slope-adjusted absolute peak with the largest signed
    task contrast. This is not fitted to the injected ground truth and has no
    deployment/reliability decision. A linear log-frequency background is only
    a screening approximation, not a validated periodic/aperiodic model.
    """
    log_power = 10*np.log10(np.maximum(absolute, 1e-30))
    residual = log_power-np.polyval(np.polyfit(np.log10(freqs), log_power, 1), np.log10(freqs))
    peaks, _ = signal.find_peaks(residual, prominence=thresholds['min_absolute_prominence_db'])
    peaks = [p for p in peaks if spec['band_hz'][0] < freqs[p] < spec['band_hz'][1]]
    if not peaks:
        return dict(absolute_anchor_candidate_hz=None, absolute_anchor_effect_db=None)
    p = max(peaks, key=lambda p: spec['direction']*contrast[p])
    return dict(absolute_anchor_candidate_hz=float(freqs[p]), absolute_anchor_effect_db=float(contrast[p]))


def quantify(ep, times, fs, spec, cfg):
    f, trials, base, active, _, _ = spectra(ep, times, fs, spec)
    # The probe tests the estimator conditional on retained epochs. Original
    # eligible/retained counts remain separate and cannot be overridden by this.
    absolute = base if spec['direction'] < 0 else active
    r = assess(f, trials, absolute, spec, cfg, len(ep), ep.shape[1])
    r.update(absolute_anchor(f, trials.mean(0), absolute.mean(0), spec, cfg['reliability']))
    # Independent FFT check of the supplied waveform; no ground truth enters it.
    fft_f, psd = signal.periodogram(ep, fs=fs, axis=-1)
    band = (fft_f >= spec['band_hz'][0]) & (fft_f <= spec['band_hz'][1])
    r['fourier_peak_hz'] = float(fft_f[band][np.argmax(psd.mean((0,1))[band])])
    return r


def stage(n_eligible, n_retained, n_roi, cfg):
    if n_eligible < cfg['reliability']['min_epochs']:
        return 'too_few_eligible_trials_before_artifact_screening'
    if n_roi < cfg['preprocessing']['min_roi_channels']:
        return 'channel_screening_limited'
    if n_retained < cfg['reliability']['min_epochs'] or n_retained/n_eligible < cfg['reliability']['min_retention']:
        return 'retained_trial_yield_limited'
    return 'sufficient_trial_yield_assess_target_and_method_separately'


def run(out):
    out.mkdir(parents=True, exist_ok=False)
    cfg = json.loads((ROOT/'code/rhythm_validation_config.json').read_text())
    manifest = json.loads((ROOT/'validation/pilot_manifest.json').read_text())
    # A single fixed sensitivity contrast, not optimized against peak outcomes.
    sensitivity = copy.deepcopy(cfg['preprocessing'])
    sensitivity['epoch_ptp_uv'] *= 1.5
    sensitivity['step_uv'] *= 1.5
    sensitivity['max_bad_window_fraction'] = .30
    records, probes = [], []
    for job_index, job in enumerate(manifest['jobs']):
        keys = ['response_beta_erd', 'feedback_theta_enhancement'] if job['task'] == 'bandit' else [
            'response_beta_erd', 'stop_success_beta_enhancement', 'stop_failure_beta_enhancement']
        failure = None
        try:
            raw, t, fs, names, rows, _ = load_pair(ROOT, job, cfg['preprocessing'])
            clean, filtered, roi, refs, channels = preprocess(raw, fs, names, cfg['preprocessing'])
            clean_s, filtered_s, roi_s, refs_s, channels_s = preprocess(raw, fs, names, sensitivity)
        except InputError as exc:
            failure = str(exc)
        for key_index, key in enumerate(keys):
            common = dict(recording_id=job['id'], estimand=key)
            eligible = None
            try:
                if failure:
                    raise InputError(failure)
                spec = cfg['estimands'][key]
                logs = select_events(rows, job['task'], key, job['clock_domain'], job)
                eligible = sum(x['eligible'] for x in logs)
                alignment_qc(logs, rows, t, cfg['preprocessing'])
                ep_s, _, logs_s = epoch_data(clean_s, filtered_s, t, fs, names, roi_s, refs_s,
                                            copy.deepcopy(logs), spec, sensitivity)
                ep, times, logs = epoch_data(clean, filtered, t, fs, names, roi, refs, logs, spec, cfg['preprocessing'])
                eligible = sum(x['eligible'] for x in logs)
                result = json.loads((ROOT/'validation/pilot_results_input_recovery'/job['id']/key/'result.json').read_text())
                assert len(ep) == result['n_retained'], common
                record = dict(**common, input_and_timing_status='verified_by_current_checks',
                    stage=stage(eligible, len(ep), len(roi), cfg), n_eligible=eligible,
                    n_retained=len(ep), n_retained_sensitivity=len(ep_s),
                    roi_channels=[names[i] for i in roi], sensitivity_roi_channels=[names[i] for i in roi_s],
                    channel_diagnostics=channels,
                    exclusions=dict(collections.Counter(x['reason'] for x in logs if x['eligible'] and x['reason'])),
                    sensitivity_exclusions=dict(collections.Counter(x['reason'] for x in logs_s if x['eligible'] and x['reason'])),
                    native_candidate_hz=result.get('candidate_hz'), native_effect_db=result.get('effect_db'),
                    native_failure_reasons=result['failure_reasons'], native_splits=result.get('splits'),
                    native_approved_stimulation_frequency_hz=None)
                if len(ep) >= cfg['reliability']['min_epochs']:
                    frequencies = [5., 6., 7.] if key.startswith('feedback') else [17., 21., 26.]
                    record['probe_status'] = 'tested_conditionally_on_retained_epochs'
                    record['retained_epoch_median_channel_std_uv'] = float(np.median(np.std(ep, axis=-1)))
                    for frequency in frequencies:
                        for amplitude in [3., 10.]:
                            seed = 910000+job_index*1000+key_index*100+int(frequency)*2+int(amplitude)
                            probe = probe_epochs(times, len(ep), len(roi), spec, frequency, amplitude, seed)
                            rng = np.random.default_rng(seed+1)
                            clean_control = rng.normal(0, 1, ep.shape)+probe
                            for background, values in [('clean_1uv_noise', clean_control), ('retained_real_eeg', ep+probe)]:
                                r = quantify(values, times, fs, spec, cfg)
                                error = abs(r['candidate_hz']-frequency) if r['candidate_hz'] is not None else None
                                tolerance = .5 if key.startswith('feedback') else 1.
                                accurate = error is not None and error <= tolerance and r['effect_db']*spec['direction'] > 0
                                anchor_error = abs(r['absolute_anchor_candidate_hz']-frequency) if r['absolute_anchor_candidate_hz'] is not None else None
                                anchor_accurate = anchor_error is not None and anchor_error <= tolerance and r['absolute_anchor_effect_db']*spec['direction'] > 0
                                probes.append(dict(**common, background=background, true_frequency_hz=frequency,
                                    high_peak_amplitude_uv=amplitude, low_peak_amplitude_uv=amplitude/4,
                                    seed=seed, sampling_hz=fs, n_trials=len(ep), frequency_error_hz=error,
                                    recovered_frequency_and_direction=accurate, tolerance_hz=tolerance,
                                    absolute_anchor_error_hz=anchor_error, absolute_anchor_recovered=anchor_accurate,
                                    fourier_error_hz=abs(r['fourier_peak_hz']-frequency), **r))
                else:
                    record['probe_status'] = 'not_tested_fewer_than_40_retained_epochs'
                records.append(record)
            except InputError as exc:
                records.append(dict(**common, input_and_timing_status='not_established',
                                    stage='no_eligible_behavioral_trials' if str(exc) == 'no_eligible_events' else 'input_or_timing_unresolved',
                                    n_eligible=eligible, reason=str(exc), probe_status='not_tested_input_or_timing_unresolved'))
        print(job['id'], 'diagnosed', flush=True)
    groups = collections.defaultdict(list)
    for r in probes:
        groups[(r['background'], r['high_peak_amplitude_uv'])].append(r)
    summaries = [dict(background=b, high_peak_amplitude_uv=a, datasets=len(rr),
                      recovered=sum(r['recovered_frequency_and_direction'] for r in rr),
                      absolute_anchor_recovered=sum(r['absolute_anchor_recovered'] for r in rr),
                      fourier_recovered=sum(r['fourier_error_hz'] <= r['tolerance_hz'] for r in rr),
                      accepted=sum(r['reliable'] for r in rr),
                      accurately_recovered_but_rejected=sum(r['recovered_frequency_and_direction'] and not r['reliable'] for r in rr))
                 for (b, a), rr in groups.items()]
    source_paths = [Path(__file__), ROOT/'code/rhythm_validation_core.py', ROOT/'code/rhythm_validation_io.py',
                    ROOT/'code/rhythm_validation_config.json', ROOT/'validation/pilot_manifest.json']
    payload = dict(config=cfg, artifact_sensitivity_settings=sensitivity, python=platform.python_version(),
        source_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in source_paths},
        stage_counts=dict(collections.Counter(r['stage'] for r in records)), probe_summary=summaries,
        limitations='Post-preprocessing additive probes test only recovery of the injected signal at specified amplitudes, frequencies, and event windows. They cannot prove absence of a native rhythm, validate all methods, certify acquisition quality, or authorize stimulation. The permissive artifact contrast is a sensitivity analysis, not adopted settings.',
        records=records, probes=probes)
    with (out/'diagnostics.json').open('x') as f:
        json.dump(payload, f, indent=2, allow_nan=False)
        f.write('\n')
    print(json.dumps(dict(stage_counts=payload['stage_counts'], probe_summary=summaries), indent=2), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    run(parser.parse_args().out)
