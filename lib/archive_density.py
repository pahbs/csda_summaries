"""Monthly global acquisition density for each vendor constellation, and the page that animates it.

    python lib/archive_density.py fetch hydrosat      # one vendor's months; run the vendors side by side
    python lib/archive_density.py build               # html/archive_density.html from what has been fetched

Each month is saved on its own under STORE/<vendor>/YYYY-MM.pkl, so a stopped run resumes and a monthly update only
searches the last REFRESH_MONTHS months again, for late deliveries. A month with a failed search is not saved, so it is
searched next time and never shows as empty. Failed windows are halved: busy catalogs answer HTTP 502 to long ones.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

import multistac
from archive_dashboard import LAND, merge_passes

REPO = Path(__file__).resolve().parents[1]
STORE = Path("/explore/nobackup/people/pmontesa/multistac/global_analysis/monthly")
PAGE = REPO / "html" / "archive_density.html"
TEMPLATE = Path(__file__).with_name("archive_density_template.html")
START = "2024-01"
REFRESH_MONTHS = 3
CELL_DEG = 1.5

VENDORS = {
    "hydrosat": dict(collections=["vz-l1b"], vendor="Hydrosat", constellation="VanZyl", unit="scene",
                     guide="One scene counts once. Daytime L1B only: L2 covers the same scenes, and L1A and night scenes are left out."),
    "kuva": dict(collections=["L1B"], vendor="Kuva Space", constellation="Hyperfield", unit="capture",
                 guide="One capture counts once, from its L1B product."),
    "vantor": dict(collections=["lg01", "lg02", "lg03", "lg04", "lg05", "lg06"], vendor="Vantor", constellation="Legion", unit="strip",
                   guide="One catalog strip (Vantor catalog ID) counts once. Strips are not merged into passes: a satellite collects "
                         "strip after strip along an orbit, so merging by time would join a whole orbit into one. This is Vantor's "
                         "own catalog, so it shows what was collected, not what CSDA holds."),
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
    r = multistac.search(None, f"{first:%Y-%m-%d}", f"{last:%Y-%m-%d}", {vendor: info["collections"]}, progress=False, **options)
    if not (r.log["status"] == "failed").any():
        return [r.gdf] if len(r.gdf) else []
    if first >= last:
        failed.append(f"{first:%Y-%m-%d}")
        return []
    middle = first + (last - first) // 2
    return _search(vendor, first, middle, failed) + _search(vendor, middle + pd.Timedelta(days=1), last, failed)


def _points(frames: List[pd.DataFrame], vendor: str) -> pd.DataFrame:
    """What the maps need: one row per item, with the footprint's center."""
    columns = ["provider", "id", "acquisition_id", "sensor", "datetime", "cloud_cover", "lon", "lat"]
    if not frames:
        return pd.DataFrame(columns=columns)
    g = pd.concat(frames, ignore_index=True).drop_duplicates("id")
    if "satl:product_version" in g:
        g = g[g["satl:product_version"].astype(str).str.split(".").str[0].astype(float) >= 1]
    points = g.geometry.representative_point()
    return pd.DataFrame(g.drop(columns="geometry")).assign(lon=points.x.values, lat=points.y.values)[columns]


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


def fetch(vendor: str, refresh: int = REFRESH_MONTHS) -> None:
    folder = STORE / vendor
    folder.mkdir(parents=True, exist_ok=True)
    every = months()
    for month in every:
        path = folder / f"{month}.pkl"
        if path.exists() and month not in every[-refresh:]:
            continue
        started = time.time()
        table = fetch_month(vendor, month)
        if table is not None:
            table.to_pickle(path)
            print(f"{vendor} {month}: {len(table)} items, {time.time() - started:.0f} s", flush=True)
    print(f"{vendor} done", flush=True)


def tab(vendor: str, cell: float = CELL_DEG) -> Optional[dict]:
    """One constellation: for each month, the cells with acquisitions and how many."""
    info = VENDORS[vendor]
    every = months()
    tables = {m: pd.read_pickle(STORE / vendor / f"{m}.pkl") for m in every if (STORE / vendor / f"{m}.pkl").exists()}
    tables = {m: t for m, t in tables.items() if len(t)}
    if not tables:
        return None
    first, columns = min(tables), int(360 / cell)
    frames, totals = [], []
    for month in [m for m in every if m >= first]:
        table = tables.get(month)
        if table is None:
            frames.append([]); totals.append({"month": month, "n": 0, "cells": 0, "sensors": {}, "clear": 0})
            continue
        if info.get("match_seconds"):
            table = merge_passes(table, info["match_seconds"])
        col = ((table.lon + 180) / cell).astype(int).clip(0, columns - 1)
        row = ((90 - table.lat) / cell).astype(int).clip(0, int(180 / cell) - 1)
        one = table.assign(cell=row * columns + col).drop_duplicates(["acquisition_id", "cell"])
        counts = one.groupby("cell").size()
        acqs = table.drop_duplicates("acquisition_id")
        frames.append([int(v) for pair in counts.items() for v in pair])
        totals.append({"month": month, "n": int(acqs.shape[0]), "cells": int(counts.size),
                       "sensors": {str(k): int(v) for k, v in acqs.sensor.value_counts().sort_index().items()},
                       "clear": int((pd.to_numeric(acqs.cloud_cover, errors="coerce") <= 20).sum())})
    return {"key": vendor, "vendor": info["vendor"], "constellation": info["constellation"], "unit": info["unit"],
            "guide": info["guide"], "collections": info["collections"], "cell": cell, "columns": columns,
            "partial": f"{pd.Timestamp.today():%Y-%m}", "frames": frames, "totals": totals}


def build(page: Path = PAGE) -> Path:
    tabs = [t for t in (tab(v) for v in VENDORS) if t]
    data = json.dumps({"tabs": tabs, "land": LAND.read_text(encoding="utf-8").strip(), "updated": f"{pd.Timestamp.today():%-d %b %Y}"},
                      separators=(",", ":"))
    page.write_text(TEMPLATE.read_text(encoding="utf-8").replace("/*DATA*/null", data.replace("</", "<\\/")), encoding="utf-8")
    print(page, f"{page.stat().st_size / 1e6:.1f} MB", [f"{t['constellation']}: {sum(m['n'] for m in t['totals'])}" for t in tabs])
    return page


if __name__ == "__main__":
    fetch(sys.argv[2]) if sys.argv[1] == "fetch" else build()
