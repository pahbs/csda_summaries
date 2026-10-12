"""Smoke test for multistac_download with YOUR Earthdata credentials.

Run in the ILAB TensorFlow env:
    python tests/smoke_download.py [out_dir]

Downloads one small metadata file from CSDA STAC (CSDA download API) and one
from NASA CMR (Earthdata HTTPS), then prints statuses and file sizes only.
Uses [EarthData] username/password from the credentials INI; nothing secret
is printed.
"""

import sys
import tempfile
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

import multistac  # noqa: E402
import multistac_download as md  # noqa: E402

out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tempfile.mkdtemp(prefix="multistac_dl_"))
sites = multistac.load_sites(str(Path(__file__).resolve().parents[1] / "sites" / "csda_sites_aoi.geojson"),
                             site_name_field="Site Name")
sites = sites[sites.site_name == "San Diego"]
res = multistac.search(sites, "2024-06-01", "2025-06-01",
                       {"csda": ["satellogic"], "csda-cmr": ["WV03_MSI_L1B"]}, progress=False)
print(res)
one_each = [res.gdf[res.gdf.provider == p]["id"].iloc[0] for p in ("csda", "csda-cmr")
            if (res.gdf.provider == p).any()]
manifest = md.download(res, out, assets=["xml-metadata", "xml"], ids=one_each, progress=False)
print(manifest[["provider", "collection", "asset", "status", "bytes", "error"]].to_string(index=False))
print("Files in", out)
ok = (manifest["status"] == "downloaded").all() and (manifest["bytes"] > 0).all() and len(manifest) == 2
print("ALL PASSED" if ok else "SOME DOWNLOADS FAILED")
