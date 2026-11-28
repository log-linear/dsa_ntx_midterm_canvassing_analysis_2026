"""Streamlit precinct choropleth dashboard.

Draws the county's 2026 election precincts as a pydeck PolygonLayer over a MapLibre
basemap, joins data/precinct_data.csv onto each polygon on `NewPrcnt` <->
`dallas_county_precinct_number`, and turns a clicked precinct into two
side-by-side detail panels: `Precinct results` (RESULTS_PANEL_FIELDS) and
`Precinct Demographics (estimated)` (DETAIL_FIELDS, narrowed to the populated
ones).  Hovering shows TOOLTIP_FIELDS, which is its own list: the panel and the
tooltip are adjusted independently.  Every metric is labelled with its
`readable_name` from data/data_dictionary.csv -- never the raw field name.

The colour selectbox opens on "All Precincts" (`ALL_PRECINCTS_VIEW_LABEL`), which
paints every displayed polygon one flat grey at FILL_ALPHA with a layer-wide white
hairline: a precinct with no value for any metric is visible there, which is the
one thing the choropleth cannot do because NO_DATA_COLOR is fully transparent.
Choosing a metric restores the viridis ramp, drops the stroke and brings back the
gradient legend.  Filtering, the council overlay, hover and both detail panels
behave identically in the two views -- the view changes the fill and the stroke,
never the join.

The extract carries a row for every precinct the VTD crosswalk can attribute,
not only the precincts a canvass workbook named, so the detail panel resolves a
row for 704 of the 791 polygons; a polygon the crosswalk does not reach is the
only case that shows "no data in this research extract".  Canvass-era columns
are still blank for the precincts nobody canvassed -- blank is what they are,
not an absence of a row.

Layout of the modular src/ tree: this module is the Streamlit entrypoint only.
`main()` wires the pieces together and the three `_cached_*` bindings sit beside
it because it is their only caller (and the target of the suite's monkeypatching).
The constants live in `settings`, the pure transforms in `utils/data_layer.py`
(importable without a Streamlit run context, which is what makes the plan's
edge-case matrix testable in tests/test_dashboard.py), and the HTML/pydeck/panel
builders in `utils/streamlit.py`.  The four `assert`s that used to guard the ramp
and the council overlay colours at import time now live in the test suite, next
to the checks that already prove the same invariants on the rendered payload.

Layer props are written in the @deck.gl/json expression grammar, not as Python
lambdas: Streamlit marks every string prop with `@@=` and the browser *parses*
it, so `d => d.properties.__color` is a runtime error there, not a function.

Run it with:  uv run streamlit run src/dashboard.py
"""

from __future__ import annotations

import streamlit as st

import settings
from utils import data_layer
from utils import streamlit as ui


def main() -> None:
    rows = data_layer.load_rows()
    dictionary = data_layer.build_dictionary()
    # Fail fast, before anything renders, if the dictionary cannot name a field.
    # TOOLTIP_FIELDS (hover) and RESULTS_PANEL_FIELDS (panel) are listed separately
    # because they are separate lists: each surface needs its own fields documented,
    # and neither one is derived from the other.
    labels = {
        f: data_layer.label_for(dictionary, f)
        for f in settings.CHOROPLETH_FIELDS + settings.DETAIL_FIELDS + settings.TOOLTIP_FIELDS
        + settings.RESULTS_PANEL_FIELDS
    }
    tooltip = data_layer.tooltip_template(dictionary)
    panel_fields = data_layer.detail_panel_fields(rows)
    # The results panel's own share/count decisions, over its own field list. The
    # hover card computes TOOLTIP_FIELDS' inside `decorate`; two lists, two calls,
    # so adding a field to one cannot KeyError out of the other's formatting.
    result_fractions = data_layer.fraction_flags(rows, settings.RESULTS_PANEL_FIELDS)
    index = data_layer.join_index(rows)

    with st.sidebar:
        st.header("Map")
        # One selectbox, same label, same position: "All Precincts" is an added
        # option at index 0, not a second widget, because the selected option IS
        # the view -- a separate toggle would be a second source of truth that can
        # desynchronise from the colours on the map.  The view label is not in
        # CHOROPLETH_FIELDS (it is a view, not a column), so it cannot be looked up
        # in `labels` and must not be added to any field table or the dictionary.
        chosen = st.selectbox(
            "Colour precincts by",
            [settings.ALL_PRECINCTS_VIEW_LABEL]
            + [labels[f] for f in settings.CHOROPLETH_FIELDS],
            index=0,
        )
        # None is the sentinel for the uniform view.  Without the guard the lookup
        # below raises StopIteration on an option that names no field; with it
        # `color_scale`/`field_domain` are never reached in that mode either.
        field = (
            None
            if chosen == settings.ALL_PRECINCTS_VIEW_LABEL
            else next(f for f in settings.CHOROPLETH_FIELDS if labels[f] == chosen)
        )
        # The district menu is NOT created here.  st.sidebar elements are laid out
        # in call order, so it is added below -- after the precinct layer is known
        # good -- and still lands directly beneath this selectbox.  It has to be
        # created there because its options come from the council service, and
        # building it up here would put a council request on the offline path,
        # which must stay a single st.error with no second failure behind it.
        # st.caption(
        #     f"Hover a precinct for all {len(TOOLTIP_FIELDS)} metrics; "
        #     "click one for its "
        #     "demographics.  Precincts with no value for the chosen metric draw "
        #     "nothing, but stay hoverable and clickable."
        # )

    # The title names what is on the map: the metric for a choropleth, the view
    # name for "All Precincts".  `chosen` is the option the reader can see, and in
    # metric mode it is exactly labels[field], so nothing drifts from the map.
    st.title(chosen)

    try:
        features = _cached_features()["features"]
    except Exception as exc:  # unreachable endpoint is a supported state
        st.error(
            f"Could not load the precinct layer from {settings.LAYER_URL} "
            f"({type(exc).__name__}: {exc}).  Polygons are unavailable; the "
            "joined precinct fields still render below."
        )
        picked = st.selectbox("Precinct (research extract only)", sorted(index))
        ui._detail_panels(
            index.get(picked), picked, dictionary, panel_fields, result_fractions
        )
        return

    # Reopening the sidebar rather than building the menu in the block above:
    # Streamlit collects sidebar elements in call order, so this still lands
    # directly beneath "Colour precincts by", but the district option request now
    # sits on this side of the precinct-layer guard.  On the offline path the
    # function has already returned, so a dead precinct service still means zero
    # council requests of any size -- not even the cheap one.
    #
    # The option list comes from COUNCIL_OPTIONS_URL (attributes only) rather than
    # from the boundary geometry the menu is about, so a page load that draws no
    # districts does not download 860 KB to find out which districts exist.  If that
    # listing fails, the menu is left empty WITH a warning naming the URL it tried:
    # a silently empty menu would read as "this county has no council districts".
    with st.sidebar:
        district_options: list[str] = []
        try:
            district_options = data_layer.council_district_options(
                _cached_district_options()["features"]
            )
        except Exception as exc:
            st.warning(
                f"Could not list the Dallas Council Districts from "
                f"{settings.COUNCIL_OPTIONS_URL} ({type(exc).__name__}: {exc}).  The district "
                "menu is empty, so no boundaries can be drawn."
            )
        chosen_districts = st.multiselect(
            settings.DISTRICT_SELECTOR_LABEL, options=district_options, default=settings.DEFAULT_DISTRICT_SELECTION
        )
        # Only worth saying when a choice was actually available to make; when the
        # listing failed there is already a warning explaining the empty menu.
        if district_options and not chosen_districts:
            st.caption(settings.DISTRICT_NONE_HINT)

        # The range filters sit below the district menu in their own expander, so
        # the widgets the suite asserts on above -- the colour selectbox and the
        # district multiselect -- keep their order and nothing lands before
        # "Colour precincts by".  `filter_sliders` owns the block: it drops each
        # field's stale persisted value before creating that slider, renders one
        # slider per field `filter_bounds` could bound, and closes with reset.
        # Bounds come from the extract, so no range here is a typed-in 0-1 and the
        # all-blank / single-valued fields simply get no widget.  The expander is
        # what keeps 32 sliders off the sidebar's face by default.
        bounds = data_layer.filter_bounds(rows)
        with st.expander(settings.FILTER_EXPANDER_LABEL):
            filter_ranges = ui.filter_sliders(
                rows, bounds, dictionary, ui.filter_reset
            )

    # Boundaries are fetched only for districts actually selected.  At the empty
    # default -- and whenever the option listing failed, since then nothing could
    # have been chosen -- no geometry request goes out at all, which is the same
    # guarantee the old Yes/No switch gave for "No".
    #
    # A council-endpoint problem degrades to one warning and a precinct-only map:
    # it never replaces the precinct error path.  No warning is added for a
    # selection that yields zero drawable records: the option list and the records
    # come from the same 14 single-ring polygons, so the state has no evidence of
    # being reachable (same reasoning that retired it from the overlay plan).
    district_records = None
    if chosen_districts:
        try:
            district_records = data_layer.filter_district_records(
                data_layer.council_district_records(_cached_council_features()["features"]),
                chosen_districts,
            )
        except Exception as exc:
            st.warning(
                f"Could not load the Dallas Council Districts layer from "
                f"{settings.COUNCIL_LAYER_URL} ({type(exc).__name__}: {exc}).  Showing the "
                "precinct choropleth without district boundaries."
            )
            district_records = None

    # `field=None` here is the "All Precincts" view: every record gets the uniform
    # fill, so a precinct the ramp would leave transparent is painted and edged.
    fc = data_layer.decorate(features, rows, field)
    # The mask is decided from the joined CSV and applied only to what the
    # precinct layer draws: `decorate` never learns filtering exists, so colour,
    # tooltip and both detail panels keep describing a hidden precinct.  None --
    # every slider untouched -- means `visible_records` returns `fc` itself, so a
    # default load hands the deck the identical list it always did.
    # Bounds were read once for the sliders; the same object decides what is
    # narrowed, so a slider's endpoints and the mask it feeds cannot disagree.
    visible = data_layer.visible_precincts(rows, bounds, filter_ranges)
    stats = data_layer.join_precincts(features, rows)
    colored = sum(1 for record in fc if record["__color"] != settings.NO_DATA_COLOR)

    chart = st.pydeck_chart(
        ui.build_deck(
            ui.visible_records(fc, visible),
            tooltip,
            features,
            district_records,
            # Layer-wide edge, and only for the uniform view: a choropleth keeps
            # `stroked=False`, so the two modes still differ in exactly the one
            # prop this view exists to add.
            line_colour=None if field is not None else settings.ALL_PRECINCTS_LINE_COLOR,
        ),
        on_select="rerun",
        selection_mode="single-object",
        key="precinct_map",
        width="stretch",
        height=680,
    )

    # Directly under the map, so the ramp and its range read as one unit.  Only a
    # metric has a ramp: "All Precincts" paints one colour, so a gradient bar would
    # describe a scale the map is not using.  field_domain is not called with None.
    if field is not None:
        st.html(ui.legend_html(data_layer.field_domain(rows, field)))

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

    clicked = ui.selected_props(chart) if chart is not None else None
    precinct = (
        str(clicked.get(settings.JOIN_LAYER_KEY, "")).strip() if clicked is not None else None
    )
    ui._detail_panels(
        None if precinct is None else index.get(precinct),
        precinct,
        dictionary,
        panel_fields,
        result_fractions,
    )


# Cache geometry so switching the colour field does not refetch 4.6 MB.
_cached_features = st.cache_data(ttl=settings.CACHE_TTL)(data_layer.fetch_features)
# Same TTL and same cache for the same reason: the boundary geometry rarely
# moves, and a rerun that only changes the colour field must not refetch it.
_cached_council_features = st.cache_data(ttl=settings.CACHE_TTL)(
    lambda: data_layer.fetch_features(settings.COUNCIL_LAYER_URL)
)
# The district *names* only, so the menu can be built without the geometry. Under
# 1 KB against the boundary payload's ~860 KB, and cached for the same reason as
# the two above: a rerun that changes only the colour field or the selection must
# not ask the service what districts exist.
_cached_district_options = st.cache_data(ttl=settings.CACHE_TTL)(
    lambda: data_layer.fetch_features(settings.COUNCIL_OPTIONS_URL)
)

# `streamlit run src/dashboard.py` executes this file as __main__; a bare
# `import dashboard` must not start a run, so the pure data layer stays testable.
if __name__ == "__main__":
    main()
