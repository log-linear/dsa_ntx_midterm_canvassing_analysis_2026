---
title: 'Streamlit precinct choropleth dashboard'
type: feature
ticket: ''
created: '2026-11-10'
status: ready-for-dev
baseline_revision: '5b01f45'
route: full
route_source: auto
risk: medium
review: ''
review_source: ''
lenses_ran: []
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
  - `pdk.Layer("PolygonLayer", data=<GeoJSON FeatureCollection dict>, id="<layer_id>", get_fill_color="d => d.properties.__color", get_line_color=[..], pickable=True, auto_highlight=True, tooltip="...")` → serializes to `getFillColor`/`@@type: PolygonLayer`. A FeatureCollection dict is accepted as `data`.
  - Per-feature colors must be **injected into each feature's `properties`** (`__color`); a fixed `[r,g,b]` colors every polygon identically.
  - `tooltip="<b>{NewPrcnt}</b> {v_<field>}"` survives `.to_json()` (the `@@=` prefix marks a JS string). Pre-format values into `properties` so the template holds placeholders only.
  - `st.pydeck_chart(deck, on_select="rerun", selection_mode="single-object", key=..., width="stretch", height=...)` returns `PydeckState`; clicked attributes are at `.selection.objects["<layer_id>"]` — a list of the feature's GeoJSON `properties` dicts. **`Layer(id=...)` is required** or selection state is unkeyed. `use_container_width` is superseded by `width="stretch"`.
  - Basemap: `map_provider="maplibre"` + a style **URL string** serializes cleanly (`mapStyle` = URL). A `dict` style raises `AssertionError: The map_provider parameter must be 'mapbox' when map_style is provided as a dict.` CARTO Positron `https://basemaps.cartocdn.com/gl/positron-gl-style/style.json` returns HTTP 200 keyless.
  - Telemetry: `browser.gatherUsageStats` (default `True`); env `STREAMLIT_BROWSER_GATHER_USAGE_STATS`; settable in `.streamlit/config.toml`.
- `dashboard.py`, `.streamlit/config.toml`, `tests/` — do not exist yet.

## Tasks & Acceptance

**Execution:**
- [ ] `build_data_dictionary.py` -- add a readable-name override covering every mangled label (58 fields inherit them from the DFS export), then run it to regenerate `data/data_dictionary.csv` -- root fix; a display-layer patch would be clobbered by the next generation
- [ ] `dashboard.py` -- create: pure data functions (`fetch_features`, `load_rows`, `build_dictionary`, `join_precincts`, `color_scale`, `tooltip_html`) importable without Streamlit, then the UI (sidebar `st.selectbox` of the 5 readable labels, `st.pydeck_chart`, detail view) -- keeping prep pure makes the edge matrix testable
- [ ] `.streamlit/config.toml` -- create `[browser] gatherUsageStats = false` -- satisfies telemetry at launch rather than via an overridable runtime `set_option`
- [ ] `pyproject.toml` -- add `streamlit>=1.67`, `pydeck`, `pandas` -- declared so `uv run` works on a fresh clone
- [ ] `tests/test_dashboard.py` -- assert each checkable Matrix row: join cardinality 84 and `1046` absent from layer, blank≠zero, all 5 choropleth fields present in every tooltip incl. for a data-less precinct, all 17 displayed detail fields resolve to corrected labels, the 9 no-data fields are absent from the panel, `Layer(id=...)` == the selection key, regenerated labels contain no `Pct `/` nh `/` us ` artifacts -- protects semantics a choropleth gets silently wrong

**Acceptance Criteria:**
- Given a fresh `uv run streamlit run dashboard.py`, when the map renders, then all 791 polygons are drawn over a basemap, exactly 84 carry CSV data, and color is `prop_a_city_no_canvassing_pct`.
- Given any selected color field, when hovering any polygon, then all five choropleth metrics appear with their `readable_name` labels.
- Given a polygon click, then a second view shows the 17 populated metrics by `readable_name`, omits the 9 with no data anywhere, and no raw field name appears in the UI.
- Given the committed config, then `streamlit config show` reports `gatherUsageStats` as `false`.
- Given no network, then the app starts and shows one clear error, not a traceback.
- Given `build_data_dictionary.py` re-run after these edits, then `data_dictionary.csv` is byte-stable and its 26 labels are the corrected ones.

## Implementation Notes

## Plan Change Log

## Review Triage Log

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
- `uv run streamlit run dashboard.py --server.headless true & sleep 8; curl -s localhost:8501/healthz` -- expected: `ok`, no traceback on stderr
- `uv run python -c "from streamlit import config; print(config.get_option('browser.gatherUsageStats'))"` -- expected: `False`

**Manual checks:**
- Hover a colored precinct → five labeled values; hover a grey one → same five labels, all `—`.
- Click a precinct → detail fills; click another → view replaces it (no stacking).
- Toggle all five fields: color changes, tooltips do not.
- Basemap loads; confirm precincts remain legible if it does not.
- No raw field name (`prop_a_city_no_canvassing_pct`, `pct_nh_white`) appears in the rendered UI.
