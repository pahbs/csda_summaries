"""First check of a provider in lib/stac_providers.yaml, for when a vendor's catalog access starts (e.g. airbus, earthdaily).

    python tests/smoke_provider.py earthdaily                  # login, collections, one search at two calibration sites
    python tests/smoke_provider.py airbus --collections Pleiades

Works on a provider still marked enabled: false, so it can be checked before switching it on. Prints only statuses, counts,
collection ids and property NAMES - never tokens or credential values - so the output is safe to share.
"""
import argparse
import sys
import tempfile
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

import multistac  # noqa: E402
import yaml  # noqa: E402
import stac_auth  # noqa: E402

SITES = Path(__file__).resolve().parents[1] / "sites" / "csda_sites_aoi.geojson"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("provider")
    p.add_argument("--collections", nargs="*", help="default: the profile's default_collections, else every collection")
    p.add_argument("--sites", nargs="*", default=["Railroad Valley", "Gobabeb"])
    p.add_argument("--start", default="2025-01-01")
    p.add_argument("--end", default="2026-12-31")
    a = p.parse_args()

    profile = multistac.load_profiles()[a.provider]
    print(f"=== {a.provider}: enabled={profile.get('enabled', True)}, api={profile.get('api', 'stac')}, "
          f"url={profile.get('stac_url') or profile.get('url')}")
    profile = {**profile, "enabled": True}   # checked even before it is switched on: a copy of the profiles with it enabled
    profiles = multistac.load_profiles()
    profiles[a.provider]["enabled"] = True
    copy = Path(tempfile.mkdtemp()) / "stac_providers.yaml"
    copy.write_text(yaml.safe_dump({k: {x: y for x, y in v.items() if x != "name"} for k, v in profiles.items()}, sort_keys=False))
    multistac.PROFILES_PATH = copy

    print("\n=== login")
    try:
        headers = stac_auth.make_auth({**profile, "name": a.provider}).headers()
        print("ok:", ", ".join(sorted(headers)) or "no headers (public)")
    except Exception as error:
        print("FAILED:", type(error).__name__, str(error)[:200])
        return 1

    print("\n=== collections")
    try:
        cols = multistac.collections(a.provider)
        print(len(cols), "collections:", ", ".join(cols["id"].astype(str).head(40)))
    except Exception as error:
        print("FAILED:", type(error).__name__, str(error)[:200])
        return 1

    wanted = a.collections or profile.get("default_collections") or list(cols["id"])[:5]
    print(f"\n=== search {wanted} at {a.sites}, {a.start} to {a.end}")
    sites = multistac.load_sites(str(SITES), site_name_field="Site Name")
    sites = sites[sites.site_name.isin(a.sites)]
    res = multistac.search(sites, a.start, a.end, {a.provider: wanted}, progress=False)
    print(res)
    failed = res.log[res.log.status == "failed"]
    if len(failed):
        print("failed searches:", failed[["site_name", "collection", "error"]].astype(str).head().to_string(index=False))
    if len(res.gdf):
        g = res.gdf
        print("rows by site and collection:", g.groupby(["site_name", "collection"]).size().to_dict())
        for col in ["cloud_cover", "off_nadir", "processing_level", "platform", "sensor", "constellation", "acquisition_id"]:
            if col in g:
                print(f"  {col}: {g[col].notna().mean():.0%} filled, e.g. {g[col].dropna().astype(str).head(3).tolist()}")
        first = res.items[0] if res.items else None
        if first:
            print("item property names:", ", ".join(sorted(first.get("properties", {}))))
            print("asset names (for previews):", ", ".join(sorted(first.get("assets", {}))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
