# Recruitment namespaces and legacy aliases

G/R prefixes are an intentional recruitment namespace, not an acquisition error:
`G10034` identifies the G25 source, while `R10034` can identify a different person
from RF1. Avi's explanation of the migration establishes this policy. Matching
bare numeric suffixes alone do not establish an individual identity or enrollment.

The analysis preserves these prefixes and all numeric leading zeros. It removes
the BIDS-style `sub-` wrapper/outer whitespace, and standardizes a lowercase g/r
before digits to uppercase. Thus `sub-g010034` becomes `G010034`, not `10034`.
Other strings retain their spelling. Acquisition/data files are never renamed.

## Explicit mapping

Use the private header-only template `templates/aliases.example.csv` to create
`behavioral_analysis/local/aliases.csv`. Required columns:

| Column | Meaning |
|---|---|
| `alias` | Exact legacy/formatted ID as recorded, including significant zeros |
| `participant` | Canonical participant string established by the private roster |
| `evidence` | Nonempty source/reference supporting the identity link |
| `source_file` | Optional exact repository-relative file path; blank applies globally |

Synthetic example only (not a mapping for any enrolled participant):

```csv
alias,participant,evidence,source_file
19999,G19999,Example roster review reference,
```

Apply explicitly from the repository root:

```sh
python -m behavioral_analysis --aliases behavioral_analysis/local/aliases.csv
```

No alias is inferred from the presence of a G/R file, the participant's frequency,
the generator branch, or similar filenames. No private mapping is bundled or
automatically loaded. Without `--aliases`, bare legacy IDs remain bare and separate
from G/R IDs. Do not interpret the number of unmatched ID strings as a verified
unique-person count.

For shared legacy numbers, specify one rule per exact source file, for example
`19999 -> G19999` for a confirmed G25 source and `19999 -> R19999` for a different
confirmed RF1 source. These rules affect only those named files, not every file
with that number. There are no glob patterns. Supply canonical IDs in a private
roster/condition key when a legacy number is ambiguous across files; scoped aliases
do not guess which identity a separate roster/key row represents.

The resolver rejects duplicate/conflicting rules, missing evidence, self mappings,
chains/cycles, absolute/traversal paths, and conflicting global versus scoped rules.
It also rejects G-to-R/R-to-G links and removal of an existing G/R namespace. Multiple
documented legacy aliases may point directly to one canonical identity. Mapping
leading-zero variants requires an explicit rule too; they are not stripped silently.

## Coverage and audit

The same resolver runs **before** filename/body identity validation, recording
selection, pooling and metadata joins. It applies to behavioral filenames/body IDs,
historical frequency reports, generated protocols, device `.info` identities,
private recruitment rosters and condition keys. Equal trial content cannot
deduplicate two different namespaces. Duplicate roster/key rows created by alias
resolution are rejected rather than arbitrarily collapsed.

`manifest.csv` records the filename's `raw_participant`, formatting-only
`recorded_participant`, resolved `participant`, namespace, resolution status,
alias evidence/scope and JSON `body_identity_resolution`. Frequency/device/protocol
tables retain the corresponding original and resolved identities too.
`identity_resolution.csv` provides a compact per-file review table;
`identity_aliases.csv` records the rules actually supplied. Both are ignored derived
outputs. `provenance.json` includes the alias-file SHA-256 and identity-policy label.
Keep the private map and identifying evidence out of Git.

## Cohorts and the protocol investigation

Namespace does not establish enrollment. Pilot-folder provenance remains pilot;
the existing five-digit study-ID heuristic now recognizes both namespaced and
bare versions as experimental candidates, while other namespaced numeric IDs are
unverified rather than labeled test merely for containing a letter. A documented
roster takes precedence over this heuristic.

The 11450/G11450 investigation concerns which report, generator selection and
protocol were used during an ID migration. It is not an argument against the G
prefix. A later regeneration is a plausible explanation for extra protocol files;
the actual assignment and execution still need original records. The NIC sham
encoding/runtime question is independent of identity naming.
