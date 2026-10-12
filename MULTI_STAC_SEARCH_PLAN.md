# Plan: one search across many commercial STAC APIs

**Status:** phases 1–4 implemented for CSDA and Satellogic (2026-10-11): `lib/stac_providers.yaml`, `lib/stac_auth.py`, `lib/multistac.py`, `tests/smoke_multistac.py`, `notebooks/multistac_search_tutorial.ipynb`. Hydrosat is on hold (see section 12).
**Goal:** Use one call to search every STAC API I have access to. The search takes a sites GeoJSON, a time range and optional filters such as collection, cloud cover and product level. It returns one harmonized GeoDataFrame plus the raw STAC items. Each vendor's differences live in a **provider profile**, not in the search code.

---

## 1. What exists today (and why it does not scale)

| Piece | Where | Problem |
|---|---|---|
| `stac_search_site()` | `lib/staclib.py` | CSDA URL is hardcoded and the search uses `pystac_client`. |
| `stac_search_site_satellogic()` | `lib/staclib.py` | This is a near-copy of the function above, with a different client. A new vendor would mean another copy. |
| `SatellogicAuth`, `SatellogicSTACClient` | `lib/satellogic_auth.py`, `lib/satellogic_stac.py` | They are written for one vendor. They mimic `pystac_client` because it handles custom auth headers poorly (the custom header name is `authorizationToken`, plus a contract-ID header). |
| `searchlib.search_global_stac()` | `lib/searchlib.py` | It has good resumable, checkpointed, threaded searching, but it works only with CSDA. |
| `crosswalk_stac_gdf()` | `csda_stac_search_multiple.ipynb` | It guesses the cloud and platform fields by keyword after the search runs. It is brittle and lives only in a notebook. |
| Credential path | Hardcoded `/home/pmontesa/code/credentials.ini` in `staclib.py` and the notebooks | That is fine for one user. The repo is **public**, so the path should come from an environment variable, with this path as the fallback default. |

The pieces worth keeping are `_build_seasonal_intervals`, `create_site_dict_from_gdf`, the checkpoint pattern in `searchlib.py`, `stac_items_to_gdf`, and the profile-driven idea already used in `sensor_profiles.py`.

---

## 2. Design overview

```
sites.geojson ─┐
dates/months  ─┤        ┌───────────────┐   per provider   ┌──────────────┐
filters       ─┼──────► │  SearchRequest │ ───────────────► │  translate() │──► vendor-specific payload
providers     ─┘        └───────────────┘                   └──────────────┘
                                                                   │
                         provider profile (YAML, no secrets) ──────┤
                         credentials.ini (secret, outside repo) ─► Auth plugin ─► authenticated session
                                                                   │
                                                          StacApiClient (requests)
                                                          POST/GET /search + pagination + retries
                                                                   │
                                                          normalize() via profile field map
                                                                   │
                                        one GeoDataFrame (+ raw items, + run log), cached per task
```

There are four layers, each with one job:

1. **Provider profile.** This is declarative: where the API lives, how it authenticates (but never the secrets), which query features it supports, and how its property names map to common names.
2. **Auth plugin.** It turns a profile and a credentials section into an authenticated `requests.Session`. It also refreshes tokens. There are a few types, reused across vendors.
3. **STAC client.** One small `requests`-based client handles every provider: building the `/search` request, following `next` links (both POST-body-merge and GET-href styles), retries and backoff, and rate limiting. It replaces both `pystac_client` (for search) and `SatellogicSTACClient`.
4. **Runner.** It expands sites × providers × time intervals into tasks, runs them in parallel with per-provider concurrency limits, checkpoints each task to disk, then normalizes and combines the results.

### Why not `pystac_client` for everything?
You already found that it struggles with vendor auth headers. Vendors also differ in pagination, datetime strictness and filter extensions. One small client gives every provider identical behavior and error handling. Items stay plain dicts, and `pystac.Item.from_dict()` turns them into `pystac.Item` objects for the download code (`CsdaClient`) when needed.

---

## 3. Provider profiles

There is one YAML file, `lib/stac_providers.yaml`, committed to the repo. It contains **no secrets**, only the *name* of the credentials section to use.

```yaml
csda:
  label: NASA CSDA
  stac_url: https://csdap.earthdata.nasa.gov/stac
  auth: {type: none}                         # search is public; assets need an Earthdata token
  search: {method: POST, page_size: 250, max_concurrency: 8}
  geometry: intersects                       # send real site polygon
  filter_mode: query                         # STAC 'query' extension (verify vs cql2)
  default_collections: [planet, airbus-optical, satellogic, maxar-legion]
  fields:
    cloud_cover: eo:cloud_cover
    product_level: processing:level
    platform: platform
    gsd: gsd
    off_nadir: view:off_nadir
    vendor_item_id: [csda:item_id, pl:product_id]   # first non-null wins

satellogic:
  label: Satellogic
  stac_url: https://api.satellogic.com/v2/archive
  auth:
    type: satellogic                         # OAuth2 client-credentials + contract header
    credentials_section: Satellogic_STAC_API
    token_url: https://auth.platform.satellogic.com/oauth/token
    audience: https://api.satellogic.com/
    token_header: authorizationToken         # non-standard header name
    contract_url: https://api.satellogic.com/contracts
  search: {method: POST, page_size: 1000, max_concurrency: 2}
  datetime_format: full_iso_z                # rejects bare dates
  geometry: bbox                             # verify whether 'intersects' works
  filter_mode: client                        # until verified server-side
  default_collections: [quickview-visual]
  fields:
    cloud_cover: eo:cloud_cover              # verify
    gsd: gsd

hydrosat:
  label: Hydrosat
  stac_url: https://stac.hydrosat.com
  auth:
    type: oauth2_client_credentials          # to confirm
    credentials_section: Hydrosat_STAC_API   # name TBD by you
    token_url: TBD
  search: {method: POST, page_size: 100, max_concurrency: 2}
  geometry: intersects
  filter_mode: cql2-json                     # verify via /queryables
  fields: {}                                 # fill from /queryables
```

**Profile keys**

- `auth`: the plugin `type` plus any non-secret parameters.
- `search`: the method, page size, `max_concurrency` (for politeness and rate limits) and timeout.
- `geometry`: `intersects` sends the site polygon. `bbox` sends the polygon bounds, and the runner then clips the results locally with an intersection test so that bbox overshoot is removed.
- `datetime_format`: `iso` or `full_iso_z`, because some APIs reject `YYYY-MM-DD`.
- `filter_mode`: `query`, `cql2-json` or `client`. This says how cloud cover and product level are sent. See section 5.
- `fields`: the map from vendor property names to the common column names. This **replaces the keyword guessing in `crosswalk_stac_gdf`**.
- `product_levels`: an optional map from my generic level names to vendor values, for example `{L1: "L1B", ortho: "ortho"}`.
- `backend`: `stac` by default. This leaves room for a non-STAC adapter later (see section 9).

Adding a vendor normally means adding a profile block and a credentials section. New code is needed only when a vendor's auth flow is genuinely new.

---

## 4. Credentials and secrets

- There is a single INI file **outside the repo**. Its path comes from the env var `STAC_CREDENTIALS`, falling back to `~/code/credentials.ini` (your current file). One section per provider, for example `[Satellogic_STAC_API]` with `client_id` and `client_secret`.
- Profiles hold only the section *name*. Auth plugins read only the keys they need, and only when they need them (lazily, so searching CSDA never opens the file).
- Rules the code will enforce:
  - Secrets never appear in logs, exception messages, `repr()` or saved run manifests. HTTP errors report the status code and response body, never the request headers.
  - Tokens stay in memory only, not cached to disk. I'm open to a disk cache later with `0600` permissions if token-fetch rate limits become a problem.
  - Run manifests record the provider and section *name* only.
- **For me (Claude):** I will not open, `cat`, grep or otherwise read the credentials file, and I will not run code that loads it. To test the authenticated providers, **you** run a smoke-test script I write that prints only counts and status. I can test CSDA myself because its search is public.
- Housekeeping, separate from this work: `stac_search_tutorial-satellogic.ipynb` has inline auth cells. They read from the INI file, which is good, but before you publish it, make sure no token or contract ID is left in the cell outputs.

### Auth plugin types (initial set)

| type | Used by | Behavior |
|---|---|---|
| `none` | CSDA search | A plain session. |
| `bearer_env` | CSDA assets, other token-in-env cases | Adds `Authorization: Bearer $ENVVAR` (for example `EARTHDATA_TOKEN`, matching `searchlib.py`). |
| `oauth2_client_credentials` | Hydrosat (likely), EarthDaily, others | Generic: token URL, audience or scope, refresh 5 min before expiry. |
| `satellogic` | Satellogic | Subclass of the OAuth2 plugin that adds the `authorizationToken` header name and the `X-Satellogic-Contract-Id` lookup. This is a port of `SatellogicAuth`. |
| `api_key_header` | Vendors with static keys | Puts the key in a header (name set in the profile). |
| `api_key_exchange` | For example Airbus OneAtlas style | Exchanges an API key for a short-lived bearer token. |

Each plugin returns a `requests.Session`. The client calls `auth.refresh_if_needed(session)` before each page, so long paginated searches survive token expiry.

---

## 5. The unified search request

```python
import multistac

res = multistac.search(
    sites="sites/eval_sites_aoi.geojson",   # path, URL, or GeoDataFrame
    site_name_field="Site Name",
    start="2023-01-01", end="2026-10-01",
    months=[6, 7, 8],                        # optional seasonal subset (reuses _build_seasonal_intervals)
    providers={
        "csda":       {"collections": ["airbus-optical", "planet"]},
        "satellogic": {"collections": ["quickview-visual"]},
        "hydrosat":   {},                    # {} → profile default_collections
    },
    cloud_cover_max=20,                      # generic filter
    product_level=None,                      # generic filter, mapped per profile
    extra={"csda": {"query": {...}}},        # raw passthrough per provider (escape hatch)
    buffer_m=0,
    cache_dir="/explore/nobackup/people/pmontesa/stac_cache",
    max_workers=8,
)

res.gdf      # harmonized GeoDataFrame, one row per (provider, item, site)
res.items    # raw STAC item dicts (→ pystac.Item.from_dict for downloads)
res.log      # DataFrame: provider, site, interval, status, count, error, filter_mode_used
res.save("stac_eval_JJA")   # writes .gpkg + .csv (asset/list columns flattened) + items .json
```

**How generic filters are applied.** Each profile's `filter_mode` decides:

- `query`: `{"query": {"eo:cloud_cover": {"lte": 20}}}`
- `cql2-json`: `{"filter-lang": "cql2-json", "filter": {"op": "<=", "args": [{"property": "eo:cloud_cover"}, 20]}}`
- `client`: nothing is sent to the server, and the filter is applied after normalization.

The same filter is **always re-applied on the client** after normalization. A provider that silently ignores a filter therefore cannot leak results. `res.log` records whether the filter ran on the server or only on the client.

**Discovery helpers.** These help fill in profiles and choose collections:

- `multistac.list_providers()`: the configured providers and whether credentials are present (it checks only that the section exists, never the values).
- `multistac.collections("satellogic")`: the collection IDs and titles.
- `multistac.queryables("hydrosat", collection=...)`: the property names, which are what populates `fields:`.
- `multistac.sample_item("hydrosat", collection=...)`: one item, for checking field names by eye.

---

## 6. Normalized output schema

Every row has these common columns, followed by all of the vendor's raw properties. Nothing is dropped, so the vendor-specific columns stay available.

| column | notes |
|---|---|
| `provider` | Profile key, for example `csda` or `satellogic`. This is the API that was searched. |
| `vendor` | The data owner. Through CSDA it can differ from `provider`: CSDA serves Planet, Airbus, Satellogic and Maxar/Vantor data. |
| `collection`, `id`, `datetime` (UTC), `site_name`, `geometry` | |
| `cloud_cover`, `product_level`, `platform`, `gsd`, `off_nadir`, `sun_elevation` | Mapped through the profile `fields`. NaN when the vendor lacks the field. |
| `vendor_item_id` | Used for cross-provider de-duplication. |
| `stac_self_href` | A link back to the item. |

**Cross-provider duplicates.** The same Satellogic scene can come back from both CSDA and the Satellogic API. `res.dedupe(prefer=["satellogic", "csda"])` would keep one row per `vendor_item_id`. This is optional and off by default, because which one to keep is a decision you make.

---

## 7. Runner, parallelism, caching

- **Tasks:** provider × collection × site × interval. Seasonal months become several intervals.
- **Threads, not processes.** The work is I/O-bound, and threads let one auth session and token be shared per provider. Today each `Pool` worker re-authenticates for every site.
- **Concurrency:** a global `max_workers`, plus a per-provider semaphore set by `max_concurrency`, so small vendor APIs are not overloaded.
- **Checkpointing:** I'll adopt the `searchlib.py` pattern. Each task writes an atomic GeoJSON under `cache_dir/<run-hash>/<provider>/<collection>/<interval>/<site>.geojson`. A re-run skips tasks that already finished and retries failed ones. The run hash covers the search settings but not the credentials.
- **Retries:** backoff on 429 and 5xx responses. `Retry-After` is honored when present.
- **Large AOIs and global searches:** `searchlib.create_global_tiles` can feed the same runner as "sites", so `search_global_stac` becomes one more caller of the runner.

---

## 8. Code layout

The repo convention is a flat `lib/` folder imported through `sys.path`, so:

```
lib/
  stac_providers.yaml   # profiles (no secrets)
  stac_auth.py          # auth plugins + credential loading
  multistac.py          # SearchRequest, StacApiClient, translate, normalize, runner, search()
notebooks/
  multistac_search_tutorial.ipynb
tests/
  smoke_multistac.py    # you run: prints per-provider status/counts only
```

**Backward compatibility.** `staclib.stac_search_site` and `stac_search_site_satellogic` keep their signatures and become thin wrappers around `multistac`, so existing notebooks keep working. `satellogic_auth.py` and `satellogic_stac.py` stay in place until nothing imports them.

**Dependencies:** `requests`, `geopandas`, `shapely`, `pyyaml` and optionally `pystac`. These are already in your environment apart from possibly `pyyaml`.

---

## 9. Vendors: what is known vs to verify

| Provider | Endpoint | Auth | Status |
|---|---|---|---|
| NASA CSDA | `csdap.earthdata.nasa.gov/stac` | none for search, Earthdata token for assets | **Test now** (I can run this) |
| Satellogic | `api.satellogic.com/v2/archive` | OAuth2 client credentials + contract header | **Test now** (you run it, using the existing INI section) |
| NASA CMR, `CSDA` provider | `cmr.earthdata.nasa.gov/search` (CMR search API, not STAC) | none for search; Earthdata Login for downloads | **Done** (`csda-cmr`, see section 13) |
| Hydrosat | `stac.hydrosat.com` | OAuth2 according to a public API directory; details TBD | **Test now.** I need the auth flow details from you or Hydrosat's docs. |
| Airbus (OneAtlas) | TBD | Likely an API key exchanged for a bearer token | Later |
| Vantor (ex-Maxar) | TBD (MGP STAC?) | TBD | Later |
| Planet | Data API is **not STAC**; Planet also offers some STAC interfaces | API key | Later. This may need a `backend: planet_data_api` adapter that emits STAC-like dicts. |
| EarthDaily | TBD | Likely OAuth2 client credentials | Later |
| BlackSky, OroraTech | TBD | TBD | Later |
| Satlantis | TBD | TBD | Later: no API access yet (2026-10-11) |
| ImageSat (ISI) | TBD | TBD | Later: no API access yet (2026-10-11) |

The "later" rows are unverified guesses. Each one gets confirmed when access arrives.

---

## 10. Implementation phases

1. **Core and auth.** Write `stac_providers.yaml` (csda, satellogic, hydrosat), `stac_auth.py` (`none`, `oauth2_client_credentials`, `satellogic`) and `StacApiClient` with pagination and retries. Add a single-site search for one provider.
   - *Test:* CSDA at Railroad Valley, `airbus-optical`, JJA, checked against the existing `stac_search_site` results (same IDs). You run the smoke test for Satellogic (compare with the tutorial notebook counts) and Hydrosat.
2. **Filters and normalization.** Add the generic `cloud_cover_max` and `product_level` filters, `fields` maps, the common schema, the client-side re-filter and the discovery helpers. Fill the Satellogic and Hydrosat `fields` from `/queryables` and sample items.
3. **Runner.** Add multi-site × multi-provider runs, threading, per-provider limits, checkpoint and resume, `res.save()` and the optional `dedupe()`. Rewire `staclib` wrappers and `searchlib`.
4. **Tutorial notebook** that replaces the per-vendor search notebooks for new work.
5. **Ongoing.** Add a profile (and an auth plugin if needed) for each vendor as access arrives.

---

## 11. Decisions (2026-10-11)

1. **Hydrosat:** on hold. Discover GUI access works, but there is no API token yet; a request to Hydrosat is pending. The profile stays in the YAML with `enabled: false`.
2. **Product level:** both. Two normalized columns, `processing_level` (L1B, L1D_SR, ORT, LV2A, ...) and `product_type` (PSScene, PAN/MS-FS, Ortho, ...), plus constellation, instrument, gsd, view and sun angles. All raw vendor properties are kept as extra columns.
3. **Duplicates:** kept. When CSDA and a vendor API are searched together, vendor rows get `in_csda` (matched on `vendor_item_id`, e.g. `satl:outcome_id`) to show which items CSDA already holds.
4. **Python environment:** the ILAB Kernel (TensorFlow) env (`ilab-tensorflow`, Python 3.8). It already has geopandas, pyyaml, requests and pystac, and it is the notebooks' kernel. The code avoids syntax newer than 3.8.
5. **Profiles format:** YAML.
6. **Credentials:** `$STAC_CREDENTIALS`, falling back to `/home/pmontesa/code/credentials.ini`, one section per vendor. Satellogic may set an optional `contract_id` key to pin a contract.

**Not done yet:** `staclib.stac_search_site*` wrappers and `searchlib` are unchanged. `staclib.py` has uncommitted edits, so rewiring waits until those are committed.

## 12. Hydrosat: what's needed

- The OAuth2 token URL, plus the audience or scope, from Hydrosat.
- A `[Hydrosat_STAC_API]` section with `client_id` and `client_secret` (or tell me if they issue a static API key; `api_key_header` covers that).
- Then set `enabled: true` and `token_url` in the profile, and fill `fields` from `multistac.queryables('hydrosat', ...)`.

## 13. NASA CMR (`csda-cmr`), added 2026-10-11

CMR's `CSDA` provider holds 23 collections, none of which are in the CSDA STAC API: the Maxar legacy archive (WorldView-1/2/3/4, GeoEye-1 at L1B/L2A; IKONOS, QuickBird, WV01 3D and WV03 SWIR exist but have no granules) and `PSScene3Band`. A keyword search found no CSDA collections at other DAACs.

- **Backend:** profile `api: cmr` selects `CMRProvider`, which queries `search/granules.umm_json` (POST, `CMR-Search-After` paging) and converts each UMM-G granule to a STAC-like item. Everything downstream (fields, filters, cache, `in_csda`, `save()`, `pystac_items()`) is shared with the STAC backend.
- **Why not CMR-STAC:** its items only carry datetime and cloud cover, and asset keys are mangled URLs. The UMM-G records add GSD, sun elevation, max off-nadir angle, platform and clean HTTPS/S3 links.
- **Server-side filters:** site polygon (counter-clockwise; convex hull above 500 vertices), temporal and `cloud_cover`. Extra CMR parameters can be passed via `extra`, e.g. `{"csda-cmr": {"attribute[]": "float,Maximum Angle Off Nadir,,20"}}`.
- **Cloud cover units:** Maxar collections store a 0-1 fraction (negative = unknown); PlanetScope stores percent. `cloud_cover_scale` converts to percent on output and on the server filter. Many `PSScene3Band` granules have no cloud cover, so `cloud_cover_max` drops them.
- **Derived IDs:** `maxar:catalog_id`, `maxar:product_code` (M1BS, P1BS, ...), `planet:item_id`, `processing:level` and `csda:band_set` are parsed from the granule ID or collection name (`derived` in the profile). `vendor_item_id` is the Maxar catalog ID or Planet item ID, so a future Vantor or Planet API can be matched for `in_csda`.
- **`off_nadir`** is CMR's *maximum* off-nadir angle over the scene, not the mean.
- **Holdings:** `csda_holdings: true` marks both `csda` and `csda-cmr` rows as CSDA holdings.
- **Test:** `tests/smoke_cmr.py` (no credentials needed).

## 14. Affiliation / constellation / sensor and plots (2026-10-11)

- **Normalized columns:** `affiliation` (data owner; replaces the earlier `vendor` column), `constellation` and `sensor`, the same across all catalogs. They follow the vocabulary in `sensor_lookup_table.py` (LG01, WV03, GE01, SN46, PNEO3, FF01, ...), with Maxar listed as **Vantor**.
- **How:** each profile's `fields: sensor` names the raw satellite identifiers (e.g. `satl:sat_id`, `pl:satellite_id`, `platform`). `lib/sensor_catalog.yaml` holds ordered regex rules that map them to the three columns. A new vendor needs rules there, not code. Unmatched values keep the raw identifier as `sensor`.
- **Coverage checked** on items from all 23 CSDA STAC collections and the CMR collections: everything with a satellite identifier resolves. `maxar-sdx`, `kuvaspace` and `ororatech` items carry none; `airbus-dem` gives product names (WorldDEM).
- **Display names:** profile `display_name` (`CSDA STAC`, `Earthdata CMR – CSDA`, `Satellogic`), used in plots; data keeps the short provider codes.
- **Month tables:** `res.by_month(by=[...])` and `multistac.month_table(gdf, by=[...])` group by any columns.
- **Plots:** `multistac_plots.plot_month_heatmap(table, rows=, color_by=, cmap=, start=, end=, max_rows=)`.
- **CSDA STAC counts:** the API reports no totals (no context/aggregation extension). Requested from the CSDA team instead of counting client-side.

## 15. Skyplots, global search, downloads, analysis notebooks (2026-10-11)

- **Geometry columns:** `sat_azimuth` / `sat_elevation` (satellite as seen from the target) join the sun angles. Profile `fields` map each vendor's names (BlackSky `blacksky_satellite*`, Legion `maxar_legion:mean_sat_elevation`, GHGSat `ghgsat:los_*`, DESIS `desis_specific_*`, STAC `view:*`); a `"90-"` prefix converts zenith to elevation. Without an elevation, it is estimated from `off_nadir` at the constellation's nominal altitude (`sensor_catalog.yaml: altitude_km`); `sat_elevation_source` records which.
- **Azimuth convention is unverified per vendor.** CSDA copies vendor azimuths as-is (GHGSat `view:azimuth` = `ghgsat:los_azimuth_deg`), so `sat_azimuth` assumes "azimuth from target to satellite". Set `sat_azimuth_offset: {collection: 180}` in a profile where a vendor uses the opposite. Check e.g. Legion against the IMD `satAz` your footprint pipeline parses.
- **CMR:** sun elevation and *max* off-nadir only, no azimuths, so CMR scenes do not appear on skyplots.
- **Global search:** `multistac.search(None, start, end, providers)`; split by month (parallel, cached, resumable), assets dropped via the STAC fields extension.
- **Downloads:** `lib/multistac_download.py`. CSDA STAC assets are internal `s3://` links, so they go through the CSDA download API (`/api/v2/download/{collection}/{item}/{asset}`) after the Earthdata OAuth login used by `csda_client` (re-implemented with `requests`, since `csda_client` needs Python 3.12). CMR assets use an Earthdata user token on the HTTPS links. Routes are profile `download:` entries. Test: `tests/smoke_download.py` (needs your credentials).
- **Plots:** `plot_skyplot`, `plot_density_maps` (wraps `staclib.plot_stac_acquisition_density`), `plot_distributions`; `color_by` keeps 7 hues + gray "Other" when there are more than 8 groups.
- **Notebooks:** `notebooks/multistac_site_analysis.ipynb` (sites → overview → search → what/where → variation → select → download) and `notebooks/multistac_global_analysis.ipynb` (overview → global search → density maps → timelines → variation).
