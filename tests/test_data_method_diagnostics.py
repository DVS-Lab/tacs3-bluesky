"""Distinguish missing samples, estimator error, and acceptance-policy error."""
import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('data_method_diagnostics', ROOT/'validation/experiments/diagnose_data_vs_method.py')
diag = importlib.util.module_from_spec(spec)
spec.loader.exec_module(diag)


def config():
    return json.loads((ROOT/'code/rhythm_validation_config.json').read_text())


def test_trial_scarcity_is_not_attributed_to_eeg_rejection():
    assert diag.stage(20, 0, 0, config()) == 'too_few_eligible_trials_before_artifact_screening'
    assert diag.stage(120, 0, 1, config()) == 'channel_screening_limited'
    assert diag.stage(120, 10, 3, config()) == 'retained_trial_yield_limited'
    assert diag.stage(120, 110, 3, config()) == 'sufficient_trial_yield_assess_target_and_method_separately'


@pytest.mark.parametrize('key,frequency',[('response_beta_erd',21),('feedback_theta_enhancement',6)])
def test_native_rate_clean_probe_has_known_fourier_and_absolute_peak(key,frequency):
    cfg=config();spec=cfg['estimands'][key];fs=500
    cfg['reliability']['bootstrap_iterations']=10
    times=np.arange(round(np.diff(spec['epoch_sec'])[0]*fs))/fs+spec['epoch_sec'][0]
    probe=diag.probe_epochs(times,40,3,spec,frequency,10,555)
    assert np.max(np.abs(probe))<=10
    ep=probe+np.random.default_rng(556).normal(0,1,probe.shape)
    before=ep.copy()
    r=diag.quantify(ep,times,fs,spec,cfg)
    np.testing.assert_array_equal(ep,before)
    assert abs(r['fourier_peak_hz']-frequency)<.3
    assert abs(r['absolute_anchor_candidate_hz']-frequency)<=.5
    assert r['approved_stimulation_frequency_hz'] is None
    # Deliberately do not enshrine the existing contrast-extremum failure as a
    # required result: a future repair is allowed to recover the true frequency.


def test_absolute_anchor_does_not_create_a_peak_from_a_power_law():
    cfg=config();f=np.arange(8,40.5,.5)
    r=diag.absolute_anchor(f,-np.ones(len(f)),1/f**2,cfg['estimands']['response_beta_erd'],cfg['reliability'])
    assert r['absolute_anchor_candidate_hz'] is None


def test_spatial_metrics_separate_shared_signal_from_independent_channels():
    sp = importlib.util.spec_from_file_location('spatial_diagnostics', ROOT/'validation/experiments/audit_eeg_spatial_quality.py')
    spatial = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(spatial)
    rng = np.random.default_rng(23)
    independent = rng.normal(size=(10000,6))
    shared = rng.normal(size=(10000,1)) + .02*independent
    def measure(x):
        return spatial.spatial_metrics(x, x-x.mean(axis=1,keepdims=True), [0,1,2], list(range(6)))
    a, b = measure(independent), measure(shared)
    assert a['first_component_variance_fraction'] < .20
    assert a['residual_std_fraction'] > .8
    assert b['median_pairwise_correlation'] > .99
    assert b['first_component_variance_fraction'] > .99
    assert b['residual_std_fraction'] < .03
