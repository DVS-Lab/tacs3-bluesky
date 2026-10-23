#!/usr/bin/env python3
"""EEG-only quality measurements, independent of behavioral matching or peaks."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'code'))
from rhythm_validation_core import preprocess
from rhythm_validation_io import InputError, clock_qc, sha256


def spatial_metrics(filtered, clean, roi, refs):
    result = dict(n_reference_channels=len(refs), n_roi_channels=len(roi))
    if len(refs) < 2:
        return result
    covariance = np.cov(filtered[:, refs].T)
    eigenvalues = np.maximum(np.linalg.eigvalsh(covariance), 0)
    corr = np.corrcoef(filtered[:, refs].T)
    offdiag = corr[np.triu_indices(len(refs), 1)]
    result.update(median_pairwise_correlation=float(np.median(offdiag)),
                  first_component_variance_fraction=float(eigenvalues[-1]/eigenvalues.sum()),
                  effective_spatial_rank=float(eigenvalues.sum()**2/np.sum(eigenvalues**2)))
    if roi:
        before = float(np.median(np.std(filtered[:, roi], axis=0)))
        after = float(np.median(np.std(clean[:, roi], axis=0)))
        result.update(median_roi_std_before_reference_uv=before, median_roi_std_after_reference_uv=after,
                      residual_std_fraction=after/before if before else None)
    return result


def run(out):
    out.mkdir(parents=True, exist_ok=False)
    cfg = json.loads((ROOT/'code/rhythm_validation_config.json').read_text())
    manifest = json.loads((ROOT/'validation/pilot_manifest.json').read_text())
    records = []
    for job in manifest['jobs']:
        result = dict(recording_id=job['id'], subject=job['subject'], task=job['task'], phase=job['phase'],
                      behavior_matched=bool(job.get('events')), input_sha256=job['sha256'])
        try:
            for key in ('eeg', 'metadata'):
                if sha256(ROOT/job[key]) != job['sha256'][key]:
                    raise InputError(key+'_hash_mismatch')
            meta = (ROOT/job['metadata']).read_text()
            if 'EEG units: nV' not in meta:
                raise InputError('unverified_units')
            names = re.findall(r'Channel\s+\d+:\s*(\S+)', meta)
            fs = float(re.search(r'EEG sampling rate:\s*([\d.]+)', meta)[1])
            raw = np.loadtxt(ROOT/job['eeg'])
            if raw.ndim != 2 or raw.shape[1] != len(names)+5:
                raise InputError('channel_count_mismatch')
            if len(raw) != int(re.search(r'Number of records of EEG:\s*(\d+)', meta)[1]):
                raise InputError('metadata_sample_count_mismatch')
            t = raw[:, -1]/1000
            if abs(float(re.search(r'firstEEGtimestamp\):\s*(\d+)', meta)[1])/1000-t[0]) > 1/fs:
                raise InputError('metadata_start_mismatch')
            if np.any(raw[:, -2] == 255):
                raise InputError('packet_loss_marker')
            timing = clock_qc(t, fs, cfg['preprocessing'])
            clean, filtered, roi, refs, channels = preprocess(raw[:, :len(names)]/1000, fs, names, cfg['preprocessing'])
            result.update(eeg_status='readable_units_and_sampling_verified', timing=timing,
                          reference_channels=[names[i] for i in refs], roi_channels=[names[i] for i in roi],
                          channels=channels, spatial=spatial_metrics(filtered, clean, roi, refs))
        except InputError as exc:
            result.update(eeg_status='eeg_input_failure', reason=str(exc))
        records.append(result)
    payload = dict(records=records, source_sha256={str(p.relative_to(ROOT)):sha256(p) for p in
        [Path(__file__), ROOT/'code/rhythm_validation_core.py', ROOT/'code/rhythm_validation_io.py',
         ROOT/'code/rhythm_validation_config.json', ROOT/'validation/pilot_manifest.json']},
        interpretation='Descriptive acquisition/spatial diagnostics, not validated exclusion thresholds. Very similar channels with little residual after reference warrant acquisition/reference review; they do not identify the cause or prove unusable EEG. No behavioral identity or stimulation approval follows from this EEG-only read.')
    with (out/'spatial_quality.json').open('x') as f:
        json.dump(payload, f, indent=2, allow_nan=False)
        f.write('\n')
    print(len(records), 'EEG recordings measured independently of event availability')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    run(parser.parse_args().out)
