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
    "Satlantis": "#96A713", "SatVu": "#D59D08", "US Agency": "#0000FF", "Vantor": "#00B8D9",
    "OrbitalSideKick": "#7570B3", "DLR": "#00441B",   # added (not in the sheet when the R palette was made)
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
    """Cross-track swath width (nominal image footprints at true scale): small multiples, one panel per
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
    fig.suptitle(title or "Cross-track swath width (square of side = swath width, true scale)", x=0.01, ha="left",
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
# Revisit: how often a constellation can image a site, by latitude
# --------------------------------------------------------------------------
# The sheet's 'Revisit Time' mixes definitions (vendor figures at full agility, single-satellite repeat cycles), so
# revisit is simulated from the orbit instead: circular orbit with J2 node drift, a year of 2-minute steps, sites on 36
# longitudes at each latitude. A pass counts when the site is within the satellite's reach (half the swath, plus the
# agility for pointable satellites), within the view-angle cap, and the sun is high enough. Revisit = 1 / (passes per day),
# averaged over longitudes, with the constellation's satellites spread evenly (passes add). It is the mean gap, not
# the longest; cloud, competing tasking and duty cycle are not included.

R_EARTH, MU_EARTH, J2, OMEGA_EARTH = 6378.137, 398600.4418, 1.08263e-3, 7.2921159e-5
REVISIT_LATS = (0, 40, 60)
SEASONS = {"year": (1, 365), "jja": (152, 243)}          # day-of-year ranges: whole year, June-August
# Inclination is not in the sheet (an 'Inclination (deg)' column would be used first). Sun-synchronous rows get it from
# the altitude; these rows need it given.
ORBIT_INCLINATION = {
    ("Legion", "LG-3"): (45.0, "Maxar: mid-inclination orbit, 45°, 4 planes (Legion 3-6)"),
    ("Legion", "LG-4"): (45.0, "Maxar: mid-inclination orbit, 45°, 4 planes (Legion 3-6)"),
    ("Legion", "LG-5"): (45.0, "Maxar: mid-inclination orbit, 45°, 4 planes (Legion 3-6)"),
    ("Legion", "LG-6"): (45.0, "Maxar: mid-inclination orbit, 45°, 4 planes (Legion 3-6)"),
    ("ImageSat", "EROS-C3"): (139.3, "tracking data (NORAD 54880): retrograde, 139.3°"),
    ("ISS", "DESIS"): (51.6, "ISS orbit"),
}


def sso_inclination(alt_km: float) -> float:
    """Inclination (deg) that makes a circular orbit at this altitude sun-synchronous."""
    a = R_EARTH + alt_km
    n = np.sqrt(MU_EARTH / a ** 3)
    rate = 2 * np.pi / (365.2422 * 86400)
    return float(np.degrees(np.arccos(-rate / (1.5 * n * J2 * (R_EARTH / a) ** 2))))


def _off_nadir(alt_km: float, central_deg):
    """Off-nadir angle (deg) from the satellite to a ground point `central_deg` (Earth central angle) from nadir."""
    d = np.radians(central_deg)
    return np.degrees(np.arctan2(np.sin(d), (R_EARTH + alt_km) / R_EARTH - np.cos(d)))


def half_swath_angle(alt_km: float, swath_km: float) -> float:
    """Off-nadir angle (deg) of the swath edge, looking straight down."""
    return float(_off_nadir(alt_km, np.degrees(swath_km / 2 / R_EARTH)))


_PASS_CACHE: Dict[tuple, dict] = {}


def orbit_passes(alt_km: float, incl_deg: float, sso: bool, lats=REVISIT_LATS, n_lon: int = 36, days: int = 365,
                 step_s: float = 120, ltdn_h: float = 10.5, start: str = "2026-01-01") -> dict:
    """Every pass of one satellite over sites at `lats` x `n_lon` longitudes for `days` days: arrays lat (index into
    lats), day (day of year, 1 = start), off_nadir (deg, at closest approach) and sun (sun elevation at the site, deg).
    Sun-synchronous orbits cross the equator southbound at `ltdn_h` local time. Cached."""
    key = (round(alt_km, 1), round(incl_deg, 2), sso, tuple(lats), n_lon, days, step_s, ltdn_h, start)
    if key in _PASS_CACHE:
        return _PASS_CACHE[key]
    a = R_EARTH + alt_km
    i = np.radians(incl_deg)
    n = np.sqrt(MU_EARTH / a ** 3)
    t = np.arange(0, days * 86400, step_s)
    d0 = (pd.Timestamp(start) - pd.Timestamp("2000-01-01 12:00")).total_seconds() / 86400   # days since J2000

    def sun(d):                                     # low-precision solar ecliptic longitude, obliquity (rad)
        g = np.radians(357.528 + 0.9856003 * d)
        lam = np.radians(280.460 + 0.9856474 * d) + np.radians(1.915) * np.sin(g) + np.radians(0.020) * np.sin(2 * g)
        return lam, np.radians(23.439 - 4e-7 * d)

    lam0, eps0 = sun(d0)
    ra0 = np.arctan2(np.cos(eps0) * np.sin(lam0), np.cos(lam0))
    node_rate = -1.5 * n * J2 * (R_EARTH / a) ** 2 * np.cos(i)
    raan = (ra0 + np.radians((ltdn_h + 12 - 12) * 15) if sso else 0.0) + node_rate * t
    u = n * t                                       # argument of latitude
    gmst = np.radians(280.46061837 + 360.98564736629 * d0) + OMEGA_EARTH * t
    horizon = np.arccos(R_EARTH / a)
    out = {k: [] for k in ("lat", "day", "off_nadir", "sun")}
    for li, lat in enumerate(lats):
        cp, sp = np.cos(np.radians(lat)), np.sin(np.radians(lat))
        for lon in np.linspace(0, 2 * np.pi, n_lon, endpoint=False):
            psi = lon + gmst - raan                 # site angle from the ascending node, in the equatorial plane
            x, y = cp * np.cos(psi), np.cos(i) * cp * np.sin(psi) + sp * np.sin(i)
            cross = np.arcsin(np.clip(-np.sin(i) * cp * np.sin(psi) + sp * np.cos(i), -1, 1))   # angle off the orbit plane
            dl = np.angle(np.exp(1j * (u - np.arctan2(y, x))))                                    # along-track, (-pi, pi]
            k = np.flatnonzero((dl[:-1] < 0) & (dl[1:] >= 0) & (dl[:-1] > -0.5))
            f = dl[k] / (dl[k] - dl[k + 1])
            c = np.abs(cross[k] + f * (cross[k + 1] - cross[k]))
            tk = t[k] + f * step_s
            ok = c < horizon
            c, tk = c[ok], tk[ok]
            ang = lon + np.radians(280.46061837 + 360.98564736629 * d0) + OMEGA_EARTH * tk
            lam, eps = sun(d0 + tk / 86400)
            s = np.stack([np.cos(lam), np.cos(eps) * np.sin(lam), np.sin(eps) * np.sin(lam)])
            p = np.stack([cp * np.cos(ang), cp * np.sin(ang), np.full_like(ang, sp)])
            out["lat"].append(np.full(len(tk), li))
            out["day"].append(tk / 86400 + 1)
            out["off_nadir"].append(_off_nadir(alt_km, np.degrees(c)))
            out["sun"].append(np.degrees(np.arcsin(np.clip((s * p).sum(0), -1, 1))))
    res = {k: np.concatenate(v) for k, v in out.items()}
    res.update(lats=tuple(lats), n_lon=n_lon, days=days)
    _PASS_CACHE[key] = res
    return res


def orbit_inputs(df: pd.DataFrame, inclination: Optional[dict] = None) -> pd.DataFrame:
    """Per sheet row, the orbit and pointing used for revisit: altitude, inclination (+ source), whether
    sun-synchronous, satellites, swath, reach (deg off-nadir: half swath + agility; NaN = agility not in the sheet
    for a tasked satellite), whether it maps systematically, and notes on what was assumed."""
    inclination = {**ORBIT_INCLINATION, **(inclination or {})}
    rows = []
    for _, r in df.iterrows():
        notes = []
        alt, swath = to_number(r["Orbit Altitude (km)"]), to_number(r["Swath Width (km)"])
        otype = str(r["Orbit Type"]).lower() if pd.notna(r["Orbit Type"]) else ""
        given = to_number(r["Inclination (deg)"]) if "Inclination (deg)" in df.columns else np.nan
        key = (str(r["Constellation/Platform"]).strip(), str(r["Sensor Name"]).strip())
        sso, incl, src = False, np.nan, ""
        if not np.isnan(given):
            incl, src = given, "sheet"
            sso = "sun" in otype
        elif key in inclination:
            incl, src = inclination[key]
        elif ("sun" in otype or "polar" in otype) and not np.isnan(alt):
            sso, incl, src = True, sso_inclination(alt), "sun-synchronous, from the altitude"
            if "sun" not in otype:
                notes.append(f"'{r['Orbit Type']}' treated as sun-synchronous")
        nsat = to_number(r["n satellites"])
        if np.isnan(nsat):
            nsat = 1.0
            notes.append("number of satellites not in the sheet: 1 assumed")
        ag = r["Agility (off-nadir, ± degrees )"]
        agility = 0.0 if str(ag).strip().lower() == "limited" else to_number(ag)
        half = half_swath_angle(alt, swath) if not (np.isnan(alt) or np.isnan(swath)) else np.nan
        if np.isnan(agility) and str(r["Acquisition Strategy"]).strip() == "Systematic" and swath >= 100:
            agility = 0.0
            notes.append("no agility in the sheet; wide-swath systematic mapper, so nadir-looking assumed")
        missing = [k for k, v in (("altitude", alt), ("swath", swath), ("inclination", incl)) if np.isnan(v)]
        rows.append(dict(sheet_row=r["sheet_row"], label=r["label"], current=r["Mission Status"] in CURRENT_STATUS,
                         alt_km=alt, incl_deg=incl, incl_source=src, sso=sso, n_sat=nsat, swath_km=swath,
                         half_swath_deg=half, agility_deg=agility, reach_deg=half + agility,
                         systematic=str(r["Acquisition Strategy"]).strip() == "Systematic",
                         missing=", ".join(missing), notes="; ".join(notes)))
    return pd.DataFrame(rows)


def revisit(df: pd.DataFrame, groups: pd.DataFrame, cap_deg: float = 20, sun_min_deg: float = 10,
            lats=REVISIT_LATS, inclination: Optional[dict] = None, **sim):
    """Mean revisit (days) per constellation group at each latitude, for two views ('cap' = view angle <= cap_deg,
    'max' = full agility) and two seasons ('year', 'jja'), counting passes with the sun >= sun_min_deg.
    Uses a group's current rows if it has any, else all its rows. A tasked satellite with no agility in the sheet
    is assumed able to point to cap_deg (so it appears in the 'cap' view only). A systematic imager collects its whole
    swath on every pass, so the full swath counts in both views, even past cap_deg (MODIS). Returns (table, inputs):
    table has one row per group x view x season x latitude (revisit_days NaN = no access; `why` = not computed)."""
    inp = orbit_inputs(df, inclination)
    out = []
    for g in groups.itertuples():
        rows = inp[inp.sheet_row.isin(int(x) for x in g.sheet_rows.split(", "))]
        if rows.current.any():
            rows = rows[rows.current]
        for view in ("cap", "max"):
            why, rates = "", []
            for r in rows.itertuples():
                if r.missing:
                    why = f"{r.label}: {r.missing} not in the sheet"
                    break
                reach = r.reach_deg
                if np.isnan(reach):
                    if view == "max":
                        why = f"{r.label}: agility not in the sheet"
                        break
                    reach = cap_deg                              # assumed able to point to the cap
                limit = min(reach, cap_deg) if view == "cap" else reach
                if r.systematic:
                    limit = max(limit, r.half_swath_deg)
                p = orbit_passes(r.alt_km, r.incl_deg, r.sso, lats=lats, **sim)
                ok = (p["off_nadir"] <= limit) & (p["sun"] >= sun_min_deg)
                rates.append((r.n_sat, ok, p))
            for season, (d0, d1) in SEASONS.items():
                for li, lat in enumerate(lats):
                    if why:
                        days = np.nan
                    else:
                        per_day = 0.0
                        for nsat, ok, p in rates:
                            sel = ok & (p["lat"] == li) & (p["day"] >= d0) & (p["day"] < d1 + 1)
                            per_day += nsat * sel.sum() / (p["n_lon"] * (d1 - d0 + 1))
                        days = 1 / per_day if per_day > 0 else np.inf
                    out.append(dict(group=g.group, view=view, season=season, lat=lat, revisit_days=days, why=why))
    table = pd.DataFrame(out)
    table.attrs.update(cap_deg=cap_deg, sun_min_deg=sun_min_deg, lats=list(lats))
    return table, inp


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


# Edit record: one row per sheet cell, kept in the repo (specs/edits_log.csv). New batches are appended;
# rows are never rewritten, so the file is the full history of what was changed, from what, and why. Exception:
# an edit the sheet cannot take (e.g. rejected by data validation) is withdrawn: removed here and marked
# change = False, with the reason, in its batch CSV; its edit_id is not reused.
EDIT_LOG_COLUMNS = ["edit_id", "date", "batch", "cell", "sheet_row", "label", "column", "field", "before", "after",
                    "source", "source_url", "note"]
EMPTY = "(empty)"


def _cell_text(v) -> str:
    return EMPTY if v is None or (isinstance(v, float) and np.isnan(v)) or str(v).strip() == "" else str(v).strip()


def load_edit_log(path: str) -> pd.DataFrame:
    """The edit record (empty frame with the log columns if the file does not exist yet)."""
    from pathlib import Path
    if not Path(path).exists():
        return pd.DataFrame(columns=EDIT_LOG_COLUMNS)
    return pd.read_csv(path, dtype=str).fillna("")


def record_edits(raw: pd.DataFrame, edits: pd.DataFrame, log_path: str, batch: str, date: str) -> pd.DataFrame:
    """Add a batch of proposed edits (public_check_*.csv: one row per field and row span) to the edit record as
    one row per sheet cell, with the cell address and the sheet value it replaces. Rows with change != True are
    left out. A batch already in the record is not added again. Rows below the last sheet row are new rows (every
    cell empty before; label from their proposed Constellation/Platform and Sensor Name). Returns the full record."""
    log = load_edit_log(log_path)
    if batch in set(log["batch"]):
        return log
    cols = list(raw.columns[2:])                     # sheet columns (after sheet_row, label)
    start = int(pd.to_numeric(log["edit_id"]).max()) if len(log) else 0
    edits = edits[edits["change"].astype(str) == "True"] if "change" in edits else edits
    last = max([int(raw.sheet_row.max())] + pd.to_numeric(log["sheet_row"]).astype(int).tolist())   # incl. rows the record added
    added = {}                                        # new sheet row -> {field: proposed}
    for e in edits.itertuples():
        for row in _rows(e.sheet_rows):
            if row > last:
                added.setdefault(row, {})[e.field] = str(e.proposed).strip()
    if added and sorted(added) != list(range(last + 1, last + 1 + len(added))):
        raise ValueError(f"new rows must follow the last sheet row ({last}) without gaps: {sorted(added)}")
    labels = {row: f"{f.get('Constellation/Platform', '')} {f.get('Sensor Name', '')}".strip() for row, f in added.items()}
    new = []
    for e in edits.itertuples():
        letter = column_letter(cols.index(e.field))
        if e.column and e.column != letter:
            raise ValueError(f"{e.field}: column {e.column} in the edits, {letter} in the sheet")
        for row in _rows(e.sheet_rows):
            if row > last:
                label, before = labels[row], EMPTY
            else:
                r = raw.loc[raw.sheet_row == row].iloc[0]
                label, before = r["label"], _cell_text(r[e.field])
            new.append(dict(edit_id=start + len(new) + 1, date=date, batch=batch, cell=f"{letter}{row}", sheet_row=row,
                            label=label, column=letter, field=e.field, before=before,
                            after=_cell_text(e.proposed), source=e.source, source_url=e.source_url, note=e.note))
    log = pd.concat([log, pd.DataFrame(new, columns=EDIT_LOG_COLUMNS).astype(str)], ignore_index=True)
    log.to_csv(log_path, index=False)
    return log


def _same(a: str, b: str) -> bool:
    """Same cell text, or the same plain number written differently ('0.50' and '0.5': the sheet drops zeros)."""
    if a == b:
        return True
    num = r"\d+(\.\d+)?"
    return bool(re.fullmatch(num, a) and re.fullmatch(num, b)) and float(a) == float(b)


def apply_edits(raw: pd.DataFrame, log: pd.DataFrame):
    """Apply the edit record to the sheet as read now. Per cell, `status`:
    'in sheet' = the sheet already holds the new value; 'applied (not yet in sheet)' = the sheet still holds the
    old value, so the new one is used here; 'skipped: sheet changed' = the sheet holds a third value (edited since
    the record was made): the sheet wins. Later edits of the same cell win over earlier ones.
    Rows the record adds that the sheet does not have yet are added (empty) before the edits are applied.
    Returns (edited copy of raw, log with `now` = sheet value and `status`)."""
    raw = raw.copy()
    rows = pd.to_numeric(log["sheet_row"]).astype(int) if len(log) else pd.Series(dtype=int)
    for row in sorted(set(rows) - set(raw.sheet_row)):
        raw.loc[len(raw)] = {"sheet_row": row, "label": log.loc[rows == row, "label"].iloc[0]}
    raw = raw.reset_index(drop=True)
    out = raw.copy()
    log = log.copy()
    now, status = [], []
    for e in log.itertuples():
        i = out.index[out.sheet_row == int(e.sheet_row)][0]
        v = _cell_text(raw.at[i, e.field])
        now.append(v)
        if _same(v, e.after):
            status.append("in sheet")
        elif _same(_cell_text(out.at[i, e.field]), e.before):  # out: earlier edits of the cell already applied
            out.at[i, e.field] = np.nan if e.after == EMPTY else e.after
            status.append("applied (not yet in sheet)")
        else:
            status.append("skipped: sheet changed")
    log["now"], log["status"] = now, status
    return out, log


APPS_SCRIPT = r"""/**
 * Apply recorded edits to the CSDA Vendor Specs sheet: __N__ cells (__BATCHES__), __TODO__ not yet in the sheet.
 * Written by csda_summaries lib/vendor_specs.py (apps_script) from specs/edits_log.csv on __DATE__.
 *
 * Use: open the spreadsheet > Extensions > Apps Script, paste this file, save.
 *   1. Run previewEdits: changes nothing; the log (View > Logs / Execution log) lists what would change.
 *   2. Run applyEdits: writes the cells and adds one row per edit to the tab 'Edit log' (result 'written', or
 *      'already in sheet' for an edit made earlier that the tab does not list yet).
 * A cell is written only if the column header matches the field and the cell still shows the 'before' value
 * (a cell edited since the record was made is skipped and listed). A cell the sheet rejects (e.g. data
 * validation) is skipped and listed; the run goes on. Running applyEdits again writes nothing new and adds no
 * duplicate rows to 'Edit log'.
 */
const SHEET_ID = '__SHEET_ID__';
const TAB_GID = __GID__;
const LOG_TAB = 'Edit log';
const EMPTY = '(empty)';
const EDITS = __EDITS__;

function previewEdits() { run_(false); }
function applyEdits() { run_(true); }

function same_(a, b) {
  if (a === b) return true;
  const num = /^\d+(\.\d+)?$/;
  return num.test(a) && num.test(b) && Number(a) === Number(b);
}

function run_(write) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  if (ss.getId() !== SHEET_ID) throw new Error('Wrong spreadsheet: run this from the CSDA Vendor Specs sheet.');
  const sh = ss.getSheets().find(s => s.getSheetId() === TAB_GID);
  if (!sh) throw new Error('Vendor Specs tab (gid ' + TAB_GID + ') not found.');
  const counts = {written: 0, 'already new value': 0, 'skipped: header differs': 0, 'skipped: cell changed': 0,
                  'skipped: sheet rejected': 0};
  const logRows = [], stamp = Utilities.formatDate(new Date(), Session.getScriptTimeZone(), 'yyyy-MM-dd HH:mm');
  let lg = ss.getSheetByName(LOG_TAB);
  const logged = new Set();                    // batch|edit_id already in the 'Edit log' tab
  if (lg && lg.getLastRow() > 1)
    lg.getRange(2, 3, lg.getLastRow() - 1, 2).getDisplayValues().forEach(r => logged.add(r[1] + '|' + r[0]));
  const row = (result, e) => [stamp, result, e.edit_id, e.batch, e.cell, e.label, e.field, e.before, e.after,
                              e.source, e.source_url, e.note];
  for (const e of EDITS) {
    const rng = sh.getRange(e.cell);
    const header = String(sh.getRange(1, rng.getColumn()).getDisplayValue()).trim();
    const now = String(rng.getDisplayValue()).trim() || EMPTY;
    let result;
    if (header !== e.field.trim()) result = 'skipped: header differs';
    else if (same_(now, e.after)) result = 'already new value';
    else if (!same_(now, e.before)) result = 'skipped: cell changed';
    else {
      result = 'written';
      if (write) {
        try {
          if (e.after === EMPTY) rng.clearContent();
          else {
            if (/^\d+(\.\d+)?-\d+(\.\d+)?$/.test(e.after)) rng.setNumberFormat('@');   // a range ('1-2'), not a date
            rng.setValue(e.after);
            if (/^\d{4}-\d{2}-\d{2}$/.test(e.after)) rng.setNumberFormat('yyyy-mm-dd');
          }
          SpreadsheetApp.flush();              // surface a validation error on this cell, not a later one
        } catch (err) {
          result = 'skipped: sheet rejected';
          Logger.log(['skipped: sheet rejected', e.cell, e.label, e.field, 'after: ' + e.after, String(err.message || err)].join(' | '));
        }
      }
    }
    counts[result]++;
    if (write && !logged.has(e.batch + '|' + e.edit_id)) {
      if (result === 'written') logRows.push(row('written', e));
      else if (result === 'already new value') logRows.push(row('already in sheet', e));
    }
    if (result !== 'written' && result !== 'already new value' && result !== 'skipped: sheet rejected' || !write && result === 'written')
      Logger.log([write ? result : 'would write', e.cell, e.label, e.field,
                  'now: ' + now, 'before: ' + e.before, 'after: ' + e.after].join(' | '));
  }
  if (write && logRows.length) {
    if (!lg) {
      lg = ss.insertSheet(LOG_TAB);
      lg.appendRow(['logged', 'result', 'edit_id', 'batch', 'cell', 'sensor', 'field', 'before', 'after', 'source',
                    'source_url', 'note']);
      lg.setFrozenRows(1);
    }
    lg.getRange(lg.getLastRow() + 1, 1, logRows.length, logRows[0].length).setNumberFormat('@').setValues(logRows);
  }
  Logger.log((write ? 'Applied: ' : 'Preview: ') + JSON.stringify(counts));
}
"""


def apps_script(log: pd.DataFrame, out_path: str) -> str:
    """Write a Google Apps Script for the edit record (apply_edits() log, rows not skipped): it writes the edits
    not yet in the sheet and lists every edit in the sheet's 'Edit log' tab once; see the header of APPS_SCRIPT.
    Returns the path."""
    import json
    from pathlib import Path
    todo = log[~log["status"].str.startswith("skipped")]
    keys = ["edit_id", "batch", "cell", "label", "field", "before", "after", "source", "source_url", "note"]
    rows = ",\n  ".join(json.dumps({k: str(r[k]) for k in keys}, ensure_ascii=False) for _, r in todo.iterrows())
    js = (APPS_SCRIPT.replace("__N__", str(len(todo)))
          .replace("__TODO__", str((todo["status"] == "applied (not yet in sheet)").sum())).replace("__BATCHES__", ", ".join(sorted(set(todo["batch"]))))
          .replace("__DATE__", pd.Timestamp.today().strftime("%Y-%m-%d")).replace("__SHEET_ID__", SHEET_ID)
          .replace("__GID__", str(GID["Vendor Specs"])).replace("__EDITS__", "[\n  " + rows + "\n]"))
    Path(out_path).write_text(js)
    return str(Path(out_path).resolve())


def revisit_header(lat: int, view: str, cap_deg: float = 20) -> str:
    """Sheet column name for one revisit estimate, e.g. 'Revisit est. 40°N (days, ≤20° view)'."""
    where = "0°" if lat == 0 else f"{lat}°N"
    return f"Revisit est. {where} (days, " + (f"≤{cap_deg:g}° view)" if view == "cap" else "full agility)")


REVISIT_NOTE_HEADER = "Revisit est. notes"


def revisit_sheet_columns(revisit, groups: pd.DataFrame, df: pd.DataFrame, date: str) -> pd.DataFrame:
    """The revisit estimates as sheet columns, one row per sheet row: whole-year constellation mean (days) at each
    latitude for both views, and a note. A group's value goes on the rows it was computed from (its current
    satellites, or all rows of a group with none current); other rows get only a note. 'no access' = the orbit
    never reaches that latitude; empty = not computed (reason in the note)."""
    table, inp = revisit
    cap, sun, lats = table.attrs["cap_deg"], table.attrs["sun_min_deg"], table.attrs["lats"]
    year = table[table.season == "year"]
    heads = [(lat, view, revisit_header(lat, view, cap)) for view in ("cap", "max") for lat in lats]
    base = (f"Simulated {date} (csda_summaries csda_specs_compare.ipynb §6): mean revisit of the constellation's "
            f"current satellites, whole year, sun ≥ {sun:g}°")
    by_row = {}
    for g in groups.itertuples():
        rows = inp[inp.sheet_row.isin(int(x) for x in g.sheet_rows.split(", "))]
        used = rows[rows.current] if rows.current.any() else rows
        t = year[year.group == g.group]
        for r in rows.itertuples():
            rec = {h: "" for _, _, h in heads}
            if r.sheet_row in set(used.sheet_row):
                notes = [base + f" ({g.group}: {', '.join(used.label)})"]
                for lat, view, h in heads:
                    v = t[(t.view == view) & (t.lat == lat)].revisit_days.iloc[0]
                    rec[h] = "" if np.isnan(v) else ("no access" if np.isinf(v) else round(float(v), 2))
                why = t[t.why != ""].drop_duplicates("view")
                notes += [f"{'≤' + format(cap, 'g') + '° view' if w.view == 'cap' else 'full agility'} not computed: "
                          f"{w.why.split(': ', 1)[-1]}" for w in why.itertuples()]
                notes += [n for n in used.notes.unique() if n]
                if (used.systematic & (used.half_swath_deg > cap)).any():
                    notes.append(f"systematic imager: full swath counted in the ≤{cap:g}° view too")
                if r.incl_source and not r.sso:
                    notes.append(f"inclination {r.incl_deg:g}° ({r.incl_source})")
            else:
                status = df.loc[df.sheet_row == r.sheet_row, "Mission Status"].iloc[0]
                notes = [f"Not estimated: status {status}; the {g.group} estimate covers current satellites only"]
            rec[REVISIT_NOTE_HEADER] = "; ".join(notes)
            by_row[r.sheet_row] = rec
    out = df[["sheet_row", "Constellation/Platform", "Sensor Name"]].copy()
    recs = pd.DataFrame.from_dict(by_row, orient="index")
    return out.join(recs, on="sheet_row").fillna("")


REVISIT_SCRIPT = r"""/**
 * Write the simulated revisit estimates into the CSDA Vendor Specs sheet: __NCOL__ columns x __NROW__ rows.
 * Written by csda_summaries lib/vendor_specs.py (revisit_apps_script) on __DATE__ (record: specs/revisit_estimates.csv).
 *
 * Use: open the spreadsheet > Extensions > Apps Script, paste this file, save.
 *   1. Run previewRevisit: changes nothing; the log lists the columns and how many cells would change.
 *   2. Run writeRevisit: writes the cells and adds one row per column to the tab 'Edit log'.
 * Columns are found by header; a missing one is added after the last header in row 1 (only into empty columns).
 * Each value goes to the row whose Sensor Name and Constellation/Platform match (found again if rows moved; a row
 * not found is skipped and listed). Rows not in this file are left as they are. Running it again changes nothing.
 */
const SHEET_ID = '__SHEET_ID__';
const TAB_GID = __GID__;
const LOG_TAB = 'Edit log';
const BATCH = '__BATCH__';
const HEADERS = __HEADERS__;
const ROWS = __ROWS__;

function previewRevisit() { run_(false); }
function writeRevisit() { run_(true); }

function run_(write) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  if (ss.getId() !== SHEET_ID) throw new Error('Wrong spreadsheet: run this from the CSDA Vendor Specs sheet.');
  const sh = ss.getSheets().find(s => s.getSheetId() === TAB_GID);
  if (!sh) throw new Error('Vendor Specs tab (gid ' + TAB_GID + ') not found.');
  const nRows = sh.getLastRow();
  const head = sh.getRange(1, 1, 1, sh.getMaxColumns()).getDisplayValues()[0].map(h => String(h).trim());
  const names = sh.getRange(1, 1, nRows, 2).getDisplayValues().map(r => [String(r[0]).trim(), String(r[1]).trim()]);
  const iSensor = head.indexOf('Sensor Name'), iCon = head.indexOf('Constellation/Platform');
  if (iSensor !== 0 || iCon !== 1) throw new Error('Expected Sensor Name in A and Constellation/Platform in B.');
  // rows: at the recorded row if the names match, else the one row with the same names
  const target = [], missing = [];
  for (const r of ROWS) {
    const at = names[r.sheet_row - 1];
    let row = at && at[0] === r.sensor && at[1] === r.constellation ? r.sheet_row : 0;
    if (!row) {
      const hits = names.map((n, i) => n[0] === r.sensor && n[1] === r.constellation ? i + 1 : 0).filter(i => i > 1);
      row = hits.length === 1 ? hits[0] : 0;
    }
    if (row) target.push([row, r]); else missing.push(r.constellation + ' ' + r.sensor);
  }
  // columns: existing by header, else appended after the last header (must be empty)
  let last = head.reduce((m, h, i) => h ? i + 1 : m, 0);
  const cols = [];
  for (const h of HEADERS) {
    let c = head.indexOf(h) + 1, added = false;
    if (!c) {
      c = ++last; added = true;
      if (c <= sh.getMaxColumns()) {
        const used = sh.getRange(1, c, Math.max(nRows, 1), 1).getDisplayValues().some(v => String(v[0]).trim());
        if (used) throw new Error('Column ' + c + ' (for "' + h + '") is not empty; nothing written.');
      }
    }
    cols.push([h, c, added]);
  }
  if (write && last > sh.getMaxColumns()) sh.insertColumnsAfter(sh.getMaxColumns(), last - sh.getMaxColumns());
  const stamp = Utilities.formatDate(new Date(), Session.getScriptTimeZone(), 'yyyy-MM-dd HH:mm');
  const logRows = [];
  for (const [h, c, added] of cols) {
    const letter = added && c > sh.getMaxColumns() ? '(new)' :
      sh.getRange(1, c).getA1Notation().replace(/\d+$/, '');
    let changed = 0;
    let vals = c <= sh.getMaxColumns() ? sh.getRange(1, c, nRows, 1).getValues() : names.map(() => ['']);
    for (const [row, r] of target) {
      const v = r[h];
      if (String(vals[row - 1][0]) !== String(v)) { vals[row - 1][0] = v; changed++; }
    }
    Logger.log([write ? 'write' : 'would write', 'column ' + letter + (added ? ' (new)' : ''), h, changed + ' cells change'].join(' | '));
    if (write) {
      vals[0][0] = h;
      const rng = sh.getRange(1, c, nRows, 1);
      rng.setValues(vals);
      if (h !== '__NOTE__') sh.getRange(2, c, nRows - 1, 1).setNumberFormat('0.00');
      if (added) sh.getRange(1, c).setFontWeight('bold');
      if (changed) logRows.push([stamp, 'written', h, BATCH, letter + '2:' + letter + nRows, '(all rows)', h, '',
                                 changed + ' cells', 'computed', '', 'Simulated revisit (csda_specs_compare.ipynb §6)']);
    }
  }
  if (missing.length) Logger.log('Rows not found (skipped): ' + missing.join(', '));
  if (write && logRows.length) {
    let lg = ss.getSheetByName(LOG_TAB);
    if (!lg) {
      lg = ss.insertSheet(LOG_TAB);
      lg.appendRow(['logged', 'result', 'edit_id', 'batch', 'cell', 'sensor', 'field', 'before', 'after', 'source',
                    'source_url', 'note']);
      lg.setFrozenRows(1);
    }
    lg.getRange(lg.getLastRow() + 1, 1, logRows.length, logRows[0].length).setNumberFormat('@').setValues(logRows);
  }
  Logger.log((write ? 'Written: ' : 'Preview: ') + target.length + ' rows matched, ' + missing.length + ' not found');
}
"""


def revisit_apps_script(cols: pd.DataFrame, out_path: str, batch: str) -> str:
    """Write a Google Apps Script that puts revisit_sheet_columns() into the sheet (see the header of
    REVISIT_SCRIPT). Returns the path."""
    import json
    from pathlib import Path
    heads = [c for c in cols.columns if c.startswith("Revisit est.")]
    rows = ",\n  ".join(json.dumps(dict(sheet_row=int(r.sheet_row), constellation=str(r["Constellation/Platform"]).strip(),
                                        sensor=str(r["Sensor Name"]).strip(), **{h: r[h] for h in heads}),
                                   ensure_ascii=False) for _, r in cols.iterrows())
    js = (REVISIT_SCRIPT.replace("__NCOL__", str(len(heads))).replace("__NROW__", str(len(cols)))
          .replace("__DATE__", pd.Timestamp.today().strftime("%Y-%m-%d")).replace("__SHEET_ID__", SHEET_ID)
          .replace("__GID__", str(GID["Vendor Specs"])).replace("__BATCH__", batch)
          .replace("__NOTE__", REVISIT_NOTE_HEADER)
          .replace("__HEADERS__", json.dumps(heads, ensure_ascii=False)).replace("__ROWS__", "[\n  " + rows + "\n]"))
    Path(out_path).write_text(js)
    return str(Path(out_path).resolve())


def _revisit_payload(revisit, g) -> Optional[dict]:
    """One group's revisit for the page: days[view][season] = [one value per latitude] (None = not computed,
    -1 = no access), why[view] = reason not computed, and the inputs per sheet row."""
    if revisit is None:
        return None
    table, inp = revisit
    t = table[table.group == g.group]
    days, why = {}, {}
    for (view, season), d in t.groupby(["view", "season"]):
        d = d.sort_values("lat")
        days.setdefault(view, {})[season] = [None if np.isnan(v) else (-1 if np.isinf(v) else round(float(v), 3))
                                             for v in d.revisit_days]
        why[view] = d.why.iloc[0]
    rows = inp[inp.sheet_row.isin(int(x) for x in g.sheet_rows.split(", "))]
    if rows.current.any():
        rows = rows[rows.current]
    num = lambda v: None if pd.isna(v) else round(float(v), 2)
    inputs = [dict(label=r.label, alt_km=num(r.alt_km), incl_deg=num(r.incl_deg), incl_source=r.incl_source,
                   n_sat=num(r.n_sat), half_swath_deg=num(r.half_swath_deg), agility_deg=num(r.agility_deg),
                   notes=r.notes) for r in rows.itertuples()]
    return dict(days=days, why=why, inputs=inputs)


def eval_sites(path: Optional[str] = None) -> List[dict]:
    """Evaluation site names, points and AOIs for the dashboard's footprint map, from the sites database export.
    Each AOI is simplified to 1% of its extent and rounded to 5 decimals, to keep the page small."""
    import json
    from pathlib import Path
    import shapely
    from shapely.geometry import mapping, shape

    def aoi(geometry):
        g = shape(geometry)
        x0, y0, x1, y1 = g.bounds
        return mapping(shapely.transform(g.simplify(0.01 * max(x1 - x0, y1 - y0)), lambda c: np.round(c, 5)))

    path = path or Path(__file__).resolve().parents[1] / "sites" / "eval_sites_aoi.geojson"
    out = []
    for f in json.loads(Path(path).read_text())["features"]:
        p = f["properties"]
        out.append(dict(name=p["Site Name"], lat=float(p["Latitude"]), lon=float(p["Longitude"]), aoi=aoi(f["geometry"]),
                        place=" · ".join(str(p[k]) for k in ("Location Name", "Country", "Program Use") if p.get(k))))
    return sorted(out, key=lambda x: x["name"].lower())


RSR_CSV = "/explore/nobackup/projects/CSDA_eval/results/csda_rsr_curve_data.csv"
RSR_OWNER = {"Maxar": "Vantor", "Planet": "Planet Labs", "NASA/USGS": "US Agency"}   # as named on the dashboard
RSR_CONSTELLATION = {"Sentinel": "Sentinel-2"}
RSR_GROUPS = {   # dashboard constellation groups each RSR panel belongs to, so the dashboard's filters apply to it
    "Sentinel-2": ["Sentinel-2"], "Landsat": ["Landsat 8/9"], "Pleiades": ["Pléiades"], "PleiadesNeo": ["Pléiades Neo"],
    "SPOT": ["SPOT-6/7"], "Global": ["BlackSky Gen 1", "BlackSky Gen 2", "BlackSky Gen 3"],
    "Dove-Classic": ["PlanetScope Dove-Classic/Dove-R"], "Dove-R": ["PlanetScope Dove-Classic/Dove-R"],
    "SuperDove": ["PlanetScope SuperDove"], "RapidEye": ["RapidEye"], "SkySat": ["SkySat A/B", "SkySat C1", "SkySat C2"],
    "Aleph-1": [f"Satellogic Mark {m}" for m in ("I", "II", "III", "IV", "V")], "GeoEye": ["GeoEye-1"], "Legion": ["Legion"],
    "QuickBird": ["QuickBird"], "WV2": ["WorldView-2"], "WV3": ["WorldView-3"]}


def rsr_curves(path: str = RSR_CSV) -> Optional[dict]:
    """Relative spectral response curves for the dashboard (see build_rsr_db.ipynb), None if the file is not there.
    TIR is left out, as in the notebook's comparison plots. Bands that share a name and wavelengths are two real bands
    (SuperDove's two greens), so they are split; a few repeated wavelengths in a band keep the larger value. Each
    curve drops its near-zero ends and is simplified to within 0.3 nm or 0.003 response to keep the page small."""
    from pathlib import Path
    from shapely.geometry import LineString
    if not Path(path).exists():
        return None
    d = pd.read_csv(path).dropna(subset=["wavelength_nm", "rsr", "band", "sensor", "constellation"])
    d = d[~d["band"].str.startswith("TIR")].assign(
        owner=lambda x: x["affiliation"].replace(RSR_OWNER), name=lambda x: x["constellation"].replace(RSR_CONSTELLATION),
        sector=lambda x: x["sector"].replace({"Civil": "Government"}))

    def group(band):
        for pattern, label in (("(?i)swir", "SWIR"), ("(?i)rededge", "RedEdge"), ("(?i)^nir", "NIR"), ("^Green", "Green")):
            if re.search(pattern, band):
                return label
        return band

    keys = d[["sector", "owner", "name"]].drop_duplicates()
    keys = sorted(keys.itertuples(index=False), key=lambda k: (k.sector != "Government", k.owner, k.name))
    panels, curves = [], []
    for i, k in enumerate(keys):
        c = d[(d["sector"] == k.sector) & (d["owner"] == k.owner) & (d["name"] == k.name)]
        panels.append(dict(name=k.name, owner=k.owner, sector=k.sector, sensors=int(c["sensor"].nunique()),
                           groups=RSR_GROUPS.get(k.name, []), sensor_names=" ".join(c["sensor"].unique())))
        for (sensor, band), x in c.groupby(["sensor", "band"], sort=False):
            if x.duplicated("wavelength_nm", keep=False).mean() > 0.5:
                parts = [(f"{band} {n + 1}", y) for n, y in x.groupby(x.groupby("wavelength_nm").cumcount())]
            else:
                parts = [(band, x.groupby("wavelength_nm", as_index=False)["rsr"].max())]
            for label, y in parts:
                y = y.sort_values("wavelength_nm")
                w, r = y["wavelength_nm"].to_numpy(float), y["rsr"].clip(lower=0).to_numpy(float)
                on = np.flatnonzero(r >= 0.002)
                if len(on) < 2:
                    continue
                w, r = w[on[0]:on[-1] + 1], r[on[0]:on[-1] + 1]
                half = w[r >= r.max() / 2]
                line = np.array(LineString(np.c_[w / 100, r]).simplify(0.003).coords)
                curves.append(dict(p=i, sensor=sensor, band=label, group=group(band), center=round(float((w * r).sum() / r.sum()), 1),
                                   fwhm=round(float(half.max() - half.min()), 1), w=[round(v * 100, 1) for v in line[:, 0]],
                                   r=[round(v, 3) for v in line[:, 1]]))
    return dict(panels=panels, curves=curves, source=Path(path).name)


def write_dashboard(raw: pd.DataFrame, groups: pd.DataFrame, issues: pd.DataFrame, edit_log: Optional[pd.DataFrame],
                    out_path: str, template: Optional[str] = None,
                    footprint_max_km: float = 100, sheet_url: Optional[str] = None, revisit=None,
                    rsr_path: Optional[str] = RSR_CSV) -> str:
    """Write the interactive dashboard (one self-contained HTML file): scatter of GSD
    vs swath, launches, aligned spec strips, cross-track swath widths, completeness, checks,
    the edit record and a table view, with hover details for every constellation.
    `raw`: the sheet with the edits applied; `edit_log`: apply_edits() log (with `status`);
    `groups`: constellations() output (all rows; the page filters by sector / status);
    `revisit`: revisit() output (table, inputs), for the Revisit tab.
    `rsr_path`: RSR curves CSV for the Spectral Response tab; the tab is hidden if it is None or not there."""
    import json
    from pathlib import Path
    template = template or str(Path(__file__).with_name("vendor_specs_dashboard.html"))
    edit_log = edit_log if edit_log is not None else pd.DataFrame(columns=EDIT_LOG_COLUMNS + ["now", "status"])
    used = edit_log[~edit_log["status"].str.startswith("skipped")]
    num = lambda v: None if pd.isna(v) else float(v)
    out = []
    for g in groups.itertuples():
        rows = {int(r) for r in g.sheet_rows.split(", ")}
        qa = [f"{r.column} {r.field}: {r.check}" for r in issues.itertuples() if r.sheet_row in rows]
        ed = list({(e.field, e.before, e.after): dict(field=e.field, before=e.before, after=e.after)
                   for e in used.itertuples() if int(e.sheet_row) in rows}.values())
        out.append(dict(
            group=g.group, affiliation=g.affiliation, sector=g.sector, constellation=g.constellation, sensors=g.sensors,
            status=g.status, current=bool(g.current),
            first_launch=None if pd.isna(g.first_launch) else g.first_launch.strftime("%Y-%m-%d"),
            n_satellites=num(g.n_satellites), pan_gsd=num(g.pan_gsd), ms_gsd=num(g.ms_gsd), swir_gsd=num(g.swir_gsd),
            tir_gsd=num(g.tir_gsd), swath_km=num(g.swath_km), ms_bands=num(g.ms_bands), total_bands=num(g.total_bands),
            revisit_days=num(g.revisit_days), ce90_m=num(g.ce90_m), scanner=g.scanner if pd.notna(g.scanner) else None,
            acquisition=g.acquisition if pd.notna(g.acquisition) else None, sheet_rows=g.sheet_rows,
            qa=qa, edits=ed, n_flags=len(qa) + len(ed), revisit=_revisit_payload(revisit, g)))
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
        groups=out, sensors=sensors, footprint_max_km=footprint_max_km, sites=eval_sites(), rsr=rsr_curves(rsr_path) if rsr_path else None,
        revisit=None if revisit is None else revisit[0].attrs,
        affiliation_colors=affiliation_colors(raw["Affiliation"].dropna().unique()),
        edits=edit_log.to_dict("records"),
        edit_status=edit_log["status"].value_counts().to_dict(),
        completeness=[dict(letter=column_letter(i), field=f, pct=float(comp[f].mean() * 100))
                      for i, f in enumerate(comp.columns)],
        qa_summary=qa_sum.to_dict("records"),
        footer=("Built by csda_summaries/notebooks/csda_specs_compare.ipynb (lib/vendor_specs.py). Constellation groups merge "
                "sensors of one data owner with the same GSD, swath and band count. Numbers are parsed from the sheet text "
                "(ranges -> first value). Band counts: Total Bands (MS) includes the pan band. Data-owner colors follow "
                "csda_specs_multispec_smry.ipynb (Set1 + Dark2), except Vantor and DLR; sector colors: commercial blue, government orange. "
                "Black ring = has a panchromatic band."))
    html = Path(template).read_text().replace("/*__DATA__*/null",
                                              json.dumps(payload, default=str, separators=(",", ":")).replace("</", "<\\/"))
    Path(out_path).write_text(html)
    return str(Path(out_path).resolve())
