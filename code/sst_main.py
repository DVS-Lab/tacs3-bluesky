#!/usr/bin/env python3
"""Stop Signal Task with task-evoked rhythm localizer/stimulation support.

This entry point adapts the Scan-SST task from DVS-Lab/gambling-2025 while
adding the same practical StarStim/NIC-2 workflow used by the bandit task:
event markers, optional local EEG recording, individualized rhythm selection,
operator confirmation, and hardware-free test mode.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime
import json
import os
from pathlib import Path
import random
import sys
import time
from typing import Any

import numpy as np

from eeg_lsl_recorder import LSLEEGRecorder, save_recording_summary
from select_stimulation_frequency import select_stimulation_frequency
from task_markers import TaskMarkerLogger, lsl_clock

try:
    from psychopy import core, event, gui, visual

    PSYCHOPY_AVAILABLE = True
except ImportError:  # pragma: no cover - operator dependency
    core = event = gui = visual = None
    PSYCHOPY_AVAILABLE = False


SUPPORTED_SST_MODES = {
    "LOCALIZER_SST",
    "ITHETA_TACS",
    "IBETA_TACS",
    "FIXED_THETA_TACS",
    "FIXED_BETA_TACS",
    "SHAM",
}


def normalize_id(value: str, prefix: str) -> str:
    return str(value).replace(prefix, "").strip()


def normalize_mode(mode: str | None) -> str:
    value = (mode or "LOCALIZER_SST").strip().upper()
    aliases = {
        "SST_LOCALIZER": "LOCALIZER_SST",
        "LOCALIZER": "LOCALIZER_SST",
        "IBETA": "IBETA_TACS",
        "ITHEATA_TACS": "ITHETA_TACS",
        "FIXED_THETA": "FIXED_THETA_TACS",
        "FIXED_BETA": "FIXED_BETA_TACS",
    }
    value = aliases.get(value, value)
    if value not in SUPPORTED_SST_MODES:
        raise ValueError(f"Unsupported SST mode {mode!r}. Expected one of {sorted(SUPPORTED_SST_MODES)}.")
    return value


def load_config(config_path: str | Path | None = None) -> dict[str, Any]:
    if config_path is None:
        config_path = Path(__file__).resolve().parent / "config.json"
    with Path(config_path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


class SSTTask:
    def __init__(self, config: dict[str, Any], cli_args: argparse.Namespace):
        self.config = config
        self.cli_args = cli_args
        self.mode = normalize_mode(cli_args.mode or config.get("sst", {}).get("mode", "LOCALIZER_SST"))
        self.test_mode = bool(cli_args.test_mode or config.get("stimulation", {}).get("test_mode", False))
        self.auto_respond = bool(cli_args.auto_respond or self.test_mode)
        self.subject_id = normalize_id(cli_args.subject or "", "sub-")
        self.session_id = normalize_id(cli_args.session or "001", "ses-")
        self.run_number = int(cli_args.run or 1)
        self.run_label = "run-localizer" if self.mode == "LOCALIZER_SST" else f"run-{self.run_number:02d}"
        self.date_label = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self.results: list[dict[str, Any]] = []
        self.operator_confirmation: dict[str, Any] = {}
        self.rhythm_decision = self._select_frequency()
        self.event_logger = TaskMarkerLogger(config.get("eeg_recording", {}).get("marker_stream_name", "LSLOutletStreamName-Markers"))
        self.eeg_recorder: LSLEEGRecorder | None = None
        self.eeg_recording_saved = False
        data_root = Path(config.get("paths", {}).get("data_dir", "../data"))
        self.data_dir = (Path(__file__).resolve().parent / data_root).resolve() / f"sub-{self.subject_id}"
        self.eeg_dir = self.data_dir / "eeg"
        self.logs_dir = self.data_dir / "logs"
        self.qc_dir = self.data_dir / "qc"
        for path in (self.data_dir, self.eeg_dir, self.logs_dir, self.qc_dir):
            path.mkdir(parents=True, exist_ok=True)
        self.marker_log_path = self.logs_dir / f"sub-{self.subject_id}_ses-{self.session_id}_{self.run_label}_task-SST_markers.jsonl"
        self.eeg_summary_path = self.logs_dir / f"sub-{self.subject_id}_ses-{self.session_id}_{self.run_label}_task-SST_eeg_summary.json"
        self.run_start_lsl_time: float | None = None
        self.run_end_lsl_time: float | None = None
        self.run_start_task_time = 0.0
        self.run_end_task_time: float | None = None

    def _select_frequency(self) -> dict[str, Any]:
        if self.mode == "ITHETA_TACS":
            decision = select_stimulation_frequency(
                self.subject_id,
                self.session_id,
                self.config,
                rhythm_key="sst_stop_theta",
                manual_override_hz=self.cli_args.frequency,
                manual_override_reason="CLI frequency override" if self.cli_args.frequency else None,
            )
            return decision.to_log_dict()
        if self.mode == "IBETA_TACS":
            decision = select_stimulation_frequency(
                self.subject_id,
                self.session_id,
                self.config,
                rhythm_key="sst_response_beta",
                manual_override_hz=self.cli_args.frequency,
                manual_override_reason="CLI frequency override" if self.cli_args.frequency else None,
            )
            return decision.to_log_dict()
        if self.mode == "FIXED_THETA_TACS":
            frequency = float(self.cli_args.frequency or self.config.get("stimulation_frequency_selection", {}).get("default_fixed_theta_hz", 6.0))
            return self._fixed_decision("sst_stop_theta", "participant_specific_sst_stop_theta", "fixed_6hz", frequency)
        if self.mode == "FIXED_BETA_TACS":
            frequency = float(self.cli_args.frequency or self.config.get("stimulation_frequency_selection", {}).get("default_fixed_beta_hz", 20.0))
            return self._fixed_decision("sst_response_beta", "participant_specific_sst_response_beta", "fixed_beta", frequency)
        if self.mode == "SHAM":
            return {
                "rhythm_key": "none",
                "rhythm_label": "none",
                "rhythm_source": "sham",
                "rhythm_reliable": False,
                "rhythm_reliability_reason": "Sham condition.",
                "rhythm_estimate_file": "",
                "frequency_to_use_hz": None,
                "protocol_label_to_show": "SHAM",
                "theta_source": "sham",
                "theta_reliable": False,
                "theta_reliability_reason": "Sham condition.",
                "theta_estimate_file": "",
            }
        return {
            "rhythm_key": "none",
            "rhythm_label": "none",
            "rhythm_source": "none",
            "rhythm_reliable": False,
            "rhythm_reliability_reason": "No stimulation during SST localizer.",
            "rhythm_estimate_file": "",
            "frequency_to_use_hz": None,
            "protocol_label_to_show": "LOCALIZER_NO_STIM",
            "theta_source": "none",
            "theta_reliable": False,
            "theta_reliability_reason": "No stimulation during SST localizer.",
            "theta_estimate_file": "",
        }

    def _fixed_decision(self, rhythm_key: str, rhythm_label: str, source: str, frequency: float) -> dict[str, Any]:
        protocol_prefix = "FIXED_BETA_TACS" if "beta" in rhythm_key else "FIXED_THETA_TACS"
        return {
            "rhythm_key": rhythm_key,
            "rhythm_label": rhythm_label,
            "rhythm_source": source,
            "rhythm_reliable": False,
            "rhythm_reliability_reason": "Fixed-frequency control condition.",
            "rhythm_estimate_file": "",
            "frequency_to_use_hz": frequency,
            "protocol_label_to_show": f"{protocol_prefix}_{frequency:.1f}Hz",
            "theta_source": source if "theta" in rhythm_key else "none",
            "theta_reliable": False,
            "theta_reliability_reason": "Fixed-frequency theta control condition." if "theta" in rhythm_key else "",
            "theta_estimate_file": "",
            "beta_source": source if "beta" in rhythm_key else "none",
            "beta_reliable": False,
            "beta_reliability_reason": "Fixed-frequency beta control condition." if "beta" in rhythm_key else "",
            "beta_estimate_file": "",
        }

    def _operator_setup_summary(self) -> list[str]:
        frequency = self.rhythm_decision.get("frequency_to_use_hz")
        lines = [
            f"Subject: sub-{self.subject_id}",
            f"Session: ses-{self.session_id}",
            f"Run: {self.run_label}",
            f"Mode: {self.mode}",
            f"Protocol label: {self.rhythm_decision.get('protocol_label_to_show', '')}",
            f"Rhythm target: {self.rhythm_decision.get('rhythm_label', 'none')}",
            f"Rhythm source: {self.rhythm_decision.get('rhythm_source', 'none')}",
            f"Frequency to use: {frequency if frequency is not None else 'N/A'} Hz",
            f"Reason: {self.rhythm_decision.get('rhythm_reliability_reason', '')}",
        ]
        if self.mode in {"ITHETA_TACS", "FIXED_THETA_TACS"} and frequency is not None:
            lines.append(f"Operator instruction: Load the NIC-2 theta-tACS protocol at {frequency:.1f} Hz.")
        if self.mode in {"IBETA_TACS", "FIXED_BETA_TACS"} and frequency is not None:
            lines.append(f"Operator instruction: Load the NIC-2 beta-tACS protocol at {frequency:.1f} Hz.")
        if self.mode == "SHAM":
            lines.append("Operator instruction: Load the sham protocol and confirm marker 203 when ready.")
        return lines

    def prompt_operator_confirmation(self) -> None:
        if self.mode == "LOCALIZER_SST":
            return
        for line in self._operator_setup_summary():
            print(line)
        if self.auto_respond:
            self.operator_confirmation = {
                "operator_confirmed_protocol": self.rhythm_decision.get("protocol_label_to_show", ""),
                "operator_confirmed_frequency_hz": self.rhythm_decision.get("frequency_to_use_hz"),
            }
            return
        protocol = input("Operator-confirmed protocol label: ") or self.rhythm_decision.get("protocol_label_to_show", "")
        default_frequency = self.rhythm_decision.get("frequency_to_use_hz")
        entered = input(f"Operator-confirmed frequency in Hz ({default_frequency if default_frequency is not None else 'blank'}): ").strip()
        self.operator_confirmation = {
            "operator_confirmed_protocol": protocol,
            "operator_confirmed_frequency_hz": float(entered) if entered else default_frequency,
        }

    def _start_eeg_recording_if_requested(self) -> None:
        if self.mode != "LOCALIZER_SST":
            return
        eeg_config = self.config.get("eeg_recording", {})
        if not eeg_config.get("record_lsl_eeg_during_localizer", True):
            return
        self.eeg_recorder = LSLEEGRecorder(
            preferred_stream_type=eeg_config.get("preferred_stream_type", "EEG"),
            preferred_stream_name_contains=eeg_config.get("preferred_stream_name_contains", "StarStim"),
        )
        if self.eeg_recorder.start():
            print("Recording StarStim EEG over LSL during SST localizer.")
        else:
            print(f"EEG recording not started: {self.eeg_recorder.status_message}")

    def _stop_eeg_recording(self) -> None:
        if self.eeg_recording_saved or self.eeg_recorder is None:
            return
        eeg_config = self.config.get("eeg_recording", {})
        basename = f"sub-{self.subject_id}_ses-{self.session_id}_{self.run_label}_task-SST_eeg"
        summary = self.eeg_recorder.save(
            self.eeg_dir,
            basename,
            write_raw_csv=eeg_config.get("write_raw_csv", True),
            write_raw_npz=eeg_config.get("write_raw_npz", True),
            extra_metadata={
                "subject_id": f"sub-{self.subject_id}",
                "session_id": f"ses-{self.session_id}",
                "task": "SST",
                "run_label": self.run_label,
                "mode": self.mode,
            },
        )
        save_recording_summary(summary, self.eeg_summary_path)
        self.eeg_recording_saved = True

    def run(self) -> None:
        if not self.subject_id:
            if self.test_mode:
                self.subject_id = "999"
            elif PSYCHOPY_AVAILABLE:
                info = {"Subject Number": ""}
                dlg = gui.DlgFromDict(info, title="Stop Signal Task")
                if not dlg.OK:
                    return
                self.subject_id = normalize_id(info["Subject Number"], "sub-")
            else:
                self.subject_id = input("Subject ID: ")
        self.prompt_operator_confirmation()
        self._start_eeg_recording_if_requested()
        self.run_start_lsl_time = self.event_logger.send(100, "run_start", {"task": "SST", "mode": self.mode, "run": self.run_label})
        self.run_start_task_time = time.time()
        try:
            if self.test_mode:
                self._run_test_mode()
            else:
                self._run_psychopy()
        finally:
            self.run_end_task_time = time.time() - self.run_start_task_time
            self.run_end_lsl_time = self.event_logger.send(200, "run_end", {"task": "SST", "mode": self.mode, "run": self.run_label})
            self.save_events()
            self.event_logger.save(self.marker_log_path)
            self._stop_eeg_recording()

    def _run_test_mode(self) -> None:
        n_trials = int(self.config.get("sst", {}).get("test_mode_trials", 24))
        rng = np.random.default_rng(911)
        ssd = float(self.config.get("sst", {}).get("initial_ssd_sec", 0.25))
        for trial_num in range(1, n_trials + 1):
            direction = "left" if trial_num % 2 else "right"
            is_stop = bool(rng.random() < float(self.config.get("sst", {}).get("stop_probability", 0.3)))
            rt = float(rng.normal(0.42, 0.07))
            responded = not is_stop or rng.random() < 0.5
            self._record_trial(trial_num, direction, is_stop, responded, rt if responded else None, ssd)
            if is_stop:
                ssd = min(float(self.config.get("sst", {}).get("max_ssd_sec", 0.9)), ssd + 0.05 if not responded else ssd - 0.05)
        print(f"SST test mode complete: {n_trials} simulated trials.")

    def _run_psychopy(self) -> None:  # pragma: no cover - requires GUI
        if not PSYCHOPY_AVAILABLE:
            raise RuntimeError("PsychoPy is not installed. Use --test-mode or install psychopy to run SST.")
        script_dir = Path(__file__).resolve().parent / "sst"
        screen = int(self.cli_args.screen if self.cli_args.screen is not None else 0)
        win = visual.Window(size=(1200, 900), color="grey", fullscr=not self.cli_args.windowed, units="pix", screen=screen, allowGUI=False)
        image_stimuli = {
            "left": visual.ImageStim(win, image=str(script_dir / "images" / "left_arrow.png"), size=(518, 300)),
            "right": visual.ImageStim(win, image=str(script_dir / "images" / "right_arrow.png"), size=(518, 300)),
            "left_red": visual.ImageStim(win, image=str(script_dir / "images" / "left_red_arrow.png"), size=(518, 300)),
            "right_red": visual.ImageStim(win, image=str(script_dir / "images" / "right_red_arrow.png"), size=(518, 300)),
        }
        fixation = visual.TextStim(win, text="+", height=40)
        start_msg = visual.TextStim(win, text="Please wait for this round to begin.\n\nRespond quickly to black arrows. Try to stop when the arrow turns red.", color="white", height=36)
        start_msg.draw()
        win.flip()
        event.waitKeys(keyList=("space", "equal"))
        n_trials = int(self.cli_args.trials or self.config.get("sst", {}).get("localizer_trials", 120))
        stop_prob = float(self.config.get("sst", {}).get("stop_probability", 0.3))
        ssd = float(self.config.get("sst", {}).get("initial_ssd_sec", 0.25))
        ssd_step = float(self.config.get("sst", {}).get("ssd_step_sec", 0.05))
        min_ssd = float(self.config.get("sst", {}).get("min_ssd_sec", 0.05))
        max_ssd = float(self.config.get("sst", {}).get("max_ssd_sec", 0.9))
        response_keys = ["1", "2"]
        global_clock = core.Clock()
        for trial_num in range(1, n_trials + 1):
            direction = random.choice(["left", "right"])
            is_stop = random.random() < stop_prob
            isi = random.uniform(*self.config.get("sst", {}).get("isi_range_sec", [0.8, 2.5]))
            iti = random.uniform(*self.config.get("sst", {}).get("iti_range_sec", [1.5, 4.0]))
            fixation.draw()
            win.flip()
            core.wait(isi)
            image_stimuli[direction].draw()
            win.flip()
            stim_onset = global_clock.getTime()
            stim_lsl = self.event_logger.send(110, "sst_go", {"trial_num": trial_num, "stimulus": direction})
            trial_clock = core.Clock()
            responded = False
            response_key = ""
            response_time = None
            stop_presented = False
            stop_lsl_time = None
            while trial_clock.getTime() < float(self.config.get("sst", {}).get("stimulus_duration_sec", 1.5)):
                keys = event.getKeys(keyList=response_keys + ["z"], timeStamped=trial_clock)
                if keys:
                    for key, timestamp in keys:
                        if key == "z":
                            win.close()
                            core.quit()
                        responded = True
                        response_key = key
                        response_time = float(timestamp)
                        break
                if responded:
                    break
                if is_stop and not stop_presented and trial_clock.getTime() >= ssd:
                    image_stimuli[f"{direction}_red"].draw()
                    win.flip()
                    stop_lsl_time = self.event_logger.send(111, "sst_stop", {"trial_num": trial_num, "ssd": ssd})
                    stop_presented = True
            self._record_trial(
                trial_num,
                direction,
                is_stop,
                responded,
                response_time,
                ssd,
                stim_onset_task_time=stim_onset,
                stim_onset_lsl_time=stim_lsl,
                stop_onset_lsl_time=stop_lsl_time,
                response_key=response_key,
            )
            if is_stop:
                ssd = min(max_ssd, ssd + ssd_step) if not responded else max(min_ssd, ssd - ssd_step)
            fixation.draw()
            win.flip()
            core.wait(iti)
        win.close()

    def _record_trial(
        self,
        trial_num: int,
        direction: str,
        is_stop: bool,
        responded: bool,
        rt: float | None,
        ssd: float,
        *,
        stim_onset_task_time: float | None = None,
        stim_onset_lsl_time: float | None = None,
        stop_onset_lsl_time: float | None = None,
        response_key: str = "",
    ) -> None:
        expected_key = "1" if direction == "left" else "2"
        now_task = time.time() - self.run_start_task_time
        stim_onset_task_time = now_task if stim_onset_task_time is None else stim_onset_task_time
        stim_onset_lsl_time = self.event_logger.send(110, "sst_go", {"trial_num": trial_num, "stimulus": direction}) if stim_onset_lsl_time is None else stim_onset_lsl_time
        stop_onset_task_time = stim_onset_task_time + ssd if is_stop else None
        if is_stop:
            stop_onset_lsl_time = stop_onset_lsl_time or self.event_logger.send(111, "sst_stop", {"trial_num": trial_num, "ssd": ssd})
        response_onset_task_time = stim_onset_task_time + rt if responded and rt is not None else None
        response_onset_lsl_time = None
        if responded and rt is not None:
            response_onset_lsl_time = self.event_logger.send(120, "sst_response", {"trial_num": trial_num, "rt": rt})
        go_correct = int((not is_stop) and responded and (response_key in {"", expected_key}))
        go_incorrect = int((not is_stop) and responded and response_key not in {"", expected_key})
        go_miss = int((not is_stop) and not responded)
        stop_success = int(is_stop and not responded)
        stop_failure = int(is_stop and responded)
        if stop_success:
            outcome_marker, outcome = 131, "stop_success"
        elif stop_failure:
            outcome_marker, outcome = 132, "stop_failure"
        elif go_correct:
            outcome_marker, outcome = 133, "go_correct"
        elif go_incorrect:
            outcome_marker, outcome = 134, "go_incorrect"
        else:
            outcome_marker, outcome = 135, "go_miss"
        outcome_lsl_time = self.event_logger.send(outcome_marker, outcome, {"trial_num": trial_num})
        self.results.append(
            {
                "subject_id": f"sub-{self.subject_id}",
                "session_id": f"ses-{self.session_id}",
                "run": self.run_label,
                "mode": self.mode,
                "phase": "localizer" if self.mode == "LOCALIZER_SST" else "stimulation",
                "stim_condition": "sham" if self.mode == "SHAM" else "none" if self.mode == "LOCALIZER_SST" else "active",
                "protocol_label_to_show": self.rhythm_decision.get("protocol_label_to_show", ""),
                "operator_confirmed_protocol": self.operator_confirmation.get("operator_confirmed_protocol", ""),
                "operator_confirmed_frequency_hz": self.operator_confirmation.get("operator_confirmed_frequency_hz"),
                "intended_stimulation_frequency_hz": self.rhythm_decision.get("frequency_to_use_hz"),
                "actual_or_confirmed_stimulation_frequency_hz": self.operator_confirmation.get("operator_confirmed_frequency_hz", self.rhythm_decision.get("frequency_to_use_hz")),
                "theta_source": self.rhythm_decision.get("theta_source", "none"),
                "theta_estimate_file": self.rhythm_decision.get("theta_estimate_file", ""),
                "theta_reliable": self.rhythm_decision.get("theta_reliable", False),
                "theta_reliability_reason": self.rhythm_decision.get("theta_reliability_reason", ""),
                "beta_source": self.rhythm_decision.get("beta_source", "none"),
                "beta_estimate_file": self.rhythm_decision.get("beta_estimate_file", ""),
                "beta_reliable": self.rhythm_decision.get("beta_reliable", False),
                "beta_reliability_reason": self.rhythm_decision.get("beta_reliability_reason", ""),
                "rhythm_key": self.rhythm_decision.get("rhythm_key", ""),
                "rhythm_label": self.rhythm_decision.get("rhythm_label", ""),
                "rhythm_source": self.rhythm_decision.get("rhythm_source", "none"),
                "rhythm_estimate_file": self.rhythm_decision.get("rhythm_estimate_file", ""),
                "rhythm_reliable": self.rhythm_decision.get("rhythm_reliable", False),
                "rhythm_reliability_reason": self.rhythm_decision.get("rhythm_reliability_reason", ""),
                "trialNumber": trial_num,
                "stim_onset": stim_onset_task_time,
                "stim_onset_lsl_time": stim_onset_lsl_time,
                "stop_onset": stop_onset_task_time if stop_onset_task_time is not None else "",
                "stop_onset_lsl_time": stop_onset_lsl_time if stop_onset_lsl_time is not None else "",
                "response_onset": response_onset_task_time if response_onset_task_time is not None else "",
                "response_onset_lsl_time": response_onset_lsl_time if response_onset_lsl_time is not None else "",
                "outcome_lsl_time": outcome_lsl_time,
                "marker_code": outcome_marker,
                "stimulus": direction,
                "stop": int(is_stop),
                "response": bool(responded),
                "response_key": response_key,
                "rt": rt if rt is not None else "",
                "ssd": round(float(ssd), 3),
                "go_correct": go_correct,
                "go_incorrect": go_incorrect,
                "go_miss": go_miss,
                "stop_success": stop_success,
                "stop_failure_arrowcorrect": bool(response_key in {"", expected_key}) if stop_failure else "",
                "outcome": outcome,
                "run_start_lsl_time": self.run_start_lsl_time,
                "run_end_lsl_time": self.run_end_lsl_time,
                "run_start_task_time": 0.0,
                "run_end_task_time": self.run_end_task_time,
            }
        )

    def save_events(self) -> None:
        for row in self.results:
            row["run_end_lsl_time"] = self.run_end_lsl_time
            row["run_end_task_time"] = self.run_end_task_time
        if not self.results:
            return
        base = self.data_dir / f"sub-{self.subject_id}_ses-{self.session_id}_{self.run_label}_task-SST_{self.date_label}_events"
        fields = list(self.results[0].keys())
        for suffix, delimiter in [(".csv", ","), (".tsv", "\t")]:
            with (base.with_suffix(suffix)).open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields, delimiter=delimiter)
                writer.writeheader()
                writer.writerows(self.results)
        print(f"SST events saved to: {base.with_suffix('.csv')}")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run SST localizer/stimulation workflows with rhythm logging.")
    parser.add_argument("--config", default=str(Path(__file__).resolve().parent / "config.json"))
    parser.add_argument("--mode", default="LOCALIZER_SST")
    parser.add_argument("--subject", help="Subject ID with or without sub- prefix.")
    parser.add_argument("--session", default="001", help="Session ID with or without ses- prefix.")
    parser.add_argument("--run", type=int, default=1)
    parser.add_argument("--frequency", type=float, help="Optional theta/beta frequency override.")
    parser.add_argument("--trials", type=int, help="Override trial count.")
    parser.add_argument("--test-mode", action="store_true", help="Run without PsychoPy, LSL, or stimulation hardware.")
    parser.add_argument("--auto-respond", action="store_true", help="Auto-confirm operator prompts and simulate responses.")
    parser.add_argument("--screen", type=int)
    parser.add_argument("--windowed", action="store_true")
    return parser


def main() -> int:
    args = build_arg_parser().parse_args()
    config = load_config(args.config)
    task = SSTTask(config, args)
    task.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
