"""Search many satellite catalogs (CSDA, Satellogic, NASA CMR, ...) with one call.

Vendor differences live in stac_providers.yaml; auth lives in stac_auth.py.
Each profile has an `api`: `stac` (default) or `cmr`. CMR granules are converted
to STAC-like items, so every provider returns the same columns and item dicts.

    import multistac
    multistac.overview({"csda": ["planet"], "csda-cmr": None}, "2023-01-01", "2026-10-01")
    res = multistac.search(
        sites="sites/eval_sites.geojson", site_name_field="Site Name",
        start="2023-01-01", end="2026-10-01", months=[6, 7, 8],
        providers={"csda": ["satellogic", "planet"], "satellogic": None},
        cloud_cover_max=20, processing_level=["L1B", "ORT"],
        cache_dir="/explore/nobackup/people/pmontesa/stac_cache",
    )
    res.gdf    # one row per (provider, item, site); common columns + all vendor properties
    res.items  # raw STAC item dicts (pystac.Item.from_dict(...) for downloads)
    res.log    # one row per search task: status, count, server-side filters, error

Generic filters are pushed to the server where the profile and the collection's
/queryables allow it, and are always re-applied locally, so a server that
ignores a filter cannot leak results. Rows missing a filtered field are dropped.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Union

import geopandas as gpd
import pandas as pd
import requests
import yaml
from shapely.geometry import MultiPolygon, Point, Polygon, box, mapping, shape
from shapely.geometry.polygon import orient
from shapely.ops import unary_union

import stac_auth

PROFILES_PATH = Path(__file__).with_name("stac_providers.yaml")
SENSOR_CATALOG_PATH = Path(__file__).with_name("sensor_catalog.yaml")

COMMON_COLUMNS = [
    "provider", "affiliation", "constellation", "sensor", "collection", "id",
    "datetime", "site_name", "cloud_cover", "processing_level", "product_type",
    "platform", "instrument", "gsd", "off_nadir", "incidence_angle",
    "view_azimuth", "sun_elevation", "sun_azimuth", "sat_azimuth", "sat_elevation",
    "sat_elevation_source", "vendor_item_id",
    "in_csda", "stac_self_href",
]
NUMERIC_COLUMNS = [
    "cloud_cover", "gsd", "off_nadir", "incidence_angle", "view_azimuth",
    "sun_elevation", "sun_azimuth", "sat_azimuth", "sat_elevation",
]
EARTH_RADIUS_KM = 6371.0


# --------------------------------------------------------------------------
# Profiles and providers
# --------------------------------------------------------------------------

def load_profiles(path: Union[str, Path, None] = None) -> Dict[str, Dict[str, Any]]:
    with open(path or PROFILES_PATH) as f:
        profiles = yaml.safe_load(f)
    for name, profile in profiles.items():
        profile["name"] = name
    return profiles


class Provider:
    """One STAC API: authenticated, retrying, paginating requests."""

    def __init__(self, profile: Dict[str, Any], max_retries: int = 4):
        self.profile = profile
        self.name = profile["name"]
        self.url = (profile.get("url") or profile["stac_url"]).rstrip("/")
        self.auth = stac_auth.make_auth(profile)
        self.search_cfg = profile.get("search", {})
        self.max_retries = max_retries
        self.semaphore = threading.Semaphore(self.search_cfg.get("max_concurrency", 2))
        self._local = threading.local()
        self._queryables: Dict[str, Optional[set]] = {}
        self._queryables_lock = threading.Lock()

    def __repr__(self) -> str:
        return f"Provider({self.name!r}, {self.url!r})"

    def _session(self) -> requests.Session:
        if not hasattr(self._local, "session"):
            self._local.session = requests.Session()
        return self._local.session

    def request(self, method: str, url: str, body: Optional[dict] = None) -> dict:
        return self._send(method, url, json=body).json()

    def _send(self, method: str, url: str, headers: Optional[dict] = None,
              **kwargs) -> requests.Response:
        """Request with auth, retries on 429/5xx/network errors, one re-auth on 401."""
        timeout = self.search_cfg.get("timeout", 120)
        for attempt in range(self.max_retries + 1):
            last = attempt == self.max_retries
            try:
                all_headers = {"Accept": "application/geo+json, application/json"}
                all_headers.update(self.auth.headers())
                all_headers.update(headers or {})
                response = self._session().request(
                    method, url, headers=all_headers, timeout=timeout, **kwargs
                )
            except requests.RequestException as error:
                if last:
                    raise RuntimeError(f"{self.name}: {type(error).__name__}: {error}")
                time.sleep(min(2 ** attempt, 30))
                continue
            if response.status_code == 401 and attempt == 0:
                self.auth.invalidate()
                continue
            if response.status_code == 429 or response.status_code >= 500:
                if last:
                    break
                retry_after = response.headers.get("Retry-After", "")
                wait = float(retry_after) if retry_after.isdigit() else 2 ** attempt
                time.sleep(min(wait, 60))
                continue
            break
        if not response.ok:
            raise RuntimeError(
                f"{self.name}: HTTP {response.status_code} for {method} "
                f"{url.split('?')[0]}: {response.text[:300]}"
            )
        return response

    def search(self, payload: dict, max_items: Optional[int] = None) -> List[dict]:
        """POST /search and follow `next` links. Returns raw feature dicts."""
        features: List[dict] = []
        method, url, body = "POST", f"{self.url}/search", payload
        seen = set()
        while True:
            page = self.request(method, url, body)
            batch = page.get("features", [])
            features.extend(batch)
            if not batch or (max_items and len(features) >= max_items):
                break
            link = next((l for l in page.get("links", []) if l.get("rel") == "next"), None)
            if not link:
                break
            if self.profile.get("next_link") == "post_empty":
                method, url, body = "POST", link["href"], {}
            else:
                method = link.get("method", "GET").upper()
                url = link["href"]
                if method == "POST":
                    body = {**payload, **link.get("body", {})} if link.get("merge") else link.get("body", {})
                else:
                    body = None
            key = (method, url, json.dumps(body, sort_keys=True))
            if key in seen:
                break
            seen.add(key)
        return features[:max_items] if max_items else features

    def queryables(self, collection: str) -> Optional[set]:
        """Queryable property names for a collection (None if unavailable)."""
        with self._queryables_lock:
            if collection not in self._queryables:
                try:
                    data = self.request("GET", f"{self.url}/collections/{collection}/queryables")
                    self._queryables[collection] = set(data.get("properties", {}))
                except Exception:
                    self._queryables[collection] = None
            return self._queryables[collection]

    def list_collections(self) -> pd.DataFrame:
        url, rows = f"{self.url}/collections", []
        while url:
            data = self.request("GET", url)
            rows += [{"id": c["id"], "title": c.get("title")} for c in data.get("collections", [])]
            nxt = next((l for l in data.get("links", []) if l.get("rel") == "next"), None)
            url = nxt["href"] if nxt else None
        return pd.DataFrame(rows)

    def overview(self, collection: str) -> Dict[str, Any]:
        """Catalog-wide first/last acquisition and item count for one collection.

        Dates come from date-sorted searches (sort extension), falling back to
        the collection's temporal extent. `total` is only filled when the API
        reports a match count; many STAC APIs (including CSDA) do not.
        """
        row: Dict[str, Any] = {"title": None, "first": None, "last": None,
                               "total": None, "dates_from": None}
        try:
            info = self.request("GET", f"{self.url}/collections/{collection}")
            row["title"] = info.get("title")
            interval = (info.get("extent", {}).get("temporal", {}).get("interval") or [[None, None]])[0]
            row["first"], row["last"], row["dates_from"] = interval[0], interval[1], "collection extent"
        except Exception:
            pass
        try:
            ends = []
            for direction in ("asc", "desc"):
                page = self.request("POST", f"{self.url}/search", {
                    "collections": [collection], "limit": 1,
                    "sortby": [{"field": "properties.datetime", "direction": direction}]})
                feats = page.get("features", [])
                props = feats[0]["properties"] if feats else {}
                ends.append(props.get("datetime") or props.get("start_datetime"))
                matched = page.get("numberMatched", (page.get("context") or {}).get("matched"))
                if matched is not None:
                    row["total"] = matched
            # first == last with a wider extent means sortby was ignored
            if all(ends) and not (ends[0] == ends[1] and row["first"] and row["first"] != row["last"]):
                row["first"], row["last"], row["dates_from"] = ends[0], ends[1], "items"
        except Exception as error:
            row["error"] = str(error)[:200]
        return row

    def _count(self, collection: str, interval: Optional[str] = None) -> Optional[int]:
        body: Dict[str, Any] = {"collections": [collection], "limit": 1}
        if interval:
            body["datetime"] = _iso_interval(interval)
        page = self.request("POST", f"{self.url}/search", body)
        return page.get("numberMatched", (page.get("context") or {}).get("matched"))

    def monthly_counts(self, collection: str, years: List[int]) -> Optional[Dict[tuple, int]]:
        """{(year, month): count}, or None if the API does not report counts."""
        if self._count(collection) is None:
            return None
        months = [(y, m) for y in years for m in range(1, 13)]
        def one(ym):
            y, m = ym
            last = (pd.Timestamp(y, m, 1) + pd.offsets.MonthEnd(1)).strftime("%Y-%m-%d")
            return ym, self._count(collection, f"{y}-{m:02d}-01/{last}") or 0
        with ThreadPoolExecutor(max_workers=self.search_cfg.get("max_concurrency", 2)) as pool:
            return dict(pool.map(one, months))

    def fields_for(self, collection: str) -> Dict[str, List[str]]:
        fields = {k: _as_list(v) for k, v in self.profile.get("fields", {}).items()}
        overrides = self.profile.get("collection_fields", {}).get(collection, {})
        fields.update({k: _as_list(v) for k, v in overrides.items()})
        return fields

    def affiliation_for(self, collection: str) -> Optional[str]:
        affiliations = self.profile.get("affiliation", {})
        return affiliations.get(collection, affiliations.get("default"))

    @property
    def display_name(self) -> str:
        return self.profile.get("display_name", self.name)


# --------------------------------------------------------------------------
# CMR backend: NASA's Common Metadata Repository granule search, as STAC items
# --------------------------------------------------------------------------

# STAC payload keys the CMR translation understands; any other key (e.g. from
# `extra`) is passed straight through as a CMR search parameter.
_STAC_KEYS = {"collections", "datetime", "limit", "intersects", "bbox",
              "filter", "filter-lang", "query"}
_CMR_ROLES = {
    "GET DATA": ["data"],
    "GET DATA VIA DIRECT ACCESS": ["data"],
    "GET RELATED VISUALIZATION": ["thumbnail"],
    "EXTENDED METADATA": ["metadata"],
}
_CQL_RANGE = {"<=": "max", "<": "max", ">=": "min", ">": "min"}


def _snake(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return value


class CMRProvider(Provider):
    """NASA CMR granule search (search/granules.umm_json) behind the Provider API.

    Collections are CMR short names within the profile's `cmr_provider`.
    Granules come back as STAC-like items: UMM AdditionalAttributes become
    `cmr:<snake_name>` properties, `derived` regexes add vendor IDs, and
    RelatedUrls become assets keyed by file suffix (HTTPS href, S3 alternate).
    """

    def list_collections(self) -> pd.DataFrame:
        data = self.request("GET", f"{self.url}/collections.json?provider="
                            f"{self.profile['cmr_provider']}&page_size=2000&include_granule_counts=true")
        return pd.DataFrame([{"id": c["short_name"], "title": c.get("title"),
                              "version": c.get("version_id"),
                              "granule_count": int(c.get("granule_count") or 0)}
                             for c in data["feed"]["entry"]])

    def queryables(self, collection: str) -> Optional[set]:
        return set(self.profile.get("queryables", []))

    def monthly_counts(self, collection: str, years: List[int]) -> Optional[Dict[tuple, int]]:
        """{(year, month): count} from CMR temporal facets."""
        base = (f"{self.url}/granules.json?provider={self.profile['cmr_provider']}"
                f"&short_name={collection}&page_size=0&include_facets=v2")

        def path(url: str, *titles: str) -> List[dict]:
            node = self.request("GET", url)["feed"].get("facets", {})
            for title in titles:
                node = next((c for c in node.get("children", []) if c.get("title") == title), {})
            return node.get("children", [])

        wanted = [int(n["title"]) for n in path(base, "Temporal", "Year") if int(n["title"]) in set(years)]

        def one(year):
            months = path(f"{base}&temporal_facet%5B0%5D%5Byear%5D={year}",
                          "Temporal", "Year", str(year), "Month")
            return {(year, int(n["title"])): int(n["count"]) for n in months}

        counts: Dict[tuple, int] = {}
        with ThreadPoolExecutor(max_workers=self.search_cfg.get("max_concurrency", 4)) as pool:
            for part in pool.map(one, wanted):
                counts.update(part)
        return counts

    def overview(self, collection: str) -> Dict[str, Any]:
        row: Dict[str, Any] = {"title": None, "first": None, "last": None,
                               "total": None, "dates_from": "items"}
        base = (f"{self.url}/granules.json?provider={self.profile['cmr_provider']}"
                f"&short_name={collection}&page_size=1")
        try:
            dates = []
            for sort in ("start_date", "-start_date"):
                response = self._send("GET", f"{base}&sort_key={sort}")
                entries = response.json()["feed"]["entry"]
                dates.append(entries[0]["time_start"] if entries else None)
                row["total"] = int(response.headers.get("CMR-Hits", 0))
            row["first"], row["last"] = dates
            info = self.request("GET", f"{self.url}/collections.json?provider="
                                f"{self.profile['cmr_provider']}&short_name={collection}")
            row["title"] = info["feed"]["entry"][0].get("title")
        except Exception as error:
            row["error"] = str(error)[:200]
        return row

    def _per_collection(self, key: str, collection: str, default=None):
        values = self.profile.get(key, {})
        return values.get(collection, values.get("default", default))

    def _params(self, payload: dict) -> list:
        params = [("provider", self.profile["cmr_provider"]),
                  ("page_size", payload.get("limit", 1000)), ("sort_key", "start_date")]
        collections = _as_list(payload.get("collections"))
        params += [("short_name", c) for c in collections]
        if payload.get("datetime"):
            start, _, end = payload["datetime"].partition("/")
            params.append(("temporal", f"{'' if start == '..' else start},{'' if end in ('', '..') else end}"))
        if payload.get("intersects"):
            geom = shape(payload["intersects"])
            polys = list(geom.geoms) if isinstance(geom, MultiPolygon) else [geom]
            key = "polygon[]" if len(polys) > 1 else "polygon"
            for poly in polys:
                if not isinstance(poly, Polygon):
                    poly = poly.envelope
                if len(poly.exterior.coords) > 500:
                    poly = poly.convex_hull  # results are re-checked against the site
                coords = orient(Polygon(poly.exterior), 1.0).exterior.coords
                params.append((key, ",".join(f"{x:.8f},{y:.8f}" for x, y in coords)))
            if len(polys) > 1:
                params.append(("options[polygon][or]", "true"))
        elif payload.get("bbox"):
            params.append(("bounding_box", ",".join(map(str, payload["bbox"]))))
        if payload.get("filter"):
            params += self._filter_params(payload["filter"], collections)
        for key, value in payload.items():
            if key not in _STAC_KEYS:
                params += [(key, v) for v in _as_list(value)]
        return params

    def _filter_params(self, node: dict, collections: List[str]) -> list:
        """CQL2 comparisons (optionally joined by `and`) -> CMR range parameters."""
        if node.get("op") == "and":
            return [p for arg in node["args"] for p in self._filter_params(arg, collections)]
        prop, value = node["args"][0]["property"], node["args"][1]
        if node.get("op") not in _CQL_RANGE or prop != "eo:cloud_cover":
            raise ValueError(f"{self.name}: unsupported filter {node}")
        scales = {self._per_collection("cloud_cover_scale", c, 1) for c in collections}
        if len(scales) != 1:
            raise ValueError(f"{self.name}: collections with different cloud_cover_scale in one search")
        bound = value / scales.pop()
        rng = f"0,{bound}" if _CQL_RANGE[node["op"]] == "max" else f"{bound},1000000"
        return [("cloud_cover", rng)]

    def search(self, payload: dict, max_items: Optional[int] = None) -> List[dict]:
        features: List[dict] = []
        params = self._params(payload)
        page_size = int(payload.get("limit", 1000))
        search_after = None
        while True:
            headers = {"CMR-Search-After": search_after} if search_after else {}
            response = self._send("POST", f"{self.url}/granules.umm_json",
                                  headers=headers, data=params)
            batch = response.json().get("items", [])
            features += [self.to_feature(item) for item in batch]
            search_after = response.headers.get("CMR-Search-After")
            if len(batch) < page_size or not search_after or (max_items and len(features) >= max_items):
                break
        return features[:max_items] if max_items else features

    def to_feature(self, item: dict) -> dict:
        """One UMM-G granule -> STAC-like item dict."""
        umm, meta = item["umm"], item["meta"]
        collection = umm["CollectionReference"]["ShortName"]
        temporal = umm.get("TemporalExtent", {})
        rng = temporal.get("RangeDateTime", {})
        start = temporal.get("SingleDateTime") or rng.get("BeginningDateTime")
        props: Dict[str, Any] = {
            "datetime": start,
            "start_datetime": start,
            "end_datetime": rng.get("EndingDateTime") or start,
            "cmr:concept_id": meta.get("concept-id"),
            "cmr:native_id": meta.get("native-id"),
            "cmr:provider": meta.get("provider-id"),
            "cmr:revision_date": meta.get("revision-date"),
            "cmr:collection_version": umm["CollectionReference"].get("Version"),
            "cmr:day_night_flag": umm.get("DataGranule", {}).get("DayNightFlag"),
            "cmr:production_datetime": umm.get("DataGranule", {}).get("ProductionDateTime"),
        }
        cloud = umm.get("CloudCover")
        if cloud is not None:
            props["cmr:cloud_cover_raw"] = cloud
            if cloud >= 0:  # negative = unknown
                props["eo:cloud_cover"] = round(cloud * self._per_collection("cloud_cover_scale", collection, 1), 3)
        platforms = umm.get("Platforms", [])
        if platforms:
            props["platform"] = ", ".join(p["ShortName"] for p in platforms)
            props["instruments"] = [i["ShortName"] for p in platforms for i in p.get("Instruments", [])]
        for attr in umm.get("AdditionalAttributes", []):
            values = [_number(v) for v in attr.get("Values", [])]
            props[f"cmr:{_snake(attr['Name'])}"] = values[0] if len(values) == 1 else values
        sources = {"id": umm["GranuleUR"], "collection": collection}
        derived_ids = []
        for prop, rule in (self.profile.get("derived") or {}).items():
            match = re.search(rule["pattern"], sources[rule.get("source", "id")])
            if match:
                props[prop] = match.group(1)
                if rule.get("source", "id") == "id":
                    derived_ids.append(prop)

        links = [{"rel": "self", "type": "application/json",
                  "href": f"{self.url}/concepts/{meta.get('concept-id')}.umm_json"}]
        urls = umm.get("RelatedUrls", [])
        for u in urls:
            if u["URL"].endswith("/s3credentials"):
                links.append({"rel": "s3credentials", "href": u["URL"]})
        geometry = self._geometry(umm)
        return {
            "type": "Feature",
            "stac_version": "1.0.0",
            "id": umm["GranuleUR"],
            "collection": collection,
            "geometry": geometry,
            "bbox": list(shape(geometry).bounds) if geometry else None,
            "properties": props,
            "assets": self._assets(urls, [umm["GranuleUR"]] + [props[k] for k in derived_ids]),
            "links": links,
        }

    @staticmethod
    def _geometry(umm: dict) -> Optional[dict]:
        geom = umm.get("SpatialExtent", {}).get("HorizontalSpatialDomain", {}).get("Geometry", {})
        parts = []
        for gp in geom.get("GPolygons", []):
            pts = [(p["Longitude"], p["Latitude"]) for p in gp["Boundary"]["Points"]]
            parts.append(Polygon(pts))
        for r in geom.get("BoundingRectangles", []):
            parts.append(box(r["WestBoundingCoordinate"], r["SouthBoundingCoordinate"],
                             r["EastBoundingCoordinate"], r["NorthBoundingCoordinate"]))
        parts += [Point(p["Longitude"], p["Latitude"]) for p in geom.get("Points", [])]
        if not parts:
            return None
        return mapping(parts[0] if len(parts) == 1 else unary_union(parts))

    @staticmethod
    def _assets(urls: List[dict], stems: List[str]) -> Dict[str, dict]:
        """Group RelatedUrls by file name; key = file name minus the granule stem.

        `stems` are the granule ID and IDs derived from it (e.g. a Planet item
        ID); the longest one a file name starts with is removed, so keys such
        as `ntf` or `1b_analytic_tif` are the same for every granule.
        """
        files: Dict[str, dict] = {}
        for u in urls:
            name = u["URL"].rstrip("/").rsplit("/", 1)[-1]
            if name == "s3credentials" or u.get("Type") not in _CMR_ROLES:
                continue
            entry = files.setdefault(name, {"roles": _CMR_ROLES[u["Type"]]})
            kind = "s3" if u["URL"].startswith("s3://") else "https"
            # Prefer the public Earthdata host over raw API-gateway URLs
            if kind == "https" and "earthdata.nasa.gov" in u["URL"]:
                entry[kind] = u["URL"]
            else:
                entry.setdefault(kind, u["URL"])
        stems = sorted({s for s in stems if s}, key=len, reverse=True)
        assets: Dict[str, dict] = {}
        for name, entry in files.items():
            stem = next((s for s in stems if name.startswith(s)), "")
            key = _snake(name[len(stem):]) or _snake(name)
            while key in assets:
                key += "_"
            asset = {"href": entry.get("https") or entry.get("s3"), "title": name, "roles": entry["roles"]}
            if entry.get("https") and entry.get("s3"):
                asset["alternate"] = {"s3": {"href": entry["s3"]}}
            assets[key] = asset
        return assets


BACKENDS = {"stac": Provider, "cmr": CMRProvider}


def display_names() -> Dict[str, str]:
    """Provider code -> display name for tables and plots (profile `display_name`)."""
    return {name: p.get("display_name", name) for name, p in load_profiles().items()}


# --------------------------------------------------------------------------
# Sensor vocabulary: affiliation / constellation / sensor across vendors
# --------------------------------------------------------------------------

@lru_cache(maxsize=None)
def _sensor_rules() -> List[Dict[str, Any]]:
    with open(SENSOR_CATALOG_PATH) as f:
        rules = yaml.safe_load(f)["rules"]
    for rule in rules:
        rule["_re"] = re.compile(rule["pattern"], re.IGNORECASE)
    return rules


def resolve_sensor(raw_values: Iterable, affiliation: Optional[str] = None,
                   constellation: Optional[str] = None) -> Dict[str, Optional[str]]:
    """Raw platform/satellite IDs -> {affiliation, constellation, sensor}.

    Each raw value (lists and "a, b" strings are split) is tried against the
    rules in sensor_catalog.yaml; the first match wins. Unmatched: sensor =
    first raw value, constellation and affiliation = the given defaults.
    """
    values = []
    for v in raw_values:
        if v is None or v == "":
            continue
        parts = v if isinstance(v, (list, tuple)) else str(v).split(",")
        # also handles list-like strings, e.g. "['WV03', 'WV03']"
        values += [str(x).strip(" []'\"") for x in parts if str(x).strip(" []'\"")]
    for value in values:
        for rule in _sensor_rules():
            if rule.get("when_affiliation") and rule["when_affiliation"] != affiliation:
                continue
            match = rule["_re"].fullmatch(value)
            if match:
                groups = {k: int(v) if v and v.isdigit() else v for k, v in match.groupdict().items()}
                sensor = rule.get("sensor")
                return {
                    "affiliation": rule.get("affiliation") or affiliation,
                    "constellation": rule.get("constellation") or constellation,
                    "sensor": str(sensor).format(**groups) if sensor else value,
                }
    return {"affiliation": affiliation, "constellation": constellation,
            "sensor": values[0] if values else None}


def constellation_altitude_km(constellation: Optional[str]) -> float:
    """Nominal orbit altitude (sensor_catalog.yaml `altitude_km`)."""
    with open(SENSOR_CATALOG_PATH) as f:
        alts = (yaml.safe_load(f) or {}).get("altitude_km", {})
    return float(alts.get(constellation, alts.get("default", 550)))


def _satellite_position(record: Dict[str, Any], prov: "Provider", collection: str) -> None:
    """Fill sat_azimuth / sat_elevation (satellite as seen from the target).

    sat_elevation comes from the profile `fields` (reported elevation, or
    90 - incidence/view zenith). If missing, it is derived from off_nadir on a
    spherical Earth at the constellation's nominal altitude (approximate).
    sat_azimuth comes from the profile `fields`, plus the collection's
    `sat_azimuth_offset` (0 or 180) when a vendor reports the opposite direction.
    """
    def num(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None
    elev, off = num(record.get("sat_elevation")), num(record.get("off_nadir"))
    if elev is not None:
        record["sat_elevation_source"] = "reported"
    elif off is not None and 0 <= off < 60:
        h = constellation_altitude_km(record.get("constellation"))
        s = min(1.0, math.sin(math.radians(off)) * (EARTH_RADIUS_KM + h) / EARTH_RADIUS_KM)
        record["sat_elevation"] = round(90.0 - math.degrees(math.asin(s)), 2)
        record["sat_elevation_source"] = f"from off_nadir, h={h:.0f} km"
    az = num(record.get("sat_azimuth"))
    if az is not None:
        offsets = prov.profile.get("sat_azimuth_offset", {})
        record["sat_azimuth"] = (az + offsets.get(collection, offsets.get("default", 0))) % 360


@lru_cache(maxsize=None)
def get_provider(name: str) -> Provider:
    profiles = load_profiles()
    if name not in profiles:
        raise KeyError(f"Unknown provider '{name}'. Known: {sorted(profiles)}")
    api = profiles[name].get("api", "stac")
    if api not in BACKENDS:
        raise ValueError(f"Provider '{name}': unknown api '{api}'. Known: {sorted(BACKENDS)}")
    return BACKENDS[api](profiles[name])


# --------------------------------------------------------------------------
# Discovery helpers
# --------------------------------------------------------------------------

def list_providers() -> pd.DataFrame:
    """Configured providers and whether their credentials section exists."""
    rows = []
    for name, p in load_profiles().items():
        section = p.get("auth", {}).get("credentials_section")
        rows.append({
            "provider": name,
            "label": p.get("label"),
            "api": p.get("api", "stac"),
            "enabled": p.get("enabled", True),
            "auth": p.get("auth", {}).get("type", "none"),
            "credentials_section": section,
            "credentials_found": stac_auth.has_credentials(section) if section else None,
            "url": p.get("url") or p.get("stac_url"),
            "display_name": p.get("display_name", name),
        })
    return pd.DataFrame(rows)


def collections(provider: str) -> pd.DataFrame:
    """Collection IDs and titles available from a provider."""
    return get_provider(provider).list_collections()


def overview(providers: Union[Dict[str, Optional[List[str]]], List[str]],
             start: Optional[str] = None, end: Optional[str] = None,
             max_workers: int = 8) -> pd.DataFrame:
    """One row per collection: catalog-wide first/last acquisition and total.

    `providers` takes the same form as in search(). With start/end, the
    `in_window` column flags collections with acquisitions in that window, so
    an empty collection is spotted before the search runs. `total` is a
    display string with thousands separators, "n/a" where the API does not
    report counts (e.g. CSDA STAC).
    """
    if isinstance(providers, (list, tuple)):
        providers = {p: None for p in providers}
    jobs = [(name, c) for name, cols in providers.items()
            for c in _as_list(cols) or get_provider(name).profile.get("default_collections", [])]
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        rows = list(pool.map(lambda job: {"provider": job[0], "collection": job[1],
                                          **get_provider(job[0]).overview(job[1])}, jobs))
    df = pd.DataFrame(rows)
    for col in ("first", "last"):
        df[col] = pd.to_datetime(df[col], utc=True, errors="coerce").dt.date
    # Display string, e.g. "6,846,674"; "n/a" where the API reports no count
    df["total"] = [f"{int(t):,}" if pd.notna(t) else "n/a" for t in df["total"]]
    cols = ["provider", "collection", "title", "first", "last", "total", "dates_from"]
    if start or end:
        lo = pd.Timestamp(start or "1900-01-01").date()
        hi = pd.Timestamp(end or "2100-01-01").date()
        df["in_window"] = [bool(f and l and f <= hi and l >= lo) if pd.notna(f) and pd.notna(l) else pd.NA
                           for f, l in zip(df["first"], df["last"])]
        cols.append("in_window")
    if "error" in df:
        cols.append("error")
    return df[cols]


MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _month_table(long: pd.DataFrame, keys: List[str]) -> pd.DataFrame:
    """long [keys..., year, month, count] -> one row per keys+year, Jan..Dec + total."""
    wide = long.pivot_table(index=keys + ["year"], columns="month", values="count",
                            aggfunc="sum", fill_value=0)
    wide = wide.reindex(columns=range(1, 13), fill_value=0).astype(int)
    wide.columns = MONTH_NAMES
    wide["total"] = wide.sum(axis=1)
    return wide.reset_index()


def month_table(gdf: pd.DataFrame, by: Union[str, List[str]] = ("provider", "collection"),
                unique_items: bool = True) -> pd.DataFrame:
    """Acquisitions per `by` columns, year and month (Jan..Dec + total).

    Works on res.gdf or a saved result read back with geopandas. Missing
    values in `by` columns show as "unknown".
    """
    by = _as_list(by)
    if gdf.empty:
        return pd.DataFrame(columns=by + ["year"] + MONTH_NAMES + ["total"])
    g = gdf.copy()
    g["datetime"] = pd.to_datetime(g["datetime"], utc=True, errors="coerce")
    g = g.dropna(subset=["datetime"])
    if unique_items:
        g = g.drop_duplicates(subset=["provider", "id"])
    long = g[by].astype(object).where(g[by].notna(), "unknown")
    long = long.assign(year=g["datetime"].dt.year, month=g["datetime"].dt.month, count=1)
    return _month_table(long, by)


def overview_by_month(providers: Union[Dict[str, Optional[List[str]]], List[str]],
                      start: Optional[str] = None, end: Optional[str] = None,
                      max_workers: int = 4) -> pd.DataFrame:
    """Catalog-wide acquisitions per collection, year and month (Jan..Dec + total).

    Only for APIs that report counts: CMR (via temporal facets) and STAC APIs
    returning numberMatched. Others (e.g. CSDA STAC) are skipped with a
    printed note; use SearchResult.by_month() for counts within a search.
    Years default to each collection's first..last acquisition, clipped to
    start/end.
    """
    ov = overview(providers)
    lo = pd.Timestamp(start).year if start else None
    hi = pd.Timestamp(end).year if end else None

    def one(row):
        if pd.isna(row["first"]) or pd.isna(row["last"]):
            return row, None
        y0, y1 = row["first"].year, row["last"].year
        years = list(range(max(y0, lo or y0), min(y1, hi or y1) + 1))
        return row, get_provider(row["provider"]).monthly_counts(row["collection"], years)

    rows, skipped = [], []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        for row, counts in pool.map(one, [r for _, r in ov.iterrows()]):
            if counts is None:
                skipped.append(f"{row['provider']}/{row['collection']}")
                continue
            rows += [{"provider": row["provider"], "collection": row["collection"],
                      "year": y, "month": m, "count": c} for (y, m), c in counts.items()]
    if skipped:
        print("No catalog counts from this API (use res.by_month()):", ", ".join(skipped))
    if not rows:
        return pd.DataFrame(columns=["provider", "collection", "year"] + MONTH_NAMES + ["total"])
    table = _month_table(pd.DataFrame(rows), ["provider", "collection"])
    if start or end:
        # Months outside start/end within the edge years are blanked
        for i, r in table.iterrows():
            for m, name in enumerate(MONTH_NAMES, 1):
                ts = pd.Timestamp(int(r["year"]), m, 1)
                if (start and ts + pd.offsets.MonthEnd(1) < pd.Timestamp(start)) or (end and ts > pd.Timestamp(end)):
                    table.at[i, name] = 0
        table["total"] = table[MONTH_NAMES].sum(axis=1)
    return table


def queryables(provider: str, collection: str) -> Optional[List[str]]:
    q = get_provider(provider).queryables(collection)
    return sorted(q) if q is not None else None


def sample_item(provider: str, collection: str, **payload) -> Optional[dict]:
    """One raw item, for checking a vendor's property names."""
    features = get_provider(provider).search({"collections": [collection], "limit": 1, **payload}, max_items=1)
    return features[0] if features else None


# --------------------------------------------------------------------------
# Inputs
# --------------------------------------------------------------------------

def load_sites(sites, site_name_field: str = "Site_Name",
               point_buffer_deg: float = 0.1) -> gpd.GeoDataFrame:
    """Sites as a GeoDataFrame [site_name, geometry] in EPSG:4326.

    `sites` may be a file path/URL, a GeoDataFrame, or a site dict from
    staclib.create_site_dict_from_gdf. Points become boxes of +/- point_buffer_deg.
    """
    if isinstance(sites, dict):
        gdf = gpd.GeoDataFrame(
            {"site_name": list(sites), "geometry": [box(*v["bbox"]) for v in sites.values()]},
            crs="EPSG:4326",
        )
    else:
        gdf = gpd.read_file(sites) if isinstance(sites, (str, Path)) else sites.copy()
        gdf = gdf.to_crs("EPSG:4326") if gdf.crs else gdf.set_crs("EPSG:4326")
        gdf = gdf.rename(columns={site_name_field: "site_name"})[["site_name", "geometry"]]
    gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty].copy()
    is_point = gdf.geom_type == "Point"
    if is_point.any():
        gdf.loc[is_point, "geometry"] = [
            box(p.x - point_buffer_deg, p.y - point_buffer_deg,
                p.x + point_buffer_deg, p.y + point_buffer_deg)
            for p in gdf.loc[is_point].geometry
        ]
    return gdf.reset_index(drop=True)


def _intervals(start: str, end: str, months: Optional[Iterable[int]],
               split: Optional[str] = None) -> List[str]:
    """Date intervals to search. `split` ("month" or "year") cuts the range
    into chunks, so big (global) searches run in parallel and cache per chunk;
    with `months`, only chunks in those months are kept."""
    if split:
        freq = {"month": "MS", "year": "YS"}[split]
        t0, t1 = pd.Timestamp(start), pd.Timestamp(end)
        edges = list(pd.date_range(t0, t1, freq=freq))
        edges = ([t0] if not edges or edges[0] > t0 else []) + edges + [t1 + pd.Timedelta(days=1)]
        out = []
        for a, b in zip(edges[:-1], edges[1:]):
            b = b - pd.Timedelta(days=1)
            if a <= b and (not months or a.month in set(months)):
                out.append(f"{a:%Y-%m-%d}/{b:%Y-%m-%d}")
        return out
    if not months:
        return [f"{start}/{end}"]
    from staclib import _build_seasonal_intervals
    return _build_seasonal_intervals(start, end, list(months))


def _iso_interval(interval: str) -> str:
    def fix(value: str, suffix: str) -> str:
        value = value.strip()
        if value in ("", ".."):
            return ".."
        if "T" not in value:
            return value + suffix
        return value if value.endswith("Z") or "+" in value else value + "Z"
    start, end = interval.split("/")
    return f"{fix(start, 'T00:00:00Z')}/{fix(end, 'T23:59:59Z')}"


def _as_list(value) -> list:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return [value]


# --------------------------------------------------------------------------
# One search task: provider x collection x site x interval
# --------------------------------------------------------------------------

def _safe(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value))


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False, suffix=".tmp") as f:
        json.dump(data, f, separators=(",", ":"))
        tmp = f.name
    os.replace(tmp, path)


def _build_payload(prov: Provider, task: dict, cloud_cover_max, extra: dict):
    payload: Dict[str, Any] = {
        "collections": [task["collection"]],
        "datetime": _iso_interval(task["interval"]),
        "limit": prov.search_cfg.get("page_size", 100),
    }
    geom = task["geometry"]
    if geom is None:
        pass  # global search: no spatial filter
    elif prov.profile.get("geometry", "intersects") == "intersects":
        payload["intersects"] = mapping(geom)
    else:
        payload["bbox"] = list(geom.bounds)
    if task.get("slim") and prov.profile.get("fields_extension"):
        payload["fields"] = {"exclude": ["assets", "links"]}

    server_filters = []
    filter_mode = prov.profile.get("filter_mode")
    if cloud_cover_max is not None and filter_mode in ("query", "filter"):
        queryable = prov.queryables(task["collection"]) or set()
        prop = next((p for p in prov.fields_for(task["collection"]).get("cloud_cover", [])
                     if p in queryable), None)
        if prop and filter_mode == "query":
            payload.setdefault("query", {})[prop] = {"lte": cloud_cover_max}
            server_filters.append(f"{prop}<={cloud_cover_max}")
        elif prop:
            payload["filter-lang"] = "cql2-json"
            payload["filter"] = {"op": "<=", "args": [{"property": prop}, cloud_cover_max]}
            server_filters.append(f"{prop}<={cloud_cover_max} (cql2)")
    for key, value in (extra or {}).items():
        if key == "query" and isinstance(value, dict):
            payload.setdefault("query", {}).update(value)
        else:
            payload[key] = value
    return payload, server_filters


def _run_task(task: dict, cloud_cover_max, extra: dict, cache_dir: Optional[Path],
              max_items: Optional[int]) -> dict:
    prov = get_provider(task["provider"])
    started = time.time()
    result = {k: task[k] for k in ("provider", "collection", "site_name", "interval")}
    try:
        payload, server_filters = _build_payload(prov, task, cloud_cover_max, extra)
        result["server_filters"] = "; ".join(server_filters)
        cache_file = None
        if cache_dir is not None:
            digest = hashlib.sha1(json.dumps(
                {k: v for k, v in payload.items() if k != "limit"},
                sort_keys=True, default=str).encode()).hexdigest()[:10]
            cache_file = (Path(cache_dir) / _safe(prov.name) / _safe(task["collection"])
                          / f"{_safe(task['site_name'])}__{_safe(task['interval'])}__{digest}.json")
            if cache_file.exists():
                try:
                    features = json.loads(cache_file.read_text())["features"]
                    return {**result, "status": "cached", "count": len(features),
                            "features": features, "seconds": 0.0}
                except (OSError, ValueError, KeyError):
                    pass
        with prov.semaphore:
            features = prov.search(payload, max_items=max_items)
        if cache_file is not None:
            _write_json(cache_file, {"type": "FeatureCollection", "features": features})
        return {**result, "status": "searched", "count": len(features),
                "features": features, "seconds": round(time.time() - started, 1)}
    except Exception as error:
        return {**result, "status": "failed", "count": 0, "features": [],
                "error": str(error)[:500], "seconds": round(time.time() - started, 1)}


# --------------------------------------------------------------------------
# Normalization and client-side filtering
# --------------------------------------------------------------------------

def _first(props: dict, candidates: List[str], feature: dict):
    """First non-empty candidate. A "90-" prefix converts a zenith angle to an
    elevation (e.g. "90-view:incidence_angle")."""
    for key in candidates:
        complement = key.startswith("90-")
        key = key[3:] if complement else key
        value = feature.get(key) if key in ("id", "collection") else props.get(key)
        if value is None or value == "" or value == []:
            continue
        if complement:
            try:
                return 90.0 - float(value)
            except (TypeError, ValueError):
                continue
        if isinstance(value, (list, tuple)):
            return ", ".join(map(str, value))
        return value
    return None


def normalize(feature: dict, provider: str, collection: str, site_name: str,
              include_assets: bool = True) -> dict:
    prov = get_provider(provider)
    props = feature.get("properties") or {}
    collection = feature.get("collection") or collection
    record = {
        "provider": provider,
        "affiliation": prov.affiliation_for(collection),
        "collection": collection,
        "id": feature.get("id"),
        "datetime": props.get("datetime") or props.get("start_datetime"),
        "site_name": site_name,
    }
    fields = prov.fields_for(collection)
    for column, candidates in fields.items():
        if column != "sensor":
            record[column] = _first(props, candidates, feature)
    raw = [feature.get(k) if k in ("id", "collection") else props.get(k)
           for k in fields.get("sensor", ["platform"])]
    record.update(resolve_sensor(raw, record["affiliation"], record.get("constellation")))
    _satellite_position(record, prov, collection)
    self_link = next((l.get("href") for l in feature.get("links", []) if l.get("rel") == "self"), None)
    record["stac_self_href"] = self_link
    for key, value in props.items():
        record.setdefault(key, value)
    if include_assets:
        for key, asset in (feature.get("assets") or {}).items():
            record[f"asset_{key}_href"] = asset.get("href")
    geometry = feature.get("geometry")
    record["geometry"] = shape(geometry) if geometry else None
    return record


def _match(series: pd.Series, wanted) -> pd.Series:
    wanted = {str(w).lower() for w in _as_list(wanted)}
    return series.astype(str).str.lower().isin(wanted)


def apply_filters(gdf: gpd.GeoDataFrame, cloud_cover_max=None, processing_level=None,
                  product_type=None, where: Optional[Callable] = None) -> gpd.GeoDataFrame:
    """Client-side filters on the normalized columns. Usable on saved results too."""
    keep = pd.Series(True, index=gdf.index)
    if cloud_cover_max is not None:
        keep &= gdf["cloud_cover"].le(cloud_cover_max)
    if processing_level is not None:
        keep &= _match(gdf["processing_level"], processing_level)
    if product_type is not None:
        keep &= _match(gdf["product_type"], product_type)
    if where is not None:
        keep &= where(gdf).astype(bool)
    return gdf[keep]


def flag_csda_holdings(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Set `in_csda` for vendor-API rows whose vendor_item_id CSDA also returned.

    Rows from providers with `csda_holdings: true` in the profile (CSDA STAC,
    CMR's CSDA provider) are CSDA holdings. Vendor rows are only flagged when a
    holdings provider was searched for that affiliation; otherwise they stay NA.
    """
    gdf = gdf.copy()
    gdf["in_csda"] = pd.Series(pd.NA, index=gdf.index, dtype="boolean")
    holdings = [name for name, p in load_profiles().items() if p.get("csda_holdings")]
    is_csda = gdf["provider"].isin(holdings)
    gdf.loc[is_csda, "in_csda"] = True
    if is_csda.any():
        csda_keys = set(zip(gdf.loc[is_csda, "affiliation"], gdf.loc[is_csda, "vendor_item_id"].astype(str)))
        searched = set(gdf.loc[is_csda, "affiliation"])
        others = ~is_csda & gdf["affiliation"].isin(searched)
        gdf.loc[others, "in_csda"] = [
            (a, str(i)) in csda_keys
            for a, i in zip(gdf.loc[others, "affiliation"], gdf.loc[others, "vendor_item_id"])
        ]
    return gdf


# --------------------------------------------------------------------------
# Results
# --------------------------------------------------------------------------

class SearchResult:
    def __init__(self, gdf: gpd.GeoDataFrame, items: List[dict], log: pd.DataFrame):
        self.gdf, self.items, self.log = gdf, items, log

    def __repr__(self) -> str:
        return (f"SearchResult({len(self.gdf)} rows, {len(self.items)} unique items, "
                f"{(self.log['status'] == 'failed').sum()} failed tasks)")

    def summary(self) -> pd.DataFrame:
        """Row counts by provider, collection and processing level."""
        if self.gdf.empty:
            return pd.DataFrame()
        cols = ["provider", "collection", "processing_level"]
        g = self.gdf.fillna({"processing_level": "?"})
        out = g.groupby(cols).agg(rows=("id", "size"), items=("id", "nunique"),
                                  sites=("site_name", "nunique"))
        if g["in_csda"].notna().any():
            out["in_csda"] = g.groupby(cols)["in_csda"].sum()
        return out.reset_index()

    def by_month(self, by: Union[str, List[str]] = ("provider", "collection"),
                 unique_items: bool = True) -> pd.DataFrame:
        """Acquisitions found by this search per `by` columns, year and month
        (Jan..Dec + total), e.g. by=["affiliation", "constellation", "sensor"].
        unique_items=False counts site rows instead of unique items."""
        return month_table(self.gdf, by, unique_items)

    def pystac_items(self) -> list:
        import pystac
        return [pystac.Item.from_dict(item) for item in self.items]

    def save(self, prefix: Union[str, Path]) -> List[Path]:
        """Write <prefix>.gpkg, <prefix>.csv and <prefix>_items.geojson, <prefix>_log.csv."""
        prefix = Path(prefix)
        prefix.parent.mkdir(parents=True, exist_ok=True)
        flat = self.gdf.copy()
        for col in flat.columns:
            if col != "geometry" and flat[col].dtype == object:
                flat[col] = flat[col].apply(
                    lambda v: json.dumps(v, default=str) if isinstance(v, (list, dict)) else v)
        flat["in_csda"] = flat["in_csda"].astype(object)
        paths = [prefix.with_suffix(".gpkg"), prefix.with_suffix(".csv"),
                 Path(f"{prefix}_items.geojson"), Path(f"{prefix}_log.csv")]
        flat.to_file(paths[0], driver="GPKG")
        flat.drop(columns="geometry").to_csv(paths[1], index=False)
        _write_json(paths[2], {"type": "FeatureCollection", "features": self.items})
        self.log.to_csv(paths[3], index=False)
        return paths


# --------------------------------------------------------------------------
# Main entry point
# --------------------------------------------------------------------------

def search(sites, start: str, end: str,
           providers: Union[Dict[str, Optional[List[str]]], List[str]],
           months: Optional[Iterable[int]] = None,
           site_name_field: str = "Site_Name",
           point_buffer_deg: float = 0.1,
           cloud_cover_max: Optional[float] = None,
           processing_level=None,
           product_type=None,
           where: Optional[Callable] = None,
           extra: Optional[Dict[str, dict]] = None,
           cache_dir: Union[str, Path, None] = None,
           max_items_per_task: Optional[int] = None,
           max_workers: int = 8,
           include_assets: Optional[bool] = None,
           split: Optional[str] = None,
           progress: bool = True) -> SearchResult:
    """Search sites x dates across providers; see module docstring.

    sites : sites file / GeoDataFrame / site dict, or None for a GLOBAL search
        (no spatial filter; site_name = "global"). Global searches default to
        split="month" and skip assets (include_assets=False) to stay light.
    split : "month" or "year" - search each chunk of the date range separately
        (parallel, cached and resumable per chunk).

    providers : {"csda": ["planet", ...], "satellogic": None} (None -> profile
        default_collections), or a list of provider names.
    processing_level, product_type : str or list, case-insensitive exact match
        on the normalized columns (e.g. "L1B", ["ORT", "LV2A"], "PSScene").
    where : optional callable gdf -> boolean Series for any other filter.
    extra : raw per-provider payload additions, e.g. {"csda": {"query": {...}}}.
    """
    if isinstance(providers, (list, tuple)):
        providers = {p: None for p in providers}
    is_global = sites is None or (isinstance(sites, str) and sites == "global")
    if is_global:
        sites_gdf = gpd.GeoDataFrame({"site_name": ["global"], "geometry": [None]}, crs="EPSG:4326")
        split = split or "month"
    else:
        sites_gdf = load_sites(sites, site_name_field, point_buffer_deg)
    if include_assets is None:
        include_assets = not is_global
    intervals = _intervals(start, end, months, split)

    tasks = []
    for name, cols in providers.items():
        prov = get_provider(name)
        if not prov.profile.get("enabled", True):
            raise ValueError(f"Provider '{name}' is disabled in stac_providers.yaml")
        for collection in _as_list(cols) or prov.profile.get("default_collections", []):
            for site in sites_gdf.itertuples():
                for interval in intervals:
                    tasks.append({"provider": name, "collection": collection,
                                  "site_name": site.site_name, "geometry": site.geometry,
                                  "interval": interval, "slim": not include_assets})

    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [pool.submit(_run_task, t, cloud_cover_max, (extra or {}).get(t["provider"]),
                               cache_dir, max_items_per_task) for t in tasks]
        iterator = as_completed(futures)
        if progress:
            try:
                from tqdm import tqdm  # plain text bar; widget bars fail without ipywidgets
                iterator = tqdm(iterator, total=len(futures), desc="searches")
            except ImportError:
                pass
        for future in iterator:
            results.append(future.result())

    site_geoms = dict(zip(sites_gdf.site_name, sites_gdf.geometry))
    records, items = [], {}
    for r in results:
        for feature in r["features"]:
            geom = feature.get("geometry")
            site_geom = site_geoms[r["site_name"]]
            if geom and site_geom is not None and not shape(geom).intersects(site_geom):
                continue  # bbox overshoot
            records.append(normalize(feature, r["provider"], r["collection"],
                                     r["site_name"], include_assets))
            items.setdefault((r["provider"], feature.get("id")), feature)

    log = pd.DataFrame([{k: v for k, v in r.items() if k != "features"} for r in results],
                       columns=["provider", "collection", "site_name", "interval", "status",
                                "count", "server_filters", "error", "seconds"])
    log = log.sort_values(["provider", "collection", "site_name", "interval"]).reset_index(drop=True)

    if not records:
        gdf = gpd.GeoDataFrame(columns=COMMON_COLUMNS + ["geometry"], geometry="geometry", crs="EPSG:4326")
        return SearchResult(gdf, [], log)

    df = pd.DataFrame(records)
    for col in COMMON_COLUMNS:
        if col not in df:
            df[col] = None
    for col in NUMERIC_COLUMNS:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["datetime"] = pd.to_datetime(df["datetime"], utc=True, errors="coerce")
    # Vendors are inconsistent (CSDA Satellogic has both "L1D" and "l1d")
    df["processing_level"] = df["processing_level"].map(lambda v: v.upper() if isinstance(v, str) else v)
    df = df.drop_duplicates(subset=["provider", "id", "site_name"])
    gdf = gpd.GeoDataFrame(df, geometry="geometry", crs="EPSG:4326")
    gdf = apply_filters(gdf, cloud_cover_max, processing_level, product_type, where)
    gdf = flag_csda_holdings(gdf)
    ordered = COMMON_COLUMNS + [c for c in gdf.columns if c not in COMMON_COLUMNS and c != "geometry"] + ["geometry"]
    gdf = gdf[ordered].sort_values(["site_name", "datetime", "provider"]).reset_index(drop=True)

    kept = {(p, i) for p, i in zip(gdf["provider"], gdf["id"])}
    return SearchResult(gdf, [f for k, f in items.items() if k in kept], log)
