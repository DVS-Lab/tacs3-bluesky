#!/usr/bin/env python3
"""Stop Signal Task with StarStim/NIC-2 sync support.

Adapted from the Scan-SST task in DVS-Lab/gambling-2025. Task mechanics
(go/stop-signal trial structure, SSD staircase, timing) are identical
regardless of stimulation condition. Frequency/condition selection happens
outside this script (see select_stimulation_frequency.py and
run_rhythm_estimation.py) and is applied by the operator directly in NIC-2 -
this script has no concept of "mode" or condition, to avoid leaking
condition information into its output or behavior.

Run 1:
    Displays the full task instructions before starting.

Run 2:
    Displays only:

        Press SPACE to begin.

    Pressing SPACE starts the task.

The localizer option is retained for the pre-stimulation baseline run.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime
import json
from pathlib import Path
import queue
import random
import re
import time
import subprocess
import sys

import numpy as np

from eeg_lsl_recorder import LSLEEGRecorder, save_recording_summary
from task_markers import TaskMarkerLogger

try:
    from psychopy import core, event, gui, visual

    PSYCHOPY_AVAILABLE = True
except ImportError:  # pragma: no cover - operator dependency
    core = event = gui = visual = None
    PSYCHOPY_AVAILABLE = False


def normalize_id(value: str, prefix: str) -> str:
    """Remove a prefix such as sub- or ses- from an ID."""
    return str(value).replace(prefix, "").strip()


def load_config(config_path: str | Path | None = None) -> dict:
    if config_path is None:
        config_path = Path(__file__).resolve().parent / "config.json"

    with Path(config_path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


class SSTTask:

    def _start_lsl_marker_detector(self) -> None:
        """Launch lsl_marker_detector.py as a separate process."""

        if self.test_mode:
            return

        detector_path = (
            Path(__file__).resolve().parent
            / "lsl_marker_detector.py"
        )

        if not detector_path.exists():
            print(
                f"WARNING: LSL marker detector not found: "
                f"{detector_path}"
            )
            return

        try:
            subprocess.Popen(
                [
                    sys.executable,
                    str(detector_path),
                ],
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
            )

            print(
                "LSL marker detector started: "
                f"{detector_path}"
            )

        except Exception as exc:
            print(
                "WARNING: Could not start "
                f"LSL marker detector: {exc}"
            )

    def __init__(
        self,
        config: dict,
        cli_args: argparse.Namespace,
    ):
        self.config = config
        self.cli_args = cli_args

        self.test_mode = bool(
            cli_args.test_mode
        )

        self.auto_respond = bool(
            cli_args.auto_respond
            or self.test_mode
        )

        sst_cfg = config.get(
            "sst",
            {}
        )

        self.stop_probability = float(
            sst_cfg.get(
                "stop_probability",
                0.3,
            )
        )

        self.stimulus_duration_sec = float(
            sst_cfg.get(
                "stimulus_duration_sec",
                1.5,
            )
        )

        self.initial_ssd_sec = float(
            sst_cfg.get(
                "initial_ssd_sec",
                0.25,
            )
        )

        self.ssd_step_sec = float(
            sst_cfg.get(
                "ssd_step_sec",
                0.05,
            )
        )

        self.min_ssd_sec = float(
            sst_cfg.get(
                "min_ssd_sec",
                0.05,
            )
        )

        self.max_ssd_sec = float(
            sst_cfg.get(
                "max_ssd_sec",
                0.9,
            )
        )

        self.isi_range_sec = tuple(
            sst_cfg.get(
                "isi_range_sec",
                [0.8, 2.5],
            )
        )

        self.iti_range_sec = tuple(
            sst_cfg.get(
                "iti_range_sec",
                [1.5, 4.0],
            )
        )

        self.target_trials = sst_cfg.get(
            "target_trials",
            200,
        )

        self.stop_rule = sst_cfg.get(
            "stop_rule",
            "duration_or_trials",
        )

        duration_minutes = float(
            cli_args.duration_minutes
            or config.get(
                "experiment",
                {},
            ).get(
                "run_duration_minutes",
                6,
            )
        )

        self.max_duration_seconds = (
            duration_minutes * 60.0
        )

        self.marker_codes = config.get(
            "stimulation",
            {},
        ).get(
            "markers",
            {},
        )

        # --------------------------------------------------------------
        # Subject / session / run information
        # --------------------------------------------------------------

        self.subject_id: str | None = None
        self.session_id: str | None = None
        self.run_label: str | None = None
        self.date_label: str | None = None
        self.data_dir: Path | None = None

        # --------------------------------------------------------------
        # Trial information
        # --------------------------------------------------------------

        self.results: list[dict] = []

        self.current_trial = 0
        self.ssd = self.initial_ssd_sec
        self.task_should_stop = False

        # --------------------------------------------------------------
        # Timing
        # --------------------------------------------------------------

        self.run_start_time: float | None = None
        self.run_start_task_time: float | None = None
        self.run_start_lsl_time: float | None = None

        self.run_end_task_time: float | None = None
        self.run_end_lsl_time: float | None = None

        # --------------------------------------------------------------
        # Saving state
        # --------------------------------------------------------------

        self._saved = False
        self._marker_log_saved = False
        self.eeg_recording_saved = False

        # --------------------------------------------------------------
        # Marker logging
        # --------------------------------------------------------------

        self.event_logger = TaskMarkerLogger(
            config.get(
                "eeg_recording",
                {},
            ).get(
                "marker_stream_name",
                "LSLOutletStreamName-Markers",
            )
        )

        # --------------------------------------------------------------
        # EEG
        # --------------------------------------------------------------

        self.eeg_recorder: LSLEEGRecorder | None = None


        # --------------------------------------------------------------
        # PsychoPy window
        # --------------------------------------------------------------

        self.win = None

    # ==================================================================
    # SETUP
    # ==================================================================

    def _resolve_subject(self) -> None:
        """Get subject ID, session number, and run number.

        In normal PsychoPy mode, one dialog asks for:

            Subject Number
            Session Number
            Run Number

        Run Number must be 1 or 2.

        Session Number is typed manually and can be 1, 2, 3, etc.

        If --subject, --session, or --run are supplied on the command
        line, those values take precedence over the dialog values.
        """

        # --------------------------------------------------------------
        # TEST MODE
        # --------------------------------------------------------------

        if self.test_mode:

            # Subject
            if self.cli_args.subject:
                self.subject_id = normalize_id(
                    self.cli_args.subject,
                    "sub-",
                )
            else:
                self.subject_id = "999"

            # Session
            if self.cli_args.session:
                self.session_id = normalize_id(
                    self.cli_args.session,
                    "ses-",
                )
            else:
                self.session_id = "1"

            # Run
            if self.cli_args.run is None:
                self.cli_args.run = 1

            if self.cli_args.run not in (1, 2):
                raise ValueError(
                    "Run Number must be 1 or 2."
                )

            return

        # --------------------------------------------------------------
        # NORMAL PSYCHOPY MODE
        # --------------------------------------------------------------

        if PSYCHOPY_AVAILABLE:

            # If command-line values were supplied, use them as
            # the starting values in the dialog.

            info = {
                "Subject Number": (
                    self.cli_args.subject
                    if self.cli_args.subject
                    else ""
                ),

                "Session Number": (
                    self.cli_args.session
                    if self.cli_args.session
                    else "1"
                ),

                "Run Number": (
                    str(self.cli_args.run)
                    if self.cli_args.run is not None
                    else "1"
                ),
            }

            dlg = gui.DlgFromDict(
                info,
                title="Stop Signal Task",
            )

            if not dlg.OK:
                raise SystemExit(0)

            # ----------------------------------------------------------
            # Subject ID
            # ----------------------------------------------------------

            if self.cli_args.subject:

                self.subject_id = normalize_id(
                    self.cli_args.subject,
                    "sub-",
                )

            else:

                self.subject_id = normalize_id(
                    info["Subject Number"],
                    "sub-",
                )

            # ----------------------------------------------------------
            # Session Number
            # ----------------------------------------------------------

            if self.cli_args.session:

                self.session_id = normalize_id(
                    self.cli_args.session,
                    "ses-",
                )

            else:

                self.session_id = normalize_id(
                    info["Session Number"],
                    "ses-",
                )

            # Make sure something was entered for session.
            if not self.session_id:
                raise ValueError(
                    "Session Number cannot be blank."
                )

            # ----------------------------------------------------------
            # Run Number
            # ----------------------------------------------------------

            if self.cli_args.run is None:

                try:
                    self.cli_args.run = int(
                        info["Run Number"]
                    )

                except ValueError:
                    raise ValueError(
                        "Run Number must be 1 or 2."
                    )

        # --------------------------------------------------------------
        # FALLBACK WITHOUT PSYCHOPY
        # --------------------------------------------------------------

        else:

            # Subject
            if self.cli_args.subject:

                self.subject_id = normalize_id(
                    self.cli_args.subject,
                    "sub-",
                )

            else:

                self.subject_id = input(
                    "Subject ID: "
                )

            # Session
            if self.cli_args.session:

                self.session_id = normalize_id(
                    self.cli_args.session,
                    "ses-",
                )

            else:

                session_input = input(
                    "Session Number: "
                )

                self.session_id = normalize_id(
                    session_input,
                    "ses-",
                )

            if not self.session_id:
                raise ValueError(
                    "Session Number cannot be blank."
                )

            # Run
            if self.cli_args.run is None:

                run_input = input(
                    "Run Number (1 or 2): "
                )

                try:

                    self.cli_args.run = int(
                        run_input
                    )

                except ValueError:

                    raise ValueError(
                        "Run Number must be 1 or 2."
                    )

        # --------------------------------------------------------------
        # VALIDATE RUN NUMBER
        # --------------------------------------------------------------

        if self.cli_args.run not in (1, 2):

            raise ValueError(
                "Run Number must be 1 or 2."
            )

    def _next_run_number(self) -> int:

        pattern = re.compile(
            rf"^sub-{re.escape(self.subject_id)}"
            rf"_ses-{re.escape(self.session_id)}"
            rf"_run-(\d+)_task-SST_"
        )

        existing = []

        for path in self.data_dir.glob(
            f"sub-{self.subject_id}"
            f"_ses-{self.session_id}"
            f"_run-*_task-SST_*.csv"
        ):

            match = pattern.match(
                path.name
            )

            if match:

                existing.append(
                    int(match.group(1))
                )

        return max(
            existing,
            default=0,
        ) + 1

    def _setup_session(self) -> None:

        # If _resolve_subject() already obtained the session number
        # from the PsychoPy dialog, keep it.
        #
        # Otherwise, fall back to the command-line/default value.

        if self.session_id is None:

            self.session_id = normalize_id(
                self.cli_args.session or "1",
                "ses-",
            )

        self.date_label = datetime.now().strftime(
            "%Y-%m-%d_%H-%M-%S"
        )

        data_root = Path(
            self.config.get(
                "paths",
                {},
            ).get(
                "data_dir",
                "../data",
            )
        )

        self.data_dir = (
            Path(__file__).resolve().parent
            / data_root
        ).resolve() / f"sub-{self.subject_id}"

        self.data_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.eeg_dir = (
            self.data_dir / "eeg"
        )

        self.eeg_dir.mkdir(
            exist_ok=True
        )

        self.qc_dir = (
            self.data_dir / "qc"
        )

        self.qc_dir.mkdir(
            exist_ok=True
        )

        self.logs_dir = (
            self.data_dir / "logs"
        )

        self.logs_dir.mkdir(
            exist_ok=True
        )

        # --------------------------------------------------------------
        # RUN LABEL
        # --------------------------------------------------------------

        if self.cli_args.localizer:

            self.run_label = (
                "run-localizer"
            )

        else:

            run_number = (
                self.cli_args.run
            )

            self.run_label = (
                f"run-{int(run_number):02d}"
            )

        base = (
            f"sub-{self.subject_id}"
            f"_ses-{self.session_id}"
            f"_{self.run_label}"
            f"_task-SST"
        )

        self.marker_log_path = (
            self.logs_dir
            / f"{base}_markers.jsonl"
        )

        self.eeg_summary_path = (
            self.logs_dir
            / f"{base}_eeg_summary.json"
        )

    def _should_stop_run(self) -> bool:

        elapsed = (
            time.time()
            - self.run_start_time
        )

        duration_reached = (
            elapsed
            >= self.max_duration_seconds
        )

        trial_target_reached = (
            self.target_trials is not None
            and self.current_trial
            >= self.target_trials
        )

        if self.stop_rule == "duration":

            return duration_reached

        if self.stop_rule == "trials":

            return trial_target_reached

        if self.stop_rule == "duration_and_trials":

            return (
                duration_reached
                and trial_target_reached
            )

        return (
            duration_reached
            or trial_target_reached
        )

    # ==================================================================
    # EEG RECORDING
    # ==================================================================

    def _start_eeg_recording_if_requested(
        self,
    ) -> None:

        eeg_config = self.config.get(
            "eeg_recording",
            {},
        )

        if not eeg_config.get(
            "record_lsl_eeg_during_localizer",
            True,
        ):
            return

        self.eeg_recorder = LSLEEGRecorder(
            preferred_stream_type=eeg_config.get(
                "preferred_stream_type",
                "EEG",
            ),
            preferred_stream_name_contains=eeg_config.get(
                "preferred_stream_name_contains",
                "StarStim",
            ),
        )

        if not self.eeg_recorder.start():

            print(
                "EEG recording not started: "
                f"{self.eeg_recorder.status_message}"
            )

    def _stop_eeg_recording(self) -> None:

        if (
            self.eeg_recording_saved
            or self.eeg_recorder is None
        ):
            return

        eeg_config = self.config.get(
            "eeg_recording",
            {},
        )

        basename = (
            f"sub-{self.subject_id}"
            f"_ses-{self.session_id}"
            f"_{self.run_label}"
            f"_task-SST_eeg"
        )

        summary = self.eeg_recorder.save(
            self.eeg_dir,
            basename,
            write_raw_csv=eeg_config.get(
                "write_raw_csv",
                True,
            ),
            write_raw_npz=eeg_config.get(
                "write_raw_npz",
                True,
            ),
            extra_metadata={
                "subject_id": (
                    f"sub-{self.subject_id}"
                ),
                "session_id": (
                    f"ses-{self.session_id}"
                ),
                "task": "SST",
                "run_label": self.run_label,
            },
        )

        save_recording_summary(
            summary,
            self.eeg_summary_path,
        )

        self.eeg_recording_saved = True

    # ==================================================================
    # ENTRY POINT
    # ==================================================================

    def run(self) -> None:

        try:

            # IMPORTANT:
            # This happens before the PsychoPy instruction screen
            # is created, so the selected subject/session/run values
            # are available when deciding what to display.

            self._resolve_subject()

            self._setup_session()

            self._start_lsl_marker_detector()

            if self.test_mode:

                self._run_test_mode()

            else:

                self._run_psychopy()

        except KeyboardInterrupt:

            print(
                "\nSession interrupted by user"
            )

        finally:

            self.cleanup()

    def cleanup(self) -> None:

        if (
            self.run_start_time is not None
            and self.run_end_lsl_time is None
        ):

            self.run_end_task_time = (
                time.time()
                - self.run_start_time
            )

            self.run_end_lsl_time = (
                self.event_logger.send(
                    200,
                    "run_end",
                    {
                        "task": "SST",
                        "run": self.run_label,
                    },
                )
            )

        self.save_events()


        self._stop_eeg_recording()

        if (
            not self._marker_log_saved
            and self.event_logger.events
        ):

            self.event_logger.save(
                self.marker_log_path
            )

            self._marker_log_saved = True

    # ==================================================================
    # TEST MODE
    # ==================================================================

    def _run_test_mode(self) -> None:

        rng = np.random.default_rng(
            911
        )

        self.ssd = (
            self.initial_ssd_sec
        )

        self.run_start_time = (
            time.time()
        )

        self.run_start_task_time = 0.0

        self.run_start_lsl_time = (
            self.event_logger.send(
                100,
                "run_start",
                {
                    "task": "SST",
                    "run": self.run_label,
                },
            )
        )

        while not self._should_stop_run():

            trial_num = (
                self.current_trial + 1
            )

            direction = (
                "left"
                if trial_num % 2
                else "right"
            )

            is_stop = bool(
                rng.random()
                < self.stop_probability
            )

            rt = float(
                rng.normal(
                    0.42,
                    0.07,
                )
            )

            responded = (
                not is_stop
                or rng.random() < 0.5
            )

            self._record_trial(
                trial_num,
                direction,
                is_stop,
                responded,
                rt if responded else None,
                self.ssd,
            )

            if is_stop:

                self.ssd = (

                    min(
                        self.max_ssd_sec,
                        self.ssd
                        + self.ssd_step_sec,
                    )

                    if not responded

                    else max(
                        self.min_ssd_sec,
                        self.ssd
                        - self.ssd_step_sec,
                    )
                )

            self.current_trial += 1

        self.run_end_task_time = (
            time.time()
            - self.run_start_time
        )

        self.run_end_lsl_time = (
            self.event_logger.send(
                200,
                "run_end",
                {
                    "task": "SST",
                    "run": self.run_label,
                },
            )
        )

        print(
            "SST test mode complete: "
            f"{self.current_trial} simulated trials."
        )

    # ==================================================================
    # WAITING / INSTRUCTION SCREEN
    # ==================================================================

    def _show_waiting_screen(
        self,
        msg_stim,
    ) -> bool:
        """Show the appropriate pre-run screen.

        Run 1:
            Full instructions.

        Run 2:
           No instructions

        = starts the task for both runs.

        ESC or Z cancels the run.

        """

        msg_stim.draw()

        self.win.flip()

        if self.auto_respond:

            core.wait(0.05)

            return True


        while True:

            keys = event.getKeys(
                keyList=[
                    "equal",
                    "escape",
                    "z",
                ]
            )

            # ----------------------------------------------------------
            # SPACE STARTS THE TASK
            # ----------------------------------------------------------

            if "equal" in keys:
                return True

            # ----------------------------------------------------------
            # ESCAPE / Z CANCEL
            # ----------------------------------------------------------

            if (
                "escape" in keys
                or "z" in keys
            ):

                return False

            core.wait(0.01)

    # ==================================================================
    # PSYCHOPY TASK
    # ==================================================================

    def _run_psychopy(self) -> None:

        if not PSYCHOPY_AVAILABLE:

            raise RuntimeError(
                "PsychoPy is not installed. "
                "Use --test-mode or install "
                "psychopy to run SST."
            )

        script_dir = (
            Path(__file__).resolve().parent
            / "sst"
        )

        screen = int(
            self.cli_args.screen
            if self.cli_args.screen is not None
            else 0
        )

        self.win = visual.Window(
            size=(1200, 900),
            color="grey",
            fullscr=(
                not self.cli_args.windowed
            ),
            units="pix",
            screen=screen,
            allowGUI=False,
        )

        win = self.win

        try:

            # ==========================================================
            # IMAGE STIMULI
            # ==========================================================

            image_stimuli = {

                "left": visual.ImageStim(
                    win,
                    image=str(
                        script_dir
                        / "images"
                        / "left_arrow.png"
                    ),
                    size=(518, 300),
                ),

                "right": visual.ImageStim(
                    win,
                    image=str(
                        script_dir
                        / "images"
                        / "right_arrow.png"
                    ),
                    size=(518, 300),
                ),

                "left_red": visual.ImageStim(
                    win,
                    image=str(
                        script_dir
                        / "images"
                        / "left_red_arrow.png"
                    ),
                    size=(518, 300),
                ),

                "right_red": visual.ImageStim(
                    win,
                    image=str(
                        script_dir
                        / "images"
                        / "right_red_arrow.png"
                    ),
                    size=(518, 300),
                ),
            }

            fixation = visual.TextStim(
                win,
                text="+",
                height=40,
            )

            # ==========================================================
            # RUN-SPECIFIC INSTRUCTIONS
            # ==========================================================

            if self.cli_args.run == 2:

                wait_text = (
                    "Please wait for the task to begin."
                )

            else:

                wait_text = (
                    f"Stop Signal Task — "
                    f"{self.run_label}\n\n"
                    "to start the task.\n\n"
                    "Press A when the arrow points LEFT.\n"
                    "Press L when the arrow points RIGHT.\n"
                    "Respond as quickly as possible.\n\n"
                    "If the arrow turns RED, try to stop "
                    "yourself from pressing anything.\n\n"
                    "Please wait for the experimenter to start the task"
                )

            wait_msg = visual.TextStim(
                win,
                text=wait_text,
                color="white",
                height=36,
                wrapWidth=900,
            )

            # ==========================================================
            # WAIT FOR START
            # ==========================================================

            if not self._show_waiting_screen(
                wait_msg
            ):

                return

            # ==========================================================
            # START EEG RECORDING
            # ==========================================================

            self._start_eeg_recording_if_requested()

            # ==========================================================
            # START RUN
            # ==========================================================

            self.run_start_time = (
                time.time()
            )

            self.run_start_task_time = 0.0

            self.run_start_lsl_time = (
                self.event_logger.send(
                    100,
                    "run_start",
                    {
                        "task": "SST",
                        "run": self.run_label,
                    },
                )
            )

            self.ssd = (
                self.initial_ssd_sec
            )

            global_clock = core.Clock()

            # ==========================================================
            # MAIN TRIAL LOOP
            # ==========================================================

            while (
                not self._should_stop_run()
                and not self.task_should_stop
            ):

                trial_num = (
                    self.current_trial + 1
                )

                direction = random.choice(
                    [
                        "left",
                        "right",
                    ]
                )

                is_stop = (
                    random.random()
                    < self.stop_probability
                )

                expected_key = (
                    "a"
                    if direction == "left"
                    else "l"
                )

                isi = random.uniform(
                    *self.isi_range_sec
                )

                iti = random.uniform(
                    *self.iti_range_sec
                )

                # ------------------------------------------------------
                # FIXATION / ISI
                # ------------------------------------------------------

                fixation.draw()

                win.flip()

                core.wait(isi)

                # ------------------------------------------------------
                # GO STIMULUS
                # ------------------------------------------------------

                image_stimuli[
                    direction
                ].draw()

                win.flip()

                stim_onset = (
                    global_clock.getTime()
                )

                stim_lsl = (
                    self.event_logger.send(
                        int(
                            self.marker_codes.get(
                                "sst_go",
                                110,
                            )
                        ),
                        "sst_go",
                        {
                            "trial_num": trial_num,
                            "stimulus": direction,
                        },
                    )
                )

                trial_clock = core.Clock()

                responded = False
                response_key = ""
                response_time = None

                stop_presented = False
                stop_lsl_time = None

                simulated_rt = (
                    max(
                        0.05,
                        random.gauss(
                            0.42,
                            0.07,
                        ),
                    )
                    if self.auto_respond
                    else None
                )

                # ------------------------------------------------------
                # RESPONSE WINDOW
                # ------------------------------------------------------

                while (
                    trial_clock.getTime()
                    < self.stimulus_duration_sec
                ):

                    # --------------------------------------------------
                    # AUTO RESPONSE
                    # --------------------------------------------------

                    if self.auto_respond:

                        if (
                            not responded
                            and simulated_rt is not None
                            and trial_clock.getTime()
                            >= simulated_rt
                        ):

                            responded = True

                            response_key = (
                                expected_key
                                if random.random()
                                < 0.95
                                else (
                                    "l"
                                    if expected_key == "a"
                                    else "a"
                                )
                            )

                            response_time = (
                                simulated_rt
                            )

                    # --------------------------------------------------
                    # REAL PARTICIPANT RESPONSE
                    # --------------------------------------------------

                    else:

                        keys = event.getKeys(
                            keyList=[
                                "a",
                                "l",
                                "z",
                            ],
                            timeStamped=trial_clock,
                        )

                        if keys:

                            for key, timestamp in keys:

                                if key == "z":

                                    self.task_should_stop = True

                                    break

                                responded = True

                                response_key = key

                                response_time = (
                                    float(timestamp)
                                )

                                break

                    # --------------------------------------------------
                    # STOP IF PARTICIPANT RESPONDED
                    # --------------------------------------------------

                    if (
                        self.task_should_stop
                        or responded
                    ):

                        break

                    # --------------------------------------------------
                    # PRESENT STOP SIGNAL
                    # --------------------------------------------------

                    if (
                        is_stop
                        and not stop_presented
                        and trial_clock.getTime()
                        >= self.ssd
                    ):

                        image_stimuli[
                            f"{direction}_red"
                        ].draw()

                        win.flip()

                        stop_lsl_time = (
                            self.event_logger.send(
                                int(
                                    self.marker_codes.get(
                                        "sst_stop",
                                        111,
                                    )
                                ),
                                "sst_stop",
                                {
                                    "trial_num": trial_num,
                                    "ssd": self.ssd,
                                },
                            )
                        )

                        stop_presented = True

                    if self.auto_respond:

                        core.wait(0.01)

                # ------------------------------------------------------
                # ABORT TASK IF REQUESTED
                # ------------------------------------------------------

                if self.task_should_stop:

                    break

                # ------------------------------------------------------
                # RECORD TRIAL
                # ------------------------------------------------------

                self._record_trial(
                    trial_num,
                    direction,
                    is_stop,
                    responded,
                    response_time,
                    self.ssd,
                    stim_onset_task_time=stim_onset,
                    stim_onset_lsl_time=stim_lsl,
                    stop_presented=stop_presented,
                    stop_onset_lsl_time=stop_lsl_time,
                    response_key=response_key,
                )

                # ------------------------------------------------------
                # SSD STAIRCASE
                # ------------------------------------------------------

                if is_stop:

                    self.ssd = (

                        min(
                            self.max_ssd_sec,
                            self.ssd
                            + self.ssd_step_sec,
                        )

                        if not responded

                        else max(
                            self.min_ssd_sec,
                            self.ssd
                            - self.ssd_step_sec,
                        )
                    )

                self.current_trial += 1

                # ------------------------------------------------------
                # ITI
                # ------------------------------------------------------

                fixation.draw()

                win.flip()

                core.wait(iti)

            # ==========================================================
            # RUN COMPLETE
            # ==========================================================

            self.run_end_task_time = (
                time.time()
                - self.run_start_time
            )

            self.run_end_lsl_time = (
                self.event_logger.send(
                    200,
                    "run_end",
                    {
                        "task": "SST",
                        "run": self.run_label,
                    },
                )
            )

            print(
                f"\nRun complete. "
                f"Total trials: "
                f"{self.current_trial}"
            )

            # ==========================================================
            # LOCALIZER FOLLOW-UP
            # ==========================================================

            if self.cli_args.localizer:

                print(
                    "Next step: "
                    "python run_rhythm_estimation.py "
                    "--task sst "
                    f"--subject {self.subject_id} "
                    f"--session {self.session_id} "
                    "--auto-find --all-defaults"
                )

            # ==========================================================
            # END SCREEN
            # ==========================================================

            end_msg = visual.TextStim(
                win,
                text=(
                    "Run complete.\n\n"
                    "Thank you!"
                ),
                color="white",
                height=36,
            )

            end_msg.draw()

            win.flip()

            if self.auto_respond:

                core.wait(0.05)

            else:

                event.waitKeys(
                    keyList=[
                        "space",
                        "escape",
                    ],
                    maxWait=8.0,
                )

        finally:

            if self.win is not None:

                self.win.close()

    # ==================================================================
    # TRIAL RECORDING
    # ==================================================================

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
        stop_presented: bool | None = None,
        stop_onset_lsl_time: float | None = None,
        response_key: str = "",
    ) -> None:

        stop_presented = (
            is_stop
            if stop_presented is None
            else stop_presented
        )

        m = self.marker_codes

        expected_key = (
            "a"
            if direction == "left"
            else "l"
        )

        now_task = (
            time.time()
            - self.run_start_time
        )

        stim_onset_task_time = (
            now_task
            if stim_onset_task_time is None
            else stim_onset_task_time
        )

        stim_onset_lsl_time = (

            self.event_logger.send(
                int(
                    m.get(
                        "sst_go",
                        110,
                    )
                ),
                "sst_go",
                {
                    "trial_num": trial_num,
                    "stimulus": direction,
                },
            )

            if stim_onset_lsl_time is None

            else stim_onset_lsl_time
        )

        stop_onset_task_time = (
            stim_onset_task_time + ssd
            if stop_presented
            else None
        )

        if stop_presented:

            stop_onset_lsl_time = (
                stop_onset_lsl_time
                or self.event_logger.send(
                    int(
                        m.get(
                            "sst_stop",
                            111,
                        )
                    ),
                    "sst_stop",
                    {
                        "trial_num": trial_num,
                        "ssd": ssd,
                    },
                )
            )

        response_onset_task_time = (
            stim_onset_task_time + rt
            if responded
            and rt is not None
            else None
        )

        response_onset_lsl_time = None

        if responded and rt is not None:

            response_onset_lsl_time = (
                self.event_logger.send(
                    int(
                        m.get(
                            "sst_response",
                            120,
                        )
                    ),
                    "sst_response",
                    {
                        "trial_num": trial_num,
                        "rt": rt,
                    },
                )
            )

        go_correct = int(
            (not is_stop)
            and responded
            and (
                response_key
                in {
                    "",
                    expected_key,
                }
            )
        )

        go_incorrect = int(
            (not is_stop)
            and responded
            and response_key
            not in {
                "",
                expected_key,
            }
        )

        go_miss = int(
            (not is_stop)
            and not responded
        )

        stop_success = int(
            is_stop
            and not responded
        )

        stop_failure = int(
            is_stop
            and responded
        )

        if stop_success:

            outcome_marker = int(
                m.get(
                    "sst_stop_success",
                    131,
                )
            )

            outcome = "stop_success"

        elif stop_failure:

            outcome_marker = int(
                m.get(
                    "sst_stop_failure",
                    132,
                )
            )

            outcome = "stop_failure"

        elif go_correct:

            outcome_marker = int(
                m.get(
                    "sst_go_correct",
                    133,
                )
            )

            outcome = "go_correct"

        elif go_incorrect:

            outcome_marker = int(
                m.get(
                    "sst_go_incorrect",
                    134,
                )
            )

            outcome = "go_incorrect"

        else:

            outcome_marker = int(
                m.get(
                    "sst_go_miss",
                    135,
                )
            )

            outcome = "go_miss"

        outcome_lsl_time = (
            self.event_logger.send(
                outcome_marker,
                outcome,
                {
                    "trial_num": trial_num,
                },
            )
        )

        self.results.append(
            {
                "subject_id": (
                    f"sub-{self.subject_id}"
                ),
                "session_id": (
                    f"ses-{self.session_id}"
                ),
                "run": self.run_label,
                "localizer": int(
                    bool(
                        self.cli_args.localizer
                    )
                ),
                "trialNumber": trial_num,
                "stim_onset": (
                    stim_onset_task_time
                ),
                "stim_onset_lsl_time": (
                    stim_onset_lsl_time
                ),
                "stop_onset": (
                    stop_onset_task_time
                    if stop_onset_task_time
                    is not None
                    else ""
                ),
                "stop_onset_lsl_time": (
                    stop_onset_lsl_time
                    if stop_onset_lsl_time
                    is not None
                    else ""
                ),
                "response_onset": (
                    response_onset_task_time
                    if response_onset_task_time
                    is not None
                    else ""
                ),
                "response_onset_lsl_time": (
                    response_onset_lsl_time
                    if response_onset_lsl_time
                    is not None
                    else ""
                ),
                "outcome_lsl_time": (
                    outcome_lsl_time
                ),
                "marker_code": (
                    outcome_marker
                ),
                "stimulus": direction,
                "stop": int(is_stop),
                "response": bool(
                    responded
                ),
                "response_key": (
                    response_key
                ),
                "rt": (
                    rt
                    if rt is not None
                    else ""
                ),
                "ssd": round(
                    float(ssd),
                    3,
                ),
                "go_correct": (
                    go_correct
                ),
                "go_incorrect": (
                    go_incorrect
                ),
                "go_miss": (
                    go_miss
                ),
                "stop_success": (
                    stop_success
                ),
                "stop_failure_arrowcorrect": (
                    bool(
                        response_key
                        in {
                            "",
                            expected_key,
                        }
                    )
                    if stop_failure
                    else ""
                ),
                "outcome": outcome,
                "run_start_lsl_time": (
                    self.run_start_lsl_time
                ),
                "run_end_lsl_time": (
                    self.run_end_lsl_time
                ),
                "run_start_task_time": 0.0,
                "run_end_task_time": (
                    self.run_end_task_time
                ),
            }
        )

    # ==================================================================
    # SAVE EVENTS
    # ==================================================================

    def save_events(self) -> None:

        if (
            self._saved
            or not self.results
        ):
            return

        for row in self.results:

            row[
                "run_end_lsl_time"
            ] = self.run_end_lsl_time

            row[
                "run_end_task_time"
            ] = self.run_end_task_time

        base = (
            self.data_dir
            / f"sub-{self.subject_id}"
            f"_ses-{self.session_id}"
            f"_{self.run_label}"
            f"_task-SST"
            f"_{self.date_label}"
            f"_events"
        )

        fields = list(
            self.results[0].keys()
        )

        for suffix, delimiter in [
            (".csv", ","),
            (".tsv", "\t"),
        ]:

            with (
                base.with_suffix(suffix)
            ).open(
                "w",
                encoding="utf-8",
                newline="",
            ) as handle:

                writer = csv.DictWriter(
                    handle,
                    fieldnames=fields,
                    delimiter=delimiter,
                )

                writer.writeheader()

                writer.writerows(
                    self.results
                )

        self._saved = True

        print(
            "SST events saved to: "
            f"{base.with_suffix('.csv')}"
        )


# ======================================================================
# COMMAND-LINE ARGUMENTS
# ======================================================================

def build_arg_parser() -> argparse.ArgumentParser:

    parser = argparse.ArgumentParser(
        description=(
            "Run the Stop Signal Task "
            "with optional NIC-2 LSL trigger sync."
        )
    )

    parser.add_argument(
        "--config",
        default=str(
            Path(__file__).resolve().parent
            / "config.json"
        ),
    )

    parser.add_argument(
        "--subject",
        help=(
            "Subject ID, with or without "
            "the sub- prefix. If omitted, "
            "PsychoPy will ask for it."
        ),
    )

    parser.add_argument(
        "--session",
        help=(
            "Session number, with or without "
            "the ses- prefix. If omitted, "
            "PsychoPy will ask for it."
        ),
    )

    parser.add_argument(
        "--run",
        type=int,
        choices=[1, 2],
        help=(
            "Run number, either 1 or 2. "
            "If omitted, PsychoPy will ask "
            "for the run number."
        ),
    )

    parser.add_argument(
        "--localizer",
        action="store_true",
        help=(
            "Mark this as the pre-stimulation "
            "baseline run."
        ),
    )

    parser.add_argument(
        "--duration-minutes",
        type=float,
        help=(
            "Override the configured "
            "run duration."
        ),
    )

    parser.add_argument(
        "--test-mode",
        action="store_true",
        help=(
            "Run without PsychoPy, LSL, "
            "or stimulation hardware."
        ),
    )

    parser.add_argument(
        "--auto-respond",
        action="store_true",
        help=(
            "Auto-start and simulate "
            "button responses."
        ),
    )

    parser.add_argument(
        "--screen",
        type=int,
        help=(
            "Monitor index for the "
            "PsychoPy window."
        ),
    )

    parser.add_argument(
        "--windowed",
        action="store_true",
        help=(
            "Run in a window instead "
            "of fullscreen."
        ),
    )

    return parser


# ======================================================================
# MAIN
# ======================================================================

def main() -> int:

    cli_args = (
        build_arg_parser()
        .parse_args()
    )

    config = load_config(
        cli_args.config
    )

    task = SSTTask(
        config,
        cli_args,
    )

    task.run()

    return 0


if __name__ == "__main__":

    raise SystemExit(
        main()
    )