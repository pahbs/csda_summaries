"""The results of the data tracking notebooks, worked out the same way for every vendor.

airbus_order_tracking.ipynb and vantor_legion_supp_tracking.ipynb differ in what was requested and how it is read.
From `products` on (one row per CSDA product and site) they share this module, so they report the same things:

    products = tracking_report.products_table(res.gdf)
    products = tracking_report.mark_on_adapt(products, res.items, have_dirs, local_copies)
    products, last_run = tracking_report.compare_with_last_run(products, out_dir)      # 1. what is new
    tracking_report.write_summary_page(products, html_path, title, intro, notes, last_run, ...)   # 2. the HTML summary
    plan = tracking_report.plan_download(products, res.items)
    check = tracking_report.download(plan, res.items, products, ...)                   # 3. the download
    tracking_report.save_run(products, out_dir, res.log)
    tracking_report.results(vendor, products, last_run, html_path, plan, check)

CSDA STAC items have no date added, so "new" comes from comparing with the product list saved by the previous run
(`<out_dir>/runs/products_YYYYMMDD.csv`). That also finds old acquisitions delivered late.
"""

from __future__ import annotations

import html
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple, Union

import pandas as pd

import order_tracking

KEYS = ["site_name", "acquisition_id"]
LEGION_RADIOMETRY = {"Off": "TOA", "ACOMP": "SR"}   # .IMD radiometricEnhancement; anything else (DRA) is 'other'
# What the codes mean, from the vendors' delivered metadata (Airbus DIM_*.XML, Vantor .IMD)
LEVELS = {"ORT": "Ortho (ORT)", "SEN": "Sensor geometry (SEN)", "LV3D": "Ortho (LV3D)", "LV2A": "Standard (LV2A)"}
AIRBUS_RADIOMETRY_LABELS = {"TOA": "TOA reflectance (RFL)", "SR": "Surface reflectance (SR)", "basic": "Raw counts (BAS)"}
LEGION_RADIOMETRY_LABELS = {"TOA": "Calibrated DN (enhancement off)", "SR": "Surface reflectance (ACOMP)", "other": "Other"}
TERMS = [("Geometry", "Terrain-corrected and map-projected: the one to use for overlays and comparing dates", "<code>ORT</code> (ORTHO)",
          "<code>LV3D</code> (Ortho, fine DEM)"),
         ("Geometry", "Map-projected with a coarse DEM only, so terrain can still shift features", "not delivered",
          "<code>LV2A</code> (Standard, coarse DEM)"),
         ("Geometry", "As the sensor saw it, not map-projected", "<code>SEN</code> (SENSOR)", "not delivered"),
         ("Bands", "Panchromatic: one band, the sharpest", "<code>P</code>, <code>PAN</code>", "<code>P2AS</code>, <code>P3DS</code>"),
         ("Bands", "Multispectral", "<code>MS</code>: 4 bands. <code>MS-FS</code> (Pl&eacute;iades Neo): 6 bands, adding deep blue and red edge",
          "<code>M2AS</code>, <code>M3DS</code>: 8 bands (coastal, blue, green, yellow, red, 2 red edge, NIR)"),
         ("Bands", "Pansharpened: multispectral at the pan pixel size", "not delivered", "<code>S3DS</code>: usually 3 bands (RGB)"),
         ("Radiometry", "Top of atmosphere", "<code>RFL</code> (REFLECTANCE): pixels are already reflectance",
          "Enhancement <code>Off</code>: pixels are calibrated DN, converted to radiance and reflectance with <code>absCalFactor</code>"),
         ("Radiometry", "Surface reflectance", "<code>SR</code> (SURFACE_REFLECTANCE)",
          "<code>ACOMP</code> (atmospheric compensation), read as surface reflectance: the metadata do not say so, "
          "<code>absCalFactor</code> is &minus;999 and pixel values are consistent with reflectance &times; 10,000"),
         ("Radiometry", "Raw counts, with gains in the metadata to reach TOA radiance", "<code>BAS</code> (BASIC)", "not delivered")]
PAGE_STYLE = """:root{color-scheme:light dark;--bg:#fff;--fg:#1d1d1f;--mut:#5f6368;--line:#dadce0;--tot:#f1f3f4}
@media (prefers-color-scheme:dark){:root{--bg:#1e1f22;--fg:#e8eaed;--mut:#9aa0a6;--line:#3c4043;--tot:#2a2b2e}}
body{font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif;background:var(--bg);color:var(--fg);max-width:1100px;margin:2rem auto;padding:0 1rem}
h1{font-size:1.35rem;margin:0 0 .25rem} p,li{color:var(--mut)} .meta{margin:0 0 1.25rem}
table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums} th,td{padding:.45rem .6rem;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
th{font-weight:600;font-size:.85rem;color:var(--mut)} td.n,th.n{text-align:right} tr.tot td{font-weight:600;background:var(--tot)}
h2{font-size:1.05rem;margin:2rem 0 .35rem} .wrap{overflow-x:auto} code{font-size:.9em} .lead{color:var(--fg)}"""


def _utc(times: pd.Series) -> pd.Series:
    """UTC times from mixed ISO formats (with and without fractional seconds), under pandas 1 and 2."""
    return pd.to_datetime(times.map(pd.Timestamp), utc=True)


def products_table(gdf, radiometry: Optional[pd.Series] = None, bands: Optional[pd.Series] = None) -> pd.DataFrame:
    """One row per CSDA product and site, from a search result. `radiometry` (TOA, SR or other) if the catalog has it,
    `bands` = number of bands."""
    cols = ["site_name", "acquisition_id", "id", "constellation", "sensor", "spectral_mode", "processing_level", "gsd",
            "cloud_cover", "off_nadir"]
    products = pd.DataFrame(gdf[cols]).assign(acq_time=_utc(gdf["datetime"]))
    products["radiometry"] = radiometry if radiometry is not None else None
    products["bands"] = bands if bands is not None else None
    return products.drop_duplicates(["site_name", "id"]).reset_index(drop=True)


def airbus_local_copies(products: pd.DataFrame, footprints: Union[str, Path], match_seconds: float) -> pd.Series:
    """Item id -> metadata path of the same product in the local footprints, whatever folder it is in:
    same platform, P / MS, radiometry and acquisition time within `match_seconds`."""
    local = pd.read_csv(footprints, usecols=["affiliation", "sensor", "acquisition_datetime", "image_type",
                                             "radiometric_type", "metadata_path"])
    local = local[local.affiliation.eq("Airbus")].copy()
    # Time as in the CSDA ID: from the metadata file name (DIM_PHR1A_MS_202503311054361_ORT_...); the footprint time is
    # the first located time (PHR Top Center), up to several seconds later
    name_time = local.metadata_path.str.extract(r"_(\d{14})(\d)_[^/]*$")
    local["local_time"] = (pd.to_datetime(name_time[0], format="%Y%m%d%H%M%S", utc=True, errors="coerce")
                           + pd.to_timedelta(name_time[1].astype(float) / 10, unit="s")
                           ).fillna(_utc(local.acquisition_datetime))
    local["image_type"] = local.image_type.mask(local.metadata_path.str.contains("_PMS_", na=False), "PMS")   # pansharpened, not MS
    wanted = products.drop_duplicates("id").assign(
        sensor=lambda d: d.id.map(lambda i: order_tracking.id_time(i)[0]),
        t=lambda d: d.id.map(lambda i: order_tracking.id_time(i)[1]),
        image_type=lambda d: d.spectral_mode.map({"pan": "P", "ms": "MS"}),
        radiometric_type=lambda d: d.radiometry.map({"TOA": "REFLECTANCE", "SR": "SURFACE_REFLECTANCE", "basic": "BASIC"}))
    on_disk = pd.merge_asof(
        wanted.dropna(subset=["image_type", "radiometric_type", "t"]).sort_values("t")[
            ["id", "sensor", "t", "image_type", "radiometric_type"]],
        local.sort_values("local_time")[["sensor", "local_time", "image_type", "radiometric_type", "metadata_path"]],
        left_on="t", right_on="local_time", by=["sensor", "image_type", "radiometric_type"],
        tolerance=pd.Timedelta(seconds=match_seconds), direction="nearest")
    return on_disk.dropna(subset=["metadata_path"]).set_index("id").metadata_path


def _legion_footprints(footprints: Union[str, Path]) -> pd.DataFrame:
    """Legion rows of the local footprints with the CSDA item id, rebuilt from the file name:
    26MAY09092818-M2AS-200014660685_01_P001.XML is item 200014660685_01_P001_M2AS."""
    local = pd.read_csv(footprints, usecols=["constellation", "radiometric_type", "metadata_path"])
    local = local[local.constellation.eq("Legion")].copy()
    parts = local.metadata_path.str.extract(r"-([A-Z0-9]{4})(?:_R\d+C\d+)?-(\d+_\d+_P\d+)")
    return local.assign(item_id=parts[1] + "_" + parts[0]).dropna(subset=["item_id"]).drop_duplicates("item_id")


def legion_local_copies(footprints: Union[str, Path]) -> pd.Series:
    """Item id -> metadata path of each Legion product in the local footprints."""
    return _legion_footprints(footprints).set_index("item_id").metadata_path


def legion_radiometry(products: pd.DataFrame, footprints: Union[str, Path], have_dirs: Iterable[Path]) -> pd.DataFrame:
    """CSDA STAC shows both Legion versions as LV2A: only the .IMD tells them apart, so radiometry is known once a product
    is on ADAPT (footprints, or the .IMD of a download not in the footprints yet) and stays empty before that."""
    known = _legion_footprints(footprints).set_index("item_id").radiometric_type.dropna().to_dict()

    def from_imd(item_id):
        for d in have_dirs:
            for imd in (Path(d) / item_id).glob("*.IMD"):
                found = re.search(r'radiometricEnhancement\s*=\s*"([^"]+)"', imd.read_text(errors="ignore"))
                if found:
                    return found.group(1)
        return None

    raw = products.id.map(lambda i: known.get(i) or from_imd(i))
    return products.assign(radiometry=raw.map(lambda r: LEGION_RADIOMETRY.get(r, "other") if isinstance(r, str) else None))


def mark_on_adapt(products: pd.DataFrame, items: List[dict], have_dirs: Iterable[Path],
                  local_copies: pd.Series) -> pd.DataFrame:
    """Adds `on_adapt` per product: a folder <dir>/<item id>/ holds all of its assets (some files = an interrupted
    download, to resume), or the product is in the local footprints (`local_copies`, for other folder names)."""
    n_assets = {it["id"]: len(it["assets"]) for it in items}

    def complete(item_id):
        for d in have_dirs:
            folder = Path(d) / item_id
            if folder.is_dir() and sum(f.stat().st_size > 0 for f in folder.iterdir()) >= n_assets[item_id]:
                return True
        return False

    in_folder = {i: complete(i) for i in products.id.unique()}
    return products.assign(on_adapt=products.id.map(in_folder) | products.id.isin(local_copies.index))


def acquisitions_table(products: pd.DataFrame) -> pd.DataFrame:
    """One row per acquisition and site. `on_adapt`: at least one of its products is; `products_on_adapt` says how many."""
    join = lambda s: ", ".join(sorted(s.dropna().astype(str).unique()))
    agg = dict(sensor=("sensor", "first"), constellation=("constellation", "first"), acq_time=("acq_time", "min"),
               products=("id", "nunique"), products_on_adapt=("on_adapt", "sum"), on_adapt=("on_adapt", "any"),
               radiometry=("radiometry", join))
    agg.update({c: (c, "any") for c in ("new", "new_acquisition", "wanted") if c in products})
    return products.groupby(KEYS, as_index=False).agg(**agg).sort_values(["site_name", "acq_time"]).reset_index(drop=True)


def _run_files(out_dir: Union[str, Path]) -> Dict[str, Path]:
    return {re.search(r"(\d{8})", p.name).group(1): p for p in sorted(Path(out_dir, "runs").glob("products_*.csv"))}


def compare_with_last_run(products: pd.DataFrame, out_dir: Union[str, Path]) -> Tuple[pd.DataFrame, Optional[pd.Timestamp]]:
    """Adds `new` (product not in the last run) and `new_acquisition` (nor any product of its acquisition). The last run is
    the latest one before today, so re-running the same day gives the same answer. With no earlier run nothing is new."""
    today = pd.Timestamp.today().strftime("%Y%m%d")
    earlier = {k: v for k, v in _run_files(out_dir).items() if k < today}
    if not earlier:
        print(f"No earlier run in {out_dir}/runs: this run is the baseline, nothing counts as new")
        return products.assign(new=False, new_acquisition=False), None
    stamp = max(earlier)
    last = pd.read_csv(earlier[stamp], usecols=["id", "acquisition_id"])
    return (products.assign(new=~products.id.isin(last.id), new_acquisition=~products.acquisition_id.isin(last.acquisition_id)),
            pd.Timestamp(stamp))


def new_table(products: pd.DataFrame) -> pd.DataFrame:
    """The acquisitions with something new: `new_acquisition` False = a new product of an acquisition seen before."""
    new = products[products.new]
    table = acquisitions_table(new)
    return table[["site_name", "acquisition_id", "sensor", "acq_time", "products", "new_acquisition", "radiometry", "on_adapt"]]


def save_run(products: pd.DataFrame, out_dir: Union[str, Path], log: pd.DataFrame) -> Optional[Path]:
    """Saves this run's products for the next comparison. Not after failed searches: the next run would call
    everything they missed new."""
    if (log["status"] == "failed").any():
        print("Some searches failed: this run is not saved, so the next run compares with the last complete one")
        return None
    path = Path(out_dir, "runs", f"products_{pd.Timestamp.today():%Y%m%d}.csv")
    path.parent.mkdir(parents=True, exist_ok=True)
    products.drop(columns=["new", "new_acquisition"], errors="ignore").to_csv(path, index=False)
    return path


def _dates(times: pd.Series) -> str:
    first, last = f"{times.min():%Y-%m-%d}", f"{times.max():%Y-%m-%d}"
    return first if first == last else f"{first} – {last}"


def _sensors(acqs: pd.DataFrame) -> str:
    """LG01 (1), LG02 (2); with several constellations: Pleiades: PHR1A (3); SPOT: SPOT6 (1)."""
    groups = [(name, ", ".join(f"{s} ({n})" for s, n in sorted(g.drop_duplicates("acquisition_id").sensor.value_counts().items())))
              for name, g in acqs.groupby("constellation")]
    return "; ".join(f"{name}: {text}" for name, text in groups) if len(groups) > 1 else groups[0][1]


def _site_row(name: str, products: pd.DataFrame) -> dict:
    # Unique products and acquisitions: in the Total row, one that falls on two sites counts once
    one = products.drop_duplicates("id")
    per_acq = products.groupby("acquisition_id").radiometry.agg(lambda r: set(r.dropna()))
    acqs = products.drop_duplicates("acquisition_id")
    both = per_acq.map(lambda r: {"TOA", "SR"} <= r)
    return {"Site": name, "Acqs": products.acquisition_id.nunique(),
            "New": products.loc[products.new_acquisition, "acquisition_id"].nunique(),
            "On ADAPT": products.loc[products.on_adapt, "acquisition_id"].nunique(),
            "Products": len(one), "Products on ADAPT": int(one.on_adapt.sum()),
            "TOA only": int(per_acq.map(lambda r: "TOA" in r and "SR" not in r).sum()),
            "SR only": int(per_acq.map(lambda r: "SR" in r and "TOA" not in r).sum()), "TOA + SR": int(both.sum()),
            "Other": int(per_acq.map(lambda r: not r & {"TOA", "SR"}).sum()),
            "Sensors (acqs)": _sensors(acqs), "Acquired": _dates(products.acq_time)}


def site_table(products: pd.DataFrame) -> pd.DataFrame:
    """Per site and in total: what CSDA has, what is new and what is on ADAPT."""
    rows = [_site_row(name, g) for name, g in products.groupby("site_name")]
    rows.sort(key=lambda r: (-r["Acqs"], r["Site"]))
    return pd.DataFrame(rows + [_site_row("Total", products)])


def _spectral(mode: str, bands) -> str:
    return {"pan": "Pan", "ms": f"MS {bands:.0f}-band" if pd.notna(bands) else "MS",
            "pansharpened": f"Pansharpened {bands:.0f}-band" if pd.notna(bands) else "Pansharpened"}.get(mode, str(mode))


def _bands_text(products: pd.DataFrame) -> str:
    """Pan 0.35 m + MS 8-band 1.4 m: what was delivered, with its pixel size."""
    one = products.drop_duplicates("id")
    parts = one.assign(label=[_spectral(m, b) for m, b in zip(one.spectral_mode, one.bands)]).groupby("label").gsd.median()
    return " + ".join(f"{k} {v:.2g} m" for k, v in sorted(parts.items(), key=lambda kv: (kv[0] != "Pan", kv[0])))


def _radiometry_text(radiometry, labels: Dict[str, str]) -> str:
    return labels.get(radiometry, str(radiometry)) if isinstance(radiometry, str) else "Not known until on ADAPT"


def product_table(products: pd.DataFrame, labels: Dict[str, str]) -> pd.DataFrame:
    """What is available at each site, in plain terms: one row per satellite family, processing level and radiometry."""
    rows = []
    keys = ["site_name", "constellation", "processing_level", "radiometry"]
    for (site, family, level, radiometry), g in products.groupby(keys, dropna=False):
        rows.append({"Site": site, "Satellites": family, "Processing level": LEVELS.get(level, level),
                     "Radiometry": _radiometry_text(radiometry, labels), "Bands and pixel size": _bands_text(g),
                     "Acqs": g.acquisition_id.nunique(), "Products": g.id.nunique(), "Latest": f"{g.acq_time.max():%Y-%m-%d}"})
    return pd.DataFrame(rows)


def _new_page_table(products: pd.DataFrame, labels: Dict[str, str]) -> pd.DataFrame:
    """The new products, one row per acquisition and site, newest first, in plain terms."""
    rows = []
    for (site, acq), g in products[products.new].groupby(KEYS):
        delivered = "; ".join(f"{LEVELS.get(level, level)}, {_radiometry_text(r, labels)}: {_bands_text(p)}"
                              for (level, r), p in g.groupby(["processing_level", "radiometry"], dropna=False))
        rows.append({"Site": site, "Acquired": g.acq_time.min(), "Sensor": g.sensor.iloc[0], "Products delivered": delivered,
                     "Cloud %": g.cloud_cover.max(), "Off-nadir °": g.off_nadir.max(),
                     "What is new": "New acquisition" if g.new_acquisition.any() else "New product of an earlier acquisition",
                     "On ADAPT": f"{int(g.on_adapt.sum())} of {g.id.nunique()} products"})
    table = pd.DataFrame(rows, columns=["Site", "Acquired", "Sensor", "Products delivered", "Cloud %", "Off-nadir °",
                                        "What is new", "On ADAPT"])
    if table.empty:
        return table
    table = table.sort_values(["Site", "Acquired"]).reset_index(drop=True)
    return table.assign(Acquired=table.Acquired.dt.strftime("%Y-%m-%d"), **{"Cloud %": table["Cloud %"].round(0),
                        "Off-nadir °": table["Off-nadir °"].round(1)})


def _html_table(table: pd.DataFrame) -> str:
    def cell(value, tag, numeric):
        text = "–" if pd.isna(value) else (f"{value:g}" if isinstance(value, float) else str(value))
        return f"<{tag}{' class=n' if numeric else ''}>{html.escape(text)}</{tag}>"
    numeric = [pd.api.types.is_numeric_dtype(table[c]) for c in table.columns]
    head = "".join(cell(c, "th", n) for c, n in zip(table.columns, numeric))
    body = "\n".join(f"<tr{' class=tot' if row[0] == 'Total' else ''}>" + "".join(cell(v, "td", n) for v, n in zip(row, numeric))
                     + "</tr>" for row in table.itertuples(index=False))
    return f'<div class="wrap"><table><thead><tr>{head}</tr></thead><tbody>\n{body}\n</tbody></table></div>'


def _download_section(products: pd.DataFrame, plan: Optional[pd.DataFrame], check: Optional[pd.DataFrame],
                      download_dir: str) -> str:
    one = products.drop_duplicates("id")
    state = (f"{int(one.on_adapt.sum())} of {len(one)} products are on ADAPT, covering "
             f"{products[products.on_adapt].acquisition_id.nunique()} of {products.acquisition_id.nunique()} acquisitions.")
    if plan is None or plan.empty:
        return f"<p>{state} Nothing was downloaded in this run.</p>"
    done = plan if check is None else plan[plan.id.isin(check[check.complete].id)]
    if check is None:
        return f"<p>{state} {len(plan)} products ({plan.GB.sum():.1f} GB) are still to be downloaded.</p>"
    table = (done.groupby("site_name").agg(Acqs=("acquisition_id", "nunique"), Products=("id", "size"), GB=("GB", "sum"))
             .round(1).reset_index().rename(columns={"site_name": "Site"}))
    text = (f"<p>{state} This run downloaded {len(done)} of {len(plan)} products ({done.GB.sum():.1f} GB) "
            f"into <code>{html.escape(str(download_dir))}</code>.</p>")
    return text + _html_table(table)


def write_summary_page(products: pd.DataFrame, path: Union[str, Path], title: str, intro: str, notes: Iterable[str],
                       last_run: Optional[pd.Timestamp] = None, labels: Optional[Dict[str, str]] = None,
                       sites: Iterable[str] = (), coming: Optional[Tuple[str, pd.DataFrame]] = None,
                       other_page: Optional[Tuple[str, str]] = None, plan: Optional[pd.DataFrame] = None,
                       check: Optional[pd.DataFrame] = None, download_dir: str = "") -> Path:
    """The HTML summary for SMEs: 1. what is new, 2. what is available, 3. what is on ADAPT, then the products and
    processing levels at each site, what is still to come, and the vendor terms. `intro`, `notes` and the first item of
    `coming` are HTML; `coming` is (text, table); `other_page` is (title, file name)."""
    labels = labels or {}
    today = f"{pd.Timestamp.today():%-d %b %Y}"
    since = f"{last_run:%-d %b %Y}" if last_run is not None else "no earlier run"
    new = products[products.new]
    new_acqs = new[new.new_acquisition].acquisition_id.nunique()
    late = new[~new.new_acquisition].id.nunique()
    if last_run is None:
        new_text = "This is the first run, so nothing is compared yet."
    elif new.empty:
        new_text = f"Nothing new since the last run ({since})."
    else:
        new_text = (f"{new_acqs} new acquisitions" + (f" and {late} new products of earlier acquisitions" if late else "")
                    + f" since the last run ({since}), at {new.site_name.nunique()} sites: {', '.join(sorted(new.site_name.unique()))}. "
                    "CSDA STAC does not record delivery dates, so new means not in the last run's list. "
                    "An old acquisition delivered late counts as new.")
    empty = sorted(set(sites) - set(products.site_name))
    none_text = f"<p>No acquisitions in CSDA STAC yet at: {html.escape(', '.join(empty))}.</p>" if empty else ""
    terms = pd.DataFrame(TERMS, columns=["Aspect", "In plain words", "Airbus calls it", "Vantor Legion calls it"])
    term_rows = "\n".join("<tr>" + "".join(f"<td>{v}</td>" for v in row) + "</tr>" for row in terms.itertuples(index=False))
    term_head = "".join(f"<th>{c}</th>" for c in terms.columns)
    defined = ["<b>Acqs</b> = acquisitions in CSDA STAC at the site. <b>New</b> = not there at the last run. "
               "<b>On ADAPT</b> = at least one of its products is on ADAPT. <b>Other</b> = no TOA or SR product known."]
    items = "\n".join(f"<li>{n}</li>" for n in defined + list(notes))
    link = f'<p>Same summary for <a href="{other_page[1]}">{html.escape(other_page[0])}</a>.</p>' if other_page else ""
    still = f"<h2>Still to come</h2>\n<p>{coming[0]}</p>\n{_html_table(coming[1])}\n" if coming else ""
    new_table_html = _html_table(_new_page_table(products, labels)) if len(new) else ""
    page = f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)} ({today})</title>
<style>
{PAGE_STYLE}
</style></head><body>
<h1>{html.escape(title)}</h1>
<p class="meta">As of {today}. {intro}</p>
<h2>1. What is new</h2>
<p class="lead">{new_text}</p>
{new_table_html}
<h2>2. What is available</h2>
<p>Everything in CSDA STAC at these sites, by site.</p>
{_html_table(site_table(products))}
{none_text}
<h2>3. What is on ADAPT</h2>
{_download_section(products, plan, check, download_dir)}
<h2>Products and processing levels at each site</h2>
<p>What was delivered, in the terms explained below.</p>
{_html_table(product_table(products, labels))}
{still}<h2>What the vendor terms mean</h2>
<p>The vendors name the same things differently. <b>"TOA" is not the same on both</b>: Airbus pixels are already reflectance,
Vantor pixels still need converting.</p>
<div class="wrap"><table><thead><tr>{term_head}</tr></thead><tbody>
{term_rows}
</tbody></table></div>
<h2>Notes</h2>
<ul>
{items}
</ul>
{link}</body></html>
"""
    Path(path).write_text(page, encoding="utf-8")
    return Path(path)


def plan_download(products: pd.DataFrame, items: List[dict]) -> pd.DataFrame:
    """The wanted products not on ADAPT, one row each, with their size."""
    size = {it["id"]: sum(a.get("file:size") or 0 for a in it["assets"].values()) / 1e9 for it in items}
    plan = products[products.wanted & ~products.on_adapt].drop_duplicates("id").reset_index(drop=True)
    return plan.assign(GB=plan.id.map(size))


def download(plan: pd.DataFrame, items: List[dict], products: pd.DataFrame, download_dir: Union[str, Path],
             products_csv: Union[str, Path], credentials_file: Union[str, Path], do_download: bool = True,
             download_all: bool = True, max_workers: int = 8) -> Optional[pd.DataFrame]:
    """Downloads the plan into <download_dir>/<item id>/ (ILAB DEV kernel, for csda_client): every asset, or with
    download_all=False the metadata only. Files already there are kept, so a re-run resumes. Returns a table of the assets
    on disk per product, or None if nothing was fetched. `products_csv` keeps the site and acquisition of each product."""
    if plan.empty or not do_download:
        print("Nothing to download" if plan.empty else f"DO_DOWNLOAD = False: would download {len(plan)} products to {download_dir}")
        return None

    import configparser
    import pystac
    from httpx import BasicAuth
    from csda_client import CsdaClient
    import csdalib_download

    config = configparser.ConfigParser()
    config.read(Path(credentials_file).expanduser())
    client = CsdaClient.open(BasicAuth(username=config["EarthData"]["username"], password=config["EarthData"]["password"]))
    print("Auth:", client.verify())
    try:   # csda_client 0.1.0's Profile model fails on the current API response (missing 'nda_signed')
        for vendor in client.profile(config["EarthData"]["username"]).vendors:
            print(f"Quota: {vendor.vendor} {vendor.quota} {vendor.quota_unit}")
    except Exception as e:
        print(f"Quota table unavailable: {str(e)[:100]}")

    os.umask(0o022)   # JupyterLab's umask left folders owner-only
    download_dir = Path(download_dir)
    by_id = {it["id"]: it for it in items}
    stac_items = [pystac.Item.from_dict(by_id[i]) for i in plan.id]
    for item in stac_items:   # before the threads write to them
        (download_dir / item.id).mkdir(parents=True, exist_ok=True)

    rows = products[products.id.isin(plan.id)]
    if Path(products_csv).exists():
        rows = pd.concat([pd.read_csv(products_csv, low_memory=False), rows], ignore_index=True)
    rows.drop(columns="geometry", errors="ignore").drop_duplicates(["site_name", "id"], keep="last").to_csv(products_csv, index=False)

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        if download_all:
            futures = {pool.submit(csdalib_download.download_all_assets, item, client, download_dir / item.id,
                                   overwrite=False): item for item in stac_items}
        else:
            futures = {pool.submit(csdalib_download._process_one_item, item, client, download_dir / item.id): item
                       for item in stac_items}
        for future in as_completed(futures):
            try:
                future.result()
                print(f"Successfully processed: {futures[future].id}")
            except Exception as e:
                print(f"Error on {futures[future].id}: {e}")

    check = pd.DataFrame([{"id": i, "assets": len(by_id[i]["assets"]),
                           "files_on_disk": sum(f.stat().st_size > 0 for f in (download_dir / i).glob("*"))} for i in plan.id])
    return check.assign(complete=check.files_on_disk >= check.assets)


def results(vendor: str, products: pd.DataFrame, last_run: Optional[pd.Timestamp], page: Union[str, Path],
            plan: pd.DataFrame, check: Optional[pd.DataFrame] = None, do_download: bool = True) -> str:
    """The three results, as Markdown."""
    since = f"{last_run:%-m/%-d/%y}" if last_run is not None else None
    new = products[products.new]
    new_acqs = new[new.new_acquisition].acquisition_id.nunique()
    new_elsewhere = new[~new.new_acquisition]
    per_site = ", ".join(f"{k} {v}" for k, v in new.groupby("site_name").id.nunique().sort_values(ascending=False).items())
    late = f" and {new_elsewhere.id.nunique()} new products of earlier acquisitions" if len(new_elsewhere) else ""
    if since is None:
        first = "No earlier run to compare with: this run is the baseline."
    elif new.empty:
        first = f"Nothing new in CSDA STAC since the last run ({since})."
    else:
        first = (f"New in CSDA STAC since the last run ({since}): {new_acqs} acquisitions{late} "
                 f"({new.id.nunique()} products: {per_site}).")

    one = products.drop_duplicates("id")
    second = (f"HTML summary updated: `{page}`. CSDA STAC has {products.acquisition_id.nunique()} acquisitions at "
              f"{products.site_name.nunique()} sites; {products[products.on_adapt].acquisition_id.nunique()} are on ADAPT "
              f"({int(one.on_adapt.sum())} of {len(one)} products).")

    gb = f"{plan.GB.sum():.1f} GB" if plan.GB.sum() else "size not in the catalog"
    if plan.empty:
        third = "Download: nothing to fetch, every wanted product is on ADAPT."
    elif check is not None:
        done = int(check.complete.sum())
        third = f"Download: {done} of {len(check)} products complete ({gb})."
        if done < len(check):
            third += " Re-run to resume the rest."
        else:
            third += " Rerun `footprint_CSDA_eval_all_data.ipynb` to add them to the footprints."
    elif do_download:
        third = f"Download: {len(plan)} products ({gb}) still to fetch."
    else:
        third = f"Download: not run (`DO_DOWNLOAD = False`). {len(plan)} products ({gb}) would be fetched."

    skipped = one[~one.wanted & ~one.on_adapt]
    extra = f" Not wanted and not on ADAPT: {len(skipped)} products." if len(skipped) else ""
    return (f"**{vendor}, as of {pd.Timestamp.today():%-m/%-d/%y}**\n\n"
            f"1. {first}\n2. {second}\n3. {third}{extra}")
