# Verification record

- Environment: macOS ARM64, Python 3.11.17; direct and transitive dependencies pinned in `requirements-validation.txt`.
- Full tests: `python -m pytest tests -q -ra` — **50 passed, 1 skipped**. Raw summary in `test_results.txt`; 14 third-party Matplotlib/Pyparsing deprecation warnings do not affect results.
- Baseline before edits: 7 passed, 1 failed. The failed test calls an obsolete SST `--test-mode` interface; the current `sst_main.py` requires PsychoPy and immediately launches a GUI. It is explicitly skipped with that reason, not reported as passing. Experimental timing/code was not altered to satisfy it.
- Actual-data smoke: `python code/validate_rhythms.py --subject 10034` completed with all ten result records.
- Batch: `python code/validate_rhythms.py` completed all 38 recordings / 95 result records, with explicit QC/input failures, and `completion.json`.
- Reproducibility: a second independent 10034 smoke run produced **exactly equal parsed JSON** for all ten scientific results compared with the batch. Only run-level provenance/output location is expected to differ.
- Provenance: source SHA-256 hashes and configuration match the committed snapshot. The run's `git_commit` is the starting main commit because analyses ran before committing; the listed source hashes identify the exact analysis files, not just that starting commit.
- Historical replay: all 11 available Bandit beta fixture values reproduced exactly. SST provenance remains unknown (4/11 all-response and 5/11 correct-go hypothesis matches).
- Visual inspection: fixture overview, response spectrum/TFR panels, and channel-QC panels checked for readable labels, clear failed-candidate status, and visible search boundaries. All figures use the same reviewed layout.
- Preservation: Git diff inspected to confirm no original EEG, behavioral data, historical report, `.neprot`, task timing script, `code/config.json`, or counterbalancing changes.
- Windows/Linux Python 3.11 tests and the actual 10034 smoke test are configured in `.github/workflows/rhythm-validation.yml`. Remote results are reported on the PR; local validation is not a claim that Avi's lab computer was tested.
