"""Extend the existing inventory with protocol/configuration evidence, never wiring guesses."""
import json
import math
import subprocess
from collections import Counter
from pathlib import Path

import pandas as pd

from .core import metadata_record

PROTOCOLS = {
    'impedance_check': 'stimulation/protocols/TACS3_Impedance-Check.neprot',
    'experimental_template': 'stimulation/protocols/PROTOCOL_TEMPLATE.neprot',
    'eeg_recording_template': 'stimulation/protocols/TACS3_bandit_pre-stim.neprot',
}
# Only controlled vocabulary can leave the private inventory. Arbitrary XML
# location labels, NIC step names and operator lead identifiers remain private.
LOCATIONS = {'F3','Fp1','FCz','FT7','F4','P4','P3','EXT','EOG1','Ch8'}
ROLES = {'Stimulation','EEG','EEG Recording','Not used','EEG montage only'}


def protocol_history(root, relative):
    try:
        revisions = subprocess.check_output(['git','-C',str(root),'log','HEAD','--format=%H','--',relative], text=True, stderr=subprocess.DEVNULL).splitlines()
    except (OSError,subprocess.CalledProcessError):
        return [], 'git_history_unavailable'
    records = []
    for revision in revisions:
        try:
            blob = subprocess.check_output(['git','-C',str(root),'show',f'{revision}:{relative}'], stderr=subprocess.DEVNULL)
        except subprocess.CalledProcessError:
            continue  # Deletion commit is not an extant version.
        record = metadata_record(Path(root)/relative, Path(root), data=blob)
        records.append(dict(commit=revision, record=record))
    return records, 'reachable_HEAD_path_history_only_not_NIC_import_history'


def zero_amplitudes(channel, xml=False):
    fields = ['atdcsValue','atacsValue','atrnsValue'] if xml else ['atdcs','atacs','atrns']
    try:
        vals = [float(channel[k]) for k in fields]
        return all(x == 0 for x in vals)
    except (KeyError,TypeError,ValueError):
        return None


def numeric(value):
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError,ValueError):
        return None


def public_protocol(record, category):
    """Exact generic-template settings; never publish generated participant protocols."""
    return dict(category=category, sha256=record['sha256'], parse_issue=bool(record['parse_issue']),
        steps=[{k:numeric(v) for k,v in step.items() if k!='stepName'} for step in record.get('step_details',[])],
        channels=[dict(index=numeric(c['index']),programmed_location=c['location'] if c['location'] in LOCATIONS else 'unrecognized_private_label',
            electrode_type=numeric(c['electrode_type']),all_amplitudes_zero=zero_amplitudes(c,True),
            **({k:numeric(c[k]) for k in ['atdcsValue','atacsValue','ftacsValue','ptacsValue','atrnsValue']} if category=='impedance_check' else {})) for c in record['channels']])


def audit(root, metadata, inventory, values, private, share):
    current = {}; history = {}; sources = {m['source_file']:m for m in metadata}
    for category,relative in PROTOCOLS.items():
        if relative in sources:current[category] = sources[relative]
        versions,status = protocol_history(root,relative)
        history[category] = dict(status=status,versions=versions)
    check_infos = [m for m in metadata if m['kind']=='device_info' and m.get('step_name')=='Impedance Check Only']
    signatures = Counter((m.get('stimulation_channel_count'),m.get('configured_duration_s'),m.get('ramp_up_s'),m.get('ramp_down_s'),m.get('stim_record_count'),m.get('first_stim_timestamp')) for m in check_infos)
    info_summary = [dict(zip(['stimulation_channel_count','configured_duration_s','ramp_up_s','ramp_down_s','stim_record_count','first_stim_timestamp'],sig),n_info_records=n) for sig,n in signatures.items()]
    mappings=[]
    for m in metadata:
        channels = [dict(index=i,**ch) for i,ch in m['channels'].items()] if m['kind']=='device_info' else m['channels']
        for c in channels:
            if c.get('location')=='F3' and str(c.get('index')) in {str(i) for i in range(1,9)}:mappings.append(dict(kind=m['kind'],index=c['index'],source_file=m['source_file'],sha256=m['sha256']))
    private_audit = dict(current_protocols=current,protocol_history=history,impedance_named_info=check_infos,f3_programmed_mappings=mappings,
        interpretation='Settings and recorded channel slots are not physical connection evidence. No current protocol is assigned retrospectively to standalone exports.')
    (private/'protocol_audit.json').write_text(json.dumps(private_audit,indent=2))
    public = dict(schema='impedance-protocol-audit-v1',current_generic_protocols=[public_protocol(m,c) for c,m in current.items()],
        protocol_history=[dict(category=c,status=h['status'],n_extant_versions=len(h['versions']),n_distinct_blobs=len({x['record']['sha256'] for x in h['versions']}),commits=[x['commit'] for x in h['versions']]) for c,h in history.items()],
        impedance_named_info_groups=info_summary,
        f3_programmed_index_counts=[dict(kind=k,channel_index=i,n_configuration_occurrences=n) for (k,i),n in Counter((x['kind'],x['index']) for x in mappings).items()],
        n_documented_physical_locations=int(values.documented_physical_location.ne('').sum()),
        n_documented_physical_leads=int(values.documented_physical_lead.ne('').sum()),
        interpretation='Programmed F3 labels vary by configuration. Channel slots, labels, roles, physical sites and leads remain separate. Zero amplitude does not mean disconnected or excluded from NIC impedance checks. Exact 150000 semantics and diagnostic channel inclusion require manufacturer confirmation.')
    (share/'protocol_audit.json').write_text(json.dumps(public,indent=2))
    # Preserve export mode, named recording context and connection evidence as
    # separate dimensions. Do not turn sample counts into independent checks.
    clean = values.copy()
    clean['programmed_location_category'] = clean.programmed_location.map(lambda x:x if x in LOCATIONS else 'unresolved' if not x else 'unrecognized_private_label')
    clean['configured_role_category'] = clean.configured_role.map(lambda x:x if x in ROLES else 'unresolved' if not x else 'unrecognized_private_role')
    clean['documented_physical_location_available'] = clean.documented_physical_location.ne('')
    clean['documented_physical_lead_available'] = clean.documented_physical_lead.ne('')
    fields=['export_type','measurement_context','source_availability','physical_channel','programmed_location_category','configured_role_category','configured_zero_amplitudes','connected','active']
    rows=[]
    for keys,group in clean.groupby(fields,dropna=False):
        valid=group[group.structurally_valid & group.category.isin(['exact_150000','above_threshold_other','positive_at_or_below_threshold'])]
        rows.append(dict(zip(fields,keys),n_recorded_slots=len(group),n_exports=group.export_id.nunique(),n_eligible_positive_readings=len(valid),n_exact_150000=valid.category.eq('exact_150000').sum(),n_zero=group.category.eq('zero_uninterpreted').sum(),n_documented_physical_locations=group.documented_physical_location_available.sum(),n_documented_physical_leads=group.documented_physical_lead_available.sum()))
    pd.DataFrame(rows,columns=fields+['n_recorded_slots','n_exports','n_eligible_positive_readings','n_exact_150000','n_zero','n_documented_physical_locations','n_documented_physical_leads']).to_csv(share/'configuration_channel_summary.csv',index=False)
    return public
