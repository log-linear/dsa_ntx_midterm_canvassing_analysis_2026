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
all_needed = dashboard.CHOROPLETH_FIELDS + dashboard.DETAIL_FIELDS + [dashboard.JOIN_CSV_KEY]
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
ok("all 89 labels free of 'Pct '/' nh '/' us ' artifacts")

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

# the five choropleth labels were already correct upstream -- still asserted
CHOR_EXPECT = {
    "prop_a_city_no_canvassing_pct": "Prop A No Share (Canvassed)",
    "2024_prop_r_for": "2024 Prop R (For)",
    "2024_prop_u_against": "2024 Prop U (Against)",
    "2024_kamala": "2024 Kamala Vote Share",
    "response_rate": "Canvass Response Rate",
}
for field, want in CHOR_EXPECT.items():
    got = dashboard.label_for(dictionary, field)
    assert got == want, f"choropleth label {field}: {got!r} != {want!r}"
ok("the five choropleth labels are the readable ones")

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
    "v_" + f for f in dashboard.CHOROPLETH_FIELDS
], tokens
body = re.sub(r"\{[^{}]+\}", "", template)
for field in dashboard.CHOROPLETH_FIELDS:
    assert dashboard.label_for(dictionary, field) in template, field
    assert field not in body, f"raw field name visible in tooltip: {field}"
assert template.count("\n") == len(dashboard.CHOROPLETH_FIELDS), template
ok("tooltip template carries the precinct id plus all five labelled slots")

fc = dashboard.decorate(
    [{"properties": {dashboard.JOIN_LAYER_KEY: key}} for key in ["1046", "999999"]],
    rows,
    zero_field,
)
with_data, without_data = fc  # decorate() yields records, not features
for props in (with_data, without_data):
    slots = [k for k in props if k.startswith("v_")]
    assert len(slots) == 5, slots
assert sum(1 for k in with_data if k.startswith("v_")) == 5
# a polygon whose precinct is in the CSV: unmatched polygons get em-dashes, not gaps
assert without_data["__matched"] is False
assert without_data["__color"] == dashboard.NO_DATA_COLOR
for field in dashboard.CHOROPLETH_FIELDS:
    assert without_data["v_" + field] == dashboard.NO_DATA_TEXT, field
ok("a data-less precinct still lists all five labels, each as an em-dash")
assert with_data["__matched"] is True
assert index["1046"] is not None
ok("joined precinct carries its own values alongside the five slots")

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
          | {"v_" + f for f in dashboard.CHOROPLETH_FIELDS})
missing = sorted(needed - record_keys)
assert not missing, f"an accessor names a key the records do not carry: {missing}"
ok("every @@= prop is a JSON expression over keys the records have")
ok("Layer(id=...) is the id pydeck emits and the selection key", dashboard.LAYER_ID)

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
    """Render main() with the layer and the click both under our control."""
    dashboard._cached_features = (
        (lambda *a, **k: fc) if fc is not None else ORIG_CACHED
    )
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
        dashboard.st.pydeck_chart = ORIG_PYDECK_CHART
    assert not at.exception, f"app raised {at.exception[0].value if at.exception else ''}"
    return at


# Default load: colour field, coverage caption, 24 of 791, all on the live layer.
at = run_app()
labels5 = [dashboard.label_for(dictionary, f) for f in dashboard.CHOROPLETH_FIELDS]
side = at.selectbox[0]
assert side.label == "Colour precincts by", side.label
assert side.value == dashboard.label_for(dictionary, dashboard.DEFAULT_CHOROPLETH), side.value
assert [o for o in side.options] == labels5, side.options
assert any("24 of 791 polygons are coloured by" in c.value for c in at.caption), [c.value for c in at.caption]
assert any("1046" in c.value for c in at.caption), "exclusion not reported"
assert not any("20261108" in c.value or "data/raw" in c.value for c in at.caption), "a source path leaked into the UI"
assert any("84 of 85" in c.value for c in at.caption), "match count not stated"
ok("default load colours by prop_a_city_no_canvassing_pct and states 24 of 791 coverage")

# No selection yet: a prompt, and no empty table.
assert at.dataframe == [], f"detail table rendered with no click: {at.dataframe}"
assert any("Click a precinct" in i.value for i in at.info), [i.value for i in at.info]
assert any("Precinct detail" in s.value for s in at.subheader)
ok("no selection -> prompt to click, no empty table")

# 707 of 791 polygons hold no CSV row; each still carries all five em-dashes.
decorated = dashboard.decorate(features, rows, dashboard.DEFAULT_CHOROPLETH)
bare = [r for r in decorated if not r["__matched"]]
assert len(bare) == 791 - 84, len(bare)
assert all(r["__color"] == dashboard.NO_DATA_COLOR for r in bare)
assert all(r["v_" + fld] == dashboard.NO_DATA_TEXT for r in bare for fld in dashboard.CHOROPLETH_FIELDS)
ok("a precinct with no CSV row is unfilled and lists all five metrics as em-dashes", f"{len(bare)} of 791")

# Switch field: colours re-scale to that field's range; tooltip values do not move.
kamala = dashboard.label_for(dictionary, "2024_kamala")
at2 = run_app()
at2.selectbox[0].set_value(kamala)
at2.run()
assert any(f"84 of 791 polygons are coloured by {kamala}" in c.value for c in at2.caption), [c.value for c in at2.caption]
other = dashboard.decorate(features, rows, "2024_kamala")
same = all(
    a[k] == b[k]
    for a, b in zip(decorated, other)
    for k in a
    if k.startswith("v_") or k == "__matched"
)
assert same, "tooltip values changed when the colour field changed"
assert dashboard.tooltip_template(dictionary) == template, "tooltip is field-dependent"
ok("switching field re-scales colour and leaves all five tooltip metrics unchanged")

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

# A field the dictionary cannot name fails fast rather than rendering blank.
sabotaged = {k: v for k, v in dictionary.items() if k != "pct_nh_white"}
err = expect_raises(KeyError, dashboard.label_for, sabotaged, "pct_nh_white")
assert "pct_nh_white" in str(err), err
ok("missing dictionary entry fails fast naming the field")


print(f"\n{PASS} checks passed")
