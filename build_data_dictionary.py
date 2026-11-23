"""Build data/data_dictionary.csv for every field in data/precinct_data.csv.

Columns: field_name, data_type, description, readable_name.

Coverage strategy
1. The 58 fields inherited from the Dallas Fair Districts export keep their own
   published metadata (data/raw/dfs-export-precinct-20261108/dictionary.csv:
   `label` -> readable_name, `description` -> description).  Those descriptions
   are written for the DFS profile, so a source note naming the joined key is
   appended where one exists.
2. Fields created by this project (the .ods union, the VTD mapping, the county
   results roll-up precinct_comb.csv, and the derived ratios) are described by
   hand in MANUAL below.
3. data_type is *observed*, not declared: it is inferred from the values that
   actually appear in precinct_data.csv, so a column whose source calls itself a
   number but which carries text is reported honestly.  Columns listed in
   FORCE_TEXT are identifiers whose digits are not quantities, so they stay text
   even when they parse as integers.

Run after build_precinct_data.py; it reads the output, so it must not run first.
"""

import csv
from pathlib import Path

BASE = Path(__file__).resolve().parent
DATA = BASE / "data"
RAW = DATA / "raw"
IN_CSV = DATA / "precinct_data.csv"
DFS_DICT = RAW / "dfs-export-precinct-20261108" / "dictionary.csv"
OUT = DATA / "data_dictionary.csv"

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

MANUAL = {
    # --- union of the .ods sheets (data/raw/District {1,2,9} precincts.ods) ---
    "dallas_county_precinct_number": (
        "text",
        "Dallas County precinct number: this extract's row key, one row per code. "
        "A row arrives by one of two routes -- either the unnamed first column of "
        "a sheet in the three district canvassing workbooks, or, for precincts no "
        "workbook named, a `dallas_county_precinct_id` in the VTD crosswalk. Join "
        "key to the VTD mapping and, with the county, to the precinct results "
        "roll-up; compared as TEXT, so codes like 0024 and 30C4 survive.",
        "Dallas County Precinct Number",
    ),
    "precinct_group": (
        "text",
        "Name of the .ods sheet the row came from; a precinct group is the set of "
        "precincts one district worksheet covers (e.g. 'Casa View', 'Far Westside').",
        "Precinct Group",
    ),
    "district": (
        "text",
        "Dallas City Council district, taken from the source workbook filename "
        "(District 1 / District 2 / District 9).",
        "Council District",
    ),
    "sheet_column_alignment": (
        "text",
        "Audit flag for the alignment repair. 'aligned' means the row's cells sat "
        "under their own headers; 'shifted_left_1_corrected' means the metric values "
        "were keyed one column left of their headers in the source and have been "
        "shifted right. 22 District 2 rows were corrected.",
        "Source Row Alignment",
    ),
    "2024_prop_r_for": (
        "number",
        "Share of the 2024 vote on Proposition 14 (Prop R) cast FOR, as recorded in "
        "the county results roll-up (fraction 0-1). Blank where the precinct has no "
        "Dallas row in that file, or where that row leaves the measure empty.",
        "2024 Prop R (For)",
    ),
    "2024_prop_u_against": (
        "number",
        "Share of the 2024 vote on Proposition 5 (Prop U) cast AGAINST, as recorded "
        "in the county results roll-up (fraction 0-1). Blank where the precinct has "
        "no Dallas row in that file, or where that row leaves the measure empty.",
        "2024 Prop U (Against)",
    ),
    "2024_kamala": (
        "number",
        "Share of the 2024 presidential vote cast for Harris/Walz in this precinct, "
        "as recorded in the county results roll-up (fraction 0-1). Blank where the "
        "precinct has no Dallas row in that file, or where that row leaves the "
        "measure empty.",
        "2024 Kamala Vote Share",
    ),
    "2024_turnout": (
        "number",
        "Turnout as a share of registered voters in the 2024 general election "
        "(fraction 0-1). District 9's 'Apartment City' sheet headed this column "
        "'2028 Turnout'; that typo is aliased onto this field.",
        "2024 Turnout Share",
    ),
    "2026_registered": (
        "integer",
        "Registered voters in the precinct as recorded in the canvassing "
        "workbooks ahead of the 2026 canvass. A canvass-period figure, not the "
        "official general-election count, which is carried separately as "
        "2026_registered_general; the two are not interchangeable.",
        "2026 Registered Voters (Canvass)",
    ),
    "canvass_attempts": (
        "integer",
        "Total canvas attempts (i.e. knocked doors) within a given precinct.",
        "Canvass Attempts",
    ),
    "response_rate": (
        "number",
        "Share of canvassed households that responded (fraction 0-1). ",
        "Canvass Response Rate",
    ),
    "strong_no": (
        "integer",
        "Number of canvassed voters (i.e. those who answered the door) who indicated 'strong no' on Prop A",
        "Total Strong No Responses",
    ),
    "source_file": (
        "text",
        "Filename of the .ods workbook the row came from, for provenance.",
        "Source Workbook",
    ),
    # --- inherited from the DFS export, re-authored: the source's own
    # description of this column misstates its grain (see JOIN_NOTE below). ---
    "name": (
        "text",
        "Census voting-district identifier of the VTD this row's demographic "
        "figures describe -- the export's own seat name, which is a VTD code "
        "(`source_ref` == '48113' + `name`), NOT a Dallas County precinct number. "
        "The two namespaces are both four digits and coincide for some precincts "
        "while describing different ground, so this column is never a join key "
        "here: precincts are attributed through the VTD crosswalk only.",
        "Name",
    ),
    # --- data/raw/dallas_vtd_to_county_precinct.csv ---
    "census_vtd_id": (
        "text",
        "Census voting-district identifier from the county precinct-to-VTD crosswalk. "
        "A precinct does map to several VTDs in that file, but the fan-out is "
        "collapsed before writing: this extract holds one row per precinct, so this "
        "column names the single VTD whose DFS figures were kept, not every VTD the "
        "precinct touches.",
        "Census VTD ID",
    ),
    "census_vtd_geoid": (
        "text",
        "Full Census GEOID of the voting district named by census_vtd_id; join key "
        "to the demographic export's `source_ref`.",
        "Census VTD GEOID",
    ),
    "share_of_vtd": (
        "number",
        "Share of this census VTD that falls inside the precinct (fraction 0-1).",
        "Share of VTD in Precinct",
    ),
    "share_of_county_precinct": (
        "number",
        "Share of the county precinct covered by this census VTD (fraction 0-1); "
        "sums to 1 across a precinct's VTDs except precinct 1057, which is recorded "
        "in two districts.",
        "Share of County Precinct",
    ),
    # --- data/raw/precinct_comb.csv (county results roll-up, official canvass) ---
    # Three further measures from this file arrive under a field the canvass
    # workbooks used to fill: see the .ods section above for 2024_kamala,
    # 2024_prop_r_for and 2024_prop_u_against.
    #
    # These are 2020 Democratic PRIMARY figures, not the 2020 general election.
    # Decisive: Bernie Sanders appears among the vote columns and he was not on
    # the 2020 general ballot; the file names no Republican for 2020 at all; and
    # each precinct's Biden+Sanders+Other total matches DFS
    # president_2020_total_votes on 0 of 84 rows while running about a third of
    # the 2024 presidential total.  This table also carries the general-election
    # Democratic share as president_2020_dem_share (DFS), which for 4079 reads
    # 0.7633 where 2020_percent_Biden reads 0.4537 -- the two disagree in 84 of
    # 84 rows, so they are not interchangeable and each field names its contest.
    "2020_votes_Biden": (
        "integer",
        "Votes cast for Joseph Biden in the 2020 Democratic presidential primary "
        "in this precinct, as recorded in the county results roll-up. Blank where "
        "the precinct has no Dallas row in that file, or where its Dallas row "
        "leaves the measure empty.",
        "2020 Primary Votes Biden",
    ),
    "2020_votes_Sanders": (
        "integer",
        "Votes cast for Bernie Sanders in the 2020 Democratic presidential primary "
        "in this precinct, as recorded in the county results roll-up. Blank where "
        "the precinct has no Dallas row in that file, or where its Dallas row "
        "leaves the measure empty.",
        "2020 Primary Votes Sanders",
    ),
    "2020_votes_Other": (
        "integer",
        "Votes cast for the remaining candidates combined in the 2020 Democratic "
        "presidential primary in this precinct, as recorded in the county results "
        "roll-up. Blank where the precinct has no Dallas row in that file, or where "
        "its Dallas row leaves the measure empty.",
        "2020 Primary Votes Other",
    ),
    "2020_percent_Biden": (
        "number",
        "Share of this precinct's 2020 Democratic presidential primary vote cast "
        "for Joseph Biden (fraction 0-1), as recorded in the county results "
        "roll-up. A primary share, not the 2020 general-election figure in "
        "president_2020_dem_share. Blank where the precinct has no Dallas row in "
        "that file, or where its Dallas row leaves the measure empty.",
        "2020 Primary Percent Biden",
    ),
    "2020_percent_Sanders": (
        "number",
        "Share of this precinct's 2020 Democratic presidential primary vote cast "
        "for Bernie Sanders (fraction 0-1), as recorded in the county results "
        "roll-up. A primary share, not the 2020 general-election figure in "
        "president_2020_dem_share. Blank where the precinct has no Dallas row in "
        "that file, or where its Dallas row leaves the measure empty.",
        "2020 Primary Percent Sanders",
    ),
    "2020_percent_Other": (
        "number",
        "Share of this precinct's 2020 Democratic presidential primary vote cast "
        "for the remaining candidates combined (fraction 0-1), as recorded in the "
        "county results roll-up. A primary share, not the 2020 general-election "
        "figure in president_2020_dem_share. Blank where the precinct has no Dallas "
        "row in that file, or where its Dallas row leaves the measure empty.",
        "2020 Primary Percent Other",
    ),
    "2024_votes_Harris": (
        "integer",
        "Votes cast for Kamala Harris in the 2024 presidential election in this "
        "precinct, as recorded in the county results roll-up. Blank where the "
        "precinct has no Dallas row in that file, or where its Dallas row leaves "
        "the measure empty.",
        "2024 Votes Harris",
    ),
    "2024_votes_Trump": (
        "integer",
        "Votes cast for Donald Trump in the 2024 presidential election in this "
        "precinct, as recorded in the county results roll-up. Blank where the "
        "precinct has no Dallas row in that file, or where its Dallas row leaves "
        "the measure empty.",
        "2024 Votes Trump",
    ),
    "2024_votes_Other": (
        "integer",
        "Votes cast for all other candidates combined in the 2024 presidential "
        "election in this precinct, as recorded in the county results roll-up. "
        "Blank where the precinct has no Dallas row in that file, or where its "
        "Dallas row leaves the measure empty.",
        "2024 Votes Other",
    ),
    "2024_percent_Trump": (
        "number",
        "Share of the 2024 presidential vote cast for Donald Trump in this precinct "
        "(fraction 0-1), as recorded in the county results roll-up. Blank where the "
        "precinct has no Dallas row in that file, or where its Dallas row leaves "
        "the measure empty.",
        "2024 Percent Trump",
    ),
    "2024_percent_Other": (
        "number",
        "Share of the 2024 presidential vote cast for all other candidates combined "
        "in this precinct (fraction 0-1), as recorded in the county results "
        "roll-up. Blank where the precinct has no Dallas row in that file, or where "
        "its Dallas row leaves the measure empty.",
        "2024 Percent Other",
    ),
    "2024_votes_Against_R": (
        "integer",
        "Votes cast AGAINST Proposition 14 (Prop R) in this "
        "precinct, as recorded in the county results roll-up. Blank where the "
        "precinct has no Dallas row in that file, or where its Dallas row leaves "
        "this measure empty.",
        "2024 Votes Against Prop R",
    ),
    "2024_votes_Against_U": (
        "integer",
        "Votes cast AGAINST Proposition 5 (Prop U) in this "
        "precinct, as recorded in the county results roll-up. Blank where the "
        "precinct has no Dallas row in that file, or where its Dallas row leaves "
        "this measure empty.",
        "2024 Votes Against Prop U",
    ),
    "2024_votes_For_R": (
        "integer",
        "Votes cast FOR Proposition 14 (Prop R) in this "
        "precinct, as recorded in the county results roll-up. Blank where the "
        "precinct has no Dallas row in that file, or where its Dallas row leaves "
        "this measure empty.",
        "2024 Votes For Prop R",
    ),
    "2024_votes_For_U": (
        "integer",
        "Votes cast FOR Proposition 5 (Prop U) in this "
        "precinct, as recorded in the county results roll-up. Blank where the "
        "precinct has no Dallas row in that file, or where its Dallas row leaves "
        "this measure empty.",
        "2024 Votes For Prop U",
    ),
    "2024_percent_Against_R": (
        "number",
        "Share of the 2024 vote on Proposition 14 (Prop R) cast AGAINST in this precinct "
        "(fraction 0-1), as recorded in the county results roll-up. Blank where the "
        "precinct has no Dallas row in that file, or where its Dallas row leaves "
        "this measure empty.",
        "2024 Percent Against Prop R",
    ),
    "2024_percent_For_U": (
        "number",
        "Share of the 2024 vote on Proposition 5 (Prop U) cast FOR in this precinct (fraction "
        "0-1), as recorded in the county results roll-up. Blank where the precinct "
        "has no Dallas row in that file, or where its Dallas row leaves this "
        "measure empty.",
        "2024 Percent For Prop U",
    ),
    # --- 2026 general election: data/raw/2026_governor_general_precinct.csv,
    # 2026_senate_general_precinct.csv and 2026_props_general_precinct.csv,
    # joined on the precinct code carried in their `new_precinct` key
    # (`113:<code>`).  Measures are namespaced by contest because `votes_Other`
    # appears in both race files and `votes_For` in both proposition rows.
    # Blank means the file holds no row for the precinct, or its row leaves the
    # measure empty; a recorded 0 is carried as 0.  Shares are fractions 0-1.
    "2026_gov_votes_Abbott": (
        "integer",
        "Votes cast for Abbott in the 2026 general election for governor in this "
        "precinct. Blank where the precinct has no row in "
        "`2026_governor_general_precinct.csv`.",
        "2026 Governor Votes Abbott",
    ),
    "2026_gov_votes_Hinojosa": (
        "integer",
        "Votes cast for Hinojosa in the 2026 general election for governor in this "
        "precinct. Blank where the precinct has no row in "
        "`2026_governor_general_precinct.csv`.",
        "2026 Governor Votes Hinojosa",
    ),
    "2026_gov_votes_Other": (
        "integer",
        "Votes cast for all other candidates combined in the 2026 general election "
        "for governor in this precinct. Blank where the precinct has no row in "
        "`2026_governor_general_precinct.csv`.",
        "2026 Governor Votes Other",
    ),
    "2026_gov_percent_Abbott": (
        "number",
        "Share of this precinct's 2026 general governor vote cast for Abbott "
        "(fraction 0-1). Blank where the precinct has no row in "
        "`2026_governor_general_precinct.csv`.",
        "2026 Governor Percent Abbott",
    ),
    "2026_gov_percent_Hinojosa": (
        "number",
        "Share of this precinct's 2026 general governor vote cast for Hinojosa "
        "(fraction 0-1). Blank where the precinct has no row in "
        "`2026_governor_general_precinct.csv`.",
        "2026 Governor Percent Hinojosa",
    ),
    "2026_gov_percent_Other": (
        "number",
        "Share of this precinct's 2026 general governor vote cast for all other "
        "candidates combined (fraction 0-1). Blank where the precinct has no row in "
        "`2026_governor_general_precinct.csv`.",
        "2026 Governor Percent Other",
    ),
    "2026_gov_percent_Turnout": (
        "number",
        "Share of this precinct's registered voters who voted on the governor ballot "
        "in the 2026 general election (fraction 0-1). Blank where the precinct has no "
        "row in `2026_governor_general_precinct.csv`.",
        "2026 Governor Turnout Share",
    ),
    "2026_sen_votes_Paxton": (
        "integer",
        "Votes cast for Paxton in the 2026 general election for Senate in this "
        "precinct. Blank where the precinct has no row in "
        "`2026_senate_general_precinct.csv`.",
        "2026 Senate Votes Paxton",
    ),
    "2026_sen_votes_Talarico": (
        "integer",
        "Votes cast for Talarico in the 2026 general election for Senate in this "
        "precinct. Blank where the precinct has no row in "
        "`2026_senate_general_precinct.csv`.",
        "2026 Senate Votes Talarico",
    ),
    "2026_sen_votes_Other": (
        "integer",
        "Votes cast for all other candidates combined in the 2026 general election "
        "for Senate in this precinct. Blank where the precinct has no row in "
        "`2026_senate_general_precinct.csv`.",
        "2026 Senate Votes Other",
    ),
    "2026_sen_percent_Paxton": (
        "number",
        "Share of this precinct's 2026 general Senate vote cast for Paxton (fraction "
        "0-1). Blank where the precinct has no row in "
        "`2026_senate_general_precinct.csv`.",
        "2026 Senate Percent Paxton",
    ),
    "2026_sen_percent_Talarico": (
        "number",
        "Share of this precinct's 2026 general Senate vote cast for Talarico "
        "(fraction 0-1). Blank where the precinct has no row in "
        "`2026_senate_general_precinct.csv`.",
        "2026 Senate Percent Talarico",
    ),
    "2026_sen_percent_Other": (
        "number",
        "Share of this precinct's 2026 general Senate vote cast for all other "
        "candidates combined (fraction 0-1). Blank where the precinct has no row in "
        "`2026_senate_general_precinct.csv`.",
        "2026 Senate Percent Other",
    ),
    "2026_sen_percent_Turnout": (
        "number",
        "Share of this precinct's registered voters who voted on the Senate ballot in "
        "the 2026 general election (fraction 0-1). Blank where the precinct has no "
        "row in `2026_senate_general_precinct.csv`.",
        "2026 Senate Turnout Share",
    ),
    "2026_prop_city_votes_For": (
        "integer",
        "Votes cast FOR the 2026 city proposition in this precinct. Blank where the "
        "precinct has no `city` row in `2026_props_general_precinct.csv`.",
        "2026 Prop City (For) Votes",
    ),
    "2026_prop_city_votes_Against": (
        "integer",
        "Votes cast AGAINST the 2026 city proposition in this precinct. Blank where "
        "the precinct has no `city` row in `2026_props_general_precinct.csv`.",
        "2026 Prop City (Against) Votes",
    ),
    "2026_prop_city_percent_For": (
        "number",
        "Share of this precinct's vote on the 2026 city proposition cast FOR "
        "(fraction 0-1). Blank where the precinct has no `city` row in "
        "`2026_props_general_precinct.csv`.",
        "2026 Prop City (For) Share",
    ),
    "2026_prop_city_percent_Against": (
        "number",
        "Share of this precinct's vote on the 2026 city proposition cast AGAINST "
        "(fraction 0-1). Blank where the precinct has no `city` row in "
        "`2026_props_general_precinct.csv`.",
        "2026 Prop City (Against) Share",
    ),
    "2026_prop_city_percent_Turnout": (
        "number",
        "Share of this precinct's registered voters who voted on the ballot carrying "
        "the 2026 city proposition (fraction 0-1). Blank where the precinct has no "
        "`city` row in `2026_props_general_precinct.csv`.",
        "2026 Prop City Turnout Share",
    ),
    "2026_prop_county_votes_For": (
        "integer",
        "Votes cast FOR the 2026 county proposition in this precinct. Blank where the "
        "precinct has no `county` row in `2026_props_general_precinct.csv`.",
        "2026 Prop County (For) Votes",
    ),
    "2026_prop_county_votes_Against": (
        "integer",
        "Votes cast AGAINST the 2026 county proposition in this precinct. Blank where "
        "the precinct has no `county` row in `2026_props_general_precinct.csv`.",
        "2026 Prop County (Against) Votes",
    ),
    "2026_prop_county_percent_For": (
        "number",
        "Share of this precinct's vote on the 2026 county proposition cast FOR "
        "(fraction 0-1). Blank where the precinct has no `county` row in "
        "`2026_props_general_precinct.csv`.",
        "2026 Prop County (For) Share",
    ),
    "2026_prop_county_percent_Against": (
        "number",
        "Share of this precinct's vote on the 2026 county proposition cast AGAINST "
        "(fraction 0-1). Blank where the precinct has no `county` row in "
        "`2026_props_general_precinct.csv`.",
        "2026 Prop County (Against) Share",
    ),
    "2026_prop_county_percent_Turnout": (
        "number",
        "Share of this precinct's registered voters who voted on the ballot carrying "
        "the 2026 county proposition (fraction 0-1). Blank where the precinct has no "
        "`county` row in `2026_props_general_precinct.csv`.",
        "2026 Prop County Turnout Share",
    ),
    "2026_registered_general": (
        "integer",
        "Registered voters in this precinct as published with the 2026 "
        "general-election results. The official count, distinct from the "
        "canvass-period 2026_registered; the two are not interchangeable. Blank where the precinct "
        "has no row in `2026_governor_general_precinct.csv`.",
        "2026 Registered Voters (General Election)",
    ),
    # --- derived ---
    "response_count": (
        "integer",
        "round(canvass_attempts * response_rate): estimated number of households "
        "the canvass actually reached, i.e. responses rather than knocks. The "
        "denominator of prop_a_city_no_canvassing_pct. Reads 0 where the response "
        "rate is 0, which is a finding (nobody was reached), not missing data; "
        "missing only where attempts or the response rate are not recorded.",
        "Canvass Response Count",
    ),
    "prop_a_city_no_canvassing_pct": (
        "number",
        "Percentage of canvassed voters (i.e. those who answered the door) who indicated 'strong no' on Prop A",
        "Prop A No Share (Canvassed)",
    ),
    "pct_renter_occupied": (
        "number",
        "1 - pct_owner_occupied: the renter-occupied share of occupied housing units "
        "(fraction 0-1). Note pct_owner_occupied is a share of *occupied* units while "
        "pct_vacant is a share of *all* units, so this field excludes vacant stock and "
        "renter + vacant does not always sum to 1. Blank where the source owner share "
        "is missing (those VTDs also have blank or zero housing_units).",
        "Percent Renter Occupied",
    ),
}

# DFS fields joined on a key worth naming in the dictionary.
JOIN_NOTE = {
    # The attribution rule, stated as the build actually applies it: fullness
    # first, share only as a tie-break, so two rows of 820 land on a minority
    # VTD (1315 at 0.115, 1724 at 0.144) because the fuller DFS row won.
    "source_ref": " Reached by this row's `census_vtd_geoid` from the precinct-to-VTD "
                  "crosswalk: the export is keyed by VTD, and the VTD kept for a "
                  "precinct is the one `dedupe_output_by_precinct()` scored fullest, "
                  "tie-broken by the largest `share_of_county_precinct`. So these "
                  "figures describe that VTD -- usually the one covering most of the "
                  "precinct, but not guaranteed to be it.",
}

# ---------------------------------------------------------------------------
# READABLE_OVERRIDES -- the single source of truth for corrected labels.
#
# 58 of the 99 fields inherit `label` verbatim from the read-only Dallas Fair
# Districts export, and that export mangles them ('Pct nh white', 'Not us
# citizen', 'Fb pct africa').  The fix belongs here, at the root, and is applied
# *after* label selection so data/raw/ stays untouched and MANUAL stays readable
# as authored.  It covers the whole dictionary, not just the fields the precinct
# dashboard displays: half-fixed labels would leak into the next tool.
#
# Rule: title-case, and expand the source's machine-mangled abbreviations --
#   pct -> Percent, nh -> Non-Hispanic, us -> U.S., snap -> SNAP,
#   50k -> $50k, sq_mi -> Square Mile, bachelors_plus -> Bachelor's or Higher
# plus ordinary acronym casing (ACS, CVAP, MOE, VTD, ID, HS) and one lowercase
# connective where the source reads better that way ('on', 'or'), matching the
# human's worked examples 'Percent Age 18-64' / 'Percent Households on SNAP'.
# 'fb' is left as the source's own acronym, upper-cased, because the rule does
# not license guessing at what it stands for.
# ---------------------------------------------------------------------------
READABLE_OVERRIDES = {
    # identity / demographics inherited from the DFS export
    "district_id": "District ID",
    "source_ref": "Census Code",
    "land_area_sq_m": "Land Area",
    "acs_release": "ACS Release",
    "acs_lines_match_current": "ACS Lines Match Current",
    "cvap_total": "CVAP Total",
    "cvap_total_moe": "CVAP Total MOE",
    "fb_pct_africa": "FB Percent Africa",
    "fb_pct_asia": "FB Percent Asia",
    "fb_pct_europe": "FB Percent Europe",
    "fb_pct_latin_america": "FB Percent Latin America",
    "foreign_born": "Foreign Born",
    "housing_units": "Housing Units",
    "median_age": "Median Age",
    "median_household_income": "Median Household Income",
    "not_us_citizen": "Not U.S. Citizen",
    # the pct_* family
    "pct_age_18_64": "Percent Age 18\u201364",
    "pct_age_20_39": "Percent Age 20\u201339",
    "pct_bachelors_plus": "Percent Bachelor's or Higher",
    "pct_below_poverty": "Percent Below Poverty",
    "pct_english_only": "Percent English Only",
    "pct_family_households": "Percent Family Households",
    "pct_female": "Percent Female",
    "pct_hispanic": "Percent Hispanic",
    "pct_households_snap": "Percent Households on SNAP",
    "pct_hs_or_less": "Percent HS or Less",
    "pct_income_under_50k": "Percent Income Under $50k",
    "pct_married_couple_households": "Percent Married Couple Households",
    "pct_multi_unit": "Percent Multi Unit",
    "pct_nh_asian": "Percent Non-Hispanic Asian",
    "pct_nh_black": "Percent Non-Hispanic Black",
    "pct_nh_other": "Percent Non-Hispanic Other",
    "pct_nh_white": "Percent Non-Hispanic White",
    "pct_owner_occupied": "Percent Owner Occupied",
    "pct_single_unit": "Percent Single Unit",
    "pct_spanish": "Percent Spanish",
    "pct_us_born": "Percent U.S. Born",
    "pct_vacant": "Percent Vacant",
    "population_per_sq_mi": "Population Per Square Mile",
    # registration / turnout
    "registered_active": "Registered Active",
    "registered_active_per_cvap": "Registered Active Per CVAP",
    "registered_total": "Registered Total",
    "registered_total_per_cvap": "Registered Total Per CVAP",
    "voted_total": "Voted Total",
    "voted_total_per_cvap": "Voted Total Per CVAP",
    "voted_total_per_registered_total": "Voted Total Per Registered Total",
    # presidential
    "president_2020_dem_share": "2020 Democratic Share",
    "president_2020_margin": "2020 Margin",
    "president_2020_total_votes": "2020 Total Votes",
    "president_2024_dem_share": "2024 Democratic Share",
    "president_2024_margin": "2024 Margin",
    "president_2024_total_votes": "2024 Total Votes",
    "opportunity_sanders_avg": "Sanders Primary Share",
    "opportunity_sanders_margin_avg": "Sanders Margin",
}


def classify(values):
    """Type of the non-blank values in a column (blanks are missing, not text)."""
    vals = [v for v in values if v not in ("", None)]
    if not vals:
        return "empty"
    if all(v in ("true", "false", "True", "False") for v in vals):
        return "boolean"

    def num(v):
        try:
            return float(v)
        except ValueError:
            return None

    # Collect the parsed values rather than testing the list with all(), so the
    # elements are known floats (not `float | None`) wherever they are used.
    nums = [n for n in (num(v) for v in vals) if n is not None]
    if len(nums) != len(vals):
        return "text"
    return "integer" if all(n.is_integer() for n in nums) else "number"


def reconcile(field, values, declared):
    """Final data_type plus a caveat, if the values contradict the declared type.

    A column that is numeric but only partly populated keeps its numeric type:
    missing cells are absent data, not text.  Identifiers in FORCE_TEXT stay text
    even when every value parses as an integer, because arithmetic on them is
    meaningless.
    """
    vals = [v for v in values if v not in ("", None)]
    n_blank = len(values) - len(vals)
    obs = classify(vals)
    sentinels = sorted({v.strip() for v in vals if classify([v]) == "text" and v.strip() in SENTINELS})
    n_sentinel = sum(1 for v in vals if classify([v]) == "text" and v.strip() in SENTINELS)
    numeric_like = [v for v in vals if classify([v]) in ("integer", "number")]

    if field in FORCE_TEXT:
        final = "text"
    elif obs in ("integer", "number", "boolean"):
        final = obs
    elif obs == "empty":
        final = declared if declared in ("integer", "number", "boolean", "text") else "text"
    elif sentinels and len(numeric_like) + n_sentinel == len(vals):
        # every non-numeric value is a known placeholder: keep the numeric type
        final = "integer" if classify(numeric_like) == "integer" else "number"
    else:
        final = "text"

    parts = []
    if n_blank and "blank for" not in _DESC_CACHE.get(field, "").lower():
        parts.append(f"{n_blank} of {len(values)} rows empty" if "blank" in _DESC_CACHE.get(field, "").lower() else f"blank for {n_blank} of {len(values)} rows")
    if sentinels and final in ("integer", "number"):
        parts.append(
            f"{n_sentinel} row(s) hold the literal placeholder "
            f"{'/'.join(sentinels)} rather than a number"
        )
    elif final == "text" and declared in ("integer", "number") and obs == "text":
        non_num = sorted({v for v in vals if classify([v]) == "text"})[:3]
        parts.append(f"holds non-numeric values {non_num} despite source declaring {declared}")
    if declared in ("integer", "number") and final in ("integer", "number") and declared != final:
        # Say what the extract holds, not what `declared` implies it should. The
        # shape and the declaration disagree in BOTH directions: whole numbers
        # under a `number` declaration, and fractions under an `integer` one.
        # Naming only the first let a mis-declared share column ship a caveat
        # claiming its fractions were whole numbers.
        shape = "whole numbers" if final == "integer" else "fractions"
        parts.append(f"{shape} in this extract, declared {declared} upstream")
    caveat = f" ({'; '.join(parts)})." if parts else "."
    return final, caveat


def readable_from_name(field):
    """Fallback title-casing for any field neither the DFS dictionary nor MANUAL covers."""
    words = field.replace("_", " ").split()
    return " ".join(w.upper() if w.isdigit() or len(w) == 1 else w.capitalize() for w in words)


_DESC_CACHE: "dict[str, str]" = {}


def main():
    with open(IN_CSV, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        fields = list(reader.fieldnames or [])
        columns = {f: [] for f in fields}
        rows = list(reader)
    for r in rows:
        for f in fields:
            columns[f].append(r[f])

    dfs = {
        d["column"]: d
        for d in csv.DictReader(open(DFS_DICT, newline="", encoding="utf-8"))
    }

    stale = sorted(set(READABLE_OVERRIDES) - set(fields))
    if stale:
        raise SystemExit(f"READABLE_OVERRIDES names fields not in precinct_data.csv: {stale}")

    records, gaps = [], []
    n_overridden = 0
    for f in fields:
        _DESC_CACHE[f] = MANUAL[f][1] if f in MANUAL else (
            dfs[f]["description"] if f in dfs else ""
        )
        if f in MANUAL:
            declared, description, label = MANUAL[f]
        elif f in dfs:
            declared = dfs[f]["type"]
            label = dfs[f]["label"] or readable_from_name(f)
            description = dfs[f]["description"] + JOIN_NOTE.get(f, "")
        else:
            # Nothing documents this field, so there is no upstream type to
            # contradict: claim `text` rather than reading `observed`, which is
            # only ever bound by a *previous* iteration of this loop.
            declared = "text"
            label = readable_from_name(f)
            description = "Not documented -- add to MANUAL in build_data_dictionary.py."
            gaps.append(f)
        # Applied after label selection so both the DFS-inherited labels and the
        # hand-authored MANUAL ones can be corrected at the root, in one place.
        if f in READABLE_OVERRIDES:
            label = READABLE_OVERRIDES[f]
            n_overridden += 1
        observed, note = reconcile(f, columns[f], declared)
        records.append(
            {
                "field_name": f,
                "data_type": observed,
                "description": description.rstrip(".") + note,
                "readable_name": label,
            }
        )

    with open(OUT, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh, fieldnames=["field_name", "data_type", "description", "readable_name"]
        )
        writer.writeheader()
        writer.writerows(records)

    print(f"rows in precinct_data.csv   : {len(rows)}")
    print(f"fields documented           : {len(records)}")
    print(f"  from DFS dictionary       : {sum(1 for f in fields if f in dfs and f not in MANUAL)}")
    print(f"  hand-authored (MANUAL)    : {sum(1 for f in fields if f in MANUAL)}")
    print(f"  UNDOCUMENTED (fallback)   : {gaps}")
    print(f"contradicts source type     : "
          f"{[r['field_name'] for r in records if 'despite source declaring' in r['description']]}")
    print(f"partly blank fields         : {sum(1 for r in records if 'blank for' in r['description'])}")
    print(f"blank-readable names        : "
          f"{[r['field_name'] for r in records if not r['readable_name']]}")
    print(f"labels corrected (overrides) : {n_overridden}")
    print(f"types used                  : {sorted({r['data_type'] for r in records})}")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
