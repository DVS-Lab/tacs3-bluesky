#!/usr/bin/env python3
"""Inventory unresolved event files without inferring identities or clock offsets."""
import argparse
import hashlib
import json
from pathlib import Path
import re

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
SEARCH_ROOTS = ['data', 'behavioral-data', 'pilot_data', 'stimulation']


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise FileExistsError(args.out)
    manifest = ROOT/'validation/pilot_manifest.json'
    files = sorted(p for d in SEARCH_ROOTS for p in (ROOT/d).rglob('*') if p.suffix in ('.csv', '.tsv'))
    records = []
    for job in json.loads(manifest.read_text())['jobs']:
        if job.get('events'):
            continue
        # Substring deliberately includes conflicting IDs, so they are documented,
        # never accepted as equivalent identities by this inventory.
        candidates = [p for p in files if job['subject'] in p.name and job['task'] in p.name.lower()]
        meta = (ROOT/job['metadata']).read_text()
        start = float(re.search(r'firstEEGtimestamp\):\s*(\d+)', meta)[1])/1000
        fs = float(re.search(r'EEG sampling rate:\s*([\d.]+)', meta)[1])
        n = int(re.search(r'Number of records of EEG:\s*(\d+)', meta)[1])
        end = start+(n-1)/fs
        details = []
        for p in candidates:
            df = pd.read_csv(p, sep='\t' if p.suffix == '.tsv' else ',')
            identities = {col: sorted(str(x) for x in df[col].dropna().unique())
                          for col in ['subject_id', 'session_id', 'run'] if col in df}
            timing = {}
            stems = ['response_onset', 'stop_onset'] if job['task'] == 'sst' else ['choice_onset', 'feedback_onset']
            for stem in stems:
                col = stem+'_unix_time'
                if col not in df:
                    timing[stem] = dict(unix_column_present=False, lsl_column_present=stem+'_lsl_time' in df)
                else:
                    values = pd.to_numeric(df[col], errors='coerce').dropna()/1000
                    overlap = int(((values >= start) & (values <= end)).sum())
                    timing[stem] = dict(unix_column_present=True, finite_events=len(values),
                                        within_recording=overlap, overlap_fraction=overlap/len(values) if len(values) else None)
            details.append(dict(path=str(p.relative_to(ROOT)), sha256=digest(p), n_rows=len(df),
                                identity_fields=identities, timing=timing))
        records.append(dict(recording_id=job['id'], eeg=job['eeg'], manifest_session=job['session'],
                            candidate_files=details, status='unresolved_no_manifest_change'))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open('x') as f:
        json.dump(dict(search_roots=SEARCH_ROOTS, manifest_sha256=digest(manifest),
                       script_sha256=digest(Path(__file__)), records=records), f, indent=2)
        f.write('\n')
    print(len(records), 'unresolved recordings inventoried; no source data or identities changed')


if __name__ == '__main__':
    main()
