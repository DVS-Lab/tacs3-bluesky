"""Read-only orchestration and explicit diagnostic denominators."""
import json
import math
import importlib.metadata
import platform
import subprocess
from pathlib import Path

import pandas as pd

from behavioral_analysis.identity import IdentityResolver
from . import __version__
from .protocol_audit import audit, zero_amplitudes
from .core import digest, source_paths, parse_export, metadata_record, load_config, link_export, historical_exports


def save(frame, path):
    frame.to_csv(path, index=False, float_format="%.12g")


def summaries(readings):
    rows = []
    for (mode, availability, channel), group in readings.groupby(["export_type", "source_availability", "physical_channel"]):
        eligible = group[group.structurally_valid & group.category.isin([
            "exact_150000", "above_threshold_other", "positive_at_or_below_threshold"])]
        for scope in ["all_recorded_connection_unknown_or_known", "documented_connected", "documented_active"]:
            data = eligible if scope.startswith("all_") else eligible[eligible["connected" if scope.endswith("connected") else "active"].eq("yes")]
            n = len(data)
            flagged = data.category.eq("exact_150000")
            high = data.category.eq("above_threshold_other")
            rows.append(dict(export_type=mode, source_availability=availability, physical_channel=channel, denominator_scope=scope,
                             n_eligible_positive_readings=n, n_exports=int(data.export_id.nunique()),
                             n_exact_150000=int(flagged.sum()), n_above_threshold_other=int(high.sum()),
                             fraction_exact_150000=float(flagged.mean()) if n else None,
                             fraction_above_threshold_other=float(high.mean()) if n else None,
                             n_zero_all_recorded=int(group.category.eq("zero_uninterpreted").sum()),
                             n_invalid_or_negative_all_recorded=int(group.category.isin(["invalid_or_missing", "negative_invalid"]).sum()),
                             n_malformed_row_slots_all_recorded=int((~group.structurally_valid).sum())))
    return pd.DataFrame(rows)


def sequences(inventory, readings):
    """Temporal changes within ID/visit/day, without asserting identical setups."""
    rows = []
    base = inventory[inventory.export_type.eq("standalone") & inventory.timestamp.ne("") & inventory.n_rows.eq(1) & inventory.n_malformed_rows.eq(0)]
    for _, group in base.groupby(["participant", "visit", base.timestamp.str[:10]]):
        group = group.sort_values(["timestamp", "source_file"])
        previous = None
        for _, export in group.iterrows():
            data = readings[readings.export_id.eq(export.export_id)]
            if previous is not None:
                before, before_data = previous
                elapsed = (pd.Timestamp(export.timestamp) - pd.Timestamp(before.timestamp)).total_seconds()
                if elapsed > 7200 or elapsed <= 0:
                    previous = (export, data)
                    continue
                left = before_data.set_index("physical_channel")
                for _, value in data.iterrows():
                    channel = value.physical_channel
                    prior = left.loc[channel]
                    if not (prior.structurally_valid and value.structurally_valid):
                        continue
                    normal = "positive_at_or_below_threshold"
                    kind = ""
                    if prior.category == "exact_150000" and value.category == normal:
                        kind = "exact_150000_to_positive_at_or_below_threshold"
                    elif prior.category == normal and value.category == "exact_150000":
                        kind = "positive_at_or_below_threshold_to_exact_150000"
                    elif prior.category == "above_threshold_other" and value.category == normal:
                        kind = "other_high_to_positive_at_or_below_threshold"
                    if kind:
                        setup_status = "unknown_or_not_comparable"
                        if prior.setup != "unknown" and value.setup != "unknown":
                            setup_status = "same_documented_setup_label_wiring_not_proven_identical" if prior.setup == value.setup else "documented_setup_changed"
                        rows.append(dict(previous_export_id=before.export_id, export_id=export.export_id,
                                         previous_timestamp=before.timestamp, timestamp=export.timestamp,
                                         physical_channel=channel, previous_value=prior.value, value=value.value,
                                         transition=kind, elapsed_seconds=elapsed, setup_comparability=setup_status,
                                         interpretation="temporal_transition_not_proof_of_hardware_recovery"))
            previous = (export, data)
    return pd.DataFrame(rows, columns=["previous_export_id", "export_id", "previous_timestamp", "timestamp", "physical_channel",
                                      "previous_value", "value", "transition", "elapsed_seconds", "setup_comparability", "interpretation"])


def run(root, output, configuration_log=None, aliases=None, threshold=20000, figures=True):
    root, output = Path(root).resolve(), Path(output).resolve()
    if not root.is_dir():
        raise ValueError("root must be an existing repository directory")
    if not math.isfinite(threshold) or threshold <= 0 or threshold >= 150000:
        raise ValueError("threshold must be positive and below the separately flagged 150000 value")
    # Outputs may be outside root, or solely inside the package's ignored outputs.
    allowed = root / "impedance_analysis/outputs"
    if output == root or output in root.parents or (root in output.parents and allowed not in [output, *output.parents]):
        raise ValueError("output overlaps repository sources; use impedance_analysis/outputs or an external directory")
    private_inputs = {}
    for supplied in [configuration_log, aliases]:
        if supplied is not None:
            supplied = Path(supplied).resolve()
            if supplied == output or output in supplied.parents:
                raise ValueError("configuration/alias inputs must be outside the output tree")
            private_inputs[supplied] = digest(supplied)
    paths = source_paths(root)
    exports = [p for p in paths if p.name.lower().endswith(("_impval.txt", "_imp.txt"))]
    metadata_paths = [p for p in paths if p.suffix.lower() in {".info", ".neprot"}]
    protected = exports + metadata_paths + [p for p in paths if p.relative_to(root).parts[0] == "code"]
    before = {p.relative_to(root).as_posix(): digest(p) for p in protected}
    private = output / "private"
    share = output / "share"
    private.mkdir(parents=True, exist_ok=True)
    share.mkdir(parents=True, exist_ok=True)
    identities = IdentityResolver(aliases)
    metadata = [metadata_record(p, root, identities) for p in metadata_paths]
    inventory, readings, errors = [], [], []
    for path in exports:
        meta, values, malformed = parse_export(path, root, threshold, identities)
        meta.update(source_availability="working_tree", historical_commit="")
        for row in values:
            row["source_availability"] = "working_tree"
        inventory.append(meta)
        readings.extend(values)
        errors.extend(malformed)
    recovered, history_status = historical_exports(root, {x["source_file"] for x in inventory})
    for rel, commit, data in recovered:
        meta, values, malformed = parse_export(root / rel, root, threshold, identities, data=data)
        meta.update(source_availability="git_history_only", historical_commit=commit)
        for row in values:
            row["source_availability"] = "git_history_only"
        inventory.append(meta)
        readings.extend(values)
        errors.extend(malformed)
    if not inventory:
        raise ValueError("no impedance exports found")
    configs = load_config(configuration_log, inventory, metadata)
    rows_by_export = {}
    for row in readings:
        rows_by_export.setdefault(row["export_id"], []).append(row)
    for export in inventory:
        config = configs.get(export["source_file"], {})
        links, info = link_export(export, metadata, config)
        export.update(links, setup=config.get("setup", "unknown"), configuration_evidence=config.get("evidence", ""))
        export.update(nic_version=info.get("nic_version", "") if info else "",
                      firmware=info.get("firmware", "") if info else "")
        for row in rows_by_export.get(export["export_id"], []):
            ch = row["physical_channel"]
            channel_info = info["channels"].get(str(ch), {}) if info else {}
            row.update(programmed_location=channel_info.get("location", ""),
                       documented_physical_location=config.get("locations", {}).get(str(ch), ""),
                       documented_physical_lead=config.get("leads", {}).get(str(ch), ""),
                       channel_index_basis="export_column_1_to_8_device_mapping_to_confirm",
                       configured_zero_amplitudes={True:"yes",False:"no",None:"unknown"}[zero_amplitudes(channel_info)],
                       measurement_context=("standalone_check_mode_unverified" if export["export_type"]=="standalone" else
                           "continuous_impedance_named_record" if export.get("step")=="Impedance Check Only" else "continuous_recording_export"),
                       setup=export["setup"],
                       connected="unknown" if config.get("connected") is None else "yes" if ch in config["connected"] else "no",
                       active="unknown" if config.get("active") is None else "yes" if ch in config["active"] else "no",
                       location=config.get("locations", {}).get(str(ch), channel_info.get("location", "")),
                       location_evidence="operator_documented" if str(ch) in config.get("locations", {}) else links["info_link_status"],
                       configured_role=channel_info.get("configured_role", ""),
                       info_link_status=links["info_link_status"], nic_version=export["nic_version"], firmware=export["firmware"])
    inv = pd.DataFrame(inventory)
    inv["identical_content_export_count"] = inv.groupby("sha256").sha256.transform("size")
    values = pd.DataFrame(readings)
    # Empty or malformed-only datasets still retain inventory, errors and report.
    if values.empty:
        values = pd.DataFrame(columns=["export_id", "export_type", "source_availability", "physical_channel", "row_number", "timestamp", "sample_utc", "epoch_ms", "raw_token", "value", "category", "structurally_valid", "row_issues", "setup", "connected", "active", "location", "location_evidence", "configured_role", "info_link_status", "nic_version", "firmware", "programmed_location", "documented_physical_location", "documented_physical_lead", "channel_index_basis", "configured_zero_amplitudes", "measurement_context"])
    summary = summaries(values)
    changes = sequences(inv, values)
    pattern_rows = []
    for export_id, group in values[values.export_type.eq("standalone")].groupby("export_id"):
        valid = group[group.structurally_valid & group.value.between(3500, 4500)]
        if len(valid) >= 2:
            pattern_rows.append(dict(export_id=export_id, timestamp=group.timestamp.iloc[0],
                                     n_channels_3500_4500=len(valid), physical_channels=";".join(map(str, valid.physical_channel)),
                                     setup=group.setup.iloc[0], interpretation="testboard_like_hypothesis_only_configuration_not_inferred"))
    patterns = pd.DataFrame(pattern_rows, columns=["export_id", "timestamp", "n_channels_3500_4500", "physical_channels", "setup", "interpretation"])
    save(inv, private / "inventory.csv")
    save(values, private / "readings.csv")
    save(pd.DataFrame(errors, columns=["export_id", "row_number", "issues", "raw_line"]), private / "parse_errors.csv")
    (private / "metadata_inventory.json").write_text(json.dumps(metadata, indent=2))
    # Blank, hash-bound private template for every export. No setup is filled by inference.
    template = inv[["source_file", "sha256"]].copy()
    template["setup"] = "unknown"
    for name in ["connected_channels", "active_channels", "evidence", "info_file", "info_sha256", "protocol_file", "protocol_sha256", "channel_locations", "channel_leads"]:
        template[name] = ""
    save(template, private / "configuration_log_template.csv")
    public_columns = ["export_id", "export_type", "source_availability", "timestamp", "timestamp_basis", "n_rows", "n_malformed_rows", "file_issues", "setup", "nic_version", "firmware", "info_link_status", "protocol_link_status", "sha256", "identical_content_export_count"]
    save(inv[public_columns], share / "exports.csv")
    save(values.drop(columns=["raw_token", "row_issues", "location", "location_evidence", "configured_role", "programmed_location", "documented_physical_location", "documented_physical_lead"]), share / "readings.csv")
    save(pd.DataFrame(errors, columns=["export_id", "row_number", "issues"]), share / "parse_errors.csv")
    save(summary, share / "channel_summary.csv")
    save(changes, share / "suspicious_sequences.csv")
    save(patterns, share / "pattern_hypotheses.csv")
    protocol_audit = audit(root, metadata, inv, values, private, share)
    if private_inputs != {p: digest(p) for p in private_inputs}:
        raise RuntimeError("private input hash changed during analysis")
    if before != {p.relative_to(root).as_posix(): digest(p) for p in protected}:
        raise RuntimeError("source hash changed during analysis")
    # Detect addition/deletion of raw input files as well as changed bytes.
    after_paths = source_paths(root)
    after_relevant = {p.relative_to(root).as_posix() for p in after_paths if p.name.lower().endswith(("_impval.txt", "_imp.txt")) or p.suffix.lower() in {".info", ".neprot"} or p.relative_to(root).parts[0] == "code"}
    if set(before) != after_relevant:
        raise RuntimeError("source inventory changed during analysis")
    try:
        revision = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        revision = "unavailable"
    provenance = dict(analysis_code_hashes={p.name: digest(p) for p in Path(__file__).parent.glob("*.py")},
                      dependencies={name: importlib.metadata.version(name) for name in ["numpy", "pandas", "matplotlib"]},
                      version=__version__, git_revision=revision, python=platform.python_version(), source_integrity_verified=True,
                      threshold=threshold, exact_value_category=150000, testboard_hypothesis_interval=[3500, 4500],
                      configuration_log_sha256=digest(configuration_log) if configuration_log else None,
                      alias_log_sha256=digest(aliases) if aliases else None, protected_source_hashes=before,
                      git_history_status=history_status, recovered_blob_hashes={x["source_file"]: x["sha256"] for x in inventory if x["source_availability"] == "git_history_only"},
                      inventory_scope="recursive repository except .git, outputs, local, virtualenv and cache directories; no symlinks")
    (private / "provenance.json").write_text(json.dumps(provenance, indent=2))
    result = dict(n_exports=len(inv), n_standalone_exports=int(inv.export_type.eq("standalone").sum()),
                  n_continuous_exports=int(inv.export_type.eq("continuous").sum()),
                  n_working_tree_standalone_exports=int((inv.export_type.eq("standalone") & inv.source_availability.eq("working_tree")).sum()),
                  n_history_only_exports=int(inv.source_availability.eq("git_history_only").sum()), git_history_status=history_status,
                  n_malformed_rows=len(errors), n_files_with_issues=int((inv.file_issues.ne("") | inv.n_malformed_rows.gt(0)).sum()),
                  n_channel_readings=len(values), n_documented_configuration_exports=len(configs),
                  n_metadata_records=len(metadata), n_metadata_parse_issues=sum(bool(x["parse_issue"]) for x in metadata),
                  source_integrity_verified=True)
    (share / "summary.json").write_text(json.dumps(result, indent=2))
    from .report import build_report
    build_report(share, inv, values, summary, changes, patterns, result, threshold, figures, protocol_audit)
    return result
