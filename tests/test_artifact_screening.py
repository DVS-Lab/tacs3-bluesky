"""Continuous-signal challenges for artifact screening, independent of peak gates."""
import json
from pathlib import Path
import sys

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'code'))
from rhythm_validation_core import epoch_data, preprocess, ocular_screen, spectra
from rhythm_validation_carrier import carrier_spectra

ROOT = Path(__file__).resolve().parents[1]
NAMES = ['F3', 'Fp1', 'FCz', 'FT7', 'F4', 'P4', 'P3', 'EXT']


def run_signal(raw, fs, event=20):
    cfg = json.loads((ROOT/'code/rhythm_validation_config.json').read_text())
    clean, filtered, roi, refs, qc = preprocess(raw, fs, NAMES, cfg['preprocessing'])
    logs = [dict(eligible=True, event_sec=event, reason='', retained=False)]
    ep, _, logs = epoch_data(clean, filtered, np.arange(len(raw))/fs, fs, NAMES,
                            roi, refs, logs, cfg['estimands']['feedback_theta_enhancement'],
                            cfg['preprocessing'], raw=raw)
    return ep, logs[0], qc


@pytest.mark.parametrize('fs', [100, 500])
def test_small_blink_spread_below_general_amplitude_gate_is_rejected(fs):
    rng = np.random.default_rng(89)
    t = np.arange(60*fs)/fs
    raw = rng.normal(0, 2, (len(t), 8))
    blink = np.exp(-.5*((t-20)/.07)**2)
    raw[:, 1] += 100*blink
    raw[:, 0] += 55*blink
    raw[:, 2] += 40*blink
    epochs, log, qc = run_signal(raw, fs)
    # The generic 150-uV threshold alone cannot reject this signal.
    assert log['filtered_max_channel_ptp_uv'] < 150
    assert not qc['F3']['bad']
    assert not len(epochs)
    assert log['reason'] == 'ocular_artifact_spreads_to_roi'
    assert log['ocular_local_event_count'] >= 1
    assert 'F3' in log['ocular_local_spread_channels']


@pytest.mark.parametrize('fs', [100, 500])
def test_isolated_fp1_deflection_does_not_erase_clean_roi(fs):
    rng = np.random.default_rng(89)
    t = np.arange(60*fs)/fs
    raw = rng.normal(0, 2, (len(t), 8))
    raw[:, 1] += 100*np.exp(-.5*((t-20)/.07)**2)
    epochs, log, _ = run_signal(raw, fs)
    assert len(epochs) == 1
    assert log['warning'] == 'fp1_artifact_without_detected_roi_spread'
    assert not log['ocular_local_spread_channels']


def test_smooth_removable_drift_is_diagnosed_without_blanket_rejection():
    fs = 100
    rng = np.random.default_rng(120)
    t = np.arange(60*fs)/fs
    raw = rng.normal(0, 2, (len(t), 8))
    raw[:, 0] += 600*np.sin(2*np.pi*.1*t)
    epochs, log, qc = run_signal(raw, fs)
    assert len(epochs) == 1
    assert log['raw_max_channel_ptp_uv'] > 500
    assert log['filtered_max_channel_ptp_uv'] < 20
    assert log['raw_large_filtered_below_threshold']
    assert qc['F3']['raw_window_ptp_p95_uv'] > 500
    assert qc['F3']['raw_window_abs_slope_p95_uv_per_sec'] > 100
    assert not qc['F3']['bad']


def test_transient_bad_reference_window_rejects_epoch_even_if_channel_global_qc_passes():
    fs = 100
    rng = np.random.default_rng(55)
    t = np.arange(60*fs)/fs
    raw = rng.normal(0, 2, (len(t), 8))
    # P4 contributes to the reference; a short excursion must not spread silently.
    raw[:, 5] += 600*np.exp(-.5*((t-20)/.035)**2)
    epochs, log, qc = run_signal(raw, fs)
    assert not qc['P4']['bad']
    assert not len(epochs)
    assert 'P4' in log['reason']


def test_clean_theta_is_not_identified_as_a_blink():
    fs = 100
    rng = np.random.default_rng(39)
    t = np.arange(60*fs)/fs
    raw = rng.normal(0, 2, (len(t), 8))
    for channel in [0, 2, 4]:
        raw[:, channel] += 15*np.sin(2*np.pi*6*t + channel)
    epochs, log, _ = run_signal(raw, fs)
    assert len(epochs) == 1
    assert log['ocular_local_event_count'] == 0


@pytest.mark.parametrize('quality', ['missing', 'flat', 'nonfinite', 'noisy'])
def test_missing_or_bad_ocular_proxy_is_explicit(quality):
    cfg = json.loads((ROOT/'code/rhythm_validation_config.json').read_text())
    rng = np.random.default_rng(50)
    raw = rng.normal(0, 2, (6000, 8))
    names = NAMES.copy()
    if quality == 'missing': names[1] = 'unused'
    elif quality == 'flat': raw[:, 1] = 0
    elif quality == 'nonfinite': raw[100, 1] = np.nan
    else: raw[:, 1] = rng.normal(0, 800, len(raw))
    clean, filtered, roi, refs, qc = preprocess(raw, 100, names, cfg['preprocessing'])
    _, _, status = ocular_screen(clean, filtered, 100, names, roi, cfg['preprocessing'], raw=raw)
    assert status != 'Fp1_proxy_screened'
    assert ('poor_quality' if quality == 'noisy' else 'unavailable') in status


def test_highpass_removes_drift_without_shifting_known_theta_carrier():
    fs = 100
    rng = np.random.default_rng(341)
    t = np.arange(60*fs)/fs
    raw = rng.normal(0, 2, (len(t), 8))
    for channel in [0, 2, 4]:
        raw[:, channel] += 15*np.sin(2*np.pi*6*t + channel)
    clean_epochs, _, _ = run_signal(raw.copy(), fs)
    raw[:, 0] += 600*np.sin(2*np.pi*.1*t)
    drift_epochs, log, _ = run_signal(raw, fs)
    assert len(drift_epochs) == len(clean_epochs) == 1
    cfg = json.loads((ROOT/'code/rhythm_validation_config.json').read_text())
    spec = cfg['estimands']['feedback_theta_enhancement']
    f, power = carrier_spectra(clean_epochs, fs, spec)
    _, drift_power = carrier_spectra(drift_epochs, fs, spec)
    assert f[power[0].argmax()] == f[drift_power[0].argmax()]
    assert abs(f[drift_power[0].argmax()]-6) <= .25
    assert log['raw_large_filtered_below_threshold']


def test_repeated_ocular_theta_bursts_cannot_be_exported_as_individualized_frequency():
    """An event-locked narrow ocular waveform can otherwise look reproducible."""
    from rhythm_validation_core import estimate
    cfg = json.loads((ROOT/'code/rhythm_validation_config.json').read_text())
    fs = 100
    events = 4 + 6*np.arange(44)
    t = np.arange(round((events[-1]+4)*fs))/fs
    rng = np.random.default_rng(983)
    raw = rng.normal(0, 1, (len(t), 8))
    for event in events:
        relative = t-event-.45
        ocular = np.exp(-.5*(relative/.25)**2)*np.cos(2*np.pi*6*relative)
        raw[:, 1] += 65*ocular
        raw[:, 0] += 30*ocular
        raw[:, 2] += 25*ocular
    clean, filtered, roi, refs, _ = preprocess(raw, fs, NAMES, cfg['preprocessing'])
    logs = [dict(eligible=True, event_sec=float(e), reason='', retained=False) for e in events]
    result, _, _, _ = estimate(clean, filtered, t, fs, NAMES, roi, refs, logs,
                               cfg['estimands']['feedback_theta_enhancement'], cfg, raw=raw)
    assert result['n_retained'] == 0
    assert result['exclusions']['ocular_artifact_spreads_to_roi'] == len(events)
    assert not result['reliable']
    assert result['individualized_frequency_hz'] is None
    assert result['approved_stimulation_frequency_hz'] is None
