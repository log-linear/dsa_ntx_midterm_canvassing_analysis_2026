<!-- bmad:context -->
<!-- Verified 2026-11-15 against fbc8b2c. Managed by bmad-project-context; edits inside this block are replaced on refresh. Keep anything you want preserved outside the markers. -->

## dsa_electoral_research

Precinct-level canvassing, election, and demographic analysis for Dallas County: two build scripts produce a research table that a Streamlit choropleth reads. Python 3.12, uv, stdlib-heavy. There is no CI, linter, formatter, typecheck config, or git hook — the checks named below are the only ones that exist. The edge-case matrix and defect history live in `_bmad-output/plan-streamlit-precinct-dashboard.md`.

## Policy

- Never commit unless the user explicitly asks. Never `git add -A`: `scratch/` and `data/raw/precinct_comb.csv` + `precinct_district_comb.csv` are untracked but not gitignored, so `-A` sweeps them. Stage paths by name.
- Never modify an existing file in `data/raw/` — they are the research record. New raw files get added only when the user supplies new data. `data/precinct_data.csv` and `data/data_dictionary.csv` are the only writable outputs.
- Never hand-edit `data/data_dictionary.csv`; regenerate it with `build_data_dictionary.py`, or the next build silently overwrites your edit.
- Never add `requirements.txt` — the Streamlit Cloud deploy works from `pyproject.toml` + `uv.lock` as they are, and a requirements file changes what the deploy installs.

## Running and verifying

- `uv run python tests/test_dashboard.py`, from the repo root, ~4 s. It needs network: `:300` queries the live FeatureServer and asserts 791 polygons. pytest is not installed and `uv run pytest` escapes to `/usr/bin/pytest` on system Python; the file has no `def test_*` functions, so pytest collects 0 either way. Read the `PASS` lines.
- The suite ends in a known failure at `tests/test_dashboard.py:514`, asserting captions that `dashboard.py:667-682` comments out deliberately as placeholders. Do not re-add the captions to get green, and do not delete the assertions unilaterally.
- `uv run streamlit run dashboard.py` is the only way to see the app. `python dashboard.py` exits 0 while rendering nothing but `missing ScriptRunContext` warnings — a zero exit code proves nothing ran.
- Rebuild in order: `build_precinct_data.py && build_data_dictionary.py`. The dictionary reads the precinct CSV and exits 0 on stale input; nothing checks the order.
- Copy both `data/*.csv` aside before any rebuild. Each opens its output with `"w"`, no flags and no dry-run, and a missing `.ods` is a silent empty glob (`build_precinct_data.py:76`) that yields a well-formed, mostly-empty file over committed data.

## Conventions that differ from defaults

- Field labels and descriptions are authored in `build_data_dictionary.py` (`MANUAL`, then `READABLE_OVERRIDES`) and regenerated; `dashboard.py` holds zero label literals. To change what the UI says, edit the generator, never the CSV or the app.
- Descriptions are plain definitions: no formula prose, no typed-in row counts. `reconcile()` owns every count.
- Shares are fractions in 0-1 throughout, including `2024_prop_r_for` and `2024_prop_u_against` — result shares, not vote counts.
- One row is one precinct, but its demographic columns describe the surviving census VTD, not the precinct: the DFS export's smallest geography is the VTD. Never sum `share_of_county_precinct` expecting 1.0.
- The three "No" measures are not interchangeable and not the same rows: `prop_a_city_no_canvassing_pct` = `strong_no / response_count` (22 of 85), `response_count` (24 of 85), `prop_a_city_no_actual_pct` = Against ÷ ballots cast (84 of 85, precinct 1046 the gap). Never "simplify" the first back to `strong_no / canvass_attempts` — a low response rate then reads as a friendly precinct (2082: 0.18, now 0.71). Blank means the input was never recorded; `response_count` reading `0` for 4073 and 2150 while their share is blank is a finding, not missing data.

## Known pitfalls

- pydeck string layer props are parsed as `@deck.gl/json` expressions, never run as JavaScript — no arrow functions, no `{token}` templates. Tooltips belong on `Deck(tooltip=...)`, not on the layer; a layer-level tooltip serialises fine and shows nothing while the map looks flawless.
- Assert the rendered payload and the channel, not the existence of a string. Four defects shipped from checks that proved a Python string was built where the browser never read it (`fc08df5`, `7af094d`, `e081298`).
- 22 District 2 rows were authored one column left of their headers and `choose_shift()` repairs them per row from ODF `value-type` — a cell displaying `56.72%` and a raw count are both `float`, so display text proves nothing. Leave that logic alone, keep the values those rows never recorded blank rather than inferring them, and use `sheet_column_alignment` as the audit flag.

<!-- /bmad:context -->
