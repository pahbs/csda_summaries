"""Site names from a requests spreadsheet, on SharePoint or on disk, for the multistac site notebooks.

    table = site_request.read_table(link_or_path, sheet="API search", client_id=...)
    names, missing = site_request.match_names(site_request.site_names(table), sites.site_name)

A SharePoint link is read through Microsoft Graph with your own NASA sign-in: a device code is printed, you enter it
in any browser, and the workbook is read into memory. The token stays in memory and the workbook is not saved.
This needs the client ID of an app registered in the tenant, with delegated Files.Read.All.
"""

from __future__ import annotations

import base64
import difflib
import io
import re
import time
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

import pandas as pd
import requests

LOGIN = "https://login.microsoftonline.com"
GRAPH = "https://graph.microsoft.com/v1.0"
SCOPE = "https://graph.microsoft.com/Files.Read.All"
NAME_COLUMNS = ("site name", "site_name", "site", "name")
MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
REL_ID = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"


def share_id(url: str) -> str:
    """Graph's id for a sharing link: 'u!' + unpadded base64url of the link."""
    return "u!" + base64.urlsafe_b64encode(url.encode()).decode().rstrip("=")


def device_code_token(client_id: str, tenant: str = "organizations", session=requests) -> str:
    """Access token for your account: prints a code to enter in a browser, then waits for the sign-in."""
    base = f"{LOGIN}/{tenant}/oauth2/v2.0"
    flow = session.post(f"{base}/devicecode", data={"client_id": client_id, "scope": SCOPE}, timeout=60).json()
    if "device_code" not in flow:
        raise RuntimeError(f"Sign-in could not start: {flow.get('error')}: {flow.get('error_description', '')[:300]}")
    print(flow["message"])
    interval, deadline = flow.get("interval", 5), time.time() + flow.get("expires_in", 900)
    while time.time() < deadline:
        time.sleep(interval)
        r = session.post(f"{base}/token", timeout=60, data={"client_id": client_id, "device_code": flow["device_code"],
                                                            "grant_type": "urn:ietf:params:oauth:grant-type:device_code"}).json()
        if "access_token" in r:
            return r["access_token"]
        if r.get("error") == "slow_down":
            interval += 5
        elif r.get("error") != "authorization_pending":
            raise RuntimeError(f"Sign-in failed: {r.get('error')}: {r.get('error_description', '')[:300]}")
    raise TimeoutError("Sign-in timed out: the code was not entered in time.")


def _xlsx_table(data: bytes, sheet: str, header: int = 0) -> pd.DataFrame:
    """One sheet of an .xlsx as text, with the standard library: the notebook's kernel has no openpyxl.
    `header` is the 0-based sheet row of the column names; values come back as strings (formulas as their last result)."""
    z = zipfile.ZipFile(io.BytesIO(data))
    sheets = {s.get("name"): s.get(REL_ID) for s in ET.fromstring(z.read("xl/workbook.xml")).find(MAIN + "sheets")}
    if sheet not in sheets:
        raise KeyError(f"No sheet {sheet!r}; sheets: {list(sheets)}")
    target = {r.get("Id"): r.get("Target") for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))}[sheets[sheet]]
    path = target.lstrip("/") if target.startswith("/") else f"xl/{target}"
    strings = []
    if "xl/sharedStrings.xml" in z.namelist():
        strings = ["".join(t.text or "" for t in si.iter(MAIN + "t")) for si in ET.fromstring(z.read("xl/sharedStrings.xml"))]
    rows = {}
    for row in ET.fromstring(z.read(path)).iter(MAIN + "row"):
        for c in row.findall(MAIN + "c"):
            letters = re.match(r"[A-Z]+", c.get("r")).group()
            col = 0
            for ch in letters:
                col = col * 26 + ord(ch) - 64
            v = c.find(MAIN + "v")
            if c.get("t") == "inlineStr":
                value = "".join(t.text or "" for t in c.iter(MAIN + "t"))
            elif v is None or v.text is None:
                continue
            else:
                value = strings[int(v.text)] if c.get("t") == "s" else v.text
            rows.setdefault(int(row.get("r")) - 1, {})[col - 1] = value
    width = max((max(r) for r in rows.values()), default=-1) + 1
    names = [rows.get(header, {}).get(i, f"Unnamed: {i}") for i in range(width)]
    body = [[rows[n].get(i) for i in range(width)] for n in sorted(rows) if n > header]
    return pd.DataFrame(body, columns=names)


def read_table(source: str, sheet: str, header: int = 0, client_id: Optional[str] = None,
               tenant: str = "organizations") -> pd.DataFrame:
    """One sheet of a workbook at a SharePoint link or a local path, as a DataFrame. Links need client_id."""
    if not str(source).lower().startswith("http"):
        return _xlsx_table(Path(source).read_bytes(), sheet, header)
    if not client_id:
        raise ValueError("A SharePoint link needs SHAREPOINT_CLIENT_ID (an app registered in the NASA tenant). "
                         "Otherwise save the workbook on ADAPT and set SITE_REQUEST to its path.")
    token = device_code_token(client_id, tenant)
    r = requests.get(f"{GRAPH}/shares/{share_id(source)}/driveItem/content", timeout=120,
                     headers={"Authorization": f"Bearer {token}"})
    if not r.ok:
        raise RuntimeError(f"Graph could not read the workbook: HTTP {r.status_code}: {r.text[:300]}")
    return _xlsx_table(r.content, sheet, header)


def site_names(table: pd.DataFrame, column: Optional[str] = None) -> List[str]:
    """Unique, non-empty names in `column`, or in the first column with a usual site-name header."""
    if column is None:
        found = [c for c in table.columns if str(c).strip().lower() in NAME_COLUMNS]
        if not found:
            raise KeyError(f"No site name column found; set SITE_REQUEST_COLUMN. Columns: {list(table.columns)}")
        column = found[0]
    names = table[column].dropna().astype(str).map(lambda n: " ".join(n.split()))   # also a non-breaking space
    return list(dict.fromkeys(n for n in names if n))


def match_names(requested: Iterable[str], known: Iterable[str]) -> Tuple[List[str], pd.DataFrame]:
    """Requested names as spelled in the sites file (case ignored), and a table of those not found with close names."""
    known = list(known)
    lower = {k.lower(): k for k in known}
    matched, missing = [], []
    for name in requested:
        if name.lower() in lower:
            matched.append(lower[name.lower()])
        else:
            close = difflib.get_close_matches(name.lower(), list(lower), n=3, cutoff=0.6)
            missing.append({"requested": name, "closest_in_sites_file": ", ".join(lower[c] for c in close)})
    return matched, pd.DataFrame(missing, columns=["requested", "closest_in_sites_file"])
