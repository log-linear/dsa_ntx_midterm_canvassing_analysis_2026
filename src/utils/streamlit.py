"""Render-side helpers: legend markup, the pydeck Deck, and the two detail panels.

The nine functions that touch streamlit/pydeck/HTML, moved out of the former
root-level `dashboard.py` so the pure transforms in `utils/data_layer.py` can
stay free of a Streamlit import.  Colour and layout values come from `settings`,
every numeric/formatting decision from `data_layer`, so the legend swatches are
the same colours `color_scale` puts on the polygons.

This module is deliberately named `streamlit.py` inside the `utils` package.
Absolute imports mean `import streamlit` below still resolves to the installed
package, not to this file: importing this module gives `utils.streamlit`, while
the `st` it binds is the site-packages package (checkable as
`utils.streamlit.st is streamlit`).  Only a `src/streamlit.py` would shadow it,
and there is none.
"""

from __future__ import annotations

import math
from typing import Any, cast

import streamlit as st

import settings
from utils import data_layer

# ---------------------------------------------------------------------------
# Colour legend -- pure string building, rendered by st.html under the map.
#
# The swatches come out of `color_scale`/`ramp_rgb`, so the legend cannot drift
# from the map: change VIRIDIS_STOPS or FILL_ALPHA and the two move together.
# ---------------------------------------------------------------------------


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
    bar = f"width:{settings.LEGEND_BAR_WIDTH}px;height:{settings.LEGEND_BAR_HEIGHT}px;border-radius:3px;"
    edge = f"border:1px solid {settings.MUTED};"

    if domain is None:
        scale = (
            '<div style="display:flex;align-items:center;'
            f'height:{settings.LEGEND_BAR_HEIGHT}px;">'
            "No precinct in the extract carries a value for this metric.</div>"
        )
    else:
        lo, hi = domain
        # Same decision the tooltip makes, from the same range, so the two
        # can never label one field's endpoints differently.
        share = data_layer.domain_is_share(domain)
        # `low` is the whole swatch when the field is single-valued; for a real
        # range the gradient below carries every stop, whose last entry is the
        # same colour `color_scale(hi, domain)` returns.
        low = _css_rgba(data_layer.color_scale(lo, domain))
        if lo == hi:
            swatch = f'<div style="{bar}{edge}background:{low};"></div>'
        else:
            # One CSS stop per viridis control point, so the bar shows the same
            # colours the polygons do.  A bare 0%/100% pair would draw the
            # straight purple->yellow chord instead: a legend promising a
            # gradient no precinct is ever painted with.
            stops = ", ".join(
                f"{_css_rgba(data_layer.ramp_rgb(pos) + [settings.FILL_ALPHA])} {pos * 100:.1f}%"
                for pos, _ in settings.VIRIDIS_STOPS
            )
            gradient = f"linear-gradient(90deg, {stops})"
            swatch = f'<div style="{bar}{edge}background:{gradient};"></div>'
        scale = (
            f'<div style="{row}justify-content:space-between;'
            f'width:{settings.LEGEND_BAR_WIDTH}px;">'
            f"<span>{_html_escape(data_layer.format_value(lo, share))}</span>"
            f"<span>{_html_escape(data_layer.format_value(hi, share))}</span></div>"
            f"<div>{swatch}</div>"
        )

    empty = (
        f'<div style="width:{settings.LEGEND_BAR_HEIGHT}px;height:{settings.LEGEND_BAR_HEIGHT}px;'
        f'border:1px dashed {settings.MUTED};border-radius:3px;background:transparent;"></div>'
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
    box = data_layer.bbox(features)
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
        id=settings.LAYER_ID,
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
                id=settings.COUNCIL_LAYER_ID,
                get_polygon="__rings",
                filled=True,
                get_fill_color=list(settings.COUNCIL_FILL_COLOR),
                stroked=True,
                get_line_color=list(settings.COUNCIL_LINE_COLOR),
                line_width_min_pixels=settings.COUNCIL_LINE_WIDTH_MIN_PIXELS,
                pickable=False,
                extruded=False,
            )
        )
    return pdk.Deck(
        layers=layers,
        initial_view_state=_view_state(features),
        map_provider="maplibre",
        map_style=settings.MAP_STYLE_URL,
        # `text`, not `html`: the frontend assigns `text` through innerText, so
        # precinct ids and labels arriving from the live layer cannot inject
        # markup.  Must be a dict -- pydeck defaults this to True, and Streamlit
        # only ships the tooltip when it is a dict.  pydeck leaves this
        # parameter unannotated and defaults it to True, so type checkers
        # infer `bool` and reject the dict Streamlit actually requires.
        tooltip=cast("Any", {"text": tooltip}),
    )


# ---------------------------------------------------------------------------
# The sidebar's range filters.
#
# One two-sided slider per field the extract can bound, each defaulting to that
# field's own populated min/max so a fresh session hides nothing.  Which fields
# get one is `data_layer.filter_bounds`'s answer, never a list maintained here.
# ---------------------------------------------------------------------------


def _span_divisor(span: int, target: int) -> int:
    """The largest divisor of `span` at least 1 and at most `target`.

    Used to pick an integer slider's step.  A step that does not DIVIDE the span
    puts the far-right handle on `min + n*step`, which is short of the bound --
    `canvass_attempts` 0-613 at step 6 lands on 612 -- so the populated maximum
    is not a reachable position and a reader who never touches the widget appears
    to have narrowed it.  613 is prime, which is exactly why the fallback matters:
    the answer here is 1, not the nearest round number.
    """
    cap = max(1, min(int(target), int(span)))
    for candidate in range(cap, 0, -1):
        if span % candidate == 0:
            return candidate
    return 1


def _slider_format(
    field: str, bound: tuple[float, float], dictionary: dict, rows: list[dict[str, str]]
) -> tuple:
    """`(dtype, axis_lo, axis_hi, step, format, scale)` for one field's slider.

    A share is drawn on a WHOLE PERCENT-POINT axis: `st.slider` applies `format` as a
    literal printf to the widget's own value, and shares are stored 0-1, so a 0-1
    widget renders `0.4` where `legend_html` renders `40.0%` -- the same field labelled
    two ways, 100x apart.  So a share's axis is `lo*100`..`hi*100` ROUNDED OUTWARD to
    integers -- floor down, ceil up, clamped to 0-100 -- with `scale` 100.0, step 1 and
    format "%d%%", and `filter_sliders` divides the value back out.  Rounding outward
    is what keeps an untouched slider inert: a populated maximum of 39.645% gets an
    axis end of 40, so the handle at rest still covers the bound instead of stranding
    it.  The mask, `filter_bounds` and every comparison therefore stay in the field's
    native unit; only the widget knows about the axis.

    dtype is int for a share, and otherwise when BOTH endpoints are integral AND every
    populated value is one.  Endpoints alone cannot carry that non-share decision: a
    native-unit field spanning 0.0-1.0 with fractional values would get an int slider
    offering 0 and 1 only, and the only narrowing it could express would hide
    everything between.  A share escapes that because its axis has 100 positions rather
    than 2, which is exactly why the whole-point requirement is safe there.  An int
    step always divides the span (`_span_divisor`), so the bound is a position the
    handle can actually reach; non-integer floats keep `span/100`.

    `format` is always a printf string: it ships in a protobuf string field, so a
    callable dies with TypeError (the `@@=` lesson of fc08df5, one layer up).  It
    follows the axis -- "%d%%" on the whole percent-point axis, "%d" for integer-valued
    fields, "%g" otherwise -- which is the same `domain_is_share` decision
    `legend_html` makes, so slider and legend agree on scale (the legend keeps one
    decimal, the slider cannot, since it only ever sits on a whole point).
    """
    lo, hi = bound
    span = hi - lo
    entry = dictionary.get(field) or {}
    whole = lo == int(lo) and hi == int(hi) and all(
        v == int(v) for v in (data_layer.to_float(r.get(field)) for r in rows) if v is not None
    )
    if data_layer.domain_is_share(bound):
        # WHOLE percentage points, rounded OUTWARD: floor down at the low end and
        # ceil up at the high end, so a bound of 39.645% becomes an axis of 0-40
        # rather than 0-39 -- rounding in would put the populated maximum off the
        # end of the scale and make a slider nobody touched hide precincts.  The
        # hair absorbs a bound that is already a whole point (40.0 exactly), which
        # naive ceil would otherwise push to 41.
        axis_lo = max(0, min(100, math.floor(lo * 100.0 + settings.SHARE_AXIS_HAIR)))
        axis_hi = max(0, min(100, math.ceil(hi * 100.0 - settings.SHARE_AXIS_HAIR)))
        if axis_hi <= axis_lo:  # a span narrower than one percentage point
            axis_hi = min(100, axis_lo + 1)
            axis_lo = max(0, axis_hi - 1)
        # int dtype with step 1 is what makes the handles move in whole points and
        # the labels print without decimals; `scale` still divides them back to the
        # field's native unit for the mask.
        return int, axis_lo, axis_hi, 1, "%d%%", 100.0
    if whole:
        return (
            int,
            int(lo),
            int(hi),
            _span_divisor(int(span), round(span / 100)),
            "%d",
            1.0,
        )
    fmt = "%d" if entry.get("data_type") == "integer" else "%g"
    return float, float(lo), float(hi), span / 100.0, fmt, 1.0


def _forget_stale_range(
    field: str, axis_bound: tuple[float, float], integral: bool = False
) -> None:
    """Delete a persisted `f_<field>` value that no longer fits `axis_bound`.

    Runs immediately BEFORE that field's `st.slider` is created, which is the
    only order that works: a value outside the widget's min/max makes Streamlit
    warn and then raise `StreamlitValueAboveMaxError`, so the stale key has to be
    gone before the widget reads it.  Deleting rather than assigning is the same
    rule reset follows -- you cannot write a value into a live widget's key -- and
    it is what lets a rebuild that narrowed a domain fall back to the new full
    range instead of crashing.

    `axis_bound` is the bound ON THE WIDGET'S OWN AXIS, not the field's native
    bound, because that is what session state holds.  Comparing a persisted axis
    value against a native bound would be wrong in both directions for a share
    field: a stale native 0.4 against an axis bound of 40.0 reads as "well inside"
    and survives, and a legitimate axis 45.0 reads as "far outside" and is thrown
    away.  `filter_sliders` scales before calling, so the two sides always match.

    `integral` marks an axis whose step is 1, i.e. one holding WHOLE percentage
    points or whole counts.  Being inside the range is not enough there: Streamlit
    accepts an off-step persisted value without warning and hands it straight back,
    so a 20.5 left over from an earlier float axis would filter at 20.5% while
    `"%d%%"` printed "20%" -- the label and the mask disagreeing by the fraction the
    label cannot show.  Treating a non-integral pair as stale drops it, and the
    slider comes back at its own full range rather than lying about one precinct's
    worth of data.  It also keeps the handles on whole points, which is the point of
    the axis.

    Bare-mode safe: with no run context the session-state proxy raises, and an
    unkeyed widget has nothing persisted anyway, so this is a no-op there.
    """
    key = settings.FILTER_SESSION_PREFIX + field
    try:
        current = st.session_state.get(key)
    except Exception:  # no runtime: nothing could have been persisted
        return
    if current is None:
        return
    lo, hi = axis_bound
    try:
        stale = current[0] < lo or current[1] > hi
        if integral and not stale:
            stale = any(float(v) != int(float(v)) for v in current[:2])
    except (TypeError, IndexError, ValueError):
        stale = True
    if stale:
        try:
            del st.session_state[key]
        except Exception:
            pass


def filter_reset() -> None:
    """The reset button's callback: delete every `f_*` key, pre-run.

    Callbacks run BEFORE the script, so on the next render each slider is created
    with no persisted value.  Deletion is the mechanism because of WHEN it happens:
    a write made after the widget exists is rejected outright by the
    already-instantiated guard (`StreamlitWidgetAlreadyInstantiatedError`), and
    `StreamlitValueAboveMaxError` is what a persisted value OUTSIDE a shrunk range
    raises at widget creation.  Deleting sidesteps both and needs no copy of the
    current bounds to be held here.

    Deletion alone does not reset the SLIDER THUMB, though -- only the map.  The
    browser keeps its own copy of every widget's value (`WidgetStateManager`), keyed
    on the element id, and deleting a server-side key leaves that id in place, so the
    client still holds the narrowed pair.  What tells the client otherwise is the
    proto's `set_value` event flag, which the backend sets only when
    `is_new_state_value(key)` or one of its restore branches fires
    (`SessionState._get_widget_state`) -- and a deletion is none of those.  So
    `filter_sliders` seeds the default back with `setdefault`, which IS a new state
    value on the run that follows a reset, and the thumb follows the map.  See
    `filter_sliders` for that half.
    """
    for key in [k for k in st.session_state if str(k).startswith(settings.FILTER_SESSION_PREFIX)]:
        del st.session_state[key]


def filter_sliders(
    rows: list[dict[str, str]],
    bounds: dict[str, tuple[float, float]],
    dictionary: dict[str, dict[str, str]],
    on_reset=None,
) -> dict[str, tuple[float, float]]:
    """Drop one range slider per bounded field, plus the reset button.

    The reset button is emitted FIRST, so it leads the expander and is reachable
    without scrolling past the slider list.  Position carries no behaviour here:
    `on_click` callbacks run before the script, so the `f_*` keys are already gone by
    the time any slider in the loop is created.

    For every field in `bounds`, in bounds order: a persisted value outside the
    field's own bounds is deleted first, then the slider is created at its full
    range.  Fields absent from `bounds` -- the all-blank ones and any
    single-valued one -- get no widget at all, the same treatment
    `detail_panel_fields` gives them, and nothing here explains the omission.
    `rows` is the extract those bounds and dtypes are read against.

    Labels come from `label_for`, so a raw field name never reaches the sidebar.
    Keys are `FILTER_SESSION_PREFIX + field`, which is what lets reset clear the
    filters as one namespace delete instead of a list of widget names maintained
    in two places.

    Returns each chosen range in the field's NATIVE unit: the pair comes back from
    the widget on its own axis and is divided by `scale` here, so a share that the
    reader set to 40-100 on a percent-point axis is handed to
    `visible_precincts`/`filter_bounds` as 0.4-1.0.  Nothing downstream ever sees
    the axis.  The division also means an int-dtype field's whole numbers arrive as
    floats, which is what the float bounds are compared against.
    """
    ranges: dict[str, tuple[float, float]] = {}
    if on_reset is not None:  # first child of the expander; see the docstring
        st.button(settings.FILTER_RESET_LABEL, on_click=on_reset)
    for field, bound in bounds.items():
        label = data_layer.label_for(dictionary, field)
        dtype, lo, hi, step, fmt, scale = _slider_format(field, bound, dictionary, rows)
        # Like with like: session state holds the AXIS value, so the staleness
        # test has to run on the axis too, not on the native bound.
        _forget_stale_range(field, (lo, hi), dtype is int)
        # Seed the full range into session state, then let the widget read it by
        # passing `value=None`.  Two reasons both halves matter:
        #   * `setdefault` is a no-op once the reader has touched the slider (the
        #     key already exists), so a drag is never overwritten; it only fills the
        #     hole a reset or a stale-drop just left.
        #   * filling it that way makes the key a NEW state value, which is what
        #     raises `set_value` on the outgoing proto -- and `set_value` is the only
        #     thing the browser's Slider honours for an already-mounted widget.  With
        #     an explicit `value=(lo, hi)` instead, a reset moves the map but leaves
        #     every thumb where the reader put it.
        # `value=None` also sidesteps the duplicate-default warning, since the policy
        # check only fires when an explicit default is passed alongside a new
        # session-state value.
        #
        # SEED AFTER `_forget_stale_range`, not before: with `value=None` the widget
        # infers single-vs-range from whatever the key holds, so seeding first lets a
        # stale pair occupy the key, get deleted below it, and leave nothing to read --
        # Streamlit then builds a SINGLE slider and `chosen[0]` dies with
        # `'int' object is not subscriptable`.
        key = settings.FILTER_SESSION_PREFIX + field
        st.session_state.setdefault(key, (dtype(lo), dtype(hi)))
        chosen = st.slider(
            label,
            min_value=dtype(lo),
            max_value=dtype(hi),
            value=None,
            step=dtype(step),
            format=fmt,
            key=key,
            help=label,
        )
        ranges[field] = (float(chosen[0]) / scale, float(chosen[1]) / scale)
    return ranges


def visible_records(
    records: list[dict[str, Any]], visible: set[str] | None
) -> list[dict[str, Any]]:
    """The deck records whose precinct survived the filters.

    `visible` None is the untouched case, and the input list comes back as the
    SAME object: no mask, no rebuild of the records, so a default load is
    byte-identical to the one from before filters existed.  Otherwise a record
    survives on its own `JOIN_LAYER_KEY` -- the precinct number `decorate`
    already carries, so filtering never enters `decorate`'s colour/token contract
    and hidden precincts keep their tooltip lines and their detail panels.

    A record that cannot name its precinct is NOT visible: the mask is keyed on
    that number, so a record which cannot state it has unprovable membership and is
    dropped -- the same ruling the frozen matrix gives a polygon the crosswalk
    cannot attribute, and the same one `layer_keys` and `decorate` already apply to
    a missing join key.  A handful of property-less polygons therefore hides itself
    instead of blanking every other precinct on the map.

    What still fails loudly is the mis-wire: `visible` is a real set, records were
    handed over, and NONE of them carries the key.  That is the wrong payload --
    council records passed where precinct records belong -- and answering it with an
    empty map would look like an over-strict filter rather than a bug.
    """
    if visible is None:
        return records
    nameable = sum(settings.JOIN_LAYER_KEY in r for r in records)
    if records and not nameable:
        raise ValueError(
            f"no record handed to the filter mask carries {settings.JOIN_LAYER_KEY!r}: "
            f"{len(records)} records of keys {sorted(records[0])[:6]}"
        )
    kept = []
    for record in records:
        if settings.JOIN_LAYER_KEY not in record:
            continue
        if str(record.get(settings.JOIN_LAYER_KEY, "")).strip() in visible:
            kept.append(record)
    return kept


def selected_props(selection: Any) -> dict[str, Any] | None:
    """Clicked feature attributes, at .selection.objects[<layer_id>]."""
    inner = getattr(selection, "selection", None)
    objects = getattr(inner, "objects", None) or {}
    hit = objects.get(settings.LAYER_ID) if isinstance(objects, dict) else None
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
        st.subheader(settings.RESULTS_PANEL_HEADING)
        _panel_column(
            row, precinct, dictionary, settings.RESULTS_PANEL_FIELDS, result_fractions, "results"
        )
    with demographics_col:
        st.subheader(settings.DEMOGRAPHICS_PANEL_HEADING)
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
        data_layer.detail_records(row, dictionary, fields, fractions),
        hide_index=True,
        width="stretch",
    )
