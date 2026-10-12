import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
CODE_DIR = REPO_ROOT / "code"
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

from rhythm_estimator import EEGData, estimate_rhythm, load_config
from select_stimulation_frequency import select_stimulation_frequency


def make_config(tmp_path: Path) -> dict:
    config = copy.deepcopy(load_config(CODE_DIR / "config.json"))
    config["paths"]["data_dir"] = str(tmp_path / "data")
    config["stimulation"]["test_mode"] = True
    config["eeg_preprocessing"]["blink_rejection"] = False
    for key, spec in config["rhythm_estimands"].items():
        spec["bootstrap_iterations"] = 80
        spec["hard_min_usable_epochs"] = 20
        spec["recommended_min_usable_epochs"] = 30
        spec["min_usable_epoch_fraction"] = 0.5
        spec["min_peak_prominence_z"] = 0.4
    return config


def make_synthetic_events_and_eeg(
    *,
    n_epochs: int = 96,
    rhythm_key: str = "bandit_feedback_theta",
    freq_hz: float = 6.5,
    second_half_freq_hz: float | None = None,
    amplitude_uv: float = 35.0,
    noise_uv: float = 6.0,
) -> tuple[EEGData, list[dict]]:
    rng = np.random.default_rng(7)
    srate = 250.0
    channel_names = ["Fz", "FCz", "Cz", "F3", "F4", "Pz", "O1", "O2"]
    spacing_sec = 3.0
    spacing_samples = int(spacing_sec * srate)
    n_samples = spacing_samples * (n_epochs + 3)
    timestamps = np.arange(n_samples, dtype=float) / srate
    samples = rng.normal(0.0, noise_uv, size=(n_samples, len(channel_names)))
    if "beta" in rhythm_key:
        epoch_tmin, epoch_tmax = -1.5, 1.0
        burst_window = (-0.55, -0.05)
        time_column = "choice_onset_lsl_time"
        marker_column = None
    else:
        epoch_tmin, epoch_tmax = -1.0, 1.5
        burst_window = (0.2, 0.8)
        time_column = "feedback_onset_lsl_time"
        marker_column = "feedback_marker"
    epoch_time = np.arange(int((epoch_tmax - epoch_tmin) * srate), dtype=float) / srate + epoch_tmin
    burst_mask = (epoch_time >= burst_window[0]) & (epoch_time <= burst_window[1])
    taper = np.sin(np.linspace(0, np.pi, int(np.sum(burst_mask))))
    roi_indices = [0, 1, 2, 3, 4]
    rows = []
    for epoch_index in range(n_epochs):
        center = spacing_samples * (epoch_index + 1)
        event_time = timestamps[center]
        this_freq = freq_hz
        if second_half_freq_hz is not None and epoch_index >= n_epochs // 2:
            this_freq = second_half_freq_hz
        burst = np.sin(2 * np.pi * this_freq * epoch_time[burst_mask]) * taper * amplitude_uv
        start = center + int(epoch_tmin * srate)
        stop = start + len(epoch_time)
        if 0 <= start and stop <= n_samples:
            for channel_index in roi_indices:
                samples[start:stop, channel_index][burst_mask] += burst
        row = {
            time_column: event_time,
            "run_start_lsl_time": 0.0,
            "outcome": "win" if epoch_index % 2 == 0 else "loss",
        }
        if marker_column:
            row[marker_column] = 31 if epoch_index % 2 == 0 else 32
        rows.append(row)
    eeg = EEGData(samples=samples, timestamps=timestamps, channel_names=channel_names, sampling_rate_hz=srate, metadata={})
    return eeg, rows


class RhythmEstimatorTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmpdir.name)
        self.config = make_config(self.tmp_path)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_reliable_feedback_theta_6_5_hz(self):
        eeg, events = make_synthetic_events_and_eeg(freq_hz=6.5)
        result, _ = estimate_rhythm(eeg, events, self.config, subject_id="001", session_id="001", rhythm_key="bandit_feedback_theta")
        self.assertTrue(result["reliable"], result["decision"]["reason"])
        self.assertEqual(result["itheta_hz_rounded"], 6.5)
        self.assertEqual(result["frequency_to_use_hz"], 6.5)

    def test_reliable_decision_beta(self):
        eeg, events = make_synthetic_events_and_eeg(rhythm_key="bandit_decision_beta", freq_hz=21.0)
        result, _ = estimate_rhythm(eeg, events, self.config, subject_id="001", session_id="001", rhythm_key="bandit_decision_beta")
        self.assertTrue(result["reliable"], result["decision"]["reason"])
        self.assertEqual(result["ibeta_hz_rounded"], 21.0)

    def test_noisy_no_peak_falls_back(self):
        eeg, events = make_synthetic_events_and_eeg(amplitude_uv=0.0, noise_uv=20.0)
        result, _ = estimate_rhythm(eeg, events, self.config, subject_id="001", session_id="001", rhythm_key="bandit_feedback_theta")
        self.assertFalse(result["reliable"])
        self.assertEqual(result["frequency_to_use_hz"], 6.0)
        self.assertEqual(result["rhythm_source"], "fallback_fixed_6hz")

    def test_edge_peak_is_unreliable(self):
        eeg, events = make_synthetic_events_and_eeg(freq_hz=4.0)
        result, _ = estimate_rhythm(eeg, events, self.config, subject_id="001", session_id="001", rhythm_key="bandit_feedback_theta")
        self.assertFalse(result["reliable"])
        self.assertIn("edge", result["decision"]["reason"])

    def test_split_half_disagreement_falls_back(self):
        eeg, events = make_synthetic_events_and_eeg(freq_hz=5.0, second_half_freq_hz=7.5)
        result, _ = estimate_rhythm(eeg, events, self.config, subject_id="001", session_id="001", rhythm_key="bandit_feedback_theta")
        self.assertFalse(result["reliable"])
        self.assertEqual(result["frequency_to_use_hz"], 6.0)

    def test_too_few_epochs_is_unreliable(self):
        eeg, events = make_synthetic_events_and_eeg(n_epochs=5, freq_hz=6.5)
        result, _ = estimate_rhythm(eeg, events, self.config, subject_id="001", session_id="001", rhythm_key="bandit_feedback_theta")
        self.assertFalse(result["reliable"])
        self.assertIn("hard minimum", result["decision"]["reason"])

    def test_selection_reads_reliable_and_fallback_json(self):
        qc = self.tmp_path / "data" / "sub-001" / "qc"
        qc.mkdir(parents=True)
        theta_json = qc / "sub-001_ses-001_bandit_feedback_theta_estimate.json"
        theta_json.write_text(
            json.dumps(
                {
                    "reliable": True,
                    "frequency_to_use_hz": 6.5,
                    "rhythm_source": "reliable_itheta",
                    "decision": {"reason": "Reliable feedback-locked theta estimate."},
                }
            ),
            encoding="utf-8",
        )
        decision = select_stimulation_frequency("001", "001", self.config, rhythm_key="bandit_feedback_theta", search_root=self.tmp_path / "data")
        self.assertEqual(decision.frequency_to_use_hz, 6.5)
        self.assertEqual(decision.rhythm_source, "reliable_itheta")

        theta_json.write_text(
            json.dumps(
                {
                    "reliable": False,
                    "frequency_to_use_hz": 6.0,
                    "rhythm_source": "fallback_fixed_6hz",
                    "decision": {"reason": "Unreliable estimate."},
                }
            ),
            encoding="utf-8",
        )
        decision = select_stimulation_frequency("001", "001", self.config, rhythm_key="bandit_feedback_theta", search_root=self.tmp_path / "data")
        self.assertEqual(decision.frequency_to_use_hz, 6.0)
        self.assertEqual(decision.rhythm_source, "fallback_fixed_6hz")

    def test_sst_test_mode_saves_events(self):
        code_dir = CODE_DIR
        config_path = self.tmp_path / "config.json"
        config_path.write_text(json.dumps(self.config), encoding="utf-8")
        command = [
            sys.executable,
            str(code_dir / "sst_main.py"),
            "--config",
            str(config_path),
            "--mode",
            "LOCALIZER_SST",
            "--subject",
            "001",
            "--session",
            "001",
            "--test-mode",
        ]
        subprocess.run(command, check=True, cwd=code_dir, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        events = list((self.tmp_path / "data" / "sub-001").glob("*task-SST*_events.csv"))
        markers = list((self.tmp_path / "data" / "sub-001" / "logs").glob("*task-SST_markers.jsonl"))
        self.assertTrue(events)
        self.assertTrue(markers)


if __name__ == "__main__":
    unittest.main()
