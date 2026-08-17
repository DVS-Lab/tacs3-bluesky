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
import queue
import random
import re
import time
from datetime import datetime
from pathlib import Path

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
        self.stop_rule = task_cfg.get("stop_rule", "duration_or_trials")

        self.timing = dict(config.get("timing", {}))
        duration_minutes = float(
            cli_args.duration_minutes or config.get("experiment", {}).get("run_duration_minutes", 6)
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
        self.current_good = random.randint(1, 2)
        self.trial_in_contingency = 0
        self.contingency_id = 1
        self.contingency_trials = self._get_contingency_duration()
        self.current_trial = 0
        self.trial_data: list[dict] = []
        self.task_should_stop = False
        self.slot1_side: str | None = None
        self.slot2_side: str | None = None

        self.run_start_time: float | None = None
        self.run_start_task_time: float | None = None
        self.run_start_lsl_time: float | None = None
        self.run_end_task_time: float | None = None
        self.run_end_lsl_time: float | None = None

        self._saved = False
        self._marker_log_saved = False
        self.eeg_recording_saved = False

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

    def _resolve_subject(self) -> None:
        if self.cli_args.subject:
            self.subject_id = normalize_id(self.cli_args.subject, "sub-")
            return
        if self.test_mode:
            self.subject_id = "999"
            return
        if PSYCHOPY_AVAILABLE:
            info = {"Subject Number": ""}
            dlg = gui.DlgFromDict(info, title="Two-Armed Bandit Task")
            if not dlg.OK:
                raise SystemExit(0)
            self.subject_id = normalize_id(info["Subject Number"], "sub-")
        else:
            self.subject_id = input("Subject ID: ")

    def _next_run_number(self) -> int:
        pattern = re.compile(
            rf"^sub-{re.escape(self.subject_id)}_ses-{re.escape(self.session_id)}_run-(\d+)_task-bandit_"
        )
        existing = []
        for path in self.data_dir.glob(f"sub-{self.subject_id}_ses-{self.session_id}_run-*_task-bandit_*.csv"):
            match = pattern.match(path.name)
            if match:
                existing.append(int(match.group(1)))
        return max(existing, default=0) + 1

    def _setup_session(self) -> None:
        self.session_id = normalize_id(self.cli_args.session or "001", "ses-")
        self.date_label = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

        # Save all participant data to a single directory
        self.data_dir = Path(
            r"C:\Users\Public\LAB PROJECTS\Smith-Lab\tacs3-bluesky\stimulation\pre-stimulation-participant-responses"
        )
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # Always use a single run label
        self.run_label = "run-01"


    def _select_flowers_for_run(self) -> bool:
        available = set(self.flower_id_pool) - self.used_flowers
        if len(available) < 2:
            self.used_flowers = set()
            available = set(self.flower_id_pool)
        if len(available) < 2:
            print("Error: need at least 2 configured flower stimulus ids (stimuli.flower_indices).")
            return False
        self.current_flowers = random.sample(sorted(available), 2)
        self.used_flowers.update(self.current_flowers)
        return True

    def _slot_positions(self):
        half_sep = self.slot_separation / 2.0
        if random.random() < 0.5:
            return (-half_sep, 0.0), (half_sep, 0.0), "left", "right"
        return (half_sep, 0.0), (-half_sep, 0.0), "right", "left"

    def _should_stop_run(self) -> bool:
        elapsed = time.time() - self.run_start_time
        duration_reached = elapsed >= self.max_duration_seconds
        trial_target_reached = self.target_trials is not None and self.current_trial >= self.target_trials
        if self.stop_rule == "duration":
            return duration_reached
        if self.stop_rule == "trials":
            return trial_target_reached
        if self.stop_rule == "duration_and_trials":
            return duration_reached and trial_target_reached
        return duration_reached or trial_target_reached

    def _feedback_marker(self, reward: bool | None) -> tuple[int, str]:
        if reward is None:
            return int(self.marker_codes.get("feedback_miss", 33)), "miss"
        if reward:
            return int(self.marker_codes.get("feedback_win", 31)), "win"
        return int(self.marker_codes.get("feedback_loss", 32)), "loss"

    def _advance_contingency(self) -> None:
        self.trial_in_contingency += 1
        if self.trial_in_contingency >= self.contingency_trials:
            self.current_good = 3 - self.current_good
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
        choice_window_onset_task_time,
        choice_window_onset_lsl_time,
        choice_onset_task_time,
        choice_onset_lsl_time,
        choice_marker_send_lsl_time,
        feedback_task_time,
        feedback_lsl_time,
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
            "choice_window_onset_task_time": choice_window_onset_task_time,
            "choice_window_onset_lsl_time": choice_window_onset_lsl_time,
            "choice_onset_task_time": choice_onset_task_time,
            "choice_onset_lsl_time": choice_onset_lsl_time,
            "choice_marker_send_lsl_time": choice_marker_send_lsl_time,
            "feedback_onset_task_time": feedback_task_time,
            "feedback_onset_lsl_time": feedback_lsl_time,
            "lsl_marker_send_time": feedback_lsl_time,
            "wait_time": wait_time * 1000.0,
            "iti": self.timing["iti_duration"] * 1000.0,
            "run_start_task_time": 0.0,
            "run_start_lsl_time": self.run_start_lsl_time,
            "run_end_task_time": None,
            "run_end_lsl_time": None,
        }

    def save_data(self) -> None:
        if self._saved or not self.trial_data:
            return
        for row in self.trial_data:
            row["run_end_task_time"] = self.run_end_task_time
            row["run_end_lsl_time"] = self.run_end_lsl_time
        df = pd.DataFrame(self.trial_data)
        filename = f"sub-{self.subject_id}_ses-{self.session_id}_{self.run_label}_task-bandit_{self.date_label}.csv"
        filepath = self.data_dir / filename
        df.to_csv(filepath, index=False)
        self._saved = True
        print(f"\nData saved to: {filepath}")

    def cleanup(self) -> None:
        if self.run_start_time is not None and self.run_end_lsl_time is None:
            self.run_end_task_time = time.time() - self.run_start_time
            self.run_end_lsl_time = self.event_logger.send(200, "run_end", {"run_label": self.run_label})
        self.save_data()
        if self.lsl_trigger:
            self.lsl_trigger.stop_listening()


    # -- test-mode (headless, no PsychoPy/pygame required) ------------------

    def _run_test_mode(self) -> None:
        if not self._select_flowers_for_run():
            return
        self.run_start_time = time.time()
        self.run_start_task_time = 0.0
        self.run_start_lsl_time = self.event_logger.send(100, "run_start", {"run_label": self.run_label})

        while not self._should_stop_run():
            trial_num = self.current_trial + 1
            _, _, slot1_side, slot2_side = self._slot_positions()
            self.slot1_side, self.slot2_side = slot1_side, slot2_side

            trial_start_task_time = time.time() - self.run_start_time
            trial_start_lsl_time = lsl_clock()
            self.event_logger.send(10, "trial_start", {"trial_num": trial_num})

            choice_window_onset_task_time = time.time() - self.run_start_time
            choice_window_onset_lsl_time = lsl_clock()
            responded = random.random() < 0.9
            choice = random.choice([1, 2]) if responded else None
            rt = random.uniform(0.25, max(0.26, self.timing["max_response_time"] - 0.05)) if responded else None

            if choice is not None:
                correct = choice == self.current_good
                reward_prob = self.win_fraction if correct else 1 - self.win_fraction
                reward = random.random() < reward_prob
                rt_ms = rt * 1000.0
                choice_onset_task_time = choice_window_onset_task_time + rt
                choice_onset_lsl_time = choice_window_onset_lsl_time + rt
                choice_marker_send_lsl_time = self.event_logger.send(
                    20, "choice", {"trial_num": trial_num, "choice": choice}
                )
            else:
                correct = reward = rt_ms = None
                choice_onset_task_time = choice_onset_lsl_time = choice_marker_send_lsl_time = None

            wait_time = random.uniform(self.timing["wait_duration_min"], self.timing["wait_duration_max"])
            feedback_marker, outcome = self._feedback_marker(reward)
            feedback_lsl_time = self.event_logger.send(feedback_marker, f"feedback_{outcome}", {"trial_num": trial_num})
            feedback_task_time = time.time() - self.run_start_time

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
                choice_window_onset_task_time=choice_window_onset_task_time,
                choice_window_onset_lsl_time=choice_window_onset_lsl_time,
                choice_onset_task_time=choice_onset_task_time,
                choice_onset_lsl_time=choice_onset_lsl_time,
                choice_marker_send_lsl_time=choice_marker_send_lsl_time,
                feedback_task_time=feedback_task_time,
                feedback_lsl_time=feedback_lsl_time,
                wait_time=wait_time,
            )
            self.trial_data.append(row)
            self._advance_contingency()
            self.current_trial += 1

        self.run_end_task_time = time.time() - self.run_start_time
        self.run_end_lsl_time = self.event_logger.send(200, "run_end", {"run_label": self.run_label})
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
        self.fixation = visual.TextStim(self.win, text="+", height=0.05, color="white")
        self._highlight_ring = visual.Circle(
            self.win, radius=self.slot_size / 2.0 + 0.02, lineColor="white", lineWidth=6, fillColor=None, edges=64
        )
        self._instructions_stim = visual.TextStim(self.win, text="", color="white", height=0.045, wrapWidth=1.6)

    def _build_feedback_stims(self) -> None:
        win_images = sorted(self.stimuli_dir.glob("*-win.png")) if self.stimuli_dir.exists() else []
        loss_images = sorted(self.stimuli_dir.glob("*-loss.png")) if self.stimuli_dir.exists() else []
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
        lines = [
            f"Two-Armed Bandit Task — {self.run_label}",
            "",
            "Choose between two options using",
            "A for left and L for right",
            "",
            "One option is better than the other.",
            "The better option can change!",
            "Try to win as much as possible.",
            "",
            "Press SPACE when ready to begin",
        ]
        self._instructions_stim.text = "\n".join(lines)
        self._instructions_stim.draw()
        self.win.flip()
        if self.auto_respond:
            core.wait(0.05)
            return True
        while True:
            keys = event.getKeys(keyList=["space", "escape"])
            if "space" in keys:
                return True
            if "escape" in keys:
                return False
            core.wait(0.01)

    def _show_waiting_screen(self) -> bool:
        lines = [
            f"Two-Armed Bandit Task — {self.run_label}",
            "",
            "Please wait for the experimenter",
            "to start the task, then",
            "",
            "Press SPACE to begin",
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
            keys = event.getKeys(keyList=["space", "escape"])
            if "space" in keys:
                return True
            if "escape" in keys:
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
            if self.lsl_trigger and self.lsl_trigger.check_for_stimulation_stop():
                return "stim_stopped", None
            keys = event.getKeys(keyList=["1", "2", "num_1", "num_2", "a", "l", "escape"], timeStamped=clock)
            if keys:
                key, rt = keys[0]
                if key == "escape":
                    return "escape", rt
                if key in ("1", "num_1"):
                    return 1, rt
                if key in ("2", "num_2"):
                    return 2, rt
                if key == "a":
                    return (1 if self.slot1_side == "left" else 2), rt
                if key == "l":
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
        trial_start_lsl_time = lsl_clock()
        self.event_logger.send(10, "trial_start", {"trial_num": trial_num})

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
        choice_window_onset_lsl_time = lsl_clock()

        if self.auto_respond:
            rt = min(self.timing["max_response_time"] - 0.05, 0.5)
            core.wait(rt)
            choice = random.choice([1, 2])
        else:
            choice, rt = self._get_response(self.timing["max_response_time"])

        if choice in ("escape", "stim_stopped"):
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

            correct = choice == self.current_good
            reward_prob = self.win_fraction if correct else 1 - self.win_fraction
            reward = random.random() < reward_prob
            rt_ms = rt * 1000.0
            choice_onset_task_time = choice_window_onset_task_time + rt
            choice_onset_lsl_time = choice_window_onset_lsl_time + rt
            choice_marker_send_lsl_time = self.event_logger.send(
                20, "choice", {"trial_num": trial_num, "choice": choice, "choice_onset_lsl_time": choice_onset_lsl_time}
            )
        else:
            correct = reward = rt_ms = None
            choice_onset_task_time = choice_onset_lsl_time = choice_marker_send_lsl_time = None

        self.win.flip()
        wait_time = random.uniform(self.timing["wait_duration_min"], self.timing["wait_duration_max"])
        core.wait(wait_time)

        feedback_marker, outcome = self._feedback_marker(reward)
        feedback_lsl_time = self.event_logger.send(feedback_marker, f"feedback_{outcome}", {"trial_num": trial_num})
        feedback_task_time = time.time() - self.run_start_time
        self._feedback_stims[outcome].draw()
        self.win.flip()
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
            choice_window_onset_task_time=choice_window_onset_task_time,
            choice_window_onset_lsl_time=choice_window_onset_lsl_time,
            choice_onset_task_time=choice_onset_task_time,
            choice_onset_lsl_time=choice_onset_lsl_time,
            choice_marker_send_lsl_time=choice_marker_send_lsl_time,
            feedback_task_time=feedback_task_time,
            feedback_lsl_time=feedback_lsl_time,
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
            if not self._show_instructions():
                return
            event.clearEvents()
            if not self._show_waiting_screen():
                return
            if not self._show_start_buffer():
                return

            self.run_start_time = time.time()
            self.run_start_task_time = 0.0
            self.run_start_lsl_time = self.event_logger.send(100, "run_start", {"run_label": self.run_label})

            print(f"\nStarting {self.run_label}")
            print(f"Duration: {self.max_duration_seconds / 60.0:.1f} minutes, target trials: {self.target_trials}")
            print("Press ESC to abort\n")

            while self._run_trial():
                if self.current_trial and self.current_trial % 10 == 0:
                    elapsed = time.time() - self.run_start_time
                    print(f"  Trial {self.current_trial}, Time: {elapsed:.1f}s")

            self.run_end_task_time = time.time() - self.run_start_time
            self.run_end_lsl_time = self.event_logger.send(200, "run_end", {"run_label": self.run_label})
            print(f"\nRun complete. Total trials: {self.current_trial}")
            if self.cli_args.localizer:
                print(
                    "Next step: python run_rhythm_estimation.py --task bandit "
                    f"--subject {self.subject_id} --session {self.session_id} --auto-find --all-defaults"
                )
            self._show_run_end_screen()
        finally:
            if self.win is not None:
                self.win.close()

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
    parser.add_argument("--session", default="001", help="Session ID, with or without the ses- prefix.")
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
    task = BanditTask(config, cli_args)
    task.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
