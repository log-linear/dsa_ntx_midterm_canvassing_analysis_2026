"""Edge-case matrix checks for dashboard.py -- `uv run python tests/test_dashboard.py`.

Plain asserts, one pass line per check, exit 0 when all hold.  Run from the
repo root.
"""

from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

import dashboard  # noqa: E402

PASS = 0


def ok(name: str, detail: str = "") -> None:
    global PASS
    PASS += 1
    print(f"PASS  {name}{('  [' + detail + ']') if detail else ''}")


def is_painted(color: list[int]) -> bool:
    """Does this fill put pixels on the screen?  Any alpha above 0, any colour."""
    return len(color) == 4 and color[3] > 0


def grammar_ok(expr: str, where: str) -> None:
    """Reject what @deck.gl/json cannot parse: no JS, no {token} templates.

    Streamlit hands the browser every string layer prop prefixed `@@=`, and that
    prop is *parsed* as a JSON expression -- key lookups, quoted literals, `+`,
    ternary.  An arrow function throws `Unexpected "=" at character 2` and a
    `{token}` throws `Unexpected "{"`, both at render time and both invisible to
    every Python-side check.  Quoted literals are stripped first because labels
    legitimately contain parentheses.
    """
    stripped = re.sub(r'"(?:[^"\\]|\\.)*"', "", expr)
    stripped = re.sub(r"'(?:[^'\\]|\\.)*'", "", stripped)
    assert "=>" not in expr, f"{where}: arrow function is not JSON-expression syntax: {expr[:60]!r}"
    assert "{" not in stripped and "}" not in stripped, (
        f"{where}: no template placeholders in this grammar: {expr[:60]!r}"
    )
    assert "(" not in stripped and ")" not in stripped, (
        f"{where}: function calls are not allowed in JSON expressions: {expr[:60]!r}"
    )


def expect_raises(exc_type, fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except exc_type as err:
        return err
    raise AssertionError(f"expected {exc_type.__name__} and got none")


rows = dashboard.load_rows()
dictionary = dashboard.build_dictionary()
index = dashboard.join_index(rows)
labels = {f: dashboard.label_for(dictionary, f) for f in dashboard.DETAIL_FIELDS}

# --- the two universes this change is about, read from data/raw/ ------------
# Every count the plan's matrix moves is derived from these rather than typed
# in.  The extract's row universe is the set of precinct codes the VTD crosswalk
# can attribute; the population it ALREADY covered is the set of codes the
# canvass workbooks name.  Both come straight from the inputs, never from the
# extract -- an extract that dropped or invented a row must fail a check against
# the sources, not agree with itself.
import build_precinct_data as bpd  # noqa: E402

CROSSWALK_CSV = BASE / "data/raw/dallas_vtd_to_county_precinct.csv"
CROSSWALK_ID_COL = "dallas_county_precinct_id"
with open(CROSSWALK_CSV, newline="", encoding="utf-8") as _fh:
    _cw_reader = csv.DictReader(_fh)
    CROSSWALK_COLS = list(_cw_reader.fieldnames or [])
    crosswalk_rows = list(_cw_reader)
# Header guard: these literals are the attribution path the plan freezes.  A
# renamed key must fail here rather than silently shrink the expected universe
# to the rows that still match.
for _c in (CROSSWALK_ID_COL, "census_vtd_geoid", "share_of_county_precinct"):
    assert _c in CROSSWALK_COLS, f"{CROSSWALK_CSV.name} header is {CROSSWALK_COLS}"
CROSSWALK_CODES = {r[CROSSWALK_ID_COL].strip() for r in crosswalk_rows} - {""}
ODS_ROWS, ODS_COLS = bpd.read_ods_tables()
CANVASSED_CODES = {r[bpd.PRECINCT_COL].strip() for r in ODS_ROWS} - {""}
ADDED_CODES = sorted(CROSSWALK_CODES - CANVASSED_CODES)
EXTRACT_CODES = {r[dashboard.JOIN_CSV_KEY].strip() for r in rows}
assert CANVASSED_CODES <= CROSSWALK_CODES, sorted(CANVASSED_CODES - CROSSWALK_CODES)
assert CANVASSED_CODES <= EXTRACT_CODES, sorted(CANVASSED_CODES - EXTRACT_CODES)
ok("universes read from data/raw/, not from the extract",
   f"{len(CROSSWALK_CODES)} crosswalk codes, {len(CANVASSED_CODES)} canvassed, "
   f"{len(ADDED_CODES)} added")

# --- the three 2026 general files, read once and keyed by precinct code -----
# Read up here because BOTH halves of the suite need them: the UI checks derive a
# field's expected populated count from the raw source rather than from the
# extract, and the build checks below compare the joined cells cell-by-cell.
GOV_RAW = list(csv.DictReader(open(BASE / "data/raw/2026_governor_general_precinct.csv", newline="", encoding="utf-8")))
SEN_RAW = list(csv.DictReader(open(BASE / "data/raw/2026_senate_general_precinct.csv", newline="", encoding="utf-8")))
PROPS_RAW = list(csv.DictReader(open(BASE / "data/raw/2026_props_general_precinct.csv", newline="", encoding="utf-8")))
GOV_IDX = {bpd.general_code(r[bpd.GENERAL_KEY_COL], bpd.GOV_CSV): r for r in GOV_RAW}
SEN_IDX = {bpd.general_code(r[bpd.GENERAL_KEY_COL], bpd.SEN_CSV): r for r in SEN_RAW}
PROPS_IDX: "dict[str, dict[str, dict[str, str]]]" = {}
for _r in PROPS_RAW:
    PROPS_IDX.setdefault(bpd.general_code(_r[bpd.GENERAL_KEY_COL], bpd.PROPS_CSV), {})[
        _r[bpd.GENERAL_PROPS_COL].strip()] = _r
GENERAL_COLS = bpd.general_columns()
assert len(GENERAL_COLS) == 25, GENERAL_COLS


def general_source(contest, code):
    """The raw source row one 2026 contest holds for one precinct code."""
    if contest == "gov":
        return GOV_IDX.get(code)
    if contest == "sen":
        return SEN_IDX.get(code)
    return PROPS_IDX.get(code, {}).get(contest)


# ONE field -> source map for the 24 contest measures, derived from the builder's
# own GENERAL_CONTESTS rather than a second hand-written table plus a prefix-
# routing helper.  A fifth colourable 2026 field is therefore covered by every
# check at once: a hand-written map would KeyError in one loop while another
# routed it silently to the governor file.
FIELD_SOURCE = {
    target: (contest, source)
    for contest, measures in bpd.GENERAL_CONTESTS
    for source, target in measures.items()
}
assert len(FIELD_SOURCE) == 24, len(FIELD_SOURCE)
assert set(FIELD_SOURCE) <= set(GENERAL_COLS), sorted(set(FIELD_SOURCE) - GENERAL_COLS)


def raw_populated_codes(field, codes):
    """Codes among `codes` whose RAW 2026 source row carries a figure here.

    Read from data/raw/, so this is the expectation the extract is judged
    against -- not a restatement of what the extract happens to hold.
    """
    contest, source_col = FIELD_SOURCE[field]
    return [c for c in codes
            if dashboard.to_float((general_source(contest, c) or {}).get(source_col)) is not None]

# --- dictionary coverage: every field the dashboard touches is documented ----
all_needed = (
    dashboard.CHOROPLETH_FIELDS + dashboard.TOOLTIP_FIELDS
    + dashboard.DETAIL_FIELDS + dashboard.RESULTS_PANEL_FIELDS
    + [dashboard.JOIN_CSV_KEY]
)
missing = [f for f in all_needed if f not in dictionary]
assert not missing, f"undocumented fields: {missing}"
ok("dictionary covers every dashboard field", f"{len(dictionary)} entries")

assert len(rows) == len(CROSSWALK_CODES), (len(rows), len(CROSSWALK_CODES))
assert len(index) == len(rows), (len(index), len(rows))
assert EXTRACT_CODES == CROSSWALK_CODES, (
    f"the extract's universe is not the crosswalk's: "
    f"{sorted(EXTRACT_CODES ^ CROSSWALK_CODES)[:10]}"
)
ok(f"CSV is {len(rows)} rows / {len(index)} unique precinct keys, exactly the "
   "crosswalk's universe")

# --- Decision 2b: regenerated labels carry no source artifacts ---------------
ARTIFACTS = ["Pct ", " nh ", " us ", "pct ", "sq mi", " snap", "50k "]
dirty = {
    r["field_name"]: [a for a in ARTIFACTS if a in r["readable_name"]]
    for r in dictionary.values()
    if any(a in r["readable_name"] for a in ARTIFACTS)
}
assert not dirty, f"mangled labels remain: {dirty}"
# The count is reported, not asserted: the check above covers whatever
# dictionary.csv holds, so a new field cannot fail here for the wrong reason.
ok("every label free of 'Pct '/' nh '/' us ' artifacts", f"{len(dictionary)} labels")

# Decision 2b: every override in the generator must reach the CSV.  26 of the 54
# corrections carry no artifact substring and are not worked examples, so without
# this check they could regress silently -- the override dict is the source of
# truth, and the generated file is required to agree with it field by field.
import build_data_dictionary  # noqa: E402

OVERRIDES = build_data_dictionary.READABLE_OVERRIDES
unlogged = sorted(set(OVERRIDES) - set(dictionary))
assert not unlogged, f"overrides name undocumented fields: {unlogged}"
silent = {f: (OVERRIDES[f], dictionary[f]["readable_name"]) for f in OVERRIDES
          if f in dictionary and dictionary[f]["readable_name"] != OVERRIDES[f]}
assert not silent, f"overrides did not reach data_dictionary.csv: {silent}"
ok("every READABLE_OVERRIDES label landed in the generated dictionary", f"{len(OVERRIDES)} overrides")

# worked examples the human specified
EXPECTED = {
    "pct_age_18_64": "Percent Age 18\u201364",
    "not_us_citizen": "Not U.S. Citizen",
    "pct_households_snap": "Percent Households on SNAP",
    "pct_nh_white": "Percent Non-Hispanic White",
    "pct_income_under_50k": "Percent Income Under $50k",
    "population_per_sq_mi": "Population Per Square Mile",
    "pct_bachelors_plus": "Percent Bachelor's or Higher",
}
for field, want in EXPECTED.items():
    got = dashboard.label_for(dictionary, field)
    assert got == want, f"{field}: {got!r} != {want!r}"
ok("label overrides match the human's worked examples", f"{len(EXPECTED)} checked")

# the choropleth and tooltip labels were already correct upstream
CHOR_EXPECT = {
    "prop_a_city_no_canvassing_pct": "Prop A No Share (Canvassed)",
    "2024_prop_r_for": "2024 Prop R (For)",
    "2024_prop_u_against": "2024 Prop U (Against)",
    "2024_kamala": "2024 Kamala Vote Share",
    "response_rate": "Canvass Response Rate",
    "canvass_attempts": "Canvass Attempts",
}
for field, want in CHOR_EXPECT.items():
    got = dashboard.label_for(dictionary, field)
    assert got == want, f"choropleth label {field}: {got!r} != {want!r}"
ok("every choropleth and tooltip label is the readable one")

# --- blank vs zero ----------------------------------------------------------
assert dashboard.to_float("") is None
assert dashboard.to_float("   ") is None
assert dashboard.to_float("0.0000") == 0.0
assert dashboard.to_float(None) is None
ok('blank "" is no data; "0.0000" is the real value 0.0')

assert dashboard.format_value(None) == dashboard.NO_DATA_TEXT
assert dashboard.format_value(0.0) == "0.0%"
assert dashboard.format_value(None) != dashboard.format_value(0.0)
ok("blank and zero render differently")

# Units come from the field's own range, never from the size of one value.
# `canvass_attempts` is an integer 0-613; guessing per value rendered zero
# attempts as "0.0%" and one attempt as "100.0%" while 113 stayed "113".
attempts = dashboard.field_domain(rows, "canvass_attempts")
assert attempts and not dashboard.domain_is_share(attempts), attempts
assert dashboard.format_value(0.0, fraction=False) == "0"
assert dashboard.format_value(1.0, fraction=False) == "1"
assert dashboard.format_value(613.0, fraction=False) == "613"
rates = dashboard.field_domain(rows, "response_rate")
assert dashboard.domain_is_share(rates), rates
assert dashboard.format_value(0.0) == dashboard.format_value(0.0, True)
ok("counts and shares told apart by the field's range, not per value")

# a real 0.0 must take the scale minimum, not the empty no-data style
zero_field = "prop_a_city_no_canvassing_pct"
domain = dashboard.domain_for([dashboard.to_float(r.get(zero_field)) for r in rows])
assert domain and domain[0] == 0.0, domain
colored = dashboard.color_scale(0.0, domain)
empty = dashboard.color_scale(None, domain)
assert empty == dashboard.NO_DATA_COLOR == [0, 0, 0, 0], empty
assert empty[3] == 0, "no-data fill must be transparent"
assert colored != empty and colored[:3] == dashboard.COLOR_LOW, (colored, empty)
assert len(colored) == len(empty) == 4, (colored, empty)
assert is_painted(colored), f"a data-bearing fill went invisible: {colored}"
ok("0.0000 colours at the scale minimum; blank is transparent", f"domain {domain}")

# FILL_ALPHA is the single opacity knob: it reaches every colour in the ramp and
# nothing else can override it.  Under 255 by design, so the basemap stays
# legible beneath the choropleth -- set it to 255 (and update this check) only if
# a solid map is deliberately wanted.
assert 0 < dashboard.FILL_ALPHA < 255, dashboard.FILL_ALPHA
assert {dashboard.color_scale(v, domain)[3] for v in (0.0, 0.5, 1.0)} == {
    dashboard.FILL_ALPHA
}, [dashboard.color_scale(v, domain) for v in (0.0, 0.5, 1.0)]
ok("FILL_ALPHA is the one opacity knob and lands on every ramp colour", str(dashboard.FILL_ALPHA))

# The ramp is plain RGB so opacity cannot be baked into one endpoint only: a
# mismatch would truncate zip() and strip the alpha from the whole scale.
assert len(dashboard.COLOR_LOW) == len(dashboard.COLOR_HIGH) == 3, (
    dashboard.COLOR_LOW,
    dashboard.COLOR_HIGH,
)
ok("ramp endpoints are plain RGB; FILL_ALPHA is the only source of opacity")

# --- the ramp is viridis, sampled across its stops ------------------------
# Since 2026-11-24 the choropleth colours with viridis instead of a pink->red
# two-stop ramp.  Two things are under test here, because either can break while
# the map still paints a smooth purple->yellow gradient that *looks* right:
#   (1) the endpoints are viridis's own, and
#   (2) the interior follows viridis's curve rather than the straight CHORD
#       between those endpoints.  A 2-stop interpolation of the endpoints is a
#       different colormap, and the difference is only visible mid-ramp.
assert dashboard.COLOR_LOW == [68, 1, 84], dashboard.COLOR_LOW
assert dashboard.COLOR_HIGH == [253, 231, 37], dashboard.COLOR_HIGH
assert dashboard.VIRIDIS_STOPS[0][1] == dashboard.COLOR_LOW
assert dashboard.VIRIDIS_STOPS[-1][1] == dashboard.COLOR_HIGH
ok("ramp endpoints are viridis's own (68,1,84) -> (253,231,37)")

# Every stop must be reachable: `ramp_rgb` picks the bracketing pair by index,
# so a gap or an unsorted position would miscolour the map silently.
assert [t for t, _ in dashboard.VIRIDIS_STOPS] == [i / 8 for i in range(9)], (
    dashboard.VIRIDIS_STOPS
)
assert all(len(rgb) == 3 for _, rgb in dashboard.VIRIDIS_STOPS), dashboard.VIRIDIS_STOPS
ok("viridis ships 9 evenly-spaced plain-RGB stops")

# The stops land exactly, and t=1.0 folds onto the last pair instead of
# indexing past the array.
for _i, (_pos, _rgb) in enumerate(dashboard.VIRIDIS_STOPS):
    assert dashboard.ramp_rgb(_pos) == _rgb, (_pos, dashboard.ramp_rgb(_pos), _rgb)
assert dashboard.ramp_rgb(0.0) == dashboard.COLOR_LOW
assert dashboard.ramp_rgb(1.0) == dashboard.COLOR_HIGH
assert dashboard.ramp_rgb(-0.5) == dashboard.COLOR_LOW, "t below 0 must clamp"
assert dashboard.ramp_rgb(1.5) == dashboard.COLOR_HIGH, "t above 1 must clamp"
ok("ramp_rgb hits every stop and clamps out-of-range positions")

# The discriminating check: mid-ramp must be viridis's teal, NOT the chord.
# Computed from COLOR_LOW/COLOR_HIGH here so the assertion cannot be satisfied
# by the same constant it tests.
_chord = [
    round(a + (b - a) * 0.5)
    for a, b in zip(dashboard.COLOR_LOW, dashboard.COLOR_HIGH)
]
_mid = dashboard.ramp_rgb(0.5)
assert _mid != _chord, f"a 2-stop chord passed as viridis: {_mid} == {_chord}"
assert max(abs(x - y) for x, y in zip(_mid, _chord)) > 40, (_mid, _chord)
assert _mid == [33, 144, 141], _mid
ok("the scale samples viridis's stops, not a purple->yellow chord",
   f"t=.5 -> {_mid}, 2-stop chord -> {_chord}")

# Perceptual monotonicity is the reason viridis replaced pink->red: lightness
# must rise across the ramp, so the map reads in order even in greyscale or to a
# reader who cannot separate the hues.  Checked on the relative-luminance
# approximation rather than hue, which is the property that was asked for.
def _lum(rgb):
    return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]


_samples = [dashboard.ramp_rgb(i / 200) for i in range(201)]
_lums = [_lum(c) for c in _samples]
assert all(b >= a - 1e-9 for a, b in zip(_lums, _lums[1:])), [
    round(a, 1) for a, b in zip(_lums, _lums[1:]) if b < a - 1e-9
][:5]
assert _lums[-1] > _lums[0], (_lums[0], _lums[-1])
ok("ramp lightness is monotonic end to end (greyscale-legible)",
   f"{_lum(_samples[0]):.0f} -> {_lum(_samples[-1]):.0f}")

# Alpha stays outside the ramp: viridis's stops are RGB, so a colour taken from
# anywhere on the curve still gets exactly FILL_ALPHA, and no-data still short-
# circuits before the ramp is consulted at all.
for _v in (0.0, 0.25, 0.5, 0.75, 1.0):
    assert len(dashboard.color_scale(_v * domain[1], domain)) == 4, _v
    assert dashboard.color_scale(_v * domain[1], domain)[3] == dashboard.FILL_ALPHA
assert dashboard.color_scale(None, domain) == [0, 0, 0, 0]
ok("viridis stops are RGB only: FILL_ALPHA still reaches every painted fill")

# Borders are gone, so a no-data precinct now paints literally nothing.  What
# still has to hold is that those invisible polygons are pickable (the fill
# sublayer is asserted above) and that the dead border colour was not left
# behind as a second source of truth.
assert not hasattr(dashboard, "LINE_COLOR"), "LINE_COLOR outlived the borders"
assert dashboard.NO_DATA_COLOR == [0, 0, 0, 0], dashboard.NO_DATA_COLOR
ok("no-data precincts stay fully empty regardless of FILL_ALPHA: no fill, no border")
assert dashboard.color_scale(None, domain) == [0, 0, 0, 0], "no-data must not inherit FILL_ALPHA"

# per-field normalization, never a fixed 0-1.  `2024_kamala` spanned 0.51-0.85
# over the 85 canvassed rows; widening the universe put 481 precincts on the
# field, and among them precincts 1301 and 1742 really recorded 0 and 1 votes --
# recorded, not blanked into zeros.  So the domain moved and no typed-in range
# survives it: the expectation is recomputed from the extract's own populated
# values here, which is a different code path from `domain_for`'s.
def _populated_range(field, source=rows):
    vals = [dashboard.to_float(r.get(field)) for r in source]
    pop = [v for v in vals if v is not None]
    return None if not pop else (min(pop), max(pop))


kamala = dashboard.domain_for([dashboard.to_float(r.get("2024_kamala")) for r in rows])
assert kamala == _populated_range("2024_kamala"), (kamala, _populated_range("2024_kamala"))
# The 0 and the 1 are real recorded figures carried by crosswalk-only precincts,
# and are NOT present among the canvassed 85: the widening moved the range
# honestly rather than inventing an endpoint.
_lo = sorted(p for p in index if dashboard.to_float(index[p].get("2024_kamala")) == 0.0)
_hi = sorted(p for p in index if dashboard.to_float(index[p].get("2024_kamala")) == 1.0)
assert _lo and _hi, (kamala, _lo[:3], _hi[:3])
assert not set(_lo) & CANVASSED_CODES and not set(_hi) & CANVASSED_CODES, (
    f"a canvassed precinct recorded an endpoint: {sorted(set(_lo) | set(_hi))}")
assert set(_lo) <= set(ADDED_CODES) and set(_hi) <= set(ADDED_CODES)
# "never a fixed 0-1" still has to be true of a field, so it is asserted on one
# whose populated range is strictly inside: the default metric tops out at the
# no-rate of responders, and it is recomputed the same way.
_default_dom = dashboard.domain_for(
    [dashboard.to_float(r.get(dashboard.DEFAULT_CHOROPLETH)) for r in rows])
assert _default_dom == _populated_range(dashboard.DEFAULT_CHOROPLETH), _default_dom
assert 0.0 <= _default_dom[0] < _default_dom[1] < 1.0, _default_dom
assert _default_dom != kamala, (_default_dom, kamala)
assert dashboard.color_scale(kamala[0], kamala) == dashboard.color_scale(0.0, domain)
ok("each field scales on its own populated min/max", f"2024_kamala {kamala}, "
   f"default {_default_dom}, {len(_lo)} real zeros / {len(_hi)} real ones")

# --- Decision 1c: the detail panel ----------------------------------------
panel = dashboard.detail_panel_fields(rows)
assert len(panel) == 17, panel
assert len(dashboard.NO_DATA_FIELDS) == 9
assert not set(panel) & set(dashboard.NO_DATA_FIELDS), "no-data field in panel"
assert set(panel) | set(dashboard.NO_DATA_FIELDS) == set(dashboard.DETAIL_FIELDS)
ok("detail panel shows the 17 populated fields", f"{len(panel)}")
ok("the 9 no-data fields are omitted from the panel entirely")

record = next(
    (r for r in rows if r["dallas_county_precinct_number"] == "1046"), rows[0]
)
pairs = dashboard.detail_records(record, dictionary, panel)
assert len(pairs) == 17, len(pairs)
shown = " ".join(p["Metric"] for p in pairs)
leaked = [f for f in panel if f in shown]
assert not leaked, f"raw field name leaked into the UI: {leaked}"
for field in panel:
    assert dashboard.label_for(dictionary, field) in shown, field
ok("all 17 displayed detail fields resolve to corrected labels")
ok("no raw field name appears in the detail panel")

assert dashboard.detail_records(None, dictionary, panel) == []
ok("a precinct with no CSV row yields no detail rows (no traceback)")

# a missing dictionary entry fails fast and names the field
err = expect_raises(KeyError, dashboard.label_for, {}, "pct_nope")
assert "pct_nope" in str(err), err
ok("missing dictionary entry fails fast naming the field")

# --- tooltip: all five metrics, always ------------------------------------
# This one is a `{token}` template, the grammar Streamlit's OWN tooltip channel
# uses -- deliberately not the `@@=` expression grammar the layer props need.
# `\n` is fine here because the frontend assigns the text via innerText.
template = dashboard.tooltip_template(dictionary)
tokens = re.findall(r"\{([^{}]+)\}", template)
assert tokens == [dashboard.JOIN_LAYER_KEY] + [
    "v_" + f for f in dashboard.TOOLTIP_FIELDS
], tokens
body = re.sub(r"\{[^{}]+\}", "", template)
for field in dashboard.TOOLTIP_FIELDS:
    assert dashboard.label_for(dictionary, field) in template, field
    assert field not in body, f"raw field name visible in tooltip: {field}"
assert template.count("\n") == len(dashboard.TOOLTIP_FIELDS), template
ok("tooltip template carries the precinct id plus all labelled slots")

# The guard this refactor needed. The template and the record keys are built
# from DIFFERENT lists, so a token can be perfectly well-formed and still
# resolve to nothing -- and Streamlit then renders the token as its own
# literal text, which is exactly the "v_2024_prop_r_for" that hit the screen.
# Asserting the template against a field list was self-consistent and told
# no lies but proved nothing about the layer; assert against the records.
hovered = dashboard.decorate(
    [{"properties": {dashboard.JOIN_LAYER_KEY: "1046"}}],
    rows,
    dashboard.DEFAULT_CHOROPLETH,
)[0]
unresolved = [t for t in tokens if t not in hovered]
assert not unresolved, (
    f"tooltip asks for {unresolved}: no such key on the records handed to the "
    "layer, so it renders as the token text instead of a value"
)
# and the counts stay counts once they reach a record
zeroed = dashboard.decorate(
    [{"properties": {dashboard.JOIN_LAYER_KEY: "4080"}}], rows, dashboard.DEFAULT_CHOROPLETH
)[0]
assert index["4080"]["canvass_attempts"] == "0", index["4080"]["canvass_attempts"]
assert zeroed["v_canvass_attempts"] == "0", zeroed["v_canvass_attempts"]
ok("every tooltip token resolves against the records the layer is given")


fc = dashboard.decorate(
    [{"properties": {dashboard.JOIN_LAYER_KEY: key}} for key in ["1046", "999999"]],
    rows,
    zero_field,
)
with_data, without_data = fc  # decorate() yields records, not features
for props in (with_data, without_data):
    slots = [k for k in props if k.startswith("v_")]
    assert len(slots) == len(dashboard.TOOLTIP_FIELDS), slots
assert sum(1 for k in with_data if k.startswith("v_")) == len(dashboard.TOOLTIP_FIELDS)
# a polygon whose precinct is in the CSV: unmatched polygons get em-dashes, not gaps
assert without_data["__matched"] is False
assert without_data["__color"] == dashboard.NO_DATA_COLOR
for field in dashboard.TOOLTIP_FIELDS:
    assert without_data["v_" + field] == dashboard.NO_DATA_TEXT, field
ok("a data-less precinct still lists every tooltip label, each as an em-dash")
assert with_data["__matched"] is True
assert index["1046"] is not None
ok("joined precinct carries its own values alongside the tooltip slots")

# --- join against the live layer ------------------------------------------
# The live endpoint is part of the plan's contract, so these checks run or the
# suite fails: a skipped check counts as missing coverage in the matrix audit.
payload = dashboard.fetch_features()


features = payload["features"]
stats = dashboard.join_precincts(features, rows)
assert len(features) == 791, len(features)
assert stats["polygons"] == 791
assert stats["csv_rows"] == len(rows), stats["csv_rows"]
# AC2: matched polygons. Recomputed from the live features against the CROSSWALK
# (the raw input), never from `stats` or from the extract -- `join_precincts()`
# derives `matched` from the index, so comparing it to anything the index defines
# would be an identity that cannot fail. Here the expected count comes from a
# different pair of sources: the layer's own NewPrcnt text and
# data/raw/dallas_vtd_to_county_precinct.csv.
EXPECT_MATCHED = sum(
    1 for f in features
    if str(f["properties"].get(dashboard.JOIN_LAYER_KEY, "")).strip() in CROSSWALK_CODES
)
assert stats["matched"] == EXPECT_MATCHED, (stats["matched"], EXPECT_MATCHED)
assert EXPECT_MATCHED == 704, EXPECT_MATCHED
# ...and the polygons left without a row are exactly the ones the crosswalk
# cannot attribute -- nothing else, so no polygon loses a row for another reason.
NO_CROSSWALK = sorted(
    str(f["properties"].get(dashboard.JOIN_LAYER_KEY, "")).strip() for f in features
    if str(f["properties"].get(dashboard.JOIN_LAYER_KEY, "")).strip() not in CROSSWALK_CODES
)
assert len(NO_CROSSWALK) == 87, len(NO_CROSSWALK)
assert sorted(NO_CROSSWALK) == sorted(set(NO_CROSSWALK)), "NewPrcnt repeats"
# The polygons the join leaves without a row are EXACTLY the polygons the
# crosswalk cannot attribute: a polygon in the layer, whose code the crosswalk
# does name, must have a row. Compared as sets because `stats` reports matched
# keys, not unmatched polygons; this is the matrix's "87 polygons with no
# crosswalk entry stay uncovered" row, read off the live layer.
LAYER_KEYS = dashboard.layer_keys(features)
polygons_without_row = sorted(LAYER_KEYS - set(index))
assert polygons_without_row == sorted(set(NO_CROSSWALK)), (
    f"{len(polygons_without_row)} polygons have no row; expected the "
    f"{len(NO_CROSSWALK)} the crosswalk cannot attribute"
)
assert stats["matched"] == len(features) - len(polygons_without_row)
assert "1046" in stats["unmatched"], stats["unmatched"]
# Matrix row "Precinct in CSV, absent from layer": the excluded ids are CSV
# rows the layer does not carry, so unmatched keys are in the index and NOT
# in the layer's NewPrcnt set.
keys = dashboard.layer_keys(features)
assert "1046" in index and "1046" not in keys
assert all(k in index and k not in keys for k in stats["unmatched"]), stats["unmatched"]
# Matrix row "Extract precinct the layer omits": 116 codes the crosswalk names
# but the live layer does not draw, reachable only through the offline selectbox.
assert len(stats["unmatched"]) == len(CROSSWALK_CODES) - EXPECT_MATCHED, (
    len(stats["unmatched"]), EXPECT_MATCHED)
ok(f"join cardinality: {stats['matched']} of {stats['csv_rows']} CSV precincts "
   f"match a polygon; {len(stats['unmatched'])} rows have no polygon")
ok("precinct 1046 is absent from the layer (excluded, reported)")

assert len(keys) == 791 and "" not in keys
ok("NewPrcnt is unique and non-blank on all 791 polygons")

ring_shapes = {
    (f["geometry"]["type"], len(f["geometry"]["coordinates"])) for f in features
}
assert ring_shapes == {("Polygon", 1)}, ring_shapes
lo, lat_min, lon_max, lat_max = dashboard.bbox(features)
assert -97.6 < lo < lon_max < -96.0 and 32.3 < lat_min < lat_max < 33.2, (lo, lat_max)
ok("geometry is WGS84 lon/lat as delivered, one ring per polygon")

populated = {}
for field in dashboard.CHOROPLETH_FIELDS:
    live = dashboard.decorate(features, rows, field)
    vals = [
        r["v_" + field] for r in live if r["__matched"]
    ]
    populated[field] = sum(1 for v in vals if v != dashboard.NO_DATA_TEXT)
    assert isinstance(live, list) and len(live) == 791, len(live)
    # deck.gl takes the colour attribute's item size from the first record and
    # applies it to all of them: a ragged mix of [r,g,b] and [r,g,b,a] silently
    # misreads the entire scale, so every fill must be RGBA.
    assert {len(r["__color"]) for r in live} == {4}, {
        len(r["__color"]) for r in live
    }

    # The empty style tracks the *value*, not the join: a precinct present in the
    # CSV but blank for the selected field is exactly as unfilled as one absent
    # from it, and only a real number earns a fill at all.
    for record in live:
        row = index.get(str(record[dashboard.JOIN_LAYER_KEY]).strip())
        valued = row is not None and dashboard.to_float(row.get(field)) is not None
        assert is_painted(record["__color"]) == valued, (
            f"{field}: precinct {record[dashboard.JOIN_LAYER_KEY]} filled "
            f"{record['__color']} but valued={valued}"
        )
        if valued:
            assert record["__color"][3] == dashboard.FILL_ALPHA, record["__color"]
ok("per-record __color: painted where data exists, empty where not", str(populated))
distinct = {
    tuple(r["__color"])
    for r in dashboard.decorate(features, rows, "2024_kamala")
    if r["__matched"]
}
assert len(distinct) > 1, distinct
ok("colours actually vary across precincts", f"{len(distinct)} distinct")

# --- pydeck serialisation + the selection-key contract -----------------
deck = dashboard.build_deck(
    dashboard.decorate(features, rows[:1], "2024_kamala"), template, features
)
layer = deck.layers[0]
assert layer.id == dashboard.LAYER_ID, layer.id
assert dashboard.LAYER_ID == "precincts"
blob = json.loads(deck.to_json())
dj = json.dumps(blob)
assert dashboard.LAYER_ID in dj, "layer id missing from the serialised deck"
# pydeck's Layer is not itself JSON-serialisable; the contract is the blob
# Deck.to_json() emits, so assert on the serialised layer dict.
emitted = blob["layers"][0]
assert emitted["id"] == dashboard.LAYER_ID, emitted["id"]
assert emitted["@@type"] == "PolygonLayer", emitted["@@type"]
# pydeck marks every string layer prop with `@@=` and the browser PARSES what
# follows, so each must be legal JSON-expression syntax and must name a key the
# records actually carry.  This is the guard for the render-time crash that no
# Python-side check could see: `d => d.properties.__color` threw
# `Unexpected "=" at character 2` in the browser while the suite stayed green.
for prop, value in emitted.items():
    if isinstance(value, str) and value.startswith("@@="):
        grammar_ok(value[3:], prop)
assert emitted["getFillColor"] == "@@=__color", emitted["getFillColor"]
assert emitted["getPolygon"] == "@@=__rings", emitted["getPolygon"]
# PolygonLayer defaults stroked:true, so the border only disappears if this
# ships as a plain boolean false -- a string would be marked `@@=` and read as a
# record lookup.  No line-styling prop should survive the removal at all.
assert emitted["stroked"] is False, emitted.get("stroked")
# The tooltip has to reach Streamlit's proto field, which is the ONLY place
# st.pydeck_chart looks.  Asserting the template string exists somewhere in the
# spec was never enough -- it did, and hover still showed nothing.
from streamlit.elements.deck_gl_json_chart import _get_pydeck_tooltip

shipped = _get_pydeck_tooltip(deck)
assert isinstance(shipped, dict), f"tooltip never reaches Streamlit: {shipped!r}"
assert shipped.get("text") == template, shipped
assert "html" not in shipped, "html is assigned via innerHTML; text is not"
assert "tooltip" not in emitted, "the inert layer-level tooltip prop is back"
ok("tooltip ships on Streamlit's own channel, not as a deck.gl layer prop")
leftover = sorted(k for k in emitted if "line" in k.lower())
assert not leftover, f"border props survived the removal: {leftover}"
ok("stroked serialises as boolean false and no line props remain")
assert "=>" not in dj, "an arrow function reached the serialised deck"
record_keys = set(dashboard.decorate(features, rows, "2024_kamala")[0])
needed = ({dashboard.JOIN_LAYER_KEY, "__color", "__rings"}
          | {"v_" + f for f in dashboard.TOOLTIP_FIELDS})
missing = sorted(needed - record_keys)
assert not missing, f"an accessor names a key the records do not carry: {missing}"
ok("every @@= prop is a JSON expression over keys the records have")
ok("Layer(id=...) is the id pydeck emits and the selection key", dashboard.LAYER_ID)

# ===========================================================================
# 2026 colour fields + the Dallas Council Districts overlay
# ===========================================================================
# The four additions the plan names, in the order the sidebar must offer them.
NEW_FIELDS = [
    "2026_gov_percent_Hinojosa",
    "2026_sen_percent_Talarico",
    "2026_prop_city_percent_Against",
    "2026_prop_county_percent_Against",
]
assert dashboard.CHOROPLETH_FIELDS[3:] == NEW_FIELDS, dashboard.CHOROPLETH_FIELDS
assert dashboard.TOOLTIP_FIELDS[-4:] == NEW_FIELDS, dashboard.TOOLTIP_FIELDS
assert dashboard.DEFAULT_CHOROPLETH == "prop_a_city_no_canvassing_pct"
# Hover stays the wider list, and the 11 pre-existing tooltip rows keep their
# order so the new figures land last rather than reshuffling the hover card.
assert dashboard.TOOLTIP_FIELDS[:11] == [
    "prop_a_city_no_canvassing_pct", "canvass_attempts", "response_rate",
    "strong_no", "response_count", "2024_prop_r_for", "2024_prop_u_against",
    "2024_kamala", "2020_percent_Sanders", "2020_percent_Biden",
    "2020_percent_Other",
], dashboard.TOOLTIP_FIELDS
ok("the four 2026 fields are colourable and hover-last; default unmoved",
   f"{len(dashboard.CHOROPLETH_FIELDS)} colourable / {len(dashboard.TOOLTIP_FIELDS)} hover")

# --- each new colour field scales as a share ------------------------------
# The pre-existing loop over CHOROPLETH_FIELDS (":331") already decorates all
# seven colourable fields and asserts 791 records, RGBA-4 fills, `is_painted ==
# valued` and FILL_ALPHA for each, and collects `populated[field]`.  Repeating
# that here would only add literals that can drift, so this loop covers what
# that one cannot: these four are result *shares*, and the count of filled
# polygons is read from `populated`/`stats`, never typed in.
# The populated count can no longer be `stats["matched"]` for all four: the
# widening reaches precincts the 2026 files cover unevenly (a precinct can be in
# the county proposition file and have no city row at all), so the city share is
# populated on fewer polygons than the join matches.  Each field's expectation is
# therefore recomputed from the RAW 2026 files, per precinct code -- the extract
# and `stats` are both under test here, so neither gets to define the number.
MATCHED_POLYGON_CODES = [
    str(f["properties"].get(dashboard.JOIN_LAYER_KEY, "")).strip() for f in features
    if str(f["properties"].get(dashboard.JOIN_LAYER_KEY, "")).strip() in CROSSWALK_CODES
]
for field in NEW_FIELDS:
    dom = dashboard.field_domain(rows, field)
    assert dom and dashboard.domain_is_share(dom), (field, dom)
    assert 0.0 <= dom[0] < dom[1] <= 1.0, (field, dom)
    _expect_pop = len(raw_populated_codes(field, MATCHED_POLYGON_CODES))
    assert populated[field] == _expect_pop, (field, populated[field], _expect_pop)
    assert _expect_pop <= stats["matched"], (field, _expect_pop)
    live = dashboard.decorate(features, rows, field)
    # a field whose domain is a share must vary: a flat ramp would claim a
    # spread the colour scale does not have.
    assert len({tuple(r["__color"]) for r in live if is_painted(r["__color"])}) > 1, field
    # the record carries a formatted value for the hover card too, percented
    # from the field's own share range (key taken from the extract, not typed in)
    _probed = next(k for k in sorted(index) if dashboard.to_float(index[k].get(field)) is not None)
    one = dashboard.decorate(
        [{"properties": {dashboard.JOIN_LAYER_KEY: _probed}}], rows, field
    )[0]
    assert one["v_" + field].endswith("%"), (field, one["v_" + field])
    assert one["v_" + field] != dashboard.NO_DATA_TEXT, field
ok("each new field is a share on its own 0-1 range and hover-formats as a percent",
   f"{populated[NEW_FIELDS[0]]} populated per field")

# Matrix row "Blank field value": 1046 is blank in all four -- it draws nothing
# while every other matched precinct paints.  It is also absent from the live
# layer, so drive the polygon directly rather than expecting it in `features`.
for field in NEW_FIELDS:
    assert dashboard.to_float(index["1046"].get(field)) is None, field
    bare = dashboard.decorate(
        [{"properties": {dashboard.JOIN_LAYER_KEY: "1046"}}], rows, field
    )[0]
    assert bare["__matched"] is True, field
    assert bare["__color"] == dashboard.NO_DATA_COLOR, field
    assert not is_painted(bare["__color"]), field
    assert bare["v_" + field] == dashboard.NO_DATA_TEXT, field
ok("matrix: blank 2026 value draws nothing and hovers as an em-dash", "precinct 1046")

# --- the live CouncilBoundaries contract ---------------------------------
council = dashboard.fetch_features(dashboard.COUNCIL_LAYER_URL)["features"]
assert len(council) == 14, len(council)
assert {f["geometry"]["type"] for f in council} == {"Polygon"}, {
    f["geometry"]["type"] for f in council
}
assert {len(f["geometry"]["coordinates"]) for f in council} == {1}, "single ring expected"
assert {f["properties"]["DISTRICT"] for f in council} == {str(n) for n in range(1, 15)}, [
    f["properties"]["DISTRICT"] for f in council
]
assert not [k for f in council for k, v in f["properties"].items() if v is None], "null property"
clons, clats = [], []
for _f in council:
    for _ring in _f["geometry"]["coordinates"]:
        clons += [x[0] for x in _ring]
        clats += [x[1] for x in _ring]
# WGS84 as delivered, and inside the county like the precinct layer: f=geojson is
# what keeps this true, and a native-wkid payload would land outside these bounds.
assert -97.6 < min(clons) and max(clons) < -96.0, (min(clons), max(clons))
assert 32.3 < min(clats) and max(clats) < 33.2, (min(clats), max(clats))
assert dashboard.COUNCIL_LAYER_URL.endswith("f=geojson"), dashboard.COUNCIL_LAYER_URL
ok("live CouncilBoundaries: 14 single-ring districts, DISTRICT 1-14, WGS84 in county")

# --- council_district_records: parts, holes, and geometry it must ignore ----
def polygon(rings):
    return {"type": "Polygon", "coordinates": rings}

def _ring(x0, x1, y0, y1):
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]

_sq = _ring(-96.9, -96.8, 32.7, 32.8)
_hole = _ring(-96.88, -96.85, 32.72, 32.75)
_recs = dashboard.council_district_records([
    {"properties": {"DISTRICT": "1"}, "geometry": polygon([_sq, _hole])},
    {"properties": {"DISTRICT": "2"}, "geometry": {
        "type": "MultiPolygon", "coordinates": [[[_sq]], [[_hole]]]},
    },
    {"properties": {"DISTRICT": "3"}, "geometry": None},
    {"properties": {"DISTRICT": "4"}, "geometry": {"type": "LineString",
                                                   "coordinates": _sq}},
])
# MultiPolygon -> one record per part (a record carries one ring list, so a
# single merged record would drop a part); Polygon with a hole -> ONE record that
# keeps both rings so the inner ring draws.
assert len(_recs) == 3, _recs
assert [r["DISTRICT"] for r in _recs] == ["1", "2", "2"], [r["DISTRICT"] for r in _recs]
assert len(_recs[0]["__rings"]) == 2, "a hole was dropped"
assert _recs[1]["__rings"] == [[_sq]] and _recs[2]["__rings"] == [[_hole]], _recs
assert all(isinstance(r["__rings"], list) and r["__rings"] for r in _recs)
live_recs = dashboard.council_district_records(council)
assert len(live_recs) == 14, len(live_recs)
assert all(r["__rings"] for r in live_recs)
ok("matrix: MultiPolygon splits per part, holes keep every ring, odd types ignored")

# --- the deck actually handed to st.pydeck_chart, both layers --------------
deck2 = dashboard.build_deck(
    dashboard.decorate(features, rows, dashboard.DEFAULT_CHOROPLETH),
    template, features, live_recs,
)
blob2 = json.loads(deck2.to_json())
assert len(blob2["layers"]) == 2, len(blob2["layers"])
assert [la["id"] for la in blob2["layers"]] == [
    dashboard.LAYER_ID, dashboard.COUNCIL_LAYER_ID
], [la["id"] for la in blob2["layers"]]
precinct_layer, district_layer = blob2["layers"]
# The overlay must not disturb the precinct layer at all: same props as before.
assert {k: v for k, v in precinct_layer.items() if k != "data"} == {
    k: v for k, v in emitted.items() if k != "data"
}, [
    k for k in set(precinct_layer) | set(emitted)
    if k != "data" and precinct_layer.get(k) != emitted.get(k)
]
assert district_layer["@@type"] == "PolygonLayer", district_layer
assert len(district_layer["data"]) == 14, len(district_layer["data"])
# Amended 2026-11-23: outlines AND a transparent light gray wash.  (Decision 2a
# shipped `filled=False`; the fill is back, at low alpha, so the choropleth
# under it still reads.)  Both switches must be plain booleans -- a string would
# be `@@=`-marked and read by the browser as a record lookup.
assert district_layer["filled"] is True, district_layer.get("filled")
assert district_layer["stroked"] is True, district_layer.get("stroked")
# Both colours are layer-wide constants shipped as RGBA lists, never strings: a
# string prop is parsed as a @deck.gl/json expression and the browser reads it
# as a record key (fc08df5), and deck.gl sizes a colour attribute from the first
# record it sees, so an RGB list here would misread every district in the layer.
for _prop, _const in (
    ("getLineColor", dashboard.COUNCIL_LINE_COLOR),
    ("getFillColor", dashboard.COUNCIL_FILL_COLOR),
):
    assert district_layer[_prop] == list(_const), district_layer.get(_prop)
    assert not isinstance(district_layer[_prop], str), (
        f"{_prop}: a colour string is parsed as a JSON expression, not an RGBA list"
    )
    assert len(district_layer[_prop]) == 4, district_layer[_prop]
    assert district_layer[_prop][3] > 0, f"{_prop} at alpha 0 draws nothing"
# Both are NEUTRAL inks (R == G == B, no blue cast) and neither is the precinct
# ramp; the border sits darker than its own wash so a boundary stays legible
# inside the district it outlines.  The request said "transparent black", but
# the border was tuned by eye to a lighter neutral ink once the map was open, so
# this asserts the invariant that survives tuning, not one exact triple.
assert len(set(district_layer["getLineColor"][:3])) == 1, district_layer["getLineColor"]
assert max(district_layer["getLineColor"][:3]) < max(district_layer["getFillColor"][:3]), (
    "a border no darker than its own wash reads as a smear"
)
assert len(set(district_layer["getFillColor"][:3])) == 1, district_layer["getFillColor"]
assert min(district_layer["getFillColor"][:3]) >= 150, (
    f"the fill is not a LIGHT gray: {district_layer['getFillColor']}"
)
assert district_layer["getFillColor"][3] < 255, (
    "an opaque wash hides the precinct choropleth inside every district"
)
assert district_layer["getLineColor"] != district_layer["getFillColor"]
# Zoom-surviving width, in device pixels.
assert district_layer["lineWidthMinPixels"] == dashboard.COUNCIL_LINE_WIDTH_MIN_PIXELS, (
    district_layer.get("lineWidthMinPixels")
)
assert district_layer["lineWidthMinPixels"] >= 2, district_layer
# It must not steal precinct picks or hover.
assert district_layer["pickable"] is False, district_layer.get("pickable")
assert district_layer.get("autoHighlight") in (None, False), district_layer
assert district_layer["getPolygon"] == "@@=__rings", district_layer["getPolygon"]
assert precinct_layer["pickable"] is True, "the precinct layer lost its pickability"
assert "tooltip" not in district_layer, "a layer-level tooltip serialises and is never read"
ok("overlay deck: precinct layer then 14 filled+stroked districts, non-pickable")

# The grammar sweep now has to cover EVERY emitted layer: a second layer is a
# second batch of string props the browser will parse, and the old sweep over
# `blob["layers"][0]` alone would never have looked at it.
for la in blob2["layers"]:
    for prop, value in la.items():
        if isinstance(value, str) and value.startswith("@@="):
            grammar_ok(value[3:], f"{la['id']}.{prop}")
        assert not (isinstance(value, str) and "=>" in value), f"{la['id']}.{prop}"
assert "=>" not in json.dumps(blob2)
# The "no line props" claim is about the PRECINCT layer only: borders were
# removed from the choropleth, while the district overlay is a border (and since
# 2026-11-23 a light gray wash) by design, so scoping this to layer 0 is the
# assertion, not an oversight.
assert [k for k in precinct_layer if "line" in k.lower()] == []
assert "lineWidthMinPixels" in district_layer and "getLineColor" in district_layer
ok("every string prop on both layers is legal @deck.gl/json grammar")
assert dashboard.COUNCIL_LAYER_ID == "council_districts"

# The tooltip channel is Deck-level, so it survives the extra layer unchanged --
# and it still has to be 16 lines with the new figures present.
shipped2 = _get_pydeck_tooltip(deck2)
assert shipped2 == shipped and shipped2.get("text") == template, shipped2
assert "html" not in shipped2 and len(blob2["layers"]) == 2
assert template.count("\n") == 15 and len(NEW_FIELDS) == 4
for field in NEW_FIELDS:
    assert dashboard.label_for(dictionary, field) in template, field
    assert field not in re.sub(r"\{[^{}]+\}", "", template), field
ok("tooltip still ships on the Deck channel, 16 lines, with layers[1] present")

# Overlay off => exactly one layer, and no district geometry is attached.
deck_off = dashboard.build_deck(
    dashboard.decorate(features, rows[:1], dashboard.DEFAULT_CHOROPLETH),
    template, features, None,
)
assert len(json.loads(deck_off.to_json())["layers"]) == 1
assert len(dashboard.build_deck(
    dashboard.decorate(features, rows[:1], dashboard.DEFAULT_CHOROPLETH),
    template, features, [],
).layers) == 1, "an empty district record set still added a layer"
ok("no overlay => precinct layer only")

# --- build-side join: data/raw/precinct_comb.csv, the county results roll-up --
# These are rows of THIS plan's matrix, and they are build behaviour, not UI
# behaviour -- so they are asserted on a real rebuild.  `main()` is run with its
# output redirected to a temp file and the checked artifact is that file:
# asserting on data/precinct_data.csv alone would pass against a stale artifact,
# which is how the four shipped render defects got through.  Placed before the
# AppTest section because the caption block at the end of this file is a known
# failure that aborts the script: a check sitting after it never runs.
import build_precinct_data as bpd  # noqa: E402
import contextlib  # noqa: E402
import csv  # noqa: E402
import io  # noqa: E402
import tempfile  # noqa: E402

ROLLUP = list(csv.DictReader(open(BASE / "data/raw/precinct_comb.csv", newline="", encoding="utf-8")))
MEASURE_COLS = [c for c in ROLLUP[0] if c not in (bpd.COMB_COUNTY_COL, bpd.COMB_KEY_COL)]
JOINED_COLS = [bpd.COMB_OVERLAYS.get(c, c) for c in MEASURE_COLS]
rollup_by_county = {}
for _r in ROLLUP:
    rollup_by_county.setdefault(_r[bpd.COMB_COUNTY_COL].strip(), {})[_r[bpd.COMB_KEY_COL].strip()] = _r
dallas_rollup = rollup_by_county[bpd.COMB_COUNTY]

with tempfile.TemporaryDirectory() as rebuild_dir:
    _real_out, bpd.OUT = bpd.OUT, Path(rebuild_dir) / "precinct_data.csv"
    _stdout = io.StringIO()
    try:
        with contextlib.redirect_stdout(_stdout):
            bpd.main()
        rebuilt_bytes = bpd.OUT.read_bytes()
        rebuilt = {r[bpd.PRECINCT_COL]: r for r in csv.DictReader(
            open(bpd.OUT, newline="", encoding="utf-8"))}
    finally:
        bpd.OUT = _real_out
build_report = _stdout.getvalue()

assert rebuilt_bytes == (BASE / "data/precinct_data.csv").read_bytes(), \
    "the committed extract is not what the current build produces"
ok("committed extract reproduces from a fresh build", f"{len(rebuilt)} rows")

# The dictionary half of the join gets the same treatment.  Reading
# data/data_dictionary.csv off disk would only prove a string exists in whatever
# file was written last -- the AGENTS.md ordering pitfall says the generator
# "exits 0 on stale input; nothing checks the order", so the check that matters
# is that the generator, run on THIS rebuild, produces the committed dictionary.
with tempfile.TemporaryDirectory() as dict_dir:
    _dict_in, _dict_out = Path(dict_dir) / "precinct_data.csv", Path(dict_dir) / "data_dictionary.csv"
    _dict_in.write_bytes(rebuilt_bytes)
    _real_in, _real_dict_out = (
        build_data_dictionary.IN_CSV, build_data_dictionary.OUT)
    try:
        build_data_dictionary.IN_CSV, build_data_dictionary.OUT = _dict_in, _dict_out
        with contextlib.redirect_stdout(io.StringIO()):
            build_data_dictionary.main()
        dict_bytes = _dict_out.read_bytes()
        fresh_dict = {r["field_name"]: r for r in csv.DictReader(
            open(_dict_out, newline="", encoding="utf-8"))}
    finally:
        build_data_dictionary.IN_CSV, build_data_dictionary.OUT = _real_in, _real_dict_out

assert dict_bytes == (BASE / "data/data_dictionary.csv").read_bytes(), \
    "the committed dictionary is not what the generator produces from the current extract"
ok("committed dictionary regenerates from this rebuild (build order enforced)",
   f"{len(fresh_dict)} fields")

header = list(rebuilt[next(iter(rebuilt))].keys())
RETIRED = ["prop_a_city_against_election_day", "prop_a_city_against_ev_in_person",
           "prop_a_city_against_ev_mail", "prop_a_city_against_total_votes",
           "prop_a_city_total_votes", "prop_a_city_source_rows",
           "prop_a_city_precinct_code", "prop_a_city_no_actual_pct"]
assert not [c for c in RETIRED if c in header], f"detail.xlsx fields survived: {RETIRED}"
assert not [c for c in bpd.COMB_OVERLAYS if c in header], \
    "an overlaid measure was also carried under its own name"
# AC1 / AC7 shape, asserted rather than printed: 820 rows x 120 columns, and one
# dictionary row per extract column with nothing falling through to the
# UNDOCUMENTED branch.  Without this a further measure in precinct_comb.csv is
# silently promoted into join_cols by comb_columns(), which returns every
# non-key header column, and the count moves with no check to fail.  120 = 99 at
# the last baseline, less the four superseded 2026 canvass placeholders, plus the
# 25 measures the three 2026 general-election files join in.  The widening adds
# ROWS, never columns, so 120 is also the guard that it did not smuggle a field
# in: the header is compared to the committed extract's below.
assert len(header) == 120, header
assert len(rebuilt) == len(CROSSWALK_CODES), (len(rebuilt), len(CROSSWALK_CODES))
# Matrix row "In crosswalk, absent from the .ods union": the added population is
# exactly the crosswalk codes the canvass workbooks never named.
assert sorted(rebuilt) != sorted(CANVASSED_CODES)
assert ADDED_CODES and len(ADDED_CODES) == len(rebuilt) - len(CANVASSED_CODES), (
    len(ADDED_CODES), len(rebuilt), len(CANVASSED_CODES))
assert set(rebuilt) == CROSSWALK_CODES, sorted(set(rebuilt) ^ CROSSWALK_CODES)[:10]
assert set(CANVASSED_CODES) <= set(rebuilt), sorted(CANVASSED_CODES - set(rebuilt))[:10]
assert len(fresh_dict) == len(header) == 120, (len(fresh_dict), len(header))
assert set(fresh_dict) == set(header), \
    "dictionary and extract disagree on the field set"
undocumented = sorted(f for f, r in fresh_dict.items() if "add to MANUAL" in r["description"])
assert not undocumented, f"UNDOCUMENTED (fallback) not empty: {undocumented}"
assert not [f for f, r in fresh_dict.items() if not r["readable_name"].strip()], \
    "a field generated with a blank readable_name"
# And the overlay targets must ARRIVE, not merely be written: `apply_comb` puts
# three measures into names that come from the .ods union, and the writer is
# opened with extrasaction="ignore", so a target missing from out_cols would
# vanish silently -- the defect class where a value is proved built where the
# consumer never receives it.
missing_targets = sorted(set(bpd.COMB_OVERLAYS.values()) - set(header))
assert not missing_targets, f"overlay targets never reached the extract: {missing_targets}"
ok("sheet-72 fields gone; AC1/AC7 shape and overlay targets all present",
   f"{len(header)} columns x {len(rebuilt)} rows")

# AC2, asserted rather than left to a manual diff against a /tmp backup.  The
# reproducibility check above compares a fresh rebuild with the artifact THIS code
# wrote, so it proves determinism, not equivalence with the previous build: a
# change that silently rewrote a canvass figure would pass it.  The baseline comes
# from git because a /tmp backup does not survive a reboot or a fresh clone.
import subprocess  # noqa: E402

BASELINE_REVISION = "374c0fd"
try:
    _baseline_bytes = subprocess.run(
        ["git", "show", f"{BASELINE_REVISION}:data/precinct_data.csv"],
        cwd=BASE, capture_output=True, check=True).stdout
except FileNotFoundError:
    raise AssertionError("this check needs git to read the baseline extract") from None

with io.StringIO(_baseline_bytes.decode("utf-8-sig"), newline="") as _fh:
    baseline_rows = {r[bpd.PRECINCT_COL]: r for r in csv.DictReader(_fh)}
baseline_header = list(next(iter(baseline_rows.values())).keys())
survived = [c for c in baseline_header if c in header]
assert len(baseline_header) == 99 and len(survived) == 95, \
    f"expected 99 baseline columns with 95 surviving, got {len(baseline_header)}/{len(survived)}"
# The widening GAINS rows by design, so equality of the code sets is no longer
# the contract.  What it is: every baseline precinct keeps its row, no code
# arrives that the crosswalk cannot attribute, and the added population is
# exactly the crosswalk's codes minus the baseline's.
assert set(baseline_rows) <= set(rebuilt), sorted(set(baseline_rows) - set(rebuilt))[:10]
assert set(rebuilt) - set(baseline_rows) == set(ADDED_CODES), (
    f"{len(set(rebuilt) - set(baseline_rows))} new rows, expected {len(ADDED_CODES)}")
regressions = [
    (p, c, baseline_rows[p][c], rebuilt[p][c])
    for p in baseline_rows for c in survived
    if baseline_rows[p][c] != rebuilt[p][c]
]
assert not regressions, \
    f"columns this change does not own altered against {BASELINE_REVISION}: {regressions[:5]}"
ok(f"AC2: the {len(survived)} surviving columns are identical to {BASELINE_REVISION}",
   f"{len(baseline_rows)} rows unchanged, {len(ADDED_CODES)} rows added")

# Zero drift against THIS plan's own baseline.  The revision above predates the
# 2026 joins, so it only proves the 95 columns that survived them.  The plan's
# `baseline_revision` is the extract the widening was written against -- already
# 120 columns -- so this is the check that says the widening changed rows and
# nothing else: the header is byte-identical in name AND order, no column was
# added or renamed, and all 85 original rows are identical across all 120
# columns.  A column appended to `out_cols` would slip past the 374c0fd sweep
# above (it compares only columns that existed there) and must not slip here.
PLAN_BASELINE_REVISION = "7b38e3a"
try:
    _plan_base_bytes = subprocess.run(
        ["git", "show", f"{PLAN_BASELINE_REVISION}:data/precinct_data.csv"],
        cwd=BASE, capture_output=True, check=True).stdout
except subprocess.CalledProcessError as _exc:
    raise AssertionError(
        f"this check needs {PLAN_BASELINE_REVISION} reachable in git "
        f"({_exc.stderr.decode(errors='replace')[:120]})") from None
with io.StringIO(_plan_base_bytes.decode("utf-8-sig"), newline="") as _fh:
    _plan_base = {r[bpd.PRECINCT_COL]: r for r in csv.DictReader(_fh)}
_plan_base_header = list(next(iter(_plan_base.values())).keys())
assert _plan_base_header == header, (
    f"the widening changed the header, not just the rows: "
    f"added {sorted(set(header) - set(_plan_base_header))} "
    f"removed {sorted(set(_plan_base_header) - set(header))} "
    f"or reordered it ({len(_plan_base_header)} vs {len(header)} cols)")
assert len(header) == 120 and len(_plan_base_header) == 120, len(header)
assert set(_plan_base) <= set(rebuilt), sorted(set(_plan_base) - set(rebuilt))[:10]
_drift = [(p, c, _plan_base[p][c], rebuilt[p][c])
          for p in _plan_base for c in header if _plan_base[p][c] != rebuilt[p][c]]
assert not _drift, (
    f"{len(_drift)} cells of the {len(_plan_base)} baseline rows differ against "
    f"{PLAN_BASELINE_REVISION} on all 120 columns: {_drift[:5]}")
assert sorted(rebuilt) != sorted(_plan_base) and set(ADDED_CODES) == set(rebuilt) - set(_plan_base)
ok(f"plan baseline {PLAN_BASELINE_REVISION}: identical 120-column header and "
   f"{len(_plan_base)} rows unchanged on every column",
   f"{len(rebuilt)} rows now ({len(ADDED_CODES)} added)")

# Matrix "Normal precinct": every matched precinct carries all 20 measures
# verbatim from its Dallas row -- compared cell by cell to the source, for every
# matched precinct, not sampled.  `..._percent_Harris` landing in `2024_kamala`
# is decision 1a.  The widening grows this population: the crosswalk-only rows
# are matched too, because the result joins run AFTER it (that ordering is what
# this verbatim sweep proves -- a join placed before the widening would leave
# 397 added precincts blank and fail here).
normal = [p for p in rebuilt if p in dallas_rollup]
drift = [(p, src) for p in normal for src, tgt in zip(MEASURE_COLS, JOINED_COLS)
         if rebuilt[p][tgt] != dallas_rollup[p][src].strip()]
assert not drift, f"joined values disagree with the roll-up: {drift[:5]}"
# The expected matched population, recomputed from the TWO SOURCES the join
# reads -- the crosswalk's universe and the roll-up's Dallas rows -- not from
# `rebuilt`.  It therefore catches a widening that never reached the join (the
# added rows would carry no results) and a roll-up that lost a precinct.
EXPECT_ROLLUP = sorted(CROSSWALK_CODES & set(dallas_rollup))
assert sorted(normal) == EXPECT_ROLLUP, (
    f"{len(normal)} precincts matched the roll-up, expected {len(EXPECT_ROLLUP)}")
assert len(normal) == 481, len(normal)
added_rollup = [p for p in normal if p in ADDED_CODES]
assert added_rollup and len(added_rollup) == len(
    set(ADDED_CODES) & set(dallas_rollup)), len(added_rollup)
ok(f"matrix: {len(normal)} matched precincts carry all 20 measures verbatim",
   f"{len(drift)} mismatches, {len(added_rollup)} of them added rows")

# Matrix "Precinct absent from source": 1046 has no Dallas row.  The row is
# still emitted, its 20 result figures are blank, the canvass figures the .ods
# supplied stay intact (including its genuine zero `canvass_attempts`), and the
# build names it in its report rather than dropping it silently.
assert "1046" in rebuilt, "a precinct with no roll-up row was dropped"
gap = [c for c in JOINED_COLS if rebuilt["1046"][c] != ""]
assert not gap, f"1046 result figures not blank: {gap}"
assert rebuilt["1046"]["canvass_attempts"] == "0", rebuilt["1046"]["canvass_attempts"]
assert rebuilt["1046"]["district"] == "District 9", rebuilt["1046"]["district"]
_reported = [ln for ln in build_report.splitlines() if "missing from precinct_comb.csv" in ln]
assert _reported and "1046" in _reported[0], _reported
ok("matrix: 1046 blank across all 20, canvass intact, named in the report")

# Matrix "Code in two counties": 2103 exists under Dallas AND Denton, and the
# Denton row records Harris as 0.  A wrong-key join would show that 0.
assert "2103" in rollup_by_county["Denton"], "fixture changed: 2103 no longer spans counties"
assert rollup_by_county["Denton"]["2103"]["2024_percent_Harris"] == "0"
assert rebuilt["2103"]["2024_kamala"] == dallas_rollup["2103"]["2024_percent_Harris"]
assert rebuilt["2103"]["2024_kamala"] != "0", "the Denton row joined instead of the Dallas one"
ok("matrix: 2103 joins the Dallas row, not the Denton row")

# Matrix "Genuine zero": `0` is a value, so it must be written as `0`.  No
# matched precinct happens to hold a zero today, so this drives the unit that
# does the copying rather than trusting an absence in the current data.
_zero_row = {}
bpd.apply_comb(_zero_row, {"2024_percent_For_U": "0", "2020_votes_Biden": "0",
                           "2024_percent_Harris": "0.5", "2024_votes_Trump": ""},
               ["2024_percent_For_U", "2020_votes_Biden", "2024_percent_Harris", "2024_votes_Trump"])
assert _zero_row["2024_percent_For_U"] == "0", _zero_row
assert _zero_row["2020_votes_Biden"] == "0", _zero_row
assert _zero_row["2024_kamala"] == "0.5", _zero_row  # overlaid onto the existing name
assert _zero_row["2024_votes_Trump"] == "", _zero_row  # recorded blank stays blank
assert "2024_percent_Harris" not in _zero_row, "overlay wrote its source name"
ok("matrix: a genuine 0 is written as 0; a blank source stays blank")

# Matrix "Zero-vs-blank" over the WIDENED universe. Before this change the only
# empty cell in each of the 20 joined fields was 1046, because the extract held
# only precincts a canvass workbook named and all but one of them had a Dallas
# row.  Now the empties are a population, so they are re-derived from the
# roll-up itself rather than remembered: a field is blank exactly where the
# precinct has no Dallas row OR its Dallas row leaves that measure empty (the
# propositions are recorded for 79 precincts only).  `..._percent_Harris` ->
# `2024_kamala` means the source column is looked up through COMB_OVERLAYS.
_no_rollup = {p for p in rebuilt if p not in dallas_rollup}
assert "1046" in _no_rollup, "1046 gained a roll-up row: the exemplar moved"
for _src, _c in zip(MEASURE_COLS, JOINED_COLS):
    _empties = {p for p in rebuilt if rebuilt[p][_c] == ""}
    _expect = {p for p in _no_rollup} | {
        p for p in normal if dallas_rollup[p].get(_src, "").strip() == ""}
    assert _empties == _expect, (
        f"{_c}: {len(_empties)} blank rows, expected {len(_expect)} "
        f"({sorted(_empties ^ _expect)[:5]} differ)")
    # A recorded 0 is a value: no blank became a zero and no zero a blank.
    for p in sorted(_expect):
        assert rebuilt[p][_c] == "", p
    _zeros = [p for p in normal if rebuilt[p][_c] == "0"]
    assert len(_zeros) == sum(
        1 for p in normal if dallas_rollup[p].get(_src, "").strip() == "0"), _c
    assert f"{len(_empties)} of {len(rebuilt)} rows empty" in dictionary[_c]["description"], (
        _c, dictionary[_c]["description"][-70:])
ok(f"matrix: blank roll-up cells are exactly the precincts with no Dallas figure, "
   f"named per field by reconcile() over {len(rebuilt)} rows", f"{len(JOINED_COLS)} fields")

# --- 2026 general election: the three per-precinct result files ------------
# Same discipline as the roll-up above: asserted on the rebuild, cell by cell for
# every matched precinct, against the source files keyed by the text after the
# colon.  A sampled spot-check is what let the earlier column-shift defects ship.
# GOV_IDX / SEN_IDX / PROPS_IDX / GENERAL_COLS / general_source() / FIELD_SOURCE
# are read ONCE at the top of this file, so the UI checks and these build checks
# judge the extract against the same raw sources through one field -> map.
matched_general = [p for p in rebuilt if general_source("gov", p)]
drift = [
    (p, contest, src, tgt)
    for p in matched_general
    for contest, measures in bpd.GENERAL_CONTESTS
    for src, tgt in measures.items()
    # `or {}` because a precinct can be in one file and not another (321 precincts
    # county-wide have no city row); the blank side of that is asserted below.
    if rebuilt[p][tgt] != ((general_source(contest, p) or {}).get(src) or "").strip()
]
assert not drift, f"joined 2026 values disagree with their source row: {drift[:5]}"
# The governor file covers every county precinct the crosswalk names except the
# 116 with no polygon, so the widened join reaches 704 precincts -- recomputed
# from the raw file and the crosswalk, not from `rebuilt`.
EXPECT_GENERAL = sorted(CROSSWALK_CODES & set(GOV_IDX))
assert sorted(matched_general) == EXPECT_GENERAL, (
    len(matched_general), len(EXPECT_GENERAL))
assert len(matched_general) > len(CANVASSED_CODES), (
    "the widening did not reach the 2026 result joins")
ok(f"matrix: {len(matched_general)} matched precincts carry all 24 contest "
   "measures verbatim", f"{len(drift)} mismatches, "
   f"{len(set(matched_general) & set(ADDED_CODES))} of them added rows")

# `Registered` is carried once (decision 2b) but asserted to agree across the
# four files first; check the surviving value is the governor row's.
reg_drift = [p for p in matched_general
             if rebuilt[p][bpd.GENERAL_REGISTERED_OUT] != GOV_IDX[p][bpd.GENERAL_REGISTERED_COL].strip()]
assert not reg_drift, reg_drift
ok(f"matrix: {bpd.GENERAL_REGISTERED_OUT} equals the source `Registered` for all "
   f"{len(matched_general)}")

# Decision 2b's guard was authored over the 85 canvassed codes, whose four files
# all agree.  Widening the universe puts 45 crosswalk-only precincts on that same
# governor-figure path while their files disagree (1305: governor/senate/county
# 1840 against city 0), so the guard does NOT silently widen with them -- the
# build reports the count instead of aborting.  Both halves are asserted: the
# canvassed population still aborts, and the added population is visible.
def _registered_seen(code):
    return {v for _, v in bpd.registered_values(GOV_IDX, SEN_IDX, PROPS_IDX, code)}
CANVASS_DISAGREE = sorted(c for c in CANVASSED_CODES if len(_registered_seen(c)) > 1)
assert not CANVASS_DISAGREE, f"the aborting guard now covers disagreeing rows: {CANVASS_DISAGREE}"
ADDED_DISAGREE = sorted(c for c in ADDED_CODES if len(_registered_seen(c)) > 1)
assert len(ADDED_DISAGREE) == 45, len(ADDED_DISAGREE)
_reg_line = [ln for ln in build_report.splitlines()
             if "Registered` disagrees across files" in ln]
assert _reg_line and f"({len(ADDED_DISAGREE)})" in _reg_line[0], _reg_line
for _c in ADDED_DISAGREE[:1]:  # the shipped value is the governor file's, either way
    assert rebuilt[_c][bpd.GENERAL_REGISTERED_OUT] == GOV_IDX[_c][bpd.GENERAL_REGISTERED_COL].strip()
ok("matrix: Registered disagreement still aborts for canvassed codes and is "
   f"reported, not swallowed, for the added ones", f"{len(ADDED_DISAGREE)} codes")

# A swap of the city and county rows would be invisible if the two measures were
# always equal, so prove they are genuinely different contests.  Asserted as
# "not all collide", never "none collide": one precinct tie is possible in the
# source and would be a coincidence, not a broken join -- the per-contest loop
# above is what catches an actual swap, cell by cell.
swapped = [p for p in matched_general
           if rebuilt[p]["2026_prop_city_percent_For"] == rebuilt[p]["2026_prop_county_percent_For"]]
assert len(swapped) < len(matched_general), \
    "city and county percent_For are identical everywhere, so the pivot is unverifiable"
ok("matrix: city and county proposition rows are distinct measures, not one row twice",
   f"{len(matched_general) - len(swapped)} of {len(matched_general)} distinguishable")

# Matrix "Precinct absent from all 3": 1046 has no `113:1046` row in any file.
gap = [c for c in GENERAL_COLS if rebuilt["1046"][c] != ""]
assert not gap, f"1046 2026 result figures not blank: {gap}"
for _line, _name in (("governor", bpd.GOV_CSV.name), ("senate", bpd.SEN_CSV.name)):
    _rep = [ln for ln in build_report.splitlines() if f"missing from {_name}" in ln]
    assert _rep and "1046" in _rep[0], _rep
for _prop in ("city", "county"):
    _rep = [ln for ln in build_report.splitlines() if f"a {bpd.GENERAL_PROPS_COL} == {_prop} row" in ln]
    assert _rep and "1046" in _rep[0], _rep
ok("matrix: 1046 blank across all 25 new fields and named in the report, 4 ways")

# Matrix "Blank source cell" / "Zero-vs-blank" over the WIDENED universe. The
# only empty cell used to be 1046, because the extract held only precincts a
# canvass workbook named and all of them but 1046 appeared in the three 2026
# files.  Now the blanks are a population -- 116 codes with no row at all in a
# race file, 409 with no `city` proposition row, plus the handful whose matched
# row leaves a measure empty -- so each field's blank set is re-derived from the
# raw file it came from through FIELD_SOURCE, exactly as the builder joined it.
# 1046 stays named as the exemplar: it is one of the 116.
assert "1046" not in GOV_IDX and "1046" not in SEN_IDX and "1046" not in PROPS_IDX
for _c in GENERAL_COLS:
    _empties = {p for p in rebuilt if rebuilt[p][_c] == ""}
    if _c == bpd.GENERAL_REGISTERED_OUT:
        _expect = {p for p in rebuilt if (GOV_IDX.get(p) or {}).get(
            bpd.GENERAL_REGISTERED_COL, "").strip() == ""}
    else:
        _contest, _src = FIELD_SOURCE[_c]
        _expect = {p for p in rebuilt if (general_source(_contest, p) or {}).get(
            _src, "").strip() == ""}
    assert _empties == _expect, (
        f"{_c}: {len(_empties)} blank rows, expected {len(_expect)} "
        f"{sorted(_empties ^ _expect)[:5]}")
    assert f"{len(_empties)} of {len(rebuilt)} rows empty" in fresh_dict[_c]["description"], (
        _c, fresh_dict[_c]["description"][-70:])
assert rebuilt["1050"]["2026_gov_votes_Other"] == "0", rebuilt["1050"]["2026_gov_votes_Other"]
assert rebuilt["1050"]["2026_gov_percent_Other"] == "0", rebuilt["1050"]["2026_gov_percent_Other"]
assert rebuilt["4141"]["2026_sen_votes_Other"] == "0", rebuilt["4141"]["2026_sen_votes_Other"]
assert rebuilt["4141"]["2026_sen_percent_Other"] == "0", rebuilt["4141"]["2026_sen_percent_Other"]
ok(f"matrix: blank 2026 cells are exactly the precincts the source files do not "
   f"cover, per field over {len(rebuilt)} rows; a genuine 0 still ships as 0",
   f"{len(GENERAL_COLS)} fields")

# Decision 3a/3b: the four superseded placeholders leave the OUTPUT but stay in
# the union READ, so fullness() and choose_shift() score exactly what they did
# before.  Asserting both halves is the point: dropping them from the read too
# would be indistinguishable here and would silently move dedupe scoring.
_, union_cols_probe = bpd.read_ods_tables()
assert not [c for c in bpd.RETIRED_GENERAL_COLS if c in header], \
    f"a superseded 2026 placeholder survived into the extract: {bpd.RETIRED_GENERAL_COLS}"
assert bpd.RETIRED_GENERAL_COLS and all(
    c in union_cols_probe for c in bpd.RETIRED_GENERAL_COLS
), "a retired placeholder was dropped from the .ods union read, changing dedupe scoring"
assert "2026_registered" in header, "the canvass-period registered figure was removed with them"
# Compared as a set: which precincts are blank is the fact, and extract row order
# is not something any acceptance criterion fixes.  The widening grows this
# population on purpose -- a crosswalk-only precinct was never canvassed, so it
# has no canvass-period registered figure -- so the assertion splits: the
# canvassed 85 keep exactly the blanks they had, and every added code joins them.
assert {p for p in CANVASSED_CODES if rebuilt[p]["2026_registered"] == ""} == {"2039", "1046"}, \
    "the canvass-period registered figure changed population among canvassed precincts"
assert all(rebuilt[p]["2026_registered"] == "" for p in ADDED_CODES), \
    "an added precinct shipped a canvass-period figure it never recorded"
ok("matrix: 4 placeholders out of the extract, still read from the .ods union; "
   "2026_registered unchanged for canvassed rows, blank for added ones")

# ===========================================================================
# The widened population: the matrix rows this plan adds coverage for
# ===========================================================================
# Matrix row "In crosswalk, absent from the .ods union" (1044, 3111 as named by
# the plan) and its flip side, "Precinct already in the extract": the added rows
# carry dominant-VTD DFS demographics with every .ods-derived and canvass column
# blank, and the 85 originals byte-identical.  Column names come from the
# extract's own header, and the list is then required to be non-empty and to
# cover the columns the plan says must stay blank -- a column renamed out of the
# header cannot hide behind a stale literal (`registered` does not exist here;
# the canvass-period column is `2026_registered`).
DFS_RAW_COLS = list(csv.DictReader(open(
    BASE / "data/raw/dfs-export-precinct-20261108/data.csv", newline="", encoding="utf-8")).fieldnames or [])
ODS_IN_HEADER = [c for c in ODS_COLS if c in header]
# Canvass-period metrics and provenance: present in the .ods union, so an added
# row has no source for them.  The three 2024 shares the roll-up supersedes are
# excluded -- the roll-up DOES cover added precincts and fills them, which is the
# ordering the plan requires (asserted below).
OVERLAID = set(bpd.COMB_OVERLAYS.values())
BLANK_BY_CONSTRUCTION = [
    c for c in ODS_IN_HEADER + [bpd.RESPONSE_COUNT_COL, bpd.NO_PCT_COL]
    if c != bpd.PRECINCT_COL and c not in OVERLAID
]
assert BLANK_BY_CONSTRUCTION, "the .ods union contributes no output column"
assert all(c in header for c in BLANK_BY_CONSTRUCTION), \
    sorted(set(BLANK_BY_CONSTRUCTION) - set(header))
for _c in ("precinct_group", "district", "sheet_column_alignment", "source_file",
           "canvass_attempts", "response_rate", "strong_no", "2024_turnout",
           "2026_registered", bpd.RESPONSE_COUNT_COL, bpd.NO_PCT_COL):
    assert _c in BLANK_BY_CONSTRUCTION, f"{_c} left out of the blank-by-construction set"
_filled = {(c, p) for p in ADDED_CODES for c in BLANK_BY_CONSTRUCTION if rebuilt[p][c] != ""}
assert not _filled, f"an added precinct carries a canvass figure it never recorded: {sorted(_filled)[:6]}"
ok("matrix: added rows leave every .ods-derived and canvass column blank",
   f"{len(BLANK_BY_CONSTRUCTION)} columns x {len(ADDED_CODES)} rows")

# ...while the DFS demographic block arrives verbatim from the dominant VTD's
# row, and the official results fill the added rows too (join ordering).
DFS_FILLED = [c for c in DFS_RAW_COLS if c in header]
assert DFS_FILLED, "no DFS column reached the extract header"
_dfs_expect = {r["source_ref"].strip(): r for r in csv.DictReader(open(
    BASE / "data/raw/dfs-export-precinct-20261108/data.csv", newline="", encoding="utf-8"))}
_drift = []
for _p in ADDED_CODES:
    _row = rebuilt[_p]
    _src = _dfs_expect.get(_row.get("census_vtd_geoid", "").strip())
    if _src is None:
        _drift.append((_p, "chosen VTD has no DFS row"))
        continue
    for _c in DFS_FILLED:
        if _row[_c] != _src[_c]:
            _drift.append((_p, _c, _row[_c], _src[_c]))
assert not _drift, f"added rows do not copy their VTD's DFS row verbatim: {_drift[:6]}"
ok("matrix: every added row copies its dominant VTD's DFS row verbatim",
   f"{len(DFS_FILLED)} columns x {len(ADDED_CODES)} rows")
_added_rollup = [p for p in ADDED_CODES if p in dallas_rollup]
assert _added_rollup and all(
    rebuilt[p]["2024_kamala"] == dallas_rollup[p]["2024_percent_Harris"].strip()
    for p in _added_rollup), "the roll-up join did not reach the added rows"
ok("matrix: official results fill the added rows too (widening precedes the joins)",
   f"{len(_added_rollup)} added precincts matched the roll-up")

# --- matrix row "Precinct maps to several VTDs": the winner rule -------------
# Recomputed independently for ALL 820 codes straight from the crosswalk and the
# DFS export, then compared to what the extract actually kept.  The rule is
# spelled out here as the builder's own tuple -- fullness first, then the share,
# with a MISSING share scoring -1.0 -- because `as_number(share) or -1.0` would
# collapse a recorded `0.0` (23 crosswalk rows hold one) into "missing": the
# blank-vs-zero conflation this repo forbids.  `complement()` is applied to
# `pct_renter_occupied` BEFORE scoring, exactly as the join loop does, or the
# derived column would score differently on the two paths.
_cw_by_geoid = {r["source_ref"].strip(): r for r in csv.DictReader(open(
    BASE / "data/raw/dfs-export-precinct-20261108/data.csv", newline="", encoding="utf-8"))}
_cw_by_precinct: "dict[str, list[dict[str, str]]]" = {}
for _r in crosswalk_rows:
    if _r[CROSSWALK_ID_COL].strip():
        _cw_by_precinct.setdefault(_r[CROSSWALK_ID_COL].strip(), []).append(_r)
SKIP_COLS = {bpd.PRECINCT_COL, bpd.GROUP_COL, "district", bpd.ALIGN_COL, "source_file"}
COUNTED = [c for c in header if c not in SKIP_COLS]


def _candidate(code, mapping):
    """The joined candidate row one (precinct, VTD) pair would produce."""
    row = {c: "" for c in header}
    row[bpd.PRECINCT_COL] = code
    row.update(mapping)
    _dfs = _cw_by_geoid.get(mapping["census_vtd_geoid"].strip())
    if _dfs is not None:
        row.update(_dfs)
    row[bpd.RENTER_COL] = bpd.complement(row.get("pct_owner_occupied"))
    return row


def _winner_rule(row):
    share = dashboard.to_float(row.get(bpd.SHARE_COL))
    return (bpd.fullness(row, COUNTED), share if share is not None else -1.0)


def _expected_vtd(code):
    cands = [_candidate(code, m) for m in _cw_by_precinct[code]]
    return max(cands, key=_winner_rule)


_wrong = []
for _code in sorted(_cw_by_precinct):
    if _code not in rebuilt:
        continue
    _exp = _expected_vtd(_code)
    if rebuilt[_code]["census_vtd_geoid"] != _exp["census_vtd_geoid"]:
        _wrong.append((_code, rebuilt[_code]["census_vtd_geoid"], _exp["census_vtd_geoid"]))
assert not _wrong, f"the extract's VTD is not the winner rule's: {_wrong[:6]}"
# The builder's shared rule and this independently-written one must agree on
# every crosswalk code, so neither can drift into `or -1.0` territory silently.
_agree = all(
    _winner_rule(_candidate(_c, _m)) == bpd.row_rank(_candidate(_c, _m), COUNTED)
    for _c in _cw_by_precinct for _m in _cw_by_precinct[_c])
assert _agree, "bpd.row_rank() no longer matches the fullness-then-share rule"
# ...and falsified on the exact case the conflation would get wrong: a recorded
# 0.0 share must beat a missing one, not tie it.
_z = {bpd.SHARE_COL: "0.0", bpd.PRECINCT_COL: "x"}
_n = {bpd.SHARE_COL: "", bpd.PRECINCT_COL: "x"}
assert _winner_rule(_z) > _winner_rule(_n), "a recorded 0.0 share read as missing"
assert bpd.row_rank(_z, COUNTED) > bpd.row_rank(_n, COUNTED), "bpd.row_rank() maps 0.0 to missing"
ok("matrix: the winner rule is fullness-then-share for all 820 codes, "
   "0.0 kept as a value", f"{len(_cw_by_precinct)} codes")

# Witnesses the frozen matrix names: fullness OVERRIDING the bigger share, and
# the ties the share alone decides.  Both are recomputed from the raw crosswalk,
# never copied from the extract.  A "tie" is on the FULLNESS component alone --
# the rank tuple's second element is the tie-break itself, so comparing whole
# tuples would find no tie at all and the check would report an empty list.
_over, _ties = [], []
for _c in sorted(_cw_by_precinct):
    if _c not in rebuilt or len(_cw_by_precinct[_c]) < 2:
        continue
    _scored = [(_winner_rule(_candidate(_c, _m)), _m["census_vtd_geoid"],
                dashboard.to_float(_m[bpd.SHARE_COL])) for _m in _cw_by_precinct[_c]]
    _top_full = max(s[0][0] for s in _scored)
    _tied = [s for s in _scored if s[0][0] == _top_full]
    _best_share = max((s[2] for s in _scored if s[2] is not None), default=None)
    if len(_tied) > 1:
        _ties.append(_c)          # equal fullness: the share alone decides
    elif _tied[0][2] != _best_share:
        _over.append((_c, _tied[0][2], _best_share))  # fullness beat the bigger share
# Split by population.  For a CANVASSED code the .ods-derived columns repeat
# identically across every VTD candidate -- the fan-out copies one precinct row
# -- so they shift all candidates' fullness by the same amount and preserve the
# ORDERING, but my reconstruction is only byte-identical to the builder's rows
# for the crosswalk-only codes.  The plan's witnesses are therefore asserted on
# the added population, where the reconstruction is exact; the canvassed codes
# that also tie are reported, not claimed.
_over = [o for o in _over if o[0] in ADDED_CODES]
_ties = [c for c in _ties if c in ADDED_CODES]
assert [o[0] for o in _over] == ["1315", "1724"], _over
assert sorted(_ties) == ["1044", "1104", "1107", "1300", "1305", "3327", "3504",
                         "4537", "4662"], _ties
# Each tie really is decided by the share, and the winner is the biggest share.
for _c in _ties:
    _shares = sorted((dashboard.to_float(_m[bpd.SHARE_COL]) for _m in _cw_by_precinct[_c]),
                     reverse=True)
    assert len(set(_shares)) == len(_shares), (_c, _shares)  # share, not order, decides
    assert rebuilt[_c][bpd.SHARE_COL] != "", (_c, rebuilt[_c][bpd.SHARE_COL])
    assert dashboard.to_float(rebuilt[_c][bpd.SHARE_COL]) == _shares[0], (_c, _shares)
# The overriding rows really do sit on a MINORITY VTD, and really are the fuller
# one -- i.e. the two exceptions are the rule working, not a bug.
for _c, _share, _sibling in _over:
    assert _share < _sibling, (_c, _share, _sibling)
    assert _share < 0.5, f"{_c}: attributed to a VTD covering most of it"
    _alts = {dashboard.to_float(_m[bpd.SHARE_COL]): _m["census_vtd_geoid"]
             for _m in _cw_by_precinct[_c]}
    _biggest = max(_alts)
    assert rebuilt[_c]["census_vtd_geoid"] == _alts[_share], (_c, rebuilt[_c]["census_vtd_geoid"])
    assert _biggest == _sibling and _share < _biggest, (_c, _share, _biggest)
ok("matrix: 1315/1724 prove fullness outranks share (0.115 / 0.144 kept over "
   "0.884 / 0.851)", f"{len(_ties)} ties left to the share")
ok("matrix: 9 codes tie on fullness, so the largest share decides", f"{_ties}")

# --- matrix row "VTD's DFS cells empty": blanks stay blank, never 0 ----------
# The three codes whose dominant VTD carries no demographic figure at all are
# named by the plan (2607, 3111, 4116).  Recomputed from the raw DFS export:
# a code belongs here exactly when its chosen VTD's DFS row holds no figure.
_fig_cols = bpd.dfs_figure_columns(DFS_RAW_COLS)
assert _fig_cols and all(c in header for c in _fig_cols), _fig_cols[:6]
_expect_blank = sorted(
    c for c in _cw_by_precinct
    if c in rebuilt and c in ADDED_CODES
    and bpd.fullness(_expected_vtd(c), _fig_cols) == 0)
_named = [p for p in ADDED_CODES
          if all(rebuilt[p][c] == "" for c in _fig_cols if c in header)]
assert _expect_blank == _named, (_expect_blank, _named)
assert _named == ["2607", "3111", "4116"], _named
for _c in _named:
    # Blank means no figure, so NOTHING numeric arrived for them: not a 0, not a
    # rounded complement, not the canvass-era derived ratio.
    _filled = [k for k, v in rebuilt[_c].items()
               if k not in SKIP_COLS and v != "" and k in set(_fig_cols) | {bpd.RENTER_COL}]
    assert not _filled, f"{_c}: a figure was invented {_filled}"
    assert rebuilt[_c][bpd.RENTER_COL] == "", _c
    # ...while the VTD identity columns still arrived, proving the row exists.
    assert rebuilt[_c]["census_vtd_geoid"] and rebuilt[_c]["source_ref"], _c
# The generator reports the same three, with a count so "checked, none" is
# distinguishable from a report that cannot fire (review findings 2 and 15).
_fig_line = [ln for ln in build_report.splitlines() if "no DFS figure" in ln]
assert len(_fig_line) == 1, _fig_line
assert f"({len(_named)})" in _fig_line[0], _fig_line
for _c in _named:
    assert _c in _fig_line[0], (_c, _fig_line[0])
_dfs_line = [ln for ln in build_report.splitlines() if "no DFS row" in ln]
assert len(_dfs_line) == 1 and "(0)" in _dfs_line[0], _dfs_line
_add_line = [ln for ln in build_report.splitlines() if "crosswalk precincts added" in ln]
assert len(_add_line) == 1 and f"{len(ADDED_CODES)}" in _add_line[0], _add_line
ok("matrix: VTDs with no figures stay blank across all 3 codes, named with a "
   "count on stdout", f"{_named}")
# ...and reconcile() owns the count in the dictionary: every scored figure
# column reports exactly these rows as empty.
for _c in _fig_cols:
    if _c in fresh_dict:
        assert f"{len(_named)} of {len(rebuilt)} rows empty" in fresh_dict[_c]["description"] \
            or "blank for" in fresh_dict[_c]["description"], (_c, fresh_dict[_c]["description"][-80:])
ok("matrix: the blank-figure rows are counted by reconcile(), never typed in",
   f"{len(_fig_cols)} DFS figure columns")

# Dictionary side: one row per new field, votes/registered integer and percent
# number (decision 4a), and no new field falling through to the fallback.
for _c in GENERAL_COLS:
    _t = fresh_dict[_c]["data_type"]
    _want = "number" if "percent" in _c else "integer"
    assert _t == _want, f"{_c} typed {_t}, expected {_want}"
    assert "add to MANUAL" not in fresh_dict[_c]["description"], _c
    assert fresh_dict[_c]["readable_name"].strip(), _c
assert not [c for c in bpd.RETIRED_GENERAL_COLS if c in fresh_dict], \
    "the generator still documents a retired placeholder"
ok("dictionary: 25 new fields typed and described; the 4 retired ones are gone")


def aborts_when_rollup_is(bad_csv, expect_substring):
    """Run the build with the roll-up replaced; prove it aborted before writing."""
    _csv, _out, wrote = bpd.COMB_CSV, bpd.OUT, []
    try:
        with tempfile.TemporaryDirectory() as td:
            out_path = Path(td) / "precinct_data.csv"
            bpd.COMB_CSV, bpd.OUT = Path(bad_csv), out_path
            err = expect_raises(SystemExit, bpd.main)
            if out_path.exists():
                wrote.append(out_path.name)
    finally:
        bpd.COMB_CSV, bpd.OUT = _csv, _out
    assert not wrote, "the build wrote precinct_data.csv despite the unusable roll-up"
    assert expect_substring in str(err), (expect_substring, str(err))
    return err


# Matrix "Source missing / header-only": the roll-up is a required input, so the
# build aborts with a SystemExit naming the path, BEFORE the output is opened.
with tempfile.TemporaryDirectory() as guard_dir:
    _header_only = Path(guard_dir) / "header_only.csv"
    _header_only.write_text(",".join(ROLLUP[0].keys()) + "\n", encoding="utf-8")
    _no_dallas = Path(guard_dir) / "no_dallas.csv"
    _no_dallas.write_text(
        ",".join(ROLLUP[0].keys()) + "\n" + ",".join(
            ["Collin", "9999"] + [""] * (len(MEASURE_COLS))
        ) + "\n", encoding="utf-8")
    _err = aborts_when_rollup_is(Path(guard_dir) / "absent.csv", "missing required input")
    assert "absent.csv" in str(_err), _err
    aborts_when_rollup_is(_header_only, "no data rows")
    aborts_when_rollup_is(_no_dallas, f"no `{bpd.COMB_COUNTY_COL} == {bpd.COMB_COUNTY}` rows")
ok("matrix: missing / header-only / no-Dallas roll-up aborts before writing")

# --- the three 2026 general files as required inputs ----------------------
# The matrix rows for these have no real data to exercise them: all 84 of ours
# match every file, so the contradiction and the odd-shape cases only a synthetic
# file can present are driven on synthetic files here.  Each must abort BEFORE
# the writer opens, the same way the roll-up does -- the builder truncates its
# output with "w" and has no dry-run, so writing a mostly-empty extract over the
# committed one is the failure mode being guarded.
def aborts_when_general_is(attr, bad_path, expect_substring):
    """Run the build with one 2026 general file replaced; prove it aborted before writing."""
    _orig, _out, wrote = getattr(bpd, attr), bpd.OUT, []
    try:
        with tempfile.TemporaryDirectory() as td:
            out_path = Path(td) / "precinct_data.csv"
            setattr(bpd, attr, bad_path)
            bpd.OUT = out_path
            err = expect_raises(SystemExit, bpd.main)
            if out_path.exists():
                wrote.append(out_path.name)
    finally:
        setattr(bpd, attr, _orig)
        bpd.OUT = _out
    assert not wrote, f"the build wrote precinct_data.csv despite the unusable {attr}"
    assert expect_substring in str(err), (expect_substring, str(err))
    return err


with tempfile.TemporaryDirectory() as g_dir:
    _ghead, _phead = list(GOV_RAW[0].keys()), list(PROPS_RAW[0].keys())
    _ok = matched_general[0]  # a precinct present in all three files

    def _gen_file(name, header, rows):
        p = Path(g_dir) / name
        with open(p, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(header)
            w.writerows(rows)
        return p

    # Bodies shaped for each loader: a governor-shaped row aimed at the Senate
    # loader aborts on its foreign candidate columns long before the condition
    # under test, so every fixture must otherwise be valid for its target.
    _shead = list(SEN_RAW[0].keys())
    _body = lambda code, head=_ghead: [f"113:{code}"] + ["1"] * (len(head) - 1)
    _pbody = lambda code, prop: [f"113:{code}", prop] + ["1"] * (len(_phead) - 2)
    _absent = Path(g_dir) / "absent_governor.csv"
    _empty = _gen_file("header_only.csv", _ghead, [])
    _nomatch = _gen_file("no_match.csv", _shead, [_body("999999", _shead)])
    _dup_gov = _gen_file("dup_governor.csv", _ghead, [_body(_ok)] * 2)
    _dup_sen = _gen_file("dup_senate.csv", _shead, [_body(_ok, _shead)] * 2)
    _dup_props = _gen_file("dup_props.csv", _phead, [_pbody(_ok, "city")] * 2)
    _extra = _gen_file("extra_measure.csv", _ghead + ["votes_Romney"],
                       [_body(_ok) + ["9"]])
    _extra_sen = _gen_file("extra_senate.csv", _shead + ["votes_Romney"],
                           [_body(_ok, _shead) + ["9"]])
    _extra_props = _gen_file("extra_props.csv", _phead + ["votes_Abstain"],
                             [_pbody(_ok, "city") + ["9"]])
    _badprop = _gen_file("odd_proposition.csv", _phead,
                         [_pbody(_ok, p) for p in ("city", "school")])
    # Each failure mode is driven on a DIFFERENT file, so the shared guard in
    # _general_read is proven to run for all three paths rather than once.  The
    # file a case is aimed at must otherwise be shaped for that loader, or the
    # build aborts earlier for a different reason than the case intends.
    def _drop(header, row, *victims):
        return ([c for c in header if c not in victims],
                [v for c, v in zip(header, row) if c not in victims])

    _h, _r = _drop(_ghead, _body(_ok), bpd.GENERAL_KEY_COL)
    _nokey = _gen_file("no_key.csv", _h, [_r])
    _h, _r = _drop(_ghead, _body(_ok), bpd.GENERAL_REGISTERED_COL)
    _noreg = _gen_file("no_registered.csv", _h, [_r])
    # A race file that grew the proposition discriminator.  Shaped like the race
    # files with `Proposition` as its ONLY extra column, so the abort can only
    # come from that column: `Proposition` is exempt for the props loader alone,
    # and must read as undescribed here rather than be skipped and resurface
    # later as a duplicate suffix.
    _raceprop = _gen_file("race_with_proposition.csv", _ghead + [bpd.GENERAL_PROPS_COL],
                          [_body(_ok) + ["city"]])
    _err = aborts_when_general_is("GOV_CSV", _absent, "missing required input")
    assert "absent_governor.csv" in str(_err), _err
    aborts_when_general_is("PROPS_CSV", _empty, "no data rows")
    aborts_when_general_is("SEN_CSV", _nomatch, "matches none of")
    aborts_when_general_is("GOV_CSV", _nokey, f"no `{bpd.GENERAL_KEY_COL}` column")
    aborts_when_general_is("SEN_CSV", _noreg, f"no `{bpd.GENERAL_REGISTERED_COL}` column")
    aborts_when_general_is("SEN_CSV", _dup_sen, "would be ambiguous")
    # The props loader words its duplicate abort per proposition, since two rows
    # sharing a suffix is a different fault from two rows for the same precinct
    # and proposition -- both must abort, neither may silently pick one.
    aborts_when_general_is("PROPS_CSV", _dup_props, "the pivot would have to pick one")
    aborts_when_general_is("SEN_CSV", _extra_sen, "undescribed measure columns")
    aborts_when_general_is("PROPS_CSV", _extra_props, "undescribed measure columns")
    _err = aborts_when_general_is("GOV_CSV", _raceprop, "undescribed measure columns")
    assert bpd.GENERAL_PROPS_COL in str(_err), _err
    aborts_when_general_is("PROPS_CSV", _badprop, "expected one of")
ok("matrix: absent / header-only / no-match / missing key / missing Registered /"
   " duplicate-suffix / undescribed column / unknown proposition each abort, per file")

# Matrix "Proposition with no city row" and "Blank source cell": 321 precincts
# county-wide have no city row and 59 have blank shares, but none is ours, so the
# applier is driven directly -- the 5 city figures blank, the county figures land,
# and a cell the source leaves empty stays empty instead of becoming a zero.
_county_row = next(r for r in PROPS_RAW if r["Proposition"] == "county")
_blank_gov = {k: "" for k in _ghead}
_blank_gov[bpd.GENERAL_REGISTERED_COL] = "1000"
_probe = {}
bpd.apply_general(_probe, {"gov": _blank_gov, "sen": None, "city": None, "county": _county_row})
_city_targets = list(bpd.PROPS_MEASURES["city"].values())
assert [_probe[t] for t in _city_targets] == [""] * len(_city_targets), _probe
assert _probe["2026_prop_county_votes_For"] == _county_row["votes_For"].strip()
assert _probe["2026_gov_percent_Other"] == "", "a blank source cell became a value"
assert _probe["2026_sen_votes_Paxton"] == "", "a file with no row wrote something other than blank"
assert _probe[bpd.GENERAL_REGISTERED_OUT] == "1000"
ok("matrix: no city row leaves the 5 city figures blank; a blank source cell stays blank")

# Matrix "Registered contradiction": 48 county-wide precincts disagree and none of
# ours does, so taking the governor figure without checking would promote the
# contradiction silently.  Drive the disagreement on synthetic rows.
_err = expect_raises(
    SystemExit, bpd.assert_registered_agreement,
    {"1004": {bpd.GENERAL_REGISTERED_COL: "1708"}},
    {"1004": {bpd.GENERAL_REGISTERED_COL: "1709"}},
    {"1004": {"city": {bpd.GENERAL_REGISTERED_COL: "1708"},
              "county": {bpd.GENERAL_REGISTERED_COL: "1708"}}},
    {"1004"})
assert "1004" in str(_err) and "governor=1708" in str(_err) and "senate=1709" in str(_err), _err
# A blank reads as "not recorded", not as a rival value, so it must not abort.
bpd.assert_registered_agreement({"1004": {bpd.GENERAL_REGISTERED_COL: "1708"}},
                               {"1004": {bpd.GENERAL_REGISTERED_COL: ""}}, {}, {"1004"})
ok("matrix: a Registered disagreement aborts naming the precinct and each file's value")

# The prefix carries the county, so it is part of the key's meaning: precinct
# 2103 exists under both Dallas and Denton, and joining on a bare or foreign
# suffix would pick one at random.  Asserted on the unit that does the splitting,
# because every file in the repo carries `113` alone -- no committed row can
# present the other shapes.  Leading zeros survive as text: casting to int, the
# mistake the roll-up's rule forbids, would erase them.
assert bpd.general_code("113:1004", bpd.GOV_CSV) == "1004"
assert bpd.general_code("  113:1004  ", bpd.GOV_CSV) == "1004"
assert bpd.general_code("113:0024", bpd.GOV_CSV) == "0024", "leading zeros must survive"
for _bad_key in ("1004", "999:1004", "113:", ""):
    _e = expect_raises(SystemExit, bpd.general_code, _bad_key, bpd.GOV_CSV)
    assert "unusable" in str(_e) and "113" in str(_e), (_bad_key, _e)
ok("matrix: only `113:<code>` keys join; bare/foreign/empty keys abort, zeros preserved")

# Use Streamlit's real event-state types, not a hand-rolled double nesting:
# main() hands selected_props the PydeckState that st.pydeck_chart returns, and a
# mock that adds an extra `.selection` layer is what let the old off-by-one read
# pass while every real click resolved to None.
from streamlit.elements.deck_gl_json_chart import PydeckSelectionState, PydeckState


def pydeck_state(objects):
    return PydeckState({"selection": PydeckSelectionState({"objects": objects, "indices": {}})})


hit_props = {dashboard.JOIN_LAYER_KEY: "1046", "v_2024_kamala": "72.0%"}
assert dashboard.selected_props(pydeck_state({dashboard.LAYER_ID: [hit_props]})) == hit_props
assert dashboard.selected_props(pydeck_state({})) is None
assert dashboard.selected_props(None) is None
# PydeckSelectionState has no `selection` key, so the inner state must read as
# "nothing clicked" rather than silently yielding a value.
assert dashboard.selected_props(pydeck_state({dashboard.LAYER_ID: [hit_props]}).selection) is None
ok("selection reads back from .selection.objects[<layer_id>]; no click -> None")

# pydeck serialises these as mapProvider/mapStyle at the top of the deck JSON.
# A `not in` on a key it never emits (map_provider) holds for any regression, so
# assert on the real keys: a slip back to mapbox or a dict style must fail here.
assert blob["mapProvider"] == "maplibre", blob.get("mapProvider")
assert blob["mapStyle"] == dashboard.MAP_STYLE_URL, blob.get("mapStyle")
ok("basemap is a MapLibre style URL string, keyless", dashboard.MAP_STYLE_URL)


# --- UI rows, driven through Streamlit's own script-test runtime ----------
# AppTest runs main() against a real ScriptRunContext, so the matrix's
# render-time rows are asserted on the widgets the app actually emitted --
# never on a `hasattr` guard that can silently skip them.
from streamlit.testing.v1 import AppTest  # noqa: E402
from streamlit.testing.v1.element_tree import Block  # noqa: E402
from streamlit.proto.Block_pb2 import Block as BlockProto  # noqa: E402

MAIN_SCRIPT = "import dashboard\ndashboard.main()\n"
ORIG_CACHED = dashboard._cached_features
ORIG_COUNCIL = dashboard._cached_council_features
ORIG_OPTIONS = dashboard._cached_district_options
ORIG_PYDECK_CHART = dashboard.st.pydeck_chart


def square(lon_a, lon_b, lat_a, lat_b):
    return [[lon_a, lat_a], [lon_b, lat_a], [lon_b, lat_b], [lon_a, lat_b], [lon_a, lat_a]]


def feature(precinct):
    return {
        "type": "Feature",
        "properties": {dashboard.JOIN_LAYER_KEY: precinct},
        "geometry": {"type": "Polygon", "coordinates": [square(-96.9, -96.8, 32.7, 32.8)]},
    }


def stub_fc(precincts):
    return {"type": "FeatureCollection", "features": [feature(k) for k in precincts]}


def run_app(fc=None, selected=None, timeout=120):
    """Render main() with the layer, the overlay and the click under our control."""
    dashboard._cached_features = (
        (lambda *a, **k: fc) if fc is not None else ORIG_CACHED
    )
    # The district menu is built on every render, so stub BOTH council fetches with
    # the 14 features already fetched at :496 rather than going live again: these
    # checks are about the precinct layer, the legend and the click, and an upstream
    # outage would otherwise show up as an unrelated network hang inside a
    # pre-existing assertion.  `council_district_options` reads only properties, so
    # the geometry payload serves for both.
    #
    # Note the geometry stub is now a belt-and-braces one: the menu defaults to an
    # empty selection, so an unmodified run_app render never asks for boundaries.
    dashboard._cached_council_features = lambda *a, **k: {"features": council}
    dashboard._cached_district_options = lambda *a, **k: {"features": council}
    if selected is not None:
        # A real PydeckState from Streamlit's own types, standing in for the
        # chart's return value, so main() runs its actual selected_props(chart)
        # call.  Stubbing selected_props instead is what let the broken read ship.
        state = pydeck_state({dashboard.LAYER_ID: [selected]})
        dashboard.st.pydeck_chart = lambda *a, **k: state
    try:
        at = AppTest.from_string(MAIN_SCRIPT)
        at.default_timeout = timeout
        at.run()
    finally:
        dashboard._cached_features = ORIG_CACHED
        dashboard._cached_council_features = ORIG_COUNCIL
        dashboard._cached_district_options = ORIG_OPTIONS
        dashboard.st.pydeck_chart = ORIG_PYDECK_CHART
    assert not at.exception, f"app raised {at.exception[0].value if at.exception else ''}"
    return at


def panel_blocks(at):
    """{panel heading -> the child nodes of that panel's column}, in paint order.

    Positional `at.dataframe[0]` cannot be trusted here: `st.dataframe(key=...)`
    does not surface a `.key` to AppTest (verified: both come back None), so index
    order is the only positional handle and it silently follows whatever order
    `_detail_panels` writes its columns in.  Swapping the two columns -- a purely
    presentational edit -- would then hand each check the *other* panel's table and
    every assertion below would still pass against the wrong data.  Resolving by the
    heading each panel renders keeps a swap a layout question, not a correctness one.

    A panel that rendered `st.info` instead of a table (no click, or a crosswalk-less
    polygon) contributes nothing here, so `panel_blocks(at) == {}` is the assertion
    for "no table", not a KeyError.
    """
    out = {}
    for block in at.main:
        if not isinstance(block, Block) or block.type != "flex_container":
            continue
        for col in block.children.values():
            if not isinstance(col, Block) or col.type != "column":
                continue
            kids = list(col.children.values())
            if kids and kids[0].type == "subheader":
                out[kids[0].value] = kids
    return out


def panel_tables(at):
    """{panel heading -> its rendered dataframe}, or absent if it shows no table."""
    tables = {}
    for heading, kids in panel_blocks(at).items():
        kinds = [g.type for g in kids]
        if "dataframe" in kinds:
            tables[heading] = kids[kinds.index("dataframe")].value
    return tables


def panel_captions(at):
    """{panel heading -> its caption text}, for panels that rendered one."""
    out = {}
    for heading, kids in panel_blocks(at).items():
        kinds = [g.type for g in kids]
        if "caption" in kinds:
            out[heading] = kids[kinds.index("caption")].value
    return out


# Default load: colour field, coverage caption, populated count of 791, all on
# the live layer.  The coverage figure is read from `populated` (computed above
# from the CSV) rather than typed in, so it cannot drift when the metric's
# formula changes -- the caption is required to agree with the data, not with a
# number remembered from an earlier build.
at = run_app()
choropleth_labels = [dashboard.label_for(dictionary, f) for f in dashboard.CHOROPLETH_FIELDS]
side = at.selectbox[0]
assert side.label == "Colour precincts by", side.label
assert side.value == dashboard.label_for(dictionary, dashboard.DEFAULT_CHOROPLETH), side.value
assert [o for o in side.options] == choropleth_labels, side.options
# Colouring and tooltiping are separate concerns now, so the sets differ:
# everything colourable is also shown on hover, but not vice versa.
assert set(dashboard.CHOROPLETH_FIELDS) < set(dashboard.TOOLTIP_FIELDS), (
    dashboard.CHOROPLETH_FIELDS, dashboard.TOOLTIP_FIELDS
)
# --- AC1: the panel resolves a row for a precinct no workbook named --------
# The whole point of the widening, asserted on the RENDERED panel: the same 17
# labelled metrics for every crosswalk precinct, a value where the dominant
# VTD's DFS row carries one and the no-data line where it does not.  The frozen
# matrix governs the blank case -- 2607, 3111 and 4116 land on VTDs with no
# figures at all, so their panel is 17 em-dashes and that is CORRECT, not a
# defect.  So the population is partitioned up front over all 735 added codes
# and every one is classified: a test set filtered to the rows that satisfy the
# property being asserted would pass while hiding exactly those three.
_FULL, _BLANK = [], []
for _c in ADDED_CODES:
    _vals = [dashboard.to_float(rebuilt[_c].get(_f)) for _f in panel]
    if all(v is not None for v in _vals):
        _FULL.append(_c)
    elif all(v is None for v in _vals):
        _BLANK.append(_c)
    else:
        raise AssertionError(
            f"{_c}: only some panel metrics carry a figure {[f for f, v in zip(panel, _vals) if v is None]}")
assert len(_FULL) + len(_BLANK) == len(ADDED_CODES), (len(_FULL), len(_BLANK))
assert _BLANK == ["2607", "3111", "4116"], _BLANK
assert len(_FULL) == len(ADDED_CODES) - 3, len(_FULL)
# Never invent a 0: the blank rows hold not even a zero in a panel column, and
# they are not dropped -- they are rows, named here and by the build's stdout.
for _c in _BLANK:
    assert not any(rebuilt[_c].get(_f) not in ("", None) for _f in panel), _c

# The rendered panel, driven through main()'s own click path for a sample that
# includes both partitions and the plan's two exemplars (1044 added with
# figures, 3111 added without).  17 rows, labelled, no raw field name, no
# traceback, and the value/no-data split matching the extract cell for cell.
_labels = [dashboard.label_for(dictionary, _f) for _f in panel]
_probe_codes = [c for c in ("1044", "3111", "2607", "4116", "1315", "1724") if c in ADDED_CODES]
assert set(_probe_codes) <= set(_FULL) | set(_BLANK)
for _c in _probe_codes:
    _want_blank = _c in _BLANK
    _at = run_app(fc=stub_fc([_c]), selected={dashboard.JOIN_LAYER_KEY: _c})
    _tables = panel_tables(_at)
    assert len(_at.dataframe) == 2, f"{_c}: expected both detail panels, got {len(_at.dataframe)}"
    _frame = _tables[dashboard.DEMOGRAPHICS_PANEL_HEADING]
    assert list(_frame.columns) == ["Metric", "Value"], _frame.columns
    assert len(_frame) == 17, (_c, len(_frame))
    assert list(_frame["Metric"]) == _labels, (_c, list(_frame["Metric"]))
    _shown = " ".join(_frame["Metric"])
    assert not [_f for _f in dashboard.DETAIL_FIELDS if _f in _shown], (_c, _shown)
    for _f, _v in zip(panel, _frame["Value"]):
        _cell = dashboard.to_float(rebuilt[_c].get(_f))
        if _cell is None:
            assert _v == dashboard.NO_DATA_TEXT, (_c, _f, _v)
            assert _v != "0", (_c, _f)
        else:
            assert _v != dashboard.NO_DATA_TEXT, (_c, _f)
    if _want_blank:
        assert list(_frame["Value"]) == [dashboard.NO_DATA_TEXT] * 17, _c
    assert not any("no data in this research extract" in i.value for i in _at.info), _c
ok("AC1: a crosswalk precinct no workbook named renders the same 17 labelled "
   "metrics, blank where its VTD has no figures", f"{len(_FULL)} with figures, "
   f"{len(_BLANK)} blank: {_BLANK}")

# Matrix row "Polygon with no crosswalk entry": the info path, asserted on the
# RENDERED st.info channel -- not on a direct detail_records() call, which
# returns [] on its first line for a None row and therefore proves nothing
# about what the browser received (AGENTS.md's shipped-defect class).
for _orphan in ("30A4", "2013"):
    assert _orphan not in CROSSWALK_CODES, _orphan
    _at = run_app(fc=stub_fc([_orphan]), selected={dashboard.JOIN_LAYER_KEY: _orphan})
    assert _at.dataframe == [], f"{_orphan}: a row was invented for a crosswalk-less polygon"
    _infos = [i.value for i in _at.info]
    assert any("no data in this research extract" in v for v in _infos), (_orphan, _infos)
    assert any(_orphan in v for v in _infos), (_orphan, _infos)
ok("matrix: a crosswalk-less polygon takes the rendered st.info path, no table",
   "30A4, 2013")

# Matrix row "Field blank across all rows": the panel stays 17 metrics over the
# WIDENED extract -- the 9 all-blank fields are still blank in all 820 rows, so
# the decision is unchanged by 735 new rows, and it is recomputed from them.
assert len(dashboard.detail_panel_fields(rows)) == 17, len(rows)
assert len(dashboard.NO_DATA_FIELDS) == 9
assert len(panel) == 17
_still_blank = [f for f in dashboard.DETAIL_FIELDS
                if not any(dashboard.to_float(r.get(f)) is not None for r in rows)]
assert _still_blank == dashboard.NO_DATA_FIELDS, _still_blank
_populate_panel = [f for f in dashboard.DETAIL_FIELDS
                   if any(dashboard.to_float(r.get(f)) is not None for r in rows)]
assert _populate_panel == panel, (_populate_panel, panel)
ok("AC4: detail_panel_fields is still 17 over 820 rows, NO_DATA_FIELDS still 9",
   f"{len(rows)} rows")

# --- the district multi-select, on the rendered sidebar -------------------
# Replaces the old "Show Dallas Council Districts?" Yes/No drop-down.  The title
# lost its question mark because it is no longer a yes/no question, and the
# options are the district numbers themselves.  Asserted on the emitted widgets,
# so a multiselect nobody rendered cannot pass.
assert [b.label for b in at.selectbox] == ["Colour precincts by"], [
    b.label for b in at.selectbox
]
menu = at.multiselect[0]
assert menu.label == dashboard.DISTRICT_SELECTOR_LABEL, menu.label
# The option list is read off the layer (`council`, fetched at :722), not typed
# in, and arrives NUMERICALLY sorted: 1..14, never the 1,10,11,12,13,14,2 order a
# plain sort of the strings would give.
assert list(menu.options) == [str(n) for n in range(1, 15)], list(menu.options)
# The requested default: nothing selected, so no boundaries on the map.
assert list(menu.value) == [], menu.value
assert at.sidebar.multiselect[-1] is menu, "the menu is not in the sidebar"
assert at.sidebar.selectbox[0] is at.selectbox[0], "the colour selectbox moved"
ok('sidebar renders the district multi-select with all 14 districts, none chosen')
# The empty box says nothing on its own, so the empty state is spelled out.
assert any(dashboard.DISTRICT_NONE_HINT in c.value for c in at.sidebar.caption), [
    c.value for c in at.sidebar.caption
]
ok('empty selection renders the "no boundaries" hint')

# --- the deck handed to st.pydeck_chart, spied at the call site ------------
# AppTest gives us the widget tree but not the Deck object, so spy on the chart
# call itself: `hasattr`-style guards on main() would pass against a map that
# never reached the render stream.
council_calls = []
options_calls = []


def _spy(payload=None, options_payload=None):
    """Patch the fetches + the chart; return the list the spy appended decks to.

    `payload` drives the BOUNDARY fetch (the 860 KB one, counted in
    `council_calls`); `options_payload` drives the menu listing (counted in
    `options_calls`).  They are counted apart because the contract this block
    proves is specifically that an empty selection costs zero BOUNDARY requests --
    the menu itself legitimately lists every time, and a single shared counter
    would make that unprovable.
    """
    seen = []

    # Named `council_fetch`, not `council`: this helper must not bind the name
    # `council` in its own scope, or the closure below would read `_spy`'s local
    # and hand the app a callable instead of the 14-feature list asserted at
    # :496 -- the overlay then raises inside its own guard and silently drops.
    def council_fetch(*_a, **_k):
        council_calls.append(1)
        if payload is not None and not isinstance(payload, dict):
            raise payload
        return payload if payload is not None else {"features": council}

    def options_fetch(*_a, **_k):
        options_calls.append(1)
        if options_payload is not None and not isinstance(options_payload, dict):
            raise options_payload
        # The menu reads only `properties`, so the geometry payload stands in.
        return options_payload if options_payload is not None else {"features": council}

    dashboard._cached_council_features = council_fetch
    dashboard._cached_district_options = options_fetch

    def chart(deck_arg, *_a, **_k):
        seen.append(deck_arg)
        return None

    dashboard.st.pydeck_chart = chart
    return seen


def _render(timeout=120):
    _at = AppTest.from_string(MAIN_SCRIPT)
    _at.default_timeout = timeout
    _at.run()
    assert not _at.exception, f"app raised {_at.exception[0].value if _at.exception else ''}"
    return _at


try:
    dashboard._cached_features = lambda *_a, **_k: stub_fc(["1045", "1046"])
    seen = _spy()
    # At the DEFAULT (nothing selected) the deck must carry the precinct layer
    # ONLY, and no boundary request may go out -- the call count is the proof, a
    # fetch-and-discard would leave it incremented.  The menu still lists, which
    # is what options_calls records.
    at_off = _render()
    assert len(seen) == 1, f"expected one chart call, got {len(seen)}"
    off_layers = json.loads(seen[0].to_json())["layers"]
    assert [la["id"] for la in off_layers] == [dashboard.LAYER_ID], [
        la["id"] for la in off_layers
    ]
    assert len(off_layers) == 1, len(off_layers)
    assert council_calls == [], (
        f"{len(council_calls)} boundary requests at the empty default"
    )
    assert len(options_calls) == 1, options_calls
    assert not at_off.warning, [w.value for w in at_off.warning]
    ok('default (no districts chosen) => precinct-only deck, zero boundary requests',
       f"{len(council_calls)} boundary / {len(options_calls)} listing calls")

    # Select three districts, deliberately out of order and including a 2-digit
    # one, so the payload proves real filtering rather than "the whole layer".
    before_council = len(council_calls)
    at_off.multiselect[0].set_value(["1", "8", "12"])
    at_off.run()
    on_layers = json.loads(seen[-1].to_json())["layers"]
    assert [la["id"] for la in on_layers] == [
        dashboard.LAYER_ID, dashboard.COUNCIL_LAYER_ID
    ], [la["id"] for la in on_layers]
    assert len(on_layers[1]["data"]) == 3, len(on_layers[1]["data"])
    # key=int: sorted() on the raw strings would order these 1,12,8, which is the
    # very bug `council_district_options` avoids for the menu.  Here the assertion
    # is about WHICH records survived the filter, so it sorts numerically.
    got = sorted((r[dashboard.DISTRICT_FIELD] for r in on_layers[1]["data"]), key=int)
    assert got == ["1", "8", "12"], got
    # AC4/AC3 at the render boundary: the props that keep the overlay from
    # stealing a precinct pick or a hover have to hold on the deck actually
    # handed to st.pydeck_chart, not only on one built directly in-process.
    assert on_layers[1]["pickable"] is False, on_layers[1].get("pickable")
    # Filled AND stroked, both transparent, both shipped as RGBA lists -- the
    # same shape asserted on the in-process deck above, now on the deck actually
    # handed to st.pydeck_chart.
    assert on_layers[1]["filled"] is True, on_layers[1].get("filled")
    assert on_layers[1]["stroked"] is True, on_layers[1].get("stroked")
    assert on_layers[1]["getFillColor"] == list(dashboard.COUNCIL_FILL_COLOR), (
        on_layers[1].get("getFillColor")
    )
    assert on_layers[1]["getLineColor"] == list(dashboard.COUNCIL_LINE_COLOR), (
        on_layers[1].get("getLineColor")
    )
    assert "tooltip" not in on_layers[1], "a layer tooltip serialises and is never read"
    assert on_layers[0]["pickable"] is True, "the precinct layer lost its pickability"
    assert len(council_calls) == before_council + 1, council_calls
    assert not at_off.warning, [w.value for w in at_off.warning]
    # The hint is gone once a choice exists.
    assert not any(
        dashboard.DISTRICT_NONE_HINT in c.value for c in at_off.sidebar.caption
    ), "the no-boundaries hint survived a non-empty selection"
    ok('three districts selected => exactly those 3 records, overlay props intact')
    # 16 hover lines, one per tooltip field plus the precinct id.
    assert _get_pydeck_tooltip(seen[-1])["text"].count("\n") == len(
        dashboard.TOOLTIP_FIELDS
    )

    # Selecting ALL 14 reproduces the old whole-layer overlay.
    at_off.multiselect[0].set_value([str(n) for n in range(1, 15)])
    at_off.run()
    all_layers = json.loads(seen[-1].to_json())["layers"]
    assert len(all_layers[1]["data"]) == 14, len(all_layers[1]["data"])
    ok('all 14 districts selected => full overlay, 14 records')

    # Clearing the selection retracts the overlay AND stops asking for geometry.
    before_council = len(council_calls)
    at_off.multiselect[0].set_value([])
    at_off.run()
    cleared = json.loads(seen[-1].to_json())["layers"]
    assert [la["id"] for la in cleared] == [dashboard.LAYER_ID], [
        la["id"] for la in cleared
    ]
    assert len(council_calls) == before_council, (
        f"boundary geometry fetched ({len(council_calls) - before_council}x) "
        "just to be thrown away"
    )
    ok('clearing the selection => precinct-only deck, zero new boundary requests',
       f"{len(council_calls)} boundary calls total")

    # AC4: a click resolves identically with the overlay on.  The district layer
    # is not pickable, so it contributes no object to the selection and the
    # detail panel is unchanged.  The selection is armed ON at_click, not on the
    # object above: `_render` returns a FRESH AppTest, which starts at the empty
    # default (widget state does not carry across AppTest instances), so setting it
    # anywhere else would leave this render drawing no overlay at all and quietly
    # test the wrong state.
    # The stub has to do BOTH jobs: hand main() a real PydeckState AND keep
    # recording decks into `seen`.  Returning the state alone silently stops the
    # spy appending, and `seen[-1]` then reads as whatever the PREVIOUS run
    # rendered -- here the cleared, precinct-only deck, which made this look like
    # the overlay had stopped drawing at all.
    click_state = pydeck_state(
        {dashboard.LAYER_ID: [{dashboard.JOIN_LAYER_KEY: "1045"}]}
    )

    def _click_chart(deck_arg, *_a, **_k):
        seen.append(deck_arg)
        return click_state

    dashboard.st.pydeck_chart = _click_chart
    at_click = _render()
    before_click = len(council_calls)
    at_click.multiselect[0].set_value(["1", "2"])
    at_click.run()
    click_layers = json.loads(seen[-1].to_json())["layers"]
    assert [la["id"] for la in click_layers] == [
        dashboard.LAYER_ID, dashboard.COUNCIL_LAYER_ID
    ], [la["id"] for la in click_layers]
    assert len(council_calls) == before_click + 1, council_calls
    _click_tables = panel_tables(at_click)
    assert len(at_click.dataframe) == 2, "click with the overlay on rendered both detail panels"
    assert len(_click_tables[dashboard.DEMOGRAPHICS_PANEL_HEADING]) == len(panel), \
        _click_tables[dashboard.DEMOGRAPHICS_PANEL_HEADING].shape
    assert len(_click_tables[dashboard.RESULTS_PANEL_HEADING]) == \
        len(dashboard.RESULTS_PANEL_FIELDS), \
        _click_tables[dashboard.RESULTS_PANEL_HEADING].shape
    ok("click resolves the same two panels with the overlay on",
       f"{len(panel)} + {len(dashboard.RESULTS_PANEL_FIELDS)} metrics")

    # Matrix row "Council endpoint down".  Two states now, because the service is
    # asked twice for two different things.
    #
    # (a) The BOUNDARY fetch fails while districts are selected: one warning naming
    # the geometry URL, the precinct map still rendered, no traceback, and no
    # st.error stealing the place of the existing precinct path.  The selection is
    # armed by hand because the empty default never reaches that fetch at all --
    # which is itself asserted first, as the absence of any warning.
    seen = _spy(OSError("council service down"))
    at_bad = _render()
    # Nothing selected at the default, so the boundary endpoint is never asked --
    # hence no warning at all, which is the whole point of gating the fetch.
    assert not at_bad.warning, [w.value for w in at_bad.warning]
    before_bad = len(seen)
    at_bad.multiselect[0].set_value(["1"])
    at_bad.run()
    assert len(seen) == before_bad + 1, f"the map stopped rendering: {seen}"
    assert len(at_bad.warning) == 1, [w.value for w in at_bad.warning]
    assert dashboard.COUNCIL_LAYER_URL in at_bad.warning[0].value, at_bad.warning[0].value
    assert "CouncilBoundaries" in at_bad.warning[0].value, at_bad.warning[0].value
    assert not at_bad.error, [e.value for e in at_bad.error]
    assert not at_bad.exception
    bad_layers = json.loads(seen[-1].to_json())["layers"]
    assert [la["id"] for la in bad_layers] == [dashboard.LAYER_ID], bad_layers
    assert len(at_bad.html) == 1, "the legend vanished with the overlay"
    ok("matrix: boundary fetch raises -> one warning naming its URL, map still renders")

    # (b) Matrix row this change introduces: the menu LISTING fails, so there is
    # nothing to choose.  The app must say so rather than render a silently empty
    # menu (which would read as "this county has no council districts"), must still
    # not ask for the 860 KB of geometry, and must keep the map.
    # `council_calls` is the one list every `_spy` closure appends to, so it is
    # compared as a delta from here, not against zero -- the runs above already
    # put numbers in it.
    seen = _spy(options_payload=OSError("listing service down"))
    before_nolist = len(council_calls)
    at_nolist = _render()
    assert len(at_nolist.warning) == 1, [w.value for w in at_nolist.warning]
    assert dashboard.COUNCIL_OPTIONS_URL in at_nolist.warning[0].value, (
        at_nolist.warning[0].value
    )
    assert not at_nolist.error, [e.value for e in at_nolist.error]
    assert not at_nolist.exception
    assert list(at_nolist.multiselect[0].options) == [], at_nolist.multiselect[0].options
    assert list(at_nolist.multiselect[0].value) == [], at_nolist.multiselect[0].value
    assert len(council_calls) == before_nolist, (
        f"{len(council_calls) - before_nolist} boundary requests behind an empty menu"
    )
    nolist_layers = json.loads(seen[-1].to_json())["layers"]
    assert [la["id"] for la in nolist_layers] == [dashboard.LAYER_ID], nolist_layers
    assert len(at_nolist.html) == 1, "the legend vanished with the menu"
    ok("matrix: menu listing raises -> one warning naming its URL, no boundary request",
       f"{len(council_calls) - before_nolist} new boundary calls")
finally:
    dashboard._cached_features = ORIG_CACHED
    dashboard._cached_council_features = ORIG_COUNCIL
    dashboard._cached_district_options = ORIG_OPTIONS
    dashboard.st.pydeck_chart = ORIG_PYDECK_CHART

# The offline path must stay exactly one st.error, and must not reach for the
# council layer at all -- BOTH council fetches sit after that early return, the
# boundary geometry one and, since the district menu moved here, the cheap menu
# listing too.  Counting them apart so a regression in either one is named.
_offline_calls = []
_offline_option_calls = []
def _precinct_layer_down(*_a, **_k):
    raise OSError("network down")


dashboard._cached_features = _precinct_layer_down
dashboard._cached_council_features = lambda *_a, **_k: _offline_calls.append(1)
dashboard._cached_district_options = lambda *_a, **_k: _offline_option_calls.append(1)
dashboard.st.pydeck_chart = lambda *_a, **_k: None
try:
    at_offline = _render(timeout=60)
finally:
    dashboard._cached_features = ORIG_CACHED
    dashboard._cached_council_features = ORIG_COUNCIL
    dashboard._cached_district_options = ORIG_OPTIONS
    dashboard.st.pydeck_chart = ORIG_PYDECK_CHART
assert len(at_offline.error) == 1, f"expected one clear error, got {len(at_offline.error)}"
assert dashboard.LAYER_URL in at_offline.error[0].value
assert not at_offline.warning, [w.value for w in at_offline.warning]
assert _offline_calls == [], "the precinct layer being down must not fetch council geometry"
assert _offline_option_calls == [], (
    "the precinct layer being down must not fetch the council district list either"
)
ok("offline path unchanged: one st.error, no warning, no council request of any size")

# ===========================================================================
# The two detail panels -- side by side, on the rendered tree
# ===========================================================================
# Placed HERE, above the known caption abort, for the reason this file already
# records at :818: a check sitting below that failure never runs.  Everything the
# single-panel layout used to assert is restated against the two-panel one, and
# asserted on emitted elements rather than on `detail_records` return values.
_panels = run_app(fc=stub_fc(["1045"]), selected={dashboard.JOIN_LAYER_KEY: "1045"})
_panel_tables = panel_tables(_panels)
assert len(_panels.dataframe) == 2, (
    f"expected two detail tables, got {len(_panels.dataframe)}")
# Compared as a set, not a sequence: which panel sits left is a layout choice
# (`_detail_panels` authors results first), and pinning the order here would fail a
# swap that breaks nothing the prompt asked for.  What has to hold is that BOTH
# headings exist and each carries its own table.
assert set(_panel_tables) == {
    dashboard.DEMOGRAPHICS_PANEL_HEADING, dashboard.RESULTS_PANEL_HEADING
}, sorted(_panel_tables)
assert not any("Precinct detail" in s.value for s in _panels.subheader), \
    "the old single heading is back"
ok("clicked precinct renders both panels under their own headings, no stale heading")

# Side-by-side is a layout claim, so it is asserted on the flex container
# st.columns actually emitted -- two equal columns in one HORIZONTAL row.  A bare
# `len(dataframe) == 2` would pass for two panels stacked full-width, which is the
# reading the prompt rules out.  `wrap` is what lets the same call stack below a
# 640px viewport, so there is no second code path to keep honest.
_rows = [
    b for b in _panels.main
    if isinstance(b, Block) and b.type == "flex_container"
    and len([c for c in b.children.values() if isinstance(c, Block) and c.type == "column"]) == 2
]
assert len(_rows) == 1, [
    (b.type, [getattr(c, "type", type(c).__name__) for c in b.children.values()])
    for b in _panels.main if isinstance(b, Block)
]
_dir = BlockProto.FlexContainer.Direction
assert _rows[0].proto.flex_container.direction == _dir.HORIZONTAL
assert _rows[0].proto.flex_container.wrap, "columns cannot stack on a narrow viewport"
# `Block.children` is a dict keyed by write position, so `.values()` is paint order.
# The row's own shape is what's pinned here -- two equal columns in one horizontal
# row -- not which heading lands left, so the panel contents are keyed by heading.
_cols = list(_rows[0].children.values())
assert [c.type for c in _cols] == ["column", "column"], [c.type for c in _cols]
for _col in _cols:
    # `Column.proto` IS the BlockProto.Column (weight + gap_config), not a Block
    # wrapper, so equal halves read off `.weight` -- st.columns(2) gives 0.5 each.
    assert _col.weight == 0.5, _col.weight
    assert [g.type for g in _col.children.values()] == \
        ["subheader", "caption", "dataframe"], \
        [g.type for g in _col.children.values()]
assert set(panel_blocks(_panels)) == {
    dashboard.DEMOGRAPHICS_PANEL_HEADING, dashboard.RESULTS_PANEL_HEADING
}, sorted(panel_blocks(_panels))
_panel_captions = panel_captions(_panels)
assert _panel_captions[dashboard.DEMOGRAPHICS_PANEL_HEADING] == \
    f"Precinct 1045 -- {len(panel)} metrics", _panel_captions
assert _panel_captions[dashboard.RESULTS_PANEL_HEADING] == (
    f"Precinct 1045 -- {len(dashboard.RESULTS_PANEL_FIELDS)} metrics"
), _panel_captions
ok("two equal-width columns in one horizontal, wrappable row",
   f"{len(panel)} | {len(dashboard.RESULTS_PANEL_FIELDS)} metrics")

# The results panel lists RESULTS_PANEL_FIELDS in its own order.  Where the two
# lists overlap the panel must still agree with the hover card cell for cell --
# that cross-surface check is the whole reason `decorate` and the panel share
# `format_value`/`fraction_flags` -- but it is driven from the PANEL's list, so it
# keeps meaning something once the lists are edited apart.
_results = panel_tables(_panels)[dashboard.RESULTS_PANEL_HEADING]
assert list(_results.columns) == ["Metric", "Value"], _results.columns
assert list(_results["Metric"]) == [
    dashboard.label_for(dictionary, f) for f in dashboard.RESULTS_PANEL_FIELDS
], list(_results["Metric"])
assert not [f for f in dashboard.RESULTS_PANEL_FIELDS if f in " ".join(_results["Metric"])], \
    "raw field name in the results panel"
_rec1045 = next(
    r for r in dashboard.decorate(stub_fc(["1045"])["features"], rows,
                                  dashboard.DEFAULT_CHOROPLETH))
_cells = dict(zip(_results["Metric"], _results["Value"]))
_shared = [f for f in dashboard.RESULTS_PANEL_FIELDS if f in dashboard.TOOLTIP_FIELDS]
assert _shared, "the two lists share no field, so the cross-surface check is vacuous"
_diverged = [
    (f, _cells[dashboard.label_for(dictionary, f)], _rec1045["v_" + f])
    for f in _shared
    if _cells[dashboard.label_for(dictionary, f)] != _rec1045["v_" + f]
]
assert not _diverged, f"results panel disagrees with the tooltip: {_diverged}"
# And every panel cell is the extract's own value, formatted with the panel's own
# share/count decision -- read off the CSV row, not off a tooltip key, since the
# panel no longer depends on `decorate` writing anything.
_row1045 = index["1045"]
_mismatch = []
for f in dashboard.RESULTS_PANEL_FIELDS:
    _want = dashboard.format_value(
        dashboard.to_float(_row1045.get(f)),
        fraction=dashboard.domain_is_share(dashboard.field_domain(rows, f)),
    )
    if _cells[dashboard.label_for(dictionary, f)] != _want:
        _mismatch.append((f, _cells[dashboard.label_for(dictionary, f)], _want))
assert not _mismatch, f"panel value is not the extract's value: {_mismatch}"
# Counts stay counts, shares stay shares, decided from the extract's range -- the
# same rule the tooltip applies, so `canvass_attempts` cannot read "100.0%" here.
for _count_field in ("canvass_attempts", "response_count", "strong_no"):
    _v = _cells[dashboard.label_for(dictionary, _count_field)]
    assert "%" not in _v, f"{_count_field} rendered as a share: {_v}"
for _share_field in ("prop_a_city_no_canvassing_pct", "response_rate",
                     "2026_gov_percent_Hinojosa"):
    _v = _cells[dashboard.label_for(dictionary, _share_field)]
    assert _v == dashboard.NO_DATA_TEXT or _v.endswith("%"), \
        f"{_share_field} rendered as a count: {_v}"
ok("results panel follows its own field list, values agreeing with the extract "
   "and with the tooltip", f"{len(dashboard.RESULTS_PANEL_FIELDS)} metrics, "
   f"{len(_shared)} shared with hover")

# --- the lists are genuinely independent, not merely separately named --------
# A shared alias or a derived copy would pass every check above.  So: move one field
# onto the panel only and one off it, and require the HOVER card not to move.  Both
# surfaces are driven through the app, and the tooltip is read out of the deck that
# actually reached st.pydeck_chart -- asserting the string `tooltip_template` builds
# in-process would prove nothing about what the browser got.
_TOOLTIP_ONLY, _PANEL_ONLY = "2020_percent_Other", "2024_percent_Against_R"
assert _TOOLTIP_ONLY in dashboard.TOOLTIP_FIELDS
assert _TOOLTIP_ONLY in dashboard.RESULTS_PANEL_FIELDS
assert _PANEL_ONLY in dictionary and _PANEL_ONLY not in dashboard.TOOLTIP_FIELDS
assert dashboard.to_float(index["1045"].get(_PANEL_ONLY)) is not None, _PANEL_ONLY

_seen_decks = []


def _spy_chart(deck_arg, *_a, **_k):
    _seen_decks.append(deck_arg)
    return pydeck_state({dashboard.LAYER_ID: [{dashboard.JOIN_LAYER_KEY: "1045"}]})


_ORIG_TIP = list(dashboard.TOOLTIP_FIELDS)
_ORIG_PANEL = list(dashboard.RESULTS_PANEL_FIELDS)
try:
    dashboard.TOOLTIP_FIELDS = _ORIG_TIP + [_TOOLTIP_ONLY]
    dashboard.RESULTS_PANEL_FIELDS = [
        f for f in _ORIG_PANEL if f != _TOOLTIP_ONLY
    ] + [_PANEL_ONLY]
    # NOT run_app(): it installs its own chart stub in `if selected is not None`
    # and restores ORIG_PYDECK_CHART in its finally, which would silently discard
    # the deck recorder.  `_render` leaves the chart alone, so the spy survives.
    dashboard._cached_features = lambda *a, **k: stub_fc(["1045"])
    dashboard._cached_council_features = lambda *a, **k: {"features": []}
    # The menu lists on every render regardless of selection, so it needs stubbing
    # too -- otherwise this block reaches the live service for something it is not
    # testing, and an outage lands inside an unrelated tooltip assertion.
    dashboard._cached_district_options = lambda *a, **k: {"features": council}
    dashboard.st.pydeck_chart = _spy_chart
    _split = _render(timeout=120)
    _split_tables = panel_tables(_split)

    # Panel: gained the panel-only field, lost the tooltip-only one.
    _split_metrics = list(_split_tables[dashboard.RESULTS_PANEL_HEADING]["Metric"])
    assert dashboard.label_for(dictionary, _PANEL_ONLY) in _split_metrics, _split_metrics
    assert dashboard.label_for(dictionary, _TOOLTIP_ONLY) not in _split_metrics, _split_metrics
    assert len(_split_tables[dashboard.RESULTS_PANEL_HEADING]) == len(
        dashboard.RESULTS_PANEL_FIELDS), len(_split_tables[dashboard.RESULTS_PANEL_HEADING])

    # Tooltip: gained its own field, and still lists the one the panel dropped.
    _tip_text = _get_pydeck_tooltip(_seen_decks[-1])["text"]
    assert len(_tip_text.split("\n")) == len(dashboard.TOOLTIP_FIELDS) + 1, _tip_text
    assert dashboard.label_for(dictionary, _TOOLTIP_ONLY) in _tip_text, _tip_text
    assert dashboard.label_for(dictionary, _PANEL_ONLY) not in _tip_text, _tip_text
    # The `v_` key the new token reads is written by `decorate` off TOOLTIP_FIELDS,
    # so the added field resolves instead of rendering its own name.
    _split_rec = next(
        r for r in dashboard.decorate(stub_fc(["1045"])["features"], rows,
                                      dashboard.DEFAULT_CHOROPLETH))
    assert "v_" + _TOOLTIP_ONLY in _split_rec, sorted(_split_rec)[:6]

    # Demographics panel: untouched by either edit -- the third list stays separate.
    assert list(_split_tables[dashboard.DEMOGRAPHICS_PANEL_HEADING]["Metric"]) == _labels
finally:
    dashboard.TOOLTIP_FIELDS = _ORIG_TIP
    dashboard.RESULTS_PANEL_FIELDS = _ORIG_PANEL
    dashboard.st.pydeck_chart = ORIG_PYDECK_CHART
    dashboard._cached_features = ORIG_CACHED
    dashboard._cached_council_features = ORIG_COUNCIL
    dashboard._cached_district_options = ORIG_OPTIONS

# The restore is real, not assumed: re-render and require the original lists back.
_restored = run_app(fc=stub_fc(["1045"]), selected={dashboard.JOIN_LAYER_KEY: "1045"})
assert list(panel_tables(_restored)[dashboard.RESULTS_PANEL_HEADING]["Metric"]) == [
    dashboard.label_for(dictionary, f) for f in _ORIG_PANEL
], "the mutation leaked past the finally"
ok("tooltip and results panel move independently, demographics panel never does",
   f"+{_PANEL_ONLY} panel only, +{_TOOLTIP_ONLY} hover only")

# A crosswalk-less polygon: both panels say so in the rendered st.info channel and
# neither invents a table.  Half an answer -- one panel blank, one silent -- would
# read as a rendering bug, so both statements are required.
_orphan_panel = run_app(fc=stub_fc(["999999"]), selected={dashboard.JOIN_LAYER_KEY: "999999"})
assert _orphan_panel.dataframe == [], [d.value.shape for d in _orphan_panel.dataframe]
_orphan_infos = [i.value for i in _orphan_panel.info]
assert len(_orphan_infos) == 2, _orphan_infos
assert all("no data in this research extract" in v and "999999" in v
           for v in _orphan_infos), _orphan_infos
ok("crosswalk-less polygon -> both panels state no data, no table", "2 st.info")

# No click: both headings still render, both prompt, neither emits an empty table.
_blank_panel = run_app(fc=stub_fc(["1045"]), selected=None)
assert _blank_panel.dataframe == [], _blank_panel.dataframe
assert set(s.value for s in _blank_panel.subheader) == {
    dashboard.DEMOGRAPHICS_PANEL_HEADING, dashboard.RESULTS_PANEL_HEADING
}, [s.value for s in _blank_panel.subheader]
_blanks = [i.value for i in _blank_panel.info]
assert len(_blanks) == 2 and all("Click a precinct" in v for v in _blanks), _blanks
assert any("demographics" in v for v in _blanks) and any("results" in v for v in _blanks), _blanks
ok("no click -> both headings, two prompts, no empty table")

# A precinct the extract carries but never canvassed: the results panel shows the
# blank fields as NO_DATA_TEXT and keeps the 2026 figures it does have -- never a
# zero for a cell the source left empty.
_blank_canvass = next(
    c for c in sorted(index)
    if dashboard.to_float(index[c].get("prop_a_city_no_canvassing_pct")) is None
    and dashboard.to_float(index[c].get("2026_gov_percent_Hinojosa")) is not None
)
_partial = run_app(fc=stub_fc([_blank_canvass]),
                   selected={dashboard.JOIN_LAYER_KEY: _blank_canvass})
_pframe = panel_tables(_partial)[dashboard.RESULTS_PANEL_HEADING]
_pcells = dict(zip(_pframe["Metric"], _pframe["Value"]))
assert _pcells[dashboard.label_for(dictionary, "prop_a_city_no_canvassing_pct")] \
    == dashboard.NO_DATA_TEXT, _blank_canvass
_hino = _pcells[dashboard.label_for(dictionary, "2026_gov_percent_Hinojosa")]
assert _hino != dashboard.NO_DATA_TEXT and _hino != "0", (_blank_canvass, _hino)
ok("blank canvass field stays an em-dash beside its real 2026 figures", _blank_canvass)

# AC2 for a NEW colourable field, asserted on the emitted payload rather than a
# legend string built in-process: `legend_html` is field-agnostic, so proving it
# assembles a percent proves nothing about the render stream -- the exact shape
# of the shipped defects this file exists to catch.  It also sits deliberately
# ABOVE the known caption failure below, so it actually runs.
share_field = "2026_gov_percent_Hinojosa"
share_label = dashboard.label_for(dictionary, share_field)
at6 = run_app()
at6.selectbox[0].set_value(share_label)
at6.run()
share_domain = dashboard.field_domain(rows, share_field)
assert dashboard.domain_is_share(share_domain), share_domain
assert len(at6.html) == 1, f"expected one legend block, got {len(at6.html)}"
rendered_legend = at6.html[0].value
assert rendered_legend == dashboard.legend_html(share_domain), "legend did not follow the field"
assert [t.value for t in at6.title] == [share_label], at6.title
# Compared against the legend's own <span> LABELS, never as substring membership
# of the whole block: `domain` is now 0.0-1.0, whose "0.0%" is a substring of the
# "100.0%" the gradient markup legitimately carries, so a substring test would
# pass for the wrong reason in either direction.
_legend_labels = re.findall(r"<span>([^<]*)</span>", rendered_legend)
assert len(_legend_labels) == 2, _legend_labels
for endpoint, label in zip(share_domain, _legend_labels):
    pct = dashboard.format_value(endpoint, True)
    assert pct.endswith("%") and label == pct, (endpoint, label, pct)
    assert _legend_labels[1] != _legend_labels[0], _legend_labels
# the default metric's endpoints must be gone, not merely superseded below
_default_domain = dashboard.field_domain(rows, dashboard.DEFAULT_CHOROPLETH)
for endpoint in _default_domain:
    assert dashboard.format_value(endpoint, True) not in _legend_labels, (
        endpoint, _legend_labels)
ok("a new 2026 field renders a percent legend from its own range", f"{_legend_labels}")

expected_colored = populated[dashboard.DEFAULT_CHOROPLETH]
expected_remaining = stats["polygons"] - expected_colored
coverage = f"{expected_colored} of {stats['polygons']} polygons are coloured by"
assert any(coverage in c.value for c in at.caption), [c.value for c in at.caption]
assert any(
    f"the remaining {expected_remaining} carry no value" in c.value for c in at.caption
), [c.value for c in at.caption]
assert any("1046" in c.value for c in at.caption), "exclusion not reported"
assert not any("20261108" in c.value or "data/raw" in c.value for c in at.caption), "a source path leaked into the UI"
assert any("84 of 85" in c.value for c in at.caption), "match count not stated"
ok("default load colours by prop_a_city_no_canvassing_pct and states coverage", f"{expected_colored} of {stats['polygons']}")

# --- the title names the field on the map --------------------------------
# It used to be the fixed string "Precinct choropleth".  Asserting it equals the
# sidebar's own selection is the whole point: a title that drifted from the
# metric would misreport the map, which is worse than a generic heading.
assert [t.value for t in at.title] == [side.value], (at.title, side.value)
assert not any("Precinct choropleth" in t.value for t in at.title), "the fixed heading is back"
ok("title is the selected choropleth field's readable label")

# --- the legend must REACH the render stream -----------------------------
# Asserting a legend string can be *built* is what let the tooltip ship unread.
# This asserts one html block arrives, holding this field's real range and the
# same colours the map paints with.
assert len(at.html) == 1, f"expected exactly one legend block, got {len(at.html)}"
default_domain = dashboard.field_domain(rows, dashboard.DEFAULT_CHOROPLETH)
legend = at.html[0].value
assert isinstance(legend, str) and legend == dashboard.legend_html(default_domain)
lo, hi = default_domain
for endpoint in (dashboard.format_value(lo), dashboard.format_value(hi)):
    assert endpoint in legend, f"legend does not state the populated min/max {endpoint}"
for swatch in (dashboard.color_scale(lo, default_domain),
               dashboard.color_scale(hi, default_domain)):
    red, green, blue, alpha = swatch
    assert f"rgba({red}, {green}, {blue}, {alpha / 255:.3f})" in legend, swatch
ok("legend ships under the map with this field's own min/max and swatch colours")

# Both sides call color_scale, so the legend inherits FILL_ALPHA instead of
# restating it.  A legend that hard-coded its own colours would pass every check
# above and still misrepresent the map the moment opacity changed.
assert f", {dashboard.FILL_ALPHA / 255:.3f})" in legend, "legend opacity is not FILL_ALPHA"
assert "linear-gradient" in legend, "a two-valued domain must render as a ramp"
ok("legend opacity is inherited from FILL_ALPHA, not restated")

# The empty style is a transparent fill with no border, so its key needs an
# outline of its own -- on the default metric it describes most precincts (the
# layer far outnumbers the rows carrying a value), and an outline-less swatch
# would draw nothing at all.
assert "dashed" in legend and "No value for this metric" in legend
ok("legend keys the empty style with a dashed outline")

# Order is part of "underneath the map": heading, map, legend, then captions.
stream = [getattr(e, "type", "") or type(e).__name__ for e in at.main]
for probe in ("title", "deck_gl_json_chart", "html", "caption"):
    assert probe in stream, (probe, stream)
order = [stream.index(p) for p in ("title", "deck_gl_json_chart", "html", "caption")]
assert order == sorted(order), f"legend is out of place: {stream}"
ok("render order is title, map, legend, captions")

# No selection yet: both panels prompt, neither renders an empty table.
assert at.dataframe == [], f"detail table rendered with no click: {at.dataframe}"
assert any("Click a precinct" in i.value for i in at.info), [i.value for i in at.info]
assert set(s.value for s in at.subheader) == {
    dashboard.DEMOGRAPHICS_PANEL_HEADING, dashboard.RESULTS_PANEL_HEADING
}, [s.value for s in at.subheader]
assert not any("Precinct detail" in s.value for s in at.subheader), "the old single heading is back"
ok("no selection -> both panel headings, two prompts, no empty table")

# 707 of 791 polygons hold no CSV row; each still carries an em-dash per field.
decorated = dashboard.decorate(features, rows, dashboard.DEFAULT_CHOROPLETH)
bare = [r for r in decorated if not r["__matched"]]
assert len(bare) == 791 - 84, len(bare)
assert all(r["__color"] == dashboard.NO_DATA_COLOR for r in bare)
assert all(r["v_" + fld] == dashboard.NO_DATA_TEXT for r in bare for fld in dashboard.TOOLTIP_FIELDS)
ok("a precinct with no CSV row is unfilled and lists every metric as an em-dash", f"{len(bare)} of 791")

# Switch field: colours re-scale to that field's range; tooltip values do not move.
# `canvass_attempts` is chosen because it is colourable AND a count (0-613), so the
# rerun also proves the share/count decision reaches the rendered legend.
attempts = dashboard.label_for(dictionary, "canvass_attempts")
at2 = run_app()
at2.selectbox[0].set_value(attempts)
at2.run()
assert any("49 of 791 polygons are coloured by " + attempts in c.value for c in at2.caption), [c.value for c in at2.caption]
other = dashboard.decorate(features, rows, "canvass_attempts")
same = all(
    a[k] == b[k]
    for a, b in zip(decorated, other)
    for k in a
    if k.startswith("v_") or k == "__matched"
)
assert same, "tooltip values changed when the colour field changed"
assert dashboard.tooltip_template(dictionary) == template, "tooltip is field-dependent"
ok("switching field re-scales colour and leaves every tooltip metric unchanged")

# Same rerun: switching the metric must retitle the app AND relabel the legend,
# and the old field's endpoints must be gone rather than merely superseded.
assert [t.value for t in at2.title] == [attempts], at2.title
domain_k = dashboard.field_domain(rows, "canvass_attempts")
legend_k = at2.html[0].value
assert legend_k == dashboard.legend_html(domain_k), "legend did not follow the field"
assert not dashboard.domain_is_share(domain_k), domain_k
assert ">613<" in legend_k, f"count max not rendered as a count: {legend_k}"
assert ">0<" in legend_k, f"count min not rendered as a count: {legend_k}"
# "0.0%" would mean the attempts column was read as a share.
assert "0.0%" not in legend_k, "a count field was percent-formatted in the legend"
assert dashboard.format_value(default_domain[1]) not in legend_k, "stale endpoint left"
ok("switching field retitles the app and relabels the legend, counts as counts")

# Degenerate domains. A gradient across one number would claim a spread the
# field does not have; a field with no values at all has no ramp to draw.
flat = dashboard.legend_html((0.5, 0.5))
assert "linear-gradient" not in flat, "gradient implies a range that does not exist"
assert flat.count(dashboard.format_value(0.5)) == 2, flat
nothing = dashboard.legend_html(None)
assert "linear-gradient" not in nothing and "carries a value" in nothing
assert "No value for this metric" in nothing, "the key vanished along with the ramp"
ok("legend handles a single-valued field and a field with no values at all")

# Click a polygon whose precinct is in the CSV: 17 labeled metrics, no raw names.
clicked = {dashboard.JOIN_LAYER_KEY: "1045"}
at3 = run_app(fc=stub_fc(["1045"]), selected=clicked)
assert len(at3.dataframe) == 2, "click on a CSV precinct rendered no detail table"
frame = panel_tables(at3)[dashboard.DEMOGRAPHICS_PANEL_HEADING]
assert list(frame.columns) == ["Metric", "Value"], frame.columns
assert len(frame) == 17, len(frame)
shown = " ".join(frame["Metric"])
raw = [f for f in dashboard.DETAIL_FIELDS if f in shown]
assert not raw, f"raw field names in the panel: {raw}"
for field in panel:
    assert dashboard.label_for(dictionary, field) in shown, field
for field in dashboard.NO_DATA_FIELDS:
    assert dashboard.label_for(dictionary, field) not in shown, field
ok("click polygon -> detail renders the 17 corrected labels and omits the 9 no-data fields")

# The two panels' field lists, values and layout are asserted up at the
# "detail panels" block, deliberately placed ABOVE the known caption abort: a
# check sitting below it never runs, which is what let four earlier defects ship.

# Click a polygon with no CSV row: a statement, not a traceback, not a table.
at4 = run_app(fc=stub_fc(["999999"]), selected={dashboard.JOIN_LAYER_KEY: "999999"})
assert at4.dataframe == [], "unmatched click rendered a detail table"
assert any("no data" in i.value for i in at4.info), [i.value for i in at4.info]
ok("click non-CSV polygon -> states no data, no traceback")

# Layer unreachable: one st.error naming the URL, and the joined UI still renders.
def _boom(*_a, **_k):
    raise OSError("network down")

dashboard._cached_features = _boom
try:
    at5 = AppTest.from_string(MAIN_SCRIPT)
    at5.default_timeout = 60
    at5.run()
finally:
    dashboard._cached_features = ORIG_CACHED
assert not at5.exception, f"offline path raised a traceback: {at5.exception}"
assert len(at5.error) == 1, f"expected one clear error, got {len(at5.error)}"
assert dashboard.LAYER_URL in at5.error[0].value, at5.error[0].value
assert len(at5.dataframe) == 2, "joined-field UI did not render both panels offline"
_at5_tables = panel_tables(at5)
assert len(_at5_tables[dashboard.DEMOGRAPHICS_PANEL_HEADING]) == len(panel), \
    _at5_tables[dashboard.DEMOGRAPHICS_PANEL_HEADING].shape
assert len(_at5_tables[dashboard.RESULTS_PANEL_HEADING]) == \
    len(dashboard.RESULTS_PANEL_FIELDS), \
    _at5_tables[dashboard.RESULTS_PANEL_HEADING].shape
assert set(s.value for s in at5.subheader) == {
    dashboard.DEMOGRAPHICS_PANEL_HEADING, dashboard.RESULTS_PANEL_HEADING
}, [s.value for s in at5.subheader]
ok("layer unreachable -> one st.error naming the URL, both panels still render")

# The title is chosen before the layer is fetched, so it still names the metric
# offline.  The legend keys the MAP's ramp and there is no map, so none renders:
# a legend over an absent map would describe colours nobody can see.
assert [t.value for t in at5.title] == [
    dashboard.label_for(dictionary, dashboard.DEFAULT_CHOROPLETH)
], at5.title
assert len(at5.html) == 0, f"a legend appeared with no map to key: {at5.html}"
ok("offline -> title still names the field, no legend without the map")

# A field the dictionary cannot name fails fast rather than rendering blank.
sabotaged = {k: v for k, v in dictionary.items() if k != "pct_nh_white"}
err = expect_raises(KeyError, dashboard.label_for, sabotaged, "pct_nh_white")
assert "pct_nh_white" in str(err), err
ok("missing dictionary entry fails fast naming the field")


print(f"\n{PASS} checks passed")
