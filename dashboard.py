"""Streamlit precinct choropleth dashboard.

Draws the county's 2026 election precincts as a pydeck choropleth, joins
data/precinct_data.csv onto each polygon on `NewPrcnt` <->
`dallas_county_precinct_number`, and turns a clicked precinct into two
side-by-side detail panels: `Precinct results` (RESULTS_PANEL_FIELDS) and
`Precinct Demographics (estimated)` (DETAIL_FIELDS, narrowed to the populated
ones).  Hovering shows TOOLTIP_FIELDS, which is its own list: the panel and the
tooltip are adjusted independently.  Every metric is labelled with its
`readable_name` from data/data_dictionary.csv -- never the raw field name.

The extract carries a row for every precinct the VTD crosswalk can attribute,
not only the precincts a canvass workbook named, so the detail panel resolves a
row for 704 of the 791 polygons; a polygon the crosswalk does not reach is the
only case that shows "no data in this research extract".  Canvass-era columns
are still blank for the precincts nobody canvassed -- blank is what they are,
not an absence of a row.

The data layer (`fetch_features`, `load_rows`, `build_dictionary`,
`join_precincts`, `color_scale`, `tooltip_template`) is pure and importable
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
from typing import Any, cast

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

# The choropleth field is user-selectable across exactly these: the three
# canvass-era metrics plus the four 2026 general-election result shares.
# TOOLTIP_FIELDS is a deliberately wider list: what hovering shows. The two
# are separate concerns, so keep them separate -- `decorate` builds the
# record keys the tooltip reads from TOOLTIP_FIELDS, never from this list.
CHOROPLETH_FIELDS = [
    "prop_a_city_no_canvassing_pct",
    "canvass_attempts",
    "response_rate",
    "2026_gov_percent_Hinojosa",
    "2026_sen_percent_Talarico",
    "2026_prop_city_percent_Against",
    "2026_prop_county_percent_For",
]
TOOLTIP_FIELDS = [
]
DEFAULT_CHOROPLETH = "prop_a_city_no_canvassing_pct"

# The two clicked-precinct panels, side by side, results first.  The headings are
# view titles, not metric labels -- metric names all come out of the data
# dictionary, but no field owns a panel's title, so these are the only user-visible
# strings defined here.
DEMOGRAPHICS_PANEL_HEADING = "Precinct Demographics (estimated)"
RESULTS_PANEL_HEADING = "Precinct results"

# The fields the `Precinct results` panel lists, authored here and ONLY here.  It
# starts as a copy of TOOLTIP_FIELDS -- the panel was introduced as "what hovering
# shows" -- but these are two separate lists on purpose so either can be adjusted
# without moving the other: nothing derives one from the other, `tooltip_template`
# and `decorate` read TOOLTIP_FIELDS while `_detail_panels` reads this one, and
# `fraction_flags` is handed each list explicitly rather than defaulting.
#
# Two consequences of editing them apart, worth knowing:
#   - A field added HERE needs only a data_dictionary entry; the panel reads the
#     joined CSV row directly.
#   - A field added to TOOLTIP_FIELDS additionally needs the `v_<field>` key
#     `decorate` writes, or its token renders as its own name.
# Colourable fields still have to stay in TOOLTIP_FIELDS: that is the tooltip's
# contract, and nothing here changes it.
RESULTS_PANEL_FIELDS = [
    "prop_a_city_no_canvassing_pct",
    "canvass_attempts",
    "response_rate",
    "strong_no",
    "response_count",
    "2024_prop_r_for",
    "2024_prop_u_against",
    "2024_kamala",
    "2020_percent_Sanders",
    "2020_percent_Biden",
    "2020_percent_Other",
    "2026_gov_percent_Hinojosa",
    "2026_sen_percent_Talarico",
    "2026_prop_city_percent_Against",
    "2026_prop_county_percent_For",
]

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
    "pct_renter_occupied",
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
# 2026-11-12), so polygons with no value paint nothing at all and are
# discoverable only by hovering or clicking.  The extract now carries a row for
# every precinct the VTD crosswalk knows, so the polygons left with no row are
# the 87 the crosswalk cannot attribute (and on the default metric the far larger
# set of precincts nobody canvassed, which have demographics but no canvass
# figure).  They stay pickable because deck.gl
# rasterises the FILL sublayer -- whose shader writes the picking colour -- and
# that sublayer does not depend on `stroked`; the picking pass renders to an FBO
# without blending and discards on the picking-validity flag, never on alpha.
NO_DATA_COLOR = [0, 0, 0, 0]

# ---------------------------------------------------------------------------
# FILL_ALPHA -- the one knob for how solid a data-bearing precinct paints.
#
# It is the alpha channel appended to every ramp colour, 0 (invisible) through
# 255 (opaque).  Anything under 255 lets the MapLibre basemap show through the
# choropleth.  Lower it to read street names under dense precincts; raise it to
# 255 for a solid, poster-like map.
#
# It lives HERE, not inside COLOR_LOW/COLOR_HIGH, on purpose: `color_scale`
# interpolates the two endpoints with zip(), which silently truncates to the
# shorter list, so an alpha baked into one endpoint but not the other drops the
# alpha channel from the entire scale -- and deck.gl sizes the colour attribute
# from the first record it sees, so a ragged mix misreads every polygon.
# ---------------------------------------------------------------------------
FILL_ALPHA = 200

# The ramp, authored as plain RGB.  See the guard below.
COLOR_LOW = [251, 210, 212]
COLOR_HIGH = [236, 31, 39]

assert len(COLOR_LOW) == len(COLOR_HIGH) == 3, (
    "COLOR_LOW/COLOR_HIGH must be plain RGB (r, g, b): opacity is FILL_ALPHA's "
    "job, and mismatched lengths truncate the whole scale via zip()"
)
NO_DATA_TEXT = "\u2014"  # em-dash: no value, distinct from 0.0
MAP_STYLE_URL = "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json"
LAYER_ID = "precincts"  # Layer(id=...) is required or selection state is unkeyed
CACHE_TTL = 900  # seconds; the geometry is "Current" and reflows rarely

# Dallas City Council districts, same FeatureServer query pattern as LAYER_URL:
# `f=geojson` so the coordinates arrive WGS84 like the precinct layer and nothing
# is reprojected client-side.  14 features, `maxRecordCount` 2000, so no pagination.
COUNCIL_LAYER_URL = (
    "https://services2.arcgis.com/rwnOSbfKSwyTBcwN/arcgis/rest/services/"
    "CouncilBoundaries/FeatureServer/0/query"
    "?where=1=1&outFields=*&returnGeometry=true&f=geojson"
)
COUNCIL_LAYER_ID = "council_districts"
# ---------------------------------------------------------------------------
# The council overlay's two colour knobs.  Both are RGBA (0-255 each, alpha
# last), both are constant colours for the WHOLE layer, and neither is the
# precinct ramp: a district boundary has to stay readable over any choropleth
# colour underneath it, so it borrows nothing from COLOR_LOW/COLOR_HIGH.
#
# COUNCIL_LINE_COLOR: the district border.  A NEUTRAL ink (R == G == B) with no
# blue cast, so it reads as a plain outline over the basemap and over any ramp
# colour it crosses.  Darker RGB than the wash below keeps the boundary legible
# inside its own district.  Drop the alpha toward 0 for a whisper of a border,
# toward 255 for hard ink; lower all three channels toward 0 for true black.
#
# COUNCIL_FILL_COLOR: the wash inside each district.  A light gray at low alpha,
# so the overlay tints the district it encloses without hiding the precinct
# choropleth inside it.  Set the alpha to 0 to return to outlines-only (the
# original Decision 2a) -- the layer keeps `filled=True`, and a zero-alpha fill
# paints nothing.
#
# Both lists must stay length 4.  deck.gl sizes a colour attribute from the
# first record it sees and applies that size to every record, so a ragged mix of
# RGB and RGBA misreads the whole layer -- the same reason FILL_ALPHA lives
# outside COLOR_LOW/COLOR_HIGH above.
# ---------------------------------------------------------------------------
COUNCIL_LINE_COLOR = [150, 150, 150, 140]  # neutral ink border, no blue cast
COUNCIL_FILL_COLOR = [200, 200, 200, 75]  # transparent light gray district wash
COUNCIL_LINE_WIDTH_MIN_PIXELS = 2  # device px, so a boundary survives zoom-out

assert len(COUNCIL_LINE_COLOR) == len(COUNCIL_FILL_COLOR) == 4, (
    "overlay colours must be full RGBA: deck.gl derives the attribute width "
    "from the first record and applies it to all of them"
)
DISTRICT_ON = "Yes"
DISTRICT_OFF = "No"


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

    One row per precinct (the extract is deduplicated to the crosswalk's dominant
    VTD for each) and no numeric value is ever averaged or aggregated across rows.
    A precinct's demographic columns therefore describe that census VTD, not the
    precinct as drawn on the layer.
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


def format_value(value: float | None, fraction: bool = True) -> str:
    """Format a parsed number for display.

    Called only on floats that `to_float` produced (or None), so no source
    string ever reaches the tooltip unformatted.

    `fraction` says whether the field holds a share (0-1) or a count.  It used
    to be guessed from the magnitude of each value, which misread counts:
    `canvass_attempts` 0 became "0.0%" and 1 became "100.0%" while 113 stayed
    "113", so one column told three stories.  Callers decide from the field's own
    populated range, which is measurable and stays consistent between the tooltip
    and the legend.
    """
    if value is None:
        return NO_DATA_TEXT
    if fraction and 0.0 <= value <= 1.0:
        return f"{value * 100:.1f}%"
    return f"{value:,.4g}"


def domain_is_share(domain: tuple[float, float] | None) -> bool:
    """True when a field's populated values all lie inside 0-1, i.e. it holds a
    share rather than a count.

    Decided once per field from the whole extract, never per value: guessing it
    from magnitude made `canvass_attempts` print "0.0%" for zero attempts and
    "100.0%" for one while 113 stayed "113", three readings for one column.
    """
    return domain is not None and domain[0] >= 0.0 and domain[1] <= 1.0


def domain_for(values: list[float | None]) -> tuple[float, float] | None:
    """Min/max of the *populated* values: scale on the field's own range.

    `2024_kamala` spans 0.0-1.0 in the current extract (precincts recorded 0 and
    1 votes for real once the crosswalk-only precincts joined), while the default
    field spans 0.0-0.71, so a shared domain would flatten one and crush the
    other.
    """
    populated = [v for v in values if v is not None]
    if not populated:
        return None
    return min(populated), max(populated)


def color_scale(value: float | None, domain: tuple[float, float] | None) -> list[int]:
    """The fill for one value: the ramp at `FILL_ALPHA`, or nothing at all.

    A real 0.0 with a populated domain lands on the scale minimum, not the empty
    style: blank and zero are different states, and only blank drops the fill.
    Alpha is appended rather than interpolated, so every painted fill shares one
    opacity and one length -- change `FILL_ALPHA`, not these colours.
    """
    if value is None or domain is None:
        return list(NO_DATA_COLOR)
    lo, hi = domain
    t = 0.0 if hi == lo else (value - lo) / (hi - lo)
    t = max(0.0, min(1.0, t))
    rgb = [round(a + (b - a) * t) for a, b in zip(COLOR_LOW, COLOR_HIGH)]
    return rgb + [FILL_ALPHA]


def tooltip_template(
    dictionary: dict[str, dict[str, str]], prefix: str = "v_"
) -> str:
    """The hover tooltip as a `{token}` template, one line per metric.

    A DIFFERENT mechanism from the `@@=` layer props: st.pydeck_chart has no
    tooltip argument and ignores deck.gl's layer-level `tooltip`, so this text
    travels in its own protobuf field (see `build_deck`) and the frontend swaps
    every `{token}` for the picked record's value.  Tokens therefore have to name
    keys `decorate` actually writes.  The result lands in the tooltip element's
    innerText, so `\\n` breaks a line and no markup is involved.
    """
    lines = [f"Precinct {{{JOIN_LAYER_KEY}}}"]
    for field in TOOLTIP_FIELDS:
        lines.append(f"{label_for(dictionary, field)}: {{{prefix}{field}}}")
    return "\n".join(lines)


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


def field_domain(rows: list[dict[str, str]], field: str) -> tuple[float, float] | None:
    """The populated min/max for one field.

    The map's colour scale and the legend are both built from this, so the two
    cannot end up describing different ranges.
    """
    return domain_for([to_float(r.get(field)) for r in rows])


def decorate(
    features: list[dict[str, Any]], rows: list[dict[str, str]], field: str
) -> list[dict[str, Any]]:
    """One pydeck record per polygon: layer attributes plus display values.

    Records, not the GeoJSON FeatureCollection, because Streamlit's deck.gl
    bridge iterates `data` directly.  A polygon's rings ride along as
    `__rings`; colour, match state and the pre-formatted tooltip metrics are plain
    keys on the record, which is what the accessors below name.
    """
    index = join_index(rows)
    domain = field_domain(rows, field)
    # Whether each tooltip field holds a share (0-1) or a count, decided once per
    # field from the whole extract -- never per value.  Outside the feature loop so
    # 791 polygons do not each re-scan all 820 rows.  Scoped to TOOLTIP_FIELDS: the
    # results panel computes its own from RESULTS_PANEL_FIELDS.
    tooltip_fractions = fraction_flags(rows, TOOLTIP_FIELDS)
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
        # The `v_` keys are the tooltip's data, so they follow TOOLTIP_FIELDS --
        # NOT CHOROPLETH_FIELDS, which only decides what you can colour by.  The
        # template emits `{v_<field>}` for every TOOLTIP_FIELDS entry and nothing
        # else, so these two lists must stay in step or an unresolved token
        # renders as its own name (e.g. "v_2024_prop_r_for") in the tooltip.
        for shown in TOOLTIP_FIELDS:
            record["v_" + shown] = format_value(
                None if row is None else to_float(row.get(shown)),
                fraction=tooltip_fractions[shown],
            )
        records.append(record)
    return records


def council_district_records(features: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One pydeck record per council polygon PART, all rings kept.

    Mirrors `decorate`'s `__rings` convention so the district layer reads the
    same key.  A MultiPolygon becomes one record per part (a record can only
    carry one ring list), and a Polygon with holes carries every ring, so inner
    rings draw -- and the holes stay unpainted under the layer's fill.
    Geometry types deck cannot render as a polygon contribute nothing rather
    than a half-built record.

    The records carry the layer attributes (`DISTRICT` etc.) for the payload only:
    this layer is NOT pickable, so nothing of it can reach a tooltip or a click.
    """
    records = []
    for feature in features:
        geometry = feature.get("geometry") or {}
        gtype = geometry.get("type")
        coordinates = geometry.get("coordinates") or []
        if gtype == "Polygon":
            parts = [coordinates]
        elif gtype == "MultiPolygon":
            parts = coordinates
        else:
            continue
        for rings in parts:
            record = dict(feature.get("properties") or {})
            record["__rings"] = rings
            records.append(record)
    return records


def fraction_flags(rows: list[dict[str, str]], fields: list[str]) -> dict[str, bool]:
    """Per-field "is this a share (0-1)?" answer, decided once over the extract.

    `fields` is required rather than defaulting to TOOLTIP_FIELDS: the hover card
    and the `Precinct results` panel are decoupled lists now, so each caller says
    which one it is formatting.  A column that reads as a percentage on one surface
    and a raw count on the other is the defect `format_value`'s docstring records,
    so the decision is made once per surface from the extract's own range.
    """
    return {f: domain_is_share(field_domain(rows, f)) for f in fields}


def detail_records(
    row: dict[str, str] | None,
    dictionary: dict[str, dict[str, str]],
    fields: list[str],
    fractions: dict[str, bool] | None = None,
) -> list[dict[str, str]]:
    """A detail panel's rows for one precinct, labelled by readable_name only.

    `fractions` carries the share-vs-count decision from `fraction_flags`; left as
    None it keeps the demographic panel's historical formatting, where every field
    is a share or a value large enough that `format_value` cannot mistake it for
    one.
    """
    if row is None:
        return []
    return [
        {
            "Metric": label_for(dictionary, f),
            "Value": format_value(
                to_float(row.get(f)), fraction=True if fractions is None else fractions[f]
            ),
        }
        for f in fields
    ]


# ---------------------------------------------------------------------------
# Colour legend -- pure string building, rendered by st.html under the map.
#
# Both swatch colours come out of `color_scale`, so the legend cannot drift from
# the map: change COLOR_LOW, COLOR_HIGH or FILL_ALPHA and the two move together.
# ---------------------------------------------------------------------------
LEGEND_BAR_WIDTH = 300  # px
LEGEND_BAR_HEIGHT = 14  # px
MUTED = "rgba(128, 128, 128, 0.75)"  # chrome only -- never a ramp colour


def _html_escape(text: object) -> str:
    """Escape a value for the legend's markup.

    Everything interpolated here is `format_value` output (digits, `%`, `,`,
    em-dash), so this is belt-and-braces -- but the legend is raw HTML and no
    text from the CSV or the live layer should ever reach it unescaped.
    """
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _css_rgba(color: list[int]) -> str:
    """An RGBA list as a CSS rgba() string, alpha normalised to 0-1."""
    red, green, blue, alpha = color
    return f"rgba({red}, {green}, {blue}, {alpha / 255:.3f})"


def legend_html(domain: tuple[float, float] | None) -> str:
    """A gradient bar labelled with the selected field's own populated min/max.

    Both degenerate domains are handled: `None` when no precinct carries a value
    for the field at all, and `lo == hi`, where a gradient would be a lie. The
    "no value" key needs a dashed outline because that style is a transparent
    fill with no border -- on the default metric it describes most of the 791
    precincts (all but those carrying a value), so a swatch that simply omitted
    its background would render as nothing at all and the legend would look
    broken.
    """
    row = "display:flex;align-items:center;gap:8px;"
    bar = f"width:{LEGEND_BAR_WIDTH}px;height:{LEGEND_BAR_HEIGHT}px;border-radius:3px;"
    edge = f"border:1px solid {MUTED};"

    if domain is None:
        scale = (
            '<div style="display:flex;align-items:center;'
            f'height:{LEGEND_BAR_HEIGHT}px;">'
            "No precinct in the extract carries a value for this metric.</div>"
        )
    else:
        lo, hi = domain
        # Same decision the tooltip makes, from the same range, so the two
        # can never label one field's endpoints differently.
        share = domain_is_share(domain)
        low = _css_rgba(color_scale(lo, domain))
        high = _css_rgba(color_scale(hi, domain))
        if lo == hi:
            swatch = f'<div style="{bar}{edge}background:{low};"></div>'
        else:
            gradient = f"linear-gradient(90deg, {low} 0%, {high} 100%)"
            swatch = f'<div style="{bar}{edge}background:{gradient};"></div>'
        scale = (
            f'<div style="{row}justify-content:space-between;'
            f'width:{LEGEND_BAR_WIDTH}px;">'
            f"<span>{_html_escape(format_value(lo, share))}</span>"
            f"<span>{_html_escape(format_value(hi, share))}</span></div>"
            f"<div>{swatch}</div>"
        )

    empty = (
        f'<div style="width:{LEGEND_BAR_HEIGHT}px;height:{LEGEND_BAR_HEIGHT}px;'
        f'border:1px dashed {MUTED};border-radius:3px;background:transparent;"></div>'
    )
    return (
        '<div style="display:flex;flex-direction:column;gap:4px;'
        'font-size:0.82rem;line-height:1.4;padding-top:2px;">'
        f"{scale}"
        # f'<div style="{row}padding-top:6px;">{empty}'
        # "<span>No value for this metric (precinct draws nothing)</span></div>"
        "</div>"
    )


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
    records: list[dict[str, Any]],
    tooltip: str,
    features: list[dict[str, Any]],
    district_records: list[dict[str, Any]] | None = None,
):
    """The Deck: PolygonLayer over a free MapLibre basemap, no key.

    `map_provider="maplibre"` with a style *URL string*; a dict style would make
    Streamlit demand mapbox.  The layer id is what the selection state keys on.

    The tooltip goes on the DECK, never the layer.  st.pydeck_chart takes no
    tooltip argument: it lifts `Deck(tooltip=dict)` into its own protobuf field
    and hands deck.gl a `getTooltip` of its own, which overrides the layer prop
    deck.gl would otherwise use.  A layer-level `tooltip` string therefore
    serialises into the spec, is never read, and the map looks perfect while no
    tooltip ever appears on hover -- the bug this comment exists to prevent.
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
    )
    layers = [layer]
    if district_records:
        # Drawn after the precinct layer, so the district wash and border sit on
        # top of the choropleth.  Both colours are layer-wide constants rather
        # than per-record accessors, but they still go through `get_*` so pydeck
        # ships them as a plain RGBA list -- not the `@@=` string trap of fc08df5.
        #
        # `pickable=False` stays (Decision 2a, unchanged): a non-pickable layer
        # cannot steal a precinct click or shadow the precinct tooltip.  Enabling
        # `filled` does NOT hand this layer picking -- the fill sublayer is what
        # writes the picking colour, but `pickable` gates the whole layer.
        #
        # The fill is a transparent light gray, so the choropleth underneath
        # still reads through it; set COUNCIL_FILL_COLOR's alpha to 0 to go back
        # to outlines only.  `line_width_min_pixels` is in device pixels, so the
        # border does not vanish when zoomed to the county.
        layers.append(
            pdk.Layer(
                "PolygonLayer",
                data=district_records,
                id=COUNCIL_LAYER_ID,
                get_polygon="__rings",
                filled=True,
                get_fill_color=list(COUNCIL_FILL_COLOR),
                stroked=True,
                get_line_color=list(COUNCIL_LINE_COLOR),
                line_width_min_pixels=COUNCIL_LINE_WIDTH_MIN_PIXELS,
                pickable=False,
                extruded=False,
            )
        )
    return pdk.Deck(
        layers=layers,
        initial_view_state=_view_state(features),
        map_provider="maplibre",
        map_style=MAP_STYLE_URL,
        # `text`, not `html`: the frontend assigns `text` through innerText, so
        # precinct ids and labels arriving from the live layer cannot inject
        # markup.  Must be a dict -- pydeck defaults this to True, and Streamlit
        # only ships the tooltip when it is a dict.  pydeck leaves this
        # parameter unannotated and defaults it to True, so type checkers
        # infer `bool` and reject the dict Streamlit actually requires.
        tooltip=cast("Any", {"text": tooltip}),
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


def _detail_panels(
    row: dict[str, str] | None,
    precinct: str | None,
    dictionary: dict[str, dict[str, str]],
    panel_fields: list[str],
    result_fractions: dict[str, bool],
) -> None:
    """The two clicked-precinct views, side by side.

    `st.columns` stacks its columns below a 640px viewport by default, so this is
    one row of two panels on a desktop and two stacked rows on a phone -- the same
    call, no breakpoint to maintain.

    Both panels always render their own heading and their own statement of what is
    missing.  A half-empty row (one panel showing a table while the other silently
    shows nothing) reads as a rendering bug rather than as absent data, which is the
    whole reason `NO_DATA_TEXT` exists.
    """
    results_col, demographics_col = st.columns(2)
    with results_col:
        st.subheader(RESULTS_PANEL_HEADING)
        _panel_column(
            row, precinct, dictionary, RESULTS_PANEL_FIELDS, result_fractions, "results"
        )
    with demographics_col:
        st.subheader(DEMOGRAPHICS_PANEL_HEADING)
        _panel_column(
            row, precinct, dictionary, panel_fields, None, "demographics"
        )


def _panel_column(
    row: dict[str, str] | None,
    precinct: str | None,
    dictionary: dict[str, dict[str, str]],
    fields: list[str],
    fractions: dict[str, bool] | None,
    noun: str,
) -> None:
    """One panel: its table, or why it has none.

    `row` None with `precinct` None is "nothing clicked yet"; `row` None with a
    `precinct` is "clicked a polygon the crosswalk cannot attribute".  The second
    phrasing stays in the rendered `st.info` channel because the test matrix asserts
    on what the browser received, not on `detail_records`' return value -- a
    function that returns [] for a None row proves nothing about the UI.
    """
    if row is None:
        if precinct is None:
            st.info(f"Click a precinct on the map to see its {noun}.")
        else:
            st.info(
                f"Precinct {precinct} has no data in this research extract, so there "
                f"is nothing to show for it."
            )
        return
    st.caption(f"Precinct {precinct} -- {len(fields)} metrics")
    st.dataframe(
        detail_records(row, dictionary, fields, fractions),
        hide_index=True,
        width="stretch",
    )


def main() -> None:
    rows = load_rows()
    dictionary = build_dictionary()
    # Fail fast, before anything renders, if the dictionary cannot name a field.
    # TOOLTIP_FIELDS (hover) and RESULTS_PANEL_FIELDS (panel) are listed separately
    # because they are separate lists: each surface needs its own fields documented,
    # and neither one is derived from the other.
    labels = {
        f: label_for(dictionary, f)
        for f in CHOROPLETH_FIELDS + DETAIL_FIELDS + TOOLTIP_FIELDS
        + RESULTS_PANEL_FIELDS
    }
    tooltip = tooltip_template(dictionary)
    panel_fields = detail_panel_fields(rows)
    # The results panel's own share/count decisions, over its own field list. The
    # hover card computes TOOLTIP_FIELDS' inside `decorate`; two lists, two calls,
    # so adding a field to one cannot KeyError out of the other's formatting.
    result_fractions = fraction_flags(rows, RESULTS_PANEL_FIELDS)
    index = join_index(rows)

    with st.sidebar:
        st.header("Map")
        chosen = st.selectbox(
            "Colour precincts by",
            [labels[f] for f in CHOROPLETH_FIELDS],
            index=CHOROPLETH_FIELDS.index(DEFAULT_CHOROPLETH),
        )
        field = next(f for f in CHOROPLETH_FIELDS if labels[f] == chosen)
        # prompt.md:155-156 -- the overlay switch is a drop-down with this exact
        # title, defaulting to "Yes".
        show_districts = st.selectbox(
            "Show Dallas Council Districts?",
            [DISTRICT_ON, DISTRICT_OFF],
            index=0,
        )
        # st.caption(
        #     f"Hover a precinct for all {len(TOOLTIP_FIELDS)} metrics; "
        #     "click one for its "
        #     "demographics.  Precincts with no value for the chosen metric draw "
        #     "nothing, but stay hoverable and clickable."
        # )

    # The title names the metric actually on the map, so a screenshot or a
    # printed page carries it without the sidebar being visible.
    st.title(labels[field])

    try:
        features = _cached_features()["features"]
    except Exception as exc:  # unreachable endpoint is a supported state
        st.error(
            f"Could not load the precinct layer from {LAYER_URL} "
            f"({type(exc).__name__}: {exc}).  Polygons are unavailable; the "
            "joined precinct fields still render below."
        )
        picked = st.selectbox("Precinct (research extract only)", sorted(index))
        _detail_panels(
            index.get(picked), picked, dictionary, panel_fields, result_fractions
        )
        return

    # Fetched only when the overlay is on, and only after the precinct layer is
    # known good, so the offline path above stays a single st.error with no
    # second failure.  A council-endpoint problem degrades to one warning and a
    # precinct-only map: it never replaces the precinct error path.
    district_records = None
    if show_districts == DISTRICT_ON:
        try:
            district_records = council_district_records(
                _cached_council_features()["features"]
            )
        except Exception as exc:
            st.warning(
                f"Could not load the Dallas Council Districts layer from "
                f"{COUNCIL_LAYER_URL} ({type(exc).__name__}: {exc}).  Showing the "
                "precinct choropleth without district boundaries."
            )
            district_records = None

    fc = decorate(features, rows, field)
    stats = join_precincts(features, rows)
    colored = sum(1 for record in fc if record["__color"] != NO_DATA_COLOR)

    chart = st.pydeck_chart(
        build_deck(fc, tooltip, features, district_records),
        on_select="rerun",
        selection_mode="single-object",
        key="precinct_map",
        width="stretch",
        height=680,
    )

    # Directly under the map, so the ramp and its range read as one unit.
    st.html(legend_html(field_domain(rows, field)))

    # The [3, 2] split that used to hold the single detail panel is gone: the row of
    # two panels needs the full width, and `st.columns` nested inside another
    # `st.columns` is the shape Streamlit's own docs warn against.  The coverage
    # captions that lived in those two containers stay parked here, commented, with
    # their values still computed above -- the panels, not the layout, are the change.
    missing = stats["unmatched"]
    # st.caption(
    #     f"{colored} of {stats['polygons']} polygons are coloured by {labels[field]}; "
    #     f"the remaining {stats['polygons'] - colored} carry no value for it and "
    #     "draw nothing."
    # )
    # if missing:
    #     st.caption(
    #         f"Excluded, no polygon in the layer ({len(missing)}): "
    #         + ", ".join(missing)
    #     )
    # st.caption(
    #     f"{stats['matched']} of {stats['csv_rows']} precincts in the research "
    #     "extract matched a polygon."
    # )

    clicked = selected_props(chart) if chart is not None else None
    precinct = (
        str(clicked.get(JOIN_LAYER_KEY, "")).strip() if clicked is not None else None
    )
    _detail_panels(
        None if precinct is None else index.get(precinct),
        precinct,
        dictionary,
        panel_fields,
        result_fractions,
    )


# Cache geometry so switching the colour field does not refetch 4.6 MB.
_cached_features = st.cache_data(ttl=CACHE_TTL)(fetch_features)
# Same TTL and same cache for the same reason: the boundary geometry rarely
# moves, and a rerun that only changes the colour field must not refetch it.
_cached_council_features = st.cache_data(ttl=CACHE_TTL)(
    lambda: fetch_features(COUNCIL_LAYER_URL)
)

# `streamlit run dashboard.py` executes this file as __main__; a bare `import
# dashboard` must not start a run, so the pure data layer stays testable.
if __name__ == "__main__":
    main()
