"""Backward-compatible theta estimator imports.

Jimmy's current bandit workflow imports ``theta_estimator`` directly. The
implementation now lives in ``rhythm_estimator`` so theta, beta, bandit, and SST
estimands use the same reliability-gated code path.
"""

from rhythm_estimator import (  # noqa: F401
    EEGData,
    RhythmEstimateArtifacts,
    estimate_feedback_theta,
    estimate_feedback_theta_from_files,
    load_config,
    load_eeg,
    load_events,
)
