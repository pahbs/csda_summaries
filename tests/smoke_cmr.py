"""Smoke test for the NASA CMR backend (csda-cmr). No credentials needed.

Run in the ILAB TensorFlow env (the notebook kernel):
    python tests/smoke_cmr.py

Checks: count matches CMR's own hit count, paging across pages, cloud cover
in percent with the server filter applied, stable asset keys, and a combined
CSDA STAC + CMR search with in_csda.
"""

import sys
import warnings
from pathlib import Path

import requests

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

import multistac  # noqa: E402
from shapely.geometry.polygon import orient  # noqa: E402

SITES = Path(__file__).resolve().parents[1] / "sites" / "csda_sites_aoi.geojson"
sites = multistac.load_sites(str(SITES), site_name_field="Site Name")
sd = sites[sites.site_name == "San Diego"]
ok = True


def check(label, passed, detail=""):
    global ok
    ok &= bool(passed)
    print(f"{'PASS' if passed else 'FAIL'}  {label}  {detail}")


print(multistac.collections("csda-cmr").to_string(index=False))

# Count vs CMR hits, with 3+ pages
prov = multistac.get_provider("csda-cmr")
prov.search_cfg["page_size"] = 150
res = multistac.search(sd, "2010-01-01", "2026-10-01", {"csda-cmr": ["WV02_Pan_L1B"]}, progress=False)
prov.search_cfg["page_size"] = 1000
poly = orient(sd.geometry.iloc[0].convex_hull, 1.0)
hits = int(requests.get(f"{prov.url}/granules.json", params={
    "provider": "CSDA", "short_name": "WV02_Pan_L1B", "page_size": 0,
    "temporal": "2010-01-01T00:00:00Z,2026-10-01T23:59:59Z",
    "polygon": ",".join(f"{x},{y}" for x, y in poly.exterior.coords)}, timeout=120).headers["CMR-Hits"])
check("count matches CMR hits (paged)", res.gdf.id.nunique() == hits == len(res.gdf), f"{len(res.gdf)} vs {hits}")

# Cloud cover: percent, server filter, no leaks
both = {"csda-cmr": ["WV03_MSI_L1B"]}
allc = multistac.search(sd, "2014-01-01", "2026-10-01", both, progress=False).gdf
low = multistac.search(sd, "2014-01-01", "2026-10-01", both, cloud_cover_max=10, progress=False)
check("cloud cover in percent", allc.cloud_cover.max() > 1, f"max {allc.cloud_cover.max()}")
check("cloud filter server-side", "cql2" in low.log.server_filters.iloc[0], low.log.server_filters.iloc[0])
check("cloud filter matches local", len(low.gdf) == int((allc.cloud_cover <= 10).sum()),
      f"{len(low.gdf)} vs {int((allc.cloud_cover <= 10).sum())}")

# Stable asset keys
assets = sorted(c for c in allc.columns if c.startswith("asset_"))
check("stable asset keys", len(assets) <= 8, str(assets))

# Combined CSDA STAC + CMR
combo = multistac.search(sd, "2020-01-01", "2025-12-31", {"csda": ["maxar-legion", "satellogic"], "csda-cmr": None},
                         cloud_cover_max=20, progress=False)
print(combo)
print(combo.summary().to_string(index=False))
check("no failed tasks", (combo.log.status != "failed").all())
check("CMR rows are CSDA holdings", combo.gdf.loc[combo.gdf.provider == "csda-cmr", "in_csda"].all())
print("\nALL PASSED" if ok else "\nSOME CHECKS FAILED")
