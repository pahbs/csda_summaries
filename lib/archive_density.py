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
from archive_dashboard import LAND, vendor_palette

REPO = Path(__file__).resolve().parents[1]
STORE = Path("/explore/nobackup/people/pmontesa/multistac/global_analysis/monthly")
PAGE = REPO / "html" / "archive_density.html"
TEMPLATE = Path(__file__).with_name("archive_density_template.html")
START = "2020-01"
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
    "worldview": dict(provider="vantor", collections=["wv02", "wv03-vnir"], vendor="Vantor", constellation="WorldView", unit="strip",
                      guide="One catalog strip (Vantor catalog ID) counts once, from Vantor's own catalog. WorldView-3 is its VNIR "
                            "collection (wv03-vnir)."),
    "tanager": dict(provider="planet", collections=["TanagerScene"], vendor="Planet", constellation="Tanager", unit="scene",
                    guide="One Tanager scene counts once, in the cell holding its center, from Planet's own catalog."),
    "superdove": dict(provider="planet", collections=["PSScene"], vendor="Planet", constellation="SuperDove", unit="scene", stats=True,
                      guide="PlanetScope SuperDove scenes (instrument PSB.SD), counted by Planet's catalog statistics rather than "
                            "fetched one by one: about 7 million a month. A scene counts in every cell it touches, not only the cell "
                            "at its center, so busy cells read a little higher than on the other tabs."),
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
    """What the maps need: one row per item, with the footprint's center."""
    columns = ["provider", "collection", "id", "acquisition_id", "sensor", "datetime", "cloud_cover", "lon", "lat"]
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
    for attempt in range(8):
        r = session.post(f"{PLANET_DATA}/stats", json=body, timeout=120)
        if r.status_code in (429, 500, 502, 503, 504):
            time.sleep(min(60, 2 ** attempt))
            continue
        r.raise_for_status()
        return {b["start_time"][:7]: int(b["count"]) for b in r.json().get("buckets", [])}
    raise RuntimeError(f"Planet stats kept failing: HTTP {r.status_code}")


def land_cells(cell: float = CELL_DEG) -> List[int]:
    """Cells touching land (and a little around it), numbered as on the page: row * columns + column."""
    import geopandas as gpd
    from shapely.geometry import box
    land = gpd.read_file(gpd.datasets.get_path("naturalearth_lowres")).geometry.unary_union.buffer(cell / 2)
    columns, rows = int(360 / cell), int(180 / cell)
    return [r * columns + c for r in range(rows) for c in range(columns)
            if land.intersects(box(-180 + c * cell, 90 - (r + 1) * cell, -180 + (c + 1) * cell, 90 - r * cell))]


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
        ("vantor", [("Legion", "vantor", None), ("WorldView-2", "worldview", {"wv02"}), ("WorldView-3", "worldview", {"wv03-vnir"})])]
COMBINED = {"vantor": [("WorldView-2 and 3", ["WorldView-2", "WorldView-3"]), ("All constellations", None)]}


def _tables(store: str, collections) -> Dict[str, pd.DataFrame]:
    """Each fetched month of a store, kept to the given catalog collections."""
    out = {}
    for path in sorted((STORE / store).glob("*.pkl")):
        table = pd.read_pickle(path)
        if collections is not None:
            table = table[table["collection"].isin(collections)] if "collection" in table else table.iloc[0:0]
        out[path.stem] = table
    return out


def _group(name: str, tables: Dict[str, pd.DataFrame], every: List[str], cell: float) -> dict:
    """For each month, the cells with acquisitions and how many, plus the month's totals."""
    columns, frames, totals = int(360 / cell), [], []
    for month in every:
        table = tables.get(month)
        if table is None or not len(table):
            frames.append([]); totals.append({"month": month, "n": 0, "cells": 0, "sensors": {}, "clear": 0})
            continue
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
            g, start = _stats_group(name, tables, every), info.get("start", START)   # counted over the whole period at once
            g["lazy"] = g["counted"] = True   # large: the page loads its frames only when it is picked
        elif not any(len(x) for x in tables.values()):
            continue
        else:
            g, start = _group(name, tables, every, cell), min(tables)
        g.update(key=f"{key}-{name}".lower().replace(" ", "-"), unit=info["unit"], guide=info["guide"], collections=info["collections"],
                 first=next(m["month"] for m in g["totals"] if m["n"]), fetched_from=start, complete=start <= info.get("start", START))
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
        g.update(vendor=vendor, cell=cell, columns=int(360 / cell), partial=f"{pd.Timestamp.today():%Y-%m}", palette=palette)
    return {"key": key, "vendor": vendor, "palette": palette, "groups": out}


def build(page: Path = PAGE) -> Path:
    tabs = [t for t in (tab(k, g) for k, g in TABS) if t]
    lazy_dir = page.parent / "archive_density_data"
    for t in tabs:
        for g in t["groups"]:
            if g.get("lazy"):   # frames in their own file, read by the page when this constellation is picked
                lazy_dir.mkdir(exist_ok=True)
                (lazy_dir / f"{g['key']}.json").write_text(json.dumps({"frames": g.pop("frames")}, separators=(",", ":")))
    data = json.dumps({"tabs": tabs, "land": LAND.read_text(encoding="utf-8").strip(), "updated": f"{pd.Timestamp.today():%-d %b %Y}"},
                      separators=(",", ":"))
    page.write_text(TEMPLATE.read_text(encoding="utf-8").replace("/*DATA*/null", data.replace("</", "<\\/")), encoding="utf-8")
    print(page, f"{page.stat().st_size / 1e6:.1f} MB",
          [f"{g['constellation']}: {sum(m['n'] for m in g['totals'])}" for t in tabs for g in t["groups"] if "totals" in g])
    return page


if __name__ == "__main__":
    if sys.argv[1] == "fetch":
        fetch_stats(sys.argv[2]) if VENDORS[sys.argv[2]].get("stats") else fetch(sys.argv[2])
    else:
        build()
