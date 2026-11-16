"""Build data/precinct_data.csv.

Pipeline
1. Read every sheet of every ``data/raw/*.ods`` file (each sheet is one precinct
   group within a council district).
2. Remove cells that hold a formula -- in these files that is the per-sheet
   ``SUM`` "total voters" row, which disappears entirely once its formula
   cells are blanked.
3. Repair mis-aligned rows (see ALIGNMENT below), name the unnamed first column
   ``dallas_county_precinct_number``, keep the sheet name as ``precinct_group``
   plus ``district`` / ``source_file`` for provenance, and UNION all sheets into
   one table.  Headers are normalised so near-duplicates such as
   "2024 Prop R (for)" / "2024 Prop R (For)" collapse into a single column;
   columns missing from a sheet are left blank.
4. Collapse the union to one row per precinct (keeping the row with the most
   data), then LEFT JOIN it onto ``data/raw/dallas_vtd_to_county_precinct.csv`` on the
   precinct number (one-to-many: a precinct covers several census VTDs), then
   onto the DFS export on ``census_vtd_geoid`` == ``source_ref``; add
   ``response_count`` = round(canvass_attempts * response_rate),
   ``prop_a_city_no_canvassing_pct`` = strong_no / response_count and
   ``pct_renter_occupied`` = 1 - pct_owner_occupied.
   The county results roll-up ``data/raw/precinct_comb.csv`` joins on
   ``county == "Dallas"`` plus the precinct code compared as TEXT -- and it joins
   only AFTER step 5 has collapsed the table to one row per precinct, never
   among the joins above.  Its 20 measures therefore cannot influence how a raw
   ``.ods`` row was type-checked, alignment-repaired, or scored for fullness,
   which is what decides which row survives step 5.
   Three of those measures supersede a share the canvass workbooks used to
   supply: ``2024_kamala``, ``2024_prop_r_for`` and ``2024_prop_u_against`` keep
   their names and take the official county figure, and go blank where the
   precinct has no Dallas row in the roll-up.
5. Collapse the joined output to one row per ``dallas_county_precinct_number``
   (see ONE ROW PER PRECINCT).  The VTD fan-out produced several rows per
   precinct with repeated precinct-level values; the joined output keeps the
   single row per precinct that carries the most data.

ONE ROW PER PRECINCT
The crosswalk maps a precinct to one to four census VTDs, so joining it fans
each precinct out to that many rows.  ``dedupe_output_by_precinct()`` collapses
them back to one row per precinct before writing, keeping the row with the most
non-blank figures, tie-broken by the largest ``share_of_county_precinct`` --
i.e. the VTD covering most of the precinct, whose DFS demographics describe it
best.  The collapsed-away VTDs are reported on stdout (geoid and share) rather
than silently discarded: their demographics are still reachable through
``data/raw/dallas_vtd_to_county_precinct.csv`` if a per-VTD grain is wanted.

ALIGNMENT
Several District 2 sheets have their metric values keyed one column to the LEFT
of the header they belong to (authoring error).  Detected per row, not per
sheet: a metric column whose stored value-type contradicts the column's type
(``2024 turnout`` holding a count instead of a percentage) means the row is
shifted.  The row's values are then moved right by one column, and
``sheet_column_alignment`` records which rows were repaired.  District 1 / 9
rows, and District 2's ``Haskell-Fitzhugh`` / ``Columbia-Grand`` sheets, are
already aligned and are left untouched.

Percentage cells are written as their stored fractions (0.6736 == "67.36%").
"""

import csv
import re
import zipfile
import xml.etree.ElementTree as ET
from collections import OrderedDict
from pathlib import Path

TABLE = "{urn:oasis:names:tc:opendocument:xmlns:table:1.0}"
OFFICE = "{urn:oasis:names:tc:opendocument:xmlns:office:1.0}"

PRECINCT_COL = "dallas_county_precinct_number"
GROUP_COL = "precinct_group"
ALIGN_COL = "sheet_column_alignment"

BASE = Path(__file__).resolve().parent
DATA = BASE / "data"
RAW = DATA / "raw"               # every input lives here; DATA holds only output
ODS_FILES = sorted(RAW.glob("*.ods"))
VTD_MAP = RAW / "dallas_vtd_to_county_precinct.csv"
DFS_CSV = RAW / "dfs-export-precinct-20261108" / "data.csv"
COMB_CSV = RAW / "precinct_comb.csv"  # county results roll-up, one row per (county, precinct)
COMB_COUNTY = "Dallas"   # the only county whose rows this build joins
COMB_COUNTY_COL = "county"
COMB_KEY_COL = "precinct"
SHARE_COL = "share_of_county_precinct"  # crosswalk: how much of the precinct this VTD covers
RESPONSE_COUNT_COL = "response_count"  # estimated households reached: round(canvass_attempts * response_rate)
NO_PCT_COL = "prop_a_city_no_canvassing_pct"   # no-rate of responders: strong_no / response_count
RENTER_COL = "pct_renter_occupied"  # complement of the DFS owner-occupied share
OUT = DATA / "precinct_data.csv"

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




def normalise(header: str) -> str:
    """Canonical column name: lower snake_case so near-duplicate headers union."""
    h = re.sub(r"\s+", " ", header).strip().lower()
    h = re.sub(r"[^a-z0-9]+", "_", h).strip("_")
    return HEADER_ALIASES.get(h, h)


def cell_read(cell) -> tuple[str, str | None]:
    """Return (value, stored value-type) for one <table:table-cell>."""
    if cell.get(TABLE + "formula"):
        return "", "blank"  # formula cells are emptied; rows only holding one drop out
    stored = cell.get(OFFICE + "value")
    vtype = cell.get(OFFICE + "value-type")
    if vtype in ("percentage", "float", "currency", "date") and stored is not None:
        return stored, vtype
    text = "".join(cell.itertext()).strip()
    return (text, "string") if text else ("", "blank")


def row_cells(row) -> tuple[list[str], list[str]]:
    """Values and value-types for a table row, repeated cells expanded."""
    values, types = [], []
    for cell in row:
        if cell.tag != TABLE + "table-cell":
            continue
        value, vtype = cell_read(cell)
        repeated = int(cell.get(OFFICE + "number-columns-repeated", "1"))
        values += [value] * repeated
        types += [vtype] * repeated
    while values and values[-1] == "":
        values.pop()
        types.pop()
    return values, types


def type_penalty(header, values, types, shift):
    """Count metric columns whose value contradicts the column's expected type."""
    penalties = checks = 0
    for i, name in enumerate(header):
        if i == 0:
            continue  # column 0 is the precinct key, never a metric
        expected = EXPECTED_TYPE.get(name)
        if expected is None:
            continue
        j = i - shift
        if j < 1 or j >= len(values) or values[j] == "":
            continue  # no information: missing or blank cell
        if types[j] in (expected, "string", "blank"):
            checks += 1  # free text such as "N/A" is type-neutral
            continue
        if types[j] != "percentage" and types[j] != "float":
            checks += 1
            continue
        penalties += 1
        checks += 1
    return penalties, checks


def choose_shift(header, values, types):
    """0 if the row matches its headers, 1 if its values sit one column left."""
    p0, c0 = type_penalty(header, values, types, 0)
    if p0 == 0 or c0 < 2:
        return 0
    best_shift, best = 0, p0
    for shift in range(1, MAX_SHIFT + 1):
        p, c = type_penalty(header, values, types, shift)
        if c >= 2 and p < best:
            best_shift, best = shift, p
    return best_shift if best < p0 else 0


def sheet_rows(ods: Path, sheet):
    """Yield one dict per data row of a sheet, keyed by normalised header."""
    header: list[str] | None = None
    for row in [r for r in sheet if r.tag == TABLE + "table-row"]:
        values, types = row_cells(row)
        if header is None:  # row 0 = header; its first column is unnamed in every sheet
            header = [normalise(v) for v in values]
            header[0] = normalise(PRECINCT_COL)
            if any(h == "" for h in header):
                raise ValueError(f"{ods.name} / {sheet.get(TABLE + 'name')}: blank header cell")
            continue
        if not values or not values[0]:
            continue  # blank row, formula-only total row, or stray label row

        shift = choose_shift(header, values, types)
        if shift and len(values) + shift > len(header):
            raise ValueError(f"{ods.name} / {sheet.get(TABLE + 'name')} / {values[0]}: shift overflows header")
        rec = OrderedDict()
        for i, name in enumerate(header):
            if i == 0:  # the key column never moves
                continue
            j = i - shift
            rec[name] = values[j] if 1 <= j < len(values) else ""
        rec[PRECINCT_COL] = values[0]
        if shift:
            rec[ALIGN_COL] = f"shifted_left_{shift}_corrected"
        else:
            rec[ALIGN_COL] = "aligned"
        rec[GROUP_COL] = sheet.get(TABLE + "name")
        yield rec


def read_ods_tables():
    """Union every sheet of every .ods file into rows + an ordered column list."""
    records, columns = [], OrderedDict()
    for ods in ODS_FILES:
        root = ET.fromstring((zipfile.Path(ods) / "content.xml").read_text())
        match = re.search(r"\d+", ods.stem)
        for sheet in root.iter(TABLE + "table"):
            for rec in sheet_rows(ods, sheet):
                rec["district"] = f"District {match.group()}" if match else ods.stem
                rec["source_file"] = ods.name
                records.append(rec)
                columns.update(dict.fromkeys(rec))
    return records, list(columns)


def load_csv(path: Path):
    with open(path, newline="") as fh:
        reader = csv.DictReader(fh)
        return list(reader), list(reader.fieldnames or [])


def as_number(value):
    """Numeric value of a cell: the .ods union gives strings, CSVs give text."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def fmt_number(num):
    return str(int(num)) if float(num).is_integer() else str(num)


def load_comb():
    """Index the county results roll-up by precinct code, Dallas rows only.

    The key is `(county, precinct)` compared as TEXT with only surrounding
    whitespace stripped: the file carries codes such as `0024` and `30C4` that
    int-casting would destroy, and precinct `2103` exists under both Dallas and
    Denton, so the county is part of the key rather than a filter applied later.

    Values are carried across as the source wrote them: whitespace-stripped only,
    never re-parsed, re-formatted or rounded, so the roll-up's own precision
    survives into the extract.  A `0` is a value and stays `0`; only a precinct
    with no Dallas row is absent from the index, which is what makes its figures
    read blank rather than zero.

    The roll-up is a required input, so a missing file, a header-only file or a
    file with no Dallas row aborts the build before anything is written.
    """
    if not COMB_CSV.exists():
        raise SystemExit(f"missing required input: {COMB_CSV}")
    rows, cols = load_csv(COMB_CSV)
    for needed in (COMB_COUNTY_COL, COMB_KEY_COL):
        if needed not in cols:
            raise SystemExit(f"{COMB_CSV} has no `{needed}` column; header is {cols}")
    measures = [c for c in cols if c not in (COMB_COUNTY_COL, COMB_KEY_COL)]
    if not measures:
        raise SystemExit(f"{COMB_CSV} holds no result measures, only its key columns")
    unknown = [s for s in COMB_OVERLAYS if s not in measures]
    if unknown:
        raise SystemExit(f"{COMB_CSV} is missing overlaid columns {unknown}")

    by_precinct: "dict[str, dict[str, str]]" = {}
    clashes: "list[str]" = []
    for r in rows:
        if (r.get(COMB_COUNTY_COL) or "").strip() != COMB_COUNTY:
            continue  # another county's precinct: never joins onto ours
        code = (r.get(COMB_KEY_COL) or "").strip()
        if not code:
            continue
        if code in by_precinct:
            clashes.append(code)
            continue  # first row wins, so the result stays reproducible
        by_precinct[code] = r
    if not rows:
        raise SystemExit(f"{COMB_CSV} has a header but no data rows")
    if not by_precinct:
        raise SystemExit(f"{COMB_CSV} has no `{COMB_COUNTY_COL} == {COMB_COUNTY}` rows")
    if clashes:
        print(f"  note: {COMB_COUNTY} precinct codes repeated in {COMB_CSV.name}"
              f" (first row kept): {sorted(set(clashes))}")
    return by_precinct, measures, len(rows)


def comb_columns(measures):
    """Output names the roll-up supplies: the 17 new columns, in source order.

    A measure consumed by an overlay (decision 1a) is deliberately not also
    carried under its own name, so it drops out here and appears only as the
    existing field it supersedes.
    """
    return [m for m in measures if m not in COMB_OVERLAYS]


def apply_comb(row, source, measures):
    """Copy the roll-up's measures onto an assembled precinct row, in place.

    Runs after the .ods union, the alignment repair and both dedupes, so the
    official county figures never influence how raw workbook rows were scored or
    repaired -- `EXPECTED_TYPE` still describes the raw `.ods` cells.  A precinct
    with no Dallas row (`source` None) gets blanks across all 20 figures; a
    measure the matched row leaves empty stays empty, since the source recorded
    nothing for it.
    """
    for m in measures:
        target = COMB_OVERLAYS.get(m, m)
        row[target] = source.get(m, "").strip() if source else ""
    return row


def complement(value_raw):
    """1 - value as text, blank when the source share is missing."""
    value = as_number(value_raw)
    if value is None:
        return ""
    return fmt_number(round(1 - value, 6))


def ratio(numerator_raw, denominator_raw):
    """numerator / denominator as text, blank when either is missing/invalid."""
    numerator, denominator = as_number(numerator_raw), as_number(denominator_raw)
    if numerator is None or denominator in (None, 0):
        return ""
    return fmt_number(round(numerator / denominator, 6))


def response_count_value(attempts_raw, rate_raw):
    """round(attempts * rate) as a whole-number count, or None when unrecorded.

    How many households a precinct's canvass is estimated to have actually
    reached: `canvass_attempts` is the doors knocked, and only `response_rate`
    of those answered.  Unlike a share this is a COUNT, so a rounded product of
    0 is a real finding -- a precinct with a 0 response rate reached nobody --
    and is reported as 0 rather than left blank.  Blank means the source did not
    record attempts or the response rate at all.
    """
    attempts, rate = as_number(attempts_raw), as_number(rate_raw)
    if attempts is None or rate is None:
        return None
    return round(attempts * rate)


def response_count(attempts_raw, rate_raw):
    """`response_count_value` as text; blank only when an input is missing."""
    count = response_count_value(attempts_raw, rate_raw)
    return "" if count is None else fmt_number(count)


def response_weighted_ratio(numerator_raw, attempts_raw, rate_raw):
    """numerator / response_count as text.

    `strong_no` counts RESPONSES, so dividing it by canvass ATTEMPTS understates
    the no-rate of everyone who actually answered -- precincts with a low
    response rate looked uniformly friendly.  The denominator is therefore the
    estimated number of responses, attempts x response_rate, rounded to a whole
    count.  Rounding is applied to the denominator only, never to the share.

    Blank when any input is missing, and when the response count rounds to 0: a
    precinct that reached nobody has no defined no-rate, so it reads missing
    rather than 0 -- see the note on blanks in the module docstring.  Two
    precincts (4073, 2150) have a 0 response rate recorded and so drop out here;
    both had `strong_no` = 0, i.e. they carried only ever a zero no-rate.  In
    ``response_count`` those same two precincts read 0, not blank.
    """
    numerator = as_number(numerator_raw)
    denominator = response_count_value(attempts_raw, rate_raw)
    if numerator is None or not denominator:  # missing, or 0 responses
        return ""
    return fmt_number(round(numerator / denominator, 6))


# The canvassing proxy for a precinct's "Prop A No" share:
#   NO_PCT_COL   strong_no / round(canvass_attempts * response_rate)
# The actual result is no longer computed here: the roll-up supplies the county's
# Against/For shares directly, so `ratio()` has no caller left.  It is kept
# deliberately -- this build's own Against-divided-by-ballots-cast measure was
# retired with detail.xlsx, and the roll-up's per-ballot-question shares are not
# the same figure, so nothing here reproduces it.


def fullness(rec: "dict[str, str]", columns: "list[str]", skip: "tuple[str, ...]" = ()) -> int:
    """Count of cells in `columns` that hold a value, i.e. how much data the row has.

    Blank cells are *missing*, not zeros, so a row with a populated `population`
    and full demographic block outranks a row that is blank at the source.
    Columns in `skip` are filled on every row and would make the comparison
    meaningless, so they are not counted.
    """
    return sum(1 for c in columns if c not in skip and rec.get(c, "") != "")


def dedupe_by_precinct(
    records: "list[OrderedDict[str, str]]", union_cols: "list[str]"
) -> "tuple[list[OrderedDict[str, str]], list[str]]":
    """Collapse the union to one row per precinct, keeping the row with most data.

    A precinct is occasionally canvassed by two districts (1057 sits in both
    District 2 and District 9's `Casa View` sheets).  The metric columns decide
    the winner: the row recording more non-blank figures is kept, since the
    district labels and sheet names are otherwise equally credible.  Ties keep
    the first occurrence, so the result does not depend on file iteration order.
    """
    skip = (PRECINCT_COL, GROUP_COL, "district", ALIGN_COL, "source_file")
    metrics = [c for c in union_cols if c not in skip]

    def score(rec: "OrderedDict[str, str]") -> int:
        return fullness(rec, metrics)

    best: "dict[str, OrderedDict[str, str]]" = {}
    order: "list[str]" = []
    dropped: "list[str]" = []
    for rec in records:
        pid = rec[PRECINCT_COL]
        if pid not in best:
            best[pid] = rec
            order.append(pid)
            continue
        incumbent, challenger = best[pid], rec
        if score(challenger) > score(incumbent):
            best[pid], loser = challenger, incumbent
        else:
            loser = challenger
        dropped.append(
            f"{pid}: dropped {loser['district']}/{loser[GROUP_COL]}"
            f" ({score(loser)} filled) kept {best[pid]['district']}"
            f"/{best[pid][GROUP_COL]} ({score(best[pid])} filled)"
        )
    return [best[pid] for pid in order], dropped


def dedupe_output_by_precinct(
    rows: "list[dict[str, str]]", out_cols: "list[str]"
) -> "tuple[list[dict[str, str]], list[str]]":
    """Collapse the joined output to one row per precinct, keeping the fullest.

    The crosswalk fans a precinct out over its census VTDs, so the joined table
    repeats each precinct on one row per VTD: precinct-level `.ods` figures are
    identical on those rows, while the DFS demographics differ (a sliver VTD
    often holds no population at all).  This keeps the one row per precinct
    that carries the most data, ranked by count of non-blank output columns and
    tie-broken by the largest `share_of_county_precinct`, so among rows equally
    full the VTD covering most of the precinct wins.  Provenance and grain
    columns are excluded from the count: they are filled on every row.

    Original row order is preserved, so the output stays reproducible.
    """
    skip = (PRECINCT_COL, GROUP_COL, "district", ALIGN_COL, "source_file")
    counted = [c for c in out_cols if c not in skip]

    def key(row: "dict[str, str]") -> "tuple[int, float]":
        # higher sorts first: fullest, then biggest share of the precinct
        share = as_number(row.get(SHARE_COL))
        return (fullness(row, counted), share if share is not None else -1.0)

    best: "dict[str, dict[str, str]]" = {}
    order: "list[str]" = []
    dropped: "list[str]" = []
    for row in rows:
        pid = row[PRECINCT_COL]
        if pid not in best:
            best[pid] = row
            order.append(pid)
            continue
        incumbent, challenger = best[pid], row
        if key(challenger) > key(incumbent):
            best[pid], loser = challenger, incumbent
        else:
            loser = challenger
        dropped.append(
            f"{pid}: dropped VTD {loser.get('census_vtd_geoid', '?')}"
            f" ({fullness(loser, counted)} filled, {loser.get(SHARE_COL, '?')} of precinct)"
            f" kept {best[pid].get('census_vtd_geoid', '?')}"
            f" ({fullness(best[pid], counted)} filled,"
            f" {best[pid].get(SHARE_COL, '?')} of precinct)"
        )
    return [best[pid] for pid in order], dropped


def main() -> None:
    union, union_cols = read_ods_tables()

    # Fill in columns a given sheet does not have, then UNION (not UNION ALL)
    # so byte-identical rows collapse.
    union = [OrderedDict((c, rec.get(c, "")) for c in union_cols) for rec in union]
    seen, deduped = set(), []
    for rec in union:
        key = tuple(rec[c] for c in union_cols)
        if key not in seen:
            seen.add(key)
            deduped.append(rec)
    union, dropped = dedupe_by_precinct(deduped, union_cols)

    map_rows, map_cols = load_csv(VTD_MAP)
    dfs_rows, dfs_cols = load_csv(DFS_CSV)
    comb, comb_measures, comb_rows = load_comb()
    comb_cols = comb_columns(comb_measures)

    by_precinct: "dict[str, list[dict[str, str]]]" = {}
    for r in map_rows:
        by_precinct.setdefault(r["dallas_county_precinct_id"].strip(), []).append(r)
    by_geoid = {r["source_ref"].strip(): r for r in dfs_rows}

    key_cols = [PRECINCT_COL, GROUP_COL, "district", ALIGN_COL]
    join_cols = (
        [c for c in map_cols if c != "dallas_county_precinct_id"]
        + dfs_cols
        + comb_cols
        + [RESPONSE_COUNT_COL, NO_PCT_COL, RENTER_COL]
    )
    out_cols = (
        key_cols
        + [c for c in union_cols if c not in key_cols + ["source_file"]]
        + ["source_file"]
        + join_cols
    )

    rows, unmatched_vtd, unmatched_dfs = [], [], []
    for rec in union:
        derived = {
            RESPONSE_COUNT_COL: response_count(
                rec.get("canvass_attempts"), rec.get("response_rate")
            ),
            NO_PCT_COL: response_weighted_ratio(
                rec.get("strong_no"), rec.get("canvass_attempts"), rec.get("response_rate")
            ),
            RENTER_COL: "",
        }
        matches = by_precinct.get(rec[PRECINCT_COL])
        if not matches:  # keep the union row even if unmapped
            row = {**rec, **derived, **{c: "" for c in map_cols + dfs_cols}}
            row[RENTER_COL] = complement(row.get("pct_owner_occupied"))
            rows.append(row)
            unmatched_vtd.append(rec[PRECINCT_COL])
            continue
        for m in matches:
            merged = {**rec, **m}
            dfs = by_geoid.get(m["census_vtd_geoid"].strip())
            if dfs is None:
                unmatched_dfs.append(m["census_vtd_geoid"])
                merged.update({c: "" for c in dfs_cols})
            else:
                merged.update(dfs)
            merged[RESPONSE_COUNT_COL] = derived[RESPONSE_COUNT_COL]
            merged[NO_PCT_COL] = derived[NO_PCT_COL]
            merged[RENTER_COL] = complement(merged.get("pct_owner_occupied"))
            rows.append(merged)

    # One row per precinct: the VTD fan-out above is a join artifact, not data.
    fanout_rows = len(rows)
    rows, dropped_vtd = dedupe_output_by_precinct(rows, out_cols)

    # Election results join last: the roll-up supersedes the canvass workbooks'
    # shares, and must not influence how raw .ods rows were type-checked,
    # alignment-repaired, or scored for fullness above.
    unmatched_comb = []
    for row in rows:
        code = (row.get(PRECINCT_COL) or "").strip()
        source = comb.get(code)
        if source is None:
            unmatched_comb.append(code)
        apply_comb(row, source, comb_measures)

    with open(OUT, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=out_cols, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    repaired = [f"{r['source_file']}/{r[GROUP_COL]}/{r[PRECINCT_COL]}" for r in union if r[ALIGN_COL] != "aligned"]
    groups: "dict[str, list[str]]" = {}
    for r in union:
        groups.setdefault(r[PRECINCT_COL], []).append(f"{r['district']}/{r[GROUP_COL]}")
    dups = {p: g for p, g in groups.items() if len(g) > 1}

    print(f"ods files                 : {[p.name for p in ODS_FILES]}")
    print(f"union rows (precinct-deduped): {len(union)} over {len(union_cols)} columns")
    print(f"rows dropped as duplicate precinct ({len(dropped)}):")
    for d in dropped:
        print(f"    {d}")
    print(f"mapping / dfs rows        : {len(map_rows)} / {len(dfs_rows)}")
    print(f"output rows               : {len(rows)} ({len(set(r[PRECINCT_COL] for r in rows))} precincts)")
    print(f"output columns            : {len(out_cols)}")
    print(f"rows dropped as duplicate precinct ({fanout_rows - len(rows)} after joining; {len(rows)} precincts x VTDs = {fanout_rows} rows):")
    for d in dropped_vtd:
        print(f"    {d}")
    print(f"rows repaired for alignment ({len(repaired)}):")
    for r in repaired:
        print(f"    {r}")
    union_keys = {r[PRECINCT_COL].strip() for r in union}
    matched_comb = sorted(union_keys & set(comb))
    print(f"union precincts missing from VTD map : {sorted(set(unmatched_vtd))}")
    print(f"VTD geoids missing from DFS export   : {sorted(set(unmatched_dfs))}")
    print(f"roll-up rows                         : {comb_rows} total, {len(comb)} {COMB_COUNTY},"
          f" {len(matched_comb)} of {len(union_keys)} union precincts matched")
    print(f"union precincts missing from {COMB_CSV.name}: {sorted(set(unmatched_comb))}")
    for col in (RESPONSE_COUNT_COL, NO_PCT_COL, RENTER_COL):
        # A computed `response_count` of 0 is a finding, not an absence, so it
        # counts as populated: `r.get(col)` is the string "0", which is truthy.
        print(f"rows with a computed {col}: {sum(1 for r in rows if r.get(col))} / {len(rows)}")
    print(f"precinct numbers in >1 sheet group   : {dups}")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
