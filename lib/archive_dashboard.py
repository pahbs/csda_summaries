"""The archive first-look dashboard: one tab per vendor constellation, the same layout in every tab.

Each multistac_site_analysis_<vendor>.ipynb ends with

    archive_dashboard.publish('kuva', dash.gdf, sites, SITES, SITE_NAME_FIELD, START, END, dash.log)

where `sites` is the same set for every tab: load_sites(), the CSDA sites for optical or thermal validation.

which writes <data repo>/archive_first_look/<tab>.json and rebuilds html/archive_first_look.html from every tab's file
(the data files are published from their own repository: see data_repo.py).
`dash` is a search with no cloud limit, since the SMEs set the limits on the page.

The unit is one acquisition at one site, whatever the catalog calls an item, so vendors can be compared:

- the items of an acquisition at a site (levels, products or Satellogic's 2 km tiles) become one row;
- `cov` is the share of the site's AOI inside the union of those items' footprints;
- `cloud` and the angles are averaged over the items, weighted by their area inside the AOI, so a tiled vendor's cloud
  cover describes the tiles at the site and a whole-scene vendor's describes the scene.
"""

from __future__ import annotations

import json
import sys
import math
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Union

import geopandas as gpd
import pandas as pd
from shapely import affinity
from shapely.ops import unary_union

sys.path.insert(0, str(Path(__file__).parent))
import data_repo  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
DATA_DIR = data_repo.folder("archive_first_look")
PAGE = REPO / "html" / "archive_first_look.html"
TEMPLATE = Path(__file__).with_name("archive_dashboard_template.html")
LAND = Path(__file__).with_name("archive_dashboard_land.txt")
INDEX = "index.json"   # the tab summaries, in DATA_DIR

# The sites every tab covers: CSDA evaluation sites for optical or thermal validation (Remote Sensing Domain contains
# Optical or Thermal), as whole sites, not the corner-reflector points inside some of them.
SITES = str(REPO / "sites" / "csda_sites_aoi.geojson")
SITE_NAME_FIELD = "Site Name"
SITE_FILTERS = {"Remote Sensing Domain": lambda s: s.str.contains("Optical|Thermal", case=False, na=False),
                "feature_type": ["site"]}


def load_sites() -> gpd.GeoDataFrame:
    """The first-look sites (SITES with SITE_FILTERS), named by SITE_NAME_FIELD."""
    import multistac
    return multistac.load_sites(SITES, site_name_field=SITE_NAME_FIELD, filters=SITE_FILTERS)

# What differs between vendors, for the SMEs. Levels are in processing order.
VENDORS = {
    "hydrosat": dict(
        vendor="Hydrosat", bands="VNIR and thermal",
        acquisition="One scene (<code>hydrosat:scene_id</code>). Its L1B and L2 products count once.",
        footprint="One footprint per scene, the same at every level.",
        cloud="For the whole scene, so a cloudy scene can still be clear over a small site.", cloud_scope="scene",
        levels={"L1B": "Combined thermal and VNIR data", "L2": "Surface temperature and surface reflectance"},
        scope="L1B and L2 by day, and nighttime L1B (thermal only). Night scenes have no cloud cover, so the cloud test does not "
              "apply to them. L1A has no cloud cover and is left out: a scene's L1A shares its <code>hydrosat:scene_id</code>, so "
              "what is shown here holds for its L1A."),
    "kuva": dict(
        vendor="Kuva Space", bands="Hyperspectral",
        acquisition="One capture (<code>raw_product_landing_id</code>). Its L1B, L1C and L2A products count once.",
        footprint="One footprint per capture.",
        cloud="For the whole capture, so a cloudy capture can still be clear over a small site.", cloud_scope="scene",
        levels={"L1B": "Level 1B", "L1C": "Level 1C", "L2A": "Level 2A"},
        scope="Kuva Sense reports cloud cover but no view or sun angles, so those tests are off for this tab."),
    "satellogic": dict(
        vendor="Satellogic", bands="Visual quickview, about 0.78 m",
        acquisition="One capture (<code>satl:outcome_id</code>). The catalog cuts a capture into 2 km tiles, and all its "
                    "tiles at a site count as one acquisition.",
        footprint="Search returns only the tiles touching the site, not the whole capture, so the footprint is the union of "
                  "those tiles. Square tiles overshoot the strip edges, which can slightly overstate site coverage.",
        cloud="For the tiles at the site, weighted by their area there, so it is closer to the site than a whole-scene value.",
        cloud_scope="site",
        levels={"QUICKVIEW_VISUAL": "Archive quickview tiles, for browsing", "L1D_SR": "Surface reflectance, held by CSDA"},
        scope="Archive discovery shows quickview tiles. Which levels (L1C, L1D, L1D_SR) can be ordered for a capture is not "
              "shown by search."),
    "legion": dict(
        vendor="Vantor", bands="Pan about 0.35 m, 8-band MS about 1.4 m", match_seconds=120,
        acquisition="One satellite pass. Vantor's catalog and CSDA give a pass different IDs, so records of the same sensor within "
                    "120 seconds are matched and count once.",
        footprint="One strip per pass in Vantor's catalog. CSDA delivers products cut to the order.",
        cloud="For the whole strip, so a cloudy strip can still be clear over a small site.", cloud_scope="scene",
        levels={"LV2A": "Standard: map-projected, coarse DEM (CSDA)", "LV3D": "Ortho: fine DEM (CSDA)"},
        scope="Vantor's catalog shows everything collected; set Source to In CSDA to see what has been delivered. Vantor's catalog "
              "does not list levels, so levels are shown for CSDA products only."),
    "planet": dict(
        vendor="Planet", bands="", cloud_scope="scene", levels={}, csda_checked=False,
        acquisition="One strip (<code>pl:strip_id</code>): a pass is delivered as a run of short scenes, and the scenes of one strip "
                    "at a site count as one acquisition.",
        footprint="The union of the strip's scenes that touch the site.",
        cloud="For each scene, averaged over the scenes at the site by their area there; each scene's value covers the whole scene.",
        scope="Planet's own catalog. CSDA also holds PlanetScope data (CSDA STAC <code>planet</code> collection), which this tab "
              "does not check yet, so In CSDA is not shown.",
        by_constellation={
            "SuperDove": dict(bands="PlanetScope SuperDove: 8-band multispectral, about 3 m",
                              scope="Planet's own catalog, SuperDove only (instrument <code>PSB.SD</code>); earlier Dove generations are "
                                    "left out. CSDA also holds PlanetScope data (CSDA STAC <code>planet</code> collection), not checked "
                                    "here yet. This tab is large, so it loads when opened."),
            "Tanager": dict(bands="Tanager: hyperspectral, about 30 m")}),
    "worldview": dict(
        vendor="Vantor", bands="WorldView-2 and WorldView-3, since 2020",
        acquisition="One catalog strip (Vantor catalog ID).",
        footprint="One strip per acquisition in Vantor's catalog.",
        cloud="For the whole strip, so a cloudy strip can still be clear over a small site.", cloud_scope="scene",
        levels={}, csda_checked=False,
        scope="Vantor's own catalog (<code>wv02</code>, <code>wv03-vnir</code>): what has been collected. CSDA holds WorldView data in "
              "Earthdata CMR, which this tab does not check yet, so In CSDA is not shown. Added year by year, newest first."),
    # Ready for when catalog access starts (stac_providers.yaml: airbus, earthdaily); check these descriptions against real items then
    "airbus": dict(
        vendor="Airbus", bands="Pleiades and Pleiades Neo (pan 0.3-0.5 m, MS 1.2-2 m), SPOT 6/7 (pan 1.5 m, MS 6 m)",
        acquisition="One acquisition: its pan and multispectral products count once.",
        footprint="One footprint per acquisition.",
        cloud="For the whole scene, so a cloudy scene can still be clear over a small site.", cloud_scope="scene",
        levels={"ORT": "Ortho (CSDA)", "PRJ": "Projected", "SEN": "Sensor geometry"},
        scope="Airbus's own catalog (OneAtlas), with CSDA's <code>airbus-optical</code> holdings marked In CSDA."),
    "earthdaily": dict(
        vendor="EarthDaily", bands="EarthDaily constellation: multispectral, VNIR to thermal",
        acquisition="One scene.",
        footprint="One footprint per scene.",
        cloud="For the whole scene, so a cloudy scene can still be clear over a small site.", cloud_scope="scene",
        levels={}, csda_checked=False,
        scope="EarthDaily's own catalog (EarthPlatform STAC)."),
}


def _flat(geometry, lat: float):
    """Longitudes scaled to their length at this latitude, so areas compare without a projection."""
    return affinity.scale(geometry, xfact=math.cos(math.radians(lat)), yfact=1, origin=(0, 0))


def _number(value, digits: int = 1) -> Optional[float]:
    return None if value is None or pd.isna(value) else round(float(value), digits)


def _weighted(rows: pd.DataFrame, column: str, weights: pd.Series) -> Optional[float]:
    if column not in rows:
        return None
    values = pd.to_numeric(rows[column], errors="coerce")
    known = values.notna() & (weights > 0)
    if known.any():
        return float((values[known] * weights[known]).sum() / weights[known].sum())
    return float(values.mean()) if values.notna().any() else None


def merge_passes(gdf: gpd.GeoDataFrame, seconds: float) -> gpd.GeoDataFrame:
    """One acquisition_id per pass when catalogs name it differently: records of a sensor this close in time, CSDA's id first."""
    times = pd.to_datetime(gdf["datetime"].map(pd.Timestamp), utc=True)
    order = gdf.assign(_t=times).sort_values(["sensor", "_t"])
    gap = order.groupby("sensor")._t.diff().dt.total_seconds()
    order["_pass"] = (gap.isna() | (gap > seconds)).cumsum()
    first = order.sort_values(["_pass", "provider"]).groupby("_pass").acquisition_id.first()   # 'csda' sorts first
    return gdf.assign(acquisition_id=order._pass.map(first).reindex(gdf.index))


def _time_of_day(rows: pd.DataFrame) -> Optional[str]:
    """As the catalog says, or from the sun where it does not."""
    if "hydrosat:day_night" in rows and rows["hydrosat:day_night"].notna().any():
        return str(rows["hydrosat:day_night"].dropna().iloc[0]).lower()
    sun = pd.to_numeric(rows.get("sun_elevation"), errors="coerce") if "sun_elevation" in rows else None
    return None if sun is None or sun.isna().all() else ("day" if sun.mean() > 0 else "night")


def _rings(geometry, tolerance: float) -> List[List[List[float]]]:
    """Outer rings of a polygon or multipolygon as [[lon, lat], ...] lists, simplified, for the page's maps."""
    if geometry is None or geometry.is_empty:
        return []
    geometry = geometry.simplify(tolerance, preserve_topology=True)
    polygons = list(geometry.geoms) if geometry.geom_type in ("MultiPolygon", "GeometryCollection") else [geometry]
    return [[[round(x, 4), round(y, 4)] for x, y in p.exterior.coords] for p in polygons if p.geom_type == "Polygon"]


def acquisitions(gdf: gpd.GeoDataFrame, sites: gpd.GeoDataFrame, levels: List[str], sensors: List[str],
                 site_names: List[str]):
    """One record per acquisition and site, and each record's whole footprint (not clipped to the site)."""
    aoi = {}
    for name, geometry in zip(sites.site_name, sites.geometry):
        lat = geometry.centroid.y
        aoi[name] = (_flat(geometry.buffer(0), lat), lat)
    times = pd.to_datetime(gdf["datetime"].map(pd.Timestamp), utc=True)
    records, footprints = [], []
    for (site, acquisition), rows in gdf.assign(_t=times).groupby(["site_name", "acquisition_id"]):
        if site not in aoi:
            continue
        shape, lat = aoi[site]
        parts = [_flat(g.buffer(0), lat).intersection(shape) if g is not None else None for g in rows.geometry]
        weights = pd.Series([p.area if p is not None else 0.0 for p in parts], index=rows.index)
        union = unary_union([p for p in parts if p is not None and not p.is_empty])
        held = rows.provider.eq("csda").any() or ("in_csda" in rows and rows.in_csda.fillna(False).astype(bool).any())
        records.append({
            "s": site_names.index(site), "n": sensors.index(rows.sensor.iloc[0]), "a": str(acquisition),
            "d": f"{rows._t.min():%Y-%m-%d}", "cloud": _number(_weighted(rows, "cloud_cover", weights)),
            "off": _number(_weighted(rows, "off_nadir", weights)),
            "cov": _number(100 * min(union.area / shape.area, 1.0), 0) if shape.area else None,
            "sun": _number(_weighted(rows, "sun_elevation", weights)), "sunaz": _number(_weighted(rows, "sun_azimuth", weights)),
            "az": _number(_weighted(rows, "sat_azimuth", weights)), "el": _number(_weighted(rows, "sat_elevation", weights)),
            "items": int(rows.id.nunique()), "lv": sorted({levels.index(v) for v in rows.processing_level if v in levels}),
            "csda": bool(held), "dn": _time_of_day(rows)})
        footprints.append(_rings(unary_union([g.buffer(0) for g in rows.geometry if g is not None]), 0.001))
    return records, footprints


def _site_table(sites: gpd.GeoDataFrame, sites_file: Union[str, Path], name_field: str) -> List[dict]:
    """Each site's place and its own requirements from the sites file, where it has them."""
    limits = gpd.read_file(sites_file).drop_duplicates(name_field).set_index(name_field)
    out = []
    for name, geometry in zip(sites.site_name, sites.geometry):
        row = limits.loc[name] if name in limits.index else {}
        point = geometry.representative_point()
        out.append({"name": name, "lon": round(point.x, 3), "lat": round(point.y, 3),
                    "cloud": _number(row.get("max_cloud_pct_aoi")), "scene": _number(row.get("max_cloud_pct_scene")),
                    "off": _number(row.get("max_view_angle")),
                    "need": _number(row.get("min_num_acqs"), 0), "ideal": _number(row.get("ideal_num_acqs"), 0)})
    return sorted(out, key=lambda s: s["name"].lower())


def tab_data(vendor: str, gdf: gpd.GeoDataFrame, sites: gpd.GeoDataFrame, sites_file: Union[str, Path], name_field: str,
             start: str, end: str, log: pd.DataFrame, constellation: str) -> dict:
    info = {**VENDORS[vendor], **VENDORS[vendor].get("by_constellation", {}).get(constellation, {})}
    gdf = gdf[gdf.constellation.eq(constellation)]
    if info.get("match_seconds"):
        gdf = merge_passes(gdf, info["match_seconds"])
    known = [k for k in info["levels"] if k in set(gdf.processing_level)]
    levels = known + sorted(set(gdf.processing_level.dropna()) - set(known))
    sensors = sorted(gdf.sensor.dropna().unique())
    site_rows = _site_table(sites, sites_file, name_field)
    records, footprints = acquisitions(gdf, sites, levels, sensors, [s["name"] for s in site_rows])
    outline = dict(zip(sites.site_name, sites.geometry))
    fp = {"sites": [_rings(outline[s["name"]].buffer(0), 0.0002) for s in site_rows], "acqs": footprints}
    failed = sorted(log.loc[log["status"] == "failed", "site_name"].dropna().unique())
    return {"key": f"{vendor}-{constellation}".lower().replace(" ", "-"), "vendor": info["vendor"], "constellation": constellation,
            "bands": info["bands"], "acquisition": info["acquisition"], "footprint": info["footprint"], "cloud": info["cloud"],
            "cloud_scope": info["cloud_scope"], "csda_checked": info.get("csda_checked", True),
            "scope": info["scope"], "searched": f"{pd.Timestamp.today():%-d %b %Y}", "start": start, "end": end,
            "failed": failed, "items": int(gdf.id.nunique()),
            "levels": [{"code": k, "plain": info["levels"].get(k, "")} for k in levels],
            "sensors": sensors, "sites": site_rows, "acqs": records}, fp


def build(page: Path = PAGE, data_base: str = data_repo.DATA_URL + "archive_first_look/") -> Path:
    """The tab summaries (<data repo>/archive_first_look/index.json, from every tab's data file) and the page, which reads
    them from `data_base`. The page itself only changes with the template, so a daily refresh touches the data repo only."""
    tabs = sorted((json.loads(p.read_text(encoding="utf-8")) for p in DATA_DIR.glob("*.json") if p.name != INDEX),
                  key=lambda t: (t["vendor"], t["constellation"]))   # a vendor's constellations side by side
    for t in tabs:
        t["palette"] = vendor_palette(t["vendor"])
        if len(t["acqs"]) > LAZY_ROWS:   # the page reads them from the tab's data file when the tab is opened
            t["rows"], t["acqs"], t["lazy"] = len(t["acqs"]), None, True
    (DATA_DIR / INDEX).write_text(json.dumps({"tabs": tabs, "land": LAND.read_text(encoding="utf-8").strip(),
                                              "updated": f"{pd.Timestamp.today():%-d %b %Y}"}, separators=(",", ":")), encoding="utf-8")
    html = TEMPLATE.read_text(encoding="utf-8").replace("/*DATA*/null", json.dumps({"index": True, "data_base": data_base}))
    page.write_text(html, encoding="utf-8")
    return page


def write_footprints(tab: dict, fp: dict, folder: Path) -> None:
    """One file per site (<folder>/<site index>.json): opening a site loads only its footprints."""
    folder.mkdir(parents=True, exist_ok=True)
    for old in folder.glob("*.json"):
        old.unlink()
    by_site: Dict[int, dict] = {}
    for i, (record, rings) in enumerate(zip(tab["acqs"], fp["acqs"])):
        by_site.setdefault(record["s"], {})[i] = rings
    for s, acqs in by_site.items():
        (folder / f"{s}.json").write_text(json.dumps({"site": fp["sites"][s], "acqs": acqs}, separators=(",", ":")), encoding="utf-8")


LAZY_ROWS = 40000   # tabs bigger than this load their acquisitions when opened


def publish(vendor: str, gdf: gpd.GeoDataFrame, sites: gpd.GeoDataFrame, sites_file: Union[str, Path], name_field: str,
            start: str, end: str, log: pd.DataFrame, data_dir: Path = DATA_DIR, page: Path = PAGE) -> Path:
    """Writes this vendor's tabs, one per constellation, and rebuilds the page."""
    Path(data_dir).mkdir(parents=True, exist_ok=True)
    for constellation in sorted(gdf.constellation.dropna().unique()):
        tab, fp = tab_data(vendor, gdf, sites, sites_file, name_field, start, end, log, constellation)
        (Path(data_dir) / f"{tab['key']}.json").write_text(json.dumps(tab, separators=(",", ":")), encoding="utf-8")
        write_footprints(tab, fp, Path(data_dir) / "fp" / tab["key"])
        print(f"{tab['vendor']} {constellation}: {len(tab['acqs'])} acquisition-site rows, {tab['items']} catalog items, "
              f"{len(tab['sites'])} sites")
    built = build(page)
    print(built)
    return built


# Vendor colors, shared with the Vendor Specs page (vendor_specs.AFFILIATION_COLORS). The exact color marks the vendor;
# data marks use a light-to-dark ramp of its hue, so light colors such as Vantor's cyan still contrast with the page.
AFFILIATION = {"Hydrosat": "HydroSat", "Kuva Space": "Kuva", "Satellogic": "Satellogic", "Vantor": "Vantor", "Planet": "Planet Labs",
               "Airbus": "Airbus", "EarthDaily": "EarthDaily"}
RAMP_L = {"light": [0.90, 0.82, 0.73, 0.64, 0.55, 0.46, 0.37], "dark": [0.40, 0.48, 0.56, 0.65, 0.74, 0.83, 0.91],
          # maps: the lightest step is one acquisition, so it starts darker and must stand out from the page
          "map_light": [0.73, 0.65, 0.57, 0.49, 0.41, 0.33], "map_dark": [0.52, 0.60, 0.68, 0.76, 0.84, 0.92]}


def _to_oklch(hex_color: str):
    r, g, b = [int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in (r, g, b)]
    l_ = (0.4122214708 * lin[0] + 0.5363325363 * lin[1] + 0.0514459929 * lin[2]) ** (1 / 3)
    m_ = (0.2119034982 * lin[0] + 0.6806995451 * lin[1] + 0.1073969566 * lin[2]) ** (1 / 3)
    s_ = (0.0883024619 * lin[0] + 0.2817188376 * lin[1] + 0.6299787005 * lin[2]) ** (1 / 3)
    L = 0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_
    a = 1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_
    bb = 0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_
    return L, math.hypot(a, bb), math.atan2(bb, a)


def _from_oklch(L: float, C: float, h: float):
    a, b = C * math.cos(h), C * math.sin(h)
    l_, m_, s_ = L + 0.3963377774 * a + 0.2158037573 * b, L - 0.1055613458 * a - 0.0638541728 * b, L - 0.0894841775 * a - 1.2914855480 * b
    l, m, s = l_ ** 3, m_ ** 3, s_ ** 3
    lin = (4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s, -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
           -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s)
    if min(lin) < -1e-4 or max(lin) > 1 + 1e-4:
        return None
    rgb = [12.92 * c if c <= 0.0031308 else 1.055 * max(c, 0) ** (1 / 2.4) - 0.055 for c in lin]
    return "#" + "".join(f"{round(min(max(c, 0), 1) * 255):02x}" for c in rgb)


def vendor_palette(vendor: str) -> dict:
    """The vendor's color and its ramps for light and dark pages: its hue, with the chroma lowered where it leaves sRGB."""
    from vendor_specs import AFFILIATION_COLORS
    color = AFFILIATION_COLORS.get(AFFILIATION.get(vendor, vendor), "#2a78d6")
    _, chroma, hue = _to_oklch(color)
    ramp = {}
    for mode, steps in RAMP_L.items():
        out = []
        for L in steps:
            C = max(chroma, 0.09)
            while _from_oklch(L, C, hue) is None and C > 0:
                C -= 0.005
            out.append(_from_oklch(L, C, hue))
        ramp[mode] = out
    return {"color": color, **ramp}
