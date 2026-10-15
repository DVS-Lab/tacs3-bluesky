#!/usr/bin/env python3
"""Two-armed bandit reversal-learning task with StarStim/NIC-2 sync support.

Task mechanics (trial timing, contingency structure, stimuli) are identical
regardless of stimulation condition. Frequency/condition selection happens
outside this script (see select_stimulation_frequency.py and
run_rhythm_estimation.py) and is applied by the operator directly in NIC-2 -
this script has no concept of "mode" or condition, to avoid leaking
condition information into its output or behavior.

The one non-blinding exception is --localizer: the pre-stimulation baseline
run used to estimate individualized rhythms, before any stimulation device
is even set up. It is labeled distinctly (run-localizer) so
run_rhythm_estimation.py can find it, and it skips waiting on the external
LSL start trigger since there is nothing to sync to yet.
"""

from __future__ import annotations

import argparse
import colorsys
import json
import os
import queue
import random
import urllib.error
import urllib.parse
import urllib.request
import re
import time
from datetime import datetime
from pathlib import Path
import subprocess
import sys

import pandas as pd

from eeg_lsl_recorder import LSLEEGRecorder, save_recording_summary
from task_markers import LSLStimulationTrigger, TaskMarkerLogger, lsl_clock

try:
    from psychopy import core, event, gui, visual

    PSYCHOPY_AVAILABLE = True
except ImportError:  # pragma: no cover - operator dependency
    core = event = gui = visual = None
    PSYCHOPY_AVAILABLE = False


PRE_RUN_BUFFER_SEC = 5.0

# REDCap (PID 2185). The API token is read from an environment variable so it
# is not stored in the script or committed to the repository.
#   Windows (one time):  setx REDCAP_API_TOKEN "your-token-here"   (then reopen the terminal)
REDCAP_API_URL = "https://YOUR-REDCAP-SERVER/api/"  # TODO: set to your institution's REDCap API URL
REDCAP_RECORD_ID_FIELD = "sub_id" 
REDCAP_API_TOKEN = os.environ.get("REDCAP_API_TOKEN", "")


def launch_npcap_detector():
    detector_path = Path(__file__).resolve().parent / "npcap_ping_detector.py"
    subprocess.Popen(
        [sys.executable, str(detector_path)],
        creationflags=subprocess.CREATE_NEW_CONSOLE
    )

def normalize_id(value: str, prefix: str) -> str:
    return str(value).replace(prefix, "").strip()


def load_config(config_path: str | Path | None = None) -> dict:
    if config_path is None:
        config_path = Path(__file__).resolve().parent / "config.json"
    with Path(config_path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


class FlowerStim:
    """One choice-slot stimulus: a real image if available, else a colored shape."""

    def __init__(self, win, flower_id: int, size: float, image_path: Path | None = None):
        self.flower_id = flower_id
        if image_path is not None:
            self.parts = [visual.ImageStim(win, image=str(image_path), size=(size, size))]
        else:
            hue = (flower_id * 0.61803398875) % 1.0
            rgb01 = colorsys.hsv_to_rgb(hue, 0.65, 0.85)
            rgb = [c * 2.0 - 1.0 for c in rgb01]
            shape = visual.Circle(win, radius=size / 2.0, fillColor=rgb, lineColor=rgb, edges=64)
            label = visual.TextStim(win, text=str(flower_id), height=size * 0.3, color="white", bold=True)
            self.parts = [shape, label]

    def set_pos(self, pos) -> None:
        for part in self.parts:
            part.pos = pos

    def draw(self) -> None:
        for part in self.parts:
            part.draw()


class FeedbackStim:
    """Win/loss/miss feedback: real images if available, else colored text."""

    _TEXT_BY_KIND = {"win": ("WIN", "green"), "loss": ("LOSS", "red"), "miss": ("?", "yellow")}

    def __init__(self, win, kind: str, size: float, image_paths: list[Path] | None = None):
        self.image_stims = (
            [visual.ImageStim(win, image=str(p), size=(size, size)) for p in image_paths] if image_paths else None
        )
        text, color = self._TEXT_BY_KIND[kind]
        self.text_stim = visual.TextStim(win, text=text, height=size * 0.5, color=color, bold=True)

    def draw(self, pos=(0.0, 0.0)) -> None:
        if self.image_stims:
            stim = random.choice(self.image_stims)
            stim.pos = pos
            stim.draw()
        else:
            self.text_stim.pos = pos
            self.text_stim.draw()


class BanditTask:
    def __init__(self, config: dict, cli_args: argparse.Namespace):
        self.config = config
        self.cli_args = cli_args
        self.test_mode = bool(cli_args.test_mode)
        self.auto_respond = bool(cli_args.auto_respond or self.test_mode)

        task_cfg = config.get("task", {})
        self.win_fraction = float(task_cfg.get("win_fraction", 0.75))
        self.min_trials_same_contingency = int(task_cfg.get("min_trials_same_contingency", 20))
        self.contingency_jitter = int(task_cfg.get("contingency_jitter", 4))
        self.target_trials = task_cfg.get("target_trials")
        # The behavioral task is duration-controlled. Do not let a trial target
        # or a config stop rule terminate the run before the 10-minute duration.
        self.stop_rule = "duration"

        self.timing = dict(config.get("timing", {}))
        # Run duration: 10 minutes by default. An explicit CLI value can override it.
        # This prevents config.json from accidentally shortening the behavioral run.
        duration_minutes = (
            float(cli_args.duration_minutes)
            if cli_args.duration_minutes is not None
            else 10.0
        )
        self.max_duration_seconds = duration_minutes * 60.0

        stimuli_cfg = config.get("stimuli", {})
        self.slot_size = float(stimuli_cfg.get("slot_size", 0.15))
        self.slot_separation = float(stimuli_cfg.get("slot_separation", 0.4))
        self.feedback_size = float(stimuli_cfg.get("feedback_size", 0.1))
        flower_range = stimuli_cfg.get("flower_indices", [1, 50])
        self.flower_id_pool = list(range(int(flower_range[0]), int(flower_range[1]) + 1))

        paths_cfg = config.get("paths", {})
        self.stimuli_dir = (Path(__file__).resolve().parent / paths_cfg.get("stimuli_dir", "../stimuli/images")).resolve()

        self.marker_codes = config.get("stimulation", {}).get("markers", {})

        self.subject_id: str | None = None
        self.session_id: str | None = None
        self.run_label: str | None = None
        self.date_label: str | None = None
        self.data_dir: Path | None = None

        self.used_flowers: set[int] = set()
        self.current_flowers: list[int] = []
        self.current_good: int | None = None
        self.trial_in_contingency = 0
        self.contingency_id = 1
        self.contingency_trials = self._get_contingency_duration()
        self.current_trial = 0
        self.trial_data: list[dict] = []
        self.task_should_stop = False
        self.slot1_side: str | None = None
        self.slot2_side: str | None = None

        self.run_start_time: float | None = None
        self.run_start_unix_time: float | None = None
        self.run_end_unix_time: float | None = None
        self.run_start_monotonic: float | None = None
        self.run_start_task_time: float | None = None
        self.run_start_lsl_time: float | None = None
        self.run_end_task_time: float | None = None
        self.run_end_lsl_time: float | None = None

        self._saved = False
        self._marker_log_saved = False
        self.eeg_recording_saved = False

        # PANAS items - ALWAYS presented in exactly this order
        self.PANAS_POSITIVE = ["Active", "Alert", "Attentive", "Determined", "Inspired"]
        self.PANAS_NEGATIVE = ["Afraid", "Ashamed", "Hostile", "Nervous", "Upset"]
        self.PANAS_LABELS = [
            "1: Very slightly\nor not at all",
            "2: A little",
            "3: Moderately",
            "4: Quite a bit",
            "5: Extremely",
        ]
        self.panas_results: list[dict] = []

        self.event_logger = TaskMarkerLogger(
            config.get("eeg_recording", {}).get("marker_stream_name", "LSLOutletStreamName-Markers")
        )
        self.eeg_recorder: LSLEEGRecorder | None = None

        self.lsl_trigger: LSLStimulationTrigger | None = None
        lsl_config = config.get("stimulation", {}).get("lsl", {})
        if not self.test_mode and lsl_config.get("enabled", True):
            self.lsl_trigger = LSLStimulationTrigger(stream_name=lsl_config.get("outlet_stream_name"))
            self.lsl_trigger.connect()
            self.lsl_trigger.start_listening()

        self.win = None
        self.fixation = None
        self._highlight_ring = None
        self._flower_stim_cache: dict[int, FlowerStim] = {}
        self._feedback_stims: dict[str, FeedbackStim] = {}

    # -- setup -----------------------------------------------------------

    def _get_contingency_duration(self) -> int:
        return self.min_trials_same_contingency + random.randint(0, self.contingency_jitter)

    def _resolve_subject(self):
        info = {
            "Subject Number": "",
            "Session Number": "",
            "Run Number": "",
        }

        dlg = gui.DlgFromDict(info, title="Bandit Task Setup")
        if not dlg.OK:
            core.quit()

        # Validate subject number
        subject_number = info["Subject Number"].strip()
        if not subject_number:
            raise ValueError("Subject Number is required.")

        self.subject_id = normalize_id(subject_number, "sub-")

        # Validate session number
        session_number = info["Session Number"].strip()
        if not session_number.isdigit() or int(session_number) < 1:
            raise ValueError("Session Number must be a positive integer.")

        self.gui_session_number = int(session_number)

        # Validate run number
        run_number = info["Run Number"].strip()
        if not run_number.isdigit() or int(run_number) < 1:
            raise ValueError("Run Number must be a positive integer.")

        self.gui_run_number = int(run_number)

    def _next_run_number(self) -> int:
        pattern = re.compile(
            rf"^sub-{re.escape(self.subject_id)}_ses-{re.escape(self.session_id)}_run-(\d+)_task-bandit_.*_events\.tsv$"
        )
        existing = []
        for path in self.data_dir.glob(f"sub-{self.subject_id}_ses-{self.session_id}_run-*_task-bandit_*_events.tsv"):
            match = pattern.match(path.name)
            if match:
                existing.append(int(match.group(1)))
        return max(existing, default=0) + 1

    def _setup_session(self) -> None:

        session_number = (
            self.cli_args.session
            if self.cli_args.session is not None
            else self.gui_session_number
        )

        self.session_id = normalize_id(str(session_number), "ses-")
        self.date_label = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

        # Save behavioral data inside the repository, grouped by participant.
        # Example: .../tacs3-bluesky/behavioral-data/sub-10010/
        script_path = Path(__file__).resolve()
        repo_root = next(
            (parent for parent in (script_path.parent, *script_path.parents) if parent.name == "tacs3-bluesky"),
            script_path.parent,
        )
        self.data_dir = repo_root / "data" / f"sub-{self.subject_id}"
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # Always use a single run label
        self.run_label = f"run-{self.gui_run_number:02d}"


    def _select_flowers_for_run(self) -> bool:
        available = set(self.flower_id_pool) - self.used_flowers
        if len(available) < 2:
            self.used_flowers = set()
            available = set(self.flower_id_pool)
        if len(available) < 2:
            print("Error: need at least 2 configured flower stimulus ids (stimuli.flower_indices).")
            return False
        self.current_flowers = random.sample(sorted(available), 2)
        self.current_good = random.choice(self.current_flowers)
        self.used_flowers.update(self.current_flowers)
        return True

    def _slot_positions(self):
        half_sep = self.slot_separation / 2.0
        if random.random() < 0.5:
            return (-half_sep, 0.0), (half_sep, 0.0), "left", "right"
        return (half_sep, 0.0), (-half_sep, 0.0), "right", "left"

    def _should_stop_run(self) -> bool:
        if self.run_start_monotonic is None:
            return False

        # Monotonic time cannot jump if the computer's wall clock changes.
        elapsed = time.monotonic() - self.run_start_monotonic
        return elapsed >= self.max_duration_seconds


    def _feedback_marker(self, reward: bool | None) -> tuple[int, str]:
        if reward is None:
            return int(self.marker_codes.get("feedback_miss", 33)), "miss"
        if reward:
            return int(self.marker_codes.get("feedback_win", 31)), "win"
        return int(self.marker_codes.get("feedback_loss", 32)), "loss"

    def _advance_contingency(self) -> None:
        self.trial_in_contingency += 1
        if self.trial_in_contingency >= self.contingency_trials:
            if self.current_good == self.current_flowers[0]:
                self.current_good = self.current_flowers[1]
            else:
                self.current_good = self.current_flowers[0]

            self.trial_in_contingency = 0
            self.contingency_trials = self._get_contingency_duration()
            self.contingency_id += 1


    # -- trial row / persistence -------------------------------------------

    def _build_trial_row(
        self,
        *,
        trial_num,
        slot1_side,
        slot2_side,
        choice,
        rt_ms,
        correct,
        reward,
        outcome,
        feedback_marker,
        trial_start_task_time,
        trial_start_lsl_time,
        trial_start_unix_time,
        choice_window_onset_task_time,
        choice_window_onset_lsl_time,
        choice_window_onset_unix_time,
        choice_onset_task_time,
        choice_onset_lsl_time,
        choice_onset_unix_time,
        choice_marker_send_lsl_time,
        feedback_task_time,
        feedback_lsl_time,
        feedback_onset_unix_time,
        wait_time,
    ) -> dict:
        left_stimulus = self.current_flowers[0] if slot1_side == "left" else self.current_flowers[1]
        right_stimulus = self.current_flowers[1] if slot1_side == "left" else self.current_flowers[0]
        return {
            "subject_id": f"sub-{self.subject_id}",
            "session_id": f"ses-{self.session_id}",
            "run": self.run_label,
            "localizer": int(bool(self.cli_args.localizer)),
            "trial_num": trial_num,
            "current_good": self.current_good,
            "contingency_id": self.contingency_id,
            "trial_in_contingency": self.trial_in_contingency,
            "contingency_trials": self.contingency_trials,
            "flower1": self.current_flowers[0],
            "flower2": self.current_flowers[1],
            "left_stimulus": left_stimulus,
            "right_stimulus": right_stimulus,
            "slot1_position": slot1_side,
            "slot2_position": slot2_side,
            "choice": choice,
            "rt": rt_ms,
            "correct": correct,
            "reward": reward,
            "outcome": outcome,
            "feedback_marker": feedback_marker,
            "trial_start_task_time": trial_start_task_time,
            "trial_start_lsl_time": trial_start_lsl_time,
            "trial_start_unix_time": trial_start_unix_time,
            "choice_window_onset_task_time": choice_window_onset_task_time,
            "choice_window_onset_lsl_time": choice_window_onset_lsl_time,
            "choice_window_onset_unix_time": choice_window_onset_unix_time,
            "choice_onset_task_time": choice_onset_task_time,
            "choice_onset_lsl_time": choice_onset_lsl_time,
            "choice_onset_unix_time": choice_onset_unix_time,
            "choice_marker_send_lsl_time": choice_marker_send_lsl_time,
            "feedback_onset_task_time": feedback_task_time,
            "feedback_onset_lsl_time": feedback_lsl_time,
            "feedback_onset_unix_time": feedback_onset_unix_time,
            "lsl_marker_send_time": feedback_lsl_time,
            "wait_time": wait_time * 1000.0,
            "iti": self.timing["iti_duration"] * 1000.0,
            "run_start_task_time": 0.0,
            "run_start_lsl_time": self.run_start_lsl_time,
            "run_start_unix_time": self.run_start_unix_time,
            "run_end_task_time": None,
            "run_end_lsl_time": None,
            "run_end_unix_time": self.run_end_unix_time,
        }

    def save_data(self) -> None:
        if self._saved or not self.trial_data:
            return
        for row in self.trial_data:
            row["run_end_task_time"] = self.run_end_task_time
            row["run_end_lsl_time"] = self.run_end_lsl_time
            row["run_end_unix_time"] = self.run_end_unix_time
        df = pd.DataFrame(self.trial_data)
        filename = (
            f"sub-{self.subject_id}_ses-{self.session_id}_{self.run_label}"
            f"_task-bandit_{self.date_label}_events.csv"
        )
        filepath = self.data_dir / filename
        df.to_csv(filepath, index=False)
        self._saved = True
        print(f"\nData saved to: {filepath}")

    def cleanup(self) -> None:
        if self.run_start_time is not None and self.run_end_lsl_time is None:
            self.run_end_task_time = time.time() - self.run_start_time
            self.run_end_unix_time = time.time() * 1000.0
            self.run_end_lsl_time = self.event_logger.send(200, "run_end", {
                "run_label": self.run_label,
                "run_end_unix_time": self.run_end_unix_time,
            })
        self.save_data()
        if self.lsl_trigger:
            self.lsl_trigger.stop_listening()


    # -- test-mode (headless, no PsychoPy/pygame required) ------------------

    def _run_test_mode(self) -> None:
        if not self._select_flowers_for_run():
            return
        self.run_start_time = time.time()
        self.run_start_unix_time = self.run_start_time * 1000.0
        self.run_start_monotonic = time.monotonic()
        self.run_start_task_time = 0.0
        self.run_start_lsl_time = self.event_logger.send(
            100, "run_start",
            {"run_label": self.run_label, "run_start_unix_time": self.run_start_unix_time},
        )

        while not self._should_stop_run():
            trial_num = self.current_trial + 1
            _, _, slot1_side, slot2_side = self._slot_positions()
            self.slot1_side, self.slot2_side = slot1_side, slot2_side

            trial_start_task_time = time.time() - self.run_start_time
            trial_start_unix_time = time.time() * 1000.0
            trial_start_lsl_time = lsl_clock()
            self.event_logger.send(
                10, "trial_start",
                {"trial_num": trial_num, "trial_start_unix_time": trial_start_unix_time},
            )

            choice_window_onset_task_time = time.time() - self.run_start_time
            choice_window_onset_unix_time = time.time() * 1000.0
            choice_window_onset_lsl_time = lsl_clock()
            responded = random.random() < 0.9
            choice = random.choice([1, 2]) if responded else None
            rt = random.uniform(0.25, max(0.26, self.timing["max_response_time"] - 0.05)) if responded else None

            if choice is not None:
                chosen_flower = self.current_flowers[choice - 1]
                correct = chosen_flower == self.current_good
                reward_prob = self.win_fraction if correct else 1 - self.win_fraction
                reward = random.random() < reward_prob
                rt_ms = rt * 1000.0
                choice_onset_task_time = choice_window_onset_task_time + rt
                choice_onset_unix_time = choice_window_onset_unix_time + (rt * 1000.0)
                choice_onset_lsl_time = choice_window_onset_lsl_time + rt
                choice_marker_send_lsl_time = self.event_logger.send(
                    20, "choice", {"trial_num": trial_num, "choice": choice, "choice_onset_unix_time": choice_onset_unix_time}
                )
            else:
                correct = reward = rt_ms = None
                choice_onset_task_time = choice_onset_lsl_time = choice_marker_send_lsl_time = None
                choice_onset_unix_time = None

            wait_time = random.uniform(self.timing["wait_duration_min"], self.timing["wait_duration_max"])
            feedback_marker, outcome = self._feedback_marker(reward)
            feedback_onset_unix_time = time.time() * 1000.0
            feedback_lsl_time = self.event_logger.send(
                feedback_marker, f"feedback_{outcome}",
                {"trial_num": trial_num, "feedback_onset_unix_time": feedback_onset_unix_time}
            )
            feedback_task_time = (feedback_onset_unix_time / 1000.0) - self.run_start_time

            row = self._build_trial_row(
                trial_num=trial_num,
                slot1_side=slot1_side,
                slot2_side=slot2_side,
                choice=choice,
                rt_ms=rt_ms,
                correct=correct,
                reward=reward,
                outcome=outcome,
                feedback_marker=feedback_marker,
                trial_start_task_time=trial_start_task_time,
                trial_start_lsl_time=trial_start_lsl_time,
                trial_start_unix_time=trial_start_unix_time,
                choice_window_onset_task_time=choice_window_onset_task_time,
                choice_window_onset_lsl_time=choice_window_onset_lsl_time,
                choice_window_onset_unix_time=choice_window_onset_unix_time,
                choice_onset_task_time=choice_onset_task_time,
                choice_onset_lsl_time=choice_onset_lsl_time,
                choice_onset_unix_time=choice_onset_unix_time,
                choice_marker_send_lsl_time=choice_marker_send_lsl_time,
                feedback_task_time=feedback_task_time,
                feedback_lsl_time=feedback_lsl_time,
                feedback_onset_unix_time=feedback_onset_unix_time,
                wait_time=wait_time,
            )
            self.trial_data.append(row)
            self._advance_contingency()
            self.current_trial += 1

        self.run_end_task_time = time.time() - self.run_start_time
        self.run_end_unix_time = time.time() * 1000.0
        self.run_end_lsl_time = self.event_logger.send(200, "run_end", {
            "run_label": self.run_label,
            "run_end_unix_time": self.run_end_unix_time,
        })
        print(f"Test-mode run complete: {self.current_trial} simulated trials.")

    # -- PsychoPy rendering --------------------------------------------------

    @staticmethod
    def _rgb01_to_pm1(color01):
        return [c * 2.0 - 1.0 for c in color01]

    def _build_window(self) -> None:
        display_cfg = self.config.get("display", {})
        size = (display_cfg.get("window_width", 1024), display_cfg.get("window_height", 768))
        self.win = visual.Window(
            size=size,
            color=self._rgb01_to_pm1(display_cfg.get("background_color", [0, 0, 0])),
            fullscr=not self.cli_args.windowed,
            units="height",
            screen=int(self.cli_args.screen or 0),
            allowGUI=False,
        )
        self.win.mouseVisible = False

    def _build_base_stimuli(self) -> None:
        self.fixation = visual.TextStim(
            self.win,
            text="+",
            height=0.05,
            color="white"
        )

        self._highlight_ring = visual.Circle(
            self.win,
            radius=self.slot_size / 2.0 + 0.02,
            lineColor="white",
            lineWidth=6,
            fillColor=None,
            edges=64
        )

        self._instructions_stim = visual.TextStim(
            self.win,
            text="",
            color="white",
            height=0.045,
            wrapWidth=1.6,
            pos=(0, 0)
        )

        # Instruction-page feedback images
        win_image_path = self.stimuli_dir / "win-up.png"
        loss_image_path = self.stimuli_dir / "neutral-gray.png"

        self._instruction_win_stim = visual.ImageStim(
            self.win,
            image=str(win_image_path),
            size=(0.18, 0.18),
            pos=(0.0, -0.15)
        )

        self._instruction_loss_stim = visual.ImageStim(
            self.win,
            image=str(loss_image_path),
            size=(0.18, 0.18),
            pos=(0.0, -0.15)
        )
    def _build_feedback_stims(self) -> None:
        win_images = sorted(self.stimuli_dir.glob("win-up.png")) if self.stimuli_dir.exists() else []
        loss_images = sorted(self.stimuli_dir.glob("neutral-gray.png")) if self.stimuli_dir.exists() else []
        question_image = self.stimuli_dir / "question-mark.png"
        question_images = [question_image] if question_image.exists() else []
        self._feedback_stims = {
            "win": FeedbackStim(self.win, "win", self.feedback_size, image_paths=win_images or None),
            "loss": FeedbackStim(self.win, "loss", self.feedback_size, image_paths=loss_images or None),
            "miss": FeedbackStim(self.win, "miss", self.feedback_size, image_paths=question_images or None),
        }

    def _get_flower_stim(self, flower_id: int) -> FlowerStim:
        if flower_id not in self._flower_stim_cache:
            image_path = self.stimuli_dir / f"{flower_id:03d}-flowers.png"
            self._flower_stim_cache[flower_id] = FlowerStim(
                self.win, flower_id, self.slot_size, image_path=image_path if image_path.exists() else None
            )
        return self._flower_stim_cache[flower_id]

    def _show_instructions(self) -> bool:
        instruction_pages = [
            [
                "Welcome to the Two-Armed Bandit task!",
                "",
                "In this game, you will see two flowers on the screen.",
                "",
                "Each round, you will choose one of the two flowers",
                "and then receive feedback about your choice.",
                "",
                "Use 1 to choose the flower on the left.",
                "Use 0 to choose the flower on the right.",
                "",
                "You will only have a few seconds to make your decision.",
                "Try to respond as quickly as possible.",
                "",
                "Press SPACE to continue.",
            ],

            [
                "After making your choice, you will receive feedback",
                "based on your decision.",
                "",
                "You can either receive a prize or receive nothing.",
                "",
                "Press SPACE to continue.",
            ],

            [
                "When you receive a prize, you will see:",
                "",
            ],

            [
                "When you receive nothing, you will see:",
                "",
            ],

            [
                "One of these flowers is more likely to give you a prize,",
                "and this flower may occasionally change during the game.",
                "",
                "Your goal is to earn as many prizes as you can.",
                "",
                "Press SPACE to continue.",
            ],

            [
                "At the end of the study, the number of prizes you earn",
                "will be used to calculate your bonus payment.",
                "",
                "This run of the game will last about 10 minutes.",
                "",
                "You will see the same two flowers for this run.",
                "",
                "Do you have any questions?",
                "",
                "Press SPACE to continue.",
            ],
        ]

        for page_num, page in enumerate(instruction_pages):

            lines = page

            self._instructions_stim.text = "\n".join(lines)
            self._instructions_stim.draw()

            # Prize image on its own screen
            if page_num == 2:
                self._instruction_win_stim.draw()

            # Nothing/loss image on its own screen
            elif page_num == 3:
                self._instruction_loss_stim.draw()

            self.win.flip()

            if self.auto_respond:
                core.wait(0.05)
                continue

            while True:
                keys = event.getKeys(keyList=["space", "escape"])

                if "space" in keys:
                    break

                if "escape" in keys:
                    return False

                core.wait(0.01)

        return True


    def _show_waiting_screen(self) -> bool:
        lines = [
            f"Two-Armed Bandit Task — {self.run_label}",
            "",
            "Please wait for the experimenter",
            "to start the task, then",
            "",
            "Please wait for the experimenter to begin the task",
            "Press ESC to exit",
        ]

        self._instructions_stim.text = "\n".join(lines)
        self._instructions_stim.draw()
        self.win.flip()

        if self.auto_respond:
            core.wait(0.05)
            return True

        listen_lsl = (not self.cli_args.localizer) and self.lsl_trigger is not None

        while True:
            # Get whatever key was pressed rather than restricting keyList.
            keys = event.getKeys()

            for key in keys:
                print(f"Waiting screen key detected: {repr(key)}")

                if key in ("=", "equal"):
                    print("= detected. Starting task.")
                    return True

                if key == "escape":
                    return False

            if listen_lsl:
                try:
                    marker_code, _ = self.lsl_trigger.marker_queue.get_nowait()

                    if marker_code == self.lsl_trigger.TASK_START_MARKER:
                        print(f"LSL: marker {marker_code} received. Starting task.")
                        return True

                except queue.Empty:
                    pass

            core.wait(0.01)

    def _show_start_buffer(self) -> bool:
        if self.auto_respond:
            core.wait(0.05)
            return True
        self.fixation.draw()
        self.win.flip()
        clock = core.Clock()
        while clock.getTime() < PRE_RUN_BUFFER_SEC:
            if event.getKeys(keyList=["escape"]):
                return False
            core.wait(0.01)
        return True

    def _get_response(self, max_time: float):
        clock = core.Clock()
        event.clearEvents()
        while clock.getTime() < max_time:
            # Stimulation ending must not end the behavioral task.
            # The behavioral task has its own independent 10-minute timer.
            keys = event.getKeys(keyList=["1", "0", "escape"], timeStamped=clock)
            if keys:
                key, rt = keys[0]
                if key == "escape":
                    return "escape", rt
                if key == "1":
                    return (1 if self.slot1_side == "left" else 2), rt
                if key == "0":
                    return (1 if self.slot1_side == "right" else 2), rt
            core.wait(0.005)
        return None, None

    def _run_trial(self) -> bool:
        if self.task_should_stop or self._should_stop_run():
            return False

        trial_num = self.current_trial + 1
        pos1, pos2, slot1_side, slot2_side = self._slot_positions()
        self.slot1_side, self.slot2_side = slot1_side, slot2_side

        trial_start_task_time = time.time() - self.run_start_time
        trial_start_unix_time = time.time() * 1000.0
        trial_start_lsl_time = lsl_clock()
        self.event_logger.send(
            10, "trial_start",
            {"trial_num": trial_num, "trial_start_unix_time": trial_start_unix_time},
        )

        self.fixation.draw()
        self.win.flip()
        core.wait(self.timing["fixation_duration"])

        event.clearEvents()
        flower1 = self._get_flower_stim(self.current_flowers[0])
        flower2 = self._get_flower_stim(self.current_flowers[1])
        flower1.set_pos(pos1)
        flower2.set_pos(pos2)
        flower1.draw()
        flower2.draw()
        self.win.flip()

        choice_window_onset_task_time = time.time() - self.run_start_time
        choice_window_onset_unix_time = time.time() * 1000.0
        choice_window_onset_lsl_time = lsl_clock()

        if self.auto_respond:
            rt = min(self.timing["max_response_time"] - 0.05, 0.5)
            core.wait(rt)
            choice = random.choice([1, 2])
            choice_onset_unix_time = choice_window_onset_unix_time + (rt * 1000.0)
        else:
            choice, rt = self._get_response(self.timing["max_response_time"])
            choice_onset_unix_time = (
                choice_window_onset_unix_time + (rt * 1000.0)
                if choice is not None else None
            )


        if choice == "escape":
            self.task_should_stop = True
            return False

        if choice is not None:
            chosen_pos = pos1 if choice == 1 else pos2
            chosen_stim = flower1 if choice == 1 else flower2
            chosen_stim.draw()
            self._highlight_ring.pos = chosen_pos
            self._highlight_ring.draw()
            self.win.flip()
            core.wait(self.timing["choice_highlight_duration"])

            chosen_flower = self.current_flowers[choice - 1]
            correct = chosen_flower == self.current_good
            reward_prob = self.win_fraction if correct else 1 - self.win_fraction
            reward = random.random() < reward_prob
            rt_ms = rt * 1000.0
            choice_onset_task_time = choice_window_onset_task_time + rt
            choice_onset_lsl_time = choice_window_onset_lsl_time + rt
            choice_marker_send_lsl_time = self.event_logger.send(
                20, "choice", {"trial_num": trial_num, "choice": choice, "choice_onset_lsl_time": choice_onset_lsl_time, "choice_onset_unix_time": choice_onset_unix_time}
            )
        else:
            correct = reward = rt_ms = None
            choice_onset_task_time = choice_onset_lsl_time = choice_marker_send_lsl_time = None
            choice_onset_unix_time = None

        self.win.flip()
        wait_time = random.uniform(self.timing["wait_duration_min"], self.timing["wait_duration_max"])
        core.wait(wait_time)

        feedback_marker, outcome = self._feedback_marker(reward)

        # Draw feedback, then capture the Unix timestamp immediately after the
        # screen flip so it represents feedback onset on the behavioral computer.
        self._feedback_stims[outcome].draw()
        self.win.flip()
        feedback_onset_unix_time = time.time() * 1000.0
        feedback_task_time = (feedback_onset_unix_time / 1000.0) - self.run_start_time

        feedback_lsl_time = self.event_logger.send(
            feedback_marker,
            f"feedback_{outcome}",
            {
                "trial_num": trial_num,
                "feedback_onset_unix_time": feedback_onset_unix_time,
            }
        )

        core.wait(self.timing["outcome_duration"])

        self.win.flip()
        core.wait(self.timing["iti_duration"])

        row = self._build_trial_row(
            trial_num=trial_num,
            slot1_side=slot1_side,
            slot2_side=slot2_side,
            choice=choice,
            rt_ms=rt_ms,
            correct=correct,
            reward=reward,
            outcome=outcome,
            feedback_marker=feedback_marker,
            trial_start_task_time=trial_start_task_time,
            trial_start_lsl_time=trial_start_lsl_time,
            trial_start_unix_time=trial_start_unix_time,
            choice_window_onset_task_time=choice_window_onset_task_time,
            choice_window_onset_lsl_time=choice_window_onset_lsl_time,
            choice_window_onset_unix_time=choice_window_onset_unix_time,
            choice_onset_task_time=choice_onset_task_time,
            choice_onset_lsl_time=choice_onset_lsl_time,
            choice_onset_unix_time=choice_onset_unix_time,
            choice_marker_send_lsl_time=choice_marker_send_lsl_time,
            feedback_task_time=feedback_task_time,
            feedback_lsl_time=feedback_lsl_time,
            feedback_onset_unix_time=feedback_onset_unix_time,
            wait_time=wait_time,
        )
        self.trial_data.append(row)
        self._advance_contingency()
        self.current_trial += 1
        return True

    def _run_psychopy(self) -> None:
        if not PSYCHOPY_AVAILABLE:
            raise RuntimeError("PsychoPy is not installed. Use --test-mode or install psychopy to run the task.")
        self._build_window()
        self._build_base_stimuli()
        self._build_feedback_stims()
        try:
            if not self._select_flowers_for_run():
                return
            # Only show instructions on Run 1
            if self.gui_run_number == 1:
                if not self._show_instructions():
                    return
            event.clearEvents()
            if not self._show_waiting_screen():
                return
            if not self._show_start_buffer():
                return

            self.run_start_time = time.time()
            self.run_start_unix_time = self.run_start_time * 1000.0
            self.run_start_monotonic = time.monotonic()
            self.run_start_task_time = 0.0
            self.run_start_lsl_time = self.event_logger.send(
            100, "run_start",
            {"run_label": self.run_label, "run_start_unix_time": self.run_start_unix_time},
        )

            print(f"\nStarting {self.run_label}")
            print(
    f"Duration: {self.max_duration_seconds / 60.0:.1f} minutes, "
    f"stop rule: {self.stop_rule}, target trials: {self.target_trials}"
)
            print("Press ESC to abort\n")

            while self._run_trial():
                if self.current_trial and self.current_trial % 10 == 0:
                    elapsed = time.time() - self.run_start_time
                    print(f"  Trial {self.current_trial}, Time: {elapsed:.1f}s")

            self.run_end_task_time = time.time() - self.run_start_time
            self.run_end_unix_time = time.time() * 1000.0
            self.run_end_lsl_time = self.event_logger.send(200, "run_end", {
                "run_label": self.run_label,
                "run_end_unix_time": self.run_end_unix_time,
            })
            print(f"\nRun complete. Total trials: {self.current_trial}")
            if self.cli_args.localizer:
                print(
                    "Next step: python run_rhythm_estimation.py --task bandit "
                    f"--subject {self.subject_id} --session {self.session_id} --auto-find --all-defaults"
                )
            # Post-run PANAS (fixed order: 5 positive, then 5 negative).
            # Skipped if the run was aborted with ESC.
            if not self.task_should_stop:
                self.panas_results = self._show_panas_assessment()
                self.panas_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                for row in self.trial_data:
                    for i, p in enumerate(self.panas_results):
                        row[f"panas_item_{i + 1}"] = p["item"]
                        row[f"panas_valence_{i + 1}"] = p["valence"]
                        row[f"panas_rating_{i + 1}"] = p["rating"]
            self._show_run_end_screen()
            self._upload_panas_to_redcap()
        finally:
            if self.win is not None:
                self.win.close()

    def _show_number_selection(self, word: str, value_min: int = 1, value_max: int = 5):
        """Show one PANAS item. Press a number key to select, SPACE to confirm.
        No default selection. Returns the int rating, or None if ESC is pressed."""
        if self.auto_respond:
            core.wait(0.05)
            return 3

        win = self.win
        title = visual.TextStim(win, text=f"Two-Armed Bandit Task — {self.run_label}",
                                height=0.05, color="white", pos=(0, 0.38))
        prompt = visual.TextStim(win, text="Indicate the extent to which you\nfeel this way right now:",
                                 height=0.04, color="white", pos=(0, 0.25), wrapWidth=1.6)
        word_stim = visual.TextStim(win, text=word, height=0.08, color="yellow",
                                    bold=True, pos=(0, 0.1))
        hint = visual.TextStim(win, text="", height=0.035, color="white", pos=(0, -0.32))

        n = value_max - value_min + 1
        total_width = 0.9
        xs = [-total_width / 2 + i * total_width / (n - 1) for i in range(n)]
        num_y = -0.05

        circle = visual.Circle(win, radius=0.04, fillColor="white", lineColor="white", edges=64)
        num_stims, label_stims = [], []
        for i, x in enumerate(xs):
            num_stims.append(visual.TextStim(win, text=str(value_min + i), height=0.05,
                                             color="gray", pos=(x, num_y)))
            label_stims.append(visual.TextStim(win, text=self.PANAS_LABELS[i], height=0.025,
                                               color="gray", pos=(x, num_y - 0.1), wrapWidth=0.25))

        key_map = {}
        for v in range(value_min, value_max + 1):
            key_map[str(v)] = v
            key_map[f"num_{v}"] = v

        selected = None
        event.clearEvents()
        while True:
            title.draw()
            prompt.draw()
            word_stim.draw()
            for i, x in enumerate(xs):
                val = value_min + i
                if selected == val:
                    circle.pos = (x, num_y)
                    circle.draw()
                    num_stims[i].color = "black"
                else:
                    num_stims[i].color = "gray"
                num_stims[i].draw()
                label_stims[i].draw()

            if selected is None:
                hint.text = "Press a number key to select, then SPACE to confirm"
                hint.color = "gray"
            else:
                hint.text = f"Selected: {selected}  —  Press SPACE to confirm"
                hint.color = "white"
            hint.draw()
            win.flip()

            for key in event.getKeys(keyList=list(key_map) + ["space", "escape"]):
                if key == "escape":
                    return None
                if key == "space":
                    if selected is not None:
                        return selected
                else:
                    selected = key_map[key]
            core.wait(0.01)

    def _show_panas_assessment(self) -> list[dict]:
        """Present the 10 PANAS items in fixed order: 5 positive, then 5 negative."""
        items = [(w, "positive") for w in self.PANAS_POSITIVE] + \
                [(w, "negative") for w in self.PANAS_NEGATIVE]
        results = []
        for idx, (word, valence) in enumerate(items):
            rating = self._show_number_selection(word)
            results.append({"item": word, "valence": valence, "rating": rating})
            if rating is not None:
                print(f"PANAS item {idx + 1}/{len(items)}: {word} ({valence}) = {rating}")
        return results

    def _upload_panas_to_redcap(self) -> None:
        """Send the completed PANAS responses to REDCap. Never raises: on any
        problem it prints a warning, and the ratings are still in the CSV."""
        if self.test_mode or self.auto_respond:
            return
        if not self.panas_results or any(p["rating"] is None for p in self.panas_results):
            print("REDCap: PANAS incomplete or aborted; nothing uploaded.")
            return
        run = self.gui_run_number
        if run not in (1, 2):
            print(f"REDCap: no PANAS variables for run {run} (only runs 1 and 2); nothing uploaded.")
            return
        if not REDCAP_API_TOKEN:
            print("REDCap: REDCAP_API_TOKEN environment variable is not set; nothing uploaded.")
            return
        if "YOUR-REDCAP-SERVER" in REDCAP_API_URL:
            print("REDCap: REDCAP_API_URL has not been set in the script; nothing uploaded.")
            return

        try:
            record = {
                REDCAP_RECORD_ID_FIELD: self.subject_id,
                "redcap_event_name": f"visit_{int(self.session_id)}_arm_1",
                f"panas_task{run}_timestamp_1": self.panas_timestamp,
            }
            counts = {"positive": 0, "negative": 0}
            for p in self.panas_results:
                counts[p["valence"]] += 1
                suffix = "pos" if p["valence"] == "positive" else "neg"
                record[f"panas_task{run}_{suffix}{counts[p['valence']]}"] = p["rating"]

            payload = urllib.parse.urlencode({
                "token": REDCAP_API_TOKEN,
                "content": "record",
                "format": "json",
                "type": "flat",
                "overwriteBehavior": "normal",
                "forceAutoNumber": "false",
                "data": json.dumps([record]),
                "returnContent": "count",
                "returnFormat": "json",
            }).encode("utf-8")
            req = urllib.request.Request(REDCAP_API_URL, data=payload, method="POST")
            with urllib.request.urlopen(req, timeout=15) as resp:
                body = resp.read().decode("utf-8", errors="replace")
            print(f"REDCap: PANAS uploaded for sub-{self.subject_id}, {record['redcap_event_name']} ({body.strip()})")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            print(f"REDCap upload FAILED (HTTP {exc.code}): {detail}")
        except Exception as exc:
            print(f"REDCap upload FAILED: {exc}")

    def _show_run_end_screen(self) -> None:
        self._instructions_stim.text = "Run complete.\n\nThank you!"
        self._instructions_stim.draw()
        self.win.flip()
        if self.auto_respond:
            core.wait(0.05)
            return
        event.waitKeys(keyList=["space", "escape"], maxWait=8.0)

    # -- entry point ----------------------------------------------------

    def run(self) -> None:
        try:
            self._resolve_subject()
            self._setup_session()
            if self.test_mode:
                self._run_test_mode()
            else:
                self._run_psychopy()
        except KeyboardInterrupt:
            print("\nSession interrupted by user")
        finally:
            self.cleanup()


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the two-armed bandit reversal-learning task.")
    parser.add_argument("--config", default=str(Path(__file__).resolve().parent / "config.json"))
    parser.add_argument("--subject", help="Subject ID, with or without the sub- prefix.")
    parser.add_argument(
        "--session",
        default=None,
        help="Session number; if omitted, use the GUI selection."
    )
    parser.add_argument("--run", type=int, help="Explicit run number. Auto-incremented from existing files if omitted.")
    parser.add_argument(
        "--localizer",
        action="store_true",
        help="Mark this as the pre-stimulation baseline run (labels the file run-localizer, skips the LSL start trigger).",
    )
    parser.add_argument("--duration-minutes", type=float, help="Override the configured run duration.")
    parser.add_argument("--test-mode", action="store_true", help="Run without PsychoPy, LSL, or stimulation hardware.")
    parser.add_argument("--auto-respond", action="store_true", help="Auto-start and simulate button responses.")
    parser.add_argument("--screen", type=int, help="Monitor index for the PsychoPy window.")
    parser.add_argument("--windowed", action="store_true", help="Run in a window instead of fullscreen.")
    return parser


def main() -> int:
    cli_args = build_arg_parser().parse_args()
    config = load_config(cli_args.config)

    launch_npcap_detector()

    task = BanditTask(config, cli_args)
    task.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
