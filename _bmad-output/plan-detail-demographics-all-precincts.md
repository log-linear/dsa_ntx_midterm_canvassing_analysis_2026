---
title: 'Detail demographics for every precinct in the DFS export'
type: feature
ticket: ''
created: '2026-11-22'
status: built
baseline_revision: '7b38e3a709630f671064c4fbc6c2b5817ae87afb'
route: full
route_source: auto
risk: medium
review: quick
review_source: pinned
lenses_ran: [quick]
review_loop_iteration: 1
context:
  - '{project-root}/AGENTS.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The detail page shows demographics only for the 85 precincts a canvass workbook
named. Clicking any other polygon renders "Precinct … has no data in this research extract" even
though the extract already joins `data/raw/dfs-export-precinct-20261108/data.csv` (796 precinct
rows). The pipeline throws that coverage away by keeping only rows that survived the `.ods` union.

**Approach:** Widen the extract's row universe from "precincts a canvass sheet named" to
"precincts the VTD crosswalk knows", giving each the DFS demographics of the census VTD covering
most of it — the attribution rule the pipeline already applies, same grain, so the existing 85
rows do not change. The detail panel then resolves a row for every precinct it can reach, with no
new fields and no new join.

## Decisions

- **Row universe = crosswalk only (option a).** "All precincts in `data.csv`" means every county
  precinct the VTD crosswalk can attribute to a DFS row: 820 precinct codes, 704 of 791 polygons.
  The 87 polygons with no crosswalk entry and the 35 DFS rows no precinct code claims stay
  uncovered and unemitted respectively — an unavailable attribution reads as "no data", never as
  borrowed demographics.
- **Token budget accepted over length (keep full plan).** The plan is one user-facing goal; the
  Code Map and Verification density that pushes it past 1,600 tokens is deliberate, because the
  DFS `name`-vs-VTD collision is the one mistake that would silently corrupt the research record.

## Boundaries & Constraints

**Always:**
- Attribution goes through `dallas_vtd_to_county_precinct.csv` (`dallas_county_precinct_id` →
  `census_vtd_geoid`) then DFS `source_ref`. Verified: all 795 crosswalk geoids are DFS
  `source_ref` values.
- One row per precinct, chosen by the existing fullness-then-`share_of_county_precinct` winner
  rule (`dedupe_output_by_precinct()`).
- `data/precinct_data.csv` keeps its exact 120-column header and order.
- The panel's 26 authored `DETAIL_FIELDS` and 9 `NO_DATA_FIELDS` are unchanged; the displayed 17
  stay data-driven.
- Rebuild `build_precinct_data.py && build_data_dictionary.py`, in that order, after copying both
  `data/*.csv` aside. Row counts in descriptions come only from `reconcile()`. `data/raw/` is
  read-only.

**Never:**
- Do not key a precinct off DFS `name`. `source_ref == "48113"+name` and
  `census_vtd_geoid == "48113"+census_vtd_id`: `name` is a **VTD** identifier that coincides with
  a county precinct code for 59 of the 85 and describes different ground when it does — precinct
  3011 reads 3033 people by `name`, 11251 by the crosswalk.
- Do not touch `CHOROPLETH_FIELDS`, `TOOLTIP_FIELDS`, `DETAIL_FIELDS`, `NO_DATA_FIELDS`, or add
  fields/columns.
- Do not re-add `dashboard.py`'s commented-out captions and do not touch
  `tests/test_dashboard.py:1384` or anything below it — the known failure stays the only one.
- Do not touch `choose_shift()` / the District 2 alignment repair. Do not commit.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| In crosswalk, absent from the `.ods` union | `1044`, `3111` | New row: dominant-VTD DFS demographics; canvass and workbook columns blank | None — this is the added population |
| Precinct already in the extract | all 85 existing codes | Byte-identical on every column (verified: 0 of 85 change) | None |
| Precinct maps to several VTDs | 40 codes, up to 4 VTDs | Fullest wins, tie-broken by largest share | None |
| VTD's DFS cells empty | DFS blank = "no figure", never 0 | Blanks stay blank; `pct_renter_occupied` blank where `pct_owner_occupied` blank (3 of 735) | Count and report; never invent |
| Polygon with no crosswalk entry | 87 of 791 (`30A4`, `2013`, …) | No row: keeps today's "no data in this research extract" info path | Existing `st.info`, unchanged |
| Field blank across all rows | the 9 `NO_DATA_FIELDS` | Panel stays 17 metrics for every precinct | `detail_panel_fields()`, as today |
| Extract precinct the layer omits | 116 of 820 (incl. `1046`) | Not clickable; reachable via the offline selectbox | Existing `unmatched` report |

</frozen-after-approval>

## Code Map

- `build_precinct_data.py:779` `by_geoid` (DFS keyed `source_ref`), `:796` `by_precinct`
  (crosswalk keyed `dallas_county_precinct_id`) — both indexes already exist; reuse them.
- `build_precinct_data.py:819-852` union→crosswalk→DFS join + `dedupe_output_by_precinct()` (copy
  its winner rule), `:861-884` comb/2026 general joins that run **after** it keyed on
  `PRECINCT_COL`, `:886` writer. New rows must be appended before the result joins so official
  results fill them too, and after both dedupes so fullness/alignment scoring is untouched.
- `build_precinct_data.py:596` `complement()` computes `pct_renter_occupied`; `:612-655`
  `response_count()` / `response_weighted_ratio()` read `.ods` cells only and stay blank for added
  rows.
- `build_precinct_data.py:1-60` module docstring steps 4-5 + "ONE ROW PER PRECINCT" — describe the
  widened universe and the `name` trap.
- `dashboard.py:329` `join_index()` keys `dallas_county_precinct_number`; `:799-801` click
  resolution; `:360` `detail_panel_fields()`; `:467` `detail_records()`; `:675` `_detail_block()`.
  `NewPrcnt` and `dallas_county_precinct_number` are both unpadded 4-digit codes, so the app needs
  **no** lookup change — widening the CSV is what moves the panel.
- `dashboard.py:1-16`, `:85-87`, `:204-211` — docstring prose asserting the "canvassed extract"
  framing; correct the words only.
- `build_data_dictionary.py:30` `DFS_DICT`, `:518` `JOIN_NOTE`, `:625` `reconcile()`.
- `tests/test_dashboard.py` counts that move: `:76-78`, `:305-319`, `:453-455`, `:697-706`,
  `:769-776`, `:801-808`, `:885`, `:1446`, `:1452`.

## Tasks & Acceptance

**Execution:**
- [ ] `build_precinct_data.py` -- after both dedupes and before the comb/2026 result joins, add
  every crosswalk precinct code not already present: best VTD by the existing fullness-then-share
  rule, copy that DFS row's columns, leave `.ods`-derived and canvass columns blank, then compute
  `pct_renter_occupied`. Report added count, codes with no DFS row, and blank-demographic codes on
  stdout.
- [ ] `build_precinct_data.py` -- update the docstring pipeline steps and the ONE ROW PER
  PRECINCT note.
- [ ] `dashboard.py` -- correct only the stale docstrings/comments; change no logic unless a check
  proves a gap.
- [ ] `build_data_dictionary.py` -- regenerate; fix any inherited DFS description that misstates
  grain in `MANUAL`/`JOIN_NOTE`, never in the CSV.
- [ ] `tests/test_dashboard.py` -- derive the moved counts from the rebuilt extract instead of
  hardcoding, and add checks for the matrix rows above (the added population renders the same 17
  labelled metrics, values where the VTD has figures and the no-data line where it has none, with
  the blank rows named rather than filtered away; `1046` unchanged; a crosswalk-less polygon still
  takes the info path **on the rendered app's `st.info` channel**, not via a direct
  `detail_records()` call). Derive counts by recomputing them from the features and the extract,
  never as an algebraic identity of the quantity under test. Nothing at or below `:1384`.

**Acceptance criteria:**
- Given the rebuilt extract, when the panel opens for a crosswalk precinct no workbook named, then
  the panel renders the same 17 labelled metrics -- labelled, no raw field name, no traceback --
  each showing its value where the dominant VTD's DFS row carries one, and the no-data line where
  that row is blank. Blanks are never invented as `0`: the frozen matrix's "VTD's DFS cells empty"
  row is the governing rule, so a precinct whose VTD carries no figures renders 17 blanks and is
  correct, not a defect. The build names those precincts on stdout and the test names them too.
- Given the rebuilt extract, when `join_precincts()` runs on the live layer, then matched polygons
  go from 84 to 704 of 791, and the 87 crosswalk-less precincts are the only polygons without a row.
- Given the saved pre-rebuild CSV, when diffed against the rebuild, then all 85 original rows are
  unchanged on all 120 columns and the header is identical.
- Given all 820 rows, when `detail_panel_fields()` runs, then it returns the same 17 fields and
  `NO_DATA_FIELDS` is still 9.
- Given the suite, when it runs, then every reachable check passes except the single known
  caption failure at `:1384`.

## Plan Change Log

### 1 — 2026-11-22, loopback from Step 04 review (route: bad_plan, `review_loop_iteration: 1`)

**Triggering finding.** Review finding #1: AC1 read "17 labelled metrics render with real values
and no 'no data' line", but the frozen matrix above it already says the opposite for the same
population — "DFS blank = 'no figure', never 0 … Blanks stay blank; `pct_renter_occupied` blank
where `pct_owner_occupied` blank (3 of 735)". `2607`, `3111` and `4116` are crosswalk-only precincts
whose dominant VTD's DFS row carries no figures at all, so their panel is 17 blanks and that is
correct behaviour. AC1 was unsatisfiable as written, and the previous implementation responded by
building its test set with the property it then asserted
(`FULL = [c for c in ADDED if all(... is not None ...)]`), which passes while concealing the three
exceptions — `3111` being one of the plan's own named exemplars.

**Amended.** AC1 now states what the panel must guarantee (17 labelled metrics, no raw field name,
no traceback; value where the VTD has one, the no-data line where it does not; never invent a 0) and
requires the blank rows to be **named** by both the build's stdout and the test. The
`tests/test_dashboard.py` Execution bullet additionally requires: counts recomputed from the
features and the extract rather than expressed as an algebraic identity of the value under test, and
the crosswalk-less polygon check driven through the rendered app's `st.info` channel.

**Known-bad state now avoided.** A green suite built on a filtered sample; a vacuous assertion that
returns `[]` because the input is `None` by construction; a "report" line whose predicate can never
fire; two spellings of one source mapping.

**KEEP — verified good, must survive re-derivation.**
- `crosswalk_only_rows()` runs **after both dedupes and before the comb/2026 result joins**, reuses
  the existing `by_precinct` / `by_geoid`, and appends one row per crosswalk code absent from the
  canvass union. Scoring must be the builder's own rule, byte-for-byte:
  `(fullness(row, counted), share if share is not None else -1.0)`. Do NOT substitute
  `as_number(share) or -1.0` — that maps a recorded `0.0` (23 crosswalk rows hold one) to "missing".
- Apply `complement()` to `pct_renter_occupied` **before** scoring the candidate, as `:836` does.
- Attribution only through `dallas_county_precinct_id` → `census_vtd_geoid` → DFS `source_ref`;
  never DFS `name`.
- Winning DFS row copied verbatim; `.ods`-derived, canvass and provenance columns left blank;
  no new fields, no header or column-order change.
- Verified outcomes to reproduce: exit 0; **820 rows over 820 precincts, 120 columns**; 85 canvassed
  + 735 added; the 85 originals **byte-identical on all 120 columns** vs `/tmp/pd.before.csv`;
  `704 of 791` polygons matched, `87` crosswalk-less, `116` extract precincts the layer omits
  (incl. `1046`); `detail_panel_fields()` still 17, `NO_DATA_FIELDS` still 9; dictionary 120 fields
  with `UNDOCUMENTED (fallback) : []`.
- `dashboard.py`: docstrings and comments only, no logic change. Its `domain_for` example and the
  `NO_DATA_COLOR` "707 precincts" count are stale and must be corrected here (they moved with the
  widening: `2024_kamala` now spans 0.0–1.0 because precincts 1301/1742 really recorded 0 and 1
  votes; polygons without a row are 87, not 707).
- `build_data_dictionary.py`: edit `MANUAL` / `JOIN_NOTE` and regenerate, never the CSV.
- Tests: keep the header-guarded `BLANK_BY_CONSTRUCTION` (real column names only — `registered` does
  not exist; the canvass-period column is `2026_registered`); keep matrix rows 3 and 4, which had no
  covering test at all, recomputed independently with `1315`/`1724` as the fullness-over-share
  witnesses and the 9 fullness ties as the share tie-break witnesses; keep the plan-baseline
  120-column zero-drift check; keep the legend check comparing `<span>` **labels**, not substring
  membership of the whole block (`'0.0%'` is a substring of the now-legitimate `'100.0%'`).

**Also fix in this re-derivation** (review findings routed to patch; moot as separate edits because
the code is being re-derived):
1. The blank-demographic stdout report must score demographic columns, not all 58 DFS columns —
   `district_id`, `name`, `body`, `state`, `source_ref` are non-blank on every DFS row, so the old
   predicate printed `0 []` over data with 2 fully-blank rows. Name `2607`/`3111`/`4116`.
2. Print counts for both report lines so "checked, none" is distinguishable from "cannot fire".
3. The duplicate-drop audit line printed `-724` because `fanout_rows` is captured before the
   widening; report the fan-out dedupe over the rows it actually saw.
4. `JOIN_NOTE["source_ref"]` said every figure describes the VTD "that covers most of the precinct";
   2 of 820 rows land on a minority VTD where fullness wins. State the real rule.
5. `MANUAL["census_vtd_id"]` still says "a precinct appears on one row per VTD" — false for this
   extract (820 rows / 820 precincts). This is the grain-misstatement the plan already tasked.
6. DFS `name`'s inherited description ("The seat's name, for example Hudson County or Ward 3")
   misstates its grain and is the exact column the first **Never** rule protects; correct it in
   `MANUAL`/`JOIN_NOTE`.
7. `assert_registered_agreement`'s docstring claims "none of ours does" disagree on `Registered`.
   `union_keys` is still the 85 canvassed codes, so 45 emitted crosswalk-only rows ship a
   contradiction silently (`1305`: governor/senate/county `1840` vs city `0`). Correct the claim and
   report the count; do not silently widen the abort.
8. The matched-polygon check must not reduce to `len(keys & CROSSWALK_CODES)` — an identity of the
   value under test. Recompute from the features and state the count.
9. The crosswalk-less polygon check must assert the rendered `st.info` path, not
   `detail_records(None, ...) == []`.
10. Keep one field→source map for the 2026 columns, derived from `bpd.GENERAL_CONTESTS`, instead of
    a prefix-routing helper plus a 4-entry dict.

## Review Triage Log

| # | Finding | Verdict | Evidence and route |
|---|---------|---------|--------------------|
| 1 | `tests/test_dashboard.py` `FULL` block — AC1 unmet for 3 added precincts; the test filters to the rows that satisfy the property it then asserts | **medium** | Real. `FULL` is built by filtering `ADDED` on the very `all(... is not None)` test being asserted, so it cannot fail. 732 of 735 added rows populate all 17 panel metrics; `2607`, `3111`, `4116` populate none and render 17 em-dashes. `3111` is the plan's own exemplar for the added population. Route: patch the test to partition and report the empty set; AC1's wording amended in the Plan Change Log (non-frozen). |
| 2 | `build_precinct_data.py:846` — the blank-demographic-block report can never fire | **medium** | Real. `dfs_cols` is the whole DFS header (58 columns) and includes `district_id`, `name`, `body`, `state`, `source_ref`, all non-blank on every one of the 796 source rows, so `any(...)` is always true and stdout prints `0 []` over data where 2 precincts carry no DFS figure at all. Matrix row 4's "Count and report; never invent" is unmet. Route: patch — score against a validated identity/provenance skip set, the way `fullness()` uses `skip`. |
| 3 | `build_precinct_data.py:844` — `no_dfs` is unfalsifiable | **false** | Checked, the bad outcome does not occur at this location. All 795 crosswalk `census_vtd_geoid` values are DFS `source_ref`s (verified: 0 missing), so the list is legitimately empty; `hit_dfs` is live code that fires on a future geoid loss. An empty report is correct behaviour, not a dead check. |
| 4 | `build_precinct_data.py:1004` — the duplicate-drop audit line prints a negative count | **medium** | Real, reproduced in build stdout: `rows dropped as duplicate precinct (-724 after joining; 820 precincts x VTDs = 96 rows)`. `fanout_rows` is captured at `:938` before `rows.extend(added_rows)`, so the subtraction now spans rows the dedupe never saw. Developers meet this on every build. Route: patch. |
| 5 | `build_data_dictionary.py:524` `JOIN_NOTE["source_ref"]` — claims every figure describes the VTD covering most of the precinct | **low** | Real. Precinct `1315` is attributed to a VTD covering 0.115 of it (sibling 0.884) and `1724` to 0.144 (sibling 0.851) — the two cases fullness correctly overrides share for, which the test's own `_FULLNESS_WINS` names. 2 of 820 rows, but the sentence is a research-record field description. Route: patch the wording to state the actual rule. |
| 6 | `build_data_dictionary.py` — `name` still described as "The seat's name, for example Hudson County or Ward 3" | **medium** | Real. The column holds VTD identifiers (`003700` for precinct `1742`), and this is the exact column the plan's first **Never** rule protects — the widening puts it on 735 more rows while nothing in the dictionary says so. Route: patch. |
| 7 | `build_data_dictionary.py` `MANUAL["census_vtd_id"]` — "a precinct appears on one row per VTD" | **medium** | Real, and a direct miss of the plan's own bullet "fix any inherited DFS description that misstates grain". The shipped extract is 820 rows / 820 unique precinct codes; both dedupes run before the widening. The one field that documents the fan-out is the one left describing the old grain. Route: patch. |
| 8 | `build_precinct_data.py:576` — `assert_registered_agreement` guards only the 85 canvassed codes while 45 added rows ship a contradicted `Registered` | **medium** | Real. Reproducing the guard's own logic over the emitted universe: 45 codes disagree across the four 2026 files (`1305`: governor/senate/county `1840` vs city `0`), 0 of the 85 canvassed ones do, and each ships the governor figure. The docstring's "none of ours does" is now false. Shipped value is the best-supported of the four (three agree; the city file records `0` where that contest had no votes), so this is a visibility gap, not a wrong number. Route: patch — correct the claim and report the count; whether to abort instead is a human call, raised at presentation. |
| 9 | `tests/test_dashboard.py:200-216` — the recomputed winner rule is not the builder's rule on a share of `0.0` | **medium** | Real. The test scores `as_number(share) or -1.0`, which maps a literal `0.0` to `-1.0`; the builder uses `share if share is not None else -1.0`. The crosswalk holds 23 rows with a literal `0.0` share, so the mirror reads a recorded zero as unrecorded — the exact blank-vs-zero conflation this repo forbids. Same root cause: `_vtd_candidate` omits the `complement()` pass the builder applies before scoring. Winners agree today (verified for all 33), so the suite is green by luck. Route: patch. |
| 10 | `tests/test_dashboard.py:540-546` — AC2's matched count is now an identity, not a check | **low** | Real. `stats["matched"] == len(keys & CROSSWALK_CODES)` follows necessarily from `set(index) == CROSSWALK_CODES` plus `join_precincts()`'s own definition, so it cannot fail; the old `== 84` compared an independently computed figure. The count is at least reported on the PASS line. Route: patch — recompute from the features rather than from `stats`. |
| 11 | `tests/test_dashboard.py:543-545` — the crosswalk-less info-path check is a tautology and never exercises the channel | **medium** | Real. `index.get(k)` is `None` by construction for every `k` in `keys - set(index)`, and `detail_records()` returns `[]` on its first line, so the assertion only fails if the `None` guard is deleted. The matrix row asks for the rendered `st.info` path, and AGENTS.md names this exact defect class (four shipped defects proved a Python string the browser never read). Route: patch — drive the rendered app and assert the `st.info` channel. |
| 12 | `dashboard.py:292` — `domain_for` docstring still says `2024_kamala` spans 0.51-0.85 | **low** | Real. The same diff pins `kamala == (0.0, 1.0)` and the extract confirms it; the docstring is now the only surviving copy of the retired claim and it is the worked example justifying per-field scaling. The plan tasked `dashboard.py` with correcting stale docstrings. Route: patch. |
| 13 | `dashboard.py:136` — comment still says "the 707 precincts with no value" | **low** | Real. 707 was `791 - 84`; polygons without a row are now 87. The sibling figure at `:417` was corrected in this same diff and this one was missed. Route: patch. |
| 14 | `tests/test_dashboard.py:1747-1751` / `:1691` — the frozen region at/below `:1384` is now factually wrong (`791 - 84`, `"84 of 85"`) | **defer** | Real but out of reach: the plan's frozen **Never** forbids touching `:1384` or anything below it, and the pre-existing toggle abort at `:1502` means the suite never gets there, so no check is silently passing — it is never run. Renegotiating that boundary is the human's, and it is recorded in `deferred-work.md`. |
| 15 | `build_precinct_data.py:999` — the missing-DFS line prints a bare list with no count, unlike its sibling | **low** | Real. `{sorted(added_no_dfs)}` renders `[]` for "checked, none found" and would render `[]` for a check that could not fire, so the two are indistinguishable in the log; the sibling line prints `0 []`. Folded into finding 2's patch. |
| 16 | `tests/test_dashboard.py:131-133` — two parallel field-to-source mappings for the same 2026 columns | **low** | Real. `source_codes()` routes by prefix (so an unlisted field silently falls through to the governor file) while `GEN_SOURCE` names only 4 of the 25 and is the only place the measure column is recorded; a fifth colourable 2026 field would `KeyError` in one loop and pass silently in the other. Duplicated source of truth, same class the `BLANK_BY_CONSTRUCTION` header guard was added for. Route: patch — derive one map from `bpd.GENERAL_CONTESTS`. |
| 17 | Council-district toggle ships defaulting to "No" while prompt.md:155-156 and its own test ask for "Yes" | **defer** | Pre-existing, not caused by this change, and the user chose to route it: baseline `7b38e3a` in a clean worktree aborts at the identical assertion with `['No', 'Yes']`. Owned by the council-overlay plan; the one-line fix lives in `dashboard.py`'s toggle logic, outside this plan's "correct the words only". Recorded in `deferred-work.md`. |

**Pass 2 skipped at the user's request (2026-11-22).** The Quick lens ran once, on the pass-1 tree, and produced the 17 findings above; finding #1 drove the loopback and is now fixed and verified. The re-derived pass-2 tree was instead checked directly against the plan by the orchestrator: build exit 0 with 820 rows over 820 precincts and 120 columns, 735 crosswalk-only rows added, idempotent rebuild, the 85 originals byte-identical on all 120 columns (0 differing cells), `dashboard.py`'s executable token stream identical to baseline (docstrings only), dictionary 120 fields with `UNDOCUMENTED (fallback) : []`, 80 PASS with the frozen `:1384` boundary proven untouched (highest old line touched 1380), and all 7 edge-case matrix rows covered by a test that ran and passed. No independent second review pass has examined the re-derived code — that coverage was traded for time, deliberately.

## Verification

**Commands:**
- `cp data/precinct_data.csv /tmp/pd.before.csv && cp data/data_dictionary.csv /tmp/dd.before.csv`
  -- expected: copies exist before any rebuild.
- `uv run python build_precinct_data.py` -- expected: exit 0; stdout reports 820 output rows /
  820 precincts over 120 columns, the added-precinct count, and no missing-DFS surprises.
- `uv run python build_data_dictionary.py` -- expected: exit 0, 120 fields documented, `UNDOCUMENTED
  (fallback)` stays `[]`.
- Python diff of the 85 original codes, old vs new CSV -- expected: zero differing cells.
- `uv run python tests/test_dashboard.py` -- expected: `PASS` lines across the reachable suite,
  ending in the one known failure at `tests/test_dashboard.py:1384`.
- `uv run streamlit run dashboard.py` -- expected: clicking a never-canvassed precinct such as
  `1044` renders the 17-row metric table. `python dashboard.py` proves nothing; never use it.
