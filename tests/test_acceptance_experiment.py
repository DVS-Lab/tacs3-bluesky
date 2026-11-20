"""Meaningful guardrails for the optional policy experiment, not tuned outcomes."""
import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
module_spec = importlib.util.spec_from_file_location('calibrate_acceptance', ROOT/'validation/experiments/calibrate_acceptance.py')
experiment = importlib.util.module_from_spec(module_spec)
module_spec.loader.exec_module(experiment)


def test_development_and_heldout_have_disjoint_seeds_and_frequencies():
    dev = list(experiment.cases('development'))
    held = list(experiment.cases('heldout'))
    assert len(dev) == 216 and len(held) == 324
    assert not {r['seed'] for r in dev} & {r['seed'] for r in held}
    for key in experiment.KEYS:
        assert not {r['frequency_hz'] for r in dev if r['estimand'] == key and r['scenario'] == 'known'} & {
            r['frequency_hz'] for r in held if r['estimand'] == key and r['scenario'] == 'known'}


@pytest.mark.parametrize('shape', ['flat', 'boundary', 'wrong_sign', 'missing_absolute'])
def test_experimental_policy_preserves_basic_rejection_guards(shape):
    cfg = json.loads((ROOT/'code/rhythm_validation_config.json').read_text())
    f = np.arange(8, 40.5, .5)
    center = 13 if shape == 'boundary' else 21
    g = np.exp(-.5*((f-center)/1.8)**2)
    contrast = np.zeros(len(f)) if shape == 'flat' else (3*g if shape == 'wrong_sign' else -3*g)
    absolute = 1/f if shape == 'missing_absolute' else 1+5*g
    r = experiment.full_grid_feature(f, contrast, cfg['estimands']['response_beta_erd'], cfg['reliability'], absolute)
    assert r['reasons']


def test_experimental_assessment_cannot_change_default_feature_function():
    cfg = json.loads((ROOT/'code/rhythm_validation_config.json').read_text())
    cfg['reliability']['bootstrap_iterations'] = 10
    f = np.arange(8, 40.5, .5)
    g = np.exp(-.5*((f-21)/1.8)**2)
    before = experiment.core.feature
    result = experiment.evaluate('full_grid_localization', f, np.tile(-3*g, (80,1)),
                                 np.tile(1+5*g, (80,1)), cfg['estimands']['response_beta_erd'], cfg, 80, 3)
    assert experiment.core.feature is before
    assert result['reliable'] and result['approved_stimulation_frequency_hz'] is None


def test_heldout_refuses_changed_sources(tmp_path):
    with pytest.raises(ValueError, match='Source/config changed'):
        experiment.benchmark('heldout', tmp_path, {}, {'source_sha256': {}})
