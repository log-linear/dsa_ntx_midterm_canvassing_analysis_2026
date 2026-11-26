"""Shared constants for the Dallas County precinct research tooling.

Everything `src/` treats as configuration is DEFINED here.  The render path reads
it attribute-style (`settings.TOOLTIP_FIELDS`), never with `from settings import
...`: `tests/test_dashboard.py` rebinds `TOOLTIP_FIELDS` / `RESULTS_PANEL_FIELDS`
and then checks the rebinding reaches the tooltip and the panel, and a module
holding its own imported copy would keep painting the old list while the test
believed it had changed one -- a check that passes vacuously, the failure class
AGENTS.md records.

The two builders are the deliberate exception.  `src/build_precinct_data.py` and
`src/build_data_dictionary.py` alias what they need into module globals
(`OUT = settings.PRECINCT_CSV`) because `main()` looks those names up at CALL time
and the suite rebinds them there (`bpd.OUT`, `build_data_dictionary.IN_CSV`) to run
a build against a temp file.  Those aliases are the test surface, so they stay;
nothing rebinds the non-path tables, and a `settings.X` rebind of an alias the
suite does not touch is inert by design.

Paths are anchored on `REPO_ROOT`, the parent of this `src/` directory, so a
builder run as `uv run python src/build_precinct_data.py` still reads and writes
`data/` at the repo root instead of creating `src/data/`.

Scope note: what does NOT move out of `src/build_data_dictionary.py` is its three
hand-authored tables -- `MANUAL`, `READABLE_OVERRIDES`, `JOIN_NOTE` -- because
those are the field vocabulary AGENTS.md says is authored in the generator, not
runtime configuration.  Everything else it reads is defined here.

`src/build_precinct_data.py` keeps no constant definitions of its own: the tables
feeding its repair/join algorithms (the ODF namespaces, `TABLE`, `HEADER_ALIASES`,
`EXPECTED_TYPE`, `MAX_SHIFT`, the per-contest measure maps) are DEFINED below and
only aliased into that module's globals.  Edit them here, not there.
"""

from __future__ import annotations

from pathlib import Path

# ---------------------------------------------------------------------------
# paths -- one anchor for the whole repo
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parents[1]
DATA = REPO_ROOT / "data"
RAW = DATA / "raw"               # every input lives here; DATA holds only output

# The two writable outputs.  One name per value: the dashboard's input CSV,
# `build_precinct_data.py`'s output and `build_data_dictionary.py`'s input are all
# the same file, so they share `PRECINCT_CSV` rather than carrying three names for
# it (the old `OUT` / `IN_CSV` collisions between the two builders are what made a
# single `settings.py` need distinct names -- last-write-wins would silently point
# one builder at the other's file).
PRECINCT_CSV = DATA / "precinct_data.csv"
DICTIONARY_CSV = DATA / "data_dictionary.csv"


# ---------------------------------------------------------------------------
# dashboard: live layers, join keys and the fields each surface shows
# ---------------------------------------------------------------------------
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
    "pct_renter_occupied",
    "pct_bachelors_plus",
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
# It lives HERE, not inside the viridis stops, on purpose: `color_scale`
# interpolates a pair of stops with zip(), which silently truncates to the
# shorter list, so an alpha baked into one stop but not its neighbour drops the
# alpha channel from every colour that segment produces -- and deck.gl sizes the
# colour attribute from the first record it sees, so a ragged mix misreads every
# polygon.  Viridis ships as plain RGB for exactly this reason.
#
# The four guards that used to sit under these definitions are in
# tests/test_dashboard.py, beside the ramp and council-overlay checks that
# already assert the same invariants on the rendered payload.  Constants here are
# data; the checks that protect them belong to the suite, not to import time.
# ---------------------------------------------------------------------------
FILL_ALPHA = 150

# ---------------------------------------------------------------------------
# The ramp: viridis, matplotlib's default perceptually-uniform sequential
# colormap, authored as plain RGB (viridis's own 9 control points).  The guards
# that used to sit under this definition are now in tests/test_dashboard.py,
# beside the ramp checks that read the same constants.
#
# Viridis replaces the old pink-to-red two-stop ramp.  Two stops only ever
# promised one thing -- more of this hue means more of that -- and could not
# keep lightness monotonic, so a pale pink precinct read as *less* than its
# neighbours by colour order alone.  Viridis varies hue AND lightness, so the
# map still separates precincts for a reader who cannot tell the hues apart and
# when printed in greyscale.
#
# Nine stops, not two: linear RGB interpolation between only the endpoints of a
# colormap cuts a chord through colour space that viridis never travels (the
# 2-stop purple->yellow midpoint is a muddy olive, not viridis's teal). The
# intermediate stops below are what make the ramp actually *be* viridis.
#
# COLOR_LOW / COLOR_HIGH name the two ENDS of the ramp -- the first and last
# stops -- so the legend and any caller that wants "the colour at the minimum"
# read them by name rather than indexing VIRIDIS_STOPS.  They are not the
# ramp's whole definition; `color_scale` samples VIRIDIS_STOPS.
# ---------------------------------------------------------------------------
VIRIDIS_STOPS: list[tuple[float, list[int]]] = [
    (0.000, [68, 1, 84]),     # #440154
    (0.125, [71, 44, 122]),   # #472c7a
    (0.250, [59, 81, 139]),   # #3b518b
    (0.375, [44, 113, 142]),  # #2c718e
    (0.500, [33, 144, 141]),  # #21908d
    (0.625, [39, 173, 129]),  # #27ad81
    (0.750, [92, 200, 99]),   # #5cc863
    (0.875, [170, 220, 50]),  # #aadc32
    (1.000, [253, 231, 37]),  # #fde725
]
COLOR_LOW = VIRIDIS_STOPS[0][1]
COLOR_HIGH = VIRIDIS_STOPS[-1][1]

NO_DATA_TEXT = "\u2014"  # em-dash: no value, distinct from 0.0
MAP_STYLE_URL = "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json"
LAYER_ID = "precincts"  # Layer(id=...) is required or selection state is unkeyed
CACHE_TTL = 900  # seconds; the geometry is "Current" and reflows rarely

# The council layer's district number, as the service spells it.  One name for the
# property key, the option list and the query that builds it, so a rename on the
# service side is a one-line fix here rather than three places that silently
# disagree.  The values arrive as the strings "1".."14".
DISTRICT_FIELD = "DISTRICT"

# Dallas City Council districts, same FeatureServer query pattern as LAYER_URL:
# `f=geojson` so the coordinates arrive WGS84 like the precinct layer and nothing
# is reprojected client-side.  14 features, `maxRecordCount` 2000, so no pagination.
COUNCIL_LAYER_BASE = (
    "https://services2.arcgis.com/rwnOSbfKSwyTBcwN/arcgis/rest/services/"
    "CouncilBoundaries/FeatureServer/0/query"
)
COUNCIL_LAYER_URL = (
    f"{COUNCIL_LAYER_BASE}?where=1=1&outFields=*&returnGeometry=true&f=geojson"
)
# Same service, same field, geometry dropped.  This is what the district menu is
# built from, and it has to stay cheap: the menu renders on every load while the
# boundaries are drawn only when something is picked, so asking the geometry
# endpoint for the option list would pull ~860 KB on a load that draws none of it.
COUNCIL_OPTIONS_URL = (
    f"{COUNCIL_LAYER_BASE}?where=1=1&outFields={DISTRICT_FIELD}"
    "&returnGeometry=false&f=geojson"
)
COUNCIL_LAYER_ID = "council_districts"
# ---------------------------------------------------------------------------
# The council overlay's two colour knobs.  Both are RGBA (0-255 each, alpha
# last), both are constant colours for the WHOLE layer, and neither is the
# precinct ramp: a district boundary has to stay readable over any choropleth
# colour underneath it, so it borrows nothing from VIRIDIS_STOPS.
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
# outside the viridis stops above.
# ---------------------------------------------------------------------------
COUNCIL_LINE_COLOR = [75, 75, 75, 200]  # neutral ink border, no blue cast
COUNCIL_FILL_COLOR = [200, 200, 200, 75]  # transparent light gray district wash
COUNCIL_LINE_WIDTH_MIN_PIXELS = 2  # device px, so a boundary survives zoom-out

# The district menu's caption.  The menu's values are the district numbers the
# service reports, so nothing else needs a name of its own.  (It superseded the
# earlier Yes/No overlay switch that used to be the widget here.)
DISTRICT_SELECTOR_LABEL = "Dallas Council Districts"
# With no choice made the menu reads as an empty box, which does not say "the map
# has no overlay".  This caption is what makes the empty state legible.
DISTRICT_NONE_HINT = "No districts selected -- no boundaries on the map."
DEFAULT_DISTRICT_SELECTION = ["1", "2", "5", "9"]

# ---------------------------------------------------------------------------
# Colour legend geometry.  The swatch colours are NOT here on purpose: they come
# out of `color_scale`/`ramp_rgb`, so the legend cannot drift from the map --
# change VIRIDIS_STOPS or FILL_ALPHA and the two move together.  Only the pixel
# box and the chrome colour live here.
# ---------------------------------------------------------------------------
LEGEND_BAR_WIDTH = 300  # px
LEGEND_BAR_HEIGHT = 14  # px
MUTED = "rgba(128, 128, 128, 0.75)"  # chrome only -- never a ramp colour


# ---------------------------------------------------------------------------
# build_precinct_data.py: ODF parsing, header repair, and the join inputs
# ---------------------------------------------------------------------------
TABLE = "{urn:oasis:names:tc:opendocument:xmlns:table:1.0}"
OFFICE = "{urn:oasis:names:tc:opendocument:xmlns:office:1.0}"

# Sheets disagree on wording/case for the same metric.  UNION aligns columns by
# name, so fold the known variants onto one canonical name.  "2028 Turnout" is a
# typo in District 9 / "Apartment City": it sits in the same column position as
# "2024 turnout" everywhere else, and there is no 2028 general election yet.
HEADER_ALIASES = {"2028_turnout": "2024_turnout"}

# Expected ODF value-type per metric column, used to detect shifted rows.
# `strong_no` is deliberately absent: the sheets store both counts and
# percentages in it, so its type carries no signal.
EXPECTED_TYPE = {
    "2024_prop_r_for": "percentage",
    "2024_prop_u_against": "percentage",
    "2024_kamala": "percentage",
    "2024_turnout": "percentage",
    "2026_registered": "float",
    "canvass_attempts": "float",
    "response_rate": "percentage",
}
MAX_SHIFT = 1  # the only observed mis-alignment is one column left

# ---------------------------------------------------------------------------
# build_precinct_data.py: inputs and the field names it writes
# ---------------------------------------------------------------------------
# Every raw input lives under RAW; DATA holds only output.  These four paths are
# read at call time inside the build so the suite can point them at a temp file
# and prove a bad input aborts BEFORE the writer opens -- the extract is written
# with "w" and has no dry-run, so a truncated output over committed data is the
# failure mode being guarded.
ODS_FILES = sorted(RAW.glob("*.ods"))
VTD_MAP_CSV = RAW / "dallas_vtd_to_county_precinct.csv"
DFS_EXPORT_CSV = RAW / "dfs-export-precinct-20261108" / "data.csv"
COMB_ROLLUP_CSV = RAW / "precinct_comb.csv"  # county results roll-up, one row per (county, precinct)
COMB_COUNTY = "Dallas"   # the only county whose rows this build joins
COMB_COUNTY_COL = "county"
COMB_KEY_COL = "precinct"

# --- 2026 general election: three official per-precinct result files -------
GOV_CSV = RAW / "2026_governor_general_precinct.csv"
SEN_CSV = RAW / "2026_senate_general_precinct.csv"
PROPS_CSV = RAW / "2026_props_general_precinct.csv"  # long format: one row per precinct per proposition
GENERAL_KEY_COL = "new_precinct"        # `113:<dallas county precinct code>`
GENERAL_KEY_PREFIXES = {"113"}          # Dallas; every key in all three files carries it
GENERAL_REGISTERED_COL = "Registered"
GENERAL_PROPS_COL = "Proposition"       # discriminator: `city` / `county`
GENERAL_PROPS = ("city", "county")

# Output names, namespaced by contest (decision 2a): `votes_Other` appears in
# both race files and `votes_For` in both proposition rows, so no source name
# can be carried verbatim.  `Registered` is carried once, from the governor
# file, after asserting all four files agree on it for every matched precinct
# (decision 2b).  A source column outside these maps aborts the build rather
# than being promoted silently the way comb_columns() promotes one.
GOV_MEASURES = {
    "votes_Abbott": "2026_gov_votes_Abbott",
    "votes_Hinojosa": "2026_gov_votes_Hinojosa",
    "votes_Other": "2026_gov_votes_Other",
    "percent_Abbott": "2026_gov_percent_Abbott",
    "percent_Hinojosa": "2026_gov_percent_Hinojosa",
    "percent_Other": "2026_gov_percent_Other",
    "percent_Turnout": "2026_gov_percent_Turnout",
}
SEN_MEASURES = {
    "votes_Paxton": "2026_sen_votes_Paxton",
    "votes_Talarico": "2026_sen_votes_Talarico",
    "votes_Other": "2026_sen_votes_Other",
    "percent_Paxton": "2026_sen_percent_Paxton",
    "percent_Talarico": "2026_sen_percent_Talarico",
    "percent_Other": "2026_sen_percent_Other",
    "percent_Turnout": "2026_sen_percent_Turnout",
}
PROPS_MEASURES = {
    "city": {
        "votes_For": "2026_prop_city_votes_For",
        "votes_Against": "2026_prop_city_votes_Against",
        "percent_For": "2026_prop_city_percent_For",
        "percent_Against": "2026_prop_city_percent_Against",
        "percent_Turnout": "2026_prop_city_percent_Turnout",
    },
    "county": {
        "votes_For": "2026_prop_county_votes_For",
        "votes_Against": "2026_prop_county_votes_Against",
        "percent_For": "2026_prop_county_percent_For",
        "percent_Against": "2026_prop_county_percent_Against",
        "percent_Turnout": "2026_prop_county_percent_Turnout",
    },
}
GENERAL_CONTESTS = [
    ("gov", GOV_MEASURES),
    ("sen", SEN_MEASURES),
    ("city", PROPS_MEASURES["city"]),
    ("county", PROPS_MEASURES["county"]),
]
GENERAL_REGISTERED_OUT = "2026_registered_general"

# Canvass-workbook placeholders the official results supersede (decision 3a).
# They stay in the .ods union read, so fullness() and choose_shift() scoring is
# byte-unchanged; only the writer excludes them (decision 3b).
RETIRED_GENERAL_COLS = ("2026_turnout", "2026_bond", "2026_talarico", "2026_hinojosa")

PRECINCT_COL = "dallas_county_precinct_number"
GROUP_COL = "precinct_group"
ALIGN_COL = "sheet_column_alignment"
SHARE_COL = "share_of_county_precinct"  # crosswalk: how much of the precinct this VTD covers
RESPONSE_COUNT_COL = "response_count"  # estimated households reached: round(canvass_attempts * response_rate)
NO_PCT_COL = "prop_a_city_no_canvassing_pct"   # no-rate of responders: strong_no / response_count
RENTER_COL = "pct_renter_occupied"  # complement of the DFS owner-occupied share

# Columns the fullness score ignores: they are filled on every row (key,
# provenance, grain, alignment audit), so counting them would make the winner
# rule meaningless.  Shared by `dedupe_output_by_precinct()` and
# `crosswalk_only_rows()` so the widening scores candidates by exactly the same
# rule the fan-out dedupe uses -- one definition, not a copy that can drift.
DEDUPE_SKIP = (PRECINCT_COL, GROUP_COL, "district", ALIGN_COL, "source_file")

# The roll-up's 20 measures, in source order.  Three of them arrive under an
# existing field name instead of their own (decision 1a): the .ods canvass
# workbooks used to supply these shares, and the official county result
# supersedes them while the name, its label and the dashboard code naming it
# all stay put.  A source column consumed this way is not also carried under
# its own name, so 3 of the 20 fold in and 17 arrive as new columns.
COMB_OVERLAYS = {
    "2024_percent_Harris": "2024_kamala",
    "2024_percent_For_R": "2024_prop_r_for",
    "2024_percent_Against_U": "2024_prop_u_against",
}


# ---------------------------------------------------------------------------
# build_data_dictionary.py: its remaining input path and its two type knobs
# ---------------------------------------------------------------------------
DFS_DICT_CSV = RAW / "dfs-export-precinct-20261108" / "dictionary.csv"

# Identifiers: numeric-looking, but arithmetic on them is meaningless.
FORCE_TEXT = {
    "dallas_county_precinct_number",
    "census_vtd_id",
    "census_vtd_geoid",
    "source_ref",
    "district",
    "name",
    "geography_hierarchy",
}

# Placeholder strings a human typed instead of a number.  They do not make a
# numeric column textual; they are reported as a caveat on the numeric type.
SENTINELS = {"N/A", "NA", "n/a", "n\\A", "-", "--", "None", "null"}
