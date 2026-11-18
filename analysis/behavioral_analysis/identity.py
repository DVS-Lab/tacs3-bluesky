"""Preserve recruitment namespaces; resolve legacy identities only from evidence."""
import re
from pathlib import PurePosixPath

import pandas as pd


def participant_id(raw):
    """Remove the sub- wrapper only; preserve namespace and numeric leading zeros."""
    value = re.sub(r"^sub-", "", str(raw).strip(), flags=re.I)
    if re.fullmatch(r"[GgRr]\d+", value):
        value = value[0].upper() + value[1:]
    return value


class IdentityResolver:
    """Flat alias map, optionally scoped to an exact repository-relative file."""

    def __init__(self, path=None):
        self.path = path
        self.rows = pd.DataFrame(columns=["alias", "participant", "evidence", "source_file"])
        self.mapping = {}
        if path is None:
            return
        from .discovery import read_table
        rows, _ = read_table(path)
        if not {"alias", "participant", "evidence"}.issubset(rows):
            raise ValueError("aliases require alias, participant, evidence")
        if "source_file" not in rows:
            rows["source_file"] = ""
        rows.alias = rows.alias.map(participant_id)
        rows.participant = rows.participant.map(participant_id)
        rows.source_file = rows.source_file.str.strip()
        if rows.duplicated(["alias", "source_file"]).any():
            raise ValueError("duplicate/conflicting alias within the same source scope")
        alias_ids = set(rows.alias)
        for _, row in rows.iterrows():
            if not row.alias or not row.participant or not row.evidence.strip():
                raise ValueError("alias identities and evidence must be nonempty")
            if row.alias == row.participant or row.participant in alias_ids:
                raise ValueError("self aliases, chains and cycles are not allowed; use direct canonical targets")
            source_prefix = re.match(r"^[GR](?=\d+$)", row.alias)
            target_prefix = re.match(r"^[GR](?=\d+$)", row.participant)
            if source_prefix and (not target_prefix or source_prefix[0] != target_prefix[0]):
                raise ValueError("aliases must not strip or cross G/R namespaces")
            scope = PurePosixPath(row.source_file)
            if row.source_file and (scope.is_absolute() or ".." in scope.parts or "\\" in row.source_file):
                raise ValueError("alias source_file must be an exact repository-relative path")
            self.mapping[(row.alias, row.source_file)] = (row.participant, row.evidence)
        # A global rule and a file rule may coexist only if they agree on identity.
        for (alias, scope), (target, _) in self.mapping.items():
            global_rule = self.mapping.get((alias, ""))
            if scope and global_rule and global_rule[0] != target:
                raise ValueError("global and source-specific alias rules conflict")
        self.rows = rows[["alias", "participant", "evidence", "source_file"]].copy()

    def fields(self, raw, source_file=""):
        recorded = participant_id(raw)
        scope = source_file if source_file and (recorded, source_file) in self.mapping else ""
        rule = self.mapping.get((recorded, scope))
        canonical, evidence = rule if rule else (recorded, "")
        namespaced = bool(re.fullmatch(r"[GR]\d+", canonical))
        return dict(participant=canonical, recorded_participant=recorded,
                    participant_namespace=canonical[0] if namespaced else "legacy" if canonical.isdigit() else "other",
                    identity_status="explicit_alias" if rule else "namespace_preserved" if namespaced else "legacy_unmapped" if canonical.isdigit() else "other_id",
                    alias_evidence=evidence, alias_scope=scope if rule and scope else "global" if rule else "")

    def resolve(self, raw, source_file=""):
        return self.fields(raw, source_file)["participant"]
