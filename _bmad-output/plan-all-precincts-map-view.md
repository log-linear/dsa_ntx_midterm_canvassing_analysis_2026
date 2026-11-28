---
title: 'All Precincts default map view'
type: feature
ticket: ''
created: '2026-11-27'
status: in-review
baseline_revision: '388dc3b75902fe5952433100b7ed4f76e21c1f5b'
route: full
route_source: auto
risk: medium
review: quick
review_source: pinned
lenses_ran: []
review_loop_iteration: 0
context:
  - '{project-root}/AGENTS.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The only map view is a choropleth, and a precinct with no value for the selected metric paints nothing (`NO_DATA_COLOR` is fully transparent), so on the default metric most of the county's 791 polygons are invisible. There is no way to see the precinct map as a whole.

**Approach:** Add "All Precincts" to the existing "Colour precincts by" selectbox, where it draws every displayed precinct in one uniform colour with a white hairline between them, and the gradient legend is not rendered. Filtering, the council overlay, hover, and the two click-through detail panels keep working exactly as they do now, in both modes.

## Decisions

- **Default:** "All Precincts" is option 0 and is selected on load, replacing `DEFAULT_CHOROPLETH` as the initial selection. `DEFAULT_CHOROPLETH` itself is unchanged and still names the fallback metric.
- **Extent:** every polygon the layer returns gets the uniform fill, including the ~87 the VTD crosswalk cannot attribute.
- **Fill:** neutral gray `[128, 128, 128]` at `FILL_ALPHA` (150), so the basemap's street names stay legible underneath and this view shares the one opacity knob the choropleth already has.
- **Outline:** a white `[255, 255, 255]` hairline at full alpha, stroked **only** in this view. The choropleth keeps `stroked=False`.

## Boundaries & Constraints

**Always:**
- One selectbox, same label, same sidebar position: "All Precincts" is an added option, not a new widget.
- Range filters keep narrowing the map in "All Precincts"; a kept precinct gets the uniform fill and edge.
- Clicking still resolves the row via `JOIN_LAYER_KEY` and fills both panels; the tooltip is unchanged.
- The fill rides on each record's `__color`, so the choropleth's per-record accessor is shared by both modes.
- Read `settings.*` attribute-style; never `from settings import`.

**Never:**
- Never add "All Precincts" to `CHOROPLETH_FIELDS`, `TOOLTIP_FIELDS`, `DETAIL_FIELDS`, `RESULTS_PANEL_FIELDS`, or the data dictionary — it is a view, not a column.
- Never add a radio/toggle/checkbox, and never re-order the sidebar block.
- Never change `NO_DATA_COLOR`, `FILL_ALPHA`, `VIRIDIS_STOPS`, `COLOR_LOW/HIGH`, `color_scale`, or anything under `data/`.
- Never put a per-record line-colour key on the records: the stroke is layer-wide, so one mode cannot hand deck.gl an attribute the other omits.
- Never edit `TOOLTIP_FIELDS` or disable `tests/test_dashboard.py:1588` to reach green; that abort is expected.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Fresh load | Nothing touched | "All Precincts" selected; all 791 records drawn, one identical RGBA fill, layer-wide white stroke; zero legend elements | No error expected |
| Metric-empty precinct | Row exists, no value for any metric | Painted and edged (invisible in choropleth mode) | No error expected |
| Unattributable polygon | No CSV row for it | Painted and edged; clicking gives the "no data in this research extract" info | No error expected |
| Narrowed filter | One slider moved inside its bound | Only survivors drawn, all uniform, still edged | No error expected |
| Switch to a metric | A `CHOROPLETH_FIELDS` label chosen | Ramp colours return, `stroked=False`, gradient legend reappears, blanks go transparent | No error expected |
| Switch back | "All Precincts" chosen again | Uniform fill + edge, no legend, filter state kept | No error expected |
| Layer unreachable | `_cached_features` raises | Unchanged: one `st.error`, fallback picker, no map, no legend | Existing path |

</frozen-after-approval>

## Code Map

- `src/settings.py:75-86` — `CHOROPLETH_FIELDS` (7) and `DEFAULT_CHOROPLETH`. **Stays as-is**; the view label is a new constant, never an added field.
- `src/settings.py:203` — `FILL_ALPHA = 150`, defined **after** `:75`. A new `[..., FILL_ALPHA]` colour therefore cannot sit beside the field lists at `:75` (import-time `NameError`); put the colour constants after `:203`, and the view label among the sidebar strings at `:327-331`.
- `src/settings.py:181` — `NO_DATA_COLOR=[0,0,0,0]`: the transparency this view exists to break.
- `src/settings.py:296-321` — `COUNCIL_LINE_COLOR`, `COUNCIL_LINE_WIDTH_MIN_PIXELS`: the shipped precedent for a layer-wide constant RGBA reaching `get_*_color` as a plain list, not an `@@=` string. Copy that shape.
- `src/utils/data_layer.py:380-419` — `decorate(features, rows, field)` writes `__rings`, `__color`, `__matched`, `v_<field>`. Guard the `domain = field_domain(rows, field)` at `:391`: with `field=None` it does not raise, it returns `None`, so every `color_scale` call answers `NO_DATA_COLOR` and the map silently draws nothing — the failure mode here is invisible, not loud. Only the `__color` line branches.
- `src/utils/data_layer.py:174-186` — `color_scale`: untouched, unreachable in the new mode.
- `src/utils/streamlit.py:130-190` — `build_deck`: precinct layer reads `get_fill_color="__color"` per record and sets `stroked=False` explicitly, because deck.gl strokes by default. Amend the signature with an optional line colour — when given, `stroked=True` + `get_line_color=list(...)` + a min-pixel width; when `None`, today's layer byte-identical.
- `src/dashboard.py:66-72` — the selectbox, and `field = next(f for f in CHOROPLETH_FIELDS if labels[f] == chosen)`, which raises `StopIteration` on a non-field option. The load-bearing edit.
- `src/dashboard.py:88,198` — `st.title(labels[field])` (`KeyError` on `labels[None]`) and `st.html(ui.legend_html(field_domain(rows, field)))`: both need the new branch.
- `src/dashboard.py:155-167` — `visible_precincts` → `visible_records(fc, visible)`; the mask runs before the deck and must keep running in both modes. `colored` at `:167` feeds commented-out captions only.
- `tests/test_dashboard.py:791-815` `render_filters()`, `:818` `_drawn()` — new live checks go in `:791`–`:1587`; **everything at and below `:1588` never runs** (AGENTS.md calls it `:454`; the file has grown).
- Live guards the design must not trip: `:154` (dictionary covers every field list), `:430` (`FILTER_FIELDS == 41`), `:852`/`:861-866`/`:875` (one selectbox at index 0 labelled "Colour precincts by", no extra sidebar widget).
- Dead asserts to correct rather than delete: `:3045-3048` (options, default value), `:3147`, `:3683`/`:3728` (`len(at.html)==1`).

## Tasks & Acceptance

**Execution:**
- [ ] `src/settings.py` -- add `ALL_PRECINCTS_VIEW_LABEL = "All Precincts"`, `ALL_PRECINCTS_COLOR` (gray at `FILL_ALPHA`), `ALL_PRECINCTS_LINE_COLOR` (white, alpha 255) and a min-pixel line width, placed per the `FILL_ALPHA` ordering above, each with a one-line why
- [ ] `src/utils/data_layer.py` -- `decorate(..., field: str | None)`: when `field is None`, skip `field_domain`/`color_scale` and set `record["__color"] = list(settings.ALL_PRECINCTS_COLOR)`; leave `__rings`, `__matched`, `v_*` and the ramp branch byte-identical
- [ ] `src/utils/streamlit.py` -- `build_deck(records, tooltip, features, district_records=None, line_colour=None)`: `line_colour` switches the precinct layer to `stroked=True` with `get_line_color=list(line_colour)` and the min-pixel width; `None` leaves the layer exactly as it is today
- [ ] `src/dashboard.py` -- prepend the view label with `index=0`; `field = None` when the chosen label is the view label, else today's `next(...)`; title = chosen label; legend only when `field is not None`; pass `line_colour` to `build_deck` only when `field is None`
- [ ] `tests/test_dashboard.py` -- live checks above `:1588` (options + default; every drawn record shares the fill colour incl. metric-empty and unattributable precincts; serialised precinct layer carries the stroke props in the new view and `stroked=False` in a metric; zero `st.html` in the new view, one for a metric; filters still shrink the layer); correct the dead asserts listed above

**Acceptance Criteria:**
- Given a fresh session, when the deck payload is read, then the precinct layer holds all polygons, every record shares one fill RGBA, and no legend element is rendered.
- Given a precinct with no value for any metric, when the view is "All Precincts", then its polygon carries the uniform fill.
- Given a slider narrowed, when the view is "All Precincts", then exactly the survivors are drawn, each uniform.
- Given a precinct clicked in "All Precincts", when the panels render, then results and demographics appear as in choropleth mode.
- Given the selectbox moved to any `CHOROPLETH_FIELDS` label, on rerun the colours are the ramp's, the precinct layer is not stroked, and the gradient legend is back.
- Given `uv run python tests/test_dashboard.py`, then every new check prints PASS and the run still ends at the `:1588` abort.

## Implementation Notes

## Plan Change Log

## Review Triage Log

## Design Notes

The existing selectbox, not a new widget: the sidebar's widget set and order are pinned by live asserts (`:852`, `:861-866`, `:875`), and the selected option *is* the view, so no second source of truth can desynchronise.

The fill goes on the record, the stroke on the layer: `get_fill_color="__color"` already reads per record, so both modes share one deck path. A per-record line colour would exist in one mode's payload and not the other's — and deck.gl sizes a colour attribute from the first record it sees, which is how the ragged-alpha bug in `settings.py:196-201` was born. Layer-wide stroke mirrors `COUNCIL_FILL_COLOR` instead.

`field=None` as the sentinel rather than a magic string keeps `color_scale`/`field_domain` unreachable and gives `main()`'s `next()` a guard instead of a lookup that can never succeed.

## Verification

**Commands:**
- `uv run python tests/test_dashboard.py` -- expected: new checks print `PASS`; the run still ends in the `AssertionError` at `:1588` with nothing failing above it
- `uv run streamlit run src/dashboard.py` -- expected: default load paints every precinct gray with white edges and no gradient bar; a metric still colours unstroked; filters still hide; clicking still fills both panels

**Manual checks:**
- Adjacent precincts are distinguishable by edge at county zoom, and street names read through the fill.
- Sidebar still reads: colour selectbox, district multi-select, "Filter precincts" expander — one each, in that order.
