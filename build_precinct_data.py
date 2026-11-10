"""Build data/precinct_data.csv.

Pipeline
1. Read every sheet of every ``data/*.ods`` file (each sheet is one precinct
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
4. LEFT JOIN that union onto ``dallas_vtd_to_county_precinct.csv`` on the
   precinct number (one-to-many: a precinct covers several census VTDs), then
   onto the DFS export on ``census_vtd_geoid`` == ``source_ref``.

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
ODS_FILES = sorted(DATA.glob("*.ods"))
VTD_MAP = DATA / "dallas_vtd_to_county_precinct.csv"
DFS_CSV = DATA / "dfs-export-precinct-20261108" / "data.csv"
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
    union = deduped

    map_rows, map_cols = load_csv(VTD_MAP)
    dfs_rows, dfs_cols = load_csv(DFS_CSV)

    by_precinct: dict[str, list[dict]] = {}
    for r in map_rows:
        by_precinct.setdefault(r["dallas_county_precinct_id"].strip(), []).append(r)
    by_geoid = {r["source_ref"].strip(): r for r in dfs_rows}

    key_cols = [PRECINCT_COL, GROUP_COL, "district", ALIGN_COL]
    out_cols = (
        key_cols
        + [c for c in union_cols if c not in key_cols + ["source_file"]]
        + ["source_file"]
        + [c for c in map_cols if c != "dallas_county_precinct_id"]
        + dfs_cols
    )

    rows, unmatched_vtd, unmatched_dfs = [], [], []
    for rec in union:
        matches = by_precinct.get(rec[PRECINCT_COL])
        if not matches:  # keep the union row even if unmapped
            rows.append({**rec, **{c: "" for c in map_cols + dfs_cols}})
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
            rows.append(merged)

    with open(OUT, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=out_cols, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    repaired = [f"{r['source_file']}/{r[GROUP_COL]}/{r[PRECINCT_COL]}" for r in union if r[ALIGN_COL] != "aligned"]
    groups: dict[str, list[str]] = {}
    for r in union:
        groups.setdefault(r[PRECINCT_COL], []).append(f"{r['district']}/{r[GROUP_COL]}")
    dups = {p: g for p, g in groups.items() if len(g) > 1}

    print(f"ods files                 : {[p.name for p in ODS_FILES]}")
    print(f"union rows (deduped)      : {len(union)} over {len(union_cols)} columns")
    print(f"mapping / dfs rows        : {len(map_rows)} / {len(dfs_rows)}")
    print(f"output rows               : {len(rows)} ({len(set(r[PRECINCT_COL] for r in rows))} precincts)")
    print(f"output columns            : {len(out_cols)}")
    print(f"rows repaired for alignment ({len(repaired)}):")
    for r in repaired:
        print(f"    {r}")
    print(f"union precincts missing from VTD map : {sorted(set(unmatched_vtd))}")
    print(f"VTD geoids missing from DFS export   : {sorted(set(unmatched_dfs))}")
    print(f"precinct numbers in >1 sheet group   : {dups}")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
