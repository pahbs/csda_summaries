"""Daily refresh of the archive first-look page, with the full history searched for sites new to the sites file.

    lib/first_look_daily.sh                                  # what cron runs: lock, log, then this script
    python lib/first_look_daily.py                           # every vendor; push the data repository if anything changed
    python lib/first_look_daily.py --vendors kuva,hydrosat --no-push

Each vendor's search results are kept under CACHE/<vendor>/ (results.pkl, sites.json, last_log.csv). A run, per vendor:

1. compares the first-look sites (archive_dashboard.load_sites) with the sites the cache holds: a site that is new, or whose
   outline changed, is searched over the vendor's whole history; a site no longer in the set is dropped;
2. searches the last REFRESH_DAYS days again at every other site (catalogs add acquisitions late) and replaces that part;
3. retries failed searches in halves; a vendor whose searches still fail keeps its cache and its tab as they were;
4. republishes the vendor's tabs if anything changed.

Then it rebuilds the tab summaries and pushes the data repository (one commit, replaced; see data_repo.py). The page in
this repository reads the summaries from there, so a daily refresh does not change it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import traceback
from pathlib import Path

import geopandas as gpd
import pandas as pd
import shapely

sys.path.insert(0, str(Path(__file__).parent))
import archive_dashboard as ad  # noqa: E402
import data_repo  # noqa: E402
import multistac  # noqa: E402

CACHE = Path(os.environ.get("FIRST_LOOK_CACHE", "/explore/nobackup/people/pmontesa/multistac/first_look_cache"))
REFRESH_DAYS = 90   # searched again every day: vendors add acquisitions to their catalogs weeks after they are taken
KEY = ["site_name", "provider", "id"]


def _csda(*ids):
    have = set(multistac.collections("csda")["id"])
    return [c for c in ids if c in have]


# The search each vendor notebook publishes from (multistac_site_analysis_<vendor>.ipynb), from its first possible year
VENDORS = {
    "kuva": dict(providers=lambda: {"csda": _csda("kuvaspace"), "kuva": None}),
    "hydrosat": dict(providers=lambda: {"csda": _csda("hydrosat"), "hydrosat": ["vz-l1b", "vz-l2", "vz-l1b-night"]}),
    "legion": dict(providers=lambda: {"csda": ["maxar-legion"], "vantor": ["lg01", "lg02", "lg03", "lg04", "lg05", "lg06"]},
                   split="year"),
    "worldview": dict(providers=lambda: {"vantor": ["wv02", "wv03-vnir"]}, split="year"),
    "satellogic": dict(providers=lambda: {"csda": _csda("satellogic"), "satellogic": ["quickview-visual"]},
                       split="month"),   # busy sites answer HTTP 502 to longer windows
    "planet": dict(providers=lambda: {"planet": ["PSScene", "TanagerScene"]}, split="month"),
    # Ready for when catalog access starts: skipped while the provider is enabled: false in stac_providers.yaml. Set the
    # collections when access arrives (None = the profile's default_collections).
    "airbus": dict(providers=lambda: {"csda": _csda("airbus-optical"), "airbus": None}, needs="airbus"),
    "earthdaily": dict(providers=lambda: {"earthdaily": None}, needs="earthdaily"),
}
START = "2020-01-01"


def _for_page(vendor: str, gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """What the notebooks publish from the search: the same filters and names."""
    if vendor == "satellogic":   # Satellogic product version 1 and later; earlier ones are superseded
        version = gdf["satl:product_version"].astype(str).str.split(".").str[0]
        return gdf[gdf.provider.eq("csda") | (pd.to_numeric(version, errors="coerce") >= 1)]
    if vendor == "planet":
        ps = gdf.collection.eq("PSScene")
        gdf = gdf[~ps | gdf.instrument.astype(str).str.contains("PSB.SD", regex=False)].copy()   # SuperDove only
        gdf.loc[gdf.collection.eq("PSScene"), ["constellation", "sensor"]] = ["SuperDove", "SuperDove"]
        gdf.loc[gdf.collection.eq("TanagerScene"), ["constellation", "sensor"]] = ["Tanager", "Tanager-1"]
    return gdf


def say(*args) -> None:
    print(f"{pd.Timestamp.now():%Y-%m-%d %H:%M:%S}", *args, flush=True)


def signature(geometry) -> str:
    """Changes when a site's outline changes, so the site is searched again from the start."""
    return hashlib.sha1(shapely.to_wkb(shapely.normalize(geometry))).hexdigest()[:16]


def search(sites: gpd.GeoDataFrame, start: str, end: str, providers: dict, split=None):
    """multistac.search, with failed windows searched again in halves. Returns (results, log, windows still failing)."""
    if not len(sites):
        return None, pd.DataFrame(), []
    r = multistac.search(sites, start, end, providers, split=split, progress=False)
    parts, still = [r.gdf], []

    def retry(site, a, b, depth):
        x = multistac.search(sites[sites.site_name.eq(site)], f"{a:%Y-%m-%d}", f"{b:%Y-%m-%d}", providers, progress=False)
        if not (x.log.status == "failed").any():
            parts.append(x.gdf)
            return
        if depth >= 4 or a >= b:
            still.append(f"{site} {a:%Y-%m-%d}")
            return
        m = a + (b - a) // 2
        retry(site, a, m, depth + 1)
        retry(site, m + pd.Timedelta(days=1), b, depth + 1)

    for _, row in r.log[r.log.status == "failed"].iterrows():
        a, b = [pd.Timestamp(v[:10]) for v in str(row.interval).split("/")]
        retry(row.site_name, a, b, 0)
    log = r.log.copy()
    if not still:
        log.loc[log.status == "failed", "status"] = "retried"
    parts = [p for p in parts if p is not None and len(p)]
    gdf = gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), geometry="geometry", crs="EPSG:4326") if parts else None
    return (gdf.drop_duplicates(KEY) if gdf is not None else None), log, still


def _when(gdf: pd.DataFrame) -> pd.Series:
    return pd.to_datetime(gdf["datetime"], utc=True, errors="coerce")


def load(vendor: str):
    folder = CACHE / vendor
    if not (folder / "results.pkl").exists():
        return None, {}
    return pd.read_pickle(folder / "results.pkl"), json.loads((folder / "sites.json").read_text())


def save(vendor: str, gdf: gpd.GeoDataFrame, known: dict, log: pd.DataFrame) -> None:
    folder = CACHE / vendor
    folder.mkdir(parents=True, exist_ok=True)
    tmp = folder / "results.pkl.tmp"
    gdf.to_pickle(tmp)
    tmp.replace(folder / "results.pkl")   # never a half-written cache
    (folder / "sites.json").write_text(json.dumps(known, indent=1, sort_keys=True))
    log.to_csv(folder / "last_log.csv", index=False)


def _fingerprint(gdf) -> str:
    keys = gdf[KEY].astype(str).agg("|".join, axis=1).sort_values() if gdf is not None and len(gdf) else pd.Series([], dtype=str)
    return hashlib.sha1("\n".join(keys).encode()).hexdigest()


def refresh(vendor: str, sites: gpd.GeoDataFrame, today: pd.Timestamp, force_publish: bool = False) -> str:
    """One vendor: new sites from the start, the last REFRESH_DAYS days everywhere, then its tabs. Returns what happened."""
    info = VENDORS[vendor]
    providers, split = info["providers"](), info.get("split")
    end = (today + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    cache, known = load(vendor)
    current = {n: signature(g) for n, g in zip(sites.site_name, sites.geometry)}
    new = sorted(n for n, s in current.items() if known.get(n) != s)
    gone = sorted(set(known) - set(current))
    if new:
        say(vendor, f"{len(new)} new or changed sites, searched from {START}:", ", ".join(new))
    if gone:
        say(vendor, f"{len(gone)} sites no longer in the set, dropped:", ", ".join(gone))

    hist, hist_log, hist_still = search(sites[sites.site_name.isin(new)], START, end, providers, split)
    window = max(pd.Timestamp(START), today - pd.Timedelta(days=REFRESH_DAYS)).strftime("%Y-%m-%d")
    win, win_log, win_still = search(sites[~sites.site_name.isin(new)], window, end, providers, split)
    if hist_still or win_still:
        say(vendor, "searches still failing after retries, cache and tab left as they were:", hist_still + win_still)
        return "failed"

    keep = cache[cache.site_name.isin(set(current) - set(new))] if cache is not None else None
    if keep is not None:   # the window was searched again: its old rows are replaced
        keep = keep[~(_when(keep) >= pd.Timestamp(window, tz="UTC"))]
    parts = [p for p in (keep, hist, win) if p is not None and len(p)]
    merged = gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), geometry="geometry", crs="EPSG:4326").drop_duplicates(KEY) \
        if parts else gpd.GeoDataFrame(columns=KEY + ["geometry"], geometry="geometry", crs="EPSG:4326")
    added = len(set(map(tuple, merged[KEY].astype(str).values)) - set(map(tuple, cache[KEY].astype(str).values))) if cache is not None else len(merged)
    changed = force_publish or new or gone or cache is None or _fingerprint(merged) != _fingerprint(cache)
    log = pd.concat([x for x in (hist_log, win_log) if len(x)], ignore_index=True) if len(hist_log) or len(win_log) else pd.DataFrame(
        columns=["site_name", "status"])
    save(vendor, merged, current, log)
    say(vendor, f"{len(merged):,} rows at {merged.site_name.nunique()} sites; {added:,} new rows")
    if not changed:
        return "unchanged"
    ad.publish(vendor, _for_page(vendor, merged), sites, ad.SITES, ad.SITE_NAME_FIELD, START, today.strftime("%Y-%m-%d"),
               log.assign(status=log.status.replace({"failed": "retried"})))
    return "published"


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--vendors", default=",".join(VENDORS), help="comma-separated, from: " + ", ".join(VENDORS))
    p.add_argument("--no-push", action="store_true", help="update the data repository's files but do not push them")
    p.add_argument("--publish", action="store_true", help="republish the tabs even if nothing changed")
    a = p.parse_args(argv)
    today = pd.Timestamp.today().normalize()
    sites = ad.load_sites()
    say(f"first look daily: {len(sites)} sites, {a.vendors}")
    outcome = {}
    for vendor in a.vendors.split(","):
        t = time.time()
        needs = VENDORS[vendor].get("needs")
        if needs and not multistac.get_provider(needs).profile.get("enabled", True):
            say(vendor, f"skipped: catalog access not switched on yet ({needs} in stac_providers.yaml)")
            continue
        try:
            outcome[vendor] = refresh(vendor, sites, today, a.publish)
        except Exception:
            traceback.print_exc()
            outcome[vendor] = "error"
        say(vendor, outcome[vendor], f"{time.time() - t:.0f} s")
    ad.build()
    say("summaries rebuilt:", outcome)
    page = subprocess.run(["git", "-C", str(ad.REPO), "status", "--porcelain", "--", str(ad.PAGE)], capture_output=True, text=True).stdout
    if page.strip():
        say("NOTE: html/archive_first_look.html changed (template or code changed): commit and push it by hand")
    changes = subprocess.run(["git", "-C", str(data_repo.DATA_REPO), "status", "--porcelain"], capture_output=True, text=True).stdout
    if a.no_push:
        say("not pushed (--no-push)")
    elif changes.strip():
        data_repo.push(f"First look {today:%Y-%m-%d}: " + ", ".join(f"{v} {o}" for v, o in outcome.items()))
    else:
        say("nothing to push")
    return 0 if all(o in ("published", "unchanged") for o in outcome.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
