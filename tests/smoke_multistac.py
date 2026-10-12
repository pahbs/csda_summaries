"""Smoke test for multistac against authenticated providers (Satellogic).

Run in the ILAB TensorFlow env (the notebook kernel):
    python tests/smoke_multistac.py

Prints only statuses, counts and property NAMES - never tokens, contract IDs
or credential values - so the output is safe to paste back to Claude.
"""

import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

import multistac  # noqa: E402

SITES = Path(__file__).resolve().parents[1] / "sites" / "csda_sites_aoi.geojson"
SITE_NAMES = ["San Diego", "Casablanca"]  # CSDA holds Satellogic items here
START, END = "2025-01-01", "2026-10-01"


def step(title):
    print(f"\n=== {title}")


step("Providers")
print(multistac.list_providers()[["provider", "enabled", "auth", "credentials_found"]].to_string(index=False))

step("Satellogic auth")
prov = multistac.get_provider("satellogic")
try:
    headers = prov.auth.headers()
    print("OK - headers:", sorted(headers))
except Exception as error:
    print("FAILED:", error)
    sys.exit(1)

step("Satellogic collections")
cols = multistac.collections("satellogic")
print(cols.to_string(index=False))

step("Queryables and sample item property names")
for col in cols["id"]:
    q = multistac.queryables("satellogic", col)
    item = multistac.sample_item("satellogic", col)
    print(f"[{col}] queryables: {q}")
    print(f"[{col}] properties: {sorted(item['properties']) if item else 'no items'}")
    print(f"[{col}] assets: {sorted(item.get('assets', {})) if item else ''}")

sites = multistac.load_sites(str(SITES), site_name_field="Site Name")
sites = sites[sites.site_name.isin(SITE_NAMES)]

step("Server capability probes (San Diego, first collection)")
site = sites.iloc[0].geometry
col = cols["id"].iloc[0]
base = {"collections": [col], "datetime": multistac._iso_interval(f"{START}/{END}"), "limit": 1000}
probes = {
    "bbox": {**base, "bbox": list(site.bounds)},
    "intersects": {**base, "intersects": multistac.mapping(site)},
    "bbox + query eo:cloud_cover<=20": {**base, "bbox": list(site.bounds),
                                        "query": {"eo:cloud_cover": {"lte": 20}}},
    "bbox + cql2 eo:cloud_cover<=20": {**base, "bbox": list(site.bounds), "filter-lang": "cql2-json",
                                       "filter": {"op": "<=", "args": [{"property": "eo:cloud_cover"}, 20]}},
}
for label, payload in probes.items():
    try:
        feats = prov.search(payload)
        clouds = [f["properties"].get("eo:cloud_cover") for f in feats]
        over = sum(1 for c in clouds if c is not None and c > 20)
        print(f"{label:34s} -> {len(feats)} items ({over} with cloud > 20)")
    except Exception as error:
        print(f"{label:34s} -> FAILED: {error}")

step("Satellogic search with filter_mode=filter (cloud <= 20)")
saved_mode = prov.profile.get("filter_mode")
prov.profile["filter_mode"] = "filter"
res = multistac.search(sites, START, END, {"satellogic": list(cols["id"])},
                       cloud_cover_max=20, cache_dir=None, progress=False)
print(res.log[["collection", "site_name", "status", "count", "server_filters", "error"]].to_string(index=False))
prov.profile["filter_mode"] = saved_mode

step("Combined CSDA + Satellogic search, all Satellogic collections")
res = multistac.search(sites, START, END,
                       {"csda": ["satellogic"], "satellogic": list(cols["id"])},
                       progress=False)
print(res)
print(res.log.groupby(["provider", "collection", "status"])["count"].sum().to_string())
failed = res.log[res.log.status == "failed"]
if len(failed):
    print("Errors:", failed["error"].unique()[:3])
print(res.summary().to_string(index=False))
sat = res.gdf[res.gdf.provider == "satellogic"]
print("Satellogic rows with vendor_item_id:", sat["vendor_item_id"].notna().sum(), "/", len(sat))
print("Satellogic rows already in CSDA:", int(sat["in_csda"].sum()), "/", len(sat))

step("Affiliation / constellation / sensor (Satellogic API vs CSDA copies)")
print(res.gdf.groupby(["provider", "affiliation", "constellation"], dropna=False)["sensor"]
      .agg(lambda s: ", ".join(sorted(map(str, s.unique()))[:12])).to_string())
