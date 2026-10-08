"""Offline effect-specific estimation. Results are candidates, never prescriptions."""
from __future__ import annotations

from collections import Counter
import numpy as np
from scipy import signal

from rhythm_validation_io import InputError, number


def mask(times, window):
    return (times >= window[0] - 1e-8) & (times < window[1] - 1e-8)


def preprocess(data, fs, names, cfg):
    """Detect bad channels before reference; use a prespecified non-ocular reference.

    Fp1 is an ocular diagnostic, EXT is not a scalp reference. No interpolation.
    Bad channels are never allowed into the reference or the analysis ROI.
    """
    n = int(round(cfg['channel_window_sec'] * fs))
    sos = signal.butter(cfg['filter_order'], [cfg['highpass_hz'], cfg['lowpass_hz']],
                        btype='bandpass', fs=fs, output='sos')
    filtered = signal.sosfiltfilt(sos, np.nan_to_num(data), axis=0)
    qc = {}
    good = []
    for i, name in enumerate(names):
        x = data[:, i]
        reasons = []
        if not np.isfinite(x).all():
            reasons.append('nonfinite')
            frac = 1.0
        else:
            windows = [filtered[j:j+n, i] for j in range(0, len(x) - n + 1, n)]
            bad = [np.std(w) < cfg['flat_std_uv'] or np.ptp(w) > cfg['epoch_ptp_uv'] or
                   np.max(np.abs(np.diff(w))) > cfg['step_uv'] for w in windows]
            frac = float(np.mean(bad)) if bad else 1.0
            if np.std(x) < cfg['flat_std_uv']:
                reasons.append('flat')
            if frac > cfg['max_bad_window_fraction']:
                reasons.append('excess_bad_windows')
        if name == 'EXT':
            reasons.append('external_channel_not_scalp')
        if not reasons:
            good.append(i)
        qc[name] = dict(bad=bool(reasons), reasons=reasons, bad_window_fraction=frac,
                        raw_std_uv=number(np.std(x)), role='ocular_only' if name == 'Fp1' else 'scalp')
    refs = [i for i in good if names[i] in cfg['reference_channels']]
    roi = [i for i in good if names[i] in cfg['roi_channels']]
    if len(refs) >= cfg['min_roi_channels']:
        clean = filtered - filtered[:, refs].mean(axis=1, keepdims=True)
    else:
        clean = filtered.copy()
        roi = []
    return clean, filtered, roi, refs, qc


def epoch_data(clean, filtered, t, fs, names, roi, refs, logs, spec, cfg):
    times = np.arange(round((spec['epoch_sec'][1] - spec['epoch_sec'][0]) * fs)) / fs + spec['epoch_sec'][0]
    # Both ends must be beyond the actual five-sigma wavelet support.
    half = 5 * spec['cycles'] / (2 * np.pi * spec['grid_hz'][0])
    for window in (spec['baseline_sec'], spec['analysis_sec'], spec['plot_sec']):
        if window[0] - half < times[0] or window[1] + half > times[-1] + 1 / fs:
            raise InputError('insufficient_real_data_wavelet_padding')
    epochs = []
    ocular = names.index('Fp1') if 'Fp1' in names else None
    for log in logs:
        if not log['eligible'] or log['reason']:
            continue
        event = log['event_sec']
        center = int(np.searchsorted(t, event))
        center = min(center, len(t) - 1)
        if center and abs(t[center-1] - event) < abs(t[center] - event):
            center -= 1
        residual = abs(t[center] - event)
        log['alignment_error_sec'] = float(residual)
        start = center + round(spec['epoch_sec'][0] * fs)
        stop = start + len(times)
        reason = ''
        if residual > cfg['event_tolerance_sec']:
            reason = 'event_outside_recording_or_alignment_error'
        elif start < 0 or stop > len(clean):
            reason = 'insufficient_epoch_padding'
        elif len(roi) < cfg['min_roi_channels']:
            reason = 'insufficient_roi_channels'
        else:
            ep = clean[start:stop, roi].T
            # Check referenced ROI and the channels contributing to its reference.
            checks = [(ep, [names[i] for i in roi]),
                      (filtered[start:stop, refs].T, [names[i] for i in refs])]
            affected = set()
            for arr, labels in checks:
                bad = (np.ptp(arr, axis=1) > cfg['epoch_ptp_uv']) | (np.max(np.abs(np.diff(arr, axis=1)), axis=1) > cfg['step_uv'])
                affected.update(label for label, b in zip(labels, bad) if b)
            if affected:
                reason = 'artifact:' + ','.join(sorted(affected))
            if not reason and ocular is not None:
                fp = clean[start:stop, ocular]
                log['fp1_ptp_uv'] = float(np.ptp(fp))
                if np.ptp(fp) > cfg['epoch_ptp_uv']:
                    correlations = [abs(np.corrcoef(fp, clean[start:stop, i])[0, 1]) for i in roi]
                    if np.nanmax(correlations) > cfg['ocular_correlation']:
                        reason = 'ocular_artifact_spreads_to_roi'
                    else:
                        log['warning'] = 'fp1_artifact_without_detected_roi_spread'
            if not reason:
                epochs.append(ep)
                log['retained'] = True
        log['reason'] = reason
    shape = (0, len(roi), len(times))
    return np.stack(epochs) if epochs else np.empty(shape), times, logs


def spectra(epochs, times, fs, spec):
    """Per-trial dB ratios after power averaging across channels (no cancellation).

    Convolve real padded epochs, normalize each trial to its own baseline.
    Retain the trial dimension for uncertainty; never bootstrap frequency bins.
    """
    low, high, step = spec['grid_hz']
    freqs = np.arange(low, high + step / 2, step)
    base_mask = mask(times, spec['baseline_sec'])
    active_mask = mask(times, spec['analysis_sec'])
    plot_idx = np.flatnonzero(mask(times, spec['plot_sec']))[::max(1, round(fs / 50))]
    contrasts = np.empty((len(epochs), len(freqs)))
    base = np.empty_like(contrasts)
    active = np.empty_like(contrasts)
    tf = np.empty((len(freqs), len(plot_idx)))
    if not len(epochs):
        return freqs, contrasts, base, active, times[plot_idx], np.full(tf.shape, np.nan)
    for j, f in enumerate(freqs):
        sigma = spec['cycles'] / (2 * np.pi * f)
        h = int(np.ceil(5 * sigma * fs))
        wtime = np.arange(-h, h + 1) / fs
        # Explicitly zero-mean Morlet; all conventions are frozen here.
        wave = (np.exp(2j * np.pi * f * wtime) - np.exp(-spec['cycles']**2 / 2)) * np.exp(-wtime**2 / (2*sigma**2))
        wave /= np.sqrt(np.sum(np.abs(wave)**2))
        power = np.abs(signal.fftconvolve(epochs, wave[None, None, :], mode='same', axes=-1))**2
        power = power.mean(axis=1)
        baseline = power[:, base_mask].mean(axis=1)
        active[:, j] = power[:, active_mask].mean(axis=1)
        base[:, j] = baseline
        db = 10 * np.log10(np.maximum(power, 1e-30) / np.maximum(baseline[:, None], 1e-30))
        contrasts[:, j] = db[:, active_mask].mean(axis=1)
        tf[j] = db[:, plot_idx].mean(axis=0)
    return freqs, contrasts, base, active, times[plot_idx], tf


def feature(freqs, spectrum, spec, thresholds, absolute=None):
    """Require interior, signed, localized, unambiguous contrast and absolute support.

    Removing a linear spectral trend is an additional localization check, not a
    claim to fit the aperiodic component. Absolute support uses log-frequency slope.
    """
    band = (freqs >= spec['band_hz'][0]) & (freqs <= spec['band_hz'][1])
    f, signed = freqs[band], spec['direction'] * np.asarray(spectrum)[band]
    result = dict(candidate_hz=None, effect_db=None, prominence_db=None, width_hz=None,
                  absolute_peak_hz=None, reasons=[])
    if not len(f) or not np.isfinite(signed).all():
        result['reasons'] = ['missing_or_nonfinite_spectrum']
        return result
    idx = int(np.argmax(signed))
    result.update(candidate_hz=float(f[idx]), effect_db=float(spectrum[band][idx]))
    reasons = result['reasons']
    if idx in {0, len(f)-1}:
        reasons.append('search_band_boundary')
    if signed[idx] < thresholds['min_effect_db']:
        reasons.append('wrong_direction_or_small_effect')
    # Real local prominence, unlike a peak-versus-median z score.
    peaks, properties = signal.find_peaks(signed, prominence=thresholds['min_prominence_db'])
    if idx not in peaks:
        reasons.append('no_localized_contrast')
    else:
        k = list(peaks).index(idx)
        prominence = properties['prominences'][k]
        width = signal.peak_widths(signed, [idx], rel_height=0.5)[0][0] * (f[1] - f[0])
        result.update(prominence_db=float(prominence), width_hz=float(width))
        if not spec['width_hz'][0] <= width <= spec['width_hz'][1]:
            reasons.append('too_narrow_or_broad_feature')
        competitors = [p for p, pr in zip(peaks, properties['prominences'])
                       if p != idx and pr >= prominence * thresholds['competing_peak_fraction']]
        if competitors:
            reasons.append('ambiguous_competing_features')
        detrended = signal.detrend(signed)
        local, _ = signal.find_peaks(detrended, prominence=thresholds['min_prominence_db'])
        if not any(abs(f[p] - f[idx]) <= spec['absolute_match_hz'] for p in local):
            reasons.append('contrast_explained_by_spectral_slope')
    if absolute is not None:
        log_power = 10 * np.log10(np.maximum(absolute, 1e-30))
        slope = np.polyval(np.polyfit(np.log10(freqs), log_power, 1), np.log10(freqs))
        residual = log_power - slope
        peaks, _ = signal.find_peaks(residual, prominence=thresholds['min_absolute_prominence_db'])
        matches = [p for p in peaks if abs(freqs[p] - f[idx]) <= spec['absolute_match_hz']]
        if matches:
            p = min(matches, key=lambda p: abs(freqs[p] - f[idx]))
            result['absolute_peak_hz'] = float(freqs[p])
        else:
            reasons.append('no_absolute_spectral_corroboration')
    return result


def assess(freqs, trials, absolute, spec, cfg, n_eligible, n_roi):
    thresholds = cfg['reliability']
    n = len(trials)
    spectrum = trials.mean(axis=0) if n else np.full(len(freqs), np.nan)
    abs_mean = absolute.mean(axis=0) if n else None
    found = feature(freqs, spectrum, spec, thresholds, abs_mean)
    reasons = list(found['reasons'])
    retention = n / n_eligible if n_eligible else 0
    if n < thresholds['min_epochs']:
        reasons.append('insufficient_epochs')
    if retention < thresholds['min_retention']:
        reasons.append('low_retention')
    if n_roi < cfg['preprocessing']['min_roi_channels']:
        reasons.append('insufficient_roi_channels')
    split_results = {}
    boot = []
    effects = []
    if n >= 4:
        for label, halves in [('chronological', (np.arange(n//2), np.arange(n//2, n))),
                               ('odd_even', (np.arange(0, n, 2), np.arange(1, n, 2)))]:
            hs = [feature(freqs, trials[h].mean(0), spec, thresholds, absolute[h].mean(0)) for h in halves]
            diff = abs(hs[0]['candidate_hz'] - hs[1]['candidate_hz']) if all(h['candidate_hz'] is not None for h in hs) else None
            split_results[label] = dict(halves=hs, difference_hz=diff)
            if any(h['reasons'] for h in hs) or diff is None or diff > spec['max_split_hz']:
                reasons.append(f'{label}_split_unstable_or_missing')
        rng = np.random.default_rng(cfg['seed'])
        block = min(thresholds['bootstrap_block_epochs'], n)
        center_idx = int(np.argmin(abs(freqs - found['candidate_hz']))) if found['candidate_hz'] is not None else 0
        # Circular moving-block resampling preserves short-range trial dependence.
        for _ in range(thresholds['bootstrap_iterations']):
            starts = rng.integers(0, n, size=int(np.ceil(n/block)))
            inds = ((starts[:, None] + np.arange(block)) % n).ravel()[:n]
            avg = trials[inds].mean(0)
            estimate = feature(freqs, avg, spec, thresholds, absolute[inds].mean(0))
            if not estimate['reasons']:
                boot.append(estimate['candidate_hz'])
            effects.append(float(avg[center_idx]))
    detection = len(boot) / thresholds['bootstrap_iterations']
    ci = np.percentile(boot, [2.5, 97.5]).tolist() if boot else None
    effect_ci = np.percentile(effects, [2.5, 97.5]).tolist() if effects else None
    if detection < thresholds['min_bootstrap_detection_fraction']:
        reasons.append('bootstrap_feature_often_missing')
    if ci is None or ci[1] - ci[0] > spec['max_ci_hz']:
        reasons.append('bootstrap_frequency_uncertain')
    if effect_ci is None or (spec['direction'] == -1 and effect_ci[1] >= 0) or (spec['direction'] == 1 and effect_ci[0] <= 0):
        reasons.append('effect_direction_uncertain')
    reasons = sorted(set(reasons))
    reliable = not reasons
    return dict(**found, reliable=reliable, failure_reasons=reasons,
                status='reliable_candidate_requires_pi_approval' if reliable else 'unreliable_no_individualized_frequency',
                individualized_frequency_hz=found['candidate_hz'] if reliable else None,
                approved_stimulation_frequency_hz=None, fallback_option_hz=spec['fallback_option_hz'],
                n_eligible=n_eligible, n_retained=n, retention_fraction=retention,
                splits=split_results, bootstrap_detection_fraction=detection,
                bootstrap_ci_hz=ci, effect_ci_db=effect_ci,
                bootstrap_valid_iterations=len(boot),
                qc='PASS' if reliable else 'FAIL',
                warnings=['below_recommended_epoch_count'] if n < thresholds['recommended_epochs'] else [])


def estimate(clean, filtered, timestamps, fs, names, roi, refs, logs, spec, config):
    epochs, times, logs = epoch_data(clean, filtered, timestamps, fs, names, roi, refs, logs, spec, config['preprocessing'])
    freqs, trials, base, active, plot_times, tf = spectra(epochs, times, fs, spec)
    absolute = base if spec['direction'] < 0 else active
    result = assess(freqs, trials, absolute, spec, config, sum(x['eligible'] for x in logs), len(roi))
    result['exclusions'] = dict(Counter(x['reason'] for x in logs if x['reason']))
    result['roi_channels'] = [names[i] for i in roi]
    result['reference_channels'] = [names[i] for i in refs]
    result['resolution'] = dict(grid_step_hz=spec['grid_hz'][2],
                                wavelet_power_fwhm_hz_at_candidate=(1.665 * result['candidate_hz'] / spec['cycles']) if result['candidate_hz'] else None,
                                interpretation='grid spacing is not independent frequency resolution')
    return result, dict(freqs=freqs, trials=trials, base=base, active=active, times=plot_times, tfr=tf), epochs, times


def preview(result):
    """No protocol labels or condition assignments; cannot authorize stimulation."""
    return dict(schema='rhythm-recommendation-preview-v1', mode='dry_run_only',
                subject=result['subject'], session=result['session'], task=result['task'],
                phase=result['phase'], run=result['run'], estimand=result['estimand'],
                candidate_frequency_hz=result.get('individualized_frequency_hz'),
                approved_stimulation_frequency_hz=None,
                fallback_option_hz=result.get('fallback_option_hz'),
                requires_pi_approval=True, failure_reasons=result.get('failure_reasons', []),
                analysis_version=result['analysis_version'], input_sha256=result.get('input_sha256'))
