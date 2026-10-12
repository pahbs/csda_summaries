"""Download assets of multistac search results with your Earthdata credentials.

    import multistac, multistac_download as md
    res = multistac.search(...)
    md.list_assets(res)                                   # what can be downloaded
    manifest = md.download(res, "/explore/nobackup/.../downloads",
                           assets=["metadata", "tile"], roles=None)

Routing is set per provider in stac_providers.yaml (`download:`):
  csda_api   CSDA STAC items via the CSDA download API
             (https://csdap.earthdata.nasa.gov/api/v2/download/{collection}/{item}/{asset}),
             logged in through Earthdata Login - the same flow as csda_client.
  earthdata  direct HTTPS asset links behind Earthdata Login (NASA CMR granules),
             with an Earthdata user token.
Providers without `download:` (e.g. the Satellogic vendor API) are skipped.

Credentials: INI section [EarthData] (username, password) in the multistac
credentials file ($STAC_CREDENTIALS). Tokens stay in memory; nothing secret
is printed or written.
"""

from __future__ import annotations

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Union
from urllib.parse import parse_qs, urlparse

import pandas as pd
import requests

import multistac
import stac_auth

EDL_TOKEN_URL = "https://urs.earthdata.nasa.gov/api/users/find_or_create_token"
CSDA_URL = "https://csdap.earthdata.nasa.gov"
_sessions: Dict[str, requests.Session] = {}
_lock = threading.Lock()


class DownloadAuthError(RuntimeError):
    pass


def _credentials(section: str):
    creds = stac_auth._read_section(section)
    try:
        return creds["username"], creds["password"]
    except KeyError:
        raise DownloadAuthError(f"[{section}] needs 'username' and 'password' keys")


def earthdata_session(section: str = "EarthData") -> requests.Session:
    """Session carrying an Earthdata Login user token (Bearer)."""
    with _lock:
        if "earthdata" not in _sessions:
            user, password = _credentials(section)
            r = requests.post(EDL_TOKEN_URL, auth=(user, password), timeout=60)
            if r.status_code != 200 or "access_token" not in r.text:
                raise DownloadAuthError(f"Earthdata token request failed: HTTP {r.status_code}")
            s = requests.Session()
            s.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
            _sessions["earthdata"] = s
        return _sessions["earthdata"]


def csda_session(section: str = "EarthData", url: str = CSDA_URL) -> requests.Session:
    """Session logged in to the CSDA API through Earthdata Login.

    Same flow as csda_client.CsdaClient.login: CSDA redirects to the Earthdata
    OAuth page, Earthdata (basic auth) returns a code, CSDA exchanges it for a
    token used as Bearer.
    """
    with _lock:
        if "csda" not in _sessions:
            user, password = _credentials(section)
            s = requests.Session()
            r = s.get(f"{url}/api/v1/auth/", params={"redirect_uri": url}, allow_redirects=False, timeout=60)
            edl_url = r.headers.get("Location", "")
            if r.status_code not in (302, 307) or "/oauth/authorize" not in edl_url:
                raise DownloadAuthError(f"CSDA login: expected a redirect to Earthdata, got HTTP {r.status_code}")
            r = s.get(edl_url, auth=(user, password), allow_redirects=False, timeout=60)
            query = parse_qs(urlparse(r.headers.get("Location", "")).query)
            if "resolution_url" in r.text:
                start = r.text.find("resolution_url") + len("resolution_url") + 1
                raise DownloadAuthError("Authorize the CSDA application in Earthdata Login first: "
                                        + r.text[start:r.text.find('"', start)])
            if r.status_code not in (302, 307) or "code" not in query:
                raise DownloadAuthError(f"Earthdata login failed (HTTP {r.status_code}); check [{section}]")
            r = s.post(f"{url}/api/v1/auth/token", data={"code": query["code"][0]}, timeout=60)
            if r.status_code != 200:
                raise DownloadAuthError(f"CSDA token exchange failed: HTTP {r.status_code}")
            s.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
            _sessions["csda"] = s
        return _sessions["csda"]


def reset_sessions() -> None:
    with _lock:
        _sessions.clear()


# --------------------------------------------------------------------------
# What can be downloaded
# --------------------------------------------------------------------------

def asset_table(res_or_gdf) -> pd.DataFrame:
    """One row per (item, asset): provider, collection, id, site_name, asset,
    roles, href, filename. Accepts a SearchResult (with roles) or a result
    GeoDataFrame (asset_<key>_href columns, e.g. read back from res.save())."""
    is_result = isinstance(res_or_gdf, multistac.SearchResult)
    gdf = res_or_gdf.gdf if is_result else res_or_gdf
    rows = []
    if is_result:
        item_of = {(i.get("collection"), i.get("id")): i for i in res_or_gdf.items}
        for r in gdf[["provider", "collection", "id"]].drop_duplicates().itertuples(index=False):
            item = item_of.get((r.collection, r.id), {})
            for key, a in (item.get("assets") or {}).items():
                rows.append({"provider": r.provider, "collection": r.collection, "id": r.id, "asset": key,
                             "roles": ",".join(a.get("roles") or []), "href": a.get("href"),
                             "title": a.get("title")})
    else:
        cols = [c for c in gdf.columns if c.startswith("asset_") and c.endswith("_href")]
        base = gdf[["provider", "collection", "id"] + cols].drop_duplicates(subset=["provider", "id"])
        for c in cols:
            sub = base[base[c].notna()]
            rows += [{"provider": p, "collection": col, "id": i, "asset": c[6:-5], "roles": "", "href": h, "title": None}
                     for p, col, i, h in zip(sub["provider"], sub["collection"], sub["id"], sub[c])]
    df = pd.DataFrame(rows, columns=["provider", "collection", "id", "asset", "roles", "href", "title"])
    df["filename"] = [t if isinstance(t, str) and "." in t else str(h).rstrip("/").split("/")[-1].split("?")[0]
                      for t, h in zip(df["title"], df["href"])]
    return df.drop(columns="title")


def list_assets(res_or_gdf) -> pd.DataFrame:
    """Asset keys available per provider/collection, with roles and item counts."""
    t = asset_table(res_or_gdf)
    if t.empty:
        return t
    out = (t.groupby(["provider", "collection", "asset"])
           .agg(roles=("roles", "first"), items=("id", "nunique")).reset_index())
    profiles = multistac.load_profiles()
    out["download"] = out["provider"].map(lambda p: (profiles.get(p, {}).get("download") or {}).get("type", "not supported"))
    return out


# --------------------------------------------------------------------------
# Download
# --------------------------------------------------------------------------

def _fetch(session: requests.Session, url: str, path: Path, retries: int = 3) -> int:
    tmp = path.with_suffix(path.suffix + ".part")
    for attempt in range(retries + 1):
        try:
            with session.get(url, stream=True, timeout=600, allow_redirects=True) as r:
                if r.status_code in (401, 403):
                    raise DownloadAuthError(f"HTTP {r.status_code}: not authorized for {url.split('?')[0]}")
                r.raise_for_status()
                with open(tmp, "wb") as f:
                    for chunk in r.iter_content(1 << 20):
                        f.write(chunk)
            os.replace(tmp, path)
            return path.stat().st_size
        except DownloadAuthError:
            raise
        except Exception:
            if attempt == retries:
                raise
            time.sleep(2 ** attempt)
    return 0


def download(res_or_gdf, out_dir: Union[str, Path], assets: Optional[Iterable[str]] = None,
             roles: Optional[Iterable[str]] = None, ids: Optional[Iterable[str]] = None,
             overwrite: bool = False, max_workers: int = 4, credentials_section: str = "EarthData",
             dry_run: bool = False, progress: bool = True) -> pd.DataFrame:
    """Download selected assets to out_dir/<provider>/<collection>/<item id>/<file>.

    assets : asset keys to fetch (see list_assets), e.g. ["metadata", "tile"].
    roles : alternatively, STAC asset roles, e.g. ["data", "metadata"]
        (needs a SearchResult, not a bare GeoDataFrame).
    ids : optional subset of item ids.
    dry_run : return the plan (manifest) without downloading.
    Existing files are skipped unless overwrite=True. Returns a manifest
    DataFrame (also written to out_dir/download_manifest.csv).
    """
    if assets is None and roles is None:
        raise ValueError("Choose assets=[...] or roles=[...]; see multistac_download.list_assets(res)")
    t = asset_table(res_or_gdf)
    if assets is not None:
        t = t[t["asset"].isin(list(assets))]
    if roles is not None:
        wanted = set(roles)
        t = t[t["roles"].map(lambda r: bool(wanted & set(r.split(","))))]
    if ids is not None:
        t = t[t["id"].isin(list(ids))]
    profiles = multistac.load_profiles()
    t = t.assign(method=t["provider"].map(lambda p: (profiles.get(p, {}).get("download") or {}).get("type")))
    out_dir = Path(out_dir)
    t["path"] = [str(out_dir / multistac._safe(p) / multistac._safe(c) / multistac._safe(i) / multistac._safe(f))
                 for p, c, i, f in zip(t["provider"], t["collection"], t["id"], t["filename"])]
    t["status"], t["bytes"], t["error"] = "planned", 0, None
    t.loc[t["method"].isna(), "status"] = "skipped: no download route"
    if dry_run or t.empty:
        return t.reset_index(drop=True)

    def one(row) -> dict:
        path = Path(row["path"])
        if path.exists() and path.stat().st_size > 0 and not overwrite:
            return {"status": "exists", "bytes": path.stat().st_size}
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            if row["method"] == "csda_api":
                url = (f"{(profiles[row['provider']]['download'].get('url') or CSDA_URL)}/api/v2/download/"
                       f"{row['collection']}/{row['id']}/{row['asset']}")
                size = _fetch(csda_session(credentials_section), url, path)
            elif row["method"] == "earthdata":
                if not str(row["href"]).startswith("http"):
                    return {"status": "failed", "error": "no HTTPS link"}
                size = _fetch(earthdata_session(credentials_section), row["href"], path)
            else:
                return {"status": f"skipped: unknown method {row['method']}"}
            return {"status": "downloaded", "bytes": size}
        except Exception as error:
            try:
                path.parent.rmdir()  # only removes the item folder if it is empty
            except OSError:
                pass
            return {"status": "failed", "error": str(error)[:300]}

    todo = t[t["status"] == "planned"]
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(one, row): idx for idx, row in todo.iterrows()}
        iterator = as_completed(futures)
        if progress:
            try:
                from tqdm import tqdm
                iterator = tqdm(iterator, total=len(futures), desc="downloads")
            except ImportError:
                pass
        for fut in iterator:
            for k, v in fut.result().items():
                t.at[futures[fut], k] = v
    t = t.reset_index(drop=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    t.drop(columns=["href"]).to_csv(out_dir / "download_manifest.csv", index=False)
    return t
