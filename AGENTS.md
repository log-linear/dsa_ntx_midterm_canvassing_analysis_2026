<!-- bmad:context -->
<!-- Verified 2026-11-25 against 59821df. Managed by bmad-project-context; edits inside this block are replaced on refresh. Keep anything you want preserved outside the markers. -->

## dsa_electoral_research

Precinct-level canvassing, election, and demographic analysis for Dallas County: two build scripts under `src/` produce a research table that a Streamlit choropleth reads. Python 3.12, uv, stdlib-heavy. There is no CI, linter, formatter, typecheck config, or git hook — the checks named below are the only ones that exist. The edge-case matrix and defect history live in `_bmad-output/plan-streamlit-precinct-dashboard.md`.

## Policy

- Never commit unless the user explicitly asks. Never `git add -A`: `scratch/`, `data/raw/precinct_district_comb.csv` and the untracked `_bmad-output/plan-*.md` are untracked but not gitignored, so `-A` sweeps them. Stage paths by name.
- Never modify an existing file in `data/raw/` — they are the research record. New raw files get added only when the user supplies new data. `data/precinct_data.csv` and `data/data_dictionary.csv` are the only writable outputs.
- Never hand-edit `data/data_dictionary.csv`; regenerate it with `src/build_data_dictionary.py`, or the next build silently overwrites your edit.
- Never add `requirements.txt` — the Streamlit Cloud deploy works from `pyproject.toml` + `uv.lock` as they are, and a requirements file changes what the deploy installs.

## Where things are

- `src/settings.py` — every constant, and the only place that anchors paths (`REPO_ROOT = parents[1]`). `src/utils/data_layer.py` — pure transforms, no `import streamlit`. `src/utils/streamlit.py` — render/HTML/pydeck helpers. `src/dashboard.py` — `main()` + the three `_cached_*` bindings only.
- The deployed app's main script must be set to `src/dashboard.py` in Streamlit Cloud; the repo has no root-level entrypoint shim.

## Running and verifying

- `uv run python tests/test_dashboard.py`, from the repo root. `uv run pytest` escapes to `/usr/bin/pytest` on system Python; the file has no `def test_*` functions, so pytest collects 0 either way. Read the `PASS` lines.
- It aborts at `tests/test_dashboard.py:454` (tooltip line-count vs the deliberately-empty `TOOLTIP_FIELDS`) **before** any network call, so it runs offline in ~0.3 s and the live-FeatureServer asserts below it (`:505`, 791 polygons) never execute. That abort is expected — do not "fix" `TOOLTIP_FIELDS` or delete the assertion to reach green.
- The caption assertions at `:2527-2533` sit below that abort and check captions `src/dashboard.py:79-84,183-196` comments out as placeholders. Do not re-add the captions, and do not delete the assertions unilaterally.
- `uv run streamlit run src/dashboard.py` is the only way to see the app. `python src/dashboard.py` exits 0 while rendering nothing but `missing ScriptRunContext` warnings — a zero exit code proves nothing ran.
- Rebuild in order: `src/build_precinct_data.py && src/build_data_dictionary.py`. The dictionary reads the precinct CSV and exits 0 on stale input; nothing checks the order.
- Copy both `data/*.csv` aside before any rebuild. Each opens its output with `"w"`, no flags and no dry-run, and a missing `.ods` is a silent empty glob (`src/settings.py:353`) that yields a well-formed, mostly-empty file over committed data — and that glob now runs on `import settings`, i.e. when the dashboard imports.

## Conventions that differ from defaults

- Read constants attribute-style (`settings.TOOLTIP_FIELDS`), never `from settings import X`: the suite rebinds them and a copied name makes the check pass vacuously. The builders' `OUT`/`IN_CSV` module globals are the deliberate exception — `main()` reads them at call time and that is the suite's rebind surface.
- Guard shipped behaviour in `tests/`, not with module-level `assert`s in `src/` (there are none). But a guard must sit **above** the `:454` abort to be live — one that only runs below it enforces nothing.
- Field labels and descriptions are authored in `src/build_data_dictionary.py` (`MANUAL`, then `READABLE_OVERRIDES`) and regenerated; `src/dashboard.py` holds none of them (only widget chrome like `"Colour precincts by"`). To change what the UI says about a field, edit the generator, never the CSV or the app.
- Descriptions are plain definitions: no formula prose, no typed-in row counts. `reconcile()` owns every count.
- Shares are fractions in 0-1 throughout, including `2024_prop_r_for` and `2024_prop_u_against` — result shares, not vote counts.
- One row is one precinct, but its demographic columns describe the surviving census VTD, not the precinct: the DFS export's smallest geography is the VTD. Never sum `share_of_county_precinct` expecting 1.0.
- The two "No" measures are not interchangeable and not the same rows: `prop_a_city_no_canvassing_pct` = `strong_no / response_count` (22 of 820) and `response_count` (24 of 820). Never "simplify" the first back to `strong_no / canvass_attempts` — a low response rate then reads as a friendly precinct (2082: 0.18, now 0.71). Blank means the input was never recorded; `response_count` reading `0` for 4073 and 2150 while their share is blank is a finding, not missing data. (`prop_a_city_no_actual_pct` was retired in `374c0fd`.)

## Known pitfalls

- pydeck string layer props are parsed as `@deck.gl/json` expressions, never run as JavaScript — no arrow functions, no `{token}` templates. Tooltips belong on `Deck(tooltip=...)`, not on the layer; a layer-level tooltip serialises fine and shows nothing while the map looks flawless.
- Assert the rendered payload and the channel, not the existence of a string. Four defects shipped from checks that proved a Python string was built where the browser never read it (`fc08df5`, `7af094d`, `e081298`).
- 22 District 2 rows were authored one column left of their headers and `choose_shift()` repairs them per row from ODF `value-type` — a cell displaying `56.72%` and a raw count are both `float`, so display text proves nothing. Leave that logic alone, keep the values those rows never recorded blank rather than inferring them, and use `sheet_column_alignment` as the audit flag.

<!-- /bmad:context -->
