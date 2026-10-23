"""Read-only historical frequency, generated-protocol and device-record inventory.

    A generated frequency or an EEG file never establishes intended assignment or
    verified stimulation delivery. Condition labels require an explicit local key.
"""
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import pandas as pd

from .common import digest, flag, number
from .discovery import read_table
from .identity import IdentityResolver


COUNTERBALANCE = {"A": ["sham", "beta", "theta"], "B": ["sham", "theta", "beta"],
                  "C": ["beta", "theta", "sham"], "D": ["beta", "sham", "theta"],
                  "E": ["theta", "sham", "beta"], "F": ["theta", "beta", "sham"]}


def scan_metadata(root, identities=None):
    identities = identities or IdentityResolver()
    frequencies, stimulation, inventory = [], [], []
    folders = ["stimulation/calculated-theta-beta", "stimulation/protocols/generated", "stimulation/stimulation-data"]
    for folder in folders:
        for path in sorted((root / folder).rglob("*")):
            if not path.is_file() or path.name.startswith("."):
                continue
            inventory.append(dict(source_file=str(path.relative_to(root)), bytes=path.stat().st_size,
                                  file_type=path.suffix, metadata_role=folder))
    # pilot EEG and auxiliary historical estimates are inventoried without loading raw EEG.
    for path in sorted((root / "pilot_data").rglob("*")):
        if path.is_file() and "_task-" not in path.name and not path.name.startswith("."):
            inventory.append(dict(source_file=str(path.relative_to(root)), bytes=path.stat().st_size,
                                  file_type=path.suffix, metadata_role="pilot_auxiliary"))
    for path in sorted((root / "stimulation/calculated-theta-beta").glob("*_pre-stim_theta-beta.txt")):
        match = re.fullmatch(r"(.+)-(\d+)_pre-stim_theta-beta.txt", path.name)
        if not match:
            continue
        text = path.read_text(errors="replace")
        eeg = re.search(r"^EEG:\s*(.*)$", text, re.M)
        behavior = re.search(r"^Behavior:\s*(.*)$", text, re.M)
        eeg = eeg[1].strip() if eeg else ""
        behavior = behavior[1].strip() if behavior else ""
        source_task = "sst" if "sst" in behavior.lower() else "bandit" if "bandit" in behavior.lower() else "unknown"
        task_conflict = ("sst" in eeg.lower() and source_task == "bandit") or ("bandit" in eeg.lower() and source_task == "sst")
        for rhythm in ["theta", "beta"]:
            value = re.search(rf"^{rhythm} stimulation frequency:\s*([\d.]+)", text, re.I | re.M)
            method = re.search(r"Selected theta:\s*(.*)", text) if rhythm == "theta" else None
            section = text.split("\nTHETA\n")[-1].split("\nBETA\n")[0] if rhythm == "theta" else text.split("\nBETA\n")[-1].split("STIMULATION FREQUENCIES")[0]
            counts = re.search(rf"{'Feedback' if rhythm == 'theta' else 'Decision'}:\s*(\d+) valid events\s*\|\s*(\d+) retained", text)
            warnings = ["historical_estimate_not_validated"]
            if "BAND EDGE" in section:
                warnings.append("band_edge")
            if task_conflict:
                warnings.append("eeg_behavior_task_mismatch")
            if counts and int(counts[2]) == 0:
                warnings.append("zero_retained_epochs")
            if not value:
                warnings.append("frequency_unavailable")
            if rhythm == "beta":
                contrast = re.search(r"TFR beta ERD:.*?\|\s*([+-]?[\d.]+) dB", section)
                if contrast and float(contrast[1]) >= 0:
                    warnings.append("no_beta_suppression")
            frequencies.append(dict(**identities.fields(match[1], str(path.relative_to(root))), raw_participant=match[1], session=int(match[2]),
                                    rhythm=rhythm, historical_frequency_hz=number(value[1]) if value else np.nan,
                                    method=method[1].strip() if method else "historical_TFR_ERD" if rhythm == "beta" else "unknown",
                                    task_source=source_task, eeg_source=eeg, behavior_source=behavior,
                                    eligible_epochs=int(counts[1]) if counts else np.nan,
                                    retained_epochs=int(counts[2]) if counts else np.nan,
                                    fallback_status="documented_fallback" if "fallback" in section.lower() else "not_documented",
                                    reliability_status="unvalidated", qc_flags=";".join(warnings),
                                    source_file=str(path.relative_to(root)), sha256=digest(path)))
    for path in sorted((root / "stimulation/protocols/generated").glob("*.neprot")):
        match = re.match(r"(.+)_visit(\d+)(?:_(bandit|SST)_run(\d+))?\.neprot", path.name, re.I)
        if not match:
            continue
        try:
            xml = ET.parse(path)
            hz = sorted({float(node.text) for node in xml.findall(".//ftacsValue") if node.text})
            step_types = ";".join(sorted({n.text for n in xml.findall(".//stepType") if n.text}))
            electrode_types = ";".join(sorted({n.text for n in xml.findall(".//electrodeType") if n.text}))
            amps = [float(n.text) for tag in ["atdcsValue", "atacsValue", "atrnsValue"] for n in xml.findall(".//" + tag) if n.text]
            zero_amplitudes = all(x == 0 for x in amps) if amps else None
            error = ""
        except (ET.ParseError, ValueError) as exc:
            hz, error = [], str(exc)
            step_types, electrode_types, zero_amplitudes = "", "", None
        stimulation.append(dict(**identities.fields(match[1], str(path.relative_to(root))), raw_participant=match[1], session=int(match[2]),
                                task=(match[3] or "unknown").lower(), run=int(match[4]) if match[4] else np.nan,
                                record_kind="generated_protocol", protocol_step_types=step_types,
                                protocol_electrode_types=electrode_types, all_programmed_amplitudes_zero=zero_amplitudes, frequency_hz=hz[0] if len(hz) == 1 else np.nan,
                                frequency_values=";".join(map(str, hz)), delivery_status="generation_only",
                                stim_record_count=np.nan, first_stim_timestamp=np.nan,
                                source_file=str(path.relative_to(root)), sha256=digest(path), qc_flags=error))
    for path in sorted((root / "stimulation/stimulation-data").rglob("*.info")):
        match = re.match(r"\d{14}_([^_]+)-(\d+)_(Bandit|SST)-(\d+)\.info", path.name, re.I)
        if not match:
            continue
        text = path.read_text(errors="replace")
        hz = sorted({float(x) for x in re.findall(r"Ftacs \(Hz\):\s*([\d.]+)", text)})
        count = re.search(r"Number of records of Stimulation:\s*(\d+)", text)
        first = re.search(r"StartDate \(firstSTIMtimestamp\):\s*(\d+)", text)
        records = int(count[1]) if count else np.nan
        stimulation.append(dict(**identities.fields(match[1], str(path.relative_to(root))), raw_participant=match[1], session=int(match[2]),
                                task=match[3].lower(), run=int(match[4]), record_kind="device_info",
                                frequency_hz=hz[0] if len(hz) == 1 else np.nan, frequency_values=";".join(map(str, hz)),
                                delivery_status="eeg_only_documented" if "EEG only mode" in text else "settings_only_delivery_unverified",
                                stim_record_count=records, first_stim_timestamp=int(first[1]) if first else np.nan,
                                source_file=str(path.relative_to(root)), sha256=digest(path),
                                qc_flags="no_recorded_stimulation_samples" if records == 0 else ""))
    return pd.DataFrame(frequencies), pd.DataFrame(stimulation), pd.DataFrame(inventory)


def condition_key(path, identities=None):
    identities = identities or IdentityResolver()
    if path is None:
        return pd.DataFrame(columns=["participant", "session", "intended_condition", "intended_frequency_hz",
                                     "documented_delivered_frequency_hz", "delivery_verified", "condition_evidence"])
    d, _ = read_table(path)
    required = {"participant", "session", "condition_evidence"}
    if not required.issubset(d):
        raise ValueError("condition key requires participant, session, condition_evidence")
    d["recorded_participant"] = d.participant
    d.participant = d.participant.map(identities.resolve)
    d.session = pd.to_numeric(d.session, errors="raise").astype(int)
    if d.duplicated(["participant", "session"]).any():
        raise ValueError("duplicate participant/session in condition key")
    for name in ["intended_condition", "intended_frequency_hz", "documented_delivered_frequency_hz", "delivery_verified"]:
        if name not in d:
            d[name] = ""
    for i, row in d.iterrows():
        cb = row.get("counterbalance", "")
        if cb:
            if cb not in COUNTERBALANCE or row.session not in [1, 2, 3]:
                raise ValueError("invalid counterbalance or visit in key")
            inferred = COUNTERBALANCE[cb][row.session - 1]
            if row.intended_condition and inferred != row.intended_condition:
                raise ValueError("explicit condition conflicts with documented counterbalance")
            d.loc[i, "intended_condition"] = inferred
        if d.loc[i, "intended_condition"] not in {"sham", "theta", "beta", ""}:
            raise ValueError("unknown condition label in key")
        if not d.loc[i, "intended_condition"]:
            raise ValueError("condition key requires intended_condition or documented counterbalance")
        if not row.condition_evidence.strip():
            raise ValueError("a local condition key requires documented evidence")
        if flag(row.delivery_verified) is True and (not np.isfinite(number(row.documented_delivered_frequency_hz))):
            raise ValueError("verified delivery requires a documented frequency (zero permitted for sham)")
    d["condition_key_sha256"] = digest(path)
    # Arbitrary key columns cannot overwrite frequency/QC or clinical fields.
    allowed = ["participant", "recorded_participant", "session", "intended_condition", "counterbalance", "intended_frequency_hz",
               "documented_delivered_frequency_hz", "delivery_verified", "condition_evidence", "condition_key_sha256"]
    return d[[name for name in allowed if name in d]]


def session_metadata(manifest, freq, stim, key):
    rows = []
    sessions = manifest.dropna(subset=["participant", "session"])[["participant", "session"]].drop_duplicates()
    for _, session in sessions.iterrows():
        p, s = session.participant, session.session
        f = freq[(freq.participant == p) & (freq.session == s)] if len(freq) else freq
        t = stim[(stim.participant == p) & (stim.session == s)] if len(stim) else stim
        row = dict(participant=p, session=s, intended_condition="", intended_frequency_hz=np.nan,
                   documented_delivered_frequency_hz=np.nan, delivery_verified=False, condition_evidence="",
                   condition_status="missing_local_key", verified_delivery_status="unverified",
                   frequency_reliability="unvalidated_historical;PR1_no_primary_estimate_passed")
        for rhythm in ["theta", "beta"]:
            group = f[f.rhythm.eq(rhythm)] if len(f) else f
            values = sorted(group.historical_frequency_hz.dropna().unique()) if len(group) else []
            row[f"historical_{rhythm}_hz"] = values[0] if len(values) == 1 else np.nan
            row[f"historical_{rhythm}_values"] = ";".join(map(str, values))
            row[f"{rhythm}_frequency_status"] = "conflicting_reports" if len(values) > 1 else "unvalidated" if values else "missing"
            row[f"{rhythm}_frequency_sources"] = ";".join(group.source_file) if len(group) else ""
        protocols = t[t.record_kind.eq("generated_protocol")] if len(t) else t
        devices = t[t.record_kind.eq("device_info")] if len(t) else t
        row["generated_frequency_values_hz"] = ";".join(map(str, sorted(protocols.frequency_hz.dropna().unique()))) if len(protocols) else ""
        row["device_documented_frequency_values_hz"] = ";".join(map(str, sorted(devices.frequency_hz.dropna().unique()))) if len(devices) else ""
        row["n_generated_protocols"] = len(protocols)
        row["n_device_records"] = len(devices)
        row["n_eeg_only_device_records"] = int(devices.delivery_status.eq("eeg_only_documented").sum()) if len(devices) else 0
        explicit = key[(key.participant == p) & (key.session == s)]
        if len(explicit):
            row.update(explicit.iloc[0].to_dict())
            row["delivery_verified"] = flag(row["delivery_verified"]) is True
            row["verified_delivery_status"] = "locally_verified" if row["delivery_verified"] else "unverified"
            row["condition_status"] = "documented_intended_assignment"
        rows.append(row)
    return pd.DataFrame(rows)
