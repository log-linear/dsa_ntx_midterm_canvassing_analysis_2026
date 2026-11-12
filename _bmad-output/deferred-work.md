# Deferred Work

- source_plan: `plan-streamlit-precinct-dashboard.md`
  summary: `build_data_dictionary.py`'s undocumented-field branch reads `declared = observed` before `observed` is assigned, so a field missing from both `MANUAL` and the DFS export raises `UnboundLocalError` instead of reporting the gap.
  evidence: Pre-existing, not caused by this change — the line is byte-identical at the plan's baseline revision `5b01f45` (`git show 5b01f45:build_data_dictionary.py`, line 352) and the file was touched here only for the `readable_name` label fix. The generator's `UNDOCUMENTED (fallback)` report, and the `[]` the dashboard plan's Verification expects from it, are unreachable if a field ever goes undocumented: it crashes rather than listing the gap. Settles as real if a synthetic field absent from both sources is added and `build_data_dictionary.py` is run.
