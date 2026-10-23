"""Loss-aware parsing and evidence-bound configuration linkage."""
import csv
import hashlib
import json
import math
import re
import subprocess
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

from behavioral_analysis.identity import IdentityResolver

SKIP = {".git", ".venv", "venv", "outputs", "local", "__pycache__", ".pytest_cache"}
SETUPS = {"flat_cable_testboard", "normal_electrode_cable", "headcap", "other", "unknown"}


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def source_paths(root):
    """Scan the repository, including pilots; omit only derived/tool directories."""
    return sorted(p for p in root.rglob("*") if p.is_file() and not p.is_symlink()
                  and not (set(p.relative_to(root).parts) & SKIP))


def filename_fields(name, identities=None, source_file=""):
    identities = identities or IdentityResolver()
    m = re.match(r"(\d{14})_(.*)", name)
    timestamp, tail, issue = "", name, ""
    if m:
        tail = m[2]
        try:
            timestamp = datetime.strptime(m[1], "%Y%m%d%H%M%S").isoformat()
        except ValueError:
            issue = "invalid_filename_timestamp"
    else:
        issue = "missing_filename_timestamp"
    tail = re.sub(r"_(?:ImpVal|IMP)\.txt$|\.info$", "", tail, flags=re.I)
    # Only a numeric or G/R numeric identity has an unambiguous visit suffix here.
    match = re.match(r"([GgRr]?\d+)-(\d+)(?:_(.*))?$", tail)
    participant, visit, step = (match[1], match[2], match[3] or "") if match else (tail.split("_")[0], "", tail.partition("_")[2])
    return dict(timestamp=timestamp, timestamp_basis="filename_wall_time_timezone_unverified",
                recorded_participant=participant, participant=identities.resolve(participant, source_file),
                visit=visit, step=step, filename_issue=issue)


def classify(value, threshold=20000):
    if value is None or not math.isfinite(value):
        return "invalid_or_missing"
    if value == 150000:
        return "exact_150000"
    if value == 0:
        return "zero_uninterpreted"
    if value < 0:
        return "negative_invalid"
    return "above_threshold_other" if value > threshold else "positive_at_or_below_threshold"


def parse_export(path, root, threshold=20000, identities=None, data=None):
    rel = path.relative_to(root).as_posix()
    mode = "standalone" if path.name.lower().endswith("_impval.txt") else "continuous"
    data = path.read_bytes() if data is None else data
    sha = hashlib.sha256(data).hexdigest()
    # Stable opaque identifier without recruitment identity; paths stay private.
    export_id = "E" + hashlib.sha256((rel + sha).encode()).hexdigest()[:16]
    meta = dict(source_file=rel, sha256=sha, export_id=export_id, export_type=mode,
                **filename_fields(path.name, identities, rel))
    text = data.decode("utf-8", errors="replace")
    issues = [meta["filename_issue"]] if meta["filename_issue"] else []
    if "\ufffd" in text:
        issues.append("undecodable_bytes")
    lines = text.splitlines()
    if not lines:
        issues.append("empty_file")
    if mode == "standalone" and len(lines) != 1:
        issues.append("expected_one_row")
    rows, errors = [], []
    for line_number, line in enumerate(lines, 1):
        tokens = line.split()  # bare tab/space-separated NIC exports
        expected = 8 if mode == "standalone" else 9
        row_issues = [x for x in issues if x in {"expected_one_row", "undecodable_bytes"}]
        if len(tokens) != expected:
            row_issues.append(f"expected_{expected}_fields_got_{len(tokens)}")
        epoch, epoch_time = "", ""
        if mode == "continuous" and len(tokens) >= 9:
            epoch = tokens[8]
            try:
                number = float(epoch)
                if not math.isfinite(number) or number <= 0:
                    raise ValueError()
                epoch_time = datetime.fromtimestamp(number / 1000, timezone.utc).isoformat()
            except (ValueError, OverflowError, OSError):
                row_issues.append("invalid_epoch_ms")
        values = []
        for channel in range(1, 9):
            token = tokens[channel - 1] if channel <= len(tokens) else ""
            try:
                value = float(token)
                if not math.isfinite(value):
                    raise ValueError()
            except ValueError:
                value = None
                row_issues.append(f"invalid_channel_{channel}")
            values.append((token, value))
        if row_issues:
            errors.append(dict(export_id=export_id, row_number=line_number, issues=";".join(row_issues), raw_line=line))
        # Even malformed rows retain eight channel slots; never repair shifted columns.
        for channel, (token, value) in enumerate(values, 1):
            rows.append(dict(export_id=export_id, export_type=mode, row_number=line_number,
                             timestamp=meta["timestamp"], epoch_ms=epoch, sample_utc=epoch_time,
                             physical_channel=channel, raw_token=token, value=value,
                             category=classify(value, threshold), structurally_valid=not row_issues,
                             row_issues=";".join(row_issues)))
    meta.update(n_rows=len(lines), n_malformed_rows=len(errors), file_issues=";".join(issues))
    return meta, rows, errors


def metadata_record(path, root, identities=None, data=None):
    rel = path.relative_to(root).as_posix()
    data = path.read_bytes() if data is None else data
    record = dict(source_file=rel, sha256=hashlib.sha256(data).hexdigest(), kind="device_info" if path.suffix.lower() == ".info" else "protocol",
                  channels={}, steps=[], parse_issue="")
    text = data.decode("utf-8", errors="replace")
    if record["kind"] == "device_info":
        record.update(filename_fields(path.name, identities, rel))
        for field, pattern in [("nic_version", r"Software's version:\s*([^\n]+)"),
                               ("firmware", r"Firmware's version:\s*([^\n]+)"),
                               ("device_id", r"Device ID:\s*([^\n]+)"), ("step_name", r"Step name:\s*([^\n]+)")]:
            match = re.search(pattern, text)
            record[field] = match[1].strip() if match else ""
        for field, pattern in [
            ("stimulation_channel_count", r"Number of stimulation channels:\s*(\d+)"),
            ("stim_record_count", r"Number of records of Stimulation:\s*(\d+)"),
            ("first_stim_timestamp", r"StartDate \(firstSTIMtimestamp\):\s*(\d+)"),
            ("configured_duration_s", r"Stimulation configured duration \(s\):\s*([\d.]+)"),
            ("ramp_up_s", r"Ramp up duration \(s\):\s*([\d.]+)"),
            ("ramp_down_s", r"Ramp down duration \(s\):\s*([\d.]+)")]:
            match = re.search(pattern, text)
            record[field] = float(match[1]) if match else None
        record["execution_evidence"] = ("zero_recorded_stimulation_samples_not_proof_no_diagnostic_current"
            if record["stim_record_count"] == 0 else "recorded_stimulation_samples_require_delivery_review"
            if record["stim_record_count"] is not None and record["stim_record_count"] > 0 else "not_established")
        block = text.partition("Stimulation parameters:")[2]
        for match in re.finditer(r"Channel (\d+):\s*\n(.*?)(?=\n\s*Channel \d+:|\Z)", block, re.S):
            position = re.search(r"Position:\s*([^\n]+)", match[2])
            role = re.search(r"Type:\s*([^\n]+)", match[2])
            record["channels"][match[1]] = dict(location=position[1].strip() if position else "",
                                                  configured_role=role[1].strip() if role else "")
        for match in re.finditer(r"Channel (\d+):\s*\n(.*?)(?=\n\s*Channel \d+:|\Z)", block, re.S):
            channel = record["channels"][match[1]]
            for field, pattern in [("atdcs", r"Atdcs \(uA\):"), ("atacs", r"Atacs \(uA\):"),
                                   ("ftacs", r"Ftacs \(Hz\):"), ("ptacs", r"Ptacs \([^)]*\):"),
                                   ("atrns", r"Atrns \(uA\):")]:
                value = re.search(pattern+r"\s*([-+\d.eE]+)", match[2])
                try: channel[field] = float(value[1]) if value else None
                except ValueError: channel[field] = None
        if not record["channels"]:
            montage = text.partition("EEG montage:")[2].partition("Accelerometer")[0]
            record["channels"] = {m[1]: dict(location=m[2].strip(), configured_role="EEG montage only")
                                   for m in re.finditer(r"Channel (\d+):\s*([^\n]+)", montage)}
        if not record["channels"]:
            record["parse_issue"] = "no_channel_configuration_found"
    else:
        try:
            xml = ET.fromstring(text)
            record["steps"] = [step.findtext("stepName", "") for step in xml.findall(".//Step")]
            record["step_details"] = [dict(step_index=i, **{tag:step.findtext(tag, "") for tag in ["stepName", "stepType", "stimulationTime", "rampUp", "rampDown", "rampSham"]}) for i,step in enumerate(xml.findall(".//Step"),1)]
            record["channels"] = [dict(step=step.findtext("stepName", ""), index=c.findtext("index", ""),
                                       location=c.findtext("location", ""), electrode_type=c.findtext("electrodeType", ""),
                                       **{tag:c.findtext(tag, "") for tag in ["atdcsValue", "atacsValue", "ftacsValue", "ptacsValue", "atrnsValue"]})
                                  for step in xml.findall(".//Step") for c in step.findall("Channel")]
        except ET.ParseError as exc:
            record["parse_issue"] = str(exc)
    return record


def channel_set(value):
    if not value or value == "unknown":
        return None
    if value == "none":
        return set()
    values = value.split(";")
    try:
        result = {int(x) for x in values}
    except ValueError:
        raise ValueError("channel lists require 1;2;3, none, or unknown") from None
    if len(values) != len(result) or not result <= set(range(1, 9)):
        raise ValueError("channel lists must have unique physical channels 1 through 8")
    return result


def load_config(path, inventory, metadata):
    """Explicit file/hash bindings; no unlogged inference from impedance values."""
    if path is None:
        return {}
    exports = {x["source_file"]: x for x in inventory}
    records = {x["source_file"]: x for x in metadata}
    configs = {}
    with Path(path).open(newline="") as f:
        reader = csv.DictReader(f)
        required = {"source_file", "sha256", "setup", "connected_channels", "active_channels", "evidence"}
        if not required <= set(reader.fieldnames or []):
            raise ValueError("configuration log requires " + ", ".join(sorted(required)))
        for row in reader:
            rel = row["source_file"]
            if rel in configs or rel not in exports or row["sha256"] != exports[rel]["sha256"]:
                raise ValueError("duplicate, unknown source_file or mismatched configuration hash")
            if row["setup"] not in SETUPS or not row["evidence"].strip():
                raise ValueError("configuration requires allowed setup and documented evidence")
            connected, active = channel_set(row["connected_channels"]), channel_set(row["active_channels"])
            if connected is not None and active is not None and not active <= connected:
                raise ValueError("active channels must be a subset of documented connected channels")
            for field, kind in [("info", "device_info"), ("protocol", "protocol")]:
                target = row.get(field + "_file", "")
                if target and (target not in records or records[target]["kind"] != kind
                               or row.get(field + "_sha256") != records[target]["sha256"]):
                    raise ValueError("configuration metadata linkage requires correct path, kind and hash")
            locations = json.loads(row.get("channel_locations") or "{}")
            if not isinstance(locations, dict) or any(k not in [str(i) for i in range(1, 9)] or not isinstance(v, str) for k, v in locations.items()):
                raise ValueError("channel_locations requires a JSON object with channel keys 1 through 8")
            leads = json.loads(row.get("channel_leads") or "{}")
            if not isinstance(leads, dict) or any(k not in [str(i) for i in range(1,9)] or not isinstance(v,str) for k,v in leads.items()):
                raise ValueError("channel_leads requires a JSON object with channel keys 1 through 8")
            configs[rel] = dict(**row, connected=connected, active=active, locations=locations, leads=leads)
    return configs


def link_export(meta, records, config):
    infos = [x for x in records if x["kind"] == "device_info"]
    protocols = [x for x in records if x["kind"] == "protocol"]
    candidates = []
    for info in infos:
        if not meta["timestamp"] or not info["timestamp"] or info["participant"] != meta["participant"] or info["visit"] != meta["visit"]:
            continue
        delta = (datetime.fromisoformat(info["timestamp"]) - datetime.fromisoformat(meta["timestamp"])).total_seconds()
        if meta["timestamp"][:10] == info["timestamp"][:10] and abs(delta) <= 3600:
            candidates.append((info, delta))
    # IMP and info share run-name and start stamp (often one second apart).
    exact = [x for x, delta in candidates if meta["export_type"] == "continuous" and meta["step"] == x["step"] and abs(delta) <= 2]
    explicit = config.get("info_file", "")
    linked = next((x for x in infos if x["source_file"] == explicit), None) if explicit else exact[0] if len(exact) == 1 else None
    status = "operator_documented" if explicit else "run_name_time_association_not_wiring_proof" if linked else "unresolved"
    protocol_candidates = [x["source_file"] for x in protocols if linked and linked.get("step_name") in x["steps"]]
    return dict(info_link_status=status, info_file=linked["source_file"] if linked else "",
                info_candidates=json.dumps([dict(source_file=x["source_file"], delta_seconds=delta) for x, delta in candidates]),
                protocol_file=config.get("protocol_file", ""),
                protocol_link_status="operator_documented" if config.get("protocol_file") else "unresolved",
                protocol_candidates=json.dumps(protocol_candidates)), linked


def historical_exports(root, available):
    """Recover exports absent from the working tree, without restoring raw files.

    Only ancestors of HEAD are consulted. A current path is not counted again for
    every historical version. Older overwritten versions are logged separately.
    """
    try:
        log = subprocess.check_output(["git", "-C", str(root), "log", "HEAD", "--format=%H", "--name-only", "--", "*.txt"],
                                      text=True, stderr=subprocess.DEVNULL)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return [], "git_history_unavailable"
    paths = sorted({x for x in log.splitlines() if x.lower().endswith(("_impval.txt", "_imp.txt"))})
    recovered = []
    for rel in paths:
        if rel in available:
            continue
        # Revisions touching the path, newest first. A deletion has no blob;
        # walking back retrieves the last extant content, without git checkout.
        commits = subprocess.check_output(["git", "-C", str(root), "log", "HEAD", "--format=%H", "--", rel], text=True).splitlines()
        for commit in commits:
            result = subprocess.run(["git", "-C", str(root), "show", f"{commit}:{rel}"], capture_output=True)
            if result.returncode == 0:
                recovered.append((rel, commit, result.stdout))
                break
        else:
            raise RuntimeError("historical impedance path has no recoverable blob: " + rel)
    return recovered, "HEAD_ancestor_missing_paths_recovered_latest_extant_blob"
