"""Preserve distinctions between settings, recording, diagnostic current and wiring."""
import csv
import json
import subprocess
from pathlib import Path

import pandas as pd
import pytest

from impedance_analysis.core import metadata_record,digest
from impedance_analysis.pipeline import run
from impedance_analysis.protocol_audit import protocol_history,public_protocol,zero_amplitudes


def xml(location='F3',role='2',amplitude='0'):
    return f'''<ProtocolTemplates><Template><Step><stepName>PRIVATE participant label</stepName><stepType>0</stepType><stimulationTime>300</stimulationTime><rampUp>30</rampUp><rampDown>30</rampDown><Channel><index>1</index><location>{location}</location><electrodeType>{role}</electrodeType><atacsValue>{amplitude}</atacsValue><atdcsValue>0</atdcsValue><atrnsValue>0</atrnsValue><ftacsValue>6</ftacsValue><ptacsValue>0</ptacsValue></Channel></Step></Template></ProtocolTemplates>'''


def test_zero_amplitude_keeps_configured_role_and_not_execution(tmp_path):
    p=tmp_path/'generic.neprot';p.write_text(xml())
    r=metadata_record(p,tmp_path)
    assert r['channels'][0]['electrode_type']=='2'
    assert zero_amplitudes(r['channels'][0],True) is True
    assert r['step_details'][0]['stimulationTime']=='300'
    assert 'execution_evidence' not in r
    assert zero_amplitudes({'atacs':0}) is None


def test_info_distinguishes_channel_count_duration_and_zero_recording(tmp_path):
    p=tmp_path/'20260101120000_G00001-1_Test.info'
    p.write_text("Step name: Impedance Check Only\nNumber of stimulation channels: 7\nNumber of records of Stimulation: 0\nStartDate (firstSTIMtimestamp): 0\nStimulation configured duration (s): 180\nStimulation parameters:\nChannel 1: \n Position: F3\n Type: Stimulation\n Atdcs (uA): 0\n Atacs (uA): 0\n Ftacs (Hz): 0\n Ptacs (º): 0\n Atrns (uA): 0\n")
    r=metadata_record(p,tmp_path)
    assert r['stimulation_channel_count']==7 and r['configured_duration_s']==180
    assert r['execution_evidence']=='zero_recorded_stimulation_samples_not_proof_no_diagnostic_current'
    assert r['channels']['1']['configured_role']=='Stimulation'
    assert zero_amplitudes(r['channels']['1']) is True


def test_protocol_history_is_versioned_and_read_only(tmp_path):
    p=tmp_path/'check.neprot';p.write_text(xml('F3'))
    def git(*args):return subprocess.run(['git','-C',str(tmp_path),*args],check=True,capture_output=True)
    git('init');git('add','.');git('-c','user.name=Test','-c','user.email=test@example.org','commit','-m','initial')
    p.write_text(xml('F4'));git('add','.');git('-c','user.name=Test','-c','user.email=test@example.org','commit','-m','mapping change')
    before=p.read_bytes();versions,status=protocol_history(tmp_path,'check.neprot')
    assert len(versions)==2 and len({v['record']['sha256'] for v in versions})==2
    assert [v['record']['channels'][0]['location'] for v in versions]==['F4','F3']
    assert p.read_bytes()==before and 'not_NIC_import_history' in status


@pytest.mark.parametrize('configured_role',['Stimulation','EEG Recording'])
def test_programmed_location_physical_site_and_lead_never_conflated(tmp_path,configured_role):
    root=tmp_path/'repo';root.mkdir();out=tmp_path/'out'
    p=root/'20260101120000_G00001-1_Test_IMP.txt';p.write_text('150000 4000 4000 4000 0 0 0 0 1767268800000')
    info=root/'20260101120001_G00001-1_Test.info';info.write_text('Step name: Test\nStimulation parameters:\nChannel 1: \n Position: F3\n Type: Stimulation\n Atdcs (uA): 0\n Atacs (uA): 0\n Atrns (uA): 0\n'.replace('Type: Stimulation',f'Type: {configured_role}'))
    log=tmp_path/'configuration.csv'
    row=dict(source_file=p.name,sha256=digest(p),setup='flat_cable_testboard',connected_channels='none',active_channels='none',evidence='PRIVATE wiring note',channel_locations='{"1":"PRIVATE SITE"}',channel_leads='{"1":"PRIVATE LEAD G00001"}')
    with log.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(row));w.writeheader();w.writerow(row)
    run(root,out,configuration_log=log,figures=False)
    d=pd.read_csv(out/'private/readings.csv',keep_default_na=False).iloc[0]
    assert d.programmed_location=='F3' and d.documented_physical_location=='PRIVATE SITE'
    assert d.documented_physical_lead=='PRIVATE LEAD G00001'
    assert d.connected=='no' and d.configured_zero_amplitudes=='yes'
    shared='\n'.join(p.read_text() for p in (out/'share').iterdir())
    assert 'PRIVATE' not in shared and 'G00001' not in shared
    s=pd.read_csv(out/'share/configuration_channel_summary.csv')
    assert s.loc[s.physical_channel==1,'programmed_location_category'].iloc[0]=='F3'
    assert s.loc[s.physical_channel==1,'connected'].iloc[0]=='no'
    assert s.loc[s.physical_channel==1,'configured_role_category'].iloc[0]==configured_role


def test_public_audit_rejects_arbitrary_text_in_generic_fields(tmp_path):
    p=tmp_path/'check.neprot';p.write_text(xml('PRIVATE SITE',role='PRIVATE ROLE',amplitude='PRIVATE AMPLITUDE').replace('<stimulationTime>300','<stimulationTime>PRIVATE DURATION'))
    r=public_protocol(metadata_record(p,tmp_path),'impedance_check')
    assert 'PRIVATE' not in json.dumps(r)
    assert r['channels'][0]['electrode_type'] is None
    assert r['steps'][0]['stimulationTime'] is None
