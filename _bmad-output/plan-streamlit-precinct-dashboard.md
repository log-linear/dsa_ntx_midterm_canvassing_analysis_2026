---
title: 'Streamlit precinct choropleth dashboard'
type: feature
ticket: ''
created: '2026-11-10'
status: built
baseline_revision: '5b01f45'
route: full
route_source: auto
risk: medium
review: quick
review_source: pinned
lenses_ran: [quick]
review_loop_iteration: 0
context:
  - '{project-root}/data/precinct_data.csv'
  - '{project-root}/data/data_dictionary.csv'
  - '{project-root}/pyproject.toml'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The precinct research in `data/precinct_data.csv` is only inspectable as a flat 85-row, 89-column CSV. Organisers cannot see where canvass-based "no" share, response rate, and 2024 vote shares are geographically concentrated, or read a precinct's demographics alongside those numbers.

**Approach:** A single Streamlit app that draws the county's 2026 election precincts as a pydeck choropleth, joins the CSV onto each polygon, and turns a clicked precinct into a demographic detail panel. Labels come from `data_dictionary.csv`.

## Boundaries & Constraints

**Always:**
- Use the live ArcGIS FeatureServer REST endpoint for layer `2026 Election Precincts (Current)`; request `f=geojson` so geometry arrives as WGS84 lon/lat (the layer's native `wkid 103159` is Texas South in feet — never reproject client-side).
- Join on `NewPrcnt` ↔ `dallas_county_precinct_number`.
- Choropleth field is user-selectable across exactly these five, default `prop_a_city_no_canvassing_pct`: `2024_prop_r_for`, `2024_prop_u_against`, `2024_kamala`, `response_rate`.
- Every precinct tooltip shows **all five** fields with values, whichever one is selected for color.
- Clicking a polygon populates a second view with exactly these 26 fields: `median_age`, `median_household_income`, `not_us_citizen`, `pct_age_18_64`, `pct_age_20_39`, `pct_bachelors_plus`, `pct_below_poverty`, `pct_english_only`, `pct_family_households`, `pct_female`, `pct_hispanic`, `pct_households_snap`, `pct_hs_or_less`, `pct_income_under_50k`, `pct_married_couple_households`, `pct_multi_unit`, `pct_nh_asian`, `pct_nh_black`, `pct_nh_other`, `pct_nh_white`, `pct_owner_occupied`, `pct_single_unit`, `pct_spanish`, `pct_us_born`, `pct_vacant`, `population_per_sq_mi` — narrowed by Decision 1c below to the 17 that carry data.
- Display `readable_name` from `data_dictionary.csv` for every metric, never the raw field name.
- Disable built-in Streamlit telemetry in a committed config file.
- Distinguish blank from zero: `""` is no data; `0.0000` is a real value.

**Decisions from the human (2026-11-11):**
- **Fan-out is resolved at the source.** `precinct_data.csv` was deduplicated to one row per precinct (85 rows, 85 unique keys), so no row-picking rule is needed.
- **Fix labels at the root, in the generator.** `readable_name` values must be corrected in `build_data_dictionary.py` and the dictionary regenerated — not patched in the display layer and not hand-edited into the CSV (it is generated, so edits are clobbered). Rule: title-case, and expand the source's machine-mangled abbreviations — `pct`→`Percent`, `nh`→`Non-Hispanic`, `us`→`U.S.`, `snap`→`SNAP`, `50k`→`$50k`, `sq_mi`→`Square Mile`, `bachelors_plus`→`Bachelor's or Higher`. Examples: `'Pct age 18 64'`→`'Percent Age 18–64'`, `'Not us citizen'`→`'Not U.S. Citizen'`, `'Pct households snap'`→`'Percent Households on SNAP'`.
- **Basemap: free MapLibre, no key.** Use `map_provider="maplibre"` with a public CARTO style URL.
- **pandas is allowed** where it makes the code more parsimonious.
- **1c — the detail panel omits no-data fields.** The 9 fields blank in every row
  (`median_age`, `median_household_income`, `not_us_citizen`, `pct_below_poverty`,
  `pct_english_only`, `pct_households_snap`, `pct_spanish`, `pct_us_born`,
  `population_per_sq_mi`) are omitted from the detail view entirely, not rendered as `—`.
  Omitting them supersedes the 26-field list above: the panel shows the 17 populated fields.
- **2b — the label fix covers the whole dictionary.** Correct every mangled `readable_name`
  in `build_data_dictionary.py`, not just the fields this dashboard displays; the dictionary is
  shared metadata and half-fixed labels would leak into future tools.

**Never:**
- Do not modify `data/precinct_data.csv` or anything under `data/raw/` (upstream sources). `build_data_dictionary.py` and `data_dictionary.csv` may change only for the label fix above; no other edits.
- No new HTTP or geometry dependency: stdlib `urllib.request` + `csv` for I/O, plus `pandas`, `streamlit`, `pydeck`.
- No scraping the ArcGIS Instant Apps HTML; no database, no JS framework, no `st.map`/Altair for the map.
- Do not aggregate or average numeric values across rows.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Default load | App start, no interaction | Choropleth colored by `prop_a_city_no_canvassing_pct`; 24 of 791 polygons colored, rest grey; coverage stated in a caption | — |
| Switch field | User picks `2024_kamala` | Colors re-scale to that field's own range; tooltips unchanged (still all five) | — |
| Hover a precinct with no CSV row | 707 of 791 polygons | Grey polygon; tooltip lists all five labels with `—` | — |
| Blank vs zero | `0.0000` vs `""` | `0.0000` colored at scale minimum; `""` grey "no data" | — |
| Precinct in CSV, absent from layer | `1046` | Excluded from map; reported by count and id in a caption | Note, not error |
| Click polygon | Selection carries `NewPrcnt` | Detail view renders the 26 labeled fields | — |
| Click non-CSV polygon | `NewPrcnt` unmatched | Detail view states no data for that precinct | No traceback |
| No-data detail fields | The 9 fields blank in every row | Omitted from the detail panel entirely (Decision 1c), never rendered as `—` | — |
| No selection yet | Fresh session | Prompt to click a precinct; no empty table | — |
| Layer unreachable | Endpoint offline/5xx | `st.error` naming the URL; joined-field UI still renders | Graceful |
| Missing dictionary entry | Field absent from `data_dictionary.csv` | Fail fast naming the field | — |

</frozen-after-approval>

## Code Map

- `data/precinct_data.csv` — 85 rows (deduplicated: `dallas_county_precinct_number` is unique), 89 cols. All 5 choropleth + 26 detail fields present as **strings**; blank is `""`. Fields starting with a digit (`2024_kamala`) are dict/DataFrame keys, never identifiers.
- `data/data_dictionary.csv` — cols `field_name,data_type,description,readable_name`; 89 entries, covers every field needed. **Generated file**: committed content == output of `build_data_dictionary.py` for all 89 fields, so regenerating is a no-op until the labels are intentionally changed.
- `build_data_dictionary.py` — the label source. 58 fields take `label` from `data/raw/dfs-export-precinct-20261108/dictionary.csv` (these are the ugly ones: `'Pct nh white'`); 31 are hand-authored in its `MANUAL` table with good labels. Its `readable_from_name()` fallback already title-cases. Apply the fix as a label override consumed after label selection, so the read-only DFS export is untouched. The 5 choropleth labels are already correct.
- GIS layer (verified live) — `https://services3.arcgis.com/zqe2kwz79KUqUvxC/arcgis/rest/services/2025_Proposed_Election_Precincts_791/FeatureServer/0/query?where=1=1&outFields=*&returnGeometry=true&f=geojson` → 4.6 MB, 791 `Polygon` features, one ring each, `NewPrcnt` unique and non-blank on all 791, `maxRecordCount` 2000 so **one request needs no pagination**; warm fetch ~0.15 s. 84/85 CSV precincts match.
- Per-field populated coverage on the 791 polygons — `prop_a_city_no_canvassing_pct` 24, `2024_prop_r_for` 63, `2024_prop_u_against` 63, `2024_kamala` 84, `response_rate` 25.
- Blank detail fields: `median_age`, `median_household_income`, `not_us_citizen`, `pct_below_poverty`, `pct_english_only`, `pct_households_snap`, `pct_spanish`, `pct_us_born`, `population_per_sq_mi` have **no value in any row**, and are likewise empty (0/796) in the DFS source export — this app cannot populate them. The other 17 are populated in all 85 rows.
- API facts (verified by running streamlit 1.67.0 / pydeck 0.9.3):
  - `pdk.Layer("PolygonLayer", data=<list of records>, id="<layer_id>", get_polygon="__rings", get_fill_color="__color", get_line_color=[..], pickable=True, auto_highlight=True, tooltip="<expression>")` → serializes to `getPolygon`/`getFillColor`/`@@type: PolygonLayer`.
  - **CORRECTED 2026-11-12 — the `@@=` prefix does NOT mark a JS string.** pydeck prefixes *every* string layer prop with `@@=` (`bindings/layer.py:99-101`), and `@deck.gl/json` then **parses** it with a restricted expression grammar: quoted literals, record-key lookups, `+`, ternary, arithmetic, array literals. It does **not** evaluate JavaScript. `d => d.properties.__color` throws `Unexpected "=" at character 2` in the browser and `{token}` templates throw `Unexpected "{"` — both at render time, **invisible to every Python-side check, including `Deck.to_json()`**. Reproduce with `new JSONConverter().convert({'@@type':'PolygonLayer', getFillColor:'@@=' + expr})`.
  - **CORRECTED: a FeatureCollection dict is NOT usable as `data`.** Pass a **list of records** — polygon rings under `__rings`, per-feature attributes promoted to top-level keys on each record. Accessors then name record keys (`__color`), never `d.properties.x`.
  - Per-feature colors are a plain key on each record; a fixed `[r,g,b]` colors every polygon identically.
  - The tooltip is an expression, so labels interpolate in **Python** and only values are looked up per record: `"Precinct " + NewPrcnt + '\n' + "Prop R (For): " + v_2024_prop_r_for`. It lands in `innerText`, where `\n` renders as a line break.
  - `st.pydeck_chart(deck, on_select="rerun", selection_mode="single-object", key=..., width="stretch", height=...)` returns `PydeckState`; clicked attributes are at `.selection.objects["<layer_id>"]` — a list of the feature's GeoJSON `properties` dicts. **`Layer(id=...)` is required** or selection state is unkeyed. `use_container_width` is superseded by `width="stretch"`.
  - Basemap: `map_provider="maplibre"` + a style **URL string** serializes cleanly (`mapStyle` = URL). A `dict` style raises `AssertionError: The map_provider parameter must be 'mapbox' when map_style is provided as a dict.` CARTO Positron `https://basemaps.cartocdn.com/gl/positron-gl-style/style.json` returns HTTP 200 keyless.
  - Telemetry: `browser.gatherUsageStats` (default `True`); env `STREAMLIT_BROWSER_GATHER_USAGE_STATS`; settable in `.streamlit/config.toml`.
- `dashboard.py`, `.streamlit/config.toml`, `tests/` — do not exist yet.

## Tasks & Acceptance

**Execution:**
- [x] `build_data_dictionary.py` -- add a readable-name override covering every mangled label (58 fields inherit them from the DFS export), then run it to regenerate `data/data_dictionary.csv` -- root fix; a display-layer patch would be clobbered by the next generation
- [x] `dashboard.py` -- create: pure data functions (`fetch_features`, `load_rows`, `build_dictionary`, `join_precincts`, `color_scale`, `tooltip_expression`) importable without Streamlit, then the UI (sidebar `st.selectbox` of the 5 readable labels, `st.pydeck_chart`, detail view) -- keeping prep pure makes the edge matrix testable. Renamed from `tooltip_html` on 2026-11-12: it emits a @deck.gl/json expression, not HTML.
- [x] `.streamlit/config.toml` -- create `[browser] gatherUsageStats = false` -- satisfies telemetry at launch rather than via an overridable runtime `set_option`
- [x] `pyproject.toml` -- add `streamlit>=1.67`, `pydeck`, `pandas` -- declared so `uv run` works on a fresh clone
- [x] `tests/test_dashboard.py` -- assert each checkable Matrix row: join cardinality 84 and `1046` absent from layer, blank≠zero, all 5 choropleth fields present in every tooltip incl. for a data-less precinct, all 17 displayed detail fields resolve to corrected labels, the 9 no-data fields are absent from the panel, `Layer(id=...)` == the selection key, regenerated labels contain no `Pct `/` nh `/` us ` artifacts -- protects semantics a choropleth gets silently wrong

**Acceptance Criteria:**
- Given a fresh `uv run streamlit run dashboard.py`, when the map renders, then all 791 polygons are drawn over a basemap, exactly 84 carry CSV data, and color is `prop_a_city_no_canvassing_pct`.
- Given any selected color field, when hovering any polygon, then all five choropleth metrics appear with their `readable_name` labels.
- Given a polygon click, then a second view shows the 17 populated metrics by `readable_name`, omits the 9 with no data anywhere, and no raw field name appears in the UI.
- Given the committed config, then `streamlit config show` reports `gatherUsageStats` as `false`.
- Given no network, then the app starts and shows one clear error, not a traceback.
- Given `build_data_dictionary.py` re-run after these edits, then `data_dictionary.csv` is byte-stable and its 26 labels are the corrected ones.

## Implementation Notes

- `dashboard.py` splits a pure data layer (`fetch_features`, `load_rows`, `build_dictionary`, `label_for`, `to_float`, `format_value`, `domain_for`, `color_scale`, `tooltip_expression`, `join_index`, `join_precincts`, `layer_keys`, `detail_panel_fields`, `bbox`, `decorate`, `detail_records`, `build_deck`, `selected_props`) from the Streamlit UI. `streamlit` is imported at the top as a normal dependency and `main()` runs only under `__main__`, so `import dashboard` works with no run context. (The earlier lazy `try: import streamlit / st = None` dance is gone: it typed `st` as `Optional[Module]` and produced ~18 "not a known attribute of None" errors for a condition that never occurs — streamlit is a declared dependency.)
- `decorate()` returns a **list of pydeck records**, not a FeatureCollection: polygon rings under `__rings`, the layer's own properties promoted to top-level keys, plus `__color`, `__matched` and the five pre-formatted `v_<field>` values. `build_deck` feeds that straight to `data=` and the accessors name record keys. See the corrected API facts in Code Map — the browser parses these strings, it does not run them.
- `detail_panel_fields()` decides Decision 1c from the data (drop fields blank in *every* row) rather than hard-coding the 17, so a field that later gains values appears without an edit. `NO_DATA_FIELDS` is asserted against it, keeping the frozen row checkable.
- `build_data_dictionary.py` gained `READABLE_OVERRIDES` (54 entries), applied *after* label selection so it corrects DFS-inherited and `MANUAL` labels alike, plus a guard raising on an override naming a field no longer in the CSV (Decision 2b). `data/raw/` stays read-only.
- Grey outlines (`LINE_COLOR`, opaque) keep precincts legible if MapLibre tiles never load — the offline-basemap path in Design Notes.
- Left for the human (no browser in this environment): the plan's `## Verification` manual checks — hover coloured vs grey, click then click-a-second (no stacking), toggle all five fields, basemap legibility without tiles.

## Plan Change Log

- 2026-11-11 (implement): corrected `## Verification` boot command `localhost:8501/healthz` → `localhost:8501/_stcore/health`. `/healthz` serves the SPA HTML shell in streamlit 1.67; `/_stcore/health` returns `ok`. Verified both. No intent change.
- 2026-11-11 (implement): Code Map per-field populated counts confirmed as written (24/63/63/84/25) by live measurement; an interim report of "64/64/85" was a mis-measurement and is not a plan error. Join cardinality is 84 of 85 with `1046` excluded, as the matrix states.
- 2026-11-11 (implement): the first draft of `tests/test_dashboard.py` encoded matrix row "Precinct in CSV, absent from layer" backwards (asserted `1046` absent from the CSV index). Fixed the test to the frozen row — absent from the *layer*, present in the CSV. Never edited a matrix expectation to match code.
- 2026-11-11 (implement): matrix rows that only hold at render time (default-load coverage, no-selection prompt, click, layer-unreachable) were initially guarded by `hasattr`/`try` skips, which the matrix audit counts as missing coverage. Rewritten to drive `main()` through `streamlit.testing.v1.AppTest` so every row asserts on emitted widgets; `SKIP` lines are now zero.

## Review Triage Log

Quick lens (2026-11-11), 16 findings, each verified at the cited location before verdict. No `intent_gap` / `bad_plan` survivor, so no loopback. Grouped: **A** = findings 1-3, **B** = 4-5, **C** = 9, **D** = 14-15, **E** = 10.

| # | Finding (location) | Verdict | Evidence & route |
|---|---|---|---|
| 1 | `dashboard.py:460` `selected_props(chart.selection)` never resolves a click | **high** | Reproduced: a real `PydeckState` with a populated selection returns the dict when passed whole and `None` when passed as `.selection`, because `PydeckSelectionState` has no `selection` key and `getattr(..., None)` swallows the `AttributeError`. Unmet AC "Given a polygon click…". **patch → applied**; suite mutation-checked (reintroducing it fails at `tests/test_dashboard.py:389`). |
| 2 | `tests` `_State` double nesting documented the mock, not the chart contract | **high** | Same root cause as 1: the hand-rolled `self.selection = _Sel(objects)` is a shape `main()` never produces. **patch → applied**; replaced with Streamlit's real `PydeckState`/`PydeckSelectionState`. |
| 3 | `run_app` stubbed `selected_props`, so the click rows could not fail | **medium** | Confirmed: `AppTest.from_string` reuses the module in `sys.modules`, so the patch bypassed the broken extractor. **patch → applied**; now patches `st.pydeck_chart` to return a real state and lets the actual call site run. |
| 4 | `tests:269` `'"map_provider": "mapbox"' not in dj` can never fail | **medium** | Confirmed by measurement: the deck JSON emits `mapProvider`/`mapStyle` and no `map_provider`, and `blob.get("map")` is `{}`. **patch → applied**; asserts `blob["mapProvider"] == "maplibre"` and `blob["mapStyle"] == MAP_STYLE_URL`. |
| 5 | Dead `20261108` disjunct + unused `texts` lambda | **low** | `dashboard.py` puts no source path in any caption, so the branch never fired; the lambda was unreferenced. **patch → applied**; replaced with a positive "no path leaked" assertion. |
| 6 | `format_value` guesses % from magnitude; non-% branch prints `4.5e+04` | **low** (rejected) | The branch is real (`f"{45000:,.4g}"` → `4.5e+04`) but unreachable: measured, **no** displayed field carries a value outside [0,1] — the fields that would break are exactly the 9 omitted by Decision 1c. Unlikely to be met in everyday use and a fix adds per-field unit branches. Rejected; flagged to the human as a latent risk if the extract later populates a non-fraction field. |
| 7 | Colour domain includes the excluded `1046` row | **false** (rejected) | Measured `domain_for` over all 85 rows vs the 84 drawable: **identical for all five fields** (0.0–0.179856 / 0.3019–0.834 / 0.3327–0.7145 / 0.5087–0.8539 / 0.0–0.4). The claim does not occur. |
| 8 | Offline branch renders a table, violating "No selection yet" | **false** (rejected) | The frozen row's expected behavior is "no **empty** table"; the offline path renders a *populated* 17-metric panel behind an explicit precinct selectbox, and the adjacent row requires "joined-field UI still renders" offline. Refuted by the test's own shape assertions. |
| 9 | Generator `open()` without `encoding` now writes non-ASCII | **medium** | Verified baseline `data_dictionary.csv` held **zero** non-ASCII chars; the en dash in `Percent Age 18–64` is new to this change, so `LC_ALL=C` would raise `UnicodeEncodeError` and cp1252 would write mojibake — breaking the byte-stability AC. **patch → applied**; regenerated byte-identical (md5 `749febbc…`) under default, `LC_ALL=C` and `C.UTF-8`. |
| 10 | `pyproject.toml` deps without an `uv.lock` hunk — diff not self-contained | **medium** | `git show 5b01f45:uv.lock` has 0 streamlit/pydeck/pandas entries while the worktree has 11. **patch → applied**; `{diff_file}` re-staged to include `uv.lock`. |
| 11 | `tooltip_html` interpolates `NewPrcnt` unescaped into tooltip HTML | **low** (rejected) | Design Notes do say "never pass a source string through unformatted", but all 791 layer values are alphanumeric (15 like `30A4`, 0 HTML metacharacters), so the bad outcome needs a hostile layer. Fix adds escaping complexity for a closed value space. Rejected; disclosed to the human. |
| 12 | `join_index` trusts "fan-out resolved at source" rather than enforcing it | **false** (rejected) | A frozen Decision explicitly waives a row-picking rule, and `tests` asserts 85 rows → 85 unique non-blank keys, so regressed fan-out fails the suite rather than silently captioning wrong. |
| 13 | Per-rerun `deepcopy` of 791 features + full `bbox` rescan | **low** (rejected) | Measured 221 ms + 36 ms per rerun. The `deepcopy` is load-bearing: without it `decorate` would mutate the object `st.cache_data` hands back and poison later reruns. Caching it adds invalidation state not demonstrated as a problem. |
| 14 | Override coverage rests on inspection; artifact list is substring-brittle | **medium** | Real silent-regress risk: computed, only 35 of the 54 corrections were protected by artifact substrings or worked examples — **26 would regress unnoticed** (e.g. `Median age` → `Median Age`), against Decision 2b. **patch → applied** (finding 15's check subsumes the substring scan). |
| 15 | `n_overridden` printed but never asserted against the generated file | **medium** | Same root cause as 14; no check tied the override dict to the CSV. **patch → applied**; `tests` now asserts every `READABLE_OVERRIDES` entry equals the emitted `readable_name` (54/54). |
| 16 | `declared = observed` before assignment in the undocumented-field branch | **defer** | Line is byte-identical at baseline (`git show 5b01f45:build_data_dictionary.py` → line 352), so it is pre-existing and outside this change's "label fix only" boundary. Recorded in `_bmad-output/deferred-work.md`. |

### Post-delivery defect, found by the human running the app (2026-11-12)

Browser crash on load — `Error: Unexpected "=" at character 2` in `DeckGlJsonChart…js`. Not in the 16 findings above: the quick lens reviewed by inspection and could not execute the renderer, and every Python-side check in the suite passed against it.

- **Root cause.** The plan's Code Map asserted "`@@=` marks a JS string" and "a FeatureCollection dict is accepted as `data`". Both wrong. pydeck prefixes *every* string layer prop with `@@=` (`bindings/layer.py:99-101`); `@deck.gl/json` then **parses** it with a restricted expression grammar (literals, record-key lookups, `+`, ternary) and does not evaluate JavaScript. So `getFillColor="d => d.properties.__color"` throws at the `=` — index 2, matching the error exactly — and the `{token}` tooltip was a second crash queued behind it (`Unexpected "{" at character 12`). Reproduced with the real converter, not inferred.
- **Why review missed it.** `## Tasks` asked for a test that `Layer(id=…)` equals the selection key; the implementation asserted `emitted["getFillColor"] == "@@=d => d.properties.__color"` — i.e. the test *pinned the broken string*, turning the defect into a green check. A test written from the plan's false API fact cannot detect that fact.
- **Fix.** `decorate()` now returns a list of pydeck records (rings under `__rings`, layer props and the five formatted values promoted to record keys); accessors name those keys; `tooltip_html` → `tooltip_expression`, which concatenates Python-interpolated labels with record lookups. `tests` gained `grammar_ok()`, which rejects `=>`, `{}`, and calls in any `@@=` prop and checks each named key exists on the records — the guard that was missing.
- **Verified in the renderer**, which is what had never happened: chromium + WebGL2, **0 console/page errors**, polygons actually drawn (9 distinct colours sampled across a non-empty canvas), correct captions, no raw field name in the UI. `mypy --disallow-any-generics` clean, which also closes the 48 pasted linter errors.
- **Side effects worth noting.** Dropping `copy.deepcopy` (records are built fresh) took `decorate` from 221 ms to **2 ms** per rerun, so quick-lens finding 13 — rejected then as "low, deepcopy is load-bearing" — is now moot: the copy is gone and nothing depended on it. `bbox` rewritten to collect points first, which also fixed a genuine `tuple[float | None, …]` type error.
- **Still unproven here:** deck.gl picking in headless Chromium did not register hover or click, so the click path rests on the AppTest/`PydeckState` test plus the mutation check, not on a real browser click. Needs the human's eye — see `## Verification`.

## Design Notes

Grey-vs-colored is the product for sparse fields, so no-data is a first-class style, not an absence of style. The default metric is populated for 24 of 84 matched precincts (a canvass-coverage proxy, not a result) — the map is intentionally mostly grey at default.

Normalize each color scale on the **selected field's own populated min/max**, never a fixed 0–1: `2024_kamala` spans 0.51–0.85 while the default spans 0.00–0.18, so a shared domain would flatten one and crush the other. Interpolate two colors across that domain; keep grey `[200,200,200]` for blank.

Cache geometry with `st.cache_data(ttl=...)` so a 4.6 MB fetch does not repeat on rerun — switching the color field must not refetch.

Values are interpolated into tooltip HTML; every value shown is a locally formatted number. Format numbers only — never pass a source string through unformatted.

Decision 1c drops the 9 no-data fields with no visible trace; their absence reads as a scoping choice rather than a data gap, which is the tradeoff accepted here.

Keep the choropleth readable without the basemap: precincts must stay distinguishable if tiles fail to load, since that path is third-party and offline is a supported state.

## Verification

**Commands:**
- `uv sync` -- expected: resolves streamlit + pydeck + pandas, no conflict
- `uv run python build_data_dictionary.py` -- expected: `rows in precinct_data.csv: 85`, `UNDOCUMENTED (fallback): []`, `blank-readable names: []`
- `uv run python tests/test_dashboard.py` -- expected: exits 0 with a pass line per assertion
- `uv run python -c "import dashboard; print(len(dashboard.load_rows()), len(dashboard.build_dictionary()))"` -- expected: `85 89`
- `uv run streamlit run dashboard.py --server.headless true & sleep 12; curl -s localhost:8501/_stcore/health` -- expected: `ok`, no traceback on stderr (`/healthz` serves the SPA HTML shell; `/_stcore/health` is the health endpoint in streamlit 1.67)
- `uv run python -c "from streamlit import config; print(config.get_option('browser.gatherUsageStats'))"` -- expected: `False`

- `uv run streamlit run dashboard.py --server.headless true`, then open http://localhost:8501 -- expected: polygons draw and **the browser console is free of `Unexpected "="` / `Unexpected "{"`**. No Python-side check can see those two errors: pydeck marks every string layer prop `@@=` and the browser *parses* it, so an illegal expression fails only at render time (2026-11-12 incident).

**Manual checks:**
- Hover a colored precinct → five labeled values; hover a grey one → same five labels, all `—`.
- Click a precinct → detail fills; click another → view replaces it (no stacking).
- Toggle all five fields: color changes, tooltips do not.
- Basemap loads; confirm precincts remain legible if it does not.
- No raw field name (`prop_a_city_no_canvassing_pct`, `pct_nh_white`) appears in the rendered UI.
