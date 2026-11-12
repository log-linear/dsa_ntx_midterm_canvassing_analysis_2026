"""Streamlit precinct choropleth dashboard.

Draws the county's 2026 election precincts as a pydeck choropleth, joins
data/precinct_data.csv onto each polygon on `NewPrcnt` <->
`dallas_county_precinct_number`, and turns a clicked precinct into a
demographic detail panel.  Every metric is labelled with its `readable_name`
from data/data_dictionary.csv -- never the raw field name.

The data layer (`fetch_features`, `load_rows`, `build_dictionary`,
`join_precincts`, `color_scale`, `tooltip_expression`) is pure and importable
without a Streamlit run context, which is what makes the plan's edge-case matrix
testable in tests/test_dashboard.py.

Layer props are written in the @deck.gl/json expression grammar, not as Python
lambdas: Streamlit marks every string prop with `@@=` and the browser *parses*
it, so `d => d.properties.__color` is a runtime error there, not a function.

Run it with:  uv run streamlit run dashboard.py
"""

from __future__ import annotations

import csv
import json
import urllib.request

import streamlit as st
from pathlib import Path
from typing import Any

BASE = Path(__file__).resolve().parent
DATA = BASE / "data"
IN_CSV = DATA / "precinct_data.csv"
DICT_CSV = DATA / "data_dictionary.csv"

# Live ArcGIS FeatureServer REST endpoint for `2026 Election Precincts
# (Current)`.  f=geojson means geometry arrives as WGS84 lon/lat; the layer's
# native wkid 103159 (Texas South, feet) is *never* reprojected client-side.
# maxRecordCount is 2000 > 791 features, so one request needs no pagination.
LAYER_URL = (
    "https://services3.arcgis.com/zqe2kwz79KUqUvxC/arcgis/rest/services/"
    "2025_Proposed_Election_Precincts_791/FeatureServer/0/query"
    "?where=1=1&outFields=*&returnGeometry=true&f=geojson"
)
JOIN_LAYER_KEY = "NewPrcnt"
JOIN_CSV_KEY = "dallas_county_precinct_number"

# The choropleth field is user-selectable across exactly these five.
CHOROPLETH_FIELDS = [
    "prop_a_city_no_canvassing_pct",
    "2024_prop_r_for",
    "2024_prop_u_against",
    "2024_kamala",
    "response_rate",
]
DEFAULT_CHOROPLETH = "prop_a_city_no_canvassing_pct"

# The 26 detail fields from the plan, in display order.  Decision 1c narrows
# this to the ones that actually carry data (see `detail_panel_fields`), which
# in the current extract is 17; the 9 all-blank fields are omitted from the
# panel entirely rather than rendered as an em-dash.
DETAIL_FIELDS = [
    "median_age",
    "median_household_income",
    "not_us_citizen",
    "pct_age_18_64",
    "pct_age_20_39",
    "pct_bachelors_plus",
    "pct_below_poverty",
    "pct_english_only",
    "pct_family_households",
    "pct_female",
    "pct_hispanic",
    "pct_households_snap",
    "pct_hs_or_less",
    "pct_income_under_50k",
    "pct_married_couple_households",
    "pct_multi_unit",
    "pct_nh_asian",
    "pct_nh_black",
    "pct_nh_other",
    "pct_nh_white",
    "pct_owner_occupied",
    "pct_single_unit",
    "pct_spanish",
    "pct_us_born",
    "pct_vacant",
    "population_per_sq_mi",
]
NO_DATA_FIELDS = [
    "median_age",
    "median_household_income",
    "not_us_citizen",
    "pct_below_poverty",
    "pct_english_only",
    "pct_households_snap",
    "pct_spanish",
    "pct_us_born",
    "population_per_sq_mi",
]

# No data is an empty polygon: transparent fill AND no border (both requested
# 2026-11-12), so the 707 precincts with no value paint nothing at all and are
# discoverable only by hovering or clicking.  They stay pickable because deck.gl
# rasterises the FILL sublayer -- whose shader writes the picking colour -- and
# that sublayer does not depend on `stroked`; the picking pass renders to an FBO
# without blending and discards on the picking-validity flag, never on alpha.
# Every fill carries an explicit alpha.  deck.gl takes the colour attribute's
# item size from the FIRST record and applies it to all of them, so mixing
# [r,g,b] with [r,g,b,a] misreads the whole scale, not just the blanks.
NO_DATA_COLOR = [0, 0, 0, 0]
COLOR_LOW = [251, 210, 212]
COLOR_HIGH = [236, 31, 39, 255]
NO_DATA_TEXT = "\u2014"  # em-dash: no value, distinct from 0.0
MAP_STYLE_URL = "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json"
LAYER_ID = "precincts"  # Layer(id=...) is required or selection state is unkeyed
CACHE_TTL = 900  # seconds; the geometry is "Current" and reflows rarely


# ---------------------------------------------------------------------------
# pure data layer -- importable with no Streamlit run context
# ---------------------------------------------------------------------------
def fetch_features(url: str = LAYER_URL, timeout: int = 30) -> dict[str, Any]:
    """One GeoJSON FeatureCollection of polygons from the live layer.

    Stdlib urllib only: no new HTTP dependency.  Raises if the endpoint is
    unreachable or the payload is not a FeatureCollection; the UI turns that
    into a single st.error rather than a traceback.
    """
    req = urllib.request.Request(url, headers={"User-Agent": "dsa-electoral-research/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    if payload.get("type") != "FeatureCollection":
        raise ValueError(
            f"expected a GeoJSON FeatureCollection from {url}, got {payload.get('type')!r}"
        )
    return payload


def load_rows(path: Path = IN_CSV) -> list[dict[str, str]]:
    """The precinct rows as strings, exactly as the CSV holds them.

    One row per precinct (the extract is deduplicated) and no numeric value is
    ever averaged or aggregated across rows.
    """
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def build_dictionary(path: Path = DICT_CSV) -> dict[str, dict[str, str]]:
    """field_name -> {data_type, description, readable_name}."""
    with open(path, newline="", encoding="utf-8") as fh:
        return {
            r["field_name"]: {
                "data_type": r["data_type"],
                "description": r["description"],
                "readable_name": r["readable_name"],
            }
            for r in csv.DictReader(fh)
        }


def label_for(dictionary: dict[str, dict[str, str]], field: str) -> str:
    """readable_name for `field`; fails fast and names the field if absent."""
    entry = dictionary.get(field)
    if entry is None:
        raise KeyError("field is not documented in data/data_dictionary.csv: " + field)
    name = (entry.get("readable_name") or "").strip()
    if not name:
        raise ValueError(f"readable_name is blank for {field} in data/data_dictionary.csv")
    return name


def to_float(value) -> float | None:
    """Blank is no data, never zero: `""` -> None, `"0.0000"` -> 0.0."""
    if value is None:
        return None
    text = str(value).strip()
    if text == "":
        return None
    try:
        return float(text)
    except ValueError:
        return None


def format_value(value: float | None) -> str:
    """Format a parsed number for display.

    Called only on floats that `to_float` produced (or None), so no source
    string ever reaches the tooltip HTML unformatted.
    """
    if value is None:
        return NO_DATA_TEXT
    if 0.0 <= value <= 1.0:
        return f"{value * 100:.1f}%"
    return f"{value:,.4g}"


def domain_for(values: list[float | None]) -> tuple[float, float] | None:
    """Min/max of the *populated* values: scale on the field's own range.

    `2024_kamala` spans 0.51-0.85 while the default field spans 0.00-0.18, so a
    shared domain would flatten one and crush the other.
    """
    populated = [v for v in values if v is not None]
    if not populated:
        return None
    return min(populated), max(populated)


def color_scale(value: float | None, domain: tuple[float, float] | None) -> list[int]:
    """Two-colour interpolation across `domain`; blank -> transparent "no data".

    A real 0.0 with a populated domain lands on the scale minimum, not the empty
    style: blank and zero are different states, and only blank drops the fill.
    """
    if value is None or domain is None:
        return list(NO_DATA_COLOR)
    lo, hi = domain
    t = 0.0 if hi == lo else (value - lo) / (hi - lo)
    t = max(0.0, min(1.0, t))
    return [round(a + (b - a) * t) for a, b in zip(COLOR_LOW, COLOR_HIGH)]


def _js_literal(text: str) -> str:
    """`text` as a double-quoted literal for the @deck.gl/json expression grammar."""
    escaped = str(text).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return '"' + escaped + '"'


def tooltip_expression(
    dictionary: dict[str, dict[str, str]], prefix: str = "v_"
) -> str:
    """The hover tooltip as a @deck.gl/json *expression*, not HTML or JS.

    pydeck marks every string layer prop with `@@=`, and the browser parses what
    follows with the JSON-expression grammar: key lookups, literals, `+` and
    ternary -- no arrow functions, no `{token}` templates.  The returned string
    goes into the tooltip's innerText, so labels are concatenated in Python and
    only the per-precinct values are looked up at hover time.
    """
    lines = [_js_literal("Precinct ") + " + " + JOIN_LAYER_KEY]
    for field in CHOROPLETH_FIELDS:
        label = label_for(dictionary, field) + ": "
        lines.append(_js_literal(label) + " + " + prefix + field)
    return r" + '\n' + ".join(lines)


def join_index(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    """Key the CSV by precinct number.  Already one row per precinct, so there
    is no row-picking rule to apply."""
    return {
        r[JOIN_CSV_KEY].strip(): r
        for r in rows
        if (r.get(JOIN_CSV_KEY) or "").strip()
    }


def layer_keys(features: list[dict[str, Any]]) -> set[str]:
    """The layer's NewPrcnt values, as text."""
    return {str(f["properties"].get(JOIN_LAYER_KEY, "")).strip() for f in features}


def join_precincts(
    features: list[dict[str, Any]], rows: list[dict[str, str]]
) -> dict[str, Any]:
    """Cardinality of the NewPrcnt <-> dallas_county_precinct_number join."""
    index = join_index(rows)
    in_layer = layer_keys(features)
    matched = sorted(k for k in index if k in in_layer)
    return {
        "polygons": len(features),
        "csv_rows": len(index),
        "matched": len(matched),
        "matched_keys": matched,
        "unmatched": sorted(k for k in index if k not in in_layer),
    }


def detail_panel_fields(
    rows: list[dict[str, str]], fields: list[str] | None = None
) -> list[str]:
    """Decision 1c: omit fields that are blank in *every* row.

    Decided from the data rather than hard-coded, so a field that later gains
    values appears in the panel without an edit here.
    """
    fields = DETAIL_FIELDS if fields is None else fields
    return [f for f in fields if any(to_float(r.get(f)) is not None for r in rows)]


def bbox(features: list[dict[str, Any]]) -> tuple[float, float, float, float] | None:
    """lon/lat extent read straight off the WGS84 coordinates as delivered."""
    points = [
        (lon, lat)
        for f in features
        for ring in (f.get("geometry") or {}).get("coordinates") or []
        for lon, lat in ring
    ]
    if not points:
        return None
    lons = [p[0] for p in points]
    lats = [p[1] for p in points]
    return min(lons), min(lats), max(lons), max(lats)


def decorate(
    features: list[dict[str, Any]], rows: list[dict[str, str]], field: str
) -> list[dict[str, Any]]:
    """One pydeck record per polygon: layer attributes plus display values.

    Records, not the GeoJSON FeatureCollection, because Streamlit's deck.gl
    bridge iterates `data` directly.  A polygon's rings ride along as
    `__rings`; colour, match state and the pre-formatted five metrics are plain
    keys on the record, which is what the accessors below name.
    """
    index = join_index(rows)
    domain = domain_for([to_float(r.get(field)) for r in rows])
    records = []
    for feature in features:
        geometry = feature.get("geometry") or {}
        coordinates = geometry.get("coordinates") or []
        record = dict(feature.get("properties") or {})
        row = index.get(str(record.get(JOIN_LAYER_KEY, "")).strip())
        record["__rings"] = coordinates if geometry.get("type") == "Polygon" else []
        record["__color"] = color_scale(
            None if row is None else to_float(row.get(field)), domain
        )
        record["__matched"] = row is not None
        for choropleth in CHOROPLETH_FIELDS:
            record["v_" + choropleth] = format_value(
                None if row is None else to_float(row.get(choropleth))
            )
        records.append(record)
    return records


def detail_records(
    row: dict[str, str] | None,
    dictionary: dict[str, dict[str, str]],
    fields: list[str],
) -> list[dict[str, str]]:
    """The detail panel's rows for one precinct, labelled by readable_name only."""
    if row is None:
        return []
    return [
        {"Metric": label_for(dictionary, f), "Value": format_value(to_float(row.get(f)))}
        for f in fields
    ]


# ---------------------------------------------------------------------------
# Streamlit UI
# ---------------------------------------------------------------------------
def _pydeck():
    import pydeck as pdk

    return pdk


def _view_state(features: list[dict[str, Any]]):
    pdk = _pydeck()
    box = bbox(features)
    if box is None:
        return pdk.ViewState(longitude=-96.8, latitude=32.75, zoom=9, pitch=0)
    lo, lat_min, lon_max, lat_max = box
    return pdk.ViewState(
        longitude=(lo + lon_max) / 2.0,
        latitude=(lat_min + lat_max) / 2.0,
        zoom=9.4,
        pitch=0,
    )


def build_deck(
    records: list[dict[str, Any]], tooltip: str, features: list[dict[str, Any]]
):
    """The Deck: PolygonLayer over a free MapLibre basemap, no key.

    `map_provider="maplibre"` with a style *URL string*; a dict style would make
    Streamlit demand mapbox.  The layer id is what the selection state keys on.
    """
    pdk = _pydeck()
    layer = pdk.Layer(
        "PolygonLayer",
        data=records,
        id=LAYER_ID,
        get_polygon="__rings",
        get_fill_color="__color",
        # deck.gl strokes polygons by DEFAULT (PolygonLayer.defaultProps sets
        # stroked:true), so the border only goes away if this is switched off
        # explicitly.  Booleans serialise as plain values -- not the `@@=`
        # string trap of fc08df5.  auto_highlight stays on: with no border and
        # no fill, it is the only hover feedback an empty precinct can give.
        stroked=False,
        pickable=True,
        auto_highlight=True,
        extruded=False,
        tooltip=tooltip,
    )
    return pdk.Deck(
        layers=[layer],
        initial_view_state=_view_state(features),
        map_provider="maplibre",
        map_style=MAP_STYLE_URL,
    )


def selected_props(selection: Any) -> dict[str, Any] | None:
    """Clicked feature attributes, at .selection.objects[<layer_id>]."""
    inner = getattr(selection, "selection", None)
    objects = getattr(inner, "objects", None) or {}
    hit = objects.get(LAYER_ID) if isinstance(objects, dict) else None
    if isinstance(hit, list) and hit:
        return hit[0]
    if isinstance(hit, dict):
        return hit
    return None


def _detail_block(
    row: dict[str, str] | None,
    precinct: str,
    dictionary: dict[str, dict[str, str]],
    panel_fields: list[str],
) -> None:
    st.subheader("Precinct detail")
    if row is None:
        st.info(
            f"Precinct {precinct} has no data in this research extract, so there "
            "is nothing to show for it."
        )
        return
    st.caption(f"Precinct {precinct} -- {len(panel_fields)} metrics")
    st.dataframe(
        detail_records(row, dictionary, panel_fields),
        hide_index=True,
        width="stretch",
    )


def main() -> None:
    rows = load_rows()
    dictionary = build_dictionary()
    # Fail fast, before anything renders, if the dictionary cannot name a field.
    labels = {f: label_for(dictionary, f) for f in CHOROPLETH_FIELDS + DETAIL_FIELDS}
    tooltip = tooltip_expression(dictionary)
    panel_fields = detail_panel_fields(rows)
    index = join_index(rows)

    with st.sidebar:
        st.header("Map")
        chosen = st.selectbox(
            "Colour precincts by",
            [labels[f] for f in CHOROPLETH_FIELDS],
            index=CHOROPLETH_FIELDS.index(DEFAULT_CHOROPLETH),
        )
        field = next(f for f in CHOROPLETH_FIELDS if labels[f] == chosen)
        st.caption(
            "Hover a precinct for all five metrics; click one for its "
            "demographics.  Precincts with no value for the chosen metric draw "
            "nothing, but stay hoverable and clickable."
        )

    st.title("Precinct choropleth")

    try:
        features = _cached_features()["features"]
    except Exception as exc:  # unreachable endpoint is a supported state
        st.error(
            f"Could not load the precinct layer from {LAYER_URL} "
            f"({type(exc).__name__}: {exc}).  Polygons are unavailable; the "
            "joined precinct fields still render below."
        )
        picked = st.selectbox("Precinct (research extract only)", sorted(index))
        _detail_block(index.get(picked), picked, dictionary, panel_fields)
        return

    fc = decorate(features, rows, field)
    stats = join_precincts(features, rows)
    colored = sum(1 for record in fc if record["__color"] != NO_DATA_COLOR)

    chart = st.pydeck_chart(
        build_deck(fc, tooltip, features),
        on_select="rerun",
        selection_mode="single-object",
        key="precinct_map",
        width="stretch",
        height=680,
    )

    left, right = st.columns([3, 2])
    with left:
        st.caption(
            f"{colored} of {stats['polygons']} polygons are coloured by {labels[field]}; "
            f"the remaining {stats['polygons'] - colored} carry no value for it and "
            "draw nothing."
        )
        missing = stats["unmatched"]
        if missing:
            st.caption(
                f"Excluded, no polygon in the layer ({len(missing)}): "
                + ", ".join(missing)
            )
    with right:
        st.caption(
            f"{stats['matched']} of {stats['csv_rows']} precincts in the research "
            "extract matched a polygon."
        )
        clicked = selected_props(chart) if chart is not None else None
        if clicked is None:
            st.subheader("Precinct detail")
            st.info("Click a precinct on the map to see its demographics.")
        else:
            precinct = str(clicked.get(JOIN_LAYER_KEY, "")).strip()
            _detail_block(index.get(precinct), precinct, dictionary, panel_fields)


# Cache geometry so switching the colour field does not refetch 4.6 MB.
_cached_features = st.cache_data(ttl=CACHE_TTL)(fetch_features)

# `streamlit run dashboard.py` executes this file as __main__; a bare `import
# dashboard` must not start a run, so the pure data layer stays testable.
if __name__ == "__main__":
    main()
