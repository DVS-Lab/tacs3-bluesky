#!/usr/bin/env python3
"""Inventory Git-tracked inputs without guessing identities, clocks, or missing runs.

Generated manifests and inventory details contain participant filenames. Keep them
in ignored validation_outputs; commit this builder and synthetic tests only.
A complete Git inventory is not proof of complete acquisition coverage.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
EEG = re.compile(r'^(?P<run>\d{14})_(?P<subject>[A-Za-z0-9]+)-(?P<session>\d+)_(?P<task>Bandit|SST)_(?P<phase>pre|post)-stim\.easy$', re.I)
EVENT = re.compile(r'^sub-(?P<subject>[A-Za-z0-9]+)-(?P<session>\d+)_task-(?P<task>Bandit|SST)_(?P<phase>pre|post)-stim.*\.(?:csv|tsv)$', re.I)


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024*1024), b''): h.update(block)
    return h.hexdigest()


def identity(match):
    # Task and phase names are case-insensitive, participant identifiers are not.
    d = match.groupdict()
    return (d['subject'], str(int(d['session'])), d['task'].lower(), d['phase'].lower())


def exclusion_category(paths):
    """Describe filename evidence only; do not infer delivered stimulation/phase."""
    name=Path(sorted(paths)[0]).name
    if re.search(r'_(Bandit|SST)-\d+\.easy$',name,re.I):return 'numbered_task_run_phase_unspecified'
    if re.search(r'_(Bandit|SST)_(pre|post)-stim\.easy$',name,re.I):return 'task_phase_present_missing_session'
    if 'Template change later lol' in name:return 'generic_template_label'
    if re.search(r'_(?:\d+ (?:Beta|Theta)(?: Sham)?|Sham)\.easy$',name,re.I):return 'stimulation_named'
    if re.search(r'_Run \d+\.easy$',name,re.I):return 'generic_run_label'
    if re.search(r'test',name,re.I):return 'test_named'
    if 'Non-stim' in name:return 'non_stim_named'
    return 'other_unclassified'


def tracked_paths(root, ref):
    return subprocess.check_output(['git','-C',str(root),'ls-tree','-r','--name-only',ref], text=True).splitlines()


def build(root, paths, historical):
    root = Path(root)
    relevant = sorted(p for p in paths if Path(p).suffix.lower() in {'.easy','.info','.csv','.tsv'})
    present = [p for p in relevant if (root/p).is_file()]
    hashes = {p:digest(root/p) for p in present}
    by_hash = defaultdict(list)
    for p,h in hashes.items(): by_hash[h].append(p)
    eeg_paths = [p for p in relevant if Path(p).suffix.lower()=='.easy']
    infos = defaultdict(list); behaviors = defaultdict(list)
    for p in present:
        if p.endswith('.info'): infos[Path(p).stem].append(p)
        m = EVENT.fullmatch(Path(p).name)
        if m: behaviors[identity(m)].append(p)

    def unique(candidates):
        groups = defaultdict(list)
        for p in candidates: groups[hashes[p]].append(p)
        return sorted(next(iter(groups.values())))[0] if len(groups)==1 else None

    def restore(path, expected, suffix):
        if not path or not expected: return None
        if path in hashes and hashes[path]==expected: return path
        choices = [p for p in by_hash[expected] if Path(p).suffix.lower()==suffix]
        return sorted(choices)[0] if choices else None

    jobs=[]; consumed=set(); provenance=[]
    for original in historical.get('jobs',[]):
        job=deepcopy(original); changes=[]; missing=[]
        for field in ('eeg','events','metadata'):
            old=original.get(field)
            if not old: continue
            selected=restore(old, original.get('sha256',{}).get(field), Path(old).suffix.lower())
            job[field]=selected
            if selected!=old: changes.append({'field':field,'old_path':old,'new_path':selected,'basis':'exact_sha256_only'})
            if selected is None: missing.append(field)
        if missing:
            job['missing_reason']='historical_input_missing_or_changed:'+','.join(missing)
            # The runner represents all unresolved inputs as explicit failures.
            if 'metadata' in missing: job['events']=None
        job['manifest_origin']='historical_hash_verified_link'
        if original.get('sha256',{}).get('eeg'): consumed.add(original['sha256']['eeg'])
        jobs.append(job); provenance.append({'id':job['id'],'relocations':changes,'missing':missing})

    eeg_groups=defaultdict(list)
    for p in eeg_paths:
        if p in hashes: eeg_groups[hashes[p]].append(p)
    excluded=[]
    for h, copies in sorted(eeg_groups.items(),key=lambda item:sorted(item[1])[0]):
        if h in consumed: continue
        parsed=[(p,EEG.fullmatch(Path(p).name)) for p in copies]
        parsed=[(p,m) for p,m in parsed if m]
        if not parsed:
            excluded.append({'sha256':h,'paths':copies,'reason':'no_explicit_task_phase_session_filename'})
            continue
        keys={(*identity(m),m['run']) for _,m in parsed}
        if len(keys)!=1:
            excluded.append({'sha256':h,'paths':copies,'reason':'identical_eeg_with_conflicting_filename_identity'})
            continue
        eeg,m=sorted(parsed,key=lambda item:item[0])[0]
        subject,session,task,phase=identity(m)
        event_candidates=behaviors[(subject,session,task,phase)]
        events=unique(event_candidates)
        metadata_candidates=infos[Path(eeg).stem]
        metadata=unique(metadata_candidates)
        reasons=[]
        if not events: reasons.append('ambiguous_behavior' if event_candidates else 'missing_explicit_behavior')
        if not metadata: reasons.append('ambiguous_metadata' if metadata_candidates else 'missing_metadata')
        job=dict(id=f'{subject}_ses-{session}_{task}_{phase}_{m["run"]}',subject=subject,session=session,
                 task=task,phase=phase,run=m['run'],eeg=eeg,events=events,metadata=metadata,
                 clock_domain='unix',event_unit='ms',sha256={k:hashes[v] for k,v in [('eeg',eeg),('events',events),('metadata',metadata)] if v},
                 manifest_origin='exact_explicit_filename_identity',
                 match_evidence='Unique content for exact subject/session/task/phase; no acquisition-clock offset or overlap inferred.',
                 duplicate_eeg_paths=sorted(copies),behavior_candidates=sorted(event_candidates),metadata_candidates=sorted(metadata_candidates))
        if reasons:
            job['missing_reason']=';'.join(reasons)
            # Missing metadata must not allow an otherwise resolved events link
            # to masquerade as a usable complete pair in summary or runner.
            if not metadata: job['events']=None
        jobs.append(job)
    for item in excluded:
        item['filename_category']=exclusion_category(item['paths'])
    aliases=[dict(sha256=h,paths=sorted(copies),in_historical_manifest=h in consumed) for h,copies in eeg_groups.items() if len({Path(p).name for p in copies})>1]
    counts=Counter(Path(p).suffix.lower() for p in paths)
    resolved=[j for j in jobs if all(j.get(k) for k in ('eeg','events','metadata'))]
    ids=[j['id'] for j in jobs]
    if len(ids)!=len(set(ids)): raise ValueError('duplicate_recording_ids_require_review')
    summary=dict(tracked_file_counts=dict(counts),tracked_easy_files=len(eeg_paths),
                 unique_easy_content=len(eeg_groups),duplicate_easy_copies=sum(len(p)-1 for p in eeg_groups.values()),
                 missing_tracked_input_files=[p for p in relevant if p not in hashes],
                 manifest_recordings=len(jobs),historical_recordings=len(historical.get('jobs',[])),
                 recordings_with_all_input_paths=len(resolved),unresolved_recordings=len(jobs)-len(resolved),
                 excluded_easy_content=len(excluded),excluded_easy_copies=sum(len(x['paths']) for x in excluded),
                 excluded_filename_categories=dict(Counter(x['filename_category'] for x in excluded)),
                 excluded_category_interpretation='Filename categories only. Numbered task runs have no verified pre/post phase and may involve stimulation; a name or zero recorded STIM samples does not establish delivered stimulation.',
                 distinct_filename_alias_groups=len(aliases),
                 unresolved_reasons=dict(Counter(j.get('missing_reason','unknown') for j in jobs if j not in resolved)),
                 acquisition_completeness='Unknown: no master acquisition/session inventory supplied. Git availability does not verify completeness, wiring, timing, or executable build provenance.',
                 pairing_policy='No newest-file, nearest-identity, maximum-overlap, phase, or clock-offset substitution. Exact SHA256 duplicates are counted once. Downstream identity/clock/channel checks remain mandatory.')
    return dict(schema='rhythm-input-manifest-v1',jobs=jobs),dict(summary=summary,historical_relocations=provenance,excluded_eeg=excluded,distinct_filename_aliases=aliases,input_sha256=hashes)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--ref',default='origin/main');p.add_argument('--historical',type=Path,default=ROOT/'validation/pilot_manifest.json')
    p.add_argument('--output-name',default='current_inventory')
    a=p.parse_args()
    if Path(a.output_name).name!=a.output_name or a.output_name in {'.','..'}:p.error('output-name must be a new directory name')
    out=ROOT/'validation_outputs'/a.output_name;out.mkdir(parents=True,exist_ok=False)
    paths=tracked_paths(ROOT,a.ref)
    changed=set(subprocess.check_output(['git','-C',str(ROOT),'diff','--name-only',a.ref],text=True).splitlines())
    dirty_inputs=sorted(p for p in paths if p in changed and Path(p).suffix.lower() in {'.easy','.info','.csv','.tsv'})
    if dirty_inputs: raise ValueError('Tracked source inputs differ from requested Git ref; resolve or explicitly audit them before building a manifest.')
    manifest,inventory=build(ROOT,paths,json.loads(a.historical.read_text()))
    inventory['tracked_source_files_match_ref']=True
    inventory['git_source_ref']=a.ref
    inventory['git_source_commit']=subprocess.check_output(['git','-C',str(ROOT),'rev-parse',a.ref],text=True).strip()
    inventory['historical_manifest_sha256']=digest(a.historical)
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    (out/'inventory.json').write_text(json.dumps(inventory,indent=2)+'\n')
    print(json.dumps(inventory['summary'],indent=2));print(out)


if __name__=='__main__':main()
