"""Read the On-Ramp order tracking workbook (sites/OnRamp2_OrderTracking_*.xlsx).

    import order_tracking as ot
    tracking = ot.read_airbus_tracking("sites/OnRamp2_OrderTracking_August2026.xlsx")
    tracking.groupby(["platform", "radiometry", "status"]).size()
    vantor = ot.read_vantor_supp("sites/OnRamp2_OrderTracking_August2026.xlsx")   # Legion tasking windows

The AirbusTracking tab is a grid, not a table: one block of rows per site
(Acq # 1..8), one column pair per platform (TOA, SR), and the order status is
the cell's fill colour, explained by the legend in the first rows. Reading it
needs the fills, so this uses the raw .xlsx XML (standard library only; no
openpyxl needed).
"""

from __future__ import annotations

import re
import zipfile
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

import pandas as pd

_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
       "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
_M = "{%s}" % _NS["m"]

# Fills that are not in the legend: Excel theme 1 = text (black), 0 = background (white)
FILL_LABELS = {("theme", "1", None): "n/a (black)",
               ("theme", "0", None): "unmarked",
               None: "unmarked"}

# Acquisition time inside Airbus IDs: DS_PHR1A_202304050917383_... or PHR1A_202304050917383_...
_ID_TIME = re.compile(r"^(?:DS_)?([A-Z]+[0-9][A-Z0-9]*)_(\d{14})(\d)")


def _col_index(ref: str) -> int:
    n = 0
    for ch in re.match(r"[A-Z]+", ref).group():
        n = n * 26 + ord(ch) - 64
    return n - 1


def _fill_key(fill) -> Optional[Tuple]:
    """Hashable fill colour: ("theme", "5", tint rounded) or ("rgb", "FFFF00", None)."""
    if fill is None:
        return None
    if "rgb" in fill:
        return ("rgb", fill["rgb"][-6:], None)
    if "theme" in fill:
        tint = fill.get("tint")
        return ("theme", fill["theme"], round(float(tint), 3) if tint else None)
    return None


def read_xlsx_cells(path: Union[str, Path], sheet: str) -> pd.DataFrame:
    """Every cell of one sheet: [row, col, value, fill] (1-based row, 0-based col).
    `fill` is a hashable fill colour (see _fill_key) or None. Merged ranges are
    expanded so each cell in the range carries the top-left cell's value."""
    with zipfile.ZipFile(path) as z:
        strings = []
        if "xl/sharedStrings.xml" in z.namelist():
            for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", _NS):
                strings.append("".join(t.text or "" for t in si.iter(_M + "t")))
        styles = ET.fromstring(z.read("xl/styles.xml"))
        fills = []
        for f in styles.find("m:fills", _NS):
            pattern = f.find("m:patternFill", _NS)
            fg = pattern.find("m:fgColor", _NS) if pattern is not None else None
            fills.append(_fill_key(None if fg is None else dict(fg.attrib)))
        xf_fill = [fills[int(x.get("fillId", 0))] for x in styles.find("m:cellXfs", _NS)]

        book = ET.fromstring(z.read("xl/workbook.xml"))
        rels = {r.get("Id"): r.get("Target")
                for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))}
        targets = {s.get("name"): rels[s.get("{%s}id" % _NS["r"])] for s in book.find("m:sheets", _NS)}
        if sheet not in targets:
            raise KeyError(f"sheet {sheet!r} not in {list(targets)}")
        target = targets[sheet].lstrip("/")
        root = ET.fromstring(z.read(target if target.startswith("xl/") else "xl/" + target))

    rows = []
    for row in root.iter(_M + "row"):
        for c in row.findall("m:c", _NS):
            v, kind = c.find("m:v", _NS), c.get("t")
            if kind == "inlineStr":
                value = "".join(t.text or "" for t in c.iter(_M + "t"))
            elif v is None:
                value = None
            elif kind == "s":
                value = strings[int(v.text)]
            else:
                value = v.text
            if isinstance(value, str):
                value = value.strip().strip('"').strip() or None
            rows.append({"row": int(re.sub(r"[A-Z]+", "", c.get("r"))), "col": _col_index(c.get("r")),
                         "value": value, "fill": xf_fill[int(c.get("s", 0))]})
    cells = pd.DataFrame(rows, columns=["row", "col", "value", "fill"])

    # Merged cells: copy the top-left value into the rest of the range
    for m in root.iter(_M + "mergeCell"):
        a, b = m.get("ref").split(":")
        r0, r1 = int(re.sub(r"[A-Z]+", "", a)), int(re.sub(r"[A-Z]+", "", b))
        c0, c1 = _col_index(a), _col_index(b)
        top = cells[(cells.row == r0) & (cells.col == c0)]
        if top.empty or top.value.iloc[0] is None:
            continue
        inside = cells.row.between(r0, r1) & cells.col.between(c0, c1) & cells.value.isna()
        cells.loc[inside, "value"] = top.value.iloc[0]
    return cells


def _excel_date(value) -> pd.Timestamp:
    """Excel serial day (e.g. '46282') or a date string -> UTC Timestamp (NaT if empty)."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return pd.NaT
    try:
        return pd.Timestamp("1899-12-30", tz="UTC") + pd.Timedelta(days=float(value))
    except (TypeError, ValueError):
        return pd.to_datetime(value, utc=True, errors="coerce")


def read_vantor_supp(path: Union[str, Path], sheet: str = "VantorLegion_Supp",
                     site_aliases: Optional[Dict[str, str]] = None) -> pd.DataFrame:
    """The Vantor Legion supplemental tasking tab as a table: one row per tasking
    window (OrderID), with the window as `window_start` / `window_end` (UTC; the
    sheet's End is the next window's Start, so a window is [start, end)).

    The sheet is a plain table (header in row 1); dates are Excel serial days.
    An unnamed column after End holds a product note (e.g. '2A ORTHO ACOMP')."""
    cells = read_xlsx_cells(path, sheet)
    header = cells[cells.row == 1].set_index("col").value.to_dict()
    body = cells[cells.row > 1].pivot(index="row", columns="col", values="value")
    body.columns = [header.get(c) or "note" for c in body.columns]
    body = body.dropna(how="all")

    out = pd.DataFrame({
        "site_name": body["AOI Name"].replace(site_aliases or {}),
        "country": body.get("Country"),
        "lon": pd.to_numeric(body.get("Long"), errors="coerce"),
        "lat": pd.to_numeric(body.get("Lat"), errors="coerce"),
        "data_type": body.get("Data Type"),
        "eval_category": body.get("Evaluation Category"),
        "min_scenes": pd.to_numeric(body.get("Min # of Scenes"), errors="coerce").astype("Int64"),
        "ideal_scenes": pd.to_numeric(body.get("Ideal # of Scenes"), errors="coerce").astype("Int64"),
        "catalog_id": body.get("CatalogID"),
        "order_id": body.get("OrderID"),
        "order_date": body.get("Order Date", pd.Series(index=body.index, dtype=object)).map(_excel_date),
        "date_received": body.get("Date Rec'd", pd.Series(index=body.index, dtype=object)).map(_excel_date),
        "toa_radiance": body.get("Ortho TOA radiance"),
        "surface_refl": body.get("Ortho Surface Refl"),
        "window_start": body["Start"].map(_excel_date),
        "window_end": body["End"].map(_excel_date),
        "note": body.get("note"),
    })
    out["window"] = out.groupby("site_name").cumcount() + 1
    out["cell_row"] = out.index
    return out.reset_index(drop=True)


def google_sheet_csv_url(sheet_id: str, gid: Union[int, str]) -> str:
    """CSV export URL of one tab of a Google Sheet shared as 'anyone with the link'.
    Use the tab's gid (from its URL): the export by tab *name* silently returns the first tab
    when the name does not match."""
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"


def _count(value) -> Tuple[Optional[int], bool, str]:
    """'5' -> (5, False, ''); '1 per sensor' -> (1, True, ''); '10*' -> (10, False, '*'); '' -> (None, False, '')."""
    text = "" if value is None or (isinstance(value, float) and pd.isna(value)) else str(value).strip()
    match = re.match(r"^(\d+)\s*(.*)$", text)
    if not match:
        return None, False, text
    rest = match.group(2)
    per_sensor = "per sensor" in rest.lower()
    return int(match.group(1)), per_sensor, "" if per_sensor else rest


def read_legion_request(source: Union[str, Path], site_aliases: Optional[Dict[str, str]] = None) -> pd.DataFrame:
    """The Legion evaluation site request tab (Evaluation Site Requests sheet, e.g. Legion_20260914) as one
    row per site with its requirements. `source`: a CSV path or URL (see google_sheet_csv_url).

    min / ideal number of acquisitions: '1 per sensor' -> 1 with per_sensor=True; a trailing note such as
    '*' goes to min_note / ideal_note. Pan / MS / TOA / SR: yes -> True. LG01..LG06 are kept as text
    (the sheet has '?' until sensors are confirmed). Blank cloud or view-angle limits = no limit."""
    raw = pd.read_csv(source, dtype=str).dropna(how="all")
    raw.columns = [c.strip() for c in raw.columns]
    num = lambda col: pd.to_numeric(raw.get(col), errors="coerce")
    yes = lambda col: raw.get(col, pd.Series(index=raw.index, dtype=str)).str.strip().str.lower().eq("yes")
    out = pd.DataFrame({
        "site_name": raw["Site Name"].str.strip().replace(site_aliases or {}),
        "location_name": raw.get("Location Name"),
        "country": raw.get("Country"),
        "lon": num("Longitude"), "lat": num("Latitude"),
        "eval_category": raw.get("Evaluation Category"),
        "aoi_shape": raw.get("aoi_shape"), "aoi_size_km": num("aoi_size_km"),
        "max_view_angle": num("max_view_angle"),
        "max_cloud_pct_aoi": num("max_cloud_pct_aoi"), "max_cloud_pct_scene": num("max_cloud_pct_scene"),
        "pan": yes("Pan"), "ms": yes("MS"), "toa": yes("TOA"), "sr": yes("SR"),
    })
    for kind in ("min", "ideal"):
        parsed = raw[f"{kind}_num_acqs"].map(_count)
        out[f"{kind}_acqs"] = pd.array([p[0] for p in parsed], dtype="Int64")
        out[f"{kind}_per_sensor"] = [p[1] for p in parsed]
        out[f"{kind}_note"] = [p[2] for p in parsed]
    for col in [c for c in raw.columns if re.fullmatch(r"LG\d\d", c)]:
        out[col] = raw[col]
    return out.reset_index(drop=True)


def id_time(acq_id) -> Tuple[Optional[str], pd.Timestamp]:
    """(platform, UTC acquisition time) from an Airbus ID, e.g.
    'DS_PHR1A_202304050917383_FR1_...' or 'PNEO4_202603050911357_PAN_ORT_SR'
    -> ('PHR1A', 2023-04-05 09:17:38.3). (None, NaT) if the ID has no time."""
    m = _ID_TIME.match(str(acq_id)) if isinstance(acq_id, str) else None
    if not m:
        return None, pd.NaT
    t = pd.to_datetime(m.group(2), format="%Y%m%d%H%M%S", utc=True)
    return m.group(1), t + pd.Timedelta(seconds=int(m.group(3)) / 10)


def read_airbus_tracking(path: Union[str, Path], sheet: str = "AirbusTracking",
                         legend_rows: Tuple[int, ...] = (1, 2),
                         site_aliases: Optional[Dict[str, str]] = None) -> pd.DataFrame:
    """The Airbus tracking tab as one row per (site, acq #, platform, radiometry):

    site_name, acq_num, platform (PHR1A, PHR1B, PNEO3, PNEO4, SPOT6),
    radiometry (TOA / SR column of the sheet), status (from the cell fill, via
    the legend in `legend_rows`), tracking_id (DS_... or ACQ_... as written),
    acq_time (UTC; from the DS_ ID, or the PNeo date column), sheet_note (the
    "CSDA has N scenes" header above the site's block, per platform), cell (e.g. 'G6'),
    cells (all cells of the entry, e.g. 'G6 H6' for a PNeo date + ACQ_ pair).

    Empty cells that carry a status fill (e.g. 'New Tasking Submitted' with no
    acquisition yet) are kept with tracking_id = NaN; empty unfilled cells are not.
    CSDA acquisition IDs written by write_csda_status for new tasking
    (e.g. 'PNEO3_202610061657285') count as tracking IDs.
    A PNeo SR cell has only an ACQ_ ID; it takes the acquisition time of the
    TOA cell in the same row when the IDs are the same.
    """
    cells = read_xlsx_cells(path, sheet)
    legend = {r.fill: r.value for r in cells[cells.row.isin(legend_rows) & (cells.col >= 2)].itertuples()
              if r.value and r.fill is not None}
    labels = {**FILL_LABELS, **legend}

    # Header: platform names (row with 'PHR'), radiometry (row with 'TOA'), both filled rightwards
    def header_row(pattern):
        hit = cells[cells.value.fillna("").str.contains(pattern)]
        return hit.row.min()
    platform_row, radio_row = header_row(r"^PHR"), header_row(r"^TOA$")
    cols = sorted(cells.loc[cells.row.isin([platform_row, radio_row]) & (cells.col >= 2), "col"].unique())
    plat = cells[cells.row == platform_row].set_index("col").value.reindex(cols).ffill()
    radio = cells[cells.row == radio_row].set_index("col").value.reindex(cols)
    radio = radio.groupby(plat).ffill()   # PNeo: the date + ACQ_ pair sits under one TOA header
    plat = plat.str.upper().str.replace(r"[\s\-]", "", regex=True)   # 'PNeo 3' -> 'PNEO3'

    data = cells[cells.row > radio_row].copy()
    is_note = data.value.fillna("").str.contains(r"CSDA has", case=False)
    note_rows = data[is_note]
    site_rows = data[(data.col == 0) & data.value.notna()].set_index("row").value
    acq_rows = data[(data.col == 1) & data.value.fillna("").str.fullmatch(r"\d+")].set_index("row").value

    records = []
    for row, acq_num in acq_rows.items():
        site = site_rows[site_rows.index <= row].iloc[-1]
        site = (site_aliases or {}).get(site, site)
        block_notes = note_rows[note_rows.row < row]
        block_notes = block_notes[block_notes.row == block_notes.row.max()].set_index("col").value
        line = data[(data.row == row) & data.col.isin(cols)].set_index("col")
        for (p, r), group in pd.DataFrame({"platform": plat, "radiometry": radio}).groupby(
                ["platform", "radiometry"], sort=False):
            here = line.reindex(group.index)
            values = here.value.dropna().tolist()
            fills = [f for f in here.fill if labels.get(f) != "unmarked"]
            fill = fills[0] if fills else (here.fill.dropna().iloc[0] if here.fill.notna().any() else None)
            status = labels.get(fill, f"unknown fill {fill}")
            if not values and status in ("unmarked", "n/a (black)"):
                continue
            # Sheet IDs (DS_..., ACQ_...) or CSDA acquisition IDs written for new tasking (PNEO3_2026...)
            ids = [v for v in values if re.match(r"^(DS|ACQ)_", v) or _ID_TIME.fullmatch(v)]
            times = [t for t in pd.to_datetime(pd.Series(values, dtype=object), utc=True, errors="coerce")
                     if pd.notna(t)] if values else []
            tracking_id = ids[0] if ids else None
            acq_time = times[0] if times else id_time(tracking_id)[1]
            note = block_notes.reindex(plat.index[plat == p]).dropna()   # the note sits over TOA only
            records.append({
                "site_name": site, "acq_num": int(acq_num), "platform": p, "radiometry": r,
                "status": status, "tracking_id": tracking_id, "acq_time": acq_time,
                "sheet_note": note.iloc[0] if len(note) else None,
                "cell": _cell_ref(group.index[0], row),
                "cells": " ".join(_cell_ref(c, row) for c in group.index),   # PNeo TOA: date + ACQ_ cells
            })
    out = pd.DataFrame(records)
    out["acq_time"] = pd.to_datetime(out["acq_time"], utc=True)

    # PNeo SR cells: borrow the TOA time when it is the same ACQ_ ID
    toa = out[out.radiometry == "TOA"].set_index(["site_name", "acq_num", "platform"])
    sr = (out.radiometry == "SR") & out.acq_time.isna() & out.tracking_id.notna()
    for i in out.index[sr]:
        key = tuple(out.loc[i, ["site_name", "acq_num", "platform"]])
        if key in toa.index and toa.loc[key, "tracking_id"] == out.loc[i, "tracking_id"]:
            out.loc[i, "acq_time"] = toa.loc[key, "acq_time"]
    return out


def _cell_ref(col: int, row: int) -> str:
    name = ""
    col += 1
    while col:
        col, rem = divmod(col - 1, 26)
        name = chr(65 + rem) + name
    return f"{name}{row}"


# --------------------------------------------------------------------------
# Write a copy of the tab, recoloured to show what is in CSDA STAC
# --------------------------------------------------------------------------

def _solid_fill(rgb: str) -> str:
    return (f'<fill><patternFill patternType="solid"><fgColor rgb="FF{rgb}"/>'
            f'<bgColor indexed="64"/></patternFill></fill>')


def _sheet_time(t: pd.Timestamp) -> str:
    """'2026-10-06T16:57:28.500Z', as the sheet writes PNeo acquisition dates."""
    return t.tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%S.") + f"{t.microsecond // 1000:03d}Z"


def write_csda_status(path_in: Union[str, Path], path_out: Union[str, Path], tracking: pd.DataFrame,
                      sheet: str = "AirbusTracking", as_of: Optional[str] = None,
                      colors: Tuple[str, str] = ("92D050", "E2EFDA"),
                      legend_cells: Tuple[str, str] = ("G1", "G2"),
                      new_tasking_label: str = "New Tasking Received",
                      only_sheet: bool = True) -> pd.DataFrame:
    """Copy the workbook with the cells of tracked acquisitions that are in
    CSDA STAC filled green, and two legend entries added:

        colors[0] at legend_cells[0]: "In CSDA STAC (as of <as_of>)"   - match == 'id time'
        colors[1] at legend_cells[1]: "Likely in CSDA STAC (check)"    - match == 'same pass?'

    New tasking slots filled by the notebook (match == 'new tasking') get the
    fill of the sheet's own `new_tasking_label` legend entry and the CSDA
    acquisition ID; a PNeo TOA slot (date + ID cells) also gets the date.

    `tracking` is read_airbus_tracking() output with the notebook's match
    columns (in_csda, match, radiometry_in_csda, and acquisition_id / csda_time
    for new tasking). A cell is recoloured only if CSDA has its column's
    radiometry (TOA or SR); everything else, including values (other than new
    tasking), borders and fonts, is left as it was. only_sheet=True keeps just
    `sheet` in the new workbook. Returns the recoloured entries.
    """
    as_of = as_of or pd.Timestamp.today().strftime("%Y-%m-%d")
    labels = (f"In CSDA STAC (as of {as_of})", "Likely in CSDA STAC (acquisition time differs; check)")
    found = tracking[tracking.in_csda & tracking.radiometry_in_csda].copy()
    is_new = found["match"].eq("new tasking")
    hit, new = found[~is_new].copy(), found[is_new]
    hit["kind"] = (hit["match"] != "id time").astype(int)   # 0 = confirmed, 1 = check
    kind_of = {ref: k for refs, k in zip(hit.cells, hit.kind) for ref in refs.split()}
    # New tasking: (date cell,) ID cell
    value_of = {}
    for refs, acq_id, t in zip(new.cells, new.acquisition_id, new.csda_time):
        refs = refs.split()
        value_of[refs[-1]] = acq_id
        if len(refs) > 1:
            value_of[refs[0]] = _sheet_time(t)

    with zipfile.ZipFile(path_in) as z:
        parts = {n: z.read(n) for n in z.namelist()}
    book = parts["xl/workbook.xml"].decode("utf8")
    rels = parts["xl/_rels/workbook.xml.rels"].decode("utf8")
    rid = re.search(r'<sheet [^>]*name="%s"[^>]*r:id="([^"]+)"' % re.escape(sheet), book).group(1)
    target = re.search(r'Id="%s"[^>]*Target="([^"]+)"' % rid, rels).group(1)
    sheet_part = "xl/" + target.lstrip("/").replace("xl/", "", 1)
    xml = parts[sheet_part].decode("utf8")

    # Styles: two new fills, and for every style used by a recoloured cell a copy with the new fill
    styles = parts["xl/styles.xml"].decode("utf8")
    n_fills = int(re.search(r'<fills count="(\d+)"', styles).group(1))
    styles = re.sub(r'<fills count="\d+"', f'<fills count="{n_fills + 2}"', styles)
    styles = styles.replace("</fills>", _solid_fill(colors[0]) + _solid_fill(colors[1]) + "</fills>")
    xfs_block = re.search(r"<cellXfs[^>]*>(.*?)</cellXfs>", styles, re.S)
    xfs = re.findall(r"<xf\b[^>]*?/>|<xf\b[^>]*?>.*?</xf>", xfs_block.group(1), re.S)
    new_xfs, xf_for = [], {}

    def recoloured(style: int, fill_id: int) -> int:
        if (style, fill_id) not in xf_for:
            xf = xfs[style]
            head = re.match(r"<xf\b[^>]*?(?=/?>)", xf).group()
            new_head = re.sub(r'\s(fillId|applyFill)="[^"]*"', "", head) + \
                f' fillId="{fill_id}" applyFill="1"'
            new_xfs.append(xf.replace(head, new_head, 1))
            xf_for[(style, fill_id)] = len(xfs) + len(new_xfs) - 1
        return xf_for[(style, fill_id)]

    # Fill of the sheet's legend entry for new tasking received (legend rows 1-2)
    new_fill = None
    if value_of:
        legend = read_xlsx_cells(path_in, sheet).query("row <= 2 and value == @new_tasking_label")
        if legend.empty:
            raise ValueError(f"No {new_tasking_label!r} entry in the legend of {sheet}")
        ref = _cell_ref(legend.col.iloc[0], legend.row.iloc[0])
        legend_xf = xfs[int(re.search(r'<c r="%s" s="(\d+)"' % ref, xml).group(1))]
        new_fill = int(re.search(r'fillId="(\d+)"', legend_xf).group(1))
    unwritten = set(value_of)

    def restyle(match):
        cell = match.group(0)
        ref = re.search(r'\br="([A-Z]+\d+)"', cell).group(1)
        old = re.search(r'\bs="(\d+)"', cell)
        style = int(old.group(1)) if old else 0
        if ref in value_of:
            unwritten.discard(ref)
            return (f'<c r="{ref}" s="{recoloured(style, new_fill)}" t="inlineStr">'
                    f'<is><t>{escape(str(value_of[ref]))}</t></is></c>')
        if ref not in kind_of:
            return cell
        new_style = recoloured(style, n_fills + kind_of[ref])
        return re.sub(r'\ss="\d+"', "", cell, count=1).replace("<c ", f'<c s="{new_style}" ', 1)

    xml = re.sub(r"<c\b[^>]*?(?:/>|>.*?</c>)", restyle, xml, flags=re.S)
    if unwritten:   # slots read from the sheet always exist as styled cells
        raise ValueError(f"New tasking cells not found in {sheet}: {sorted(unwritten)}")

    # Legend entries, styled like the first legend cell
    legend_style = int(re.search(r'<c r="C1" s="(\d+)"', xml).group(1))
    for ref, kind, text in zip(legend_cells, (0, 1), labels):
        cell = (f'<c r="{ref}" s="{recoloured(legend_style, n_fills + kind)}" t="inlineStr">'
                f'<is><t>{text}</t></is></c>')
        row_num = re.sub(r"[A-Z]+", "", ref)
        if re.search(r'<c r="%s"[^>]*?(/>|>.*?</c>)' % ref, xml):
            xml = re.sub(r'<c r="%s"[^>]*?(/>|>.*?</c>)' % ref, cell, xml, count=1)
        else:   # append to the row, keeping cells in column order
            row = re.search(r'(<row [^>]*r="%s"[^>]*>)(.*?)(</row>)' % row_num, xml, re.S)
            cells_xml = re.findall(r"<c\b[^>]*?(?:/>|>.*?</c>)", row.group(2), re.S)
            cells_xml.append(cell)
            cells_xml.sort(key=lambda c: _col_index(re.search(r'r="([A-Z]+)', c).group(1)))
            xml = xml[:row.start(2)] + "".join(cells_xml) + xml[row.end(2):]

    styles = (styles[:xfs_block.start(1)] + xfs_block.group(1) + "".join(new_xfs) + styles[xfs_block.end(1):])
    styles = re.sub(r'<cellXfs count="\d+"', f'<cellXfs count="{len(xfs) + len(new_xfs)}"', styles)
    parts["xl/styles.xml"] = styles.encode("utf8")
    parts[sheet_part] = xml.encode("utf8")

    if only_sheet:
        drop = set()
        for m in re.finditer(r'<sheet [^>]*r:id="([^"]+)"[^>]*/>', book):
            if m.group(1) != rid:
                t = re.search(r'Id="%s"[^>]*Target="([^"]+)"' % m.group(1), rels).group(1)
                drop.add("xl/" + t.lstrip("/").replace("xl/", "", 1))
        drop.add("xl/calcChain.xml")   # formula order of the dropped sheets; Excel rebuilds it
        book = re.sub(r'<sheet [^>]*r:id="(?!%s")[^"]+"[^>]*/>' % rid, "", book)
        book = re.sub(r'\s(firstSheet|activeTab)="\d+"', "", book)
        book = re.sub(r"<definedNames>.*?</definedNames>", "", book, flags=re.S)
        rels = re.sub(r'<Relationship [^>]*Target="(?:/xl/)?(%s)"[^>]*/>'
                      % "|".join(re.escape(d.replace("xl/", "", 1)) for d in drop), "", rels)
        types = parts["[Content_Types].xml"].decode("utf8")
        types = re.sub(r'<Override PartName="/(%s)"[^>]*/>' % "|".join(re.escape(d) for d in drop), "", types)
        parts["[Content_Types].xml"] = types.encode("utf8")
        parts["xl/workbook.xml"] = book.encode("utf8")
        parts["xl/_rels/workbook.xml.rels"] = rels.encode("utf8")
        for d in drop:
            parts.pop(d, None)
            parts.pop(d.replace("worksheets/", "worksheets/_rels/") + ".rels", None)

    with zipfile.ZipFile(path_out, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in parts.items():
            z.writestr(name, data)
    return pd.concat([hit.drop(columns="kind").assign(color=hit.kind.map({0: labels[0], 1: labels[1]})),
                      new.assign(color=new_tasking_label)])
