"""Build data/data_dictionary.csv for every field in data/precinct_data.csv.

Columns: field_name, data_type, description, readable_name.

Coverage strategy
1. The 58 fields inherited from the Dallas Fair Districts export keep their own
   published metadata (data/raw/dfs-export-precinct-20261108/dictionary.csv:
   `label` -> readable_name, `description` -> description).  Those descriptions
   are written for the DFS profile, so a source note naming the joined key is
   appended where one exists.
2. Fields created by this project (the .ods union, the VTD mapping, sheet 72 of
   detail.xlsx, and the derived ratios) are described by hand in MANUAL below.
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
    "prop_a_city_precinct_code",
    "name",
    "geography_hierarchy",
}

# Placeholder strings a human typed instead of a number.  They do not make a
# numeric column textual; they are reported as a caveat on the numeric type.
SENTINELS = {"N/A", "NA", "n/a", "n\A", "-", "--", "None", "null"}

MANUAL = {
    # --- union of the .ods sheets (data/raw/District {1,2,9} precincts.ods) ---
    "dallas_county_precinct_number": (
        "text",
        "Dallas County precinct number, from the unnamed first column of every "
        "sheet in the three district canvassing workbooks. Join key to the VTD "
        "mapping and to the first four characters of sheet 72's `Precinct`.",
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
        "integer",
        "2024 Proposition 14 (Prop R) votes FOR, as recorded by district volunteers "
        "in the canvassing workbooks. Blank where the source sheet did not record it "
        "(including all rows whose values were column-shifted).",
        "2024 Prop R (For)",
    ),
    "2024_prop_u_against": (
        "integer",
        "2024 Proposition 5 (Prop U) votes AGAINST, as recorded in the canvassing "
        "workbooks. Blank where the source sheet did not record it.",
        "2024 Prop U (Against)",
    ),
    "2024_kamala": (
        "number",
        "Share of the 2024 presidential vote cast for Harris/Walz in this precinct, "
        "as recorded in the canvassing workbooks (fraction 0-1).",
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
        "Registered voters in the precinct as recorded for the 2026 canvass.",
        "2026 Registered Voters",
    ),
    "canvass_attempts": (
        "integer",
        "Canvass attempts logged by district volunteers. Denominator of "
        "prop_a_city_no_canvassing_pct; 0 or blank means no canvass data.",
        "Canvass Attempts",
    ),
    "response_rate": (
        "number",
        "Share of canvassed households that responded (fraction 0-1).",
        "Canvass Response Rate",
    ),
    "strong_no": (
        "integer",
        "Voters canvassers recorded as a 'strong no' -- the numerator of "
        "prop_a_city_no_canvassing_pct.",
        "Strong No (Canvassed)",
    ),
    "2026_turnout": (
        "integer",
        "Turnout recorded for the 2026 election in the canvassing workbooks.",
        "2026 Turnout",
    ),
    "2026_bond": (
        "integer",
        "2026 bond measure votes recorded in the canvassing workbooks.",
        "2026 Bond Votes",
    ),
    "2026_talarico": (
        "integer",
        "2026 Talarico votes recorded in the canvassing workbooks.",
        "2026 Talarico Votes",
    ),
    "2026_hinojosa": (
        "integer",
        "2026 Hinojosa votes recorded in the canvassing workbooks.",
        "2026 Hinojosa Votes",
    ),
    "source_file": (
        "text",
        "Filename of the .ods workbook the row came from, for provenance.",
        "Source Workbook",
    ),
    # --- data/raw/dallas_vtd_to_county_precinct.csv ---
    "census_vtd_id": (
        "text",
        "Census voting-district identifier from the county precinct-to-VTD crosswalk. "
        "One precinct maps to several VTDs, so a precinct appears on one row per VTD.",
        "Census VTD ID",
    ),
    "census_vtd_geoid": (
        "text",
        "Full Census GEOID of the voting district; join key to the demographic "
        "export's `source_ref`.",
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
    # --- data/raw/detail.xlsx, sheet '72' (City of Dallas Proposition A) ---
    "prop_a_city_against_election_day": (
        "integer",
        "Votes AGAINST City of Dallas Proposition A cast on election day (sheet 72 "
        "column G), summed across the sheet's sub-precinct rows for this precinct.",
        "Prop A (City) Against - Election Day",
    ),
    "prop_a_city_against_ev_in_person": (
        "integer",
        "Votes AGAINST City of Dallas Proposition A cast early in person (sheet 72 "
        "column H).",
        "Prop A (City) Against - Early In Person",
    ),
    "prop_a_city_against_ev_mail": (
        "integer",
        "Votes AGAINST City of Dallas Proposition A cast by mail during early voting "
        "(sheet 72 column I).",
        "Prop A (City) Against - Early Vote By Mail",
    ),
    "prop_a_city_against_total_votes": (
        "integer",
        "Total votes AGAINST City of Dallas Proposition A (sheet 72 column J; equals "
        "columns G+H+I on every row). Numerator of prop_a_city_no_actual_pct.",
        "Prop A (City) Against - Total",
    ),
    "prop_a_city_total_votes": (
        "integer",
        "Total votes cast on City of Dallas Proposition A, FOR and AGAINST combined "
        "(sheet 72 column K). Note: the sheet's 'Against (En contra)' header spans "
        "only G-J, so K is the ballot-question total, not an Against subtotal. "
        "Denominator of prop_a_city_no_actual_pct.",
        "Prop A (City) Total Votes",
    ),
    "prop_a_city_source_rows": (
        "integer",
        "How many sheet-72 sub-precinct rows were summed into this precinct. '1' for "
        "most; 1063 and 4086 have two.",
        "Prop A (City) Source Row Count",
    ),
    "prop_a_city_precinct_code": (
        "text",
        "The sheet-72 `Precinct` code(s) that matched this precinct, pipe-separated "
        "when more than one was summed (e.g. '1063-01|1063-03').",
        "Prop A (City) Source Precinct Codes",
    ),
    # --- derived ---
    "prop_a_city_no_canvassing_pct": (
        "number",
        "strong_no / canvass_attempts: share of a precinct's *canvassed* voters "
        "recorded as a strong no. A canvass-coverage proxy, not an election result; "
        "blank where canvass attempts are 0 or missing.",
        "Prop A No Share (Canvassed)",
    ),
    "prop_a_city_no_actual_pct": (
        "number",
        "prop_a_city_against_total_votes / prop_a_city_total_votes: the share who "
        "actually voted against City of Dallas Proposition A. Blank for precincts with no "
        "matching sheet-72 row (e.g. 1046).",
        "Prop A No Share (Actual Result)",
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
    "source_ref": " Joined to `census_vtd_geoid` from the precinct-to-VTD crosswalk.",
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

    nums = [num(v) for v in vals]
    if all(n is not None for n in nums):
        return "integer" if all(n.is_integer() for n in nums) else "number"
    return "text"


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
        parts.append(f"whole numbers in this extract, declared {declared} upstream")
    caveat = f" ({'; '.join(parts)})." if parts else "."
    return final, caveat


def readable_from_name(field):
    """Fallback title-casing for any field neither the DFS dictionary nor MANUAL covers."""
    words = field.replace("_", " ").split()
    return " ".join(w.upper() if w.isdigit() or len(w) == 1 else w.capitalize() for w in words)


_DESC_CACHE: "dict[str, str]" = {}


def main():
    with open(IN_CSV, newline="") as fh:
        reader = csv.DictReader(fh)
        fields = list(reader.fieldnames or [])
        columns = {f: [] for f in fields}
        rows = list(reader)
    for r in rows:
        for f in fields:
            columns[f].append(r[f])

    dfs = {
        d["column"]: d
        for d in csv.DictReader(open(DFS_DICT, newline=""))
    }

    records, gaps = [], []
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
            declared = observed
            label = readable_from_name(f)
            description = "Not documented -- add to MANUAL in build_data_dictionary.py."
            gaps.append(f)
        observed, note = reconcile(f, columns[f], declared)
        records.append(
            {
                "field_name": f,
                "data_type": observed,
                "description": description.rstrip(".") + note,
                "readable_name": label,
            }
        )

    with open(OUT, "w", newline="") as fh:
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
    print(f"types used                  : {sorted({r['data_type'] for r in records})}")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
