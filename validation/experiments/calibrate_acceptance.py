#!/usr/bin/env python3
"""Offline acceptance-policy experiment; does not change the production policy.

Run development first, then heldout with its frozen lock, then pilot. Outputs
are exclusively created. No simulation result authorizes participant stimulation.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
from pathlib import Path
import sys
from unittest.mock import patch

import numpy as np
from scipy import signal

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'code'))
import rhythm_validation_core as core
from rhythm_validation_io import InputError, alignment_qc, load_pair, select_events

KEYS = ['response_beta_erd', 'stop_success_beta_enhancement', 'feedback_theta_enhancement']
CONTROLS = ['noise', 'stationary_peak', 'broadband', 'broadband_with_peak',
            'switch', 'boundary', 'transient', 'chirp', 'competing']
POLICIES = ['current_v1_1', 'full_grid_localization']


def full_grid_feature(freqs, spectrum, spec, thresholds, absolute=None):
    """Keep band-limited selection, measure prominence on the available full grid.

    A fixed width of a log-power contrast and its linearly detrended peak are
    not used as vetoes. Absolute-power corroboration, competing peaks, effect,
    band boundaries, split checks, and block bootstrap remain mandatory.
    This is an experimental alternative, not an established optimal estimator.
    """
    signed = spec['direction'] * np.asarray(spectrum)
    band_idx = np.flatnonzero((freqs >= spec['band_hz'][0]) & (freqs <= spec['band_hz'][1]))
    result = dict(candidate_hz=None, effect_db=None, prominence_db=None, width_hz=None,
                  absolute_peak_hz=None, reasons=[])
    if not len(band_idx) or not np.isfinite(signed).all():
        result['reasons'] = ['missing_or_nonfinite_spectrum']
        return result
    idx = band_idx[np.argmax(signed[band_idx])]
    result.update(candidate_hz=float(freqs[idx]), effect_db=float(spectrum[idx]))
    reasons = result['reasons']
    if idx in (band_idx[0], band_idx[-1]):
        reasons.append('search_band_boundary')
    if signed[idx] < thresholds['min_effect_db']:
        reasons.append('wrong_direction_or_small_effect')
    peaks, props = signal.find_peaks(signed, prominence=thresholds['min_prominence_db'])
    if idx not in peaks:
        reasons.append('no_localized_contrast')
    else:
        k = list(peaks).index(idx)
        prominence = props['prominences'][k]
        result.update(prominence_db=float(prominence), width_hz=float(
            signal.peak_widths(signed, [idx])[0][0] * (freqs[1] - freqs[0])))
        if any(p != idx and p in band_idx and pr >= prominence * thresholds['competing_peak_fraction']
               for p, pr in zip(peaks, props['prominences'])):
            reasons.append('ambiguous_competing_features')
    if absolute is not None:
        log_power = 10 * np.log10(np.maximum(absolute, 1e-30))
        slope = np.polyval(np.polyfit(np.log10(freqs), log_power, 1), np.log10(freqs))
        peaks, _ = signal.find_peaks(log_power - slope, prominence=thresholds['min_absolute_prominence_db'])
        matches = [p for p in peaks if abs(freqs[p] - freqs[idx]) <= spec['absolute_match_hz']]
        if matches:
            p = min(matches, key=lambda p: abs(freqs[p] - freqs[idx]))
            result['absolute_peak_hz'] = float(freqs[p])
        else:
            reasons.append('no_absolute_spectral_corroboration')
    return result


def evaluate(policy, freqs, trials, absolute, spec, cfg, eligible, n_roi):
    if policy == 'current_v1_1':
        return core.assess(freqs, trials, absolute, spec, cfg, eligible, n_roi)
    if policy != 'full_grid_localization':
        raise ValueError(policy)
    with patch.object(core, 'feature', full_grid_feature):
        return core.assess(freqs, trials, absolute, spec, cfg, eligible, n_roi)


def generate(spec, case, phase):
    rng = np.random.default_rng(case['seed'])
    fs = 100 if phase == 'development' else 250
    n = case['n_trials']
    t = np.arange(round(np.diff(spec['epoch_sec'])[0] * fs)) / fs + spec['epoch_sec'][0]
    noise = rng.normal(size=(n, 3, len(t)))
    bins = np.fft.rfftfreq(len(t), 1 / fs)
    exponent = case['background_exponent']
    weights = np.maximum(bins, .5) ** (-exponent / 2)
    weights[0] = 0
    noise = np.fft.irfft(np.fft.rfft(noise, axis=-1) * weights, n=len(t), axis=-1)
    noise *= 2 / np.std(noise, axis=-1, keepdims=True)
    # The held-out set adds AR-like trial gain dependence and smooth transitions.
    gains = rng.normal(0, .6, n)
    if phase == 'heldout':
        gains = signal.lfilter([1], [1, -.6], gains)
    start, end = spec['analysis_sec']
    transition = .02 if phase == 'development' else .07
    envelope = .5 * (np.tanh((t - start + .10) / transition) -
                     np.tanh((t - end - .10) / transition))
    scenario = case['scenario']
    theta = spec['band_hz'][1] == 8
    center = case.get('frequency_hz') or (6 if theta else 21)
    if scenario in ('broadband', 'broadband_with_peak'):
        noise *= (1 + ((.35 if spec['direction'] < 0 else 3) - 1) * envelope)
    if scenario in ('known', 'stationary_peak', 'broadband_with_peak', 'switch', 'boundary', 'chirp', 'competing'):
        f = np.full(n, center, dtype=float)
        if scenario == 'switch':
            f[:n//2] = 5 if theta else 17
            f[n//2:] = 7 if theta else 26
        if scenario == 'boundary':
            f[:] = spec['band_hz'][0]
        if phase == 'heldout' and scenario == 'known':
            f += rng.normal(0, .08 if theta else .15, n)
        phase0 = rng.uniform(-np.pi, np.pi, (n, 1))
        angle = 2 * np.pi * f[:, None] * t + phase0
        if scenario == 'chirp':
            angle += np.pi * (2 if theta else 9) * (t - start) ** 2
        wave = np.sin(angle)
        high = case.get('amplitude', 4)
        amp = 1 + (high - 1) * (1 - envelope if spec['direction'] < 0 else envelope)
        if scenario in ('stationary_peak', 'broadband_with_peak'):
            amp = np.full(len(t), 4.)
        if scenario == 'competing':
            other = 5 if theta else 17
            f[:] = 7 if theta else 26
            wave = np.sin(2 * np.pi * f[:, None] * t + phase0) + np.sin(2 * np.pi * other * t - phase0)
        noise += wave[:, None, :] * amp[None, None, :] * np.array([1, -1, .6])[None, :, None]
    if scenario == 'transient':
        # Nonoscillatory event-related voltage transient; enhancement analyses only
        # have the expected effect direction, but all analyses test it as a control.
        center_t = np.mean(spec['analysis_sec'])
        widths = rng.uniform(.025, .075, (n, 1))
        transient = 12 * np.exp(-.5 * ((t - center_t) / widths) ** 2)
        noise += transient[:, None, :] * np.array([1, -.6, .8])[None, :, None]
    return noise * np.exp(gains)[:, None, None], t, fs


def cases(phase):
    # Fully specified before either run. Held-out frequencies, seeds, sampling
    # rate, backgrounds, gain structure, envelope, and jitter differ.
    offset = 310000 if phase == 'development' else 730000
    seeds = range(2) if phase == 'development' else range(3)
    backgrounds = [0, 1] if phase == 'development' else [.5, 1.5]
    for ki, key in enumerate(KEYS):
        theta = key.startswith('feedback')
        frequencies = ([5, 6, 7] if theta else [17, 21, 26]) if phase == 'development' else ([4.75, 5.75, 6.75] if theta else [16, 20, 25])
        serial = 0
        for strength, amp in [('weak', 1.3), ('moderate', 2), ('strong', 4)]:
            for f in frequencies:
                for bg in backgrounds:
                    for rep in seeds:
                        serial += 1
                        yield dict(estimand=key, scenario='known', strength=strength, amplitude=amp,
                                   frequency_hz=f, background_exponent=bg, seed=offset + ki*10000 + serial,
                                   n_trials=[40, 80, 120][rep % 3])
        for scenario in CONTROLS:
            for bg in backgrounds:
                for rep in seeds:
                    serial += 1
                    yield dict(estimand=key, scenario=scenario, strength=None,
                               background_exponent=bg, seed=offset + ki*10000 + serial,
                               n_trials=[40, 80, 120][rep % 3])


def hashes():
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in
            [Path(__file__), ROOT/'code/rhythm_validation_core.py', ROOT/'code/rhythm_validation_config.json']}


def write(path, value):
    with path.open('x') as f:
        json.dump(value, f, indent=2, allow_nan=False)
        f.write('\n')


def summarize(records):
    summary = []
    for policy in POLICIES:
        groups = collections.defaultdict(list)
        for r in records:
            if r['policy'] == policy:
                groups[(r['estimand'], r['scenario'], r.get('strength'))].append(r)
        for (key, scenario, strength), rr in groups.items():
            accepted = [r for r in rr if r['reliable']]
            errors = [r['frequency_error_hz'] for r in accepted if r.get('frequency_error_hz') is not None]
            summary.append(dict(policy=policy, estimand=key, scenario=scenario, strength=strength,
                                datasets=len(rr), accepted=len(accepted), max_accepted_frequency_error_hz=max(errors) if errors else None))
    return summary


def benchmark(phase, out, cfg, lock=None):
    if lock and lock['source_sha256'] != hashes():
        raise ValueError('Source/config changed after development lock; heldout is no longer independent of this revision.')
    records = []
    for i, case in enumerate(cases(phase)):
        spec = cfg['estimands'][case['estimand']]
        epochs, t, fs = generate(spec, case, phase)
        f, trials, base, active, _, _ = core.spectra(epochs, t, fs, spec)
        absolute = base if spec['direction'] < 0 else active
        for policy in POLICIES:
            r = evaluate(policy, f, trials, absolute, spec, cfg, len(epochs), 3)
            error = abs(r['candidate_hz'] - case['frequency_hz']) if case['scenario'] == 'known' else None
            records.append(dict(**case, policy=policy, sampling_hz=fs, frequency_error_hz=error, **r))
        if (i+1) % 18 == 0:
            print(phase, i+1, 'datasets completed', flush=True)
    summary = summarize(records)
    write(out/'results.json', dict(phase=phase, source_sha256=hashes(), config=cfg, summary=summary, records=records))
    if phase == 'development':
        # This is a screening rule, not a claim of population error control.
        eligible = []
        for policy in POLICIES:
            rr = [r for r in records if r['policy'] == policy]
            controls = [r for r in rr if r['scenario'] != 'known']
            strong = [r for r in rr if r['scenario'] == 'known' and r['strength'] == 'strong']
            wrong = [r for r in rr if r['scenario'] == 'known' and r['reliable'] and
                     r['frequency_error_hz'] > (.75 if r['estimand'].startswith('feedback') else 2)]
            if not any(r['reliable'] for r in controls) and not wrong and np.mean([r['reliable'] for r in strong]) >= .8:
                eligible.append((sum(r['reliable'] for r in rr if r['scenario'] == 'known'), policy))
        selected = max(eligible)[1] if eligible else None
        write(out/'lock.json', dict(source_sha256=hashes(), selected_policy=selected,
              criterion='Zero accepted development controls; no accepted known error >2 Hz beta/0.75 Hz theta; >=80% strong-signal acceptance; maximize known-signal acceptance among eligible policies. No eligible policy means no promotion.',
              deployment_authorized=False))
        print('Development selected policy:', selected, flush=True)
    print('Finished:', out, flush=True)


def pilot(out, cfg, lock):
    if lock['source_sha256'] != hashes():
        raise ValueError('Source/config changed since lock')
    manifest = json.loads((ROOT/'validation/pilot_manifest.json').read_text())
    records = []
    for job in manifest['jobs']:
        keys = ['response_beta_erd', 'feedback_theta_enhancement'] if job['task'] == 'bandit' else [
            'response_beta_erd', 'stop_success_beta_enhancement', 'stop_failure_beta_enhancement']
        failure = None
        try:
            raw, timestamps, fs, names, rows, _ = load_pair(ROOT, job, cfg['preprocessing'])
            clean, filtered, roi, refs, _ = core.preprocess(raw, fs, names, cfg['preprocessing'])
        except InputError as exc:
            failure = str(exc)
        for key in keys:
            common = dict(recording_id=job['id'], estimand=key, source_input_sha256=job['sha256'])
            try:
                if failure:
                    raise InputError(failure)
                spec = cfg['estimands'][key]
                logs = select_events(rows, job['task'], key, job['clock_domain'], job)
                alignment_qc(logs, rows, timestamps, cfg['preprocessing'])
                ep, times, logs = core.epoch_data(clean, filtered, timestamps, fs, names, roi, refs, logs, spec, cfg['preprocessing'])
                f, trials, base, active, _, _ = core.spectra(ep, times, fs, spec)
                absolute = base if spec['direction'] < 0 else active
                for policy in POLICIES:
                    r = evaluate(policy, f, trials, absolute, spec, cfg, sum(x['eligible'] for x in logs), len(roi))
                    records.append(dict(**common, policy=policy, **r))
            except InputError as exc:
                for policy in POLICIES:
                    records.append(dict(**common, policy=policy, reliable=False, failure_reasons=[str(exc)], n_retained=0))
        print(job['id'], 'complete', flush=True)
    write(out/'results.json', dict(source_sha256=hashes(), development_lock=lock,
          intended_use='Policy sensitivity analysis only; no production or stimulation changes', records=records))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['development', 'heldout', 'pilot'])
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--lock', type=Path)
    args = parser.parse_args()
    if args.phase != 'development' and not args.lock:
        parser.error('--lock is required for heldout/pilot')
    lock = json.loads(args.lock.read_text()) if args.lock else None
    args.out.mkdir(parents=True, exist_ok=False)
    cfg = json.loads((ROOT/'code/rhythm_validation_config.json').read_text())
    if args.phase == 'pilot':
        pilot(args.out, cfg, lock)
    else:
        benchmark(args.phase, args.out, cfg, lock)


if __name__ == '__main__':
    main()
