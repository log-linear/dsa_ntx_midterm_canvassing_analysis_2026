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
   The row universe is then widened from "precincts a canvass workbook named" to
   "precincts the VTD crosswalk knows": ``crosswalk_only_rows()`` appends one row
   for every crosswalk precinct code the union did not already carry, attributed to
   the census VTD covering most of it by the same winner rule as step 5, and copies
   that VTD's DFS row verbatim.  Those rows have no canvass history, so every
   ``.ods``-derived column -- the canvass metrics, the workbooks' provenance and
   both canvass-era derived ratios -- stays blank rather than being inferred.
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
   The three official 2026 general-election precinct files -- governor, Senate
   and the city/county propositions -- join on the same basis and for the same
   reason: their ``new_precinct`` key is ``113:<precinct code>``, so the join
   compares the text after the colon as TEXT and never casts it to int.  They
   too join only after both dedupes, so their 25 measures cannot influence how a
   raw ``.ods`` row was scored or repaired either.  They supersede the canvass
   workbooks' four 2026 placeholders -- ``2026_turnout``, ``2026_bond``,
   ``2026_talarico`` and ``2026_hinojosa`` -- which are dropped from the output
   while staying in the union read, so the dedupe scoring is byte-unchanged.
5. Collapse the joined output to one row per ``dallas_county_precinct_number``
   (see ONE ROW PER PRECINCT).  The VTD fan-out produced several rows per
   precinct with repeated precinct-level values; the joined output keeps the
   single row per precinct that carries the most data.

ONE ROW PER PRECINCT
The crosswalk maps a precinct to one to four census VTDs, so joining it fans
each precinct out to that many rows.  ``dedupe_output_by_precinct()`` collapses
them back to one row per precinct before writing, keeping the row with the most
non-blank figures, tie-broken by the largest ``share_of_county_precinct``.
``row_rank()`` is that rule and is used twice: here, and by
``crosswalk_only_rows()`` when it picks the dominant VTD for a precinct the
canvass workbooks never named.  Fullness wins outright, so the share is a
tie-break, not the criterion: two precincts (1315, 1724) land on a VTD covering
only 0.115 / 0.144 of them because the fuller DFS row beat the bigger sliver,
which is why the demographic columns describe the *chosen* VTD rather than
guaranteed the largest one.  The collapsed-away VTDs are reported on stdout
(geoid and share) rather than silently discarded: their demographics are still
reachable through ``data/raw/dallas_vtd_to_county_precinct.csv`` if a per-VTD
grain is wanted.

A precinct, not a VTD, is the grain: the output holds one row per precinct code
(820 rows over 820 codes), so ``census_vtd_id`` / ``census_vtd_geoid`` /
``share_of_county_precinct`` name the ONE VTD whose figures were kept, not a
membership the precinct also has in every other VTD it touches.

THE `name` TRAP
The DFS export's ``name`` column is a VTD identifier, not a seat name:
``source_ref == "48113" + name``, exactly as ``census_vtd_geoid == "48113" +
census_vtd_id``.  Because the county's precinct codes and the county's VTD
identifiers are both four digits, a ``name`` coincides with a precinct code for
many rows -- and describes different ground when it does.  Precinct 3011 reads
3033 people if you look ``name == "3011"`` up, and 11251 if you follow the
crosswalk.  Nothing in this build keys off DFS ``name``; attribution goes
``dallas_county_precinct_id`` -> ``census_vtd_geoid`` -> ``source_ref`` only.

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

import settings


# Every value this build reads as a constant is authored in `src/settings.py`:
# the repo-root path anchors, the raw-input paths, the field names it writes, and
# the tables driving header normalisation, shift detection and the roll-up
# overlay.  Anchoring on `settings.REPO_ROOT` rather than this module's own
# directory is what lets `uv run python src/build_precinct_data.py` still find `data/` at
# the repo root instead of creating `src/data/`.
#
# These bindings are not a compatibility shim for callers: the module body refers
# to these names throughout, and `main()` reads the path ones as module globals at
# CALL time, which is a property the suite depends on -- it rebinds OUT / COMB_CSV
# / GOV_CSV / SEN_CSV / PROPS_CSV to a temp or synthetic file and asserts the build
# aborts with SystemExit BEFORE the writer opens.  The extract is written with "w"
# with no dry-run, so "truncated output over committed data" is the exact failure
# mode those checks guard, and it can only be guarded on a path read this late.
#
# ODS_FILES globs at settings-import time rather than at build time, exactly as it
# globbed at this module's import time before the move: a missing .ods is still a
# silent empty list, which is why AGENTS.md says to copy data/*.csv aside first.
ODS_FILES = settings.ODS_FILES
VTD_MAP = settings.VTD_MAP_CSV
DFS_CSV = settings.DFS_EXPORT_CSV
COMB_CSV = settings.COMB_ROLLUP_CSV
COMB_COUNTY = settings.COMB_COUNTY
COMB_COUNTY_COL = settings.COMB_COUNTY_COL
COMB_KEY_COL = settings.COMB_KEY_COL
COMB_OVERLAYS = settings.COMB_OVERLAYS

GOV_CSV = settings.GOV_CSV
SEN_CSV = settings.SEN_CSV
PROPS_CSV = settings.PROPS_CSV
GENERAL_KEY_COL = settings.GENERAL_KEY_COL
GENERAL_KEY_PREFIXES = settings.GENERAL_KEY_PREFIXES
GENERAL_REGISTERED_COL = settings.GENERAL_REGISTERED_COL
GENERAL_PROPS_COL = settings.GENERAL_PROPS_COL
GENERAL_PROPS = settings.GENERAL_PROPS
GOV_MEASURES = settings.GOV_MEASURES
SEN_MEASURES = settings.SEN_MEASURES
PROPS_MEASURES = settings.PROPS_MEASURES
GENERAL_CONTESTS = settings.GENERAL_CONTESTS
GENERAL_REGISTERED_OUT = settings.GENERAL_REGISTERED_OUT
RETIRED_GENERAL_COLS = settings.RETIRED_GENERAL_COLS

# The output path: the same file as `settings.PRECINCT_CSV`, reached through the
# name `main()` opens.
OUT = settings.PRECINCT_CSV

PRECINCT_COL = settings.PRECINCT_COL
GROUP_COL = settings.GROUP_COL
ALIGN_COL = settings.ALIGN_COL
SHARE_COL = settings.SHARE_COL
RESPONSE_COUNT_COL = settings.RESPONSE_COUNT_COL
NO_PCT_COL = settings.NO_PCT_COL
RENTER_COL = settings.RENTER_COL
DEDUPE_SKIP = settings.DEDUPE_SKIP

TABLE = settings.TABLE
OFFICE = settings.OFFICE
HEADER_ALIASES = settings.HEADER_ALIASES
EXPECTED_TYPE = settings.EXPECTED_TYPE
MAX_SHIFT = settings.MAX_SHIFT





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


def general_columns():
    """Output names the 2026 general files supply: 24 contest measures plus Registered."""
    cols = [target for _, measures in GENERAL_CONTESTS for target in measures.values()]
    return cols + [GENERAL_REGISTERED_OUT]


def general_code(key, path):
    """Precinct code from a general-election key: the text after the colon.

    The three files key `new_precinct` as `113:<code>` while the extract holds
    bare codes, so the join compares the suffix as whitespace-stripped TEXT and
    never casts either side to int -- `0024`-style codes do not survive casting.
    The prefix set is `{113}` only, so a key outside it is not silently joined
    on its suffix: it would make two counties' precincts indistinguishable, which
    is precisely the ambiguity that aborts the build.
    """
    text = (key or "").strip()
    prefix, sep, suffix = text.partition(":")
    if not sep or prefix not in GENERAL_KEY_PREFIXES or not suffix.strip():
        raise SystemExit(
            f"{path}: unusable `{GENERAL_KEY_COL}` {text!r}; expected "
            f"{sorted(GENERAL_KEY_PREFIXES)} + ':' + the precinct code"
        )
    return suffix.strip()


def _general_read(path, union_keys):
    """Read one 2026 general-election file, guarding it as a required input.

    A missing file, a header-only file, an absent key column or a file matching
    none of the union precincts aborts before anything is written -- the roll-up
    gets the same treatment in load_comb().
    """
    if not path.exists():
        raise SystemExit(f"missing required input: {path}")
    rows, cols = load_csv(path)
    if GENERAL_KEY_COL not in cols:
        raise SystemExit(f"{path} has no `{GENERAL_KEY_COL}` column; header is {cols}")
    if GENERAL_REGISTERED_COL not in cols:
        raise SystemExit(f"{path} has no `{GENERAL_REGISTERED_COL}` column; header is {cols}")
    if not rows:
        raise SystemExit(f"{path} has a header but no data rows")
    codes = {general_code(r[GENERAL_KEY_COL], path) for r in rows}
    if not codes & set(union_keys):
        raise SystemExit(
            f"{path} matches none of the {len(set(union_keys))} union precincts "
            f"({len(codes)} distinct codes in the file)"
        )
    return rows, cols


def _general_check_measures(path, cols, measures, allowed, exempt=(GENERAL_KEY_COL,)):
    """Abort unless the file's columns are exactly the described measures.

    `exempt` names the non-measure columns of that file: only the proposition
    file carries `Proposition`, so a race file that grew one is an undescribed
    column and aborts rather than being mistaken for a measure.
    """
    described = set(measures) | set(allowed)
    extra = [c for c in cols if c not in exempt and c not in described]
    if extra:
        raise SystemExit(
            f"{path} carries undescribed measure columns {extra}; describe them in "
            f"the contest map rather than letting a new measure join silently"
        )
    absent = [m for m in measures if m not in cols]
    if absent:
        raise SystemExit(f"{path} is missing described measures {absent}")


def load_general_race(path, measures, union_keys):
    """Index one 2026 general race file by precinct code (text after the colon).

    One row per precinct: two rows sharing a suffix would make the join
    ambiguous, so that aborts instead of the first row winning.  Values are
    carried as the source wrote them, whitespace-stripped only, and a `0` stays
    `0` -- only a precinct with no row is absent from the index, which is what
    makes its figures read blank rather than zero.
    """
    rows, cols = _general_read(path, union_keys)
    _general_check_measures(path, cols, list(measures), [GENERAL_REGISTERED_COL])
    index: "dict[str, dict[str, str]]" = {}
    for r in rows:
        code = general_code(r[GENERAL_KEY_COL], path)
        if code in index:
            raise SystemExit(
                f"{path}: precinct {code} has two rows "
                f"({index[code][GENERAL_KEY_COL]!r} and {r[GENERAL_KEY_COL]!r}); "
                f"the suffix join would be ambiguous"
            )
        index[code] = r
    return index, len(rows)


def load_general_props(path, union_keys):
    """Index the long-format proposition file as code -> {proposition: row}.

    Pivoted (decision 1a) into one column set per `Proposition` value, and only
    the two described values are accepted: an unexpected one would otherwise be
    dropped without a trace.  A precinct with no `city` row simply has no `city`
    entry, which is what leaves its 5 city figures blank.
    """
    rows, cols = _general_read(path, union_keys)
    if GENERAL_PROPS_COL not in cols:
        raise SystemExit(f"{path} has no `{GENERAL_PROPS_COL}` column; header is {cols}")
    measures = list(PROPS_MEASURES["city"])
    if list(PROPS_MEASURES["county"]) != measures:
        raise SystemExit(f"{PROPS_CSV} city and county column maps disagree; both must describe {measures}")
    _general_check_measures(
        path, cols, measures, [GENERAL_REGISTERED_COL],
        exempt=(GENERAL_KEY_COL, GENERAL_PROPS_COL))
    index: "dict[str, dict[str, dict[str, str]]]" = {}
    for r in rows:
        code = general_code(r[GENERAL_KEY_COL], path)
        prop = (r.get(GENERAL_PROPS_COL) or "").strip()
        if prop not in GENERAL_PROPS:
            raise SystemExit(
                f"{path} carries `{GENERAL_PROPS_COL}` value {prop!r} for precinct "
                f"{code}; expected one of {list(GENERAL_PROPS)}"
            )
        slot = index.setdefault(code, {})
        if prop in slot:
            raise SystemExit(
                f"{path}: precinct {code} has two `{prop}` proposition rows; the "
                f"pivot would have to pick one"
            )
        slot[prop] = r
    return index, len(rows)


def registered_values(gov, sen, props, code) -> "list[tuple[str, str]]":
    """The `Registered` figures the four 2026 files record for one precinct.

    Contest name and value for every file holding a non-blank figure: a blank is
    "not recorded" rather than a rival value, so it never joins the list.
    """
    seen = []
    for contest, source in (
        ("governor", gov.get(code)),
        ("senate", sen.get(code)),
        ("city", (props.get(code) or {}).get("city")),
        ("county", (props.get(code) or {}).get("county")),
    ):
        if source is None:
            continue
        value = (source.get(GENERAL_REGISTERED_COL) or "").strip()
        if value:
            seen.append((contest, value))
    return seen


def assert_registered_agreement(gov, sen, props, codes) -> None:
    """Decision 2b: the canvassed precincts must agree on `Registered`.

    County-wide 48 of 791 precincts disagree.  The guard runs over the precincts
    the canvass workbooks named (the union keys), and none of those disagrees, so
    a contradiction still aborts here.  It deliberately does NOT cover the
    crosswalk-only rows widened in afterwards: 45 of those DO disagree across the
    four files (1305: governor/senate/county `1840` against city `0`), and each
    ships the governor figure -- the best-supported of the four, since the city
    file records `0` where that ballot question had no votes.  Aborting the build
    on them would widen a human-authored guard without human sign-off, so they
    are counted and reported on stdout instead; see `registered_disagreements`.
    """
    for code in sorted(codes):
        seen = registered_values(gov, sen, props, code)
        if len({v for _, v in seen}) > 1:
            raise SystemExit(
                f"2026 `{GENERAL_REGISTERED_COL}` disagrees for precinct {code}: "
                + ", ".join(f"{c}={v}" for c, v in seen)
            )


def registered_disagreements(gov, sen, props, rows) -> "list[str]":
    """Codes among `rows` whose four 2026 files disagree on `Registered`.

    The report for the widened universe: the emitted row still carries the
    governor figure, so this is a visibility gap rather than a wrong number.
    Recomputes the same comparison `assert_registered_agreement()` aborts on, via
    the same `registered_values()` reader, so the two cannot drift apart.
    """
    out = []
    for row in rows:
        code = (row.get(PRECINCT_COL) or "").strip()
        if code and len({v for _, v in registered_values(gov, sen, props, code)}) > 1:
            out.append(code)
    return sorted(out)


def apply_general(row, sources):
    """Copy the 2026 general-election measures onto an assembled precinct row, in place.

    `sources` maps each of the four contests to its matched row, or None where
    that file has no row for the precinct: those measures stay blank, never zero.
    A measure the matched row leaves empty stays empty, since the source recorded
    nothing for it.  Runs after the .ods union, the alignment repair and both
    dedupes, exactly like apply_comb, so these figures cannot influence how raw
    rows were type-checked or scored for fullness.
    """
    for contest, measures in GENERAL_CONTESTS:
        source = sources.get(contest)
        for m, target in measures.items():
            row[target] = ((source.get(m) if source else None) or "").strip()
    gov = sources.get("gov")
    row[GENERAL_REGISTERED_OUT] = ((gov.get(GENERAL_REGISTERED_COL) if gov else None) or "").strip()
    return row


def dfs_figure_columns(dfs_cols: "list[str]") -> "list[str]":
    """The DFS columns that carry a demographic figure, for the blank-row audit.

    ``district_id`` / ``name`` / ``body`` / ``state`` / ``source_ref`` are filled
    on every one of the 796 export rows -- they are the row's identity, not data
    about the ground -- so scoring them would let a VTD with no figures at all
    read as populated, exactly as `fullness()`'s `skip` argument exists to
    prevent.  What remains is the ACS share/median block: the figures a reader
    would call "the demographics", which is the question the widening asks of a
    row ("does this precinct's VTD carry any figure?").
    """
    identity = {"district_id", "name", "body", "state", "source_ref"}
    return [c for c in dfs_cols if c not in identity and (
        c.startswith(("pct_", "median_")) or c == "not_us_citizen"
    )]


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




def row_rank(row: "dict[str, str]", counted: "list[str]") -> "tuple[int, float]":
    """The winner rule: fullest row first, tie-broken by the biggest VTD share.

    `counted` is the column list the score runs over (output columns minus
    `DEDUPE_SKIP`).  A missing `share_of_county_precinct` scores -1.0 so it loses
    every tie, while a recorded `0.0` keeps its value: `0.0` means the crosswalk
    measured a zero overlap, which is a figure, not an absence -- collapsing the
    two would make an unrecorded share outrank a measured one.  Higher sorts
    first, so `max()` and `>` both pick the winner.
    """
    share = as_number(row.get(SHARE_COL))
    return (fullness(row, counted), share if share is not None else -1.0)


def crosswalk_only_rows(
    rows: "list[dict[str, str]]",
    out_cols: "list[str]",
    by_precinct: "dict[str, list[dict[str, str]]]",
    by_geoid: "dict[str, dict[str, str]]",
    dfs_figure_cols: "list[str]",
) -> "tuple[list[dict[str, str]], dict[str, list]]":
    """Append the DFS demographics of every crosswalk precinct the union did not name.

    The row universe the extract reports on is the one the VTD crosswalk can
    attribute, not the one the canvass workbooks happened to name: this turns the
    extract from 85 canvassed precincts into every precinct code in
    ``data/raw/dallas_vtd_to_county_precinct.csv``.  Attribution goes strictly
    ``dallas_county_precinct_id`` -> ``census_vtd_geoid`` -> DFS ``source_ref``.
    DFS ``name`` is never consulted: it is a VTD identifier that coincides with a
    county precinct code for some rows and describes different ground when it
    does (precinct 3011 reads 3033 people by ``name``, 11251 by the crosswalk),
    so keying off it would silently borrow another geography's demographics.

    One row per added code, chosen by `row_rank()` over that code's VTD
    candidates -- the identical rule `dedupe_output_by_precinct()` applies to the
    fan-out, so a precinct already in the extract and a precinct arriving here
    resolve to the same VTD.  The winning DFS row is copied verbatim; every
    ``.ods``-derived column stays blank because these precincts have no canvass
    history, and blank is what the panel must show rather than an inferred zero.
    ``pct_renter_occupied`` is computed with `complement()` before the candidate
    is ranked, exactly as the join loop does, so the derived share counts toward
    fullness on both paths.

    Returns the new rows plus the audit sets: `no_dfs` (codes whose chosen VTD has
    no DFS row at all), `no_figures` (codes whose DFS row carries no demographic
    figure, judged against `dfs_figure_cols` only -- the identity and provenance
    columns are filled on every DFS row and would hide a fully blank figure
    block) and `fanout_in` (candidate rows considered, so the drop count the
    build prints spans only rows this function actually scored).

    Codes already present are left alone byte-for-byte, and a crosswalk row with
    a blank precinct id contributes nothing: it is not a precinct.
    """
    present = {(r.get(PRECINCT_COL) or "").strip() for r in rows}
    counted = [c for c in out_cols if c not in DEDUPE_SKIP]
    added, no_dfs, no_figures = [], [], []
    fanout_in = 0
    for code in sorted(by_precinct):
        if not code or code in present:
            continue
        best: "dict[str, str] | None" = None
        for mapping in by_precinct[code]:
            fanout_in += 1
            row = {c: "" for c in out_cols}
            row[PRECINCT_COL] = code
            row.update(mapping)
            dfs = by_geoid.get(mapping["census_vtd_geoid"].strip())
            if dfs is not None:
                row.update(dfs)
            row[RENTER_COL] = complement(row.get("pct_owner_occupied"))
            if best is None or row_rank(row, counted) > row_rank(best, counted):
                best = row
        if best is None:
            continue
        if not best.get("source_ref"):
            no_dfs.append(code)
        if fullness(best, dfs_figure_cols) == 0:
            no_figures.append(code)
        added.append(best)
    return added, {
        "no_dfs": no_dfs,
        "no_figures": no_figures,
        "fanout_in": fanout_in,
        "fanout_dropped": fanout_in - len(added),
    }


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

    The ranking is `row_rank()`, the same rule `crosswalk_only_rows()` applies to
    the precincts the union never named, so one precinct resolves to one VTD no
    matter which path it arrived by.

    Original row order is preserved, so the output stays reproducible.
    """
    counted = [c for c in out_cols if c not in DEDUPE_SKIP]

    def key(row: "dict[str, str]") -> "tuple[int, float]":
        # higher sorts first: fullest, then biggest share of the precinct
        return row_rank(row, counted)

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

    # The 2026 general files are required inputs, so they are read and validated
    # here -- before the writer opens -- and joined to the assembled rows below.
    # Strict indexing, as this line did before the 2026 files needed it early: a
    # sheet that lost its first column must abort here, not contribute a blank
    # key that would then flow into the required-input guards below.
    union_keys = {r[PRECINCT_COL].strip() for r in union}
    gov, gov_rows = load_general_race(GOV_CSV, GOV_MEASURES, union_keys)
    sen, sen_rows = load_general_race(SEN_CSV, SEN_MEASURES, union_keys)
    props, props_rows = load_general_props(PROPS_CSV, union_keys)
    assert_registered_agreement(gov, sen, props, union_keys)
    general_cols = general_columns()

    by_precinct: "dict[str, list[dict[str, str]]]" = {}
    for r in map_rows:
        by_precinct.setdefault(r["dallas_county_precinct_id"].strip(), []).append(r)
    by_geoid = {r["source_ref"].strip(): r for r in dfs_rows}

    key_cols = [PRECINCT_COL, GROUP_COL, "district", ALIGN_COL]
    join_cols = (
        [c for c in map_cols if c != "dallas_county_precinct_id"]
        + dfs_cols
        + comb_cols
        + general_cols
        + [RESPONSE_COUNT_COL, NO_PCT_COL, RENTER_COL]
    )
    out_cols = (
        key_cols
        # The four superseded 2026 placeholders are read from the .ods union but
        # not written (decision 3b): extrasaction="ignore" drops them, so the
        # fullness and alignment scoring above stays byte-unchanged.
        + [c for c in union_cols
           if c not in key_cols + ["source_file"] + list(RETIRED_GENERAL_COLS)]
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
    fanout_kept = len(rows)  # scored by THIS dedupe, before the widening below

    # Widen the row universe from "precincts a canvass workbook named" to
    # "precincts the VTD crosswalk knows".  Appended AFTER both dedupes, so the
    # fullness and alignment scoring above is byte-unchanged, and BEFORE the
    # result joins below, so the official 2024/2026 figures fill these rows too.
    added_rows, widening = crosswalk_only_rows(
        rows, out_cols, by_precinct, by_geoid, dfs_figure_columns(dfs_cols)
    )
    rows.extend(added_rows)
    registered_conflicts = registered_disagreements(gov, sen, props, rows)

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

    # The 2026 general election joins last for the same reason: its measures must
    # not reach fullness(), choose_shift() or the alignment repair above.
    unmatched_general: "dict[str, list[str]]" = {}
    for row in rows:
        code = (row.get(PRECINCT_COL) or "").strip()
        prop_rows = props.get(code) or {}
        sources = {
            "gov": gov.get(code),
            "sen": sen.get(code),
            "city": prop_rows.get("city"),
            "county": prop_rows.get("county"),
        }
        for contest, source in sources.items():
            if source is None:
                unmatched_general.setdefault(contest, []).append(code)
        apply_general(row, sources)

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
    # The fan-out dedupe collapsed `fanout_rows` joined rows down to
    # `fanout_kept`; the widening added rows afterwards, so subtracting today's
    # row count here would report rows this dedupe never saw.
    print(f"rows dropped as duplicate precinct ({fanout_rows - fanout_kept} after joining; {fanout_kept} precincts x VTDs = {fanout_rows} rows):")
    for d in dropped_vtd:
        print(f"    {d}")
    print(f"crosswalk precincts added : {len(added_rows)} "
          f"({widening['fanout_in']} candidate rows x VTDs, "
          f"{widening['fanout_dropped']} dropped to their dominant VTD)")
    # Both audit lines print their count as well as the list, so "checked, none
    # found" is distinguishable from a check that could not have fired.
    print(f"added precincts with no DFS row          ({len(widening['no_dfs'])}): "
          f"{sorted(widening['no_dfs'])}")
    print(f"added precincts with no DFS figure       ({len(widening['no_figures'])}): "
          f"{sorted(widening['no_figures'])}")
    print(f"rows whose 2026 `Registered` disagrees across files ({len(registered_conflicts)}): "
          f"{registered_conflicts}")
    print(f"rows repaired for alignment ({len(repaired)}):")
    for r in repaired:
        print(f"    {r}")
    matched_comb = sorted(union_keys & set(comb))
    print(f"union precincts missing from VTD map : {sorted(set(unmatched_vtd))}")
    print(f"VTD geoids missing from DFS export   : {sorted(set(unmatched_dfs))}")
    print(f"roll-up rows                         : {comb_rows} total, {len(comb)} {COMB_COUNTY},"
          f" {len(matched_comb)} of {len(union_keys)} union precincts matched")
    print(f"union precincts missing from {COMB_CSV.name}: {sorted(set(unmatched_comb))}")
    print(f"2026 general rows                      : {gov_rows} governor, {sen_rows} senate, "
          f"{props_rows} proposition rows over {len(props)} precincts")
    print(f"2026 general columns                   : {len(general_cols)} new "
          f"({GENERAL_REGISTERED_OUT} carried once from the governor file)")
    print(f"union precincts missing from {GOV_CSV.name}: {sorted(unmatched_general.get('gov', []))}")
    print(f"union precincts missing from {SEN_CSV.name}: {sorted(unmatched_general.get('sen', []))}")
    print(f"union precincts missing a {GENERAL_PROPS_COL} == city row   : {sorted(unmatched_general.get('city', []))}")
    print(f"union precincts missing a {GENERAL_PROPS_COL} == county row : {sorted(unmatched_general.get('county', []))}")
    for col in (RESPONSE_COUNT_COL, NO_PCT_COL, RENTER_COL):
        # A computed `response_count` of 0 is a finding, not an absence, so it
        # counts as populated: `r.get(col)` is the string "0", which is truthy.
        print(f"rows with a computed {col}: {sum(1 for r in rows if r.get(col))} / {len(rows)}")
    print(f"precinct numbers in >1 sheet group   : {dups}")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
