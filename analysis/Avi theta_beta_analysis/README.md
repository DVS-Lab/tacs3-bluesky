# Historical exploratory theta/beta analysis

`frequency_analysis.py` produced the batch CSVs reviewed in the November 17 presentation. Its forced band extrema are descriptive candidates, not reliability-qualified individualized frequencies. Changing the feedback window alone is not a reliability test.

For input validation, explicit artifact diagnostics, and frequency acceptance checks, follow [the offline audit and script codebook](../../docs/artifact_reliability_audit.md). `code/validate_rhythms.py` produces `qc_summary.csv` in a new ignored output directory. Existing batch CSVs and raw data are preserved.
