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
