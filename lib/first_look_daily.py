"""Daily refresh of the archive first-look page, with the full history searched for sites new to the sites file.

    lib/first_look_daily.sh                                  # what cron runs: lock, log, then this script
    python lib/first_look_daily.py                           # every vendor, side by side; push the data repository if anything changed
    python lib/first_look_daily.py --vendors kuva,hydrosat --no-push

The vendors run in parallel, one process each (their catalogs are separate services), each stopped after VENDOR_HOURS so a
slow or stuck catalog cannot hold back the others; each writes its log to CACHE/logs/<date>_<vendor>.log. When all are done
or stopped, the tab summaries are rebuilt once and the data repository is pushed once (one commit, replaced; data_repo.py).
The page in this repository reads the summaries from there, so a daily refresh does not change it.

Each vendor's search results are kept under CACHE/<vendor>/ (results.pkl, sites.json, last_log.csv, published.txt). Per vendor:

1. the last REFRESH_DAYS days are searched again at the sites already held (catalogs add acquisitions late), and saved;
2. sites that are new, or whose outline changed, are searched over the vendor's whole history, NEW_BATCH sites at a time,
   saved after each batch, so a vendor stopped part way keeps what it finished;
3. failed searches are retried in halves; a site whose searches still fail is left out (a new site) or keeps its earlier
   rows (a site already held), is named on the page, and is tried again the next day; the rest goes ahead;
4. the vendor's tabs are republished when the results differ from what was last published (published.txt).
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
VENDOR_HOURS = 4    # a vendor still running after this is stopped; it keeps the batches it finished and goes on the next day
NEW_BATCH = 6       # new sites searched over the whole history at a time, saved after each batch
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
    # Airbus's own catalog (OneAtlas STAC). CSDA's airbus-optical holdings are left out: their IDs do not match Airbus's
    # acquisition IDs, so the same acquisition would count twice (CSDA holdings: html/augmentation/airbus_augmentation_summary.html)
    "airbus": dict(providers=lambda: {"airbus": ["PLEIADES", "PLEIADES-NEO", "SPOT"]}, needs="airbus"),
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
            still.append((site, f"{a:%Y-%m-%d}"))
            return
        m = a + (b - a) // 2
        retry(site, a, m, depth + 1)
        retry(site, m + pd.Timedelta(days=1), b, depth + 1)

    for _, row in r.log[r.log.status == "failed"].iterrows():
        a, b = [pd.Timestamp(v[:10]) for v in str(row.interval).split("/")]
        retry(row.site_name, a, b, 0)
    log = r.log.copy()
    failing = {site for site, _ in still}
    log.loc[log.status.eq("failed") & ~log.site_name.isin(failing), "status"] = "retried"
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


def _published(vendor: str) -> str:
    path = CACHE / vendor / "published.txt"
    return path.read_text().strip() if path.exists() else ""


def _merge(parts) -> gpd.GeoDataFrame:
    parts = [p for p in parts if p is not None and len(p)]
    if not parts:
        return gpd.GeoDataFrame(columns=KEY + ["geometry"], geometry="geometry", crs="EPSG:4326")
    return gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), geometry="geometry", crs="EPSG:4326").drop_duplicates(KEY)


def refresh(vendor: str, sites: gpd.GeoDataFrame, today: pd.Timestamp, force_publish: bool = False, summaries: bool = True) -> str:
    """One vendor: the recent window at the sites held, then new sites in batches, then its tabs. Returns what happened:
    published, unchanged, or partial (published, with some sites still failing; they are tried again the next day)."""
    info = VENDORS[vendor]
    providers, split = info["providers"](), info.get("split")
    end = (today + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    cache, known = load(vendor)
    current = {n: signature(g) for n, g in zip(sites.site_name, sites.geometry)}
    new = sorted(n for n, s in current.items() if known.get(n) != s)
    held = [n for n in current if n not in new]
    gone = sorted(set(known) - set(current))
    if gone:
        say(vendor, f"{len(gone)} sites no longer in the set, dropped:", ", ".join(gone))

    # 1. the recent window at the sites already held; a site whose window still fails keeps its earlier rows
    window = max(pd.Timestamp(START), today - pd.Timedelta(days=REFRESH_DAYS)).strftime("%Y-%m-%d")
    win, win_log, win_still = search(sites[sites.site_name.isin(held)], window, end, providers, split)
    stuck = {site for site, _ in win_still}
    keep = cache[cache.site_name.isin(held)] if cache is not None else None
    if keep is not None:   # the window was searched again: its old rows are replaced, except where it failed
        keep = keep[~(_when(keep) >= pd.Timestamp(window, tz="UTC")) | keep.site_name.isin(stuck)]
    if win is not None:
        win = win[~win.site_name.isin(stuck)]
    merged, done, logs = _merge([keep, win]), {n: current[n] for n in held}, [win_log]
    save(vendor, merged, done, win_log)
    say(vendor, f"recent {REFRESH_DAYS} days at {len(held)} sites" + (f"; still failing at {', '.join(sorted(stuck))}" if stuck else ""))

    # 2. new sites over the whole history, a batch at a time, each batch saved
    left_out = []
    if new:
        say(vendor, f"{len(new)} new or changed sites, searched from {START} in batches of {NEW_BATCH}:", ", ".join(new))
    for k in range(0, len(new), NEW_BATCH):
        batch = new[k:k + NEW_BATCH]
        hist, hist_log, hist_still = search(sites[sites.site_name.isin(batch)], START, end, providers, split)
        bad = {site for site, _ in hist_still}
        left_out += sorted(bad)
        if hist is not None:
            hist = hist[~hist.site_name.isin(bad)]
        merged = _merge([merged, hist])
        done.update({n: current[n] for n in batch if n not in bad})
        logs.append(hist_log)
        save(vendor, merged, done, pd.concat([x for x in logs if len(x)], ignore_index=True) if any(len(x) for x in logs) else win_log)
        say(vendor, f"new sites {min(k + NEW_BATCH, len(new))} of {len(new)} searched" + (f"; still failing: {', '.join(sorted(bad))}" if bad else ""))

    # 3. the tabs, when the results differ from what was last published
    failing = sorted(stuck | set(left_out))
    say(vendor, f"{len(merged):,} rows at {merged.site_name.nunique()} sites" + (f"; {len(failing)} sites to try again tomorrow" if failing else ""))
    mark = _fingerprint(merged)
    if not (force_publish or gone or mark != _published(vendor)):
        return "partial" if failing else "unchanged"
    log = pd.concat([x for x in logs if len(x)], ignore_index=True) if any(len(x) for x in logs) else pd.DataFrame(columns=["site_name", "status"])
    ad.publish(vendor, _for_page(vendor, merged), sites, ad.SITES, ad.SITE_NAME_FIELD, START, today.strftime("%Y-%m-%d"), log,
               rebuild=summaries)
    (CACHE / vendor / "published.txt").write_text(mark)
    return "partial" if failing else "published"


def run_one(vendor: str, sites: gpd.GeoDataFrame, today: pd.Timestamp, force_publish: bool, summaries: bool) -> str:
    t = time.time()
    needs = VENDORS[vendor].get("needs")
    if needs and not multistac.get_provider(needs).profile.get("enabled", True):
        say(vendor, f"skipped: catalog access not switched on yet ({needs} in stac_providers.yaml)")
        return "skipped"
    try:
        outcome = refresh(vendor, sites, today, force_publish, summaries)
    except Exception:
        traceback.print_exc()
        outcome = "error"
    say(vendor, outcome, f"{time.time() - t:.0f} s")
    return outcome


def side_by_side(vendors, today: pd.Timestamp, force_publish: bool) -> dict:
    """One process per vendor, each stopped after VENDOR_HOURS. Returns vendor -> outcome."""
    (CACHE / "logs").mkdir(parents=True, exist_ok=True)
    procs = {}
    for v in vendors:
        out = CACHE / v / "outcome.txt"
        out.unlink(missing_ok=True)
        log = open(CACHE / "logs" / f"{today:%Y%m%d}_{v}.log", "a")
        cmd = [sys.executable, "-u", __file__, "--vendors", v, "--child"] + (["--publish"] if force_publish else [])
        procs[v] = (subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, cwd=str(ad.REPO)), log, time.time())
        say(v, f"started (log {log.name})")
    outcome, deadline = {}, VENDOR_HOURS * 3600
    while procs:
        for v, (proc, log, started) in list(procs.items()):
            if proc.poll() is None and time.time() - started < deadline:
                continue
            if proc.poll() is None:
                proc.kill(); proc.wait()
                outcome[v] = "stopped"
                say(v, f"stopped after {VENDOR_HOURS} h: keeps the batches it finished, carries on tomorrow")
            else:
                out = CACHE / v / "outcome.txt"
                outcome[v] = out.read_text().strip() if out.exists() else f"error (exit {proc.returncode})"
                say(v, outcome[v], f"{time.time() - started:.0f} s")
            log.close(); del procs[v]
        time.sleep(15)
    return outcome


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--vendors", default=",".join(VENDORS), help="comma-separated, from: " + ", ".join(VENDORS))
    p.add_argument("--no-push", action="store_true", help="update the data repository's files but do not push them")
    p.add_argument("--publish", action="store_true", help="republish the tabs even if nothing changed")
    p.add_argument("--one-by-one", action="store_true", help="run the vendors in this process, one after another")
    p.add_argument("--child", action="store_true", help=argparse.SUPPRESS)   # one vendor, started by side_by_side
    a = p.parse_args(argv)
    today = pd.Timestamp.today().normalize()
    vendors = a.vendors.split(",")
    if a.child:   # no summary rebuild or push here: the parent does those once, after every vendor
        outcome = run_one(vendors[0], ad.load_sites(), today, a.publish, summaries=False)
        (CACHE / vendors[0]).mkdir(parents=True, exist_ok=True)
        (CACHE / vendors[0] / "outcome.txt").write_text(outcome)
        return 0
    sites = ad.load_sites()
    say(f"first look daily: {len(sites)} sites, {a.vendors}" + ("" if a.one_by_one else ", side by side"))
    if a.one_by_one or len(vendors) == 1:
        outcome = {v: run_one(v, sites, today, a.publish, summaries=False) for v in vendors}
    else:
        outcome = side_by_side(vendors, today, a.publish)
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
    return 0 if all(o in ("published", "unchanged", "skipped") for o in outcome.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
