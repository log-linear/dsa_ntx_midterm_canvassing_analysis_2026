"""Streamlit precinct choropleth dashboard.

Draws the county's 2026 election precincts as a pydeck choropleth, joins
data/precinct_data.csv onto each polygon on `NewPrcnt` <->
`dallas_county_precinct_number`, and turns a clicked precinct into a
demographic detail panel.  Every metric is labelled with its `readable_name`
from data/data_dictionary.csv -- never the raw field name.

The data layer (`fetch_features`, `load_rows`, `build_dictionary`,
`join_precincts`, `color_scale`, `tooltip_html`) is pure and importable without
a Streamlit run context, which is what makes the plan's edge-case matrix
testable in tests/test_dashboard.py.

Run it with:  uv run streamlit run dashboard.py
"""

from __future__ import annotations

import copy
import csv
import json
import urllib.request
from pathlib import Path

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

# no-data is a first-class style, not an absence of style
GREY = [200, 200, 200]
COLOR_LOW = [247, 222, 195]
COLOR_HIGH = [112, 0, 91]
LINE_COLOR = [72, 72, 72, 255]  # outlines keep precincts legible if tiles fail
NO_DATA_TEXT = "\u2014"  # em-dash: no value, distinct from 0.0
MAP_STYLE_URL = "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json"
LAYER_ID = "precincts"  # Layer(id=...) is required or selection state is unkeyed
CACHE_TTL = 900  # seconds; the geometry is "Current" and reflows rarely


# ---------------------------------------------------------------------------
# pure data layer -- importable with no Streamlit run context
# ---------------------------------------------------------------------------
def fetch_features(url: str = LAYER_URL, timeout: int = 30) -> dict:
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


def load_rows(path: Path = IN_CSV) -> list[dict]:
    """The precinct rows as strings, exactly as the CSV holds them.

    One row per precinct (the extract is deduplicated) and no numeric value is
    ever averaged or aggregated across rows.
    """
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def build_dictionary(path: Path = DICT_CSV) -> dict[str, dict]:
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


def label_for(dictionary: dict[str, dict], field: str) -> str:
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
    """Two-colour interpolation across `domain`; blank -> grey "no data".

    A real 0.0 with a populated domain lands on the scale minimum, not grey:
    blank and zero are different states.
    """
    if value is None or domain is None:
        return list(GREY)
    lo, hi = domain
    t = 0.0 if hi == lo else (value - lo) / (hi - lo)
    t = max(0.0, min(1.0, t))
    return [round(a + (b - a) * t) for a, b in zip(COLOR_LOW, COLOR_HIGH)]


def tooltip_html(dictionary: dict[str, dict], prefix: str = "v_") -> str:
    """pydeck tooltip template carrying all five choropleth metrics.

    The template holds `{placeholder}` tokens only; the values are pre-formatted
    into each feature's properties as `<prefix><field>` by `decorate()`.  All
    five labels show whichever field is selected for colour.
    """
    parts = [f"<b>Precinct {{{JOIN_LAYER_KEY}}}</b>"]
    for field in CHOROPLETH_FIELDS:
        parts.append(f"<br/>{label_for(dictionary, field)}: {{{prefix}{field}}}")
    return "".join(parts)


def join_index(rows: list[dict]) -> dict[str, dict]:
    """Key the CSV by precinct number.  Already one row per precinct, so there
    is no row-picking rule to apply."""
    return {
        r[JOIN_CSV_KEY].strip(): r
        for r in rows
        if (r.get(JOIN_CSV_KEY) or "").strip()
    }


def layer_keys(features: list[dict]) -> set[str]:
    """The layer's NewPrcnt values, as text."""
    return {str(f["properties"].get(JOIN_LAYER_KEY, "")).strip() for f in features}


def join_precincts(features: list[dict], rows: list[dict]) -> dict:
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


def detail_panel_fields(rows: list[dict], fields: list[str] | None = None) -> list[str]:
    """Decision 1c: omit fields that are blank in *every* row.

    Decided from the data rather than hard-coded, so a field that later gains
    values appears in the panel without an edit here.
    """
    fields = DETAIL_FIELDS if fields is None else fields
    return [f for f in fields if any(to_float(r.get(f)) is not None for r in rows)]


def bbox(features: list[dict]) -> tuple[float, float, float, float] | None:
    """lon/lat extent read straight off the WGS84 coordinates as delivered."""
    lo = lon_max = lat_min = lat_max = None
    for f in features:
        for ring in (f.get("geometry") or {}).get("coordinates") or []:
            for lon, lat in ring:
                lo = lon if lo is None else min(lo, lon)
                lon_max = lon if lon_max is None else max(lon_max, lon)
                lat_min = lat if lat_min is None else min(lat_min, lat)
                lat_max = lat if lat_max is None else max(lat_max, lat)
    if lo is None:
        return None
    return lo, lat_min, lon_max, lat_max


def decorate(features: list[dict], rows: list[dict], field: str) -> dict:
    """Deep copy of the FeatureCollection with per-feature display properties.

    Per-feature colours must be injected into each feature's `properties`
    (`__color`); a fixed [r,g,b] would paint every polygon identically.  The
    pre-formatted tooltip values ride along on `v_<field>`.
    """
    fc = copy.deepcopy({"type": "FeatureCollection", "features": features})
    index = join_index(rows)
    domain = domain_for([to_float(r.get(field)) for r in rows])
    for feature in fc["features"]:
        props = feature["properties"]
        row = index.get(str(props.get(JOIN_LAYER_KEY, "")).strip())
        props["__color"] = color_scale(
            None if row is None else to_float(row.get(field)), domain
        )
        props["__matched"] = row is not None
        for choropleth in CHOROPLETH_FIELDS:
            props["v_" + choropleth] = format_value(
                None if row is None else to_float(row.get(choropleth))
            )
    return fc


def detail_records(row: dict | None, dictionary: dict[str, dict], fields: list[str]) -> list[dict]:
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


def _view_state(features: list[dict]):
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


def build_deck(fc: dict, tooltip: str, features: list[dict]):
    """The Deck: PolygonLayer over a free MapLibre basemap, no key.

    `map_provider="maplibre"` with a style *URL string*; a dict style would make
    Streamlit demand mapbox.  The layer id is what the selection state keys on.
    """
    pdk = _pydeck()
    layer = pdk.Layer(
        "PolygonLayer",
        data=fc,
        id=LAYER_ID,
        get_fill_color="d => d.properties.__color",
        get_line_color=list(LINE_COLOR),
        get_line_width=1.2,
        line_thickness=1.5,
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


def selected_props(selection) -> dict | None:
    """Clicked feature attributes, at .selection.objects[<layer_id>]."""
    inner = getattr(selection, "selection", None)
    objects = getattr(inner, "objects", None) or {}
    hit = objects.get(LAYER_ID) if isinstance(objects, dict) else None
    if isinstance(hit, list) and hit:
        return hit[0]
    if isinstance(hit, dict):
        return hit
    return None


def _detail_block(row: dict | None, precinct: str, dictionary, panel_fields) -> None:
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
    tooltip = tooltip_html(dictionary)
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
            "demographics.  Grey polygons hold no value for the chosen metric."
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
    colored = sum(1 for f in fc["features"] if f["properties"]["__color"] != GREY)

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
            f"the remaining {stats['polygons'] - colored} carry no value for it and are "
            "drawn grey."
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


# Resolve Streamlit lazily so the pure data layer above imports without it.
try:
    import streamlit as st
except Exception:  # pragma: no cover - bare import for tests / data use
    st = None

if st is not None:
    # Cache geometry so switching the colour field does not refetch 4.6 MB.
    _cached_features = st.cache_data(ttl=CACHE_TTL)(fetch_features)

# `streamlit run dashboard.py` executes this file as __main__; a bare `import
# dashboard` must not start a run, so the pure data layer stays testable.
if __name__ == "__main__" and st is not None:
    main()
