---
title: 'Dashboard range filters'
type: feature
ticket: ''
created: '2026-11-26'
status: built
baseline_revision: '6397d65378e631b12075c792cb5aae1dd130d5cf'
route: 'full'
route_source: 'auto'
risk: 'medium'
review: 'quick'
review_source: 'pinned'
lenses_ran: ['quick', 'quick']
review_loop_iteration: 1
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
- Reset seeds each field's own full range with `setdefault` at slider creation. A bare delete leaves
  the element id intact, the browser keeps its own copy of the value, and the thumbs never move;
  `set_value` on the outgoing proto is what the mounted Slider honours. (Amended 2026-11-27 after
  loopback 4.)

**Never:**
- Do not touch `fetch_features`, `join_precincts`, or `decorate`'s colour/token contract; filtering
  is a mask over `decorate`'s output. Detail panels and tooltips keep working for hidden precincts.
- Do not filter the council overlay layer.
- Do not add a sidebar `selectbox`/`multiselect`/`html`, nor any widget before "Colour precincts
  by" — the suite asserts on those channels and on element order.
- Never reset by writing a *persisted* range back into session state: a value outside a new range
  makes Streamlit raise `StreamlitValueAboveMaxError`, so a stale key must be deleted before its
  widget exists. (Amended 2026-11-27 after loopback 4 — the original wording forbade writing at all,
  which is what let the thumb bug through; see "Always" for the required seed.)
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
| RESET | click after narrowing | all `f_*` keys deleted pre-run; sliders re-seeded to full range, and the outgoing proto carries `set_value` so the browser moves the thumbs too; nothing hidden | n/a |
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
  range is narrowed **by more than a relative tolerance** (see Design Notes: a widget's far-right
  handle reports `min + n*step`, so exact equality is the wrong untouched test), else the set of
  `JOIN_CSV_KEY` whose value is non-None and within its range for every narrowed field.
- [ ] `src/utils/streamlit.py` — `_slider_format(field, bound, dictionary, rows)` returns
  `(dtype, axis_lo, axis_hi, step, fmt, scale)` where `scale` is 100.0 for a share field and 1.0
  otherwise: shares go on a whole percent-point axis — `floor(lo*100)`…`ceil(hi*100)` clamped
  0-100, int, step 1, `"%d%%"` (see Loopback 2) — integer-valued fields go int with a step that
  **divides the span**, everything else float `%g` at `span/100`.
  `filter_sliders(rows, bounds, dictionary, on_reset)`: emit `st.button` **first** (see Loopback 3),
  then per bounded field drop a stale `f_*` key outside the field's axis bound — including a
  non-integral pair on an integral axis — **before** the call, seed the full axis range with
  `session_state.setdefault(PREFIX+field, (lo, hi))` and render `st.slider(label, axis_lo, axis_hi,
  None, step, format=fmt, key=PREFIX+field, help=label)` — the seed, not an explicit `value`, is what
  sets proto `set_value` so the browser moves the thumb (see Loopback 4); then divide the returned
  pair by `scale` so callers keep the field's native unit. Plus `visible_records(records,
  visible)` → `records` unchanged when `visible` is None, else those whose `JOIN_LAYER_KEY` is in
  `visible`, hiding a record that cannot name itself and raising only if none can.
- [ ] `src/dashboard.py` — in the second sidebar block after the district multiselect, render
  the expander + `st.button(settings.FILTER_RESET_LABEL, on_click=on_reset)`; apply
  `ui.visible_records(fc, visible)` at the `build_deck` call only.
- [ ] `tests/test_dashboard.py` — live section above the abort: bounds equal `_populated_range` per
  field; 32 emitted and the 9 `NO_DATA_FIELDS` absent; every label is `label_for`; no narrowed
  range → `visible_precincts` returns None and `visible_records` returns its input untouched;
  narrowing one field hides exactly the outside values *and* the blanks; two fields intersect;
  `visible_records` over synthetic `stub_fc`-style features drops a non-survivor and keeps
  `__rings` intact.
- [ ] `tests/test_dashboard.py` — **finding #1/#2 guards**: every share slider's displayed endpoints
  equal `format_value(lo/hi, True)` as rendered by the same printf string the widget ships, and the
  far-right handle position equals the bound for **all 32** fields (a step that does not divide its
  span is the defect); assert a `canvass_attempts` slider left untouched yields `visible is None`.
- [ ] `tests/test_dashboard.py` — **finding #3**: seed a stale **low** (`(2.0, 40.0)` against a
  `10.0`-minimum bound) so the `current[0] < lo` branch is actually executed, not only the high side.
- [ ] `tests/test_dashboard.py` — **finding #8**: after narrowing, assert `layers[1]` (the council
  overlay, keyed `settings.COUNCIL_LAYER_ID`) still carries every district record — the overlay must
  not be filtered.
- [ ] `tests/test_dashboard.py` — **finding #9**: assert the sidebar caption set is exactly the
  district hint (`len == 1`), so a new filter caption fails the check instead of slipping past a
  keyword filter.
- [ ] `tests/test_dashboard.py` — **finding #4**: keep `clear_filter_state` (a post-run `del` of a
  live widget key raises `KeyError "$$ID-…-f_x"` from AppTest's own serialisation), correct its
  docstring to say the write is test-side-only (AppTest's `_AppTestSessionState` bypasses the
  already-instantiated guard the app's proxy enforces), and bound the sweep to keys in
  `filter_bounds`.

**Acceptance Criteria:**
- Given a fresh session, when the app renders, then 32 sliders read full ranges and the precinct
  layer carries all 791 records — identical to today.
- Given one narrowed slider, when the map reruns, then only precincts inside every narrowed range
  are drawn, and one blank on a narrowed field is not drawn.
- Given narrowed sliders, when reset is clicked, then every slider reads its full range, all
  precincts are drawn, and no Streamlit warning or exception is raised.
- Given a dead precinct endpoint, when the app loads, then the single `st.error` path is unchanged.

## Implementation Notes

Implemented against `6397d65` on branch `feature/filters` (the plan was committed as
`c25ee34` by the user; no code was committed). Suite: 27 PASS → **47 PASS**, still aborting at
the same pre-existing tooltip assertion, shifted `:454` → `:983` by the inserted checks.

Two deviations from this plan, both found while verifying rather than reported as finished work:

1. **`_slider_format`'s dtype rule is stronger than written, because the written rule was
   wrong.** The plan said float-unless-both-bounds-integral. That makes `pct_renter_occupied`
   (0.0–1.0) an **int** slider with step `max(1, round(0.01)) = 1` — it offers only 0 and 1, so
   the only narrowing it can express hides all 798 fractional rows, and the plan's own headline
   example becomes unreachable. Same trap on `2024_kamala`, `2024_prop_r_for`,
   `2026_prop_city_percent_Against`, `pct_multi_unit`. Shipped rule reads the field's **values**
   as well as its bounds. The implementer's docstring claimed the two rules "pick the same 32
   fields"; measured, they disagree on exactly those 5 — corrected, and a live check now pins the
   3-int/5-float split so it cannot regress in either direction.
2. **`clear_filter_state` restores each widget's own `proto.default` instead of deleting the
   key.** A bare `del` makes a *later* `at.run()` raise `KeyError` out of AppTest's own
   serialisation, and ~25 renders below the abort rerun after this section. Resetting to the
   proto default is equally inert (full range, nothing hidden); orphaned keys are still deleted.

Also added beyond the task list: a check for the matrix's NARROWED second clause (Q2a — a hidden
precinct keeps its row in the panels' index), which had no coverage. Mutation-checked the three
highest-value guards (endpoints-only dtype, blank-as-in-range, untouched-as-narrowed); each fails
loudly, so none is vacuous.

## Design Notes

- The mask keys on **precinct number from the joined CSV**, not on record colour, so `decorate`
  never learns filtering exists; colour, tooltip and panels keep describing hidden precincts.
- "Untouched = inert" is enforced by the **mask's bound test, not by widget arithmetic**. A slider
  reports `min + n*step` after a drag, so where the step does not divide the span the populated
  maximum is not a reachable position (`canvass_attempts` 0–613 at step 6 lands on 612). Treating
  exact equality with the bound as "untouched" would therefore hide precincts on a slider the reader
  never narrowed — the frozen default state forbids that. So each side counts as narrowed only when
  it moves **inside** its bound by more than a relative tolerance (`span * 1e-9`).
- Step size must leave the populated maximum reachable: for an integer-valued field the step is the
  largest divisor of the span not exceeding `round(span/100)`, never a bare `max(1, round(...))`.
- **Slider axis for a share field is whole percent-points, 0-100, not 0-1.** `st.slider`'s
  `format` is a literal printf string applied to the widget's own value, and there is no callable
  form (a lambda dies in the protobuf field), so a 0-1 field formatted `"%.1f%%"` prints `0.4%`
  where `legend_html` prints `40.0%`. Shares are therefore put on a percent-point axis with
  `scale` 100.0, and `filter_sliders` divides the chosen range back by 100 before returning it, so
  the mask, `filter_bounds` and every comparison stay in the field's native 0-1 unit. Non-share
  floats read `"%g"`; integer-valued fields read `"%d"`.
- **Amended (Loopback 2, user request): that axis is INTEGER — `floor(lo*100)` … `ceil(hi*100)`,
  clamped 0-100, `step=1`, `dtype=int`, `format="%d%%"`.** No decimal labels, no sub-point drags.
  Rounding is **outward** so the axis always CONTAINS the populated bound; rounding in would strand
  a 39.645% maximum off the end of the scale and make a slider nobody touched hide precincts. A
  `1e-9` hair (`settings.SHARE_AXIS_HAIR`) keeps a bound that IS a whole point from gaining a
  spurious extra point to `0.07*100 == 7.000000000000001`. The legend keeps one decimal; the
  slider cannot, because it only ever sits on a whole point — they now agree on *scale*, not
  character-for-character. A persisted non-integral range on an integral axis counts as STALE
  (`_forget_stale_range(integral=True)`): Streamlit accepts it silently, and `"%d%%" % 20.5` prints
  `20%` while filtering at 20.5% — a label lying by the fraction it cannot display.
- Slider `format` and legend formatting stay coupled through `domain_is_share` — the same decision
  `legend_html` makes, so the two can never label one field's endpoints differently.


Passes 1-2 appended: PASS now **55** (abort shifted again to `tests/test_dashboard.py:1340`; the
`:983` above was pass 0's position). `lenses_ran` records the `quick` lens launched twice — once
per pass, both as context-free subagents at this session's model. Two pass-1/pass-2 findings were
routed `defer` and written to `deferred-work.md`: the uncached `load_rows()` CSV read (pre-existing
at `6397d65`, cost measured negligible at 820 rows) and the below-abort renders' exposure to 33 new
sidebar elements (unsettled while the `TOOLTIP_FIELDS` abort stands, which this plan freezes).

## Implementation Notes (post-build, added during the walkthrough)

Stop 2 of the `df5e238` walkthrough surfaced a **pre-existing** classification defect that the new
slider made visible rather than caused: 3 rows of `data/precinct_data.csv` carry
`pct_single_unit` = `1.0000000000000002`, a sum-of-quotients artifact `2.22e-16` above 1.0, and
`domain_is_share`'s exact `domain[1] <= 1.0` put the whole column on the count axis. The legend read
`0`/`1`, the detail panel read `1`, and the slider spanned `0`/`1.0000000000000002` on `%g` — while
its complement `pct_multi_unit`, which tops out at exactly 1.0, read `0.0%`/`100.0%`. One housing
table, two units.

Fixed with a named tolerance (`settings.SHARE_TOLERANCE = 1e-12`) applied at BOTH places that decide
share-vs-count — `domain_is_share` for the field, `format_value` for the value, clamped before
scaling since `-1e-13` otherwise reaches the UI as `-0.0%` — rather than a special case for one
field, so the next artifact cannot re-arm the same trap. `data/` was not edited: the value arrives
already-artifacted from the DFS export, and the classification layer is where all four surfaces read.

Suite 55 → **58 PASS**, no name lost. Three new checks, each mutation-tested: the axis decision is
re-derived from the raw CSV **text** (replacing `assert _share_seen == 28`, a typed-in count that
stayed green through the actual defect); the emitted `pct_single_unit` widget reads `0.0%`/`100.0%`;
and the tolerance's *magnitude* is pinned on synthetic domains, because no field in this extract
sits between `1e-12` and `1.01`, so nothing else would notice an over-wide band being opened.

## Plan Change Log

### Loopback 4 — 2026-11-27, user-reported bug: reset moved the map but not the thumbs

**Bug:** clicking reset filtered the map correctly while every slider kept the position the
reader had dragged it to. **Pre-existing since the feature shipped** — reproduced with
`set_value=False` after reset at `df5e238` (the first filter commit), `0a95c6b` and `545a5b7`, all
with the button at the bottom. Loopback 3's move did not cause it.

**Mechanism** (read out of this Streamlit build, 1.67.0, not reasoned from the diff): the browser
keeps its own copy of each widget's value in `WidgetStateManager`, keyed on the element id. The
id is computed from key + `min_value`/`max_value`/`step` only (`key_as_main_identity`), so a reset
that deletes the `f_*` keys leaves every id unchanged and the mounted component keeps its local
`uiValue`. The only thing that pushes a server value into an already-mounted slider is the proto's
`set_value` flag — `useBasicWidgetState` returns early on `if (!element.setValue) return`, and
`Slider.tsx`'s `useEffect(..., [value])` then re-syncs `uiValue`. `set_value` is set from
`widget_state.value_changed`, whose branches all require the key to be a **new state value**
(`is_new_state_value(user_key)`); a deletion is none of them. So the backend recomputed full ranges
into `proto.value` and the client ignored it. Worse: on the next interaction the client re-sends the
stale pair, which the backend honours, so a filter the reader thought they cleared comes back.

**Fix:** `filter_sliders` seeds `(lo, hi)` with `st.session_state.setdefault(key, ...)` and passes
`value=None`, so the key IS a new state value on the post-reset run → `set_value` True → the thumbs
follow. `setdefault` is a no-op while the key exists, so a drag is never overwritten and
`set_value` stays False for a plain drag (asserted). The seed runs **after** `_forget_stale_range`:
with `value=None` the widget infers single-vs-range from the key, so seeding first lets a stale pair
occupy it, get deleted, and leave Streamlit building a single slider — `chosen[0]` then dies with
`'int' object is not subscriptable` (mutation-tested).

**Freezes amended (human authorised 2026-11-27, "amend the constraint text"):**
- `## Boundaries & Constraints` no longer forbids writing outright. The conflated case is split:
  **Never** covers writing a *persisted* range back (still the `StreamlitValueAboveMaxError` the
  original sentence was reaching for, still handled by `_forget_stale_range`), and **Always** gained
  the positive requirement the bug turned on — seed each field's own full range with `setdefault` at
  creation, because `set_value` is the only thing a mounted Slider honours.
- The `RESET` matrix row gained the seed and the `set_value` requirement as its expected behaviour.
- Loopback 1's KEEP instruction #3 ("never writes them") marked superseded in place rather than
  rewritten, so the sequence of decisions stays readable.
- Pass-2 triage finding #3's "the frozen rule is honoured" is left as written: it was true of the
  code at that date, and the triage log is a record, not a spec.
- The duplication warning the rule also cites is sidestepped rather than suppressed: with
  `value=None` there is no explicit default, and `check_session_state_rules` only warns when one is
  passed alongside a new state value.

**Why AC3 stayed green:** every existing check reads `widget.value` / `proto.value`, i.e. what the
server computed. None read `proto.set_value`, the field the browser actually gates on — the same
class as the `fc08df5`/`7af094d` lesson in `AGENTS.md`: assert the rendered payload *and the channel*.
New check asserts `set_value` True for all 32 after a reset and False after a drag. 64 PASS, up from
63; baseline differential re-run with the abort neutralised identically — no check lost.

**Unrelated, still open:** seeding an `f_*` key with a scalar (e.g. `None`) makes `st.slider` raise
`float() argument must be … not 'NoneType'`. Identical at `0a95c6b`, so pre-existing and not
introduced here; unreachable via the app, which only ever writes pairs.

### Loopback 3 — 2026-11-27, user request (UI position only)

**Changed:** the reset button is emitted before the slider loop, so it leads the
expander instead of trailing 32 sliders.

No behaviour rides on it — `on_click` callbacks run before the script, so `filter_reset`
has already deleted the `f_*` keys by the time the first slider in the loop is created,
which is why AC3 stays green from either position. Nothing in the frozen block is touched
(still exactly one button, still inside the expander, no new caption/selectbox/multiselect/
html). Pass-2 finding #8 is what makes this provable at all: the containment assertions it
added walk the expander's own subtree, but they count rather than order, so a new check
reads `[c.type for c in expander if c is not expander]` and requires `button` first —
verified to fail with `['slider', 'slider', 'slider']` when the button is moved back.
Suite 62 → **63 PASS**.

### Loopback 2 — 2026-11-27, user request after `df5e238`/`545a5b7`

**Changed:** share sliders show WHOLE percentage points only — no decimal labels, no fractional
adjustments. `## Design Notes` share-axis bullet amended above.

**Why the plan was not wrong:** loopback 1 put shares on a 0-100 float axis with `"%d%%"`-adjacent
`"%.1f%%"` and `step = span/100`, which is the finest granularity a slider can carry, not the
coarsest the reader asked for. The requirement changed, not the defect.

**Folded in while implementing:**
- Outward rounding (`floor`/`ceil`) is load-bearing for the frozen "default = zero precincts
  hidden", not cosmetic: rounding in clips a bound and re-opens loopback 1 finding #2 through a
  different door. Verified: 28 of 29 share axes contain their bound exactly; the one that cannot
  is `pct_single_unit`, whose bound is the artifact `1.0000000000000002` above the 100 clamp —
  which is why `visible_precincts`' `span * 1e-9` membership tolerance stays.
- `settings.SHARE_AXIS_HAIR = 1e-9` absorbs binary noise at exact points. Pinned synthetically
  (`0.07*100` and `0.29*100` drift to opposite sides, and no field in this extract sits where the
  hair matters), because with the hair at `0.0` the suite is otherwise fully green while every
  whole-point share bound gains a spurious point.
- `_forget_stale_range` gains `integral=`: a persisted non-whole pair inside an int axis is now
  stale. Streamlit does not reject it — it stores it and returns it verbatim — so the label and
  the mask disagree by the fraction the label cannot print.
- Three tests renamed for the new arithmetic (`slider dtype follows the field's values…`,
  `share sliders display the legend's own percentage string…`, `endpoint holders stay visible: 5
  drifting share fields…`); their substance survives in the whole-point blocks plus the outward
  containment sweep. Baseline differential re-run the same way as loopback 1 — pristine `HEAD`
  worktree, abort neutralised identically in both, `comm` on sorted PASS names — no check dropped.
- One test-side bug found and fixed while writing these: `Slider.data_type` is a protobuf ENUM
  (`INT=0`), so `== "int"` compares against the absent-default repr and reads false.

**Suite:** 58 → **62 PASS** above the unchanged `TOOLTIP_FIELDS` abort. Mutation-tested: step 2,
format `%.1f%%`, round-in axes, `SHARE_AXIS_HAIR = 0`, and dropping `integral=` each fail the
suite. Live AppTest: 32 sliders, zero exceptions/warnings, share handles at step 1 with
decimal-free labels, `pct_vacant` 39-40 keeps precinct 3041, reset restores full ranges.

### Loopback 1 — 2026-11-27, triggered by review pass 1 findings #1 and #2 (both `high`)

**Amended:** `## Design Notes` slider-format bullet and the `## Tasks & Acceptance`
`filter_sliders`/`visible_precincts` bullets.

**What was wrong in the plan (not in the implementation):**
- Design Notes prescribed `format="%.1f%%"` for a share field. `st.slider`'s `format` is a
  literal printf string applied to the **raw** value, and shares are stored 0-1, so the slider
  rendered `0.4%` where the legend renders `40.0%`. A 28-of-32-field mislabel, and it defeated the
  very "slider and legend endpoints read alike" claim written beside it.
- Tasks prescribed `step = (hi-lo)/100` and `max(1, round((hi-lo)/100))`. rc-slider aligns a
  dragged value to `min + n*step`, so where the step does not divide the span the populated maximum
  is **not a reachable position**: `canvass_attempts` 0-613 at step 6 reports 612 far-right. Combined
  with `visible_precincts`' exact float compare, that made the frozen "Default state = zero precincts
  hidden" false for a slider the reader never narrowed.

**Known-bad state the amendment avoids:** a filter UI whose numbers disagree with the map's own
legend by 100x; a default load that silently hides precincts; an unreachable upper bound.

**KEEP instructions — must survive re-derivation:**
1. All ~20 filter checks stay **above** the `TOOLTIP_FIELDS` abort; the region below it never
   executes. Prove no coverage is lost the way pass 0 did: a baseline worktree at `6397d65`, the
   abort neutralised **identically** in both trees, then `comm` the sorted PASS names and require
   zero only-in-baseline.
2. Keep the dtype rule reading the field's **values**, not just its endpoints (3 int / 5 float
   split, pinned live; an endpoints-only rule strands `pct_renter_occupied` on 0 and 1).
3. Keep: bounds from `field_domain`; the 9 `NO_DATA_FIELDS` get no slider (Q1a); reset **deletes**
   `f_*` keys from an `on_click` callback and never writes them *(superseded by loopback 4: delete
   the persisted key, but seed the field's own full range with `setdefault` at creation — a bare
   delete leaves the thumbs unmoved)*; `visible_precincts` returns `None`
   when nothing is narrowed and `visible_records` returns its input list object; `decorate`,
   `fetch_features`, `build_deck` and the tooltip contract untouched; no new caption/selectbox/
   multiselect/html in the sidebar; no committed `data/` edit and nothing deleted from the suite.
4. Keep these matrix rows as written: intersection, blank-hidden-on-narrowed-field, blank-kept on
   untouched field, crosswalk-less polygon, STALE drop-before-widget, OFFLINE single `st.error`,
   Q2a panels-index retention.
5. `clear_filter_state` must **stay** (deleting a live widget's key after a run raises
   `KeyError: "$$ID-…-f_x"` from AppTest's own serialisation) — but per finding #4 it is a
   test-side-only path; say so accurately.

**Folded in from this pass's `patch` findings:** #3 seed a stale **low** value; #8 assert the council
overlay layer is unfiltered; #9 make the "no filter caption" assertion able to fail; #4 correct
`clear_filter_state`'s docstring and bound its key sweep to `filter_bounds`.

## Review Triage Log

Pass 2 (lens `quick`; diff `/tmp/dashboard-range-filters-review.diff`, 65 kB, post-loopback).
17 findings → 4 kept, 13 refuted. Every refutation below is measured against the shipped code or
this Streamlit build, not argued from the diff.

| # | Verdict | Route | Evidence |
|---|---------|-------|----------|
| 1 | `false` | — | A float dtype paired with `%d` is unreachable by construction, not merely today: the int branch fires when `lo`/`hi` are integral **and** every populated value is integral, and a dictionary `integer` field cannot have fractional values (checked all 27 integer-typed columns: zero fractional values), so its bounds are integral and it always takes the int branch. |
| 2 | `false` | — | `filtered_state` yields **user** keys: `is_keyed_element_id` ids are mapped back through `wid_key_map` before being put in the dict, so an unkeyed widget's `$$ID-<hash>-None` never surfaces as an `f_*` key and `filter_reset` cannot try to delete a reserved id. Also checked `_LAST_TRIGGERED-widget-key` does not start with `f_`. |
| 3 | `low` | patch | CONFIRMED as a doc-only defect: `filter_reset`'s docstring conflates the already-instantiated guard with the value-vs-range check. The frozen rule (never reset by writing) is honoured; only the stated reason is imprecise. |
| 4 | `false` | — | REFUTED. The matrix's STALE row is a *shrunk domain after a rebuild*, which is exactly when a persisted value falls outside the new bound; the function fires there (measured: seeding native `(0.4,1.0)` against an axis bound of `15.686..100` deletes it). "Always inside the previous axis" describes a run where nothing changed. |
| 5 | `false` | — | REFUTED. `(5.0,6.4)` and `(5.0,5.4)` never reach `_span_divisor`: the int branch requires `lo == int(lo) and hi == int(hi)`, both measured False. The zero-step scenario needs a non-integral span in the integral branch, which the guard excludes. |
| 6 | `false` | — | REFUTED, and the direction is inverted: `set(FILTER_FIELDS) - set(main's precheck) == empty`, so `main()` already fail-fasts on a strict **superset** of the filter fields (it adds `TOOLTIP_FIELDS`). No one-line settings edit turns this into a mid-render `ValueError`. |
| 7 | `low` | patch | PARTLY CONFIRMED. Asserting "all stub polygons" against a 43-polygon stub is the correct substitution for AC1's 791 — the invariant is "nothing hidden", not the number. But `_drawn()` addressing `layers[0]` positionally is a real inconsistency: pass 1's own fix identified layers **by id**, and this section's key guards still index. |
| 8 | `medium` | patch | CONFIRMED gap. Every assertion in the section is existence/order over the flattened sidebar subtree. Replacing `with st.expander(...)` with a bare container, or hoisting the reset button out of it, leaves all 26 checks green while the PASS line reads "rendered expander holds one slider per bounded field". |
| 9 | `high` | patch | CONFIRMED, and reproduced independently: for `pct_vacant` the axis round trip gives hi `0.3964497041420118` against a bound of `...86`, so a reader dragging **only the left** handle yields 21 precincts where the exact bound yields 22 — `3041`, the sole holder of that field's maximum, disappears behind a handle that *displays* the same `39.6%`. The tolerance added in loopback 1 bought inertness for an untouched slider but not inclusivity at an endpoint. Same field family, 5 of 28 shares drift; the other 3 checked are bit-exact. |
| 10 | `false` | — | REFUTED. With `DEFAULT_DISTRICT_SELECTION` non-empty the hint is suppressed, so `_captions == []` is the live branch and it is a strict emptiness check: any added caption makes both alternatives false and fails the assert. |
| 11 | `low` | reject | The structural half of the reachability guard is sound and independently confirmed (all 32 fields, `(max-min)/step` integral). The drag half duplicates the untouched-bound case already pinned; the defect it aimed at is closed by the step rule, which has its own guard. |
| 12 | `low` | reject | Q2a as frozen says a hidden precinct "stays in the panels' index", which is what is asserted. The tooltip/panel contract is untouched code (`decorate`, `_detail_panels`, `build_deck`'s tooltip arg), and the panel path is exercised by ~25 renders below the abort once that abort is resolved. |
| 13 | `maybe-false` | defer | Whether the ~25 below-abort renders need updating for 33 new sidebar elements cannot be settled: that region never executes while `TOOLTIP_FIELDS` is empty, which the plan freezes as intended. Settled by running the suite with the abort neutralised (done for coverage-loss only, pass 1) — the full-green state is a separate, pre-existing blocker. |
| 15 | `low` | patch | CONFIRMED. `src/settings.py`'s comment asserts "Nothing else in the app keys a widget"; `src/dashboard.py` keys the chart `precinct_map`. False clause, and it is the sentence used to justify the reset sweep's width. |
| 16 | `medium` | patch | CONFIRMED severity mismatch, in code this plan prescribed. When a mask is active, one polygon whose properties lack `NewPrcnt` raises `ValueError` and kills the whole map, though every other join consumer treats a missing key as merely unmatched (`layer_keys` uses `.get(...,"")`). A record that cannot name its precinct is the same unprovable case the frozen matrix already says is **hidden** ("a polygon with no CSV row is hidden by a narrowed field"). |
| 14 | `low` | reject | The finding's fix is to edit this build's plan, which step-04 excludes from routing. Its one true observation — the pass-1 triage heading counted rows before they existed — is corrected below as orchestrator hygiene, not a code change. |
| 17 | `low` | reject | The reviewer itself classes this as fragility rather than violation: both behaviours are stated plan constraints, the default path is verified live (`visible is None` ⇒ `visible_records` returns the caller's own list object), and no defect follows. The one clause checked and found false: `visible_precincts` and `filter_sliders` read the **same** `rows` list object `main()` loaded once at `:46` — there is no second CSV read per render inside the run, so the "byte-identical across the two reads in one run" invariant cannot diverge within a render. |

Kept findings processed as patches (pass 2): P1 membership tolerance in `visible_precincts`; P2 expander-subtree containment; P3 `visible_records` hides a stray keyless record and raises only on an all-missing payload; P4 deck reads by layer id; P5 two false comments corrected in `src/settings.py` and `filter_reset`. All five verified by the orchestrator: PASS 53 → 55 with no name lost, `3041` survives a left-handle drag on `pct_vacant` (was hidden), mixed-payload and all-missing behaviours measured directly, and hoisting the widgets out of the expander in `src/dashboard.py` fails the new containment check (`AssertionError: []` — 0 sliders inside, 32 in the sidebar). Frozen block re-verified byte-identical to `c25ee34` after line-anchored extraction; an earlier unanchored comparison had sliced into this section's own quoted marker text and was discarded.


Pass 1 (review: quick, lens `quick`, model same as session; diff `/tmp/dashboard-range-filters-review.diff`, 47 kB). 14 findings reported → 4 kept, 10 refuted.

| # | Verdict | Route | Evidence |
|---|---------|-------|----------|
| 1 | `high` | bad_plan | CONFIRMED. `st.slider`'s `format` is a printf string, so `%.1f%%` renders the raw value: a share of `0.4` displays `0.4%` where `legend_html`'s `format_value(0.4, True)` says `40.0%`. Measured 28 of the 32 bounded fields are shares. Root cause is this plan's own Design Notes, which prescribed `"%.1f%%"` on the raw 0-1 value. |
| 2 | `high` | bad_plan | CONFIRMED. `canvass_attempts` gets int dtype with `step = max(1, round(613/100)) = 6`; rc-slider aligns values to `min + n*step`, so the far-right handle reports **612**, not the bound 613. `visible_precincts` compares with exact float equality, so a slider visually at full range registers as narrowed and hides the one row at 613 — violating the frozen "Default state = zero precincts hidden". `strong_no` (37/1) and `response_count` (135/1) divide evenly by luck. |
| 3 | `low` | patch | PARTLY CONFIRMED. The claim "a stale LOW is never deleted" is **false** — seeding `f_x=(2.0,40.0)` against bound `(10.0,50.0)` deletes the key. But the test's two seeds both have `lo == 0.0`, so the `< lo` branch is genuinely never exercised. |
| 4 | `low` | patch | CONFIRMED as a doc-accuracy defect, not a bug. `AppTest`'s `_AppTestSessionState` does bypass `SessionState.__setitem__`'s already-instantiated guard (verified: a post-run write neither warns nor raises), so `clear_filter_state` is harmless. Its stated reason is wrong (see #5) and its key sweep is unbounded. |
| 5 | `false` | — | REFUTED as stated, and the opposite holds: deleting a key *during* a run is clean (verified: in-run `del` → full range, no exception, later `set_value().run()` fine), while deleting a live widget's key **after** a run raises `KeyError: st.session_state has no key "$$ID-…-f_x"` (reproduced). The workaround is correct for the case that actually arises; only its docstring's explanation was imprecise. |
| 6 | `false` | — | REFUTED. Reproduced the reviewer's scenario (a `f_`-prefixed key holding `None`): `for k in st.session_state` enumerated it, deleted it, and the rerun raised nothing. |
| 7 | `false` | — | REFUTED. `assert 0 < len(_got_n) < len(_FILTER_CODES)` is the intended "something was hidden" bound, not "one fewer"; 15 of 43 satisfies it and 43 would fail it. The reviewer described a different assertion than the one at `:829`. |
| 8 | `medium` | patch | CONFIRMED gap. `## Boundaries & Constraints` freezes "Do not filter the council overlay layer", but every deck check in the new section reads `layers[0]` only. No test would notice a change that dropped overlay records. |
| 9 | `low` | patch | CONFIRMED. `assert not [c.value for c in _at_f.sidebar.caption if "filter" in c.value.lower()]` passes when no caption exists at all, so it polices the keyword rather than the absence. |
| 10 | `false` | — | REFUTED. `status`/`review` frontmatter transitions are step-03/step-04 protocol, and `## Implementation Notes` sits outside `<frozen-after-approval>`; the matrix and constraints are unmodified. The one true part — an empty `## Plan Change Log` — is fixed by this pass. |
| 11 | `false` | — | REFUTED. `domain_is_share` is False for all three integer fields, so `elif data_type == "integer": "%d"` is live and the assertion proves the branch that runs, not a dead one. |
| 12 | `defer` | defer | Real but pre-existing and negligible: `load_rows()` was already uncached at `6397d65` (this change did not introduce it), and the added scans are ~32 × 820 ≈ 26 k float parses per render, single-digit milliseconds on 820 rows. Fixing it properly means caching the CSV read, which is outside this intent. |
| 13 | `false` | — | REFUTED on both halves. `render_filters` installs the spy at `tests/test_dashboard.py:707` (`dashboard.st.pydeck_chart = chart`), and `_offline()` never replaces `pydeck_chart`, so restoring `_ORIG_FILTER[:3]` restores exactly what it changed. |
| 14 | `false` | — | REFUTED. `_slider_for()` looks each slider up **by** `label_for(...)` and requires exactly one match, so the emitted widget's label channel is asserted; and the `FILTER_FIELDS` equality mirrors the frozen order spec, with `len == 41` and the per-field `_populated_range` sweep as the independent halves. |

## Verification

**Commands:**
- `uv run python tests/test_dashboard.py` — expected: **64 `PASS`** lines above the known abort
  (27 at baseline), still failing with `AssertionError: Precinct {NewPrcnt}` — the assertion
  itself, unmodified, now at `tests/test_dashboard.py:1588`. The abort is expected and must not be
  chased; a green exit is not achievable while `TOOLTIP_FIELDS` is empty.
- `uv run streamlit run src/dashboard.py` — expected: "Filter precincts" expander, reset button
  first, then 32 sliders at full range below the district menu; share sliders reading WHOLE percent
  (e.g. `0%`…`100%`, `0%`…`40%` for `pct_vacant`, `15%`…`100%` for `2026_gov_percent_Hinojosa`) with
  step-1 handles; count sliders reading bare integers (`0`…`613`).
- `git diff --numstat 6397d65 -- src tests` — expected: 5 files, pure additions in `src/settings.py`,
  `src/utils/streamlit.py` (new) and `tests/test_dashboard.py`; exactly **4 deleted lines** elsewhere
  — the `build_deck` call in `src/dashboard.py` rewritten to wrap `fc`, and `format_value`'s two
  exact-band lines plus `domain_is_share`'s in `data_layer.py`, replaced by the `SHARE_TOLERANCE`
  forms (545a5b7). `git status --porcelain data` empty.

**Manual checks:**
- Narrow a slider, watch polygons vanish; click reset, watch **the thumbs as well as the map** return
  with no warning. Drag a share handle and confirm it snaps to whole points and its label has no
  decimals. The legend under the map keeps one decimal (`40.0%` against a handle reading `40%`) —
  same scale, not the same string; a whole-point handle cannot express the legend's fraction.
- Narrow two sliders, reset, then move one of them again: the other must come back at its full range
  rather than resurrecting its old narrowed pair (the loopback-4 symptom).
