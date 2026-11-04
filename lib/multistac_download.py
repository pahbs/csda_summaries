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
  earthdata  direct HTTPS asset links behind Earthdata Login, with an
             Earthdata user token.
  cumulus    CSDA's legacy archive in NASA CMR (data.csdap.earthdata.nasa.gov):
             protected files sit behind CSDA's own Cognito sign-in, not an
             Earthdata token. Call cumulus_login() first; it asks for your
             Cognito username, password (getpass) and authenticator MFA code.
             download(..., via="s3") fetches the same files from S3 with
             temporary AWS keys from CSDA's /s3credentials (renewed hourly).
Providers without `download:` (e.g. the Satellogic vendor API) are skipped.

Credentials: INI section [EarthData] (username, password) in the multistac
credentials file ($STAC_CREDENTIALS), or typed in for cumulus_login(). Tokens
and cookies stay in memory; nothing secret is printed or written.
"""

from __future__ import annotations

import getpass
import html
import html.parser
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Union
from urllib.parse import parse_qs, urljoin, urlparse

import pandas as pd
import requests

import multistac
import stac_auth

EDL_TOKEN_URL = "https://urs.earthdata.nasa.gov/api/users/find_or_create_token"
CSDA_URL = "https://csdap.earthdata.nasa.gov"
CUMULUS_S3_CREDENTIALS = "https://data.csdap.earthdata.nasa.gov/s3credentials"
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


class _Inputs(html.parser.HTMLParser):
    """Collects <input name=... value=...> from a sign-in page."""

    def __init__(self, text: str):
        super().__init__()
        self.values: Dict[str, str] = {}
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag.lower() == "input" and a.get("name"):
            self.values[a["name"]] = a.get("value") or ""  # last one wins, as in the test notebook


def _s3_keys(r) -> Optional[dict]:
    """Temporary S3 keys from a /s3credentials response, whatever its Content-Type."""
    try:
        c = r.json()
    except ValueError:
        return None
    return c if isinstance(c, dict) and "accessKeyId" in c else None


def _describe(r) -> str:
    """Short, secret-free description of an unexpected response."""
    title = re.search(r"(?is)<title>(.*?)</title>", r.text or "")
    return (f"HTTP {r.status_code}, {r.headers.get('Content-Type', '?')}, at {urlparse(r.url).netloc}"
            f"{urlparse(r.url).path}" + (f", page '{title.group(1).strip()[:60]}'" if title else ""))


def cumulus_login(username: Optional[str] = None, password: Optional[str] = None,
                  mfa_code: Optional[str] = None) -> requests.Session:
    """Sign in to CSDA's protected archive (Cognito hosted login + authenticator
    MFA) and keep the session for downloads with method `cumulus`.

    Same flow as notebooks/earthdata_s3_access_test.ipynb: open /s3credentials,
    post username/password to the Cognito form, then the MFA code; the
    redirect lands back on /s3credentials with temporary S3 keys, which are
    kept for cumulus_s3_client(). Anything not given is prompted for
    (password via getpass). Nothing is printed or written.
    """
    s = requests.Session()
    page = s.get(CUMULUS_S3_CREDENTIALS, timeout=60)
    page.raise_for_status()
    form = _Inputs(page.text)
    if "_csrf" not in form.values:
        raise DownloadAuthError("Could not find the sign-in form on the CSDA login page")
    if username is None:
        username = input("CSDA Cognito username: ").strip()
    if password is None:
        password = getpass.getpass("CSDA Cognito password: ")
    data = {"_csrf": form.values["_csrf"], "username": username, "password": password}
    if form.values.get("cognitoAsfData"):
        data["cognitoAsfData"] = form.values["cognitoAsfData"]
    page = s.post(page.url, data=data, timeout=60)
    page.raise_for_status()

    keys = _s3_keys(page)
    if keys is None:
        mfa = _Inputs(page.text)
        if "_csrf" not in mfa.values or "password" in mfa.values:
            raise DownloadAuthError("CSDA sign-in failed (wrong username/password?)")
        if mfa_code is None:
            mfa_code = input("CSDA authenticator MFA code: ").strip()
        r = s.post(page.url, allow_redirects=False, timeout=60,
                   data={"_csrf": mfa.values["_csrf"], "authentication_code": mfa_code,
                         "cognitoAsfData": mfa.values.get("cognitoAsfData", "")})
        if r.is_redirect:
            r = s.get(urljoin(r.url, r.headers["Location"]), timeout=60)
        r.raise_for_status()
        keys = _s3_keys(r)
        if keys is None:
            r = s.get(CUMULUS_S3_CREDENTIALS, timeout=60)
            keys = _s3_keys(r)
        if keys is None:
            raise DownloadAuthError(f"CSDA sign-in failed after the MFA step (wrong code?): {_describe(r)}")
    with _lock:
        _sessions["cumulus"] = s
        _s3.clear()
        _s3["credentials"] = keys
    print("Signed in to the CSDA archive; temporary S3 credentials acquired")
    return s


_s3: Dict[str, object] = {}


def cumulus_s3_client(interactive: bool = True):
    """boto3 S3 client with the temporary keys from CSDA's /s3credentials
    (needs cumulus_login first). Keys last ~1 h; when < 5 min remain they are
    renewed with the signed-in session, or you are asked to sign in again."""
    import boto3
    from botocore.config import Config
    with _lock:
        now = pd.Timestamp.now(tz="UTC")
        expires = _s3.get("expires")
        if "client" in _s3 and expires is not None and now < expires - pd.Timedelta(minutes=5):
            return _s3["client"]
        c = _s3.pop("credentials", None)
        if c is None and "cumulus" in _sessions:
            c = _s3_keys(_sessions["cumulus"].get(CUMULUS_S3_CREDENTIALS, timeout=60))
    if c is None:
        if not interactive:
            raise DownloadAuthError("Temporary S3 credentials expired; run cumulus_login() and rerun "
                                    "download (finished files are skipped)")
        print("Temporary S3 credentials expired or missing; sign in again.")
        cumulus_login()
        with _lock:
            c = _s3.pop("credentials")
    if not {"accessKeyId", "secretAccessKey", "sessionToken"} <= set(c):
        raise DownloadAuthError("CSDA response did not contain temporary S3 credentials")
    client = boto3.client("s3", region_name="us-west-2", aws_access_key_id=c["accessKeyId"],
                          aws_secret_access_key=c["secretAccessKey"], aws_session_token=c["sessionToken"],
                          config=Config(retries={"max_attempts": 5, "mode": "standard"}))
    expires = pd.Timestamp(c["expiration"]) if c.get("expiration") else pd.Timestamp.now(tz="UTC") + pd.Timedelta(minutes=55)
    with _lock:
        _s3["client"] = client
        _s3["expires"] = expires if expires.tzinfo else expires.tz_localize("UTC")
    return client


def _fetch_s3(s3_href: str, path: Path, retries: int = 3) -> int:
    from botocore.exceptions import ClientError
    bucket, key = s3_href[5:].split("/", 1)
    tmp = path.with_suffix(path.suffix + ".part")
    for attempt in range(retries + 1):
        try:
            cumulus_s3_client(interactive=False).download_file(bucket, key, str(tmp))
            os.replace(tmp, path)
            return path.stat().st_size
        except ClientError as error:
            code = error.response.get("Error", {}).get("Code", "")
            if code in ("ExpiredToken", "InvalidToken") and attempt < retries:
                _s3.clear(); continue
            if code in ("403", "AccessDenied", "Forbidden"):
                raise DownloadAuthError(f"S3 403 Forbidden for {key.rsplit('/', 1)[-1]}: the CSDA bucket policy "
                                        "only allows approved in-region (AWS us-west-2) access; run on a cloud "
                                        "platform or use via='https'")
            if attempt == retries:
                raise
            time.sleep(2 ** attempt)
    return 0


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
    # Not isinstance: after importlib.reload(multistac), an existing result is an
    # instance of the old SearchResult class
    is_result = hasattr(res_or_gdf, "gdf") and hasattr(res_or_gdf, "items")
    gdf = res_or_gdf.gdf if is_result else res_or_gdf
    rows = []
    if is_result:
        item_of = {(i.get("collection"), i.get("id")): i for i in res_or_gdf.items}
        for r in gdf[["provider", "collection", "id"]].drop_duplicates().itertuples(index=False):
            item = item_of.get((r.collection, r.id), {})
            for key, a in (item.get("assets") or {}).items():
                rows.append({"provider": r.provider, "collection": r.collection, "id": r.id, "asset": key,
                             "roles": ",".join(a.get("roles") or []), "href": a.get("href"),
                             "s3_href": ((a.get("alternate") or {}).get("s3") or {}).get("href"),
                             "title": a.get("title")})
    else:
        cols = [c for c in gdf.columns if c.startswith("asset_") and c.endswith("_href")]
        base = gdf[["provider", "collection", "id"] + cols].drop_duplicates(subset=["provider", "id"])
        for c in cols:
            sub = base[base[c].notna()]
            rows += [{"provider": p, "collection": col, "id": i, "asset": c[6:-5], "roles": "", "href": h,
                      "s3_href": None, "title": None}
                     for p, col, i, h in zip(sub["provider"], sub["collection"], sub["id"], sub[c])]
    df = pd.DataFrame(rows, columns=["provider", "collection", "id", "asset", "roles", "href", "s3_href", "title"])
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
                if "html" in r.headers.get("Content-Type", "") and not path.suffix.startswith(".htm"):
                    raise DownloadAuthError(f"Got a web page (sign-in?) instead of {path.name}")
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
             via: str = "https", dry_run: bool = False, progress: bool = True) -> pd.DataFrame:
    """Download selected assets to out_dir/<provider>/<collection>/<item id>/<file>.

    assets : asset keys to fetch (see list_assets), e.g. ["metadata", "tile"].
    roles : alternatively, STAC asset roles, e.g. ["data", "metadata"]
        (needs a SearchResult, not a bare GeoDataFrame).
    ids : optional subset of item ids.
    via : "https" (default) or "s3" - for `cumulus` providers, fetch from the
        S3 copy with temporary keys (cumulus_login first).
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
            elif row["method"] == "cumulus":
                if "cumulus" not in _sessions:
                    raise DownloadAuthError("Not signed in: run multistac_download.cumulus_login() first")
                if via == "s3":
                    if not row.get("s3_href"):
                        return {"status": "failed", "error": "no S3 link"}
                    size = _fetch_s3(row["s3_href"], path)
                else:
                    size = _fetch(_sessions["cumulus"], row["href"], path)
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
    if via == "s3" and (todo["method"] == "cumulus").any():
        cumulus_s3_client()  # sign in / renew keys here, not inside worker threads
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
    t.drop(columns=["href", "s3_href"]).to_csv(out_dir / "download_manifest.csv", index=False)
    return t
