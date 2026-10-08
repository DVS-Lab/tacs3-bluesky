"""Strict, hardware-free input and clock validation for offline analysis.

A reviewed manifest is the recording identity authority. Never search by mtime,
join by row position, infer an LSL/Unix offset from recording starts, or repair gaps.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd


class InputError(ValueError):
    """Invalid or unverifiable input; represented as FAIL by the batch CLI."""

    def __init__(self, message, diagnostics=None):
        super().__init__(message)
        self.diagnostics = diagnostics or {}


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def number(value):
    try:
        x = float(value)
        return x if np.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def truth(value):
    return str(value).strip().lower() in {'1', '1.0', 'true'}


def seconds(values, unit, domain):
    v = np.asarray(values, dtype=float)
    if unit not in {'s', 'ms'} or domain not in {'unix', 'lsl'}:
        raise InputError('explicit_timestamp_unit_and_domain_required')
    v = v / (1000 if unit == 'ms' else 1)
    finite = v[np.isfinite(v)]
    if domain == 'unix' and finite.size and not np.all((finite > 1e9) & (finite < 1e10)):
        raise InputError('unix_timestamp_unit_or_domain_mismatch')
    return v


def clock_qc(t, fs, cfg):
    if len(t) < 2 or not np.isfinite(t).all():
        raise InputError('missing_or_nonfinite_eeg_timestamps')
    dt = np.diff(t)
    if np.any(dt <= 0):
        raise InputError('duplicate_or_reversed_eeg_timestamps')
    empirical = (len(t) - 1) / (t[-1] - t[0])
    irregular = np.mean(np.abs(dt - 1 / fs) > cfg['interval_tolerance_fraction'] / fs)
    if abs(empirical / fs - 1) > cfg['sampling_relative_tolerance']:
        raise InputError('nominal_empirical_sampling_rate_mismatch')
    if irregular > cfg['max_irregular_fraction'] or dt.max() > cfg['max_gap_factor'] / fs:
        raise InputError('irregular_sampling_or_gap_no_interpolation_allowed')
    return dict(n_samples=len(t), start_sec=float(t[0]), end_sec=float(t[-1]),
                nominal_hz=fs, empirical_hz=float(empirical),
                irregular_fraction=float(irregular), max_interval_sec=float(dt.max()))


def resolve(root, relative):
    p = (root / relative).resolve()
    if not p.is_relative_to(root.resolve()):
        raise InputError('input_outside_repository')
    return p


def validate_identity(job, rows):
    subject, session = str(job['subject']), str(job['session'])
    task, phase = job['task'], job['phase']
    if task not in {'bandit', 'sst'} or phase not in {'pre', 'post'} or not job.get('run'):
        raise InputError('invalid_task_phase_or_missing_run')
    # An identity exception must be explicitly recorded; it is never guessed at runtime.
    for kind in ('eeg', 'events'):
        name = Path(job[kind]).name.lower()
        if not re.search(rf'(?<!\d){re.escape(subject)}(?!\d)', name):
            raise InputError(f'{kind}_participant_mismatch')
        if task not in name:
            raise InputError(f'{kind}_task_mismatch')
        for other in ('pre', 'post'):
            if f'{other}-stim' in name and other != phase:
                raise InputError(f'{kind}_phase_mismatch')
    eeg_name = Path(job['eeg']).name
    matched_session = re.search(rf'{re.escape(subject)}-(\d+)_', eeg_name)
    if matched_session and int(matched_session[1]) != int(session):
        raise InputError('eeg_session_mismatch')
    event_session = re.search(r'_ses-(\d+)_', Path(job['events']).name)
    if event_session and int(event_session[1]) != int(session):
        raise InputError('events_session_mismatch')
    for col, expected, prefix in [('subject_id', subject, 'sub-'), ('session_id', session, 'ses-')]:
        if col in rows:
            values = {str(v).removeprefix(prefix).lstrip('0') or '0' for v in rows[col].dropna().unique()}
            if values != {expected.lstrip('0') or '0'}:
                raise InputError(f'behavior_{col}_mismatch')
    if 'run' in rows and rows['run'].dropna().astype(str).nunique() > 1:
        raise InputError('multiple_behavioral_runs_in_one_file')


def load_pair(root, job, cfg):
    if not job.get('eeg') or not job.get('events'):
        raise InputError(job.get('missing_reason', 'missing_eeg_or_events'))
    paths = {key: resolve(root, job[key]) for key in ('eeg', 'events', 'metadata') if job.get(key)}
    for key, path in paths.items():
        if not path.is_file():
            raise InputError(f'missing_{key}_file')
        if sha256(path) != job['sha256'][key]:
            raise InputError(f'{key}_hash_mismatch_review_manifest')
    rows = pd.read_csv(paths['events'], sep='\t' if paths['events'].suffix == '.tsv' else ',', dtype={'subject_id': str, 'session_id': str})
    validate_identity(job, rows)
    eeg_path = paths['eeg']
    if eeg_path.suffix == '.easy':
        if 'metadata' not in paths:
            raise InputError('easy_info_metadata_required')
        meta = paths['metadata'].read_text()
        names = re.findall(r'Channel\s+\d+:\s*(\S+)', meta)
        match = re.search(r'EEG sampling rate:\s*([\d.]+)', meta)
        if not match or not names or 'EEG units: nV' not in meta:
            raise InputError('unrecognized_easy_metadata')
        fs = float(match[1])
        raw = np.loadtxt(eeg_path)
        if raw.ndim != 2 or raw.shape[1] != len(names) + 5:
            raise InputError('easy_channel_count_mismatch')
        records = re.search(r'Number of records of EEG:\s*(\d+)', meta)
        if records and int(records[1]) != raw.shape[0]:
            raise InputError('info_sample_count_mismatch')
        if len(set(names)) != len(names):
            raise InputError('duplicate_channel_labels')
        data = raw[:, :len(names)] * 1e-3
        t = seconds(raw[:, -1], 'ms', 'unix')
        start = re.search(r'firstEEGtimestamp\):\s*(\d+)', meta)
        if not start or abs(float(start[1]) / 1000 - t[0]) > 1 / fs:
            raise InputError('info_recording_start_mismatch')
        if np.any(raw[:, -2] == 255):
            raise InputError('nic_packet_loss_marker')
        domain = 'unix'
    elif eeg_path.suffix == '.csv':
        meta = json.loads(paths['metadata'].read_text()) if 'metadata' in paths else {}
        frame = pd.read_csv(eeg_path)
        if frame.empty or meta.get('status') == 'no_samples':
            raise InputError('lsl_recording_has_no_samples')
        names = meta.get('channel_names')
        fs = number(meta.get('sampling_rate_hz'))
        units = meta.get('units') or job.get('amplitude_unit')
        if not names or not fs or units not in {'uV', 'V', 'nV'}:
            raise InputError('lsl_channel_rate_or_amplitude_unit_unverified')
        data = frame[names].to_numpy(float) * {'uV': 1, 'V': 1e6, 'nV': 1e-3}[units]
        domain = 'lsl'
        t = seconds(frame['lsl_timestamp'], 's', domain)
    else:
        raise InputError('unsupported_format_use_easy_or_lsl_csv')
    if job['clock_domain'] != domain:
        raise InputError('eeg_manifest_clock_domain_mismatch')
    qc = clock_qc(t, fs, cfg)
    qc['clock_domain'] = domain
    return data, t, fs, names, rows, qc


def select_events(rows, task, estimand, domain, job):
    """One log row per original behavioral trial, including selection exclusions."""
    if estimand == 'response_beta_erd':
        stem = 'choice_onset' if task == 'bandit' else 'response_onset'
    elif estimand.startswith('stop_'):
        stem = 'stop_onset'
    else:
        stem = 'feedback_onset'
    col = job.get('event_columns', {}).get(stem, f'{stem}_{domain}_time')
    unit = job.get('event_unit', 'ms' if domain == 'unix' else 's')
    if col not in rows:
        raise InputError(f'missing_explicit_event_column:{col}')
    event_times = seconds(pd.to_numeric(rows[col], errors='coerce'), unit, domain)
    logs = []
    for i, (_, row) in enumerate(rows.iterrows()):
        reason = ''
        if task == 'sst':
            if estimand == 'response_beta_erd' and not (str(row.get('stop')) in {'0', '0.0', 'False'} and truth(row.get('go_correct'))):
                reason = 'not_correct_go'
            elif estimand.startswith('stop_success') and not (truth(row.get('stop')) and truth(row.get('stop_success'))):
                reason = 'not_successful_stop'
            elif estimand.startswith('stop_failure') and not (truth(row.get('stop')) and not truth(row.get('stop_success')) and truth(row.get('response'))):
                reason = 'not_failed_stop'
        elif estimand == 'response_beta_erd' and number(row.get('choice')) not in {1, 2}:
            reason = 'no_bandit_choice'
        elif estimand.startswith('feedback') and str(row.get('outcome')).lower() not in {'win', 'loss'}:
            reason = 'not_win_or_loss_feedback'
        eligible = not reason
        if not reason and not np.isfinite(event_times[i]):
            reason = 'missing_event_timestamp'
        logs.append(dict(row=i + 1, event_column=col, event_sec=number(event_times[i]),
                         eligible=eligible, retained=False, reason=reason))
    return logs


def alignment_qc(logs, rows, t, cfg):
    values = np.array([x['event_sec'] for x in logs if x['eligible'] and x['event_sec'] is not None], float)
    if not len(values):
        raise InputError('no_eligible_events')
    if np.any(np.diff(values) <= 0):
        raise InputError('duplicate_or_reversed_event_timestamps')
    overlap = float(np.mean((values >= t[0]) & (values <= t[-1])))
    if overlap < cfg['min_event_overlap_fraction']:
        raise InputError('event_recording_overlap_below_threshold', {'event_overlap_fraction': overlap, 'n_valid_timestamps': len(values)})
    # Two clock readings taken at the same event can reveal unit errors/drift.
    # This is diagnostic only; never use it to silently shift event times.
    col = logs[0]['event_column']
    lsl_col = col.replace('_unix_time', '_lsl_time')
    residual = None
    if col.endswith('_unix_time') and lsl_col in rows:
        unix = pd.to_numeric(rows[col], errors='coerce').to_numpy() / 1000
        lsl = pd.to_numeric(rows[lsl_col], errors='coerce').to_numpy()
        mask = np.isfinite(unix) & np.isfinite(lsl)
        if mask.sum() > 2:
            offset = unix[mask] - lsl[mask]
            residual = float(np.max(np.abs(offset - np.median(offset))))
            if residual > cfg['clock_residual_limit_sec']:
                raise InputError('event_unix_lsl_clock_inconsistency', {'event_overlap_fraction': overlap, 'unix_lsl_max_offset_residual_sec': residual})
    return dict(event_overlap_fraction=overlap, unix_lsl_max_offset_residual_sec=residual,
                synchronization='software_timestamps_only_no_hardware_latency_validation')
