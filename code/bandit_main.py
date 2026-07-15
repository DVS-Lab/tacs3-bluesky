#!/usr/bin/env python3
"""
Two-Armed Bandit Task
Version 17: Multi-run support, display options, double-blinding
"""

import argparse
import copy
from datetime import datetime
import json
import os
from pathlib import Path
import queue
import sys
import threading
import time

import numpy as np
import pandas as pd
import pygame

from eeg_lsl_recorder import LSLEEGRecorder, save_recording_summary
from select_stimulation_frequency import select_stimulation_frequency

# LSL import with fallback (silent)
try:
    import pylsl
    LSL_AVAILABLE = True
except ImportError:
    LSL_AVAILABLE = False


LEGACY_EXPERIMENT_MODES = {"THETA_NIC", "DC_NIC", "BEHAVIORAL"}
SUPPORTED_EXPERIMENT_MODES = LEGACY_EXPERIMENT_MODES | {
    "LOCALIZER_FAST_THETA",
    "ITHETA_TACS",
    "FIXED_THETA_TACS",
    "IBETA_TACS",
    "FIXED_BETA_TACS",
    "SHAM",
}


def normalize_subject_id(subject_id: str) -> str:
    return str(subject_id).replace("sub-", "").strip()


def normalize_session_id(session_id: str) -> str:
    return str(session_id).replace("ses-", "").strip()


def normalize_mode(mode: str | None) -> str:
    value = (mode or "THETA_NIC").strip().upper()
    aliases = {
        "THETA": "FIXED_THETA_TACS",
        "FIXED_THETA": "FIXED_THETA_TACS",
        "BETA": "FIXED_BETA_TACS",
        "FIXED_BETA": "FIXED_BETA_TACS",
        "IBETA": "IBETA_TACS",
        "ITHEATA_TACS": "ITHETA_TACS",
        "ITTHETA_TACS": "ITHETA_TACS",
        "LOCALIZER_FAST_BANDIT": "LOCALIZER_FAST_THETA",
        "LOCALIZER_FAST_RHYTHM": "LOCALIZER_FAST_THETA",
        "BEHAVIOR": "BEHAVIORAL",
    }
    value = aliases.get(value, value)
    if value not in SUPPORTED_EXPERIMENT_MODES:
        raise ValueError(f"Unsupported mode '{mode}'. Expected one of {sorted(SUPPORTED_EXPERIMENT_MODES)}.")
    return value


def lsl_clock() -> float:
    if LSL_AVAILABLE:
        try:
            return float(pylsl.local_clock())
        except Exception:
            return time.time()
    return time.time()


def load_config_file(config_path: str | Path | None = None) -> dict:
    if config_path is None:
        config_path = Path(__file__).resolve().parent / "config.json"
    config_path = Path(config_path)
    with config_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


class TaskMarkerLogger:
    """Send task markers over LSL when available and always save a local event log."""

    def __init__(self, stream_name: str = "LSLOutletStreamName-Markers"):
        self.stream_name = stream_name
        self.outlet = None
        self.events = []
        if LSL_AVAILABLE:
            try:
                info = pylsl.StreamInfo(
                    stream_name,
                    "Markers",
                    1,
                    0,
                    pylsl.cf_int32,
                    f"{stream_name}-source",
                )
                self.outlet = pylsl.StreamOutlet(info)
            except Exception:
                self.outlet = None

    def send(self, marker_code: int, label: str, payload: dict | None = None) -> float:
        marker_time = lsl_clock()
        if self.outlet is not None:
            try:
                self.outlet.push_sample([int(marker_code)], marker_time)
            except Exception:
                pass
        event = {
            "marker_code": int(marker_code),
            "label": label,
            "lsl_time": marker_time,
            "created_at": datetime.utcnow().isoformat(timespec="milliseconds") + "Z",
        }
        if payload:
            event.update(payload)
        self.events.append(event)
        return marker_time

    def save(self, output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8") as handle:
            for event in self.events:
                handle.write(json.dumps(event) + "\n")


class LSLStimulationTrigger:
    """Listens for stimulation start/stop markers from NIC-2 via LSL"""
    
    def __init__(self, test_mode: bool = False):
        """
        Initialize LSL trigger listener
        
        Parameters:
        -----------
        test_mode : bool
            If True, simulate triggers without LSL
        """
        self.test_mode = test_mode
        self.inlet = None
        self.listening = False
        self.marker_queue = queue.Queue()
        self.listener_thread = None
        
        # Marker codes from NIC-2
        self.RAMP_UP_START = 201
        self.RAMP_DOWN_START = 202  
        self.STIMULATION_START = 203
        self.STIMULATION_STOP = 204
        
        # We trigger task start on stimulation start (203) - works for both active and sham
        self.TASK_START_MARKER = 203  # Stimulation start
        
    def connect(self) -> bool:
        """
        Connect to NIC-2 LSL marker stream
        
        Returns:
        --------
        bool : True if connected successfully
        """
        if self.test_mode:
            print("LSL: Connected to marker stream (TEST MODE)")
            return True
            
        if not LSL_AVAILABLE:
            print("LSL: pylsl not available, cannot connect to markers")
            return False
            
        try:
            print("LSL: Looking for NIC-2 marker streams...")
            
            # CHANGE #1 FIX: Suppress verbose network interface output from pylsl
            # Save stderr and redirect to devnull
            stderr_fd = sys.stderr.fileno()
            old_stderr = os.dup(stderr_fd)
            devnull_fd = os.open(os.devnull, os.O_WRONLY)
            os.dup2(devnull_fd, stderr_fd)
            
            try:
                streams = pylsl.resolve_streams(wait_time=5.0)
            finally:
                # Restore stderr
                os.dup2(old_stderr, stderr_fd)
                os.close(old_stderr)
                os.close(devnull_fd)
            
            if not streams:
                print("LSL: No streams found. Make sure LSL is enabled in NIC-2.")
                return False
            
            # Look for marker streams specifically
            marker_streams = [s for s in streams if s.type() == 'Markers']
            
            if not marker_streams:
                print(f"LSL: Found {len(streams)} streams but no marker streams:")
                for i, s in enumerate(streams):
                    print(f"  Stream {i}: {s.name()} (type: {s.type()})")
                print("LSL: Looking for ANY stream with markers...")
                # Try first available stream
                if streams:
                    self.inlet = pylsl.StreamInlet(streams[0])
                    print(f"LSL: Connected to stream '{streams[0].name()}' (type: {streams[0].type()})")
                else:
                    return False
            else:
                print(f"LSL: Found {len(marker_streams)} marker stream(s)")
                self.inlet = pylsl.StreamInlet(marker_streams[0])
                print(f"LSL: Connected to marker stream '{marker_streams[0].name()}'")
                
            return True
            
        except Exception as e:
            print(f"LSL: Failed to connect to marker stream: {e}")
            return False
    
    def start_listening(self):
        """Start listening for markers in background thread"""
        if self.listening:
            return
            
        self.listening = True
        self.listener_thread = threading.Thread(target=self._listen_loop, daemon=True)
        self.listener_thread.start()
        print("LSL: Started listening for stimulation markers")
    
    def stop_listening(self):
        """Stop listening for markers"""
        self.listening = False
        if self.listener_thread:
            self.listener_thread.join(timeout=1.0)
    
    def _listen_loop(self):
        """Background thread loop for listening to markers"""
        while self.listening:
            try:
                if self.test_mode:
                    # In test mode, don't actually listen
                    time.sleep(0.1)
                    continue
                    
                if self.inlet:
                    # Pull marker with timeout
                    marker, timestamp = self.inlet.pull_sample(timeout=0.1)
                    if marker:
                        marker_code = int(marker[0])
                        self.marker_queue.put((marker_code, timestamp))
                        print(f"LSL: Received marker {marker_code}")
                else:
                    time.sleep(0.1)
                    
            except Exception as e:
                print(f"LSL: Error in listen loop: {e}")
                time.sleep(0.1)
    
    def wait_for_stimulation_start(self, timeout: float = None) -> bool:
        """
        Wait for stimulation ramp-up start marker (for perfect 6-min timing)
        
        Parameters:
        -----------
        timeout : float
            Timeout in seconds (None = wait forever)
            
        Returns:
        --------
        bool : True if stimulation ramp-up detected
        """
        if self.test_mode:
            print("LSL: Simulating stimulation ramp-up start (TEST MODE)")
            print("LSL: Press ENTER to simulate ramp-up start...")
            input()  # Wait for user input in test mode
            return True
            
        start_time = time.time()
        
        while True:
            try:
                # Check for markers
                marker_code, timestamp = self.marker_queue.get(timeout=0.1)
                
                if marker_code == self.TASK_START_MARKER:  # Stimulation start (203)
                    print("LSL: Stimulation START detected! Starting task now!")
                    return True
                elif marker_code == self.STIMULATION_START:
                    print("LSL: Full stimulation detected (ramp-up complete)")
                elif marker_code == self.STIMULATION_STOP:
                    print("LSL: Stimulation STOP detected")
                elif marker_code == self.RAMP_DOWN_START:
                    print("LSL: Stimulation ramp-down detected...")
                    
            except queue.Empty:
                # No markers received, check timeout
                if timeout and (time.time() - start_time) > timeout:
                    print("LSL: Timeout waiting for stimulation ramp-up")
                    return False
                    
                # Show periodic status
                if int(time.time() - start_time) % 10 == 0:
                    elapsed = int(time.time() - start_time)
                    print(f"LSL: Still waiting for stimulation ramp-up... ({elapsed}s)")
                    
            except KeyboardInterrupt:
                print("LSL: Interrupted by user")
                return False
    
    def check_for_stimulation_stop(self) -> bool:
        """
        Check if stimulation stop marker received (non-blocking)
        
        Returns:
        --------
        bool : True if stimulation stop detected
        """
        try:
            while True:
                marker_code, timestamp = self.marker_queue.get_nowait()
                if marker_code == self.STIMULATION_STOP:
                    print("LSL: Stimulation STOP detected!")
                    return True
                elif marker_code == self.RAMP_DOWN_START:
                    print("LSL: Stimulation ramp-down detected...")
        except queue.Empty:
            pass
            
        return False


class TwoArmedBanditTask:
    """Two-armed bandit task with multi-run support"""
    
    def __init__(self, config=None):
        """Initialize the task"""
        # Load config
        if config is None:
            config = self.load_config()
        self.config = config
        
        # Initialize Pygame
        pygame.init()
        pygame.font.init()
        
        # Task variables
        self.subject_info = {}
        self.all_trial_data = []  # Store all runs
        self.trial_data = []  # Current run
        self.current_trial = 0
        self.run_number = 0
        self.current_good = np.random.randint(1, 3)
        self.trial_in_contingency = 0
        self.contingency_trials = self._get_contingency_duration()
        self.run_start_time = None
        self.experiment_start_time = None
        self.task_should_stop = False
        
        # Image tracking
        self.used_flowers = set()
        self.current_flowers = []
        self.flower_images = {}
        self.feedback_images = {}
        
        # Stimulation and LSL components
        self.nic_interface = None
        self.stimulation_manager = None
        self.lsl_trigger = None
        self.stimulation_enabled = self.config.get('stimulation', {}).get('enabled', False)
        
        # Display settings
        self.screen = None
        self.display_choice = None
        
        # Colors
        self.BLACK = (0, 0, 0)
        self.WHITE = (255, 255, 255)
        self.RED = (255, 100, 100)
        self.BLUE = (100, 100, 255)
        self.GREEN = (100, 255, 100)
        self.YELLOW = (255, 255, 100)
        self.GRAY = (128, 128, 128)
        
        # Load images
        self.load_images()
        
        # Initialize stimulation if enabled
        if self.stimulation_enabled:
            self._initialize_stimulation()
            
        # Initialize LSL trigger
        self._initialize_lsl_trigger()
        
    def load_config(self):
        """Load configuration from file or use defaults"""
        config_file = 'config.json'
        if os.path.exists(config_file):
            with open(config_file, 'r') as f:
                config = json.load(f)
                # Ensure display section has required fields
                if 'display' in config:
                    if 'window_size' in config['display'] and isinstance(config['display']['window_size'], list):
                        config['display']['window_width'] = config['display']['window_size'][0]
                        config['display']['window_height'] = config['display']['window_size'][1]
                    elif 'window_width' not in config['display']:
                        config['display']['window_width'] = 1024
                        config['display']['window_height'] = 768
                    if 'fullscreen' not in config['display']:
                        config['display']['fullscreen'] = False
                return config
        
        # Default configuration
        return {
            'experiment': {
                'mode': 'THETA_NIC',
                'run_duration_minutes': 6,
                'run_types': {
                    '1': 'baseline', '2': 'stimulation', '3': 'stimulation', '4': 'post_stimulation',
                    '5': 'baseline', '6': 'stimulation', '7': 'stimulation', '8': 'post_stimulation'
                }
            },
            'task': {
                'min_trials_same_contingency': 25,
                'contingency_jitter': 4,
                'win_fraction': 0.75
            },
            'timing': {
                'fixation_duration': 0.5, 'max_response_time': 2.0, 'choice_highlight_duration': 0.5,
                'wait_duration_min': 2.0, 'wait_duration_max': 2.0, 'outcome_duration': 1.0, 'iti_duration': 0.25
            },
            'stimulation': {
                'enabled': False, 'test_mode': True, 'communication_type': 'lsl_triggered',
                'command_directory': './nic_commands', 
                'protocols': {'active': 'DLPFC_Active', 'sham': 'DLPFC_Sham'}
            },
            'display': {'window_width': 1024, 'window_height': 768, 'fullscreen': False},
            'paths': {'data_dir': '../data', 'stimuli_dir': '../stimuli/images'}
        }
    
    def _initialize_stimulation(self):
        """Initialize stimulation components"""
        try:
            from local_starstim_module import LocalNICInterface, StimulationManager, NICError
            
            stim_config = self.config['stimulation']
            
            # Initialize local NIC interface (for logging and verification)
            self.nic_interface = LocalNICInterface(
                command_dir=stim_config.get('command_directory', './nic_commands'),
                test_mode=stim_config.get('test_mode', True)
            )
            
            # Initialize stimulation manager
            self.stimulation_manager = StimulationManager(self.nic_interface)
            
            print("Stimulation system initialized")
            if stim_config.get('test_mode', True):
                print("WARNING: Running in stimulation TEST MODE")
            
        except ImportError:
            print("Warning: Stimulation module not found. Continuing without stimulation.")
            self.stimulation_enabled = False
        except Exception as e:
            print(f"Warning: Failed to initialize stimulation: {e}")
            self.stimulation_enabled = False
    
    def _initialize_lsl_trigger(self):
        """Initialize LSL trigger system (silent — no terminal output)"""
        stim_config = self.config.get('stimulation', {})
        test_mode = stim_config.get('test_mode', True)
        
        self.lsl_trigger = LSLStimulationTrigger(test_mode=test_mode)
        
        if self.stimulation_enabled:
            # Suppress all LSL connection output
            old_stdout = sys.stdout
            sys.stdout = open(os.devnull, 'w')
            try:
                success = self.lsl_trigger.connect()
                if success:
                    self.lsl_trigger.start_listening()
            finally:
                sys.stdout.close()
                sys.stdout = old_stdout
    
    def load_images(self):
        """Load flower and feedback images"""
        stimuli_dir = Path(self.config['paths']['stimuli_dir'])
        
        # Load flower images
        for i in range(1, 51):
            flower_file = stimuli_dir / f"{i:03d}-flowers.png"
            if flower_file.exists():
                try:
                    image = pygame.image.load(str(flower_file))
                    image = pygame.transform.scale(image, (120, 120))
                    self.flower_images[i] = image
                except pygame.error as e:
                    print(f"Warning: Could not load {flower_file}: {e}")
        
        # Load feedback images
        win_images = []
        for i in range(1, 10):
            win_file = stimuli_dir / f"{i:03d}-win.png"
            if win_file.exists():
                try:
                    image = pygame.image.load(str(win_file))
                    image = pygame.transform.scale(image, (150, 150))
                    win_images.append(image)
                except pygame.error as e:
                    print(f"Warning: Could not load {win_file}: {e}")
        
        loss_images = []
        for i in range(1, 10):
            loss_file = stimuli_dir / f"{i:03d}-loss.png"
            if loss_file.exists():
                try:
                    image = pygame.image.load(str(loss_file))
                    image = pygame.transform.scale(image, (150, 150))
                    loss_images.append(image)
                except pygame.error as e:
                    print(f"Warning: Could not load {loss_file}: {e}")
        
        question_file = stimuli_dir / "question-mark.png"
        question_image = None
        if question_file.exists():
            try:
                question_image = pygame.image.load(str(question_file))
                question_image = pygame.transform.scale(question_image, (150, 150))
            except pygame.error as e:
                print(f"Warning: Could not load {question_file}: {e}")
        
        self.feedback_images = {
            'win': win_images,
            'loss': loss_images,
            'question': question_image
        }
        
        print(f"Loaded {len(self.flower_images)} flower images")
        print(f"Loaded {len(win_images)} win images, {len(loss_images)} loss images")
        if question_image:
            print("Loaded question mark image")
    
    def select_flowers_for_run(self):
        """Select two unique flower images for this run"""
        available_flowers = set(self.flower_images.keys()) - self.used_flowers
        
        if len(available_flowers) < 2:
            print("Warning: Running out of unique flowers, resetting used flowers")
            self.used_flowers = set()
            available_flowers = set(self.flower_images.keys())
        
        if len(available_flowers) < 2:
            print("Error: Not enough flower images available")
            return False
        
        selected = np.random.choice(list(available_flowers), size=2, replace=False)
        self.current_flowers = list(selected)
        self.used_flowers.update(selected)
        
        print(f"Selected flowers for run {self.run_number}: {self.current_flowers}")
        return True
    
    def _get_contingency_duration(self):
        """Get the number of trials for current contingency"""
        min_trials = self.config['task']['min_trials_same_contingency']
        jitter = self.config['task']['contingency_jitter']
        return min_trials + np.random.randint(0, jitter + 1)
    
    def get_subject_info(self):
        """Get subject information and setup for LSL-triggered run"""
        print("\n=== Two-Armed Bandit Task ===\n")
        
        self.subject_info = {
            'subject_id': input("Subject ID: "),
            'session': input("Session number (default 1): ") or "1",
            'age': input("Age: "),
            'gender': input("Gender (M/F/Other): ")
        }
        
        # CHANGE #7: Get display preferences
        self.get_display_preferences()
        
        # Get starting run number
        while True:
            run_input = input("Starting run number (1-8): ")
            try:
                run_num = int(run_input)
                if 1 <= run_num <= 8:
                    self.run_number = run_num
                    break
                else:
                    print("Run number must be between 1 and 8")
            except ValueError:
                print("Please enter a valid number")
        
        # CHANGE #2 FIX: Setup counterbalancing silently (for internal tracking only)
        if self.stimulation_enabled and self.stimulation_manager:
            # Suppress output from setup_counterbalancing
            old_stdout = sys.stdout
            sys.stdout = open(os.devnull, 'w')
            try:
                self.stimulation_manager.setup_counterbalancing(
                    self.subject_info['subject_id'],
                    self.subject_info['session']
                )
            finally:
                sys.stdout.close()
                sys.stdout = old_stdout
        
        self.subject_info['date'] = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        
        # Create data directory
        self.data_dir = Path(self.config['paths']['data_dir']) / "bandit" / f"sub-{self.subject_info['subject_id']}"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        return True
    
    def get_display_preferences(self):
        """CHANGE #7: Get display and fullscreen preferences"""
        print("\n=== Display Setup ===")
        
        # Detect available displays
        pygame.display.init()
        num_displays = pygame.display.get_num_displays()
        
        if num_displays > 1:
            print(f"Detected {num_displays} displays")
            while True:
                display_choice = input(f"Select display (0-{num_displays-1}, default: {num_displays-1} for extended): ") or str(num_displays - 1)
                try:
                    display_idx = int(display_choice)
                    if 0 <= display_idx < num_displays:
                        self.display_choice = display_idx
                        break
                    else:
                        print(f"Display must be between 0 and {num_displays-1}")
                except ValueError:
                    print("Please enter a valid number")
        else:
            print(f"Detected {num_displays} display")
            self.display_choice = 0
        
        # Get fullscreen preference
        while True:
            fullscreen_choice = input("Display mode (1=Fullscreen, 2=Windowed, default: 1): ") or "1"
            if fullscreen_choice in ['1', '2']:
                self.config['display']['fullscreen'] = (fullscreen_choice == '1')
                break
            else:
                print("Please enter 1 or 2")
        
        print(f"Using display {self.display_choice}, {'fullscreen' if self.config['display']['fullscreen'] else 'windowed'} mode")
    
    def setup_display(self):
        """Setup Pygame display"""
        # CHANGE #7: Setup display with monitor selection
        os.environ['SDL_VIDEO_WINDOW_POS'] = f"{self.display_choice * 1920},0"  # Approximate positioning
        
        if self.config['display']['fullscreen']:
            # Use fullscreen on selected display
            flags = pygame.FULLSCREEN
            if self.display_choice > 0:
                # For secondary display, use fullscreen on that display
                flags |= pygame.NOFRAME
            self.screen = pygame.display.set_mode((0, 0), flags, display=self.display_choice)
            self.width, self.height = self.screen.get_size()
        else:
            self.width = self.config['display']['window_width']
            self.height = self.config['display']['window_height']
            self.screen = pygame.display.set_mode((self.width, self.height))
        
        pygame.display.set_caption(f"Two-Armed Bandit Task - Run {self.run_number}")
        
        self.font_large = pygame.font.Font(None, 72)
        self.font_medium = pygame.font.Font(None, 48)
        self.font_small = pygame.font.Font(None, 36)
        
        self.center_x = self.width // 2
        self.center_y = self.height // 2
        self.slot_size = 120
        self.slot_spacing = 300
        
        self.update_slot_positions()
    
    def update_slot_positions(self):
        """Update slot positions"""
        left_x = self.center_x - self.slot_spacing // 2
        right_x = self.center_x + self.slot_spacing // 2
        
        if np.random.random() < 0.5:
            slot1_x, slot2_x = left_x, right_x
            self.slot1_side = 'left'
            self.slot2_side = 'right'
        else:
            slot1_x, slot2_x = right_x, left_x
            self.slot1_side = 'right'
            self.slot2_side = 'left'
        
        self.slot1_rect = pygame.Rect(slot1_x - self.slot_size // 2, self.center_y - self.slot_size // 2, self.slot_size, self.slot_size)
        self.slot2_rect = pygame.Rect(slot2_x - self.slot_size // 2, self.center_y - self.slot_size // 2, self.slot_size, self.slot_size)
    
    def show_text(self, text, y_offset=0, font=None, color=None):
        """Display text on screen"""
        if font is None:
            font = self.font_medium
        if color is None:
            color = self.WHITE
            
        lines = text.split('\n')
        for i, line in enumerate(lines):
            text_surface = font.render(line, True, color)
            text_rect = text_surface.get_rect(center=(self.center_x, self.center_y + y_offset + i * 50))
            self.screen.blit(text_surface, text_rect)
    
    def show_fixation(self, duration):
        """Show fixation cross"""
        self.screen.fill(self.BLACK)
        pygame.draw.line(self.screen, self.WHITE, (self.center_x - 20, self.center_y), (self.center_x + 20, self.center_y), 3)
        pygame.draw.line(self.screen, self.WHITE, (self.center_x, self.center_y - 20), (self.center_x, self.center_y + 20), 3)
        pygame.display.flip()
        time.sleep(duration)
    
    def show_slots(self, highlight=None):
        """Show the two flower slot machines"""
        self.screen.fill(self.BLACK)
        
        if self.current_flowers[0] in self.flower_images:
            flower1 = self.flower_images[self.current_flowers[0]]
            self.screen.blit(flower1, self.slot1_rect)
            # CHANGE #4: Use circle instead of rectangle for highlight
            if highlight == 1:
                center = (self.slot1_rect.centerx, self.slot1_rect.centery)
                pygame.draw.circle(self.screen, self.WHITE, center, self.slot_size // 2 + 5, 5)
        
        if self.current_flowers[1] in self.flower_images:
            flower2 = self.flower_images[self.current_flowers[1]]
            self.screen.blit(flower2, self.slot2_rect)
            # CHANGE #4: Use circle instead of rectangle for highlight
            if highlight == 2:
                center = (self.slot2_rect.centerx, self.slot2_rect.centery)
                pygame.draw.circle(self.screen, self.WHITE, center, self.slot_size // 2 + 5, 5)
        
        pygame.display.flip()
    
    def get_response(self, max_time):
        """Get keyboard response"""
        start_time = time.time()
        clock = pygame.time.Clock()
        
        while time.time() - start_time < max_time:
            # Check for stimulation stop
            if self.lsl_trigger and self.lsl_trigger.check_for_stimulation_stop():
                self.task_should_stop = True
                return 'stim_stopped', time.time() - start_time
                
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.cleanup()
                    sys.exit()
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        return 'escape', time.time() - start_time
                    elif event.key == pygame.K_1 or event.key == pygame.K_KP1:
                        return 1, time.time() - start_time
                    elif event.key == pygame.K_2 or event.key == pygame.K_KP2:
                        return 2, time.time() - start_time
                    elif event.key == pygame.K_a:
                        return 1 if self.slot1_side == 'left' else 2, time.time() - start_time
                    elif event.key == pygame.K_l:
                        return 1 if self.slot1_side == 'right' else 2, time.time() - start_time
            
            clock.tick(60)
        
        return None, None
    
    def show_feedback(self, reward, duration):
        """Show feedback using images"""
        self.screen.fill(self.BLACK)
        feedback_rect = pygame.Rect(self.center_x - 75, self.center_y - 75, 150, 150)
        
        if reward is None:
            if self.feedback_images['question']:
                self.screen.blit(self.feedback_images['question'], feedback_rect)
            else:
                self.show_text("?", font=self.font_large, color=self.YELLOW)
        elif reward:
            if self.feedback_images['win']:
                win_image = np.random.choice(self.feedback_images['win'])
                self.screen.blit(win_image, feedback_rect)
            else:
                self.show_text("$$$", font=self.font_large, color=self.GREEN)
        else:
            if self.feedback_images['loss']:
                loss_image = np.random.choice(self.feedback_images['loss'])
                self.screen.blit(loss_image, feedback_rect)
            else:
                self.show_text("---", font=self.font_large, color=self.RED)
        
        pygame.display.flip()
        time.sleep(duration)
    
    def run_trial(self):
        """Run a single trial"""
        # Check for task stop conditions
        if self.task_should_stop:
            return False
            
        if self.run_start_time:
            elapsed = time.time() - self.run_start_time
            max_duration = self.config['experiment']['run_duration_minutes'] * 60
            if elapsed >= max_duration:
                return False
        
        # Determine stim condition for this run
        run_types = self.config['experiment']['run_types']
        run_type = run_types.get(str(self.run_number), 'unknown')
        
        # Get stimulation condition from stimulation manager if available
        if self.stimulation_enabled and self.stimulation_manager:
            stim_condition = self.stimulation_manager.get_run_condition(self.run_number)
        else:
            # Fallback logic
            subject_num = int(self.subject_info['subject_id']) if self.subject_info['subject_id'].isdigit() else 0
            if subject_num % 2 == 0:
                if self.run_number in [2, 3]:
                    stim_condition = 'active'
                elif self.run_number in [6, 7]:
                    stim_condition = 'sham'
                else:
                    stim_condition = 'baseline'
            else:
                if self.run_number in [2, 3]:
                    stim_condition = 'sham'
                elif self.run_number in [6, 7]:
                    stim_condition = 'active'
                else:
                    stim_condition = 'baseline'
        
        trial_info = {
            'trial_num': self.current_trial,
            'run': self.run_number,
            'run_type': run_type,
            'stim_condition': stim_condition,
            'trial_in_contingency': self.trial_in_contingency,
            'current_good': self.current_good,
            'contingency_trials': self.contingency_trials,
            'flower1': self.current_flowers[0],
            'flower2': self.current_flowers[1]
        }
        
        timing = self.config['timing']
        
        self.update_slot_positions()
        trial_info['slot1_position'] = self.slot1_side
        trial_info['slot2_position'] = self.slot2_side
        
        # Send trial start marker
        if self.stimulation_manager:
            self.stimulation_manager.send_trial_marker('trial_start', self.current_trial)
        
        self.show_fixation(timing['fixation_duration'])
        
        # CHANGE #5: Clear event queue before showing slots to prevent premature responses
        pygame.event.clear()
        
        self.show_slots()
        choice, rt = self.get_response(timing['max_response_time'])
        
        if choice == 'escape':
            self.save_data()
            self.cleanup()
            sys.exit()
        elif choice == 'stim_stopped':
            print("Stimulation stopped - ending task")
            return False
        
        # Send choice marker
        if self.stimulation_manager and choice is not None:
            self.stimulation_manager.send_trial_marker('choice', self.current_trial)
        
        if choice is not None:
            self.show_slots(highlight=choice)
            time.sleep(timing['choice_highlight_duration'])
            
            correct = (choice == self.current_good)
            reward_prob = self.config['task']['win_fraction'] if correct else 1 - self.config['task']['win_fraction']
            reward = np.random.random() < reward_prob
            rt = rt * 1000
        else:
            correct = None
            reward = None
            rt = None
        
        self.screen.fill(self.BLACK)
        pygame.display.flip()
        wait_time = np.random.uniform(timing['wait_duration_min'], timing['wait_duration_max'])
        time.sleep(wait_time)
        
        # Send feedback marker
        if self.stimulation_manager:
            if reward is None:
                self.stimulation_manager.send_trial_marker('feedback_miss', self.current_trial)
            elif reward:
                self.stimulation_manager.send_trial_marker('feedback_win', self.current_trial)
            else:
                self.stimulation_manager.send_trial_marker('feedback_loss', self.current_trial)
        
        self.show_feedback(reward, timing['outcome_duration'])
        
        self.screen.fill(self.BLACK)
        pygame.display.flip()
        iti = timing['iti_duration']
        time.sleep(iti)
        
        trial_info.update({
            'choice': choice,
            'rt': rt,
            'correct': correct,
            'reward': reward if reward is not None else None,
            'wait_time': wait_time * 1000,
            'iti': iti * 1000,
            'timestamp': time.time() - self.experiment_start_time,
            'trial_start_time': time.time() - self.run_start_time
        })
        self.trial_data.append(trial_info)
        
        # Update contingency
        self.trial_in_contingency += 1
        if self.trial_in_contingency >= self.contingency_trials:
            self.current_good = 3 - self.current_good
            self.trial_in_contingency = 0
            self.contingency_trials = self._get_contingency_duration()
            print(f"  Contingency reversed at trial {self.current_trial + 1}")
        
        self.current_trial += 1
        return True
    
    def show_waiting_screen(self):
        """Show waiting screen - wait for spacebar (or LSL trigger) to start"""
        # Determine stim condition (for LSL checking only, not display)
        if self.stimulation_enabled and self.stimulation_manager:
            stim_condition = self.stimulation_manager.get_run_condition(self.run_number)
        else:
            subject_num = int(self.subject_info['subject_id']) if self.subject_info['subject_id'].isdigit() else 0
            if subject_num % 2 == 0:
                if self.run_number in [2, 3]:
                    stim_condition = 'active'
                elif self.run_number in [6, 7]:
                    stim_condition = 'sham'
                else:
                    stim_condition = 'baseline'
            else:
                if self.run_number in [2, 3]:
                    stim_condition = 'sham'
                elif self.run_number in [6, 7]:
                    stim_condition = 'active'
                else:
                    stim_condition = 'baseline'
        
        # Always show same waiting screen (double-blind)
        self.screen.fill(self.BLACK)
        
        # Title at same position as instructions screen (index 0: y = -250)
        title_y = -250
        self.show_text(f"Two-Armed Bandit Task - Run {self.run_number}", title_y, self.font_large)
        
        # "Press SPACE..." at same y as instructions screen (index 11: y = -250 + 11*35 = 135)
        space_y = 135
        self.show_text("Press SPACE to begin task", space_y, self.font_small)
        
        # "Press ESC..." directly below SPACE text
        esc_y = space_y + 35
        self.show_text("Press ESC to exit", esc_y, self.font_small)
        
        # Waiting reminder centered between title and SPACE text
        reminder_y = (title_y + space_y) // 2
        self.show_text("Please WAIT for the experimenter to start the task, THEN", reminder_y - 18, self.font_small)
        
        pygame.display.flip()
        
        # Wait for LSL trigger OR spacebar
        # Only check LSL for non-baseline runs, but don't indicate this to user
        check_lsl = (stim_condition != 'baseline' and self.stimulation_enabled and self.lsl_trigger)
        
        if check_lsl:
            print(f"\n** READY FOR RUN {self.run_number} **")
            print("Waiting for trigger or SPACE to start...")
        
        clock = pygame.time.Clock()
        waiting = True
        
        while waiting:
            # Check for keyboard input
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    return False
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_SPACE:
                        print("Task started by SPACE press")
                        return True
                    elif event.key == pygame.K_ESCAPE:
                        return False
            
            # Check for LSL trigger if applicable
            if check_lsl:
                try:
                    marker_code, timestamp = self.lsl_trigger.marker_queue.get_nowait()
                    if marker_code == self.lsl_trigger.TASK_START_MARKER:
                        print("LSL: Stimulation START detected! Beginning task!")
                        return True
                except queue.Empty:
                    pass
            
            clock.tick(60)  # Run at 60 FPS
        
        return False
    
    def show_instructions(self):
        """Show task instructions and wait for spacebar"""
        self.screen.fill(self.BLACK)
        
        # CHANGE #1: Removed stim condition from instructions
        instructions = [
            f"Two-Armed Bandit Task - Run {self.run_number}",
            "",
            "Choose between two flowers using",
            "A for left and L for right",
            "",
            "One flower is better than the other",
            "The better flower can change!",
            "Try to win as much as possible",
            "",
            f"This run will last {self.config['experiment']['run_duration_minutes']} minutes",
            "",
            "Press SPACE when ready to begin"
        ]
        
        for i, line in enumerate(instructions):
            font = self.font_large if i == 0 else self.font_small
            y_offset = -250 + i * 35
            self.show_text(line, y_offset, font)
        
        pygame.display.flip()
        
        # Wait for spacebar or escape
        waiting = True
        while waiting:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.cleanup()
                    sys.exit()
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_SPACE:
                        return True
                    elif event.key == pygame.K_ESCAPE:
                        return False
        
        return True
    
    def show_start_buffer(self):
        """Show 5-second fixation buffer before starting trials"""
        print("Starting 5-second buffer...")
        
        # Show fixation cross for 5 seconds
        self.screen.fill(self.BLACK)
        pygame.draw.line(self.screen, self.WHITE, (self.center_x - 20, self.center_y), (self.center_x + 20, self.center_y), 3)
        pygame.draw.line(self.screen, self.WHITE, (self.center_x, self.center_y - 20), (self.center_x, self.center_y + 20), 3)
        pygame.display.flip()
        
        # Wait 5 seconds, but check for escape
        start_wait = time.time()
        while time.time() - start_wait < 5.0:
            for event in pygame.event.get():
                if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    return False
                if event.type == pygame.QUIT:
                    return False
            time.sleep(0.05)
        
        return True
    
    def show_stimulation_guess(self):
        """Ask participant to guess if they received active stimulation"""
        self.screen.fill(self.BLACK)
        
        # Show title consistent with other screens
        title = f"Two-Armed Bandit Task - Run {self.run_number}"
        title_surface = self.font_large.render(title, True, self.WHITE)
        title_rect = title_surface.get_rect(center=(self.center_x, self.center_y - 250))
        self.screen.blit(title_surface, title_rect)
        
        # Show question
        question_lines = [
            "",
            "Do you think you received",
            "active stimulation during this run?",
            "",
            "Press 1 for YES",
            "Press 2 for NO"
        ]
        
        for i, line in enumerate(question_lines):
            y_offset = -250 + (i + 1) * 35  # Start below title
            self.show_text(line, y_offset, self.font_small)
        
        pygame.display.flip()
        
        # Wait for response
        waiting = True
        guess = None
        while waiting:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    return None
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_1 or event.key == pygame.K_KP1:
                        guess = 'yes'
                        waiting = False
                    elif event.key == pygame.K_2 or event.key == pygame.K_KP2:
                        guess = 'no'
                        waiting = False
                    elif event.key == pygame.K_ESCAPE:
                        return None
        
        print(f"Stimulation guess for run {self.run_number}: {guess}")
        return guess
    
    def show_run_complete(self):
        """CHANGE #6: Show run completion with option to continue"""
        run_trials = [t for t in self.trial_data if t['run'] == self.run_number]
        responses = [t for t in run_trials if t['choice'] is not None]
        
        if responses:
            n_trials = len(run_trials)
            n_responses = len(responses)
            correct_pct = np.mean([t['correct'] for t in responses]) * 100
            reward_pct = np.mean([t['reward'] for t in responses]) * 100
            
            reversals = 0
            for i in range(1, len(run_trials)):
                if run_trials[i]['current_good'] != run_trials[i-1]['current_good']:
                    reversals += 1
            
            # Print reversals to terminal only (not shown on screen)
            print(f"Contingency reversals: {reversals}")
            
            # Check if there are more runs to do
            if self.run_number < 8:
                feedback = [
                    f"Run {self.run_number} Complete!",
                    "",
                    f"Trials completed: {n_trials}",
                    f"Response rate: {n_responses}/{n_trials} ({100*n_responses/n_trials:.1f}%)",
                    f"Correct choices: {correct_pct:.1f}%",
                    f"Rewards earned: {reward_pct:.1f}%",
                    "",
                    "Data saved successfully",
                    "",
                    "Press SPACE to continue to next run",
                    "Press ESC to exit"
                ]
            else:
                feedback = [
                    f"Run {self.run_number} Complete!",
                    "",
                    "*** ALL RUNS COMPLETE ***",
                    "",
                    f"Trials completed: {n_trials}",
                    f"Response rate: {n_responses}/{n_trials} ({100*n_responses/n_trials:.1f}%)",
                    f"Correct choices: {correct_pct:.1f}%",
                    f"Rewards earned: {reward_pct:.1f}%",
                    "",
                    "Data saved successfully",
                    "",
                    "Press SPACE to exit"
                ]
        else:
            if self.run_number < 8:
                feedback = [
                    "Run complete",
                    "",
                    "Press SPACE to continue to next run",
                    "Press ESC to exit"
                ]
            else:
                feedback = [
                    "Run complete",
                    "",
                    "*** ALL RUNS COMPLETE ***",
                    "",
                    "Press SPACE to exit"
                ]
        
        self.screen.fill(self.BLACK)
        for i, line in enumerate(feedback):
            font = self.font_large if i == 0 or "ALL RUNS" in line else self.font_small
            y_offset = -250 + i * 35
            self.show_text(line, y_offset, font)
        pygame.display.flip()
        
        # CHANGE #6: Wait for space or escape
        waiting = True
        continue_to_next = False
        while waiting:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    waiting = False
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_SPACE:
                        continue_to_next = True
                        waiting = False
                    elif event.key == pygame.K_ESCAPE:
                        waiting = False
        
        return continue_to_next
    
    def reset_for_new_run(self):
        """Reset variables for a new run"""
        self.trial_data = []
        self.current_trial = 0
        self.current_good = np.random.randint(1, 3)
        self.trial_in_contingency = 0
        self.contingency_trials = self._get_contingency_duration()
        self.task_should_stop = False
    
    def cleanup(self):
        """Clean up and close"""
        self.save_data()
        
        if self.lsl_trigger:
            self.lsl_trigger.stop_listening()
        
        if self.stimulation_enabled and self.nic_interface:
            try:
                self.nic_interface.disconnect()
            except Exception as e:
                print(f"Warning: Error disconnecting stimulation: {e}")
        
        pygame.quit()
    
    def save_data(self):
        """Save trial data to CSV"""
        if not self.trial_data:
            return
        
        df = pd.DataFrame(self.trial_data)
        
        for key, value in self.subject_info.items():
            if key not in df.columns:
                df[key] = value
        
        filename = (
            f"sub-{self.subject_info['subject_id']}_"
            f"ses-{self.subject_info['session']}_"
            f"run-{self.run_number:02d}_"
            f"task-bandit_{self.subject_info['date']}.csv"
        )
        
        filepath = self.data_dir / filename
        df.to_csv(filepath, index=False)
        print(f"\nData saved to: {filepath}")
    
    def wait_for_stimulation_trigger(self):
        """Wait for stimulation start trigger before beginning task"""
        # Determine stim condition
        if self.stimulation_enabled and self.stimulation_manager:
            stim_condition = self.stimulation_manager.get_run_condition(self.run_number)
        else:
            subject_num = int(self.subject_info['subject_id']) if self.subject_info['subject_id'].isdigit() else 0
            if subject_num % 2 == 0:
                if self.run_number in [2, 3]:
                    stim_condition = 'active'
                elif self.run_number in [6, 7]:
                    stim_condition = 'sham'
                else:
                    stim_condition = 'baseline'
            else:
                if self.run_number in [2, 3]:
                    stim_condition = 'sham'
                elif self.run_number in [6, 7]:
                    stim_condition = 'active'
                else:
                    stim_condition = 'baseline'
        
        if not self.stimulation_enabled or stim_condition == 'baseline':
            print("No stimulation for this run - starting task immediately")
            return True
            
        if not self.lsl_trigger:
            print("LSL trigger not available - starting task immediately")
            return True
            
        print(f"\n** READY FOR RUN {self.run_number} **")
        # CHANGE #2: Don't print protocol name (double-blind)
        print("Waiting for stimulation to start...")
        print("(Start the protocol in NIC-2 when ready)")
        print("Task will begin when stimulation marker (203) is received")
        
        # Wait for stimulation start signal
        success = self.lsl_trigger.wait_for_stimulation_start()
        
        if success:
            print("Stimulation started (marker 203)! Beginning bandit task NOW!")
            return True
        else:
            print("No stimulation signal received. Starting task anyway.")
            return True
    
    def reset_for_new_run(self):
        """Reset variables for a new run"""
        self.trial_data = []
        self.current_trial = 0
        self.current_good = np.random.randint(1, 3)
        self.trial_in_contingency = 0
        self.contingency_trials = self._get_contingency_duration()
        self.task_should_stop = False
    
    def cleanup(self):
        """Clean up and close"""
        self.save_data()
        
        if self.lsl_trigger:
            self.lsl_trigger.stop_listening()
        
        if self.stimulation_enabled and self.nic_interface:
            try:
                self.nic_interface.disconnect()
            except Exception as e:
                print(f"Warning: Error disconnecting stimulation: {e}")
        
        pygame.quit()
    
    def run_single_run(self):
        """Run a single run of the task"""
        # Select flowers for this run
        if not self.select_flowers_for_run():
            return False
        
        # Show instructions and wait for space
        if not self.show_instructions():
            return False  # User pressed escape
        
        # Clear event queue before waiting screen
        pygame.event.clear()
        
        # Show waiting screen and wait for trigger or space
        if not self.show_waiting_screen():
            return False  # User pressed escape
        
        # Show 5-second buffer with countdown before starting trials
        self.show_start_buffer()
        
        # Initialize timing for this run
        self.run_start_time = time.time()
        
        # Log stimulation markers
        if self.stimulation_manager:
            self.stimulation_manager.send_trial_marker('run_start')
        
        # Run trials
        print(f"\nStarting Run {self.run_number}")
        print(f"Duration: {self.config['experiment']['run_duration_minutes']} minutes")
        print("Press ESC to abort\n")
        
        trial_count = 0
        while True:
            try:
                if not self.run_trial():
                    break
                
                trial_count += 1
                if trial_count % 10 == 0:
                    elapsed = time.time() - self.run_start_time
                    print(f"  Trial {trial_count}, Time: {elapsed:.1f}s")
                    
            except Exception as e:
                print(f"Error during trial {trial_count}: {e}")
                break
        
        # End markers
        if self.stimulation_manager:
            self.stimulation_manager.send_trial_marker('run_end')
        
        print(f"\nRun {self.run_number} complete!")
        print(f"Total trials: {trial_count}")
        
        # Ask participant to guess stimulation condition
        stim_guess = self.show_stimulation_guess()
        
        # Add stimulation guess to trial data for this run
        for trial in self.trial_data:
            trial['stim_guess'] = stim_guess
        
        # Save data for this run
        self.save_data()
        
        # Add this run's data to all trial data
        self.all_trial_data.extend(self.trial_data)
        
        return True
    
    def run(self):
        """CHANGE #6: Main task execution with multi-run support"""
        try:
            # Get subject info and display preferences
            if not self.get_subject_info():
                return
            
            # Setup display (only once)
            self.setup_display()
            
            # Initialize experiment timing
            self.experiment_start_time = time.time()
            
            # Run from starting run to run 8
            current_run = self.run_number
            while current_run <= 8:
                self.run_number = current_run
                
                # Update display caption
                pygame.display.set_caption(f"Two-Armed Bandit Task - Run {self.run_number}")
                
                # Reset for new run
                self.reset_for_new_run()
                
                # Run this run
                if not self.run_single_run():
                    break
                
                # Show completion screen
                continue_to_next = self.show_run_complete()
                
                if not continue_to_next or current_run >= 8:
                    break
                
                current_run += 1
            
            print("\n=== Session Complete ===")
            
        except KeyboardInterrupt:
            print("\nSession interrupted by user")
        finally:
            self.cleanup()


class IndividualizedThetaBanditTask(TwoArmedBanditTask):
    """Generalized single-run workflow for the fast localizer and theta selection modes."""

    def __init__(self, config=None, cli_args=None):
        self.cli_args = cli_args
        self.full_config = copy.deepcopy(config or load_config_file(getattr(cli_args, "config", None)))
        working_config = copy.deepcopy(self.full_config)
        working_config.setdefault("stimulation", {})
        working_config["stimulation"]["enabled"] = False
        working_config["stimulation"]["test_mode"] = bool(
            getattr(cli_args, "test_mode", False) or working_config["stimulation"].get("test_mode", False)
        )

        super().__init__(config=working_config)

        self.full_config.setdefault("experiment", {})
        self.experiment_mode = normalize_mode(
            getattr(cli_args, "mode", None) or self.full_config["experiment"].get("mode", "LOCALIZER_FAST_THETA")
        )
        self.test_mode = bool(
            getattr(cli_args, "test_mode", False)
            or self.full_config.get("stimulation", {}).get("test_mode", False)
        )
        self.auto_respond = bool(getattr(cli_args, "auto_respond", False) or self.test_mode)
        self.outputs_saved = False
        self.eeg_recording_saved = False
        self.marker_log_saved = False
        self.theta_decision = None
        self.operator_confirmation = {}
        self.event_logger = TaskMarkerLogger(
            self.full_config.get("eeg_recording", {}).get("marker_stream_name", "LSLOutletStreamName-Markers")
        )
        self.eeg_recorder = None
        self.eeg_recording_summary = None
        self.current_phase = "localizer" if self.experiment_mode == "LOCALIZER_FAST_THETA" else "stimulation"
        self.contingency_id = 1
        self.run_start_task_time = None
        self.run_start_lsl_time = None
        self.run_end_task_time = None
        self.run_end_lsl_time = None
        self.run_label = None
        self.mode_stop_rule = "duration"
        self.target_trials = None
        self.max_duration_seconds = None
        self.localizer_target_summary = ""
        self._apply_mode_profile()
        self._maybe_prepare_lsl_trigger()

    def _apply_mode_profile(self):
        if self.experiment_mode == "LOCALIZER_FAST_THETA":
            localizer = self.full_config.get("localizer_fast_theta", {})
            timing = localizer.get("timing", {})
            self.config.setdefault("timing", {})
            self.config["timing"].update(timing)
            self.mode_stop_rule = localizer.get("stop_rule", "duration_or_trials")
            self.target_trials = int(localizer.get("target_trials", 120))
            duration_minutes = float(
                getattr(self.cli_args, "duration_minutes", None)
                or localizer.get("duration_minutes")
                or self.full_config.get("experiment", {}).get("run_duration_minutes", 6)
            )
            self.max_duration_seconds = duration_minutes * 60.0
            self.config.setdefault("experiment", {})
            self.config["experiment"]["run_duration_minutes"] = duration_minutes
            self.localizer_target_summary = (
                f"Target {self.target_trials} trials or {duration_minutes:.0f} minutes, whichever comes first."
            )
        else:
            duration_minutes = float(self.full_config.get("experiment", {}).get("run_duration_minutes", 6))
            self.max_duration_seconds = duration_minutes * 60.0
            self.target_trials = None
            self.mode_stop_rule = "duration"
            self.config.setdefault("experiment", {})
            self.config["experiment"]["run_duration_minutes"] = duration_minutes

    def _maybe_prepare_lsl_trigger(self):
        should_wait_for_trigger = self.experiment_mode in {"ITHETA_TACS", "FIXED_THETA_TACS", "IBETA_TACS", "FIXED_BETA_TACS", "SHAM"}
        if not should_wait_for_trigger:
            self.lsl_trigger = None
            return
        if not self.lsl_trigger:
            self.lsl_trigger = LSLStimulationTrigger(test_mode=self.test_mode)
        if self.full_config.get("stimulation", {}).get("lsl", {}).get("enabled", True):
            self.lsl_trigger.connect()
            self.lsl_trigger.start_listening()

    def _default_run_label(self) -> str:
        if self.experiment_mode == "LOCALIZER_FAST_THETA":
            return "run-localizer"
        return f"run-{self.run_number:02d}"

    def get_subject_info(self):
        print("\n=== Two-Armed Bandit Task ===\n")

        subject_id = getattr(self.cli_args, "subject", None)
        session_id = getattr(self.cli_args, "session", None)
        if not subject_id:
            subject_id = input("Subject ID: ")
        if not session_id:
            session_id = input("Session number (default 1): ") or "1"

        age = getattr(self.cli_args, "age", None)
        gender = getattr(self.cli_args, "gender", None)
        if not self.auto_respond:
            if age is None:
                age = input("Age (optional): ")
            if gender is None:
                gender = input("Gender (optional): ")

        self.subject_info = {
            "subject_id": normalize_subject_id(subject_id),
            "session": normalize_session_id(session_id),
            "age": age or "",
            "gender": gender or "",
            "date": datetime.now().strftime("%Y-%m-%d_%H-%M-%S"),
        }

        run_arg = getattr(self.cli_args, "run", None)
        self.run_number = int(run_arg) if run_arg is not None else 1
        self.run_label = self._default_run_label()

        self.get_display_preferences()

        data_root = Path(self.full_config.get("paths", {}).get("data_dir", "../data"))
        self.data_dir = (Path(__file__).resolve().parent / data_root).resolve() / f"sub-{self.subject_info['subject_id']}"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.eeg_dir = self.data_dir / "eeg"
        self.eeg_dir.mkdir(exist_ok=True)
        self.qc_dir = self.data_dir / "qc"
        self.qc_dir.mkdir(exist_ok=True)
        self.logs_dir = self.data_dir / "logs"
        self.logs_dir.mkdir(exist_ok=True)
        self.marker_log_path = self.logs_dir / (
            f"sub-{self.subject_info['subject_id']}_ses-{self.subject_info['session']}_{self.run_label}_markers.jsonl"
        )
        self.eeg_summary_path = self.logs_dir / (
            f"sub-{self.subject_info['subject_id']}_ses-{self.subject_info['session']}_{self.run_label}_eeg_summary.json"
        )

        if self.experiment_mode == "ITHETA_TACS":
            selection = select_stimulation_frequency(
                self.subject_info["subject_id"],
                self.subject_info["session"],
                self.full_config,
                rhythm_key="bandit_feedback_theta",
                manual_override_hz=getattr(self.cli_args, "frequency", None),
                manual_override_reason="CLI frequency override" if getattr(self.cli_args, "frequency", None) else None,
            )
            self.theta_decision = selection.to_log_dict()
        elif self.experiment_mode == "IBETA_TACS":
            selection = select_stimulation_frequency(
                self.subject_info["subject_id"],
                self.subject_info["session"],
                self.full_config,
                rhythm_key="bandit_decision_beta",
                manual_override_hz=getattr(self.cli_args, "frequency", None),
                manual_override_reason="CLI frequency override" if getattr(self.cli_args, "frequency", None) else None,
            )
            self.theta_decision = selection.to_log_dict()
        elif self.experiment_mode == "FIXED_THETA_TACS":
            fixed_hz = float(getattr(self.cli_args, "frequency", None) or 6.0)
            self.theta_decision = {
                "rhythm_key": "bandit_feedback_theta",
                "rhythm_label": "participant_specific_feedback_theta",
                "rhythm_source": "fixed_6hz",
                "rhythm_reliable": False,
                "rhythm_reliability_reason": "Fixed-frequency theta control condition.",
                "rhythm_estimate_file": "",
                "frequency_to_use_hz": fixed_hz,
                "theta_source": "fixed_6hz",
                "theta_reliable": False,
                "theta_reliability_reason": "Fixed-frequency theta control condition.",
                "theta_estimate_file": "",
                "protocol_label_to_show": f"FIXED_THETA_TACS_{fixed_hz:.1f}Hz",
            }
        elif self.experiment_mode == "FIXED_BETA_TACS":
            fixed_hz = float(getattr(self.cli_args, "frequency", None) or self.full_config.get("stimulation_frequency_selection", {}).get("default_fixed_beta_hz", 20.0))
            self.theta_decision = {
                "rhythm_key": "bandit_decision_beta",
                "rhythm_label": "participant_specific_decision_beta",
                "rhythm_source": "fixed_beta",
                "rhythm_reliable": False,
                "rhythm_reliability_reason": "Fixed-frequency beta control condition.",
                "rhythm_estimate_file": "",
                "frequency_to_use_hz": fixed_hz,
                "theta_source": "none",
                "theta_reliable": False,
                "theta_reliability_reason": "",
                "theta_estimate_file": "",
                "beta_source": "fixed_beta",
                "beta_reliable": False,
                "beta_reliability_reason": "Fixed-frequency beta control condition.",
                "beta_estimate_file": "",
                "protocol_label_to_show": f"FIXED_BETA_TACS_{fixed_hz:.1f}Hz",
            }
        elif self.experiment_mode == "SHAM":
            self.theta_decision = {
                "rhythm_key": "none",
                "rhythm_label": "none",
                "rhythm_source": "sham",
                "rhythm_reliable": False,
                "rhythm_reliability_reason": "Sham condition.",
                "rhythm_estimate_file": "",
                "frequency_to_use_hz": None,
                "theta_source": "sham",
                "theta_reliable": False,
                "theta_reliability_reason": "Sham condition.",
                "theta_estimate_file": "",
                "protocol_label_to_show": "SHAM",
            }
        else:
            self.theta_decision = {
                "rhythm_key": "none",
                "rhythm_label": "none",
                "rhythm_source": "none",
                "rhythm_reliable": False,
                "rhythm_reliability_reason": "No stimulation during localizer.",
                "rhythm_estimate_file": "",
                "frequency_to_use_hz": None,
                "theta_source": "none",
                "theta_reliable": False,
                "theta_reliability_reason": "No stimulation during localizer.",
                "theta_estimate_file": "",
                "protocol_label_to_show": "LOCALIZER_NO_STIM",
            }

        return True

    def show_start_buffer(self):
        if self.auto_respond:
            time.sleep(0.05)
            return True
        return super().show_start_buffer()

    def get_display_preferences(self):
        if self.auto_respond:
            self.display_choice = 0
            self.config.setdefault("display", {})
            self.config["display"]["fullscreen"] = False
            return
        return super().get_display_preferences()

    def select_flowers_for_run(self):
        if self.flower_images:
            return super().select_flowers_for_run()
        available_flowers = set(range(1, 51)) - self.used_flowers
        if len(available_flowers) < 2:
            self.used_flowers = set()
            available_flowers = set(range(1, 51))
        selected = np.random.choice(list(available_flowers), size=2, replace=False)
        self.current_flowers = list(selected)
        self.used_flowers.update(selected)
        return True

    def get_response(self, max_time):
        if self.auto_respond:
            simulated_rt = min(float(max_time), max(0.25, min(float(max_time) - 0.05, 0.55)))
            time.sleep(0.01 if self.test_mode else simulated_rt)
            return int(np.random.choice([1, 2])), simulated_rt
        return super().get_response(max_time)

    def show_instructions(self):
        self.screen.fill(self.BLACK)
        lines = [f"Two-Armed Bandit Task - {self.experiment_mode}", ""]
        if self.experiment_mode == "LOCALIZER_FAST_THETA":
            lines += [
                "Fast no-stimulation localizer",
                "Choose between two flowers using A for left and L for right",
                "The better option reverses over time",
                self.localizer_target_summary,
                "",
                "Press SPACE when ready to begin",
            ]
        else:
            frequency_text = self.theta_decision.get("frequency_to_use_hz")
            source = self.theta_decision.get("theta_source", "none")
            lines += [
                f"Mode: {self.experiment_mode}",
                f"Theta source: {source}",
                f"Frequency to use: {frequency_text if frequency_text is not None else 'N/A'} Hz",
                self.theta_decision.get("theta_reliability_reason", ""),
                "",
                "Choose between two flowers using A for left and L for right",
                f"This run will last {self.config['experiment']['run_duration_minutes']} minutes",
                "",
                "Press SPACE when ready to begin",
            ]
        for i, line in enumerate(lines):
            font = self.font_large if i == 0 else self.font_small
            self.show_text(line, -250 + i * 35, font)
        pygame.display.flip()
        if self.auto_respond:
            time.sleep(0.05)
            return True
        waiting = True
        while waiting:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    return False
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_SPACE:
                        return True
                    if event.key == pygame.K_ESCAPE:
                        return False
        return True

    def _operator_setup_summary(self) -> list[str]:
        frequency = self.theta_decision.get("frequency_to_use_hz")
        protocol = self.theta_decision.get("protocol_label_to_show", "")
        lines = [
            f"Subject: sub-{self.subject_info['subject_id']}",
            f"Session: ses-{self.subject_info['session']}",
            f"Run: {self.run_label}",
            f"Mode: {self.experiment_mode}",
            f"Protocol label: {protocol}",
            f"Rhythm target: {self.theta_decision.get('rhythm_label', 'none')}",
            f"Rhythm source: {self.theta_decision.get('rhythm_source', self.theta_decision.get('theta_source', 'none'))}",
            f"Frequency to use: {frequency if frequency is not None else 'N/A'} Hz",
            f"Reason: {self.theta_decision.get('rhythm_reliability_reason', self.theta_decision.get('theta_reliability_reason', ''))}",
        ]
        if self.experiment_mode == "ITHETA_TACS":
            lines.append(
                f"Operator instruction: Load the NIC-2 theta-tACS protocol at {frequency:.1f} Hz."
            )
        elif self.experiment_mode == "IBETA_TACS":
            lines.append(
                f"Operator instruction: Load the NIC-2 beta-tACS protocol at {frequency:.1f} Hz."
            )
        elif self.experiment_mode == "FIXED_THETA_TACS":
            lines.append(
                f"Operator instruction: Load the fixed 6.0 Hz theta-tACS protocol at {frequency:.1f} Hz."
            )
        elif self.experiment_mode == "FIXED_BETA_TACS":
            lines.append(
                f"Operator instruction: Load the fixed beta-tACS protocol at {frequency:.1f} Hz."
            )
        elif self.experiment_mode == "SHAM":
            lines.append("Operator instruction: Load the sham protocol and confirm marker 203 when ready.")
        return lines

    def prompt_operator_confirmation(self):
        if self.experiment_mode == "LOCALIZER_FAST_THETA":
            return
        for line in self._operator_setup_summary():
            print(line)
        if self.auto_respond:
            self.operator_confirmation = {
                "operator_confirmed_protocol": self.theta_decision.get("protocol_label_to_show", ""),
                "operator_confirmed_frequency_hz": self.theta_decision.get("frequency_to_use_hz"),
            }
            return
        protocol = input("Operator-confirmed protocol label: ") or self.theta_decision.get("protocol_label_to_show", "")
        frequency_default = self.theta_decision.get("frequency_to_use_hz")
        frequency_input = input(
            f"Operator-confirmed frequency in Hz ({frequency_default if frequency_default is not None else 'blank'}): "
        ).strip()
        confirmed_frequency = frequency_default
        if frequency_input:
            confirmed_frequency = float(frequency_input)
        self.operator_confirmation = {
            "operator_confirmed_protocol": protocol,
            "operator_confirmed_frequency_hz": confirmed_frequency,
        }

    def show_waiting_screen(self):
        self.screen.fill(self.BLACK)
        lines = [
            f"Two-Armed Bandit Task - {self.run_label}",
            "",
            "Please wait for the experimenter",
            "to start the task, then",
            "",
        ]
        if self.experiment_mode in {"ITHETA_TACS", "FIXED_THETA_TACS", "IBETA_TACS", "FIXED_BETA_TACS", "SHAM"}:
            lines.append("Press SPACE to begin or wait for marker 203")
        else:
            lines.append("Press SPACE to begin task")
        lines.append("Press ESC to exit")
        for i, line in enumerate(lines):
            font = self.font_large if i == 0 else self.font_small
            self.show_text(line, -220 + i * 40, font)
        pygame.display.flip()

        if self.auto_respond:
            time.sleep(0.05)
            return True

        waiting = True
        clock = pygame.time.Clock()
        while waiting:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    return False
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_SPACE:
                        return True
                    if event.key == pygame.K_ESCAPE:
                        return False
            if self.lsl_trigger:
                try:
                    marker_code, timestamp = self.lsl_trigger.marker_queue.get_nowait()
                    if marker_code == self.lsl_trigger.TASK_START_MARKER:
                        print(f"LSL: Marker {marker_code} received at {timestamp:.3f}. Starting task.")
                        return True
                except queue.Empty:
                    pass
            clock.tick(60)
        return True

    def _start_eeg_recording_if_requested(self):
        if self.experiment_mode != "LOCALIZER_FAST_THETA":
            return
        eeg_config = self.full_config.get("eeg_recording", {})
        if not eeg_config.get("record_lsl_eeg_during_localizer", True):
            return
        self.eeg_recorder = LSLEEGRecorder(
            preferred_stream_type=eeg_config.get("preferred_stream_type", "EEG"),
            preferred_stream_name_contains=eeg_config.get("preferred_stream_name_contains", "StarStim"),
        )
        if not self.eeg_recorder.start():
            summary = self.eeg_recorder.fail_summary()
            summary.message = (
                summary.message
                or "No live EEG stream was found. Behavioral localizer output will still be saved."
            )
            save_recording_summary(summary, self.eeg_summary_path)
            self.eeg_recording_saved = True
            print(summary.message)

    def _stop_eeg_recording(self):
        if not self.eeg_recorder or self.eeg_recording_saved:
            return
        basename = (
            f"sub-{self.subject_info['subject_id']}_ses-{self.subject_info['session']}_localizer_eeg"
        )
        summary = self.eeg_recorder.save(
            self.eeg_dir,
            basename,
            write_raw_csv=bool(self.full_config.get("eeg_recording", {}).get("write_raw_csv", True)),
            write_raw_npz=bool(self.full_config.get("eeg_recording", {}).get("write_raw_npz", True)),
            extra_metadata={
                "subject_id": self.subject_info["subject_id"],
                "session_id": self.subject_info["session"],
                "run_label": self.run_label,
                "mode": self.experiment_mode,
            },
        )
        save_recording_summary(summary, self.eeg_summary_path)
        self.eeg_recording_summary = summary
        self.eeg_recording_saved = True

    def _should_stop_run(self):
        elapsed = time.time() - self.run_start_time
        duration_reached = elapsed >= self.max_duration_seconds
        trial_target_reached = self.target_trials is not None and self.current_trial >= self.target_trials
        if self.mode_stop_rule == "duration":
            return duration_reached
        if self.mode_stop_rule == "trials":
            return trial_target_reached
        if self.mode_stop_rule == "duration_and_trials":
            return duration_reached and trial_target_reached
        return duration_reached or trial_target_reached

    def _stim_condition(self):
        if self.experiment_mode == "SHAM":
            return "sham"
        if self.experiment_mode == "LOCALIZER_FAST_THETA":
            return "none"
        return "active"

    def _feedback_marker(self, reward):
        if reward is None:
            return 33, "miss"
        if reward:
            return 31, "win"
        return 32, "loss"

    def run_trial(self):
        if self.task_should_stop:
            return False
        if self._should_stop_run():
            return False

        timing = self.config["timing"]
        self.update_slot_positions()
        left_stimulus = self.current_flowers[0] if self.slot1_side == "left" else self.current_flowers[1]
        right_stimulus = self.current_flowers[1] if self.slot1_side == "left" else self.current_flowers[0]
        trial_num = self.current_trial + 1
        trial_start_task_time = time.time() - self.run_start_time
        trial_start_lsl_time = lsl_clock()
        self.event_logger.send(
            10,
            "trial_start",
            {
                "trial_num": trial_num,
                "mode": self.experiment_mode,
            },
        )

        self.show_fixation(timing["fixation_duration"])
        pygame.event.clear()
        self.show_slots()
        choice_window_onset_task_time = time.time() - self.run_start_time
        choice_window_onset_lsl_time = lsl_clock()
        choice, rt = self.get_response(timing["max_response_time"])

        if choice == "escape":
            self.save_data()
            self.cleanup()
            sys.exit()
        if choice == "stim_stopped":
            self.task_should_stop = True
            return False

        if choice is not None:
            choice_onset_task_time = choice_window_onset_task_time + (rt or 0.0)
            choice_onset_lsl_time = choice_window_onset_lsl_time + (rt or 0.0)
            choice_marker_send_lsl_time = self.event_logger.send(
                20,
                "choice",
                {
                    "trial_num": trial_num,
                    "choice": choice,
                    "choice_onset_lsl_time": choice_onset_lsl_time,
                },
            )
            self.show_slots(highlight=choice)
            time.sleep(timing.get("choice_highlight_duration", 0.5))
            correct = choice == self.current_good
            reward_prob = self.full_config.get("localizer_fast_theta", {}).get(
                "win_fraction",
                self.config["task"]["win_fraction"],
            ) if correct else 1 - self.full_config.get("localizer_fast_theta", {}).get(
                "win_fraction",
                self.config["task"]["win_fraction"],
            )
            reward = np.random.random() < reward_prob
            rt_ms = rt * 1000.0 if rt is not None else None
        else:
            choice_onset_task_time = None
            choice_onset_lsl_time = None
            choice_marker_send_lsl_time = None
            correct = None
            reward = None
            rt_ms = None

        self.screen.fill(self.BLACK)
        pygame.display.flip()
        wait_time = np.random.uniform(timing["wait_duration_min"], timing["wait_duration_max"])
        time.sleep(wait_time)

        feedback_marker, outcome = self._feedback_marker(reward)
        feedback_lsl_time = self.event_logger.send(
            feedback_marker,
            f"feedback_{outcome}",
            {"trial_num": trial_num, "outcome": outcome},
        )
        feedback_task_time = time.time() - self.run_start_time
        self.show_feedback(reward, timing["outcome_duration"])
        self.screen.fill(self.BLACK)
        pygame.display.flip()
        time.sleep(timing["iti_duration"])

        trial_info = {
            "subject_id": f"sub-{self.subject_info['subject_id']}",
            "session_id": f"ses-{self.subject_info['session']}",
            "run": self.run_label,
            "mode": self.experiment_mode,
            "phase": self.current_phase,
            "stim_condition": self._stim_condition(),
            "protocol_label_to_show": self.theta_decision.get("protocol_label_to_show", ""),
            "operator_confirmed_protocol": self.operator_confirmation.get("operator_confirmed_protocol", ""),
            "operator_confirmed_frequency_hz": self.operator_confirmation.get("operator_confirmed_frequency_hz"),
            "intended_stimulation_frequency_hz": self.theta_decision.get("frequency_to_use_hz"),
            "actual_or_confirmed_stimulation_frequency_hz": self.operator_confirmation.get(
                "operator_confirmed_frequency_hz",
                self.theta_decision.get("frequency_to_use_hz"),
            ),
            "theta_source": self.theta_decision.get("theta_source", "none"),
            "theta_estimate_file": self.theta_decision.get("theta_estimate_file", ""),
            "theta_reliable": self.theta_decision.get("theta_reliable", False),
            "theta_reliability_reason": self.theta_decision.get("theta_reliability_reason", ""),
            "rhythm_key": self.theta_decision.get("rhythm_key", ""),
            "rhythm_label": self.theta_decision.get("rhythm_label", ""),
            "rhythm_source": self.theta_decision.get("rhythm_source", self.theta_decision.get("theta_source", "none")),
            "rhythm_estimate_file": self.theta_decision.get("rhythm_estimate_file", self.theta_decision.get("theta_estimate_file", "")),
            "rhythm_reliable": self.theta_decision.get("rhythm_reliable", self.theta_decision.get("theta_reliable", False)),
            "rhythm_reliability_reason": self.theta_decision.get("rhythm_reliability_reason", self.theta_decision.get("theta_reliability_reason", "")),
            "beta_source": self.theta_decision.get("beta_source", "none"),
            "beta_estimate_file": self.theta_decision.get("beta_estimate_file", ""),
            "beta_reliable": self.theta_decision.get("beta_reliable", False),
            "beta_reliability_reason": self.theta_decision.get("beta_reliability_reason", ""),
            "trial_num": trial_num,
            "current_good_option": self.current_good,
            "current_good": self.current_good,
            "contingency_id": self.contingency_id,
            "trial_in_contingency": self.trial_in_contingency,
            "left_stimulus": left_stimulus,
            "right_stimulus": right_stimulus,
            "flower1": self.current_flowers[0],
            "flower2": self.current_flowers[1],
            "slot1_position": self.slot1_side,
            "slot2_position": self.slot2_side,
            "choice": choice,
            "rt": rt_ms,
            "choice_window_onset_task_time": choice_window_onset_task_time,
            "choice_window_onset_lsl_time": choice_window_onset_lsl_time,
            "choice_onset_task_time": choice_onset_task_time,
            "choice_onset_lsl_time": choice_onset_lsl_time,
            "choice_marker_send_lsl_time": choice_marker_send_lsl_time,
            "outcome": outcome,
            "reward": reward if reward is not None else None,
            "correct": correct,
            "feedback_marker": feedback_marker,
            "feedback_onset_task_time": feedback_task_time,
            "feedback_onset_lsl_time": feedback_lsl_time,
            "lsl_marker_send_time": feedback_lsl_time,
            "run_start_task_time": 0.0,
            "run_start_lsl_time": self.run_start_lsl_time,
            "run_end_task_time": None,
            "run_end_lsl_time": None,
            "wait_time": wait_time * 1000.0,
            "iti": timing["iti_duration"] * 1000.0,
            "timestamp": time.time() - self.experiment_start_time,
            "trial_start_time": trial_start_task_time,
            "trial_start_lsl_time": trial_start_lsl_time,
            "run_type": self.experiment_mode,
        }
        self.trial_data.append(trial_info)

        self.trial_in_contingency += 1
        if self.trial_in_contingency >= self.contingency_trials:
            self.current_good = 3 - self.current_good
            self.trial_in_contingency = 0
            self.contingency_trials = self._get_contingency_duration()
            self.contingency_id += 1
            print(f"  Contingency reversed at trial {trial_num + 1}")

        self.current_trial += 1
        return True

    def save_data(self):
        if not self.trial_data or self.outputs_saved:
            return
        for trial in self.trial_data:
            trial["run_end_task_time"] = self.run_end_task_time
            trial["run_end_lsl_time"] = self.run_end_lsl_time
        df = pd.DataFrame(self.trial_data)
        filename = (
            f"sub-{self.subject_info['subject_id']}_"
            f"ses-{self.subject_info['session']}_"
            f"{self.run_label}_task-bandit_{self.subject_info['date']}.csv"
        )
        filepath = self.data_dir / filename
        df.to_csv(filepath, index=False)
        self.outputs_saved = True
        print(f"\nData saved to: {filepath}")

    def cleanup(self):
        self.save_data()
        if self.lsl_trigger:
            self.lsl_trigger.stop_listening()
        self._stop_eeg_recording()
        if not self.marker_log_saved and self.event_logger.events and hasattr(self, "marker_log_path"):
            self.event_logger.save(self.marker_log_path)
            self.marker_log_saved = True
        pygame.quit()

    def run_single_run(self):
        if not self.select_flowers_for_run():
            return False
        self.prompt_operator_confirmation()
        if not self.show_instructions():
            return False
        self._start_eeg_recording_if_requested()
        pygame.event.clear()
        if not self.show_waiting_screen():
            return False
        self.show_start_buffer()

        self.run_start_time = time.time()
        self.experiment_start_time = self.run_start_time
        self.run_start_task_time = 0.0
        self.run_start_lsl_time = self.event_logger.send(
            100,
            "run_start",
            {
                "mode": self.experiment_mode,
                "run_label": self.run_label,
            },
        )

        print(f"\nStarting {self.experiment_mode}")
        print(f"Run label: {self.run_label}")
        print(f"Duration: {self.config['experiment']['run_duration_minutes']} minutes")
        if self.experiment_mode == "LOCALIZER_FAST_THETA":
            print(self.localizer_target_summary)
        print("Press ESC to abort\n")

        while True:
            if not self.run_trial():
                break
            if self.current_trial and self.current_trial % 10 == 0:
                elapsed = time.time() - self.run_start_time
                print(f"  Trial {self.current_trial}, Time: {elapsed:.1f}s")

        self.run_end_task_time = time.time() - self.run_start_time
        self.run_end_lsl_time = self.event_logger.send(
            200,
            "run_end",
            {"mode": self.experiment_mode, "run_label": self.run_label},
        )
        self.event_logger.save(self.marker_log_path)
        self.marker_log_saved = True
        self._stop_eeg_recording()

        print(f"\nRun complete. Total trials: {self.current_trial}")
        self.save_data()
        if self.experiment_mode == "LOCALIZER_FAST_THETA":
            print(
                "Next step: run `python run_theta_estimation.py "
                f"--subject {self.subject_info['subject_id']} --session {self.subject_info['session']} --auto-find`"
            )
        return True

    def run(self):
        try:
            if not self.get_subject_info():
                return
            self.setup_display()
            self.reset_for_new_run()
            self.run_single_run()
        except KeyboardInterrupt:
            print("\nSession interrupted by user")
        finally:
            self.cleanup()


def build_arg_parser():
    parser = argparse.ArgumentParser(description="Run the bandit task in legacy, individualized-theta, or individualized-beta modes.")
    parser.add_argument("--config", default=str(Path(__file__).resolve().parent / "config.json"))
    parser.add_argument("--mode", help="Experiment mode to run.")
    parser.add_argument("--subject", help="Subject ID, with or without the sub- prefix.")
    parser.add_argument("--session", help="Session ID, with or without the ses- prefix.")
    parser.add_argument("--run", type=int, help="Run number for stimulation runs.")
    parser.add_argument("--frequency", type=float, help="Optional theta/beta frequency override.")
    parser.add_argument("--age", help="Optional age field for the behavioral CSV.")
    parser.add_argument("--gender", help="Optional gender field for the behavioral CSV.")
    parser.add_argument("--test-mode", action="store_true", help="Run without requiring stimulation hardware.")
    parser.add_argument("--auto-respond", action="store_true", help="Auto-start and simulate button responses.")
    parser.add_argument("--duration-minutes", type=float, help="Override the configured run duration.")
    return parser


def run_experiment_from_cli(cli_args):
    config = load_config_file(cli_args.config)
    mode = normalize_mode(cli_args.mode or config.get("experiment", {}).get("mode", "THETA_NIC"))

    if mode in LEGACY_EXPERIMENT_MODES:
        if cli_args.test_mode:
            config.setdefault("stimulation", {})
            config["stimulation"]["test_mode"] = True
        config.setdefault("experiment", {})
        config["experiment"]["mode"] = mode
        task = TwoArmedBanditTask(config=config)
        task.run()
        return

    config.setdefault("experiment", {})
    config["experiment"]["mode"] = mode
    task = IndividualizedThetaBanditTask(config=config, cli_args=cli_args)
    task.run()


def main():
    cli_args = build_arg_parser().parse_args()
    run_experiment_from_cli(cli_args)


if __name__ == '__main__':
    main()
