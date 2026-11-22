"""Edge-case matrix checks for dashboard.py -- `uv run python tests/test_dashboard.py`.

Plain asserts, one pass line per check, exit 0 when all hold.  Run from the
repo root.
"""

from __future__ import annotations

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

# --- dictionary coverage: every field the dashboard touches is documented ----
all_needed = (
    dashboard.CHOROPLETH_FIELDS + dashboard.TOOLTIP_FIELDS
    + dashboard.DETAIL_FIELDS + [dashboard.JOIN_CSV_KEY]
)
missing = [f for f in all_needed if f not in dictionary]
assert not missing, f"undocumented fields: {missing}"
ok("dictionary covers every dashboard field", f"{len(dictionary)} entries")

assert len(rows) == 85, len(rows)
assert len(index) == 85, len(index)
ok("CSV is 85 rows / 85 unique precinct keys")

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

# Borders are gone, so a no-data precinct now paints literally nothing.  What
# still has to hold is that those invisible polygons are pickable (the fill
# sublayer is asserted above) and that the dead border colour was not left
# behind as a second source of truth.
assert not hasattr(dashboard, "LINE_COLOR"), "LINE_COLOR outlived the borders"
assert dashboard.NO_DATA_COLOR == [0, 0, 0, 0], dashboard.NO_DATA_COLOR
ok("no-data precincts stay fully empty regardless of FILL_ALPHA: no fill, no border")
assert dashboard.color_scale(None, domain) == [0, 0, 0, 0], "no-data must not inherit FILL_ALPHA"

# per-field normalization, never a fixed 0-1
kamala = dashboard.domain_for([dashboard.to_float(r.get("2024_kamala")) for r in rows])
assert kamala and 0.5 < kamala[0] and kamala[1] < 0.9, kamala
assert dashboard.color_scale(kamala[0], kamala) == dashboard.color_scale(0.0, domain)
ok("each field scales on its own populated min/max", f"2024_kamala {kamala}")

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
assert stats["matched"] == 84, stats
assert stats["csv_rows"] == 85
assert "1046" in stats["unmatched"], stats["unmatched"]
# Matrix row "Precinct in CSV, absent from layer": the excluded ids are CSV
# rows the layer does not carry, so unmatched keys are in the index and NOT
# in the layer's NewPrcnt set.
keys = dashboard.layer_keys(features)
assert "1046" in index and "1046" not in keys
assert all(k in index and k not in keys for k in stats["unmatched"]), stats["unmatched"]
ok("join cardinality: 84 of 85 CSV precincts match a polygon")
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
for field in NEW_FIELDS:
    dom = dashboard.field_domain(rows, field)
    assert dom and dashboard.domain_is_share(dom), (field, dom)
    assert 0.0 <= dom[0] < dom[1] <= 1.0, (field, dom)
    # every matched precinct carries a value for a 2026 result share, so the
    # populated count tracks the join rather than the canvass metrics' 22-49.
    assert populated[field] == stats["matched"], (field, populated[field])
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
# Decision 2a: outlines only.  Both must be plain booleans -- a string would be
# `@@=`-marked and read by the browser as a record lookup.
assert district_layer["filled"] is False, district_layer.get("filled")
assert district_layer["stroked"] is True, district_layer.get("stroked")
assert district_layer["getLineColor"] == list(dashboard.COUNCIL_LINE_COLOR), (
    district_layer.get("getLineColor")
)
assert not isinstance(district_layer["getLineColor"], str), (
    "a colour string is parsed as a JSON expression, not an RGBA list"
)
assert len(district_layer["getLineColor"]) == 4, district_layer["getLineColor"]
assert district_layer["getLineColor"][3] > 0, "an invisible border draws nothing"
# Zoom-surviving width, in device pixels.
assert district_layer["lineWidthMinPixels"] == dashboard.COUNCIL_LINE_WIDTH_MIN_PIXELS, (
    district_layer.get("lineWidthMinPixels")
)
assert district_layer["lineWidthMinPixels"] >= 2, district_layer
# It must not steal precinct picks or hover.
assert district_layer["pickable"] is False, district_layer.get("pickable")
assert district_layer.get("autoHighlight") in (None, False), district_layer
assert "getFillColor" not in district_layer, "an unfilled layer still asks for a fill"
assert district_layer["getPolygon"] == "@@=__rings", district_layer["getPolygon"]
assert precinct_layer["pickable"] is True, "the precinct layer lost its pickability"
assert "tooltip" not in district_layer, "a layer-level tooltip serialises and is never read"
ok("overlay deck: precinct layer then 14 unfilled stroked districts, non-pickable")

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
# removed from the choropleth, while the district overlay is a border by design,
# so scoping this to layer 0 is the assertion, not an oversight.
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
# AC1 / AC7 shape, asserted rather than printed: 85 rows x 120 columns, and one
# dictionary row per extract column with nothing falling through to the
# UNDOCUMENTED branch.  Without this a further measure in precinct_comb.csv is
# silently promoted into join_cols by comb_columns(), which returns every
# non-key header column, and the count moves with no check to fail.  120 = 99 at
# the last baseline, less the four superseded 2026 canvass placeholders, plus the
# 25 measures the three 2026 general-election files join in.
assert len(header) == 120, header
assert len(rebuilt) == 85, len(rebuilt)
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
assert set(baseline_rows) == set(rebuilt), "the build gained or lost precinct rows"
regressions = [
    (p, c, baseline_rows[p][c], rebuilt[p][c])
    for p in baseline_rows for c in survived
    if baseline_rows[p][c] != rebuilt[p][c]
]
assert not regressions, \
    f"columns this change does not own altered against {BASELINE_REVISION}: {regressions[:5]}"
ok(f"AC2: the {len(survived)} surviving columns are identical to {BASELINE_REVISION}",
   f"{len(baseline_rows)} rows x {len(survived)} columns")

# Matrix "Normal precinct": every matched precinct carries all 20 measures
# verbatim from its Dallas row -- compared cell by cell to the source, for all
# 84, not sampled.  `..._percent_Harris` landing in `2024_kamala` is decision 1a.
normal = [p for p in rebuilt if p in dallas_rollup]
drift = [(p, src) for p in normal for src, tgt in zip(MEASURE_COLS, JOINED_COLS)
         if rebuilt[p][tgt] != dallas_rollup[p][src].strip()]
assert not drift, f"joined values disagree with the roll-up: {drift[:5]}"
assert len(normal) == 84, len(normal)
ok("matrix: 84 matched precincts carry all 20 measures verbatim", f"{len(drift)} mismatches")

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

# Matrix "Zero-vs-blank among our 84": the only empty cell in each of the 20
# joined fields is 1046, and no matched precinct holds a zero -- which is why
# the generator reports the gap as a row count, per field, from reconcile().
for _c in JOINED_COLS:
    _empties = [p for p in rebuilt if rebuilt[p][_c] == ""]
    assert _empties == ["1046"], f"{_c}: unexpected empty rows {_empties}"
    assert not [p for p in normal if rebuilt[p][_c].strip() == "0"], f"{_c}: unexpected zero"
    assert "1 of 85 rows empty" in dictionary[_c]["description"], _c
ok("matrix: 1046 alone is empty in all 20 fields, reported as 1 of 85 rows", f"{len(JOINED_COLS)} fields")

# --- 2026 general election: the three per-precinct result files ------------
# Same discipline as the roll-up above: asserted on the rebuild, cell by cell for
# every matched precinct, against the source files keyed by the text after the
# colon.  A sampled spot-check is what let the earlier column-shift defects ship.
GOV_RAW = list(csv.DictReader(open(BASE / "data/raw/2026_governor_general_precinct.csv", newline="", encoding="utf-8")))
SEN_RAW = list(csv.DictReader(open(BASE / "data/raw/2026_senate_general_precinct.csv", newline="", encoding="utf-8")))
PROPS_RAW = list(csv.DictReader(open(BASE / "data/raw/2026_props_general_precinct.csv", newline="", encoding="utf-8")))
GOV_IDX = {bpd.general_code(r[bpd.GENERAL_KEY_COL], bpd.GOV_CSV): r for r in GOV_RAW}
SEN_IDX = {bpd.general_code(r[bpd.GENERAL_KEY_COL], bpd.SEN_CSV): r for r in SEN_RAW}
PROPS_IDX: dict[str, dict[str, dict[str, str]]] = {}
for _r in PROPS_RAW:
    PROPS_IDX.setdefault(bpd.general_code(_r[bpd.GENERAL_KEY_COL], bpd.PROPS_CSV), {})[
        _r[bpd.GENERAL_PROPS_COL].strip()] = _r
GENERAL_COLS = bpd.general_columns()
assert len(GENERAL_COLS) == 25, GENERAL_COLS


def general_source(contest, code):
    if contest == "gov":
        return GOV_IDX.get(code)
    if contest == "sen":
        return SEN_IDX.get(code)
    return PROPS_IDX.get(code, {}).get(contest)


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
assert len(matched_general) == 84, len(matched_general)
ok("matrix: 84 matched precincts carry all 24 contest measures verbatim", f"{len(drift)} mismatches")

# `Registered` is carried once (decision 2b) but asserted to agree across the
# four files first; check the surviving value is the governor row's.
reg_drift = [p for p in matched_general
             if rebuilt[p][bpd.GENERAL_REGISTERED_OUT] != GOV_IDX[p][bpd.GENERAL_REGISTERED_COL].strip()]
assert not reg_drift, reg_drift
ok(f"matrix: {bpd.GENERAL_REGISTERED_OUT} equals the source `Registered` for all 84")

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

# Matrix "Blank source cell" / "Zero-vs-blank": the only empty cell in each new
# field is 1046, and a recorded 0 stays 0 rather than reading as a gap.  1050
# (governor Other) and 4141 (Senate Other) are real zeros in the source.
for _c in GENERAL_COLS:
    _empties = [p for p in rebuilt if rebuilt[p][_c] == ""]
    assert _empties == ["1046"], f"{_c}: unexpected empty rows {_empties}"
    assert "1 of 85 rows empty" in fresh_dict[_c]["description"], _c
assert rebuilt["1050"]["2026_gov_votes_Other"] == "0", rebuilt["1050"]["2026_gov_votes_Other"]
assert rebuilt["1050"]["2026_gov_percent_Other"] == "0", rebuilt["1050"]["2026_gov_percent_Other"]
assert rebuilt["4141"]["2026_sen_votes_Other"] == "0", rebuilt["4141"]["2026_sen_votes_Other"]
assert rebuilt["4141"]["2026_sen_percent_Other"] == "0", rebuilt["4141"]["2026_sen_percent_Other"]
ok("matrix: 1046 alone is empty in all 25 fields; a genuine 0 ships as 0",
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
# is not something any acceptance criterion fixes.
assert {p for p in rebuilt if rebuilt[p]["2026_registered"] == ""} == {"2039", "1046"}, \
    "the canvass-period registered figure changed population"
ok("matrix: 4 placeholders out of the extract, still read from the .ods union; 2026_registered intact")

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

MAIN_SCRIPT = "import dashboard\ndashboard.main()\n"
ORIG_CACHED = dashboard._cached_features
ORIG_COUNCIL = dashboard._cached_council_features
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
    # The overlay defaults to "Yes", so every render from here on reaches for
    # council geometry.  Hand it the 14 features already fetched at :496 instead
    # of a second live request: these checks are about the precinct layer, the
    # legend and the click, and an upstream outage would otherwise show up as an
    # unrelated network hang inside a pre-existing assertion.
    dashboard._cached_council_features = lambda *a, **k: {"features": council}
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
        dashboard.st.pydeck_chart = ORIG_PYDECK_CHART
    assert not at.exception, f"app raised {at.exception[0].value if at.exception else ''}"
    return at


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
# --- the overlay drop-down, on the rendered sidebar -----------------------
# prompt.md:155-156 asks for a drop-down with this exact title defaulting to
# "Yes", and the plan puts it directly beneath the colour selectbox.  Asserted on
# the emitted widgets, so a selectbox nobody rendered cannot pass.
assert [b.label for b in at.selectbox] == [
    "Colour precincts by", "Show Dallas Council Districts?"
], [b.label for b in at.selectbox]
toggle = at.selectbox[1]
assert toggle.label == "Show Dallas Council Districts?", toggle.label
assert list(toggle.options) == [dashboard.DISTRICT_ON, dashboard.DISTRICT_OFF], toggle.options
assert toggle.options[0] == "Yes" and toggle.options[1] == "No", toggle.options
assert toggle.value == "Yes", toggle.value
assert at.sidebar.selectbox[-1] is toggle, "the toggle is not in the sidebar"
ok('sidebar renders "Show Dallas Council Districts?" defaulting to "Yes"')

# --- the deck handed to st.pydeck_chart, spied at the call site ------------
# AppTest gives us the widget tree but not the Deck object, so spy on the chart
# call itself: `hasattr`-style guards on main() would pass against a map that
# never reached the render stream.
council_calls = []


def _spy(payload=None):
    """Patch the fetch + the chart; return the list the spy appended decks to."""
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

    dashboard._cached_council_features = council_fetch

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
    at_on = _render()
    assert len(seen) == 1, f"expected one chart call, got {len(seen)}"
    on_layers = json.loads(seen[0].to_json())["layers"]
    assert [la["id"] for la in on_layers] == [dashboard.LAYER_ID, dashboard.COUNCIL_LAYER_ID], (
        [la["id"] for la in on_layers]
    )
    assert len(on_layers[1]["data"]) == 14, len(on_layers[1]["data"])
    # AC4/AC3 at the render boundary: the props that keep the overlay from
    # stealing a precinct pick or a hover have to hold on the deck actually
    # handed to st.pydeck_chart, not only on one built directly in-process.
    assert on_layers[1]["pickable"] is False, on_layers[1].get("pickable")
    assert on_layers[1]["filled"] is False, on_layers[1].get("filled")
    assert on_layers[1]["stroked"] is True, on_layers[1].get("stroked")
    assert "tooltip" not in on_layers[1], "a layer tooltip serialises and is never read"
    assert on_layers[0]["pickable"] is True, "the precinct layer lost its pickability"
    assert len(council_calls) == 1, council_calls
    assert not at_on.warning, [w.value for w in at_on.warning]
    # 16 hover lines, one per tooltip field plus the precinct id.
    assert _get_pydeck_tooltip(seen[0])["text"].count("\n") == len(
        dashboard.TOOLTIP_FIELDS
    )

    # Toggle to "No": precinct layer only, and NO council request at all.  The
    # call count is the proof -- a fetch-and-discard would leave it incremented.
    before = len(council_calls)
    at_on.selectbox[1].set_value("No")
    at_on.run()
    off_layers = json.loads(seen[-1].to_json())["layers"]
    assert [la["id"] for la in off_layers] == [dashboard.LAYER_ID], [
        la["id"] for la in off_layers
    ]
    assert len(off_layers) == 1, len(off_layers)
    assert len(council_calls) == before, (
        f"the overlay was fetched anyway ({len(council_calls) - before} extra calls) "
        "just to be thrown away"
    )
    ok('toggle "No" => precinct-only deck and zero council requests',
       f"{len(council_calls)} calls total")

    # Back to "Yes" re-arms the overlay.
    at_on.selectbox[1].set_value("Yes")
    at_on.run()
    assert len(json.loads(seen[-1].to_json())["layers"]) == 2
    assert len(council_calls) == before + 1, council_calls
    ok('toggle back to "Yes" restores the district layer')

    # AC4: a click resolves identically with the overlay on.  The district layer
    # is not pickable, so it contributes no object to the selection and the
    # detail panel is unchanged.
    dashboard.st.pydeck_chart = lambda deck_arg, *_a, **_k: pydeck_state(
        {dashboard.LAYER_ID: [{dashboard.JOIN_LAYER_KEY: "1045"}]}
    )
    at_click = _render()
    assert len(at_click.dataframe) == 1, "click with the overlay on rendered no detail table"
    assert len(at_click.dataframe[0].value) == 17, at_click.dataframe[0].value.shape
    ok("click resolves the same detail panel with the overlay on", "17 metrics")

    # Matrix row "Council endpoint down": one warning naming the URL, the
    # precinct map still rendered, no traceback, and no st.error stealing the
    # place of the existing precinct path.
    seen = _spy(OSError("council service down"))
    at_bad = _render()
    assert len(at_bad.warning) == 1, [w.value for w in at_bad.warning]
    assert dashboard.COUNCIL_LAYER_URL in at_bad.warning[0].value, at_bad.warning[0].value
    assert "CouncilBoundaries" in at_bad.warning[0].value, at_bad.warning[0].value
    assert not at_bad.error, [e.value for e in at_bad.error]
    assert not at_bad.exception
    assert len(seen) == 1, f"the map stopped rendering: {len(seen)} chart calls"
    bad_layers = json.loads(seen[0].to_json())["layers"]
    assert [la["id"] for la in bad_layers] == [dashboard.LAYER_ID], bad_layers
    assert len(at_bad.html) == 1, "the legend vanished with the overlay"
    ok("matrix: council fetch raises -> one warning naming its URL, map still renders")
finally:
    dashboard._cached_features = ORIG_CACHED
    dashboard._cached_council_features = ORIG_COUNCIL
    dashboard.st.pydeck_chart = ORIG_PYDECK_CHART

# The offline path must stay exactly one st.error, and must not reach for the
# council layer at all -- the district fetch sits after that early return.
_offline_calls = []
def _precinct_layer_down(*_a, **_k):
    raise OSError("network down")


dashboard._cached_features = _precinct_layer_down
dashboard._cached_council_features = lambda *_a, **_k: _offline_calls.append(1)
dashboard.st.pydeck_chart = lambda *_a, **_k: None
try:
    at_off = _render(timeout=60)
finally:
    dashboard._cached_features = ORIG_CACHED
    dashboard._cached_council_features = ORIG_COUNCIL
    dashboard.st.pydeck_chart = ORIG_PYDECK_CHART
assert len(at_off.error) == 1, f"expected one clear error, got {len(at_off.error)}"
assert dashboard.LAYER_URL in at_off.error[0].value
assert not at_off.warning, [w.value for w in at_off.warning]
assert _offline_calls == [], "the precinct layer being down must not fetch council geometry"
ok("offline path unchanged: one st.error, no warning, no council request")

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
for endpoint in share_domain:
    pct = dashboard.format_value(endpoint, True)
    assert pct.endswith("%") and pct in rendered_legend, (endpoint, pct, rendered_legend)
# the default metric's endpoints must be gone, not merely superseded below
_default_domain = dashboard.field_domain(rows, dashboard.DEFAULT_CHOROPLETH)
assert dashboard.format_value(_default_domain[1], True) not in rendered_legend
assert dashboard.format_value(_default_domain[0], True) not in rendered_legend
ok("a new 2026 field renders a percent legend from its own range", share_label)

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

# No selection yet: a prompt, and no empty table.
assert at.dataframe == [], f"detail table rendered with no click: {at.dataframe}"
assert any("Click a precinct" in i.value for i in at.info), [i.value for i in at.info]
assert any("Precinct detail" in s.value for s in at.subheader)
ok("no selection -> prompt to click, no empty table")

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
assert len(at3.dataframe) == 1, "click on a CSV precinct rendered no detail table"
frame = at3.dataframe[0].value
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
assert len(at5.dataframe) == 1, "joined-field UI did not render offline"
assert len(at5.dataframe[0].value) == 17, at5.dataframe[0].value.shape
ok("layer unreachable -> one st.error naming the URL, joined fields still render")

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
