"""Monthly global acquisition density for each vendor constellation, and the page that animates it.

    python lib/archive_density.py fetch hydrosat      # one vendor's months; run the vendors side by side
    python lib/archive_density.py build               # html/archive_density.html from what has been fetched

Each month is saved on its own under STORE/<vendor>/YYYY-MM.pkl, so a stopped run resumes and a monthly update only
searches the last REFRESH_MONTHS months again, for late deliveries. A month with a failed search is not saved, so it is
searched next time and never shows as empty. Failed windows are halved: busy catalogs answer HTTP 502 to long ones.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
import shapely
import shapely.wkb

import multistac
from archive_dashboard import LAND, PENDING_VENDORS, vendor_palette
import data_repo

REPO = Path(__file__).resolve().parents[1]
# Footprint stores (one outline per item) count each acquisition in every cell it covers; older point stores, only at its center.
STORE = Path(os.environ.get("ARCHIVE_DENSITY_STORE", "/explore/nobackup/people/pmontesa/multistac/global_analysis/monthly_fp"))
PAGE = REPO / "html" / "archive_density.html"
TEMPLATE = Path(__file__).with_name("archive_density_template.html")
START = "2020-01"
REFRESH_MONTHS = 3
CELL_DEG = float(os.environ.get("ARCHIVE_DENSITY_CELL", 0.5))   # map cell; SuperDove is counted on it when fetched
SIMPLIFY_DEG = 0.001   # outlines kept to about 100 m: far finer than any map cell

VENDORS = {
    "hydrosat": dict(collections=["vz-l1b"], vendor="Hydrosat", constellation="VanZyl", unit="scene",
                     guide="One scene counts once. Daytime L1B only: L2 covers the same scenes, and L1A and night scenes are left out."),
    "kuva": dict(collections=["L1B"], vendor="Kuva Space", constellation="Hyperfield", unit="capture",
                 guide="One capture counts once, from its L1B product."),
    "vantor": dict(collections=["lg01", "lg02", "lg03", "lg04", "lg05", "lg06"], vendor="Vantor", constellation="Legion", unit="strip",
                   guide="One catalog strip (Vantor catalog ID) counts once. Strips are not merged into passes: a satellite collects "
                         "strip after strip along an orbit, so merging by time would join a whole orbit into one. This is Vantor's "
                         "own catalog, so it shows what was collected, not what CSDA holds."),
    "worldview": dict(provider="vantor", collections=["wv02", "wv03-vnir"], vendor="Vantor", constellation="WorldView", unit="strip",
                      guide="One catalog strip (Vantor catalog ID) counts once, from Vantor's own catalog. WorldView-3 is its VNIR "
                            "collection (wv03-vnir)."),
    "tanager": dict(provider="planet", collections=["TanagerScene"], vendor="Planet", constellation="Tanager", unit="strip",
                    guide="One Tanager strip counts once (pl:strip_id): a pass is delivered as a run of consecutive scenes, about four "
                          "to a strip, from Planet's own catalog."),
    "superdove": dict(provider="planet", collections=["PSScene"], vendor="Planet", constellation="SuperDove", unit="scene", stats=True,
                      guide="PlanetScope SuperDove scenes (instrument PSB.SD), counted by Planet's catalog statistics rather than "
                            "fetched one by one: about 7 million a month. A scene counts in every cell it touches, not only the cell "
                            "at its center, so busy cells read a little higher than on the other tabs."),
    # Public missions, from Earth Search (no login). Too many items to keep (Sentinel-2: ~450,000 tiles a month), so each month is
    # counted as it is fetched (fetch_counted) and only the counts per cell are kept.
    "sentinel2": dict(provider="earth-search", collections=["sentinel-2-l2a"], vendor="ESA", constellation="Sentinel-2", unit="pass",
                      stats=True, count_on_fetch=True, window_days=1,
                      guide="One datatake counts once: a satellite's continuous acquisition along an orbit, cut into 110 km tiles. "
                            "Sentinel-2A, 2B and 2C, Level-2A, from Earth Search (Element84)."),
    "landsat": dict(provider="earth-search", collections=["landsat-c2-l2"], vendor="USGS / NASA", constellation="Landsat 8 and 9",
                    unit="pass", stats=True, count_on_fetch=True, window_days=7, platforms=["landsat-8", "landsat-9"],
                    guide="One pass counts once: the scenes one satellite takes in a row, less than 2 minutes apart. Landsat 8 and 9, "
                          "Collection 2 Level-2, from Earth Search (Element84); Landsat 7 is left out."),
    "satellogic": dict(collections=["quickview-visual-thumb"], vendor="Satellogic", constellation="Aleph-1", unit="capture",
                       window_days=3, full_records=True,
                       guide="One capture counts once, from its thumbnail item rather than its 2 km tiles. "
                             "Product version 1 and later, as in the site notebook."),
}


def months(start: str = START, end: Optional[str] = None) -> List[str]:
    end = end or f"{pd.Timestamp.today():%Y-%m}"
    return [f"{p}" for p in pd.period_range(start, end, freq="M")]


def _search(vendor: str, first: pd.Timestamp, last: pd.Timestamp, failed: List[str]) -> List[pd.DataFrame]:
    """One date window, halved until it works or is a single day."""
    info = VENDORS[vendor]
    options = dict(compact=False, include_assets=False) if info.get("full_records") else {}
    r = multistac.search(None, f"{first:%Y-%m-%d}", f"{last:%Y-%m-%d}", {info.get("provider", vendor): info["collections"]}, progress=False, **options)
    if not (r.log["status"] == "failed").any():
        return [r.gdf] if len(r.gdf) else []
    if first >= last:
        failed.append(f"{first:%Y-%m-%d}")
        return []
    middle = first + (last - first) // 2
    return _search(vendor, first, middle, failed) + _search(vendor, middle + pd.Timedelta(days=1), last, failed)


def _points(frames: List[pd.DataFrame], vendor: str) -> pd.DataFrame:
    """What the maps need: one row per item, with its center and its outline (WKB, simplified), so any grid can be counted later."""
    columns = ["provider", "collection", "id", "acquisition_id", "sensor", "datetime", "cloud_cover", "lon", "lat", "wkb"]
    if not frames:
        return pd.DataFrame(columns=columns)
    g = pd.concat(frames, ignore_index=True).drop_duplicates("id")
    if VENDORS[vendor].get("platforms"):
        g = g[g.platform.isin(VENDORS[vendor]["platforms"])]
    if "satl:product_version" in g:
        g = g[g["satl:product_version"].astype(str).str.split(".").str[0].astype(float) >= 1]
    points = g.geometry.representative_point()
    outlines = [None if x is None or x.is_empty else shapely.wkb.dumps(x) for x in g.geometry.simplify(SIMPLIFY_DEG).values]
    return pd.DataFrame(g.drop(columns="geometry")).assign(lon=points.x.values, lat=points.y.values, wkb=outlines)[columns]


def fetch_month(vendor: str, month: str) -> Optional[pd.DataFrame]:
    """A month's items, or None if any of its searches failed."""
    first = pd.Timestamp(f"{month}-01")
    last = min(first + pd.offsets.MonthEnd(0), pd.Timestamp.today().normalize())
    step = VENDORS[vendor].get("window_days")
    frames: List[pd.DataFrame] = []
    failed: List[str] = []
    if step:
        day = first
        while day <= last:
            frames += _search(vendor, day, min(day + pd.Timedelta(days=step - 1), last), failed)
            day += pd.Timedelta(days=step)
    else:
        frames = _search(vendor, first, last, failed)
    if failed:
        print(f"{vendor} {month}: failed on {failed}", flush=True)
        return None
    return _points(frames, vendor)


def fetch(vendor: str, refresh: int = REFRESH_MONTHS, only: Optional[List[str]] = None) -> None:
    """Newest month first, so the recent archive is there soonest. `only`: these months (e.g. one year)."""
    folder = STORE / vendor
    folder.mkdir(parents=True, exist_ok=True)
    every = months(VENDORS[vendor].get("start", START))
    for month in reversed(only or every):
        path = folder / f"{month}.pkl"
        if path.exists() and month not in every[-refresh:]:
            continue
        started = time.time()
        table = fetch_month(vendor, month)
        if table is not None:
            table.to_pickle(path)
            print(f"{vendor} {month}: {len(table)} items, {time.time() - started:.0f} s", flush=True)
    print(f"{vendor} done", flush=True)


def fetch_counted(vendor: str, refresh: int = REFRESH_MONTHS, only: Optional[List[str]] = None, cell: float = CELL_DEG) -> None:
    """A public mission too large to keep item by item: each month is fetched in windows of `window_days`, counted per cell
    (each pass once per cell) and saved as STORE/<vendor>/counts/YYYY-MM.pkl (cell, n) and .json (totals). Newest month first;
    one file per month, so several runs can fetch different years at the same time (`only`)."""
    info = VENDORS[vendor]
    folder = STORE / vendor / "counts"
    folder.mkdir(parents=True, exist_ok=True)
    every = months(info.get("start", START))
    for month in reversed(only or every):
        path = folder / f"{month}.pkl"
        if path.exists() and month not in every[-refresh:]:
            continue
        started, failed, pairs, clouds = time.time(), [], [], []
        first = pd.Timestamp(f"{month}-01")
        last = min(first + pd.offsets.MonthEnd(0), pd.Timestamp.today().normalize())
        day, step = first, info.get("window_days", 7)
        while day <= last:
            frames = _search(vendor, day, min(day + pd.Timedelta(days=step - 1), last), failed)
            if frames:
                table = _points(frames, vendor)
                pairs.append(_footprint_pairs(table, cell))
                clouds.append(table[["acquisition_id", "cloud_cover"]])
            day += pd.Timedelta(days=step)
        if failed:
            print(f"{vendor} {month}: failed on {failed}; not saved", flush=True)
            continue
        p = pd.concat(pairs).drop_duplicates() if pairs else pd.DataFrame({"acquisition_id": [], "cell": []})
        counts = p.groupby("cell").size().rename("n").reset_index()
        cloud = (pd.concat(clouds).assign(cloud_cover=lambda x: pd.to_numeric(x.cloud_cover, errors="coerce"))
                 .groupby("acquisition_id").cloud_cover.mean()) if clouds else pd.Series(dtype=float)
        counts.to_pickle(path)
        (folder / f"{month}.json").write_text(json.dumps({"n": int(len(cloud)), "clear": int((cloud <= 20).sum())}))
        print(f"{vendor} {month}: {len(cloud)} passes, {len(counts)} cells, {time.time() - started:.0f} s", flush=True)
    print(f"{vendor} done", flush=True)


PLANET_DATA = "https://api.planet.com/data/v1"


def _planet_session():
    import configparser
    import requests
    from stac_auth import credentials_path
    config = configparser.ConfigParser()
    config.read(credentials_path())
    session = requests.Session()
    session.auth = (config["Planet_STAC_DATA_API"]["api_key"], "")
    return session


def _planet_stats(session, filters: list, start: str, end: str, item_type: str = "PSScene") -> Dict[str, int]:
    """Monthly counts from Planet's stats endpoint, retried when Planet asks to slow down."""
    body = {"item_types": [item_type], "interval": "month", "filter": {"type": "AndFilter", "config": [
        {"type": "DateRangeFilter", "field_name": "acquired", "config": {"gte": f"{start}-01T00:00:00Z", "lte": f"{end}T23:59:59Z"}}] + filters}}
    import requests
    for attempt in range(8):
        try:
            r = session.post(f"{PLANET_DATA}/stats", json=body, timeout=120)
        except requests.exceptions.RequestException:   # a dropped or timed-out connection: wait and try again
            time.sleep(min(120, 5 * 2 ** attempt))
            continue
        if r.status_code in (429, 500, 502, 503, 504):
            time.sleep(min(60, 2 ** attempt))
            continue
        r.raise_for_status()
        return {b["start_time"][:7]: int(b["count"]) for b in r.json().get("buckets", [])}
    raise RuntimeError("Planet stats kept failing")


def land_cells(cell: float = CELL_DEG) -> List[int]:
    """Cells touching land (and a little around it), numbered as on the page: row * columns + column."""
    import geopandas as gpd
    from shapely.geometry import box
    land = gpd.read_file(gpd.datasets.get_path("naturalearth_lowres")).geometry.unary_union.buffer(min(cell / 2, 0.5))
    columns, rows = int(360 / cell), int(180 / cell)
    r, c = np.divmod(np.arange(rows * columns), columns)
    boxes = shapely.box(-180 + c * cell, 90 - (r + 1) * cell, -180 + (c + 1) * cell, 90 - r * cell)
    shapely.prepare(land)
    return [int(i) for i in np.flatnonzero(shapely.intersects(land, boxes))]


def fetch_stats(vendor: str = "superdove", refresh: int = REFRESH_MONTHS, workers: int = 3, cell: float = CELL_DEG) -> None:
    """SuperDove: monthly counts per land cell from Planet's stats, about 9,000 small requests for the whole archive.
    Saved as STORE/<vendor>/cells.pkl (cell, month, n) and totals.json; later runs ask only for the last `refresh` months."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    folder = STORE / vendor
    folder.mkdir(parents=True, exist_ok=True)
    path, done_path = folder / "cells.pkl", folder / "cells_done.json"
    every = months(VENDORS[vendor].get("start", START))
    old = pd.read_pickle(path) if path.exists() else pd.DataFrame(columns=["cell", "month", "n"])
    complete = done_path.exists() and json.loads(done_path.read_text()).get("complete")
    start = every[-refresh] if complete else every[0]
    end = f"{pd.Timestamp.today():%Y-%m-%d}"
    done = set() if complete else set(json.loads(done_path.read_text()).get("cells", [])) if done_path.exists() else set()
    instrument = [{"type": "StringInFilter", "field_name": "instrument", "config": ["PSB.SD"]}]
    session = _planet_session()
    columns = int(360 / cell)

    def one(c):
        r, k = divmod(c, columns)
        lon, lat = -180 + k * cell, 90 - r * cell
        ring = [[lon, lat], [lon + cell, lat], [lon + cell, lat - cell], [lon, lat - cell], [lon, lat]]
        geo = [{"type": "GeometryFilter", "field_name": "geometry", "config": {"type": "Polygon", "coordinates": [ring]}}]
        return c, _planet_stats(session, instrument + geo, start, end)

    todo = [c for c in land_cells(cell) if c not in done]
    print(f"{vendor}: {len(todo)} cells to count from {start}", flush=True)
    new, started = [], time.time()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for i, future in enumerate(as_completed([pool.submit(one, c) for c in todo]), 1):
            c, counts = future.result()
            new += [(c, m, n) for m, n in counts.items() if n]
            done.add(c)
            if i % 500 == 0 or i == len(todo):   # checkpoint, so a stopped run resumes
                table = pd.concat([old[~(old.month >= start)] if complete else old, pd.DataFrame(new, columns=["cell", "month", "n"])])
                table.drop_duplicates(["cell", "month"], keep="last").to_pickle(path)
                done_path.write_text(json.dumps({"complete": i == len(todo) or complete, "cells": [] if i == len(todo) else sorted(done)}))
                print(f"{vendor}: {i} of {len(todo)} cells, {time.time() - started:.0f} s", flush=True)
    totals = {m: {"n": n} for m, n in _planet_stats(session, instrument, every[0], end).items()}
    clear = _planet_stats(session, instrument + [{"type": "RangeFilter", "field_name": "cloud_cover", "config": {"lte": 0.2}}], every[0], end)
    for m, n in clear.items():
        totals.setdefault(m, {"n": 0})["clear"] = n
    (folder / "totals.json").write_text(json.dumps(totals))
    print(f"{vendor} done", flush=True)


# Page tabs: one per vendor; a vendor's constellations are groups within it, shown one at a time or together.
# (label, store, catalog collections or None for all)
TABS = [("hydrosat", [("VanZyl", "hydrosat", None)]),
        ("kuva", [("Hyperfield", "kuva", None)]),
        ("planet", [("SuperDove", "superdove", None), ("Tanager", "tanager", None)]),
        ("satellogic", [("Aleph-1", "satellogic", None)]),
        ("vantor", [("Legion", "vantor", None), ("WorldView-2", "worldview", {"wv02"}), ("WorldView-3", "worldview", {"wv03-vnir"})]),
        ("landsat", [("Landsat 8 and 9", "landsat", None)]),
        ("sentinel2", [("Sentinel-2", "sentinel2", None)])]
COMBINED = {"vantor": [("WorldView-2 and 3", ["WorldView-2", "WorldView-3"]), ("All constellations", None)]}


def _tables(store: str, collections) -> Dict[str, pd.DataFrame]:
    """Each fetched month of a store, kept to the given catalog collections."""
    out = {}
    for path in sorted((STORE / store).glob("*.pkl")):
        table = pd.read_pickle(path)
        if collections is not None:
            table = table[table["collection"].isin(collections)] if "collection" in table else table.iloc[0:0]
        if store == "tanager":   # months fetched before the sensor rule named it
            table = table.assign(sensor="Tanager-1")
        out[path.stem] = table
    return out


def _footprint_pairs(table: pd.DataFrame, cell: float) -> pd.DataFrame:
    """Every (acquisition, cell) pair where one of the acquisition's items touches the cell, once each.

    Each item outline is tested against the cells of its bounding box. An acquisition's items are not joined first: a cell is
    touched by the joined outline exactly when one of its items touches it, and joining a long orbit's tiles is slow.
    (Rasterizing with all_touched and an adding merge, as at first, counted a cell along a polygon's edge several times.)
    """
    t = table[table.wkb.notna()]
    shapes = shapely.from_wkb(t.wkb.values)
    acq = t.acquisition_id.astype(str).values
    keep = ~(pd.isna(shapes) | shapely.is_empty(shapes))
    shapes, acq = shapes[keep], acq[keep]
    if not len(shapes):
        return pd.DataFrame({"acquisition_id": [], "cell": []})
    bounds = shapely.bounds(shapes)
    wraps = (bounds[:, 2] - bounds[:, 0]) > 180   # across the antimeridian: move the western part east by 360°
    if wraps.any():
        shapes[wraps] = [shapely.transform(g, lambda xy: np.where(xy[:, :1] < 0, xy + [360, 0], xy)) for g in shapes[wraps]]
    columns, rows = int(round(360 / cell)), int(round(180 / cell))
    b = shapely.bounds(shapes)
    c0, c1 = [np.floor((b[:, k] + 180) / cell).astype(int).clip(0, 2 * columns - 1) for k in (0, 2)]   # up to 540° east
    r0, r1 = [np.floor((90 - b[:, k]) / cell).astype(int).clip(0, rows - 1) for k in (3, 1)]
    nc, n = c1 - c0 + 1, (c1 - c0 + 1) * (r1 - r0 + 1)
    which = np.repeat(np.arange(len(shapes)), n)                  # every (outline, cell of its bounding box) pair
    k = np.arange(n.sum()) - np.repeat(np.cumsum(n) - n, n)
    r, c = r0[which] + k // nc[which], c0[which] + k % nc[which]
    shapely.prepare(shapes)
    hit = shapely.intersects(shapes[which], shapely.box(-180 + c * cell, 90 - (r + 1) * cell, -180 + (c + 1) * cell, 90 - r * cell))
    cells = r[hit] * columns + c[hit] % columns                   # fold the part east of 180° back
    return pd.DataFrame({"acquisition_id": acq[which[hit]], "cell": cells}).drop_duplicates()


def _footprint_counts(table: pd.DataFrame, cell: float) -> pd.Series:
    """How many acquisitions cover each cell: each acquisition counts once in every cell any of its items touches."""
    pairs = _footprint_pairs(table, cell)
    return pairs.groupby("cell").size().sort_index() if len(pairs) else pd.Series(dtype=int)


def _group(name: str, tables: Dict[str, pd.DataFrame], every: List[str], cell: float) -> dict:
    """For each month, the cells with acquisitions and how many, plus the month's totals."""
    columns, frames, totals = int(360 / cell), [], []
    for month in every:
        table = tables.get(month)
        if table is None or not len(table):
            frames.append([]); totals.append({"month": month, "n": 0, "cells": 0, "sensors": {}, "clear": 0})
            continue
        if "wkb" in table and table.wkb.notna().any():
            counts = _footprint_counts(table, cell)
        else:   # an older point store: each acquisition at its center only
            col = ((table.lon + 180) / cell).astype(int).clip(0, columns - 1)
            row = ((90 - table.lat) / cell).astype(int).clip(0, int(180 / cell) - 1)
            counts = table.assign(cell=row * columns + col).drop_duplicates(["acquisition_id", "cell"]).groupby("cell").size()
        acqs = table.drop_duplicates("acquisition_id")
        frames.append([int(v) for pair in counts.items() for v in pair])
        totals.append({"month": month, "n": int(len(acqs)), "cells": int(counts.size),
                       "sensors": {str(k): int(v) for k, v in acqs.sensor.value_counts().sort_index().items()},
                       "clear": int((pd.to_numeric(acqs.cloud_cover, errors="coerce") <= 20).sum())})
    return {"constellation": name, "frames": frames, "totals": totals}


def _stats_tables(store: str) -> Optional[dict]:
    """A counted store (SuperDove): cell counts by month and the monthly totals, once the counting has finished."""
    folder = STORE / store
    counted = sorted((folder / "counts").glob("*.pkl")) if (folder / "counts").exists() else []
    if counted:   # fetch_counted: a file per month
        cells = pd.concat([pd.read_pickle(f).assign(month=f.stem) for f in counted], ignore_index=True)
        return {"cells": cells[["cell", "month", "n"]], "totals": {f.stem: json.loads(f.with_suffix(".json").read_text()) for f in counted}}
    if not (folder / "totals.json").exists() or not (folder / "cells.pkl").exists():
        return None
    return {"cells": pd.read_pickle(folder / "cells.pkl"), "totals": json.loads((folder / "totals.json").read_text())}


def _stats_group(name: str, counted: dict, every: List[str]) -> dict:
    by_month = {m: g for m, g in counted["cells"].groupby("month")}
    frames = [[int(v) for pair in zip(by_month[m].cell, by_month[m].n) for v in pair] if m in by_month else [] for m in every]
    totals = [{"month": m, "n": counted["totals"].get(m, {}).get("n", 0), "cells": len(frames[i]) // 2, "sensors": {},
               "clear": counted["totals"].get(m, {}).get("clear", 0)} for i, m in enumerate(every)]
    return {"constellation": name, "frames": frames, "totals": totals}


def tab(key: str, groups, cell: float = CELL_DEG) -> Optional[dict]:
    """One vendor: its groups share a month axis, from the earliest month fetched for any of them."""
    loaded = [(name, store, _stats_tables(store) if VENDORS[store].get("stats") else _tables(store, collections))
              for name, store, collections in groups]
    loaded = [(n, s, t) for n, s, t in loaded if t is not None]
    fetched = [m for _, s, t in loaded for m in (t["totals"] if VENDORS[s].get("stats") else t)]
    if not fetched or not any(VENDORS[s].get("stats") or any(len(x) for x in t.values()) for _, s, t in loaded):
        return None
    # the axis starts where the stores are meant to start, so months not fetched yet show as such, not as missing
    every = months(min([min(fetched)] + [VENDORS[store].get("start", START) for _, store, _ in groups]), max(fetched))
    out = []
    for name, store, tables in loaded:
        info = VENDORS[store]
        if info.get("stats"):
            g = _stats_group(name, tables, every)
            start = info.get("start", START)
            if info.get("count_on_fetch"):   # counted a month at a time, several years at once: mark the months not counted yet
                wanted = [m for m in every if m >= start]
                for m in g["totals"]:
                    m["pending"] = m["month"] >= start and m["month"] not in tables["totals"]
                done = sum(m in tables["totals"] for m in wanted)
                if done < len(wanted):
                    g["progress_note"] = f"{done} of {len(wanted)} months counted so far; the rest are being added."
            g["lazy"] = g["counted"] = True   # large: the page loads its frames only when it is picked
            g["count_note"] = ("Each pass counts once in every square its footprint touches." if info.get("count_on_fetch")
                               else "Each scene counts in every square it touches, from Planet's catalog statistics.")
        elif not any(len(x) for x in tables.values()):
            continue
        else:
            g, start = _group(name, tables, every, cell), min(tables)
            g["footprints"] = any("wkb" in x and x.wkb.notna().any() for x in tables.values() if len(x))
            g["lazy"] = cell < 1.5   # fine grids are large: each constellation loads when it is picked
        g.update(key=f"{key}-{name}".lower().replace(" ", "-"), unit=info["unit"], guide=info["guide"], collections=info["collections"],
                 first=next(m["month"] for m in g["totals"] if m["n"]), fetched_from=start,
                 complete=start <= info.get("start", START) and not g.get("progress_note"))
        out.append(g)
    base = list(out)   # combinations are summed in the page from the constellations, so the data are not stored twice
    for name, members in COMBINED.get(key, []):
        parts = [g for g in base if members is None or g["constellation"] in members]
        if len(parts) < 2:
            continue
        out.append({"constellation": name, "parts": [p["constellation"] for p in parts], "key": f"{key}-{name}".lower().replace(" ", "-"),
                    "unit": parts[0]["unit"], "guide": f"{', '.join(p['constellation'] for p in parts)} together, each strip counted once.",
                    "collections": [c for p in parts for c in p["collections"]], "first": min(p["first"] for p in parts),
                    "fetched_from": max(p["fetched_from"] for p in parts), "complete": all(p["complete"] for p in parts)})
    vendor = VENDORS[groups[0][1]]["vendor"]
    palette = vendor_palette(vendor)
    for g in out:
        c = CELL_DEG if g.get("counted") else cell   # Planet's statistics: the grid they were counted on (CELL_DEG)
        g.update(vendor=vendor, cell=c, columns=int(360 / c), partial=f"{pd.Timestamp.today():%Y-%m}", palette=palette)
    return {"key": key, "vendor": vendor, "palette": palette, "groups": out}


def pending_tabs(have_vendors) -> List[dict]:
    """A placeholder tab for each vendor whose catalog access is not in place yet (archive_dashboard.PENDING_VENDORS)."""
    return [dict(key=k, vendor=v["vendor"], palette=vendor_palette(v["vendor"]), pending=True, catalog=v["catalog"],
                 groups=[dict(constellation=c) for c in v["constellations"]])
            for k, v in PENDING_VENDORS.items() if v["vendor"] not in set(have_vendors)]


def _delta(frame: List[int]) -> List[int]:
    """[cell, n, cell, n, ...] sorted by cell, each cell stored as the step from the one before: small numbers, a smaller file."""
    pairs, out, previous = sorted(zip(frame[::2], frame[1::2])), [], 0
    for c, n in pairs:
        out += [c - previous, n]
        previous = c
    return out


def build(page: Path = PAGE, cell: float = CELL_DEG, data_dir: Optional[Path] = None,
          data_base: str = data_repo.DATA_URL + "archive_density/") -> Path:
    """The page. Large frames go to `data_dir` (default: the data repository), read by the page from `data_base`."""
    tabs = [t for t in (tab(k, g, cell) for k, g in TABS) if t]
    tabs += pending_tabs(t["vendor"] for t in tabs)
    lazy_dir = data_dir or data_repo.folder("archive_density")
    for t in tabs:
        for g in t["groups"]:
            if g.get("lazy"):   # frames in their own file, read by the page when this constellation is picked
                lazy_dir.mkdir(exist_ok=True)
                (lazy_dir / f"{g['key']}.json").write_text(json.dumps({"delta": True, "frames": [_delta(f) for f in g.pop("frames")]},
                                                                      separators=(",", ":")))
    data = json.dumps({"tabs": tabs, "land": LAND.read_text(encoding="utf-8").strip(), "updated": f"{pd.Timestamp.today():%-d %b %Y}",
                       "data_base": data_base}, separators=(",", ":"))
    page.write_text(TEMPLATE.read_text(encoding="utf-8").replace("/*DATA*/null", data.replace("</", "<\\/")), encoding="utf-8")
    print(page, f"{page.stat().st_size / 1e6:.1f} MB",
          [f"{g['constellation']}: {sum(m['n'] for m in g['totals'])}" for t in tabs for g in t["groups"] if "totals" in g])
    return page


if __name__ == "__main__":
    if sys.argv[1] == "fetch":   # fetch <vendor> [year ...]: those years only (counted stores; one run per year in parallel)
        v, years = sys.argv[2], sys.argv[3:]
        if VENDORS[v].get("count_on_fetch"):
            fetch_counted(v, only=[m for m in months(VENDORS[v].get("start", START)) if not years or m[:4] in years])
        else:
            fetch_stats(v) if VENDORS[v].get("stats") else fetch(v)
    else:
        build()
