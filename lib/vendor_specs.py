"""
CSDA Vendor Specs database (Google Sheet): load, QA checks, constellation summary.

The sheet 'NASA CSDA ... Vendor Specs' has one row per sensor / satellite
(generation) and ~110 columns. Columns A-AS (identity, orbit, geometry,
radiometry) are the core spec fields; AT onward are band ranges, band counts,
notes and the GNSS-R fields.

    import vendor_specs as vs
    raw = vs.load()                       # live from the sheet (shared 'anyone with the link')
    issues = vs.qa_checks(raw)            # one row per suspect cell, columns A-AS (+ band counts)
    groups = vs.constellations(raw)       # one row per constellation / generation with distinct specs
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

SHEET_ID = "13MrpqFtAOqQY9WdW9lHNsqjCbG-e3VQkEDbHOGIKa6k"
GID = {"Vendor Specs": 1094438485, "SME needs": 1783095051}

# Controlled vocabularies used by the checks (values seen in the sheet that are fine)
STATUS = {"Operational", "Constellation", "Limited", "Planned", "Retired", "Failed", "Deorbited"}
CURRENT_STATUS = {"Operational", "Constellation", "Limited"}
SECTOR = {"Commercial", "Government"}
SCANNER = {"Pushbroom", "Whiskbroom", "Frame", "Frame/Video", "Pushframe"}
ACQUISITION = {"Tasking", "Systematic"}
YES_NO = {"Yes", "No", "Limited"}
# Satellite size class by mass (kg), as in csda_specs_multispec_smry.ipynb
SIZE_CLASS = [("Nano", 1, 10), ("Micro", 10, 100), ("Mini", 100, 500), ("Medium", 500, 1000), ("Large", 1000, 1e9)]

NUMERIC = ["Weight Range (kg)", "Orbit Altitude (km)", "Orbit Period (min)", "Revisit Time (days, < 20 ° onva)",
           "Swath Width (km)", "Downlink Latency (min, median)", "n satellites",
           "Pan GSD Nadir (m)", "MS GSD Nadir (m)", "SWIR GSD Nadir (m)", "TIR GSD Nadir (m)",
           "Pan GSD Off-Nadir Min (m)", "Pan GSD Off-Nadir Max (m)", "MS GSD Off-Nadir Min (m)",
           "MS GSD Off-Nadir Max (m)", "Geolocation Accuracy (CE90, m)", "Geometric Temporal Stability (CE90, m)",
           "Agility (off-nadir, ± degrees )", "Total Bands (MS)", "Total Bands"]


def csv_url(sheet_id: str = SHEET_ID, gid: int = GID["Vendor Specs"]) -> str:
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"


def load(source: Optional[str] = None) -> pd.DataFrame:
    """The Vendor Specs tab as text (no type conversion), plus `sheet_row`
    (row number in the sheet, header = 1) and `label` (constellation + sensor)."""
    df = pd.read_csv(source or csv_url(), dtype=str)
    df = df.loc[:, ~df.columns.str.startswith("Unnamed")]
    df = df.apply(lambda s: s.str.strip().mask(s.str.strip() == "") if s.dtype == object else s)
    con = df["Constellation/Platform"].fillna("")
    front = pd.DataFrame({"sheet_row": np.arange(len(df)) + 2,
                          "label": (con + " " + df["Sensor Name"].fillna("")).str.strip()}, index=df.index)
    return pd.concat([front, df], axis=1)


def to_number(value, how: str = "first") -> float:
    """'~97' -> 97, '>0.30' -> 0.3, '500-1000' -> 500 (how='first'), 'max' or 'mean';
    '10.41%' -> 10.41; text without a number -> NaN."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return np.nan
    nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", str(value).replace(",", ""))]
    if not nums:
        return np.nan
    if len(nums) >= 2 and re.search(r"\d\s*[-–]\s*\d", str(value)):
        return {"first": nums[0], "max": max(nums[:2]), "mean": float(np.mean(nums[:2]))}[how]
    return nums[0]


def column_letter(i: int) -> str:
    """0 -> 'A', 26 -> 'AA'."""
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def _period_minutes(alt_km: float) -> float:
    """Circular-orbit period from altitude (Kepler)."""
    mu, r_e = 398600.4418, 6378.137
    return 2 * np.pi * np.sqrt((r_e + alt_km) ** 3 / mu) / 60


def qa_checks(df: pd.DataFrame, today: Optional[str] = None) -> pd.DataFrame:
    """Automated checks on columns A-AS (and the band counts). One row per suspect
    cell: sheet_row, label, column (letter), field, value, check, detail.
    These find structural problems (shifted cells, swapped dates, unparseable
    numbers, inconsistent pairs); they do not prove a value is right."""
    today = pd.Timestamp(today or pd.Timestamp.today().normalize())
    cols = [c for c in df.columns if c not in ("sheet_row", "label")]
    letter = {c: column_letter(i) for i, c in enumerate(cols)}
    out = []

    def flag(r, field, check, detail=""):
        out.append(dict(sheet_row=r.sheet_row, label=r.label, column=letter.get(field, ""), field=field,
                        value=r.get(field), check=check, detail=detail))

    num = {c: df[c].map(to_number) for c in NUMERIC if c in df}
    for i, r in df.iterrows():
        # --- identity ---
        for field in ("Sensor Name", "Constellation/Platform", "Launch Date", "Affiliation", "Sector",
                      "Mission Status", "Scanner Type", "Acquisition Strategy", "Swath Width (km)"):
            if pd.isna(r.get(field)):
                flag(r, field, "missing", "core field is empty")
        if pd.notna(r["Sector"]) and r["Sector"] not in SECTOR:
            flag(r, "Sector", "not in vocabulary", f"expected one of {sorted(SECTOR)}")
        status = str(r["Mission Status"]) if pd.notna(r["Mission Status"]) else ""
        if status and status not in STATUS:
            flag(r, "Mission Status", "not in vocabulary",
                 f"expected one of {sorted(STATUS)}; put dates in Start / End Date")
        for field, vocab in (("Scanner Type", SCANNER), ("Acquisition Strategy", ACQUISITION)):
            if pd.notna(r[field]) and r[field] not in vocab:
                flag(r, field, "not in vocabulary", f"expected one of {sorted(vocab)}")

        # --- dates ---
        dates = {}
        for field in ("Launch Date", "Start Date", "End Date"):
            v = r[field]
            if pd.isna(v):
                continue
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(v)):
                flag(r, field, "date format", "use YYYY-MM-DD")
            dates[field] = pd.to_datetime(v, errors="coerce")
        launch, start, end = (dates.get(k) for k in ("Launch Date", "Start Date", "End Date"))
        if launch is not None and start is not None and pd.notna(launch) and pd.notna(start):
            if start < launch:
                flag(r, "Start Date", "before launch")
            elif (start - launch).days > 3 * 365:
                flag(r, "Start Date", "start years after launch", "looks like an end date (shifted into Start Date?)")
        if launch is not None and end is not None and pd.notna(launch) and pd.notna(end) and end < launch:
            flag(r, "End Date", "before launch")
        if launch is not None and pd.notna(launch):
            if launch > today and status in CURRENT_STATUS:
                flag(r, "Mission Status", "status vs launch", f"{status} but launch is in the future")
            if launch <= today and status == "Planned":
                flag(r, "Mission Status", "status vs launch", "Planned but the launch date has passed")
        if end is not None and pd.notna(end) and end <= today and status in CURRENT_STATUS:
            flag(r, "Mission Status", "status vs end date", f"{status} but End Date has passed")

        # --- mass and size class ---
        mass = num["Weight Range (kg)"][i]
        size = r["Satellite Size Class"]
        if pd.notna(mass) and pd.notna(size) and size in {s for s, _, _ in SIZE_CLASS}:
            expect = next(s for s, lo, hi in SIZE_CLASS if lo <= mass < hi)
            if expect != size:
                flag(r, "Satellite Size Class", "size class vs mass", f"{mass:g} kg is {expect}")

        # --- orbit ---
        alt, per = num["Orbit Altitude (km)"][i], num["Orbit Period (min)"][i]
        if pd.notna(alt) and pd.notna(per) and abs(_period_minutes(alt) - per) > 1.5:
            flag(r, "Orbit Period (min)", "period vs altitude",
                 f"{alt:g} km gives {_period_minutes(alt):.1f} min (circular orbit)")

        # --- geometry ---
        pan, ms = num["Pan GSD Nadir (m)"][i], num["MS GSD Nadir (m)"][i]
        if pd.notna(pan) and pd.notna(ms) and pan > ms:
            flag(r, "Pan GSD Nadir (m)", "pan coarser than MS")
        for kind, nadir in (("Pan", pan), ("MS", ms)):
            lo = num[f"{kind} GSD Off-Nadir Min (m)"][i]
            hi = num[f"{kind} GSD Off-Nadir Max (m)"][i]
            if pd.notna(nadir) and pd.notna(lo) and lo < nadir - 1e-9:
                flag(r, f"{kind} GSD Off-Nadir Min (m)", "off-nadir finer than nadir",
                     f"off-nadir min {lo:g} m < nadir {nadir:g} m")
            if pd.notna(lo) and pd.notna(hi) and hi < lo:
                flag(r, f"{kind} GSD Off-Nadir Max (m)", "max < min")

        # --- shifted cells (text where a number belongs, or the reverse) ---
        for field in ("Stereo Capability", "DEM Generation"):
            v = r[field]
            if pd.notna(v) and v not in YES_NO:
                flag(r, field, "shifted cells?", f"expected Yes / No / Limited; cells from here right may be shifted")
        for field in ("Geolocation Accuracy (CE90, m)", "Agility (off-nadir, ± degrees )", "Swath Width (km)",
                      "Orbit Altitude (km)"):
            v = r[field]
            if pd.notna(v) and np.isnan(to_number(v)):
                flag(r, field, "not a number", "text in a numeric field")
        bit = r["Bit Depth"]
        if pd.notna(bit) and not re.fullmatch(r"\d{1,2}(-bit)?", str(bit)):
            flag(r, "Bit Depth", "format", "expected e.g. '12-bit'")

        # --- band counts ---
        nb_ms, nb = num["Total Bands (MS)"][i], num["Total Bands"][i]
        if pd.notna(nb_ms) and pd.notna(nb) and nb < nb_ms:
            flag(r, "Total Bands", "total < MS bands")
        # The sheet has 16 named band-range slots (Coastal ... SWIR2); skip sensors with more bands
        filled = sum(pd.notna(r.get(f"{b} Min (nm)")) for b in BAND_NAMES)
        has_pan = pd.notna(r.get("Pan Min (nm)"))
        # Rule (2 Nov 2026): Total Bands (MS) counts the pan band
        expect = filled + int(has_pan)
        if pd.notna(nb_ms) and filled and nb_ms <= len(BAND_NAMES) + 1 and expect != nb_ms:
            if has_pan and filled == nb_ms:
                flag(r, "Total Bands (MS)", "MS count leaves out pan",
                     f"{filled} MS band ranges + pan = {expect}; Total Bands (MS) = {nb_ms:g} (rule: count pan)")
            else:
                flag(r, "Total Bands (MS)", "band count vs band ranges",
                     f"{filled} MS band ranges{' + pan' if has_pan else ''} filled = {expect}, "
                     f"Total Bands (MS) = {nb_ms:g}")
    return pd.DataFrame(out)


BAND_NAMES = ["Coastal", "Blue", "Blue2", "Green1", "Green2", "Yellow", "Red", "RedEdge", "RedEdge1", "RedEdge2",
              "NIR", "NIR2", "NIR WV", "SWIRCirrus", "SWIR1", "SWIR2"]


def _group_label(g: pd.DataFrame) -> str:
    """Readable name for sensors that share specs: 'Legion', 'Sentinel-2', 'Landsat 8/9', 'VIIRS'."""
    sensors = g["Sensor Name"].fillna("").unique()
    brands = {}
    for b in g["Branded Name"].dropna().str.strip():
        brands.setdefault(b.lower(), b)                         # 'Kuva' and 'kuva' are one name
    brands = sorted(brands.values())
    con = (g["Constellation/Platform"].fillna("").iloc[0] or "").strip()
    if len(g) > 1 and len(sensors) == 1:                      # same instrument on several platforms
        return sensors[0]
    if len(brands) == 1:
        return brands[0]
    if len(brands) > 1:
        prefix = "".join(c[0] for c in zip(*brands) if len(set(c)) == 1) if all(brands) else ""
        prefix = prefix[:next((i for i, c in enumerate(zip(*brands)) if len(set(c)) > 1), len(prefix))]
        tails = [b[len(prefix):] for b in brands]
        if prefix.strip(" -") and all(re.fullmatch(r"[A-Z]", t) for t in tails):   # Sentinel-2A/B/C/D
            return prefix.strip(" -")
        if prefix.strip(" -") and all(len(t) <= 3 for t in tails):                  # Landsat 8/9
            return prefix + "/".join(tails)
        return " / ".join(brands)
    return con or sensors[0]


def constellations(df: pd.DataFrame, labels: Optional[Dict[str, str]] = None,
                   drop_rows: Optional[List[int]] = None) -> pd.DataFrame:
    """One row per constellation / generation: sensors of one constellation with the
    same GSD, swath and band count are merged (e.g. Legion LG-1..6). Numbers parsed
    with to_number (ranges -> first value). `labels`: {group label: display name}
    overrides. `drop_rows`: sheet rows whose band counts are not trusted (set NaN)."""
    d = df.copy()
    for c in NUMERIC:
        d[c] = d[c].map(to_number)
    if drop_rows:
        d.loc[d.sheet_row.isin(drop_rows), ["Total Bands (MS)", "Total Bands"]] = np.nan
    d["launch"] = pd.to_datetime(d["Launch Date"], errors="coerce")
    # Same data owner and same specs = one group, whatever the platform (VIIRS on Suomi NPP / NOAA-20 / ...)
    key = ["Affiliation", "Pan GSD Nadir (m)", "MS GSD Nadir (m)", "Swath Width (km)", "Total Bands (MS)"]
    d["_key"] = d[key].astype(str).agg("|".join, axis=1)
    rows = []
    for _, g in d.groupby("_key", sort=False):
        f = g.iloc[0]
        rows.append(dict(
            group=_group_label(g), affiliation=f["Affiliation"], sector=f["Sector"],
            constellation=f["Constellation/Platform"], sensors=", ".join(g["Sensor Name"].fillna("?")),
            status=", ".join(sorted(g["Mission Status"].fillna("?").unique())),
            current=g["Mission Status"].isin(CURRENT_STATUS).any() or g["Mission Status"].isna().all(),
            first_launch=g["launch"].min(), n_sensors=len(g),
            n_satellites=g["n satellites"].sum(min_count=1),
            pan_gsd=f["Pan GSD Nadir (m)"], ms_gsd=f["MS GSD Nadir (m)"], swir_gsd=f["SWIR GSD Nadir (m)"],
            tir_gsd=f["TIR GSD Nadir (m)"], swath_km=f["Swath Width (km)"], ms_bands=f["Total Bands (MS)"],
            total_bands=f["Total Bands"], revisit_days=f["Revisit Time (days, < 20 ° onva)"],
            ce90_m=f["Geolocation Accuracy (CE90, m)"], scanner=f["Scanner Type"],
            acquisition=f["Acquisition Strategy"], sheet_rows=", ".join(g.sheet_row.astype(str))))
    out = pd.DataFrame(rows)
    # Names still shared by different spec sets: the constellation name if that tells them apart
    # (Pleiades / PleiadesNeo), else add the sensor names (BlackSky Gen 1 / Gen 2)
    dup = out.group.duplicated(keep=False)
    by_con = dup & ~out.constellation.fillna("").duplicated(keep=False) & out.constellation.notna()
    out.loc[by_con, "group"] = out.loc[by_con, "constellation"]
    dup = out.group.duplicated(keep=False)
    out.loc[dup, "group"] = out.loc[dup, "group"] + " " + out.loc[dup, "sensors"].str.replace(", ", "/")
    if labels:
        out["group"] = out.group.replace(labels)
    return out.sort_values(["sector", "ms_gsd"]).reset_index(drop=True)


def core_fields(df: pd.DataFrame) -> List[str]:
    """Sheet columns A-AS (the core spec fields), in sheet order."""
    cols = [c for c in df.columns if c not in ("sheet_row", "label")]
    return cols[:cols.index("Radiometric Temporal Stability (%)") + 1]


FIELD_HINTS = {
    "Launch Date": "YYYY-MM-DD", "Start Date": "YYYY-MM-DD, first usable data", "End Date": "YYYY-MM-DD",
    "Mission Status": "/".join(sorted(STATUS)), "Sector": "/".join(sorted(SECTOR)),
    "Satellite Size Class": "Nano <10 kg, Micro 10-100, Mini 100-500, Medium 500-1000, Large >1000",
    "Orbit Type": "e.g. Sun-synchronous, Inclined LEO", "Scanner Type": "/".join(sorted(SCANNER)),
    "Acquisition Strategy": "/".join(sorted(ACQUISITION)), "Stereo Capability": "Yes/No/Limited",
    "DEM Generation": "Yes/No/Limited", "Bit Depth": "e.g. 12-bit",
}


def extraction_prompt(df: pd.DataFrame, constellation: str) -> str:
    """Text to paste into NASA Chat with a vendor document attached: asks for
    columns A-AS for one constellation, one value per line with the page it
    came from, as CSV. The current sheet values are included so the answer
    says what to change. Paste or save the answer and run compare_extracted()."""
    rows = df[df["Constellation/Platform"].fillna("").str.casefold() == constellation.casefold()]
    if rows.empty:
        rows = df[df.label.str.contains(constellation, case=False, na=False)]
    sensors = ", ".join(rows["Sensor Name"].fillna("?"))
    lines = []
    for f in core_fields(df):
        if f in ("Reference", "assessment status"):
            continue
        cur = "; ".join(sorted({str(v) for v in rows[f].dropna()})) or "(empty)"
        hint = FIELD_HINTS.get(f, "")
        lines.append(f"- {f}{f'  [{hint}]' if hint else ''}  -- current: {cur}")
    return (
        f"From the attached document(s), extract the specifications of the {constellation} satellites "
        f"({sensors}) for the fields below. Use only what the documents state; do not use outside knowledge "
        "and do not guess. If a value differs between satellites or generations, give one line per sensor.\n\n"
        "Answer ONLY as CSV with this header:\n"
        "sensor,field,value,unit,document,page,quote\n"
        "- field: exactly as written below\n"
        "- value: number or vocabulary term only (e.g. 0.34, Pushbroom, 2024-05-02)\n"
        "- quote: the short text the value comes from\n"
        "- leave out fields the documents do not give\n\n"
        "Fields (unit or allowed values in [ ]; the current database value is shown for reference):\n"
        + "\n".join(lines))


def compare_extracted(df: pd.DataFrame, extracted, constellation: str) -> pd.DataFrame:
    """Compare a NASA Chat / manual extraction (CSV path, text or DataFrame with
    columns sensor, field, value, document, page) with the sheet rows of one
    constellation. Returns one row per extracted value: sheet_row, sensor,
    field, column letter, sheet value, extracted value, same (numbers compared
    with to_number), source."""
    import io
    if isinstance(extracted, str):
        extracted = pd.read_csv(io.StringIO(extracted) if "\n" in extracted else extracted, dtype=str)
    ex = extracted.copy()
    ex.columns = [c.strip().lower() for c in ex.columns]
    cols = [c for c in df.columns if c not in ("sheet_row", "label")]
    letter = {c: column_letter(i) for i, c in enumerate(cols)}
    rows = df[df["Constellation/Platform"].fillna("").str.casefold() == constellation.casefold()]
    out = []
    for _, e in ex.iterrows():
        field = str(e.get("field", "")).strip()
        match = rows[rows["Sensor Name"].fillna("").str.casefold() == str(e.get("sensor", "")).strip().casefold()]
        targets = match if len(match) else rows                # no sensor match: compare with every row
        for _, r in targets.iterrows():
            cur = r.get(field)
            new = e.get("value")
            nc, nn = to_number(cur), to_number(new)
            same = (abs(nc - nn) < 1e-9) if not (np.isnan(nc) or np.isnan(nn)) else \
                (str(cur).strip().casefold() == str(new).strip().casefold())
            out.append(dict(sheet_row=r.sheet_row, sensor=r["Sensor Name"], field=field,
                            column=letter.get(field, "?"), sheet_value=cur, extracted=new, same=same,
                            source=f"{e.get('document', '')} p.{e.get('page', '')}".strip(),
                            quote=e.get("quote")))
    res = pd.DataFrame(out)
    return res.sort_values(["same", "sheet_row", "column"]).reset_index(drop=True) if len(res) else res


def completeness(df: pd.DataFrame) -> pd.DataFrame:
    """True where a core field (A-AS) has a value, one row per sensor (label)."""
    f = [c for c in core_fields(df)]
    return df.set_index("label")[f].notna()


# --------------------------------------------------------------------------
# Plots: footprint (swath), GSD and number of bands across constellations
# --------------------------------------------------------------------------
# Colors: dataviz reference palette, categorical slots 1-2 (validated all-pairs for
# scatter forms); text in ink tokens, recessive grid.
SECTOR_COLORS = {"Commercial": "#2a78d6", "Government": "#eb6834"}
# Data-owner colors: the palette of csda_specs_multispec_smry.ipynb (RColorBrewer Set1 + Dark2, BlackSky black,
# US Agency blue), so plots stay familiar; owners added since get unused Dark2 colors.
AFFILIATION_COLORS = {
    "Airbus": "#E41A1C", "BlackSky": "#000000", "DLR / Teledyne": "#4DAF4A", "Earth Fire Alliance / Muon": "#984EA3",
    "EarthDaily": "#FF7F00", "ESA": "#FFFF33", "HydroSat": "#A65628", "ImageSat": "#F781BF", "JAXA": "#1B9E77",
    "Kuva": "#C16610", "OroraTech": "#8D6B86", "Planet Labs": "#BC4399", "Satellogic": "#A66753",
    "Satlantis": "#96A713", "SatVu": "#D59D08", "US Agency": "#0000FF", "Vantor": "#666666",
    "OrbitalSideKick": "#7570B3",   # added (not in the sheet when the R palette was made)
}
EXTRA_COLORS = ["#E7298A", "#66A61E", "#E6AB02", "#D95F02", "#A6761D", "#377EB8"]   # for owners new to the sheet
SURFACE, INK, INK_2, INK_3, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#8a8984", "#e8e7e2"
# Marker size bins for the number of MS / spectral bands
BAND_BINS = [(1, 4, "1–4 bands", 45), (5, 9, "5–9", 95), (10, 40, "10–40", 170), (41, 10_000, "> 40 (hyperspectral)", 280)]


def _style(ax):
    ax.set_facecolor(SURFACE)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(INK_3)
    ax.tick_params(colors=INK_2, labelsize=8.5, length=3)
    ax.grid(color=GRID, linewidth=0.7, which="major")
    ax.set_axisbelow(True)


def _band_size(n) -> float:
    if pd.isna(n):
        return BAND_BINS[0][3]
    return next(s for lo, hi, _, s in BAND_BINS if lo <= n <= hi)


def _place_labels(ax, xs, ys, texts, sizes, fontsize=7.5):
    """Greedy label placement around each point: the first candidate offset that
    does not overlap a placed label or a marker, else the least-overlapping one."""
    fig = ax.figure
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    pts = ax.transData.transform(np.column_stack([xs, ys]))
    radius = [np.sqrt(s) / 2 * fig.dpi / 72 + 2 for s in sizes]
    marks = [(x - r, y - r, x + r, y + r) for (x, y), r in zip(pts, radius)]
    placed = []
    cands = [(1, 1, "left", "bottom"), (1, -1, "left", "top"), (-1, 1, "right", "bottom"), (-1, -1, "right", "top"),
             (0, 1.4, "center", "bottom"), (0, -1.4, "center", "top"), (1.6, 0, "left", "center"),
             (-1.6, 0, "right", "center")]
    order = np.argsort(ys)[::-1]
    for i in order:
        best = None
        for dx, dy, ha, va in cands:
            r_pt = radius[i] * 72 / fig.dpi
            off = (dx * (r_pt + 5), dy * (r_pt + 4))
            # Leader from the label corner nearest the point to the marker edge, so every label is tied to its point
            relpos = ({"left": 0, "center": 0.5, "right": 1}[ha], {"bottom": 0, "center": 0.5, "top": 1}[va])
            t = ax.annotate(texts[i], (xs[i], ys[i]), xytext=off, textcoords="offset points", ha=ha, va=va,
                            fontsize=fontsize, color=INK,
                            arrowprops=dict(arrowstyle="-", color=INK_3, lw=0.6, shrinkA=0, shrinkB=r_pt,
                                            relpos=relpos))
            bb = t.get_window_extent(renderer).expanded(1.04, 1.1)
            box = (bb.x0, bb.y0, bb.x1, bb.y1)
            hits = sum(_overlap(box, o) for o in placed) + sum(_overlap(box, m) for j, m in enumerate(marks) if j != i)
            inside = ax.get_window_extent(renderer)
            hits += 0 if (bb.x0 >= inside.x0 and bb.x1 <= inside.x1 and bb.y0 >= inside.y0 and bb.y1 <= inside.y1) else 1e6
            if best is None or hits < best[0]:
                if best is not None:
                    best[1].remove()
                best = (hits, t, box)
            else:
                t.remove()
            if hits == 0:
                break
        placed.append(best[2])


def _overlap(a, b) -> float:
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    return w * h if w > 0 and h > 0 else 0.0


def plot_gsd_swath(groups: pd.DataFrame, title: Optional[str] = None, flagged=(), figsize=(11, 7.5)):
    """Scatter of MS GSD (x) vs swath width (y), both log; marker area = band-count
    bin; color = sector; black ring = has a panchromatic band (pan GSD in the sheet).
    Diagonals: pixels across the swath (swath / GSD).
    `flagged`: group names whose plotted values need checking (marked with *).
    Groups without MS GSD or swath are listed under the plot. Returns fig."""
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    d = groups.dropna(subset=["ms_gsd", "swath_km"]).reset_index(drop=True)
    left_out = groups.loc[groups.ms_gsd.isna() | groups.swath_km.isna(), "group"].tolist()
    fig, ax = plt.subplots(figsize=figsize, facecolor=SURFACE)
    _style(ax)
    ax.set_xscale("log"); ax.set_yscale("log")
    xlim = (d.ms_gsd.min() / 1.8, d.ms_gsd.max() * 2.2)
    ylim = (d.swath_km.min() / 1.6, d.swath_km.max() * 1.8)
    ax.set_xlim(xlim); ax.set_ylim(ylim)
    # Pixels across the swath: swath (km) * 1000 / GSD (m)
    gx = np.geomspace(*xlim, 50)
    for n in (1_000, 10_000, 100_000):
        ax.plot(gx, n * gx / 1000, color=INK_3, lw=0.8, ls=(0, (4, 3)), zorder=1)
        xl = np.clip(ylim[1] / 1.25 * 1000 / n, xlim[0] * 1.05, xlim[1] / 1.6)
        if ylim[0] < n * xl / 1000 < ylim[1]:
            ax.text(xl, n * xl / 1000, f"{n:,} pixels across", color=INK_3, fontsize=7.5, rotation=0,
                    ha="right", va="bottom")
    sizes = d.ms_bands.map(_band_size).to_numpy()
    sizes_lab = np.where(d.pan_gsd.notna(), (np.sqrt(sizes) + 4.5) ** 2, sizes)
    for i, r in d.iterrows():
        c = SECTOR_COLORS.get(r.sector, INK_3)
        known = pd.notna(r.ms_bands)
        ax.scatter(r.ms_gsd, r.swath_km, s=sizes[i], facecolor=c if known else SURFACE, edgecolor=c if not known else SURFACE,
                   linewidth=1.6 if not known else 1.2, alpha=0.9, zorder=3)
        if pd.notna(r.pan_gsd):              # panchromatic band: black ring around the marker
            ax.scatter(r.ms_gsd, r.swath_km, s=(np.sqrt(sizes[i]) + 4.5) ** 2, facecolor="none", edgecolor=INK,
                       linewidth=1.1, zorder=4)
    texts = [g + ("*" if g in flagged else "") for g in d.group]
    _place_labels(ax, d.ms_gsd.to_numpy(), d.swath_km.to_numpy(), texts, sizes_lab)
    ax.set_xlabel("Multispectral GSD at nadir (m, log scale)  —  finer detail ←", color=INK_2, fontsize=9.5)
    ax.set_ylabel("Swath width (km, log scale)  —  larger footprint ↑", color=INK_2, fontsize=9.5)
    from matplotlib.ticker import FuncFormatter
    fmt = FuncFormatter(lambda v, _: f"{v:g}")
    ax.xaxis.set_major_formatter(fmt); ax.yaxis.set_major_formatter(fmt)
    handles = [Line2D([], [], marker="o", ls="", color=c, markersize=8, label=s) for s, c in SECTOR_COLORS.items()
               if s in set(d.sector)]
    handles += [Line2D([], [], marker="o", ls="", color=INK_3, markersize=np.sqrt(s), label=lab, markeredgecolor=SURFACE)
                for _, _, lab, s in BAND_BINS]
    handles += [Line2D([], [], marker="o", ls="", markerfacecolor=SURFACE, markeredgecolor=INK_3, markersize=7,
                       markeredgewidth=1.6, label="band count not in sheet"),
                Line2D([], [], marker="o", ls="", markerfacecolor=INK_3, markeredgecolor=INK, markersize=9,
                       markeredgewidth=1.4, label="has a panchromatic band")]
    leg = ax.legend(handles=handles, loc="lower right", fontsize=8, frameon=True, framealpha=0.92,
                    edgecolor=GRID, title="Sector · number of bands", title_fontsize=8.5, labelcolor=INK)
    leg.get_frame().set_facecolor(SURFACE)
    ax.set_title(title or "Image footprint vs. detail: swath width and multispectral GSD", loc="left",
                 fontsize=13, color=INK, pad=12)
    notes = []
    if flagged:
        notes.append("* values flagged for checking in the specs DB")
    if left_out:
        notes.append("Not shown (no MS GSD or swath in the sheet): " + ", ".join(left_out))
    if notes:
        fig.text(0.01, 0.005, "\n".join(notes), fontsize=7.5, color=INK_2, ha="left", va="bottom", wrap=True)
    fig.tight_layout(rect=(0, 0.04 if notes else 0, 1, 1))
    return fig


def plot_spec_strips(groups: pd.DataFrame, title: Optional[str] = None, flagged=(), row_height=0.24):
    """Three aligned panels, one row per constellation (sorted by MS GSD):
    GSD (MS filled, pan open), swath width, number of bands. Each panel has its
    own axis (log). Returns fig."""
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    from matplotlib.ticker import FuncFormatter
    d = groups.sort_values(["ms_gsd", "pan_gsd", "swath_km"], na_position="last").reset_index(drop=True)
    n = len(d)
    fig, axes = plt.subplots(1, 3, figsize=(12.5, row_height * n + 1.6), sharey=True, facecolor=SURFACE,
                             gridspec_kw=dict(width_ratios=[1.25, 1, 0.9], wspace=0.06))
    y = np.arange(n)[::-1]
    fmt = FuncFormatter(lambda v, _: f"{v:g}")
    specs = [("GSD at nadir (m)", "ms_gsd", "pan_gsd"), ("Swath width (km)", "swath_km", None),
             ("Number of bands (MS / spectral)", "ms_bands", None)]
    for ax, (label, col, col2) in zip(axes, specs):
        _style(ax)
        ax.set_xscale("log")
        ax.grid(axis="y", visible=False)
        for yi, (_, r) in zip(y, d.iterrows()):
            c = SECTOR_COLORS.get(r.sector, INK_3)
            ax.axhline(yi, color=GRID, lw=0.5, zorder=0)
            if col2 and pd.notna(r[col2]):
                ax.scatter(r[col2], yi, s=36, facecolor=SURFACE, edgecolor=c, linewidth=1.4, zorder=3)
                if pd.notna(r[col]):
                    ax.plot([r[col2], r[col]], [yi, yi], color=c, lw=1, alpha=0.5, zorder=2)
            if pd.notna(r[col]):
                ax.scatter(r[col], yi, s=40, color=c, edgecolor=SURFACE, linewidth=0.8, zorder=4)
                ax.annotate(f"{r[col]:g}", (r[col], yi), xytext=(6, 0), textcoords="offset points", va="center",
                            fontsize=6.8, color=INK_2)
            else:
                ax.text(0.99, yi, "–", transform=ax.get_yaxis_transform(), ha="right", va="center", fontsize=7,
                        color=INK_3)
        ax.xaxis.set_major_formatter(fmt)
        ax.set_title(label, loc="left", fontsize=9.5, color=INK, pad=6)
        lo, hi = np.nanmin(d[[col] + ([col2] if col2 else [])].to_numpy(dtype=float)), np.nanmax(d[col].to_numpy(dtype=float))
        ax.set_xlim(lo / 1.5, hi * 3)
    axes[0].set_yticks(y)
    axes[0].set_yticklabels([f"{g}{'*' if g in flagged else ''}  ·  {a}" for g, a in zip(d.group, d.affiliation)],
                            fontsize=7.8, color=INK)
    axes[0].set_ylim(-0.7, n - 0.3)
    handles = [Line2D([], [], marker="o", ls="", color=c, markersize=6.5, label=s) for s, c in SECTOR_COLORS.items()
               if s in set(d.sector)]
    handles += [Line2D([], [], marker="o", ls="", color=INK_3, markersize=6, label="multispectral GSD"),
                Line2D([], [], marker="o", ls="", markerfacecolor=SURFACE, markeredgecolor=INK_3, markersize=6,
                       markeredgewidth=1.4, label="panchromatic GSD")]
    fig.legend(handles=handles, loc="upper right", ncol=4, fontsize=8, frameon=False, labelcolor=INK,
               bbox_to_anchor=(0.99, 1.0))
    fig.suptitle(title or "Key specs by constellation (sorted by multispectral GSD)", x=0.01, ha="left",
                 fontsize=13, color=INK, y=1.0)
    note = "– = not in the sheet" + ("   * values flagged for checking" if flagged else "")
    fig.text(0.01, 0.0, note, fontsize=7.5, color=INK_2)
    fig.subplots_adjust(left=0.25, right=0.99, top=1 - 0.75 / (row_height * n + 1.6), bottom=0.9 / (row_height * n + 1.6))
    return fig


def plot_footprints(groups: pd.DataFrame, max_swath_km: float = 100, title: Optional[str] = None, flagged=(),
                    ncols: int = 8, cell_in: float = 1.5):
    """Nominal image footprints at true scale: small multiples, one panel per
    constellation (smallest swath first), all panels on one km scale. Each
    footprint is a square of side = swath width (a nominal scene; pushbroom
    strips can be much longer). Groups with a wider swath than `max_swath_km`
    are listed instead. Returns fig."""
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle
    d = groups.dropna(subset=["swath_km"]).sort_values(["swath_km", "group"]).reset_index(drop=True)
    wide = d[d.swath_km > max_swath_km]
    d = d[d.swath_km <= max_swath_km].reset_index(drop=True)
    side = d.swath_km.max() * 1.08                      # panel extent (km), the same for every panel
    nrows = int(np.ceil(len(d) / ncols))
    fig, axes = plt.subplots(nrows, ncols, figsize=(ncols * cell_in, nrows * (cell_in + 0.42) + 0.9),
                             facecolor=SURFACE, squeeze=False)
    for ax in axes.ravel():
        ax.set_xlim(0, side); ax.set_ylim(0, side); ax.set_aspect("equal"); ax.axis("off")
    for ax, (_, r) in zip(axes.ravel(), d.iterrows()):
        c = SECTOR_COLORS.get(r.sector, INK_3)
        ax.add_patch(Rectangle((0, 0), side, side, facecolor="none", edgecolor=GRID, linewidth=0.8, clip_on=False))
        s_ = r.swath_km
        ax.add_patch(Rectangle(((side - s_) / 2, (side - s_) / 2), s_, s_, facecolor=c, alpha=0.85,
                               edgecolor=SURFACE, linewidth=0.6))
        name = r.group + ("*" if r.group in flagged else "")
        ax.set_title(f"{name}\n{s_:g} km", fontsize=7.6, color=INK, pad=3, linespacing=1.15)
    # scale bar in the last panel row's first empty panel, else under the grid
    spare = axes.ravel()[len(d):]
    bar = 10 if side < 60 else 20
    ax = spare[0] if len(spare) else axes.ravel()[-1]
    ax.plot([(side - bar) / 2, (side + bar) / 2], [side / 2] * 2, color=INK, lw=2)
    ax.text(side / 2, side / 2 + side * 0.06, f"{bar} km", ha="center", va="bottom", fontsize=8, color=INK)
    ax.text(side / 2, side / 2 - side * 0.08, f"panel = {side:.0f} km", ha="center", va="top", fontsize=7, color=INK_2)
    fig.suptitle(title or "Nominal image footprints at true scale (square of side = swath width)", x=0.01, ha="left",
                 fontsize=13, color=INK)
    notes = []
    if len(wide):
        notes.append(f"Wider than {max_swath_km:g} km, not drawn: " +
                     ", ".join(f"{g} ({s:g} km)" for g, s in zip(wide.group, wide.swath_km)))
    notes.append("Pushbroom strips can be much longer than wide; frame sensors take fixed frames. "
                 "Blue = commercial, orange = government" + ("; * values flagged for checking" if flagged else ""))
    fig.text(0.01, 0.005, "\n".join(notes), fontsize=7.5, color=INK_2, ha="left", va="bottom")
    fig.tight_layout(rect=(0, 0.05, 1, 0.97))
    return fig


def plot_completeness(df: pd.DataFrame, title: Optional[str] = None):
    """Which core fields (A-AS) are filled, one row per sensor, sheet order.
    Filled = dark blue, empty = light; column letters on top. Returns fig."""
    import matplotlib.pyplot as plt
    from matplotlib.colors import ListedColormap
    c = completeness(df)
    fig, ax = plt.subplots(figsize=(0.22 * c.shape[1] + 3.2, 0.16 * c.shape[0] + 1.6), facecolor=SURFACE)
    ax.imshow(c.to_numpy(dtype=float), aspect="auto", interpolation="nearest",
              cmap=ListedColormap(["#eef0f3", "#256abf"]), vmin=0, vmax=1)
    ax.set_yticks(range(c.shape[0]))
    ax.set_yticklabels(c.index, fontsize=6.5, color=INK)
    ax.set_xticks(range(c.shape[1]))
    ax.set_xticklabels([f"{column_letter(i)}  {f}" for i, f in enumerate(c.columns)], rotation=90, fontsize=6.5,
                       color=INK)
    ax.tick_params(length=0)
    ax.set_xticks(np.arange(-0.5, c.shape[1]), minor=True)
    ax.set_yticks(np.arange(-0.5, c.shape[0]), minor=True)
    ax.grid(which="minor", color=SURFACE, linewidth=0.8)
    for sp in ax.spines.values():
        sp.set_visible(False)
    pct = c.mean(axis=0) * 100
    ax2 = ax.secondary_xaxis("top")
    ax2.set_xticks(range(c.shape[1]))
    ax2.set_xticklabels([f"{p:.0f}" for p in pct], fontsize=6, color=INK_2)
    ax2.tick_params(length=0)
    for sp in ax2.spines.values():
        sp.set_visible(False)
    ax.set_title((title or f"Core fields filled (dark) or empty (light): {c.to_numpy().mean() * 100:.0f}% filled")
                 + "\nnumbers on top = % of sensors with the field filled", loc="left", fontsize=11, color=INK, pad=24)
    fig.tight_layout()
    return fig


# --------------------------------------------------------------------------
# Interactive HTML dashboard
# --------------------------------------------------------------------------

def _rows(spec: str) -> List[int]:
    """'31-36' -> [31..36]; '62-63, 4-7' -> [...]."""
    out = []
    for part in str(spec).split(","):
        part = part.strip()
        if not part:
            continue
        a, _, b = part.partition("-")
        out += list(range(int(a), int(b or a) + 1))
    return out


def affiliation_colors(owners) -> Dict[str, str]:
    """AFFILIATION_COLORS for the given owners; owners not in it take EXTRA_COLORS in turn."""
    out, extra = {}, iter(EXTRA_COLORS)
    for a in sorted(owners):
        out[a] = AFFILIATION_COLORS.get(a) or next(extra, "#999999")
    return out


def load_edits(path: str) -> pd.DataFrame:
    """Proposed edits from a public-source check (specs/public_check_*.csv)."""
    return pd.read_csv(path, dtype=str).fillna("")


def write_dashboard(raw: pd.DataFrame, groups: pd.DataFrame, issues: pd.DataFrame, edits: Optional[pd.DataFrame],
                    out_path: str, template: Optional[str] = None, edits_date: str = "",
                    footprint_max_km: float = 100, sheet_url: Optional[str] = None) -> str:
    """Write the interactive dashboard (one self-contained HTML file): scatter of GSD
    vs swath, aligned spec strips, footprints at true scale, completeness, checks,
    proposed edits and a table view, with hover details for every constellation.
    `groups`: constellations() output (all rows; the page filters by sector / status)."""
    import json
    from pathlib import Path
    template = template or str(Path(__file__).with_name("vendor_specs_dashboard.html"))
    edits = edits if edits is not None else pd.DataFrame(columns=["sheet_rows", "field", "current", "proposed"])
    changes = edits[edits["change"].astype(str) == "True"] if "change" in edits else edits
    edit_rows = [(set(_rows(e.sheet_rows)), e) for e in changes.itertuples()]
    num = lambda v: None if pd.isna(v) else float(v)
    out = []
    for g in groups.itertuples():
        rows = {int(r) for r in g.sheet_rows.split(", ")}
        qa = [f"{r.column} {r.field}: {r.check}" for r in issues.itertuples() if r.sheet_row in rows]
        ed = [dict(field=e.field, current=e.current, proposed=e.proposed) for rs, e in edit_rows if rs & rows]
        out.append(dict(
            group=g.group, affiliation=g.affiliation, sector=g.sector, constellation=g.constellation, sensors=g.sensors,
            status=g.status, current=bool(g.current),
            first_launch=None if pd.isna(g.first_launch) else g.first_launch.strftime("%Y-%m-%d"),
            n_satellites=num(g.n_satellites), pan_gsd=num(g.pan_gsd), ms_gsd=num(g.ms_gsd), swir_gsd=num(g.swir_gsd),
            tir_gsd=num(g.tir_gsd), swath_km=num(g.swath_km), ms_bands=num(g.ms_bands), total_bands=num(g.total_bands),
            revisit_days=num(g.revisit_days), ce90_m=num(g.ce90_m), scanner=g.scanner if pd.notna(g.scanner) else None,
            acquisition=g.acquisition if pd.notna(g.acquisition) else None, sheet_rows=g.sheet_rows,
            qa=qa, edits=ed, n_flags=len(qa) + len(ed)))
    # One row per sensor for the launch timeline (launch / end dates, orbit, size class)
    def orbit_class(v):
        v = str(v).lower() if pd.notna(v) else ""
        if "sun" in v:
            return "Sun-synchronous"
        if "mid" in v or "inclin" in v:
            return "Mid-inclination / inclined"
        if "polar" in v:
            return "Near-polar"
        return "Not in sheet"
    date = lambda v: None if pd.isna(pd.to_datetime(v, errors="coerce")) else pd.to_datetime(v).strftime("%Y-%m-%d")
    row_group = {int(r): g.group for g in groups.itertuples() for r in g.sheet_rows.split(", ")}
    sensors = []
    for _, r in raw.iterrows():
        launch = r["Launch Date"]
        if pd.notna(launch) and re.fullmatch(r"\d{4}", str(launch)):
            launch = f"{launch}-07-01"                       # year only: mid-year
        sensors.append(dict(
            label=r["label"], group=row_group.get(int(r["sheet_row"])), constellation=r["Constellation/Platform"],
            sensor=r["Sensor Name"],
            affiliation=r["Affiliation"], sector=r["Sector"], status=r["Mission Status"],
            current=bool(r["Mission Status"] in CURRENT_STATUS or pd.isna(r["Mission Status"])),
            launch=date(launch), end=date(r["End Date"]), altitude_km=num(to_number(r["Orbit Altitude (km)"])),
            orbit_type=orbit_class(r["Orbit Type"]), orbit_text=r["Orbit Type"] if pd.notna(r["Orbit Type"]) else None,
            size_class=r["Satellite Size Class"] if pd.notna(r["Satellite Size Class"]) else None,
            mass_kg=num(to_number(r["Weight Range (kg)"])), n_satellites=num(to_number(r["n satellites"])),
            sheet_row=int(r["sheet_row"])))
    comp = completeness(raw)
    qa_sum = (issues.groupby("check").agg(cells=("sheet_row", "size"), rows=("sheet_row", "nunique"),
                                          detail=("detail", "first"))
              .sort_values("cells", ascending=False).reset_index())
    payload = dict(
        asof=pd.Timestamp.today().strftime("%d %b %Y"), sheet_url=sheet_url or
        f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit?gid={GID['Vendor Specs']}",
        n_sensors=len(raw), pct_filled=float(comp.to_numpy().mean() * 100), n_issues=len(issues),
        groups=out, sensors=sensors, footprint_max_km=footprint_max_km, edits_date=edits_date,
        affiliation_colors=affiliation_colors(raw["Affiliation"].dropna().unique()),
        edits=edits.to_dict("records"),
        completeness=[dict(letter=column_letter(i), field=f, pct=float(comp[f].mean() * 100))
                      for i, f in enumerate(comp.columns)],
        qa_summary=qa_sum.to_dict("records"),
        footer=("Built by csda_summaries/notebooks/csda_specs_compare.ipynb (lib/vendor_specs.py). Constellation groups merge "
                "sensors of one data owner with the same GSD, swath and band count. Numbers are parsed from the sheet text "
                "(ranges -> first value). Band counts: Total Bands (MS) includes the pan band. Data-owner colors follow "
                "csda_specs_multispec_smry.ipynb (Set1 + Dark2); sector colors: commercial blue, government orange. "
                "Black ring = has a panchromatic band."))
    html = Path(template).read_text().replace("/*__DATA__*/null",
                                              json.dumps(payload, default=str).replace("</", "<\\/"))
    Path(out_path).write_text(html)
    return str(Path(out_path).resolve())
