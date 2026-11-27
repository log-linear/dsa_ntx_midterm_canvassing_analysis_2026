---
title: 'Dashboard range filters'
type: feature
ticket: ''
created: '2026-11-26'
status: in-progress
baseline_revision: '6397d65378e631b12075c792cb5aae1dd130d5cf'
route: 'full'
route_source: 'auto'
risk: 'medium'
review: ''
review_source: ''
lenses_ran: []
review_loop_iteration: 0
context: []
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The dashboard never hides a precinct: all 791 polygons are always drawn, so a
reader cannot ask "show only precincts above 40% renter-occupied" without hovering each one.

**Approach:** One two-sided `st.slider` per filterable field in a sidebar "Filter precincts"
expander, each defaulting to the field's own populated range so nothing is filtered on load. A
shared visibility mask decides which precincts survive every active range; the precinct layer
draws only survivors. A "Click here to reset filters" button restores all full ranges.

## Boundaries & Constraints

**Always:**
- Default state = every slider at its populated min/max = zero precincts hidden.
- A precinct blank for a *narrowed* field stays hidden — blanks are never inferred as zeros. An
  untouched field can hide nothing.
- Bounds come from the extract (`field_domain`), never typed-in 0–1: `canvass_attempts` is 0–613.
- Labels come from `data_dictionary.csv` through `label_for`, never raw field names.
- Read constants attribute-style (`settings.X`).

**Never:**
- Do not touch `fetch_features`, `join_precincts`, or `decorate`'s colour/token contract; filtering
  is a mask over `decorate`'s output. Detail panels and tooltips keep working for hidden precincts.
- Do not filter the council overlay layer.
- Do not add a sidebar `selectbox`/`multiselect`/`html`, nor any widget before "Colour precincts
  by" — the suite asserts on those channels and on element order.
- Do not reset by *writing* values into session state; Streamlit warns and raises
  `StreamlitValueAboveMaxError` when a persisted value falls outside a new range. Delete keys instead.
- Do not emit a caption; do not edit `data/raw/`, `data/*.csv`, `TOOLTIP_FIELDS`, or delete any
  assertion in `tests/test_dashboard.py`.

## Decisions

Settled at Checkpoint 1 (2026-11-26).

- **Full plan kept** despite 2514 tokens (> 1600 target): the residue is the field matrix and task
  specs, and every carve-out would be a deliverable that cannot ship alone.
- **Q1 = (a)** The 9 fields blank across all 820 rows get **no slider**; 32 sliders total. Same
  rule `detail_panel_fields` already applies to them. No fake bounds, no explanatory caption.
- **Q2 = (a)** A precinct filtered out **keeps its detail panels** if it was already clicked: the
  panels describe the research extract, not the current filter. No selection-clearing.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| HAPPY | all sliders untouched | no mask computed at all → 791 layer records, exactly as today | No error expected |
| NARROWED | one range excludes a precinct's value | that polygon drops out; its row stays in the panels' index | n/a |
| BLANK + narrowed field | precinct's value is `""`, or it has no CSV row (the 87 the crosswalk cannot attribute) | hidden — membership in the range is unprovable | n/a |
| BLANK + untouched field | full-range default | visible and uncoloured, as shipped | n/a |
| ALL-BLANK field (the 9 in `NO_DATA_FIELDS`) | `min == max` | no slider emitted | `st.slider` would raise `StreamlitInvalidMinMaxError` |
| STALE persisted value after a rebuild shrinks a domain | value outside new bounds | key dropped before the widget is created → slider shows the new full range | avoids `StreamlitValueAboveMaxError` |
| RESET | click after narrowing | all `f_*` keys deleted pre-run; sliders full; nothing hidden | n/a |
| OFFLINE precinct service | `fetch_features` fails | unchanged single `st.error`, zero filter widgets | existing path |

</frozen-after-approval>

## Code Map

- `src/settings.py` — `CHOROPLETH_FIELDS`:75, `RESULTS_PANEL_FIELDS`:109, `DETAIL_FIELDS`:131,
  `NO_DATA_FIELDS`:180, `DISTRICT_SELECTOR_LABEL`:302. Filter chrome strings join this block.
- `src/utils/data_layer.py` — pure transforms, no streamlit import. Reuse `field_domain`:253
  (populated min/max), `to_float`:80 (blank→None). Add `FILTER_FIELDS`/`filter_bounds`/
  `visible_precincts` here.
- `src/utils/streamlit.py` — `build_deck`:144 already accepts any-length `records`. Add
  `filter_sliders`/`visible_records` here. `decorate` output carries `JOIN_LAYER_KEY` per record.
- `src/dashboard.py` — `main()` only: sidebar block :65-84, second sidebar block :116-134 (district
  menu), `fc = data_layer.decorate(...)` :161, `ui.build_deck(fc, ...)` :166.
- `tests/test_dashboard.py` — flat script, no pytest. Aborts at :454 (`TOOLTIP_FIELDS` is empty by
  design), so :455-2711 never run: **live checks must sit above :441**. `ok()` :26 prints PASS;
  `_populated_range` :382 recomputes a domain independently; `run_app` :1775 restores 4 `ORIG_*`.
- Do not change the :454 assertion or the commented captions at `src/dashboard.py:79-84,183-196`.

## Tasks & Acceptance

**Execution:**
- [ ] `src/settings.py` — add `FILTER_EXPANDER_LABEL = "Filter precincts"`,
  `FILTER_RESET_LABEL = "Click here to reset filters"`, `FILTER_SESSION_PREFIX = "f_"`.
- [ ] `src/utils/data_layer.py` — `FILTER_FIELDS` = CHOROPLETH+DETAIL+RESULTS, de-duplicated in
  that order (41 fields); `filter_bounds(rows, fields=None)` → `{field: (lo, hi)}` keeping only
  domains with `lo < hi` (32 today); `visible_precincts(rows, bounds, ranges)` → **None** when no
  range is narrowed (so the untouched case never recomputes the map), else the set of
  `JOIN_CSV_KEY` whose value is non-None and within its range for every field in `ranges`.
- [ ] `src/utils/streamlit.py` — `filter_sliders(rows, bounds, dictionary, on_reset)`: per bounded
  field drop a stale `f_*` key outside `bounds` **before** the call, then
  `st.slider(label, lo, hi, (lo, hi), (hi-lo)/100, format=…, key=PREFIX+field, help=label)` —
  float dtype unless both bounds are integral (then int, step `max(1, round((hi-lo)/100))`);
  return the chosen ranges. Plus `visible_records(records, visible)` → `records` unchanged when
  `visible` is None, else those whose `JOIN_LAYER_KEY` is in `visible`, raising `ValueError` if any
  record lacks that key.
- [ ] `src/dashboard.py` — in the second sidebar block after the district multiselect, render
  the expander + `st.button(settings.FILTER_RESET_LABEL, on_click=on_reset)`; apply
  `ui.visible_records(fc, visible)` at the `build_deck` call only.
- [ ] `tests/test_dashboard.py` — live section above :441: bounds equal `_populated_range` per
  field; 32 emitted and the 9 `NO_DATA_FIELDS` absent; every label is `label_for`; no narrowed
  range → `visible_precincts` returns None and `visible_records` returns its input untouched;
  narrowing one field hides exactly the outside values *and* the blanks; two fields intersect;
  `visible_records` over synthetic `stub_fc`-style features drops a non-survivor and keeps
  `__rings` intact.
- [ ] `tests/test_dashboard.py` — extend `run_app`'s `finally` to delete leftover `f_*` session
  keys so filter state cannot leak into the ~25 renders below the abort.

**Acceptance Criteria:**
- Given a fresh session, when the app renders, then 32 sliders read full ranges and the precinct
  layer carries all 791 records — identical to today.
- Given one narrowed slider, when the map reruns, then only precincts inside every narrowed range
  are drawn, and one blank on a narrowed field is not drawn.
- Given narrowed sliders, when reset is clicked, then every slider reads its full range, all
  precincts are drawn, and no Streamlit warning or exception is raised.
- Given a dead precinct endpoint, when the app loads, then the single `st.error` path is unchanged.

## Implementation Notes

## Design Notes

- The mask keys on **precinct number from the joined CSV**, not on record colour, so `decorate`
  never learns filtering exists; colour, tooltip and panels keep describing hidden precincts.
- "Untouched = inert" holds by construction: every range is validated inside its own `bounds`, so
  an untouched field can exclude no populated precinct.
- Slider `format`: `"%.1f%%"` when `domain_is_share` (the decision `legend_html` already makes, so
  slider and legend endpoints read alike), `"%d"` for a dictionary `integer` field, else `"%g"`.
  Never a callable — `format` ships in a protobuf string field; a lambda dies with `TypeError`.

## Plan Change Log

## Review Triage Log

## Verification

**Commands:**
- `uv run python tests/test_dashboard.py` — expected: 32 `PASS` lines above the known abort
  (27 today) and the same `AssertionError: Precinct {NewPrcnt}` traceback. The abort is expected;
  a green exit is *not* achievable and must not be chased.
- `uv run streamlit run src/dashboard.py` — expected: "Filter precincts" expander, 32 sliders,
  below the district menu.
- `git diff --stat` — expected: only the four `src/`/`tests/` files above.

**Manual checks:**
- Narrow a slider, watch polygons vanish; click reset, watch all return with no warning.
