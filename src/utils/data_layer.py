"""The dashboard's pure data layer: fetch, join, scale, format.

Moved verbatim out of the former root-level `dashboard.py` by the modular src/
layout refactor.  Nothing here imports streamlit or pydeck, which is what keeps
the layer importable with no Streamlit run context and makes the plan's
edge-case matrix testable in tests/test_dashboard.py.

Constants are read attribute-style off `settings` rather than imported, on
purpose: `tests/test_dashboard.py` rebinds `settings.TOOLTIP_FIELDS` and then
renders the app to prove the hover card follows.  An imported copy would make
that rebinding inert, so the check would pass vacuously.
"""

from __future__ import annotations

import csv
import json
import urllib.request
from pathlib import Path
from typing import Any

import settings

# ---------------------------------------------------------------------------
# pure data layer -- importable with no Streamlit run context
# ---------------------------------------------------------------------------
def fetch_features(url: str = settings.LAYER_URL, timeout: int = 30) -> dict[str, Any]:
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


def load_rows(path: Path = settings.PRECINCT_CSV) -> list[dict[str, str]]:
    """The precinct rows as strings, exactly as the CSV holds them.

    One row per precinct (the extract is deduplicated to the crosswalk's dominant
    VTD for each) and no numeric value is ever averaged or aggregated across rows.
    A precinct's demographic columns therefore describe that census VTD, not the
    precinct as drawn on the layer.
    """
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def build_dictionary(path: Path = settings.DICTIONARY_CSV) -> dict[str, dict[str, str]]:
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
        return settings.NO_DATA_TEXT
    if fraction and -settings.SHARE_TOLERANCE <= value <= 1.0 + settings.SHARE_TOLERANCE:
        # Clamped before scaling: 1.0000000000000002 must not print as "100.0%" by
        # accident of rounding while sitting outside the band it is being clamped
        # from, and a value this far out cannot mean anything but 100%.
        return f"{max(0.0, min(1.0, value)) * 100:.1f}%"
    return f"{value:,.4g}"


def domain_is_share(domain: tuple[float, float] | None) -> bool:
    """True when a field's populated values all lie inside 0-1, i.e. it holds a
    share rather than a count.

    Decided once per field from the whole extract, never per value: guessing it
    from magnitude made `canvass_attempts` print "0.0%" for zero attempts and
    "100.0%" for one while 113 stayed "113", three readings for one column.

    `SHARE_TOLERANCE` keeps a sum-of-quotients artifact from flipping a whole
    field's axis: `pct_single_unit`'s populated maximum is 1.0000000000000002, and
    an exact `<= 1.0` here reads that as a count, which is what made the legend,
    the detail panel and the filter slider all label one column two ways.
    """
    return (
        domain is not None
        and domain[0] >= -settings.SHARE_TOLERANCE
        and domain[1] <= 1.0 + settings.SHARE_TOLERANCE
    )


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


def ramp_rgb(t: float) -> list[int]:
    """The ramp's plain-RGB colour at position `t` (0-1).

    Piecewise-linear ACROSS the viridis stops, not one interpolation between the
    two endpoints: a straight chord from purple to yellow is a muddy olive that
    viridis never travels, so a 2-stop "approximation" of a colormap is a
    different colormap.  `t` is clamped, so a value outside the domain -- which
    `color_scale` cannot produce, but a hand-passed position can -- returns the
    nearest end colour rather than indexing off the array.
    """
    t = max(0.0, min(1.0, t))
    # The stops are evenly spaced and sorted (asserted on `settings.VIRIDIS_STOPS`
    # in tests/test_dashboard.py), so
    # the bracketing pair comes straight from the index.  The last position folds
    # onto the final pair so t=1.0 lands on COLOR_HIGH exactly.
    last = len(settings.VIRIDIS_STOPS) - 2
    idx = min(int(t * (len(settings.VIRIDIS_STOPS) - 1)), last)
    t0, c0 = settings.VIRIDIS_STOPS[idx]
    t1, c1 = settings.VIRIDIS_STOPS[idx + 1]
    span = t1 - t0
    local = 0.0 if span == 0 else (t - t0) / span
    return [round(a + (b - a) * local) for a, b in zip(c0, c1)]


def color_scale(value: float | None, domain: tuple[float, float] | None) -> list[int]:
    """The fill for one value: the ramp at `FILL_ALPHA`, or nothing at all.

    A real 0.0 with a populated domain lands on the scale minimum, not the empty
    style: blank and zero are different states, and only blank drops the fill.
    Alpha is appended rather than interpolated, so every painted fill shares one
    opacity and one length -- change `FILL_ALPHA`, not these colours.
    """
    if value is None or domain is None:
        return list(settings.NO_DATA_COLOR)
    lo, hi = domain
    t = 0.0 if hi == lo else (value - lo) / (hi - lo)
    return ramp_rgb(t) + [settings.FILL_ALPHA]


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
    lines = [f"Precinct {{{settings.JOIN_LAYER_KEY}}}", "Click to show precinct demographics and electoral metrics below"]
    for field in settings.TOOLTIP_FIELDS:
        lines.append(f"{label_for(dictionary, field)}: {{{prefix}{field}}}")
    return "\n".join(lines)


def join_index(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    """Key the CSV by precinct number.  Already one row per precinct, so there
    is no row-picking rule to apply."""
    return {
        r[settings.JOIN_CSV_KEY].strip(): r
        for r in rows
        if (r.get(settings.JOIN_CSV_KEY) or "").strip()
    }


def layer_keys(features: list[dict[str, Any]]) -> set[str]:
    """The layer's NewPrcnt values, as text."""
    return {str(f["properties"].get(settings.JOIN_LAYER_KEY, "")).strip() for f in features}


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
    fields = settings.DETAIL_FIELDS if fields is None else fields
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


# The fields a range filter can be offered for: CHOROPLETH + DETAIL + RESULTS,
# de-duplicated with that precedence, so anything the reader can colour by or
# read in a panel is also something they can filter on.  Built here rather than
# in `settings` because it is a derived view of three lists, not a fourth list to
# keep in step by hand; the membership that matters stays authored there.  Order
# is user-visible -- it is the order the sliders are dropped in -- so the
# de-duplication keeps first occurrence instead of sorting.
FILTER_FIELDS = list(
    dict.fromkeys(
        settings.CHOROPLETH_FIELDS
        + settings.DETAIL_FIELDS
        + settings.RESULTS_PANEL_FIELDS
    )
)


def filter_bounds(
    rows: list[dict[str, str]], fields: list[str] | None = None
) -> dict[str, tuple[float, float]]:
    """`{field: (lo, hi)}` for the fields worth a slider, from the extract.

    Only domains with `lo < hi` survive.  That one condition is what implements
    both edge rows of the plan's matrix: a field blank across every row has no
    domain at all (`field_domain` returns None), and a single-valued field has
    `lo == hi`.  Either one handed to `st.slider` would raise
    `StreamlitInvalidMinMaxError`, so the field simply gets no widget.  Nothing
    here is a typed-in 0-1: `canvass_attempts` comes back 0-613, and a slider's
    endpoints are always the field's own populated range.
    """
    fields = FILTER_FIELDS if fields is None else fields
    bounds = {}
    for f in fields:
        domain = field_domain(rows, f)
        if domain is not None and domain[0] < domain[1]:
            bounds[f] = domain
    return bounds


def visible_precincts(
    rows: list[dict[str, str]],
    bounds: dict[str, tuple[float, float]],
    ranges: dict[str, tuple[float, float]],
) -> set[str] | None:
    """The precinct numbers that survive every narrowed range, or None.

    Returns **None** when nothing is narrowed.  That is not a micro-optimisation:
    it is what lets the untouched default leave `decorate`'s output untouched, so a
    fresh session draws the same 791 records it drew before filters existed instead
    of a re-derived copy.

    "Narrowed" is decided HERE, by a side sitting inside its bound by more than a
    relative tolerance -- never by exact equality.  A slider cannot be trusted to
    hand back its own endpoints verbatim: it reports `min + n*step` after a drag, so
    where the step does not divide the span the far-right reading falls short of the
    bound, and a share's percent-point axis is not bit-exact on the way back to the
    field's native unit.  Either one read as a narrowing would hide precincts on a
    slider the reader never touched, which the frozen default state forbids.

    Otherwise the mask is built the same way the join is: one CSV row per
    precinct, keyed on `JOIN_CSV_KEY`.  A precinct is kept only where its value
    is non-None and falls inside the range for EVERY narrowed field, so blanks on
    a narrowed field drop out (membership is unprovable, and a blank is never an
    inferred zero) while blanks on an untouched field stay visible.  A polygon the
    crosswalk cannot attribute has no row here at all, so it drops out of a
    narrowed filter for the same reason: its value is unknown.
    """
    narrowed = {}
    for f, chosen in ranges.items():
        bound = bounds.get(f)
        if bound is None:
            continue
        lo, hi = chosen
        # "Narrowed" is measured with a RELATIVE TOLERANCE, not by equality.  Two
        # reasons exact comparison is the wrong test: a slider reports
        # `min + n*step` after a drag, so a step that does not divide the span
        # cannot return the bound itself; and a share's axis round trip
        # (`lo*100/100`) is not bit-exact.  Either one would make a widget the
        # reader never touched look narrowed and hide precincts -- the frozen
        # default state forbids that.  A side counts as moved only when it is
        # inside its bound by more than a hair of the span.
        tol = (bound[1] - bound[0]) * 1e-9
        if lo > bound[0] + tol or hi < bound[1] - tol:
            narrowed[f] = (lo, hi)
    if not narrowed:
        return None
    keep = None
    for f, (lo, hi) in narrowed.items():
        # The SAME tolerance, applied to MEMBERSHIP and not only to the
        # narrowed-side test above.  A handle's reading is never bit-exact with the
        # value it points at: `pct_vacant`'s populated maximum comes back off the
        # percent axis as 0.3964497041420118 where the field says
        # 0.39644970414201186.  An exact `v <= hi` would then hide the sole holder
        # of that maximum behind a right handle displaying the identical `39.6%` --
        # a precinct disappearing on an endpoint the reader did not move.
        tol = (bounds[f][1] - bounds[f][0]) * 1e-9
        hits = {
            r[settings.JOIN_CSV_KEY].strip()
            for r in rows
            if (r.get(settings.JOIN_CSV_KEY) or "").strip()
            and (v := to_float(r.get(f))) is not None
            and lo - tol <= v <= hi + tol
        }
        keep = hits if keep is None else keep & hits
    return keep


def decorate(
    features: list[dict[str, Any]], rows: list[dict[str, str]], field: str | None
) -> list[dict[str, Any]]:
    """One pydeck record per polygon: layer attributes plus display values.

    Records, not the GeoJSON FeatureCollection, because Streamlit's deck.gl
    bridge iterates `data` directly.  A polygon's rings ride along as
    `__rings`; colour, match state and the pre-formatted tooltip metrics are plain
    keys on the record, which is what the accessors below name.

    `field=None` is the "All Precincts" view, and the ONLY non-metric case.  It
    skips `field_domain`/`color_scale` entirely and paints every record with the
    uniform `ALL_PRECINCTS_COLOR`, which is what makes a precinct that carries no
    value for any metric visible at all.  The alternative -- passing a field whose
    domain comes back None -- does not raise, it answers `NO_DATA_COLOR` for every
    record, and the map silently draws nothing: an invisible failure, not a loud
    one.  Nothing else about the record changes between the two modes; the stroke
    is a LAYER prop (`build_deck`'s `line_colour`) and never a per-record key, so
    one view cannot hand deck.gl an attribute the other omits.
    """
    index = join_index(rows)
    # Only read for a metric: with field None there is no ramp to scale onto, and
    # `domain` staying None keeps the colour branch below the sole path available.
    domain = None if field is None else field_domain(rows, field)
    # Whether each tooltip field holds a share (0-1) or a count, decided once per
    # field from the whole extract -- never per value.  Outside the feature loop so
    # 791 polygons do not each re-scan all 820 rows.  Scoped to TOOLTIP_FIELDS: the
    # results panel computes its own from RESULTS_PANEL_FIELDS.
    tooltip_fractions = fraction_flags(rows, settings.TOOLTIP_FIELDS)
    records = []
    for feature in features:
        geometry = feature.get("geometry") or {}
        coordinates = geometry.get("coordinates") or []
        record = dict(feature.get("properties") or {})
        row = index.get(str(record.get(settings.JOIN_LAYER_KEY, "")).strip())
        record["__rings"] = coordinates if geometry.get("type") == "Polygon" else []
        if field is None:
            # Every polygon, matched or not: the whole point of the view is that
            # nothing is transparent.  A fresh list per record, as `color_scale`
            # returns, so no two records share one mutable list.
            record["__color"] = list(settings.ALL_PRECINCTS_COLOR)
        else:
            record["__color"] = color_scale(
                None if row is None else to_float(row.get(field)), domain
            )
        record["__matched"] = row is not None
        # The `v_` keys are the tooltip's data, so they follow TOOLTIP_FIELDS --
        # NOT CHOROPLETH_FIELDS, which only decides what you can colour by.  The
        # template emits `{v_<field>}` for every TOOLTIP_FIELDS entry and nothing
        # else, so these two lists must stay in step or an unresolved token
        # renders as its own name (e.g. "v_2024_prop_r_for") in the tooltip.
        for shown in settings.TOOLTIP_FIELDS:
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


def council_district_options(features: list[dict[str, Any]]) -> list[str]:
    """The district numbers the menu offers, as strings, lowest first.

    Read from the layer rather than typed in, so the menu cannot offer a district
    the service no longer has or omit one it added.  `to_float` sorts them as
    numbers -- `sorted()` on the raw strings would put 10, 11, 12 between 1 and 2.

    A feature whose district is missing or non-numeric contributes no option: an
    empty choice would render a selectable nothing, and filtering on it could never
    match a record.  The values are the layer's own, never re-formatted, so whatever
    the service calls a district is exactly what the filter matches on.
    """
    seen = set()
    for feature in features:
        value = (feature.get("properties") or {}).get(settings.DISTRICT_FIELD)
        if value is None or str(value).strip() == "":
            continue
        if to_float(value) is None:
            continue
        seen.add(str(value))
    return sorted(seen, key=lambda v: (to_float(v), v))


def filter_district_records(
    records: list[dict[str, Any]], selected: list[str]
) -> list[dict[str, Any]]:
    """Only the records for chosen districts, in the layer's own order.

    Matching is exact against `DISTRICT_FIELD`, because that is the same value
    `council_district_options` listed: the menu hands back what it was given, so no
    normalisation is needed and none is attempted -- a leading-zero or whitespace
    variant would simply fail to match rather than be guessed at.

    A MultiPolygon that split into several records keeps all of them, so selecting
    one district can legitimately yield more than one record.  An empty or all-blank
    `selected` yields nothing, which is the map's "no overlay" state.
    """
    chosen = {str(s) for s in selected if str(s).strip() != ""}
    if not chosen:
        return []
    return [
        record
        for record in records
        if str(record.get(settings.DISTRICT_FIELD) or "").strip() in chosen
    ]


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
