"""Thumbnail viewer for acquisitions picked on the Vendor archive first look page.

Download a CSV from a first-look tab, then run:

    python lib/thumbnail_viewer.py legion-legion_good_acquisitions.csv

Each acquisition is looked up in its vendor's catalog at its site and date, and the vendor's preview image is fetched with your
credentials. The result is ONE private HTML file (images inside it, so it opens anywhere, JupyterLab included): a card per
acquisition showing the site up close, Keep and Drop buttons, a map with the whole preview over imagery, and an export of what you
kept. Nothing is published: vendor previews need your login and may not be shared publicly.

Placement: Vantor's previews are GeoTIFFs and sit exactly. The other vendors' previews are plain images, placed on the scene's
bounding box, which is close for north-up products but approximate.
"""
from __future__ import annotations

import base64
import io
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
import requests
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).parent))
import multistac  # noqa: E402
import stac_auth  # noqa: E402
from archive_dashboard import vendor_palette  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
SITES = REPO / "sites" / "csda_sites_aoi.geojson"
OUT = Path("/explore/nobackup/people/pmontesa/multistac/thumbnails")
TEMPLATE = Path(__file__).with_name("thumbnail_viewer_template.html")

# First-look tab (the CSV name starts with it) -> where its previews are: provider, collections, preview assets by preference.
SOURCES = {
    "hydrosat": dict(vendor="Hydrosat", provider="hydrosat", collections=["vz-l1b", "vz-l1b-night"], assets=["THUMBNAIL", "PREVIEW"]),
    "kuva": dict(vendor="Kuva Space", provider="kuva", collections=None, assets=[]),
    "satellogic": dict(vendor="Satellogic", provider="satellogic", collections=["quickview-visual"], assets=["preview", "thumbnail"]),
    "legion": dict(vendor="Vantor", provider="vantor", collections=["lg01", "lg02", "lg03", "lg04", "lg05", "lg06"], assets=["browse"]),
    "worldview": dict(vendor="Vantor", provider="vantor", collections=["wv02", "wv03-vnir"], assets=["browse"]),
    "planet": dict(vendor="Planet", provider="planet", collections=["PSScene", "TanagerScene"], assets=["thumbnail"]),
}
MAX_ITEMS = 16      # scenes or tiles of one acquisition drawn at most, those covering most of the site first
CROP_PX = 360       # longest side of the close-up of the site
WHOLE_PX = 640      # longest side of the whole preview (shown on the map)


# --- catalog lookup ---------------------------------------------------------------------------------------------------------

def _matches(found: pd.DataFrame, row, site_geom) -> tuple:
    """The catalog items of one CSV acquisition: by its ID, else (Legion: CSDA names a pass differently) same sensor and date."""
    hit = found[found.acquisition_id.astype(str) == str(row.acquisition_id)]
    how = "id"
    if hit.empty and len(found):
        day = pd.to_datetime(found.datetime, utc=True, errors="coerce").dt.strftime("%Y-%m-%d")
        same = found[(found.sensor.astype(str).str.upper() == str(row.sensor).upper()) & (day == row.date)]
        if len(same):
            best = same.assign(_o=same.geometry.intersection(site_geom).area).groupby("acquisition_id")._o.sum().idxmax()
            hit, how = same[same.acquisition_id == best], "sensor and date"
    if len(hit):
        hit = hit.assign(_o=hit.geometry.intersection(site_geom).area).sort_values("_o", ascending=False).head(MAX_ITEMS)
    return hit, how


def _search(source: dict, site, date: str) -> pd.DataFrame:
    day = pd.Timestamp(date)
    found = multistac.search(site, f"{day - pd.Timedelta(days=1):%Y-%m-%d}", f"{day + pd.Timedelta(days=1):%Y-%m-%d}",
                             {source["provider"]: source["collections"]}, include_assets=True, compact=False, progress=False,
                             max_workers=2).gdf
    return found.drop_duplicates("id") if len(found) else found


# --- images -----------------------------------------------------------------------------------------------------------------

def _get(session, url: str, headers: dict) -> Optional[bytes]:
    signed = "X-Amz-" in url or "Signature=" in url        # a signed link carries its own access; a login header would break it
    for _ in range(3):
        try:
            r = session.get(url, headers={} if signed else headers, timeout=60)
            if r.ok:
                return r.content
            if r.status_code < 500 and r.status_code != 429:
                return None
        except requests.RequestException:
            pass
    return None


def _decode(data: bytes, geometry) -> Optional[tuple]:
    """(RGBA image, (west, south, east, north), exact placement?)"""
    if data[:4] in (b"II*\x00", b"MM\x00*"):                 # GeoTIFF: read in lon/lat
        import rasterio
        from rasterio.io import MemoryFile
        from rasterio.vrt import WarpedVRT
        with MemoryFile(data) as mem, mem.open() as src, WarpedVRT(src, crs="EPSG:4326") as vrt:
            bands = vrt.read(list(range(1, min(vrt.count, 3) + 1)), masked=True)
            bounds = tuple(vrt.bounds)
        bands = np.ma.concatenate([bands] * 3) if bands.shape[0] == 1 else bands
        if bands.dtype != np.uint8:
            lo, hi = np.percentile(bands.compressed(), [2, 98]) if bands.count() else (0, 1)
            bands = np.ma.clip((bands - lo) / max(hi - lo, 1e-9) * 255, 0, 255)
        alpha = (~np.ma.getmaskarray(bands).any(0) & (bands.filled(0).sum(0) > 0)) * 255
        rgba = np.dstack([bands.filled(0).astype(np.uint8).transpose(1, 2, 0), alpha.astype(np.uint8)])
        return Image.fromarray(rgba, "RGBA"), bounds, True
    try:
        image = Image.open(io.BytesIO(data)).convert("RGBA")
    except Exception:
        return None
    pixels = np.asarray(image).copy()
    pixels[..., 3] = np.where(pixels[..., :3].max(-1) <= 2, 0, pixels[..., 3])   # black no-data edges see through to what is below
    image = Image.fromarray(pixels, "RGBA")
    filled = image.getchannel("A").getbbox()       # some previews pad the scene (Planet's are square): its data spans the footprint
    return (image.crop(filled) if filled else image), tuple(geometry.bounds), False


def _compose(pieces: List[tuple], extent: tuple, longest: int) -> Optional[Image.Image]:
    """Place images by their lon/lat bounds on one canvas over `extent`, at the finest resolution available up to `longest` px."""
    w, s, e, n = extent
    shrink = np.cos(np.radians((s + n) / 2))                  # a degree of longitude is shorter away from the equator
    finest = min((b[3] - b[1]) / im.height for im, b, _ in pieces)
    width, height = (e - w) * shrink / finest, (n - s) / finest
    scale = min(1.0, longest / max(width, height))
    width, height = max(1, round(width * scale)), max(1, round(height * scale))
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    for image, (bw, bs, be, bn), _ in reversed(pieces):        # the item covering most of the site last, on top
        cw, cs, ce, cn = max(w, bw), max(s, bs), min(e, be), min(n, bn)
        if ce <= cw or cn <= cs:
            continue
        sx, sy = image.width / (be - bw), image.height / (bn - bs)
        part = image.crop((round((cw - bw) * sx), round((bn - cn) * sy), round((ce - bw) * sx), round((bn - cs) * sy)))
        tx, ty = width / (e - w), height / (n - s)
        box = (round((cw - w) * tx), round((n - cn) * ty), round((ce - w) * tx), round((n - cs) * ty))
        if box[2] > box[0] and box[3] > box[1] and part.width and part.height:
            canvas.alpha_composite(part.resize((box[2] - box[0], box[3] - box[1]), Image.BILINEAR), box[:2])
    return canvas if canvas.getbbox() else None


def _outline(image: Image.Image, extent: tuple, geometry) -> Image.Image:
    w, s, e, n = extent
    draw = ImageDraw.Draw(image)
    polygons = getattr(geometry, "geoms", [geometry])
    for poly in polygons:
        xy = [((x - w) / (e - w) * image.width, (n - y) / (n - s) * image.height) for x, y in poly.exterior.coords]
        draw.line(xy, fill=(0, 0, 0, 255), width=4)
        draw.line(xy, fill=(255, 255, 255, 255), width=2)
    return image


def _jpeg(image: Image.Image) -> str:
    flat = Image.new("RGB", image.size, (58, 58, 56))
    flat.paste(image, mask=image.split()[3])
    buffer = io.BytesIO()
    flat.save(buffer, "JPEG", quality=80)
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode()


def _site_extent(geometry) -> tuple:
    w, s, e, n = geometry.bounds
    pad = max((e - w), (n - s), 0.02) * 0.5                   # the site and half its size around it, at least ~1 km
    return w - pad, s - pad, e + pad, n + pad


# --- one acquisition --------------------------------------------------------------------------------------------------------

def preview(source: dict, session, headers: dict, row, site, found: pd.DataFrame) -> dict:
    site_geom = site.geometry.iloc[0]
    out = {"found": 0, "how": None, "exact": None, "crop": None, "whole": None, "bounds": None}
    if found is None or found.empty or not source["assets"]:
        return out
    items, how = _matches(found, row, site_geom)
    out.update(found=int(len(items)), how=how)
    pieces = []
    for _, item in items.iterrows():
        href = next((item.get(f"asset_{a}_href") for a in source["assets"]
                     if isinstance(item.get(f"asset_{a}_href"), str) and item.get(f"asset_{a}_href").startswith("http")), None)
        if not href:
            continue
        data = _get(session, href, headers)
        decoded = _decode(data, item.geometry) if data else None
        if decoded:
            pieces.append(decoded)
    if not pieces:
        return out
    extent = _site_extent(site_geom)
    crop = _compose(pieces, extent, CROP_PX)
    whole_extent = (min(b[0] for _, b, _ in pieces), min(b[1] for _, b, _ in pieces),
                    max(b[2] for _, b, _ in pieces), max(b[3] for _, b, _ in pieces))
    whole = _compose(pieces, whole_extent, WHOLE_PX)
    out.update(exact=all(x for _, _, x in pieces),
               crop=_jpeg(_outline(crop, extent, site_geom)) if crop else None,
               whole=None if whole is None else "data:image/png;base64," + base64.b64encode(_png(whole)).decode(),
               bounds=[[whole_extent[1], whole_extent[0]], [whole_extent[3], whole_extent[2]]])
    return out


def _png(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.quantize(255, method=Image.FASTOCTREE).save(buffer, "PNG", optimize=True)   # keeps the transparent edges
    return buffer.getvalue()


# --- the page ---------------------------------------------------------------------------------------------------------------

def tab_of(csv: Path) -> str:
    return csv.name.split("-")[0].split("_")[0].lower()


def build(csv, out: Optional[Path] = None, tab: Optional[str] = None, limit: Optional[int] = None,
          sites=SITES, site_name_field: str = "Site Name", workers: int = 4) -> Path:
    """Look up every acquisition in `csv` (a first-look download) and write the viewer page. Returns its path."""
    csv = Path(csv)
    tab = tab or tab_of(csv)
    if tab not in SOURCES:
        raise ValueError(f"Can't tell the vendor from {csv.name}; pass tab= one of {sorted(SOURCES)}")
    source = SOURCES[tab]
    rows = pd.read_csv(csv, dtype=str).fillna("")
    if limit:
        rows = rows.head(limit)
    site_table = multistac.load_sites(str(sites), site_name_field=site_name_field)
    missing = sorted(set(rows.site) - set(site_table.site_name))
    if missing:
        print("Sites not in the sites file, skipped:", ", ".join(missing))
        rows = rows[~rows.site.isin(missing)]
    session = requests.Session()
    headers = stac_auth.make_auth(multistac.get_provider(source["provider"]).profile).headers() if source["assets"] else {}

    groups = list(rows.groupby(["site", "date"]).groups.items())   # one catalog search per site and day
    results: Dict[int, dict] = {}

    def run(group):
        (site_name, date), index = group
        site = site_table[site_table.site_name == site_name]
        try:
            found = _search(source, site, date) if source["assets"] else None
        except Exception as error:                       # a failed search shows as "not found" on its cards
            print(f"  search failed: {site_name} {date}: {str(error)[:120]}")
            found = None
        return {i: preview(source, session, headers, rows.loc[i], site, found) for i in index}

    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for part in pool.map(run, groups):
            results.update(part)
            done += 1
            if done % 20 == 0 or done == len(groups):
                print(f"  {done} of {len(groups)} site-days, {sum(1 for r in results.values() if r['crop'])} previews", flush=True)

    sites_used = site_table[site_table.site_name.isin(rows.site)]
    outlines = {r.site_name: [[[round(y, 5), round(x, 5)] for x, y in p.exterior.coords] for p in getattr(r.geometry, "geoms", [r.geometry])]
                for r in sites_used.itertuples()}
    cards = [dict(row=rows.loc[i].to_dict(), **results.get(i, {})) for i in rows.index]
    data = {"title": csv.stem, "tab": tab, "vendor": source["vendor"], "palette": vendor_palette(source["vendor"]),
            "columns": list(rows.columns), "cards": cards, "sites": outlines, "has_previews": bool(source["assets"]),
            "made": f"{pd.Timestamp.today():%-d %b %Y}"}
    out = Path(out) if out else OUT / f"{csv.stem}_thumbnails.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    page = TEMPLATE.read_text(encoding="utf-8").replace("/*DATA*/null", json.dumps(data, separators=(",", ":")).replace("</", "<\\/"))
    out.write_text(page, encoding="utf-8")
    shown = sum(1 for c in cards if c.get("crop"))
    print(f"{out}  {out.stat().st_size / 1e6:.1f} MB  {shown} of {len(cards)} acquisitions with a preview")
    return out


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("csv", help="a CSV downloaded from the Vendor archive first look page")
    parser.add_argument("--out", help=f"output HTML (default: {OUT}/<csv name>_thumbnails.html)")
    parser.add_argument("--tab", choices=sorted(SOURCES), help="vendor, if the CSV was renamed")
    parser.add_argument("--limit", type=int, help="only the first N acquisitions (the CSV lists good ones first)")
    args = parser.parse_args()
    build(args.csv, args.out, args.tab, args.limit)
